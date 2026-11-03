"""HTTP mapping for Otari policy refusals (budget, guardrail)."""

from fastapi import Request
from fastapi.responses import JSONResponse

from app.services.llm import OtariPolicyError


async def otari_policy_error(request: Request, exc: OtariPolicyError):
    """Budget and guardrail refusals from Otari are user-facing, not outages."""
    headers = {}
    retry_after = exc.details.get("retry_after")
    if retry_after:
        headers["Retry-After"] = str(retry_after)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": str(exc), "code": exc.code, **{k: v for k, v in exc.details.items() if v}},
        headers=headers,
    )
