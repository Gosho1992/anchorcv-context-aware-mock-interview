# AnchorCV — Discovery Pipeline Implementation Plan

> **For:** Codex CLI / Codex IDE (or any coding agent).
> **Goal:** Implement a "Career Discovery" feature that doubles as the onboarding entry point for new users.
> **Estimated effort:** 3–5 hours of agent time, including tests.
> **Author:** review-derived spec, not exploratory. Do exactly what is here unless you find a hard contradiction; if so, stop and report.

---

## 0. WHO YOU ARE AND WHAT YOU MUST NOT DO

You are a coding agent working in the AnchorCV monorepo at `C:\Users\SiliCon\Downloads\ANCHOR CV\` (Windows) or `/root/ANCHOR CV/` (production server). The app has two parts:

- **Backend:** FastAPI at `anchorcv-backend/`
- **Frontend:** React + Vite at `anchorcv-frontend/`

### DO NOT TOUCH

These files were just stabilised and any change is regression risk:

- `anchorcv-backend/app/routers/webhook.py` — Lemon Squeezy webhook, already fixed
- `anchorcv-backend/app/routers/payments.py` — payment router
- `anchorcv-backend/app/routers/extension.py` — Chrome extension router
- `anchorcv-backend/app/services/legacy_bridge.py` — legacy CV pipeline glue (read-only — you may import from it but do not modify)
- `anchorcv-backend/anchor_shared.py` (root) — Supabase + Lemon Squeezy helpers, do not modify
- `anchorcv-frontend/src/pages/BuilderPage.jsx` and `FilesPage.jsx` — different feature, leave alone

### DO NOT INVENT

- Do **not** invent Python imports. The OpenAI client is created locally per-call:
  `from openai import OpenAI; client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))`
- Do **not** import `openai_client` from anywhere — it does not exist.
- Do **not** install new npm packages or pip packages. Everything below uses what is already in the repo.
- Do **not** add Tailwind utility classes — the project does not actually use Tailwind even though it is installed.

### CONVENTIONS YOU MUST FOLLOW

1. **Routers are mounted with `prefix=settings.api_prefix` in `main.py`** (which is `/api`). Therefore router prefix in the file is **just the resource path** (`/discover`), NOT `/api/discover`. Following the pattern of every existing router.
2. **Auth dependency** is `from app.deps.auth import get_current_user`. Use this in any endpoint that requires a logged-in user.
3. **Supabase client** is reached via `from app.services import legacy_bridge` and then `legacy_bridge.db_get_user(...)`, `legacy_bridge.db_get_user_by_email(...)`. Do not create a second client.
4. **Frontend store** uses `export default`. Import as `import useCvWorkspaceStore from '../store/useCvWorkspaceStore'` (default import).
5. **The store setter for analysis requirement text is `setAnalysisRequirementText`** — not `setRequirementText`. Verify in `useCvWorkspaceStore.js` before writing the click handler.
6. **API client** — use `postJson` from `../api/client`, which already handles credentials and error normalisation.

---

## 1. WHAT YOU ARE BUILDING

A new feature called **Discovery** consisting of:

1. **Backend endpoint** `POST /api/discover/landscape` that takes a free-text query, calls GPT-4o-mini, validates the JSON shape, caches in SQLite, returns a structured "career landscape" (related subfields, adjacent fields, known programs from a strict allowlist, and search tags).
2. **Backend endpoint** `POST /api/auth/me/onboard` that sets `onboarded_at` on the current user.
3. **Frontend page** `/discover` that renders the landscape as cards, with a "Regenerate" button and clickable opportunity cards that send the user into `/analysis` with the context pre-filled.
4. **Routing change** so a user whose `onboarded_at` is `NULL` is redirected to `/discover` after login. Once they've completed their first analysis (or visited `/analysis` once) we mark them onboarded.
5. **Sidebar nav item** "Discover".
6. **Supabase migration** to add `onboarded_at TIMESTAMPTZ` to `anchor_users`.

Out of scope for this PR (do not build):
- Chrome extension generic page capture (deferred — needs CORS work)
- Redis cache (deferred — SQLite is fine for v1)
- Discovery query analytics dashboard (deferred — log only)

---

## 2. PHASE 1 — Database migration (do this FIRST)

**Why first:** the rest of the plan reads `user.onboarded_at`. If the column doesn't exist, every login response breaks.

### Action

Open the Supabase project at https://app.supabase.com → SQL Editor → New query, and run:

```sql
ALTER TABLE public.anchor_users
  ADD COLUMN IF NOT EXISTS onboarded_at TIMESTAMPTZ;

COMMENT ON COLUMN public.anchor_users.onboarded_at IS
  'Timestamp when the user completed their first meaningful action. NULL = not yet onboarded.';
```

### Acceptance

```sql
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'anchor_users' AND column_name = 'onboarded_at';
```

Should return one row with `data_type = 'timestamp with time zone'`.

---

## 3. PHASE 2 — Backend Discovery endpoint

### File: CREATE `anchorcv-backend/app/routers/discovery.py`

Use this exact code:

```python
import hashlib
import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from openai import OpenAI
from pydantic import BaseModel, Field

from app.deps.auth import get_current_user

router = APIRouter(prefix="/discover", tags=["discovery"])
logger = logging.getLogger(__name__)

CACHE_TTL_HOURS = 24
DAILY_LIMIT_FREE = 20
DAILY_LIMIT_PREMIUM = 500  # very high, effectively unlimited

# Strict allowlist of internationally recognised funding programs.
# The model is instructed to only suggest opportunities tied to one of these.
PROGRAM_ALLOWLIST = [
    "DAAD", "Commonwealth Scholarship", "Chevening", "Fulbright",
    "Erasmus Mundus", "Marie Skłodowska-Curie Actions", "EPSRC", "NSERC",
    "JSPS", "KAUST", "Aga Khan Foundation", "OFID",
]

# SQLite cache lives next to the backend code (same directory as main.py).
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


# --------------------------------------------------------------------------
# Pydantic models — nested so FastAPI/Pydantic actually validates the shape.
# --------------------------------------------------------------------------

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
    type: str  # "PhD" | "Masters" | "Scholarship" | "Job"
    note: str


class LandscapeResponse(BaseModel):
    primary_field: str
    related_subfields: List[Subfield]
    adjacent_fields: List[AdjacentField]
    known_opportunities: List[KnownOpportunity]
    search_tags: List[str]
    summary: str
    cached: bool = False


class LandscapeRequest(BaseModel):
    query: str
    bypass_cache: bool = False


# --------------------------------------------------------------------------
# Cache + rate-limit helpers
# --------------------------------------------------------------------------

def _hash_query(query: str) -> str:
    return hashlib.sha256(query.strip().lower().encode("utf-8")).hexdigest()


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


def _delete_cache(query_hash: str) -> None:
    with sqlite3.connect(_DB_PATH) as conn:
        conn.execute("DELETE FROM landscape_cache WHERE query_hash = ?", (query_hash,))


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


# --------------------------------------------------------------------------
# Endpoint
# --------------------------------------------------------------------------

@router.post("/landscape", response_model=LandscapeResponse)
def generate_landscape(
    payload: LandscapeRequest,
    user: dict = Depends(get_current_user),
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

    query_hash = _hash_query(query)
    _log_query(user_id, query_hash)

    if not payload.bypass_cache:
        cached = _get_cached(query_hash)
        if cached:
            cached["cached"] = True
            return LandscapeResponse.model_validate(cached)

    allowlist_str = ", ".join(PROGRAM_ALLOWLIST)
    system_prompt = (
        "You are a career discovery engine for international students. "
        "Generate a structured career landscape based on the student's free-text query. "
        "Be specific, honest, and helpful. NEVER invent program names. "
        f"Only suggest opportunities tied to one of these well-known programs if they truly match the student's field: {allowlist_str}. "
        "If none of those clearly match, return an empty `known_opportunities` list and rely on `search_tags` instead. "
        "Better a missing card than a fabricated scholarship."
    )

    user_prompt = (
        f'A student describes their background and goals:\n\n"{query}"\n\n'
        "Return ONLY valid JSON with this exact schema:\n"
        "{\n"
        '  "primary_field": "string",\n'
        '  "related_subfields": [\n'
        '    { "name": "string", "description": "one sentence", "growing": true,\n'
        '      "hot_regions": ["string"], "typical_roles": ["string"],\n'
        '      "distance_from_user": "close | 4-8 weeks | 3-6 months | career shift",\n'
        '      "why": "why this matches the student" }\n'
        "  ],\n"
        '  "adjacent_fields": [\n'
        '    { "name": "string", "description": "one sentence", "growing": true,\n'
        '      "distance_from_user": "4-8 weeks | 3-6 months | career shift",\n'
        '      "why": "why this is adjacent" }\n'
        "  ],\n"
        '  "known_opportunities": [\n'
        '    { "title": "e.g., DAAD Research Grant for PhD candidates",\n'
        '      "institution": "string", "country": "string",\n'
        '      "type": "PhD | Masters | Scholarship | Job",\n'
        '      "note": "Always end with: Verify on official site." }\n'
        "  ],\n"
        '  "search_tags": ["10-15 specific Google-ready search queries"],\n'
        '  "summary": "3-4 sentences of honest, helpful guidance"\n'
        "}\n\n"
        "Rules:\n"
        "- related_subfields: 4-6 entries\n"
        "- adjacent_fields: 2-3 entries\n"
        "- known_opportunities: only programs from the allowlist; if nothing fits, return []\n"
        "- search_tags: 10-15 practical queries\n"
        "- Be honest about distance. Don't claim a student is 'close' to a field they lack skills for.\n"
        "- No fabrications. If uncertain, omit."
    )

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))

    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            response_format={"type": "json_object"},
            max_tokens=2000,
        )
    except Exception as exc:
        logger.exception("OpenAI call failed for discovery query: %s", exc)
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

    try:
        validated = LandscapeResponse.model_validate({**raw, "cached": False})
    except Exception as exc:
        logger.warning("Discovery shape validation failed. raw=%s err=%s", raw, exc)
        raise HTTPException(
            status_code=502,
            detail="The discovery engine returned an unexpected shape. Please try again.",
        ) from exc

    payload_dict = validated.model_dump()
    _set_cache(query_hash, payload_dict)
    return validated
```

### File: EDIT `anchorcv-backend/app/main.py`

Add `discovery` to the import line at the top and one `app.include_router(...)` at the bottom. Final file should look like this:

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import (
    analysis, auth, builder, export, files, matching,
    payments, extension, webhook, discovery,
)

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(analysis.router, prefix=settings.api_prefix)
app.include_router(matching.router, prefix=settings.api_prefix)
app.include_router(builder.router, prefix=settings.api_prefix)
app.include_router(export.router, prefix=settings.api_prefix)
app.include_router(files.router, prefix=settings.api_prefix)
app.include_router(payments.router, prefix=settings.api_prefix)
app.include_router(extension.router, prefix=settings.api_prefix)
app.include_router(webhook.router, prefix=settings.api_prefix)
app.include_router(discovery.router, prefix=settings.api_prefix)
```

### Acceptance for Phase 2

After restart, run from the server:

```bash
# Should be 401 (no session cookie)
curl -X POST http://localhost:8000/api/discover/landscape \
  -H "Content-Type: application/json" \
  -d '{"query":"electrical engineering, power systems, PhD in Germany"}'

# With a real session cookie (replace SESSION):
curl -X POST http://localhost:8000/api/discover/landscape \
  -H "Content-Type: application/json" \
  -b "anchorcv_session=SESSION" \
  -d '{"query":"electrical engineering, power systems, PhD in Germany"}'
# → 200 with JSON containing primary_field, related_subfields, summary, etc.

# Same query within 24h → "cached": true
# 21st call within 24h on a free account → 429
```

---

## 4. PHASE 3 — Backend onboarding endpoint

### File: EDIT `anchorcv-backend/app/routers/auth.py`

Add a new endpoint at the bottom of the file. The full new auth.py should look like this:

```python
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.config import settings
from app.deps.auth import get_current_user
from app.schemas.auth import LoginRequest, RegisterRequest
from app.services import legacy_bridge
from anchor_shared import create_session_token

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookie(response: Response, user_id: str) -> None:
    token = create_session_token(user_id, settings.session_secret, settings.session_max_age)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        max_age=settings.session_max_age,
        path="/",
    )


@router.post("/register")
def register(payload: RegisterRequest, response: Response):
    ok, result = legacy_bridge.db_register_user(
        payload.first_name, payload.last_name, payload.email, payload.country, payload.password,
    )
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result)
    user = legacy_bridge.db_get_user(result)
    sanitized = legacy_bridge.sanitize_user(user)
    _set_session_cookie(response, result)
    return {"user": sanitized}


@router.post("/login")
def login(payload: LoginRequest, response: Response):
    ok, result = legacy_bridge.db_login_user(payload.email, payload.password)
    if not ok:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=result["error"])
    sanitized = legacy_bridge.sanitize_user(result)
    _set_session_cookie(response, result["id"])
    return {"user": sanitized}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(key=settings.session_cookie_name, path="/")
    return {"ok": True}


@router.get("/me")
def me(user=Depends(get_current_user)):
    return {"user": user}


@router.post("/me/onboard")
def mark_onboarded(user=Depends(get_current_user)):
    """Mark the current user as having completed onboarding.
    Idempotent — calling repeatedly does not move the timestamp forward."""
    if user.get("onboarded_at"):
        return {"user": user, "already_onboarded": True}

    sb = legacy_bridge._get_supabase() if hasattr(legacy_bridge, "_get_supabase") else None
    # Fallback path: anchor_shared exposes the supabase client through its helpers.
    # We update via a direct SQL-like call.
    from anchor_shared import _get_supabase  # type: ignore
    sb = _get_supabase()
    if not sb:
        raise HTTPException(status_code=500, detail="Database is not connected.")

    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        sb.table("anchor_users").update({"onboarded_at": now_iso}).eq("id", user["id"]).execute()
    except Exception as exc:
        # If the column does not exist, surface a clear error instead of silently ignoring.
        raise HTTPException(status_code=500, detail=f"Failed to mark onboarded: {exc}") from exc

    refreshed = legacy_bridge.db_get_user(user["id"])
    return {"user": legacy_bridge.sanitize_user(refreshed), "already_onboarded": False}
```

### Note on `sanitize_user`

`sanitize_user` already returns the full user row minus `password_hash`. After Phase 1 the row contains `onboarded_at`, so it will be in the `/auth/me` response automatically. Verify by running:

```bash
curl -b "anchorcv_session=SESSION" http://localhost:8000/api/auth/me | jq
# → user object should have an "onboarded_at" key (initially null)
```

### Acceptance for Phase 3

```bash
curl -X POST -b "anchorcv_session=SESSION" http://localhost:8000/api/auth/me/onboard
# → 200, user.onboarded_at is now an ISO timestamp
# Calling it twice → already_onboarded: true, timestamp unchanged
```

---

## 5. PHASE 4 — Frontend Discovery page

### File: CREATE `anchorcv-frontend/src/pages/DiscoveryPage.jsx`

```jsx
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { postJson } from "../api/client";
import useCvWorkspaceStore from "../store/useCvWorkspaceStore";

const EXAMPLE_QUERIES = [
  "Electrical engineering, power systems, PhD in Germany",
  "Computer science Master's, AI/ML, fully funded scholarship",
  "Public health, epidemiology, post-doc in UK or Canada",
  "Renewable energy, policy research, Erasmus Mundus",
];

export default function DiscoveryPage() {
  const navigate = useNavigate();
  const setAnalysisRequirementText = useCvWorkspaceStore(
    (s) => s.setAnalysisRequirementText
  );

  const [query, setQuery] = useState("");
  const [landscape, setLandscape] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleExplore(bypassCache = false) {
    const trimmed = query.trim();
    if (!trimmed) return;
    setLoading(true);
    setError("");
    try {
      const data = await postJson("/discover/landscape", {
        query: trimmed,
        bypass_cache: bypassCache,
      });
      setLandscape(data);
    } catch (err) {
      const msg = err?.detail || err?.message || "Something went wrong.";
      setError(typeof msg === "string" ? msg : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  function handleAnalyzeOpportunity(opp) {
    const reqText = [
      opp.title,
      `${opp.institution}, ${opp.country}`,
      `Type: ${opp.type}`,
      opp.note,
    ]
      .filter(Boolean)
      .join("\n");
    setAnalysisRequirementText(reqText);
    navigate("/analysis");
  }

  function handleUseSearchTag(tag) {
    window.open(
      `https://www.google.com/search?q=${encodeURIComponent(tag)}`,
      "_blank",
      "noopener,noreferrer"
    );
  }

  function handleCopyAllTags() {
    if (landscape?.search_tags?.length) {
      navigator.clipboard.writeText(landscape.search_tags.join("\n"));
    }
  }

  return (
    <section className="stack">
      <div className="hero-panel">
        <p className="eyebrow">Discover</p>
        <h2 className="page-title">What are you looking for?</h2>
        <p className="muted-copy">
          Describe your background, interests, and goals. We&rsquo;ll map out the
          opportunities and the path to each.
        </p>

        <div
          className="button-row"
          style={{ marginTop: "1rem", flexWrap: "nowrap" }}
        >
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleExplore(false)}
            placeholder="e.g., Electrical engineering, power systems, PhD in Germany"
            style={{ flex: 1 }}
          />
          <button
            className="primary-button"
            onClick={() => handleExplore(false)}
            disabled={loading || !query.trim()}
            style={{ whiteSpace: "nowrap" }}
          >
            {loading ? "Exploring..." : "Explore"}
          </button>
        </div>

        {!landscape && !loading && (
          <div style={{ marginTop: "1rem" }}>
            <p className="muted-copy" style={{ fontSize: "0.85rem", marginBottom: "0.5rem" }}>
              Try one of these:
            </p>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
              {EXAMPLE_QUERIES.map((eq) => (
                <button
                  key={eq}
                  onClick={() => setQuery(eq)}
                  className="secondary-button"
                  style={{ padding: "0.4rem 0.9rem", fontSize: "0.8rem" }}
                >
                  {eq}
                </button>
              ))}
            </div>
          </div>
        )}

        {error && <p className="error-text" style={{ marginTop: "1rem" }}>{error}</p>}
      </div>

      {landscape && (
        <>
          <div className="panel">
            <p style={{ fontSize: "1.05rem", lineHeight: 1.6, margin: 0 }}>
              {landscape.summary}
            </p>
            <div className="button-row" style={{ marginTop: "1rem", flexWrap: "wrap" }}>
              <button
                className="secondary-button compact-button"
                onClick={() => handleExplore(true)}
                disabled={loading}
              >
                {loading ? "Regenerating..." : "Regenerate"}
              </button>
              {landscape.cached && (
                <span className="muted-copy" style={{ fontSize: "0.8rem" }}>
                  Loaded from cache
                </span>
              )}
            </div>
          </div>

          <h3 style={{ margin: "0.5rem 0" }}>Close matches</h3>
          <div className="grid two-up">
            {landscape.related_subfields?.map((field, i) => (
              <div key={i} className="panel stack tight">
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "flex-start",
                    gap: "0.5rem",
                  }}
                >
                  <strong style={{ fontSize: "1.05rem" }}>{field.name}</strong>
                  <span
                    style={{
                      fontSize: "0.72rem",
                      padding: "2px 10px",
                      borderRadius: "999px",
                      background: field.growing
                        ? "rgba(34,197,94,0.15)"
                        : "rgba(148,163,184,0.15)",
                      color: field.growing ? "#bbf7d0" : "#cbd5e1",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {field.growing ? "Growing" : "Stable"}
                  </span>
                </div>
                <p className="muted-copy" style={{ margin: 0, fontSize: "0.9rem" }}>
                  {field.description}
                </p>
                <p style={{ margin: 0, fontSize: "0.85rem" }}>
                  <strong>Distance:</strong> {field.distance_from_user}
                </p>
                <p className="muted-copy" style={{ margin: 0, fontSize: "0.85rem" }}>
                  {field.why}
                </p>
                {field.hot_regions?.length > 0 && (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: "0.3rem" }}>
                    {field.hot_regions.map((r) => (
                      <span
                        key={r}
                        style={{
                          fontSize: "0.7rem",
                          padding: "1px 8px",
                          borderRadius: "999px",
                          background: "rgba(99,102,241,0.16)",
                          color: "#c7d2fe",
                        }}
                      >
                        {r}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>

          {landscape.adjacent_fields?.length > 0 && (
            <>
              <h3 style={{ margin: "1rem 0 0.5rem" }}>Nearby (some upskilling)</h3>
              <div className="grid two-up">
                {landscape.adjacent_fields.map((field, i) => (
                  <div key={i} className="panel stack tight" style={{ opacity: 0.9 }}>
                    <strong>{field.name}</strong>
                    <p className="muted-copy" style={{ margin: 0, fontSize: "0.9rem" }}>
                      {field.description}
                    </p>
                    <p style={{ margin: 0, fontSize: "0.85rem" }}>
                      <strong>Distance:</strong> {field.distance_from_user}
                    </p>
                    <p className="muted-copy" style={{ margin: 0, fontSize: "0.85rem" }}>
                      {field.why}
                    </p>
                  </div>
                ))}
              </div>
            </>
          )}

          {landscape.known_opportunities?.length > 0 && (
            <>
              <h3 style={{ margin: "1rem 0 0.5rem" }}>Known programs</h3>
              <p className="muted-copy" style={{ margin: 0, fontSize: "0.85rem" }}>
                Curated international funding sources. Always verify the latest call on
                the official site.
              </p>
              <div className="grid two-up">
                {landscape.known_opportunities.map((opp, i) => (
                  <div key={i} className="panel stack tight">
                    <strong>{opp.title}</strong>
                    <p className="muted-copy" style={{ margin: 0, fontSize: "0.9rem" }}>
                      {opp.institution}, {opp.country} &mdash; {opp.type}
                    </p>
                    <p className="muted-copy" style={{ margin: 0, fontSize: "0.8rem" }}>
                      {opp.note}
                    </p>
                    <button
                      className="primary-button compact-button"
                      onClick={() => handleAnalyzeOpportunity(opp)}
                    >
                      Analyse my CV
                    </button>
                  </div>
                ))}
              </div>
            </>
          )}

          <div className="panel stack tight">
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <strong>Search tags</strong>
              <button
                className="secondary-button compact-button"
                onClick={handleCopyAllTags}
              >
                Copy all
              </button>
            </div>
            <p className="muted-copy" style={{ margin: 0, fontSize: "0.85rem" }}>
              Use these on Google, EURAXESS, or directly on university sites.
            </p>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
              {landscape.search_tags?.map((tag, i) => (
                <button
                  key={i}
                  onClick={() => handleUseSearchTag(tag)}
                  style={{
                    padding: "0.4rem 1rem",
                    borderRadius: "999px",
                    border: "1px solid var(--border)",
                    background: "rgba(99,102,241,0.1)",
                    color: "var(--text)",
                    cursor: "pointer",
                    fontSize: "0.85rem",
                  }}
                >
                  {tag}
                </button>
              ))}
            </div>
          </div>
        </>
      )}
    </section>
  );
}
```

### Note on the API path

`postJson("/discover/landscape", ...)` — `postJson` already prepends the base URL (which itself includes `/api`). So the full URL is `/api/discover/landscape`. Do NOT pass `/api/discover/landscape` as the path — that would double the prefix.

### Acceptance for Phase 5 (frontend)

- Visit `/discover` while logged in
- Type a query, press Enter or click Explore → loading state, then cards
- Click a "Known program" → arrives on `/analysis` with the textarea pre-filled
- Click a search tag → opens Google in a new tab
- Click Regenerate → fresh request, `cached: false` in the response

---

## 6. PHASE 5 — Routing, sidebar, and onboarding redirect

### File: EDIT `anchorcv-frontend/src/App.jsx`

Add the discovery route inside the protected/Layout group:

```jsx
import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import ProtectedRoute from "./components/ProtectedRoute";
import AccountPage from "./pages/AccountPage";
import AnalysisPage from "./pages/AnalysisPage";
import BuilderPage from "./pages/BuilderPage";
import DashboardPage from "./pages/DashboardPage";
import DiscoveryPage from "./pages/DiscoveryPage";
import FilesPage from "./pages/FilesPage";
import LoginPage from "./pages/LoginPage";
import PaymentPage from "./pages/PaymentPage";
import PaymentSuccessPage from "./pages/PaymentSuccessPage";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<ProtectedRoute requirePremium={false} />}>
        <Route path="/payment" element={<PaymentPage />} />
        <Route path="/payment-success" element={<PaymentSuccessPage />} />
      </Route>
      <Route path="/" element={<ProtectedRoute />}>
        <Route element={<Layout />}>
          <Route index element={<DashboardPage />} />
          <Route path="discover" element={<DiscoveryPage />} />
          <Route path="analysis" element={<AnalysisPage />} />
          <Route path="builder" element={<BuilderPage />} />
          <Route path="files" element={<FilesPage />} />
          <Route path="account" element={<AccountPage />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
```

### File: EDIT `anchorcv-frontend/src/components/Layout.jsx`

Add Discover to `navItems`. Put it second (between Dashboard and Analysis) since it is the new front door:

```js
const navItems = [
  { to: "/", label: "Dashboard" },
  { to: "/discover", label: "Discover" },
  { to: "/analysis", label: "Analysis" },
  { to: "/builder", label: "Builder" },
  { to: "/files", label: "Files" },
  { to: "/account", label: "Account" }
];
```

### File: EDIT `anchorcv-frontend/src/components/ProtectedRoute.jsx`

Add the onboarding redirect. Final file:

```jsx
import { useEffect } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";
import useAuthStore from "../store/useAuthStore";
import { hasActivePremium } from "../utils/premium";

const ONBOARDING_TARGET = "/discover";
const ONBOARDING_BYPASS_PATHS = new Set([
  "/discover", "/account", "/payment", "/payment-success"
]);

export default function ProtectedRoute({ requirePremium = true }) {
  const location = useLocation();
  const { status, user, hydrate } = useAuthStore();

  useEffect(() => {
    if (status === "idle") {
      hydrate();
    }
  }, [hydrate, status]);

  if (status === "idle" || status === "loading") {
    return <div className="screen-shell"><div className="panel">Loading AnchorCV...</div></div>;
  }

  if (!user) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  if (requirePremium && !hasActivePremium(user)) {
    return <Navigate to="/payment" replace state={{ from: location }} />;
  }

  // First-time-user onboarding redirect — premium users who have never
  // completed onboarding land on /discover instead of the bare dashboard.
  if (
    requirePremium &&
    hasActivePremium(user) &&
    !user.onboarded_at &&
    !ONBOARDING_BYPASS_PATHS.has(location.pathname)
  ) {
    return <Navigate to={ONBOARDING_TARGET} replace state={{ from: location }} />;
  }

  return <Outlet />;
}
```

### File: EDIT `anchorcv-frontend/src/pages/AnalysisPage.jsx` (small change)

After a successful first analysis, mark the user as onboarded so they stop being redirected to `/discover`. Find the `mutation` `useMutation` block (around line 517) and update its `onSuccess` to also call the onboard endpoint:

Add this import at the top with the other api imports:

```jsx
import { postJson } from "../api/client";
```

(it is likely already imported — check first)

Then in `mutation`'s `onSuccess`, after `setCvRequirementPrefill(...)`, append:

```jsx
// One-shot mark-onboarded — fire and forget; backend is idempotent.
if (!useAuthStore.getState().user?.onboarded_at) {
  postJson("/auth/me/onboard", {})
    .then(() => useAuthStore.getState().hydrate())
    .catch(() => { /* ignore */ });
}
```

You'll need `useAuthStore` imported at the top of AnalysisPage.jsx (it already is — confirm).

### Acceptance for Phase 5

- Brand new user signs up + pays → after `/payment-success` countdown lands on `/discover` (not `/`).
- Existing user with `onboarded_at` set → lands on `/`.
- New user can still navigate to `/account` without being trapped in the redirect loop.
- After running their first analysis, refresh — they are now sent to `/` on next login, not `/discover`.
- Discover appears in sidebar.

---

## 7. END-TO-END TEST SCRIPT

Run all of these in order on a staging environment before declaring done.

1. **Migration applied?** `\d+ public.anchor_users` in psql shows `onboarded_at`.
2. **Backend up?** `curl http://localhost:8000/health` → `{"status":"ok"}`
3. **Discovery requires auth?** `curl -X POST http://localhost:8000/api/discover/landscape -d '{"query":"x"}' -H 'Content-Type: application/json'` → 401
4. **Discovery works for an authed user?** With a real session cookie and a valid query → 200 with full landscape JSON.
5. **Cache works?** Run the same query twice → second response has `"cached": true`.
6. **Bypass cache works?** Pass `"bypass_cache": true` → fresh call, `"cached": false`.
7. **Pydantic shape rejects bad GPT?** Manually call OpenAI with a bad prompt to force malformed JSON — backend returns 502 with a clear message, never 200 with garbage.
8. **Rate limit works?** Make 21 calls in a day on a free account → 21st returns 429.
9. **Onboard endpoint?** `POST /api/auth/me/onboard` → user row's `onboarded_at` is now non-null. Calling again → `already_onboarded: true`.
10. **Frontend page renders?** Visit `/discover`, type a query, click Explore. See cards. No console errors.
11. **Analysis hand-off?** Click "Analyse my CV" on a known opportunity → arrive on `/analysis` with the JD textarea pre-filled.
12. **Onboarding redirect?** Create a new account, pay, go through `/payment-success` → land on `/discover`. After running first analysis, log out and back in → land on `/`.

---

## 8. DEPLOY (after all tests green)

From your dev box:

```powershell
# Sync code
scp "C:\Users\SiliCon\Downloads\ANCHOR CV\anchorcv-backend\app\routers\discovery.py" `
  root@178.104.48.216:/root/ANCHOR\ CV/anchorcv-backend/app/routers/discovery.py
scp "C:\Users\SiliCon\Downloads\ANCHOR CV\anchorcv-backend\app\routers\auth.py" `
  root@178.104.48.216:/root/ANCHOR\ CV/anchorcv-backend/app/routers/auth.py
scp "C:\Users\SiliCon\Downloads\ANCHOR CV\anchorcv-backend\app\main.py" `
  root@178.104.48.216:/root/ANCHOR\ CV/anchorcv-backend/app/main.py
scp -r "C:\Users\SiliCon\Downloads\ANCHOR CV\anchorcv-frontend\src\pages\DiscoveryPage.jsx" `
  root@178.104.48.216:/root/ANCHOR\ CV/anchorcv-frontend/src/pages/DiscoveryPage.jsx
scp "C:\Users\SiliCon\Downloads\ANCHOR CV\anchorcv-frontend\src\App.jsx" `
  root@178.104.48.216:/root/ANCHOR\ CV/anchorcv-frontend/src/App.jsx
scp "C:\Users\SiliCon\Downloads\ANCHOR CV\anchorcv-frontend\src\components\Layout.jsx" `
  root@178.104.48.216:/root/ANCHOR\ CV/anchorcv-frontend/src/components/Layout.jsx
scp "C:\Users\SiliCon\Downloads\ANCHOR CV\anchorcv-frontend\src\components\ProtectedRoute.jsx" `
  root@178.104.48.216:/root/ANCHOR\ CV/anchorcv-frontend/src/components/ProtectedRoute.jsx
scp "C:\Users\SiliCon\Downloads\ANCHOR CV\anchorcv-frontend\src\pages\AnalysisPage.jsx" `
  root@178.104.48.216:/root/ANCHOR\ CV/anchorcv-frontend/src/pages/AnalysisPage.jsx
```

On the server:

```bash
ssh root@178.104.48.216
cd /root/ANCHOR\ CV/anchorcv-frontend && npm run build
systemctl restart anchorcv
journalctl -u anchorcv -f -n 100
```

Then in another terminal, hit a discovery request and watch the log line confirm the call.

---

## 9. KNOWN GOTCHAS / DEFERRED WORK

### Single worker requirement (read this!)

The SQLite cache file lives on the local filesystem. If `anchorcv` is run with multiple Uvicorn/Gunicorn workers on the same host, they all share the same file (SQLite handles concurrent writes via locking) — so this is fine on one host. If you ever scale to multiple hosts (load balancer in front of two boxes), each box has its own cache and rate-limit counters, which means a user can effectively double their daily quota. Migrate to Redis at that point.

### OpenAI spend cap

Not in this PR. Estimated worst case: 1,000 active free users × 20 calls/day × $0.0012/call = $24/day = $720/month. Add a global daily cap in a follow-up by tracking `daily_calls` aggregated across users.

### Chrome extension generic page capture

Deferred. Needs CORS work on the backend (`chrome-extension://...` origin), and the manifest needs `host_permissions` for `app.anchorcv.com`. Build as a separate PR.

### Query analytics dashboard

Queries are logged to `query_log` in SQLite. There is no UI for viewing them yet. Run `sqlite3 discovery_cache.db "SELECT query_hash, COUNT(*) FROM query_log GROUP BY query_hash ORDER BY 2 DESC LIMIT 20;"` to see most popular queries (hashed, so not the original text). If you want unhashed analytics, log the original query alongside the hash — but that becomes PII.

### Content moderation

Not implemented. A user could type a query like "how to get a fake CV" and the model might respond. Consider adding a simple OpenAI moderation call before `generate_landscape` if this becomes a problem.

### Cache TTL of 24h is per-query

Two users typing the exact same query (modulo whitespace and case) hit the same cache. That's correct for v1 since the response is not personalised. If you ever want per-user customization, the cache key should hash `(query + user.country + user.experience_level)`.

---

## 10. ROLLBACK PLAN

If anything goes wrong in production:

1. **Revert the routers** — restore the previous `auth.py` and `main.py`, delete `discovery.py`. Restart anchorcv.
2. **Revert the frontend** — restore `App.jsx`, `Layout.jsx`, `ProtectedRoute.jsx`, `AnalysisPage.jsx`. Delete `DiscoveryPage.jsx`. Rebuild `npm run build`.
3. **The migration is safe to leave** — `onboarded_at` is nullable and unused by the legacy code. No need to drop the column.
4. **The SQLite file is safe to delete** — `rm /root/ANCHOR CV/anchorcv-backend/app/discovery_cache.db` clears all caches and rate counters.

---

## 11. CHECKLIST FOR THE AGENT

Tick each box only when complete and tested:

- [ ] Phase 1: `onboarded_at` column added to `anchor_users`
- [ ] Phase 2: `discovery.py` created, `main.py` updated, backend restarts cleanly
- [ ] Phase 2: 401/200/cached/429 acceptance tests all pass
- [ ] Phase 3: `auth.py` updated with `/me/onboard` endpoint
- [ ] Phase 3: GET /auth/me returns `onboarded_at` field (initially null)
- [ ] Phase 4: `DiscoveryPage.jsx` created
- [ ] Phase 4: page renders, Explore button works, cards render
- [ ] Phase 5: route added in `App.jsx`
- [ ] Phase 5: Discover added to sidebar `Layout.jsx`
- [ ] Phase 5: ProtectedRoute redirect logic in place
- [ ] Phase 5: AnalysisPage `onSuccess` calls `/auth/me/onboard`
- [ ] End-to-end: new account + pay + auto-redirect to /discover works
- [ ] End-to-end: existing account lands on dashboard, not /discover
- [ ] Deploy: files synced, frontend rebuilt, service restarted
- [ ] Deploy: smoke test passes against production URL
