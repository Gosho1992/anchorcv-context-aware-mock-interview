"""
World-class CV templates: gallery, convert, and compare.

Each template encodes the real structural conventions of a target format
(World Bank, ADB, immigration, legal, executive). ``/convert`` restructures an
uploaded CV into the chosen format; ``/compare`` scores the CV against the
format's standards and returns a gap report.
"""
import json
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.deps.auth import get_current_user, require_active_access
from app.services.llm import get_routed_client, resolve_model

router = APIRouter(prefix="/templates", tags=["templates"])
logger = logging.getLogger(__name__)

MAX_RESUME_CHARS = 12000

TEMPLATES = {
    "world_bank": {
        "id": "world_bank",
        "name": "World Bank CV",
        "tagline": "For World Bank Group, IFC, and MIGA applications",
        "audience": "Development professionals, economists, sector specialists",
        "sections": [
            "Personal Information (name, nationality, languages)",
            "Education (degrees with institutions and years)",
            "Employment Record (reverse chronological, with employer, title, dates, and duty station)",
            "Detailed Description of Assignments (project name, client, role, key achievements)",
            "Countries of Work Experience",
            "Languages (speaking / reading / writing proficiency)",
            "Certifications & Memberships",
        ],
        "standards": [
            "Third-person, factual, achievement-oriented tone — no marketing language",
            "Every assignment names the client/funder (e.g. World Bank, ADB, EU, USAID)",
            "Quantified outcomes: budgets managed, loans supervised, beneficiaries reached",
            "Explicit country and regional experience — this is heavily weighted",
            "Language proficiencies stated per skill (speak/read/write)",
            "Typically 3-6 pages; completeness beats brevity",
        ],
        "example_note": "Assignment entries read like: 'Team Leader, Public Financial Management Reform (World Bank, $12M IPF, Ghana, 2021-2023): led a team of 8 specialists; achieved 94% disbursement rate.'",
    },
    "adb": {
        "id": "adb",
        "name": "ADB Consultant CV",
        "tagline": "For Asian Development Bank consultant and staff rosters (CMS format)",
        "audience": "Consultants and specialists targeting ADB-financed projects",
        "sections": [
            "Proposed Position & Expertise Summary",
            "Personal Data (nationality, date of birth, languages)",
            "Education & Training",
            "Employment Record (firm, position, dates)",
            "Work Undertaken that Best Illustrates Capability to Handle the Assignment",
            "Countries of Work Experience",
            "Certifications",
        ],
        "standards": [
            "Mirrors ADB's Consultant Management System (CMS) field structure",
            "The 'Work Undertaken' section is decisive — pick 4-8 assignments most relevant to the target TOR",
            "Each assignment: project name, funder, location, year, position, and activities performed",
            "Asia-Pacific experience highlighted explicitly",
            "Factual, terse, third person; no adjectives without evidence",
        ],
        "example_note": "ADB evaluators score CVs against the TOR line-by-line; generic CVs lose to targeted ones with matching assignment evidence.",
    },
    "immigration": {
        "id": "immigration",
        "name": "Immigration / Visa CV",
        "tagline": "For skilled-migration, Global Talent, and points-based visa applications",
        "audience": "Applicants for UK Global Talent, EB-1/EB-2 NIW, Express Entry, EU Blue Card",
        "sections": [
            "Personal Details (full legal name matching passport, nationality)",
            "Professional Summary (aligned to the target occupation code)",
            "Employment History (exact dates month/year, employer, job title, hours per week)",
            "Education & Credential Equivalency (degrees with dates and awarding bodies)",
            "Evidence of Achievements (awards, publications, media, salary evidence)",
            "Licenses & Professional Registrations",
            "References / Verifiable Contacts",
        ],
        "standards": [
            "Zero gaps: every month between jobs is accounted for — case officers flag gaps",
            "Job titles and duties phrased to match the target occupation classification (SOC/ANZSCO/NOC)",
            "No exaggeration — every claim must be supportable with documentary evidence",
            "Exact employment dates (month + year), employer addresses, working hours",
            "Achievements framed as verifiable facts (award names, publication DOIs, press links)",
        ],
        "example_note": "Immigration CVs are evidence documents, not marketing documents. Consistency with reference letters and payslips is what wins.",
    },
    "legal": {
        "id": "legal",
        "name": "Lawyer / Legal CV",
        "tagline": "For law firms, in-house counsel, clerkships, and international courts",
        "audience": "Attorneys, legal counsel, judicial clerks, compliance officers",
        "sections": [
            "Header (name, bar admissions, contact)",
            "Education (law school with honors, journal membership, class rank if strong)",
            "Bar Admissions & Court Admissions",
            "Legal Experience (matters handled, deal sizes, case outcomes)",
            "Publications & Speaking Engagements",
            "Professional Associations",
            "Languages",
        ],
        "standards": [
            "Education near the top for juniors; experience first after ~5 years",
            "Matter descriptions: practice area, deal/case value, your specific role, outcome",
            "Confidentiality-safe phrasing ('a Fortune 500 pharmaceutical client'), never client names without consent",
            "Precise legal terminology; zero typos — a single error is disqualifying in legal hiring",
            "One to two pages for firms; longer academic-style CVs only for judicial/academic roles",
        ],
        "example_note": "Strong entries read like: 'Second-chaired a $240M cross-border acquisition; drafted and negotiated the SPA and disclosure schedules.'",
    },
    "executive": {
        "id": "executive",
        "name": "Executive CV",
        "tagline": "For C-suite, VP, and board-level applications",
        "audience": "Senior leaders targeting executive search firms and boards",
        "sections": [
            "Executive Summary (3-4 lines of positioning, not objectives)",
            "Career Highlights (3-5 signature achievements with numbers)",
            "Professional Experience (scope first: P&L, team size, geography — then achievements)",
            "Board Memberships & Advisory Roles",
            "Education & Executive Development",
            "Speaking, Media & Thought Leadership",
        ],
        "standards": [
            "Scope before achievements: revenue responsibility, budget, headcount, markets",
            "Every bullet leads with a business outcome: growth %, margin, exits, turnarounds",
            "Strategic language (transformation, market entry, M&A) backed by hard numbers",
            "Two pages maximum; ruthless prioritization of the last 10-15 years",
            "No task descriptions — executives are hired for outcomes, not duties",
        ],
        "example_note": "A strong highlight: 'Scaled ARR from $18M to $94M in 3 years; led Series C ($60M) and expansion into 4 APAC markets.'",
    },
}


def _template_or_404(template_id: str) -> dict:
    template = TEMPLATES.get((template_id or "").strip().lower())
    if not template:
        raise HTTPException(status_code=404, detail="Unknown template.")
    return template


def _extract_cv_text(file_bytes: bytes, content_type: str) -> str:
    from app.services.legacy_bridge import _truncate_text, extract_clean_resume_text

    text = extract_clean_resume_text(file_bytes, content_type)
    if not (text or "").strip():
        raise HTTPException(
            status_code=422,
            detail="Could not extract text from this CV. Try PDF, DOCX, or TXT.",
        )
    return _truncate_text(text, MAX_RESUME_CHARS)


@router.get("")
@router.get("/")
def list_templates(user: dict = Depends(get_current_user)):
    return {"templates": list(TEMPLATES.values())}


def _format_spec(template: dict) -> str:
    sections = "\n".join(f"- {s}" for s in template["sections"])
    standards = "\n".join(f"- {s}" for s in template["standards"])
    return (
        f"TARGET FORMAT: {template['name']} — {template['tagline']}\n\n"
        f"REQUIRED SECTION STRUCTURE (in this order):\n{sections}\n\n"
        f"FORMAT STANDARDS:\n{standards}\n\n"
        f"NOTE: {template['example_note']}"
    )


@router.post("/convert")
async def convert_to_template(
    file: UploadFile = File(...),
    template_id: str = Form(...),
    model: str = Form(default=""),
    target_role: str = Form(default=""),
    user: dict = Depends(require_active_access),
):
    template = _template_or_404(template_id)
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="CV file is required.")
    cv_text = _extract_cv_text(file_bytes, file.content_type or "")

    system = (
        "You are an elite CV writer who specializes in institutional formats. "
        "Restructure the candidate's CV into the target format below.\n\n"
        + _format_spec(template)
        + "\n\nHARD RULES:\n"
        "- Use ONLY facts present in the candidate's CV. Never invent employers, "
        "dates, degrees, numbers, or achievements.\n"
        "- If a required section has no supporting material, include the section "
        "header with the line '[No information provided — add details here]'.\n"
        "- Where the format expects details the CV lacks (e.g. client names, "
        "working hours), insert a clearly marked placeholder like [ADD: client name].\n"
        "- Output clean semantic HTML only (h1, h2, h3, p, ul, li, strong). "
        "No <html>/<head>/<body> wrapper, no markdown, no commentary."
    )
    user_prompt = (
        (f"Target role/position: {target_role.strip()}\n\n" if target_role.strip() else "")
        + f"=== CANDIDATE CV ===\n{cv_text}"
    )

    client = get_routed_client()
    try:
        response = client.chat.completions.create(
            model=resolve_model(model),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.4,
            max_tokens=4096,
        )
        html = (response.choices[0].message.content or "").strip()
    except Exception as exc:
        logger.exception("Template conversion failed: %s", exc)
        raise HTTPException(
            status_code=502, detail="Template conversion is temporarily unavailable."
        ) from exc

    if html.startswith("```"):
        html = html.strip("`")
        if html.lower().startswith("html"):
            html = html[4:]
        html = html.strip()

    return {
        "template_id": template["id"],
        "template_name": template["name"],
        "result_html": html,
    }


def _coerce_score(value) -> int:
    try:
        return max(0, min(100, int(round(float(value)))))
    except (TypeError, ValueError):
        return 0


@router.post("/compare")
async def compare_to_template(
    file: UploadFile = File(...),
    template_id: str = Form(...),
    model: str = Form(default=""),
    user: dict = Depends(require_active_access),
):
    template = _template_or_404(template_id)
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="CV file is required.")
    cv_text = _extract_cv_text(file_bytes, file.content_type or "")

    system = (
        "You are a strict CV assessor for institutional hiring. Score the "
        "candidate's CV against the target format's standards.\n\n"
        + _format_spec(template)
        + "\n\nReturn ONLY a valid JSON object with exactly these keys:\n"
        "{\n"
        '  "overall_score": 0-100,\n'
        '  "section_scores": [{"section": "name", "score": 0-100, "comment": "one sentence"}],\n'
        '  "strengths": ["specific strength grounded in the CV"],\n'
        '  "gaps": ["specific missing element the format expects"],\n'
        '  "recommendations": ["concrete, actionable fix the candidate can make"]\n'
        "}\n"
        "Score each required section of the format. Be honest: a generic CV "
        "should score 40-60 against a specialized format. 3-6 items per list."
    )

    client = get_routed_client()
    try:
        response = client.chat.completions.create(
            model=resolve_model(model),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"=== CANDIDATE CV ===\n{cv_text}"},
            ],
            temperature=0.2,
            max_tokens=2000,
            response_format={"type": "json_object"},
        )
        raw = (response.choices[0].message.content or "{}").strip()
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("Template comparison returned unparseable JSON: %s", exc)
        raise HTTPException(
            status_code=502, detail="Comparison returned an unexpected response. Try again."
        ) from exc
    except Exception as exc:
        logger.exception("Template comparison failed: %s", exc)
        raise HTTPException(
            status_code=502, detail="Template comparison is temporarily unavailable."
        ) from exc

    return {
        "template_id": template["id"],
        "template_name": template["name"],
        "overall_score": _coerce_score(data.get("overall_score")),
        "section_scores": [
            {
                "section": str(item.get("section") or ""),
                "score": _coerce_score(item.get("score")),
                "comment": str(item.get("comment") or ""),
            }
            for item in (data.get("section_scores") or [])
            if isinstance(item, dict)
        ],
        "strengths": [str(s) for s in (data.get("strengths") or [])][:8],
        "gaps": [str(s) for s in (data.get("gaps") or [])][:8],
        "recommendations": [str(s) for s in (data.get("recommendations") or [])][:8],
    }
