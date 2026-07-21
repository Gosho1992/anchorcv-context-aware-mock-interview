from io import BytesIO

from fastapi import APIRouter, Depends
from fastapi.responses import Response, StreamingResponse

from app.deps.auth import require_active_access
from app.schemas.export import DocxExportRequest, PdfExportRequest
from app.services.legacy_bridge import export_docx, export_pdf

router = APIRouter(prefix="/export", tags=["export"])


@router.post("/pdf")
def export_pdf_route(payload: PdfExportRequest, user=Depends(require_active_access)):
    pdf_result = export_pdf(payload.html)
    # export_pdf now returns a Response directly — pass it through,
    # overriding the filename from the payload.
    if isinstance(pdf_result, Response):
        pdf_result.headers["Content-Disposition"] = f'attachment; filename="{payload.filename}"'
        return pdf_result
    # Legacy fallback: BytesIO
    stream = pdf_result if isinstance(pdf_result, BytesIO) else BytesIO(pdf_result.getvalue())
    return StreamingResponse(
        stream,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{payload.filename}"'},
    )


@router.post("/docx")
def export_docx_route(payload: DocxExportRequest, user=Depends(require_active_access)):
    from fastapi import HTTPException
    import logging
    logger = logging.getLogger(__name__)
    try:
        docx_io = export_docx(html=payload.html or "", cv_data=payload.cv_data)
    except Exception as e:
        logger.error("DOCX export failed: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"DOCX export failed: {str(e)}. Try exporting as PDF instead."
        )
    stream = docx_io if isinstance(docx_io, BytesIO) else BytesIO(docx_io.getvalue())
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{payload.filename}"'},
    )
