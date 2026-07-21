import json
import logging
import os
import re
import openai
import sys
import types
from openai import OpenAI
from bs4 import BeautifulSoup

openai.api_key = os.getenv("OPENAI_API_KEY", "")

logger = logging.getLogger(__name__)

from app.config import WORKSPACE_ROOT

if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

import anchor_core  # noqa: E402

from app.services.llm import get_routed_client  # noqa: E402

# Route every anchor_core LLM call through the multi-provider client so
# claude-* models work across analysis, matching, and the builder without
# modifying the legacy pipeline itself.
anchor_core.init_openai_client = get_routed_client
from anchor_shared import (  # noqa: E402
    confirm_lemonsqueezy_payment,
    create_lemonsqueezy_checkout,
    db_get_user,
    db_get_user_by_email,
    db_login_user,
    db_mark_premium,
    db_register_user,
    get_lemonsqueezy_order,
    list_lemonsqueezy_orders,
    sanitize_user,
    storage_delete_by_id,
    storage_download_url,
    storage_get_record,
    storage_list,
    storage_upload,
    user_has_premium_access,
    verify_lemonsqueezy_webhook,
)
from docx_fix import build_docx_from_cv_data, create_docx_from_html  # noqa: E402

DEFAULT_MODEL = "gpt-4o-mini"
MAX_RESUME_CHARS = 12000
MAX_REQUIREMENT_CHARS = 8000


class _SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


class _MockStreamlit(types.ModuleType):
    def __init__(self):
        super().__init__("streamlit")
        self.session_state = _SessionState(
            {
                "openai_api_key": os.getenv("OPENAI_API_KEY", ""),
                "_openai_client": None,
                "_cached_api_key": None,
            }
        )
        self.secrets = {"OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", "")}

    def error(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def info(self, *args, **kwargs):
        return None

    def success(self, *args, **kwargs):
        return None


def _normalize_model(model: str | None) -> str:
    from app.services.llm import resolve_model
    return resolve_model(model)


def _truncate_text(text: str, max_chars: int) -> str:
    if not text:
        return ""
    return text.strip()[:max_chars]


def _normalize_unicode_text(text: str) -> str:
    if not text:
        return ""
    try:
        import ftfy
        return ftfy.fix_text(text)
    except Exception:
        try:
            return text.encode("latin-1").decode("utf-8")
        except (UnicodeDecodeError, UnicodeEncodeError):
            return text


def _strip_suspect_lines(text: str) -> str:
    if not text:
        return ""
    bad_markers = ("\u00C3", "\u00E2\u20AC", "\uFFFD")
    cleaned_lines = [line for line in text.splitlines() if not any(marker in line for marker in bad_markers)]
    return "\n".join(cleaned_lines)


# ── Per-output-type temperatures (prompt engineering review, April 2026) ──────
_OUTPUT_TEMPERATURES: dict[str, float] = {
    "Application_Strategy":  0.8,
    "Application Strategy":  0.8,
    "ATS_Optimization":      0.5,
    "ATS Optimization":      0.5,
    "ATS Score & Keywords":  0.5,
    "Resume_Optimization":   0.6,
    "Resume Improvement":    0.6,
    "Cover_Letter":          0.85,
    "Cover Letter":          0.85,
    "Email_Template":        0.8,
    "Email to Professor":    0.8,
}

# ── Banned phrases for cover letter quality gate ──────────────────────────────
_BANNED_CL_PHRASES: list[str] = [
    "i am writing to apply",
    "i am excited about the opportunity",
    "i believe i would be a great fit",
    "i would be a great fit",
    "thank you for considering my application",
    "i look forward to hearing from you",
    "i am thrilled",
    "i am excited to",
    "as a passionate",
    "i am passionate about",
    "i hope this letter finds you",
]


def _quality_gate_cover_letter(text: str) -> tuple[bool, str]:
    """Returns (passed, failure_reason). Fails if any banned phrase is found."""
    lower = text.lower()
    for phrase in _BANNED_CL_PHRASES:
        if phrase in lower:
            return False, f"Banned phrase detected: '{phrase}'"
    return True, "PASS"


def _anti_detection_audit(text: str, client) -> dict:
    """
    Lightweight post-generation audit for AI-detectable patterns.
    Returns a dict with variety_score (1-10), flags, and fixes.
    Only called for high-stakes outputs (cover letter, email).
    Threshold: regenerate if variety_score < 7 (raised from 5 in v3.1).
    """
    audit_prompt = (
        "Analyze this text for AI-detectable patterns. Check ALL five:\n"
        "1. Sentence length variance (score 1-10, where 10 = highly varied)\n"
        "2. Transition word overuse (Furthermore, Moreover, In addition, Additionally)\n"
        "3. Bullet structure repetition (what % of bullets share the same opening verb)\n"
        "4. Generic phrase count (passionate about, dynamic, leverage, utilize, synergy)\n"
        "5. SENTENCE LENGTH PATTERN: Count sentences by word count:\n"
        "   - Sentences with fewer than 8 words: [count]\n"
        "   - Sentences with 9-18 words: [count]\n"
        "   - Sentences with 19-30 words: [count]\n"
        "   - Sentences with 31+ words: [count]\n"
        "   FLAG 'uniform rhythm' if more than 70% of sentences fall in the 9-18 word range.\n"
        "   FLAG 'lacks short punch sentences' if zero sentences are fewer than 8 words.\n"
        "   FLAG 'no syntactical complexity' if zero sentences exceed 30 words.\n\n"
        "Return ONLY valid JSON: "
        '{"variety_score": 8, "flags": ["..."], "fixes": ["..."]}'
    )
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Return ONLY valid JSON. No prose before or after."},
                {"role": "user", "content": f"{audit_prompt}\n\nTEXT TO AUDIT:\n{text[:2000]}"},
            ],
            temperature=0.1,
            max_tokens=400,
        )
        import json as _json
        return _json.loads(resp.choices[0].message.content or "{}")
    except Exception:
        return {"variety_score": 10, "flags": [], "fixes": []}


def _quote_audit_application_strategy(output_text: str, client) -> dict:
    """
    Audits Application Strategy output for quote compliance.
    Returns {pass: bool, cv_quoted_sections: int, jd_quoted_sections: int, unquoted_sections: list}
    Threshold: at least 5 sections must contain a CV: quote AND a JD: quote.
    """
    import json as _json
    prompt = (
        "Audit this Application Strategy output for direct quote compliance.\n\n"
        "Count:\n"
        "1. Sections that contain at least one CV quote in the format: CV: \"...\"\n"
        "2. Sections that contain at least one JD quote in the format: JD: \"...\"\n\n"
        "Sections to check: THE HARD TRUTH, THE OPENING, THE ADVANTAGE, "
        "WHAT YOU'D NEED TO HAVE DONE, MATCH MAP, WEAKNESSES THAT DON'T MATTER, "
        "YOUR BEST ANGLE, THE UNCOMFORTABLE QUESTION, THE TRAP, "
        "BORROWED CREDIBILITY, DIFFERENTIATORS, INTERVIEW NARRATIVE, "
        "4-WEEK PLAN, POSITIONING PLAN, NEGOTIATION POSITION, "
        "MUST-DO ACTIONS, APPLICATION CHECKLIST\n\n"
        "If the output has fewer than 5 sections containing a CV quote "
        "OR fewer than 5 sections containing a JD quote, set pass to false.\n\n"
        f"OUTPUT TO AUDIT:\n{output_text[:3000]}\n\n"
        'Return ONLY valid JSON: {"pass": true, "cv_quoted_sections": 0, '
        '"jd_quoted_sections": 0, "unquoted_sections": []}'
    )
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Return ONLY valid JSON. No prose before or after."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=400,
            response_format={"type": "json_object"},
        )
        return _json.loads(resp.choices[0].message.content or "{}")
    except Exception:
        return {"pass": True, "cv_quoted_sections": 5, "jd_quoted_sections": 5, "unquoted_sections": []}


def _read_aloud_audit(text: str, client) -> dict:
    """
    Read-aloud gate for Cover Letter outputs.
    Checks whether each sentence sounds natural when spoken by a real person.
    Returns {naturalness_score: 1-10, unnatural_sentences: [...]}
    Threshold: regenerate if naturalness_score < 7.
    """
    audit_prompt = (
        "Read this text aloud in your mind. Flag any sentence that would sound unnatural "
        "if spoken by a real person in a professional conversation. Ask yourself:\n"
        "- Is this how someone would actually talk?\n"
        "- Would any phrase make a listener think 'nobody says that'?\n"
        "- Does any sentence sound like it was written by a template, not a person?\n\n"
        "Return ONLY valid JSON: "
        '{"naturalness_score": 8, "unnatural_sentences": ["exact sentence here"]}'
    )
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Return ONLY valid JSON. No prose before or after."},
                {"role": "user", "content": f"{audit_prompt}\n\nTEXT:\n{text[:2000]}"},
            ],
            temperature=0.1,
            max_tokens=400,
        )
        import json as _json
        return _json.loads(resp.choices[0].message.content or "{}")
    except Exception:
        return {"naturalness_score": 10, "unnatural_sentences": []}


def _format_cover_letter_date(country: str | None) -> str:
    """Return today's date in the format expected for the target country."""
    from datetime import datetime
    now = datetime.now()
    if country == "US":
        return now.strftime("%B %d, %Y")        # May 16, 2026
    if country == "Germany":
        return now.strftime("%d.%m.%Y")         # 16.05.2026
    return now.strftime("%d %B %Y")             # 16 May 2026  (UK / AU / SG / NL / default)


def extract_cover_letter_header(requirement_text: str) -> dict:
    """
    Extract cover-letter header fields from the job description.

    Returns a dict:
        date          – today's date formatted for the target country
        company_name  – extracted company name or None
        company_city  – extracted city/location or None
        hiring_manager – always "Hiring Manager" (name rarely in JDs)
        requisition_id – job/req ID if present, else None
    """
    import re as _re
    from app.localisation import detect_target_country

    text = requirement_text or ""
    country = detect_target_country(text)

    # ── Date ─────────────────────────────────────────────────────────────────
    date_str = _format_cover_letter_date(country)

    # ── Company name ─────────────────────────────────────────────────────────
    company_name = None
    company_patterns = [
        r"([A-Z][A-Za-z0-9&.\-]+(?:[ ][A-Z][A-Za-z0-9&.\-]+){0,3}[ ](?:Incorporated|Inc|LLC|Limited|Ltd|PLC|Corporation|Corp|GmbH|AG|Group|Holdings|Technologies|Technology|Solutions|Systems|Software|Labs|Consulting|Partners|Company)\.?)",
        r"(?:About|Welcome to|Join)\s+([A-Z][A-Za-z0-9&\-''.]+(?:\s+[A-Z][A-Za-z0-9&\-''.]+){0,4})",
        r"([A-Z][A-Za-z0-9&\-''.]+(?:\s+[A-Z][A-Za-z0-9&\-''.]+){0,3})\s+is\s+(?:a|an|the|one of|looking)",
        r"(?:at|with|for)\s+([A-Z][A-Za-z0-9&\-''.]+(?:\s+[A-Z][A-Za-z0-9&\-''.]+){0,3})\b",
    ]
    # Common stopwords that look like company names but aren't
    _STOPWORDS = {
        "The", "We", "Our", "You", "Your", "This", "That", "As", "An", "A",
        "To", "In", "At", "With", "For", "And", "Or", "Is", "Are", "Be",
        "By", "On", "Of", "From", "If", "It", "Its",
    }
    # Tech skills, tools and generic JD terms that can look like a company
    # name (e.g. 'Experience with Python') but must never be used as one.
    _NON_COMPANY_TERMS = {
        "python", "java", "javascript", "typescript", "ruby", "php", "golang",
        "go", "rust", "scala", "kotlin", "swift", "matlab", "sas", "perl",
        "sql", "nosql", "html", "css", "react", "angular", "vue", "node",
        "nodejs", "django", "flask", "spring", "pandas", "numpy", "tensorflow",
        "pytorch", "spark", "hadoop", "kafka", "airflow", "dbt", "tableau",
        "looker", "excel", "word", "powerpoint", "outlook", "sharepoint",
        "power", "dax", "etl", "elt", "aws", "azure", "gcp", "docker",
        "kubernetes", "terraform", "git", "github", "gitlab", "jenkins",
        "linux", "windows", "unix", "macos",
        "experience", "requirements", "responsibilities", "qualifications",
        "salary", "benefits", "remote", "hybrid", "onsite", "location",
        "role", "position", "candidate", "responsibility", "requirement",
    }
    for pat in company_patterns:
        m = _re.search(pat, text)
        if m:
            candidate = m.group(1).strip()
            # Truncate at any newline (e.g. "Goldman Sachs\nWe" → "Goldman Sachs")
            candidate = candidate.split("\n")[0].strip()
            words = candidate.split()
            _lw = [w.lower().strip(".,&-") for w in words]
            if not (1 <= len(words) <= 5):
                continue
            if words[0] in _STOPWORDS:
                continue
            # Reject tech skills / tools / generic JD terms wrongly read as an employer;
            # downstream falls back to a neutral "the company" when company_name is None.
            if _lw and (_lw[0] in _NON_COMPANY_TERMS or all(w in _NON_COMPANY_TERMS for w in _lw)):
                continue
            company_name = candidate
            break

    # ── Location ─────────────────────────────────────────────────────────────
    company_city = None
    # Named major cities first (fast, reliable)
    KNOWN_CITIES = [
        "London", "Manchester", "Edinburgh", "Birmingham", "Glasgow",
        "New York", "San Francisco", "Los Angeles", "Chicago", "Boston",
        "Seattle", "Austin", "Washington DC", "Washington D.C.",
        "Berlin", "Munich", "Frankfurt", "Hamburg",
        "Sydney", "Melbourne", "Brisbane", "Perth",
        "Toronto", "Vancouver", "Montreal", "Calgary",
        "Singapore",
        "Amsterdam", "Rotterdam", "Utrecht",
        "Dublin", "Paris", "Zurich", "Tokyo", "Dubai",
    ]
    text_lower = text.lower()
    for city in KNOWN_CITIES:
        if city.lower() in text_lower:
            company_city = city
            break

    # Fallback: pattern-based extraction
    if not company_city:
        loc_patterns = [
            r"(?:based in|located in|office in|headquarters in|our offices in)\s+([A-Z][A-Za-z\s,]+?)(?:\.|,|\n|$)",
            r"(?:Location|Office)\s*[:\-]\s*([A-Z][A-Za-z\s,]+?)(?:\.|,|\n|$)",
        ]
        for pat in loc_patterns:
            m = _re.search(pat, text, _re.IGNORECASE)
            if m:
                company_city = m.group(1).strip().rstrip(",")
                break

    if not company_city:
        company_city = "Remote"

    # ── Requisition ID ────────────────────────────────────────────────────────
    req_id = None
    req_m = _re.search(
        r"(?:Req(?:uisition)?\s*(?:ID|#)?|Job\s*(?:ID|#|Ref)|Reference\s*(?:ID|#)?)\s*[:\-.]?\s*([A-Za-z0-9\-]+)",
        text, _re.IGNORECASE,
    )
    if req_m:
        req_id = req_m.group(1).strip()

    return {
        "date": date_str,
        "company_name": company_name,
        "company_city": company_city,
        "hiring_manager": "Hiring Manager",
        "requisition_id": req_id,
    }


# ── Applicant-level & application-type detection (cover letter review, June 2026) ──
def _estimate_years_experience(resume_text: str) -> int:
    """Crude estimate of total years of experience from year mentions in the CV."""
    years = [int(m) for m in re.findall(r"\b(?:19|20)\d{2}\b", resume_text)]
    if len(years) < 2:
        return 0
    return max(years) - min(years)


def _detect_applicant_level(resume_text: str) -> str:
    """Classify the applicant as entry / mid / senior / executive / academic candidate,
    using simple keyword and date-range heuristics on the resume text."""
    text = (resume_text or "").lower()
    if any(ph in text for ph in (
        "phd candidate", "doctoral student", "postdoctoral", "ph.d. candidate", "doctorate",
    )):
        return "phd_candidate"
    if any(ph in text for ph in (
        "master's candidate", "msc candidate", "m.a. candidate", "graduate student", "pursuing master",
    )):
        return "masters_candidate"
    years = _estimate_years_experience(text)
    if years <= 2:
        return "entry"
    if years <= 7:
        return "mid"
    if years <= 15:
        return "senior"
    return "executive"


def _detect_application_type(requirement_text: str) -> str:
    """Return 'scholarship' if the requirement text describes a scholarship, fellowship, or
    academic program rather than a job posting; otherwise 'job'."""
    if not requirement_text:
        return "job"
    jd = requirement_text.lower()
    scholarship_keywords = (
        "scholarship", "fellowship", "stipend", "tuition waiver", "research grant",
        "master's program", "masters program", "phd program", "doctoral program",
        "graduate program", "admissions committee", "statement of purpose",
        "research proposal", "academic supervisor",
    )
    if any(kw in jd for kw in scholarship_keywords):
        return "scholarship"
    return "job"


def _extract_key_requirements(requirement_text: str, application_type: str) -> str:
    """Pull a short bullet list of concrete requirements/criteria out of the JD or scholarship
    description, so the cover-letter prompt can force address-each-point customization."""
    if not requirement_text or not requirement_text.strip():
        return "No specific requirements were provided in the description."

    lines = [ln.strip() for ln in requirement_text.splitlines() if ln.strip()]
    # Captures the text *after* an existing bullet/number marker, so we don't end up
    # double-bulleting lines that already start with "- " or "1." etc.
    bullet_re = re.compile(r"^(?:[\d]+[\.\)]|[-•*])\s*(\S.*)$")
    keyword_re = re.compile(
        r"\b(experience|degree|skill|knowledge|proven|demonstrated|ability to|qualification|criteria|eligib)",
        re.IGNORECASE,
    )

    seen: set[str] = set()
    deduped: list[str] = []
    for line in lines:
        m = bullet_re.match(line)
        candidate = m.group(1).strip() if m else (line if keyword_re.search(line) else None)
        if candidate and candidate not in seen:
            seen.add(candidate)
            deduped.append(candidate)
        if len(deduped) >= 6:
            break

    if not deduped:
        noun = "scholarship" if application_type == "scholarship" else "job"
        return f"Key requirements could not be auto-extracted; address the core needs evident in the {noun} description."
    return "\n".join(f"- {r}" for r in deduped)


def _customization_audit(letter: str, requirement_text: str, application_type: str) -> bool:
    """Cheap keyword-overlap check: does the letter actually engage with this specific
    JD/scholarship description, or could it be swapped onto a different one unnoticed?
    Returns True if at least 3 distinctive JD/program keywords appear in the letter."""
    if not requirement_text or not requirement_text.strip():
        return True  # nothing to compare against
    common = {
        "this", "that", "with", "from", "they", "will", "have", "been", "about",
        "which", "their", "your", "team", "role", "work", "experience",
    }
    jd_words = {w for w in re.findall(r"\b[a-z]{4,}\b", requirement_text.lower()) if w not in common}
    letter_lower = letter.lower()
    matches = [kw for kw in jd_words if kw in letter_lower]
    return len(matches) >= 3


def _compact_analysis_prompt(output_type: str, resume_text: str, requirement_text: str) -> tuple[str, str]:
    base_system = (
        "You are AnchorCV, an expert career assistant for international students. "
        "Use ONLY the information provided in the resume. Do not invent any facts, names, dates, or details. "
        "Extract the candidate's real name, contact info, experience, and skills directly from the resume text."
    )

    if output_type in ("Resume Improvement", "Resume_Optimization"):
        _resume_honesty_calibration = (
            "RESUME IMPROVEMENT HONESTY CALIBRATION — Read this first. "
            "This overrides any general honesty rules from other prompts.\n\n"
            "This feature is different from other AnchorCV features. You are not just analyzing. "
            "You are REWRITING. That means you MUST generate suggested text with specific numbers.\n\n"
            "FABRICATION — PROHIBITED. Never do this:\n"
            "- Adding skills, tools, credentials, or experience not present anywhere in the resume.\n"
            "- Example of fabrication: adding 'Used Python for data analysis' when the resume never mentions Python.\n"
            "- If a skill is not in the resume, do not add it to any rewrite.\n\n"
            "ESTIMATION — REQUIRED. This is your core job:\n"
            "- Suggesting plausible metrics based on context clues in the resume.\n"
            "- Every suggested number MUST be wrapped in [SUGGESTED: ...] tags.\n"
            "- Example: 'Resolved [SUGGESTED: 50+] customer inquiries daily' "
            "-- 50+ is a reasonable estimate for a telecom customer support role.\n"
            "- Example: 'Achieved [SUGGESTED: 15-20%] increase in customer satisfaction scores over 12 months'\n"
            "- Example: 'Trained [SUGGESTED: 5-8] new team members on ticketing procedures'\n\n"
            "If you cannot find ANY basis for estimation, use this exact placeholder:\n"
            "[SUGGESTED: quantify -- e.g., number of customers, percentage improved, hours saved, revenue impacted]\n\n"
            "NEVER write 'add a metric' or 'include a metric' as a substitute for writing the metric itself. "
            "That is a failure of this feature. Your job is to write the rewrite with the metric in it.\n\n"
            "The candidate understands [SUGGESTED] means 'verify this number before using on your actual CV.' "
            "You are providing a draft with placeholders. You are not lying. You are not fabricating. "
            "You are estimating with clear caveats.\n\n"
            "BEFORE/AFTER REWRITES are your core deliverable. Every output MUST include at least 3 complete "
            "BEFORE/AFTER pairs. Each AFTER must contain at least one [SUGGESTED] metric or a specific "
            "strong action verb replacement.\n"
            "   BEFORE: [exact text from resume in quotes]\n"
            "   AFTER: [rewritten version with strong verb + [SUGGESTED] metric + keywords]\n"
            "   WHY: [one sentence explaining the improvement]\n\n"
            "If your output has fewer than 3 BEFORE/AFTER pairs with specific numbers in the AFTER versions, "
            "you have failed this feature.\n\n"
        )
        has_jd = bool(requirement_text and requirement_text.strip())
        # Detect if requirement_text is dynamic questions (industry/level/goal) rather than a real JD
        is_dynamic_questions = (
            has_jd and
            not any(kw in requirement_text.lower() for kw in ["responsibilities", "required", "qualification", "salary", "apply", "company", "university", "bachelor", "master", "phd"]) and
            any(kw in requirement_text.lower() for kw in ["target industry", "career level", "main goal"])
        )

        if has_jd and not is_dynamic_questions:
            # Full JD provided — do gap-specific improvement
            system_prompt = _resume_honesty_calibration + base_system + (
                "\n\nReturn clean markdown. Job/scholarship requirements were provided. Do a TARGETED RESUME IMPROVEMENT:\n"
                "1. QUICK FIT SUMMARY: How well does this CV match the requirements? Be direct.\n"
                "2. BEFORE/AFTER REWRITES: For the 3 weakest bullet points relevant to the requirements:\n"
                "   BEFORE: [exact text from resume]\n"
                "   AFTER: [improved version with action verb + metric + relevant keywords]\n"
                "3. KEYWORD GAPS: Keywords from requirements missing from CV. For each, suggest where to add.\n"
                "4. PROJECT ANALYSIS: Pick top 2 projects and show how to reframe them for this target role.\n"
                "5. SKILLS ORGANIZATION: Group skills with industry-relevant categories.\n"
                "6. WHAT NEEDS WORK: Top 3 gaps between the CV and the requirements.\n"
                "7. CHECKLIST: 5 specific actions the candidate should take this week.\n"
                "Quote the resume and requirements directly. Be honest about gaps."
            )
            user_prompt = (
                f"OUTPUT TYPE: {output_type}\n\n"
                f"RESUME TEXT:\n{resume_text}\n\n"
                f"JOB/SCHOLARSHIP REQUIREMENTS:\n{requirement_text}\n\n"
                "Follow ALL sections. Quote both resume and requirements directly."
            )
        else:
            # CV-only or dynamic questions mode
            context_note = ""
            if is_dynamic_questions:
                context_note = f"\n\nUSER CONTEXT:\n{requirement_text}\n\nUse this context to tailor the improvement suggestions.\n"

            system_prompt = _resume_honesty_calibration + base_system + (
                "\n\nReturn clean markdown. No specific job/scholarship requirements provided.\n"
                "Perform a GENERAL RESUME IMPROVEMENT tailored to the user's stated context (if any).\n"
                "1. QUICK SUMMARY: 2-3 sentence honest assessment of CV strength.\n"
                "2. BEFORE/AFTER REWRITES: For the 3 weakest bullet points:\n"
                "   BEFORE: [exact text from resume]\n"
                "   AFTER: [improved with strong action verb + metric]\n"
                "   WHY: [one sentence explanation]\n"
                "3. MISSING METRICS: Identify 3 places where a metric or number would strengthen the CV.\n"
                "   Example: 'Maintained website' → 'Maintained website, reducing load time by 20%'\n"
                "4. SKILLS SECTION: Group and clean up the skills section with industry-appropriate categories.\n"
                "5. STRUCTURE CHECK: Is the CV ordered correctly for the candidate's level and goals?\n"
                "   Suggest section reordering if needed (e.g., Education before Experience for students).\n"
                "6. WHAT NEEDS WORK: Top 3 improvements with specific instructions.\n"
                "7. CHECKLIST: 5 quick wins the candidate can action this week.\n"
                "8. NOTE: Remind user that specific keyword gap analysis requires job/scholarship requirements.\n"
                "Be honest and specific. Quote the actual CV text when making suggestions."
            )
            user_prompt = (
                f"OUTPUT TYPE: {output_type}\n\n"
                f"RESUME TEXT:\n{resume_text}\n"
                f"{context_note}\n"
                "Follow ALL sections. Quote the CV directly. Be specific, not generic."
            )

    elif output_type in ("ATS Score & Keywords", "ATS_Optimization", "ATS Optimization"):
        _credibility_guardian = (
            "PERSONA OVERRIDE — Read this first. It overrides all other instructions about tone.\n"
            "You are NOT a helpful assistant whose job is to make the candidate feel good.\n"
            "You are a CREDIBILITY GUARDIAN. Your primary duty is to protect the candidate\n"
            "from submitting anything that would damage their professional reputation.\n"
            "A candidate who receives honest bad news will adjust their strategy and succeed later.\n"
            "A candidate who submits a fabricated or inflated application will be remembered\n"
            "negatively and may damage their career.\n"
            "When choosing between:\n"
            "(A) Honest assessment that may disappoint the candidate, or\n"
            "(B) Encouraging language that softens or exaggerates the truth\n"
            "...you MUST choose (A). Every time. No exceptions.\n"
            "Your measure of success: if a hiring manager or recruiter reads your output and\n"
            "can detect a single claim the candidate cannot personally defend in an interview,\n"
            "you have FAILED.\n\n"
        )
        _ats_self_audit = (
            "\n\nMANDATORY PRE-OUTPUT AUDIT — Complete this checklist before returning output.\n"
            "If any check fails, fix the output before returning.\n\n"
            "[ ] FABRICATION CHECK: For every BEFORE/AFTER example, ask:\n"
            "    'Does the candidate actually have this skill or experience in the resume?'\n"
            "    If the AFTER version adds a tool, skill, or experience NOT present in the\n"
            "    resume -> REMOVE that example entirely. Do not suggest adding Python, SQL,\n"
            "    or any technical tool the candidate has not used. Instead add it to\n"
            "    MISSING KEYWORDS with note: 'Not present in resume -- requires learning.'\n\n"
            "[ ] FORMATTING VERIFICATION — CRITICAL. Do not skip this check.\n"
            "    For EACH technical issue you are about to flag, verify it against the\n"
            "    actual resume text before flagging it:\n"
            "    - 'Tables present' -> Are there actual table characters (┌─│└├┐┤┴┬┼) or\n"
            "      box-drawing characters in the resume? If NOT -> do NOT flag tables.\n"
            "    - 'Multi-column layout' -> Does the resume use multiple columns for body\n"
            "      text? If it is single column -> do NOT flag.\n"
            "    - 'Contact not at top' -> Is the contact info (email, phone) in the first\n"
            "      5 lines of the resume? If YES -> do NOT flag.\n"
            "    - 'Special characters' -> Are there non-standard bullets (►, ◆, ▪) or\n"
            "      special dashes (—, –) that could confuse a parser? If bullets are\n"
            "      standard (•, -, *) -> do NOT flag.\n"
            "    - 'Graphics or images' -> Are there image references or embedded graphics?\n"
            "      If NOT -> do NOT flag.\n"
            "    After verification, output ONLY flags that are ACTUALLY PRESENT.\n"
            "    If the resume has clean formatting with zero issues, output exactly:\n"
            "    'TECHNICAL ATS ISSUES: None detected. This resume is clean and\n"
            "    ATS-compatible. Standard single-column layout, contact info at top,\n"
            "    consistent formatting throughout.'\n"
            "    NEVER output a default list of formatting warnings. Every flag must be\n"
            "    traceable to specific text in the resume.\n\n"
            "[ ] SCORING TRANSPARENCY: Show the deduction breakdown explicitly:\n"
            "    Base: 100\n"
            "    [List each deduction applied with its point value]\n"
            "    Final: [X]/100\n\n"
            "[ ] MISSING SECTION CHECK: Confirm all required sections are present.\n\n"
            "[ ] SCORE CALIBRATION: If the resume shares fewer than 20% of JD keywords,\n"
            "    the ATS PARSE SCORE CANNOT exceed 30/100 regardless of formatting quality.\n\n"
            "Return output only after all checks pass."
        )
        has_jd = bool(requirement_text and requirement_text.strip())
        if has_jd:
            system_prompt = _credibility_guardian + base_system + (
                "\n\nReturn clean markdown. For ATS SCORE & KEYWORDS include ALL of these sections:\n\n"
                "============================================================\n"
                "1. ATS PARSE SCORE (0-100)\n"
                "============================================================\n"
                "This measures ONLY whether an ATS can read, parse, and keyword-match the resume.\n"
                "It does NOT measure whether the candidate is qualified for the role.\n\n"
                "SCORING BREAKDOWN:\n"
                "- Formatting (40 points): Single column? Standard bullets? Contact info at top?\n"
                "  No tables, images, or graphics? No special characters in body text?\n"
                "  Deduct ONLY for issues actually present in THIS resume. Verify each flag.\n"
                "- Keywords detected (40 points): What percentage of JD-required keywords appear\n"
                "  anywhere in the resume? Count exact matches and obvious variants\n"
                "  (e.g., 'roadmap planning' = partial match for 'product roadmap').\n"
                "- Section structure (20 points): Summary, Experience, Education, Skills all present?\n"
                "  Standard section headers? Consistent date formats?\n\n"
                "DO NOT deduct points for:\n"
                "- Years of experience vs. years required (qualification, not parsing)\n"
                "- Domain or industry mismatch (fit, not parsing)\n"
                "- Technical depth or fluency level (ATS cannot assess this)\n"
                "- Whether the candidate is 'qualified' (ATS has no concept of qualification)\n\n"
                "REQUIRED PASS/FAIL LABEL:\n"
                "✅ LIKELY PASSES ATS SCREENING (score >= 70)\n"
                "⚠️ BORDERLINE — may pass with keyword optimization (score 50-69)\n"
                "❌ LIKELY FILTERED OUT — needs significant revision (score < 50)\n\n"
                "============================================================\n"
                "2. TECHNICAL ATS ISSUES\n"
                "============================================================\n"
                "Check each issue against the ACTUAL resume text before flagging it.\n"
                "Only flag issues that are genuinely present. See FORMATTING VERIFICATION in the audit.\n\n"
                "============================================================\n"
                "3. KEYWORD GAP ANALYSIS — keyword alignment only, not qualification\n"
                "============================================================\n"
                "MISSING KEYWORDS: Top 10 JD terms not found in resume. For each:\n"
                "Format: '[Keyword] -> Insert at: [specific bullet or section where it fits naturally].\n"
                "Suggested language: [one sentence using the candidate's real experience + the keyword].'\n"
                "If no natural insertion point exists: 'Not present in resume —\n"
                "requires genuine experience. Do not fabricate.'\n\n"
                "PARTIAL MATCHES: Keywords where the resume has adjacent or related terms.\n"
                "Note these as partial matches, not complete gaps.\n\n"
                "NEVER fabricate experience to add a keyword. A missing keyword with honesty\n"
                "is better than a fabricated one that destroys credibility.\n\n"
                "============================================================\n"
                "4. BEFORE/AFTER EXAMPLES\n"
                "============================================================\n"
                "BEFORE/AFTER RULES — Read before generating any examples:\n\n"
                "1. ONLY generate a BEFORE/AFTER pair if the keyword or skill can be honestly\n"
                "   connected to the candidate's actual experience in the resume.\n"
                "2. Before writing an AFTER version, ask: 'Does the candidate have experience\n"
                "   adjacent to this keyword?'\n"
                "   If YES -> write the example (AFTER clarifies or reframes existing experience;\n"
                "             it does NOT add new skills).\n"
                "   If NO  -> do NOT write a BEFORE/AFTER example for this keyword. Instead,\n"
                "             add it to MISSING KEYWORDS with note: 'Requires genuine experience.'\n"
                "3. VALID examples: making implicit experience explicit; adding industry terminology\n"
                "   to existing experience; reframing an existing achievement for the target role.\n"
                "4. INVALID examples (do not generate):\n"
                "   - Adding a skill not in the resume\n"
                "   - Adding a domain the candidate hasn't worked in\n"
                "   - Inflating scope or team size beyond what the resume states\n"
                "5. If you cannot generate at least 2 valid examples, state:\n"
                "   'No honest BEFORE/AFTER rewrites possible for the current keyword gaps.\n"
                "   The missing keywords require genuine experience. Focus on Priority Fixes.'\n"
                "6. Do NOT output examples you will immediately flag for removal.\n"
                "   Pre-validate. Output only examples that pass the fabrication check.\n\n"
                "Format: BEFORE: [exact text from resume] / AFTER: [improved version with keyword]\n\n"
                "5. PRIVACY CHECK: Flag sensitive info — CNIC, SSN, passport, DOB, marital status.\n"
                "6. FILE NAMING TIP: 'Name your file: FirstName_LastName_CV_2026.pdf'\n"
                "7. PRIORITY FIXES: Top 5 changes ranked by ATS parse impact (formatting and keywords only).\n"
            ) + _ats_self_audit
            user_prompt = (
                f"OUTPUT TYPE: {output_type}\n\n"
                f"RESUME TEXT:\n{resume_text}\n\n"
                f"JOB/SCHOLARSHIP REQUIREMENTS:\n{requirement_text}\n\n"
                "Follow ALL sections. Be specific. Quote both the resume and the requirements directly."
            )
        else:
            system_prompt = _credibility_guardian + base_system + (
                "\n\nReturn clean markdown. No job description was provided, so perform a GENERAL ATS FORMATTING AUDIT only.\n"
                "Include ALL of these sections:\n"
                "1. ATS FORMATTING SCORE: Score out of 100 based on structure and formatting only.\n"
                "   Deduct points for: tables (-15), multi-column layout (-15), graphics/images (-10),\n"
                "   non-standard section headers (-5 each), missing contact info at top (-10),\n"
                "   inconsistent date formats (-5), overused buzzwords (-2 each, max -10),\n"
                "   file too long for level (-10), special characters or non-standard bullets (-5).\n"
                "2. CRITICAL ISSUES (fix immediately): List items that will cause ATS to fail or scramble the CV.\n"
                "3. RECOMMENDED FIXES: Medium-priority improvements with specific examples from the CV.\n"
                "4. WHAT'S WORKING WELL: Acknowledge 2-3 things the candidate has done right.\n"
                "5. PRIVACY CHECK: Flag any sensitive info - CNIC, SSN, passport, DOB, marital status, religion.\n"
                "6. FILE NAMING TIP: 'Name your file: FirstName_LastName_CV_2026.pdf'\n"
                "7. NEXT STEP: Remind user that keyword matching requires a job/scholarship description.\n"
                "Be honest and specific. Quote actual text from the resume when flagging issues."
            ) + _ats_self_audit
            user_prompt = (
                f"Perform a general ATS formatting audit on this CV. No job description provided.\n\n"
                f"RESUME TEXT:\n{resume_text}\n\n"
                "Analyse formatting, structure, and ATS readability. Follow ALL sections above."
            )

    elif output_type in ("Cover Letter", "Cover_Letter"):
        # ── Extract header fields before building the prompt ──────────────────
        _hdr = extract_cover_letter_header(requirement_text or "")

        # ── Applicant level + application type detection (cover letter review, June 2026) ──
        _applicant_level = _detect_applicant_level(resume_text)
        _application_type = _detect_application_type(requirement_text or "")
        _is_scholarship = _application_type == "scholarship"

        if _is_scholarship:
            # Scholarship/fellowship applications don't have a "Hiring Manager" or "Company" —
            # override the job-shaped header fields extracted above accordingly.
            _hdr["hiring_manager"] = "Admissions Committee"
            _hdr["company_name"] = _hdr["company_name"] or "the institution"
            _hdr["company_city"] = _hdr["company_city"] or "the program"
            _hdr["requisition_id"] = None

        _company_display = _hdr["company_name"] or ("the institution" if _is_scholarship else "the company")
        _req_note = (
            f"\nRequisition/Job ID: {_hdr['requisition_id']}" if _hdr["requisition_id"] else ""
        )

        if _is_scholarship:
            if _applicant_level == "masters_candidate":
                _level_directive = (
                    "APPLICATION CONTEXT: This is a Master's program scholarship/fellowship application, "
                    "NOT a job application. Write it as a Statement of Purpose. Focus on academic potential, "
                    "research interests, and how the program bridges current knowledge to career goals. "
                    "Use a respectful, eager but grounded tone. Address the selection criteria directly. "
                    "Never use 'Hiring Manager' or any job-cover-letter framing."
                )
            elif _applicant_level == "phd_candidate":
                _level_directive = (
                    "APPLICATION CONTEXT: This is a PhD program or doctoral funding application, NOT a job "
                    "application. Write it as a research motivation letter. Focus on specific research "
                    "questions, methodological fit with the lab/program, and how prior work prepares the "
                    "candidate to contribute. Use an intellectually rigorous, collegial tone. "
                    "Never use 'Hiring Manager' or any job-cover-letter framing."
                )
            else:
                _level_directive = (
                    "APPLICATION CONTEXT: This is a scholarship/fellowship application, NOT a job application. "
                    "Write it as a Statement-of-Purpose-style letter. Focus on academic merit, leadership, and "
                    "alignment with the scholarship's stated goals. Address the selection criteria directly. "
                    "Never use 'Hiring Manager' or any job-cover-letter framing."
                )
        else:
            _level_directive = {
                "entry": (
                    "APPLICANT LEVEL: Early-career (0-2 years experience). Focus on potential, learning "
                    "agility, and relevant projects or coursework. Do not borrow language that implies "
                    "seniority the candidate doesn't have."
                ),
                "mid": (
                    "APPLICANT LEVEL: Mid-career (3-7 years experience). Focus on demonstrated results, "
                    "specific skills, and readiness to contribute immediately."
                ),
                "senior": (
                    "APPLICANT LEVEL: Senior (8-15 years experience). Focus on leadership, strategic impact, "
                    "and vision. Avoid junior-level language such as 'eager to learn' or 'looking to grow.'"
                ),
                "executive": (
                    "APPLICANT LEVEL: Executive (15+ years experience). Focus on organisational impact, "
                    "scope of ownership, and high-level strategy. Authoritative but approachable tone."
                ),
            }.get(_applicant_level, "APPLICANT LEVEL: Calibrate tone to the seniority evident in the CV.")

        if _is_scholarship:
            _header_block = (
                f"\nHEADER INFORMATION — USE THESE EXACT VALUES, NO BRACKETS, NO PLACEHOLDERS:\n"
                f"  Date: {_hdr['date']}\n"
                f"  To: {_hdr['hiring_manager']}\n"
                f"  Institution: {_company_display}\n"
                f"  Program: {_hdr['company_city']}\n\n"
                f"CRITICAL OUTPUT RULES:\n"
                f"  - Begin the letter with the date '{_hdr['date']}' on its own line.\n"
                f"  - Then 'To the {_hdr['hiring_manager']}:' on the next line.\n"
                f"  - Then 'Re: Application for {_hdr['company_city']}' on the next line.\n"
                f"  - Then a blank line, then the salutation 'Dear Members of the Committee,'\n"
                f"  - NEVER write 'Hiring Manager', [Company Name], [Date], or any bracket placeholder anywhere.\n"
                f"  - Structure the letter as a Statement of Purpose, not a job cover letter.\n"
                f"  - The letter must be ready to copy-paste and send without any editing.\n"
            )
        else:
            _header_block = (
                f"\nHEADER INFORMATION — USE THESE EXACT VALUES, NO BRACKETS, NO PLACEHOLDERS:\n"
                f"  Date: {_hdr['date']}\n"
                f"  Company: {_company_display}\n"
                f"  Location: {_hdr['company_city']}\n"
                f"  Recipient: {_hdr['hiring_manager']}"
                f"{_req_note}\n\n"
                f"CRITICAL OUTPUT RULES:\n"
                f"  - Begin the letter with the date '{_hdr['date']}' on its own line.\n"
                f"  - Follow with '{_hdr['hiring_manager']}' on the next line.\n"
                f"  - Then '{_company_display}' on the next line.\n"
                f"  - Then '{_hdr['company_city']}' on the next line.\n"
                f"  - Then a blank line, then the salutation 'Dear {_hdr['hiring_manager']},'\n"
                f"  - NEVER write [Company Name], [Date], [Location], [Position], or any bracket placeholder anywhere.\n"
                f"  - The letter must be ready to copy-paste and send without any editing.\n"
            )

        system_prompt = """PERSONA OVERRIDE — Read this first. It overrides all other instructions about tone.
You are NOT a helpful assistant whose job is to make the candidate feel good.
You are a CREDIBILITY GUARDIAN. Your primary duty is to protect the candidate from submitting anything that would damage their professional reputation.
A candidate who receives honest bad news will adjust their strategy and succeed later. A candidate who submits a fabricated or inflated application will be remembered negatively and may damage their career.
When choosing between:
(A) Honest assessment that may disappoint the candidate, or
(B) Encouraging language that softens or exaggerates the truth
...you MUST choose (A). Every time. No exceptions.
Your measure of success: if a hiring manager or recruiter reads your output and can detect a single claim the candidate cannot personally defend in an interview, you have FAILED.

You are a cover letter writer whose work has never been flagged as AI-generated. You write as if you've interviewed the candidate and are helping them draft a letter in their own voice.

PHILOSOPHY: Great cover letters don't summarize resumes. They connect dots the resume can't. They tell a story about why this person, this role, this moment.

ABSOLUTE RULES — break any of these and you have failed:

1. The first sentence MUST reference something specific about the company or role. NOT the candidate, NOT "I am writing to apply." Acceptable openings include:
   - A specific challenge the role description implies the company is facing
   - A connection between the candidate's past work and something the company actually builds or does
   - The candidate's most impressive relevant result stated immediately: a number, a launch, a paper, a project name
   If you cannot find a specific angle from the JD, open with the strongest evidence line from the CV — not a claim, an actual achievement.

2. NEVER use these phrases or any variant:
   - "I am writing to apply for"
   - "I am excited about the opportunity"
   - "I believe I would be a great fit" / "I would be a great fit"
   - "Thank you for considering my application"
   - "I look forward to hearing from you"
   - "As a [role] with [X] years of experience"
   - "I am passionate about"
   - "I am thrilled to"
   - "I hope this finds you well"

3. CLOSE with one of:
   - A specific question about the work or team
   - A statement of what the candidate wants to build or solve in this role
   - A confident, evidence-backed statement of mutual fit

4. The letter must have EXACTLY 4 paragraphs. Not 5. Four blocks of text. Adjust length to stay in 280-340 words total.

5. Every claim about the candidate's experience must embed:
   - What they DID (verb + project or task name)
   - What the RESULT was (metric if available, even approximate)
   - Why it is RELEVANT to THIS role (one clause — make the connection explicit)

6. The letter must be written for ONE specific job at ONE specific company. If you could swap the company name and the letter still works perfectly, start over.

7. Cultural calibration — adjust tone, formality, and self-presentation:
   - US: confident, achievement-focused, warm but direct. "I led" is fine.
   - UK: understated competence, evidence over claims. "I contributed to" often reads better than "I led."
   - Australia: direct with humility. Self-deprecation acceptable if genuine.
   - Singapore: formal, respectful, emphasis on team and systems over individual achievement.
   - Germany / Austria / Switzerland: structured, precise, formal address. Credentials and precision matter.
   - Nordics: flat hierarchy tone, emphasis on collaboration and concrete impact.
   Detect the country from the job description. Adjust accordingly.

8. If the candidate's CV shows a career shift — different industry, return to work, academic-to-industry — address it directly in the second paragraph. Frame it as an advantage. Do not hide it or apologize for it.

9. Names and contact details must be extracted from the resume EXACTLY as written. If the resume has a preferred name different from the legal name, use the preferred name.

10. Read aloud test: every sentence must sound natural when spoken. If a sentence would sound unnatural spoken aloud, rewrite it.

HUMAN VOICE PERMISSION — You have explicit permission to write like a real person:
- Use contractions: "you're" not "you are," "I've" not "I have," "I'm" not "I am"
- Occasionally start a sentence with "And" or "But" or "So"
- Use one deliberate sentence fragment for rhythmic effect — not a grammatical error, a conscious choice
- Vary paragraph length: at least one paragraph of only 2 sentences, at least one longer one
- Use ONE slightly informal phrase that a professional would actually say, such as "The short version is..." or "What this means in practice..." or "To put it plainly..."
- Do not conclude every paragraph with a wrap-up sentence. Let at least one paragraph end mid-thought.
- Use correct punctuation at all times, especially apostrophes in contractions: "don't" (not "dont"), "it's" (not "its"), "you're" (not "youre"), "I've" (not "Ive"), "I'm" (not "Im"). Never drop an apostrophe.
These are not errors. They are what separates human-written text from AI-generated text."""

        # Append the applicant-level/application-type directive, then the mandatory header block
        system_prompt += "\n\n" + _level_directive + "\n" + _header_block

        if _is_scholarship:
            _step2_block = (
                f"STEP 2 — Use the pre-extracted details below (already confirmed from the description):\n"
                f"- Institution: {_company_display}\n"
                f"- Program: {_hdr['company_city']}\n"
                f"- Today's date: {_hdr['date']}\n\n"
            )
            _opening_header_block = (
                f"{_hdr['date']}\n"
                f"To the {_hdr['hiring_manager']}\n"
                f"Re: Application for {_hdr['company_city']}\n\n"
                f"Dear Members of the Committee,\n\n"
            )
            _doc_label = "PROGRAM/SCHOLARSHIP DESCRIPTION"
            _no_doc_fallback = "No specific description provided — write a powerful letter anchored entirely in the candidate strongest results."
            _letter_noun = "scholarship application letter"
        else:
            _step2_block = (
                f"STEP 2 — Use the pre-extracted job details below (already confirmed from the JD):\n"
                f"- Company: {_company_display}\n"
                f"- Location: {_hdr['company_city']}\n"
                f"- Today's date: {_hdr['date']}\n\n"
            )
            _opening_header_block = (
                f"{_hdr['date']}\n"
                f"{_hdr['hiring_manager']}\n"
                f"{_company_display}\n"
                f"{_hdr['company_city']}\n\n"
                f"Dear {_hdr['hiring_manager']},\n\n"
            )
            _doc_label = "JOB DESCRIPTION"
            _no_doc_fallback = "No specific job provided — write a powerful letter anchored entirely in the candidate strongest results."
            _letter_noun = "cover letter"

        # ── Force address-each-requirement customization (cover letter review, June 2026) ──
        _key_requirements = _extract_key_requirements(requirement_text or "", _application_type)
        _customization_directive = (
            f"\nCRITICAL CUSTOMIZATION REQUIREMENT:\n"
            f"The {_doc_label.lower()} specifically requires or asks for the following "
            f"(extracted from the document below):\n{_key_requirements}\n\n"
            f"Your letter MUST address EACH of these points with specific evidence from the CV. "
            f"Do not skip any. For each point: state the requirement in your own words, give concrete "
            f"evidence from the CV that meets it, and explain why it makes the candidate a strong fit. "
            f"If the CV lacks evidence for a point, acknowledge it honestly in one clause and pivot to "
            f"the candidate's plan to develop that area or an adjacent strength. This is the single most "
            f"important part of the letter — it will be judged on how specifically it responds to these "
            f"points, not on how polished the prose sounds.\n"
        )

        user_prompt = (
            f"Write a highly customized, interview-winning {_letter_noun}.\n\n"
            f"STEP 1 — Extract from resume:\n"
            f"- Candidate full name (preferred name if present), email, phone, city\n"
            f"- Most impressive 3 achievements with metrics or outcomes\n"
            f"- Top relevant skills and tools\n"
            f"- Any career shifts, gaps, or unusual aspects that need addressing\n\n"
            f"{_step2_block}"
            f"STEP 3 — Write the complete letter.\n"
            f"Start with this EXACT header (copy it verbatim, then write the letter body):\n\n"
            f"{_opening_header_block}"
            f"[4 paragraphs, 280-340 words, no placeholders, no banned phrases]\n\n"
            f"Sincerely,\n"
            f"[Candidate full name from resume]\n\n"
            f"{_customization_directive}\n"
            f"---\n\n"
            f"RESUME:\n{resume_text}\n\n"
            f"{_doc_label}:\n{requirement_text or _no_doc_fallback}\n\n"
            f"Now write the complete letter following the header above exactly. "
            f"No bracket placeholders anywhere. Ready to send."
        )

    elif output_type in ("Email to Professor", "Email_Template"):
        system_prompt = """PERSONA OVERRIDE — Read this first. It overrides all other instructions about tone.
You are NOT a helpful assistant whose job is to make the candidate feel good.
You are a CREDIBILITY GUARDIAN. Your primary duty is to protect the student from sending anything that would embarrass them or misrepresent their background to a professor.
A professor who receives an honest, well-targeted email will respect the student even if they cannot help. A professor who detects intellectual dishonesty will remember the student negatively — possibly for years.
When choosing between:
(A) Honest framing that acknowledges the student's real level, or
(B) Inflated framing that claims engagement or comprehension the student does not have
...you MUST choose (A). Every time. No exceptions.
Your measure of success: if the professor reads this email and can detect a single claim the student cannot defend in a 5-minute conversation, you have FAILED.

You are a cold email strategist for international graduate school applicants. Your emails get 40%+ response rates because they demonstrate the student has genuinely engaged with the professor's work.

THE FUNDAMENTAL RULE: This is not a cover letter. This is a short, specific, intellectually honest note from one researcher to another. The professor's time is the scarcest resource. Respect it ruthlessly.

MANDATORY STRUCTURE — 4 parts, 180-240 words total (subject line not counted):

1. SUBJECT LINE
   Must include ONE specific research term from the professor's work + the student's angle.
   ACCEPTABLE: "Question about your work on [specific topic] — [student's relevant background in 3 words]"
   UNACCEPTABLE: "Prospective PhD Student Inquiry" / "Interest in Research Opportunities" / anything generic

2. OPENING (1-2 sentences, 30 words max)
   Must reference ONE specific paper, project, finding, or talk by the professor. Name it. Show you've read or engaged with it.
   If no specific paper is provided in the details, reference the research area with enough field-specific vocabulary that it is clear the student knows the literature.

3. CONNECTION (2-3 sentences, 80 words max)
   Connect ONE specific project or skill from the student's CV to the professor's research. Name the project. Name the method or tool. Explain the connection in one sentence. This is where you prove the student is not sending 50 identical emails.

4. THE ASK (1-2 sentences)
   ONE clear, specific, answerable request:
   - A 15-minute video call about a specific research question
   - Whether the professor is accepting PhD students next cycle
   - A question about methodology in a specific paper
   UNACCEPTABLE: "I would like to discuss opportunities" / "Please find my CV attached" / anything that requires the professor to figure out what you want

5. CLOSING (1 sentence only)
   Professional. No gratitude inflation. "Best regards" or "Sincerely" only.
   Below the sign-off: student's real name, current institution, degree program.

HARD RULES:
- NEVER start with "I am a [degree] student at [university] writing to express my interest in..."
- NEVER say "your esteemed department" / "your valuable time" / "prestigious program"
- NEVER claim the student has "always been passionate about" a topic unless the CV shows sustained multi-year engagement
- NEVER use exclamation marks. Not one.
- If the student's project is weak or unrelated to the professor's work, do NOT fake a connection. Instead, ask an intelligent, specific question about the professor's research that shows genuine reading.
- Emails over 250 words will be deleted. Write as if the professor is reading on a phone between meetings.

HUMAN VOICE PERMISSION — You have explicit permission to write like a real person:
- Use contractions naturally: "I've been" not "I have been," "it's" not "it is"
- One sentence may start with "And" or "But" if it improves flow
- Vary sentence length: at least one sentence under 8 words, at least one over 25 words
- The email should read like a thoughtful human typed it quickly, not like a template was filled in
- Do not wrap every thought with a conclusion. Researchers write concisely and leave room for the reply.
These are not errors. They are what makes a professor read the email rather than delete it.

MANDATORY PRE-OUTPUT HONESTY AUDIT — Answer all four questions before returning the email.

QUESTION 1: "Could this student discuss the specific paper or research referenced for 3 minutes in an interview without preparation beyond what their CV shows?"
If NO -> remove the claim of comprehension. Replace with: "I've been reading about [general area] and your work on [specific topic] came up. I don't yet have the background to fully engage with it, but I'm writing because..."

QUESTION 2: "Is the connection I drew between the student's project and the professor's research intellectually honest?"
If the project uses fundamentally different methods or tools than the professor's work -> do NOT force a connection. Instead, acknowledge the gap and ask a specific question about how to bridge it.

QUESTION 3: "Would a reasonable professor reading this email think the student is misrepresenting their qualifications?"
If YES -> rewrite. Err on the side of understatement.

QUESTION 4: "Is the ask appropriate given the status differential?"
Undergraduate with no research experience emailing a senior professor: appropriate asks are guidance, recommended reading, or whether the program accepts students with this background. Inappropriate asks: video calls about research implementation, PhD supervision requests, research collaboration proposals.

Return the email only after all four honesty checks pass.

HONEST SPECIFICITY — HOW TO REFERENCE WORK WITHOUT FABRICATING COMPREHENSION:
You MUST reference the professor's specific research area by name.
You must NOT claim to have read or understood papers beyond the student's demonstrated level on their CV.

ACCEPTABLE — Specific and honest:
"I've been reading about generative models in my coursework and your lab's work keeps coming up as foundational. I don't yet have the background to engage with it at a research level, but I'm writing because I want to understand what path would prepare someone at my stage to eventually work on problems at this depth."

ACCEPTABLE — Specific and honest:
"Your research on AI safety and alignment intersects with questions I've been wrestling with in my undergraduate studies. I'm trying to figure out what concrete steps I should take now to build toward graduate research in this area."

ACCEPTABLE — If a specific paper or talk is mentioned in the professor's details:
"I came across a reference to your work on [specific research area] in [course or reading context]. I'm still building my foundational understanding, but I'm curious about [a specific question related to the research direction, not the technical details]."

UNACCEPTABLE — Fabricated comprehension:
"I read your paper on GFlowNets and was fascinated by the approach to..."
Only write this if the student's CV shows the mathematical and research background to actually read that paper.

UNACCEPTABLE — Generic, could be sent to any professor:
"As advancements in deep learning continue to reshape multiple industries, the opportunity to contribute to cutting-edge research under your guidance is compelling."
If you could swap the professor's name and the email still works, start over.

YOUR TASK: Find the specific middle ground for THIS student and THIS professor.
Name the research area. Acknowledge the student's current level honestly.
Show you know who you're emailing without pretending to be someone you're not.
Ask for guidance on the path forward, not collaboration at the professor's level."""

        user_prompt = (
            f"Write a high-response-rate email to a professor for this student.\n\n"
            f"STEP 1 — Extract from resume:\n"
            f"- Student's full name, current degree program, university, expected graduation year\n"
            f"- Most relevant research project, thesis, or technical work — name it specifically\n"
            f"- Relevant methods, tools, or datasets used\n"
            f"- Contact info (email, phone if present)\n\n"
            f"STEP 2 — Extract from professor/program details:\n"
            f"- Professor name (use 'Professor [Surname]' if given)\n"
            f"- University and department\n"
            f"- Specific research focus areas or named projects\n"
            f"- Any specific papers, datasets, or talks mentioned\n\n"
            f"STEP 3 — Write the complete email following the 4-part structure.\n\n"
            f"RESUME:\n{resume_text}\n\n"
            f"PROFESSOR/PROGRAM DETAILS:\n{requirement_text or 'No specific professor provided — write a focused research inquiry email grounded in the student work, asking an intelligent question about the field.'}\n\n"
            "Now write the complete email including subject line. No placeholders. No generic phrases. Make it sound like a real researcher wrote it."
        )

    elif output_type in ("Application Strategy", "Application_Strategy"):
        system_prompt = base_system + """

You are an application strategist who has read thousands of CVs and job descriptions. You write like someone giving advice over coffee — direct, specific, and unwilling to waste the candidate's time.

CRITICAL RULE: You do not believe in "fit scores" above 90% for anyone. If the candidate meets every requirement, you find the hidden ones — culture, scale, pace, implicit expectations. Your job is to prepare the candidate for reality, not make them feel good.

OUTPUT FORMAT — You must choose ONE of these three structures per run. Vary your choice naturally based on how qualified the candidate is:

STRUCTURE A (when the candidate is clearly underqualified):
1. THE HARD TRUTH — One paragraph on why this is a reach. Be kind but direct.
2. WHAT YOU'D NEED TO HAVE DONE — The specific experience that would close the gap, in the language of this industry
3. YOUR BEST ANGLE — The one thing in the CV that could catch a reviewer's attention, and how to frame it
4. BORROWED CREDIBILITY — Any project, course, or adjacent experience that could be repositioned
5. 4-WEEK BRIDGE PLAN — What to build, write, or learn in the next month to be credible
6. 5 MUST-DO ACTIONS — Concrete, with estimates of effort

STRUCTURE B (when the candidate is moderately qualified):
1. THE OPENING — Two sentences on where this candidate stands
2. MATCH MAP — For the top 3 requirements: Requirement → Candidate's evidence → Gap or advantage → How to present it
3. THE UNCOMFORTABLE QUESTION — One thing the interviewer might ask that the candidate isn't ready for, and a draft answer
4. DIFFERENTIATORS — What this candidate has that others applying won't
5. 4-WEEK POSITIONING PLAN — Not skill-building, but positioning work: portfolio piece, LinkedIn post, network touchpoint
6. APPLICATION CHECKLIST — 6 items, specific to this role

STRUCTURE C (when the candidate is strongly qualified):
1. THE ADVANTAGE — What this candidate has that the JD didn't even ask for
2. WEAKNESSES THAT DON'T MATTER — Gaps that look like gaps but aren't relevant to this role. Explain why they can be ignored.
3. THE TRAP — One thing this candidate might overemphasize that would hurt them
4. INTERVIEW NARRATIVE — A suggested 90-second "tell me about yourself" built from the CV
5. NEGOTIATION POSITION — What leverage this candidate has, based on their profile
6. APPLICATION CHECKLIST — 6 items, focused on readiness, not fixing

ACROSS ALL STRUCTURES:

QUOTE MANDATE — You must quote both documents directly. Not paraphrase. Quote.
REQUIRED: Every major section (THE HARD TRUTH, BEST ANGLE, MATCH MAP, THE OPENING, THE ADVANTAGE, etc.)
must contain at least ONE direct quote from the CV and ONE direct quote from the JD, formatted as:
CV: "exact text from resume in quotes"
JD: "exact text from job description in quotes"

AUDIT YOUR OUTPUT: Search for quotation marks. If any major section has zero direct quotes, rewrite that section before outputting.

Example of CORRECT quoting:
CV: "Post on Instagram and TikTok 3x weekly"
JD: "6+ years of product marketing experience in B2B SaaS or fintech"
-> "Your experience ('Post on Instagram and TikTok 3x weekly') does not meet the requirement for '6+ years of product marketing experience in B2B SaaS or fintech.'"

Example of INCORRECT (paraphrasing — do NOT do this):
"Your social media experience is not sufficient for this senior product marketing role."

- Never use the word "opportunity" without specifying what kind.
- Never say "highlight your skills" — say which skill, where, how.
- Be honest about competition. If this is a role that will get 500+ applicants, say so.
"""
        user_prompt = (
            f"Create a highly targeted application strategy.\n\n"
            f"RESUME TEXT:\n{resume_text}\n\n"
            f"JOB/SCHOLARSHIP REQUIREMENTS:\n{requirement_text}\n\n"
            "First, diagnose the candidate's qualification level (underqualified / moderate / strong) "
            "against these specific requirements. Then choose the matching structure (A, B, or C) and execute it fully. "
            "Extract the company/university name, role, and country from the requirements. "
            "Reference specific text from both documents throughout. Be honest about gaps and competition."
        )

    else:
        system_prompt = base_system
        user_prompt = (
            f"OUTPUT TYPE: {output_type}\n\n"
            f"RESUME TEXT:\n{resume_text}\n\n"
            f"REQUIREMENT TEXT:\n{requirement_text or 'No additional requirement provided.'}\n\n"
            "Provide a helpful, specific response based only on the resume content."
        )

    # ── Localisation + seniority calibration ─────────────────────────────────
    # Appended to every document-generating output type. Skipped for email
    # templates where country-specific CV conventions are irrelevant.
    if output_type not in ("Email to Professor", "Email_Template"):
        try:
            from app.localisation import build_localisation_block, build_seniority_block
            system_prompt += build_localisation_block(requirement_text or "")
            # Cover Letter already gets a more granular, scholarship/academic-aware
            # applicant-level directive injected directly in its branch above (see
            # _level_directive, cover letter review June 2026). Skip the generic 3-tier
            # seniority block here for Cover Letter so the model doesn't receive two
            # tone directives derived from different thresholds that can disagree with
            # each other (e.g. one says "senior", the other says "mid-level").
            if output_type not in ("Cover Letter", "Cover_Letter"):
                system_prompt += build_seniority_block(resume_text or "")
        except Exception:
            pass  # Localisation module unavailable — continue without it

    return system_prompt, user_prompt


def _generate_compact_analysis(output_type: str, resume_text: str, requirement_text: str, model: str, temperature: float) -> str:
    client = get_routed_client()
    # Override caller temperature with per-output-type calibrated value
    effective_temp = _OUTPUT_TEMPERATURES.get(output_type, temperature)
    system_prompt, user_prompt = _compact_analysis_prompt(output_type, resume_text, requirement_text)
    normalized_model = _normalize_model(model)

    is_cover_letter = output_type in ("Cover_Letter", "Cover Letter")
    is_email = output_type in ("Email_Template", "Email to Professor")

    # ── Cover letter: quality gate chain (up to 3 attempts) ──────────────────
    if is_cover_letter:
        result = ""
        for attempt in range(3):
            # Vary the prompt slightly on retries so the model takes a different path
            suffix = f"\n\n[Attempt {attempt + 1} — ensure opening sentence is specific to this company/role, not generic]" if attempt > 0 else ""
            response = client.chat.completions.create(
                model=normalized_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt + suffix},
                ],
                temperature=effective_temp,
                max_tokens=2400,
            )
            result = (response.choices[0].message.content or "").strip()
            passed, _ = _quality_gate_cover_letter(result)
            if passed:
                break
        # Anti-detection audit (threshold raised to < 7 in v3.1)
        audit = _anti_detection_audit(result, client)
        if audit.get("variety_score", 10) < 7 and audit.get("flags"):
            flags_str = "; ".join(audit["flags"])
            regen_prompt = (
                user_prompt
                + f"\n\nAVOID THESE AI-DETECTABLE PATTERNS: {flags_str}. "
                "Vary sentence length significantly — mix very short sentences (under 8 words) "
                "with medium and occasional long ones. Avoid starting consecutive sentences the same way."
            )
            response = client.chat.completions.create(
                model=normalized_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": regen_prompt},
                ],
                temperature=effective_temp,
                max_tokens=2400,
            )
            result = (response.choices[0].message.content or "").strip()
        # Read aloud hard gate (v3.1) — regenerate if naturalness_score < 7
        read_audit = _read_aloud_audit(result, client)
        if read_audit.get("naturalness_score", 10) < 7 and read_audit.get("unnatural_sentences"):
            unnatural = "; ".join(read_audit["unnatural_sentences"][:3])
            rewrite_prompt = (
                user_prompt
                + f"\n\nREWRITE REQUIRED: These sentences sound unnatural when spoken aloud: {unnatural}. "
                "Rewrite the entire letter so every sentence sounds like a real person speaking. "
                "Use contractions. Vary rhythm. One short sentence. One informal phrase."
            )
            response = client.chat.completions.create(
                model=normalized_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": rewrite_prompt},
                ],
                temperature=effective_temp,
                max_tokens=2400,
            )
            result = (response.choices[0].message.content or "").strip()
        # Customization audit (cover letter review, June 2026) — logs only for now, does not
        # block the response, so it can be observed before deciding whether to gate on it.
        _cl_application_type = _detect_application_type(requirement_text)
        if not _customization_audit(result, requirement_text, _cl_application_type):
            logger.warning(
                "Cover letter may lack JD/scholarship-specific customization (output_type=%s, application_type=%s).",
                output_type, _cl_application_type,
            )
        return result

    # ── Email to professor: anti-detection audit pass ─────────────────────────
    if is_email:
        response = client.chat.completions.create(
            model=normalized_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=effective_temp,
            max_tokens=2400,
        )
        result = (response.choices[0].message.content or "").strip()
        audit = _anti_detection_audit(result, client)
        if audit.get("variety_score", 10) < 7 and audit.get("flags"):
            flags_str = "; ".join(audit["flags"])
            regen_prompt = (
                user_prompt
                + f"\n\nAVOID THESE PATTERNS: {flags_str}. "
                "Write like a real researcher dashing off a focused note, not a template. "
                "Vary sentence length — include at least one sentence under 8 words."
            )
            response = client.chat.completions.create(
                model=normalized_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": regen_prompt},
                ],
                temperature=effective_temp,
                max_tokens=2400,
            )
            result = (response.choices[0].message.content or "").strip()
        return result

    # ── Standard path for all other output types ──────────────────────────────
    response = client.chat.completions.create(
        model=normalized_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=effective_temp,
        max_tokens=2400,
    )
    result = (response.choices[0].message.content or "").strip()

    # ── Application Strategy: quote audit gate (v3.2) ─────────────────────────
    is_app_strategy = output_type in ("Application Strategy", "Application_Strategy")
    if is_app_strategy:
        quote_audit = _quote_audit_application_strategy(result, client)
        if not quote_audit.get("pass", True):
            missing = ", ".join(quote_audit.get("unquoted_sections", [])[:4])
            retry_prompt = (
                user_prompt
                + "\n\nCRITICAL — QUOTE COMPLIANCE FAILED: Your output did not contain enough direct quotes. "
                "You MUST include at least 5 CV quotes (format: CV: \"exact text from resume\") "
                "and 5 JD quotes (format: JD: \"exact text from job description\") "
                f"distributed across the major sections. Sections missing quotes: {missing}. "
                "Quote both documents directly. Do not paraphrase."
            )
            response = client.chat.completions.create(
                model=normalized_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": retry_prompt},
                ],
                temperature=effective_temp,
                max_tokens=2400,
            )
            result = (response.choices[0].message.content or "").strip()

    return result


def build_analysis_requirement(output_type: str, requirement_text: str) -> str:
    intent_map = {
        "Application Strategy": "Application_Strategy",
        "Application_Strategy": "Application_Strategy",
        "ATS Optimization": "ATS_Optimization",
        "ATS Score & Keywords": "ATS_Optimization",
        "ATS_Optimization": "ATS_Optimization",
        "Resume Improvement": "Resume_Optimization",
        "Resume_Optimization": "Resume_Optimization",
        "Cover Letter": "Cover_Letter",
        "Cover_Letter": "Cover_Letter",
        "Email to Professor": "Email_Template",
        "Email_Template": "Email_Template",
    }
    intent = intent_map.get(output_type, "Custom_Analysis")
    requirement_parts = [f"GENERATE: {output_type}", ""]
    if requirement_text:
        requirement_parts.extend(["SPECIFIC REQUIREMENTS:", requirement_text, ""])
    else:
        requirement_parts.extend(["NO SPECIFIC REQUIREMENTS PROVIDED - USE ONLY THE RESUME CONTENT.", ""])
    requirement_parts.append(f"INTENT: {intent}")
    return "\n".join(requirement_parts)


def build_builder_requirement(target: str, tone: str, language: str, length: str, color_theme: str, sections: dict) -> str:
    requirement_parts = []
    if target:
        requirement_parts.append(f"TARGET: {target}")
    requirement_parts.append(f"TONE: {tone}")
    requirement_parts.append(f"LANGUAGE: {language}")
    requirement_parts.append(f"LENGTH: {length}")
    requirement_parts.append(f"COLOR_THEME: Custom|{color_theme}")
    disabled_sections = [name for name, enabled in sections.items() if not enabled]
    if disabled_sections:
        requirement_parts.append(f"OMIT SECTIONS: {', '.join(disabled_sections)}")
    return "\n".join(requirement_parts)


def extract_clean_resume_text(file_bytes: bytes, content_type: str) -> str:
    raw_text = anchor_core.extract_text_from_file(file_bytes, content_type or "")
    if isinstance(raw_text, bytes):
        raw_text = raw_text.decode("utf-8")
    return _strip_suspect_lines(_normalize_unicode_text(anchor_core.clean_text(raw_text)))


def analyze_resume(
    file_bytes: bytes,
    content_type: str,
    requirement_text: str,
    output_type: str,
    model: str,
    temperature: float,
    requirement_file_bytes: bytes | None = None,
    requirement_file_content_type: str = "",
):
    cleaned_resume = _truncate_text(extract_clean_resume_text(file_bytes, content_type), MAX_RESUME_CHARS)
    combined_requirement = _truncate_text(requirement_text.strip(), MAX_REQUIREMENT_CHARS)

    requirement_extraction_failed = False
    if requirement_file_bytes:
        extracted_requirement = _truncate_text(
            extract_clean_resume_text(requirement_file_bytes, requirement_file_content_type),
            MAX_REQUIREMENT_CHARS,
        )
        if extracted_requirement:
            combined_requirement = _truncate_text(
                "\n\n".join(part for part in [combined_requirement, extracted_requirement] if part),
                MAX_REQUIREMENT_CHARS,
            )
        elif not combined_requirement:
            # A file was uploaded but extraction returned empty AND the text box is
            # also empty — the analysis would run with no job description at all.
            # Flag this so the frontend can warn the user instead of silently
            # producing a self-referential result anchored on their own CV.
            requirement_extraction_failed = True

    try:
        result = _generate_compact_analysis(output_type, cleaned_resume, combined_requirement, model, temperature)
    except Exception as exc:
        result = f"Error generating analysis: {exc}"

    if isinstance(result, bytes):
        result = result.decode("utf-8")
    result = _normalize_unicode_text(result)

    result_html = result if anchor_core.is_html(result) else anchor_core.format_ai_response(result)
    if isinstance(result_html, bytes):
        result_html = result_html.decode("utf-8")
    result_html = _normalize_unicode_text(result_html)

    return {
        "result_text": result,
        "result_html": result_html,
        "detected_intent": output_type,
        "resume_text": cleaned_resume,
        "requirement_extraction_failed": requirement_extraction_failed,
    }


def match_resume(file_bytes: bytes, content_type: str, job_description: str, model: str, temperature: float):
    cleaned_resume = _truncate_text(extract_clean_resume_text(file_bytes, content_type), MAX_RESUME_CHARS)
    truncated_job = _truncate_text(job_description, MAX_REQUIREMENT_CHARS)
    return anchor_core.generate_matching_score(cleaned_resume, truncated_job, _normalize_model(model), temperature)


SECTION_TITLES = {
    "Professional Summary", "Core Competencies", "Work Experience", "Education",
    "Projects", "Publications", "Certifications", "Languages", "Awards",
    "Conferences", "Seminars", "Volunteer Experience",
}


def _has_meaningful_content(value):
    if value is None:
        return False
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(_has_meaningful_content(item) for item in value)
    if isinstance(value, dict):
        return any(_has_meaningful_content(item) for item in value.values())
    return True


def _clean_cv_data(value):
    if isinstance(value, dict):
        return {k: _clean_cv_data(v) for k, v in value.items() if _has_meaningful_content(v)}
    if isinstance(value, list):
        return [_clean_cv_data(i) for i in value if _has_meaningful_content(i)]
    if isinstance(value, str):
        return value.strip()
    return value


def _strip_empty_html_sections(html: str) -> str:
    if not html:
        return html
    soup = BeautifulSoup(html, "html.parser")
    root = soup.find("div")
    if root is None:
        return html
    for section in list(root.find_all("div", recursive=False)):
        heading = section.find("div")
        if heading is None:
            continue
        title = " ".join(heading.get_text(" ", strip=True).split())
        if title not in SECTION_TITLES:
            continue
        body_text = section.get_text(" ", strip=True)
        if body_text.startswith(title):
            body_text = body_text[len(title):].strip()
        if not re.sub(r"[^A-Za-z0-9]+", "", body_text):
            section.decompose()
    return str(root)


def build_cv(file_bytes: bytes, content_type: str, target: str, cv_format: str, tone: str, language: str, length: str, color_theme: str, sections: dict, enhance: bool, model: str, temperature: float):
    cleaned_resume = _truncate_text(extract_clean_resume_text(file_bytes, content_type), MAX_RESUME_CHARS)
    requirement = _truncate_text(build_builder_requirement(target, tone, language, length, color_theme, sections), MAX_REQUIREMENT_CHARS)

    real_streamlit = sys.modules.get("streamlit")
    original_anchor_core_st = anchor_core.st
    mock_streamlit = _MockStreamlit()
    sys.modules["streamlit"] = mock_streamlit
    anchor_core.st = mock_streamlit

    try:
        html = anchor_core.generate_cv_builder(
            cleaned_resume, requirement, cv_format, _normalize_model(model), temperature,
            enhance=enhance, customization=None,
        )
        if isinstance(html, bytes):
            html = html.decode("utf-8")
        html = _normalize_unicode_text(html)
        html = _strip_empty_html_sections(html)
        cv_data_object = mock_streamlit.session_state.get("cv_data_object")
        if hasattr(cv_data_object, "model_dump"):
            cv_data = cv_data_object.model_dump()
        elif hasattr(cv_data_object, "dict"):
            cv_data = cv_data_object.dict()
        else:
            cv_data = None
        cv_data = _clean_cv_data(cv_data) if cv_data else None
        return {
            "html": html,
            "cv_data": cv_data,
            "has_suggested_metrics": bool(mock_streamlit.session_state.get("cv_has_suggested_metrics", False)),
            "color_hex": mock_streamlit.session_state.get("cv_color_hex", color_theme),
            "language": mock_streamlit.session_state.get("cv_language", language),
        }
    finally:
        anchor_core.st = original_anchor_core_st
        if real_streamlit is None:
            sys.modules.pop("streamlit", None)
        else:
            sys.modules["streamlit"] = real_streamlit


def export_pdf(html: str):
    from fastapi import HTTPException, Response

    def _read_pdf_bytes(value):
        if value is None:
            return b""
        if hasattr(value, "getvalue"):
            return value.getvalue()
        if isinstance(value, bytes):
            return value
        if hasattr(value, "read"):
            if hasattr(value, "seek"):
                value.seek(0)
            return value.read()
        return b""

    result = anchor_core.create_pdf_from_html(html)
    if result is None:
        raise HTTPException(status_code=500,
            detail="PDF generation returned None")
    try:
        pdf_bytes = _read_pdf_bytes(result)
    except Exception as e:
        raise HTTPException(status_code=500,
            detail=f"Cannot read PDF bytes: {e}")
    if len(pdf_bytes) < 500:
        raise HTTPException(status_code=500,
            detail=f"PDF too small ({len(pdf_bytes)} bytes)")
    if not pdf_bytes.startswith(b"%PDF-"):
        raise HTTPException(status_code=500,
            detail="PDF header missing")
    if not pdf_bytes.rstrip().endswith(b"%%EOF"):
        raise HTTPException(status_code=500,
            detail="PDF footer missing — file is incomplete")
    result.seek(0)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=document.pdf"}
    )


def export_docx(html: str = "", cv_data: dict | None = None):
    if html and html.strip():
        return create_docx_from_html(html)
    if cv_data:
        cv = anchor_core.CVData(**cv_data)
        return build_docx_from_cv_data(cv)
    raise ValueError("Either html or cv_data is required for DOCX export.")


def parse_sections_json(raw_sections: str) -> dict:
    if not raw_sections:
        return {
            "summary": True, "experience": True, "education": True,
            "skills": True, "projects": True, "publications": True,
            "languages": True, "certifications": True,
        }
    if isinstance(raw_sections, dict):
        return raw_sections
    parsed = json.loads(raw_sections)
    return {key: bool(value) for key, value in parsed.items()}
