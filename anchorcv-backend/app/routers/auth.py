from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from app.config import settings
from app.deps.auth import get_current_user
from app.schemas.auth import LoginRequest, RegisterRequest
from app.services import legacy_bridge
from app.services.access_control import get_user_access_status
from anchor_shared import create_session_token

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookie(response: Response, user_id: str) -> None:
    token = create_session_token(user_id, settings.session_secret, settings.session_max_age)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        max_age=settings.session_max_age,
        path="/",
    )


@router.post("/register")
def register(payload: RegisterRequest, response: Response):
    ok, result = legacy_bridge.db_register_user(
        payload.first_name,
        payload.last_name,
        payload.email,
        payload.country,
        payload.password,
    )
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result)

    user = legacy_bridge.db_get_user(result)
    sanitized = legacy_bridge.sanitize_user(user)
    _set_session_cookie(response, result)
    return {"user": sanitized, "access_status": get_user_access_status(sanitized)}


@router.post("/login")
def login(payload: LoginRequest, response: Response):
    ok, result = legacy_bridge.db_login_user(payload.email, payload.password)
    if not ok:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=result["error"])

    sanitized = legacy_bridge.sanitize_user(result)
    _set_session_cookie(response, result["id"])
    return {"user": sanitized, "access_status": get_user_access_status(sanitized)}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(key=settings.session_cookie_name, path="/")
    return {"ok": True}


@router.get("/me")
def me(user=Depends(get_current_user)):
    return {"user": user, "access_status": get_user_access_status(user)}


@router.post("/me/onboard")
def mark_onboarded(user=Depends(get_current_user)):
    """Mark the current user as having completed onboarding.
    Idempotent — calling repeatedly does not move the timestamp forward."""
    if user.get("onboarded_at"):
        return {"user": user, "already_onboarded": True}

    sb = legacy_bridge._get_supabase() if hasattr(legacy_bridge, "_get_supabase") else None
    # Fallback path: anchor_shared exposes the supabase client through its helpers.
    # We update via a direct SQL-like call.
    from anchor_shared import _get_supabase  # type: ignore
    sb = _get_supabase()
    if not sb:
        raise HTTPException(status_code=500, detail="Database is not connected.")

    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        sb.table("anchor_users").update({"onboarded_at": now_iso}).eq("id", user["id"]).execute()
    except Exception as exc:
        # If the column does not exist, surface a clear error instead of silently ignoring.
        raise HTTPException(status_code=500, detail=f"Failed to mark onboarded: {exc}") from exc

    refreshed = legacy_bridge.db_get_user(user["id"])
    return {"user": legacy_bridge.sanitize_user(refreshed), "already_onboarded": False}


@router.get("/me/stats")
def me_stats(user=Depends(get_current_user)):
    """Return workspace usage counts for the dashboard stats panel."""
    try:
        files = legacy_bridge.storage_list(user["id"])
    except Exception:
        files = []

    total_files = len(files)

    analyses = 0
    cvs_built = 0
    for f in files:
        name = f.get("filename", "").lower()
        # Analysis exports: filenames starting with "anchorcv-analysis-"
        if "anchorcv-analysis" in name:
            analyses += 1
        # CV outputs: generated CV PDFs/docx (anchorcv-cv-* or .docx)
        elif name.startswith("anchorcv-cv") or name.endswith(".docx"):
            cvs_built += 1
        # Uploaded source CVs (e.g. "Zain_Zia_CV.pdf") don't count toward built

    return {
        "files": total_files,
        "cvs_built": cvs_built,
        "analyses": analyses,
    }


def _file_to_activity(f: dict) -> dict:
    """Convert an anchor_files record into a dashboard activity item."""
    filename = f.get("filename", "")
    lower = filename.lower()

    if lower.endswith(".docx"):
        title = "CV document generated"
        description = filename
    elif lower.endswith(".pdf"):
        title = "PDF exported"
        description = filename
    else:
        title = "File saved"
        description = filename

    return {
        "title": title,
        "description": description,
        "created_at": f.get("created_at", ""),
    }


@router.get("/me/activity")
def me_activity(user=Depends(get_current_user)):
    """Return a short recent-activity feed derived from saved files."""
    try:
        files = legacy_bridge.storage_list(user["id"])
    except Exception:
        files = []

    # Most recent first, cap at 8
    recent = sorted(files, key=lambda f: f.get("created_at", ""), reverse=True)[:8]
    activity = [_file_to_activity(f) for f in recent]

    return {"activity": activity}


# ---------------------------------------------------------------------------
# Forgot / Reset password
# ---------------------------------------------------------------------------

class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


@router.post("/forgot-password")
def forgot_password(payload: ForgotPasswordRequest):
    """Send a password-reset link to the given email address.

    Always returns 200 — we never reveal whether the email exists.
    """
    from anchor_shared import create_reset_token, db_get_user_by_email, send_reset_email

    user = db_get_user_by_email(payload.email)
    if user:
        token = create_reset_token(user["id"], settings.session_secret, max_age=3600)
        reset_url = f"{settings.app_url}/reset-password?token={token}"
        send_reset_email(payload.email, reset_url)

    return {"ok": True, "message": "If that email is registered you'll receive a reset link shortly."}


@router.post("/reset-password")
def reset_password(payload: ResetPasswordRequest):
    """Validate the reset token and update the user's password."""
    from anchor_shared import verify_reset_token, db_update_password

    if not payload.new_password or len(payload.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password must be at least 8 characters.",
        )

    user_id = verify_reset_token(payload.token, settings.session_secret)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This reset link is invalid or has expired. Please request a new one.",
        )

    ok = db_update_password(user_id, payload.new_password)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to update password. Please try again.")

    return {"ok": True, "message": "Password updated successfully. You can now sign in."}
