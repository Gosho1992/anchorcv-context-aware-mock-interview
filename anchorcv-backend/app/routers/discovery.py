import asyncio
import hashlib
import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from openai import OpenAI
from pydantic import BaseModel, Field

from app.deps.auth import get_current_user, require_active_access
from app.services import legacy_bridge
from app.services.serper_search import serper_search
from app.services.llm import get_routed_client

router = APIRouter(prefix="/discover", tags=["discovery"])
logger = logging.getLogger(__name__)

CACHE_TTL_HOURS = 24
DAILY_LIMIT_FREE = 20
DAILY_LIMIT_PREMIUM = 500

PROGRAM_ALLOWLIST = [
    "DAAD", "Commonwealth Scholarship", "Chevening", "Fulbright",
    "Erasmus Mundus", "Marie Skłodowska-Curie Actions", "EPSRC", "NSERC",
    "JSPS", "KAUST", "Aga Khan Foundation", "OFID",
]

_DB_PATH = Path(__file__).resolve().parents[1] / "discovery_cache.db"


def _init_db() -> None:
    with sqlite3.connect(_DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS landscape_cache (
                query_hash   TEXT PRIMARY KEY,
                response_json TEXT NOT NULL,
                created_at   TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_calls (
                user_id TEXT NOT NULL,
                day     TEXT NOT NULL,
                count   INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, day)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS query_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    TEXT NOT NULL,
                query_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )


_init_db()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class Subfield(BaseModel):
    name: str
    description: str
    growing: bool
    hot_regions: List[str] = Field(default_factory=list)
    typical_roles: List[str] = Field(default_factory=list)
    distance_from_user: str   # "close" | "4-8 weeks" | "3-6 months" | "career shift"
    why: str


class AdjacentField(BaseModel):
    name: str
    description: str
    growing: bool
    distance_from_user: str
    why: str


class KnownOpportunity(BaseModel):
    title: str
    institution: str
    country: str
    type: str
    note: str
    link: Optional[str] = None


class SkillGap(BaseModel):
    skill: str
    importance: str
    time_to_acquire: str
    resources: List[str] = Field(default_factory=list)


class GapAnalysis(BaseModel):
    overall_fit: str
    fit_score: int
    strengths: List[str] = Field(default_factory=list)
    gaps: List[SkillGap] = Field(default_factory=list)
    time_to_readiness: str
    recommendation: str


class RegionalDemand(BaseModel):
    region: str
    demand_level: str
    trending: bool
    typical_salary: Optional[str] = None
    notes: str


class LearningPath(BaseModel):
    title: str
    steps: List[str]
    duration: str
    outcome: str


class LandscapeResponse(BaseModel):
    primary_field: str
    intent: str = "job"
    related_subfields: List[Subfield]
    adjacent_fields: List[AdjacentField]
    known_opportunities: List[KnownOpportunity]
    search_tags: List[str]
    summary: str
    gap_analysis: Optional[GapAnalysis] = None
    regional_demand: List[RegionalDemand] = Field(default_factory=list)
    learning_paths: List[LearningPath] = Field(default_factory=list)
    salary_insights: Optional[str] = None
    cached: bool = False


class LandscapeRequest(BaseModel):
    query: str
    intent: str = "job"
    bypass_cache: bool = False
    resume_text: Optional[str] = None


class ResumeExtractResponse(BaseModel):
    resume_text: str
    char_count: int
    filename: str


RESUME_TEXT_MAX_CHARS = 2000


# ---------------------------------------------------------------------------
# Cache + rate-limit helpers
# ---------------------------------------------------------------------------

def _hash_query(query: str, intent: str = "job", resume_text: str = "") -> str:
    normalized = f"{intent}::{query.strip().lower()}"
    if resume_text:
        fingerprint = " ".join(resume_text[:1000].lower().split())
        normalized = f"{normalized}||{fingerprint}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _get_cached(query_hash: str) -> Optional[dict]:
    cutoff = (datetime.utcnow() - timedelta(hours=CACHE_TTL_HOURS)).isoformat()
    with sqlite3.connect(_DB_PATH) as conn:
        row = conn.execute(
            "SELECT response_json FROM landscape_cache WHERE query_hash = ? AND created_at > ?",
            (query_hash, cutoff),
        ).fetchone()
    if not row:
        return None
    try:
        return json.loads(row[0])
    except Exception:
        return None


def _set_cache(query_hash: str, payload: dict) -> None:
    with sqlite3.connect(_DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO landscape_cache (query_hash, response_json, created_at) "
            "VALUES (?, ?, ?)",
            (query_hash, json.dumps(payload), datetime.utcnow().isoformat()),
        )


def _check_and_increment_quota(user_id: str, is_premium: bool) -> bool:
    limit = DAILY_LIMIT_PREMIUM if is_premium else DAILY_LIMIT_FREE
    today = datetime.utcnow().strftime("%Y-%m-%d")
    with sqlite3.connect(_DB_PATH) as conn:
        row = conn.execute(
            "SELECT count FROM daily_calls WHERE user_id = ? AND day = ?",
            (user_id, today),
        ).fetchone()
        current = int(row[0]) if row else 0
        if current >= limit:
            return False
        conn.execute(
            """
            INSERT INTO daily_calls (user_id, day, count) VALUES (?, ?, 1)
            ON CONFLICT(user_id, day) DO UPDATE SET count = count + 1
            """,
            (user_id, today),
        )
    return True


def _log_query(user_id: str, query_hash: str) -> None:
    with sqlite3.connect(_DB_PATH) as conn:
        conn.execute(
            "INSERT INTO query_log (user_id, query_hash, created_at) VALUES (?, ?, ?)",
            (user_id, query_hash, datetime.utcnow().isoformat()),
        )


# ---------------------------------------------------------------------------
# Intent-locked prompt builder
# The intent is the PRIMARY constraint — everything else is subordinate to it.
# ---------------------------------------------------------------------------

# Per-intent system prompt: what the model IS and what it must NOT do.
_SYSTEM_PROMPTS = {
    "phd": (
        "You are an academic career advisor specialising in doctoral programmes for international students. "
        "The user wants to find a PhD opportunity in a specific field — that field comes from their query. "
        "Your ENTIRE response must be about doctoral research within that exact queried field: "
        "research specialisations, active research areas, funded PhD positions, research groups, "
        "and funding schemes for PhDs (DAAD, Fulbright, EPSRC, NSERC, JSPS, Marie Skłodowska-Curie, KAUST). "
        "ABSOLUTE PROHIBITION: NEVER return results from a different field than the one queried. "
        "If the query is 'Electrical Engineering', every subfield must be an Electrical Engineering research area "
        "(e.g. Power Electronics, Control Systems, Electromagnetics, Signal Processing, Semiconductor Devices). "
        "NEVER suggest 'Data Analytics', 'Business Intelligence', 'Game Analytics', or any non-EE field for an EE query. "
        "If the student's CV is from a different field, that's fine — use it only to set distance_from_user and gap_analysis. "
        "NEVER suggest generic job titles (e.g. 'Data Analyst', 'Business Intelligence', 'Product Manager'). "
        "related_subfields must be PhD research specialisations within the queried field, NOT job roles. "
        "typical_roles must list doctoral career outcomes only (e.g. 'Postdoctoral Researcher', 'Academic Faculty', "
        "'R&D Scientist', 'Research Engineer'). "
        "known_opportunities must only list PhD-type grants from the verified allowlist. "
        "search_tags must include the queried field name + 'PhD', 'doctoral', 'funded position'. "
        "NEVER fabricate programme names."
    ),
    "masters": (
        "You are a graduate admissions advisor specialising in international Master's programmes. "
        "The user wants a Master's degree in a specific field — that field comes from their query. "
        "Your ENTIRE response must be about postgraduate study within that exact queried field: "
        "programme specialisations, reputable universities, admission requirements, "
        "tuition funding (DAAD, Erasmus Mundus, Commonwealth, Chevening, Fulbright), and career outcomes. "
        "ABSOLUTE PROHIBITION: NEVER return results from a different field than the one queried. "
        "If the CV shows a different background, use it only to set distance_from_user and gap_analysis — "
        "never to redirect what field or specialisations you return. "
        "related_subfields must be Master's specialisations within the queried field, NOT job roles. "
        "typical_roles must list what graduates in this specific field typically do after their MSc. "
        "known_opportunities must only list Master's-type scholarships from the verified allowlist. "
        "search_tags must include the queried field + 'MSc', 'Master', 'postgraduate'. "
        "NEVER fabricate programme names."
    ),
    "scholarship": (
        "You are a scholarship and funding advisor for international students. "
        "The user is specifically looking for scholarship or fellowship funding. "
        "Your ENTIRE response must be about funding: eligibility criteria, application strategy, "
        "award amounts, deadlines, and alternative funding sources. "
        "related_subfields must be scholarship tracks or funding categories relevant to the field "
        "(e.g. 'STEM Fellowships', 'Government-Sponsored Awards', 'University Bursaries'). "
        "known_opportunities must ONLY include verified scholarships from: "
        "DAAD, Commonwealth Scholarship, Chevening, Fulbright, Erasmus Mundus, "
        "Marie Skłodowska-Curie Actions, EPSRC, NSERC, JSPS, KAUST, Aga Khan Foundation, OFID. "
        "salary_insights is not applicable — instead use it to describe typical stipend amounts. "
        "search_tags must include 'scholarship', 'fellowship', 'funding', 'grant'. "
        "NEVER fabricate scholarship names."
    ),
    "bachelors": (
        "You are an undergraduate admissions advisor for international students. "
        "The user wants a Bachelor's degree. Your ENTIRE response must be about undergraduate study: "
        "programme specialisations, entry requirements, foundation years, international pathways, "
        "tuition costs, and undergraduate scholarships. "
        "NEVER suggest PhD positions or graduate-level programmes as primary recommendations. "
        "related_subfields must be undergraduate majors or specialisation tracks. "
        "typical_roles must list what graduates typically do after a Bachelor's in this field. "
        "known_opportunities may list any allowlist scholarships that fund undergraduate study. "
        "search_tags must include 'BSc', 'Bachelor', 'undergraduate', 'foundation year'. "
        "NEVER fabricate programme names."
    ),
    "job": (
        "You are a career advisor specialising in international job markets. "
        "The user is looking for employment opportunities in a specific field — that field comes from their query. "
        "Your ENTIRE response must be about the job market within that exact queried field. "
        "ABSOLUTE PROHIBITION: NEVER return results from a different field than the one queried. "
        "If the CV shows a different background, use it only to set distance_from_user and gap_analysis — "
        "never to redirect what field or roles you return. "
        "related_subfields must be specific in-demand roles or specialisations within the queried field. "
        "typical_roles must list concrete, real job titles in that field. "
        "known_opportunities may include any allowlist entries relevant to employment in this field. "
        "search_tags must include the queried field + role names and job board keywords. "
        "NEVER fabricate company names or invent roles that do not exist in this field."
    ),
}

# Per-intent field-level examples injected into the schema comment.
# This steers the model on what to put in each field.
_FIELD_EXAMPLES = {
    "phd": {
        "subfield_name": "e.g. 'Power Electronics & Smart Grids', 'Electromagnetic Compatibility', 'Control Systems'",
        "typical_roles": "e.g. 'Postdoctoral Researcher', 'Academic Faculty', 'R&D Scientist'",
        "distance_label": "competitiveness to secure a funded position",
        "distance_example": "e.g. 'close' = strong research fit, 'career shift' = major background mismatch",
        "opp_type": "PhD",
        "opp_example": "e.g. 'DAAD Research Grant – Electrical Engineering PhD, Germany'",
        "tag_example": "e.g. 'funded PhD power electronics Germany 2026', 'doctoral researcher smart grid ETH Zurich'",
        "region_note": "countries with top PhD programmes and funding in this field",
        "salary_note": "PhD stipend ranges (monthly/annual) in major research countries",
    },
    "masters": {
        "subfield_name": "e.g. 'Power Systems Engineering MSc', 'Renewable Energy Master's', 'Embedded Systems'",
        "typical_roles": "e.g. 'Graduate Engineer', 'Systems Analyst', 'Junior Researcher'",
        "distance_label": "likelihood of admission based on background",
        "distance_example": "e.g. 'close' = meets typical entry requirements",
        "opp_type": "Masters",
        "opp_example": "e.g. 'Erasmus Mundus Joint Master – Electrical Engineering'",
        "tag_example": "e.g. 'MSc electrical engineering Germany fully funded', 'Erasmus Mundus EE 2026'",
        "region_note": "countries with top Master's programmes and funding options",
        "salary_note": "typical graduate salaries after an MSc in this field",
    },
    "scholarship": {
        "subfield_name": "e.g. 'STEM Excellence Awards', 'Government-Sponsored Fellowships', 'University Merit Bursaries'",
        "typical_roles": "e.g. 'Scholarship Recipient', 'Funded Researcher', 'Fellow'",
        "distance_label": "your eligibility strength for this funding type",
        "distance_example": "e.g. 'close' = strong profile match for this award",
        "opp_type": "Scholarship",
        "opp_example": "e.g. 'DAAD Scholarship for International Students – Electrical Engineering'",
        "tag_example": "e.g. 'fully funded scholarship electrical engineering 2026', 'DAAD EE scholarship application'",
        "region_note": "countries with the most generous scholarship ecosystems for this field",
        "salary_note": "typical scholarship stipend amounts (monthly/annual)",
    },
    "bachelors": {
        "subfield_name": "e.g. 'Electrical & Electronic Engineering BSc', 'Mechatronics', 'Computer Engineering'",
        "typical_roles": "e.g. 'Graduate Engineer', 'Technician', 'Systems Designer'",
        "distance_label": "your readiness for undergraduate admission",
        "distance_example": "e.g. 'close' = meets entry requirements",
        "opp_type": "Masters",
        "opp_example": "e.g. 'Commonwealth Scholarship – BSc Pathway, UK'",
        "tag_example": "e.g. 'BSc electrical engineering Germany English-taught', 'undergraduate EE Netherlands tuition'",
        "region_note": "countries with affordable or English-taught undergraduate programmes",
        "salary_note": "typical tuition ranges; undergraduate stipends where applicable",
    },
    "job": {
        "subfield_name": "e.g. 'Power Systems Engineer', 'Embedded Systems Developer', 'Automation Engineer'",
        "typical_roles": "e.g. 'Power Engineer', 'Control Systems Engineer', 'Field Applications Engineer'",
        "distance_label": "how close you are to being job-ready in this area",
        "distance_example": "e.g. 'close' = ready to apply now",
        "opp_type": "Job",
        "opp_example": "e.g. 'Siemens Graduate Programme – Electrical Engineering'",
        "tag_example": "e.g. 'electrical engineer jobs Germany 2026', 'power systems engineer Netherlands salary'",
        "region_note": "strongest job markets for this role",
        "salary_note": "annual salary ranges by region for these roles",
    },
}

_GAP_LABELS = {
    "phd": {
        "strengths_hint": "research skills, publications, programming, lab experience",
        "gaps_hint": "missing methods, programming languages, domain knowledge gaps for the target research area",
        "readiness_hint": "time to prepare a competitive PhD application",
        "recommendation_hint": "specific steps to strengthen the PhD application",
    },
    "masters": {
        "strengths_hint": "academic background, relevant coursework, projects",
        "gaps_hint": "missing prerequisites, language requirements, GPA concerns",
        "readiness_hint": "time to meet entry requirements",
        "recommendation_hint": "specific steps to improve Master's application strength",
    },
    "scholarship": {
        "strengths_hint": "academic excellence, leadership, community engagement",
        "gaps_hint": "missing requirements, language scores, essay weaknesses",
        "readiness_hint": "time to prepare a competitive scholarship application",
        "recommendation_hint": "specific steps to strengthen the scholarship application",
    },
    "bachelors": {
        "strengths_hint": "secondary school grades, relevant subjects, extracurriculars",
        "gaps_hint": "missing A-level/IB subjects, language requirements",
        "readiness_hint": "time to meet undergraduate entry requirements",
        "recommendation_hint": "specific steps to meet entry requirements",
    },
    "job": {
        "strengths_hint": "technical skills, work experience, certifications",
        "gaps_hint": "missing tools, certifications, or domain knowledge",
        "readiness_hint": "time to become job-ready",
        "recommendation_hint": "specific steps to become a competitive candidate",
    },
}


def _build_prompts(query: str, intent: str, resume_text: str) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) for the given intent."""
    allowlist_str = ", ".join(PROGRAM_ALLOWLIST)
    has_resume = bool(resume_text)
    ex = _FIELD_EXAMPLES.get(intent, _FIELD_EXAMPLES["job"])
    gl = _GAP_LABELS.get(intent, _GAP_LABELS["job"])

    system_prompt = (
        _SYSTEM_PROMPTS.get(intent, _SYSTEM_PROMPTS["job"])
        + "\n\n"
        "CRITICAL RULE: The student's query determines the field. "
        "The CV (if provided) is ONLY used to calculate distance_from_user and gap_analysis. "
        "The CV must NEVER redirect or change the primary field or specialisations you return. "
        "If the query is 'Electrical Engineering' and the CV shows data analytics experience, "
        "you still return Electrical Engineering results — and use the CV mismatch to set "
        "honest distance_from_user values and gap_analysis.\n\n"
        f"Verified opportunity allowlist (ONLY use these for known_opportunities): {allowlist_str}. "
        "Return an empty known_opportunities list rather than inventing anything not on this list."
    )

    resume_section = ""
    if has_resume:
        resume_section = (
            "\n\n=== STUDENT CV — FOR DISTANCE AND GAP ANALYSIS ONLY ===\n"
            "USE THIS CV ONLY TO:\n"
            "  1. Set honest distance_from_user values for each subfield\n"
            "  2. Populate gap_analysis (strengths, gaps, readiness)\n"
            "  3. Personalise the 'why' field for each subfield\n"
            "DO NOT use the CV to change or redirect the primary field or specialisations.\n"
            f"{resume_text}\n"
            "=== END CV ===\n"
        )

    gap_block = ""
    if has_resume:
        gap_block = (
            '  "gap_analysis": {\n'
            '    "overall_fit": "strong | good | partial | stretch",\n'
            '    "fit_score": integer 0-100,\n'
            f'    "strengths": ["{gl["strengths_hint"]}"],\n'
            '    "gaps": [\n'
            '      {\n'
            '        "skill": "specific gap name",\n'
            '        "importance": "essential | helpful | nice-to-have",\n'
            '        "time_to_acquire": "e.g. 2-4 weeks",\n'
            f'        "resources": ["{gl["gaps_hint"]}"]\n'
            '      }\n'
            '    ],\n'
            f'    "time_to_readiness": "{gl["readiness_hint"]}",\n'
            f'    "recommendation": "{gl["recommendation_hint"]}"\n'
            "  },\n"
        )

    user_prompt = (
        # ── Query and intent FIRST so the model anchors on them ──
        f"FIELD (from student query): \"{query}\"\n"
        f"INTENT: {intent.upper()}\n\n"
        f"Generate a complete {intent} landscape for the field above. "
        "All specialisations, research areas, and opportunities must be within that field.\n"
        + resume_section
        + "\n"
        "Return ONLY valid JSON with this exact schema:\n"
        "{\n"
        '  "primary_field": "the specific academic or professional field",\n'
        f'  "intent": "{intent}",\n'
        '  "summary": "3-4 sentences of honest, helpful guidance written specifically for someone pursuing '
        f'a {intent}",\n'
        '  "related_subfields": [\n'
        "    {\n"
        f'      "name": "{ex["subfield_name"]}",\n'
        '      "description": "one sentence describing this specialisation",\n'
        '      "growing": true or false,\n'
        '      "hot_regions": ["country or city"],\n'
        f'      "typical_roles": ["{ex["typical_roles"]}"],\n'
        f'      "distance_from_user": "close | 4-8 weeks | 3-6 months | career shift  ({ex["distance_label"]}; {ex["distance_example"]})",\n'
        '      "why": "why this matches the student\'s background and intent"\n'
        "    }\n"
        "  ],\n"
        '  "adjacent_fields": [\n'
        "    {\n"
        '      "name": "adjacent specialisation or discipline",\n'
        '      "description": "one sentence",\n'
        '      "growing": true or false,\n'
        '      "distance_from_user": "4-8 weeks | 3-6 months | career shift",\n'
        '      "why": "why this is adjacent and worth considering"\n'
        "    }\n"
        "  ],\n"
        '  "known_opportunities": [\n'
        "    {\n"
        f'      "title": "{ex["opp_example"]}",\n'
        '      "institution": "institution name from allowlist only",\n'
        '      "country": "country",\n'
        f'      "type": "{ex["opp_type"]}",\n'
        '      "note": "one sentence of context. Verify on official site."\n'
        "    }\n"
        "  ],\n"
        f'  "search_tags": ["{ex["tag_example"]}", "10-15 entries total"],\n'
        '  "regional_demand": [\n'
        "    {\n"
        '      "region": "country or city",\n'
        '      "demand_level": "high | medium | low",\n'
        '      "trending": true or false,\n'
        f'      "typical_salary": "{ex["salary_note"]}",\n'
        f'      "notes": "{ex["region_note"]}"\n'
        "    }\n"
        "  ],\n"
        '  "learning_paths": [\n'
        "    {\n"
        f'      "title": "e.g. Prepare a competitive {intent} application",\n'
        '      "steps": ["step 1", "step 2", "step 3", "step 4"],\n'
        '      "duration": "e.g. 6-8 weeks",\n'
        '      "outcome": "what the student will achieve"\n'
        "    }\n"
        "  ],\n"
        + gap_block
        + f'  "salary_insights": "{ex["salary_note"]} — 2-3 sentences or null"\n'
        "}\n\n"
        "HARD RULES — violating any of these makes the response wrong:\n"
        f"0. MOST IMPORTANT: ALL results must be about \"{query}\". The CV (if any) does NOT change "
        f"the field. Every subfield, opportunity, and search tag must be within \"{query}\".\n"
        f"1. related_subfields: 4-6 entries. MUST be specialisations within \"{query}\". "
        + ("NEVER put generic job titles here." if intent != "job" else f"MUST be specific roles within {query}.")
        + "\n"
        "2. adjacent_fields: 2-3 entries of disciplines adjacent to the queried field (not the CV's field).\n"
        "3. known_opportunities: ONLY from the verified allowlist above. Return [] if nothing fits.\n"
        f"4. search_tags: 10-15 queries. Every tag must mention the queried field + {intent}-relevant keywords.\n"
        "5. regional_demand: 3-5 entries for the most relevant countries for this field.\n"
        "6. learning_paths: 1-2 practical paths with 4-6 ordered steps each.\n"
        + ("7. gap_analysis: REQUIRED. Assess how the student's CV bridges to the QUERIED field, not to their CV's field.\n" if has_resume
           else "7. gap_analysis: OMIT this field entirely — no CV was provided.\n")
        + "8. Be honest. 'close' means genuinely ready now, not aspirationally ready.\n"
        "9. No fabrications. Omit any field you are uncertain about."
    )

    return system_prompt, user_prompt


# ---------------------------------------------------------------------------
# Serper.dev (Google search) supplementary scholarship source
#
# known_opportunities is otherwise populated entirely by the LLM, constrained
# to the verified PROGRAM_ALLOWLIST above. search_scholarships_serper()
# supplements that with live search results so the list isn't limited to the
# ~12 allowlisted programmes, while the LLM/allowlist-derived list is always
# kept as a fallback so previously-verified programmes are never dropped.
# ---------------------------------------------------------------------------

async def search_scholarships_serper(field: str, country: str = "", level: str = "") -> List[dict]:
    """
    Search for live scholarship results via Serper.dev and map them to the
    same shape as KnownOpportunity (title, institution, country, type, note),
    plus a `link` back to the source page.
    """
    field = (field or "").strip()
    if not field:
        return []

    query_parts = [field, "scholarship"]
    if country and country.strip():
        query_parts.append(country.strip())
    if level and level.strip():
        query_parts.append(level.strip())
    query_parts.append("2026")
    query = " ".join(query_parts)

    organic = await serper_search(query, num_results=10)

    results: List[dict] = []
    seen_links: set[str] = set()
    for item in organic:
        title = (item.get("title") or "").strip()
        link = (item.get("link") or "").strip()
        if not title or not link or link in seen_links:
            continue
        seen_links.add(link)
        snippet = (item.get("snippet") or "").strip()

        results.append({
            "title": title,
            "institution": "",
            "country": country.strip() if country else "",
            "type": "Scholarship",
            "note": snippet[:300] or "Search result — verify details on the official site.",
            "link": link,
        })

    return results


def _merge_known_opportunities(serper_items: List[dict], existing: List[dict]) -> List[dict]:
    """
    Merge live Serper scholarship results with the existing (LLM/allowlist
    derived) known_opportunities. Serper results are listed first; the
    existing list is concatenated after and de-duplicated by title, so it
    acts as a fallback that is used as-is whenever Serper returns nothing or
    fails, and is otherwise preserved alongside the fresh results.
    """
    seen_titles: set[str] = set()
    merged: List[dict] = []
    for item in [*serper_items, *existing]:
        title_key = (item.get("title") or "").strip().lower()
        if not title_key or title_key in seen_titles:
            continue
        seen_titles.add(title_key)
        merged.append(item)
    return merged


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post("/landscape", response_model=LandscapeResponse)
def generate_landscape(
    payload: LandscapeRequest,
    user: dict = Depends(require_active_access),
):
    user_id = str(user.get("id") or "")
    is_premium = bool(user.get("is_premium"))

    if not _check_and_increment_quota(user_id, is_premium):
        raise HTTPException(
            status_code=429,
            detail=(
                "Daily discovery limit reached. Upgrade to premium for higher limits."
                if not is_premium else
                "Daily discovery limit reached. Please try again tomorrow."
            ),
        )

    query = (payload.query or "").strip()
    if len(query) < 3:
        raise HTTPException(status_code=400, detail="Query is too short.")
    if len(query) > 500:
        raise HTTPException(status_code=400, detail="Query is too long. Keep it under 500 characters.")

    intent = (payload.intent or "job").strip().lower()
    if intent not in {"job", "masters", "phd", "scholarship", "bachelors"}:
        intent = "job"

    resume_text = (payload.resume_text or "").strip()[:RESUME_TEXT_MAX_CHARS]
    query_hash = _hash_query(query, intent, resume_text)
    _log_query(user_id, query_hash)

    if not payload.bypass_cache:
        cached = _get_cached(query_hash)
        if cached:
            cached["cached"] = True
            cached.setdefault("intent", intent)
            cached.setdefault("regional_demand", [])
            cached.setdefault("learning_paths", [])
            try:
                serper_opportunities = asyncio.run(
                    search_scholarships_serper(query, country="", level=intent)
                )
            except Exception as exc:
                logger.warning("Serper scholarship search failed (cache path): %s", exc)
                serper_opportunities = []
            cached["known_opportunities"] = _merge_known_opportunities(
                serper_opportunities, cached.get("known_opportunities", [])
            )
            return LandscapeResponse.model_validate(cached)

    system_prompt, user_prompt = _build_prompts(query, intent, resume_text)

    client = get_routed_client()

    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            anchorcv_task="discovery_landscape",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.5,   # lower = more literal adherence to schema examples
            response_format={"type": "json_object"},
            max_tokens=3000,
        )
    except Exception as exc:
        logger.exception("LLM call failed for discovery query: %s", exc)
        raise HTTPException(status_code=502, detail="Discovery service is temporarily unavailable.") from exc

    raw_text = (completion.choices[0].message.content or "").strip()
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        logger.warning("Discovery JSON parse failed. raw=%s", raw_text[:500])
        raise HTTPException(
            status_code=502,
            detail="The discovery engine returned a malformed response. Please try again.",
        ) from exc

    raw.setdefault("intent", intent)
    raw.setdefault("regional_demand", [])
    raw.setdefault("learning_paths", [])
    raw.setdefault("salary_insights", None)
    raw.setdefault("gap_analysis", None)

    # Validate and strip distance_from_user descriptions if model added parenthetical
    for sf in raw.get("related_subfields", []):
        d = sf.get("distance_from_user", "")
        for clean in ("close", "4-8 weeks", "3-6 months", "career shift"):
            if d.startswith(clean):
                sf["distance_from_user"] = clean
                break

    try:
        validated = LandscapeResponse.model_validate({**raw, "cached": False})
    except Exception as exc:
        logger.warning("Discovery shape validation failed. raw=%s err=%s", raw, exc)
        raise HTTPException(
            status_code=502,
            detail="The discovery engine returned an unexpected shape. Please try again.",
        ) from exc

    try:
        serper_opportunities = asyncio.run(
            search_scholarships_serper(query, country="", level=intent)
        )
    except Exception as exc:
        logger.warning("Serper scholarship search failed: %s", exc)
        serper_opportunities = []

    if serper_opportunities:
        merged_opportunities = _merge_known_opportunities(
            serper_opportunities,
            [op.model_dump() for op in validated.known_opportunities],
        )
        validated.known_opportunities = [
            KnownOpportunity(**op) for op in merged_opportunities
        ]

    _set_cache(query_hash, validated.model_dump())
    return validated


# ---------------------------------------------------------------------------
# Resume extraction
# ---------------------------------------------------------------------------

ALLOWED_RESUME_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "text/plain",
}
MAX_RESUME_BYTES = 5 * 1024 * 1024


@router.post("/extract-resume", response_model=ResumeExtractResponse)
async def extract_resume(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided.")

    raw = await file.read()
    if len(raw) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(raw) > MAX_RESUME_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Keep it under {MAX_RESUME_BYTES // (1024 * 1024)} MB.",
        )

    content_type = (file.content_type or "").lower()
    name_lower = file.filename.lower()
    is_txt = name_lower.endswith(".txt") or content_type == "text/plain"
    is_pdf = name_lower.endswith(".pdf") or content_type == "application/pdf"
    is_docx = name_lower.endswith(".docx") or "wordprocessingml" in content_type

    if not (is_txt or is_pdf or is_docx):
        raise HTTPException(
            status_code=415,
            detail="Unsupported file type. Upload a PDF, DOCX, or TXT.",
        )

    try:
        text = legacy_bridge.extract_clean_resume_text(raw, content_type or "")
    except Exception as exc:
        logger.exception("Resume extraction failed for user_id=%s: %s", user.get("id"), exc)
        raise HTTPException(status_code=500, detail="Could not read the file.") from exc

    text = (text or "").strip()
    if not text:
        raise HTTPException(
            status_code=422,
            detail="No readable text in the file. If it is a scanned PDF, try a text-based PDF or DOCX.",
        )

    truncated = text[: RESUME_TEXT_MAX_CHARS * 2]

    logger.info(
        "extract_resume ok: user_id=%s filename=%s bytes=%s chars_returned=%s",
        user.get("id"),
        file.filename,
        len(raw),
        len(truncated),
    )

    return ResumeExtractResponse(
        resume_text=truncated,
        char_count=len(truncated),
        filename=file.filename,
    )
