# Testing the Registration Agent (Agent 2)

How to test every registration API with curl or Postman, and the same flows in the UI.

## Before you start

- Backend running: `./venv/bin/python manage.py runserver 8001` (from `backend/`)
- Frontend running (for UI tests): `npm run dev` (from `frontend/`), open http://localhost:5173
- Dev OTP: while `DEBUG=True`, the code **123456** always works. The real random
  code is also printed in the runserver terminal as `[dev OTP] ...`.
- In Postman, put the base URL `http://localhost:8001` in an environment variable
  and add the header `X-Session-Token` to every request after "start".

Every endpoint below (except `start` and the staff analytics) **requires the
`X-Session-Token` header** — the token comes from the `start` call.

---

## 1. Start a session — `POST /api/registration/start`

```bash
curl -s -X POST http://localhost:8001/api/registration/start \
  -H "Content-Type: application/json" \
  -d '{"channel": "web"}'
```

Expected: `201` with `{"session_token": "...", "conversation_id": N}`.

Save the token for the rest of the calls:

```bash
TOKEN=$(curl -s -X POST http://localhost:8001/api/registration/start \
  -H "Content-Type: application/json" -d '{"channel":"web"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["session_token"])')
```

Error case: `{"channel": "fax"}` → `400` listing valid channels.

## 2. Submit demographics — `POST /api/registration/demographics`

```bash
curl -s -X POST http://localhost:8001/api/registration/demographics \
  -H "Content-Type: application/json" -H "X-Session-Token: $TOKEN" \
  -d '{"first_name":"Test","last_name":"Patient","dob":"1992-03-10","contact_number":"9800000001"}'
```

Expected:
- New patient → `201` `{"patient_id": N, "match": "new"}`
- Same details again (new session) → `200` with `"match": "existing"` (linked, not duplicated)
- Similar name + same DOB but different phone → `409` `"match": "possible_duplicate"` (registration held for staff)
- Missing field → `400` listing what's missing

## 3. Request OTP — `POST /api/registration/otp/request`

```bash
curl -s -X POST http://localhost:8001/api/registration/otp/request \
  -H "Content-Type: application/json" -H "X-Session-Token: $TOKEN" \
  -d '{"channel": "SMS"}'
```

Expected: `202` `{"detail": "verification code sent"}` — watch the runserver
terminal for the `[dev OTP]` line. `{"channel":"email"}` needs an email on file
(else `400`); channel casing doesn't matter (`sms` works).

## 4. Verify OTP — `POST /api/registration/otp/verify`

```bash
curl -s -X POST http://localhost:8001/api/registration/otp/verify \
  -H "Content-Type: application/json" -H "X-Session-Token: $TOKEN" \
  -d '{"code": "123456"}'
```

Expected: `200` `{"verified": true}` (123456 is the dev master code).
Error cases: wrong code → `400` `{"code": "otp_invalid"}`; after 3 wrong tries
→ `otp_too_many_attempts`; no code requested → `otp_missing`.

## 5. Insurance

Two ways to get the policy on file:

**a) Structured endpoint — `POST /api/registration/insurance`** (needs all four fields):

```bash
curl -s -X POST http://localhost:8001/api/registration/insurance \
  -H "Content-Type: application/json" -H "X-Session-Token: $TOKEN" \
  -d '{"policy_number":"SH-90210","provider_name":"Star Health","coverage_start":"2026-01-01","coverage_end":"2026-12-31"}'
```

Expected: `201` with `eligibility_status` (`eligible` normally). A policy number
containing `INACTIVE` is flagged (`"flagged": true`) but still accepted.

**b) Card upload — `POST /api/registration/documents`** (multipart, not JSON):

```bash
curl -s -X POST http://localhost:8001/api/registration/documents \
  -H "X-Session-Token: $TOKEN" \
  -F "doc_type=insurance_card" -F "file=@/path/to/card.png"
```

Expected: `201` with `extraction_status` and `policy_created`.
Note: with `AI_PROVIDER=openai` the card reading usually fails — you'll get
`"policy_created": false` and should use option (a) or dictate the details in
chat instead. The upload itself never fails because of that.

## 6. Status — `GET /api/registration/status`

```bash
curl -s http://localhost:8001/api/registration/status -H "X-Session-Token: $TOKEN"
```

Expected: `{"registration_status": "...", "missing": [...]}` — `missing` shrinks
as you complete steps (`identity`, `insurance`, `intake`).

## 7. Intake + complete

Intake is normally collected by the chat (below). To test `complete` without
the chat, insert an intake row via the dev CRUD endpoint first:

```bash
curl -s -X POST http://localhost:8001/api/intakesummary \
  -H "Content-Type: application/json" \
  -d '{"patient": PATIENT_ID, "clinical_profile": {"symptoms": ["cough"]}, "summary_text": "test"}'

curl -s -X POST http://localhost:8001/api/registration/complete \
  -H "Content-Type: application/json" -H "X-Session-Token: $TOKEN" -d '{}'
```

Expected: `200` `{"registration_status": "complete", "event_id": N}`.
Error case: called while something is missing → `400` listing the missing steps.

## 8. Chat — `POST /api/registration/chat` (SSE stream)

The conversational way to do all of the above. Responses stream as
server-sent events (`data: {...}` lines), so use `-N`:

```bash
curl -sN -X POST http://localhost:8001/api/registration/chat \
  -H "Content-Type: application/json" -H "X-Session-Token: $TOKEN" \
  -d '{"message": "Hi, I am Test Patient, born 1992-03-10, phone 9800000001"}'
```

You'll see `{"delta": "..."}` events (the reply, word by word) and a final
`{"done": true, "stage": "...", "ui_hints": [...], ...}` event. The `stage`
tells you where you are: `demographics → identity_verification → insurance →
intake → done`. Useful test messages:

- insurance by dictation: `"My provider is Star Health, policy number SH-90210"`
  → next `stage` should be `intake`
- finish: answer the intake questions, then `"That's everything, please complete my registration"`
  → `stage: "done"`, `registration_complete: true`

Postman: the response is a stream; Postman shows it after the request finishes —
readable, just not word-by-word.

## 9. Staff analytics — `GET /api/staff/registration/analytics`

Admin only (Django session). Easiest in the browser: log into
http://localhost:8001/admin/ first, then open
http://localhost:8001/api/staff/registration/analytics. With curl, copy the
`sessionid` cookie from your browser:

```bash
curl -s http://localhost:8001/api/staff/registration/analytics \
  -H "Cookie: sessionid=YOUR_SESSIONID"
```

Unauthenticated → `403`.

---

## UI test cases (http://localhost:5173/register)

1. **Happy path**: give name, DOB, phone in chat → OTP box appears (code is in
   the runserver terminal, or type 123456) → asked for insurance → type
   provider + policy number → answer the intake questions → green
   "Registration complete" banner with a "Book an appointment" link.
2. **Card upload**: at the insurance step click 📎 and pick any image. If the
   card can't be read you get a note asking to type the details — that's the
   expected fallback on the OpenAI provider.
3. **Wrong OTP**: type a wrong code → error bubble; "Resend code" gets a new one.
4. **Duplicate**: register the same person twice with a slightly different
   name and a different phone → amber "similar record exists" banner (staff hold).
5. **Refresh survives**: reload mid-registration — the chat and progress chips
   restore (per-tab; a new tab starts fresh).
6. **Check status / Start over** buttons in the header do what they say.
