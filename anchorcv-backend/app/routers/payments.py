import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from app.config import settings
from app.deps.auth import get_current_user
from app.services import legacy_bridge

router = APIRouter(prefix="/payments", tags=["payments"])
logger = logging.getLogger(__name__)


class CheckoutRequest(BaseModel):
    checkout_started_at: str | None = None


class ConfirmPaymentRequest(BaseModel):
    order_id: str | None = None
    checkout_started_at: str | None = None


def _extract_lemonsqueezy_email(event: dict) -> str:
    data = event.get("data") or {}
    attributes = data.get("attributes") or {}
    meta = event.get("meta") or {}
    custom_data = meta.get("custom_data") or {}

    candidates = [
        attributes.get("user_email"),
        attributes.get("customer_email"),
        custom_data.get("user_email"),
        custom_data.get("email"),
    ]
    for candidate in candidates:
        email = str(candidate or "").strip().lower()
        if email:
            return email
    return ""


@router.post("/checkout")
def create_checkout(_: CheckoutRequest, user=Depends(get_current_user)):
    checkout_url = legacy_bridge.create_lemonsqueezy_checkout(
        settings.lemon_checkout_url,
        user["id"],
        user["email"],
        user_name=f"{user.get('first_name', '').strip()} {user.get('last_name', '').strip()}".strip(),
        user_country=user.get("country", ""),
    )
    if not checkout_url:
        raise HTTPException(status_code=400, detail="Lemon Squeezy checkout is not configured.")
    return {"checkout_url": checkout_url}


@router.post("/confirm")
def confirm_payment(payload: ConfirmPaymentRequest, user=Depends(get_current_user)):
    if legacy_bridge.user_has_premium_access(user):
        return {"user": user, "verified": True}

    confirmed_user = legacy_bridge.confirm_lemonsqueezy_payment(
        user["id"],
        user["email"],
        order_id=(payload.order_id or "").strip(),
        checkout_started_at=(payload.checkout_started_at or "").strip(),
    )
    if not confirmed_user:
        raise HTTPException(status_code=400, detail="Payment could not be verified.")
    return {"user": legacy_bridge.sanitize_user(confirmed_user), "verified": True}


@router.post("/webhook")
async def lemonsqueezy_webhook(
    request: Request,
    x_signature: str | None = Header(default=None, alias="X-Signature"),
):
    payload = await request.body()
    logger.info(
        "Received Lemon Squeezy webhook. payload_bytes=%s has_signature=%s received_at=%s",
        len(payload),
        bool((x_signature or "").strip()),
        datetime.now(timezone.utc).isoformat(),
    )
    event = legacy_bridge.verify_lemonsqueezy_webhook(payload, x_signature or "")
    if not event:
        logger.warning("Rejected Lemon Squeezy webhook due to failed signature verification.")
        raise HTTPException(status_code=400, detail="Invalid webhook payload.")

    event_name = str(((event.get("meta") or {}).get("event_name") or "")).strip()
    data = event.get("data") or {}
    attributes = data.get("attributes") or {}
    email = _extract_lemonsqueezy_email(event)
    status = str(attributes.get("status") or "").strip().lower()

    logger.info(
        "Parsed Lemon Squeezy webhook event. event_name=%s resource_type=%s resource_id=%s status=%s user_email=%s",
        event_name,
        data.get("type"),
        data.get("id"),
        status,
        email,
    )

    if event_name in {"order_created", "subscription_created"}:
        if not email:
            logger.warning(
                "Webhook event does not include a customer email. event_name=%s payload_preview=%s",
                event_name,
                payload.decode("utf-8", errors="replace")[:1000],
            )
            return {"received": True, "processed": False, "reason": "missing_email"}

        if event_name == "order_created" and status != "paid":
            logger.info(
                "Skipping order_created webhook because payment is not paid. status=%s user_email=%s",
                status,
                email,
            )
            return {"received": True, "processed": False, "reason": "order_not_paid"}

        user = legacy_bridge.db_get_user_by_email(email)
        if user:
            updated = legacy_bridge.db_mark_premium(user["id"])
            logger.info(
                "Processed premium entitlement from Lemon Squeezy webhook. event_name=%s user_id=%s user_email=%s premium_updated=%s",
                event_name,
                user.get("id"),
                email,
                updated,
            )
            return {"received": True, "processed": bool(updated), "user_id": user.get("id")}

        logger.warning(
            "No anchor_users row found for Lemon Squeezy webhook email. event_name=%s user_email=%s",
            event_name,
            email,
        )
        return {"received": True, "processed": False, "reason": "user_not_found"}

    logger.info(
        "Ignoring unsupported Lemon Squeezy webhook event. event_name=%s supported_events=%s",
        event_name,
        json.dumps(["order_created", "subscription_created"]),
    )

    return {"received": True}
