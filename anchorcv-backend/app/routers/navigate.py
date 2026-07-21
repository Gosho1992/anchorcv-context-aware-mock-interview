"""
AI Concierge navigation endpoint.

Accepts the current page and a small non-sensitive context object from the
frontend and returns a short message + 2-3 suggested actions.  Designed to be
called only when the user opens the concierge panel (not on every page load).
"""
import json
import logging
import os

from fastapi import APIRouter, Depends
from openai import OpenAI
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional

from app.deps.auth import get_current_user

router = APIRouter(prefix="/navigate", tags=["navigate"])
logger = logging.getLogger(__name__)

VALID_PAGES = {
    "dashboard", "discover", "analysis", "builder", "files", "account", "first-resume", "canvas",
}


class NavigationContext(BaseModel):
    """Non-sensitive aggregated state from the frontend."""
    page: str = "dashboard"
    flow: Optional[str] = None
    step: Optional[int] = None
    hasCV: bool = False
    hasResults: bool = False
    has_cv_uploaded: bool = False
    has_analysis_result: bool = False
    has_builder_result: bool = False
    last_analysis_score: Optional[int] = None
    analysis_output_type: str = ""
    builder_target: str = ""
    is_new_user: bool = False
    is_premium: bool = False


class Suggestion(BaseModel):
    text: str
    action_type: str   # "navigate" | "set_output_type" | "open_builder" | "open_discover"
    payload: Dict[str, Any] = Field(default_factory=dict)


class NavigationResponse(BaseModel):
    message: str
    suggestions: List[Suggestion] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Deterministic fallbacks — used when the API call fails or times out.
# Keyed on page name; all paths are relative to the app root.
# ---------------------------------------------------------------------------
_FALLBACKS: Dict[str, NavigationResponse] = {
    "dashboard": NavigationResponse(
        message="Hi! I'm your career assistant. Where would you like to start?",
        suggestions=[
            Suggestion(text="Explore market trends & scholarships", action_type="navigate", payload={"path": "/discover"}),
            Suggestion(text="Analyse my CV against a job", action_type="navigate", payload={"path": "/analysis"}),
            Suggestion(text="Build a polished CV", action_type="navigate", payload={"path": "/builder"}),
        ],
    ),
    "discover": NavigationResponse(
        message="Discover fields, scholarships, and PhD programmes. Select your intent and type your background above.",
        suggestions=[
            Suggestion(text="Analyse my CV for a specific role", action_type="navigate", payload={"path": "/analysis"}),
            Suggestion(text="Build a tailored CV", action_type="navigate", payload={"path": "/builder"}),
        ],
    ),
    "analysis": NavigationResponse(
        message="Upload your CV and paste a job or scholarship description to get a personalised match score.",
        suggestions=[
            Suggestion(text="Explore opportunities first", action_type="navigate", payload={"path": "/discover"}),
            Suggestion(text="Build a CV instead", action_type="navigate", payload={"path": "/builder"}),
        ],
    ),
    "builder": NavigationResponse(
        message="Upload your CV and paste the job description in the text box below — I'll tailor every bullet point to the role.",
        suggestions=[
            Suggestion(text="Find a job or scholarship to target", action_type="navigate", payload={"path": "/discover"}),
            Suggestion(text="Analyse my CV first", action_type="navigate", payload={"path": "/analysis"}),
        ],
    ),
    "files": NavigationResponse(
        message="Your saved CVs and analyses live here. Run an analysis or build a CV to populate this space.",
        suggestions=[
            Suggestion(text="Run a new analysis", action_type="navigate", payload={"path": "/analysis"}),
            Suggestion(text="Build a new CV", action_type="navigate", payload={"path": "/builder"}),
        ],
    ),
    "account": NavigationResponse(
        message="Manage your premium access and account settings here.",
        suggestions=[
            Suggestion(text="Go to Dashboard", action_type="navigate", payload={"path": "/"}),
            Suggestion(text="Explore opportunities", action_type="navigate", payload={"path": "/discover"}),
        ],
    ),
    "canvas": NavigationResponse(
        message="Choose a canvas flow and move step-by-step. I can guide you through job matching, scholarships, discovery, or CV building.",
        suggestions=[
            Suggestion(text="Open guided canvas", action_type="navigate", payload={"path": "/canvas"}),
            Suggestion(text="Discover opportunities", action_type="navigate", payload={"path": "/discover"}),
            Suggestion(text="Build a CV", action_type="navigate", payload={"path": "/builder"}),
        ],
    ),
}


def _fallback(page: str) -> NavigationResponse:
    return _FALLBACKS.get(page, _FALLBACKS["dashboard"])


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT = """You are a friendly, concise career assistant inside AnchorCV — an AI-powered CV \
and career tool for international students.

Your job is to give the user a short, warm, helpful message (1-2 sentences max) and 2-3 \
suggested next actions based on where they are and what they have or haven't done yet.

AnchorCV has these sections:
- Dashboard: overview and quick links
- Canvas: guided flow-based experience
- Discover: career intelligence, scholarships, PhD programmes, job market trends by intent
- Analysis: upload CV + paste job description → match score, gap analysis, cover letter
- Builder: upload CV → builds an ATS-optimised, Europass, Academic, or One-page CV with job description tailoring
- Files: view and download previously saved CVs and analyses
- Account: premium status, sign-out

Rules:
- Keep the message under 35 words.
- Suggest 2-3 actions. Each action needs: text (button label), action_type, and payload.
- action_type values: "navigate" (payload: {"path": "/page"}), "set_output_type" (payload: {"output_type": "..."}),
  "open_builder" (no payload), "open_discover" (no payload).
- If the user seems idle or hasn't done much yet, suggest they try Discover.
- If they have an analysis result, offer to build a CV or generate a cover letter.
- If they're on Builder without a job description, remind them about the paste field.
- Never mention specific job titles unless given in context. Never mention prices.
- Be warm but brief. No bullet points in the message — one or two natural sentences.

Return ONLY valid JSON:
{
  "message": "string",
  "suggestions": [
    {"text": "button label", "action_type": "navigate", "payload": {"path": "/discover"}}
  ]
}"""


@router.post("/", response_model=NavigationResponse)
def get_navigation(
    ctx: NavigationContext,
    user: dict = Depends(get_current_user),
):
    page = ctx.page if ctx.page in VALID_PAGES else "dashboard"

    user_prompt = (
        f"Current page: {page}\n"
        + (f"Current flow: {ctx.flow}\n" if ctx.flow else "")
        + (f"Current step: {ctx.step}\n" if ctx.step is not None else "")
        + f"Has CV (canvas): {ctx.hasCV}\n"
        + f"Has results (canvas): {ctx.hasResults}\n"
        f"New user: {ctx.is_new_user}\n"
        f"Has uploaded a CV: {ctx.has_cv_uploaded}\n"
        f"Has an analysis result: {ctx.has_analysis_result}\n"
        + (f"Last analysis score: {ctx.last_analysis_score}/100\n" if ctx.last_analysis_score is not None else "")
        + (f"Analysis output type: {ctx.analysis_output_type}\n" if ctx.analysis_output_type else "")
        + f"Has a built CV: {ctx.has_builder_result}\n"
        + (f"Builder target role: {ctx.builder_target}\n" if ctx.builder_target else "")
        + f"Premium: {ctx.is_premium}\n"
    )

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))

    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.6,
            max_tokens=250,
            response_format={"type": "json_object"},
        )
        raw = json.loads(completion.choices[0].message.content or "{}")
        return NavigationResponse(
            message=raw.get("message", ""),
            suggestions=[Suggestion(**s) for s in raw.get("suggestions", [])],
        )
    except Exception as exc:
        logger.warning("Concierge API call failed: %s — using fallback", exc)
        return _fallback(page)
