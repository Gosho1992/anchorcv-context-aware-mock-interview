# 02 Implementation Plan — Resume Defense

## 1. Executive Summary
Resume Defense should be implemented as a **new capability layer inside AnchorCV’s existing workflow**, not as a separate interview product. The feature will validate whether users can defend critical resume claims using evidence-aware questioning and claim-level scoring.

### Core engineering decisions
- **Recommendation:** Integrate Resume Defense as a Canvas-first flow that reuses existing analysis, ATS, interview, and reporting infrastructure.
  - **Rationale:** This preserves product continuity, reduces duplicate logic, and keeps adoption high because users stay in one journey.
  - **Trade-off:** Canvas/state complexity increases, and legacy pages need lightweight integration hooks.

- **Recommendation:** Build Resume Defense around a claim-evidence model (claim extraction -> targeted questions -> answer evidence scoring -> defense matrix -> readiness update).
  - **Rationale:** This directly supports the product principle of evidence-based reasoning instead of generic interview scoring.
  - **Trade-off:** Requires stronger structured prompting and more validation than simple Q&A scoring.

- **Recommendation:** Reuse existing backend capabilities (`legacy_bridge`, ATS services, interview transcription/evaluation patterns, routed model client).
  - **Rationale:** Faster delivery, lower operational risk, and architectural consistency.
  - **Trade-off:** Existing large modules remain central dependencies until later refactors.

- **Recommendation:** Persist Resume Defense outcomes in a queryable way and also publish user-readable artifacts through existing file/report paths.
  - **Rationale:** Supports reporting, progress tracking, and future analytics while preserving current “My Files” behavior.
  - **Trade-off:** Adds modest schema complexity.

## 2. User Journey
Target user journey (approved):

Resume Upload -> Resume Analysis -> ATS Analysis -> Job Selection (optional) -> Resume Defense -> Resume Improvement -> Updated Career Readiness Report

### Journey design in AnchorCV
1. **Resume Upload / Existing Resume Context**
   - Use existing resume extraction and canvas CV state.
2. **Resume Analysis + ATS Analysis**
   - Reuse current outputs and scores as defense context.
3. **Job Selection (optional branch)**
   - If JD exists, defense prioritization aligns to job requirements.
   - If no JD, defense runs in “general interview readiness” mode.
4. **Resume Defense Session**
   - Extract important claims.
   - Generate interviewer-style questions tied to claims + job req + ATS weaknesses.
   - Capture typed/voice responses.
   - Evaluate claim evidence strength dynamically.
5. **Resume Improvement**
   - Suggest wording upgrades where answers show stronger evidence than resume wording.
6. **Updated Career Readiness Report**
   - Aggregate existing readiness signals plus defense signals.

### Journey recommendations
- **Recommendation:** Place Resume Defense after ATS and before final improvement/report in Canvas.
  - **Rationale:** Defense quality is strongest when ATS gaps and job context are already known.
  - **Trade-off:** Slightly longer workflow before final report generation.

- **Recommendation:** Keep “optional JD” as a first-class branch, not a degraded error path.
  - **Rationale:** Preserves usability for users preparing generally, not for one specific posting.
  - **Trade-off:** Prompt logic must support two calibrated modes.

- **Recommendation:** Keep the user-facing unit of value as “claim evidence strength,” not “interview score.”
  - **Rationale:** Aligns with product vision and differentiates from existing interview practice tools.
  - **Trade-off:** Requires careful UX language to avoid confusing users who expect a single score.

## 3. Architecture Integration
Resume Defense should be integrated across existing AnchorCV layers, not introduced as an isolated module.

### Reused architecture elements
- Backend:
  - `app/services/legacy_bridge.py` (resume cleaning/extraction compatibility)
  - `app/services/llm.py` (model routing)
  - `app/routers/interview.py` patterns (question/evaluation/report scaffolding, whisper transcription)
  - `app/services/ats_*` outputs as weakness signals
  - `app/services/access_control.py` for gating
- Frontend:
  - Canvas orchestration (`CanvasFlow`, `useCanvasStore`)
  - Existing generation/results/export UX patterns
  - Existing analytics event pipeline (`/analytics/canvas-event`)
- Data:
  - `anchor_users`, `anchor_files`, storage bucket

### Integration recommendations
- **Recommendation:** Add Resume Defense as a new Canvas flow (or subflow) under existing intent/step architecture.
  - **Rationale:** Lowest-friction integration and best consistency with current product direction.
  - **Trade-off:** Requires expanding `FLOW_STEPS` and store payload surfaces.

- **Recommendation:** Keep Interview Coach and Resume Defense as separate user experiences with shared internal services.
  - **Rationale:** Prevents product confusion while maximizing code reuse.
  - **Trade-off:** Requires careful service boundary definition to avoid accidental duplication.

- **Recommendation:** Treat Career Readiness Report as an aggregator over existing + defense outputs rather than a new standalone reporting stack.
  - **Rationale:** Reuses current outputs and avoids conflicting scoring frameworks.
  - **Trade-off:** Aggregation logic must handle missing/partial inputs robustly.

## 4. Backend Architecture
### Proposed backend modules (design-only)
1. **Defense Orchestrator Service**
   - Coordinates end-to-end session lifecycle.
2. **Claim Extraction Service**
   - Extracts and normalizes important resume claims into structured claim objects.
3. **Claim-Job Alignment Service**
   - Maps claims to job requirements and ATS weaknesses.
4. **Defense Question Service**
   - Generates claim-targeted interviewer questions with coverage goals.
5. **Evidence Evaluation Service**
   - Evaluates each answer against claim + JD + ATS context and assigns evidence strength.
6. **Defense Matrix Service**
   - Produces matrix rows: claim, strength, reasoning, recommendation, revised wording suggestion.
7. **Readiness Aggregation Service**
   - Merges defense outcomes into Career Readiness Report.

### Request lifecycle (high level)
- Intake normalized context (resume text required, JD optional, ATS/analysis optional).
- Extract claims and priority scores.
- Generate defense question set.
- Evaluate answers incrementally per claim.
- Build matrix and improvement suggestions.
- Emit updated readiness report payload.

### Backend recommendations
- **Recommendation:** Implement a dedicated defense orchestration layer instead of embedding logic inside current `interview.py` router.
  - **Rationale:** Keeps interview workflow clean and prevents monolithic endpoint growth.
  - **Trade-off:** Adds one new domain router/service path to maintain.

- **Recommendation:** Reuse Whisper transcription path from interview for voice answers.
  - **Rationale:** Proven behavior and no need to duplicate audio processing logic.
  - **Trade-off:** Voice dependency remains coupled to OpenAI key availability.

- **Recommendation:** Use structured response schemas for every AI stage (claims, questions, evidence verdicts, matrix rows).
  - **Rationale:** Predictable frontend behavior and safer parsing.
  - **Trade-off:** Prompt strictness can reduce model creativity, requiring iterative schema tuning.

- **Recommendation:** Keep computationally heavy operations synchronous for Build Week MVP but design services to be task-queue compatible.
  - **Rationale:** Simpler delivery now while preserving path to scale.
  - **Trade-off:** Throughput limits under high concurrent load.

## 5. Frontend Architecture
Resume Defense should be delivered through the existing Canvas UX model.

### Canvas integration plan
- Add Resume Defense as a guided sequence after ATS/job-context steps.
- Keep user context in existing store (`useCanvasStore`) with additional defense state:
  - extracted claims
  - question queue
  - answer records
  - evidence matrix rows
  - wording improvement suggestions
  - readiness summary delta

### UI behavior expectations
- Claim visibility: users see what is being defended.
- Questioning: each question explicitly references claim + context source.
- Evidence result: each answer updates claim evidence strength transparently.
- Matrix output: sortable/scannable rows with recommendation actions.
- Improvement handoff: one-click transfer of wording suggestions to existing resume improvement path.

### Frontend recommendations
- **Recommendation:** Keep Resume Defense in Canvas, with legacy-page entry points that redirect into the Canvas flow.
  - **Rationale:** Prevents duplicate feature surfaces and keeps future maintenance centralized.
  - **Trade-off:** Legacy users may need a short adjustment period to flow-based UX.

- **Recommendation:** Use progressive disclosure (claim -> question -> evidence -> matrix) instead of rendering full matrix up front.
  - **Rationale:** Reduces cognitive overload and increases completion rates.
  - **Trade-off:** More step transitions and store synchronization complexity.

- **Recommendation:** Reuse existing result/export patterns for matrix and readiness report outputs.
  - **Rationale:** Consistent UX and minimal net-new UI patterns.
  - **Trade-off:** Existing export templates may need adaptation for matrix formatting.

- **Recommendation:** Preserve “typed answer fallback” when voice transcription is unavailable.
  - **Rationale:** Maintains accessibility and reliability.
  - **Trade-off:** Mixed input modality can complicate analytics interpretation.

## 6. Database Design
Goal: persist Resume Defense outcomes for continuity, reporting, and future analytics, while reusing existing structures.

### Reuse-first baseline
- Reuse `anchor_users` for user identity/access.
- Reuse `anchor_files` + storage for downloadable matrix/report artifacts.

### Proposed new persistence entities (minimal, production-oriented)
1. **Defense Run (session header)**
   - user_id, resume fingerprint/hash, optional jd fingerprint/hash
   - run status, model metadata, started/completed timestamps
   - aggregate scores (coverage, confidence, readiness delta)
2. **Defense Claim Result (claim-level rows)**
   - run_id, claim text/type/priority
   - evidence strength (enum)
   - reasoning summary
   - recommendation
   - suggested revised wording
   - linked question/answer evidence references

### Data retention policy recommendations
- Store normalized answer evidence summaries, not raw audio blobs, by default.
- If raw transcripts are stored, keep them scoped to user and retention-limited.

### Database recommendations
- **Recommendation:** Use two-table normalized design (run header + claim rows) rather than a single large JSON blob.
  - **Rationale:** Better queryability, easier analytics, clearer evolution path.
  - **Trade-off:** Slightly more schema and API mapping overhead.

- **Recommendation:** Still generate user-facing artifacts into existing `anchor_files`.
  - **Rationale:** Reuses current file UX and avoids introducing a second artifact retrieval pattern.
  - **Trade-off:** Potential duplication (structured rows + artifact file) must be managed intentionally.

- **Recommendation:** Avoid storing sensitive raw answer data unless required for user-facing replay.
  - **Rationale:** Minimizes privacy exposure.
  - **Trade-off:** Less raw data for future model re-evaluation experiments.

## 7. API Design
### API design approach
Introduce a dedicated defense domain router while reusing existing helper endpoints and services.

### Recommended endpoint surface (design-level)
1. **Start Defense Session**
   - Input: resume text/file reference, optional JD text/reference, optional prior ATS/analysis IDs or payloads.
   - Output: session ID, extracted claims, initial question set.
2. **Submit Defense Answer**
   - Input: session ID, claim/question ID, answer text or transcript.
   - Output: updated evidence assessment for that claim and next suggested question.
3. **Complete Defense Session**
   - Input: session ID.
   - Output: full Resume Defense Matrix + wording suggestions + readiness update payload.
4. **Get Defense Session**
   - Input: session ID.
   - Output: persisted matrix and status.
5. **Export Defense Report (optional route or reused export path)**
   - Output: PDF/DOCX via existing export tooling.

### Existing endpoint reuse
- Resume extraction patterns from `/discover/extract-resume`.
- Voice transcription from `/interview/transcribe`.
- ATS signal ingestion from existing ATS result payloads.
- Model picker behavior from `/models`.

### API recommendations
- **Recommendation:** Keep defense endpoints stateful by session ID.
  - **Rationale:** Supports multi-step evaluation, pause/resume, and robust retries.
  - **Trade-off:** Requires backend session persistence and state validation.

- **Recommendation:** Separate “answer evaluation” from “final matrix synthesis.”
  - **Rationale:** Enables incremental UX updates and partial progress saving.
  - **Trade-off:** More endpoint calls and orchestration logic.

- **Recommendation:** Use strict Pydantic schemas and bounded field sizes throughout.
  - **Rationale:** Reduces malformed payload risk and prompt-injection surface.
  - **Trade-off:** Occasional rejection of edge-case but valid long-form inputs unless limits are tuned.

## 8. AI Architecture
Resume Defense AI should use a **multi-stage structured reasoning pipeline**.

### Stage A: Claim extraction
- Extract “defensible claims” from resume into categories:
  - quantified impact claims
  - skill/proficiency claims
  - responsibility/ownership claims
  - leadership/collaboration claims
  - domain expertise claims
- Assign claim priority and “evidence burden” level.

### Stage B: Context alignment
- Align claims with:
  - JD requirements (if present)
  - ATS weaknesses/missing signals
  - analysis gaps
- Compute challenge priority per claim.

### Stage C: Interviewer-style question generation
- Generate question sets targeted to claims with rationale tags:
  - “prove metric authenticity”
  - “clarify depth of ownership”
  - “address ATS weakness with concrete example”
  - “bridge JD requirement gap”

### Stage D: Dynamic evidence evaluation
For each answer, evaluate against **three-way context**:
- Resume claim
- Job requirement (if available)
- Candidate answer evidence

Output per claim:
- Evidence Strength: Strong / Moderate / Weak / Unsupported
- Reasoning: explicit why
- Recommendation: strengthen, reword, remove, or keep

### Stage E: Wording improvement synthesis
- When answers contain stronger evidence than current claim wording, suggest revised phrasing.
- Enforce truthfulness guardrails (no invented metrics or fabricated scope).

### Stage F: Readiness report update
- Aggregate defense outcomes into updated readiness dimensions:
  - claim credibility
  - role alignment confidence
  - interview defensibility risk
  - priority fix list

### AI recommendations
- **Recommendation:** Use structured JSON outputs at every stage with schema validation.
  - **Rationale:** Deterministic integration and safer UI rendering.
  - **Trade-off:** Requires prompt/schema maintenance as the feature evolves.

- **Recommendation:** Reuse routed model client and model allowlist (`llm.py`) instead of direct one-off model calls.
  - **Rationale:** Operational consistency and controllable model behavior.
  - **Trade-off:** Some existing routers may need harmonization to remove special-case paths.

- **Recommendation:** Keep defense prompts explicitly evidence-grounded and include anti-fabrication instructions (similar to first-resume guardrails).
  - **Rationale:** Prevents hallucinated recommendations and protects user trust.
  - **Trade-off:** Conservative outputs may feel less “creative,” but are safer and more credible.

- **Recommendation:** Add light rubric normalization for evidence strength to reduce model drift.
  - **Rationale:** Produces stable claim scoring across sessions.
  - **Trade-off:** May flatten subtle distinctions unless rubric is iteratively tuned.

## 9. Security Review
### Threat model highlights
- User-submitted resume/JD content can contain prompt-injection or malicious payloads.
- Defense outputs contain personal/professional sensitive data.
- Voice and transcript paths may increase privacy risk.

### Security controls
- Authentication/authorization:
  - Reuse existing session auth and access control dependencies.
- Input controls:
  - enforce strict size/type bounds for resume/JD/answers
  - sanitize and normalize text before prompting
- Prompt hardening:
  - isolate user text from instructions via explicit delimiters
  - use schema-only outputs for structured stages
- Output safety:
  - sanitize/escape HTML render surfaces
  - avoid injecting untrusted text into rich HTML without cleaning
- Data minimization:
  - store only required evidence summaries by default
- Abuse/rate controls:
  - per-user session and answer submission limits
  - analytics events for abuse anomaly detection

### Security recommendations
- **Recommendation:** Reuse existing auth/access gates; do not create custom defense-only auth rules.
  - **Rationale:** Lower risk of policy drift and access bugs.
  - **Trade-off:** Defense inherits current global policy constraints.

- **Recommendation:** Treat resume, JD, and answers as untrusted content in both prompts and UI.
  - **Rationale:** Reduces prompt injection and XSS risk.
  - **Trade-off:** More sanitization and validation plumbing.

- **Recommendation:** Keep raw transcript retention optional and short-lived.
  - **Rationale:** Privacy-first storage posture.
  - **Trade-off:** Less historical data for retrospective quality audits.

- **Recommendation:** Add explicit audit fields on defense runs (model, timestamps, status transitions).
  - **Rationale:** Supports incident debugging and trust/compliance narratives.
  - **Trade-off:** Slightly larger persistence footprint.

## 10. Testing Strategy
### Test layers
1. **Unit tests (backend services)**
   - claim extraction normalization
   - claim-priority logic
   - evidence-strength rubric clamping/mapping
   - readiness aggregation formulas
2. **Contract tests (API schemas)**
   - payload validation, error handling, state transitions
3. **Integration tests (service orchestration)**
   - session start -> answer submit -> complete matrix
   - with/without JD branches
   - with ATS context and without ATS context
4. **Frontend component/flow tests**
   - canvas step progression and state persistence
   - matrix rendering and recommendation actions
5. **End-to-end tests**
   - full approved workflow path from upload to updated readiness report
6. **Regression tests**
   - ensure existing interview, analysis, ATS, and export flows remain stable

### Quality gates
- Schema compliance for every AI stage.
- Deterministic fallback behavior for partial AI failures.
- Evidence matrix completeness checks (no orphan claims, no missing strength/reasoning fields).

### Testing recommendations
- **Recommendation:** Start with deterministic service tests using mocked LLM responses before live model tests.
  - **Rationale:** Fast, reliable CI signal.
  - **Trade-off:** Mocked tests cannot capture all prompt-behavior variance.

- **Recommendation:** Add scenario-based golden tests for matrix outputs (strong claim, weak claim, unsupported claim).
  - **Rationale:** Prevents regressions in user-facing reasoning quality.
  - **Trade-off:** Golden fixtures require periodic maintenance as prompts evolve.

- **Recommendation:** Keep a focused manual QA checklist for voice and resume-rewrite handoff.
  - **Rationale:** These are integration-heavy paths where UX failures are costly.
  - **Trade-off:** Manual QA takes release time and discipline.

## 11. Implementation Roadmap
### Phase 0 — Contract Finalization
- Freeze defense domain vocabulary and schema contracts (claim, evidence strength, recommendation, readiness delta).
- Decide exact scoring taxonomy and matrix row shape.

### Phase 1 — Backend Foundation
- Create defense orchestration/service structure.
- Implement claim extraction + context alignment + question generation contracts.
- Wire session persistence model.

### Phase 2 — Evidence Evaluation Engine
- Implement answer evaluation and claim-level evidence updates.
- Add matrix synthesis and wording suggestion generation.

### Phase 3 — Canvas Integration
- Add Resume Defense flow steps and store extensions.
- Integrate typed/voice answer paths.
- Add matrix and improvement handoff UI states.

### Phase 4 — Readiness Report Integration
- Extend current readiness aggregation with defense dimensions.
- Ensure report export/file persistence consistency.

### Phase 5 — Security, Observability, and QA
- Finalize validation/rate-limit controls.
- Add analytics events and run-level audit fields.
- Run test matrix (unit/integration/e2e/manual).

### Phase 6 — Build Week Hardening
- Bug triage, prompt tuning, latency tuning.
- Freeze scope and prepare demo narratives.

### Roadmap recommendations
- **Recommendation:** Deliver in vertical slices (end-to-end thin path first), not layer-by-layer big-bang.
  - **Rationale:** Earlier demoable value and lower integration risk.
  - **Trade-off:** Some internal abstractions may be refined after initial slice.

- **Recommendation:** Prioritize “with JD” and “no JD” parity before advanced polish.
  - **Rationale:** This branch is central to the approved workflow.
  - **Trade-off:** Slight delay for non-core enhancements.

- **Recommendation:** Defer non-essential refactors of large legacy files unless they directly block delivery.
  - **Rationale:** Reduces blast radius during Build Week timeline.
  - **Trade-off:** Some technical debt remains post-delivery.

## 12. Build Week Documentation Plan
Update existing Build Week docs incrementally, aligned with implementation phases.

### `docs/build-week/01_Architecture.md`
- Document final defense architecture diagrams, data flow, and service boundaries.

### `docs/build-week/03_BuildWeek_Log.md`
- Daily log of decisions, changes, blockers, and resolved risks.

### `docs/build-week/04_Testing.md`
- Test matrix, executed cases, defects, and pass/fail evidence.

### `docs/build-week/05_AI_Usage.md`
- Model selections, prompt strategy, evaluation rubric, safety controls.

### `docs/build-week/06_API_Changes.md`
- Endpoint contracts, request/response schema changes, compatibility notes.

### Documentation recommendations
- **Recommendation:** Log architecture decisions with “decision/rationale/trade-off” format.
  - **Rationale:** Keeps product and engineering intent traceable during rapid iteration.
  - **Trade-off:** Slight documentation overhead each day.

- **Recommendation:** Record all AI prompt/rubric changes with before/after behavior notes.
  - **Rationale:** Enables reproducibility and prevents silent quality regressions.
  - **Trade-off:** Requires disciplined experiment tracking.

- **Recommendation:** Keep API change log backward-compatibility explicit for frontend coordination.
  - **Rationale:** Reduces integration breakage across backend/frontend parallel work.
  - **Trade-off:** Additional coordination burden during fast iterations.

---

Resume Defense implementation specification complete.
Waiting for approval before any implementation work begins.
