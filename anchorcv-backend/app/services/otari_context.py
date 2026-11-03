"""
Per-request Otari context.

An HTTP request to AnchorCV may make several LLM calls (question generation,
evaluation, guardrail checks). This module carries two things across them:

* who the AnchorCV user is (so Otari can bill them as an end user with their
  own budget), and
* a log of every Otari call (model that served it, fallback, cost, latency,
  guardrail verdicts) so the API can show it to the user and the benchmark.

FastAPI runs sync endpoints and dependencies in worker threads, each with a
*copy* of the request's context. A ContextVar set in a dependency would not
reach the endpoint's thread, so the middleware stores one mutable holder per
request and every thread mutates that same object.
"""

from __future__ import annotations

import contextvars
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware


@dataclass
class OtariRequestContext:
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    end_user_id: str | None = None
    access_tier: str | None = None  # "trial" | "premium"
    conversation_id: str | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(self, entry: dict[str, Any]) -> None:
        with self._lock:
            self.calls.append(entry)

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(call) for call in self.calls]


_current: contextvars.ContextVar[OtariRequestContext | None] = contextvars.ContextVar(
    "anchorcv_otari_context", default=None
)


def current() -> OtariRequestContext | None:
    return _current.get()


def ensure() -> OtariRequestContext:
    """Return the request's context, creating one outside HTTP (scripts, tests)."""
    ctx = _current.get()
    if ctx is None:
        ctx = OtariRequestContext()
        _current.set(ctx)
    return ctx


def start(**values: Any) -> contextvars.Token:
    """Begin a fresh context (used by the middleware, the benchmark and tests)."""
    return _current.set(OtariRequestContext(**values))


def reset(token: contextvars.Token) -> None:
    _current.reset(token)


def bind_user(user: dict | None, access_tier: str | None) -> None:
    """Attach the authenticated AnchorCV user to the current request."""
    ctx = current()
    if ctx is None or not user:
        return
    user_id = user.get("id") or user.get("user_id") or user.get("email")
    if user_id:
        ctx.end_user_id = f"anchorcv:{user_id}"
    ctx.access_tier = access_tier


def summary() -> dict[str, Any]:
    """Compact view of this request's Otari calls, returned to the frontend."""
    ctx = current()
    calls = ctx.snapshot() if ctx else []
    otari_calls = [c for c in calls if c.get("provider") == "otari"]
    cost = sum(float(c.get("cost_usd") or 0) for c in otari_calls)
    return {
        "via_otari": bool(otari_calls),
        "calls": calls,
        "total_cost_usd": round(cost, 6),
        "fallbacks": sum(1 for c in otari_calls if c.get("fallback")),
        "end_user_budget": next(
            (c.get("end_user_budget") for c in reversed(otari_calls) if c.get("end_user_budget")),
            None,
        ),
    }


class OtariContextMiddleware(BaseHTTPMiddleware):
    """Give every HTTP request its own OtariRequestContext."""

    async def dispatch(self, request, call_next):
        conversation_id = request.headers.get("x-anchorcv-session") or None
        token = start(conversation_id=conversation_id)
        try:
            return await call_next(request)
        finally:
            reset(token)
