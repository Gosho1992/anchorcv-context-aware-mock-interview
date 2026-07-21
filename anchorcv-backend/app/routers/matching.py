from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from typing import Optional
from app.deps.auth import require_active_access
from app.services.legacy_bridge import match_resume

router = APIRouter(tags=["matching"])


@router.post("/match")
@router.post("/match-score")
async def match_score(
    file: Optional[UploadFile] = File(None),
    resume_file: Optional[UploadFile] = File(None),
    job_description: str = Form(default=""),
    requirement_text: str = Form(default=""),
    requirement_file: Optional[UploadFile] = File(None),
    model: str = Form(default="gpt-4o-mini"),
    temperature: float = Form(default=0.3),
    user=Depends(require_active_access),
):
    # Accept both 'file' and 'resume_file' field names
    actual_file = resume_file or file
    if not actual_file:
        raise HTTPException(status_code=400, detail="Resume file is required.")

    # Accept both 'job_description' and 'requirement_text'
    job_text = job_description.strip() or requirement_text.strip()

    # If a requirement file was uploaded, extract text from it too
    if requirement_file:
        req_bytes = await requirement_file.read()
        if req_bytes:
            from app.services.legacy_bridge import extract_clean_resume_text
            req_text = extract_clean_resume_text(req_bytes, requirement_file.content_type or "")
            if req_text:
                job_text = (job_text + "\n\n" + req_text).strip() if job_text else req_text

    file_bytes = await actual_file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Resume file is empty.")

    return match_resume(file_bytes, actual_file.content_type or "", job_text, model, temperature)
