# ============================================================
# auth_layer.py — AnchorCV SaaS Authentication Layer
# ============================================================
# This is the NEW entry point. Run this file instead of app.py.
# It wraps app.py's main() with:
#   1. Auth (Sign Up / Login) via Supabase
#   2. Stripe Payment Gate
#   3. Welcome Dashboard
#   4. Cloud File Storage (Supabase Storage)
#   5. Background visual patterns
#
# RENAME this file to app.py when deploying, and rename
# the old app.py to anchor_core.py (see bottom of this file).
# ============================================================

import streamlit as st
import os
import json
import time
import hashlib
from datetime import datetime, timezone
from typing import Optional

# ─────────────────────────────────────────────────
# PAGE CONFIG (must be first Streamlit call)
# ─────────────────────────────────────────────────
st.set_page_config(
    page_title="AnchorCV",
    page_icon="🔮",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─────────────────────────────────────────────────
# SUPABASE CLIENT (lazy singleton)
# ─────────────────────────────────────────────────
_supabase_client = None

def get_supabase():
    """Return cached Supabase client. Reads credentials from st.secrets."""
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client
    try:
        from supabase import create_client
        url = st.secrets.get("SUPABASE_URL") or os.getenv("SUPABASE_URL")
        key = (
            st.secrets.get("SUPABASE_SERVICE_KEY")
            or st.secrets.get("SUPABASE_KEY")
            or os.getenv("SUPABASE_SERVICE_KEY")
        )
        if not url or not key:
            return None
        _supabase_client = create_client(url, key)
        return _supabase_client
    except Exception:
        return None


# ─────────────────────────────────────────────────
# PASSWORD HASHING  (bcrypt — correct & secure)
# ─────────────────────────────────────────────────
def _hash_password(password: str) -> str:
    """
    Hash a plaintext password with bcrypt.
    Returns a UTF-8 string safe to store in Supabase.
    """
    try:
        import bcrypt
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    except ImportError:
        # Fallback if bcrypt not installed — use PBKDF2
        import hashlib as _hl, os
        salt = os.urandom(16).hex()
        h = _hl.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260000).hex()
        return f"pbkdf2${salt}${h}"


def _verify_password(plaintext: str, stored_hash: str) -> bool:
    """
    Verify a plaintext password against whatever hash format is stored.
    Handles bcrypt AND legacy SHA-256 so old accounts still work.
    NEVER compare hashes directly — always call this function.
    """
    if not plaintext or not stored_hash:
        return False
    stored = stored_hash.strip()

    # bcrypt format ($2b$ or $2a$)
    if stored.startswith("$2b$") or stored.startswith("$2a$"):
        try:
            import bcrypt
            return bcrypt.checkpw(plaintext.encode("utf-8"), stored.encode("utf-8"))
        except Exception:
            return False

    # PBKDF2 fallback format
    if stored.startswith("pbkdf2$"):
        try:
            import hashlib as _hl
            _, salt, h = stored.split("$", 2)
            candidate = _hl.pbkdf2_hmac("sha256", plaintext.encode(), salt.encode(), 260000).hex()
            return candidate == h
        except Exception:
            return False

    # Legacy SHA-256 with static salt (old accounts before this fix)
    import hashlib as _hl
    legacy_hash = _hl.sha256(f"anchorcv_salt_2024{plaintext}".encode()).hexdigest()
    return legacy_hash == stored


# ─────────────────────────────────────────────────
# SUPABASE — USER OPERATIONS
# ─────────────────────────────────────────────────
def db_register_user(first_name: str, last_name: str, email: str,
                     country: str, password: str) -> tuple[bool, str]:
    """
    Insert a new user row into the `anchor_users` table.
    Returns (True, user_id) on success or (False, error_message).
    """
    sb = get_supabase()
    if not sb:
        return False, "Database not connected. Check SUPABASE_URL and SUPABASE_SERVICE_KEY in secrets."
    try:
        # Check if email already exists
        existing = sb.table("anchor_users").select("id").eq("email", email.lower().strip()).execute()
        if existing.data:
            return False, "This email is already registered. Please log in."

        row = {
            "first_name": first_name.strip(),
            "last_name":  last_name.strip(),
            "email":      email.lower().strip(),
            "country":    country.strip(),
            "password_hash": _hash_password(password),
            "is_paid":    False,
            "storage_used_bytes": 0,
            "storage_quota_bytes": 52428800,  # 50 MB
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_login":  datetime.now(timezone.utc).isoformat(),
        }
        result = sb.table("anchor_users").insert(row).execute()
        if result.data:
            return True, result.data[0]["id"]
        return False, "Registration failed. Please try again."
    except Exception as e:
        return False, f"Database error: {e}"


def db_login_user(email: str, password: str) -> tuple[bool, dict]:
    """
    Verify credentials and return (True, user_dict) or (False, {error}).
    """
    sb = get_supabase()
    if not sb:
        return False, {"error": "Database not connected."}
    try:
        # Fetch by email only — then verify password client-side with checkpw
        result = sb.table("anchor_users")\
            .select("*")\
            .eq("email", email.lower().strip())\
            .execute()
        if not result.data:
            return False, {"error": "Invalid email or password."}
        user = result.data[0]
        if not _verify_password(password, user.get("password_hash", "")):
            return False, {"error": "Invalid email or password."}
        # Update last_login
        sb.table("anchor_users").update({
            "last_login": datetime.now(timezone.utc).isoformat()
        }).eq("id", user["id"]).execute()
        return True, user
    except Exception as e:
        return False, {"error": f"Login error: {e}"}


def db_get_user(user_id: str) -> Optional[dict]:
    """Fetch fresh user row from DB."""
    sb = get_supabase()
    if not sb:
        return None
    try:
        result = sb.table("anchor_users").select("*").eq("id", user_id).execute()
        return result.data[0] if result.data else None
    except Exception:
        return None


def db_mark_paid(user_id: str) -> bool:
    """Set is_paid=True after confirmed Stripe payment."""
    sb = get_supabase()
    if not sb:
        return False
    try:
        sb.table("anchor_users").update({"is_paid": True}).eq("id", user_id).execute()
        return True
    except Exception:
        return False


def db_update_storage(user_id: str, delta_bytes: int) -> bool:
    """Add delta_bytes to the user's storage_used_bytes counter."""
    sb = get_supabase()
    if not sb:
        return False
    try:
        user = db_get_user(user_id)
        if not user:
            return False
        new_used = max(0, int(user.get("storage_used_bytes", 0)) + delta_bytes)
        sb.table("anchor_users").update({
            "storage_used_bytes": new_used
        }).eq("id", user_id).execute()
        return True
    except Exception:
        return False


# ─────────────────────────────────────────────────
# SUPABASE — FILE STORAGE
# ─────────────────────────────────────────────────
STORAGE_BUCKET = "user-files"

def storage_upload(user_id: str, filename: str, data: bytes,
                   content_type: str = "application/octet-stream") -> tuple[bool, str]:
    """
    Upload file to user-files/{user_id}/{filename}.
    Returns (True, path) or (False, error).
    """
    sb = get_supabase()
    if not sb:
        return False, "Storage not connected."
    try:
        # Check quota
        user = db_get_user(user_id)
        if user:
            used  = int(user.get("storage_used_bytes", 0))
            quota = int(user.get("storage_quota_bytes", 52428800))
            if used + len(data) > quota:
                mb_left = round((quota - used) / 1048576, 1)
                return False, f"Storage quota exceeded. Only {mb_left} MB remaining."

        path = f"{user_id}/{filename}"
        # Remove existing file first to allow overwrite
        try:
            sb.storage.from_(STORAGE_BUCKET).remove([path])
        except Exception:
            pass

        import tempfile, os as _os
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(delete=False) as f:
                f.write(data)
                tmp = f.name
            sb.storage.from_(STORAGE_BUCKET).upload(path=path, file=tmp)
        finally:
            if tmp:
                try: _os.remove(tmp)
                except: pass

        # Update usage counter
        db_update_storage(user_id, len(data))
        # Save file record to anchor_files table
        _save_file_record(user_id, filename, path, len(data), content_type)
        return True, path
    except Exception as e:
        return False, f"Upload error: {e}"


def storage_list(user_id: str) -> list[dict]:
    """Return list of file records for this user from anchor_files table."""
    sb = get_supabase()
    if not sb:
        return []
    try:
        result = sb.table("anchor_files")\
            .select("*")\
            .eq("user_id", user_id)\
            .order("created_at", desc=True)\
            .execute()
        return result.data or []
    except Exception:
        return []


def storage_download_url(user_id: str, filename: str, expires: int = 300) -> str:
    """Return a signed download URL valid for `expires` seconds."""
    sb = get_supabase()
    if not sb:
        return ""
    try:
        path = f"{user_id}/{filename}"
        resp = sb.storage.from_(STORAGE_BUCKET).create_signed_url(path, expires)
        if isinstance(resp, dict):
            return resp.get("signedURL") or resp.get("signed_url") or ""
        return str(resp) if resp else ""
    except Exception:
        return ""


def storage_delete(user_id: str, filename: str, file_size: int = 0) -> bool:
    """Delete a file from storage and update quota."""
    sb = get_supabase()
    if not sb:
        return False
    try:
        path = f"{user_id}/{filename}"
        sb.storage.from_(STORAGE_BUCKET).remove([path])
        if file_size > 0:
            db_update_storage(user_id, -file_size)
        # Remove from anchor_files
        sb.table("anchor_files").delete().eq("user_id", user_id).eq("filename", filename).execute()
        return True
    except Exception:
        return False


def _save_file_record(user_id: str, filename: str, path: str,
                      size: int, content_type: str):
    """Upsert a record in anchor_files so we can list user's files."""
    sb = get_supabase()
    if not sb:
        return
    try:
        sb.table("anchor_files").upsert({
            "user_id": user_id,
            "filename": filename,
            "path": path,
            "size_bytes": size,
            "content_type": content_type,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="user_id,filename").execute()
    except Exception:
        pass


# ─────────────────────────────────────────────────
# STRIPE PAYMENT HELPERS
# ─────────────────────────────────────────────────
def create_stripe_checkout(user_id: str, user_email: str) -> str:
    """
    Create a Stripe Checkout Session and return the URL.
    Falls back gracefully if Stripe SDK is not installed or key is missing.
    """
    try:
        import stripe
        stripe.api_key = st.secrets.get("STRIPE_SECRET_KEY") or os.getenv("STRIPE_SECRET_KEY")
        if not stripe.api_key:
            return ""

        price_id = st.secrets.get("STRIPE_PRICE_ID") or os.getenv("STRIPE_PRICE_ID", "")
        success_url = st.secrets.get("APP_URL", "https://your-app.streamlit.app") + "?paid=1"
        cancel_url  = st.secrets.get("APP_URL", "https://your-app.streamlit.app") + "?paid=0"

        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            customer_email=user_email,
            line_items=[{"price": price_id, "quantity": 1}],
            mode="payment",
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={"user_id": user_id},
        )
        return session.url
    except Exception:
        return ""


def check_stripe_return() -> bool:
    """
    Detect Stripe success redirect (?paid=1) and mark user as paid.
    Returns True if payment was just confirmed.
    """
    params = st.query_params
    if params.get("paid") == "1":
        user_id = st.session_state.get("user_id", "")
        if user_id:
            db_mark_paid(user_id)
            st.session_state["is_paid"] = True
            # Clear the query param so it doesn't re-fire
            st.query_params.clear()
            return True
    return False


# ─────────────────────────────────────────────────
# CSS — FULL DESIGN SYSTEM
# ─────────────────────────────────────────────────
def inject_saas_css():
    """
    Inject the complete AnchorCV SaaS design system.
    Color palette: deep navy + electric indigo + amber gold accent.
    Background: animated geometric mesh pattern.
    """
    st.markdown("""
<style>
/* ── Google Fonts ─────────────────────────────── */
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Sans:wght@300;400;500;600&display=swap');

/* ── CSS Variables ───────────────────────────── */
:root {
    --navy:      #0d1b2a;
    --navy-mid:  #1a2f4a;
    --navy-light:#243b55;
    --indigo:    #4f46e5;
    --indigo-lt: #818cf8;
    --amber:     #f59e0b;
    --amber-lt:  #fcd34d;
    --white:     #f8fafc;
    --muted:     #94a3b8;
    --card-bg:   rgba(255,255,255,0.04);
    --card-border: rgba(255,255,255,0.08);
    --radius:    14px;
    --transition: all 0.25s cubic-bezier(0.4,0,0.2,1);
}

/* ── Global reset ────────────────────────────── */
*, *::before, *::after { box-sizing: border-box; }

html, body, [data-testid="stAppViewContainer"] {
    font-family: 'DM Sans', sans-serif;
    background: var(--navy);
    color: var(--white);
}

/* ── ANIMATED BACKGROUND PATTERN ─────────────── */
[data-testid="stAppViewContainer"]::before {
    content: '';
    position: fixed;
    inset: 0;
    z-index: 0;
    background:
        radial-gradient(ellipse 80% 50% at 20% -10%, rgba(79,70,229,0.18) 0%, transparent 60%),
        radial-gradient(ellipse 60% 40% at 80% 110%, rgba(245,158,11,0.12) 0%, transparent 55%),
        radial-gradient(ellipse 40% 60% at 50% 50%, rgba(26,47,74,0.4) 0%, transparent 70%);
    pointer-events: none;
}

/* Geometric mesh lines */
[data-testid="stAppViewContainer"]::after {
    content: '';
    position: fixed;
    inset: 0;
    z-index: 0;
    background-image:
        linear-gradient(rgba(79,70,229,0.04) 1px, transparent 1px),
        linear-gradient(90deg, rgba(79,70,229,0.04) 1px, transparent 1px);
    background-size: 60px 60px;
    pointer-events: none;
    animation: meshDrift 25s linear infinite;
}

@keyframes meshDrift {
    0%   { transform: translate(0, 0); }
    100% { transform: translate(60px, 60px); }
}

/* ── Main content above background ──────────── */
[data-testid="stMain"] {
    position: relative;
    z-index: 1;
}

/* ── SIDEBAR ─────────────────────────────────── */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, var(--navy) 0%, var(--navy-mid) 100%) !important;
    border-right: 1px solid var(--card-border) !important;
}

section[data-testid="stSidebar"] * {
    color: rgba(248,250,252,0.85) !important;
    font-family: 'DM Sans', sans-serif !important;
}

section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 {
    color: #ffffff !important;
    font-family: 'Syne', sans-serif !important;
    font-weight: 700 !important;
}

section[data-testid="stSidebar"] .stButton button {
    background: linear-gradient(135deg, var(--indigo) 0%, #7c3aed 100%) !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 10px !important;
    font-weight: 600 !important;
    font-family: 'DM Sans', sans-serif !important;
    transition: var(--transition) !important;
}

section[data-testid="stSidebar"] .stButton button:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 8px 24px rgba(79,70,229,0.4) !important;
}

section[data-testid="stSidebar"] .stTextInput input,
section[data-testid="stSidebar"] .stSelectbox > div > div {
    background: rgba(255,255,255,0.06) !important;
    border: 1px solid var(--card-border) !important;
    border-radius: 8px !important;
    color: #ffffff !important;
}

/* ── AUTH SCREEN ─────────────────────────────── */
.auth-container {
    max-width: 480px;
    margin: 3rem auto;
    background: rgba(255,255,255,0.03);
    border: 1px solid var(--card-border);
    border-radius: 24px;
    padding: 2.5rem;
    backdrop-filter: blur(20px);
    box-shadow: 0 24px 80px rgba(0,0,0,0.4), 0 0 0 1px rgba(79,70,229,0.1);
}

.auth-logo {
    font-family: 'Syne', sans-serif;
    font-size: 2rem;
    font-weight: 800;
    text-align: center;
    background: linear-gradient(135deg, var(--indigo-lt), var(--amber-lt));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin-bottom: 0.25rem;
}

.auth-tagline {
    text-align: center;
    color: var(--muted);
    font-size: 0.875rem;
    margin-bottom: 2rem;
}

/* ── PAYMENT GATE ────────────────────────────── */
.payment-card {
    max-width: 560px;
    margin: 3rem auto;
    background: linear-gradient(135deg,
        rgba(79,70,229,0.12) 0%,
        rgba(26,47,74,0.6) 100%);
    border: 1px solid rgba(79,70,229,0.25);
    border-radius: 24px;
    padding: 3rem 2.5rem;
    text-align: center;
    box-shadow: 0 32px 80px rgba(0,0,0,0.5), 0 0 0 1px rgba(79,70,229,0.2);
}

.payment-price {
    font-family: 'Syne', sans-serif;
    font-size: 3.5rem;
    font-weight: 800;
    color: var(--amber-lt);
    line-height: 1;
    margin: 1rem 0 0.25rem;
}

.payment-period {
    color: var(--muted);
    font-size: 0.875rem;
    margin-bottom: 2rem;
}

.feature-list-item {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.6rem 0;
    color: rgba(248,250,252,0.8);
    font-size: 0.95rem;
    border-bottom: 1px solid rgba(255,255,255,0.04);
}

/* ── WELCOME DASHBOARD ───────────────────────── */
.welcome-header {
    font-family: 'Syne', sans-serif;
    font-size: clamp(1.8rem, 4vw, 2.8rem);
    font-weight: 800;
    background: linear-gradient(135deg, #ffffff 0%, var(--indigo-lt) 60%, var(--amber-lt) 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    line-height: 1.2;
    margin-bottom: 0.5rem;
}

.welcome-sub {
    color: var(--muted);
    font-size: 1rem;
    margin-bottom: 2.5rem;
}

.nav-card {
    background: var(--card-bg);
    border: 1px solid var(--card-border);
    border-radius: var(--radius);
    padding: 1.5rem;
    text-align: center;
    cursor: pointer;
    transition: var(--transition);
    position: relative;
    overflow: hidden;
}

.nav-card::before {
    content: '';
    position: absolute;
    inset: 0;
    background: linear-gradient(135deg, rgba(79,70,229,0.08), transparent);
    opacity: 0;
    transition: var(--transition);
}

.nav-card:hover::before { opacity: 1; }

.nav-card:hover {
    border-color: rgba(79,70,229,0.4);
    transform: translateY(-4px);
    box-shadow: 0 16px 40px rgba(0,0,0,0.3);
}

.nav-card-icon {
    font-size: 2.2rem;
    margin-bottom: 0.75rem;
    display: block;
}

.nav-card-title {
    font-family: 'Syne', sans-serif;
    font-size: 1rem;
    font-weight: 700;
    color: var(--white);
    margin-bottom: 0.25rem;
}

.nav-card-desc {
    font-size: 0.8rem;
    color: var(--muted);
    line-height: 1.4;
}

/* ── STORAGE METER ───────────────────────────── */
.storage-meter-wrap {
    background: rgba(255,255,255,0.03);
    border: 1px solid var(--card-border);
    border-radius: 12px;
    padding: 1.25rem 1.5rem;
}

.storage-meter-label {
    font-size: 0.8rem;
    color: var(--muted);
    margin-bottom: 0.5rem;
}

.storage-bar-track {
    height: 6px;
    background: rgba(255,255,255,0.08);
    border-radius: 99px;
    overflow: hidden;
    margin-bottom: 0.4rem;
}

.storage-bar-fill {
    height: 100%;
    border-radius: 99px;
    background: linear-gradient(90deg, var(--indigo), var(--amber));
    transition: width 0.6s ease;
}

.storage-bar-text {
    font-size: 0.75rem;
    color: var(--muted);
}

/* ── FILE LIST ───────────────────────────────── */
.file-row {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.75rem 1rem;
    background: rgba(255,255,255,0.02);
    border: 1px solid var(--card-border);
    border-radius: 10px;
    margin-bottom: 0.5rem;
    transition: var(--transition);
}

.file-row:hover {
    background: rgba(255,255,255,0.05);
    border-color: rgba(79,70,229,0.2);
}

.file-icon { font-size: 1.25rem; }
.file-name { flex: 1; font-size: 0.875rem; color: var(--white); font-weight: 500; }
.file-size { font-size: 0.75rem; color: var(--muted); }

/* ── BADGES ──────────────────────────────────── */
.badge-paid {
    display: inline-block;
    background: linear-gradient(135deg, #059669, #10b981);
    color: white;
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    padding: 3px 10px;
    border-radius: 99px;
    text-transform: uppercase;
}

.badge-free {
    display: inline-block;
    background: rgba(148,163,184,0.15);
    color: var(--muted);
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    padding: 3px 10px;
    border-radius: 99px;
    text-transform: uppercase;
    border: 1px solid rgba(148,163,184,0.2);
}

/* ── STREAMLIT OVERRIDES (forms, buttons, tabs) ── */
.stTextInput input, .stTextArea textarea, .stSelectbox > div > div {
    background: rgba(255,255,255,0.06) !important;
    border: 1px solid rgba(255,255,255,0.15) !important;
    border-radius: 10px !important;
    color: #f8fafc !important;
    font-family: 'DM Sans', sans-serif !important;
    transition: var(--transition) !important;
}

/* Ensure placeholder text is visible too */
.stTextInput input::placeholder,
.stTextArea textarea::placeholder {
    color: rgba(148,163,184,0.7) !important;
}

/* Force input text color for all input types */
input[type="text"], input[type="password"], input[type="email"], textarea {
    color: #f8fafc !important;
    caret-color: #818cf8 !important;
}

.stTextInput input:focus, .stTextArea textarea:focus {
    border-color: var(--indigo) !important;
    box-shadow: 0 0 0 3px rgba(79,70,229,0.2) !important;
}

label, .stLabel { color: rgba(248,250,252,0.7) !important; font-family: 'DM Sans', sans-serif !important; }

/* Primary button */
.stButton > button[kind="primary"],
.stButton > button[data-testid="baseButton-primary"] {
    background: linear-gradient(135deg, var(--indigo) 0%, #7c3aed 100%) !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 10px !important;
    font-family: 'DM Sans', sans-serif !important;
    font-weight: 600 !important;
    transition: var(--transition) !important;
}

.stButton > button[kind="primary"]:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 8px 24px rgba(79,70,229,0.45) !important;
}

/* Download buttons — always styled, always visible */
[data-testid="stDownloadButton"] > button,
[data-testid="stDownloadButton"] button {
    background: linear-gradient(135deg, var(--indigo) 0%, #7c3aed 100%) !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 10px !important;
    font-weight: 600 !important;
    font-size: 0.9rem !important;
    padding: 0.55rem 1.2rem !important;
    width: 100% !important;
    min-height: 2.5rem !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    gap: 0.4rem !important;
    transition: var(--transition) !important;
    cursor: pointer !important;
}

[data-testid="stDownloadButton"] > button:hover,
[data-testid="stDownloadButton"] button:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 8px 24px rgba(79,70,229,0.45) !important;
}

/* Secondary button */
.stButton > button:not([kind="primary"]) {
    background: rgba(255,255,255,0.04) !important;
    color: rgba(248,250,252,0.85) !important;
    border: 1px solid var(--card-border) !important;
    border-radius: 10px !important;
    font-family: 'DM Sans', sans-serif !important;
    transition: var(--transition) !important;
}

.stButton > button:not([kind="primary"]):hover {
    background: rgba(255,255,255,0.08) !important;
    border-color: rgba(79,70,229,0.3) !important;
}

/* Tabs */
.stTabs [data-baseweb="tab-list"] {
    background: rgba(255,255,255,0.03) !important;
    border-radius: 10px !important;
    padding: 4px !important;
    gap: 4px !important;
    border: 1px solid var(--card-border) !important;
}

.stTabs [data-baseweb="tab"] {
    border-radius: 8px !important;
    color: var(--muted) !important;
    font-family: 'DM Sans', sans-serif !important;
    font-weight: 500 !important;
    transition: var(--transition) !important;
}

.stTabs [aria-selected="true"] {
    background: var(--indigo) !important;
    color: #ffffff !important;
}

/* Expander */
.streamlit-expanderHeader {
    background: var(--card-bg) !important;
    border: 1px solid var(--card-border) !important;
    border-radius: 10px !important;
    color: var(--white) !important;
    font-family: 'DM Sans', sans-serif !important;
}

/* Success/error/info alerts */
.stAlert { border-radius: 10px !important; font-family: 'DM Sans', sans-serif !important; }

/* Progress bar */
.stProgress > div > div { background: linear-gradient(90deg, var(--indigo), var(--amber)) !important; border-radius: 99px !important; }

/* Divider */
hr { border-color: var(--card-border) !important; }

/* Metric */
[data-testid="stMetricValue"] { color: var(--white) !important; font-family: 'Syne', sans-serif !important; }
[data-testid="stMetricLabel"] { color: var(--muted) !important; }

/* ── FILE UPLOADER BUTTON — high contrast ──────── */
.stFileUploader button,
[data-testid="stFileUploaderDropzone"] button {
    background: linear-gradient(135deg, var(--indigo) 0%, #7c3aed 100%) !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    font-family: 'DM Sans', sans-serif !important;
}

[data-testid="stFileUploaderDropzone"] {
    background: rgba(79,70,229,0.06) !important;
    border: 1px dashed rgba(79,70,229,0.4) !important;
    border-radius: 12px !important;
}

[data-testid="stFileUploaderDropzone"] p,
[data-testid="stFileUploaderDropzone"] span {
    color: rgba(248,250,252,0.75) !important;
}

/* ── SIDEBAR — no overflow / clean bottom pad ─── */
section[data-testid="stSidebar"] > div {
    padding-bottom: 80px !important;
    overflow-x: hidden !important;
    overflow-y: auto !important;
}

/* ── WELCOME HEADER — tighter, no stretch ───────── */
.welcome-header {
    font-family: 'Syne', sans-serif !important;
    font-size: clamp(1.6rem, 3vw, 2.4rem) !important;
    font-weight: 800 !important;
    letter-spacing: 0.3px !important;
    line-height: 1.2 !important;
}

/* ── NAV CARD DESCRIPTION — higher contrast ─────── */
.nav-card-desc {
    color: #c4cfde !important;
    font-size: 0.82rem !important;
    line-height: 1.5 !important;
}

/* ── AUTH TABS — 50-50, centered, pill style ─────── */
.stTabs [data-baseweb="tab-list"] {
    width: 100% !important;
    display: flex !important;
}
.stTabs [data-baseweb="tab"] {
    flex: 1 !important;
    text-align: center !important;
    justify-content: center !important;
    font-weight: 600 !important;
    font-size: 0.9rem !important;
    padding: 0.5rem 1rem !important;
}

/* ── PAYMENT PRICE — balanced sizing ────────────── */
.payment-price {
    font-size: 3rem !important;
    font-weight: 800 !important;
    line-height: 1 !important;
    margin: 0.75rem 0 0.2rem !important;
}

/* ── SIDEBAR ICON OVERFLOW FIX ───────────────────── */
section[data-testid="stSidebar"] {
    overflow: hidden !important;
    min-width: 0 !important;
}

/* ============================================================ */
/* RADIO BUTTON STYLES                                         */
/* ============================================================ */

/* ── MAIN RADIO BUTTON CONTAINER ───────────────── */
.stRadio > div {
    background: rgba(255,255,255,0.02);
    border-radius: 16px;
    padding: 0.75rem;
    border: 1px solid rgba(255,255,255,0.05);
}

/* Style for each radio option — ALL text visible */
.stRadio > div > label {
    background: rgba(255,255,255,0.03) !important;
    padding: 0.75rem 1rem !important;
    border-radius: 12px !important;
    margin: 4px 0 !important;
    transition: all 0.2s ease !important;
    border: 1px solid transparent !important;
    display: flex !important;
    align-items: center !important;
    cursor: pointer !important;
}

/* ✅ KEY FIX: Make ALL radio label text visible */
.stRadio > div > label span,
.stRadio > div > label p,
.stRadio label span {
    color: #cbd5e1 !important;
    font-size: 0.95rem !important;
}

/* Hover effect */
.stRadio > div > label:hover {
    background: rgba(255,255,255,0.07) !important;
    border-color: rgba(79,70,229,0.4) !important;
    transform: translateX(3px);
}

.stRadio > div > label:hover span,
.stRadio > div > label:hover p {
    color: #f1f5f9 !important;
}

/* Selected state */
.stRadio > div > label:has(input:checked) {
    background: linear-gradient(90deg, rgba(79,70,229,0.2), rgba(79,70,229,0.06)) !important;
    border-left: 4px solid #6366f1 !important;
}

.stRadio > div > label:has(input:checked) span,
.stRadio > div > label:has(input:checked) p {
    color: #a5b4fc !important;
    font-weight: 600 !important;
}

/* ── Radio button circle ──────────────────────── */
.stRadio [data-testid="stMarkdownContainer"] p {
    color: #cbd5e1 !important;
    margin: 0 !important;
}

/* ============================================================ */
/* HORIZONTAL RADIO (None / Paste / Upload)                    */
/* ============================================================ */

.stRadio > div[data-testid="stHorizontalRadio"] {
    background: rgba(255,255,255,0.03);
    border-radius: 40px;
    padding: 4px;
    display: flex;
    gap: 4px;
    border: 1px solid rgba(255,255,255,0.08);
}

.stRadio > div[data-testid="stHorizontalRadio"] > label {
    background: transparent !important;
    padding: 0.6rem 1rem !important;
    border-radius: 40px !important;
    margin: 0 !important;
    flex: 1;
    text-align: center;
    transition: all 0.2s ease !important;
    border: 1px solid transparent !important;
}

/* Default text color — visible */
.stRadio > div[data-testid="stHorizontalRadio"] > label span {
    color: #94a3b8 !important;
    font-weight: 500 !important;
}

/* Hover effects */
.stRadio > div[data-testid="stHorizontalRadio"] > label:hover {
    background: rgba(255,255,255,0.05) !important;
}

.stRadio > div[data-testid="stHorizontalRadio"] > label:hover span {
    color: #f8fafc !important;
}

/* Selected state for horizontal radio */
.stRadio > div[data-testid="stHorizontalRadio"] > label:has(input:checked) {
    background: linear-gradient(135deg, #4f46e5, #7c3aed) !important;
    border: none !important;
}

.stRadio > div[data-testid="stHorizontalRadio"] > label:has(input:checked) span {
    color: white !important;
    font-weight: 600 !important;
}

/* ── SELECT BOXES — visible text ─────────────────── */
.stSelectbox [data-baseweb="select"] span {
    color: #f8fafc !important;
}

/* ── METRIC DELTA — visible ───────────────────────── */
[data-testid="stMetricDelta"] {
    color: var(--amber-lt) !important;
}

/* ── SECTION HEADERS — make them stand out ───────── */
h4.section-header {
    color: var(--indigo-lt) !important;
    font-family: 'Syne', sans-serif !important;
    font-size: 1rem !important;
    font-weight: 600 !important;
    margin-top: 1.5rem !important;
    margin-bottom: 0.75rem !important;
    letter-spacing: 0.5px !important;
    border-left: 3px solid var(--indigo);
    padding-left: 0.75rem !important;
}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────
# SESSION DEFAULTS
# ─────────────────────────────────────────────────
def init_session():
    defaults = {
        "authenticated": False,
        "user_id": None,
        "user_data": {},
        "is_paid": False,
        "show_dashboard": False,
        "app_destination": None,   # "resume" | "cv" | "files"
        "auth_tab": "login",
        "cloud_files": [],
        "storage_used": 0,
        "storage_quota": 52428800,
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)


# ─────────────────────────────────────────────────
# HELPER — storage meter HTML
# ─────────────────────────────────────────────────
def _storage_meter_html(used_bytes: int, quota_bytes: int) -> str:
    pct = min(100, round(used_bytes / quota_bytes * 100, 1)) if quota_bytes else 0
    used_mb  = round(used_bytes  / 1048576, 1)
    quota_mb = round(quota_bytes / 1048576, 0)
    # Color shifts amber → red as it fills
    color = "linear-gradient(90deg,#4f46e5,#f59e0b)" if pct < 70 else "linear-gradient(90deg,#f59e0b,#ef4444)"
    return f"""
<div class="storage-meter-wrap">
  <div class="storage-meter-label">☁️ Cloud Storage</div>
  <div class="storage-bar-track">
    <div class="storage-bar-fill" style="width:{pct}%;background:{color};"></div>
  </div>
  <div class="storage-bar-text">{used_mb} MB / {int(quota_mb)} MB used ({pct}%)</div>
</div>
"""


# ─────────────────────────────────────────────────
# SCREEN 1 — AUTHENTICATION
# ─────────────────────────────────────────────────
def show_auth_screen():
    inject_saas_css()

    # Animated floating orbs behind the card
    st.markdown("""
<div style="position:fixed;top:15%;left:10%;width:300px;height:300px;
    border-radius:50%;background:radial-gradient(circle,rgba(79,70,229,0.15),transparent 70%);
    pointer-events:none;animation:floatOrb 8s ease-in-out infinite;"></div>
<div style="position:fixed;bottom:20%;right:8%;width:250px;height:250px;
    border-radius:50%;background:radial-gradient(circle,rgba(245,158,11,0.1),transparent 70%);
    pointer-events:none;animation:floatOrb 11s ease-in-out infinite reverse;"></div>
<style>
@keyframes floatOrb {
    0%,100%{transform:translateY(0) scale(1);}
    50%{transform:translateY(-30px) scale(1.05);}
}
</style>
""", unsafe_allow_html=True)

    # Center the card
    _, col, _ = st.columns([1, 1.4, 1])
    with col:
        st.markdown('<div class="auth-container">', unsafe_allow_html=True)
        st.markdown('<div class="auth-logo">🔮 AnchorCV</div>', unsafe_allow_html=True)
        st.markdown('<div class="auth-tagline">Evidence-Anchored Career Intelligence</div>', unsafe_allow_html=True)

        # ── 50-50 SEGMENTED CONTROL ─────────────────
        if "auth_mode" not in st.session_state:
            st.session_state["auth_mode"] = "login"

        tab_col1, tab_col2 = st.columns(2)
        with tab_col1:
            if st.button(
                "Sign In",
                use_container_width=True,
                type="primary" if st.session_state["auth_mode"] == "login" else "secondary",
                key="btn_signin_tab"
            ):
                st.session_state["auth_mode"] = "login"
                st.rerun()
        with tab_col2:
            if st.button(
                "Create Account",
                use_container_width=True,
                type="primary" if st.session_state["auth_mode"] == "signup" else "secondary",
                key="btn_signup_tab"
            ):
                st.session_state["auth_mode"] = "signup"
                st.rerun()

        st.markdown("<hr style='margin:1rem 0 1.25rem;'>", unsafe_allow_html=True)

        # ── LOGIN ─────────────────────
        if st.session_state["auth_mode"] == "login":
            with st.form("login_form", clear_on_submit=False):
                email    = st.text_input("Email", placeholder="you@example.com", key="login_email")
                password = st.text_input("Password", type="password", placeholder="••••••••", key="login_pass")
                submitted = st.form_submit_button("Sign In →", use_container_width=True, type="primary")

            if submitted:
                if not email or not password:
                    st.error("Please enter your email and password.")
                else:
                    with st.spinner("Authenticating…"):
                        ok, result = db_login_user(email, password)
                    if ok:
                        _finalize_login(result)
                    else:
                        st.error(result.get("error", "Login failed."))

        # ── SIGN UP ───────────────────
        else:
            with st.form("signup_form", clear_on_submit=True):
                c1, c2 = st.columns(2)
                with c1: first = st.text_input("First Name", placeholder="Jane", key="su_first")
                with c2: last  = st.text_input("Last Name",  placeholder="Doe",  key="su_last")
                su_email   = st.text_input("Email", placeholder="jane@example.com", key="su_email")
                country    = st.text_input("Country", placeholder="Pakistan", key="su_country")
                su_pass    = st.text_input("Password", type="password", placeholder="Min 8 characters", key="su_pass")
                su_confirm = st.text_input("Confirm Password", type="password", placeholder="Repeat password", key="su_confirm")
                agree      = st.checkbox("I agree to the Terms of Service")
                su_submit  = st.form_submit_button("Create Account →", use_container_width=True, type="primary")

            if su_submit:
                if not all([first, last, su_email, country, su_pass, su_confirm]):
                    st.error("Please fill in all fields.")
                elif su_pass != su_confirm:
                    st.error("Passwords do not match.")
                elif len(su_pass) < 8:
                    st.error("Password must be at least 8 characters.")
                elif not agree:
                    st.error("Please accept the Terms of Service.")
                else:
                    with st.spinner("Creating your account…"):
                        ok, result = db_register_user(first, last, su_email, country, su_pass)
                    if ok:
                        # Auto-login after registration
                        login_ok, user = db_login_user(su_email, su_pass)
                        if login_ok and isinstance(user, dict) and "id" in user:
                            _finalize_login(user)
                        else:
                            st.success("Account created! Please sign in.")
                            st.session_state["auth_mode"] = "login"
                            st.rerun()
                    else:
                        st.error(result)

        st.markdown('</div>', unsafe_allow_html=True)


def _finalize_login(user: dict):
    """Populate session state after successful auth."""
    st.session_state["authenticated"] = True
    st.session_state["user_id"]   = user["id"]
    st.session_state["is_paid"]   = user.get("is_paid", False)
    st.session_state["user_data"] = user
    st.session_state["storage_used"]  = int(user.get("storage_used_bytes", 0))
    st.session_state["storage_quota"] = int(user.get("storage_quota_bytes", 52428800))
    # Load API key from secrets into session for anchor_core.py
    oai_key = st.secrets.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY", "")
    st.session_state["openai_api_key"] = oai_key
    st.rerun()


# ─────────────────────────────────────────────────
# SCREEN 2 — PAYMENT GATE
# ─────────────────────────────────────────────────
def show_payment_screen():
    inject_saas_css()

    # Check if returning from Stripe
    if check_stripe_return():
        st.success("🎉 Payment confirmed! Welcome to AnchorCV Premium.")
        time.sleep(1.5)
        st.session_state["show_dashboard"] = True
        st.rerun()

    user = st.session_state["user_data"]
    first_name = user.get("first_name", "there")

    _, col, _ = st.columns([1, 1.6, 1])
    with col:
        st.markdown(f"""
<div class="payment-card">
  <div style="font-family:'Syne',sans-serif;font-size:0.8rem;font-weight:700;
      letter-spacing:0.12em;color:var(--indigo-lt);text-transform:uppercase;margin-bottom:0.5rem;">
    Welcome, {first_name}
  </div>
  <div style="font-family:'Syne',sans-serif;font-size:1.6rem;font-weight:800;color:white;line-height:1.2;margin-bottom:0.5rem;">
    Unlock AnchorCV Premium
  </div>
  <div style="color:var(--muted);font-size:0.9rem;margin-bottom:1.5rem;">
    One-time payment. Lifetime access.
  </div>
  <div class="payment-price">$9</div>
  <div class="payment-period">one-time · no subscriptions</div>
  <div style="text-align:left;margin-bottom:2rem;">
    <div class="feature-list-item">✦ Resume Intelligence Engine — gap analysis + ATS fixes</div>
    <div class="feature-list-item">✦ CV Generator — 5 professional formats</div>
    <div class="feature-list-item">✦ Evidence-Anchored Cover Letters &amp; Emails</div>
    <div class="feature-list-item">✦ 50 MB Cloud Storage for your files</div>
    <div class="feature-list-item">✦ Score Rationale with reviewer risk flags</div>
    <div class="feature-list-item">✦ All future updates included</div>
  </div>
</div>
""", unsafe_allow_html=True)

        stripe_url = create_stripe_checkout(
            user_id=st.session_state["user_id"],
            user_email=user.get("email", "")
        )

        if stripe_url:
            st.link_button(
                "💳  Pay $9 — Continue to Stripe →",
                url=stripe_url,
                use_container_width=True,
                type="primary"
            )
        else:
            # Stripe not configured — show manual bypass for dev/testing
            st.warning("⚙️ Stripe not configured. Contact admin or use dev bypass below.")
            if st.button("🔓 Dev Bypass — Mark as Paid (testing only)", use_container_width=True):
                db_mark_paid(st.session_state["user_id"])
                st.session_state["is_paid"] = True
                st.session_state["show_dashboard"] = True
                st.rerun()

        st.markdown("""
<div style="text-align:center;margin-top:1.5rem;color:var(--muted);font-size:0.8rem;">
  🔒 Payments secured by Stripe · We never store card details
</div>
""", unsafe_allow_html=True)

        # Logout link
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("← Sign out", use_container_width=False):
            _logout()


# ─────────────────────────────────────────────────
# SCREEN 3 — WELCOME DASHBOARD
# ─────────────────────────────────────────────────
def show_dashboard():
    inject_saas_css()
    user = st.session_state["user_data"]
    first_name = user.get("first_name", "")
    user_id    = st.session_state["user_id"]

    # ── SIDEBAR (dashboard version) ───────────────
    with st.sidebar:
        # User badge
        st.markdown(f"""
<div style="padding:1rem 0 0.5rem;">
  <div style="font-family:'Syne',sans-serif;font-weight:700;font-size:1.1rem;color:#fff;">
    {user.get('first_name','')} {user.get('last_name','')}
  </div>
  <div style="font-size:0.8rem;color:rgba(255,255,255,0.5);margin-bottom:0.75rem;">
    {user.get('email','')}
  </div>
  <span class="badge-paid">Premium ✓</span>
</div>
""", unsafe_allow_html=True)
        st.markdown("---")

        # Storage meter
        used  = st.session_state.get("storage_used", 0)
        quota = st.session_state.get("storage_quota", 52428800)
        st.markdown(_storage_meter_html(used, quota), unsafe_allow_html=True)
        st.markdown("---")

        # Cloud Files section
        st.markdown("### 📁 My Cloud Files")
        files = storage_list(user_id)
        if files:
            for f in files[:8]:
                ext  = f.get("filename", "").rsplit(".", 1)[-1].upper()
                icon = {"PDF": "📄", "DOCX": "📝", "TXT": "📃", "PNG": "🖼", "JPG": "🖼"}.get(ext, "📎")
                size_kb = round(f.get("size_bytes", 0) / 1024, 1)
                url = storage_download_url(user_id, f.get("filename", ""))
                if url:
                    st.markdown(
                        f'<div class="file-row">'
                        f'<span class="file-icon">{icon}</span>'
                        f'<span class="file-name"><a href="{url}" target="_blank" '
                        f'style="color:#818cf8;text-decoration:none;">{f.get("filename","")}</a></span>'
                        f'<span class="file-size">{size_kb} KB</span>'
                        f'</div>',
                        unsafe_allow_html=True
                    )
                else:
                    st.markdown(
                        f'<div class="file-row">'
                        f'<span class="file-icon">{icon}</span>'
                        f'<span class="file-name">{f.get("filename","")}</span>'
                        f'<span class="file-size">{size_kb} KB</span>'
                        f'</div>',
                        unsafe_allow_html=True
                    )
        else:
            st.caption("No files saved yet.")

        st.markdown("---")
        if st.button("🚪 Sign Out", use_container_width=True):
            _logout()

    # ── MAIN DASHBOARD ────────────────────────────
    st.markdown(f"""
<div style="padding:2rem 0 1rem;">
  <div class="welcome-header">Good to see you, {first_name} 👋</div>
</div>
""", unsafe_allow_html=True)

    # ── NAV CARDS ─────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.markdown("""
<div class="nav-card">
  <span class="nav-card-icon">🔮</span>
  <div class="nav-card-title">Resume Intelligence</div>
  <div class="nav-card-desc">Gap analysis, ATS fixes, cover letters & strategy</div>
</div>
""", unsafe_allow_html=True)
        if st.button("Open →", key="goto_resume", use_container_width=True, type="primary"):
            st.session_state["app_destination"] = "resume"
            st.rerun()

    with c2:
        st.markdown("""
<div class="nav-card">
  <span class="nav-card-icon">📄</span>
  <div class="nav-card-title">CV Generator</div>
  <div class="nav-card-desc">Build professional CVs in 5 polished formats</div>
</div>
""", unsafe_allow_html=True)
        if st.button("Open →", key="goto_cv", use_container_width=True, type="primary"):
            st.session_state["app_destination"] = "cv"
            st.rerun()

    with c3:
        st.markdown("""
<div class="nav-card">
  <span class="nav-card-icon">☁️</span>
  <div class="nav-card-title">My Cloud Files</div>
  <div class="nav-card-desc">View, download or delete your saved files</div>
</div>
""", unsafe_allow_html=True)
        if st.button("Open →", key="goto_files", use_container_width=True, type="primary"):
            st.session_state["app_destination"] = "files"
            st.rerun()

    with c4:
        st.markdown(f"""
<div class="nav-card">
  <span class="nav-card-icon">📊</span>
  <div class="nav-card-title">Account</div>
  <div class="nav-card-desc">Storage: {round(st.session_state.get("storage_used",0)/1048576,1)} MB of {round(st.session_state.get("storage_quota",52428800)/1048576,0):.0f} MB used</div>
</div>
""", unsafe_allow_html=True)
        if st.button("View →", key="goto_account", use_container_width=True):
            st.session_state["app_destination"] = "account"
            st.rerun()

    # ── QUICK STATS ───────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    files = storage_list(user_id)
    total_files  = len(files)
    used_mb = round(st.session_state.get("storage_used", 0) / 1048576, 1)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("📁 Files Saved", total_files)
    m2.metric("💾 Storage Used", f"{used_mb} MB")
    m3.metric("🔑 Account Status", "Premium")
    m4.metric("🌍 Region", user.get("country", "—"))


# ─────────────────────────────────────────────────
# SCREEN 4 — CLOUD FILES MANAGER
# ─────────────────────────────────────────────────
def show_files_screen():
    inject_saas_css()
    user_id = st.session_state["user_id"]

    with st.sidebar:
        if st.button("← Dashboard", use_container_width=True):
            st.session_state["app_destination"] = None
            st.rerun()
        st.markdown(_storage_meter_html(
            st.session_state.get("storage_used", 0),
            st.session_state.get("storage_quota", 52428800)
        ), unsafe_allow_html=True)
        if st.button("🚪 Sign Out", use_container_width=True):
            _logout()

    st.markdown('<h2 style="font-family:Syne,sans-serif;font-weight:800;color:#fff;">☁️ My Cloud Files</h2>', unsafe_allow_html=True)

    files = storage_list(user_id)
    if not files:
        st.info("You haven't saved any files to the cloud yet. Generate an output in Resume Intelligence or CV Generator, then click **Save to Cloud**.")
        return

    for f in files:
        fname    = f.get("filename", "unknown")
        size_kb  = round(f.get("size_bytes", 0) / 1024, 1)
        ext      = fname.rsplit(".", 1)[-1].upper()
        icon     = {"PDF": "📄", "DOCX": "📝", "TXT": "📃", "PNG": "🖼", "JPG": "🖼"}.get(ext, "📎")
        created  = f.get("created_at", "")[:10]

        col_name, col_date, col_size, col_dl, col_del = st.columns([4, 2, 1.5, 1.5, 1.2])
        col_name.markdown(f"**{icon} {fname}**")
        col_date.caption(created)
        col_size.caption(f"{size_kb} KB")

        url = storage_download_url(user_id, fname)
        if url:
            col_dl.link_button("⬇ Download", url=url, use_container_width=True)

        if col_del.button("🗑", key=f"del_{fname}", use_container_width=True,
                          help=f"Delete {fname}"):
            storage_delete(user_id, fname, f.get("size_bytes", 0))
            # Refresh usage
            fresh = db_get_user(user_id)
            if fresh:
                st.session_state["storage_used"] = int(fresh.get("storage_used_bytes", 0))
            st.success(f"Deleted {fname}")
            st.rerun()

        st.markdown("---")


# ─────────────────────────────────────────────────
# SCREEN 5 — ACCOUNT INFO
# ─────────────────────────────────────────────────
def show_account_screen():
    inject_saas_css()
    user = st.session_state["user_data"]

    with st.sidebar:
        if st.button("← Dashboard", use_container_width=True):
            st.session_state["app_destination"] = None
            st.rerun()
        if st.button("🚪 Sign Out", use_container_width=True):
            _logout()

    st.markdown('<h2 style="font-family:Syne,sans-serif;font-weight:800;color:#fff;">👤 Account</h2>', unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### Profile")
        st.info(f"**Name:** {user.get('first_name','')} {user.get('last_name','')}")
        st.info(f"**Email:** {user.get('email','')}")
        st.info(f"**Country:** {user.get('country','—')}")
        st.info(f"**Member since:** {user.get('created_at','—')[:10]}")
    with c2:
        st.markdown("#### Storage")
        used  = st.session_state.get("storage_used", 0)
        quota = st.session_state.get("storage_quota", 52428800)
        st.markdown(_storage_meter_html(used, quota), unsafe_allow_html=True)
        st.markdown("#### Status")
        st.markdown('<span class="badge-paid">Premium — Active</span>', unsafe_allow_html=True)


# ─────────────────────────────────────────────────
# SCREEN 6 — MAIN APP WRAPPER
# ─────────────────────────────────────────────────
def show_app_screen(start_tab: str = "resume"):
    """
    Renders the existing anchor_core.py app (renamed from app.py)
    with the SaaS sidebar injected alongside it.
    """
    inject_saas_css()
    user_id = st.session_state["user_id"]
    user    = st.session_state["user_data"]

    with st.sidebar:
        # Back to dashboard
        if st.button("← Dashboard", use_container_width=True):
            st.session_state["app_destination"] = None
            st.rerun()
        st.markdown("---")

        # User info
        st.markdown(f"""
<div style="font-size:0.85rem;color:rgba(255,255,255,0.6);margin-bottom:0.25rem;">Signed in as</div>
<div style="font-weight:600;color:#fff;margin-bottom:0.75rem;">{user.get('first_name','')} {user.get('last_name','')}</div>
<span class="badge-paid">Premium ✓</span>
""", unsafe_allow_html=True)

        st.markdown("---")
        # Storage meter
        st.markdown(_storage_meter_html(
            st.session_state.get("storage_used", 0),
            st.session_state.get("storage_quota", 52428800)
        ), unsafe_allow_html=True)

        st.markdown("---")
        # Cloud files quick list
        st.markdown("**📁 My Cloud Files**")
        files = storage_list(user_id)
        if files:
            for f in files[:5]:
                ext  = f.get("filename","").rsplit(".",1)[-1].upper()
                icon = {"PDF":"📄","DOCX":"📝","TXT":"📃"}.get(ext,"📎")
                st.caption(f"{icon} {f.get('filename','')}")
        else:
            st.caption("No cloud files yet.")

        st.markdown("---")
        if st.button("🚪 Sign Out", use_container_width=True):
            _logout()

    # ── INJECT SAVE-TO-CLOUD BUTTONS AFTER OUTPUT ─
    # (The anchor_core app outputs go into st.session_state["ai_response"])
    # We call anchor_core.main() which handles Tab 1 + Tab 2 entirely,
    # but we intercept the Export tab to add "Save to Cloud".
    _run_core_app(start_tab, user_id)


def _run_core_app(start_tab: str, user_id: str):
    """
    Call the existing app's main() and add Save-to-Cloud buttons
    beneath the existing Download buttons.
    """
    try:
        import anchor_core          # The OLD app.py renamed to anchor_core.py
        anchor_core.main()
    except ImportError:
        st.error(
            "⚠️ **anchor_core.py not found.** "
            "Please rename your existing `app.py` to `anchor_core.py` and redeploy."
        )
        st.code("mv app.py anchor_core.py\nmv auth_layer.py app.py")
        return

    # ── SAVE TO CLOUD — inject after anchor_core renders ─────────
    ai_resp = st.session_state.get("ai_response")
    if ai_resp:
        st.markdown("---")
        st.markdown("#### ☁️ Save to Cloud")
        col_pdf, col_docx = st.columns(2)

        # Save PDF to cloud
        with col_pdf:
            pdf_key = None
            for k in st.session_state:
                if k.startswith("pdf_ready_"):
                    pdf_key = k
                    break
            if pdf_key and st.session_state[pdf_key]:
                if st.button("☁️ Save PDF to Cloud", use_container_width=True, key="cloud_save_pdf"):
                    fname = st.session_state.get(f"pdf_filename_{pdf_key.replace('pdf_ready_','')}", "output.pdf")
                    ok, msg = storage_upload(user_id, fname, st.session_state[pdf_key], "application/pdf")
                    if ok:
                        st.success(f"✅ {fname} saved to cloud!")
                        fresh = db_get_user(user_id)
                        if fresh:
                            st.session_state["storage_used"] = int(fresh.get("storage_used_bytes", 0))
                    else:
                        st.error(f"Upload failed: {msg}")

        # Save DOCX to cloud
        with col_docx:
            docx_key = None
            for k in st.session_state:
                if k.startswith("docx_ready_"):
                    docx_key = k
                    break
            if docx_key and st.session_state[docx_key]:
                if st.button("☁️ Save DOCX to Cloud", use_container_width=True, key="cloud_save_docx"):
                    fname = st.session_state.get(f"docx_filename_{docx_key.replace('docx_ready_','')}", "output.docx")
                    ok, msg = storage_upload(
                        user_id, fname, st.session_state[docx_key],
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    )
                    if ok:
                        st.success(f"✅ {fname} saved to cloud!")
                        fresh = db_get_user(user_id)
                        if fresh:
                            st.session_state["storage_used"] = int(fresh.get("storage_used_bytes", 0))
                    else:
                        st.error(f"Upload failed: {msg}")


# ─────────────────────────────────────────────────
# LOGOUT
# ─────────────────────────────────────────────────
def _logout():
    """Clear all session state and return to auth screen."""
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.rerun()


# ─────────────────────────────────────────────────
# ROUTER — MAIN ENTRY POINT
# ─────────────────────────────────────────────────
def main():
    init_session()

    # ── Not authenticated → Show auth ─────────────
    if not st.session_state.get("authenticated"):
        show_auth_screen()
        return

    # ── Authenticated but not paid → Payment gate ─
    if not st.session_state.get("is_paid"):
        # Re-check DB in case payment was confirmed externally
        fresh = db_get_user(st.session_state["user_id"])
        if fresh and fresh.get("is_paid"):
            st.session_state["is_paid"] = True
            st.rerun()
        else:
            show_payment_screen()
            return

    # ── Paid — route to correct screen ────────────
    dest = st.session_state.get("app_destination")

    if dest == "resume":
        show_app_screen(start_tab="resume")
    elif dest == "cv":
        show_app_screen(start_tab="cv")
    elif dest == "files":
        show_files_screen()
    elif dest == "account":
        show_account_screen()
    else:
        show_dashboard()


if __name__ == "__main__":
    main()
