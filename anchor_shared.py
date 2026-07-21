import base64
import hashlib
import hmac
import json
import logging
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

STORAGE_BUCKET = "user-files"
PREMIUM_DURATION_DAYS = 90
_supabase_client = None
_supabase_client_key = None
logger = logging.getLogger(__name__)


def _get_env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    return value


def _get_supabase():
    global _supabase_client
    global _supabase_client_key

    try:
        from supabase import create_client
    except Exception:
        return None

    url = _get_env("SUPABASE_URL")
    key = _get_env("SUPABASE_SERVICE_KEY") or _get_env("SUPABASE_KEY")
    if not url or not key:
        return None

    cache_key = f"{url}|{key}"
    if _supabase_client is not None and _supabase_client_key == cache_key:
        return _supabase_client

    _supabase_client = create_client(url, key)
    _supabase_client_key = cache_key
    return _supabase_client


def hash_password(password: str) -> str:
    try:
        import bcrypt

        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    except Exception:
        salt = os.urandom(16).hex()
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 260000).hex()
        return f"pbkdf2${salt}${digest}"


def verify_password(plaintext: str, stored_hash: str) -> bool:
    if not plaintext or not stored_hash:
        return False

    stored = stored_hash.strip()
    if stored.startswith("$2b$") or stored.startswith("$2a$"):
        try:
            import bcrypt

            return bcrypt.checkpw(plaintext.encode("utf-8"), stored.encode("utf-8"))
        except Exception:
            return False

    if stored.startswith("pbkdf2$"):
        try:
            _, salt, digest = stored.split("$", 2)
            candidate = hashlib.pbkdf2_hmac("sha256", plaintext.encode("utf-8"), salt.encode("utf-8"), 260000).hex()
            return hmac.compare_digest(candidate, digest)
        except Exception:
            return False

    legacy_hash = hashlib.sha256(f"anchorcv_salt_2024{plaintext}".encode("utf-8")).hexdigest()
    return hmac.compare_digest(legacy_hash, stored)


def create_session_token(user_id: str, secret: str, max_age: int = 7 * 24 * 3600) -> str:
    issued_at = int(time.time())
    payload = {"user_id": user_id, "iat": issued_at, "exp": issued_at + int(max_age)}
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload_json).decode("utf-8").rstrip("=")
    signature = hmac.new(secret.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{signature}"


def verify_session_token(token: str, secret: str) -> Optional[dict]:
    if not token or "." not in token:
        return None

    payload_b64, signature = token.rsplit(".", 1)
    expected = hmac.new(secret.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None

    try:
        padding = "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + padding).decode("utf-8"))
    except Exception:
        return None

    if int(payload.get("exp", 0) or 0) < int(time.time()):
        return None
    return payload


def _parse_datetime(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        normalized = str(value).strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def user_has_premium_access(user_dict: Optional[dict]) -> bool:
    if not user_dict:
        return False

    expires_at = _parse_datetime(user_dict.get("premium_expires_at"))
    if expires_at is not None:
        return expires_at > datetime.now(timezone.utc)

    return bool(user_dict.get("is_premium")) or bool(user_dict.get("is_paid"))


def _normalize_user_access(user_dict: Optional[dict]) -> Optional[dict]:
    if not user_dict:
        return None

    normalized = dict(user_dict)
    normalized["is_premium"] = user_has_premium_access(normalized)
    normalized["is_paid"] = normalized["is_premium"] or bool(normalized.get("is_paid"))
    normalized.setdefault("premium_expires_at", None)
    return normalized


def sanitize_user(user_dict: Optional[dict]) -> Optional[dict]:
    if not user_dict:
        return None
    normalized = _normalize_user_access(user_dict)
    return {key: value for key, value in normalized.items() if key != "password_hash"}


def db_register_user(first_name: str, last_name: str, email: str, country: str, password: str):
    sb = _get_supabase()
    if not sb:
        return False, "Database not connected. Check SUPABASE_URL and SUPABASE_SERVICE_KEY."

    try:
        normalized_email = email.lower().strip()
        existing = sb.table("anchor_users").select("id").eq("email", normalized_email).execute()
        if existing.data:
            return False, "This email is already registered. Please log in."

        row = {
            "first_name": first_name.strip(),
            "last_name": last_name.strip(),
            "email": normalized_email,
            "country": country.strip(),
            "password_hash": hash_password(password),
            "is_paid": False,
            "is_premium": False,
            "premium_expires_at": None,
            "storage_used_bytes": 0,
            "storage_quota_bytes": 52428800,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_login": datetime.now(timezone.utc).isoformat(),
        }
        try:
            result = sb.table("anchor_users").insert(row).execute()
        except Exception as exc:
            if "is_premium" not in str(exc) and "premium_expires_at" not in str(exc):
                raise
            fallback_row = dict(row)
            fallback_row.pop("is_premium", None)
            fallback_row.pop("premium_expires_at", None)
            result = sb.table("anchor_users").insert(fallback_row).execute()
        if result.data:
            return True, result.data[0]["id"]
        return False, "Registration failed. Please try again."
    except Exception as exc:
        return False, f"Database error: {exc}"


def db_login_user(email: str, password: str):
    sb = _get_supabase()
    if not sb:
        return False, {"error": "Database not connected."}

    try:
        normalized_email = email.lower().strip()
        result = sb.table("anchor_users").select("*").eq("email", normalized_email).execute()
        if not result.data:
            return False, {"error": "Invalid email or password."}

        user = result.data[0]
        if not verify_password(password, user.get("password_hash", "")):
            return False, {"error": "Invalid email or password."}

        sb.table("anchor_users").update({"last_login": datetime.now(timezone.utc).isoformat()}).eq("id", user["id"]).execute()
        return True, _normalize_user_access(user)
    except Exception as exc:
        return False, {"error": f"Login error: {exc}"}


def db_get_user(user_id: str) -> Optional[dict]:
    sb = _get_supabase()
    if not sb:
        return None

    try:
        result = sb.table("anchor_users").select("*").eq("id", user_id).execute()
        return _normalize_user_access(result.data[0]) if result.data else None
    except Exception:
        return None


def db_get_user_by_email(email: str) -> Optional[dict]:
    sb = _get_supabase()
    if not sb:
        logger.warning("Supabase user lookup skipped because the client is unavailable.")
        return None

    try:
        normalized_email = email.lower().strip()
        if not normalized_email:
            logger.warning("Supabase user lookup skipped because the normalized email is empty.")
            return None
        result = sb.table("anchor_users").select("*").eq("email", normalized_email).execute()
        logger.info("Supabase user lookup completed for email=%s matched_rows=%s", normalized_email, len(result.data or []))
        return _normalize_user_access(result.data[0]) if result.data else None
    except Exception as exc:
        logger.exception("Supabase user lookup by email failed for %s: %s", email, exc)
        return None


def db_mark_premium(user_id: str, duration_days: int = PREMIUM_DURATION_DAYS) -> bool:
    sb = _get_supabase()
    if not sb:
        logger.warning("Supabase premium update skipped because the client is unavailable for user_id=%s", user_id)
        return False

    try:
        current_user = db_get_user(user_id) or {}
        now = datetime.now(timezone.utc)
        current_expiry = _parse_datetime(current_user.get("premium_expires_at"))
        base_time = current_expiry if current_expiry and current_expiry > now else now
        expires_at = base_time + timedelta(days=duration_days)
        payload = {
            "is_paid": True,
            "is_premium": True,
            "premium_expires_at": expires_at.isoformat(),
        }
        try:
            result = sb.table("anchor_users").update(payload).eq("id", user_id).execute()
            updated_rows = len(result.data or []) if hasattr(result, "data") else 0
            logger.info(
                "Supabase premium update completed for user_id=%s updated_rows=%s premium_expires_at=%s",
                user_id,
                updated_rows,
                payload["premium_expires_at"],
            )
        except Exception as exc:
            if "is_premium" not in str(exc) and "premium_expires_at" not in str(exc):
                raise
            logger.warning(
                "Supabase premium columns missing, falling back to is_paid only for user %s: %s",
                user_id,
                exc,
            )
            fallback_result = sb.table("anchor_users").update({"is_paid": True}).eq("id", user_id).execute()
            fallback_rows = len(fallback_result.data or []) if hasattr(fallback_result, "data") else 0
            logger.info("Supabase fallback premium update completed for user_id=%s updated_rows=%s", user_id, fallback_rows)
        return True
    except Exception as exc:
        logger.exception("Failed to mark user %s as premium: %s", user_id, exc)
        return False


def db_update_storage(user_id: str, delta_bytes: int) -> bool:
    sb = _get_supabase()
    if not sb:
        return False

    try:
        user = db_get_user(user_id)
        if not user:
            return False
        new_used = max(0, int(user.get("storage_used_bytes", 0)) + delta_bytes)
        sb.table("anchor_users").update({"storage_used_bytes": new_used}).eq("id", user_id).execute()
        return True
    except Exception:
        return False


def _save_file_record(user_id: str, filename: str, path: str, size: int, content_type: str) -> None:
    sb = _get_supabase()
    if not sb:
        return

    try:
        sb.table("anchor_files").upsert(
            {
                "user_id": user_id,
                "filename": filename,
                "path": path,
                "size_bytes": size,
                "content_type": content_type,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="user_id,filename",
        ).execute()
    except Exception:
        return


def storage_upload(user_id: str, filename: str, data: bytes, content_type: str = "application/octet-stream"):
    sb = _get_supabase()
    if not sb:
        return False, "Storage not connected."

    try:
        user = db_get_user(user_id)
        if user:
            used = int(user.get("storage_used_bytes", 0))
            quota = int(user.get("storage_quota_bytes", 52428800))
            if used + len(data) > quota:
                mb_left = round((quota - used) / 1048576, 1)
                return False, f"Storage quota exceeded. Only {mb_left} MB remaining."

        path = f"{user_id}/{filename}"
        try:
            sb.storage.from_(STORAGE_BUCKET).remove([path])
        except Exception:
            pass

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False) as handle:
                handle.write(data)
                temp_path = handle.name
            sb.storage.from_(STORAGE_BUCKET).upload(
                path=path,
                file=temp_path,
                file_options={"content-type": content_type, "upsert": "true"},
            )
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)

        db_update_storage(user_id, len(data))
        _save_file_record(user_id, filename, path, len(data), content_type)
        return True, path
    except Exception as exc:
        return False, f"Upload error: {exc}"


def storage_list(user_id: str):
    sb = _get_supabase()
    if not sb:
        return []

    try:
        result = sb.table("anchor_files").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
        return result.data or []
    except Exception:
        return []


def storage_get_record(user_id: str, file_id: str) -> Optional[dict]:
    sb = _get_supabase()
    if not sb:
        return None

    try:
        result = sb.table("anchor_files").select("*").eq("user_id", user_id).eq("id", file_id).execute()
        return result.data[0] if result.data else None
    except Exception:
        return None


def storage_download_url(user_id: str, filename: str, expires: int = 300) -> str:
    sb = _get_supabase()
    if not sb:
        return ""

    try:
        path = f"{user_id}/{filename}"
        result = sb.storage.from_(STORAGE_BUCKET).create_signed_url(path, expires)
        if isinstance(result, dict):
            return result.get("signedURL") or result.get("signed_url") or ""
        return str(result or "")
    except Exception:
        return ""


def storage_delete_by_id(user_id: str, file_id: str) -> bool:
    sb = _get_supabase()
    record = storage_get_record(user_id, file_id)
    if not sb or not record:
        return False

    filename = record.get("filename")
    if not filename:
        return False

    try:
        sb.storage.from_(STORAGE_BUCKET).remove([f"{user_id}/{filename}"])
    except Exception:
        pass

    try:
        size_bytes = int(record.get("size_bytes", 0) or 0)
        if size_bytes:
            db_update_storage(user_id, -size_bytes)
        sb.table("anchor_files").delete().eq("user_id", user_id).eq("id", file_id).execute()
        return True
    except Exception:
        return False


def create_lemonsqueezy_checkout(checkout_url: str, user_id: str, user_email: str, user_name: str = "", user_country: str = "") -> str:
    if not checkout_url:
        return ""

    parts = urlsplit(checkout_url)
    query_params = dict(parse_qsl(parts.query, keep_blank_values=True))
    query_params["checkout[email]"] = user_email
    if user_name.strip():
        query_params["checkout[name]"] = user_name.strip()
    if user_country.strip():
        query_params["checkout[billing_address][country]"] = user_country.strip()
    query_params["checkout[custom][user_id]"] = user_id

    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query_params), parts.fragment))


def _lemonsqueezy_request(path: str) -> Optional[dict]:
    api_key = _get_env("LEMONSQUEEZY_API_KEY", "")
    if not api_key:
        return None

    request = Request(
        f"https://api.lemonsqueezy.com/v1{path}",
        headers={
            "Accept": "application/vnd.api+json",
            "Authorization": f"Bearer {api_key}",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def get_lemonsqueezy_order(order_id: str) -> Optional[dict]:
    if not order_id:
        return None
    response = _lemonsqueezy_request(f"/orders/{order_id}")
    if not response:
        return None
    return response.get("data")


def list_lemonsqueezy_orders(user_email: str) -> list[dict]:
    if not user_email:
        return []
    response = _lemonsqueezy_request(f"/orders?{urlencode({'filter[user_email]': user_email})}")
    if not response:
        return []
    return response.get("data") or []


def verify_lemonsqueezy_webhook(payload_bytes: bytes, signature_str: str):
    webhook_secret = _get_env("LEMONSQUEEZY_WEBHOOK_SECRET", "")
    if not webhook_secret or not signature_str:
        logger.warning(
            "Webhook verification skipped because secret or signature is missing. has_secret=%s has_signature=%s",
            bool(webhook_secret),
            bool(signature_str.strip()) if signature_str else False,
        )
        return None

    try:
        expected = hmac.new(webhook_secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature_str.strip()):
            logger.warning(
                "Webhook signature verification failed. expected_prefix=%s received_prefix=%s payload_bytes=%s",
                expected[:12],
                signature_str.strip()[:12],
                len(payload_bytes),
            )
            return None
        logger.info("Webhook signature verification passed. payload_bytes=%s", len(payload_bytes))
        return json.loads(payload_bytes.decode("utf-8"))
    except Exception as exc:
        logger.exception("Webhook verification failed while parsing payload: %s", exc)
        return None


def _lemonsqueezy_order_matches(order_data: Optional[dict], user_email: str, checkout_started_at: Optional[str] = None) -> bool:
    if not order_data:
        return False

    attributes = order_data.get("attributes") or {}
    order_email = str(attributes.get("user_email") or "").strip().lower()
    if not order_email or order_email != user_email.lower().strip():
        return False

    if str(attributes.get("status") or "").strip().lower() != "paid":
        return False

    started_at = _parse_datetime(checkout_started_at)
    created_at = _parse_datetime(attributes.get("created_at"))
    if started_at and created_at and created_at < started_at - timedelta(minutes=10):
        return False

    refunded = attributes.get("refunded") or attributes.get("refunded_at")
    return not bool(refunded)


def confirm_lemonsqueezy_payment(user_id: str, user_email: str, order_id: str = "", checkout_started_at: str = "") -> Optional[dict]:
    if not user_id or not user_email:
        return None
    if not order_id and not checkout_started_at:
        return None

    order = get_lemonsqueezy_order(order_id) if order_id else None
    if order and _lemonsqueezy_order_matches(order, user_email, checkout_started_at):
        return db_get_user(user_id) if db_mark_premium(user_id) else None

    for candidate in list_lemonsqueezy_orders(user_email):
        if _lemonsqueezy_order_matches(candidate, user_email, checkout_started_at):
            return db_get_user(user_id) if db_mark_premium(user_id) else None

    return None


# ---------------------------------------------------------------------------
# Password reset helpers
# ---------------------------------------------------------------------------

def create_reset_token(user_id: str, secret: str, max_age: int = 3600) -> str:
    """Create a signed password-reset token valid for `max_age` seconds."""
    issued_at = int(time.time())
    payload = {
        "user_id": user_id,
        "purpose": "password_reset",
        "iat": issued_at,
        "exp": issued_at + int(max_age),
    }
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload_json).decode("utf-8").rstrip("=")
    signature = hmac.new(secret.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{signature}"


def verify_reset_token(token: str, secret: str) -> Optional[str]:
    """Verify a password-reset token.  Returns user_id on success, None on failure."""
    if not token or "." not in token:
        return None

    payload_b64, signature = token.rsplit(".", 1)
    expected = hmac.new(secret.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None

    try:
        padding = "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + padding).decode("utf-8"))
    except Exception:
        return None

    if payload.get("purpose") != "password_reset":
        return None

    if int(payload.get("exp", 0) or 0) < int(time.time()):
        return None

    return payload.get("user_id")


def db_update_password(user_id: str, new_password: str) -> bool:
    """Hash and store a new password for the given user."""
    sb = _get_supabase()
    if not sb:
        return False

    try:
        new_hash = hash_password(new_password)
        sb.table("anchor_users").update({"password_hash": new_hash}).eq("id", user_id).execute()
        return True
    except Exception as exc:
        logger.exception("Failed to update password for user %s: %s", user_id, exc)
        return False


def send_reset_email(to_email: str, reset_url: str) -> bool:
    """Send a password-reset email.

    Reads SMTP settings from environment variables:
        SMTP_HOST, SMTP_PORT (default 587), SMTP_USER, SMTP_PASS, SMTP_FROM

    Falls back to logging the reset URL when SMTP is not configured (dev mode).
    """
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    smtp_host = _get_env("SMTP_HOST")
    smtp_user = _get_env("SMTP_USER")
    smtp_pass = _get_env("SMTP_PASS")
    smtp_from = _get_env("SMTP_FROM") or smtp_user or "noreply@anchorcv.com"
    smtp_port = int(_get_env("SMTP_PORT") or "587")

    if not smtp_host or not smtp_user or not smtp_pass:
        logger.warning(
            "[DEV MODE] Password reset link for %s: %s",
            to_email,
            reset_url,
        )
        return True  # Return True so the endpoint doesn't leak whether email exists

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Reset your AnchorCV password"
        msg["From"] = smtp_from
        msg["To"] = to_email

        plain = (
            f"Hi,\n\n"
            f"We received a request to reset your AnchorCV password.\n\n"
            f"Click the link below to choose a new password (valid for 1 hour):\n\n"
            f"{reset_url}\n\n"
            f"If you didn't request this, you can safely ignore this email.\n\n"
            f"— The AnchorCV team"
        )
        html = f"""<!DOCTYPE html>
<html>
<body style="font-family:system-ui,sans-serif;max-width:520px;margin:0 auto;padding:2rem;color:#1e293b;">
  <h2 style="margin-bottom:0.5rem;">Reset your password</h2>
  <p>We received a request to reset your AnchorCV password.</p>
  <p>Click the button below to choose a new password. The link is valid for <strong>1 hour</strong>.</p>
  <p style="margin:1.5rem 0;">
    <a href="{reset_url}"
       style="background:#7c6ff7;color:#fff;padding:0.65rem 1.4rem;border-radius:8px;text-decoration:none;font-weight:600;">
      Reset password
    </a>
  </p>
  <p style="color:#64748b;font-size:0.88rem;">
    If you didn't request this, you can safely ignore this email.
  </p>
  <hr style="border:none;border-top:1px solid #e2e8f0;margin:1.5rem 0;">
  <p style="color:#94a3b8;font-size:0.8rem;">AnchorCV · AI-powered CV builder for international students</p>
</body>
</html>"""

        msg.attach(MIMEText(plain, "plain"))
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_from, [to_email], msg.as_string())
        return True
    except Exception as exc:
        logger.exception("Failed to send reset email to %s: %s", to_email, exc)
        return False
