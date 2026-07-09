# Registration & Intake Agent (Agent 2)

The registration agent turns a chat conversation into a complete, verified
patient record: demographics, a verified identity (OTP), insurance with an
eligibility check, and a medical intake a physician can read in ten seconds.
It is the **foundational agent** — every other agent depends on the patient
record it creates.

Spec: `specifications/SPEC_Agent_2_Registration_Intake.md`
Build plan: `steps/BUILD_STEPS_Agent_2_Registration_Intake.md`
New to the code? Start with `ai/HANDLER_EXPLAINED.md` — a beginner-friendly,
from-zero walkthrough of the conversation handler.

---

## The big picture

```
patient chats ──▶ POST /api/registration/chat  (SSE stream)
                        │
                        ▼
        handle_registration_message()          ← the brain (registration/ai/handler.py)
        1. model extracts fields (strict tool)
        2. fields persisted via services.py
        3. STATE GATE decides the stage:

   demographics ─▶ identity (OTP) ─▶ insurance ─▶ medical intake ─▶ done
        │                                                            │
   duplicate check (FR-R3)                            complete_registration()
   never auto-creates a                               emits "registration.completed"
   possible duplicate                                 → scheduling offers a booking
```

Two rules drive the design:

1. **Model-driven, state-gated.** The AI decides *what to ask next*; the
   code decides *which stage the registration is in*. The model can never
   skip identity verification, no matter what it (or the patient) says.
2. **All writes go through `services.py`.** The AI layer never touches the
   database directly. Every write is audited (`AuditEvent`) and testable
   without any AI.

---

## Folder map

| File | What lives there |
|---|---|
| `models.py` | `InsurancePolicy`, `IntakeSummary`, `UploadedDocument` |
| `services.py` | All business logic (no AI): duplicate detection, OTP, eligibility, record writes, completion |
| `eligibility.py` | `PayerEligibilityGateway` interface + `StubGateway` (fake payer for dev) |
| `views.py` | HTTP endpoints (flow endpoints + chat + analytics + generic CRUD) |
| `urls.py` | Routes (mounted under `/api/`) |
| `ai/prompts.py` | `REGISTRATION_SYSTEM_PROMPT` — the assistant's standing instructions |
| `ai/tools.py` | Strict tool schemas: `record_registration_data`, `extract_document_data`, `generate_intake_summary` |
| `ai/handler.py` | `handle_registration_message()` — one conversation turn + the state gate |
| `ai/extract.py` | Document OCR-replacement: sends image/PDF to the model, saves `extracted_data` |
| `ai/summary.py` | `generate_intake_summary()` — physician paragraph + cleaned profile (FR-R7) |
| `tests/` | 76 tests across services, API, chat, AI handler/tools/summary |

Shared pieces this agent relies on (in `core/`): `Patient`, `Conversation`,
`Message`, `OTPChallenge`, `SentNotification`, `AuditEvent`, `EventLog`
models; `core.ai` (provider-agnostic AI door); `core.events` (dispatcher);
`core.notifications` (single outbound-message door).

---

## Data models

**`core.Patient`** (extended in Phase 1): demographics + `emergency_contact`,
`preferred_language`, `preferred_pharmacy`, `identity_verified` (bool),
`registration_status` (`in_process` / `verified` / `duplicate_detected` /
`complete`).

**`InsurancePolicy`**: provider, policy number, `member_id`, coverage dates,
`eligibility_status` (`unknown` / `eligible` / `ineligible`) + when it was
checked. One row per (patient, policy number) — resubmitting updates, never
duplicates.

**`IntakeSummary`**: `clinical_profile` (structured JSON: symptoms, history,
medications, allergies, family history, lifestyle) + `summary_text` (the
physician-readable paragraph).

**`UploadedDocument`**: the file, its type (insurance card / ID / prescription
/ lab report / referral letter / other), `extraction_status`
(pending / done / failed) and `extracted_data` (what the AI read off it).

**`core.OTPChallenge`**: SHA-256 hash of the code (never the code itself),
10-minute expiry, max 5 attempts, single-use.

---

## Business logic (`services.py`) — works with zero AI

| Function | What it does |
|---|---|
| `find_matching_patients(name, dob, phone)` | Duplicate check. Returns `("existing", [...])` for same phone+DOB, `("possible_duplicate", [...])` for same DOB + similar last name (staff must resolve — never auto-created), or `("new", [])`. Phone formats are normalized before comparing. |
| `create_otp(patient, channel)` / `verify_otp(patient, code)` | 6-digit code, hashed at rest, 10-min expiry, 5 attempts, single-use. New code cancels old ones. In dev, "sending" prints to console + logs a `SentNotification` row. Success sets `identity_verified=True`. |
| `verify_insurance_eligibility(policy, gateway=None)` | Asks the payer gateway for a verdict and stamps it on the policy. Dev uses `StubGateway` (any policy number is eligible; `INACTIVE-001` / `EXPIRED-2024` are not). An inactive policy is **flagged, not rejected** — registration continues (PRD Edge Case 3). Swap in a real clearinghouse via `eligibility.default_gateway()`. |
| `create_or_update_patient_record(patient=None, demographics=, insurance=, intake=)` | The stand-in for the FHIR write-back. One transaction, every write leaves an `AuditEvent`. A whitelist means chat-extracted data can never set `identity_verified` or `registration_status`. |
| `complete_registration(patient)` | Flips status to `complete` and emits `registration.completed` through `core.events` — scheduling reacts by inviting the patient to book. |

---

## API endpoints

All flow endpoints except `start` require the session token from `start`
in an `X-Session-Token` header. The token is the conversation id, signed —
it can't be forged or tampered with.

| Method | Path | Body → Result |
|---|---|---|
| POST | `/api/registration/start` | `{channel}` → `201 {session_token, conversation_id}` |
| POST | `/api/registration/chat` | `{message}` → **SSE stream**: `{"delta": "..."}` events, then `{"done": true, stage, ui_hints, patient_id, registration_complete}` |
| POST | `/api/registration/demographics` | demographics → `201 {patient_id, match: "new"}`, `200 (match: "existing")`, or `409` on a possible duplicate (nothing created) |
| POST | `/api/registration/otp/request` | `{channel}` → `202` (code printed to console in dev) |
| POST | `/api/registration/otp/verify` | `{code}` → `{verified: true}` or `400 {code: otp_expired \| otp_invalid \| otp_too_many_attempts \| otp_missing}` |
| POST | `/api/registration/documents` | multipart `{file, doc_type}` → `201 {id, extraction_status}` |
| POST | `/api/registration/insurance` | policy fields → `201 {policy_id, eligibility_status, flagged}` |
| GET | `/api/registration/status` | → `{registration_status, missing: ["identity", "insurance", "intake"]}` |
| POST | `/api/registration/complete` | → `200` or `400 {missing: [...]}` if steps remain |
| GET | `/api/staff/registration/analytics` | staff login required → FR-R10 aggregates (completion rate, OTP success, duplicates prevented, ...) |

Generic CRUD (dev/admin convenience): `/api/insurancepolicy`,
`/api/intakesummary`, `/api/uploadeddocument` (+ `/<id>`).

### Quick manual test with curl

```bash
# 1. start a session
curl -X POST localhost:8001/api/registration/start \
  -H "Content-Type: application/json" -d '{"channel":"web"}'
# → grab session_token, use it below as $TOKEN

# 2. chat (SSE)
curl -N -X POST localhost:8001/api/registration/chat \
  -H "Content-Type: application/json" -H "X-Session-Token: $TOKEN" \
  -d '{"message": "Hi, I want to register. My name is Priya Patel."}'
```

---

## The AI layer

**System prompt** (`ai/prompts.py`): conversational intake assistant — one
question per message, only relevant follow-ups, respond in the patient's
language, never give medical advice, stop and direct to emergency care on
red-flag symptoms. Volatile context stays out of the prompt (prompt-caching
friendly).

**Three strict tools** (`ai/tools.py`) — `strict: true` means the model's
output is guaranteed to match the schema:

- `record_registration_data` — every data field optional (record whatever
  the patient just said); `next_question_topic` (closed enum) and
  `registration_complete` always required. This is what makes the question
  flow dynamic but the data capture structured.
- `extract_document_data` — insurance card fields (provider, policy number,
  member ID, dates) and lab report fields (test, date, findings, physician),
  plus `legible: false` for unreadable uploads. Replaces a separate OCR
  service; the file goes to the model as an image/document content block.
- `generate_intake_summary` — cleaned `clinical_profile` JSON + a 3–6
  sentence physician paragraph. No diagnosis, ever.

**The handler** (`ai/handler.py`) runs one turn: extract → persist via
services → state gate. Stages, in order: `demographics` → `duplicate_hold`
(if a lookalike record needs staff review) → `identity_verification`
(ui hint `otp_required`) → `insurance` (ui hint `{"upload": "insurance_card"}`)
→ `intake` → `done`. Intake answers accumulate turn by turn in
`conversation.agent_context` and are written to the DB at completion. On
`done`, the conversation is handed to scheduling (`active_agent` switches,
symptoms travel along) so booking starts without re-asking identity.

**Tracing:** every AI call is traced to LangSmith. Provider calls are `llm`
runs; `handle_registration_message`, `extract_document_data`, and
`generate_intake_summary` are named `chain` spans, so each turn reads as one
nested trace. Tests disable tracing automatically.

**Provider:** all calls go through `core.ai` (`AI_PROVIDER` in `.env`:
`openai` / `anthropic` / `ollama`). One exception: document extraction is
vision, built with Anthropic-format content blocks — it needs
`AI_PROVIDER=anthropic` and an `ANTHROPIC_API_KEY`.

---

## Events, notifications, audit

- `registration.completed` is emitted via `core.events.emit()` — one durable
  `EventLog` row plus every subscriber runs. Current subscriber: scheduling
  sends the patient a "you can now book an appointment" message through
  `core.notifications.notify()` (opt-outs enforced globally there).
- Every record write, OTP event, and completion leaves an `AuditEvent` row —
  who did what, when, to which patient.

---

## Configuration (`.env`)

| Variable | Purpose |
|---|---|
| `AI_PROVIDER` | `openai` (current) / `anthropic` / `ollama` |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | provider credentials (Anthropic needed for document vision) |
| `LANGSMITH_API_KEY`, `LANGSMITH_TRACING` | tracing |
| `DB_*`, `DATABASE_NAME` | Postgres connection |

`MEDIA_ROOT` is `backend/media/` — uploaded documents land there in dev
(git-ignored).

---

## Running & testing

```bash
cd backend
python manage.py runserver          # admin at /admin/, API at /api/...
python -m pytest                    # 76 tests, no AI/network needed
```

The scripted end-to-end conversation with **real** model calls (Phase 4's
manual shell test) lives in the session scratchpad pattern: create a
`Conversation`, feed `handle_registration_message` scripted messages, and
watch the stages advance. It verified the full happy path 14/14, including a
generated physician summary.

---

## Status

| Phase | State |
|---|---|
| 0–2 Models + business logic | ✅ done, tested |
| 3 API layer | ✅ done, tested (incl. live curl) |
| 4 AI integration | ✅ done — one item open: the insurance-card image extraction test needs an `ANTHROPIC_API_KEY` |
| 5 Chat endpoint | ✅ backend done (SSE, live-tested). Frontend (ChatWindow, OTP boxes, upload button, progress bar) not started |
| 6 Integration + analytics | ✅ done (event wiring, edge cases, analytics endpoint) |
| 7 Deploy | ⬜ not started |

Known dev-mode stand-ins to swap later: console OTP "sending" (→ Twilio/
SendGrid), `StubGateway` (→ real eligibility clearinghouse), local media
folder (→ storage bucket).

---
---

# Build journal — every step, in order

This section records exactly what was done in each phase, why, and what
went wrong along the way. Follow it top to bottom and you can rebuild (or
review) the whole agent.

## Phase 0 — Extract shared models into `core`

Agent 1 (scheduling) originally owned `Patient`, `Doctor`, `Conversation`,
and `Message`. Every agent needs them, so they were moved once, early:

- Created the `core` app and moved those four model classes into
  `core/models.py`; `scheduling` keeps only `Appointment` and `Waitlist`
  and imports the rest with `from core.models import ...`.
- Because this was pre-production, the dev database was reset and
  migrations regenerated instead of writing careful data migrations.
- `core` also gained the shared infrastructure the whole system uses:
  `OTPChallenge`, `SentNotification`, `AuditEvent`, `EventLog` models,
  the `core.ai` provider door, `core.events` dispatcher, and
  `core.notifications`.

**Bug fixed here:** both new admin files imported
`from django.contrib import django_admin` — a name that doesn't exist
(it was copied from scheduling's `import admin as django_admin` without
the `as` part). The whole project failed to start until the imports were
corrected. `scheduling/admin.py` was also registering the four core
models a second time, which Django refuses (`AlreadyRegistered`) — it now
registers only its own two models.

## Phase 1 — Registration data models

- Created the `registration` app, added to `INSTALLED_APPS`.
- Extended `core.Patient` with: `emergency_contact`, `preferred_language`,
  `preferred_pharmacy`, `identity_verified` (bool, default False), and
  `registration_status` (choices: `in_process` / `verified` /
  `duplicate_detected` / `complete`).
- Created three models in `registration/models.py`:
  - `InsurancePolicy` — provider, policy number, **`member_id`** (added
    after review: the spec lists it), coverage dates, eligibility status
    + checked-at timestamp, raw extraction JSON.
  - `IntakeSummary` — `clinical_profile` JSON + `summary_text` paragraph.
  - `UploadedDocument` — file, document-type enum, `extraction_status`,
    and **`extracted_data`** JSON (added after review: without it the AI
    would have had nowhere to store what it read off a card).
- `OTPChallenge` lives in `core` rather than `registration` (fine — other
  agents reuse identity verification).
- Registered everything in the admin and confirmed at `/admin/`.

Migrations of note: `registration/0001_initial`,
`core/0003_patient_identity_verified`,
`registration/0002` (member_id + extracted_data).

**Django tip learned here:** never write `id = models.AutoField(...)`
manually — Django creates the primary key automatically (the registration
models get `BigAutoField`; the older core models declare `AutoField`
explicitly, which is harmless but unnecessary).

## Phase 2 — Business logic (`services.py`), no AI

Built and tested with hardcoded inputs before any AI existed:

1. **`normalize_phone`** — strips formatting, keeps the last 10 digits, so
   `+91 98765-43210` and `9876543210` compare equal.
2. **`find_matching_patients(name, dob, phone)`** — the FR-R3 duplicate
   check. Same DOB + same normalized phone = `existing` (same person).
   Same DOB + fuzzy-similar last name (difflib ratio ≥ 0.8) but different
   phone = `possible_duplicate` — returned to a human, never auto-created.
   Anything else = `new`. DOB is the anchor: a shared family phone alone
   is not a match.
3. **`create_otp` / `verify_otp`** — 6-digit code from `secrets`, stored
   only as a SHA-256 hash, 10-minute expiry, 5 attempts max, single-use;
   a new code cancels older unused ones. Dev "sending" = console print +
   `SentNotification` row (which doubles as the way tests recover the
   plaintext code).
4. **`verify_insurance_eligibility`** — delegates to a
   `PayerEligibilityGateway` (interface in `eligibility.py`). Dev ships
   `StubGateway` (fixture table; unknown policy numbers default to
   eligible so dev flows work; `INACTIVE-001` triggers the flagged path).
   Swapping in a real clearinghouse later = one new subclass + one line
   in `default_gateway()`.
5. **`create_or_update_patient_record`** — the FHIR-write-back stand-in.
   One transaction; every write leaves an `AuditEvent`; insurance is
   keyed on (patient, policy number) so resubmits update instead of
   duplicating; a field **whitelist** guarantees chat-extracted data can
   never flip `identity_verified` or `registration_status`.
6. **`complete_registration`** — status flip + `registration.completed`
   event (later upgraded to emit through `core.events`, see Phase 6).

Tests: `tests/test_services.py` (duplicates exact/fuzzy/none, OTP expiry/
attempts/single-use, eligibility incl. a custom injected gateway proving
the swap works, record writes, completion event).

**Environment fix:** pytest could not create its throwaway test database
because the `mediassist_admin` Postgres user lacked permission. Fixed
once with `ALTER USER mediassist_admin CREATEDB;`.

## Phase 3 — API layer

**Refactor first:** generic CRUD for the shared models (Patient, Doctor,
Conversation, Message) had been copy-pasted from scheduling into
registration. Instead, all of it moved to `core` (serializers, views,
`base_crud_views.py`, urls) — same URLs, one implementation, and agent
apps now only own their flow endpoints.

**Session design:** `POST /api/registration/start` creates a
`Conversation` (its `patient` field was made nullable — migration
`core/0004` — because a registration conversation starts before anyone
knows who is talking) and returns a **signed token** (`django.core.signing`,
salted) containing the conversation id. No session table needed; tokens
can't be forged. All other flow endpoints inherit from
`RegistrationSessionAPIView`, which verifies the token in an
`X-Session-Token` header before any endpoint code runs.

**Flow endpoints built** (each a thin wrapper over Phase 2 services):
demographics (runs duplicate detection; 409 + nothing created on a
lookalike), otp/request, otp/verify (maps service reasons to the spec's
error codes), documents (multipart upload; `MEDIA_ROOT=backend/media/`
added to settings and git-ignored), insurance (writes policy + runs
eligibility; inactive = `flagged: true` but still 201), status (what's
missing), complete (refuses with the missing list until everything's
done).

Tests: `tests/test_api.py`, including one end-to-end test that registers
a patient entirely over HTTP with zero AI — the Phase 3 exit condition.

## Phase 4 — AI integration

Follows Agent 1's layout: an `ai/` package with prompts, tools, handler.
All calls go through `core.ai.call_tool` (provider chosen by
`AI_PROVIDER`; dev used `openai`/`gpt-4.1-mini`).

1. **`REGISTRATION_SYSTEM_PROMPT`** (`ai/prompts.py`) — one question per
   message, adaptive follow-ups only, patient's language, hard rules: no
   medical advice, no diagnosis, emergencies → stop and direct to
   emergency care. No volatile data in the prompt (cache-friendly).
2. **`record_registration_data`** (`ai/tools.py`, strict) — all data
   fields optional; `next_question_topic` (closed enum) +
   `registration_complete` always required. Built with the project's
   `core.ai.strict_tool()` helper.
3. **`extract_document_data`** (strict) — insurance-card and lab-report
   fields per the spec + a `legible: false` escape hatch. `ai/extract.py`
   sends the file as a base64 image/document content block (Anthropic
   format — needs `AI_PROVIDER=anthropic`) and
   `run_document_extraction()` persists into `extracted_data` /
   `extraction_status`. This replaces a separate OCR service.
   *Supporting fix in `core/ai`*: the Anthropic client used to strip the
   `strict` flag; it now passes it through (Claude supports strict tools
   natively), so tool inputs are guaranteed schema-valid.
4. **`handle_registration_message(conversation, history)`**
   (`ai/handler.py`) — one turn: extract → persist via services → state
   gate. Partial demographics accumulate in `conversation.agent_context`
   until the duplicate check can run; intake answers accumulate (deduped)
   and are written at completion; the gate order is demographics →
   duplicate_hold → identity_verification → insurance → intake → done.
5. **`generate_intake_summary(patient)`** (`ai/summary.py`) — one API
   call: raw intake + patient age in, normalized `clinical_profile` +
   3–6 sentence physician paragraph out, saved onto the latest
   `IntakeSummary` row.
6. **LangSmith tracing** — provider calls were already `@traceable`
   (`run_type="llm"`); the three registration operations got named
   `chain` spans so traces nest per turn. Tests set
   `LANGSMITH_TRACING=false` (autouse fixture) so test runs don't pollute
   the real project.
7. **Manual `manage.py shell` test with real model calls** — a scripted
   7-turn conversation (Meera Iyer) ran the entire happy path: 14/14
   checks passed, ending with a real generated physician paragraph.
   **Bug found by this test:** after `verify_otp` updated the database,
   the handler kept trusting a stale in-memory `conversation.patient`
   and stayed stuck at the OTP gate. Fix: the handler refreshes the
   patient from the DB at the start of every turn (+ regression test).

Still open in Phase 4: the fixture insurance-card image extraction test —
blocked until an `ANTHROPIC_API_KEY` is added to `.env`.

## Phase 5 — Chat endpoint (backend)

`POST /api/registration/chat` (`RegistrationChatAPIView`): session-token
protected; saves the patient `Message`; rebuilds history from the DB;
runs `handle_registration_message`; then makes a second model call
(`core.ai.stream_reply`) to write the patient-visible reply, streamed as
SSE `{"delta": ...}` events. A per-stage instruction
(`STAGE_REPLY_GUIDANCE`) tells the model what its next message must do,
so the visible reply always matches the state gate. The final SSE event
carries `{done, stage, ui_hints, patient_id, registration_complete}` —
the frontend uses `ui_hints` to show the OTP boxes
(`"otp_required"`) or the upload button (`{"upload": "insurance_card"}`).
The assistant reply is persisted as a `Message` row.

A leftover `ChatAPIView` copied from scheduling (unreachable due to a URL
collision, and calling the wrong agent's AI) was deleted.

Verified live against the running dev server with a real SSE request.
Frontend pieces (ChatWindow reuse, file-upload button, 6-box OTP input,
progress indicator) are not built yet.

## Phase 6 — Integration, edge cases, analytics

- **Event wiring:** `complete_registration` now emits through
  `core.events.emit()` (durable `EventLog` row + subscribers run).
  `scheduling/apps.py` subscribes to `registration.completed` and sends
  the patient a "you can now book an appointment" notification through
  `core.notifications` (template `registration_complete`; opt-outs
  enforced globally there). The chat handler also hands the conversation
  off on completion: `agent_context.active_agent` flips to `"scheduling"`
  and the reported symptoms travel in `agent_context.handoff`, so booking
  can start without re-asking identity.
- **Edge cases** (PRD 3 & 4): inactive insurance → patient flagged,
  registration continues; duplicate detected → existing record reused /
  held for staff, never a second row. Both covered by tests since
  Phases 2–3.
- **Analytics (FR-R10):** `GET /api/staff/registration/analytics`
  (staff-only): patient totals + completion rate, OTP challenges +
  verification success rate, duplicates prevented (conversations holding
  `duplicate_candidate_ids`), insurance flags, document extraction counts.

## Phase 7 — Deploy

Not started. When it happens: run migrations against the deployed DB,
deploy backend + frontend as in Agent 1 Phase 11, smoke-test the full
registration on the live URL, and swap the dev stand-ins (Twilio/SendGrid
for OTP sending, a real eligibility gateway, a storage bucket for
uploads).

## Bugs found and fixed along the way (summary)

| Bug | Where | Fix |
|---|---|---|
| `from django.contrib import django_admin` (nonexistent name) crashed startup | `core/admin.py`, `registration/admin.py` | plain `from django.contrib import admin` |
| Core models registered in admin twice (`AlreadyRegistered`) | `scheduling/admin.py` | scheduling registers only Appointment + Waitlist |
| Test DB couldn't be created (`InsufficientPrivilege`) | Postgres | `ALTER USER mediassist_admin CREATEDB;` |
| Copy-pasted serializers/views duplicated across apps | `registration/` | shared CRUD moved to `core`, agents keep flow endpoints |
| `/api/chat` URL collision made registration's chat unreachable (and it called scheduling's AI) | `registration/urls.py` | dead view deleted; real chat lives at `/api/registration/chat` |
| Handler trusted a stale in-memory patient → stuck at OTP gate forever | `registration/ai/handler.py` | `patient.refresh_from_db()` every turn (found by the live shell test) |
| Anthropic client stripped the `strict` flag from tools | `core/ai/anthropic_client.py` | pass it through — Claude enforces the schema natively |
| Test runs exported traces to the real LangSmith project | `tests/conftest.py` | autouse fixture disables tracing in tests |
