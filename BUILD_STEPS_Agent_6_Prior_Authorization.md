# BUILD_STEPS_Agent_6

# BUILD_STEPS — MediAssist AI: Prior Authorization

Covers PRD → "Prior Authorization" (FR-P1…FR-P7). Like Referrals, a long-running workflow agent driven by status transitions; the AI does evidence assembly and payer-response interpretation.

**Prerequisites:** Agents 1–2; Agent 5 recommended (referrals are a major PA trigger). Real payer APIs are unspecified in the PRD — everything payer-facing is built behind an interface with a simulator implementation.

## Phase 1 — Data models

- [ ]  `python manage.py startapp priorauth`; add to `INSTALLED_APPS`
- [ ]  Models: `PayerRule` (payer name, plan, CPT code pattern, ICD-10 pattern, medication pattern, network requirement, requires_auth bool, submission channel — `api` / `epa` / `portal` / `fax`, required documentation list JSON), `TreatmentOrder` (FK → Patient + ordering Doctor; type — medication / imaging / procedure / device / therapy; CPT, ICD-10, medication; linked Referral nullable), `AuthorizationRequest` (FK → TreatmentOrder; payer; status enum per FR-P5 — `detected` / `gathering_evidence` / `ready_for_review` / `submitted` / `under_review` / `info_requested` / `approved` / `denied`; denial reason; appeal suggested bool; timestamps per status), `AuthorizationPackage` (FK → request; demographics snapshot, codes, evidence document refs JSON, reviewer summary text), `PayerMessage` (FK → request; direction, content — the audit trail of everything exchanged)
- [ ]  `makemigrations && migrate`; admin; `seed_payer_rules` command (a handful of realistic rules: MRI needs auth on plan X, generic statin doesn't, etc.)

## Phase 2 — Core business logic (no AI yet)

`priorauth/services.py`:

- [ ]  `detect_authorization_requirement(order)` — match the order against `PayerRule`s for the patient's insurance (from Agent 2's `InsurancePolicy`); no manual verification step (FR-P1). Returns rule + required documentation list or "not required"
- [ ]  `gather_evidence(auth_request)` — collect from the patient record everything the rule's documentation list names: diagnosis, notes, labs, imaging, medication history, prior treatments, allergies (FR-P2). Deterministic collection by category; the AI summarizes later
- [ ]  `submit(auth_request)` — dispatch through the rule's channel via a `PayerGateway` interface. Ship one implementation: `SimulatedPayerGateway` that accepts, requests more info, approves, or denies based on fixture config — this is what all your tests run against (FR-P4)
- [ ]  `poll_status(auth_request)` — status sync loop against the gateway (FR-P5); management command now, scheduled job later
- [ ]  `handle_info_request(auth_request, requested_items)` — auto-retrieve requested documents from the record and resubmit; if an item can't be found, stage a task for staff review instead of failing silently (FR-P6, PRD Edge Case 10)
- [ ]  `on_decision(auth_request)` — approved: notify physician + patient, emit `priorauth.approved` (Scheduling books the treatment); denied: notify physician with reason + `appeal_suggested` (FR-P7, PRD Edge Case 9)
- [ ]  Tests: detection matrix (auth vs no-auth rules), evidence gathering completeness, info-request auto-response vs staff-staging, both decision paths. `pytest` green.

## Phase 3 — API layer

- [ ]  Create treatment order (auto-triggers detection), get authorization status (patient + provider views, FR-P7 "visible at any time"), staff task list for staged reviews
- [ ]  Simulator control endpoint (dev only): force the fake payer's next response — makes manual testing of every branch trivial

## Phase 4 — AI integration

- [ ]  `write_reviewer_summary(package)` — one API call: turn the gathered evidence into a structured medical-necessity summary a payer reviewer can read (FR-P3). `strict: true` tool schema: `clinical_justification`, `relevant_history_points[]`, `guideline_citations[]`
- [ ]  `interpret_payer_message(message)` — payer responses (esp. simulated fax/portal text) → structured tool output: `decision` / `info_requested[]` / `deadline`. Feeds `handle_info_request` and `on_decision`
- [ ]  `suggest_appeal(auth_request)` — on denial, one call producing an appeal recommendation + draft argument for the physician (suggest only — automated appeal submission is a PRD Future Enhancement)
- [ ]  LangSmith tracing; shell testing
- [ ]  Test: fixture denial letters and info-requests parse to the right structured fields

## Phase 5 — Frontend

- [ ]  Provider: PA status column on the referral/order views; PA package review card in the approval queue (reuse Agent 4's queue page pattern) showing the AI summary before submission
- [ ]  Patient: authorization status card (plain-language status + what happens next)
- [ ]  Staff: staged-task list for info-requests needing human review
- [ ]  Manual E2E against the simulator: order → detected → package → submit → info requested → auto-answer → approved → treatment scheduled

## Phase 6 — Integration + edge cases

- [ ]  Consume `priorauth.needed` events from Referrals (Agent 5 Phase 6); ordering a treatment during triage disposition also triggers detection (FR-T7)
- [ ]  On approval, hand off to Scheduling to book the approved treatment (FR-P7)
- [ ]  Edge-case tests: PRD Edge Cases 9 and 10
- [ ]  Analytics: turnaround time per status, approval rate, denial reasons breakdown

## Phase 7 — Deploy

- [ ]  Migrate + deploy; seed payer rules; schedule `poll_status` (e.g. hourly)
- [ ]  Smoke-test one full simulated authorization live
- [ ]  Later swap-ins behind `PayerGateway`: real ePA network / payer APIs / fax service — the interface means no workflow code changes
