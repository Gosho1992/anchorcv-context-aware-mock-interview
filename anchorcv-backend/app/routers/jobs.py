import asyncio
import logging
import json
import re
from typing import List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.deps.auth import require_active_access
from app.services.job_search import (
    build_query,
    search_jobs as search_jobs_service,
    search_jobs_serper,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])
logger = logging.getLogger(__name__)

_VALID_EXPERIENCE_LEVELS = {"entry", "mid", "senior"}
_VALID_POSTED_WITHIN = {"24h", "3d", "7d"}

# ── Anthropic (Claude) config ────────────────────────────────────────────────
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
ANTHROPIC_MODEL = "claude-sonnet-4-6"
ANTHROPIC_MAX_TOKENS = 2000

_VALID_DOCUMENT_TYPES = {"cover_letter", "resume"}
_MAX_CV_CHARS = 12000
_MAX_JD_CHARS = 8000


class JobSearchRequest(BaseModel):
    job_title: str = Field(..., min_length=2, max_length=200)
    country: Optional[str] = Field(default=None, max_length=100)
    experience_level: Optional[str] = None
    posted_within: Optional[str] = None
    salary_min: Optional[int] = Field(default=None, ge=0)


class JobResult(BaseModel):
    title: str
    company: str
    url: str
    snippet: str
    location: str
    posted_at: Optional[str] = None
    salary: Optional[str] = None
    source: str


class JobSearchResponse(BaseModel):
    jobs: List[JobResult]
    count: int
    query: str


@router.post("/search", response_model=JobSearchResponse)
async def search_jobs(
    payload: JobSearchRequest,
    user: dict = Depends(require_active_access),
):
    job_title = payload.job_title.strip()
    if len(job_title) < 2:
        raise HTTPException(status_code=400, detail="job_title is required.")

    # Unrecognized enum-like values are dropped rather than rejected, so a
    # stale frontend build can't 400 a user over an unexpected filter value.
    experience_level = (
        payload.experience_level if payload.experience_level in _VALID_EXPERIENCE_LEVELS else None
    )
    posted_within = (
        payload.posted_within if payload.posted_within in _VALID_POSTED_WITHIN else None
    )

    try:
        adzuna_result, serper_result = await asyncio.gather(
            search_jobs_service(
                job_title=job_title,
                country=payload.country,
                experience_level=experience_level,
                posted_within=posted_within,
                salary_min=payload.salary_min,
            ),
            search_jobs_serper(
                job_title=job_title,
                country=payload.country,
                posted_within=posted_within,
            ),
            return_exceptions=True,
        )
    except Exception as exc:
        logger.exception("Job search failed for job_title=%s: %s", job_title, exc)
        raise HTTPException(status_code=502, detail="Job search is temporarily unavailable.") from exc

    if isinstance(adzuna_result, ValueError):
        raise HTTPException(status_code=400, detail=str(adzuna_result)) from adzuna_result

    adzuna_jobs: list[dict] = []
    if isinstance(adzuna_result, RuntimeError):
        # Missing/misconfigured Adzuna app_id/app_key - degrade to Serper-only
        # results rather than failing the whole request outright.
        logger.error("Adzuna search misconfigured: %s", adzuna_result)
    elif isinstance(adzuna_result, Exception):
        logger.exception("Adzuna search failed for job_title=%s: %s", job_title, adzuna_result)
    else:
        adzuna_jobs = adzuna_result

    serper_jobs: list[dict] = []
    if isinstance(serper_result, Exception):
        logger.warning("Serper job search failed for job_title=%s: %s", job_title, serper_result)
    else:
        serper_jobs = serper_result

    # Merge + dedupe by URL, Adzuna results first, capped at 30 total.
    seen_urls: set[str] = set()
    merged_jobs: list[dict] = []
    for job in [*adzuna_jobs, *serper_jobs]:
        url = job.get("url") or ""
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        merged_jobs.append(job)
    jobs = merged_jobs[:30]

    query = build_query(job_title, payload.country, experience_level)

    return JobSearchResponse(jobs=jobs, count=len(jobs), query=query)


# ── Document generation (cover letter / tailored resume) ─────────────────────


class GenerateDocumentRequest(BaseModel):
    cv_text: str = Field(..., min_length=1)
    job_title: str = Field(..., min_length=1, max_length=200)
    company_name: Optional[str] = Field(default="", max_length=200)
    location: Optional[str] = Field(default="", max_length=200)
    salary: Optional[str] = Field(default="", max_length=120)
    job_description: Optional[str] = Field(default="")
    document_type: str = Field(..., description="cover_letter or resume")


class GenerateDocumentResponse(BaseModel):
    document: str
    document_type: str
    applicant_level: str
    experience_level: str
    required_skills: List[str]
    key_responsibilities: List[str]


# Vocabulary used to spot concrete skills inside free-text job descriptions.
# Kept broad on purpose so the regex pass works across tech, business, and
# engineering postings without an LLM round-trip.
_SKILL_VOCABULARY = [
    "python", "java", "javascript", "typescript", "c\\+\\+", "c#", "go", "golang",
    "rust", "ruby", "php", "scala", "kotlin", "swift", "r", "matlab", "sql", "nosql",
    "react", "angular", "vue", "node\\.js", "node", "django", "flask", "fastapi",
    "spring", "\\.net", "express", "next\\.js", "tailwind",
    "aws", "azure", "gcp", "google cloud", "docker", "kubernetes", "terraform",
    "ci/cd", "jenkins", "git", "linux", "graphql", "rest", "microservices",
    "postgresql", "postgres", "mysql", "mongodb", "redis", "elasticsearch", "kafka",
    "spark", "hadoop", "airflow", "snowflake", "databricks", "tableau", "power bi",
    "excel", "pandas", "numpy", "pytorch", "tensorflow", "scikit-learn", "keras",
    "machine learning", "deep learning", "nlp", "computer vision", "data analysis",
    "data engineering", "etl", "statistics", "a/b testing",
    "agile", "scrum", "jira", "project management", "stakeholder management",
    "communication", "leadership", "problem solving", "salesforce", "sap",
    "figma", "ux", "ui", "seo", "marketing", "accounting", "finance",
    "autocad", "solidworks", "matlab", "plc", "cad", "fea", "ansys",
]

_RESPONSIBILITY_HEADINGS = re.compile(
    r"(responsibilities|what you('|’)?ll do|the role|duties|day[- ]to[- ]day|you will|key tasks)",
    re.IGNORECASE,
)
_REQUIREMENT_HEADINGS = re.compile(
    r"(requirements|qualifications|what we('|’)?re looking for|skills|must have|you have|about you)",
    re.IGNORECASE,
)


def _extract_required_skills(job_description: str) -> List[str]:
    """Match a known skill vocabulary against the JD text (case-insensitive)."""
    if not job_description:
        return []
    text = job_description.lower()
    found: List[str] = []
    seen: set[str] = set()
    for pattern in _SKILL_VOCABULARY:
        # \b doesn't play well with symbols like c++/.net, so guard with
        # non-word boundaries where the term starts/ends with a symbol.
        regex = rf"(?<![a-z0-9]){pattern}(?![a-z0-9])"
        try:
            if re.search(regex, text):
                label = pattern.replace("\\", "")
                key = label.lower()
                if key not in seen:
                    seen.add(key)
                    found.append(label)
        except re.error:
            continue
    return found[:20]


def _extract_experience_level(job_description: str) -> str:
    """Infer the seniority a JD is asking for, from years + seniority words."""
    if not job_description:
        return "unspecified"
    text = job_description.lower()

    years_match = re.search(r"(\d{1,2})\s*\+?\s*(?:years|yrs)", text)
    years = int(years_match.group(1)) if years_match else None

    if re.search(r"\b(lead|principal|staff|head of|director|vp|manager)\b", text):
        return "lead/management"
    if re.search(r"\b(senior|sr\.?|expert)\b", text) or (years is not None and years >= 5):
        return "senior"
    if re.search(r"\b(mid[- ]level|intermediate)\b", text) or (years is not None and 2 <= years < 5):
        return "mid"
    if re.search(r"\b(junior|jr\.?|entry[- ]level|graduate|intern|trainee)\b", text) or (
        years is not None and years < 2
    ):
        return "entry"
    return "unspecified"


def _extract_key_responsibilities(job_description: str) -> List[str]:
    """Pull bullet-like lines, preferring those under a responsibilities heading."""
    if not job_description:
        return []

    lines = [ln.strip() for ln in re.split(r"[\r\n]+", job_description) if ln.strip()]

    bullets: List[str] = []
    capturing = False
    for line in lines:
        if _RESPONSIBILITY_HEADINGS.search(line) and len(line) < 80:
            capturing = True
            continue
        if _REQUIREMENT_HEADINGS.search(line) and len(line) < 80:
            capturing = False
            continue
        is_bullet = bool(re.match(r"^[\-\*•‣◦⁃∙•·]|\d+[.)]", line))
        if (capturing or is_bullet) and len(line) > 12:
            cleaned = re.sub(r"^[\-\*•‣◦⁃∙•·\d.)\s]+", "", line).strip()
            if cleaned:
                bullets.append(cleaned[:200])

    if not bullets:
        # Fall back to the first few sentences so the prompt still has signal.
        sentences = re.split(r"(?<=[.!?])\s+", job_description)
        bullets = [s.strip() for s in sentences if len(s.strip()) > 30][:5]

    return bullets[:8]


def _detect_applicant_level(cv_text: str) -> str:
    """Estimate the candidate's seniority from their CV text."""
    if not cv_text:
        return "unspecified"
    text = cv_text.lower()

    years_match = re.search(r"(\d{1,2})\s*\+?\s*(?:years|yrs)\s+(?:of\s+)?experience", text)
    years = int(years_match.group(1)) if years_match else None

    if re.search(r"\b(chief|vp|vice president|head of|director|principal|staff engineer)\b", text):
        return "leadership"
    if re.search(r"\b(senior|sr\.?|lead)\b", text) or (years is not None and years >= 5):
        return "senior"
    if years is not None and 2 <= years < 5:
        return "mid"
    if re.search(r"\b(intern|graduate|trainee|entry[- ]level|recent graduate)\b", text) or (
        years is not None and years < 2
    ):
        return "entry"
    return "mid"


def _build_prompt(payload: GenerateDocumentRequest, skills, exp_level, responsibilities, applicant_level):
    cv_text = payload.cv_text.strip()[:_MAX_CV_CHARS]
    jd_text = (payload.job_description or "").strip()[:_MAX_JD_CHARS]
    company = (payload.company_name or "").strip() or "the company"
    location = (payload.location or "").strip()
    salary = (payload.salary or "").strip()

    skills_line = ", ".join(skills) if skills else "not explicitly listed — infer from the description"
    resp_block = "\n".join(f"- {r}" for r in responsibilities) if responsibilities else "- (see job description)"

    context = (
        f"POSITION: {payload.job_title}\n"
        f"COMPANY: {company}\n"
        f"LOCATION: {location or 'not specified'}\n"
        f"SALARY: {salary or 'not specified'}\n"
        f"SENIORITY THE ROLE TARGETS: {exp_level}\n"
        f"REQUIRED / DESIRED SKILLS: {skills_line}\n"
        f"KEY RESPONSIBILITIES:\n{resp_block}\n\n"
        f"FULL JOB DESCRIPTION:\n{jd_text or '(none provided)'}\n\n"
        f"CANDIDATE SENIORITY (from CV): {applicant_level}\n"
        f"CANDIDATE CV:\n{cv_text}\n"
    )

    if payload.document_type == "cover_letter":
        system = (
            "You are an expert cover letter writer. You write specific, human cover letters that "
            "would never be flagged as generic AI output. You connect the candidate's real, concrete "
            "achievements to the exact role and company. No clichés, no 'I am writing to express my "
            "interest', no invented facts."
        )
        instruction = (
            f"Write a tailored cover letter for the candidate applying to the {payload.job_title} role "
            f"at {company}"
            + (f" in {location}" if location else "")
            + ".\n\n"
            "Hard requirements:\n"
            f"- Address {company} by name and reference the specific position.\n"
            "- Map the candidate's ACTUAL achievements and experience (from the CV) to the role's "
            "required skills and responsibilities listed above. Cite real numbers/results when present.\n"
            "- Reflect the candidate's seniority level appropriately.\n"
            "- 3–4 concise paragraphs. Professional, warm, confident — not boastful.\n"
            "- Do NOT fabricate experience the candidate doesn't have.\n"
            "- Output only the cover letter body text (greeting through sign-off). No commentary."
        )
    else:  # resume
        system = (
            "You are an expert resume writer and ATS optimization specialist. You rewrite resumes to "
            "target a specific role using strong action verbs, quantified impact, and the role's "
            "keywords — without inventing experience the candidate does not have."
        )
        instruction = (
            f"Rewrite and tailor the candidate's resume for the {payload.job_title} role at {company}.\n\n"
            "Reference the candidate's existing CV structure and content below — preserve their real "
            "name, contact details, roles, employers, dates, and education, then reframe them for this role.\n\n"
            "FORMAT — produce a clean, scannable, well-spaced resume that renders well as a PDF, "
            "matching the quality of a polished professional CV (clean, scannable, well-spaced):\n"
            "- LINE 1: the candidate's full name in bold ALL CAPS, e.g. **JOHN SMITH**.\n"
            "- LINE 2: contact details on one line separated by ' | ' (email, phone, location, and "
            "LinkedIn/portfolio if present). Use only details found in the CV.\n"
            "- Each section starts with an ALL-CAPS header on its own line, immediately followed by a "
            "separator line of em-dashes, for example:\nPROFESSIONAL SUMMARY\n────────────────────────────\n"
            "- Section order: PROFESSIONAL SUMMARY, SKILLS, EXPERIENCE, EDUCATION "
            "(add PROJECTS or CERTIFICATIONS only if the CV contains them).\n"
            "- Leave one blank line between every section for clean spacing.\n"
            "- Start every bullet point with the '▸ ' symbol.\n"
            "- PROFESSIONAL SUMMARY: 2–3 sentences positioning the candidate for this exact role.\n"
            "- SKILLS: grouped, scannable bullets prioritising the role's required skills the candidate "
            "genuinely has.\n"
            "- EXPERIENCE: for each role put 'Job Title — Company | Location | Dates' on one line, then "
            "3–5 '▸ ' bullets using strong action verbs and quantified impact.\n"
            "- EDUCATION: degree, institution, and dates.\n\n"
            "Hard requirements:\n"
            "- Weave in the role's keywords/skills naturally where the candidate genuinely has them "
            "(ATS optimization). Do not claim skills or experience not supported by the CV.\n"
            "- Keep it truthful to the candidate's actual background and seniority.\n"
            "- Output only the tailored resume. No commentary and no markdown code fences."
        )

    return system, f"{instruction}\n\n=== APPLICATION CONTEXT ===\n{context}"


async def _call_claude(system: str, user_prompt: str) -> str:
    api_key = settings.anthropic_api_key
    if not api_key:
        raise RuntimeError("Anthropic API is not configured (missing ANTHROPIC_API_KEY).")

    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    body = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": ANTHROPIC_MAX_TOKENS,
        "system": system,
        "messages": [{"role": "user", "content": user_prompt}],
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(ANTHROPIC_API_URL, headers=headers, json=body)
        response.raise_for_status()
        data = response.json()

    # Anthropic Messages API returns content as a list of blocks.
    parts = [
        block.get("text", "")
        for block in data.get("content", [])
        if block.get("type") == "text"
    ]
    text = "".join(parts).strip()
    if not text:
        raise ValueError("Claude returned an empty response.")
    return text


@router.post("/generate-document", response_model=GenerateDocumentResponse)
async def generate_document(
    payload: GenerateDocumentRequest,
    user: dict = Depends(require_active_access),
):
    document_type = (payload.document_type or "").strip().lower()
    if document_type not in _VALID_DOCUMENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail="document_type must be 'cover_letter' or 'resume'.",
        )
    payload.document_type = document_type

    if not payload.cv_text.strip():
        raise HTTPException(status_code=400, detail="cv_text is required.")

    # 1) Regex pass over the job description.
    required_skills = _extract_required_skills(payload.job_description or "")
    experience_level = _extract_experience_level(payload.job_description or "")
    responsibilities = _extract_key_responsibilities(payload.job_description or "")

    # 2) Applicant level from the CV.
    applicant_level = _detect_applicant_level(payload.cv_text)

    # 3) Build the prompt and call Claude.
    system, user_prompt = _build_prompt(
        payload, required_skills, experience_level, responsibilities, applicant_level
    )

    try:
        document = await _call_claude(system, user_prompt)
    except RuntimeError as exc:
        logger.error("Document generation misconfigured: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "Anthropic API returned %s: %s", exc.response.status_code, exc.response.text[:300]
        )
        raise HTTPException(
            status_code=502, detail="Document generation is temporarily unavailable."
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        logger.exception("Document generation failed: %s", exc)
        raise HTTPException(
            status_code=502, detail="Document generation is temporarily unavailable."
        ) from exc

    # 4) Return the generated document text + the extracted signal.
    return GenerateDocumentResponse(
        document=document,
        document_type=document_type,
        applicant_level=applicant_level,
        experience_level=experience_level,
        required_skills=required_skills,
        key_responsibilities=responsibilities,
    )


# ── Match scoring (CV ↔ job fit, scored by Claude) ──────────────────────────


class MatchScoreRequest(BaseModel):
    cv_text: str = Field(..., min_length=1)
    job_title: str = Field(default="", max_length=200)
    company_name: Optional[str] = Field(default="", max_length=200)
    job_description: Optional[str] = Field(default="")


class MatchScoreResponse(BaseModel):
    overall_score: int
    skills_match: int
    experience_match: int
    role_fit: int
    summary: str


def _coerce_score(value) -> int:
    """Clamp any model-returned value into an int in [0, 100]."""
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, n))


def _parse_score_json(raw: str) -> dict:
    """Tolerantly parse the JSON object Claude returns (handles code fences)."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    return json.loads(text)


@router.post("/match-score", response_model=MatchScoreResponse)
async def match_score(
    payload: MatchScoreRequest,
    user: dict = Depends(require_active_access),
):
    if not payload.cv_text.strip():
        raise HTTPException(status_code=400, detail="cv_text is required.")

    cv_text = payload.cv_text.strip()[:_MAX_CV_CHARS]
    jd_text = (payload.job_description or "").strip()[:_MAX_JD_CHARS]
    company = (payload.company_name or "").strip() or "the company"

    system = (
        "You are an expert technical recruiter who scores how well a candidate's CV matches a job. "
        "You judge skills match, experience match, and overall role fit, and you are calibrated and "
        "discriminating: weak matches score low, strong matches score high. Respond with JSON only."
    )
    user_prompt = (
        "Score how well the candidate below matches the job. Consider the required skills, the years "
        "and relevance of experience, and overall fit for the role and its seniority.\n\n"
        "Return ONLY a JSON object with this exact shape (integers 0-100):\n"
        '{"overall_score": <int>, "skills_match": <int>, "experience_match": <int>, '
        '"role_fit": <int>, "summary": "<one concise sentence>"}\n\n'
        f"JOB TITLE: {payload.job_title or 'not specified'}\n"
        f"COMPANY: {company}\n"
        f"JOB DESCRIPTION:\n{jd_text or '(none provided)'}\n\n"
        f"CANDIDATE CV:\n{cv_text}\n"
    )

    try:
        raw = await _call_claude(system, user_prompt)
    except RuntimeError as exc:
        logger.error("Match scoring misconfigured: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "Anthropic API returned %s for match-score: %s",
            exc.response.status_code, exc.response.text[:300],
        )
        raise HTTPException(status_code=502, detail="Match scoring is temporarily unavailable.") from exc
    except (httpx.HTTPError, ValueError) as exc:
        logger.exception("Match scoring call failed: %s", exc)
        raise HTTPException(status_code=502, detail="Match scoring is temporarily unavailable.") from exc

    try:
        data = _parse_score_json(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Match scoring returned unparseable JSON: %s | raw=%s", exc, raw[:300])
        raise HTTPException(
            status_code=502, detail="Match scoring returned an unexpected response."
        ) from exc

    return MatchScoreResponse(
        overall_score=_coerce_score(data.get("overall_score")),
        skills_match=_coerce_score(data.get("skills_match")),
        experience_match=_coerce_score(data.get("experience_match")),
        role_fit=_coerce_score(data.get("role_fit")),
        summary=str(data.get("summary") or "").strip()[:300],
    )


# ── Extract job description text from a URL ─────────────────────────────────

_MAX_EXTRACT_CHARS = 15000
_BLOCKED_HOST_PATTERNS = re.compile(
    r"^(localhost|127\.|0\.|10\.|192\.168\.|169\.254\.|172\.(1[6-9]|2\d|3[01])\.)",
    re.IGNORECASE,
)


class ExtractFromUrlRequest(BaseModel):
    url: str = Field(..., min_length=8, max_length=2000)


class ExtractFromUrlResponse(BaseModel):
    job_description: str
    source_url: str


def _html_to_text(html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "iframe", "svg"]):
        tag.decompose()

    # Prefer the <main> or <article> region when present — job boards keep
    # the posting body there and it avoids cookie banners / related links.
    region = soup.find("main") or soup.find("article") or soup.body or soup
    text = region.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines()]
    collapsed = "\n".join(line for line in lines if line)
    return collapsed[:_MAX_EXTRACT_CHARS]


@router.post("/extract-from-url", response_model=ExtractFromUrlResponse)
async def extract_from_url(
    payload: ExtractFromUrlRequest,
    user: dict = Depends(require_active_access),
):
    url = payload.url.strip()
    if not url.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="URL must start with http:// or https://.")

    host = httpx.URL(url).host or ""
    if _BLOCKED_HOST_PATTERNS.match(host):
        raise HTTPException(status_code=422, detail="This URL cannot be fetched.")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en",
    }

    try:
        async with httpx.AsyncClient(
            timeout=15.0, follow_redirects=True, max_redirects=5
        ) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"The page returned HTTP {exc.response.status_code}. Paste the text manually instead.",
        ) from exc
    except httpx.HTTPError as exc:
        logger.warning("extract-from-url fetch failed for %s: %s", url, exc)
        raise HTTPException(
            status_code=422,
            detail="Could not reach that URL. Paste the text manually instead.",
        ) from exc

    content_type = response.headers.get("content-type", "")
    if "html" not in content_type and "text" not in content_type:
        raise HTTPException(
            status_code=422,
            detail="That URL is not a readable web page. Paste the text manually instead.",
        )

    text = _html_to_text(response.text)
    if len(text.strip()) < 80:
        raise HTTPException(
            status_code=422,
            detail=(
                "Very little text could be extracted — the page may require "
                "JavaScript or a login. Paste the text manually instead."
            ),
        )

    return ExtractFromUrlResponse(job_description=text, source_url=str(response.url))
