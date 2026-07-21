"""
ATS Shield — Orchestrator.

run_ats_simulation() ties together the deterministic components (keywords,
formatting, experience, education) plus the LLM improvement generator, and
computes a single weighted ATS score:

    overall = 40% keywords + 25% formatting + 20% experience + 15% education

No new dependencies, no ML. CV text comes from the existing
anchor_core.extract_text_from_file.
"""

import logging
import re
import sys
from typing import Dict, List

from app.config import WORKSPACE_ROOT

# anchor_core lives at the workspace root (alongside anchor_shared); make sure
# it is importable exactly like legacy_bridge does.
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

import anchor_core  # noqa: E402

from app.services import ats_keywords, ats_parser, ats_experience, ats_llm  # noqa: E402

logger = logging.getLogger(__name__)

# Score weights (must sum to 1.0).
W_KEYWORDS = 0.40
W_FORMATTING = 0.25
W_EXPERIENCE = 0.20
W_EDUCATION = 0.15

_SEVERITY_PENALTY = {"high": 18, "medium": 10, "low": 5}

# Highest-degree detection (ordered, most senior first).
_DEGREE_PATTERNS = [
    (r"\b(ph\.?d|doctorate|doctoral|d\.phil)\b", 100, "Doctorate"),
    (r"\b(m\.?b\.?a|master|m\.?sc|m\.?s\b|m\.?eng|m\.?a\b|m\.?tech|postgraduate)\b", 90, "Master's"),
    (r"\b(bachelor|b\.?sc|b\.?s\b|b\.?eng|b\.?a\b|b\.?tech|b\.?e\b|undergraduate)\b", 80, "Bachelor's"),
    (r"\b(associate|a\.?a\b|a\.?s\b)\b", 60, "Associate"),
    (r"\b(diploma|certificate|certification)\b", 55, "Diploma/Certificate"),
    (r"\b(university|college|institute of technology)\b", 50, "Institution mentioned"),
]


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _status_for_score(score: float) -> str:
    if score >= 80:
        return "Excellent — ATS-friendly"
    if score >= 65:
        return "Good — minor improvements"
    if score >= 45:
        return "Needs work"
    return "Poor — likely to be filtered"


def _score_formatting(issues: List[Dict]) -> float:
    penalty = sum(_SEVERITY_PENALTY.get(i.get("severity", "low"), 5) for i in issues)
    return round(_clamp(100 - penalty), 1)


def _score_experience(exp: Dict) -> float:
    if exp.get("job_count", 0) == 0:
        return 30.0  # No parseable dates — cannot verify experience.
    years = float(exp.get("total_years", 0.0))
    # 8+ years of verifiable experience caps the years component at 100.
    score = min(100.0, years * 12.5)
    # Penalize employment gaps and very short average tenure (job hopping).
    score -= min(len(exp.get("gaps", [])) * 8, 24)
    if 0 < float(exp.get("avg_tenure", 0.0)) < 1.0:
        score -= 10
    return round(_clamp(score), 1)


def _score_education(resume_text: str, jd_text: str) -> Dict:
    resume_lower = (resume_text or "").lower()
    best_score = 0
    best_label = "None detected"
    for pattern, value, label in _DEGREE_PATTERNS:
        if re.search(pattern, resume_lower):
            if value > best_score:
                best_score = value
                best_label = label
    if best_score == 0:
        best_score = 30  # Neutral-low when nothing recognizable is present.
    jd_requires_degree = bool(
        re.search(r"\b(degree|bachelor|master|ph\.?d|b\.?sc|m\.?sc|graduate)\b", (jd_text or "").lower())
    )
    return {"score": float(best_score), "highest_degree": best_label, "jd_requires_degree": jd_requires_degree}


def run_ats_simulation(file_bytes: bytes, content_type: str, job_description: str) -> Dict:
    """
    Run the full ATS simulation and return a dict that maps onto
    ATSSimulateResponse.
    """
    # 1. Extract CV text using the existing parser.
    try:
        resume_text = anchor_core.extract_text_from_file(file_bytes, content_type or "")
        if isinstance(resume_text, bytes):
            resume_text = resume_text.decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        logger.exception("ATS Shield: text extraction failed: %s", exc)
        resume_text = ""

    job_description = job_description or ""

    # 2. Keywords (deterministic).
    jd_keywords = ats_keywords.extract_keywords_deterministic(job_description)
    keyword_result = ats_keywords.compare_keywords(jd_keywords, resume_text)
    if jd_keywords:
        keyword_score = float(keyword_result["match_percentage"])
    else:
        keyword_score = 50.0  # No recognizable required skills in the JD.

    # 3. Formatting linter.
    formatting_issues = ats_parser.detect_formatting_issues(resume_text)
    formatting_score = _score_formatting(formatting_issues)

    # 4. Experience.
    date_ranges = ats_experience.extract_dates(resume_text)
    experience = ats_experience.calculate_experience(date_ranges)
    experience_score = _score_experience(experience)

    # 5. Education.
    education = _score_education(resume_text, job_description)
    education_score = education["score"]

    sub_scores = {
        "keyword": round(keyword_score, 1),
        "formatting": round(formatting_score, 1),
        "experience": round(experience_score, 1),
        "education": round(education_score, 1),
    }

    # 6. Weighted overall score.
    overall = (
        W_KEYWORDS * keyword_score
        + W_FORMATTING * formatting_score
        + W_EXPERIENCE * experience_score
        + W_EDUCATION * education_score
    )
    overall = round(_clamp(overall), 1)
    status = _status_for_score(overall)

    # 7. LLM improvements (truthful BEFORE/AFTER, prompt-injection guarded).
    improvements = ats_llm.generate_improvements(
        resume_text,
        job_description,
        missing_keywords=keyword_result.get("missing", []),
        formatting_issues=formatting_issues,
    )

    # 8. Estimated optimized score — closing most of the keyword & formatting
    #    gap (which the user can realistically fix). Experience/education are
    #    left unchanged because they cannot be honestly fabricated.
    opt_keyword = min(100.0, keyword_score + (100.0 - keyword_score) * 0.7)
    opt_formatting = min(100.0, formatting_score + (100.0 - formatting_score) * 0.85)
    optimized = (
        W_KEYWORDS * opt_keyword
        + W_FORMATTING * opt_formatting
        + W_EXPERIENCE * experience_score
        + W_EDUCATION * education_score
    )
    optimized_score = round(_clamp(max(optimized, overall)), 1)

    return {
        "score": overall,
        "status": status,
        "sub_scores": sub_scores,
        "keywords": {
            "present": keyword_result.get("present", []),
            "missing": keyword_result.get("missing", []),
            "partial": keyword_result.get("partial", []),
            "match_percentage": keyword_result.get("match_percentage", 0.0),
            "total_required": keyword_result.get("total_required", 0),
        },
        "formatting_issues": formatting_issues,
        "experience": experience,
        "education": education,
        "improvements": improvements,
        "optimized_score": optimized_score,
    }
