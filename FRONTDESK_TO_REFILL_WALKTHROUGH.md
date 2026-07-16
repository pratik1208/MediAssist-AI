# A Real Walkthrough: Front Desk Chat → Refill Agent

This traces one real test session end to end — every chat bubble, every API call, every
database row — from a patient opening the chat to a controlled-substance refill firing an
on-call alert. It's a companion to `FRONTDESK_AGENT_FLOW.md` (which explains *how* the
code works); this document shows *one actual run of it*, with real IDs and real log
lines, so the two read together as theory + evidence.

**Test patient:** Pratik Marudwar (`core_patient` id 7), phone `8605260762`, DOB
`1998-08-14`. Three prescriptions were seeded on his chart beforehand: Amlodipine
(clean/eligible), Metformin (zero refills left), Alprazolam (controlled substance).

---

## 1. The two-stop journey — and the one thing that's easy to miss

Front Desk (Agent 9) and Refills (Agent 4) are **two separate stops**, not one:

```
┌─────────────────────────┐         ┌──────────────────────────┐
│  1. FRONT DESK CHAT      │         │  2. REFILLS PAGE          │
│     "/" — free text      │  hand   │     "/refills" — a form   │
│     understands intent,  │ ─off──► │     that actually SUBMITS │
│     AUTHENTICATES you,   │  only   │     a refill request and  │
│     and REPORTS what's   │         │     runs eligibility      │
│     on your chart        │         │                            │
└─────────────────────────┘         └──────────────────────────┘
```

**Front Desk's `refill` handler is read-only.** It looks at `Prescription.objects.filter(
patient=..., status="active")` and reports what it finds — it never creates a
`RefillRequest` row itself (`frontdesk/services.py::_handle_refill`, line ~200). Actually
*requesting* a refill (which starts the eligibility engine, the physician queue, and the
controlled-substance alert) happens on the dedicated Refills UI. In this test, that meant
a second identity check — the Refills page reads its session token from `registration` or
`triage`'s sessionStorage key, not Front Desk's, so a fresh registration/OTP round-trip
happened before any `RefillRequest` could be created. This is current, working behavior,
not a bug — but it's worth knowing before you go looking for a `RefillRequest` row right
after a Front Desk chat message and don't find one.

---

## 2. Stop 1 — Front Desk: ask, authenticate, get reported to

**Session:** `frontdesk_patientsession` id 34, wrapping `patient_conversation` id 122.

| # | Speaker | Message | What happened underneath |
|---|---|---|---|
| 1 | Patient | *"I wanted to refill drugs"* | `POST /api/frontdesk/chat {"message": "..."}`. Deterministic red-flag regex runs first (clean, no emergency). `route_message()` (the AI router) classifies this as intent `refill`. `refill` requires auth (`frontdesk/services.py` REGISTRY) and the session is still anonymous, so the intent is appended to `session.pending_intents` — not answered yet. |
| 2 | Assistant | *"I can help with that as soon as I've verified your identity. What's your registered phone number and date of birth?"* | The auth-gate prompt. |
| 3 | Patient | `[identity claim submitted]` — phone `8605260762`, DOB `1998-08-14` | `POST /api/frontdesk/chat {"action": "start_auth", ...}` → `services.start_authentication()` matches the patient by phone+DOB, generates an OTP. |
| 4 | Assistant | *"We've sent a verification code to your phone."* | Server console: `[dev OTP] to 8605260762 via sms: Your MediAssist verification code is 897875. It expires in 10 minutes.` — printed, not actually sent (`ConsoleProvider`, Track B on the roadmap). |
| 5 | Patient | `[verification code submitted]` — `897875` | `POST /api/frontdesk/chat {"action": "verify_otp", "otp": "897875", ...}` → `services.authenticate_session()` succeeds → `PatientSession.authenticated = True`. |
| 6 | Assistant | *"You're verified."* (shown in the UI as **✓ You're verified.**) | Immediately after, the endpoint calls `services.resume_pending_intents(session)`, which dispatches the queued `refill` intent through the registry. |

### What the resumed `refill` dispatch actually returned

`_handle_refill()` read patient 7's active prescriptions (all three — none of them was the
*only* active med, so the "all-controlled → straight to staff" shortcut didn't trigger)
and replied:

> *"These are your active medications; tell me which one to refill."*
> — Amlodipine (4 refills left), Metformin (0 refills left), Alprazolam (controlled)

This reply arrived in the same API response as `resumed: [...]`, and the frontend
(`FrontdeskChatPage.tsx`) rendered it as its own chat bubble right under "You're
verified." A durable `IntentRoute` row (id 44, `intent="refill"`, `target_agent="refills"`,
`status="completed"`) was written — that's the audit trail the analytics dashboard counts.

> **Worth knowing:** the *persisted* `patient_message` row for this turn only stored the
> literal text `"You're verified."` — the resumed intent's reply text (the medication list
> above) was shown to the patient live but isn't in the saved conversation transcript.
> `IntentRoute` still records that the dispatch happened and completed, so nothing about
> *that a refill lookup ran* is lost — just the exact reply text isn't in `patient_message`
> the way a typical assistant turn is.

At this point, Front Desk's job is done: identity confirmed, request understood, patient
told what's on their chart. No `RefillRequest` exists yet.

---

## 3. Stop 2 — Refills: the actual request, one medication at a time

The test continued on `/refills`. Because that page reads a **registration** session
token and none existed yet in this browser tab, a short registration + OTP round-trip ran
first (`POST /api/registration/start` → `/demographics` → `/otp/request` → `/otp/verify`,
OTP `655084`) purely to obtain a token `RefillsPage` recognizes — same patient (7), same
phone, different auth surface. `GET /api/refills/prescriptions/` then returned the same
three medications Front Desk had already listed.

For each medication, the pattern was **try → 400 → pick a pharmacy → retry → 201**:

```
POST /api/refills/requests/ {prescription_id}          → 400 "pharmacy_id is required"
GET  /api/pharmacy                                       → pharmacy list shown to patient
POST /api/refills/requests/ {prescription_id, pharmacy_id} → 201 {id, status}
```

The 400 happened every time because patient 7's `preferred_pharmacy` field is the free-text
value `"Pharmacy with more than 20% discount"` — `_resolve_pharmacy()` tries an
`icontains` match against real `Pharmacy` names first (`refills/views.py`
`CreateRefillRequestAPIView._resolve_pharmacy`) and finds nothing, so it correctly falls
through to "ask the patient." All three requests ended up at **Apollo Pharmacy, MG Road**.

One submit also hit **409 Conflict** (`{"code": "already_requested", ...}`) — the
duplicate-request guard refusing a second open request for a prescription that already had
one in flight (`RefillRequest.OPEN_STATUSES`). That's the safety net working, not a bug —
likely a double click.

### The three outcomes

Each `POST` triggers `services.run_eligibility_check()` synchronously before the response
is returned:

| Request | Medication | Refills used | What the eligibility engine did | Final status |
|---|---|---|---|---|
| **19** | Metformin 500mg | 3/3 | Nothing else wrong, but no refills left → flagged `needs_new_prescription=True`, `renewal_summary["is_renewal"] = True` — routed as a **renewal**, not a plain refill (FR-M4, Edge Case 1) | `pending_approval` |
| **20** | Amlodipine 5mg | 1/5 | Clean — no failures, refills remain. Even so, **nothing auto-approves**; every request lands in the physician queue regardless | `pending_approval` |
| **21** | Alprazolam 0.5mg | 0/2 | `is_controlled_substance=True` → `check_eligibility()` short-circuits immediately to `escalate_controlled()`, which creates an `EscalationAlert` (category `controlled_substance`, priority `high`) and logs `[ON-CALL ALERT] controlled substance refill — request 21, patient 7`. The automated path never touches it (PRD Edge Case 12) | `pending_approval` |

All three ended up in the same status for different reasons — `pending_approval` means
"eligibility ran, no automatic paused-reason, now sitting in the physician/staff queue,"
not "approved." Nothing in this system auto-approves a refill straight to the pharmacy;
a human always makes the final call at `/staff/refills`.

The chat UI then polled `GET /api/refills/requests/21/` every 10 seconds — expected, since
`pending_approval` isn't a terminal status and the frontend keeps checking until it changes.

---

## 4. Every database row this session actually wrote

| Table | Row(s) | Written by |
|---|---|---|
| `patient_conversation` | id 122 | Front Desk session start |
| `patient_message` | ids 431–436 | every chat turn, both directions |
| `frontdesk_patientsession` | id 34, `authenticated=True` | `start_authentication` → `authenticate_session` |
| `otp_challenge` | one row, consumed | `create_otp` / `verify_otp` (Front Desk borrows Registration's OTP machinery verbatim) |
| `frontdesk_intentroute` | id 44, `intent=refill`, `status=completed` | `dispatch_intent` via `resume_pending_intents` |
| `refills_refillrequest` | ids 19, 20, 21 | `CreateRefillRequestAPIView.post`, one per medication |
| `triage_escalationalert` | one row, `category=controlled_substance` | `escalate_controlled()` for the Alprazolam request |
| `core_sentnotification` | OTP sends (x2 — Front Desk's and Registration's), any `refill_paused` notices | `core/notifications.notify` (console-only in dev) |

---

## 5. What's next for these three requests

They're sitting in the staff queue right now. To move them further through the pipeline
(`pending_approval` → `sent_to_pharmacy` → `ready_for_pickup`, or → `rejected` /
`visit_required`), a staff user acts on them at `http://localhost:5173/staff/refills` — the
doctor-facing side of Agent 4 that this walkthrough didn't exercise yet.

---

*Sources: server log for 2026-07-16 23:15–23:32 IST, `frontdesk/services.py`,
`frontdesk/views.py`, `refills/views.py`, `refills/services.py`, and the live
`frontdesk_patientsession` / `refills_refillrequest` rows for patient 7. See also
`FRONTDESK_AGENT_FLOW.md` for how the mechanisms here work in general, and
`PATIENT_CHAT_FLOW.md` §8 for how the four chat surfaces compare.*
