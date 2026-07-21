from typing import Any

from pydantic import BaseModel


class PdfExportRequest(BaseModel):
    html: str
    filename: str = "anchorcv-export.pdf"


class DocxExportRequest(BaseModel):
    html: str | None = None
    cv_data: dict[str, Any] | None = None
    filename: str = "anchorcv-export.docx"
