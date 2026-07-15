# How a Patient Chat Works — from UI click to database row

This traces the complete journey of a patient chatting through the UI: which API gets
hit, which backend function runs, which AI calls happen, and exactly which database
tables get written at every step. The deep-dive uses the **registration chat** (the flow
you just tested end-to-end); the other three chat surfaces are summarized at the end,
because they all reuse the same skeleton.

---

## 1. The big picture — five layers

```
┌─────────────────────────────────────────────────────────────────────────┐
│ 1. REACT PAGE          frontend/src/pages/RegistrationChatPage.tsx      │
│    what the patient sees: bubbles, OTP boxes, upload button              │
└───────────────┬─────────────────────────────────────────────────────────┘
                │ fetch() with X-Session-Token header   (lib/registrationApi.ts)
┌───────────────▼─────────────────────────────────────────────────────────┐
│ 2. API VIEW            backend/registration/views.py                    │
│    validates the session token, saves chat messages, streams the reply  │
└───────────────┬─────────────────────────────────────────────────────────┘
                │ one call per turn
┌───────────────▼─────────────────────────────────────────────────────────┐
│ 3. AI HANDLER          backend/registration/ai/handler.py               │
│    2 model calls per turn: EXTRACT data (strict tool), then WRITE reply │
│    …but CODE decides the stage, never the model ("model states,          │
│    code decides")                                                        │
└───────────────┬─────────────────────────────────────────────────────────┘
                │ only place that writes patient data
┌───────────────▼─────────────────────────────────────────────────────────┐
│ 4. SERVICES            backend/registration/services.py                 │
│    create_or_update_patient_record, create_otp, verify_otp,             │
│    find_matching_patients, complete_registration                        │
└───────────────┬─────────────────────────────────────────────────────────┘
                │ Django ORM
┌───────────────▼─────────────────────────────────────────────────────────┐
│ 5. DATABASE (Postgres)  Conversation · Message · Patient · OTPChallenge │
│    SentNotification · UploadedDocument · InsurancePolicy ·              │
│    IntakeSummary · AuditEvent · EventLog                                │
└─────────────────────────────────────────────────────────────────────────┘
```

In dev, the browser only ever talks to `http://localhost:5173`; Vite's proxy
(`frontend/vite.config.ts`) forwards every `/api/*` request to Django on `:8001`.

---

## 2. Step 0 — opening the page: the session token

**UI:** `RegistrationChatPage` mounts → `useEffect` calls `startRegistration()`
(`lib/registrationApi.ts`).

**API:** `POST /api/registration/start` → `StartRegistrationAPIView`
(`registration/views.py`).

**What happens:**
1. A `Conversation` row is created (`patient=NULL` — nobody is identified yet;
   `agent_context={"active_agent": "registration", "registration_stage": "demographics"}`).
2. The conversation's id is cryptographically **signed** into a token:
   `signing.dumps({"conversation_id": N}, salt="registration.session")` (`core/sessions.py`).
3. The token goes back to the browser, which stores it in `sessionStorage`
   (key `mediassist.registration`) so a page refresh doesn't restart the chat.

From now on, **every** request carries this token in the `X-Session-Token` header.
`SessionTokenAPIView.initial()` (`core/sessions.py`) verifies the signature and loads
the conversation before any endpoint code runs — a bad/missing token is a 403, and a
token whose conversation was deleted also 403s (the UI now auto-recovers from that by
starting a fresh session).

**DB writes:** 1 row — `patient_conversation`.

---

## 3. Each chat turn — the heart of the flow

This section is illustrated with **your real registration conversation** (conversation
#103 in the database — the one that created patient #63, Gagadhar). Every quote below is
copied verbatim from the stored transcript, and every scratchpad snapshot is the actual
JSON saved on the conversation row.

**UI:** patient types, `send()` calls `streamRegistrationChat(token, message, onEvent)`.

**API:** `POST /api/registration/chat` `{message: "..."}` → `RegistrationChatAPIView.post`.

### 3a. Persist the patient's message
`Message.objects.create(conversation=…, role="Patient", content=text)` — the transcript
is durable **before** any AI runs. That's why the full 30-message conversation below
could be replayed from the database days later: every turn was saved first, thought
about second.

### 3b. Rebuild the history
All `Patient`/`Assistant` messages for this conversation, oldest first, become the model's
chat history. If a patient record already exists, `on_file_context()` prepends a system
note listing what's already on file ("name, date of birth, phone…") so the model never
re-asks for data that arrived through other endpoints (like the OTP verification you did
through the code boxes, which the chat itself never saw).

### 3c. AI call #1 — extraction (`handle_registration_message`, `registration/ai/handler.py`)
One **forced tool call** (`core/ai.py → call_tool`) using the strict
`record_registration_data` tool. The model returns structured fields only — it cannot
write to the database. Watch what it did with your actual answers:

| You typed | The extraction tool returned |
|---|---|
| `Gagadhar` | `first_name: "Gagadhar"` |
| `I don't remmber` → `70 to 75 inbetween` | `dob: "1948-01-01"` — it turned an age range into an approximate date |
| `pmarudwar.gmail.com` | nothing yet — the *reply* model asked "is it pmarudwar@gmail.com?", and only after your "Yes" did extraction record the corrected email |
| `I have sugar` | `medical_history: ["diabetes"]` — normalized the colloquialism |
| `Yes every day tablet` → `Metformin` | `medications: ["daily tablet for diabetes", "Metformin"]` — both turns accumulated |
| `I am allergey with milk based product` | `allergies: ["milk based product"]` — typo tolerated, meaning kept |

One honest quirk it also recorded: when the assistant asked *"do you have any
symptoms?"* and you answered just `Yes`, extraction stored the literal word —
your intake now reads `symptoms: ["yes", "fever", "headache"]`. Structured extraction
is only as clean as the turn it reads.

### 3d. Code processes what the model extracted (all in `handler.py`)

- **Demographics** accumulate in `conversation.agent_context["pending_demographics"]` —
  a scratchpad on the conversation row, **not** a Patient yet. After your first few
  turns, yours looked like this (real snapshot):

  ```json
  "pending_demographics": {
      "first_name": "Gagadhar",
      "dob": "1948-01-01",
      "contact_number": "8634567844",
      "email": "pmarudwar@gmail.com",
      "address": {"city": "Bengaluru"},
      "emergency_contact": {"name": "Premanand", "phone": "54532321333"},
      "preferred_language": "English",
      "preferred_pharmacy": "Any pharmacy having discount"
  }
  ```

  **This is why you couldn't find Gagadhar in the admin at first.** The rule was: no
  `Patient` row until the minimum (`first_name`, *`last_name`*, `dob`, `contact_number`)
  is present — and you never gave a last name, so all of the above sat in the scratchpad
  for 20 turns while the conversation happily moved on to intake questions. After the
  fix (last name now optional), your message *"I go by a single name — just Gagadhar"*
  triggered the threshold check, and code took over:
  1. `services.find_matching_patients("Gagadhar", 1948-01-01, "8634567844")` — duplicate
     check: nobody with that dob+phone → `"new"`.
  2. `services.create_or_update_patient_record(None, demographics=…)` → **`Patient` row
     #63 created**, scratchpad cleared, conversation linked. The audit trail recorded it:
     `AuditEvent #199 patient.created {fields: [address, contact_number, dob, email, …]}`.

- **Intake answers** accumulate in `agent_context["intake"]` and are *not* written to
  the database until completion. Your fever/headache, diabetes, Metformin, milk allergy
  and lifestyle answers all lived here, surviving the 20-turn wait and even the days
  between your sessions — because the scratchpad is saved on the conversation row after
  every turn.

- **Insurance dictated in chat**: your final message —
  *"Name: Gagadhar Insurance Provider: Star Health Insurance Policy Number: SH-12345"* —
  filled `pending_insurance` with both required keys in one turn, so the handler
  immediately wrote `InsurancePolicy` #28 and ran `verify_insurance_eligibility()`
  (→ `eligible`). Audit: `#202 insurance.recorded`.

### 3e. The state gate — code decides the stage, never the model
```python
patient is None                     → "demographics" (or "duplicate_hold")
not patient.identity_verified      → "identity_verification"  + ui_hint "otp_required"
no InsurancePolicy on file         → "insurance"  + ui_hint {"upload": "insurance_card"}
model didn't flag completion       → "intake"
else                               → "done": write IntakeSummary, complete_registration()
```

Your conversation walked through **every branch of this gate, in order**:

| Your turn | Gate input | Stage returned |
|---|---|---|
| `Gagadhar` … 20 turns | no Patient row (last name missing) | `demographics` — stuck |
| *"just Gagadhar, no last name"* | Patient #63 created, not verified | `identity_verification` + `otp_required` |
| *(OTP typed in the code boxes)* | verified, but no policy | `insurance` + upload hint |
| *"Star Health … SH-12345"* | policy #28 exists, model flags complete | `done` |

The gate is also why the conversation's most misleading moment was *harmless to the
data*: at message #256, when you asked *"Registration is done?"*, the model answered
**"Yes, your registration is complete"** — while the gate was still returning
`demographics` and no patient existed at all. The model can say wrong things; it cannot
*make* them true, because only the gate's verdict reaches the database and the UI's
progress strip.

### 3f. AI call #2 — the visible reply (`stream_reply`)
The view builds the reply prompt: system prompt + a **per-stage instruction**
(`STAGE_REPLY_GUIDANCE`) + — for every stage except `done` — a hard guard:
*"registration is NOT finished yet, never wrap up."*

Your transcript captures the before/after of that guard being added, at the exact same
point in the flow:

> **Before** (message #262, after OTP, stage was `insurance`):
> *"Thank you for confirming your verification code, Gagadhar. Your registration
> process is all set. Is there anything else I can assist you with today?"* — then a
> goodbye. Wrong: insurance was still pending.
>
> **After** (message #266, same stage, guard active — even against the wrap-up bait
> *"no, nothing else, thanks"*):
> *"Before we finish, could you please upload a photo of your insurance card or tell me
> your insurance provider name and policy number?"* — steered straight back to the gate's
> next step.

The reply streams to the browser as Server-Sent Events: each fragment is a
`data: {"delta": "…"}` line the UI renders live.

### 3g. Persist the reply + tell the UI where it is
`Message(role="Assistant")` is saved, then one final SSE event carries the machine state:
`{"done": true, "stage": …, "ui_hints": […], "registration_complete": …, "patient_id": …}`.
The React page uses this to move the progress strip, show the OTP boxes, or hint at the
upload button. On your final turn this event was
`{"stage": "done", "registration_complete": true, "patient_id": 63}` — which is what made
the 🎉 completion banner appear.

### 3h. Where your conversation ended up — the final state

After the last turn, the database held (all real rows):

- `Patient` #63 — Gagadhar, no last name, verified, `registration_status="complete"`
- `InsurancePolicy` #28 — Star Health Insurance, SH-12345, `eligible`
- `IntakeSummary` #23 — symptoms/history/meds/allergies/lifestyle from the scratchpad
- 30 `Message` rows — the full transcript quoted above
- Audit trail: `patient.created → patient.updated ×2 → insurance.recorded →
  intake.recorded → registration.completed`
- `EventLog`: one `registration.completed` event — and the conversation's scratchpad now
  reads `{"active_agent": "scheduling", "handoff": {"from": "registration",
  "symptoms": ["yes", "fever", "headache"]}}`: registration has handed your session to
  the booking agent, carrying your symptoms so you never repeat them.

**DB writes per turn:** 2 `patient_message` rows, 1 `patient_conversation` update
(agent_context), plus `core_patient` / `patient_insurancepolicy` / `audit_event` rows
when a threshold is crossed.

---

## 4. Identity verification (OTP)

**UI:** when `ui_hints` includes `otp_required`, the page automatically calls
`requestOtp(token)`, then shows six digit boxes.

| Step | API | Function chain | DB writes |
|---|---|---|---|
| Send code | `POST /api/registration/otp/request` → `RequestOtpAPIView` | `services.create_otp(patient, "SMS")` — expires older codes, generates a 6-digit code, stores **only its SHA-256 hash** | `OTPChallenge` (hash, 10-min expiry, max 5 attempts) + `SentNotification` (the "SMS" — printed to the console in dev) |
| Verify | `POST /api/registration/otp/verify` `{code}` → `VerifyOtpAPIView` | `services.verify_otp(patient, code)` — hash-compare, single-use, attempt counting. In DEBUG, `123456` always passes | `OTPChallenge.consumed_at` set; `Patient.identity_verified=True` |

The UI then nudges the chat forward with an invisible message ("I've entered my
verification code") so the next turn's state gate lands on the insurance stage.

---

## 5. Insurance — two paths past the same gate

**Path A — upload a card photo/PDF:** the 📎 button posts multipart
`{file, doc_type}` to `POST /api/registration/documents` → `UploadDocumentAPIView`:
1. File saved to `media/uploaded_documents/` + `UploadedDocument` row.
2. AI vision extraction (`registration/ai/extract.py`) tries to read the card and, if
   legible, writes the `InsurancePolicy` row itself.
   ⚠️ This path needs `AI_PROVIDER=anthropic` (vision, Anthropic content-block format) —
   under `AI_PROVIDER=openai` extraction fails safely (`extraction_status="failed"`),
   the upload itself still succeeds, and the UI tells the patient to type the details.
3. Response carries `policy_created: true/false` so the UI knows which happened.

**Path B — just type it** ("My provider is Star Health, policy number SH-12345"):
extraction tool picks the fields out of the message → `pending_insurance` →
`InsurancePolicy` row + eligibility check, as described in 3d. This is the path that
completed Gagadhar's registration.

---

## 6. Completion — and the ripple across other agents

When everything is on file and the model flags `registration_complete`, the state gate:
1. Writes accumulated intake → `IntakeSummary` row.
2. Calls `services.complete_registration(patient)`:
   - `Patient.registration_status = "complete"` + `AuditEvent`
   - `emit("registration.completed", patient_id=…)` (`core/events.py`) — writes a
     durable `EventLog` row, then calls every subscriber:
     - **Scheduling** (`scheduling/apps.py`): sends a "you can now book" notification
       (`SentNotification`).
     - **Triage** (`triage/apps.py`): if intake captured symptoms, pre-creates a pending
       `TriageAssessment` so the patient never repeats their story.
3. Marks the conversation `agent_context["active_agent"] = "scheduling"` with a handoff
   note carrying the symptoms — the PRD's register→book journey.

---

## 7. Every table this journey touches

| Table | Written by | When |
|---|---|---|
| `patient_conversation` | `StartRegistrationAPIView` / handler | session start; agent_context updated every turn |
| `patient_message` | `RegistrationChatAPIView` | both sides of every turn |
| `core_patient` | `services.create_or_update_patient_record` | when the demographic minimum lands |
| `otp_challenge` | `services.create_otp` / `verify_otp` | code sent / consumed |
| `core_sentnotification` | `core/notifications.notify` | OTP send, completion invite, and every other patient message |
| `patient_uploadeddocument` | `UploadDocumentAPIView` | card/report upload |
| `patient_insurancepolicy` | handler (typed) or upload extraction | insurance captured |
| `patient_intakesummary` | handler via services | at completion |
| `audit_event` | `services._audit` | every patient-data write |
| `core_eventlog` | `core/events.emit` | registration.completed (and every other event) |

---

## 8. The other three chat surfaces (same skeleton, different brains)

| Surface | Page → endpoint | What's different |
|---|---|---|
| **Front desk** (default `/`) | `FrontdeskChatPage` → `POST /api/frontdesk/start` + `/api/frontdesk/chat` | The orchestrator. Free text goes through `frontdesk/ai.py`: a **deterministic red-flag regex runs before any AI** (emergencies short-circuit), then the `route_message` router tool splits the message into intents (multi-intent supported) and dispatches each through the registry in `frontdesk/services.py` to scheduling/refills/referrals/priorauth/caregaps/triage. Personal intents are **queued** until the patient verifies (phone + DOB + OTP in-chat), then auto-resumed. Every dispatch writes an `IntentRoute` audit row; escalations write `StaffTask`. |
| **Triage** (`/triage`) | `TriageChatPage` → `POST /api/triage/assessments/` + `/answer/` | Not free chat — a scripted protocol Q&A. Red-flag check on the raw text first; answers accumulate on a `TriageAssessment`; finishing runs the deterministic acuity rules and `route_disposition()` emits `triage.disposition` for downstream agents. |
| **Scheduling** (`/schedule`) | `ChatWindow` → `POST /api/chat` | Stateless per request: the UI sends the whole visible conversation; `scheduling/ai/handler.handle_patient_message` extracts intent/slots, `find_available_slots` computes real availability, booking goes through `book_appointment` → `Appointment` row + `appointment.booked` event → confirmation `SentNotification`. |

The shared rules across all four: chats are streamed as SSE; a signed token (or none, for
scheduling) identifies the session — never a cookie; the AI only ever *states* things
through strict tools while *code* validates and writes; every write leaves an audit
trail; and an AI failure never blocks the flow (there is always a deterministic fallback).
