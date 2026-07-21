from fastapi import Cookie, Depends, HTTPException, status

from app.config import settings
from app.services import legacy_bridge
from app.services.access_control import get_user_access_status
from anchor_shared import verify_session_token


def get_current_user(session_token: str | None = Cookie(default=None, alias=settings.session_cookie_name)):
    if not session_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")

    payload = verify_session_token(session_token, settings.session_secret)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or invalid.")

    user = legacy_bridge.db_get_user(payload["user_id"])
    sanitized = legacy_bridge.sanitize_user(user)
    if not sanitized:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found.")
    return sanitized


def get_current_premium_user(user=Depends(get_current_user)):
    if legacy_bridge.user_has_premium_access(user):
        return user
    raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="Payment required.")


def require_active_access(user=Depends(get_current_user)):
    access_status = get_user_access_status(user)
    if access_status["access"] == "blocked":
        raise HTTPException(status_code=403, detail="Access blocked. Please upgrade to premium.")
    return user


CurrentUser = Depends(get_current_user)
CurrentPremiumUser = Depends(get_current_premium_user)
CurrentActiveAccess = Depends(require_active_access)
