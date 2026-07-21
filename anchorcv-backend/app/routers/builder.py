from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.deps.auth import require_active_access
from app.services.legacy_bridge import build_cv, parse_sections_json

router = APIRouter(tags=["builder"])


@router.post("/build-cv")
async def build_cv_route(
    file: UploadFile | None = File(default=None),
    target: str = Form(default=""),
    format: str = Form(alias="format", default=""),
    tone: str = Form(default="Professional"),
    language: str = Form(default="English"),
    length: str = Form(default="Full"),
    color_theme: str = Form(default="#1e40af"),
    sections: str = Form(default=""),
    enhance: bool = Form(default=True),
    model: str = Form(default="gpt-4o-mini"),
    temperature: float = Form(default=0.7),
    user=Depends(require_active_access),
):
    if file is None:
        raise HTTPException(status_code=400, detail="Resume file is required.")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Resume file is required.")
    if not format.strip():
        raise HTTPException(status_code=400, detail="CV format is required.")

    return build_cv(
        file_bytes=file_bytes,
        content_type=file.content_type or "",
        target=target,
        cv_format=format,
        tone=tone,
        language=language,
        length=length,
        color_theme=color_theme,
        sections=parse_sections_json(sections),
        enhance=enhance,
        model=model,
        temperature=temperature,
    )
