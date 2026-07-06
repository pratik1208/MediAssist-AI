# BUILD_STEPS_Agent_4

# BUILD_STEPS — MediAssist AI: Automated Refill Coordination

Covers PRD → "Automated Refill Coordination" (FR-M1…FR-M8). First "Phase 2" agent — start once Registration, Scheduling, and Triage work end to end.

**Prerequisites:** Agents 1–3 (needs `core.Patient`, identity verification from Registration, and the escalation pattern from Triage).

## Phase 1 — Data models

- [ ]  `python manage.py startapp refills`; add to `INSTALLED_APPS`
- [ ]  Models: `Prescription` (FK → Patient + prescribing Doctor; medication name, dose, quantity, refills allowed, refills used, prescribed date, expiry date, status — `active` / `discontinued` / `expired`; required labs JSON; follow-up required bool), `Pharmacy` (name, address, phone, fax/e-rx identifier), `RefillRequest` (FK → Prescription + Patient + Pharmacy; status — `received` / `eligibility_check` / `paused` / `pending_approval` / `approved` / `rejected` / `visit_required` / `sent_to_pharmacy` / `ready_for_pickup`; pause reason; renewal summary JSON; decided_by, decided_at), `ControlledSubstanceFlag` on `Prescription` (bool — these must NEVER be auto-processed; see PRD Edge Case 12)
- [ ]  `makemigrations && migrate`; admin registration; management command `seed_prescriptions` for fixture patients

## Phase 2 — Core business logic (no AI yet)

`refills/services.py` — this agent is mostly deterministic rules; the AI layer is thin. Test everything here first.

- [ ]  `check_eligibility(refill_request)` — evaluate ALL rules from FR-M3 and return a structured result (eligible, or a list of failure reasons): prescription active + unexpired, not discontinued, refill due (not too early), required labs completed, no follow-up visit outstanding, refills remaining
- [ ]  On zero refills remaining → status flows to "new prescription needed", routed to the physician as a renewal, not a refill (FR-M4, PRD Edge Case 1)
- [ ]  On any failure → `paused` with reason; patient notified (PRD Edge Case 2)
- [ ]  Controlled substance → immediate human escalation via the Triage `EscalationAlert` pattern, no automated path
- [ ]  `build_renewal_summary(refill_request)` — assemble the physician-facing data (FR-M5): medication + dose, last prescribed date, remaining refills, recent relevant labs, allergies, adverse events, adherence (compute adherence naively from refill timing history)
- [ ]  `approve(request, doctor)` / `reject(...)` / `request_visit(...)` — approval writes back: new prescription row, approval date, prescriber, refill count (FR-M7); `request_visit` emits an event Scheduling listens to
- [ ]  `send_to_pharmacy(request)` — stub e-prescription transmitter (log + status change) behind an interface; patient notification on ready-for-pickup (FR-M8)
- [ ]  Tests: each eligibility rule failing individually; zero-refills routing; controlled-substance escalation; approve → write-back → pharmacy-send chain. `pytest` green.

## Phase 3 — API layer

- [ ]  Patient endpoints: create refill request, get request status
- [ ]  Physician endpoints: list pending approvals (with renewal summaries), approve / reject / request-visit actions — one call each, so the UI can be one-click (FR-M6)
- [ ]  Manually run the full lifecycle via curl: request → eligibility → approval → pharmacy

## Phase 4 — AI integration

The AI's job here is only (a) understanding the patient's natural-language request and (b) writing a concise human-readable summary line for the physician.

- [ ]  Tool schema `extract_refill_intent` (`strict: true`): medication name (free text as stated), dose if mentioned, quantity, preferred pharmacy, `needs_clarification` (FR-M1)
- [ ]  `match_medication(extracted_name, patient)` — resolve the stated name against the patient's active prescriptions (the model states, your code matches; ask a clarifying question via chat when 0 or >1 match)
- [ ]  `summarize_for_physician(renewal_summary)` — one API call producing a 3–4 line plain-language summary from the Phase 2 structured data ("review in seconds", NFR-10)
- [ ]  Identity check before processing: reuse Registration's OTP verification if the session isn't already verified (FR-M2)
- [ ]  LangSmith tracing; `manage.py shell` testing
- [ ]  Test suite: common phrasings ("I need my blood pressure meds again", brand vs generic names, misspellings) resolve to the right prescription or a clarification — never a wrong-medication match

## Phase 5 — Frontend

- [ ]  Patient: refill request flows through the existing chat UI; status card (requested → checking → with your doctor → sent to pharmacy → ready)
- [ ]  Physician approval queue page (PRD Screens #4): list of pending renewals, each showing the AI summary + structured data, with three buttons — Approve / Reject / Request Visit — and no page navigation required
- [ ]  Manual end-to-end test: patient asks in chat → physician approves in queue → status card updates → admin shows the write-back

## Phase 6 — Integration + edge cases

- [ ]  Scheduling handoff (FR-S10): a refill intent detected inside a scheduling conversation routes here without restarting the conversation
- [ ]  `request_visit` outcome automatically offers booking via Agent 1
- [ ]  Red-flag safety: run triage's `red_flag_check` on refill conversations too (a patient describing chest pain while asking for refills must escalate)
- [ ]  Edge-case tests: PRD Edge Cases 1, 2, 12

## Phase 7 — Deploy

- [ ]  Migrate + deploy; smoke-test the request → approve → pharmacy flow live
- [ ]  Later swap-ins: a real e-prescription network (Surescripts-type) behind the transmitter interface; real pharmacy directory
