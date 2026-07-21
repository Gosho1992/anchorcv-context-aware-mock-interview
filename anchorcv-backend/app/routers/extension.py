"""
AnchorCV Chrome Extension — Backend Router
Add to main.py:
    from app.routers import extension
    app.include_router(extension.router, prefix=settings.api_prefix)
"""

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from pydantic import BaseModel
from supabase import create_client, Client

from app.config import settings
from app.deps.auth import get_current_user
from app.services.legacy_bridge import extract_clean_resume_text, analyze_resume

# ── Supabase client (service key bypasses RLS) ───────────────────────────────
supabase: Client = create_client(settings.supabase_url, settings.supabase_service_key)

router = APIRouter(tags=["extension"])

DAILY_LIMIT = 20


# ── Models ───────────────────────────────────────────────────────────────────

class AnalyseRequest(BaseModel):
    requirement_text: str
    output_type: str  # "Cover Letter" or "Email to Professor"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_user_row(user_id: str) -> dict:
    result = supabase.table("anchor_users").select("*").eq("id", user_id).single().execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="User not found")
    return result.data


def _check_and_reset_limit(user_row: dict, user_id: str) -> int:
    """Returns current usage count, resetting if 24h have passed."""
    last_reset = user_row.get("extension_last_reset")
    count = user_row.get("extension_usage_count", 0) or 0

    if last_reset:
        if isinstance(last_reset, str):
            last_reset = datetime.fromisoformat(last_reset.replace("Z", "+00:00"))
        if datetime.now(timezone.utc) - last_reset > timedelta(hours=24):
            supabase.table("anchor_users").update({
                "extension_usage_count": 0,
                "extension_last_reset": datetime.now(timezone.utc).isoformat()
            }).eq("id", user_id).execute()
            return 0

    return count


# ── Routes ───────────────────────────────────────────────────────────────────

@router.get("/extension/cv")
def get_cv_status(current_user=Depends(get_current_user)):
    """Returns whether the user has a stored CV."""
    user_row = _get_user_row(current_user["id"])
    return {
        "stored": bool(user_row.get("stored_cv_text")),
        "filename": user_row.get("stored_cv_filename")
    }


@router.post("/extension/cv")
async def upload_cv(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user)
):
    """Upload CV once — stored as text, reused for all future analyses."""
    filename = file.filename or "cv"
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""

    if ext not in {".pdf", ".docx", ".txt"}:
        raise HTTPException(status_code=400, detail="Please upload a PDF, DOCX, or TXT file.")

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="File is empty.")

    try:
        resume_text = extract_clean_resume_text(contents, file.content_type or "")
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not parse file: {e}")

    if not resume_text or len(resume_text.strip()) < 50:
        raise HTTPException(
            status_code=422,
            detail="Not enough text extracted. Try a DOCX or TXT version of your CV."
        )

    supabase.table("anchor_users").update({
        "stored_cv_text": resume_text,
        "stored_cv_filename": filename
    }).eq("id", current_user["id"]).execute()

    return {"success": True, "filename": filename}


@router.post("/extension/analyse")
def extension_analyse(
    body: AnalyseRequest,
    current_user=Depends(get_current_user)
):
    """
    Generate cover letter or email using stored CV.
    Requires Premium subscription. 20 uses per day.
    """
    user_row = _get_user_row(current_user["id"])

    # ── Check CV exists ──────────────────────────────────────────────────────
    resume_text = user_row.get("stored_cv_text")
    if not resume_text:
        raise HTTPException(
            status_code=400,
            detail="No CV found. Please upload your CV in the extension first."
        )

    # ── Check premium status ─────────────────────────────────────────────────
    TEST_ACCOUNTS = {"test.zia@gmail.com", "zainzia1992@gmail.com"}
    is_premium = (
        user_row.get("is_premium", False) or
        user_row.get("subscription_status") == "active" or
        user_row.get("email", "") in TEST_ACCOUNTS
    )

    # ── Require premium subscription ─────────────────────────────────────────
    if not is_premium:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "premium_required",
                "message": "The AnchorCV extension requires a Premium subscription.",
                "upgrade_url": "https://anchorcv.com/#pricing"
            }
        )

    # ── Enforce daily limit (20/day) ──────────────────────────────────────────
    count = _check_and_reset_limit(user_row, current_user["id"])
    if count >= DAILY_LIMIT:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "daily_limit_reached",
                "message": f"You've used all {DAILY_LIMIT} uses today. Resets in 24 hours.",
            }
        )

    # ── Validate output type ─────────────────────────────────────────────────
    valid_types = [
        "Cover Letter",
        "Email to Professor",
        "ATS Score & Keywords",
        "Resume Improvement",
        "Application Strategy"
    ]
    if body.output_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"output_type must be one of: {', '.join(valid_types)}"
        )

    # ── Run analysis ──────────────────────────────────────────────────────────
    try:
        result = analyze_resume(
            file_bytes=resume_text.encode("utf-8"),
            content_type="text/plain",
            requirement_text=body.requirement_text,
            output_type=body.output_type,
            model="gpt-4o-mini",
            temperature=0.7
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {e}")

    # ── Increment counter ─────────────────────────────────────────────────────
    new_count = (user_row.get("extension_usage_count") or 0) + 1
    supabase.table("anchor_users").update({
        "extension_usage_count": new_count
    }).eq("id", current_user["id"]).execute()

    output_text = result.get("result_text") or result.get("result_html") or "No result returned."

    return {
        "text": output_text,
        "usage_count": new_count,
        "limit": DAILY_LIMIT,
        "is_premium": is_premium
    }
