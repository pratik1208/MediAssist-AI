# BUILD_STEPS_Agent_5

# BUILD_STEPS — MediAssist AI: Referral Execution

Covers PRD → "Referral Execution" (FR-F1…FR-F10). A long-running *workflow* agent: unlike chat agents, most of its work happens over days via status transitions and scheduled checks.

**Prerequisites:** Agents 1–2 (books specialist appointments through Scheduling; needs patient records). Agent 3 recommended (triage can originate referrals).

## Phase 1 — Data models

- [ ]  `python manage.py startapp referrals`; add to `INSTALLED_APPS`
- [ ]  Models: `Specialist` (name, specialty, practice/hospital, address + lat/long or postcode, accepted insurances M2M/JSON, languages, accepting_new_patients bool, contact channel — phone / e-referral / email / API, consultation fee nullable), `Referral` (FK → Patient, referring Doctor, Specialist nullable until matched; specialty needed; reason; urgency; status enum exactly per FR-F7 — `created` / `accepted` / `appointment_scheduled` / `patient_confirmed` / `visit_completed` / `report_received` / `closed`, plus `stalled`; created_at, each status timestamp), `ReferralPackage` (FK → Referral; selected chart data JSON, AI summary text, attached document refs), `ConsultationReport` (FK → Referral; diagnosis, treatment plan, medications, follow-up recommendations, raw document)
- [ ]  `makemigrations && migrate`; admin; `seed_specialists` command (8–10 fake specialists across specialties/insurances/locations)

## Phase 2 — Core business logic (no AI yet)

`referrals/services.py`:

- [ ]  `create_referral(doctor, patient, specialty, reason, urgency)` — the one-click entry point (FR-F1); status `created`, emits `referral.created`
- [ ]  `match_specialists(referral, patient)` — filter + rank by: accepting patients, insurance match, specialty, distance, patient language/preference (FR-F3, FR-F5). Pure queryset logic — fully testable
- [ ]  `required_documents_for(specialty)` — a config mapping (cardiology → ECG/echo/blood reports; orthopedics → imaging/surgery notes) used to attach documents to the package (FR-F4)
- [ ]  `book_specialist_visit(referral, slot)` — reuse Agent 1's booking service against the specialist's calendar (model specialist availability the same way as `Doctor` working hours, or make `Specialist` wrap a `Doctor` row)
- [ ]  Status machine: explicit `advance_status(referral, new_status)` with allowed-transition validation and timestamps
- [ ]  `check_stalled_referrals()` — anything incomplete past a configurable threshold (default 14 days) → alert care coordinators (FR-F9). Run via a management command now, a scheduled job in Phase 7
- [ ]  `handle_missed_appointment(referral)` — reminders → offer reschedule → notify referring physician if no action (FR-F8)
- [ ]  `close_loop(referral, report)` — import `ConsultationReport`, notify referring physician, status `closed` (FR-F10)
- [ ]  Tests: matching filters (insurance mismatch excluded, nearest ranked first), every legal/illegal status transition, stalled detection at the boundary, missed-appointment chain. `pytest` green.

## Phase 3 — API layer

- [ ]  Physician: create referral; care coordinator: list referrals with status + stalled flags; patient: my-referral status; specialist-side (simulated): accept referral, upload consultation report
- [ ]  Drive a full lifecycle via curl from `created` to `closed`

## Phase 4 — AI integration

- [ ]  `build_referral_package(referral)` — one API call: given the patient's chart data (as structured context) and the target specialty, select ONLY the specialty-relevant items and write a concise referral summary (FR-F2). Use a `strict: true` tool schema `select_referral_content` (list of selected item IDs + summary text) so your code controls what's actually attached — the model chooses, your code copies
- [ ]  Test: for a cardiology referral of a fixture patient with mixed history, the package contains BP/ECG/lipids/meds and excludes the unrelated dermatology note
- [ ]  `parse_consultation_report(document)` — extract diagnosis / treatment plan / medications / follow-ups from an uploaded report (document content block → structured tool output), feeding `close_loop`
- [ ]  Specialist-office outreach (FR-F3 automated calls/emails): implement as an outbound task queue with templated messages first; a voice agent is a later enhancement — record this in the doc as a deliberate simplification
- [ ]  LangSmith tracing; shell testing

## Phase 5 — Frontend

- [ ]  Physician: "Create Referral" button on the provider dashboard → small form (specialty, reason, urgency) → done (one click + minimal input, FR-F1)
- [ ]  Referral status dashboard (PRD Screens #5): pipeline view by status, stalled referrals highlighted, per-referral timeline of status timestamps
- [ ]  Patient: referral card in the portal — specialist, appointment, directions/prep instructions, status
- [ ]  Manual E2E: create referral → match → book → simulate visit + report upload → loop closed, physician notified

## Phase 6 — Integration + edge cases

- [ ]  Triage handoff: `disposition = specialist` creates a draft referral for physician confirmation
- [ ]  Booking + reminders go through Agent 1's confirmation/reminder pipeline (don't rebuild notifications)
- [ ]  Prior Auth hook (forward-compatible): when a referral's procedure needs authorization, emit `priorauth.needed` — Agent 6 will consume it
- [ ]  Edge-case tests: PRD Edge Cases 7 (missed appointment chain) and 8 (stalled alert)

## Phase 7 — Deploy

- [ ]  Migrate + deploy; seed specialists in production
- [ ]  Schedule `check_stalled_referrals` daily (Railway/Render cron, or django-crontab)
- [ ]  Smoke-test one full referral lifecycle live
