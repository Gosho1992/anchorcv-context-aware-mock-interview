import json
import sys
from io import BytesIO
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from jinja2 import Environment

from app.config import WORKSPACE_ROOT
from app.deps.auth import get_current_user
from app.form_cv_mapper import form_to_cv_data
from app.schemas.export import DocxExportRequest, PdfExportRequest
from app.services.legacy_bridge import _MockStreamlit, _clean_cv_data, _normalize_unicode_text, _strip_empty_html_sections
from app.services.legacy_bridge import export_docx, export_pdf

if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

import anchor_core  # noqa: E402

router = APIRouter(prefix="/first-resume", tags=["first-resume"])

FIRST_RESUME_GUARDRAIL = """

CRITICAL FOR FIRST RESUME: The user wrote this content themselves from scratch.
- Enhance writing quality ONLY (grammar, clarity, action verbs, structure)
- Do NOT invent metrics, team sizes, percentages, numbers, or dates
- Do NOT add skills, languages, tools, or achievements not written by the user
- If a metric would strengthen a bullet, output "[SUGGESTED: verify this number]" as a placeholder - NEVER as plain fabricated text
- Only include languages explicitly listed by the user. Do not infer languages from the user's name, country, or education.
"""

FORMAT_MAP = {
    "ATS": "ATS-Optimized CV",
    "ATS-Optimized CV": "ATS-Optimized CV",
    "Europass": "Europass CV",
    "Europass CV": "Europass CV",
    "Academic": "Academic CV",
    "Academic CV": "Academic CV",
    "One-Page": "One-page CV",
    "One-page": "One-page CV",
    "One-page CV": "One-page CV",
}

TEMPLATE_MAP = {
    "Europass CV": "europass_template",
    "Academic CV": "academic_template",
    "One-page CV": "onepage_template",
    "ATS-Optimized CV": "ats_template",
}


def _format_date(date_str: str) -> str:
    return date_str or ""


def _render_cv_data(cv_data: anchor_core.CVData, cv_format: str) -> str:
    template_name = TEMPLATE_MAP.get(cv_format, "ats_template")
    template_path = Path(anchor_core.BASE_DIR) / "templates" / f"{template_name}.txt"
    if not template_path.exists():
        raise HTTPException(status_code=500, detail="CV template is unavailable.")

    template_str = template_path.read_text(encoding="utf-8")
    env = Environment()
    env.filters["format_date"] = _format_date

    data_dict = cv_data.model_dump() if hasattr(cv_data, "model_dump") else cv_data.dict()
    data_dict["now"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data_dict["theme_color"] = "#1e40af"
    data_dict["cv_language"] = "English"

    rendered = env.from_string(template_str).render(**data_dict)
    rendered = anchor_core._remove_empty_cv_sections(rendered)
    rendered = _normalize_unicode_text(rendered)
    rendered = _strip_empty_html_sections(rendered)
    return rendered


def _resume_text_from_form(form_data: dict[str, Any]) -> str:
    return json.dumps(form_data or {}, ensure_ascii=False, indent=2)


@router.post("/generate")
async def generate_first_resume(request: Request, user: dict = Depends(get_current_user)):
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.") from exc

    form_data = payload.get("form_data") or {}
    section_order = payload.get("section_order")
    cv_format = FORMAT_MAP.get((payload.get("format") or "ATS").strip(), "ATS-Optimized CV")
    enhance = bool(payload.get("enhance", True))

    real_streamlit = sys.modules.get("streamlit")
    original_anchor_core_st = anchor_core.st
    mock_streamlit = _MockStreamlit()
    sys.modules["streamlit"] = mock_streamlit
    anchor_core.st = mock_streamlit

    try:
        cv_data = form_to_cv_data(form_data, section_order)
        if enhance:
            cv_data = anchor_core.enhance_cv_data(
                cv_data=cv_data,
                resume_text=_resume_text_from_form(form_data),
                requirement_text="",
                mode="ai",
                system_prompt_suffix=FIRST_RESUME_GUARDRAIL,
            )
        html = _render_cv_data(cv_data, cv_format)
        cv_dict = cv_data.model_dump() if hasattr(cv_data, "model_dump") else cv_data.dict()
        return {"html": html, "cv_data": _clean_cv_data(cv_dict)}
    finally:
        anchor_core.st = original_anchor_core_st
        if real_streamlit is None:
            sys.modules.pop("streamlit", None)
        else:
            sys.modules["streamlit"] = real_streamlit


@router.post("/export/pdf")
def export_first_resume_pdf(payload: PdfExportRequest, user: dict = Depends(get_current_user)):
    pdf_result = export_pdf(payload.html)
    if isinstance(pdf_result, Response):
        pdf_result.headers["Content-Disposition"] = f'attachment; filename="{payload.filename}"'
        return pdf_result
    stream = pdf_result if isinstance(pdf_result, BytesIO) else BytesIO(pdf_result.getvalue())
    return StreamingResponse(
        stream,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{payload.filename}"'},
    )


@router.post("/export/docx")
def export_first_resume_docx(payload: DocxExportRequest, user: dict = Depends(get_current_user)):
    try:
        docx_io = export_docx(html=payload.html or "", cv_data=payload.cv_data)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"DOCX export failed: {str(exc)}. Try exporting as PDF instead.",
        ) from exc
    stream = docx_io if isinstance(docx_io, BytesIO) else BytesIO(docx_io.getvalue())
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{payload.filename}"'},
    )
