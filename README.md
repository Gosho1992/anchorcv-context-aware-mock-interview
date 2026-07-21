# AnchorCV — Context-Aware Mock Interview

AnchorCV is a career intelligence platform that helps candidates improve resumes, match jobs, and practice interviews with grounded, evidence-aware feedback.

This Build Week submission focuses on **Context-Aware Mock Interview**: a guided workflow that uses both resume context and job-description context to run a personalized interview, evaluate evidence quality, and generate actionable interview-readiness reporting.

---

## Problem
Generic mock interview tools usually ask broad questions and score answers in isolation. That misses the real interview challenge:

- Can the candidate defend specific claims on their resume?
- Can they connect those claims to the selected role’s requirements?
- Can they improve weak evidence areas before a real interview?

---

## Solution
AnchorCV’s Context-Aware Mock Interview combines:

1. **Resume context** (claims, projects, quantified outcomes)
2. **Job context** (role responsibilities and requirements)
3. **Interview responses** (initial + clarification answers)

It then produces:

- Context-aware interview questions
- Adaptive clarification follow-ups when depth is missing
- Evidence-strength evaluation per claim
- Interview Evidence Matrix (strong/moderate/weak/unsupported)
- Grounded rewrite suggestions for weak/moderate claims
- Exportable report artifacts compatible with existing AnchorCV export flows

---

## Interview Workflow

```text
Upload Resume
  -> Paste Job Description
  -> Configure Interview (style, difficulty, focus, question count, time limit)
  -> Context-Aware Questioning
  -> Adaptive Clarification (when needed)
  -> Answer Evaluation + Evidence Scoring
  -> Interview Evidence Matrix
  -> Resume Rewrite Suggestions
  -> Exportable Interview Readiness Report
```

---

## Architecture (Current Production-Backed App)

### Frontend
- **React + Vite** (`anchorcv-frontend`)
- Canvas workflow orchestration (`useCanvasStore`, step-based flow)
- Interview UI:
  - `StepInterviewSetup`
  - `StepInterviewSession`
  - `StepInterviewReport`

### Backend
- **FastAPI** (`anchorcv-backend`)
- Router-based API surface (`/api/*`)
- Auth/session middleware and premium-access gating
- Interview orchestration routes:
  - `/api/interview/*`
  - `/api/resume-defense/*` (internal evidence engine reused by interview flow)

### Shared/Legacy Utilities
- `anchor_core.py` and `anchor_shared.py` for reusable text extraction, CV-related helpers, and shared integrations

### Persistence
- Existing Supabase-backed user/files/payment data paths
- Resume-defense/evidence session persistence in backend service layer

---

## OpenAI API Usage (Runtime-Accurate)

The shipped app currently uses OpenAI in these production runtime paths:

- **Default text generation model:** `gpt-4o-mini`
- **Optional text model via picker:** `gpt-4o`
- **Voice transcription model:** `whisper-1`

Interview-related AI calls include:
- Question generation (`/api/interview/generate-questions`)
- Answer evaluation (`/api/interview/evaluate`)
- Coaching (`/api/interview/teach`)
- Final report reasoning (`/api/interview/report`)
- Audio transcription (`/api/interview/transcribe`)

Important: claim-level matrix aggregation and rewrite generation in the evidence engine are implemented with deterministic logic and persisted session data reuse.

---

## Tech Stack

- Frontend: React, Vite, Zustand, React Router
- Backend: FastAPI, Pydantic, Uvicorn
- AI SDKs: OpenAI Python SDK, Anthropic-compatible routing layer
- Data/Auth/Storage: Supabase
- Export: ReportLab, python-docx, Jinja2
- Testing: pytest

---

## Local Development

### 1) Backend
```bash
cd anchorcv-backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

Create backend env file from placeholders:
```bash
# copy root .env.example to anchorcv-backend/.env and fill values
```

Run backend:
```bash
uvicorn app.main:app --reload --port 8000
```

### 2) Frontend
```bash
cd anchorcv-frontend
npm install
npm run dev
```

Set frontend API base (if needed):
```bash
VITE_API_BASE=http://localhost:8000/api
```

---

## Repository Layout

- `anchorcv-frontend/` — React Canvas app
- `anchorcv-backend/` — FastAPI backend
- `docs/build-week/` — Build Week review, implementation plan, and engineering log
- `templates/` — CV/export templates
- `anchor_core.py`, `anchor_shared.py` — shared legacy/runtime utilities

---

## Build Week Engineering Notes

Implementation followed a phased delivery path (foundation -> evaluation -> matrix -> rewrites -> integration), documented in:

- `docs/build-week/00_Project_Review.md`
- `docs/build-week/02_Implementation_Plan.md`
- `docs/build-week/03_BuildWeek_Log.md`

### How OpenAI Codex accelerated development
This entire submission was built using OpenAI Codex, which runs on GPT-5.6. Codex was used to accelerate Build Week execution by:

- speeding up architecture-to-implementation translation
- applying targeted production bug fixes and regression-safe refactors
- generating/adjusting tests during each phase
- maintaining implementation logs and change traceability during iterative review

Codex was used as an engineering assistant; runtime model behavior is determined by the application’s own configured model routing.

---

## Security & Submission Hygiene

This submission copy intentionally excludes:

- `.env` and local secret files
- API keys and service-role credentials
- cache/build artifacts (`node_modules`, `dist`, `.venv`, logs, local DB caches)

See `.gitignore` and `.env.example` for expected local setup.

