"""
Job search via the Adzuna Jobs API.

Replaces the previous Google Custom Search-based implementation. Adzuna is a
structured job-board aggregator: company name, location, posting date, and
salary all come directly from the API response, so (unlike the old Google
CSE version) there's no need to guess these fields from free-text snippets
with regex.

Docs: https://developer.adzuna.com/docs/search
"""

import logging
import re
from typing import Optional

import httpx

from app.config import settings
from app.services.serper_search import serper_search

logger = logging.getLogger(__name__)

ADZUNA_BASE_URL = "https://api.adzuna.com/v1/api/jobs"
RESULTS_PER_PAGE = 20
SNIPPET_MAX_CHARS = 500
MAX_RESULTS = 20

# Adzuna's job-search endpoint covers these ISO 3166-1 alpha-2 markets as of
# this writing. There's no "list supported countries" endpoint to check this
# against programmatically, so this map is best-effort - if Adzuna adds a new
# market, requests for it will still work via the raw-2-letter-code fallback
# in _resolve_country_code below.
_COUNTRY_CODE_MAP = {
    "GB": "gb", "UK": "gb", "UNITED KINGDOM": "gb", "ENGLAND": "gb",
    "US": "us", "USA": "us", "UNITED STATES": "us", "UNITED STATES OF AMERICA": "us",
    "DE": "de", "GERMANY": "de",
    "FR": "fr", "FRANCE": "fr",
    "AU": "au", "AUSTRALIA": "au",
    "NZ": "nz", "NEW ZEALAND": "nz",
    "CA": "ca", "CANADA": "ca",
    "IN": "in", "INDIA": "in",
    "PL": "pl", "POLAND": "pl",
    "BR": "br", "BRAZIL": "br",
    "AT": "at", "AUSTRIA": "at",
    "ZA": "za", "SOUTH AFRICA": "za",
}

DEFAULT_COUNTRY_CODE = "gb"

_EXPERIENCE_KEYWORDS = {
    "entry": "entry level",
    "mid": "mid level",
    "senior": "senior",
}

_MAX_DAYS_OLD_MAP = {
    "24h": 1,
    "3d": 3,
    "7d": 7,
}


def _resolve_country_code(country: Optional[str]) -> str:
    """Map a free-text country name/code to an Adzuna ISO alpha-2 code."""
    if not country or not country.strip():
        return DEFAULT_COUNTRY_CODE
    key = country.strip().upper()
    if key in _COUNTRY_CODE_MAP:
        return _COUNTRY_CODE_MAP[key]
    # Unrecognized but already a bare 2-letter code: pass it through rather
    # than hard-failing. Adzuna will 400 on a genuinely invalid code, and
    # that gets logged + degrades to an empty result list below.
    if len(key) == 2:
        return key.lower()
    supported = ", ".join(sorted(set(_COUNTRY_CODE_MAP.values())))
    raise ValueError(
        f"Unsupported country '{country}'. Adzuna currently covers: {supported}."
    )


def _format_salary(item: dict) -> Optional[str]:
    """Build a human-readable salary string from Adzuna's salary_min/salary_max."""
    salary_min = item.get("salary_min")
    salary_max = item.get("salary_max")
    if not salary_min and not salary_max:
        return None

    def _fmt(amount: float) -> str:
        return f"{amount:,.0f}"

    if salary_min and salary_max and round(salary_min) != round(salary_max):
        text = f"{_fmt(salary_min)}–{_fmt(salary_max)}"
    else:
        text = _fmt(salary_min or salary_max)

    if item.get("salary_is_predicted") in ("1", 1, True):
        text += " (estimated)"
    return text


def build_query(
    job_title: str,
    country: Optional[str] = None,
    experience_level: Optional[str] = None,
) -> str:
    """Build a human-readable description of the search that was run."""
    parts = [job_title.strip()]
    if experience_level and experience_level in _EXPERIENCE_KEYWORDS:
        parts.append(_EXPERIENCE_KEYWORDS[experience_level])
    parts.append("jobs")
    try:
        code = _resolve_country_code(country)
        parts.append(f"in {code.upper()}")
    except ValueError:
        if country and country.strip():
            parts.append(f"in {country.strip()}")
    return " ".join(p for p in parts if p)


async def search_jobs(
    job_title: str,
    country: Optional[str] = None,
    experience_level: Optional[str] = None,
    posted_within: Optional[str] = None,
    salary_min: Optional[int] = None,
) -> list[dict]:
    """
    Search for job postings via the Adzuna Jobs API.

    Adzuna requires a country code in the URL path (defaults to "gb" if no
    country is given or recognized - see _resolve_country_code). salary_min
    and max_days_old are passed straight through to Adzuna's own server-side
    filtering, so there's no need to guess salary from free text the way the
    old Google CSE version had to.
    """
    app_id = settings.adzuna_app_id
    app_key = settings.adzuna_api_key
    if not app_id or not app_key:
        raise RuntimeError("Adzuna API is not configured (missing app_id or app_key).")

    if not job_title or not job_title.strip():
        raise ValueError("job_title is required.")

    country_code = _resolve_country_code(country)

    what = job_title.strip()
    if experience_level in _EXPERIENCE_KEYWORDS:
        what = f"{what} {_EXPERIENCE_KEYWORDS[experience_level]}"

    params = {
        "app_id": app_id,
        "app_key": app_key,
        "what": what,
        "results_per_page": RESULTS_PER_PAGE,
        "content-type": "application/json",
    }
    if salary_min:
        params["salary_min"] = salary_min
    if posted_within in _MAX_DAYS_OLD_MAP:
        params["max_days_old"] = _MAX_DAYS_OLD_MAP[posted_within]

    url = f"{ADZUNA_BASE_URL}/{country_code}/search/1"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "Adzuna API returned %s for what=%r country=%s: %s",
            exc.response.status_code, what, country_code, exc.response.text[:300],
        )
        return []
    except httpx.HTTPError as exc:
        logger.warning(
            "Adzuna API request failed for what=%r country=%s: %s", what, country_code, exc,
        )
        return []

    data = response.json()
    raw_items = data.get("results", [])

    results: list[dict] = []
    seen_ids: set[str] = set()
    for item in raw_items:
        job_id = str(item.get("id") or item.get("redirect_url") or "")
        if not job_id or job_id in seen_ids:
            continue
        seen_ids.add(job_id)

        snippet = (item.get("description", "") or "").replace("\n", " ")[:SNIPPET_MAX_CHARS]

        results.append({
            "title": (item.get("title", "") or "").strip(),
            "company": (item.get("company") or {}).get("display_name", "Unknown"),
            "url": item.get("redirect_url", ""),
            "snippet": snippet,
            "location": (item.get("location") or {}).get("display_name", "Unknown"),
            "posted_at": item.get("created"),
            "salary": _format_salary(item),
            "source": "Adzuna",
        })

    return results[:MAX_RESULTS]


# ---------------------------------------------------------------------------
# Serper.dev (Google search) supplementary job source
#
# Adzuna is a structured job-board aggregator, but it doesn't cover every
# listing on LinkedIn/Indeed/Glassdoor. search_jobs_serper() supplements it
# with live Google search results scoped to those three sites. Unlike Adzuna,
# Serper returns free-text search snippets rather than structured job data,
# so company/location have to be guessed from the title/snippet text via the
# extract_company/extract_location helpers below.
# ---------------------------------------------------------------------------

_COMPANY_STOPWORDS = {"linkedin", "indeed", "glassdoor", "job", "jobs"}


def extract_company(title: str, snippet: str = "") -> str:
    """
    Best-effort guess at the employer name from a Google search result's
    title/snippet. Handles the common listing title patterns:
      "Job Title at Company Name | LinkedIn"
      "Company Name hiring Job Title in Location | LinkedIn"
      "Job Title - Company Name - Indeed.com"
    Falls back to "Unknown" (matching the Adzuna result shape) if nothing
    matches.
    """
    text = (title or "").strip()
    if not text:
        return "Unknown"

    # "... at <Company> | Site" or "... at <Company> - Site"
    match = re.search(r"\bat\s+([A-Z][\w&.,'\-]*(?:\s+[\w&.,'\-]+){0,4})", text)
    if match:
        candidate = re.split(r"\s[-|–—]\s", match.group(1))[0].strip(" -|–—")
        if candidate and candidate.lower() not in _COMPANY_STOPWORDS:
            return candidate

    # "<Company> hiring <Job Title>"
    match = re.search(r"^([A-Z][\w&.,'\-]*(?:\s+[\w&.,'\-]+){0,4}?)\s+(?:is\s+)?hiring\b", text)
    if match:
        candidate = match.group(1).strip()
        if candidate and candidate.lower() not in _COMPANY_STOPWORDS:
            return candidate

    # "Job Title - Company Name - Site" (take the middle/last non-site segment)
    segments = [s.strip() for s in re.split(r"\s[-|–—]\s", text) if s.strip()]
    for segment in reversed(segments[:-1] if len(segments) > 1 else segments):
        if segment.lower() not in _COMPANY_STOPWORDS and len(segment) <= 60:
            return segment

    return "Unknown"


def extract_location(snippet: str, title: str = "") -> str:
    """
    Best-effort guess at the job location from a Google search result's
    title/snippet text (e.g. "... in London, UK ...", "... based in Austin,
    TX ..."). Falls back to "Unknown" (matching the Adzuna result shape).
    """
    text = f"{title or ''} {snippet or ''}".strip()
    if not text:
        return "Unknown"

    match = re.search(
        r"\b(?:in|based in|location:?)\s+([A-Z][A-Za-z.\-]+(?:\s[A-Z][A-Za-z.\-]+)?"
        r"(?:,\s*[A-Z][A-Za-z.\-]+)?)",
        text,
    )
    if match:
        return match.group(1).strip(" ,.")

    return "Unknown"


async def search_jobs_serper(
    job_title: str,
    country: Optional[str] = None,
    posted_within: Optional[str] = None,
) -> list[dict]:
    """
    Supplement Adzuna with live Google search results (via Serper.dev). The
    query is a plain '{job_title} jobs {country}' with NO site: operators —
    Serper's free tier rejects boolean site-filter patterns with a 400
    "Query pattern not allowed for free accounts" error. posted_within is
    accepted for API-shape consistency with search_jobs() but isn't enforced
    server-side here since Serper's shared search helper only takes a query +
    result count; results are simply not filtered by recency the way Adzuna's are.
    """
    if not job_title or not job_title.strip():
        return []

    query_parts = [job_title.strip(), "jobs"]
    if country and country.strip():
        query_parts.append(country.strip())
    query = " ".join(query_parts)

    organic = await serper_search(query, num_results=MAX_RESULTS)

    results: list[dict] = []
    seen_urls: set[str] = set()
    for item in organic:
        title = (item.get("title") or "").strip()
        url = (item.get("link") or "").strip()
        if not title or not url or url in seen_urls:
            continue
        seen_urls.add(url)

        snippet = (item.get("snippet") or "").strip()[:SNIPPET_MAX_CHARS]

        results.append({
            "title": title,
            "company": extract_company(title, snippet),
            "url": url,
            "snippet": snippet,
            "location": extract_location(snippet, title),
            "posted_at": None,
            "salary": None,
            "source": "Google Search",
        })

    return results[:MAX_RESULTS]
