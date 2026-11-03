"""
Guardrail endpoint Otari calls before a model runs (any-guardrail contract).

    POST /api/guardrails/<OTARI_GUARDRAIL_TOKEN>/validate
    {"profile": "...", "input_text": "...", "validate_kwargs": {...}}
    -> {"profile": "...", "result": {"valid": bool|null, "explanation": str, "score": float}}

Otari sends no credential for a request-level guardrail URL, so the path
carries a long random token, and the endpoint is rate limited.
"""

from __future__ import annotations

import hmac
import threading
import time
from collections import deque

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.services import integrity_guard

router = APIRouter(prefix="/guardrails", tags=["guardrails"])

_RATE_LIMIT_PER_MINUTE = 240
_hits: deque[float] = deque()
_hits_lock = threading.Lock()


class ValidateRequest(BaseModel):
    profile: str = Field(default="anchorcv-integrity", max_length=128)
    input_text: str = Field(default="", max_length=400_000)
    validate_kwargs: dict = Field(default_factory=dict)


def _rate_limited() -> bool:
    now = time.monotonic()
    with _hits_lock:
        while _hits and now - _hits[0] > 60:
            _hits.popleft()
        if len(_hits) >= _RATE_LIMIT_PER_MINUTE:
            return True
        _hits.append(now)
        return False


@router.post("/{token}/validate")
def validate(token: str, payload: ValidateRequest):
    expected = settings.otari_guardrail_token
    if not expected or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=404, detail="Not found.")
    if _rate_limited():
        raise HTTPException(status_code=429, detail="Too many guardrail checks.")

    use_model = payload.validate_kwargs.get("use_model", True) is not False
    result = integrity_guard.validate(payload.input_text, use_model=use_model)
    return {
        "profile": payload.profile,
        "result": {
            "valid": result["valid"],
            "explanation": result.get("explanation"),
            "score": result.get("score"),
        },
    }
