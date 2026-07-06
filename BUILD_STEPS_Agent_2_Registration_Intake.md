# BUILD_STEPS_Agent_2

# BUILD_STEPS — MediAssist AI: Patient Registration & Intake

Covers PRD → "Patient Registration & Intake" (FR-R1…FR-R10). This is the **foundational agent** — every other agent depends on a verified patient profile, so build it immediately after (or in parallel with) Scheduling.

**Prerequisites:** the repo, backend, Postgres, and frontend scaffolding from `BUILD_STEPS_Agent_1.md` (Phases 0–2, 8) already exist. Do NOT create a new repo or new Django project — every agent is a new Django *app* inside the same `backend/`.

Work top to bottom. Don't start the AI phase before the business logic is tested.

## Phase 0 — One-time refactor: extract shared models into `core`

Agent 1 put `Patient`, `Doctor`, `Conversation`, `Message` inside the `scheduling` app. Every agent from here on needs them, so move them once now — while you only have seed data and can afford to reset the dev database.

- [ ]  `python manage.py startapp core`; add `'core'` to `INSTALLED_APPS`
- [ ]  Move `Patient`, `Doctor`, `Conversation`, `Message` model classes from `scheduling/models.py` into `core/models.py` (leave `Appointment`, `Waitlist` in `scheduling`; update its imports to `from core.models import ...`)
- [ ]  Since this is pre-production: stop the server, drop and recreate the dev database (`docker rm -f mediassist-db` then re-run the `docker run` from Agent 1), delete all files in `scheduling/migrations/` except `__init__.py`
- [ ]  `python manage.py makemigrations core scheduling && python manage.py migrate`
- [ ]  Re-run `seed_doctors`, recreate your superuser, and re-run the Agent 1 test suite (`pytest`) — everything must be green before continuing
- [ ]  Commit: `"Extract shared models into core app"`

## Phase 1 — Data models

- [ ]  `python manage.py startapp registration`; add to `INSTALLED_APPS`
- [ ]  Extend `core.Patient` with registration fields: emergency contact, preferred language, preferred pharmacy, `identity_verified` (bool), `registration_status` (`in_progress` / `verified` / `duplicate_detected` / `complete`)
- [ ]  In `registration/models.py` define: `InsurancePolicy` (provider, policy number, member ID, coverage dates, eligibility status, FK → Patient), `IntakeSummary` (structured JSON: symptoms, history, medications, allergies, family history, lifestyle; FK → Patient), `UploadedDocument` (file, doc type enum — insurance card / ID / prescription / lab report / referral letter / imaging, OCR-extracted JSON, FK → Patient), `OTPChallenge` (code hash, channel, expires_at, attempts, FK → Patient)
- [ ]  `makemigrations registration && migrate`; register all models in `registration/admin.py`; confirm in `/admin/`

## Phase 2 — Core business logic (no AI yet)

Create `registration/services.py` and test everything with hardcoded inputs first.

- [ ]  `find_matching_patients(name, dob, phone)` — duplicate search returning `existing` / `new` / `possible_duplicate` (FR-R3). Match on normalized phone + DOB, then fuzzy name
- [ ]  `create_otp(patient, channel)` and `verify_otp(patient, code)` — 6-digit code, 10-minute expiry, max 5 attempts. In dev, "send" = print to console / store in a `SentNotification` log table (a real SMS provider is a Phase 7 swap-in)
- [ ]  `verify_insurance_eligibility(policy)` — **stub payer API**: a function that returns active/inactive based on a test fixture (real payer APIs are unspecified in the PRD — see its Assumptions). Design it as an interface so it can be swapped later
- [ ]  `create_or_update_patient_record(...)` — writes demographics + insurance + intake to the DB; this is your stand-in for the FHIR write-back (see `ORCHESTRATION.md` → EHR layer)
- [ ]  `complete_registration(patient)` — flips status to `complete` and emits a `registration.completed` event (see `ORCHESTRATION.md` → Event dispatch) so downstream agents can trigger (FR-R9)
- [ ]  Tests in `registration/tests/test_services.py`: duplicate detection (exact, fuzzy, no-match), OTP expiry + max attempts, inactive insurance flagged, event emitted on completion. `pytest` green before Phase 3.

## Phase 3 — API layer

- [ ]  Serializers + views: start registration, submit demographics, request/verify OTP, upload document, submit insurance, get registration status
- [ ]  Wire `registration/urls.py` into `config/urls.py`
- [ ]  Manually exercise the whole flow with curl/Postman — a patient can be fully registered with zero AI involved

## Phase 4 — AI integration

- [ ]  System prompt constant: conversational intake assistant; collects demographics and medical history through adaptive questions; never gives medical advice; asks only one question at a time; only relevant follow-ups (FR-R1, FR-R5)
- [ ]  Tool schema `record_registration_data` (`strict: true`): captures whichever fields the patient just provided (all optional properties) plus `next_question_topic` and `registration_complete` flag — this makes the dynamic question flow model-driven but data capture structured
- [ ]  Tool schema `extract_document_data`: given an uploaded image/PDF, extract structured fields (insurance: provider, policy number, member ID, dates; lab report: test, date, findings, physician) — send the document as an image/document content block to `claude-opus-4-8` (FR-R4, FR-R6). This replaces a separate OCR service
- [ ]  `handle_registration_message(conversation_history)` — orchestration: call the API with `tool_choice` forced to `record_registration_data`, persist extracted fields via Phase 2 services, decide next step (OTP? insurance? intake questions? done)
- [ ]  `generate_intake_summary(patient)` — one API call that turns the collected intake into the structured summary JSON + a short physician-readable paragraph (FR-R7)
- [ ]  Wrap calls with LangSmith tracing, same as Agent 1
- [ ]  Test suites: (a) a scripted happy-path conversation ends with a complete, verified record; (b) fixture insurance-card images extract the right policy number; (c) a returning patient's details route to `existing`, not a duplicate record
- [ ]  Manual `manage.py shell` testing before any HTTP

## Phase 5 — Chat endpoint + frontend

- [ ]  Add a `/api/registration/chat/` streaming SSE view (same pattern as Agent 1 Phase 7)
- [ ]  Frontend: reuse the `ChatWindow` component; add a file-upload button inside the conversation (insurance card / ID) that POSTs to the upload endpoint and drops a confirmation message into the chat
- [ ]  Add an OTP input component (6 boxes) that appears when the backend requests verification
- [ ]  Registration progress indicator (demographics → identity → insurance → medical intake → done)
- [ ]  End-to-end manual test in the browser: register a brand-new patient start to finish, then check `/admin/` for the Patient, InsurancePolicy, and IntakeSummary rows

## Phase 6 — Integration + edge cases

- [ ]  Wire the `registration.completed` event to Scheduling: after registration with reported symptoms, the conversation hands off to the scheduling/triage flow without re-asking identity (PRD "User Journey" step 4–5)
- [ ]  Edge-case tests (PRD Edge Cases 3, 4): inactive insurance → patient notified immediately, registration continues but flagged; duplicate detected → existing record used, no second row created
- [ ]  Analytics endpoint (FR-R10): counts + averages (registration time, completion rate, verification success, duplicates prevented) — a simple aggregate query view is enough for now

## Phase 7 — Deploy

- [ ]  Run migrations against the deployed DB, deploy backend + frontend as in Agent 1 Phase 11
- [ ]  Smoke-test full registration on the live URL
- [ ]  Optional swap-ins when ready: Twilio (SMS OTP), SendGrid (email), a real eligibility clearinghouse behind the `verify_insurance_eligibility` interface
