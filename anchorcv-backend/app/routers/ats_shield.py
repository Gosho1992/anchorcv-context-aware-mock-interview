"""
ATS Shield router — POST /ats/simulate.

Premium-only. Accepts a CV file plus a job description, runs the deterministic
+ LLM ATS simulation, and returns a structured ATSSimulateResponse.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.deps.auth import get_current_premium_user
from app.services import ats_engine

router = APIRouter(prefix="/ats", tags=["ats-shield"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------
class SubScores(BaseModel):
    keyword: float
    formatting: float
    experience: float
    education: float


class KeywordResult(BaseModel):
    present: List[str] = []
    missing: List[str] = []
    partial: List[str] = []
    match_percentage: float = 0.0
    total_required: int = 0


class FormattingIssue(BaseModel):
    category: str
    severity: str
    description: str
    fix: str
    impact: str


class ExperienceSummary(BaseModel):
    total_years: float = 0.0
    gaps: List[dict] = []
    trajectory: str = "insufficient_data"
    job_count: int = 0
    avg_tenure: float = 0.0


class EducationSummary(BaseModel):
    score: float = 0.0
    highest_degree: str = "None detected"
    jd_requires_degree: bool = False


class Improvement(BaseModel):
    area: str
    before: str = ""
    after: str
    rationale: str = ""


class ATSSimulateResponse(BaseModel):
    score: float
    status: str
    sub_scores: SubScores
    keywords: KeywordResult
    formatting_issues: List[FormattingIssue] = []
    experience: ExperienceSummary
    education: EducationSummary
    improvements: List[Improvement] = []
    optimized_score: float


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------
@router.post("/simulate", response_model=ATSSimulateResponse)
async def simulate_ats(
    file: UploadFile = File(...),
    job_description: str = Form(default=""),
    user=Depends(get_current_premium_user),
):
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="A CV file is required.")

    if not job_description or not job_description.strip():
        raise HTTPException(status_code=400, detail="A job description is required.")

    result = ats_engine.run_ats_simulation(
        file_bytes,
        file.content_type or "",
        job_description.strip(),
    )
    return result
