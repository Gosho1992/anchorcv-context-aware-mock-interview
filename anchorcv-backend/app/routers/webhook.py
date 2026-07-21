import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException, Request

from app.services import legacy_bridge

router = APIRouter(prefix="/webhook", tags=["webhook"])
logger = logging.getLogger(__name__)

# Events that should grant premium access. Lemon Squeezy fires `order_created`
# (with status="paid") for one-time purchases; `subscription_created` for new
# subscriptions; `subscription_payment_success` / `subscription_updated` /
# `subscription_resumed` for ongoing renewals.
GRANT_PREMIUM_EVENTS = {
    "order_created",
    "subscription_created",
    "subscription_updated",
    "subscription_payment_success",
    "subscription_resumed",
}


def _get_webhook_secret() -> str:
    return str(os.getenv("LEMONSQUEEZY_WEBHOOK_SECRET") or "").strip()


def _hex_signature(payload: bytes) -> str:
    secret = _get_webhook_secret()
    if not secret:
        raise RuntimeError("LEMONSQUEEZY_WEBHOOK_SECRET is not configured.")
    return hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()


def _verify_signature(payload: bytes, signature: str) -> bool:
    received = (signature or "").strip()
    if not received:
        return False
    expected = _hex_signature(payload)
    return hmac.compare_digest(expected, received)


def _extract_customer_email(event: dict) -> str:
    data = event.get("data") or {}
    attributes = data.get("attributes") or {}
    meta = event.get("meta") or {}
    custom_data = meta.get("custom_data") or {}

    candidates = [
        attributes.get("user_email"),
        attributes.get("customer_email"),
        attributes.get("email"),
        custom_data.get("user_email"),
        custom_data.get("email"),
    ]
    for candidate in candidates:
        email = str(candidate or "").strip().lower()
        if email:
            return email
    return ""


def _extract_custom_user_id(event: dict) -> str:
    """Pull user_id we attached to the checkout via custom_data."""
    meta = event.get("meta") or {}
    custom_data = meta.get("custom_data") or {}
    candidates = [
        custom_data.get("user_id"),
        custom_data.get("anchor_user_id"),
        (event.get("data") or {}).get("attributes", {}).get("custom_data", {}).get("user_id")
        if isinstance((event.get("data") or {}).get("attributes", {}).get("custom_data"), dict)
        else None,
    ]
    for candidate in candidates:
        value = str(candidate or "").strip()
        if value:
            return value
    return ""


def _payload_preview(payload: bytes, limit: int = 1500) -> str:
    try:
        return payload.decode("utf-8", errors="replace")[:limit]
    except Exception:
        return "<unable to decode payload>"


@router.get("/lemonsqueezy")
def lemonsqueezy_webhook_status():
    return {
        "status": "ok",
        "endpoint": "/api/webhook/lemonsqueezy",
        "secret_configured": bool(os.getenv("LEMONSQUEEZY_WEBHOOK_SECRET")),
    }


@router.post("/lemonsqueezy")
async def lemonsqueezy_webhook(
    request: Request,
    x_signature: str | None = Header(default=None, alias="X-Signature"),
    x_event_name: str | None = Header(default=None, alias="X-Event-Name"),
):
    payload = await request.body()
    received_signature = (x_signature or "").strip()
    received_at = datetime.now(timezone.utc).isoformat()
    webhook_secret = _get_webhook_secret()

    logger.info(
        "lemonsqueezy_webhook received: payload_bytes=%s has_signature=%s "
        "event_header=%s using_env_secret=%s received_at=%s",
        len(payload),
        bool(received_signature),
        x_event_name,
        bool(webhook_secret),
        received_at,
    )

    if not webhook_secret:
        logger.error("lemonsqueezy_webhook rejected because LEMONSQUEEZY_WEBHOOK_SECRET is not configured.")
        raise HTTPException(status_code=500, detail="Webhook secret is not configured.")

    if not _verify_signature(payload, received_signature):
        # Log enough info to diagnose secret mismatch WITHOUT leaking the secret.
        expected_prefix = _hex_signature(payload)[:12] if payload else ""
        logger.warning(
            "lemonsqueezy_webhook signature verification failed. "
            "expected_prefix=%s received_prefix=%s payload_bytes=%s "
            "event_header=%s payload_preview=%s",
            expected_prefix,
            received_signature[:12],
            len(payload),
            x_event_name,
            _payload_preview(payload, 400),
        )
        raise HTTPException(status_code=400, detail="Invalid webhook signature.")

    try:
        event = json.loads(payload.decode("utf-8"))
    except Exception as exc:
        logger.exception("lemonsqueezy_webhook failed to parse JSON payload: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid webhook payload.") from exc

    meta = event.get("meta") or {}
    data = event.get("data") or {}
    attributes = data.get("attributes") or {}
    event_name = str(meta.get("event_name") or x_event_name or "").strip()
    resource_type = str(data.get("type") or "").strip()
    resource_id = str(data.get("id") or "").strip()
    status = str(attributes.get("status") or "").strip().lower()
    customer_email = _extract_customer_email(event)
    custom_user_id = _extract_custom_user_id(event)

    logger.info(
        "lemonsqueezy_webhook parsed: event_name=%s resource_type=%s resource_id=%s "
        "status=%s customer_email=%s custom_user_id=%s",
        event_name,
        resource_type,
        resource_id,
        status,
        customer_email,
        custom_user_id,
    )

    if event_name not in GRANT_PREMIUM_EVENTS:
        logger.info(
            "lemonsqueezy_webhook ignoring unsupported event. event_name=%s supported=%s",
            event_name,
            sorted(GRANT_PREMIUM_EVENTS),
        )
        return {"received": True, "processed": False, "reason": "unsupported_event", "event_name": event_name}

    # For one-time orders, only grant premium on confirmed paid status.
    # Subscription events generally don't carry a "paid" status — they have
    # "active", "on_trial", etc. — so we only enforce the paid check for orders.
    if event_name == "order_created" and status and status != "paid":
        logger.info(
            "lemonsqueezy_webhook skipping order_created because status is not 'paid'. status=%s email=%s",
            status,
            customer_email,
        )
        return {"received": True, "processed": False, "reason": "order_not_paid", "status": status}

    # Try to find the user — first by email, then by user_id from custom_data.
    user = None
    if customer_email:
        user = legacy_bridge.db_get_user_by_email(customer_email)
        if user:
            logger.info(
                "lemonsqueezy_webhook resolved user by email. user_id=%s email=%s",
                user.get("id"),
                customer_email,
            )

    if not user and custom_user_id:
        try:
            user = legacy_bridge.db_get_user(custom_user_id)
            if user:
                logger.info(
                    "lemonsqueezy_webhook resolved user by custom_user_id fallback. user_id=%s email_in_db=%s lemonsqueezy_email=%s",
                    user.get("id"),
                    user.get("email"),
                    customer_email,
                )
        except Exception as exc:
            logger.exception(
                "lemonsqueezy_webhook custom_user_id lookup failed for %s: %s",
                custom_user_id,
                exc,
            )

    if not user:
        logger.warning(
            "lemonsqueezy_webhook could not find a user for this event. "
            "event_name=%s email=%s custom_user_id=%s — payment will NOT grant premium. "
            "Investigate: did the customer use a different email at checkout? "
            "payload_preview=%s",
            event_name,
            customer_email,
            custom_user_id,
            _payload_preview(payload, 800),
        )
        # Return 200 so Lemon Squeezy doesn't endlessly retry; the warning above
        # is enough for an operator to find and manually flip is_premium.
        return {
            "received": True,
            "processed": False,
            "reason": "user_not_found",
            "event_name": event_name,
            "customer_email": customer_email,
            "custom_user_id": custom_user_id,
        }

    user_id = user.get("id")
    try:
        updated = legacy_bridge.db_mark_premium(user_id, duration_days=90)
    except Exception as exc:
        logger.exception(
            "lemonsqueezy_webhook db_mark_premium raised for user_id=%s email=%s: %s",
            user_id,
            customer_email,
            exc,
        )
        raise HTTPException(status_code=500, detail="Failed to update premium status.") from exc

    if not updated:
        logger.error(
            "lemonsqueezy_webhook db_mark_premium returned False. user_id=%s email=%s event_name=%s",
            user_id,
            customer_email,
            event_name,
        )
        raise HTTPException(status_code=500, detail="Failed to update premium status.")

    logger.info(
        "lemonsqueezy_webhook GRANTED premium. user_id=%s email=%s event_name=%s resource_id=%s",
        user_id,
        customer_email,
        event_name,
        resource_id,
    )

    return {
        "received": True,
        "processed": True,
        "event_name": event_name,
        "customer_email": customer_email,
        "user_id": user_id,
    }
