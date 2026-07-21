# 00 Project Review — AnchorCV

## 1. Executive Summary
AnchorCV is a production AI career platform built as a **hybrid system**: modern FastAPI + React layers around a large legacy core (`anchor_core.py`) and shared infrastructure helpers (`anchor_shared.py`).

Current architecture:
- Backend: domain routers under `/api` (auth, analysis, matching, builder, export, files, discovery, jobs, interview, templates, ATS, payments, extension, analytics, models, navigate).
- AI: mixed orchestration model (legacy bridge + modern router-level LLM flows).
- Frontend: dual UX stack (new Canvas workflow + legacy pages).
- Data: Supabase (`anchor_users`, `anchor_files`) + Supabase Storage (`user-files`) + local SQLite discovery cache (`discovery_cache.db`).

Project history/context reviewed from existing artifacts:
- `AnchorCV_Canvas_Audit_Report.md` (2026-07-02)
- `Canvas_Test_Report_2026-07-03.md` (2026-07-03)
- `AnchorCV_Discovery_Plan_for_Codex.md`
- `Codex_Kickoff_Prompt.md`

## 2. Existing Features
- Auth/session/reset-password (`/auth/*`) — cookie session + signed tokens; **maturity: high**.
- Premium/trial access model (`access_control.py`) — **maturity: high**.
- Resume analysis outputs (`/analyse`) via `legacy_bridge` — **maturity: high**.
- CV-job matching (`/match`, `/match-score`) — **maturity: high**.
- CV builder (`/build-cv`) with format/tone/language controls — **maturity: high**.
- Export (`/export/pdf`, `/export/docx`, first-resume exports) — **maturity: high**.
- Cloud files (`/files/*`) with quota tracking — **maturity: high**.
- Discovery (`/discover/landscape`, `/discover/extract-resume`) with intent-locked prompts + Serper + cache/rate-limit — **maturity: advanced beta**.
- Jobs (`/jobs/search`, `/jobs/generate-document`, `/jobs/match-score`, `/jobs/extract-from-url`) — **maturity: advanced beta**.
- Interview coach (`/interview/*`) with Whisper + evaluation/teaching/report — **maturity: advanced beta**.
- ATS shield (`/ats/simulate`) with deterministic + LLM scoring — **maturity: advanced beta/high**.
- Template system (`/templates/*`) for World Bank/ADB/Immigration/Legal/Executive formats — **maturity: advanced beta**.
- First-resume flow (`/first-resume/*`) with anti-hallucination guardrail — **maturity: beta**.
- AI concierge (`/navigate/`) with deterministic fallback — **maturity: beta**.
- Payments/webhooks (`/payments/*`, `/webhook/lemonsqueezy`) — **maturity: production-capable, fragmented**.
- Canvas workflow engine + step analytics — **maturity: high**.
- Chrome extension + backend integration (`/extension/*`) — **maturity: beta**.

## 3. Architecture Review
### Backend architecture
- Clean router-per-domain API surface in `anchorcv-backend/app/routers`.
- Hybrid orchestration: legacy bridge routes and modern direct routes coexist.
- Large coupling hotspot: `anchorcv-backend/app/services/legacy_bridge.py`.

### Frontend architecture
- React Router + Zustand stores (`useAuthStore`, `useCanvasStore`, `useCvWorkspaceStore`).
- Canvas is the primary guided system, but legacy pages remain active.
- `ProtectedRoute` enforces auth only; `requirePremium` prop is currently not applied.

### Database architecture
- Supabase core tables: `anchor_users`, `anchor_files`.
- Supabase storage bucket: `user-files`.
- Local SQLite for discovery cache/quota/log (`landscape_cache`, `daily_calls`, `query_log`).

### Authentication
- Signed cookie session token; auth dependency injection in FastAPI; frontend hydrate-on-load.

### AI integration
- Multi-provider routed client exists (`app/services/llm.py`), but not uniformly used.
- Some routers call OpenAI/Anthropic directly.

### Canvas workflow
- Frozen step sequencing per flow avoids index-shift bugs.
- Event telemetry: flow start/completion, step completion/abandon, errors.

### Interview workflow
- Structured 5-stage loop (question -> transcribe -> evaluate -> teach -> report).

### Premium workflow
- Access computed from registration date, trial window, and `premium_expires_at`.
- Duplicate webhook/payment paths increase risk of behavioral drift.

### Export workflow
- Centralized export reused across analysis, canvas, jobs/templates outputs, and first-resume.

## 4. Code Quality Review
### Strengths
- Strong domain separation in routers.
- Practical validation/error handling patterns.
- Good reusable frontend building blocks.
- Existing audit/testing artifacts show disciplined iteration.

### Weaknesses
- Very large files increase regression risk:
  - `anchor_core.py` (~4878 lines)
  - `legacy_bridge.py` (~1633 lines)
  - `AnalysisPage.jsx` (~816 lines)
  - `BuilderPage.jsx` (~594 lines)
  - `discovery.py` (~810 lines)
  - `jobs.py` (~649 lines)

### Technical debt
- Dual UI paradigms (canvas + legacy pages).
- Mixed AI invocation architecture.
- Overlapping payment webhook implementations.

### Duplicate logic
- Premium gating/entitlement logic appears in several places.
- Similar JSON parse/retry/error patterns repeated in multiple routers.

### Potential refactoring
- Split `legacy_bridge` by domain.
- Standardize AI invocation/parsing helpers.
- Reduce oversized page components via hooks/subcomponents.

### Performance concerns
- Request-path heavy operations (LLM + parsing) can increase latency.
- Discovery SQLite cache/quota is single-instance oriented.

## 5. Reusable Components
High-priority reuse targets for Build Week:
- `app/deps/auth.py` + `useAuthStore.js` (auth/session pattern)
- `app/services/access_control.py` (trial/premium policy)
- `app/services/llm.py` (model routing)
- `app/services/legacy_bridge.py` helpers (analysis/build/export text handling)
- `anchor_shared.py` storage + payment helpers
- `useCanvasStore.js` + canvas step framework
- `canvasAnalytics.js` + `/analytics/canvas-event`
- `/discover/*` prompt-schema and cache patterns
- `/jobs/extract-from-url` safety pattern
- `/templates/*` format-spec transform/compare pattern

## 6. Database Review
Important tables/storage:
- `anchor_users` (identity, auth hash, premium/trial fields, onboarding, storage quota, extension usage/CV fields)
- `anchor_files` (file metadata keyed to user)
- Supabase storage bucket `user-files` (actual bytes)
- SQLite `landscape_cache`, `daily_calls`, `query_log` (discovery subsystem)

Relationships:
- `anchor_users.id` -> `anchor_files.user_id` (1:N)
- Discovery SQLite rows keyed by user/query hash, not strict FK.

Recommendation for future schema work:
- Prefer extending `anchor_users` / `anchor_files` for user-adjacent Build Week data.
- Create new tables only for clearly separate lifecycle/high-volume entities.
- No schema changes proposed in this phase.

## 7. API Review
Current API organization is coherent by capability and already supports extension through existing routers.

Best Build Week integration points:
- Canvas flow endpoints + step orchestration
- Discovery -> Jobs/Analysis handoff
- Interview evaluation/reporting pipeline
- Template + export path
- Existing analytics endpoint for instrumentation
- `/models` endpoint for model-selection-aware UX

## 8. AI Review
Current GPT usage patterns:
- Legacy bridge pipeline for core analysis/builder/matching flows.
- Direct structured JSON generation in discovery/interview/templates/jobs/navigate.
- Whisper transcription in interview.

Reusable prompt assets:
- Intent-locked discovery system prompts.
- First-resume anti-hallucination guardrail.
- Structured interview evaluation/report schemas.
- Template format-spec scoring prompts.

Prompt architecture improvements:
- Unify model invocation through routed client where feasible.
- Centralize prompt definitions/versioning.
- Share JSON parsing/repair utilities across routers.

## 9. Build Week Opportunities
Natural integration points (without designing a feature yet):
- New canvas step/flow instead of standalone module.
- Extend analysis -> builder continuity.
- Use discovery outputs to prefill downstream workflows.
- Compose match/ATS/interview signals into richer guidance.
- Reuse files + export + analytics for measurable user value.

## 10. Risks
- Architectural: legacy bridge + monolith coupling, dual frontend paradigms.
- Technical: fragmented AI call paths, duplicate payment/webhook logic.
- Performance: synchronous heavy requests, local SQLite scalability limits.
- Maintenance: oversized files, filename-based analytics heuristics.

## 11. Recommendations
Before implementation:
- Keep Build Week work inside existing AnchorCV architecture (especially Canvas + existing API domains).
- Reuse auth/access/export/storage/model-routing infrastructure.
- Avoid creating parallel systems for entitlement, file handling, or AI orchestration.
- Limit changes in high-risk files (`anchor_core.py`, `legacy_bridge.py`) to controlled, scoped edits.
- Add telemetry for every new user-facing step/output from day one.

What should **not** be changed right now:
- Core auth/session model
- Existing premium/trial policy semantics
- Shared export/file-storage primitives
- Existing endpoint contracts unless extension is unavoidable

Architecture review complete. Waiting for approval before implementation work.
