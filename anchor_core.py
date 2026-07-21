# resume_transformer_pro.py
import streamlit as st
import requests
import pdfplumber
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.style import WD_STYLE_TYPE
import pytesseract
from PIL import Image
from io import BytesIO
import json
import re
import time
import base64
import tempfile
import os
import html
import platform
import shutil
import hashlib
from datetime import datetime
import openai
from openai import OpenAI
import plotly.graph_objects as go
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.units import inch
import markdown2
from bs4 import BeautifulSoup
import textwrap
from docxtpl import DocxTemplate

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ''''''''''''''''''''â€œ''''''''''''''' FIX: Only set Tesseract path on Windows '''''''''''''''''''''''''''''''''''''' avoids crash on Linux/Mac deployments
if platform.system() == "Windows":
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

from docx_fix import build_docx_from_cv_data, create_docx_from_text

# ----------------------------
# Initialize OpenAI Client (cached in session state)
# ----------------------------
def init_openai_client():
    """
    Return a cached OpenAI client stored in session state.
    Re-creates the client only when the API key changes.
    This avoids reconstructing the client on every AI call.
    """
    api_key = st.session_state.get("openai_api_key", "") or os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return None

    # Cache client; only rebuild when key changes
    if (
        st.session_state.get("_openai_client") is None
        or st.session_state.get("_cached_api_key") != api_key
    ):
        try:
            st.session_state["_openai_client"] = OpenAI(api_key=api_key)
            st.session_state["_cached_api_key"] = api_key
        except Exception as e:
            st.error(f"Error initializing OpenAI client: {e}")
            return None

    return st.session_state["_openai_client"]

# ----------------------------
# Configuration
# ----------------------------
MODEL_OPTIONS = {
    "GPT-4o Mini": "gpt-4o-mini",
    "GPT-4 Turbo": "gpt-4o-mini",
    "GPT-3.5 Turbo": "gpt-3.5-turbo-1106",
    "GPT-3.5": "gpt-3.5-turbo-instruct"
}

from pydantic import BaseModel
from typing import List, Dict, Optional, Any  # Added Any to imports

class CVData(BaseModel):
    # ---------- Personal ----------
    name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin: str = ""

    # ---------- Professional Summary ----------
    summary: str = ""

    # ---------- Skills ----------
    # e.g. {"Machine Learning": ["Clustering", "NLP"], "Programming": ["Python", "SQL"]}
    skills: Dict[str, List[str]] = {}

    # ---------- Experience ----------
    # each: title, company, location, start_date, end_date, bullets[]
    experience: List[Dict] = []

    # ---------- Education ----------
    # each: degree, institution, location, start_date, end_date, gpa, thesis
    education: List[Dict] = []

    # ---------- Projects ----------
    # each: name, description, bullets[]
    projects: List[Dict] = []

    # ---------- Publications ----------
    publications: List[str] = []

    # ---------- Certifications ----------
    # each: name, issuer, year
    certifications: List[Dict] = []

    # ---------- NEW: Extras ----------
    awards: List[str] = []

    # each: name, date, location, description?
    conferences: List[Dict] = []

    # each: name, date, location, description?
    seminars: List[Dict] = []

    # each: organization, role, start_date, end_date, bullets?
    volunteer: List[Dict] = []

    # e.g. [{"language": "English", "proficiency": "Fluent"}]
    languages: List[Dict] = []
     
    # NEW: Dynamic sections that AI can create
    additional_sections: Dict[str, List[str]] = {}  # e.g., {"PROFESSIONAL REGISTRATION": ["PEC: BioMed-954"]}

    # Metadata for AI decisions - FIXED: changed 'any' to 'Any'
    content_analysis: Dict[str, Any] = {}  # What the AI observed

   
def analyze_and_adapt_template(template_path: str, cv_data: CVData, resume_text: str) -> str:
    """
    AI analyzes resume content and dynamically adapts the template
    """
    client = init_openai_client()
    
    # Read original template
    with open(template_path, 'r', encoding='utf-8') as f:
        original_template = f.read()
    
    # Convert CV data to JSON
    cv_json = json.dumps(cv_data.model_dump(), indent=2)
    
    system_prompt = """You are a CV template adaptation expert. Your task is to:
1. Analyze the resume content and CV data
2. Determine what sections are NEEDED based on the content
3. Modify the template dynamically to include ALL relevant sections
4. Ensure country-specific information (PEC, Thai licenses) is properly labeled
5. Keep the template's existing style and formatting

The template uses Jinja2 syntax with variables like {{ name }}, {% for job in experience %}, etc.
You can ADD new sections, REORDER existing ones, or MODIFY section titles based on content.

Return ONLY the modified Jinja2 template."""
    
    user_prompt = f"""
ORIGINAL TEMPLATE:
{original_template}

EXTRACTED CV DATA:
{cv_json}

FULL RESUME TEXT:
{resume_text}

INSTRUCTIONS:
1. Identify ALL important information in the resume
2. Create appropriate sections for any information that doesn't fit existing template sections
3. For professional registrations:
   - If Pakistan: use "PEC Registration" or "Pakistan Engineering Council"
   - If Thailand: use "Thai Engineering License" or appropriate local term
   - Use country-appropriate terminology
4. Add sections for:
   - Workshops/Conferences if 3+ items
   - Research Supervision if any
   - Grants/Funding if any
   - Awards if any
   - Committees if any
   - Teaching Responsibilities if extensive
5. Keep the same styling (colors, borders, fonts)
6. Maintain all existing Jinja2 syntax

Return ONLY the modified template."""
    
    response = client.chat.completions.create(
        model="gpt-4-turbo",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.3
    )
    
    adapted_template = response.choices[0].message.content
    return adapted_template

def enhance_cv_data(cv_data: CVData, resume_text: str, requirement_text: str = "", mode: str = "safe", system_prompt_suffix: str = "") -> CVData:
    """
    Enhance extracted CV data BEFORE template rendering.
    mode:
      - "safe": only safe defaults + light normalization (no AI)
      - "ai": safe defaults + AI polish (still no new facts)
    """

    # --------------------------
    # Helpers (local)
    # --------------------------
    def detect_phd_status(text: str) -> str:
        t = (text or "").lower()
        if "phd" in t and ("course work completed" in t or "coursework completed" in t):
            return "coursework_completed"
        if "phd" in t and ("in progress" in t or "ongoing" in t or "candidate" in t):
            return "in_progress"
        if "phd" in t and ("awarded" in t or "completed" in t):
            return "completed"
        return "unknown"

    def enforce_no_phd_upgrade_on_cvdata(obj: CVData, text: str) -> CVData:
        phd_status = detect_phd_status(text)

        # Fix education degree wording
        if obj.education and isinstance(obj.education, list):
            for edu in obj.education:
                deg = (edu.get("degree") or "")
                if "phd" in deg.lower():
                    if phd_status == "coursework_completed":
                        edu["degree"] = "PhD (coursework completed)"
                    elif phd_status == "in_progress":
                        edu["degree"] = "PhD (in progress)"
                    # if completed explicitly in resume, keep PhD
                    break

        # Fix summary (remove "holds a phd" style claims)
        if obj.summary:
            s = obj.summary
            # normalize common risky phrases
            s_low = s.lower()
            if "holds a phd" in s_low or "phd holder" in s_low or "completed phd" in s_low:
                if phd_status == "coursework_completed":
                    # Replace only the dangerous wording (keep rest)
                    s = re.sub(r'(?i)holds a phd', 'PhD coursework completed', s)
                    s = re.sub(r'(?i)phd holder', 'PhD coursework completed', s)
                    s = re.sub(r'(?i)completed phd', 'PhD coursework completed', s)
            obj.summary = s

        return obj

    def enforce_no_phd_upgrade_on_dict(d: dict, text: str) -> dict:
        phd_status = detect_phd_status(text)

        # Education fix
        edu_list = d.get("education") or []
        if isinstance(edu_list, list):
            for edu in edu_list:
                if isinstance(edu, dict):
                    deg = (edu.get("degree") or "")
                    if "phd" in deg.lower():
                        if phd_status == "coursework_completed":
                            edu["degree"] = "PhD (coursework completed)"
                        elif phd_status == "in_progress":
                            edu["degree"] = "PhD (in progress)"
                        break
        d["education"] = edu_list

        # Summary fix
        summary = d.get("summary") or ""
        if isinstance(summary, str):
            s_low = summary.lower()
            if phd_status == "coursework_completed" and (
                "holds a phd" in s_low or "phd holder" in s_low or "completed phd" in s_low
            ):
                summary = re.sub(r'(?i)holds a phd', 'PhD coursework completed', summary)
                summary = re.sub(r'(?i)phd holder', 'PhD coursework completed', summary)
                summary = re.sub(r'(?i)completed phd', 'PhD coursework completed', summary)
                d["summary"] = summary

        return d

    def extract_requirement_rewrites(text: str) -> list[dict]:
        if not text:
            return []

        rewrites = []
        current_before = None

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            before_match = re.match(r"(?i)^before\s*:\s*(.+)$", line)
            after_match = re.match(r"(?i)^after\s*:\s*(.+)$", line)

            if before_match:
                current_before = before_match.group(1).strip()
                continue

            if after_match and current_before:
                after_text = after_match.group(1).strip()
                if after_text:
                    rewrites.append({"before": current_before, "after": after_text})
                current_before = None

        return rewrites

    # --------------------------
    # 1) SAFE RULE-BASED ENHANCEMENT (always)
    # --------------------------
    phd_status = detect_phd_status(resume_text)

    # A) Summary (safe)
    if not (cv_data.summary or "").strip():
        title_hint = ""
        if cv_data.experience and isinstance(cv_data.experience, list) and len(cv_data.experience) > 0:
            first_title = (cv_data.experience[0].get("title") or "").strip()
            if first_title:
                title_hint = first_title

        edu_hint = ""
        if cv_data.education and isinstance(cv_data.education, list) and len(cv_data.education) > 0:
            top_degree = (cv_data.education[0].get("degree") or "").strip()
            if top_degree:
                edu_hint = top_degree

        skill_hint = ""
        if cv_data.skills and isinstance(cv_data.skills, dict):
            flat = []
            for _, items in cv_data.skills.items():
                if isinstance(items, list):
                    flat.extend([str(x).strip() for x in items if str(x).strip()])
            if flat:
                skill_hint = ", ".join(flat[:4])

        summary_parts = []
        if title_hint:
            summary_parts.append(f"{title_hint} with experience in academic and professional responsibilities.")
        if edu_hint:
            # Prevent risky PhD completion language
            if "phd" in edu_hint.lower() and phd_status == "coursework_completed":
                edu_hint = "PhD (coursework completed)"
            summary_parts.append(f"Educational background includes {edu_hint}.")
        if skill_hint:
            summary_parts.append(f"Skilled in {skill_hint}.")

        cv_data.summary = " ".join(summary_parts).strip() or "Professional with academic background and teaching/research exposure."

    # B) Experience bullets (safe)
    # NOTE: Do NOT add generic fallback bullets. If the CV has no bullets for a role,
    # leave the list empty '''''''''''''''''''''''''''''''''''''' the template will skip bullet rendering cleanly.
    GENERIC_PHRASES = [
        "performed role responsibilities",
        "maintained documentation and coordinated",
        "supported team and organizational objectives",
        "research work inferred from",
        "conducted research activities aligned with publication",
        "prepared and contributed to manuscript development",
    ]
    if cv_data.experience and isinstance(cv_data.experience, list):
        for exp in cv_data.experience:
            bullets = exp.get("bullets", [])
            if not isinstance(bullets, list):
                exp["bullets"] = []
            else:
                exp["bullets"] = [
                    b for b in bullets
                    if b and not any(g in str(b).lower() for g in GENERIC_PHRASES)
                ]

    # C) Skills normalization (safe)
    if not isinstance(cv_data.skills, dict):
        cv_data.skills = {}

    fixed_skills = {}
    for cat, items in (cv_data.skills or {}).items():
        cat_name = str(cat).strip() if cat else "Skills"
        if not cat_name:
            cat_name = "Skills"
        if isinstance(items, list):
            clean_items = [str(x).strip() for x in items if str(x).strip()]
        elif items is None:
            clean_items = []
        else:
            clean_items = [str(items).strip()]
        fixed_skills[cat_name] = clean_items
    cv_data.skills = fixed_skills

    # ''''''''''''''''''''â€œ''''''''''''''' D1) Research Interests mapping (safe, schema-friendly)
    # Put into skills category "Research Interests"
    t = (resume_text or "").lower()
    if "research interests" in t:
        cv_data.skills.setdefault("Research Interests", [])
        if "theoretical plasma physics" in t and "Theoretical plasma physics" not in cv_data.skills["Research Interests"]:
            cv_data.skills["Research Interests"].append("Theoretical plasma physics")

    # D2) Research bridging via publications '''''''''''''''''''''''''''''''''''''' DO NOT add filler research project.
    # Publications section already handles this. No synthetic "Research" entry needed.

    # ''''''''''''''''''''â€œ''''''''''''''' Enforce no PhD upgrade on the safe-enhanced object
    cv_data = enforce_no_phd_upgrade_on_cvdata(cv_data, resume_text)

    # --------------------------
    # 2) OPTIONAL AI POLISH (mode == "ai")
    # --------------------------
    if mode != "ai":
        return cv_data

    client = init_openai_client()
    if not client:
        return cv_data

    data_dict = cv_data.model_dump() if hasattr(cv_data, "model_dump") else cv_data.dict()
    rewrite_pairs = extract_requirement_rewrites(requirement_text)
    rewrite_block = "\n".join(
        [
            f"{index}. BEFORE: {pair['before']}\n   AFTER: {pair['after']}"
            for index, pair in enumerate(rewrite_pairs, start=1)
        ]
    ) or "No explicit BEFORE/AFTER rewrite pairs detected."

    system_prompt = """
You are a CV enhancement expert.

STRICT RULES (NO EXCEPTIONS):
1) Do NOT add any new facts not present in the resume text.
2) Do NOT upgrade education status.
   - If PhD is not explicitly stated as completed/awarded, NEVER write "Holds a PhD", "PhD holder", or imply completion.
   - If resume says "PhD coursework completed", keep that exact meaning.
3) You may only:
   - rewrite wording for clarity and impact,
   - reorganize existing info,
   - suggest estimated metrics ONLY if clearly implied in the resume  â†’  and ALWAYS wrap them in [SUGGESTED: ...] tags.
     Example: "Reduced reporting time [SUGGESTED: by ~40%]"  â†’  the candidate must verify before sending.
   - Never invent specific percentages, hours, or numbers that have NO basis in the original text.
4) Keep the EXACT schema keys.
5) Summary must be 2 â†’ 3 sentences and must not invent credentials.
6) EMPTY SECTIONS: If a section has no data (publications, projects, languages), set it to null or empty list  â†’  do NOT write "No publications listed", "Not specified", or similar placeholder text.
7) Education dates: If start/end year is unknown, use empty string ""  â†’  do NOT write " â†’ " or "Unknown".
Return JSON only.
"""

    user_prompt = f"""
RESUME TEXT:
{resume_text}

CURRENT CV JSON:
{json.dumps(data_dict, indent=2)}

OPTIONAL REQUIREMENTS:
{requirement_text}

TASK:
Polish this CV JSON under the strict rules. Return ONLY JSON with the same schema.
"""

    system_prompt = """
You are a CV enhancement expert who has read 10,000+ CVs from real candidates across industries and countries. You know that AI-written bullet points all sound the same, and your job is to ensure this CV sounds like a specific human wrote it.

STRICT RULES (NO EXCEPTIONS):
1) Do NOT add any new facts not present in the resume text.
2) Do NOT upgrade education status.
   - If PhD is not explicitly stated as completed or awarded, never imply completion.
   - If the resume says "PhD coursework completed", keep that exact meaning.
3) You may only:
   - rewrite wording for clarity and impact,
   - reorganize existing info,
   - suggest estimated metrics only if clearly implied in the resume and always wrap them in [SUGGESTED: ...] tags,
   - never invent specific percentages, hours, or numbers that have no basis in the original text.
4) Keep the exact schema keys.
5) Summary must be 2 to 3 sentences and must not invent credentials.
6) If a section has no data, return an empty list, empty dict, or empty string. Do not emit placeholder text.
7) If education dates are unknown, use empty strings.
8) The requirement field may contain mandatory rewrite instructions from prior analysis.
   - If it includes BEFORE/AFTER rewrites, apply each AFTER rewrite to the matching summary, experience bullet, project description, or skills wording.
   - Treat those rewrites as required edits, not optional suggestions.
   - If the rewrite conflicts with the current CV JSON wording, prefer the rewrite wording as long as it does not introduce facts absent from the resume.
   - Do NOT ignore a valid rewrite just because the raw resume wording already exists in the JSON.

9) BULLET POINT DIVERSITY — Every bullet in experience and projects MUST vary in structure. Across the entire CV, use AT LEAST FIVE different structures from this list:
   a) [Result] by [action] — e.g. "Cut customer churn 22% by redesigning the onboarding flow"
   b) [Action] to [result], using [tool/method] — e.g. "Rebuilt the recommendation engine with PyTorch, doubling click-through rates"
   c) [Context/problem] → [action taken] → [outcome] — e.g. "When the legacy pipeline failed during peak traffic, built a replacement in 48 hours that handled 3x load"
   d) [Tool/method] used to [achieve outcome] for [stakeholder] — e.g. "Used Tableau to build C-suite dashboards that replaced a 40-hour monthly reporting process"
   e) Led/mentored/managed [people or process] — [quantified outcome] — e.g. "Mentored 4 interns who all converted to full-time, and standardised the onboarding documentation"
   f) [Skill] applied to [domain problem] — [specific result] — e.g. "Applied NLP to customer support tickets, surfacing the top 5 friction points that shaped the Q3 roadmap"
   g) [Action] that [saved/earned/grew] [metric] over [time period] — e.g. "Automated invoice reconciliation, saving 15 hours per week and reducing errors to near zero"
   AUDIT YOUR OUTPUT: If two consecutive bullets use the same structure, rewrite one. If more than 40% of bullets start with the same verb, diversify them.

10) WEAK VERB BAN — Never use these as bullet openers unless followed by a specific, surprising result:
    "Assisted with" / "Participated in" / "Helped" / "Worked on" / "Responsible for" / "Involved in"
    Replace with: built, led, designed, shipped, analysed, scaled, automated, authored, negotiated, launched, reduced, grew, taught.

11) METRIC PLACEMENT — Metrics must appear EARLY in the bullet, not buried at the end.
    WEAK:   "Improved system performance through optimisation, resulting in 40% faster load times"
    STRONG: "Cut load times 40% by migrating from REST to GraphQL and adding Redis caching"
    If a metric is [SUGGESTED], place it where it has the most impact — usually right after the verb.

12) HONESTY IN SCOPE — If the resume describes a group project or team achievement, the bullet must reflect shared credit:
    - "Part of a 5-person team that..."
    - "Co-led..."
    - "Contributed to..."
    - "Owned [specific component] within a team that..."
    NEVER attribute a team achievement solely to the individual candidate.

13) LANGUAGE ABILITY — Only keep or add a language in the "languages" list when the resume
    explicitly states the candidate speaks, knows, is fluent in, or has a proficiency rating for it.
    NEVER infer language ability from: project names, product/system locale, customer market,
    dataset language, client geography, NLP model language, or automation behavior.
    If a language is currently in the JSON but has NO explicit evidence in the resume text, REMOVE it.
    INVALID:  "Spanish-language booking agent"  -> remove Spanish (system language, not candidate ability)
    INVALID:  "French NLP model"                -> remove French (model language, not candidate ability)
    VALID:    "Fluent in Spanish"               -> keep Spanish
    VALID:    "Languages: Arabic (Native)"      -> keep Arabic

Return JSON only.
"""

    user_prompt = f"""
RESUME TEXT:
{resume_text}

CURRENT CV JSON:
{json.dumps(data_dict, indent=2)}

REQUIREMENTS AND BUILDER GUIDANCE:
{requirement_text}

MANDATORY REWRITE PAIRS TO APPLY:
{rewrite_block}

TASK:
Polish this CV JSON under the strict rules.
Apply every valid rewrite pair above to the closest matching content in the JSON.
If a BEFORE phrase appears in experience bullets, projects, summary, or skills wording, replace it with the AFTER version or the closest faithful adaptation.
Ensure bullet point diversity — use at least 5 different structures from rule 9. Audit consecutive bullets before finalising.
Return ONLY JSON with the same schema.
"""

    # ── Localisation + seniority calibration ─────────────────────────────────
    try:
        from app.localisation import build_localisation_block, build_seniority_block
        system_prompt += build_localisation_block(requirement_text or "")
        system_prompt += build_seniority_block(resume_text or "")
    except Exception:
        pass  # Localisation module unavailable — continue without it

    if system_prompt_suffix:
        system_prompt += "\n" + system_prompt_suffix.strip() + "\n"

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.4,
            max_tokens=3000
        )

        enhanced = resp.choices[0].message.content
        enhanced_data = json.loads(enhanced)

        # ''''''''''''''''''''â€œ''''''''''''''' Post-check 1: enforce no PhD upgrade
        enhanced_data = enforce_no_phd_upgrade_on_dict(enhanced_data, resume_text)

        # ''''''''''''''''''''â€œ''''''''''''''' Post-check 2: Remove empty placeholder sections
        EMPTY_PLACEHOLDERS = {
            "no publications", "no projects", "not specified",
            "none listed", "n/a", "none", " â†’ ", "-", ""
        }
        for section in ["publications", "projects", "languages"]:
            val = enhanced_data.get(section)
            if isinstance(val, list):
                # Remove items that are just placeholder strings
                cleaned = [
                    item for item in val
                    if str(item).strip().lower() not in EMPTY_PLACEHOLDERS
                    and str(item).strip() != ""
                ]
                enhanced_data[section] = cleaned if cleaned else []
            elif isinstance(val, str) and val.strip().lower() in EMPTY_PLACEHOLDERS:
                enhanced_data[section] = []

        # ''''''''''''''''''''â€œ''''''''''''''' Post-check 3: Fix blank education dates '''''''''''''''''''''''''''''''''''''' "'''''''''''''''''''''''''''''''''''''''" ''''''''''''''''''''''''''''''''''''''''' ""
        for edu in (enhanced_data.get("education") or []):
            if isinstance(edu, dict):
                for date_field in ["start_date", "end_date", "year", "dates"]:
                    if edu.get(date_field) in [" â†’ ", "-", "Unknown", "unknown"]:
                        edu[date_field] = ""

        # ''''''''''''''''''''â€œ''''''''''''''' Post-check 4: Flag [SUGGESTED:] metrics in session state for UI warning
        all_bullets = []
        for exp in (enhanced_data.get("experience") or []):
            if isinstance(exp, dict):
                all_bullets.extend(exp.get("bullets") or [])
        has_suggested = any("[SUGGESTED:" in str(b) for b in all_bullets)
        if has_suggested:
            st.session_state["cv_has_suggested_metrics"] = True
        else:
            st.session_state["cv_has_suggested_metrics"] = False

        # ──────────────────────────────────────────── Post-check 5: Re-validate languages
        # The AI enhance pass may have retained or re-introduced unevidenced languages.
        # Run the same deterministic gate used after extraction.
        enhanced_data["languages"] = _validate_languages(
            enhanced_data.get("languages") or [], resume_text
        )

        return CVData(**enhanced_data)

    except Exception as e:
        st.warning(f"AI polish failed: {e}. Using safe-enhanced version.")
        return cv_data
# ----------------------------
# Text extraction helpers
# ----------------------------
def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract text from PDF files"""
    text_parts = []
    try:
        with pdfplumber.open(BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                if page_text.strip():
                    text_parts.append(page_text)
    except Exception as e:
        st.error(f"Error extracting PDF: {e}")
        return ""
    return "\n\n".join(text_parts).strip()

def extract_text_from_docx(file_bytes: bytes) -> str:
    """Extract text from DOCX files including tables"""
    try:
        doc = Document(BytesIO(file_bytes))
        text_parts = []
        
        # Extract from paragraphs
        for paragraph in doc.paragraphs:
            if paragraph.text and paragraph.text.strip():
                text_parts.append(paragraph.text.strip())
        
        # Extract from tables
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    if cell.text and cell.text.strip():
                        text_parts.append(cell.text.strip())
        
        return "\n".join(text_parts)
    except Exception as e:
        st.error(f"Error extracting DOCX: {e}")
        return ""

from io import BytesIO
import re

def is_html(content: str) -> bool:
    if not content:
        return False
    c = content.strip().lower()
    return (
        c.startswith("<!doctype html") or c.startswith("<html") or c.startswith("<div")
        or bool(re.search(r"<(div|p|span|h1|h2|ul|li)\b", c))
    )

def wrap_html_for_print(body_html: str) -> str:
    # Adds a basic HTML shell so PDF printing is consistent
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="utf-8">
      <style>
        @page {{
          size: A4;
          margin: 18mm;
        }}
        body {{
          font-family: Arial, sans-serif;
          font-size: 12px;
          color: #111;
        }}
      </style>
    </head>
    <body>
      {body_html}
    </body>
    </html>
    """


def ensure_printable_html(html_content: str) -> str:
    html_content = (html_content or "").strip()
    if not html_content:
        return wrap_html_for_print("<div>No content to export.</div>")

    if not is_html(html_content):
        safe_text = html.escape(html_content).replace("\n", "<br>")
        return wrap_html_for_print(f"<div>{safe_text}</div>")

    if html_content.lower().startswith("<!doctype html") or html_content.lower().startswith("<html"):
        if "charset=" not in html_content.lower():
            return html_content.replace("<head>", '<head><meta charset="utf-8">', 1) if "<head>" in html_content.lower() else wrap_html_for_print(html_content)
        return html_content

    return wrap_html_for_print(html_content)
def strip_html(html: str) -> str:
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text("\n")
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return text
    except Exception:
        text = re.sub(r"<[^>]+>", "", html or "")
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return text

_PDF_CONTRAST_CSS = (
    "<style id='anchorcv-pdf-contrast'>"
    "html,body{background:#ffffff !important;}"
    "*,*::before,*::after{color:#1a1a1a !important;border-color:#cccccc !important;}"
    "h1,h2,h3,h4,h5,h6,th,strong,b{color:#000000 !important;}"
    "a{color:#0b3d91 !important;}"
    "</style>"
)


def _inject_pdf_contrast(html_doc: str) -> str:
    """Force dark, readable text colours into any HTML sent to the PDF renderer.
    Screen HTML carries dark-theme inline colours (near-white body, muted grey)
    that are invisible on a white PDF page; this override wins via !important
    regardless of per-element inline styles. Applied centrally so every PDF
    export path (canvas, analysis, templates, builder) is covered uniformly.
    """
    if not html_doc:
        return html_doc
    css = _PDF_CONTRAST_CSS
    low = html_doc.lower()
    idx = low.rfind('</head>')
    if idx != -1:
        return html_doc[:idx] + css + html_doc[idx:]
    m = re.search(r'<body[^>]*>', html_doc, re.IGNORECASE)
    if m:
        return html_doc[:m.end()] + css + html_doc[m.end():]
    return css + html_doc


def create_pdf_from_html(html_content: str) -> BytesIO:
    try:
        import pdfkit
        wkhtmltopdf_path = shutil.which("wkhtmltopdf") or r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe"
        if not os.path.exists(wkhtmltopdf_path):
            raise FileNotFoundError(f"wkhtmltopdf not found at {wkhtmltopdf_path}")
        config = pdfkit.configuration(wkhtmltopdf=wkhtmltopdf_path)
        printable_html = ensure_printable_html(html_content)
        printable_html = _inject_pdf_contrast(printable_html)
        options = {
            "encoding": "UTF-8",
            "enable-local-file-access": None,
            "quiet": "",
            "no-pdf-compression": None,
            "page-size": "A4",
            "margin-top": "18mm",
            "margin-bottom": "18mm",
            "margin-left": "18mm",
            "margin-right": "18mm",
        }
        pdf_bytes = pdfkit.from_string(
            printable_html,
            False,
            configuration=config,
            options=options,
        )
        if not pdf_bytes:
            raise ValueError("wkhtmltopdf returned empty bytes")
        if len(pdf_bytes) < 500:
            raise ValueError(f"PDF too small: {len(pdf_bytes)} bytes")
        if not pdf_bytes.startswith(b"%PDF-"):
            raise ValueError("Missing PDF header")
        if not pdf_bytes.rstrip().endswith(b"%%EOF"):
            raise ValueError("Missing PDF footer")
        return BytesIO(pdf_bytes)
    except Exception as e:
        print(f"[PDF Generation Error] Primary method failed: {e}")
        text_content = strip_html(html_content)
        fallback_pdf = create_pdf_from_text(text_content)
        if fallback_pdf is None:
            raise RuntimeError("Both wkhtmltopdf and fallback PDF generation failed.")
        return fallback_pdf

def sanitize_for_xml(text):
    """Remove XML-invalid control characters from text."""
    if not text:
        return text
    # XML 1.0 allowed characters: #x9 | #xA | #xD | [#x20-#xD7FF] | [#xE000-#xFFFD] | [#x10000-#x10FFFF]
    # We'll strip all control chars except tab, newline, carriage return.
    import re
    # Remove control characters that are not whitespace
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)



def extract_text_from_image(file_bytes: bytes) -> str:
    """Extract text from image files using OCR"""
    try:
        image = Image.open(BytesIO(file_bytes))
        text = pytesseract.image_to_string(image)
        return text.strip()
    except Exception as e:
        st.error(f"Error extracting image text: {e}")
        return ""

def extract_text_from_file(file_bytes: bytes, mime_type: str) -> str:
    """Generic text extraction function"""
    if mime_type == "application/pdf":
        return extract_text_from_pdf(file_bytes)
    elif mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return extract_text_from_docx(file_bytes)
    elif mime_type in ["image/png", "image/jpeg", "image/jpg"]:
        return extract_text_from_image(file_bytes)
    elif mime_type == "text/plain":
        return file_bytes.decode('utf-8').strip()
    else:
        return ""

def clean_text(text: str) -> str:
    """Simple text cleaning"""
    if not text:
        return ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)

def detect_country_from_requirement(requirement_text: str):
    """Best-effort country/region guess from the requirement text"""
    if not requirement_text:
        return None

    t = requirement_text.lower()
    checks = [
        ("Germany", [" germany", " berlin", " munich", " hamburg", " frankfurt", " deutschland"]),
        ("Pakistan", [" pakistan", " lahore", " karachi", " islamabad", " rawalpindi"]),
        ("United States", [" usa", " u.s.", " united states", " us ", " new york", " california", " federal resume", " gov "]),
        ("United Kingdom", [" uk", " u.k.", " united kingdom", " england", " london", " britain", " scotland", " wales"]),
        ("Canada", [" canada", " toronto", " vancouver", " ottawa", " montreal"]),
        ("Australia", [" australia", " sydney", " melbourne", " perth", " brisbane"]),
        ("Europe", [" europe", " eu", " europass", " schengen"]),
    ]

    t_sp = f" {t} "
    for country, kws in checks:
        if any(k in t_sp for k in kws):
            return country
    return None

def apply_customization_to_template(
    template_path: str, 
    cv_data: CVData, 
    customization: dict,
    resume_text: str
) -> str:
    """
    AI takes base template + customization options and generates modified template
    """
    client = init_openai_client()
    if not client:
        # Fallback to original template
        with open(template_path, 'r', encoding='utf-8') as f:
            return f.read()
    
    # Read original template
    with open(template_path, 'r', encoding='utf-8') as f:
        original_template = f.read()
    
    # Convert CV data to JSON for context
    cv_json = json.dumps(cv_data.model_dump(), indent=2)
    
    system_prompt = """You are a CV template customization expert. Your task is to modify a Jinja2 HTML template based on user preferences.

RULES:
1. Keep ALL Jinja2 syntax ({ { variable } }, {% for %}, etc.) intact
2. Preserve the overall structure and styling of the template
3. Apply the user's customization preferences exactly as specified
4. Return ONLY the modified template, no explanations
5. If a section should be hidden, either comment it out or remove it
6. For color changes, update the hex codes in style attributes
7. For layout changes, adjust spacing, margins, and flex properties
8. For section order, rearrange the HTML blocks accordingly"""
    
    user_prompt = f"""
ORIGINAL TEMPLATE:
{original_template}

CV DATA STRUCTURE (for reference):
{cv_json}

FULL RESUME TEXT:
{resume_text}

USER CUSTOMIZATION PREFERENCES:
{json.dumps(customization, indent=2)}

INSTRUCTIONS:

1. COLOR THEME: {customization.get('color_theme')}
   - Update all color hex codes in style attributes
   - Maintain contrast and readability

2. LAYOUT STYLE: {customization.get('layout_style')}
   - Standard: default spacing
   - Compact: reduce margins and padding by 20%
   - Spacious: increase margins and padding by 30%
   - Two-Column: rearrange content into two columns where appropriate

3. FONT SIZE: {customization.get('font_size')}px
   - Adjust all font-size values accordingly

4. SECTION ORDER:
   {customization.get('section_order')}
   - Rearrange sections to match this order exactly

5. VISIBLE SECTIONS:
   {json.dumps(customization.get('show_sections', {}), indent=2)}
   - Hide sections marked as false (remove or comment out)
   - Keep sections marked as true

6. BORDER STYLE: {customization.get('border_style')}
   - Add borders around sections if requested

7. HEADER/FOOTER:
   - Header: {customization.get('custom_header')}
   - Footer: {customization.get('custom_footer')}

8. CUSTOM SECTIONS:
   {json.dumps(customization.get('custom_sections', []), indent=2)}
   - Add these as new sections with appropriate Jinja2 syntax
   - Use the content provided

Return ONLY the modified Jinja2 template."""
    
    try:
        response = client.chat.completions.create(
            model="gpt-4-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3,
            max_tokens=4000
        )
        
        modified_template = response.choices[0].message.content
        
        # Quick validation - ensure it still has Jinja2 syntax
        if '{{' not in modified_template or '{%' not in modified_template:
            # AI might have removed Jinja2 syntax - fallback to original
            st.warning("AI customization had issues. Using original template.")
            with open(template_path, 'r', encoding='utf-8') as f:
                return f.read()
        
        return modified_template
        
    except Exception as e:
        st.error(f"Error in AI customization: {e}")
        # Fallback to original template
        with open(template_path, 'r', encoding='utf-8') as f:
            return f.read()


# ----------------------------
# Export Functions (DOCX/PDF)
# ----------------------------


def create_pdf_from_text(text: str, filename: str = "output.pdf"):
    """Create a PDF file from text content"""
    try:
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
        temp_file.close()

        c = SimpleDocTemplate(temp_file.name, pagesize=letter)
        styles = getSampleStyleSheet()
        story = []

        title = Paragraph("AnchorCV", styles['Title'])
        story.append(title)
        story.append(Spacer(1, 0.2*inch))

        timestamp = Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal'])
        story.append(timestamp)
        story.append(Spacer(1, 0.3*inch))

        lines = text.split('\n')
        for line in lines:
            if line.strip():
                if line.startswith('# '):
                    story.append(Paragraph(line[2:], styles['Heading1']))
                elif line.startswith('## '):
                    story.append(Paragraph(line[3:], styles['Heading2']))
                elif line.startswith('### '):
                    story.append(Paragraph(line[4:], styles['Heading3']))
                else:
                    html = markdown2.markdown(line)
                    soup = BeautifulSoup(html, 'html.parser')
                    plain_text = soup.get_text()
                    story.append(Paragraph(plain_text, styles['Normal']))
                story.append(Spacer(1, 0.1*inch))

        c.build(story)

        with open(temp_file.name, 'rb') as f:
            pdf_bytes = f.read()

        os.unlink(temp_file.name)
        return BytesIO(pdf_bytes)
    except Exception as e:
        st.error(f"Error creating PDF: {e}")
        return None

# ----------------------------
# AI Functions (Direct OpenAI Calls)
# ----------------------------
import json
import re

def _list_to_strings(items):
    """Convert list items (str/dict/other) into clean strings for safe joining."""
    if not items:
        return []
    out = []
    for x in items:
        if x is None:
            continue
        if isinstance(x, str):
            s = x.strip()
        elif isinstance(x, dict):
            # Try common shapes first
            if "role" in x and "company" in x:
                s = f"{str(x.get('role','')).strip()} at {str(x.get('company','')).strip()}".strip()
            elif "title" in x and "company" in x:
                s = f"{str(x.get('title','')).strip()} at {str(x.get('company','')).strip()}".strip()
            else:
                s = " | ".join(
                    f"{k}: {v}" for k, v in x.items()
                    if v is not None and str(v).strip()
                ).strip()
        else:
            s = str(x).strip()

        if s:
            out.append(s)
    return out


def _safe_join(items, sep=", "):
    return sep.join(_list_to_strings(items))


# ----------------------------
# HELPER FUNCTIONS for Requirement Extraction
# Place these AFTER the existing helper functions (_list_to_strings, _safe_join)
# and BEFORE generate_resume_analysis
# ----------------------------

def extract_reference_number(text: str) -> str:
    """Extract job/post reference number from requirement text."""
    if not text:
        return ""
    import re
    # Pattern matches: ref-12345, ref: 12345, reference number 12345, reference code ABC-123, etc.
    patterns = [
        r'ref(?:erence)?[-\s]*(?:number|code|id)?[:\s]*["\']?([A-Z0-9]+[-\s]?[A-Z0-9]+)["\']?',
        r'(?:job|post|position|application)[-\s]*(?:ref|reference)[-\s]*(?:number|code|id)?[:\s]*([A-Z0-9]+[-\s]?[A-Z0-9]+)',
        r'quoting[-\s]*(?:the)?[-\s]*reference[-\s]*(?:number|code)?[:\s]*([A-Z0-9]+[-\s]?[A-Z0-9]+)'
    ]
    for pattern in patterns:
        match = re.search(pattern, text.lower())
        if match:
            return match.group(1).strip().replace(' ', '')
    return ""


def extract_submission_email(text: str) -> str:
    """Extract submission email address from requirement text."""
    if not text:
        return ""
    import re
    email_pattern = r'[\w\.-]+@[\w\.-]+\.\w+'
    # Look for email near submission-related words
    lines = text.lower().split('\n')
    for line in lines:
        if any(kw in line for kw in ['submit', 'application', 'send', 'email', '@']):
            match = re.search(email_pattern, line)
            if match:
                return match.group(0)
    # Fallback: find any email
    match = re.search(email_pattern, text)
    return match.group(0) if match else ""


def extract_submission_method(text: str) -> str:
    """Determine submission method from requirement text."""
    if not text:
        return "Not specified"
    text_lower = text.lower()
    if 'portal' in text_lower or 'upload' in text_lower or 'online application' in text_lower:
        return "Online portal"
    elif '@' in text and any(kw in text_lower for kw in ['email', 'send to', 'submit to']):
        return "Email"
    elif 'post' in text_lower or 'mail' in text_lower or 'address' in text_lower:
        return "Physical mail"
    return "Check requirement"


def extract_deadline_date(text: str) -> str:
    """Extract deadline date from requirement text."""
    if not text:
        return ""
    import re
    # Look for dates near deadline keywords
    deadline_section = ""
    lines = text.split('\n')
    for i, line in enumerate(lines):
        if 'deadline' in line.lower() or 'by ' in line.lower() or 'closing date' in line.lower():
            deadline_section = line
            # Check next line too
            if i + 1 < len(lines):
                deadline_section += " " + lines[i + 1]
            break
    
    if not deadline_section:
        deadline_section = text
    
    # Date patterns: Oct 30, 2025 | 30 October 2025 | 2025-10-30 | 10/30/2025
    patterns = [
        r'(?:deadline|by|before|closing date)[:\s]*([A-Z][a-z]{2,8}\s+\d{1,2},?\s+\d{4})',
        r'(?:deadline|by|before|closing date)[:\s]*(\d{1,2}\s+[A-Z][a-z]{2,8}\s+\d{4})',
        r'(\d{4}-\d{2}-\d{2})',
        r'(\d{1,2}/\d{1,2}/\d{4})'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, deadline_section)
        if match:
            return match.group(1).strip()
    return ""


def generate_compliance_checklist(req: dict, requirement_text: str) -> str:
    """Generate a compliance checklist based on extracted requirement data."""
    checklist = []
    
    # Required documents
    checklist.append("Required documents (verify each):")
    checklist.append("- [ ] Cover letter (English)")
    checklist.append("- [ ] CV with publications list")
    checklist.append("- [ ] Degree certificate(s)")
    
    # Check for dissertation summary requirement
    if any(kw in requirement_text.lower() for kw in ['dissertation summary', 'thesis summary', 'phd summary', 'doctoral summary']):
        checklist.append("- [ ] Dissertation summary (max 2 pages)")
    
    # Reference number
    ref_num = extract_reference_number(requirement_text)
    if ref_num:
        checklist.append(f"- [ ] Reference number: {ref_num}")
    else:
        checklist.append("- [ ] Reference number: Check requirement")
    
    # Submission details
    submission_email = extract_submission_email(requirement_text)
    if submission_email:
        checklist.append(f"- [ ] Send to: {submission_email}")
    else:
        checklist.append(f"- [ ] Submission channel: {extract_submission_method(requirement_text)}")
    
    # Format requirement
    if 'single pdf' in requirement_text.lower() or 'one pdf' in requirement_text.lower():
        checklist.append("- [ ] Single PDF file format")
    
    # Deadline
    deadline = extract_deadline_date(requirement_text)
    if deadline:
        checklist.append(f"\nDeadline: {deadline}")
    else:
        deadline_str = _safe_join(req.get("deadlines", []))
        if deadline_str and deadline_str != "Not specified":
            checklist.append(f"\nDeadline: {deadline_str}")
    
    checklist.append("\n â†’  Note: This is an AI-generated checklist. Always verify against original requirement.")
    
    return "\n".join(checklist)


def extract_domain_translations(resume_text: str, target_domain: str) -> list:
    """Extract technical terms from resume that could be translated for target domain."""
    translations = []
    
    # Common engineering-to-social-science translations
    translation_map = {
        'optimization': 'computational modeling',
        'user behavior': 'social behavior',
        'system design': 'framework architecture',
        'predictive modeling': 'forecasting framework',
        'resource allocation': 'attention/resource distribution',
        'battery control': 'dynamic system control',
        'game-theoretic': 'strategic interaction',
        'EV charging': 'user decision modeling',
        'grid load': 'system load',
        'demand modelling': 'behavioral modeling',
    }
    
    # Find terms from resume that match the map
    for eng_term, css_term in translation_map.items():
        if eng_term in resume_text.lower():
            translations.append(f'- Original: "{eng_term}"  â†’  Target-friendly: "{css_term}"')
    
    return translations[:3]  # Limit to 3 translations





# ============================================================
# generate_resume_analysis_v2.py
# Drop-in replacement for the generate_resume_analysis function.
# Paste this entire block into app.py, replacing the old function.
# ============================================================

def generate_resume_analysis(resume_text: str, requirement_text: str, model: str, temperature: float) -> str:
    """
    ANCHORCV INTELLIGENCE ENGINE  â†’  V4.5 (FULL, PRODUCTION-READY)

     â†’ â€œ â†’  What this version guarantees (your requested fixes):
    1) APPLICATION STRATEGY (not "PhD strategy"):
       - Automatically detects study level: Bachelor's / Master's / PhD / Postdoc / Industry
       - Student-friendly, caring mentor tone (simple + actionable)
       - No cover letter included inside strategy
       - Dynamic timeline (no static 90-day blocks)

    2) ATS OPTIMIZATION (SAFE):
       - Explains ATS simply
       - Only truthful, additive keyword improvements
       - NEVER changes job titles
       - NEVER replaces tools with disciplines (Power BI  â†’  AI)
       - Blocks AI/ML insertion unless already present in resume (or explicitly in resume)

    3) RESUME OPTIMIZATION (SAFE):
       - Truthful rewrites only
       - No title inflation, no certification renaming, no AI/ML invention

     â†’ â€œ â†’  Hard enforcement:
       - Evidence anchors must be verbatim from resume or dropped silently
       - Title mutation lines are removed
       - AI/ML inflation lines are removed if not evidenced in resume
       - Certification renaming is blocked

    External dependencies expected in your app:
      - init_openai_client()
      - generate_compliance_checklist(req_dict, requirement_text)
    """

    import json
    import re
    from difflib import SequenceMatcher
    from typing import List, Dict, Any, Tuple

    # ============================================================
    # 0) Init
    # ============================================================
    client = init_openai_client()
    if not client:
        return "Error: OpenAI client not initialized. Please check your API key."

    resume_raw = resume_text or ""
    req_raw = requirement_text or ""

    # ============================================================
    # 1) Guardrails & Utilities
    # ============================================================

    # Words/phrases that should NEVER be used as evidence anchors
    FORBIDDEN_ANCHORS = {
        "full resume provided", "full resume content", "full resume",
        "see resume", "as mentioned in resume", "resume provided",
        "candidate's resume", "provided resume", "resume text",
        "resume contains", "resume shows", "as per resume",
        "resume", "cv", "curriculum vitae"
    }

    # Headers that should never count as evidence
    SECTION_HEADERS = {
        "professional summary", "summary", "education", "experience", "skills",
        "publications", "certifications", "languages", "awards", "projects",
        "core skills", "professional experience", "academic background",
        "research & publications", "workshops & conferences", "technical skills",
        "funding", "awards & achievements", "volunteer & service",
        "research experience", "teaching experience"
    }

    # High-risk inflation terms. Allowed only if explicitly present in resume text.
    HIGH_RISK_TERMS = {
        "artificial intelligence", "machine learning", "deep learning",
        "ai-driven", "ml-driven", "ai models", "ml models",
        "research fellow", "postdoctoral", "post-doc", "postdoc",
        "principal investigator", "pi", "arxiv", "neurips", "icml", "iclr"
    }

    # Title mutation triggers (we block lines that recommend changing titles)
    TITLE_MUTATION_PATTERNS = [
        r'(?i)\breplace\b.*\bdata analyst\b.*\bwith\b.*',
        r'(?i)\bdata analyst\b\s* â†’ \s*\b(research fellow|researcher|scientist|ai)\b',
        r'(?i)\bjob title\b.*\bchange\b',
        r'(?i)\bchange\b.*\btitle\b',
        r'(?i)\brename\b.*\btitle\b',
        r'(?i)\buse instead\b:\s*".*(research fellow|researcher|scientist|ai|ml).*"'
    ]

    # Certification renaming patterns (block)
    CERT_MUTATION_PATTERNS = [
        r'(?i)\brename\b.*\b(certification|certificate)\b',
        r'(?i)\breplace\b.*\b(certification|certificate)\b',
        r'(?i)\bpower bi data analyst associate\b.* â†’ ',
        r'(?i)\bmicrosoft certified\b.* â†’ '
    ]

    # Tool->discipline substitution patterns (block)
    TOOL_TO_DISCIPLINE_PATTERNS = [
        r'(?i)\bpower bi\b.* â†’ .*\b(artificial intelligence|machine learning|ai|ml)\b',
        r'(?i)\bexcel\b.* â†’ .*\b(artificial intelligence|machine learning|ai|ml)\b',
        r'(?i)\btableau\b.* â†’ .*\b(artificial intelligence|machine learning|ai|ml)\b',
        r'(?i)\bsql\b.* â†’ .*\b(artificial intelligence|machine learning|ai|ml)\b',
        r'(?i)\bpredictive analytics\b.* â†’ .*\b(artificial intelligence|machine learning|ai|ml)\b',
        r'(?i)\banalytics\b.* â†’ .*\b(machine learning|ai)\b'
    ]

    def _safe_join(items: List[str], max_len: int = 400) -> str:
        if not items:
            return ""
        s = ", ".join([str(x) for x in items if x])
        return s if len(s) <= max_len else (s[:max_len] + "...")

    def _normalize(s: str) -> str:
        s = (s or "").lower()
        s = re.sub(r"[^\w\s]", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def _similar(a: str, b: str) -> float:
        if not a or not b:
            return 0.0
        return SequenceMatcher(None, a, b).ratio()

    def _resume_contains_fuzzy(resume_norm: str, quote_norm: str) -> bool:
        if not quote_norm or len(quote_norm) < 10:
            return False
        if quote_norm in resume_norm:
            return True
        if len(quote_norm) > 240:
            return False
        window = max(len(quote_norm) + 20, 90)
        step = max(int(window / 3), 25)
        for i in range(0, max(len(resume_norm) - window, 1), step):
            chunk = resume_norm[i:i + window]
            if _similar(chunk, quote_norm) >= 0.86:
                return True
        return False

    RESUME_NORM = _normalize(resume_raw)

    def _is_valid_anchor(quote: str) -> bool:
        if not quote or not quote.strip():
            return False
        q = quote.strip()
        q_lower = q.lower()

        if any(bad in q_lower for bad in FORBIDDEN_ANCHORS):
            return False

        if q_lower.strip(":").strip() in SECTION_HEADERS:
            return False

        if len(q) < 12:
            return False

        if q in resume_raw:
            return True

        q_norm = _normalize(q)
        return _resume_contains_fuzzy(RESUME_NORM, q_norm)

    def _strip_invalid_evidence_lines(text: str) -> str:
        """
        Silently drop any line that contains an Evidence anchor that fails validation.
        """
        lines = text.split("\n")
        cleaned = []
        for line in lines:
            m = re.search(r'\(Evidence:\s*"([^"]+)"\)', line, re.IGNORECASE)
            if m:
                anchor = (m.group(1) or "").strip()
                if not _is_valid_anchor(anchor):
                    continue
            cleaned.append(line)
        out = "\n".join(cleaned)
        out = re.sub(r"\n{3,}", "\n\n", out).strip()
        return out

    def _ai_ml_present_in_resume() -> bool:
        """
        Detect whether resume explicitly contains AI/ML evidence.
        This is conservative by design.
        """
        tokens = [
            "machine learning", "deep learning", "artificial intelligence",
            "tensorflow", "pytorch", "scikit-learn", "sklearn",
            "xgboost", "lightgbm", "random forest", "svm", "neural network",
            "cnn", "lstm", "transformer", "bert"
        ]
        rn = RESUME_NORM
        return any(t in rn for t in tokens)

    AI_ML_OK = _ai_ml_present_in_resume()

    def _line_has_high_risk_without_evidence(line: str) -> bool:
        """
        If line introduces AI/ML claims but resume doesn't explicitly include AI/ML evidence,
        treat as unsafe.
        """
        lnorm = _normalize(line)
        if not AI_ML_OK:
            # If any high-risk term appears, flag it
            return any(term in lnorm for term in HIGH_RISK_TERMS)
        return False

    def _strip_unsafe_rewrite_lines(text: str) -> str:
        """
        Remove lines that:
          - encourage job title mutation
          - rename certifications
          - substitute tools -> discipline
          - introduce AI/ML inflation without evidence
        """
        lines = text.split("\n")
        out = []
        for line in lines:
            # Drop job title mutation advice
            if any(re.search(p, line) for p in TITLE_MUTATION_PATTERNS):
                continue
            # Drop certification mutation advice
            if any(re.search(p, line) for p in CERT_MUTATION_PATTERNS):
                continue
            # Drop tool->discipline substitutions
            if any(re.search(p, line) for p in TOOL_TO_DISCIPLINE_PATTERNS):
                continue
            # Drop AI/ML inflation if not evidenced in resume
            if _line_has_high_risk_without_evidence(line):
                continue

            out.append(line)

        text2 = "\n".join(out)
        text2 = re.sub(r"\n{3,}", "\n\n", text2).strip()
        return text2

    def _final_clean(text: str) -> str:
        # Evidence anchor strip first (removes invalid anchored bullets)
        text = _strip_invalid_evidence_lines(text)
        # Then remove unsafe advice lines (title mutation, AI/ML inflation, etc.)
        text = _strip_unsafe_rewrite_lines(text)
        # Normalize excessive blank lines
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return text

    # ============================================================
    # 2) Stage 1 '''''''''''''''''''''''''''''''''''''' Structured Parse (study level, intent, evidence map)
    # ============================================================

    parse_prompt = f"""You are a precision information extractor for a student application intelligence system.

Read RESUME and REQUIREMENT. Return ONLY a single valid JSON object. No prose, no markdown.

STRICT RULES:
- Never invent. Every string must be an exact quote from texts, or "".
- Arrays must contain strings only.
- Identify study level from REQUIREMENT:
  "Bachelor's" | "Master's" | "PhD" | "Postdoc/Research Fellow" | "Industry/Other" | "Unclear"

INTENT: pick exactly one:
- "Application_Strategy"  (default)
- "ATS_Optimization"
- "Resume_Optimization"
- "Cover_Letter"
- "Email_Template"
- "Academic_CV"
- "Info_Extraction"
- "Custom_Analysis"

Also extract:
- target institution
- deadline
- submission channel
- contact person
- requirement criteria (explicit criteria list)
- focus areas (max 3)
- chosen focus area (closest to resume)

RESUME:
{resume_raw}

REQUIREMENT:
{req_raw}

Return JSON with EXACT keys:
{{
  "intent": "",
  "study_level": "",
  "application_type": "academic_research|academic_teaching|industry|other",
  "tone_signal": "formal_academic|professional_corporate|warm_collaborative",
  "candidate": {{
    "name": "",
    "email": "",
    "phone": "",
    "location": "",
    "current_roles": [],
    "institutions": [],
    "core_skills": [],
    "years_experience": 0,
    "highest_degree": "",
    "publications_count": 0,
    "has_teaching_experience": false
  }},
  "requirement": {{
    "target_institution": "",
    "contact_person": "",
    "deadline": "",
    "submission_channel": "",
    "reference_number": "",
    "urls": [],
    "focus_areas": [],
    "chosen_focus_area": "",
    "requirement_criteria": []
  }},
  "resume_evidence_map": {{}}
}}"""

    try:
        parse_response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Return ONE valid JSON object only. No prose."},
                {"role": "user", "content": parse_prompt}
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
            max_tokens=3500
        )
        parsed = json.loads(parse_response.choices[0].message.content)
    except Exception:
        parsed = {
            "intent": "Application_Strategy",
            "study_level": "Unclear",
            "application_type": "other",
            "tone_signal": "warm_collaborative",
            "candidate": {},
            "requirement": {},
            "resume_evidence_map": {}
        }

    # ------------------------------------------------------------
    # Unpack parsed safely
    # ------------------------------------------------------------
    allowed_intents = {
        "Application_Strategy", "ATS_Optimization", "Resume_Optimization",
        "Cover_Letter", "Email_Template", "Academic_CV", "Info_Extraction", "Custom_Analysis"
    }
    intent = (parsed.get("intent") or "Application_Strategy").strip()
    if intent not in allowed_intents:
        intent = "Application_Strategy"

    study_level = (parsed.get("study_level") or "Unclear").strip()
    app_type = (parsed.get("application_type") or "other").strip()
    tone_signal = (parsed.get("tone_signal") or "warm_collaborative").strip()

    cand = parsed.get("candidate", {}) or {}
    req = parsed.get("requirement", {}) or {}
    evidence_map = parsed.get("resume_evidence_map", {}) or {}

    candidate_name = (cand.get("name") or "Candidate").strip()
    candidate_email = (cand.get("email") or "").strip()
    candidate_phone = (cand.get("phone") or "").strip()
    candidate_location = (cand.get("location") or "").strip()
    candidate_roles = cand.get("current_roles") or []
    candidate_insts = cand.get("institutions") or []
    candidate_skills_list = cand.get("core_skills") or []
    candidate_skills = _safe_join(candidate_skills_list[:15])
    candidate_degree = (cand.get("highest_degree") or "").strip()
    candidate_yoe = int(cand.get("years_experience") or 0)
    candidate_pubs = int(cand.get("publications_count") or 0)
    candidate_teaches = bool(cand.get("has_teaching_experience") or False)

    target_institution = (req.get("target_institution") or "").strip()
    contact_person = (req.get("contact_person") or "").strip()
    deadline = (req.get("deadline") or "").strip()
    submission_channel = (req.get("submission_channel") or "").strip()
    reference_number = (req.get("reference_number") or "").strip()
    urls = req.get("urls") or []
    urls_joined = _safe_join(urls)
    focus_areas = req.get("focus_areas") or []
    chosen_focus_area = (req.get("chosen_focus_area") or "").strip()
    criteria = req.get("requirement_criteria") or []

    is_academic = app_type in ("academic_research", "academic_teaching")

    # ============================================================
    # 3) Stage 2 '''''''''''''''''''''''''''''''''''''' Gap Matrix (JSON, conservative, weeks range)
    # ============================================================

    # Strong rule: if AI/ML is not in resume, model must treat as missing and must not suggest rewriting to AI/ML
    ai_policy_line = (
        "IMPORTANT: The resume DOES NOT explicitly contain AI/ML frameworks or model implementations. "
        "You MUST NOT label anything as AI/ML, and you MUST NOT propose title changes."
        if not AI_ML_OK else
        "IMPORTANT: The resume contains some AI/ML signals. You may mention AI/ML only where explicitly evidenced by verbatim quotes."
    )

    gap_matrix_prompt = f"""You are a senior application advisor. Build a strict, evidence-based gap matrix.

{ai_policy_line}

RULES:
- evidence_quote must be verbatim from RESUME or "" (no paraphrase).
- Never recommend changing job titles.
- Never rename certifications.
- Never substitute tools with disciplines (Power BI  â†’  AI).
- bridging_action must be concrete and doable for a student.
- weeks_to_close: 0 (met), 1-3 (framing), 4-8 (mini-project), 9-16 (project+portfolio), 17-32 (deep pivot).
- urgency: critical (must-have), important (preferred), optional (nice-to-have).
- deliverable must be tangible and realistic (GitHub repo + README + results summary preferred).

RESUME:
{resume_raw}

REQUIREMENT:
{req_raw}

REQUIREMENT CRITERIA (from extraction):
{json.dumps(criteria, indent=2)}

EVIDENCE MAP (use as starting point but improve if possible):
{json.dumps(evidence_map, indent=2)}

Return JSON exactly:
{{
  "gap_matrix": [
    {{
      "criterion": "",
      "status": "met|partial|missing",
      "evidence_quote": "",
      "gap_description": "",
      "bridging_action": "",
      "weeks_to_close": 0,
      "urgency": "critical|important|optional",
      "deliverable": ""
    }}
  ],
  "weeks_min": 0,
  "weeks_max": 0,
  "overall_fit": "strong|moderate|stretch",
  "strongest_asset": "",
  "biggest_risk": "",
  "positioning_angle": "",
  "safe_vocab_bridge": [
    {{"resume_term": "", "target_term": "", "type": "synonym|context"}}
  ]
}}"""

    try:
        gap_response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Return ONE valid JSON object only. Evidence must be verbatim from resume."},
                {"role": "user", "content": gap_matrix_prompt}
            ],
            temperature=0.15,
            response_format={"type": "json_object"},
            max_tokens=3500
        )
        gap_data = json.loads(gap_response.choices[0].message.content)
    except Exception:
        gap_data = {
            "gap_matrix": [],
            "weeks_min": 4,
            "weeks_max": 12,
            "overall_fit": "moderate",
            "strongest_asset": "",
            "biggest_risk": "",
            "positioning_angle": "",
            "safe_vocab_bridge": []
        }

    gap_matrix = gap_data.get("gap_matrix", []) or []
    weeks_min = int(gap_data.get("weeks_min") or 0)
    weeks_max = int(gap_data.get("weeks_max") or 12)
    overall_fit = (gap_data.get("overall_fit") or "moderate").strip()
    strongest_asset = (gap_data.get("strongest_asset") or "").strip()
    biggest_risk = (gap_data.get("biggest_risk") or "").strip()
    positioning_angle = (gap_data.get("positioning_angle") or "").strip()
    safe_vocab_bridge = gap_data.get("safe_vocab_bridge", []) or []

    # ============================================================
    # 4) Segment gaps + validate anchors
    # ============================================================

    met_items, partial_items, missing_items = [], [], []
    critical_gaps, important_gaps, optional_gaps = [], [], []

    for g in gap_matrix:
        status = (g.get("status") or "").strip()
        urgency = (g.get("urgency") or "").strip()
        evidence = (g.get("evidence_quote") or "").strip()

        # Keep only valid evidence for met/partial
        if status in ("met", "partial"):
            if evidence and _is_valid_anchor(evidence):
                if status == "met":
                    met_items.append(g)
                else:
                    partial_items.append(g)
        else:
            missing_items.append(g)
            if urgency == "critical":
                critical_gaps.append(g)
            elif urgency == "important":
                important_gaps.append(g)
            else:
                optional_gaps.append(g)

    # ============================================================
    # 5) Dynamic timeline builder (NO static 90-day)
    # ============================================================

    def _timeline_text() -> str:
        if not gap_matrix:
            return " â†’ â€œ â†’  I couldn â†’ t derive gaps confidently from the text. Try pasting more complete requirement text."
        if weeks_max <= 0 and not critical_gaps:
            return " â†’ â€œ â†’  You can apply NOW. Fix small wording/packaging in parallel."
        if weeks_max <= 3:
            return f" â†’  Prep estimate: ~{max(weeks_min, 1)} â†’ {weeks_max} weeks (mostly framing + small edits)."
        if weeks_max <= 8:
            return f" â†’  Prep estimate: ~{weeks_min} â†’ {weeks_max} weeks (one focused mini-project + better packaging)."
        if weeks_max <= 16:
            return f" â†’  Prep estimate: ~{weeks_min} â†’ {weeks_max} weeks (meaningful skill-building + proof deliverables)."
        return f" â†’  Prep estimate: ~{weeks_min} â†’ {weeks_max} weeks (bigger pivot; build foundations + portfolio)."

    # ============================================================
    # 6) Safe Vocabulary Bridge (no fraud)
    # ============================================================

    def _build_vocab_block() -> str:
        """
        Only allow safe synonyms/context shifts:
          - dashboard -> reporting/dashboarding
          - predictive analysis -> forecasting/trend analysis
        Absolutely forbid:
          - Power BI -> AI
          - Data Analyst -> Research Fellow
        Also: if AI_ML_OK is False, remove any mapping that introduces AI/ML.
        """
        lines = []
        for item in safe_vocab_bridge[:10]:
            a = (item.get("resume_term") or "").strip()
            b = (item.get("target_term") or "").strip()
            t = (item.get("type") or "synonym").strip()

            if not a or not b:
                continue

            # block obvious title mutation suggestions
            if "data analyst" in _normalize(a) and any(x in _normalize(b) for x in ["research fellow", "researcher", "scientist"]):
                continue

            # block tool->discipline swaps
            if any(tool in _normalize(a) for tool in ["power bi", "excel", "tableau", "sql"]) and any(
                x in _normalize(b) for x in ["ai", "artificial intelligence", "machine learning", "ml", "deep learning"]
            ):
                continue

            # block AI/ML intro if not in resume
            if not AI_ML_OK and any(x in _normalize(b) for x in ["ai", "artificial intelligence", "machine learning", "ml", "deep learning"]):
                continue

            # keep safe
            label = "Use like this" if t == "context" else "Swap wording"
            lines.append(f' â†’  {label}: "{a}"  â†’  "{b}"')

        if not lines:
            return ""
        return " â†’ â€œ SAFE VOCABULARY (truthful wording alignment)\n" + "\n".join(lines)

    vocab_block = _build_vocab_block()

    # ============================================================
    # 7) Candidate + Requirement snapshot (simple & friendly)
    # ============================================================

    def _snapshot_block() -> str:
        contact_line = " | ".join([x for x in [candidate_email, candidate_phone] if x]).strip()
        contact_line = contact_line if contact_line else "Not found"

        return f"""
 â†’ 
 â†’ â€œ â†’  YOUR SNAPSHOT (from your resume)
 â†’ 
Name: {candidate_name}
Degree: {candidate_degree or "Not found"}
Experience: {f"{candidate_yoe} years" if candidate_yoe else "Not found"}
Publications: {candidate_pubs}
Teaching: {"Yes" if candidate_teaches else "No"}
Core Skills: {candidate_skills or "Not found"}
Current Roles: {_safe_join(candidate_roles) or "Not found"}
Contact: {contact_line}
Location: {candidate_location or "Not found"}

 â†’ 
 â†’  TARGET SNAPSHOT (from the requirement)
 â†’ 
Institution: {target_institution or "Not specified"}
Study Level: {study_level}
Focus Area: {chosen_focus_area or (_safe_join(focus_areas) or "Not specified")}
Deadline: {deadline or "Not specified"}
Submission: {submission_channel or "Not specified"}
Reference #: {reference_number or "Not specified"}
URLs: {urls_joined or "None"}
""".strip()

    snapshot = _snapshot_block()

    # ============================================================
    # 8) Pretty format helpers (simple & student-friendly)
    # ============================================================

    def _format_strengths(items: List[Dict[str, Any]], max_items: int = 6) -> str:
        out = []
        for g in items[:max_items]:
            point = (g.get("criterion") or "").strip()
            ev = (g.get("evidence_quote") or "").strip()
            if point and ev and _is_valid_anchor(ev):
                out.append(f' â†’ â€œ â†’  {point} (Evidence: "{ev}")')
            elif point and not ev:
                # No evidence '''''''''''''''''''''''''''''''''''''' show criterion only
                out.append(f' â†’ â€œ â†’  {point}')
        return "\n".join(out) if out else "No strong direct matches confirmed  â†’  focus on the gaps below."

    def _format_gaps(items: List[Dict[str, Any]], max_items: int = 4, emoji: str = " â†’ ") -> str:
        out = []
        for g in items[:max_items]:
            crit = (g.get("criterion") or "").strip()
            desc = (g.get("gap_description") or "").strip()
            action = (g.get("bridging_action") or "").strip()
            deliverable = (g.get("deliverable") or "").strip()
            weeks = g.get("weeks_to_close", None)

            if not crit:
                continue
            out.append(f"{emoji} {crit}")
            if desc:
                out.append(f"    â†’  What â†’ s missing: {desc}")
            if action:
                out.append(f"    â†’  Do this: {action}")
            if deliverable:
                out.append(f"    â†’  Proof to show: {deliverable}")
            if isinstance(weeks, int) and weeks >= 0:
                out.append(f"    â†’  Time estimate: ~{weeks} week(s)")
            out.append("")
        return "\n".join(out).strip() if out else "None."

    # ============================================================
    # 9) Compliance checklist (kept from your system)
    # ============================================================
    # This helper is assumed to exist in your app
    try:
        compliance_checklist = generate_compliance_checklist(req, req_raw)
    except Exception:
        compliance_checklist = "- Checklist not available (generate_compliance_checklist missing)."

    # ============================================================
    # 10) Tone system prompt (caring + simple, '''''''''''''''''''''''''''''''''''â€œchildish'''''''''''''''''''''''''''''''' but expert)
    # ============================================================

    tone_map = {
        "formal_academic": (
            "You are a kind senior academic mentor. You explain things simply like teaching a student. "
            "Short sentences. Clear steps. No jargon unless you define it in one line."
        ),
        "professional_corporate": (
            "You are a warm, practical advisor. Explain like the reader is a beginner. "
            "Short, clear, reassuring."
        ),
        "warm_collaborative": (
            "You are a supportive mentor who talks gently and clearly. "
            "You help the student feel safe and guided. Keep it simple and actionable."
        )
    }
    voice = tone_map.get(tone_signal, tone_map["warm_collaborative"])

    system_prompt = f"""You are an expert application mentor for students (Bachelor/Master/PhD/Postdoc).

VOICE:
{voice}

ABSOLUTE RULES (must follow):
1) Never invent skills/roles/publications/metrics.
2) Never suggest changing job titles. You may add parenthetical focus tags only.
    â†’ â€œ â†’  "Data Analyst (Healthcare Analytics Focus)"
    â†’  "Data Analyst  â†’  Research Fellow"
3) Never substitute tools with fields:
    â†’ â€œ â†’  "Power BI" stays Power BI; you may say "data visualization" as a category.
    â†’  "Power BI  â†’  Artificial Intelligence"
4) Never rename certifications.
5) If AI/ML is not explicitly present in the resume, DO NOT add AI/ML language.
6) If you mention a strength bullet, end it with (Evidence: "exact quote").
   If you cannot find a real quote, omit that bullet.
7) No static 90-day plans. Use dynamic timing based on the gap matrix.
8) For Application Strategy: DO NOT write a cover letter or email.

Return only the final formatted output. No meta-commentary.
"""

    # ============================================================
    # 11) Base context for all intents
    # ============================================================
    context_block = f"""
{snapshot}

 â†’ 
 â†’  GAP SUMMARY
 â†’ 
Overall Fit: {overall_fit.upper()}
Strongest Asset: {strongest_asset or "Not determined"}
Biggest Risk: {biggest_risk or "Not determined"}
Positioning: {positioning_angle or "Not determined"}

 â†’ â€œ â†’  Strong matches:
{_format_strengths(met_items, 6)}

 â†’  Partial matches:
{_format_strengths(partial_items, 4)}

 â†’  Critical gaps:
{_format_gaps(critical_gaps, 4, " â†’ ")}

 â†’  Important gaps:
{_format_gaps(important_gaps, 4, " â†’ ")}

 â†’  Optional gaps:
{_format_gaps(optional_gaps, 3, " â†’ ")}
""".strip()

    # ============================================================
    # 12) Intent-specific prompts (FULL outputs)
    # ============================================================

    # --- APPLICATION STRATEGY ---
    if intent == "Application_Strategy":
        user_prompt = f"""
{context_block}

{vocab_block if vocab_block else ""}

 â†’ 
OUTPUT: STUDY APPLICATION STRATEGY (SIMPLE + ACTIONABLE)
 â†’ 

Write directly to {candidate_name}. Friendly, calm, like guiding a beginner.

STRUCTURE (follow exactly):

1)  â†’  Quick Picture (4 â†’ 6 short lines)
- What this programme wants (simple)
- Where you stand (strong/moderate/stretch  â†’  honest, not discouraging)
- One supportive line like: "You â†’ re not stuck. We just need a plan."
- One short motivational quote (1 line only)

2)  â†’ â€œ â†’  What you already have (3 â†’ 7 bullets)
- List real transferable strengths the candidate already has FROM THEIR CV  â†’  even if not a perfect match
- Partial matches and soft transferable skills count here
- Examples: data skills, teaching/research experience, technical background, industry experience
- Each bullet should end with (Evidence: "exact quote from CV") when possible
- If no direct match, write the strength clearly without an evidence tag  â†’  do NOT leave this section blank

3)  â†’  What needs work (grouped)
A)  â†’  MUST-FIX (critical)
B)  â†’  SHOULD-FIX (important)
C)  â†’  OPTIONAL (if time)

For each gap:
- What â†’ s missing (1 line)
- Do this (1 line)
- Proof to show (1 line)
- Time estimate (~X weeks)

4)  â†’  Your Timeline (dynamic)
- Use this: {_timeline_text()}
- Then list the order of actions: Must-fix first, then should-fix, then optional.

5)  â†’  How to position yourself (simple)
- What to emphasize (2 â†’ 3 lines)
- What NOT to claim (2 â†’ 3 lines)
- Best angle for focus area: {chosen_focus_area or "the programme focus"} (1 â†’ 2 lines)

6)  â†’  Application checklist
{compliance_checklist}

IMPORTANT:
- Do NOT write a cover letter.
- Do NOT write an outreach email.
Return ONLY the strategy.
"""

    # --- ATS OPTIMIZATION ---
    elif intent == "ATS_Optimization":
        user_prompt = f"""
{context_block}

 â†’ 
OUTPUT: ATS OPTIMIZATION (SAFE + STUDENT FRIENDLY)
 â†’ 

Write as a gentle mentor. Assume the student is new.

Non-negotiables:
- Never change job titles.
- Never insert AI/ML unless explicitly in resume.
- Never rename certifications.
- Only additive, truthful keyword improvements.

STRUCTURE:

1)  â†’ â€œ What is ATS? (very simple)
- 4 bullets only

2)  â†’  How ATS reads your resume
- keyword matching
- section structure
- formatting mistakes to avoid

3)  â†’ â€œ â†’  What your resume already does well
- 3 â†’ 6 bullets, each with (Evidence: "quote")

4)  â†’  SAFE ATS Fixes (8 â†’ 12 items)
Each item must say:
- Where to change (e.g., "Skills section", "First bullet under Role X")
- Exactly what to add/change (truthful)
- Why it helps ATS

5)  â†’ â€œ â†’  Top 5 rewrites (Before  â†’  After)
- Before MUST be verbatim from resume
- After MUST remain truthful and NOT add AI/ML
- Also mention where it goes

6)  â†’ â€œ Missing keywords (truthful only)
For each missing keyword output in this exact format:
KEYWORD: [keyword]
WHERE TO ADD: [exact section  â†’  e.g. Skills, Summary, Experience bullet]
HOW TO PHRASE: [exact suggested wording]
SAFE TO ADD: [Yes  â†’  already evidenced | Only if true  â†’  candidate must verify | No  â†’  do not add]

7)  â†’  Safe summary rewrite (2 â†’ 3 sentences)
- Use only resume-evidenced keywords
- No new claims

8)  â†’  One calm closing line (1 line)

Return ONLY the ATS output.
"""

    # --- RESUME OPTIMIZATION ---
    elif intent == "Resume_Optimization":
        user_prompt = f"""
{context_block}

 â†’ 
OUTPUT: RESUME OPTIMIZATION REPORT (SAFE)
 â†’ 

Rules:
- No job title changes.
- No AI/ML insertion unless evidenced in resume.
- No certification renaming.
- No invented metrics.

STRUCTURE:

1)  â†’  Goal (1 sentence)

2)  â†’ â€œ â†’  Strongest points to keep (3 â†’ 6 bullets)
- Each bullet with (Evidence: "quote")

3)  â†’ â€œ â†’  Top 5 rewrites (Before  â†’  After)
- Before verbatim
- After truthful and closer to requirement language
- Mention section placement

4)  â†’ â€œ Missing keywords (truthful only)
For each missing keyword output in this exact format:
KEYWORD: [keyword]
WHERE TO ADD: [exact section  â†’  e.g. Skills, Summary, Experience bullet]
HOW TO PHRASE: [exact suggested wording  â†’  only if candidate has honest evidence]
SAFE TO ADD: [Yes  â†’  already evidenced | Only if true  â†’  candidate must verify | No  â†’  do not add]

5)  â†’  Section-by-section quick fixes
- Summary / Skills / Experience / Projects (only those that need change)

6)  â†’  Summary rewrite (2 â†’ 3 sentences)

Return ONLY the report.
"""

    # --- COVER LETTER ---
    elif intent == "Cover_Letter":
        # keep cover letter separate (user asked not to include it in strategy '''''''''''''''''''''''''''''''''''''' we comply)
        word_limit = "380 words" if is_academic else "260 words"
        salutation = f"Dear {contact_person}," if contact_person else ("Dear Admissions Committee," if is_academic else "Dear Hiring Manager,")
        closing = "\n".join([x for x in [f"Best regards,\n{candidate_name}", candidate_email, candidate_phone] if x]).strip()

        user_prompt = f"""
{context_block}

 â†’ 
OUTPUT: COVER LETTER ({word_limit})
 â†’ 

Rules:
- No title inflation, no AI/ML insertion unless in resume.
- No generic praise unless it appears in requirement text.
- No placeholders.
- Keep it direct and simple.

Write the letter now.

Salutation:
{salutation}

Close with:
{closing}

Return ONLY the letter.
"""

    # --- EMAIL TEMPLATE ---
    elif intent == "Email_Template":
        salutation = f"Dear {contact_person}," if contact_person else "Dear Professor,"
        user_prompt = f"""
{context_block}

 â†’ 
OUTPUT: EMAIL TO PROFESSOR (STRICT  â†’ 150 WORDS)
 â†’ 

CRITICAL RULES:
- Maximum 150 words TOTAL including subject line. Count every word.
- NO generic opener like "I hope this email finds you well."
- NO long paragraphs. Short, direct sentences only.
- Must name the SPECIFIC program/position from the requirement.
- Must reference the professor's SPECIFIC research area (from requirement text).
- Must include exactly 1 â†’ 2 evidence-anchored skills/experience from resume.
- Must end with ONE clear ask (e.g. discuss fit, confirm eligibility).
- No placeholders like [Your Name]  â†’  use actual candidate info.

STRUCTURE (follow exactly  â†’  4 short parts):
1) Subject line: [Program name]  â†’  [Candidate name]  â†’  [One key skill]
2) Opening hook (1 sentence): Why THIS lab/professor specifically.
3) Your fit (2 â†’ 3 sentences): Resume evidence + how it connects to their research.
4) Clear ask (1 sentence): What you want them to do.

{salutation}

Return ONLY the email. No preamble, no commentary.
"""

    # --- ACADEMIC CV ---
    elif intent == "Academic_CV":
        user_prompt = f"""
{context_block}

OUTPUT: ACADEMIC CV

LANGUAGE RULE: Output ALL content in English only. Section headings and all text must be in English regardless of the resume's language.

CRITICAL RULES  â†’  follow exactly:
1. Use ONLY facts from the resume. No invented publications, grants, or roles.
2. TEACHING / ACADEMIC EXPERIENCE section: Include ANY role where the person
   taught, tutored, assisted, mentored, or supervised students  â†’  including
   "Teaching Assistant", "Lab Assistant", "Lecturer", "Tutor", "TA", "Demonstrator".
   DO NOT label this section "No teaching/academic experience listed" if such roles exist.
3. RESEARCH EXPERIENCE section: Only include if real research projects or lab work
   are listed. Do NOT add filler text like "Research work inferred from publication(s)."
4. PUBLICATIONS: List exactly as stated in resume  â†’  do not paraphrase titles. Include full citation with DOI if present. Flag each as [Published] / [Under Review] / [Pending] based on resume wording.
5. PROJECTS: Include ALL academic/research projects. For each: project name, what it demonstrates, technical details.
6. EDUCATION: Always first. Include full degree name, institution, GPA, thesis title, supervisor if present.
7. AWARDS & HONOURS: Include ALL scholarships, medals, rankings, funding, honours if present.
8. PATENT: If any patent is mentioned in the resume, include it in a dedicated Patent section.
9. PROFESSIONAL DEVELOPMENT: If courses, training, workshops, certifications are listed, include them.
10. MEMBERSHIPS: If professional body memberships (IEEE, ACM, PEC, etc.) are listed, include them.
11. If a section has no real content, OMIT it entirely. No placeholder text.

SECTION ORDER FOR ACADEMIC CV:
1. Personal Details (name, email, phone, location)
2. Research Profile / Interests (2-3 sentences from resume)
3. Education (most recent first  â†’  full detail: degree, institution, GPA, thesis)
4. Academic & Teaching Experience (ALL roles  â†’  check carefully for TA, lecturer, supervisor, demonstrator)
5. Research Projects (ALL projects with descriptions and technical details)
6. Publications (ALL publications  â†’  full citations, DOI, status flag)
7. Patent (if present in resume)
8. Professional Development / Courses / Training (if present)
9. Awards & Honours (if present)
10. Memberships (if present)
11. Skills
12. Languages (if listed)

Return ONLY the CV content, no commentary.
"""

    # --- INFO EXTRACTION ---
    elif intent == "Info_Extraction":
        user_prompt = f"""
Extract structured info from the RESUME only (no invention).

RESUME:
{resume_raw}

Return sections:
CONTACT
EDUCATION
EXPERIENCE
SKILLS
PROJECTS
PUBLICATIONS
CERTIFICATIONS
LANGUAGES
"""

    # --- CUSTOM ---
    else:
        user_prompt = f"""
{context_block}

Respond to the user's need using strict truth rules.
Keep it simple and actionable.
"""

    # ============================================================
    # 13) Final generation (model chosen by caller)
    # ============================================================
    try:
        final_response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=temperature,
            max_tokens=4000
        )
        raw_output = final_response.choices[0].message.content or ""
    except Exception as e:
        return f"Error generating analysis: {str(e)}"

    # ============================================================
    # 14) Post-processing safety passes
    # ============================================================
    cleaned = _final_clean(raw_output)

    # Final polish: avoid giant blank gaps after line drops
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    # Surface gap_matrix to session state so display_results() can render evidence
    try:
        import streamlit as _st
        _st.session_state["gap_matrix_data"] = gap_matrix
    except Exception:
        pass

    return cleaned



def generate_matching_score(resume_text: str, job_description: str, model: str, temperature: float) -> dict:
    """
    Matching score + recommendations (evidence-backed).
    - Scores are allowed but must be justified with quotes from BOTH resume and requirement.
    - Missing keywords must be exact phrases present in requirement.
    """
    client = init_openai_client()
    if not client:
        return {"error": "OpenAI client not initialized"}

    system_prompt = """
You are a rigorous matching analyst.
Rules:
- Do NOT inflate scores. If domain alignment is weak, reflect it in scores.
- Every score rationale MUST include:
  - 1 â†’ 2 exact quotes from the resume
  - 1 â†’ 2 exact quotes from the job description/requirement
- Missing keywords MUST be exact terms/phrases that appear in the requirement.
- Improvements must be concrete and tailored, not generic.

SCORING CALIBRATION (mandatory  â†’  follow strictly):
- 0 â†’ 30:  Major gaps. Core required skills/experience completely absent.
- 31 â†’ 50: Some relevant background but significant gaps in must-have requirements.
- 51 â†’ 70: Moderate alignment. Good base but notable gaps remain.
- 71 â†’ 85: Strong match. Most requirements met with minor gaps.
- 86 â†’ 100: Exceptional match. Almost all requirements clearly evidenced.

HARD CAPS (apply automatically):
- If advanced R or Python is required but absent from resume  â†’  overall_score  â†’  50, skill_match_score  â†’  45
- If required domain experience is missing (e.g. climate science, epidemiology)  â†’  experience_match_score  â†’  40
- If fewer than 40% of requirement keywords appear in resume  â†’  keyword_match_score  â†’  40
- For PhD/research positions: no publications + no research experience  â†’  overall_score  â†’  55

HARDENING RULES (apply in addition to all above):

TIMELINE: If the resume summary or skills section claims a number of years for a specific skill (e.g. "8 years React"), cross-check against the actual job date ranges in the work history. If the timeline-verifiable years are more than 1 year less than the claimed years, cap keyword_match_score at 55 and add a warning: "Claimed [X] years [skill], timeline shows approximately [Y] years."

EVIDENCE DEPTH: If a skill appears only in the skills/technologies list and never in any job bullet or project description, treat it as unverified. Do not count unverified skills toward keyword_match_score. If more than 5 required skills are unverified, add a warning: "Keyword stuffing detected -- [N] required skills listed but not evidenced in work history."

SENIORITY: Detect the required level from the job description (junior / mid / senior / lead / principal). Detect candidate level from job titles and years of experience. If the candidate is overqualified by more than one level (e.g. senior/principal applying to junior), cap overall_score at 65 and add a warning: "Overqualification risk -- candidate profile exceeds role level." If underqualified by more than one level, add a warning: "Experience level below role requirement."

DOMAIN: If the candidate's entire work history is in a different industry to the job (e.g. gaming -> fintech, academic -> SaaS), cap experience_match_score at 60 and add a warning: "Domain shift -- no direct [target industry] experience detected."

ADJACENT SKILLS: Use this map when a required skill is absent. If an adjacent skill is present, set status partial and do not count as missing, but note it in improvements. Map: React<->Vue/Angular/Svelte, Django<->Flask/FastAPI, TensorFlow<->PyTorch/Keras, JavaScript<->TypeScript, Spring<->Jakarta EE.

CAREER GAPS: If the work history shows a gap longer than 8 months, add a warning: "Employment gap of [approx duration] detected."

Populate the "warnings" array with all triggered warning strings. If no rules trigger, return an empty array.

MANDATORY PRE-OUTPUT AUDIT — Complete this checklist before returning JSON.
Detection without score adjustment is a failure. Every triggered condition MUST modify the JSON.

[ ] CAREER GAPS: Scanned full work history for gaps longer than 8 months?
    If gap found AND not explained in resume (no caregiving, study, health note):
    -> warnings MUST contain: "Career gap: [duration] ([start date] to [end date])"
    -> reduce overall_score by 5 points
    If gap found AND explained in resume:
    -> add warning but do NOT reduce score

[ ] UNVERIFIED SKILLS: Cross-checked every skill in the skills list against all
    job bullets and project descriptions?
    Count required skills claimed but with ZERO evidence in any bullet or project.
    If count >= 5:
    -> warnings MUST contain: "Keyword stuffing detected: [list unverified skills] are claimed but not evidenced in any role or project"
    -> reduce skill_match_score by 10 points
    If count is 3-4:
    -> add warning: "Multiple unverified skills: [list]. Consider adding evidence or removing."
    If count is 1-2: note in improvements only, no warning

[ ] DOMAIN SHIFT: Entire work history in a different industry than the target role?
    If YES (complete domain shift):
    -> experience_match_score MUST be <= 60
    -> warnings MUST contain: "Domain shift: [current industry] to [target industry]. No direct experience in target domain."
    If partial (some roles in target industry):
    -> reduce experience_match_score by 10 points, do not apply hard cap

[ ] SENIORITY: Compared JD-required level vs. candidate's actual titles and years?
    If overqualified by more than one level:
    -> overall_score MUST be <= 65
    -> warnings MUST contain: "Overqualification risk: candidate at [level] applying for [level] role"
    If underqualified by more than two levels:
    -> warnings MUST contain: "Significant seniority gap: role requires [X level], candidate is at [Y level]"
    -> reduce experience_match_score by 15 points

[ ] QUALIFICATION PATHS: Does the JD offer alternate paths (look for OR clauses)?
    If candidate meets alternate path but NOT primary path:
    -> increase experience_match_score by 10-15 points
    -> add to summary: "Candidate qualifies via alternate path: [description]. Gaps remain in [specific skills]."
    If candidate meets neither path: no adjustment

[ ] SCORE CONSISTENCY: Is overall_score lower than any individual sub-score?
    If YES -> raise overall_score to match the highest sub-score,
    OR explain the discrepancy explicitly in the summary.
    A candidate cannot be worse overall than they are at every individual dimension.

[ ] KEYWORD CAP: Do fewer than 40% of JD-required keywords appear in the resume?
    If YES -> keyword_match_score MUST be <= 40
    -> note in summary: "Less than 40% of required keywords found in resume."

[ ] CRITICAL SKILL CAP: Does the JD require advanced proficiency in a specific
    technical skill (Python, R, SQL, etc.) that is completely absent from the resume?
    If YES -> overall_score MUST be <= 50 AND skill_match_score MUST be <= 45
    -> warnings MUST contain: "Critical skill gap: [skill] is required but not present in resume"

Return JSON only after ALL checks pass and ALL score adjustments are applied.
"""

    user_prompt = f"""
RESUME:
{resume_text}

REQUIREMENT / JOB DESCRIPTION:
{job_description}

Return output in this exact JSON format:
{{
  "overall_score": 0,
  "skill_match_score": 0,
  "experience_match_score": 0,
  "keyword_match_score": 0,
  "score_rationale": {{
    "overall": {{
      "explanation": "",
      "resume_quotes": ["", ""],
      "requirement_quotes": ["", ""]
    }},
    "skill": {{
      "explanation": "",
      "resume_quotes": ["", ""],
      "requirement_quotes": ["", ""]
    }},
    "experience": {{
      "explanation": "",
      "resume_quotes": ["", ""],
      "requirement_quotes": ["", ""]
    }},
    "keyword": {{
      "explanation": "",
      "resume_quotes": ["", ""],
      "requirement_quotes": ["", ""]
    }}
  }},
  "missing_keywords": ["", ""],
  "strengths": ["", ""],
  "improvements": [
    {{
      "area": "",
      "current_state": "",
      "recommendation": "",
      "priority": "high"
    }}
  ],
  "warnings": [],
  "summary": ""
}}
"""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=temperature,
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        return {"error": str(e)}






def _validate_languages(languages: list, resume_text: str) -> list:
    """
    Deterministic post-extraction language validator.

    Only retains a 'languages' entry when the resume explicitly states the
    candidate speaks / knows / is fluent in that language.

    Rejects inferences from:
      - project names  ("Spanish-language WhatsApp agent")
      - product / system locale
      - customer / market language
      - dataset or NLP model language
      - client geography
    """
    import re as _re
    if not languages or not resume_text:
        return languages or []

    text_lower = resume_text.lower()
    validated = []

    for entry in languages:
        if not isinstance(entry, dict):
            continue
        lang_name = (entry.get("language") or "").strip()
        if not lang_name:
            continue
        lang_esc = _re.escape(lang_name.lower())

        evidence_patterns = [
            # "Languages: Spanish, English" or "Language Skills: French"
            rf'(?:languages?|language[\s\-]+skills?)\s*[:\-]\s*[^\n]*\b{lang_esc}\b',
            # "fluent in Spanish" / "native French" / "proficient in Arabic"
            rf'\b(?:fluent|native|proficient|conversational|intermediate|advanced|beginner|basic|bilingual|multilingual)\s+(?:in\s+)?\b{lang_esc}\b',
            # "Spanish (Conversational)" / "German (B2)" / "French – native"
            rf'\b{lang_esc}\s*[\(\-–:]\s*(?:native|fluent|conversational|proficient|intermediate|advanced|beginner|basic|mother|tongue|a1|a2|b1|b2|c1|c2)\b',
            # "speaks Spanish" / "Spanish speaker"
            rf'\b(?:speaks?|spoken|speaking)\s+(?:\w+\s+)?\b{lang_esc}\b',
            rf'\b{lang_esc}\s+(?:speaker|speaking|spoken)\b',
            # "mother tongue: Arabic" / "first language: Urdu" / "L1: English"
            rf'\b(?:mother[\s\-]+tongue|first[\s\-]+language|native[\s\-]+language|l1)\s*[:\-]?\s*\b{lang_esc}\b',
            # CEFR level paired with language: "German: B2" / "B2 German"
            rf'\b{lang_esc}\s*[:\-\(]?\s*(?:a1|a2|b1|b2|c1|c2)\b',
            rf'\b(?:a1|a2|b1|b2|c1|c2)\s*(?:level\s+)?\b{lang_esc}\b',
            # Language test certs tied to language
            rf'\b(?:ielts|toefl|toeic|delf|dalf|dele|goethe|goethe-zertifikat|hsk|jlpt|topik|cils|celi|itals)\b[^\n]*\b{lang_esc}\b',
            rf'\b{lang_esc}\b[^\n]*\b(?:ielts|toefl|toeic|delf|dalf|dele|goethe|hsk|jlpt|topik)\b',
        ]

        if any(_re.search(p, text_lower, _re.IGNORECASE) for p in evidence_patterns):
            validated.append(entry)

    return validated


def extract_cv_data(resume_text: str, client: OpenAI) -> CVData:
    import json
    import re

    def _categorize_skills(skills_data):
        """Convert flat list or malformed skills into a proper dict."""
        if isinstance(skills_data, dict):
            fixed = {}
            for cat, val in skills_data.items():
                cat_str = str(cat).strip() if cat is not None else ""
                # Avoid generic category names
                if not cat_str or cat_str.lower().startswith("category"):
                    cat_str = "Skills"

                if isinstance(val, list):
                    fixed[cat_str] = [str(x).strip() for x in val if str(x).strip()]
                elif val is None:
                    fixed[cat_str] = []
                else:
                    fixed[cat_str] = [str(val).strip()]
            return fixed

        elif isinstance(skills_data, list):
            categorized = {}
            tech_keywords = ['python', 'java', 'sql', 'excel', 'matlab', 'c++', 'power bi', 'tableau', 'pandas', 'numpy']
            tool_keywords = ['git', 'docker', 'linux', 'azure', 'aws', 'gcp', 'jira', 'powerapps', 'dataverse']
            soft_keywords = ['leadership', 'communication', 'teamwork', 'management', 'problem solving']
            lang_keywords = ['english', 'urdu', 'french', 'german', 'arabic', 'portuguese']

            for skill in skills_data:
                s = str(skill).strip()
                if not s:
                    continue
                s_lower = s.lower()

                # If a language appears in skills list, we keep it under Languages category (still in skills),
                # but ideally languages should be extracted to "languages" field by the model prompt.
                if any(k in s_lower for k in lang_keywords):
                    categorized.setdefault("Languages", []).append(s)
                elif any(k in s_lower for k in soft_keywords):
                    categorized.setdefault("Soft Skills", []).append(s)
                elif any(k in s_lower for k in tool_keywords):
                    categorized.setdefault("Tools / Platforms", []).append(s)
                elif any(k in s_lower for k in tech_keywords):
                    categorized.setdefault("Technical Skills", []).append(s)
                else:
                    categorized.setdefault("Other Skills", []).append(s)

            return categorized

        else:
            return {}

    system_prompt = """You are a precise CV data extractor.
Your task is to read a resume and output a JSON object containing all the information.
Follow the schema exactly. Use empty strings or empty lists for missing fields.
NEVER invent information. Only extract what is explicitly written.
If a date is present, keep it in the original format.
For experience bullets, preserve the exact wording as much as possible."""

    user_prompt = f"""You are a CV data extractor. Your task is to read the resume below and output a **single JSON object** that matches this schema EXACTLY:

{{
  "name": "string",
  "email": "string",
  "phone": "string",
  "location": "string",
  "linkedin": "string",
  "summary": "string",

  "skills": {{
    "category_name": ["skill1", "skill2"],
    "category_name_2": ["skill3"]
  }},

  "experience": [
    {{
      "title": "string",
      "company": "string",
      "location": "string",
      "start_date": "string",
      "end_date": "string",
      "bullets": ["string"]
    }}
  ],

  "education": [
    {{
      "degree": "string",
      "institution": "string",
      "location": "string",
      "start_date": "string",
      "end_date": "string",
      "gpa": "string",
      "thesis": "string"
    }}
  ],

  "projects": [
    {{
      "name": "string",
      "description": "string",
      "bullets": ["string"]
    }}
  ],

  "publications": ["string"],

  "certifications": [
    {{
      "name": "string",
      "issuer": "string",
      "year": "string"
    }}
  ],

  "awards": ["string"],

  "conferences": [
    {{
      "name": "string",
      "date": "string",
      "location": "string",
      "description": "string"
    }}
  ],

  "seminars": [
    {{
      "name": "string",
      "date": "string",
      "location": "string",
      "description": "string"
    }}
  ],

  "volunteer": [
    {{
      "organization": "string",
      "role": "string",
      "start_date": "string",
      "end_date": "string",
      "bullets": ["string"]
    }}
  ],

  "languages": [
    {{
      "language": "string",
      "proficiency": "string"
    }}
  ]
}}

Rules:
- Use ONLY the keys shown above. Do NOT add any other keys.
- If information is missing, use empty string "" or empty list [] or empty dict {{}}.
- Do NOT guess. Do NOT infer. Extract only what is explicitly written.
- Skills MUST be a dictionary where keys are meaningful category names from the resume.
  Examples: "Programming Languages", "Frameworks", "Tools", "Cloud", "Soft Skills", "Languages".
- Do NOT use generic keys like "Category1", "Category2".
- Put spoken languages (English/Urdu/etc.) into the "languages" field ONLY when the resume explicitly states the candidate speaks, knows, is fluent in, or has a proficiency level for that language.
  VALID evidence → add to "languages":
    "Languages: Spanish (Conversational)"  →  add Spanish
    "Fluent in French"                     →  add French
    "Native Arabic speaker"                →  add Arabic
    "German: B2"                           →  add German
    "IELTS 7.5 (English)"                  →  add English
  INVALID evidence → do NOT add to "languages":
    "Spanish-language WhatsApp booking agent"  →  system language, not candidate ability
    "German client portal"                      →  client market, not candidate ability
    "French NLP model"                          →  dataset / model language, not candidate ability
    "Arabic speech recognition project"         →  project domain, not candidate ability
    "built for Spanish speakers"                →  product audience, not candidate ability
  If you are uncertain whether the candidate actually speaks a language, leave it out.
- For experience bullets, preserve the exact wording.
- Return ONLY the JSON object, no commentary.

Resume:
{resume_text}
"""

    json_str = None
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=4000,
        )

        json_str = response.choices[0].message.content or ""

        # Usually response_format=json_object returns clean JSON.
        # But keep a safety extractor in case anything wraps it.
        json_match = re.search(r"\{.*\}", json_str, re.DOTALL)
        if not json_match:
            raise ValueError("No JSON object found in response")

        data = json.loads(json_match.group())

        # ''''''''''''''''''''â€œ''''''''''''''' Post-process skills to ensure it's always a proper categorized dict
        if "skills" in data:
            data["skills"] = _categorize_skills(data["skills"])
        else:
            data["skills"] = {}

        cv_data = CVData(**data)

        # Deterministic language gate — remove any language entry not explicitly
        # evidenced in the raw resume text (guards against LLM inferring language
        # ability from project / system / product / client language).
        cv_data.languages = _validate_languages(cv_data.languages or [], resume_text)

        # Basic validation (soft)
        if not cv_data.name and not cv_data.email:
            raise ValueError(
                "Extraction returned empty core fields (name/email). Check resume content or schema."
            )

        return cv_data

    except Exception as e:
        st.error(f"Extraction failed: {e}")
        if json_str:
            st.error("Raw response was:\n" + json_str)
        else:
            st.error("No response content received from the model.")
        return CVData()
# =========================
# generate_cv_builder BLOCK
# =========================
def _remove_empty_cv_sections(cv_text: str) -> str:
    """
    Post-render cleanup: removes sections whose content is only
    placeholder text like 'No publications listed', 'Not specified',
    blank dates like ' |  â†’ ', etc.
    """
    EMPTY_PATTERNS = [
        r'No publications listed\.?',
        r'No projects listed\.?',
        r'Not specified\.?',
        r'None listed\.?',
        r'No certifications listed\.?',
        r'No teaching/academic experience listed\.?',
        r'No teaching experience listed\.?',
        r'No academic experience listed\.?',
        r'No languages listed\.?',
        r'No awards listed\.?',
        r'No volunteer experience listed\.?',
        r'LANGUAGE SKILLS\s*\n\s*Not specified\.?',
        r'LANGUAGES\s*\n\s*Not specified\.?',
        r'CERTIFICATIONS\s*\n[- â†’ ]*\s*\n?\s*No certifications listed\.?',
        r'TEACHING\s*/?\s*ACADEMIC EXPERIENCE\s*\n[- â†’ ]*\s*\n?\s*No teaching[^\n]*listed\.?',
        r'PUBLICATIONS\s*\n[- â†’ ]+\s*\n\s*(No publications listed\.?|None\.?)',
        r'PROJECTS\s*\n[- â†’ ]+\s*\n\s*(No projects listed\.?|None\.?)',
        r'Generated on \d{4}-\d{2}-\d{2}.*',  # Remove timestamp footer
        # Strip any "Research work inferred" filler that slipped through
        r'Research work inferred from listed publication\(s\)\.',
        r'Conducted research activities aligned with publication topic\(s\)\.',
        r'Prepared and contributed to manuscript development \(status as stated in resume\)\.',
    ]
    for pattern in EMPTY_PATTERNS:
        cv_text = re.sub(pattern, '', cv_text, flags=re.IGNORECASE | re.MULTILINE)

    # Fix blank date pattern "Institution | '''''''''''''''''''''''''''''''''''''''" ''''''''''''''''''''''''''''''''''''''''' "Institution"
    cv_text = re.sub(r'\s*\|\s*[ â†’ \-]\s*$', '', cv_text, flags=re.MULTILINE)
    cv_text = re.sub(r'\s*\|\s*[ â†’ \-]\s*\n', '\n', cv_text)

    # Collapse 3+ blank lines to max 2
    cv_text = re.sub(r'\n{3,}', '\n\n', cv_text)

    return cv_text.strip()


def _apply_tone_to_summary(summary: str, tone: str) -> str:
    """
    Lightly reframes the summary string based on tone.
    - Academic: strips corporate jargon, signals research orientation
    - Concise:  handled directly in generate_cv_builder (sentence truncation)
    """
    if tone == "Academic":
        replacements = [
            ("results-driven",    "research-oriented"),
            ("results-oriented",  "research-oriented"),
            ("dynamic",           "dedicated"),
            ("synergy",           "collaboration"),
            ("leverage",          "apply"),
            ("passionate",        "committed"),
            ("self-starter",      "independent researcher"),
            ("team player",       "collaborative researcher"),
            ("strong communicator", "effective communicator"),
        ]
        s = summary
        for old, new in replacements:
            s = s.replace(old, new).replace(old.title(), new.title())
        return s
    return summary


def generate_cv_builder(
    resume_text: str,
    requirement_text: str,
    cv_format: str,
    model: str,
    temperature: float,
    enhance: bool = True,
    customization: dict = None
) -> str:
    """
    Professional CV Builder with AI-powered customization
    """
    client = init_openai_client()
    if not client:
        return "Error: OpenAI client not initialized."

    # Step 1 ''''''''''''''''''''''''''''''''''''''' Parse language early so enhance can use it
    import re as _re
    language = "English"
    for _line in (requirement_text or "").splitlines():
        if _line.strip().startswith("LANGUAGE:"):
            language = _line.strip().replace("LANGUAGE:", "").strip()
            break

    # Step 2 ''''''''''''''''''''''''''''''''''''''' Extract data
    cv_data = extract_cv_data(resume_text, client)
    if not cv_data.name:
        return "Error: Could not extract resume data. Please check your API key and try again."

    # Store CV data for DOCX export
    st.session_state.cv_data_object = cv_data

    # Step 3 ''''''''''''''''''''''''''''''''''''''' Enhance data if toggle ON
    # Append language directive to requirement_text so the AI enhance pass uses the right language
    _lang_directive = f"\nOUTPUT LANGUAGE: Write ALL bullet points, summaries, and text content in {language}. Section headings must stay in English."

    # Europass-specific enforcement directive
    if cv_format == "Europass CV":
        _lang_directive += """

EUROPASS FORMAT RULES â€” follow exactly:
1. Follow the official Europass CV format exactly. Use standard Europass section headings only.
2. Personal Information: include name, address/location, telephone, email. Also extract and place in additional_sections: 'Nationality' and 'Date of Birth' if present in the resume.
3. Work Experience: reverse chronological order. Dates in MM/YYYY format.
4. Education and Training: reverse chronological.
5. Personal Skills: use Europass subsections â€” Mother tongue(s), Other language(s), Digital skills, Other skills.
6. Languages: for each language other than the mother tongue, assign a CEFR level (A1, A2, B1, B2, C1, or C2) based on any proficiency described. Mother tongue gets 'native' flag.
7. Additional Information: include publications (if any) and references under additional_sections keys 'References' and keep publications in the publications list.
8. Do NOT invent sections. Only include sections with real content from the resume.
9. Section headings must be: Personal Statement, Work Experience, Education and Training, Personal Skills, Language Skills, Projects, Publications, Honours & Achievements, Additional Information."""

    if enhance:
        cv_data = enhance_cv_data(
            cv_data=cv_data,
            resume_text=resume_text,
            requirement_text=(requirement_text or "") + _lang_directive,
            mode="ai"
        )

    # '''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''' Parse tone, length, theme, omitted sections from requirement_text ''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''
    tone = "Professional"
    length = "Full"
    color_hex = "#1e40af"
    omit_sections = set()

    for line in (requirement_text or "").splitlines():
        line_stripped = line.strip()
        if line_stripped.startswith("TONE:"):
            tone = line_stripped.replace("TONE:", "").strip()
        elif line_stripped.startswith("LANGUAGE:"):
            language = line_stripped.replace("LANGUAGE:", "").strip()
        elif line_stripped.startswith("LENGTH:"):
            length = line_stripped.replace("LENGTH:", "").strip()
        elif line_stripped.startswith("COLOR_THEME:"):
            parts = line_stripped.replace("COLOR_THEME:", "").strip().split("|")
            if len(parts) >= 2:
                color_hex = parts[1].strip()
        elif line_stripped.startswith("OMIT SECTIONS:"):
            raw = line_stripped.replace("OMIT SECTIONS:", "").strip()
            omit_sections = {s.strip().lower() for s in raw.split(",")}

    # '''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''' Apply section toggles to cv_data ''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''
    if "summary" in omit_sections:
        cv_data.summary = ""
    if "experience" in omit_sections:
        cv_data.experience = []
    if "education" in omit_sections:
        cv_data.education = []
    if "skills" in omit_sections:
        cv_data.skills = {}
    if "projects" in omit_sections:
        cv_data.projects = []
    if "publications" in omit_sections:
        cv_data.publications = []
    if "languages" in omit_sections:
        cv_data.languages = []
    if "certifications" in omit_sections:
        cv_data.certifications = []

    # '''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''' Apply tone to summary ''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''
    if cv_data.summary and tone != "Professional":
        if tone == "Academic":
            cv_data.summary = _apply_tone_to_summary(cv_data.summary, tone)
        elif tone == "Concise":
            sentences = cv_data.summary.split(". ")
            cv_data.summary = ". ".join(sentences[:2]).strip()
            if cv_data.summary and not cv_data.summary.endswith("."):
                cv_data.summary += "."
            for job in (cv_data.experience or []):
                if isinstance(job.get("bullets"), list):
                    job["bullets"] = job["bullets"][:2]

    # '''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''' Apply length trimming ''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''
    if length == "Condensed":
        # Top 3 roles, max 3 bullets each
        if cv_data.experience:
            cv_data.experience = cv_data.experience[:3]
        for job in (cv_data.experience or []):
            if isinstance(job.get("bullets"), list):
                job["bullets"] = job["bullets"][:3]
        if cv_data.projects:
            cv_data.projects = cv_data.projects[:3]
    elif length == "Minimal":
        # Top 2 roles, 2 bullets, no projects/certs/publications
        if cv_data.experience:
            cv_data.experience = cv_data.experience[:2]
        for job in (cv_data.experience or []):
            if isinstance(job.get("bullets"), list):
                job["bullets"] = job["bullets"][:2]
        cv_data.projects = []
        cv_data.certifications = []
        cv_data.publications = []
        # Trim summary to 1 sentence
        if cv_data.summary:
            cv_data.summary = cv_data.summary.split(". ")[0].strip()
            if not cv_data.summary.endswith("."):
                cv_data.summary += "."

    # '''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''' Store theme color in session for template injection ''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''
    st.session_state["cv_color_hex"] = color_hex
    st.session_state["cv_language"] = language

    # Step 3 ''''''''''''''''''''''''''''''''''''''' Map template
    template_map = {
        "Europass CV": "europass_template",
        "Academic CV": "academic_template",
        "One-page CV": "onepage_template",
        "ATS-Optimized CV": "ats_template"
    }
    template_name = template_map.get(cv_format, "ats_template")
    template_path = os.path.join(BASE_DIR, "templates", f"{template_name}.txt")
    # Step 4 ''''''''''''''''''''''''''''''''''''''' Get the template to use
    if customization:
        # Apply AI customization
        template_str = apply_customization_to_template(
            template_path=template_path,
            cv_data=cv_data,
            customization=customization,
            resume_text=resume_text
        )
    else:
        # Just read the original template
        with open(template_path, 'r', encoding='utf-8') as f:
            template_str = f.read()

    # Step 5 ''''''''''''''''''''''''''''''''''''''' Render with data
    try:
        from jinja2 import Environment
        
        def format_date(date_str):
            if not date_str or date_str in ["Present", "present"]:
                return date_str
            try:
                if re.match(r'[A-Za-z]{3,}\. \d{4}', date_str):
                    return date_str
                elif re.match(r'\d{2}/\d{2}/\d{4}', date_str):
                    from datetime import datetime
                    dt = datetime.strptime(date_str, '%m/%d/%Y')
                    return dt.strftime('%B %Y')
                elif re.match(r'\d{4}-\d{4}', date_str):
                    return date_str
                else:
                    return date_str
            except:
                return date_str

        env = Environment()
        env.filters['format_date'] = format_date
        jinja_template = env.from_string(template_str)
        
        data_dict = cv_data.model_dump() if hasattr(cv_data, 'model_dump') else cv_data.dict()
        data_dict['now'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        data_dict['theme_color'] = color_hex
        data_dict['cv_language'] = language
        
        filled_cv = jinja_template.render(**data_dict)

        # '''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''' Inject theme color into rendered HTML ''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''
        # Replace placeholder accent color in all templates (#1e40af is default blue)
        DEFAULT_ACCENT = "#1e40af"
        if color_hex and color_hex != DEFAULT_ACCENT:
            # Also compute a lighter tint for backgrounds (20% opacity equivalent)
            filled_cv = filled_cv.replace(DEFAULT_ACCENT, color_hex)
            # Also swap common secondary blues used in templates
            for old_blue in ["#1a56db", "#2563eb", "#1d4ed8", "#3b82f6", "#1e3a8a"]:
                filled_cv = filled_cv.replace(old_blue, color_hex)

        # '''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''' Inject language instruction if non-English ''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''
        if language and language != "English":
            # Prepend a hidden instruction comment that the AI enhance pass can use
            # Also wrap with a lang attribute for the HTML
            filled_cv = filled_cv.replace(
                '<html',
                f'<html lang="{language[:2].lower()}"',
                1
            )
            # Store language for post-processing by AI translate pass
            st.session_state["cv_needs_translation"] = language

        # ''''''''''''''''''''â€œ''''''''''''''' POST-RENDER: Remove empty sections from output
        filled_cv = _remove_empty_cv_sections(filled_cv)

        # ''''''''''''''''''''â€œ''''''''''''''' POST-RENDER: Strip generic filler phrases from HTML too
        FILLER_HTML_PHRASES = [
            "No teaching/academic experience listed.",
            "No teaching experience listed.",
            "No certifications listed.",
            "No publications listed.",
            "No projects listed.",
            "Research work inferred from listed publication(s).",
            "Conducted research activities aligned with publication topic(s).",
            "Prepared and contributed to manuscript development (status as stated in resume).",
            "Performed role responsibilities aligned with position requirements.",
            "Maintained documentation and coordinated routine tasks.",
            "Supported team and organizational objectives through consistent execution.",
        ]
        for phrase in FILLER_HTML_PHRASES:
            filled_cv = filled_cv.replace(phrase, "")

        # '''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''' AI Translation pass (non-English only) ''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''
        if language and language != "English" and client:
            try:
                translate_prompt = f"""You are a professional CV translator.
Translate ALL visible text content in the following HTML CV into {language}.
Rules:
- Translate section headers, bullet points, summary, job titles, skill labels, and all body text
- Do NOT translate: proper nouns (names, company names, university names, tool names like Python/Excel)
- Do NOT change any HTML tags, CSS, or inline styles
- Do NOT add any preamble  â†’  return ONLY the translated HTML
- Keep the exact same HTML structure

HTML CV to translate:
{filled_cv[:6000]}"""
                translate_resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": translate_prompt}],
                    temperature=0.2,
                    max_tokens=4000,
                )
                translated = translate_resp.choices[0].message.content.strip()
                if translated and "<" in translated:
                    filled_cv = translated
            except Exception:
                pass  # If translation fails, return English version silently

        return filled_cv

    except Exception as e:
        st.error(f"Template error: {e}")
        return f"Error: {str(e)}"


def generate_cv_fallback(resume_text, selected_format, name, email, phone, location, linkedin,
                        profile, research_interests, education, experience, projects, publications, skills):
    """Fallback function when template files aren't available"""
    
    cv_content = []
    
    if selected_format == "ats":
        cv_content.append(f"{name}")
        cv_content.append(f"{location if location else 'Pakistan'}  â†’  {email}  â†’  {linkedin}")
        cv_content.append("")
        cv_content.append("PROFESSIONAL SUMMARY")
        cv_content.append("-" * 50)
        cv_content.append(profile)
        cv_content.append("")
        cv_content.append("CORE COMPETENCIES")
        cv_content.append("-" * 50)
        if skills['machine_learning']:
            cv_content.append(f" â†’  Machine Learning: {', '.join(skills['machine_learning'][:3])}")
        if skills['ai_systems']:
            cv_content.append(f" â†’  AI Systems: {', '.join(skills['ai_systems'][:3])}")
        if skills['optimization']:
            cv_content.append(f" â†’  Optimization: {', '.join(skills['optimization'][:2])}")
        cv_content.append("")
        cv_content.append("PROFESSIONAL EXPERIENCE")
        cv_content.append("-" * 50)
        for job in experience:
            cv_content.append(f"{job['title']}\t{job['dates']}")
            cv_content.append(f"{job['company']}  â†’  {job['location']}")
            for bullet in job['bullets']:
                cv_content.append(f" â†’  {bullet}")
            cv_content.append("")
        cv_content.append("EDUCATION")
        cv_content.append("-" * 50)
        for edu in education:
            cv_content.append(f"{edu['degree']}")
            cv_content.append(f"{edu['institution']}, {edu['location']}")
        cv_content.append("")
        cv_content.append("PUBLICATIONS")
        cv_content.append("-" * 50)
        for pub in publications[:2]:
            cv_content.append(f" â†’  {pub}")
    
    elif selected_format == "creative":
        cv_content.append("=" * 60)
        cv_content.append(f"{name}".center(60))
        cv_content.append("=" * 60)
        cv_content.append("")
        cv_content.append(f" â†’  {email}  |   â†’  {location if location else 'Pakistan'}  |   â†’  {linkedin}")
        cv_content.append("")
        cv_content.append(" â†’ â€œ â†’ " * 60)
        cv_content.append("ABOUT ME")
        cv_content.append(" â†’ â€œ â†’ " * 60)
        cv_content.append(profile[:200] + "...")
        cv_content.append("")
        cv_content.append(" â†’ â€œ â†’ " * 60)
        cv_content.append("SKILLS")
        cv_content.append(" â†’ â€œ â†’ " * 60)
        all_skills = []
        for cat in ['machine_learning', 'ai_systems', 'optimization', 'programming']:
            all_skills.extend(skills[cat][:2])
        cv_content.append("  ".join([f"[{skill}]" for skill in all_skills[:8]]))
        cv_content.append("")
        cv_content.append(" â†’ â€œ â†’ " * 60)
        cv_content.append("EXPERIENCE")
        cv_content.append(" â†’ â€œ â†’ " * 60)
        for job in experience[:2]:
            cv_content.append(f" â†’ â€œ â†’  {job['title']}  |  {job['dates']}")
            cv_content.append(f"  {job['company']}, {job['location']}")
            if job['bullets']:
                cv_content.append(f"   â†’  {job['bullets'][0][:70]}...")
            cv_content.append("")
        cv_content.append(" â†’ â€œ â†’ " * 60)
        cv_content.append("PROJECTS")
        cv_content.append(" â†’ â€œ â†’ " * 60)
        for project in projects[:2]:
            cv_content.append(f" â†’  {project['name'].split(' â†’ ')[0].strip()}")
            cv_content.append(f"  {project['bullets'][0][:80]}..." if project['bullets'] else "")
            cv_content.append("")
    
    return "\n".join(cv_content)


# Optional: Add LaTeX export capability for academic/scientific CVs
def export_to_latex(cv_content: str, style: str = "academic") -> str:
    """
    Convert CV content to LaTeX format for publication-quality PDFs.
    Useful for academic/research positions.
    """
    latex_template = r"""
\documentclass[11pt,a4paper]{moderncv}
\moderncvstyle{banking}
\moderncvcolor{blue}

\usepackage[utf8]{inputenc}
\usepackage[scale=0.8]{geometry}

\name{}{NAME_PLACEHOLDER}
\email{EMAIL_PLACEHOLDER}
\phone{PHONE_PLACEHOLDER}
\address{ADDRESS_PLACEHOLDER}

\begin{document}
\makecvtitle

CONTENT_PLACEHOLDER

\end{document}
"""
    # This is a simplified version - you'd need a full LaTeX converter
    return "LaTeX export requires additional processing. For now, please use DOCX/PDF export."



# ----------------------------
# UI Functions
# ----------------------------
def inject_custom_css():
    """Inject custom CSS for better UI"""
    st.markdown("""
    <style>
    /* IMPORTANT: Prevent feature cards from appearing in sidebar */
    section[data-testid="stSidebar"] .feature-grid,
    section[data-testid="stSidebar"] .feature-card,
    section[data-testid="stSidebar"] .feature-icon,
    section[data-testid="stSidebar"] .welcome-screen {
        display: none !important;
        visibility: hidden !important;
        height: 0 !important;
        width: 0 !important;
        overflow: hidden !important;
        margin: 0 !important;
        padding: 0 !important;
    }

    /* Hide any white text that might appear in sidebar */
    section[data-testid="stSidebar"] h3[style*="color: white"],
    section[data-testid="stSidebar"] p[style*="color: rgba"],
    section[data-testid="stSidebar"] p[style*="color: rgb"] {
        display: none !important;
    }

    /* Sidebar styling for better readability */
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #1e3c72 0%, #2a5298 100%) !important;
        color: #ffffff !important;
    }

    /* Sidebar headers */
    section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3,
    section[data-testid="stSidebar"] h4,
    section[data-testid="stSidebar"] .stMarkdown h1,
    section[data-testid="stSidebar"] .stMarkdown h2,
    section[data-testid="stSidebar"] .stMarkdown h3,
    section[data-testid="stSidebar"] .stMarkdown h4 {
        color: #ffffff !important;
        font-weight: 600 !important;
    }

    /* Sidebar text */
    section[data-testid="stSidebar"] .stMarkdown,
    section[data-testid="stSidebar"] p,
    section[data-testid="stSidebar"] div,
    section[data-testid="stSidebar"] span {
        color: rgba(255, 255, 255, 0.9) !important;
    }

    /* Sidebar labels */
    section[data-testid="stSidebar"] label {
        color: rgba(255, 255, 255, 0.95) !important;
        font-weight: 500 !important;
    }

    /* Sidebar text inputs */
    section[data-testid="stSidebar"] .stTextInput input {
        background-color: rgba(255, 255, 255, 0.15) !important;
        color: #ffffff !important;
        border: 1px solid rgba(255, 255, 255, 0.3) !important;
        border-radius: 8px !important;
        padding: 8px 12px !important;
    }

    section[data-testid="stSidebar"] .stTextInput input:focus {
        border-color: #4dabf7 !important;
        box-shadow: 0 0 0 2px rgba(77, 171, 247, 0.3) !important;
    }

    /* Sidebar select boxes */
    section[data-testid="stSidebar"] .stSelectbox > div > div {
        background-color: rgba(255, 255, 255, 0.15) !important;
        color: #ffffff !important;
        border: 1px solid rgba(255, 255, 255, 0.3) !important;
        border-radius: 8px !important;
    }

    /* Sidebar sliders */
    section[data-testid="stSidebar"] .stSlider div[data-testid="stThumbValue"] {
        color: #ffffff !important;
        font-weight: bold !important;
    }

    section[data-testid="stSidebar"] .stSlider div[role="slider"] {
        background: #4dabf7 !important;
    }

    /* Sidebar buttons */
    section[data-testid="stSidebar"] .stButton button {
        background: linear-gradient(135deg, #4dabf7 0%, #2196f3 100%) !important;
        color: #ffffff !important;
        border: none !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
        padding: 10px 16px !important;
        transition: all 0.3s ease !important;
    }

    section[data-testid="stSidebar"] .stButton button:hover {
        background: linear-gradient(135deg, #2196f3 0%, #1976d2 100%) !important;
        transform: translateY(-2px) !important;
        box-shadow: 0 4px 12px rgba(33, 150, 243, 0.3) !important;
    }

    /* Sidebar expander */
    section[data-testid="stSidebar"] .streamlit-expanderHeader {
        background-color: rgba(255, 255, 255, 0.1) !important;
        color: #ffffff !important;
        border-radius: 8px !important;
        border: 1px solid rgba(255, 255, 255, 0.2) !important;
    }

    section[data-testid="stSidebar"] .streamlit-expanderContent {
        background-color: rgba(255, 255, 255, 0.05) !important;
        border-radius: 0 0 8px 8px !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        border-top: none !important;
        padding: 12px !important;
    }

    /* Success/Error messages in sidebar */
    section[data-testid="stSidebar"] .stAlert {
        background-color: rgba(255, 255, 255, 0.1) !important;
        border: 1px solid rgba(255, 255, 255, 0.2) !important;
        border-radius: 8px !important;
    }

    section[data-testid="stSidebar"] .stAlert[data-testid="stSuccess"] {
        border-left: 4px solid #4caf50 !important;
    }

    section[data-testid="stSidebar"] .stAlert[data-testid="stError"] {
        border-left: 4px solid #f44336 !important;
    }

    section[data-testid="stSidebar"] .stAlert[data-testid="stInfo"] {
        border-left: 4px solid #2196f3 !important;
    }

    /* Main container styling */
    .main {
        padding: 2rem;
    }

    /* Welcome screen styling - ONLY FOR MAIN CONTENT */
    .welcome-screen {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border-radius: 20px;
        padding: 3rem;
        margin: 2rem 0;
        color: white;
        text-align: center;
        box-shadow: 0 10px 30px rgba(0,0,0,0.2);
    }

    /* ... keep all your other CSS styles ... */

    /*  â†’  RESPONSE BOX  â†’  readable text on dark bg  â†’  */
    .response-box {
        background: rgba(15, 23, 42, 0.6) !important;
        border: 1px solid rgba(99, 102, 241, 0.2) !important;
        border-radius: 12px !important;
        padding: 1.5rem !important;
        color: #e2e8f0 !important;
        line-height: 1.7 !important;
    }
    .response-box p, .response-box li, .response-box div {
        color: #e2e8f0 !important;
    }
    .response-box h1, .response-box h2, .response-box h3 {
        color: #f1f5f9 !important;
    }
    .response-box strong {
        color: #ffffff !important;
    }

    /*  â†’  SCORE CARDS  â†’  */
    .score-card {
        background: rgba(79, 70, 229, 0.12) !important;
        border: 1px solid rgba(79, 70, 229, 0.3) !important;
        border-radius: 12px !important;
        padding: 1.25rem !important;
        text-align: center !important;
        margin-bottom: 0.5rem !important;
    }
    .score-value {
        font-size: 2.5rem !important;
        font-weight: 800 !important;
        color: #a5b4fc !important;
        line-height: 1 !important;
        font-family: 'Syne', sans-serif !important;
    }
    .score-label {
        font-size: 0.8rem !important;
        color: #94a3b8 !important;
        margin-top: 0.35rem !important;
        font-weight: 500 !important;
        text-transform: uppercase !important;
        letter-spacing: 0.5px !important;
    }

    /*  â†’  DOWNLOAD BUTTONS  â†’  always visible and styled  â†’  */
    [data-testid="stDownloadButton"] button {
        background: linear-gradient(135deg, #4f46e5, #7c3aed) !important;
        color: #ffffff !important;
        border: none !important;
        border-radius: 10px !important;
        font-weight: 600 !important;
        font-size: 0.9rem !important;
        padding: 0.6rem 1rem !important;
        width: 100% !important;
        transition: all 0.2s ease !important;
    }
    [data-testid="stDownloadButton"] button:hover {
        transform: translateY(-2px) !important;
        box-shadow: 0 8px 24px rgba(79,70,229,0.45) !important;
    }
    /* Plain text download  â†’  amber variant */
    [data-testid="stDownloadButton"]:last-of-type button {
        background: linear-gradient(135deg, #d97706, #b45309) !important;
    }

    /*  â†’  FIX: Main content radio labels always visible  â†’  */
    .stRadio label span,
    .stRadio label p,
    .stRadio > div > label span {
        color: #cbd5e1 !important;
    }
    .stRadio > div > label:has(input:checked) span,
    .stRadio > div > label:has(input:checked) p {
        color: #a5b4fc !important;
        font-weight: 600 !important;
    }

    /*  â†’  FIX: Indentation in st.markdown lists  â†’  */
    .stMarkdown p { margin: 0.3rem 0 !important; }
    .stMarkdown ul, .stMarkdown ol {
        margin: 0.25rem 0 0.25rem 1rem !important;
        padding-left: 1rem !important;
    }

    </style>
    """, unsafe_allow_html=True)

import re
import textwrap
import streamlit as st

def show_welcome_screen():
    html = textwrap.dedent("""
    <div class="welcome-screen">
        <h1 style="text-align: center; color: white; margin-bottom: 1.5rem;"> â†’  Anchor CV</h1>

        <div style="background-color: rgba(255, 255, 255, 0.9); border-radius: 10px; padding: 2rem; margin: 1.5rem 0;">
            <h3 style="color: #2c3e50; margin-top: 0;"> â†’ Evidence â†’ â€œAnchored Application AI</h3>

            <p style="color: #34495e; line-height: 1.6; font-size: 1.1rem;">
            We don't just reformat your resume  â†’  we map your experience to exactly what opportunities are asking for. Compatibility scores, gap analysis, and ready â†’ â€œto â†’ â€œsend outreach emails. Upload your resume and let AI do the rest!
            </p>
        </div>
    </div>
    """)

    # ''''''''''''''''''''''''''''''''''''''''' IMPORTANT: remove leading spaces before any HTML tag so Markdown won't treat it as code
    html = re.sub(r'^\s+<', '<', html, flags=re.MULTILINE)

    st.markdown(html, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button(" â†’  Start Using AnchorCV", type="primary", use_container_width=True):
            st.session_state.welcome_shown = True
            st.rerun()

    st.stop()


def format_cv_for_preview(text: str) -> str:
    """
    Renders CV text as a clean document-style HTML preview.
    Handles plain text CV output from Jinja2 templates.
    """
    if not text:
        return ""

    # If already HTML, return as-is
    if text.strip().startswith("<"):
        return text

    lines = text.split('\n')
    html = []
    in_list = False

    for line in lines:
        stripped = line.strip()

        if not stripped:
            if in_list:
                html.append('</ul>')
                in_list = False
            html.append('<div style="height:0.3rem;"></div>')
            continue

        # Section headers (ALL CAPS lines like "EXPERIENCE", "EDUCATION")
        if stripped.isupper() and len(stripped) > 2 and not stripped.startswith(' â†’ '):
            if in_list:
                html.append('</ul>')
                in_list = False
            html.append(f'<h2>{stripped}</h2>')

        # Name line (first non-empty line, typically bold/large)
        elif not html and stripped:
            html.append(f'<h1>{stripped}</h1>')

        # Separator lines
        elif set(stripped) <= set('- â†’ = â†’ '):
            continue

        # Bullet points
        elif stripped.startswith((' â†’ ', '-', '*')) and not stripped.startswith('---'):
            content = stripped.lstrip(' â†’ -* ').strip()
            # Highlight [SUGGESTED: ...] already converted to spans
            if not in_list:
                html.append('<ul style="margin:0.3rem 0 0.3rem 1rem;padding-left:0.5rem;">')
                in_list = True
            html.append(f'<li>{content}</li>')

        # Bold lines (job titles, degree names '''''''''''''''''''''''''''''''''''''' often stand alone)
        elif re.match(r'^[A-Z][^a-z]{0,3}[A-Za-z]', stripped) and len(stripped) < 80 and '|' not in stripped:
            if in_list:
                html.append('</ul>')
                in_list = False
            html.append(f'<p><strong>{stripped}</strong></p>')

        # Date/company lines (contain | separator)
        elif '|' in stripped:
            if in_list:
                html.append('</ul>')
                in_list = False
            parts = [p.strip() for p in stripped.split('|')]
            formatted = ' &nbsp;|&nbsp; '.join(
                f'<span style="color:#555;">{p}</span>' for p in parts if p
            )
            html.append(f'<p style="font-size:0.85rem;margin:0.1rem 0;">{formatted}</p>')

        # Regular paragraph
        else:
            if in_list:
                html.append('</ul>')
                in_list = False
            html.append(f'<p>{stripped}</p>')

    if in_list:
        html.append('</ul>')

    return '\n'.join(html)


_MOJIBAKE_FIXES = {
    chr(0x00E2) + chr(0x20AC) + chr(0x00A2): chr(0x2022),   # bullet -> •
    chr(0x00E2) + chr(0x20AC) + chr(0x00BA): chr(0x203A),   # single right angle quote
    chr(0x00E2) + chr(0x20AC) + chr(0x201C): chr(0x2013),   # en dash
    chr(0x00E2) + chr(0x20AC) + chr(0x201D): chr(0x2014),   # em dash
    chr(0x00E2) + chr(0x20AC) + chr(0x0153): chr(0x201C),   # left double quote
    chr(0x00E2) + chr(0x20AC) + chr(0x009D): chr(0x201D),   # right double quote
    chr(0x00E2) + chr(0x20AC) + chr(0x2122): chr(0x2019),   # right single quote
    chr(0x00E2) + chr(0x20AC) + chr(0x02DC): chr(0x2018),   # left single quote
    chr(0x00E2) + chr(0x20AC) + chr(0x00A6): chr(0x2026),   # ellipsis
    chr(0x00C2) + chr(0x00B7): chr(0x00B7),                 # middle dot
}


def format_ai_response(text: str) -> str:
    """Format AI response for better display with normalized Unicode text."""
    if not text:
        return text

    try:
        import ftfy
        text = ftfy.fix_text(text)
    except Exception:
        try:
            text = text.encode("latin-1").decode("utf-8")
        except (UnicodeDecodeError, UnicodeEncodeError):
            pass

    # Defensive de-mojibake: repair common double-encoded (UTF-8 mis-read as
    # CP1252/Latin-1) sequences so bullets, arrows, dashes and quotes render
    # correctly in the canvas UI, PDF and DOCX exports even when ftfy is not
    # installed in the runtime environment.
    for _bad, _good in _MOJIBAKE_FIXES.items():
        if _bad in text:
            text = text.replace(_bad, _good)

    text = text.replace("```markdown", "").replace("```", "").strip()

    import re

    lines = [line.rstrip() for line in text.split("\n")]

    non_empty = [line for line in lines if line.strip()]
    if non_empty:
        min_indent = min(len(line) - len(line.lstrip()) for line in non_empty)
        if min_indent > 0:
            lines = [line[min_indent:] if len(line) >= min_indent else line for line in lines]

    def _apply_inline(value: str) -> str:
        value = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', value)
        value = re.sub(
            r'(\(Evidence:\s*".*?"\))',
            r'<span style="background:rgba(245,158,11,0.15);color:#fbbf24;padding:1px 6px;border-radius:3px;font-size:0.88em;border:1px solid rgba(245,158,11,0.2);">\1</span>',
            value,
        )
        return value

    html_lines = []

    for line in lines:
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())

        if not stripped:
            html_lines.append('<div style="height:0.4rem;"></div>')
            continue

        if line.startswith("# "):
            html_lines.append(
                f'<h2 style="color:#f1f5f9;border-bottom:2px solid #4f46e5;padding-bottom:0.4rem;margin:1.2rem 0 0.6rem;">{_apply_inline(line[2:])}</h2>'
            )
        elif line.startswith("## "):
            html_lines.append(
                f'<h3 style="color:#e2e8f0;margin:1rem 0 0.4rem;">{_apply_inline(line[3:])}</h3>'
            )
        elif line.startswith("#### "):
            html_lines.append(
                f'<h5 style="color:#94a3b8;margin:0.7rem 0 0.25rem;font-size:0.95rem;font-weight:700;">{_apply_inline(line[5:])}</h5>'
            )
        elif line.startswith("##### "):
            html_lines.append(
                f'<h6 style="color:#94a3b8;margin:0.5rem 0 0.2rem;font-size:0.88rem;font-weight:600;">{_apply_inline(line[6:])}</h6>'
            )
        elif line.startswith("### "):
            html_lines.append(
                f'<h4 style="color:#cbd5e1;margin:0.8rem 0 0.3rem;">{_apply_inline(line[4:])}</h4>'
            )
        elif re.match(r'^[1-9A-C]\)', stripped):
            html_lines.append(
                f'<p style="color:#a5b4fc;font-weight:700;margin:1rem 0 0.3rem;font-size:1rem;">{_apply_inline(stripped)}</p>'
            )

        # âœ… FIXED BULLET
        elif (stripped.startswith("- ") or stripped.startswith("* ")) and indent <= 2:
            content = stripped[2:]
            html_lines.append(
                f'<div style="display:flex;gap:0.6rem;margin:0.3rem 0 0.3rem 0.5rem;">'
                '<span style="color:#6366f1;flex-shrink:0;margin-top:0.1rem;">•</span>'
                f'<span style="color:#e2e8f0;line-height:1.6;">{_apply_inline(content)}</span>'
                f'</div>'
            )

        elif indent >= 3 or stripped.startswith("\u2022") or stripped.startswith(">") or stripped.startswith("\u203a"):
            content = re.sub(r"^[•>*-]\s*", "", stripped)

            label_match = re.match(
                r"^(Do this|Proof to show|Time estimate|What's missing|Current|Recommendation)[:\s]*(.*)",
                content,
                re.IGNORECASE
            )

            if label_match:
                label = label_match.group(1)
                rest = label_match.group(2)

                label_color = {
                    "do this": "#34d399",
                    "proof to show": "#60a5fa",
                    "time estimate": "#fbbf24",
                    "what's missing": "#f87171",
                    "current": "#94a3b8",
                    "recommendation": "#a5b4fc",
                }.get(label.lower(), "#cbd5e1")

                html_lines.append(
                    f'<div style="display:flex;gap:0.5rem;margin:0.2rem 0 0.2rem 1.5rem;">'
                    f'<span style="color:{label_color};font-weight:600;flex-shrink:0;font-size:0.88rem;">{label}:</span>'
                    f'<span style="color:#cbd5e1;font-size:0.9rem;line-height:1.55;">{_apply_inline(rest)}</span>'
                    f'</div>'
                )

            # âœ… FIXED ARROW
            else:
                html_lines.append(
                    f'<div style="display:flex;gap:0.5rem;margin:0.2rem 0 0.2rem 1.5rem;">'
                    '<span style="color:#475569;flex-shrink:0;">›</span>'
                    f'<span style="color:#cbd5e1;font-size:0.9rem;line-height:1.55;">{_apply_inline(content)}</span>'
                    f'</div>'
                )

        else:
            html_lines.append(
                f'<p style="margin:0.4rem 0;line-height:1.65;color:#e2e8f0;">{_apply_inline(stripped)}</p>'
            )

    return "\n".join(html_lines)


def display_results(uploaded_resume=None, uploaded_resume_cv=None, key_prefix="tab"):
    """Display AI results + export tools + matching analysis."""
    ai_resp = st.session_state.get("ai_response")
    if not ai_resp:
        return

    is_cv_tab = (key_prefix == "tab2")

    st.markdown("---")
    st.markdown("## Your CV" if is_cv_tab else "## Results")

    result_tabs = st.tabs(["Preview", "Raw Response", "Export"])

    with result_tabs[0]:
        if is_cv_tab:
            # Highlight [SUGGESTED: ...] metrics
            preview_text = re.sub(
                r'\[SUGGESTED:\s*(.*?)\]',
                r'<span style="background:#fff3cd;border:1px solid #ffc107;border-radius:3px;'
                r'padding:1px 4px;font-size:0.85em;color:#856404;font-style:italic;"> â†’ â€œ â†’  \1 (verify)</span>',
                ai_resp
            )

            # If the output is already HTML (from Jinja2 template), use it directly.
            # Otherwise convert plain text to document HTML.
            if preview_text.strip().startswith("<"):
                inner_html = preview_text
            else:
                inner_html = format_cv_for_preview(preview_text)

            # Wrap in a full self-contained HTML document and render via iframe
            full_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: 'Arial', sans-serif;
    font-size: 13px;
    color: #111827;
    background: #f8fafc;
    padding: 20px;
  }}
  .cv-doc {{
    background: #ffffff;
    max-width: 820px;
    margin: 0 auto;
    padding: 40px 48px;
    border-radius: 8px;
    box-shadow: 0 4px 24px rgba(0,0,0,0.12);
    line-height: 1.6;
  }}
  h1 {{ font-size: 22px; font-weight: 800; margin-bottom: 2px; color: #0f172a; }}
  h2 {{
    font-size: 11px; font-weight: 700; text-transform: uppercase;
    letter-spacing: 1.8px; color: #2563eb; border-bottom: 2px solid #2563eb;
    padding-bottom: 3px; margin-top: 18px; margin-bottom: 8px;
  }}
  h3 {{ font-size: 13px; font-weight: 700; color: #0f172a; margin-top: 10px; margin-bottom: 2px; }}
  p {{ margin: 3px 0; color: #334155; }}
  li {{ color: #334155; margin-bottom: 3px; }}
  ul {{ margin: 4px 0 4px 18px; padding-left: 4px; }}
  a {{ color: #2563eb; text-decoration: none; }}
  strong {{ color: #0f172a; }}
  /* contact line */
  .contact {{ font-size: 12px; color: #475569; margin-bottom: 4px; }}
  /* date/company rows */
  .meta {{ font-size: 11.5px; color: #64748b; margin-bottom: 4px; }}
  /* section entry blocks */
  div[style*="border"] {{ border-color: #e2e8f0 !important; }}
</style>
</head>
<body>
<div class="cv-doc">
{inner_html}
</div>
</body>
</html>"""
            components.html(full_html, height=900, scrolling=True)

        else:
            formatted_response = format_ai_response(ai_resp)
            st.markdown(
                f'<div class="response-box">{formatted_response}</div>',
                unsafe_allow_html=True
            )

    with result_tabs[1]:
        st.text_area(
            "Raw Response",
            ai_resp,
            height=400,
            key=f"raw_response_{key_prefix}"
        )

    with result_tabs[2]:
        st.markdown("###  â†’  Export Options")

        filename_base = "resume_output"
        try:
            if uploaded_resume_cv and hasattr(uploaded_resume_cv, "name"):
                filename_base = uploaded_resume_cv.name.rsplit(".", 1)[0]
            elif uploaded_resume and hasattr(uploaded_resume, "name"):
                filename_base = uploaded_resume.name.rsplit(".", 1)[0]
        except:
            pass

        raw_content = ai_resp or ""
        if is_cv_tab:
            # Tab 2: HTML already comes fully styled from Jinja2 template
            # Use it directly '''''''''''''''''''''''''''''''''''''' no re-wrapping that could conflict with template CSS
            cv_html_full = wrap_html_for_print(raw_content)
        else:
            # Tab 1: plain text analysis output, needs formatting
            if is_html(raw_content):
                cv_html_fragment = raw_content
            else:
                cv_html_fragment = format_ai_response(raw_content)
            cv_html_full = wrap_html_for_print(cv_html_fragment)

        col_export1, col_export2 = st.columns(2)

        with col_export1:
            st.markdown("""
<div style="background:rgba(99,102,241,0.08);border:1px solid rgba(99,102,241,0.2);
border-radius:12px;padding:1rem 1.25rem 0.5rem;margin-bottom:0.5rem;">
<div style="font-weight:700;color:#a5b4fc;margin-bottom:0.25rem;"> â†’  DOCX Export</div>
<div style="font-size:0.8rem;color:#64748b;margin-bottom:0.75rem;">Bold headings, clean spacing  â†’  easy to edit in Word</div>
</div>""", unsafe_allow_html=True)

            if st.button(" â†’  Generate DOCX", key=f"export_docx_{key_prefix}", use_container_width=True, type="secondary"):
                from docx_fix import build_docx_from_cv_data, create_docx_from_text
                if is_cv_tab:
                    # Tab 2: always use ai_resp so DOCX matches preview and PDF exactly
                    txt_content = strip_html(ai_resp)
                    docx_io = create_docx_from_text(txt_content)
                else:
                    # Tab 1: use structured cv_data_object if available
                    _cv = st.session_state.get("cv_data_object")
                    if _cv:
                        docx_io = build_docx_from_cv_data(_cv)
                    else:
                        txt_content = strip_html(ai_resp)
                        docx_io = create_docx_from_text(txt_content)
                if docx_io:
                    st.session_state[f"docx_ready_{key_prefix}"] = docx_io.getvalue()
                    st.session_state[f"docx_filename_{key_prefix}"] = f"{filename_base}_styled.docx"
                    st.success(" â†’ â€œ â†’  DOCX ready  â†’  click Download below")

            if st.session_state.get(f"docx_ready_{key_prefix}"):
                st.download_button(
                    label=" â†’  Download DOCX",
                    data=st.session_state[f"docx_ready_{key_prefix}"],
                    file_name=st.session_state.get(f"docx_filename_{key_prefix}", f"{filename_base}_styled.docx"),
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    use_container_width=True,
                    key=f"download_docx_{key_prefix}",
                    type="primary"
                )

        with col_export2:
            st.markdown("""
<div style="background:rgba(245,158,11,0.08);border:1px solid rgba(245,158,11,0.2);
border-radius:12px;padding:1rem 1.25rem 0.5rem;margin-bottom:0.5rem;">
<div style="font-weight:700;color:#fcd34d;margin-bottom:0.25rem;"> â†’ â€œ PDF Export</div>
<div style="font-size:0.8rem;color:#64748b;margin-bottom:0.75rem;">Formatted PDF ready to attach to applications</div>
</div>""", unsafe_allow_html=True)

            if st.button(" â†’  Generate PDF", key=f"export_pdf_{key_prefix}", use_container_width=True, type="secondary"):
                pdf_io = create_pdf_from_html(cv_html_full)
                if pdf_io:
                    st.session_state[f"pdf_ready_{key_prefix}"] = pdf_io.getvalue()
                    st.session_state[f"pdf_filename_{key_prefix}"] = f"{filename_base}_transformed.pdf"
                    st.success(" â†’ â€œ â†’  PDF ready  â†’  click Download below")

            if st.session_state.get(f"pdf_ready_{key_prefix}"):
                st.download_button(
                    label=" â†’  Download PDF",
                    data=st.session_state[f"pdf_ready_{key_prefix}"],
                    file_name=st.session_state.get(f"pdf_filename_{key_prefix}", f"{filename_base}_transformed.pdf"),
                    mime="application/pdf",
                    use_container_width=True,
                    key=f"download_pdf_{key_prefix}",
                    type="primary"
                )

        st.markdown("---")
        st.markdown("""
<div style="background:rgba(15,23,42,0.4);border:1px solid rgba(255,255,255,0.06);
border-radius:12px;padding:0.75rem 1.25rem;margin-bottom:0.5rem;display:inline-block;">
<span style="font-weight:700;color:#94a3b8;"> â†’  Plain Text</span>
<span style="font-size:0.8rem;color:#475569;margin-left:0.5rem;"> â†’  copy/paste friendly version</span>
</div>""", unsafe_allow_html=True)

        txt_content = ai_resp or ""
        if is_html(txt_content):
            txt_content = strip_html(txt_content)

        st.download_button(
            label=" â†’  Download as .txt",
            data=txt_content.encode("utf-8"),
            file_name=f"{filename_base}_analysis.txt",
            mime="text/plain",
            key=f"download_txt_{key_prefix}",
            type="primary"
        )

        # â”€â”€ Save to My Files (Supabase cloud storage) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        user_id = st.session_state.get("user_id")
        if user_id:
            st.markdown("---")
            st.markdown("""
<div style="background:rgba(16,185,129,0.08);border:1px solid rgba(16,185,129,0.2);
border-radius:12px;padding:1rem 1.25rem 0.5rem;margin-bottom:0.5rem;">
<div style="font-weight:700;color:#6ee7b7;margin-bottom:0.25rem;">â˜ï¸ Cloud Storage</div>
<div style="font-size:0.8rem;color:#64748b;margin-bottom:0.75rem;">Save this result to your personal file library</div>
</div>""", unsafe_allow_html=True)
            save_fname = f"{filename_base}_analysis_{key_prefix}.txt"
            if st.button("â˜ï¸ Save to My Files", key=f"save_cloud_{key_prefix}", use_container_width=True, type="secondary"):
                try:
                    from anchor_shared import storage_upload
                    save_data = txt_content.encode("utf-8")
                    ok, msg = storage_upload(user_id, save_fname, save_data, "text/plain")
                    if ok:
                        st.success(f"âœ… Saved **{save_fname}** to your files!")
                    else:
                        st.error(f"Upload failed: {msg}")
                except Exception as _e:
                    st.error(f"Could not save to cloud: {_e}")

    # ... rest of the function (matching results) ...

    matching_result = st.session_state.get("matching_result")
    if matching_result and isinstance(matching_result, dict) and "error" not in matching_result:
        st.markdown("---")
        st.markdown("##  â†’  Matching Analysis")

        result = matching_result

        overall  = result.get("overall_score", 0)
        skill    = result.get("skill_match_score", 0)
        exp      = result.get("experience_match_score", 0)
        keyword  = result.get("keyword_match_score", 0)

        def _score_color(s):
            if s >= 70: return "#4ade80"   # green
            if s >= 45: return "#fbbf24"   # amber
            return "#f87171"               # red

        # '''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''' Score cards ''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''
        col1, col2, col3, col4 = st.columns(4)
        for col, label, val in [
            (col1, "Overall Score",      overall),
            (col2, "Skill Match",        skill),
            (col3, "Experience Match",   exp),
            (col4, "Keyword Match",      keyword),
        ]:
            color = _score_color(val)
            with col:
                st.markdown(
                    f'<div class="score-card">'
                    f'<div class="score-value" style="color:{color};">{val}</div>'
                    f'<div class="score-label">{label}</div>'
                    f'</div>',
                    unsafe_allow_html=True
                )

        # '''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''' Plotly bar chart ''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''
        st.markdown("<br>", unsafe_allow_html=True)
        fig = go.Figure()
        categories = ["Overall", "Skills", "Experience", "Keywords"]
        values     = [overall, skill, exp, keyword]
        bar_colors = [_score_color(v) for v in values]

        fig.add_trace(go.Bar(
            x=categories,
            y=values,
            marker_color=bar_colors,
            marker_line_color="rgba(255,255,255,0.1)",
            marker_line_width=1,
            text=[f"{v}/100" for v in values],
            textposition="outside",
            textfont=dict(color="#e2e8f0", size=13),
        ))

        # Reference line at 70 (good match threshold)
        fig.add_hline(
            y=70,
            line_dash="dash",
            line_color="rgba(99,102,241,0.5)",
            annotation_text="Good match threshold",
            annotation_position="top right",
            annotation_font_color="#94a3b8",
        )

        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(15,23,42,0.5)",
            font=dict(color="#e2e8f0", family="Inter, sans-serif"),
            yaxis=dict(range=[0, 110], gridcolor="rgba(255,255,255,0.06)", tickfont=dict(color="#94a3b8")),
            xaxis=dict(tickfont=dict(color="#cbd5e1", size=13)),
            margin=dict(l=10, r=10, t=20, b=10),
            height=260,
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True, key=f"score_bar_chart_{id(result)}")

        st.markdown("###  â†’  Summary")
        st.info(result.get("summary", "No summary available."))

        col_strengths, col_improvements = st.columns(2)

        with col_strengths:
            st.markdown("###  â†’ â€œ â†’  Strengths")
            if "strengths" in result and result["strengths"]:
                for strength in result["strengths"]:
                    st.markdown(f" â†’ â€œ â†’  {strength}")
            else:
                st.info("No strengths identified.")

        with col_improvements:
            st.markdown("###  â†’  Recommended Improvements")
            if "improvements" in result and result["improvements"]:
                for imp in result["improvements"]:
                    area = imp.get('area', 'Area')
                    priority = imp.get('priority', 'medium')
                    current = imp.get('current_state', 'N/A')
                    recommendation = imp.get('recommendation', 'N/A')
                    st.markdown(f"**{area}** ({priority})")
                    st.markdown(f"- Current: {current}")
                    st.markdown(f"- Recommendation: {recommendation}")
                    st.markdown("")
            else:
                st.info("No improvement recommendations.")

        if "missing_keywords" in result and result["missing_keywords"]:
            st.markdown("###  â†’ â€œ Missing Keywords")
            keywords = ", ".join(result["missing_keywords"])
            st.warning(f"Consider adding these keywords: **{keywords}**")

        # ''''''''''''''''''''â€œ''''''''''''''' NEW: Score Rationale '''''''''''''''''''''''''''''''''''''' surface the evidence quotes that were silently discarded before
        score_rationale = result.get("score_rationale", {})
        if score_rationale:
            st.markdown("---")
            st.markdown("###  â†’  Score Rationale (Evidence-Backed)")
            st.caption("Exactly what the AI grounded each score on  â†’  your resume vs. the requirement.")

            rationale_tabs = st.tabs(["Overall", "Skills", "Experience", "Keywords"])
            rationale_keys = ["overall", "skill", "experience", "keyword"]

            for tab, key in zip(rationale_tabs, rationale_keys):
                with tab:
                    section = score_rationale.get(key, {})
                    if not section:
                        st.info("No rationale available for this dimension.")
                        continue

                    explanation = section.get("explanation", "")
                    if explanation:
                        st.markdown(f"**Analysis:** {explanation}")

                    resume_quotes = section.get("resume_quotes", [])
                    req_quotes = section.get("requirement_quotes", [])

                    col_r, col_j = st.columns(2)
                    with col_r:
                        st.markdown("** â†’  From your resume:**")
                        if resume_quotes and any(q for q in resume_quotes):
                            for q in resume_quotes:
                                if q and q.strip():
                                    st.markdown(
                                        f'<div style="background:#1e3a5f; border-left:3px solid #60a5fa; '
                                        f'padding:8px 12px; border-radius:4px; margin:4px 0; font-size:0.88em; color:#e2e8f0;">'
                                        f'"{q}"</div>',
                                        unsafe_allow_html=True
                                    )
                        else:
                            st.markdown(
                                '<div style="background:#1e3a5f; border-left:3px solid #475569; '
                                'padding:8px 12px; border-radius:4px; margin:4px 0; font-size:0.88em; color:#94a3b8;">'
                                'No direct quote found  â†’  see analysis above</div>',
                                unsafe_allow_html=True
                            )
                    with col_j:
                        st.markdown("** â†’  From the requirement:**")
                        if req_quotes and any(q for q in req_quotes):
                            for q in req_quotes:
                                if q and q.strip():
                                    st.markdown(
                                        f'<div style="background:#14381f; border-left:3px solid #4ade80; '
                                        f'padding:8px 12px; border-radius:4px; margin:4px 0; font-size:0.88em; color:#e2e8f0;">'
                                        f'"{q}"</div>',
                                        unsafe_allow_html=True
                                    )
                        else:
                            st.markdown(
                                '<div style="background:#14381f; border-left:3px solid #475569; '
                                'padding:8px 12px; border-radius:4px; margin:4px 0; font-size:0.88em; color:#94a3b8;">'
                                'No direct quote found  â†’  see requirement text above</div>',
                                unsafe_allow_html=True
                            )

    # â”€â”€ Evidence & Gap Matrix (Tab 1 analysis outputs) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    gap_matrix_data = st.session_state.get("gap_matrix_data")
    if gap_matrix_data and isinstance(gap_matrix_data, list) and not is_cv_tab:
        st.markdown("---")
        with st.expander("ðŸ” Evidence & Gap Matrix", expanded=False):
            st.caption("Verbatim evidence from your resume mapped to each requirement criterion.")

            _status_styles = {
                "met":     ("background:#14381f; border-left:3px solid #4ade80;", "#4ade80", "âœ… Met"),
                "partial": ("background:#3b2a00; border-left:3px solid #fbbf24;", "#fbbf24", "âš ï¸ Partial"),
                "missing": ("background:#3b0f0f; border-left:3px solid #f87171;", "#f87171", "âŒ Missing"),
            }

            for _g in gap_matrix_data:
                _criterion = (_g.get("criterion") or "").strip()
                _status    = (_g.get("status") or "missing").strip().lower()
                _evidence  = (_g.get("evidence_quote") or "").strip()
                _desc      = (_g.get("gap_description") or "").strip()

                if not _criterion:
                    continue

                _box_style, _badge_color, _badge_label = _status_styles.get(
                    _status, _status_styles["missing"]
                )

                # Criterion + status badge
                st.markdown(
                    f'<div style="display:flex;align-items:center;gap:0.5rem;margin-top:0.75rem;">'
                    f'<span style="font-weight:600;color:#e2e8f0;">{_criterion}</span>'
                    f'<span style="font-size:0.75em;font-weight:700;color:{_badge_color};'
                    f'border:1px solid {_badge_color};border-radius:4px;padding:1px 6px;">'
                    f'{_badge_label}</span></div>',
                    unsafe_allow_html=True
                )

                # Evidence blockquote (only for met/partial with real evidence)
                if _evidence:
                    st.markdown(
                        f'<blockquote style="{_box_style}padding:8px 12px;border-radius:4px;'
                        f'margin:4px 0 0 0;font-size:0.85em;color:#e2e8f0;font-style:italic;">'
                        f'"{_evidence}"</blockquote>',
                        unsafe_allow_html=True
                    )
                elif _desc:
                    st.markdown(
                        f'<div style="background:rgba(15,23,42,0.4);border-left:3px solid #475569;'
                        f'padding:8px 12px;border-radius:4px;margin:4px 0 0 0;'
                        f'font-size:0.85em;color:#94a3b8;">{_desc}</div>',
                        unsafe_allow_html=True
                    )
                else:
                    st.markdown(
                        '<div style="background:rgba(15,23,42,0.4);border-left:3px solid #475569;'
                        'padding:8px 12px;border-radius:4px;margin:4px 0 0 0;'
                        'font-size:0.85em;color:#64748b;">No evidence found in resume.</div>',
                        unsafe_allow_html=True
                    )

# ----------------------------
# Main Application
# ----------------------------


def main():
    # ============================================
    # INITIALIZE ALL SESSION STATE VARIABLES FIRST
    # ============================================
    session_defaults = {
        'openai_api_key': "",
        'ai_response': None,
        'matching_result': None,
        'selected_model': "GPT-4o Mini",
        'temperature': 0.7,
        'feature_mode': "action",
        'selected_format': "ATS-Optimized",
        'uploaded_resume': None,
        'requirement_text': "",
        'cv_requirement': "",
        'processing_done': False,
        'current_tab': " â†’  Resume Intelligence",
        'requirement_file': None,
        'extracted_requirement_text': "",
        'welcome_shown': False,
        # ''''''''''''''''''''â€œ''''''''''''''' NEW: Resume text cache keys
        'resume_hash': None,
        'cached_resume_text': None,
        # ''''''''''''''''''''â€œ''''''''''''''' NEW: OpenAI client cache keys
        '_openai_client': None,
        '_cached_api_key': None,
    }

    for key, default_value in session_defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_value

    # Inject custom CSS
    inject_custom_css()

    # ============================================
    # SIDEBAR '''''''''''''''''''''''''''''''''''''' API key is loaded from st.secrets (no visible input)
    # ============================================
    with st.sidebar:
        # Auto-load API key from secrets if not already in session
        if not st.session_state.get("openai_api_key"):
            try:
                try:
                    oai_key = st.secrets["OPENAI_API_KEY"]
                except Exception:
                    oai_key = os.getenv("OPENAI_API_KEY", "")
                if oai_key:
                    st.session_state["openai_api_key"] = oai_key
            except Exception:
                pass

        # Show connection status (no key input field)
        if st.session_state.get("openai_api_key"):
            st.markdown(
                '<div style="background:rgba(5,150,105,0.15);border:1px solid rgba(5,150,105,0.3);'
                'border-radius:8px;padding:0.5rem 0.75rem;font-size:0.8rem;color:#6ee7b7;margin-bottom:0.75rem;">'
                ' â†’  AI Engine Connected</div>',
                unsafe_allow_html=True
            )
        else:
            st.markdown(
                '<div style="background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.3);'
                'border-radius:8px;padding:0.5rem 0.75rem;font-size:0.8rem;color:#fca5a5;margin-bottom:0.75rem;">'
                ' â†’  API key not configured in secrets</div>',
                unsafe_allow_html=True
            )

        st.markdown("---")
        st.markdown("###  â†’  AI Settings")

        st.session_state.selected_model = st.selectbox(
            "Select AI Model:",
            list(MODEL_OPTIONS.keys()),
            index=0
        )

        st.session_state.temperature = st.slider(
            "Creativity (Temperature):",
            min_value=0.0,
            max_value=1.0,
            value=st.session_state.temperature,
            step=0.1,
            help="Lower = more precise, Higher = more creative"
        )

        st.markdown("---")
        with st.expander(" â†’  Quick Start Guide", expanded=True):
            st.markdown("""
            1. **Choose a feature tab**
            2. **Upload your resume**
            3. **Paste the job / programme requirement**
            4. **Select output type and generate**

            **Supported formats:**
            - PDF, DOCX, Images (OCR)
            - Multiple export options
            """)

        if st.button(" â†’ â€œ â†’  Clear Session Data", type="secondary", use_container_width=True):
            keys_to_keep = ['openai_api_key', 'selected_model', 'temperature']
            keys_to_delete = [k for k in st.session_state.keys() if k not in keys_to_keep]
            for key in keys_to_delete:
                del st.session_state[key]
            st.success("Session data cleared!")
            st.rerun()

    # ============================================
    # MAIN CONTENT AREA
    # ============================================
    if not st.session_state.welcome_shown:
        show_welcome_screen()

    tab1, tab2 = st.tabs([" â†’  Resume Intelligence", " â†’  CV Generator"])

    # ============================================
    # TAB 1: Resume Intelligence
    # ============================================
    with tab1:
        st.markdown('<div class="analysis-card">', unsafe_allow_html=True)
        st.markdown("###  â†’ â€œ Smart Resume Intelligence")
        st.markdown("Get gap analysis, ATS fixes, email templates, cover letters, and more.")

        st.markdown('<h4 class="section-header"> â†’  Step 1: Upload Your Resume</h4>', unsafe_allow_html=True)
        uploaded_resume = st.file_uploader(
            "Upload your resume (PDF/DOCX/Image)",
            type=["pdf", "docx", "png", "jpg", "jpeg"],
            key="resume_uploader_analysis"
        )

        if uploaded_resume:
            st.success(f" â†’ â€œ â†’  {uploaded_resume.name} uploaded successfully")

            # ''''''''''''''''''''â€œ''''''''''''''' NEW: Resume text preview '''''''''''''''''''''''''''''''''''''' confirm extraction before generating
            with st.expander(" â†’  Preview Extracted Resume Text", expanded=False):
                uploaded_resume.seek(0)
                _preview_bytes = uploaded_resume.read()
                _preview_hash = hashlib.md5(_preview_bytes).hexdigest()

                # Cache extracted text so we don't re-extract on every widget interaction
                if st.session_state.get("resume_hash") != _preview_hash:
                    _preview_text = clean_text(extract_text_from_file(_preview_bytes, uploaded_resume.type))
                    st.session_state["resume_hash"] = _preview_hash
                    st.session_state["cached_resume_text"] = _preview_text

                _preview_text = st.session_state.get("cached_resume_text", "")
                if _preview_text:
                    word_count = len(_preview_text.split())
                    st.caption(f" â†’  Extracted {word_count} words from your resume")
                    st.text_area(
                        "Extracted text (read-only preview):",
                        _preview_text[:3000] + ("..." if len(_preview_text) > 3000 else ""),
                        height=200,
                        disabled=True,
                        key="resume_preview_text"
                    )
                    if word_count < 50:
                        st.warning(" â†’  Very few words extracted. Your resume may be image-based or scanned. OCR will be attempted automatically.")
                else:
                    st.error("Could not extract text. Please check the file format.")

        st.markdown('<h4 class="section-header"> â†’  Step 2: Choose Output Type</h4>', unsafe_allow_html=True)
        output_type = st.radio(
            "Select what you want to generate:",
            [
                " â†’  Application Strategy (gap analysis + dynamic plan)",
                " â†’ â€œ ATS Optimization (pass the initial screening)",
                " â†’  Resume Improvement (targeted rewrites)",
                " â†’ â€œ â†’  Cover Letter",
                " â†’  Email to Professor",
                " â†’  Job Matching (Compatibility Score)"
            ],
            key="output_type_radio"
        )

        st.markdown('<h4 class="section-header"> â†’  Step 3: Provide Additional Information</h4>', unsafe_allow_html=True)

        requirement_text = ""
        job_description = ""

        if output_type == " â†’  Job Matching (Compatibility Score)":
            st.markdown("**Job Description / Requirements**")
            job_method = st.radio(
                "How to provide job description?",
                ["Paste text", "Upload file"],
                horizontal=True,
                key="job_method"
            )
            if job_method == "Paste text":
                job_description = st.text_area(
                    "Paste job description, program details, or specific requirements:",
                    height=150,
                    placeholder="Paste the complete job description here...",
                    key="job_paste"
                )
            else:
                job_file = st.file_uploader(
                    "Upload job description file",
                    type=["pdf", "docx", "png", "jpg", "jpeg", "txt"],
                    key="job_file_upload"
                )
                if job_file:
                    with st.spinner("Extracting job description..."):
                        file_bytes = job_file.read()
                        extracted = extract_text_from_file(file_bytes, job_file.type)
                        if extracted:
                            job_description = clean_text(extracted)
                            st.success(f" â†’ â€œ â†’  Extracted {len(job_description.split())} words from {job_file.name}")
        else:
            st.markdown("**Requirements / Context (Optional)**")
            requirement_method = st.radio(
                "How to provide requirements?",
                ["None - Use resume only", "Paste text", "Upload file"],
                horizontal=True,
                key="req_method"
            )
            if requirement_method == "Paste text":
                requirement_text = st.text_area(
                    "Paste job description, program details, or specific requirements:",
                    height=150,
                    placeholder="E.g., 'PhD in Electrical Engineering at MIT focusing on renewable energy...'",
                    key="requirement_paste"
                )
            elif requirement_method == "Upload file":
                req_file = st.file_uploader(
                    "Upload requirements file",
                    type=["pdf", "docx", "png", "jpg", "jpeg", "txt"],
                    key="req_file_upload"
                )
                if req_file:
                    with st.spinner("Extracting requirements..."):
                        file_bytes = req_file.read()
                        extracted = extract_text_from_file(file_bytes, req_file.type)
                        if extracted:
                            requirement_text = clean_text(extracted)
                            st.success(f" â†’ â€œ â†’  Extracted {len(requirement_text.split())} words from {req_file.name}")

        st.markdown("---")
        if st.button(" â†’  Generate Output", type="primary", use_container_width=True):
            if not st.session_state.get("openai_api_key"):
                # Try loading from secrets one more time
                try:
                    try:
                        oai_key = st.secrets["OPENAI_API_KEY"]
                    except Exception:
                        oai_key = os.getenv("OPENAI_API_KEY", "")
                    if oai_key:
                        st.session_state["openai_api_key"] = oai_key
                    else:
                        st.error(" â†’  OpenAI API key not configured. Add OPENAI_API_KEY to Streamlit secrets or environment.")
                        st.stop()
                except Exception:
                    st.error(" â†’  OpenAI API key not configured. Add OPENAI_API_KEY to Streamlit secrets or environment.")
                    st.stop()
            elif not uploaded_resume:
                st.error("Please upload your resume in Step 1")
            else:
                # ''''''''''''''''''''â€œ''''''''''''''' FIX: Use cached resume text if available (avoids re-extraction on every click)
                uploaded_resume.seek(0)
                resume_bytes = uploaded_resume.read()
                resume_hash = hashlib.md5(resume_bytes).hexdigest()

                if st.session_state.get("resume_hash") != resume_hash:
                    step1 = st.status(" â†’  Step 1/2: Extracting resume text...", expanded=False)
                    with step1:
                        extracted_resume_text = extract_text_from_file(resume_bytes, uploaded_resume.type)
                        cleaned_resume_text = clean_text(extracted_resume_text)
                        st.session_state["resume_hash"] = resume_hash
                        st.session_state["cached_resume_text"] = cleaned_resume_text
                    step1.update(label=" â†’ â€œ â†’  Step 1/2: Resume text extracted", state="complete")
                else:
                    cleaned_resume_text = st.session_state.get("cached_resume_text", "")

                if not cleaned_resume_text:
                    st.error("Could not extract text from resume. Please check the file.")
                else:
                    # ''''''''''''''''''''â€œ''''''''''''''' NEW: Clear stale export bytes so previous download buttons don't linger
                    for export_key in ["pdf_ready_tab1", "docx_ready_tab1", "pdf_ready_tab2", "docx_ready_tab2"]:
                        st.session_state.pop(export_key, None)

                    model_name = MODEL_OPTIONS[st.session_state.selected_model]

                    step2 = st.status(" â†’ â€œ Step 2/2: Generating AI output...", expanded=False)
                    with step2:
                        if output_type == " â†’  Job Matching (Compatibility Score)":
                            if not job_description.strip():
                                st.error("Please provide a job description for matching.")
                            else:
                                result = generate_matching_score(
                                    cleaned_resume_text,
                                    job_description,
                                    model_name,
                                    st.session_state.temperature
                                )
                                if "error" in result:
                                    st.error(f"Error: {result['error']}")
                                else:
                                    st.session_state.matching_result = result
                                    st.session_state.ai_response = None
                        else:
                            intent_map = {
                                " â†’  Application Strategy (gap analysis + dynamic plan)": "Application_Strategy",
                                " â†’ â€œ ATS Optimization (pass the initial screening)": "ATS_Optimization",
                                " â†’  Resume Improvement (targeted rewrites)": "Resume_Optimization",
                                " â†’ â€œ â†’  Cover Letter": "Cover_Letter",
                                " â†’  Email to Professor": "Email_Template"
                            }
                            intent = intent_map.get(output_type, "Custom_Analysis")

                            full_requirement = f"GENERATE: {output_type}\n\n"
                            if requirement_text:
                                full_requirement += f"SPECIFIC REQUIREMENTS:\n{requirement_text}\n\n"
                            else:
                                full_requirement += "NO SPECIFIC REQUIREMENTS PROVIDED - USE ONLY THE RESUME CONTENT.\n\n"
                            full_requirement += f"INTENT: {intent}"

                            response = generate_resume_analysis(
                                cleaned_resume_text,
                                full_requirement,
                                model_name,
                                st.session_state.temperature
                            )
                            st.session_state.ai_response = response
                            st.session_state.matching_result = None

                    step2.update(label=" â†’ â€œ â†’  Step 2/2: Output ready!", state="complete")
                    st.success(" â†’ â€œ â†’  Done! Scroll down to view your results.")

        st.markdown('</div>', unsafe_allow_html=True)

        # ''''''''''''''''''''â€œ''''''''''''''' RESULTS + MATCHING INSIDE TAB 1
        display_results(uploaded_resume=uploaded_resume, uploaded_resume_cv=None, key_prefix="tab1")

    # ============================================
    # TAB 2: CV Generator
    # ============================================
    with tab2:

        # '''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''' Format descriptions ''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''
        FORMAT_META = {
            "ATS-Optimized CV": {
                "icon": " â†’ â€œ",
                "color": "#fbbf24",
                "border": "rgba(251,191,36,0.3)",
                "bg": "rgba(251,191,36,0.06)",
                "desc": "Clean, keyword-rich. Passes automated screening systems.",
                "best_for": "Job applications at large companies"
            },
            "Europass CV": {
                "icon": " â†’ ",
                "color": "#60a5fa",
                "border": "rgba(96,165,250,0.3)",
                "bg": "rgba(96,165,250,0.06)",
                "desc": "Standard EU format. Structured, recognized across Europe.",
                "best_for": "European universities & employers"
            },
            "Academic CV": {
                "icon": " â†’ ",
                "color": "#a78bfa",
                "border": "rgba(167,139,250,0.3)",
                "bg": "rgba(167,139,250,0.06)",
                "desc": "Research-focused. Includes publications, projects, education first.",
                "best_for": "PhD applications, research roles"
            },
            "One-page CV": {
                "icon": " â†’ ",
                "color": "#34d399",
                "border": "rgba(52,211,153,0.3)",
                "bg": "rgba(52,211,153,0.06)",
                "desc": "Concise single page. Most impactful points only.",
                "best_for": "Experienced professionals, quick apply"
            },
        }

        # '''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''' Header ''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''
        st.markdown("""
<div style="margin-bottom:1.5rem;">
<h2 style="color:#f1f5f9;font-family:'Syne',sans-serif;font-weight:800;
margin-bottom:0.25rem;"> â†’  Professional CV Builder</h2>
<p style="color:#64748b;font-size:0.95rem;margin:0;">
Upload your resume  â†’  choose a format  â†’  get a polished, ready-to-send CV
</p>
</div>""", unsafe_allow_html=True)

        # '''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''' Step 1 + Step 2 side by side ''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''
        col1, col2 = st.columns([1, 1], gap="large")

        with col1:
            st.markdown("""
<div style="background:rgba(99,102,241,0.06);border:1px solid rgba(99,102,241,0.2);
border-radius:14px;padding:1rem 1.25rem 0.25rem;margin-bottom:1rem;">
<div style="color:#a5b4fc;font-weight:700;font-size:0.95rem;margin-bottom:0.75rem;">
 â†’  Step 1  â†’  Upload Your Resume</div>
</div>""", unsafe_allow_html=True)

            uploaded_resume_cv = st.file_uploader(
                "Upload resume",
                type=["pdf", "docx"],
                key="resume_uploader_cv",
                label_visibility="collapsed"
            )
            if uploaded_resume_cv:
                st.success(f" â†’ â€œ â†’  {uploaded_resume_cv.name} ready")

        with col2:
            st.markdown("""
<div style="background:rgba(99,102,241,0.06);border:1px solid rgba(99,102,241,0.2);
border-radius:14px;padding:1rem 1.25rem 0.25rem;margin-bottom:1rem;">
<div style="color:#a5b4fc;font-weight:700;font-size:0.95rem;margin-bottom:0.75rem;">
 â†’  Step 2  â†’  Choose Format</div>
</div>""", unsafe_allow_html=True)

            resume_formats = list(FORMAT_META.keys())
            selected_format_cv = st.selectbox(
                "CV Format",
                resume_formats,
                key="cv_format_select",
                label_visibility="collapsed"
            )

            # Show format info card
            meta = FORMAT_META[selected_format_cv]
            st.markdown(f"""
<div style="background:{meta['bg']};border:1px solid {meta['border']};
border-radius:10px;padding:0.6rem 1rem;margin-top:0.5rem;">
<span style="font-size:1.2rem;">{meta['icon']}</span>
<span style="color:{meta['color']};font-weight:600;margin-left:0.5rem;">
{selected_format_cv}</span><br>
<span style="color:#94a3b8;font-size:0.82rem;">{meta['desc']}</span><br>
<span style="color:#475569;font-size:0.78rem;"> â†’ â€œ â†’  Best for: {meta['best_for']}</span>
</div>""", unsafe_allow_html=True)

        # '''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''' Step 3: Customization ''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''
        st.markdown("<div style='height:0.75rem'></div>", unsafe_allow_html=True)
        st.markdown("""
<div style="background:rgba(99,102,241,0.06);border:1px solid rgba(99,102,241,0.2);
border-radius:14px;padding:1rem 1.25rem 0.5rem;margin-bottom:0.75rem;">
<div style="color:#a5b4fc;font-weight:700;font-size:0.95rem;margin-bottom:0.5rem;">
 â†’  Step 3  â†’  Customise Your CV</div>
</div>""", unsafe_allow_html=True)

        # '''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''' Row 1: Target + Tone/Enhance + Sections ''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''
        c1, c2, c3 = st.columns(3, gap="medium")

        with c1:
            st.markdown('<div style="color:#94a3b8;font-size:0.8rem;font-weight:600;margin-bottom:4px;"> â†’  TARGET ROLE / PROGRAM</div>', unsafe_allow_html=True)
            cv_requirement = st.text_area(
                "target",
                height=80,
                placeholder="E.g., 'Data Scientist at fintech startup'\n'PhD in Biomedical Engineering at UCL'",
                key="cv_requirement_input",
                label_visibility="collapsed"
            )

        with c2:
            st.markdown('<div style="color:#94a3b8;font-size:0.8rem;font-weight:600;margin-bottom:4px;"> â†’  TONE</div>', unsafe_allow_html=True)
            cv_tone = st.radio(
                "tone",
                ["Professional", "Academic", "Concise"],
                index=0,
                key="cv_tone_select",
                label_visibility="collapsed"
            )
            st.markdown("<div style='height:0.4rem'></div>", unsafe_allow_html=True)
            st.markdown('<div style="color:#94a3b8;font-size:0.8rem;font-weight:600;margin-bottom:4px;"> â†’ â€œ â†’  AI ENHANCE</div>', unsafe_allow_html=True)
            enhance_cv_toggle = st.checkbox(
                "Stronger bullets + summary",
                value=True,
                key="enhance_toggle"
            )

        with c3:
            st.markdown('<div style="color:#94a3b8;font-size:0.8rem;font-weight:600;margin-bottom:4px;"> â†’  SECTIONS TO INCLUDE</div>', unsafe_allow_html=True)
            sec_summary     = st.checkbox("Summary / Profile",    value=True,  key="sec_summary")
            sec_experience  = st.checkbox("Work Experience",      value=True,  key="sec_experience")
            sec_education   = st.checkbox("Education",            value=True,  key="sec_education")
            sec_skills      = st.checkbox("Skills",               value=True,  key="sec_skills")
            sec_projects    = st.checkbox("Projects",             value=True,  key="sec_projects")
            sec_publications= st.checkbox("Publications",         value=True,  key="sec_publications")
            sec_languages   = st.checkbox("Languages",            value=True,  key="sec_languages")
            sec_certs       = st.checkbox("Certifications",       value=True,  key="sec_certs")

        # Pack section toggles into a dict to pass downstream
        cv_sections = {
            "summary":      sec_summary,
            "experience":   sec_experience,
            "education":    sec_education,
            "skills":       sec_skills,
            "projects":     sec_projects,
            "publications": sec_publications,
            "languages":    sec_languages,
            "certifications": sec_certs,
        }

        # '''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''' Row 2: Color Theme + Language + Length ''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''
        st.markdown("<div style='height:0.6rem'></div>", unsafe_allow_html=True)
        r1, r2, r3 = st.columns(3, gap="medium")

        # Colour theme swatches
        THEME_META = {
            "Classic Blue":  {"hex": "#1e40af", "preview": "#3b82f6", "label": "Classic Blue"},
            "Forest Green":  {"hex": "#166534", "preview": "#22c55e", "label": "Forest Green"},
            "Charcoal Dark": {"hex": "#1e293b", "preview": "#475569", "label": "Charcoal Dark"},
            "Ruby Red":      {"hex": "#991b1b", "preview": "#ef4444", "label": "Ruby Red"},
            "Slate Grey":    {"hex": "#374151", "preview": "#9ca3af", "label": "Slate Grey"},
            "Default":       {"hex": "#111827", "preview": "#6b7280", "label": "Default (Black)"},
        }

        with r1:
            st.markdown('<div style="color:#94a3b8;font-size:0.8rem;font-weight:600;margin-bottom:6px;"> â†’  COLOUR THEME</div>', unsafe_allow_html=True)
            # Render colour swatches as clickable radio options
            theme_names = list(THEME_META.keys())
            # Visual swatch row
            swatch_html = '<div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px;">'
            for t, m in THEME_META.items():
                swatch_html += (
                    f'<div title="{t}" style="width:22px;height:22px;border-radius:50%;'
                    f'background:{m["preview"]};border:2px solid rgba(255,255,255,0.15);'
                    f'cursor:pointer;"></div>'
                )
            swatch_html += '</div>'
            st.markdown(swatch_html, unsafe_allow_html=True)
            cv_theme = st.selectbox(
                "theme_select",
                theme_names,
                index=0,
                key="cv_theme_select",
                label_visibility="collapsed"
            )
            # Show selected hex preview
            selected_theme_meta = THEME_META[cv_theme]
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:8px;margin-top:4px;">'
                f'<div style="width:14px;height:14px;border-radius:3px;background:{selected_theme_meta["preview"]};'
                f'border:1px solid rgba(255,255,255,0.2);"></div>'
                f'<span style="color:#cbd5e1;font-size:0.8rem;">{cv_theme}</span>'
                f'</div>',
                unsafe_allow_html=True
            )

        with r2:
            st.markdown('<div style="color:#94a3b8;font-size:0.8rem;font-weight:600;margin-bottom:6px;"> â†’  OUTPUT LANGUAGE</div>', unsafe_allow_html=True)
            LANGUAGE_OPTIONS = {
                " â†’  English":  "English",
                " â†’  Spanish":  "Spanish",
                " â†’  French":   "French",
                " â†’  German":   "German",
                " â†’  Italian":  "Italian",
                " â†’  Portuguese": "Portuguese",
                " â†’  Arabic":   "Arabic",
            }
            cv_language_label = st.selectbox(
                "lang_select",
                list(LANGUAGE_OPTIONS.keys()),
                index=0,
                key="cv_language_select",
                label_visibility="collapsed"
            )
            cv_language = LANGUAGE_OPTIONS[cv_language_label]
            if cv_language != "English":
                st.markdown(
                    f'<div style="background:rgba(99,102,241,0.1);border:1px solid rgba(99,102,241,0.25);'
                    f'border-radius:8px;padding:0.4rem 0.6rem;font-size:0.75rem;color:#a5b4fc;margin-top:6px;">'
                    f' â†’  AI will write all CV content in <strong>{cv_language}</strong>. '
                    f'Section headers, bullets, and summary will all be translated.</div>',
                    unsafe_allow_html=True
                )

        with r3:
            st.markdown('<div style="color:#94a3b8;font-size:0.8rem;font-weight:600;margin-bottom:6px;"> â†’  LENGTH / DENSITY</div>', unsafe_allow_html=True)
            cv_length = st.radio(
                "length_select",
                ["Full", "Condensed", "Minimal"],
                index=0,
                key="cv_length_select",
                label_visibility="collapsed",
                captions=[
                    "All experience, full bullets",
                    "Top 3 roles, 3 bullets each",
                    "1-page essentials only",
                ]
            )

        # '''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''' Build Button ''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''
        st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)

        build_col, _ = st.columns([2, 1])
        with build_col:
            build_clicked = st.button(
                " â†’  Build Professional CV",
                type="primary",
                use_container_width=True,
                key="build_cv_btn"
            )

        if build_clicked:
            if not st.session_state.get("openai_api_key"):
                try:
                    try:
                        oai_key = st.secrets["OPENAI_API_KEY"]
                    except Exception:
                        oai_key = os.getenv("OPENAI_API_KEY", "")
                    if oai_key:
                        st.session_state["openai_api_key"] = oai_key
                    else:
                        st.error(" â†’  OpenAI API key not configured. Set OPENAI_API_KEY in Streamlit secrets or environment.")
                        st.stop()
                except Exception:
                    st.error(" â†’  OpenAI API key not configured. Set OPENAI_API_KEY in Streamlit secrets or environment.")
                    st.stop()
            elif not uploaded_resume_cv:
                st.error(" â†’  Please upload your resume first.")
            else:
                spinner_msgs = {
                    "ATS-Optimized CV": " â†’ â€œ Optimizing for ATS keywords...",
                    "Europass CV": " â†’  Building Europass format...",
                    "Academic CV": " â†’  Structuring academic sections...",
                    "One-page CV": " â†’  Condensing to one page...",
                }
                spinner_text = spinner_msgs.get(selected_format_cv, " â†’  Building your CV...")

                with st.spinner(spinner_text):
                    resume_mime_type = uploaded_resume_cv.type
                    uploaded_resume_cv.seek(0)
                    resume_bytes = uploaded_resume_cv.read()
                    extracted_resume_text = extract_text_from_file(resume_bytes, resume_mime_type)
                    cleaned_resume_text = clean_text(extracted_resume_text)

                    if not cleaned_resume_text:
                        st.error("Could not extract text from your resume. Try a different file.")
                    else:
                        model_name = MODEL_OPTIONS[st.session_state.selected_model]

                        # Build requirement string with all customizations
                        requirement_parts = []
                        if cv_requirement:
                            requirement_parts.append(f"TARGET: {cv_requirement}")
                        requirement_parts.append(f"TONE: {cv_tone}")
                        requirement_parts.append(f"LANGUAGE: {cv_language}")
                        requirement_parts.append(f"LENGTH: {cv_length}")
                        requirement_parts.append(f"COLOR_THEME: {cv_theme}|{selected_theme_meta['hex']}")
                        disabled_sections = [k for k, v in cv_sections.items() if not v]
                        if disabled_sections:
                            requirement_parts.append(f"OMIT SECTIONS: {', '.join(disabled_sections)}")
                        requirement = "\n".join(requirement_parts)

                        response = generate_cv_builder(
                            cleaned_resume_text,
                            requirement,
                            selected_format_cv,
                            model_name,
                            st.session_state.temperature,
                            enhance=enhance_cv_toggle,
                            customization=None
                        )

                        st.session_state.ai_response = response
                        st.session_state.matching_result = None

                        # Success with format-specific message
                        meta = FORMAT_META[selected_format_cv]
                        st.success(
                            f"{meta['icon']} **{selected_format_cv}** generated! "
                            f"Scroll down to view, export as DOCX or PDF."
                        )

                        if st.session_state.get("cv_has_suggested_metrics"):
                            st.warning(
                                " â†’ â€œ â†’  **Review before sending:** Some bullets contain "
                                "**[SUGGESTED: ...]** metrics  â†’  AI estimates based on your "
                                "experience. Replace with your real numbers before submitting.",
                            )

        # '''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''' Results ''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''
        display_results(
            uploaded_resume=uploaded_resume if "uploaded_resume" in locals() else None,
            uploaded_resume_cv=uploaded_resume_cv if "uploaded_resume_cv" in locals() else None,
            key_prefix="tab2"
        )

if __name__ == "__main__":
    main()
