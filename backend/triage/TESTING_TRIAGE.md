# Testing the Triage Agent (Agent 3)

How to test every triage API with curl or Postman, and the same flows in the UI.

## Before you start

- Backend running: `./venv/bin/python manage.py runserver 8001` (from `backend/`)
- Frontend running (for UI tests): `npm run dev` (from `frontend/`), open http://localhost:5173
- Protocols seeded: `./venv/bin/python manage.py seed_protocols` — you should have
  Adult Fever, Adult Chest Pain, Pediatric Fever, Headache, Abdominal Pain.
- Triage requires a **verified patient**. The token is the same
  `X-Session-Token` used by registration — you get one by "signing in" through
  the registration endpoints (steps below).

## Step 0 — get a verified-patient token

Triage endpoints reject unverified sessions with `403`. Full sequence:

```bash
# 1. session
TOKEN=$(curl -s -X POST http://localhost:8001/api/registration/start \
  -H "Content-Type: application/json" -d '{"channel":"web"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["session_token"])')

# 2. identify the patient (use an existing patient's exact details to sign in as them)
curl -s -X POST http://localhost:8001/api/registration/demographics \
  -H "Content-Type: application/json" -H "X-Session-Token: $TOKEN" \
  -d '{"first_name":"Test","last_name":"Patient","dob":"1992-03-10","contact_number":"9800000001"}'

# 3. verify (123456 is the dev master code while DEBUG=True)
curl -s -X POST http://localhost:8001/api/registration/otp/request \
  -H "Content-Type: application/json" -H "X-Session-Token: $TOKEN" -d '{"channel":"SMS"}'
curl -s -X POST http://localhost:8001/api/registration/otp/verify \
  -H "Content-Type: application/json" -H "X-Session-Token: $TOKEN" -d '{"code":"123456"}'
```

In Postman: run those three requests first, keep `X-Session-Token` as a
collection-level header.

---

## 1. Start an assessment — `POST /api/triage/assessments/`

```bash
curl -s -X POST http://localhost:8001/api/triage/assessments/ \
  -H "Content-Type: application/json" -H "X-Session-Token: $TOKEN" \
  -d '{"symptoms_text": "I have had a headache and nausea since this morning"}'
```

Expected outcomes, depending on what you send:

- **Normal** → `201` `{"id": N, "protocol": "Headache", "first_question": "..."}`
  — save the `id` for the next calls. Try keywords matching the seeded
  protocols: *fever*, *headache*, *stomach/abdominal pain*, *chest pain*.
- **Red flag** (e.g. `"crushing chest pain and my left arm is numb"`) → `201`
  with the emergency payload: `"complete": true, "acuity": "emergency",
  "ui_hints": {"emergency": true}` — no questions asked, and an escalation
  alert is created for staff immediately.
- **No matching protocol** (e.g. `"my toenail looks weird"`) → `422` asking
  you to describe the symptoms differently.
- **Empty** `symptoms_text` → `400`. **Unverified/missing token** → `401/403`.

## 2. Answer questions — `POST /api/triage/assessments/{id}/answer/`

```bash
curl -s -X POST http://localhost:8001/api/triage/assessments/ID/answer/ \
  -H "Content-Type: application/json" -H "X-Session-Token: $TOKEN" \
  -d '{"answer": "It started this morning"}'
```

Repeat once per question. Expected per call, in order:

- more to ask → `{"next_question": "..."}`
- last answer → completion payload: `{"complete": true, "acuity": "low|medium|high|...",
  "disposition": "...", "explanation": "...", "ui_hints": {"offer_booking": true}}`
- a red-flag answer mid-interview (e.g. mention *chest pain and fainting*)
  → the emergency payload right away, interview over
- answering a finished assessment → `400 "no longer accepting answers"`
- an `id` from someone else's session → `404` (assessments are scoped to your session)

## 3. Assessment state — `GET /api/triage/assessments/{id}/`

```bash
curl -s http://localhost:8001/api/triage/assessments/ID/ -H "X-Session-Token: $TOKEN"
```

Expected: `{"id", "status": "pending|completed|escalated", "questions_answered",
"questions_total", "acuity", "disposition"}` (acuity/disposition only after it finishes).

## 4. Staff — escalation queue (admin login required)

These use your Django **admin session cookie**, not the session token. In the
browser: log into http://localhost:8001/admin/ then open the URLs directly.
With curl, copy `sessionid` (and `csrftoken` for POST) from browser dev tools:

```bash
# list open alerts
curl -s "http://localhost:8001/api/staff/triage/escalations/?status=open" \
  -H "Cookie: sessionid=YOUR_SESSIONID"

# acknowledge one
curl -s -X POST http://localhost:8001/api/staff/triage/escalations/ALERT_ID/ack/ \
  -H "Cookie: sessionid=YOUR_SESSIONID; csrftoken=YOUR_CSRFTOKEN" \
  -H "X-CSRFToken: YOUR_CSRFTOKEN"
```

Expected: list of `{id, patient_name, category, priority, summary, status, ...}`;
ack → `{"status": "acknowledged"}` (a second ack is still `200`, idempotent).
Without login → `403`. Tip: trigger a red-flag assessment first so the queue
isn't empty.

## 5. Staff — analytics — `GET /api/staff/triage/analytics/`

```bash
curl -s http://localhost:8001/api/staff/triage/analytics/ \
  -H "Cookie: sessionid=YOUR_SESSIONID"
```

Expected: totals, acuity distribution, escalation counts, average completion time.

---

## UI test cases (http://localhost:5173/triage)

1. **Sign-in gate**: first visit asks for name/DOB/phone of an existing
   patient, then the OTP (check the runserver terminal, or 123456). Wrong
   details for a near-match → staff-review message (409 path).
2. **Normal interview**: describe a headache → answer each question → result
   card with an urgency badge, explanation, and (usually) a
   "Book an appointment →" button that jumps to the scheduling chat with your
   symptoms pre-filled.
3. **Emergency**: type *"crushing chest pain, left arm numb"* as the first
   message → red 🚨 "Seek emergency care now" panel, no booking offered.
   Same if a red flag comes up mid-interview.
4. **Unmatched symptoms**: something vague → amber error bubble asking you to
   rephrase; the next message starts a fresh attempt.
5. **New assessment**: after a result, the header shows "New assessment" to reset.
6. **Staff queue** (http://localhost:5173/staff/escalations): without admin
   login you get a banner telling you to log into /admin/ first. After login:
   alerts with priority badges, patient phone, AI summary; "Acknowledge" moves
   them out of the open list ("Show all" reveals them again). The list
   auto-refreshes every 15 seconds — your emergency test from case 3 should
   appear here.
