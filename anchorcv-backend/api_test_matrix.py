# -*- coding: utf-8 -*-
import json
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

BASE_URL = "http://127.0.0.1:8000/api"
ROOT = Path(__file__).resolve().parents[1]
ANCHOR_CORE = ROOT / "anchor_core.py"
ENCODING_MARKERS = ["\u00C3", "\u00E2\u20AC", "\uFFFD"]
EXPECTED_STATUS = {
    "12. No CV uploaded + ATS": {400},
    "13. CV uploaded + no format selected": {400},
}
SECTION_TITLES = {
    "Professional Summary",
    "Core Competencies",
    "Work Experience",
    "Education",
    "Projects",
    "Publications",
    "Certifications",
    "Languages",
    "Awards",
    "Conferences",
    "Seminars",
    "Volunteer Experience",
}

ENGLISH_CV = """Jane Doe
Email: jane@example.com
Phone: +1 555 123 4567
Location: Berlin, Germany
LinkedIn: linkedin.com/in/janedoe

Summary:
Data-focused research assistant with experience in Python, SQL, dashboards, and stakeholder communication.

Experience:
Research Assistant, City University, 2023-Present
- Built Python scripts to clean survey data and produce weekly reports.
- Presented findings to faculty and student services teams.
- Coordinated with international students on data collection.

Education:
MSc Data Analytics, City University, 2024

Skills:
Python, SQL, Excel, Tableau, Communication, Research
"""

SHORT_CV = """Sam Lee
sam@example.com
Python and Excel
Research Assistant
Strong communication"""

JOB_POSTING = """Data Analyst role requiring Python, SQL, dashboards, stakeholder communication, and the ability to explain findings clearly to non-technical audiences."""

LONG_CV = ANCHOR_CORE.read_text(encoding="utf-8", errors="ignore")


def has_encoding_issue(text: str) -> bool:
    return any(marker in text for marker in ENCODING_MARKERS)


def has_markdown_leak(text: str) -> bool:
    return "```" in text


def detect_empty_sections(html: str) -> list[str]:
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    root = soup.find("div")
    if root is None:
        return []
    empty = []
    for section in root.find_all("div", recursive=False):
        heading = section.find("div")
        if heading is None:
            continue
        title = " ".join(heading.get_text(" ", strip=True).split())
        if title not in SECTION_TITLES:
            continue
        body_text = section.get_text(" ", strip=True)
        if body_text.startswith(title):
            body_text = body_text[len(title):].strip()
        normalized = "".join(ch for ch in body_text if ch.isalnum())
        if not normalized:
            empty.append(title)
    return empty


def summarize_response(name: str, response: httpx.Response) -> dict:
    body = response.text
    snippet = body[:200]
    html = ""
    try:
        payload = response.json()
        if isinstance(payload, dict):
            snippet_source = payload.get("result_text") or payload.get("html") or payload.get("detail") or body
            if isinstance(snippet_source, dict):
                snippet_source = json.dumps(snippet_source)
            snippet = str(snippet_source)[:200]
            html = str(payload.get("result_html") or payload.get("html") or "")
    except Exception:
        payload = None

    combined_text = body + html
    empty_sections = detect_empty_sections(html)
    issues = []
    if has_encoding_issue(combined_text):
        issues.append("encoding")
    if has_markdown_leak(combined_text):
        issues.append("markdown_leak")
    if empty_sections:
        issues.append("empty_sections:" + ", ".join(empty_sections))

    expected = EXPECTED_STATUS.get(name)
    passed = (response.status_code in expected) if expected else (response.status_code < 400 and not issues)

    return {
        "name": name,
        "status": response.status_code,
        "snippet": snippet.replace("\n", " "),
        "issues": issues,
        "pass": passed,
    }


def post_analysis(client: httpx.Client, name: str, cv_text: str, job_text: str | None):
    files = {"file": ("resume.txt", cv_text.encode("utf-8"), "text/plain")}
    data = {"output_type": "Application_Strategy"}
    if job_text is not None:
        data["requirement_text"] = job_text
    response = client.post(f"{BASE_URL}/analyse", data=data, files=files)
    return summarize_response(name, response)


def post_builder(client: httpx.Client, name: str, cv_text: str | None, cv_format: str | None, language: str = "English", length: str = "Full"):
    data = {
        "tone": "Professional",
        "language": language,
        "length": length,
        "color_theme": "#1e40af",
        "enhance": "true",
    }
    if cv_format is not None:
        data["format"] = cv_format
    files = None
    if cv_text is not None:
        files = {"file": ("resume.txt", cv_text.encode("utf-8"), "text/plain")}
    response = client.post(f"{BASE_URL}/build-cv", data=data, files=files)
    return summarize_response(name, response)


def main():
    results = []
    with httpx.Client(timeout=120.0) as client:
        results.append(post_analysis(client, "1. English CV + English job posting", ENGLISH_CV, JOB_POSTING))
        results.append(post_analysis(client, "2. English CV + no job posting", ENGLISH_CV, None))
        results.append(post_analysis(client, "3. Short CV + job posting", SHORT_CV, JOB_POSTING))
        results.append(post_analysis(client, "4. Very long CV + job posting", LONG_CV, JOB_POSTING))

        results.append(post_builder(client, "5. English CV + ATS + English", ENGLISH_CV, "ATS-Optimized CV", "English", "Full"))
        results.append(post_builder(client, "6. English CV + Europass + German", ENGLISH_CV, "Europass CV", "German", "Full"))
        results.append(post_builder(client, "7. English CV + Academic + Spanish", ENGLISH_CV, "Academic CV", "Spanish", "Full"))
        results.append(post_builder(client, "8. English CV + One-page + French", ENGLISH_CV, "One-page CV", "French", "Full"))
        results.append(post_builder(client, "9. English CV + ATS + Arabic", ENGLISH_CV, "ATS-Optimized CV", "Arabic", "Full"))
        results.append(post_builder(client, "10. English CV + Academic + Condensed", ENGLISH_CV, "Academic CV", "English", "Condensed"))
        results.append(post_builder(client, "11. English CV + Europass + Minimal", ENGLISH_CV, "Europass CV", "English", "Minimal"))
        results.append(post_builder(client, "12. No CV uploaded + ATS", None, "ATS-Optimized CV", "English", "Full"))
        results.append(post_builder(client, "13. CV uploaded + no format selected", ENGLISH_CV, "", "English", "Full"))

    for result in results:
        print(result["name"])
        print(f"Status: {result['status']}")
        print(f"First 200 chars: {result['snippet']}")
        print("Encoding issues:", "YES" if any(issue == "encoding" for issue in result["issues"]) else "NO")
        print("Markdown leaking:", "YES" if any(issue == "markdown_leak" for issue in result["issues"]) else "NO")
        empty_issue = next((issue for issue in result["issues"] if issue.startswith("empty_sections:")), None)
        print("Empty sections:", empty_issue.split(":", 1)[1] if empty_issue else "NO")
        print("Result:", "PASS" if result["pass"] else "FAIL")
        print()

    print("SUMMARY")
    for result in results:
        print(f"{result['name']} | {result['status']} | {'PASS' if result['pass'] else 'FAIL'}")


if __name__ == "__main__":
    main()

