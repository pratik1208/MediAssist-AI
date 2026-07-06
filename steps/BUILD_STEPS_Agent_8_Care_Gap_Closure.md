# BUILD_STEPS_Agent_8

# BUILD_STEPS — MediAssist AI: Care Gap Closure

Covers PRD → "Care Gap Closure" (FR-G1…FR-G9). Mostly a *rules-over-data* agent: guideline definitions scanned against patient records on a schedule. It reuses Outreach for contact and Scheduling for booking — build very little new plumbing here.

**Prerequisites:** Agents 1, 2, and 7 (outreach delivery + cohort/criteria engine). Agent 3's protocol-as-data pattern is the template for guidelines.

## Phase 1 — Data models

- [ ]  `python manage.py startapp caregaps`; add to `INSTALLED_APPS`
- [ ]  Models: `ClinicalGuideline` (name, applicable-population criteria JSON — reuse the Agent 7 criteria schema; required care item — screening / test / vaccination / visit; frequency e.g. "HbA1c every 6 months for diabetics"; risk tier — `high` / `medium` / `low` per FR-G3; active, version), `CareGap` (FK → Patient + Guideline; status — `open` / `outreach` / `scheduled` / `completed` / `closed`; detected_at, due_since, closed_at; unique open gap per patient+guideline), `CarePlan` (FK → Patient; bundled gap M2M; plan text; status), plus a lightweight `ClinicalEvent` table if your record data isn't queryable enough yet (patient, event type, code, date — what the scanner reads)
- [ ]  `makemigrations && migrate`; admin; `seed_guidelines` command (diabetic HbA1c 6-monthly, annual diabetic eye exam, flu vaccine 65+, mammogram screening schedule, post-discharge follow-up)

## Phase 2 — Core business logic (no AI yet)

`caregaps/services.py`:

- [ ]  `scan_patient(patient)` — evaluate every active guideline: is the patient in the population, and is the required item missing/overdue given their history? Create/refresh `CareGap`s; never duplicate an open gap (FR-G1/G2)
- [ ]  `scan_all()` — bulk scan (queryset-driven, NFR-9); management command now, nightly job in Phase 7
- [ ]  `prioritize()` — order open gaps by guideline risk tier + overdue duration (FR-G3)
- [ ]  `bundle_care_plan(patient)` — group a patient's open gaps into one `CarePlan`, marking which items can share a single visit (labs + vaccine + wellness visit together, FR-G4)
- [ ]  `close_gap(gap, evidence_event)` — completion detected (appointment completed / lab resulted) → gap `closed`, dashboards updated (FR-G8)
- [ ]  `recycle_incomplete()` — care plans with pending items past a window re-enter outreach automatically (FR-G7, PRD Edge Case 17)
- [ ]  Tests: scanner truth table per guideline (in/out of population, done/not done, overdue boundary), no-duplicate-gap rule, bundling, close-on-evidence, recycle loop. `pytest` green.

## Phase 3 — API layer

- [ ]  Staff endpoints: prioritized patient list, gaps per patient, trigger scan (dev), care plan detail
- [ ]  Quality metrics endpoint: open gaps by guideline, closure rate, response rate, completion rate, per-provider breakdown (FR-G9)

## Phase 4 — AI integration

Smallest AI surface of any agent — the scanning must stay deterministic (auditable, per NFR-4).

- [ ]  `write_care_plan_message(care_plan, patient)` — turn the bundled plan into a warm, plain-language outreach message in the patient's preferred language ("you're due for A, B and C — we can do all three in one visit")
- [ ]  Optional: `extract_clinical_events(document)` — reuse Agent 2's document-extraction tooling to backfill `ClinicalEvent`s from uploaded lab reports, so the scanner has data to read
- [ ]  LangSmith tracing; verify generated messages never invent clinical claims not present in the plan (spot-check suite with fixture plans)

## Phase 5 — Frontend

- [ ]  Population health / care gap dashboard (PRD Screens #6): open gaps by guideline, closure rate trend, risk-prioritized patient list, per-provider quality view
- [ ]  Per-patient gap panel on the provider dashboard (visible during scheduling, so front-desk sees "also due for cholesterol screening")
- [ ]  Manual E2E: seed a diabetic fixture overdue for HbA1c → nightly scan opens the gap → bundled plan → outreach message → patient books via reply → lab event closes the gap → dashboard reflects it

## Phase 6 — Integration + edge cases

- [ ]  Outreach delivery: care-gap outreach runs AS an Agent 7 campaign (cohort = patients with open plans) — don't build a second sender (FR-G5)
- [ ]  Scheduling: accepted plans book labs/visits/vaccinations via Agent 1, respecting availability + insurance (FR-G6)
- [ ]  Scheduling surface hook (PRD secondary journey): when any booking flow runs, expose `open_gaps_for(patient)` so the conversation can offer to add overdue items to the visit
- [ ]  Completion detection wired to appointment-completed and (if built) lab-result events
- [ ]  Edge-case test: PRD Edge Case 17

## Phase 7 — Deploy

- [ ]  Migrate + deploy; seed guidelines; schedule nightly `scan_all` + weekly `recycle_incomplete`
- [ ]  Smoke-test one gap through the full loop live
