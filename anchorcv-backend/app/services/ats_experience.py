"""
ATS Shield — Experience and employment-gap extractor.

Pulls date ranges out of resume text with regex (no NLP) and derives total
years of experience, employment gaps, job count, average tenure, and a coarse
career trajectory signal.

Supported range formats:
    2019-2022            (YYYY-YYYY, hyphen / en-dash / em-dash / "to")
    2019-Present         (YYYY-Present / Current / Now)
    Jan 2019 - Mar 2021  (Month YYYY - Month YYYY)
    January 2019 - Present
"""

import re
from datetime import date
from typing import Dict, List, Optional, Tuple

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

_MONTH_RE = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t)?(?:ember)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?)"
)
# A single endpoint token: "Month YYYY" or just "YYYY".
_TOKEN = rf"((?:{_MONTH_RE})\.?\s+\d{{4}}|\d{{4}})"
_PRESENT = r"(present|current|now|ongoing|to\s+date|till\s+date)"
_SEP = r"\s*(?:-|–|—|to|until|through)\s*"

_RANGE_RE = re.compile(
    _TOKEN + _SEP + r"(?:" + _TOKEN + r"|" + _PRESENT + r")",
    re.IGNORECASE,
)


def _parse_token(token: str) -> Optional[Tuple[int, int]]:
    """Parse a 'Month YYYY' or 'YYYY' token into (year, month)."""
    if not token:
        return None
    token = token.strip().lower().replace(".", "")
    year_match = re.search(r"(19|20)\d{2}", token)
    if not year_match:
        return None
    year = int(year_match.group(0))
    month = 1
    word_match = re.search(_MONTH_RE, token)
    if word_match:
        month = _MONTHS.get(word_match.group(0)[:4], _MONTHS.get(word_match.group(0)[:3], 1))
    return year, month


def _to_date(parsed: Tuple[int, int], end: bool = False) -> date:
    year, month = parsed
    if end:
        # Use end of month-ish; day kept at 28 to stay valid for all months.
        return date(year, month, 28)
    return date(year, month, 1)


def extract_dates(text: str) -> List[Dict]:
    """
    Return a list of detected date ranges, each as:
        {"start": "YYYY-MM", "end": "YYYY-MM" | None,
         "is_present": bool, "_start": date, "_end": date}

    Internal `_start` / `_end` (date objects) support downstream math; the
    string fields are convenient for API output.
    """
    ranges: List[Dict] = []
    if not text:
        return ranges

    today = date.today()
    for match in _RANGE_RE.finditer(text):
        start_token = match.group(1)
        end_token = match.group(2)
        present_token = match.group(3)

        start_parsed = _parse_token(start_token)
        if not start_parsed:
            continue
        start_dt = _to_date(start_parsed, end=False)

        is_present = False
        if present_token:
            is_present = True
            end_dt = today
        else:
            end_parsed = _parse_token(end_token)
            if not end_parsed:
                continue
            end_dt = _to_date(end_parsed, end=True)

        # Discard impossible ranges (end before start).
        if end_dt < start_dt:
            continue

        ranges.append(
            {
                "start": start_dt.strftime("%Y-%m"),
                "end": None if is_present else end_dt.strftime("%Y-%m"),
                "is_present": is_present,
                "_start": start_dt,
                "_end": end_dt,
            }
        )

    return ranges


def _months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def _merge_intervals(intervals: List[Tuple[date, date]]) -> List[Tuple[date, date]]:
    if not intervals:
        return []
    intervals = sorted(intervals, key=lambda iv: iv[0])
    merged = [intervals[0]]
    for start, end in intervals[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def calculate_experience(date_ranges: List[Dict]) -> Dict:
    """
    Derive experience metrics from extracted date ranges.

    Returns:
        total_years   — float, overlapping periods counted once
        gaps          — list of {"from","to","months"} gaps longer than 1 month
        trajectory    — coarse string signal about tenure trend
        job_count     — number of detected roles
        avg_tenure    — float, average individual role length in years
    """
    if not date_ranges:
        return {
            "total_years": 0.0,
            "gaps": [],
            "trajectory": "insufficient_data",
            "job_count": 0,
            "avg_tenure": 0.0,
        }

    intervals = [(r["_start"], r["_end"]) for r in date_ranges]

    # Total experience from merged (de-overlapped) intervals.
    merged = _merge_intervals(intervals)
    total_months = sum(_months_between(s, e) for s, e in merged)
    total_years = round(total_months / 12.0, 1)

    # Average tenure from individual roles (overlaps allowed).
    individual_months = [max(0, _months_between(s, e)) for s, e in intervals]
    job_count = len(intervals)
    avg_tenure = round((sum(individual_months) / 12.0) / job_count, 1) if job_count else 0.0

    # Gaps between consecutive merged intervals (> 1 month).
    gaps: List[Dict] = []
    for (prev_s, prev_e), (next_s, next_e) in zip(merged, merged[1:]):
        gap_months = _months_between(prev_e, next_s)
        if gap_months > 1:
            gaps.append(
                {
                    "from": prev_e.strftime("%Y-%m"),
                    "to": next_s.strftime("%Y-%m"),
                    "months": gap_months,
                }
            )

    # Trajectory: compare tenure of earlier vs later roles (chronological).
    trajectory = "stable"
    if job_count < 2:
        trajectory = "insufficient_data"
    else:
        chrono = [m for _, m in sorted(zip(intervals, individual_months), key=lambda x: x[0][0])]
        first_half = chrono[: len(chrono) // 2] or chrono[:1]
        second_half = chrono[len(chrono) // 2:]
        avg_first = sum(first_half) / len(first_half)
        avg_second = sum(second_half) / len(second_half)
        if avg_second > avg_first * 1.25:
            trajectory = "growing"          # longer, more stable recent tenures
        elif avg_second < avg_first * 0.75:
            trajectory = "frequent_moves"   # shorter recent tenures / job hopping
        else:
            trajectory = "stable"

    return {
        "total_years": total_years,
        "gaps": gaps,
        "trajectory": trajectory,
        "job_count": job_count,
        "avg_tenure": avg_tenure,
    }
