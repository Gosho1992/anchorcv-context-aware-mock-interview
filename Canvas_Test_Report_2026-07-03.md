# AnchorCV Canvas Dashboard — Test Execution Report

**Date:** 2026-07-03
**Environment:** localhost:5173 (frontend) + localhost:8000 (backend), driven live via Claude in Chrome.
**Account under test:** `test zia` (test.zia@gmail.com) — **Premium** (51–52 days left).
**Test data:** `test_cv.pdf` (JOHN TEST — Data Analyst) + TechGlobal "Senior Data Analyst" JD, per plan.
**Method:** Every test was actually executed in the running app (clicks, uploads, generations, network-status checks). No test was passed on code inspection alone.

---

## Summary Table

| Test ID | Result | Severity if FAIL |
|---|---|---|
| A1 — Flow-skip (Job) | PASS | — |
| A1 — Flow-skip (Scholarship) | PASS | — |
| A2 — Build-CV dead-end | PASS | — |
| A3 — Improve-Resume reachability | PASS | — |
| A4 — Mid-flow refresh | PASS | — |
| A5 — Free-user default output | BLOCKED | — |
| A6 — extract-from-url + SSRF | PASS | — |
| B — CV replace | PASS | — |
| C — Multi-model (GPT + Claude) | PASS (w/ bug) | MEDIUM (company-name bug) |
| D — Templates (World Bank) | PASS | — |
| D — Templates (Immigration/Visa) | PASS | — |
| E — Parallel generation | PASS (w/ bug) | HIGH (stale output) |
| F — /analysis | PASS | — |
| F — /discover | PASS | — |
| F — /jobs | PASS | — |
| F — /ats-shield | PASS | — |
| F — /builder | PASS | — |
| F — /first-resume | PASS | — |
| F — /files | PASS | — |
| F — /account | PASS | — |
| G — Mobile 375px | BLOCKED | — |

---

## Section A — The 6 Original P0 Bugs

### A1 — Flow-skip (Job & Scholarship): PASS
- **Done:** Canvas → "I have a job description" → uploaded test CV. Separately, Canvas → "I want to apply for a scholarship" → CV → Continue.
- **Expected:** JD-entry step appears after CV, not skipped to Select Outputs.
- **Actual:** Job flow advanced to **"Paste Job Description"** immediately after CV upload. Scholarship flow advanced to **"Paste Scholarship Details"** (title correctly adapts). Neither skipped to Select Outputs.
- **Evidence:** Screenshots of both steps; step order confirmed CV → Paste JD/Scholarship → Select Outputs.

### A2 — Build-CV dead-end: PASS
- **Done:** "Build a CV from scratch" → filled name/email → Generate Resume → Continue.
- **Expected:** Export reachable at the end.
- **Actual:** Builder's live-preview panel exposes **Export PDF / Export DOCX** directly; the canvas "Continue" leads to a clean **"Flow Complete → Finish"**. Not a dead-end.

### A3 — Improve-Resume reachability: PASS
- **Done:** Canvas intent screen showed **"Improve my existing resume"** chip; clicked it.
- **Actual:** Flow started at **"Upload Your CV"** → after upload advanced to **"Paste Job Description (optional)"**. Chip exists and flow starts correctly.

### A4 — Mid-flow refresh: PASS
- **Done:** Job flow to Select Outputs → reloaded the tab.
- **Actual:** Resumed at the **exact same step (Select Outputs)**; top-bar CV (`test_cv.pdf`) intact; stepping Back showed the **TechGlobal JD text preserved**. CV + JD both intact.

### A5 — Free-user default output: BLOCKED
- **Reason:** The only available account is **Premium** (`test zia`, ~51 days left). Creating a new account is not something I can do (account creation is a restricted action). Free-tier gating / revenue-leak behaviour could **not be tested**. Needs a non-premium test account from you.

### A6 — extract-from-url + SSRF: PASS
- **Legit fetch:** `https://boards.greenhouse.io/weee/jobs/6346692003` → **HTTP 200**, populated the requirements textarea.
- **SSRF probe:** `http://localhost:8000/api/auth/me` → **HTTP 422** (rejected by validation), UI showed "URL fetch failed." **No internal data returned.** SSRF protection is working — not a vulnerability.
- **Observation (LOW):** Extraction from the Greenhouse board URL pulled the entire job-listings index (all roles / nav), not a single clean JD. Extraction quality on board-style URLs is noisy.

---

## Section B — CV Replace: PASS
- **Actual:** A persistent **`✓ CV: <filename>  Change`** control sits in the top bar across all flows. The shared **"Your CV"** step offers **Replace / Continue**, and Replace opens an **"Upload a new CV to replace the current one"** dropzone with a **"Cancel — keep <filename>"** escape. Multiple visible, clickable ways to change the CV without clearing storage.

---

## Section C — Multi-Model (GPT + Claude): PASS (with a MEDIUM bug)
- **Config:** `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` both set in backend `.env`.
- **Selector:** Lists **GPT-4o mini, GPT-4o, Claude Haiku 4.5, Claude Sonnet 4.6**.
- **Claude Sonnet 4.6 cover letter:** Valid, well-formatted, no raw JSON, no error strings, no truncation.
- **GPT-4o cover letter:** Valid, complete, no JSON/errors/truncation; **no crash when switching providers.**
- **BUG (MEDIUM) — wrong company name in cover letters:** The target company is mis-extracted as **"Python"** instead of **"TechGlobal Inc."** In the Claude letter it appears only in the address header ("Hiring Manager / Python / London"); in the **GPT-4o letter it pervades the body** — e.g. *"align with the needs of Python," "At Python, I aim to…," "contributing to Python's success."* The letters are otherwise usable but address the wrong employer. Likely the company-name field falls back to a JD keyword ("Python") when the employer isn't parsed.

---

## Section D — CV Templates: PASS (World Bank + Immigration/Visa)

**World Bank CV**
- **Convert (HTTP 200):** No fabrication. Name/Education/Employment accurate to the CV; Countries "Pakistan" correctly inferred from Islamabad; missing fields marked `[No information provided — add details here]` and assignment fields marked `[ADD: client name]` / `[ADD: budget]`; a disclaimer explains the `[ADD:]` placeholders.
- **Compare & Score (200):** Overall **25/100** with per-section scores (name 80, nationality 0, languages 0, education 60, employment 40, assignments 0, countries 0, certs 0), each with a specific reason, plus targeted strengths/gaps/recommendations tied to WB standards. Not generic filler.
- **Export:** `/api/export/pdf` **200**, `/api/export/docx` **200**.

**Immigration / Visa CV**
- **Convert (200):** No hard fabrication — employment/education accurate; hours correctly left as `[ADD: hours per week]`; achievements/licenses/references marked "No information provided."
- **Compare & Score (200):** Overall **45/100** with per-section scores and immigration-specific recommendations (exact month/year dates, working hours, verifiable achievements).
- **Observation (LOW) — inconsistent nationality handling:** World Bank left Nationality **blank** (`[No information provided]`), but Immigration **inferred "Nationality: Pakistani"** from the Islamabad location — then its own Compare step flags nationality as "missing." Minor inference the WB path avoided; worth aligning, especially since the Immigration template is explicitly an "evidence document."

---

## Section E — Parallel Output Generation: PASS (with a HIGH bug)
- **Done:** Selected exactly 3 outputs (Resume Optimization, Job Match Score, Cover Letter) → Generate (Claude Sonnet).
- **Actual (selected 3):** All three appeared, none missing, none corrupted, **none contaminated with another output's content** — each correctly referenced John Test / TechGlobal. Parallel generation of the selected set is sound.
- **BUG (HIGH) — stale output not cleared / export-bound:** The Generated Results **also displayed a 4th section, "Application Strategy," that was NOT selected**, containing a **previous session's data**: *"ZAIN ZIA → COLABERRY DATA & AI SCHOLARSHIP"* (a different person, a different CV, and a scholarship — not the John Test / TechGlobal job). It **persisted across multiple regenerations** (both Claude and GPT runs) and flows into **"Continue to Export"** (export PDF/DOCX 200), so the export bundle would contain a document about an unrelated person/opportunity. Generated outputs are not invalidated when the CV/JD/target changes.

---

## Section F — Backward Compatibility (legacy routes): all PASS

| Route | Core action verified |
|---|---|
| `/analysis` | Uploaded CV + JD, selected output via the extracted **OutputTypeCards** (all 6 render — extraction did **not** break the page), ran analysis → valid **Application Strategy** result rendered in Result preview (MATCH MAP referencing John Test vs TechGlobal). Export/Save-to-Cloud/Use-in-Builder buttons present. |
| `/discover` | Ran a search → landscape rendered (market overview, salary insights €35k–€70k, "In-demand roles" with growth bars + role chips). |
| `/jobs` | Ran a search → **"20 results" via Adzuna** rendered (title, employer, location, salary, date) with Check-match / Tailor-Resume / Cover-letter actions. |
| `/ats-shield` | Uploaded CV + pasted JD → ATS score (**80 → 91**), keyword match 71.4% (present/partial/missing breakdown), a HIGH formatting issue (table-like structures), and experience analysis. |
| `/builder` | Renders (format cards ATS/Europass/Academic/One-page, upload, live preview). |
| `/first-resume` | Standalone builder renders and works (form → live preview; same builder proven to generate in the Build-CV flow). |
| `/files` | Lists previously exported documents (multiple `anchorcv-analysis-*.pdf`, `Zain_Zia_CV.pdf`) with View/Download/Delete. |
| `/account` | Profile + **Premium** status, "52 days remaining," storage 1% of 50MB; settings marked "Coming soon"; Sign out. |

- **Console note:** The only console errors seen were repeated *"A listener indicated an asynchronous response…the message channel closed"* — a benign Chrome-extension messaging artifact, **not** AnchorCV code.

---

## Section G — Mobile / Responsive (375px): BLOCKED
- **Reason:** The browser viewport could not be reduced to phone width in this environment. `resize_window(375×800)` and `window.resizeTo(400×780)` both **report success but leave `window.innerWidth` pinned at 1600** (outerWidth capped at 1280, devicePixelRatio 0.8). The app's responsive breakpoints are viewport-driven, so the 375px phone layout could not be rendered or evaluated. Recommend testing on a real device or Chrome DevTools device mode.

---

## Observations (not pass/fail; noted separately per plan)
1. **UTF-8 / mojibake in generated text (cosmetic):** Bullet characters render as `â€¢` / `â€º` in canvas Generated Results and in the `/analysis` output; page titles show `Â·` (e.g., "Discover Â· AnchorCV"). Appears to be a UTF-8 decoding issue in output rendering.
2. **URL extraction on board-style URLs (A6):** Greenhouse board URL returned the whole listings index rather than a single JD — noisy input for downstream generation.
3. **ATS experience parsing overcounts:** `/ats-shield` reported "Total years 10 / Roles detected 3" for a CV showing ~5 years across 2 roles.
4. **Account days off-by-one:** `/account` badge says "52 days remaining" while the sidebar says "Premium · 51 days left."

---

## Prioritized list — what must be fixed before `/canvas` is linked in main nav
*(Only CRITICAL/HIGH block rollout, per the plan.)*

- **[HIGH] Stale Generated-Results output not cleared (Section E).** A prior session's "Application Strategy" (different person / different opportunity) persists in results and is included in the export. Invalidate/clear generated outputs when the CV, JD, or target changes (and when a new generation runs). **This is the one blocker.**

No CRITICAL issues found: SSRF is properly blocked (422); templates do not fabricate content.

**Not blocking, but recommended before broad launch:**
- **[MEDIUM] Cover-letter company name = "Python" (Section C).** Fix employer extraction so letters address the real company (e.g., "TechGlobal Inc"), especially in the GPT-4o path where it pervades the body.
- **[LOW] Inconsistent nationality inference between templates (Section D).**
- **[LOW] Mojibake bullets/·, ATS year-count overcount, account off-by-one (Observations).**

---

## BLOCKED — needs Zain to unblock
1. **A5 (free-user default output):** No non-premium account available; provide a free test account to verify free-tier gating and the revenue-leak check.
2. **Section G (mobile 375px):** Viewport could not be narrowed below ~1280px in this environment; test on a real phone or Chrome DevTools device emulation.
