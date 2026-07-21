# AnchorCV Canvas Dashboard — Full Product & Code Audit

**Date:** 2026-07-02 · **Scope:** anchorcv-frontend (canvas system, extracted components, legacy pages) + anchorcv-backend (analytics, navigate, jobs, analysis, matching, export routers)

---

## 1. Executive Summary

The canvas architecture is clean, the extraction pattern is consistent, and error handling in individual steps is above average. However, **the canvas is not ready for users**: a single line in `CanvasFlow.jsx` (the `resolvedSteps` filter) silently skips the Paste-JD step in the Job/Scholarship flows and skips the entire CV builder in the Build-CV flow the moment a CV is uploaded. Additionally, the "Fetch from URL" feature calls an endpoint that does not exist in the backend, and the Improve-Resume flow is defined but unreachable from the UI. Two of five flows are functionally broken and one is inaccessible. The fixes are small and surgical — this is roughly 2–3 days of work from a shippable canvas.

---

## 2. What's Exceptional

- **Extraction pattern is genuinely consistent.** `OutputTypeCards`, `MatchScoreCard`, `DiscoveryInputControls`, `DiscoveryLandscape`, and `FileDropzone` are each used by both the legacy pages (`AnalysisPage.jsx:517,742`, `DiscoveryPage.jsx:267,301`) and the canvas steps (`StepSelectOutputs`, `StepResults`, `StepDiscoveryInput`, `StepDiscoveryLandscape`). One source of truth, no forked copies.
- **Partial-failure handling in `StepGenerate.jsx` is best-in-class for this codebase.** Per-output try/catch, successes preserved (`lines 78–93`), a dedicated 402 premium branch (`lines 95–104`), and a "Retry Failed Outputs" button that re-runs only the failures (`line 187`). This is exactly how multi-output generation should be handled.
- **Analytics instrumentation is thoughtful.** `CanvasFlow.jsx` tracks `canvas_flow_started`, `canvas_step_completed` (with time-on-step), `canvas_flow_completed`, and uses `navigator.sendBeacon` for `canvas_step_abandoned` on `beforeunload` (`canvasAnalytics.js:17–33`) — the correct API for exit events. Error events (`canvas_error_shown`) are fired at every failure site with flow/step/error_type payloads.
- **`api/client.js` is a proper centralization.** Single `request()` with credential handling, robust FastAPI error-detail normalization (handles string, array-of-validation-errors, and nested objects), automatic JSON-vs-blob response detection. Every canvas step goes through it.
- **`AIConcierge.jsx` degrades gracefully.** 5-minute per-page cache, deterministic backend fallbacks in `navigate.py:59–111` when the OpenAI call fails, outside-click close, per-page auto-open guard. The 30-second auto-open on the canvas intent step (`AIConcierge.jsx:130–134`) matches spec.
- **`FileDropzone.jsx` accessibility:** `role="button"`, `tabIndex=0`, Enter/Space handling, descriptive `aria-label`, drag-state feedback. Better a11y than most production dropzones.
- **`FirstResumePage.jsx`** — dual reorder affordances (dnd-kit drag with `KeyboardSensor` + explicit ▲/▼ buttons with aria-labels), localStorage draft autosave, local HTML preview with proper `escapeHtml`, iframe-sandboxed preview.
- **Design system in `globals.css`** — full token set (`--bg-primary`, `--accent: #7c6ff7`, `--teal`, radius scale), a complete `[data-theme="light"]` override layer, `prefers-reduced-motion` support (`line 192`), and a `pointer: coarse` block enforcing 48px tap targets (`line 2855`).
- **Backend `matching.py`** accepts both `file`/`resume_file` and `job_description`/`requirement_text` field names — defensive API design that absorbed the frontend migration without breakage.

---

## 3. What's Broken (P0 — must fix before any user sees the canvas)

### P0-1: Uploading a CV skips the next step (Job, Scholarship, Improve, Build-CV flows)
`CanvasFlow.jsx:39–42` removes `"upload"` from `resolvedSteps` as soon as `cvText` is set. `StepUploadCV.jsx:39–42` sets `cvText` via `setUploadedCV(file, text)` and **then** calls `onComplete()` (= `nextStep`) after 250ms. Sequence: upload succeeds → `cvText` set → steps re-index, `currentStep=1` now renders **StepPasteJD** → 250ms later `nextStep()` fires → user lands on **StepSelectOutputs**. The Paste-JD step is never seen. The user then generates a cover letter against an **empty job description** (backend `analysis.py:13` accepts `requirement_text=""` silently, producing generic output).
**Fix:** freeze `resolvedSteps` at flow start (compute the filter only in `setFlow`), or drop the `setTimeout(onComplete)` and don't auto-advance when the step list just re-indexed.

### P0-2: Build-CV flow never shows the builder if a CV is uploaded
Same root cause, worse outcome. `FLOW_STEPS.buildCV = ["upload", "buildCV", "export"]` (`CanvasFlow.jsx:19`). After upload: `resolvedSteps = ["buildCV","export"]`, auto-advance lands on **StepExport** — the entire `FirstResumePage` builder is skipped.

### P0-3: Build-CV flow's export step is permanently disabled
`StepExport.jsx:58` gates all buttons on `generatedResults`, but the Build-CV flow never writes to `generatedResults` — `FirstResumePage` keeps its output in local state and has its own export buttons. Even without P0-2, users finishing the builder hit an export step with three disabled buttons and no explanation.
**Fix:** either remove `export` from the buildCV flow, or push the generated resume HTML into the canvas store.

### P0-4: "Fetch from URL" calls a nonexistent endpoint
`StepPasteJD.jsx:34` posts to `/jobs/extract-from-url`. `anchorcv-backend/app/routers/jobs.py` defines only `/jobs/search`, `/jobs/generate-document`, `/jobs/match-score` — `grep -r "extract-from-url" app/` returns nothing. Every URL fetch 404s. The graceful fallback message ("paste manually") masks a feature that has never worked.
**Fix:** implement the endpoint or remove the URL input.

### P0-5: Flow E (Improve Existing Resume) is unreachable
`improveResume` exists in `FLOW_STEPS` (`CanvasFlow.jsx:20`) and `FLOW_DEFAULTS` (`StepSelectOutputs.jsx:20`), but `StepIntent.jsx:177–214` renders no chip for it and no other code calls `setFlow("improveResume")`. Dead flow. Compounding: its default output `Resume_Optimization` is in `PREMIUM_ONLY_OUTPUTS` (`StepSelectOutputs.jsx:10–15`), so free users entering this flow would get an **empty default selection** (`line 46` filters locked outputs).

### P0-6: Refresh mid-flow loses everything
`useCanvasStore.js:72–75` persists only `selectedOutputs` and `discoveryData`. `currentFlow`, `currentStep`, `cvText`, `jdText`, `generatedResults` all evaporate on reload — a user who refreshes on Step 5 restarts at intent with no explanation. (`uploadedCV` is a `File` object and can't be persisted, but `cvText`/`jdText`/`generatedResults` can.)

---

## 4. Good But Could Be Better (P1/P2)

- **P1 — Scholarship flow is a re-labeled job flow.** Title adapts (`StepPasteJD.jsx:20–23`) but the textarea placeholder is generic, defaults are identical to job (`Cover_Letter`, `Job_Match_Score` — `StepSelectOutputs.jsx:17–19`), and the meta-card admits "Scholarship flow uses Cover Letter internally." There is no Statement-of-Purpose output type and no scholarship-specific prompt path visible; generated content will read like a job cover letter unless the backend prompt branches on something the canvas never sends.
- **P1 — `StepIntent.jsx:103–140` fires an LLM call on every store change.** The `/navigate/` endpoint hits `gpt-4o-mini` (`navigate.py:182`). The effect's deps include `generatedResults` (object identity) and re-runs on every state mutation, with no cache — unlike `AIConcierge`, which caches for 5 minutes. Real money and latency for a hint. Also `is_premium: false` is hardcoded (`line 121`).
- **P1 — `dangerouslySetInnerHTML` on AI output** (`StepResults.jsx:46–56`, `AnalysisPage.jsx:747,752`, `StepExport` builds export HTML the same way). Backend HTML comes from an LLM; there's no sanitization layer (no DOMPurify in the repo). Prompt-injected markup in a scraped JD could land in the DOM.
- **P1 — Analytics events are logged, not stored.** `analytics.py:46` does `logger.info(json.dumps(record))` and returns. No table, no dashboard, no way to query funnel drop-off. The instrumentation investment on the frontend currently produces log lines only.
- **P1 — `MatchScoreCard` is hardcoded to `theme="light"`** in `StepResults.jsx:42` while the canvas defaults to dark — score-circle colors are computed for the wrong background.
- **P1 — Concierge "Your First Resume" chip is hardcoded** (`AIConcierge.jsx:249–259`) above every suggestion list and navigates to `/first-resume`, yanking a mid-flow canvas user out of the canvas without warning.
- **P2 — `StepExport.jsx:184–190`: "Finish" and "Start Over"** are two adjacent primary buttons calling the same handler. Pick one.
- **P2 — Region is smuggled into the query string** — `StepDiscoveryInput.jsx:44`: `query: \`${trimmed} | region: ${region}\``. Fragile contract; send `region` as its own field.
- **P2 — Discovery→Apply JD prefill is thin.** `StepDiscoveryLandscape.jsx:18–25` builds the "JD" from title/institution/country/type/note — a few lines, not real requirements. Match scores against it will be near-meaningless. Consider fetching the opportunity page or telling the user to paste the full posting (which they currently can't see, per P0-1).
- **P2 — `navigate.py:182` OpenAI call has no timeout**; a slow upstream hangs the request thread for the concierge panel.
- **P2 — `CanvasTestPage` is routed in production** (`App.jsx:44`).
- **P2 — Code smells:** IIFE inside `.map()` in `OutputTypeCards.jsx:49`; `StepIntent`'s `extractDiscoveryPrefill` (lines 15–78) is a 60-line key-guessing waterfall that should be a typed contract with the discovery API; heavy inline styles throughout canvas steps instead of the design-system classes; `vite.config.js` comment points at a production backend on a raw HTTP IP (`http://178.104.48.216:8000`).

---

## 5. Flow-by-Flow Audit

### Flow A — Apply for a Job: **4/10**
- **Completeness:** Broken. Fresh users skip Paste-JD (P0-1) and generate against an empty JD. Users arriving with an existing `cvText` (Continue chip) get the correct sequence.
- **Friction:** URL fetch always fails (P0-4). Back from step 1 exits to Intent, which is fine but unlabeled.
- **Visual:** Consistent panels, good loading quotes during generation.
- **Error handling:** Excellent within steps (partial failure, 402, retry).

### Flow B — Apply for a Scholarship: **3/10**
Same P0-1 skip, plus no scholarship-specific outputs, placeholders, or defaults (P1). Generated content is a job cover letter with a disclaimer card.

### Flow C — Discover Opportunities: **7/10**
- Works end-to-end: query + intent + region → `/discover/landscape` → `DiscoveryLandscape` render → "Analyze my CV for this" transitions flows with JD pre-set. Best flow in the canvas.
- Weaknesses: prefill is thin (P2); after the transition the user hits the P0-1 skip and never confirms the JD; resume uploaded during discovery isn't carried into the canvas store (re-upload required).

### Flow D — Build CV from Scratch: **3/10**
- `FirstResumePage` itself is strong (drag-and-drop works, keyboard reorder works, add/remove/reorder sections, PDF/DOCX export inside the page).
- But the flow around it is broken: upload skips the builder entirely (P0-2), the canvas export step is dead (P0-3), and nesting a full page (own `page-title` header, own export bar) inside `StepWrapper`'s panel produces a double-header, panel-in-panel layout.

### Flow E — Improve Existing Resume: **1/10**
Unreachable (P0-5). If wired up, free users get an empty output default.

---

## 6. Component-by-Component Audit

| Component | Code | Reuse | Visual | Errors | A11y |
|---|---|---|---|---|---|
| CanvasFlow.jsx | 6 — clean routing, but P0-1 filter + analytics logic could be a hook | n/a | n/a | 7 — unknown-step fallback exists | n/a |
| StepWrapper.jsx | 8 | 9 — used by all steps | 7 | n/a | 6 — Back button fine; heading order ok |
| StepIntent.jsx | 5 — prefill waterfall, uncached LLM effect | 6 | 8 — prominent-chip treatment is nice | 6 — silent catch is fine here | 6 — chips are real buttons ✔ |
| StepUploadCV.jsx | 6 — P0-1 trigger; otherwise tidy | 8 | 7 | 8 — extract error + retry + tracked | 7 (via FileDropzone) |
| StepPasteJD.jsx | 7 | 8 | 7 | 8 — URL/file/manual fallbacks | 7 — labeled textarea ✔ |
| StepSelectOutputs.jsx | 7 | 9 | 7 | 8 — locked-output hint + upgrade CTA | 6 — `aria-disabled` on locked cards ✔ |
| StepGenerate.jsx | 8 — the standout | 8 | 7 | 9 | 6 |
| StepResults.jsx | 6 — XSS surface, hardcoded light theme | 8 | 6 | 6 — empty-state card ✔ | 5 — `<details>` is keyboard-friendly ✔ |
| StepExport.jsx | 6 — duplicate buttons, disconnected from buildCV | 7 | 6 | 8 — per-action pending + retryable | 6 |
| StepDiscoveryInput.jsx | 7 | 8 | 7 | 8 | 7 |
| StepDiscoveryLandscape.jsx | 7 — thin prefill | 8 | 7 | 6 — has empty state | 6 |
| StepBuildCV.jsx | 4 — page-in-panel wrapper | 5 | 4 — double header | 5 | 6 |
| OutputTypeCards | 7 (IIFE smell) | 9 | 8 | n/a | 7 |
| FileDropzone | 9 | 9 | 8 | n/a | 9 |
| AIConcierge | 7 | n/a | 8 | 8 — fallback + cache | 6 — fab/close have aria-labels; "X" close text is weak |
| ThemeToggle | 6 | n/a | 7 | 7 — try/catch on storage | 4 — no `aria-pressed`, no `aria-label`, relies on `title` + emoji; does **not** announce state to screen readers |

---

## 7. Backward Compatibility Report

All legacy routes verified present in `App.jsx:37–49` under `ProtectedRoute` + old `Layout`: `/` (Dashboard), `/first-resume`, `/discover`, `/jobs`, `/analysis`, `/ats-shield`, `/builder`, `/files`, `/account`. Canvas is additive at `/canvas` with its own `CanvasLayout`.

- `AnalysisPage.jsx` still consumes the extracted `OutputTypeCards` (line 517) and `MatchScoreCard` (line 742) — no fork, no regression found in wiring.
- `DiscoveryPage.jsx` consumes extracted `DiscoveryInputControls` (line 267) and `DiscoveryLandscape` (line 301), keeps its own state in `useCvWorkspaceStore` (correctly separate from the canvas store).
- `FirstResumePage` works both standalone and (structurally) inside the canvas.
- One regression risk, not a current break: `DiscoveryInputControls` now serves two parents with different state containers (page store vs. step-local state); prop drift between them will bite silently. Add a shared prop-types contract or TS.

**Verdict: backward compatibility intact.**

---

## 8. Mobile Audit

- Breakpoints exist at 960/768/600px; grids collapse to one column; `pointer: coarse` enforces 48px targets on buttons and inputs (`globals.css:2855–2872`) — exceeds the 44px requirement. ✔
- Canvas top bar: `CanvasLayout` reuses the `sidebar-toggle`/`sidebar-body` collapse for the avatar/theme/sign-out cluster — works, but "Menu" toggling a 3-item row is odd labeling on a canvas with no menu.
- Steps stack fine (single-column panels, `minmax(260px,1fr)` chip grid on Intent).
- **Flag:** `FirstResumePage` inside the canvas on mobile is form-on-top/preview-below (correct per `globals.css:487`), but nested inside `StepWrapper`'s padded panel it loses ~2rem of width at 375px; the `first-resume-grid` inputs get cramped. Test at 375px before shipping Build-CV.
- **Flag:** the Concierge FAB (52px, fixed bottom-right, `globals.css:2416`) overlaps the primary Continue buttons on short viewports/landscape rotation; no `env(safe-area-inset-bottom)` handling.

---

## 9. Performance Audit

- **No code splitting at all.** `App.jsx` imports every page eagerly; `dist/assets/index-*.js` is a single **486KB** bundle. `FirstResumePage` (+dnd-kit) and `DiscoveryLandscape`/`MarketMap` are prime `React.lazy` candidates.
- **Sequential generation:** `StepGenerate.jsx:78–86` awaits each output in a `for` loop. Three outputs × ~10–20s each = worst-case minute-plus wait. The requests are independent — use `Promise.allSettled`.
- **Uncached LLM calls from StepIntent** on every store mutation (see P1). Also duplicates what `AIConcierge` already fetches with caching.
- **Re-render hygiene is otherwise good** — granular zustand selectors everywhere; no obvious render storms.
- `finishFlow`/analytics logic in `CanvasFlow` recreates closures per render — negligible, but extracting a `useFlowAnalytics` hook would help readability.

---

## 10. Final Recommendations (priority order)

1. **Fix the `resolvedSteps` skip (P0-1/P0-2):** compute step filtering once at `setFlow` time, or advance by explicit step key rather than index. This single fix repairs Flows A, B, and D. Add a regression test: "upload CV → next visible step is Paste JD."
2. **Wire up or delete Flow E** — add an "Improve my resume" chip in `StepIntent`, and give `improveResume` a free-tier default output.
3. **Implement or remove `/jobs/extract-from-url`.**
4. **Repair the Build-CV ending:** drop `export` from the flow or pipe the builder result into `generatedResults`; unwrap `FirstResumePage` from the panel (render full-bleed, suppress its duplicate header).
5. **Persist flow state:** add `currentFlow`, `currentStep`, `cvText`, `jdText`, `generatedResults` to the store's `partialize`, with a "Resume where you left off?" prompt.
6. **Store analytics events** in a table (SQLite/Supabase) instead of `logger.info`, and add a minimal funnel query — you already emit everything needed to measure step drop-off.
7. Make scholarship real: a `Statement_of_Purpose` output type and scholarship-adapted placeholder/defaults.
8. Parallelize generation with `Promise.allSettled`; cache or remove StepIntent's `/navigate/` call.
9. Sanitize AI HTML with DOMPurify at the three injection sites.
10. Code-split routes; fix ThemeToggle a11y (`aria-pressed` + `aria-label`); remove `/canvas-test`; dedupe StepExport's Finish/Start-Over; fix `MatchScoreCard` theme in `StepResults`.

The foundation is worth keeping. Fix the flow engine, connect the two dead endpoints, and this canvas is a real product.
