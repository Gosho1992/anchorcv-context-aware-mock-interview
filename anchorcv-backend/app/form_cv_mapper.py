from __future__ import annotations

import re
import sys
from typing import Any

from app.config import WORKSPACE_ROOT

if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from anchor_core import CVData  # noqa: E402


DEFAULT_SECTION_ORDER = [
    "summary",
    "experience",
    "education",
    "skills",
    "projects",
    "certifications",
    "languages",
]


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _lines(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_text(item) for item in value if _text(item)]
    return [line.strip() for line in _text(value).splitlines() if line.strip()]


def _comma_or_lines(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_text(item) for item in value if _text(item)]
    return [part.strip() for part in re.split(r"[\n,]+", _text(value)) if part.strip()]


def _has_content(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(_has_content(item) for item in value)
    if isinstance(value, dict):
        return any(_has_content(item) for item in value.values())
    return value is not None


def _ordered_sections(section_order: Any) -> list[str]:
    if not isinstance(section_order, list):
        return DEFAULT_SECTION_ORDER[:]

    seen: set[str] = set()
    ordered: list[str] = []
    for item in section_order:
        key = _text(item).lower().replace("-", "_").replace(" ", "_")
        if key and key not in seen:
            seen.add(key)
            ordered.append(key)

    for key in DEFAULT_SECTION_ORDER:
        if key not in seen:
            ordered.append(key)
    return ordered


def form_to_cv_data(form_data: dict[str, Any], section_order: list[str] | None = None) -> CVData:
    """
    Map First Resume form JSON to the exact CVData schema returned by extract_cv_data().
    Missing fields use the same empty strings, lists, and dicts expected by CVData.
    """
    form_data = form_data or {}
    personal = form_data.get("personal") or {}

    cv_dict: dict[str, Any] = {
        "name": _text(personal.get("name") or form_data.get("name")),
        "email": _text(personal.get("email") or form_data.get("email")),
        "phone": _text(personal.get("phone") or form_data.get("phone")),
        "location": _text(personal.get("location") or form_data.get("location")),
        "linkedin": _text(personal.get("linkedin") or form_data.get("linkedin")),
        "summary": "",
        "skills": {},
        "experience": [],
        "education": [],
        "projects": [],
        "publications": [],
        "certifications": [],
        "awards": [],
        "conferences": [],
        "seminars": [],
        "volunteer": [],
        "languages": [],
        "additional_sections": {},
        "content_analysis": {
            "source": "first_resume_form",
            "section_order": _ordered_sections(section_order),
        },
    }

    sections = form_data.get("sections") or {}

    summary = _text(sections.get("summary") or form_data.get("summary"))
    if summary:
        cv_dict["summary"] = summary

    skills = _comma_or_lines(sections.get("skills") or form_data.get("skills"))
    if skills:
        cv_dict["skills"] = {"Skills": skills}

    for item in sections.get("experience") or form_data.get("experience") or []:
        if not isinstance(item, dict):
            continue
        entry = {
            "title": _text(item.get("title")),
            "company": _text(item.get("company")),
            "location": _text(item.get("location")),
            "start_date": _text(item.get("start_date") or item.get("dates")),
            "end_date": "Present" if item.get("current") else _text(item.get("end_date")),
            "bullets": _lines(item.get("bullets")),
        }
        if any(_has_content(entry[key]) for key in ("title", "company", "location", "start_date", "bullets")) or (
            entry["end_date"] and not item.get("current")
        ):
            cv_dict["experience"].append(entry)

    for item in sections.get("education") or form_data.get("education") or []:
        if not isinstance(item, dict):
            continue
        coursework = _text(item.get("coursework"))
        thesis_parts = []
        if coursework:
            thesis_parts.append(f"Coursework: {coursework}")
        entry = {
            "degree": _text(item.get("degree")),
            "institution": _text(item.get("institution")),
            "location": _text(item.get("location")),
            "start_date": _text(item.get("start_date")),
            "end_date": _text(item.get("end_date")),
            "gpa": _text(item.get("gpa")),
            "thesis": "; ".join(thesis_parts),
        }
        if _has_content(entry):
            cv_dict["education"].append(entry)

    for item in sections.get("projects") or form_data.get("projects") or []:
        if not isinstance(item, dict):
            continue
        detail_parts = [_text(item.get("description"))]
        technologies = _text(item.get("technologies"))
        link = _text(item.get("link"))
        if technologies:
            detail_parts.append(f"Technologies: {technologies}")
        if link:
            detail_parts.append(f"Link: {link}")
        entry = {
            "name": _text(item.get("name")),
            "description": " ".join(part for part in detail_parts if part),
            "bullets": _lines(item.get("bullets")),
        }
        if _has_content(entry):
            cv_dict["projects"].append(entry)

    custom_sections = sections.get("custom_sections") or form_data.get("custom_sections") or []
    for section in custom_sections:
        if not isinstance(section, dict):
            continue
        key = _text(section.get("type") or section.get("name")).lower().replace(" ", "_")
        label = _text(section.get("name") or section.get("type") or "Additional")
        values = _lines(section.get("content") or section.get("items"))
        if not values:
            continue

        if key == "certifications":
            cv_dict["certifications"].extend(
                {"name": value, "issuer": "", "year": ""} for value in values
            )
        elif key == "awards":
            cv_dict["awards"].extend(values)
        elif key == "publications":
            cv_dict["publications"].extend(values)
        elif key in {"volunteer_work", "volunteer"}:
            cv_dict["volunteer"].extend(
                {"organization": value, "role": "", "start_date": "", "end_date": "", "bullets": []}
                for value in values
            )
        elif key == "languages":
            cv_dict["languages"].extend(
                {"language": value, "proficiency": ""} for value in values
            )
        elif key == "conferences":
            cv_dict["conferences"].extend(
                {"name": value, "date": "", "location": "", "description": ""} for value in values
            )
        elif key == "references":
            cv_dict["additional_sections"]["References"] = values
        else:
            cv_dict["additional_sections"][label] = values

    return CVData(**cv_dict)
