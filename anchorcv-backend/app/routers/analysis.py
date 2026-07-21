from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from app.deps.auth import require_active_access
from app.services.legacy_bridge import analyze_resume

router = APIRouter(tags=["analysis"])


@router.post("/analyse")
async def analyse(
    file: UploadFile = File(...),
    requirement_text: str = Form(default=""),
    output_type: str = Form(default="Application_Strategy"),
    model: str = Form(default="gpt-4o-mini"),
    temperature: float = Form(default=0.7),
    requirement_file: UploadFile | None = File(default=None),
    user=Depends(require_active_access),
):
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Resume file is required.")

    requirement_file_bytes = await requirement_file.read() if requirement_file else None
    result = analyze_resume(
        file_bytes,
        file.content_type or "",
        requirement_text,
        output_type,
        model,
        temperature,
        requirement_file_bytes=requirement_file_bytes,
        requirement_file_content_type=(requirement_file.content_type or "") if requirement_file else "",
    )
    return JSONResponse(content=result, headers={"Content-Type": "application/json; charset=utf-8"})
