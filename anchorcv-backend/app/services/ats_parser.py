"""
ATS Shield — Formatting linter.

Detects structural patterns in extracted resume text that commonly break or
confuse Applicant Tracking Systems: multi-column layouts, tables, contact
details that are not at the top, missing standard section headers, and
non-standard glyphs/special characters.

Everything here is heuristic and deterministic (no ML). It operates on the
plain text produced by anchor_core.extract_text_from_file.
"""

import re
from typing import Dict, List

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:\+?\d[\d\s().\-]{7,}\d)")

STANDARD_HEADERS = [
    "experience", "work experience", "professional experience",
    "employment history", "education", "skills", "technical skills",
    "projects", "summary", "professional summary", "objective",
    "certifications", "publications", "achievements", "work history",
]


def _issue(category: str, severity: str, description: str, fix: str, impact: str) -> Dict:
    return {
        "category": category,
        "severity": severity,          # "high" | "medium" | "low"
        "description": description,
        "fix": fix,
        "impact": impact,
    }


def detect_formatting_issues(text: str) -> List[Dict]:
    """
    Inspect resume text and return a list of formatting issues, each with a
    severity, human-readable description, a concrete fix, and the ATS impact.
    """
    issues: List[Dict] = []
    if not text or not text.strip():
        return [
            _issue(
                "empty",
                "high",
                "No readable text could be extracted from the document.",
                "Re-export the resume as a text-based PDF or DOCX (not a scanned image).",
                "An ATS will parse little or nothing from this file.",
            )
        ]

    lines = text.split("\n")
    nonempty = [ln for ln in lines if ln.strip()]

    # ---- 1. Multi-column layout -------------------------------------------
    # Columns usually survive text extraction as lines with two or more wide
    # internal whitespace gaps (3+ spaces) separating side-by-side content.
    multi_gap_lines = sum(1 for ln in lines if len(re.findall(r" {3,}", ln)) >= 2)
    gap_threshold = max(3, int(len(nonempty) * 0.15))
    if multi_gap_lines >= gap_threshold:
        issues.append(
            _issue(
                "columns",
                "high",
                f"Multi-column layout suspected ({multi_gap_lines} lines show side-by-side content).",
                "Switch to a single-column layout so content reads top-to-bottom.",
                "Many ATS parsers read columns left-to-right across the page, scrambling your experience.",
            )
        )

    # ---- 2. Tables --------------------------------------------------------
    pipe_lines = sum(1 for ln in lines if ln.count("|") >= 2)
    tab_lines = sum(1 for ln in lines if "\t" in ln)
    if pipe_lines >= 2 or tab_lines >= 3:
        detail = []
        if pipe_lines >= 2:
            detail.append(f"{pipe_lines} pipe-delimited rows")
        if tab_lines >= 3:
            detail.append(f"{tab_lines} tab-delimited rows")
        issues.append(
            _issue(
                "tables",
                "high",
                "Table-like structures detected (" + ", ".join(detail) + ").",
                "Replace tables with plain text lines or simple bullet points.",
                "Tables frequently lose their cell order during ATS parsing, jumbling data.",
            )
        )

    # ---- 3. Contact info position ----------------------------------------
    email_match = EMAIL_RE.search(text)
    phone_match = PHONE_RE.search(text)
    head_block = "\n".join(nonempty[:8])
    head_has_email = bool(EMAIL_RE.search(head_block))
    head_has_phone = bool(PHONE_RE.search(head_block))

    if not email_match:
        issues.append(
            _issue(
                "contact",
                "high",
                "No email address found in the resume.",
                "Add a professional email address to the header at the very top.",
                "ATS may fail to capture a contact method, dropping you from recruiter searches.",
            )
        )
    elif not head_has_email:
        issues.append(
            _issue(
                "contact",
                "medium",
                "Contact email is not near the top of the document.",
                "Move name, email, and phone into the first few lines of the resume.",
                "ATS expects contact details in the header; buried details may be missed.",
            )
        )

    if not phone_match:
        issues.append(
            _issue(
                "contact",
                "low",
                "No phone number detected.",
                "Add a phone number to the contact header.",
                "Recruiters often filter on a parseable phone field.",
            )
        )
    elif not head_has_phone and email_match and head_has_email:
        # Email is up top but phone is far away — minor.
        issues.append(
            _issue(
                "contact",
                "low",
                "Phone number appears away from the contact header.",
                "Keep email and phone together at the top.",
                "Keeps all contact fields together for reliable parsing.",
            )
        )

    # ---- 4. Standard section headers -------------------------------------
    found_headers = []
    for header in STANDARD_HEADERS:
        if re.search(rf"(?mi)^[\s\W]*{re.escape(header)}\b", text):
            found_headers.append(header)
    if len(found_headers) < 2:
        issues.append(
            _issue(
                "headers",
                "medium",
                "Few or no standard section headings were found (e.g. Experience, Education, Skills).",
                "Use clear, conventional headings such as 'Work Experience', 'Education', and 'Skills'.",
                "ATS uses section headings to categorize content; non-standard headings reduce parsing accuracy.",
            )
        )

    # ---- 5. Special characters / non-standard glyphs ---------------------
    # Flag glyphs beyond basic Latin + common accents that ATS may mangle:
    # decorative bullets, box-drawing, arrows, emoji, private-use, etc.
    problematic = set()
    for ch in text:
        cp = ord(ch)
        if cp < 0x250:          # basic Latin + Latin-1 + Latin Extended-A (accents OK)
            continue
        if ch in "‘’“”–—…•":
            # smart quotes, en/em dash, ellipsis, standard bullet — generally safe
            continue
        problematic.add(ch)
    if problematic:
        sample = " ".join(sorted(problematic)[:10])
        issues.append(
            _issue(
                "special_chars",
                "low",
                f"Non-standard characters/glyphs detected: {sample}",
                "Replace decorative symbols, icons, and unusual bullets with plain text or standard bullets.",
                "Unusual glyphs can become garbled text (e.g. 'Ã¢â‚¬') in an ATS.",
            )
        )

    return issues
