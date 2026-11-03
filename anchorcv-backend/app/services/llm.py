"""
Multi-provider LLM routing for AnchorCV.

Supports:
- OpenAI Chat Completions
- Anthropic Messages API
- Otari, Mozilla.ai's open-source AI gateway (OpenAI-compatible)

All providers expose the same chat.completions.create(...) interface to the
rest of AnchorCV, so the legacy pipeline, the interview coach and every other
feature use one client.

Otari mode
----------
With LLM_PROVIDER=otari, *every* LLM call in AnchorCV goes through Otari,
whatever model name the calling code asks for. Calls are mapped to roles:

    fast    question generation, coaching, light audits      (OTARI_MODEL_FAST)
    strong  answer evaluation, reports, CV analysis           (OTARI_MODEL_STRONG)
    guard   the integrity guardrail classifier                (OTARI_MODEL_GUARD)

Each role points at an Otari routing policy (with fallbacks) or a model id.
Callers may pass the role explicitly with ``anchorcv_role=...``; otherwise it
is inferred from the requested model (gpt-4o-mini -> fast, gpt-4o -> strong).

Every Otari call also carries, where configured:
- the AnchorCV user as an Otari end user (per-user budgets, service key)
- the AnchorCV session as Otari-Conversation-Id (one trace per interview)
- the AnchorCV integrity guardrail (``anchorcv_guardrail=True``)
- Otari built-in tools (``tools=[{"type": "otari_web_fetch"}]``)
and records what Otari reports back (served model, fallback, cost, latency).
"""

from __future__ import annotations

import logging
import time
from types import SimpleNamespace
from urllib.parse import quote

import httpx
import openai
from openai import OpenAI

from app.config import settings
from app.services import otari_context

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
ANTHROPIC_MAX_TOKENS = 4096

DEFAULT_MODEL = "gpt-4o-mini"
OTARI_DEFAULT_MAX_TOKENS = 2000
OTARI_DEFAULT_REASONING_EFFORT = "low"
OTARI_USER_AGENT = "anchorcv/1.1 (otari-integration)"

ROLE_FAST = "fast"
ROLE_STRONG = "strong"
ROLE_GUARD = "guard"
ROLES = (ROLE_FAST, ROLE_STRONG, ROLE_GUARD)

# Keyword arguments AnchorCV adds to create(); stripped before any provider call.
_INTERNAL_KWARGS = ("anchorcv_role", "anchorcv_guardrail", "anchorcv_task")

# Single source of truth for the model picker.
AVAILABLE_MODELS = [
    {
        "id": "gpt-4o-mini",
        "label": "GPT-4o mini",
        "provider": "openai",
        "tier": "fast",
        "role": ROLE_FAST,
        "description": "Fast and reliable — the default.",
    },
    {
        "id": "gpt-4o",
        "label": "GPT-4o",
        "provider": "openai",
        "tier": "advanced",
        "role": ROLE_STRONG,
        "description": "OpenAI's stronger general model.",
    },
    {
        "id": "claude-haiku-4-5",
        "label": "Claude Haiku 4.5",
        "provider": "anthropic",
        "tier": "fast",
        "role": ROLE_FAST,
        "description": "Anthropic's fast model — crisp, natural writing.",
    },
    {
        "id": "claude-sonnet-4-6",
        "label": "Claude Sonnet 4.6",
        "provider": "anthropic",
        "tier": "advanced",
        "role": ROLE_STRONG,
        "description": "Anthropic's stronger writing model for CVs and letters.",
    },
    {
        "id": "otari:fast",
        "label": "Open-weight Fast (Otari)",
        "provider": "otari",
        "tier": "fast",
        "role": ROLE_FAST,
        "description": "Open-weight models through Mozilla.ai's Otari gateway, with automatic fallback.",
    },
    {
        "id": "otari:strong",
        "label": "Open-weight Strong (Otari)",
        "provider": "otari",
        "tier": "advanced",
        "role": ROLE_STRONG,
        "description": "Larger open-weight models through Otari for evaluation and analysis.",
    },
]

MODEL_BY_ID = {model["id"]: model for model in AVAILABLE_MODELS}
ALLOWED_MODEL_IDS = set(MODEL_BY_ID)

# Model names the legacy pipeline hard-codes, mapped to a role for Otari mode.
_LEGACY_ROLE = {
    "gpt-4-turbo": ROLE_STRONG,
    "gpt-4": ROLE_STRONG,
    "gpt-4.1": ROLE_STRONG,
    "gpt-4.1-mini": ROLE_FAST,
    "gpt-3.5-turbo": ROLE_FAST,
    # Kept so links/bookmarks from the first Otari build still resolve.
    "openai/gpt-oss-20b": ROLE_FAST,
}


class OtariPolicyError(Exception):
    """Otari refused a request on purpose (budget or guardrail), not an outage."""

    status_code = 403
    code = "otari_policy"

    def __init__(self, message: str, **details):
        super().__init__(message)
        self.details = details


class OtariBudgetExceeded(OtariPolicyError):
    status_code = 402
    code = "budget_exceeded"


class OtariGuardrailBlocked(OtariPolicyError):
    status_code = 422
    code = "guardrail_violation"


def otari_mode() -> bool:
    return settings.llm_provider == "otari" and bool(_otari_key_configured())


def _otari_key_configured() -> str:
    return settings.otari_service_key or settings.otari_api_key


def list_available_models() -> list[dict]:
    """Return models whose provider credentials are configured.

    In Otari mode only the Otari roles are offered: the whole app runs on
    open-weight models through the gateway.
    """
    models = []

    for model in AVAILABLE_MODELS:
        provider = model["provider"]

        if otari_mode() and provider != "otari":
            continue

        if provider == "openai" and not settings.openai_api_key:
            continue

        if provider == "anthropic" and not settings.anthropic_api_key:
            continue

        if provider == "otari" and not _otari_key_configured():
            continue

        models.append(model)

    return models


def default_model() -> str:
    available = list_available_models()
    if otari_mode():
        return "otari:fast"
    if any(m["id"] == DEFAULT_MODEL for m in available):
        return DEFAULT_MODEL
    return available[0]["id"] if available else DEFAULT_MODEL


def role_for_model(model: str | None) -> str:
    if model in MODEL_BY_ID:
        return MODEL_BY_ID[model]["role"]
    if model in _LEGACY_ROLE:
        return _LEGACY_ROLE[model]
    if model and model.startswith("otari:"):
        role = model.split(":", 1)[1]
        if role in ROLES:
            return role
    return ROLE_FAST


def resolve_model(model: str | None) -> str:
    """Resolve a requested model against the configured model catalogue."""
    if otari_mode():
        return f"otari:{role_for_model(model)}"

    if model == "openai/gpt-oss-20b":  # id used by the first Otari build
        model = "otari:fast"

    available_ids = {item["id"] for item in list_available_models()}

    if model and model in available_ids:
        return model

    if DEFAULT_MODEL in available_ids:
        return DEFAULT_MODEL

    if available_ids:
        return next(
            item["id"]
            for item in AVAILABLE_MODELS
            if item["id"] in available_ids
        )

    raise RuntimeError(
        "No LLM provider is configured. Add an OpenAI, Anthropic, "
        "or Otari API key to the backend environment."
    )


def otari_target(role: str) -> str:
    """The Otari policy or model id that serves a role."""
    return {
        ROLE_FAST: settings.otari_model_fast,
        ROLE_STRONG: settings.otari_model_strong,
        ROLE_GUARD: settings.otari_model_guard,
    }.get(role, settings.otari_model_fast)


def _to_openai_shape(text: str) -> SimpleNamespace:
    """Return the response structure expected by existing AnchorCV code."""
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=text)
            )
        ]
    )


def _call_anthropic_sync(
    model: str,
    messages: list[dict],
    temperature: float | None,
    max_tokens: int | None,
    response_format: dict | None,
) -> SimpleNamespace:
    api_key = settings.anthropic_api_key

    if not api_key:
        raise RuntimeError(
            "Anthropic API is not configured. "
            "Missing ANTHROPIC_API_KEY."
        )

    system_parts = [
        message.get("content", "")
        for message in messages
        if message.get("role") == "system"
    ]

    chat_messages = [
        {
            "role": message["role"],
            "content": message.get("content", ""),
        }
        for message in messages
        if message.get("role") in ("user", "assistant")
    ]

    if not chat_messages:
        chat_messages = [{"role": "user", "content": ""}]

    system = "\n\n".join(
        part for part in system_parts if part
    )

    if response_format and response_format.get("type") == "json_object":
        system = (
            system + "\n\n" if system else ""
        ) + (
            "Respond with a single valid JSON object only. "
            "No prose, no markdown code fences."
        )

    body = {
        "model": model,
        "max_tokens": max_tokens or ANTHROPIC_MAX_TOKENS,
        "messages": chat_messages,
    }

    if system:
        body["system"] = system

    if temperature is not None:
        body["temperature"] = max(
            0.0,
            min(float(temperature), 1.0),
        )

    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }

    with httpx.Client(timeout=120.0) as client:
        response = client.post(
            ANTHROPIC_API_URL,
            headers=headers,
            json=body,
        )
        response.raise_for_status()
        data = response.json()

    text = "".join(
        block.get("text", "")
        for block in data.get("content", [])
        if block.get("type") == "text"
    ).strip()

    if not text:
        raise ValueError("Claude returned an empty response.")

    if response_format and response_format.get("type") == "json_object":
        if text.startswith("```"):
            text = text.strip("`")

            if text.lower().startswith("json"):
                text = text[4:]

            text = text.strip()

    usage = data.get("usage") or {}
    result = _to_openai_shape(text)
    result.usage = SimpleNamespace(
        prompt_tokens=usage.get("input_tokens"),
        completion_tokens=usage.get("output_tokens"),
    )
    return result


# ── Otari ───────────────────────────────────────────────────────────────────

def guardrail_entries() -> list[dict]:
    """The AnchorCV integrity guardrail, as an Otari request-level guardrail."""
    if not settings.otari_guardrail_url:
        return []
    return [{
        "profile": settings.otari_guardrail_profile,
        "url": settings.otari_guardrail_url,
        "mode": "block",
        # A guardrail outage must not take the interview coach down with it;
        # Otari records the skipped check in the Otari-Guardrails header.
        "on_unavailable": "monitor",
    }]


def _end_user_budget_for(tier: str | None) -> str | None:
    if tier == "premium":
        return settings.otari_budget_premium or None
    if tier == "trial":
        return settings.otari_budget_trial or None
    return None


def _header(headers, name: str):
    try:
        return headers.get(name)
    except Exception:  # pragma: no cover - defensive
        return None


def _cost_from_usage(usage) -> float | None:
    if usage is None:
        return None
    cost = getattr(usage, "cost_usd", None)
    if cost is None:
        extra = getattr(usage, "model_extra", None) or {}
        cost = extra.get("cost_usd")
    try:
        return float(cost) if cost is not None else None
    except (TypeError, ValueError):
        return None


def _sync_end_user_budget(end_user_id: str, wanted: str, current: str | None) -> None:
    """Move an end user to the budget of their current plan (e.g. trial -> paid).

    Otari copies a budget onto an end user when it is created; a later
    Otari-End-User-Budget header does not move an existing end user. When a
    trial user upgrades, AnchorCV moves them with the service key.
    """
    if not settings.otari_service_key or not wanted or current == wanted:
        return
    url = f"{settings.otari_base_url}/end-users?external_id={quote(end_user_id, safe='')}"
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.patch(
                url,
                headers={
                    "Authorization": f"Bearer {settings.otari_service_key}",
                    "User-Agent": OTARI_USER_AGENT,
                },
                json={"budget_id": wanted},
            )
        if response.status_code >= 400:
            logger.warning(
                "Otari end-user budget move failed (%s): %s",
                response.status_code,
                response.text[:200],
            )
    except httpx.HTTPError as exc:
        logger.warning("Otari end-user budget move failed: %s", exc)


_OPTIONAL_PARAMS = ("reasoning_effort", "response_format")


def _is_unsupported_param_error(exc: "openai.APIStatusError") -> bool:
    if exc.status_code != 400:
        return False
    try:
        body = exc.response.json()
        text = f"{body.get('detail', '')} {body.get('code', '')}"
    except Exception:
        text = str(exc)
    text = text.lower()
    return "all_candidates_rejected" in text or (
        "not supported" in text and any(p in text for p in _OPTIONAL_PARAMS)
    )


def _call_otari_sync(role: str, guardrail: bool, task: str | None, **kwargs):
    """Send an OpenAI-compatible chat completion request to Otari."""
    ctx = otari_context.ensure()
    use_service_key = bool(settings.otari_service_key and ctx.end_user_id)
    api_key = settings.otari_service_key if use_service_key else settings.otari_api_key

    if not api_key:
        raise RuntimeError(
            "Otari API is not configured. Missing OTARI_API_KEY."
        )

    target = otari_target(role)
    kwargs["model"] = target

    # GPT-OSS can spend too much of a small output budget on reasoning.
    # Use low reasoning effort by default, but respect an explicit setting.
    # The guard role skips it: its provider rejects the parameter.
    extra_body = dict(kwargs.get("extra_body") or {})
    if role != ROLE_GUARD:
        extra_body.setdefault(
            "reasoning_effort",
            OTARI_DEFAULT_REASONING_EFFORT,
        )
    if guardrail:
        entries = guardrail_entries()
        if entries:
            extra_body.setdefault("guardrails", entries)
    kwargs["extra_body"] = extra_body

    # Preserve a caller-supplied token limit.
    kwargs.setdefault("max_tokens", OTARI_DEFAULT_MAX_TOKENS)

    headers = dict(kwargs.pop("extra_headers", None) or {})
    headers.setdefault("User-Agent", OTARI_USER_AGENT)
    if ctx.conversation_id:
        headers.setdefault("Otari-Conversation-Id", ctx.conversation_id)

    wanted_budget = None
    if use_service_key:
        kwargs["user"] = ctx.end_user_id
        wanted_budget = _end_user_budget_for(ctx.access_tier)
        if wanted_budget:
            headers["Otari-End-User-Budget"] = wanted_budget
    kwargs["extra_headers"] = headers

    entry = {
        "provider": "otari",
        "role": role,
        "task": task,
        "target": target,
        "guardrail": bool(guardrail and settings.otari_guardrail_url),
        "end_user": bool(use_service_key),
        "tools": [t.get("type") for t in (kwargs.get("tools") or []) if isinstance(t, dict)],
    }

    client = OpenAI(
        api_key=api_key,
        base_url=settings.otari_base_url,
        default_headers={"Otari-Key": api_key},
        timeout=120.0,
        max_retries=0,
    )

    started = time.perf_counter()
    try:
        try:
            raw = client.chat.completions.with_raw_response.create(**kwargs)
        except openai.APIStatusError as first:
            # Providers behind Otari differ in which optional parameters they
            # accept; a fallback model rejecting one fails the whole chain.
            # Retry once without the optional ones.
            if not _is_unsupported_param_error(first):
                raise
            entry["compat_retry"] = True
            kwargs["extra_body"] = {
                k: v for k, v in kwargs["extra_body"].items() if k != "reasoning_effort"
            }
            kwargs.pop("response_format", None)
            raw = client.chat.completions.with_raw_response.create(**kwargs)
        completion = raw.parse()
        response_headers = raw.headers
    except openai.APIStatusError as exc:
        response_headers = exc.response.headers if exc.response is not None else {}
        code = _header(response_headers, "otari-error-code") or ""
        detail = ""
        try:
            body = exc.response.json()
            detail = str(body.get("detail") or body.get("error") or "")
        except Exception:
            detail = str(exc)
        entry.update({
            "ok": False,
            "status": exc.status_code,
            "error_code": code or None,
            "latency_ms": round((time.perf_counter() - started) * 1000),
        })
        ctx.record(entry)
        lowered = detail.lower()
        if exc.status_code == 403 and (
            code == "budget_exceeded"
            or "exceeded budget" in lowered
            or "of budget remaining" in lowered
        ):
            raise OtariBudgetExceeded(
                "Your AI allowance for this period is used up.",
                scope=_header(response_headers, "otari-budget-scope"),
                retry_after=_header(response_headers, "retry-after"),
            ) from exc
        if exc.status_code == 403 and (code == "guardrail_violation" or "guardrail" in lowered):
            raise OtariGuardrailBlocked(
                "The text was flagged by the AnchorCV integrity guardrail.",
                profile=settings.otari_guardrail_profile,
            ) from exc
        raise
    except Exception:
        entry.update({
            "ok": False,
            "status": None,
            "latency_ms": round((time.perf_counter() - started) * 1000),
        })
        ctx.record(entry)
        raise
    finally:
        client.close()

    usage = getattr(completion, "usage", None)
    extra = getattr(completion, "model_extra", None) or {}
    tool_calls = extra.get("otari_tool_calls") or []
    served_budget = _header(response_headers, "otari-end-user-budget")
    entry.update({
        "ok": True,
        "status": 200,
        "served_model": _header(response_headers, "otari-model"),
        "served_provider": _header(response_headers, "otari-provider"),
        "fallback": (_header(response_headers, "otari-fallback") or "").lower() == "true",
        "attempts": int(_header(response_headers, "otari-attempt-count") or 1),
        "request_id": _header(response_headers, "otari-request-id"),
        "guardrails": _header(response_headers, "otari-guardrails"),
        "end_user_budget": served_budget,
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "cost_usd": _cost_from_usage(usage),
        "tool_calls": [
            {"type": c.get("type"), "status": c.get("status"), "url": c.get("url"), "query": c.get("query")}
            for c in tool_calls if isinstance(c, dict)
        ],
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "gateway_ms": _header(response_headers, "otari-response-duration-ms"),
    })
    ctx.record(entry)

    if use_service_key and wanted_budget and served_budget and served_budget != wanted_budget:
        _sync_end_user_budget(ctx.end_user_id, wanted_budget, served_budget)

    return completion


class _RoutedCompletions:
    def __init__(self, get_openai_client):
        self._get_openai_client = get_openai_client

    def create(self, **kwargs):
        role_hint = kwargs.pop("anchorcv_role", None)
        guardrail = bool(kwargs.pop("anchorcv_guardrail", False))
        task = kwargs.pop("anchorcv_task", None)

        requested_model = kwargs.get("model") or DEFAULT_MODEL
        model = resolve_model(requested_model)
        provider = MODEL_BY_ID[model]["provider"]

        if provider == "otari":
            role = role_hint if role_hint in ROLES else role_for_model(model)
            return _call_otari_sync(role=role, guardrail=guardrail, task=task, **kwargs)

        # Ensure the resolved model is the one sent to the provider.
        kwargs["model"] = model
        ctx = otari_context.ensure()
        started = time.perf_counter()
        entry = {"provider": provider, "role": role_hint or role_for_model(model), "task": task, "target": model}

        try:
            if provider == "anthropic":
                result = _call_anthropic_sync(
                    model=model,
                    messages=kwargs.get("messages") or [],
                    temperature=kwargs.get("temperature"),
                    max_tokens=kwargs.get("max_tokens"),
                    response_format=kwargs.get("response_format"),
                )
            else:
                result = self._get_openai_client().chat.completions.create(**kwargs)
        except Exception:
            entry.update({"ok": False, "latency_ms": round((time.perf_counter() - started) * 1000)})
            ctx.record(entry)
            raise

        usage = getattr(result, "usage", None)
        entry.update({
            "ok": True,
            "served_model": model,
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
            "latency_ms": round((time.perf_counter() - started) * 1000),
        })
        ctx.record(entry)
        return result


class RoutedChatClient:
    """Drop-in replacement for the OpenAI client used by AnchorCV."""

    def __init__(self):
        self._openai_client = None

        self.chat = SimpleNamespace(
            completions=_RoutedCompletions(self._openai)
        )

    def _openai(self):
        if self._openai_client is None:
            self._openai_client = OpenAI(
                api_key=settings.openai_api_key
            )

        return self._openai_client


_routed_client: RoutedChatClient | None = None


def get_routed_client() -> RoutedChatClient:
    """Return the shared multi-provider client."""
    global _routed_client

    if _routed_client is None:
        _routed_client = RoutedChatClient()

    return _routed_client
