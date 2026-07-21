"""
Shared Serper.dev (Google Search API) helper.

Docs: https://serper.dev/

Used as a supplementary web-search source alongside the structured job-board
APIs (Adzuna) and the LLM-driven discovery engine, for sources that don't have
their own structured API (LinkedIn/Indeed/Glassdoor job listings, scholarship
pages, etc.).
"""

import logging
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

SERPER_SEARCH_URL = "https://google.serper.dev/search"
REQUEST_TIMEOUT_SECONDS = 15.0


async def serper_search(query: str, num_results: int = 10) -> list:
    """
    Run a Google search via Serper.dev and return the 'organic' results list.

    Each item in the returned list is a dict with (at least) 'title', 'link',
    and 'snippet' keys, mirroring Serper's raw response shape. Returns an
    empty list (rather than raising) if the API key is missing or the request
    fails, so callers can treat this as a best-effort supplementary source.
    """
    if not query or not query.strip():
        return []

    api_key: Optional[str] = settings.serper_api_key
    if not api_key:
        logger.warning("Serper API is not configured (missing SERPER_API_KEY).")
        return []

    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json",
    }
    body = {"q": query, "num": num_results}

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(SERPER_SEARCH_URL, headers=headers, json=body)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "Serper API returned %s for query=%r: %s",
            exc.response.status_code, query, exc.response.text[:300],
        )
        return []
    except httpx.HTTPError as exc:
        logger.warning("Serper API request failed for query=%r: %s", query, exc)
        return []

    try:
        data = response.json()
    except ValueError as exc:
        logger.warning("Serper API returned unparseable JSON for query=%r: %s", query, exc)
        return []

    return data.get("organic", []) or []
