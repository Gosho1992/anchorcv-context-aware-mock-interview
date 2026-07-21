"""
Standalone manual test for app.services.job_search.search_jobs() (Adzuna).

Bypasses the FastAPI route and auth layer entirely — calls the service
function directly so you can verify the real Adzuna API call, field-mapping,
and country-code resolution in isolation.

Run from the anchorcv-backend directory (so the app package and .env
resolve correctly):

    python test_job_search.py

Reads ADZUNA_APP_ID / ADZUNA_API_KEY from .env via app.config.
"""

import asyncio
import json
import sys

from app.config import settings
from app.services.job_search import search_jobs


async def main() -> int:
    print("=== job_search manual test ===")
    print(f"job_title=Data Analyst  country=UK")

    if not settings.adzuna_app_id or not settings.adzuna_api_key:
        print(
            "\nERROR: ADZUNA_APP_ID and/or ADZUNA_API_KEY are not set in .env.\n"
            "Add both values to anchorcv-backend/.env and re-run."
        )
        return 1

    try:
        jobs = await search_jobs(
            job_title="Data Analyst",
            country="UK",
        )
    except RuntimeError as exc:
        print(f"\nCONFIG ERROR: {exc}")
        return 1
    except ValueError as exc:
        print(f"\nINPUT ERROR: {exc}")
        return 1
    except Exception as exc:
        print(f"\nUNEXPECTED ERROR: {type(exc).__name__}: {exc}")
        return 1

    print(f"\nReturned {len(jobs)} job(s):\n")
    for i, job in enumerate(jobs, start=1):
        print(f"--- #{i} ---")
        print(json.dumps(job, indent=2, ensure_ascii=False))
        print()

    if not jobs:
        print(
            "No results came back. This can mean: the query genuinely had no "
            "matches, or the app_id/app_key pair is invalid/rate-limited. "
            "Check the warning-level log output above (if any) for the "
            "actual HTTP status Adzuna returned."
        )

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
