from datetime import datetime, timedelta, timezone


# Hardcoded deployment date. Users registered before this date keep old behavior.
REGISTRATION_CUTOFF = datetime(2026, 5, 16)


def _get_user_value(user, key, default=None):
    if isinstance(user, dict):
        return user.get(key, default)
    return getattr(user, key, default)


def _to_naive_utc(value):
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except Exception:
            return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def get_user_access_status(user):
    now = datetime.utcnow()
    user_created = _to_naive_utc(_get_user_value(user, "created_at")) or now
    premium_expires_at = _to_naive_utc(_get_user_value(user, "premium_expires_at"))
    is_premium = bool(_get_user_value(user, "is_premium"))

    # Existing users registered before cutoff keep old premium-only behavior.
    if user_created < REGISTRATION_CUTOFF:
        if is_premium and (premium_expires_at is None or premium_expires_at > now):
            days_left = (premium_expires_at - now).days if premium_expires_at else 999
            return {
                "access": "premium",
                "days_left": days_left,
                "badge_type": "premium",
                "show_upgrade": False,
            }
        return {
            "access": "blocked",
            "days_left": 0,
            "badge_type": "no_access",
            "show_upgrade": True,
        }

    if is_premium and premium_expires_at and premium_expires_at > now:
        days_left = (premium_expires_at - now).days
        return {
            "access": "premium",
            "days_left": days_left,
            "badge_type": "premium",
            "show_upgrade": False,
        }

    trial_end = user_created + timedelta(days=3)
    if now < trial_end:
        days_left = max(1, (trial_end - now).days + 1)
        return {
            "access": "trial",
            "days_left": days_left,
            "badge_type": "trial",
            "show_upgrade": True,
        }

    return {
        "access": "blocked",
        "days_left": 0,
        "badge_type": "expired",
        "show_upgrade": True,
    }
