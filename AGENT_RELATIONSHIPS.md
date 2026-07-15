# How the 9 Agents Relate to Each Other

MediAssist AI has 9 agents. Each one owns its own Django app, its own models, and its own
APIs — but none of them work alone. This document explains **every connection between them**,
based on the actual wiring in the code (not the design docs).

The 9 agents:

| # | Agent | Django app | One-line job |
|---|-------|-----------|--------------|
| 1 | Scheduling | `scheduling` | Find slots, book/cancel appointments |
| 2 | Registration & Intake | `registration` | New-patient chat: demographics, OTP, insurance, intake |
| 3 | Clinical Triage | `triage` | Assess symptoms, decide urgency, escalate emergencies |
| 4 | Refill Coordination | `refills` | Medication refill requests and eligibility checks |
| 5 | Referral Execution | `referrals` | Send patients to specialists and close the loop |
| 6 | Prior Authorization | `priorauth` | Get insurance approval for treatments |
| 7 | Outreach Campaigns | `outreach` | Proactive SMS/email campaigns (e.g. flu shots) |
| 8 | Care Gap Closure | `caregaps` | Find overdue screenings, bundle them into care plans |
| 9 | Front Desk / After-Hours | `frontdesk` | 24/7 receptionist: understands any request, routes it |

---

## 1. The two ways agents talk to each other

**Way 1 — The event bus (`core/events.py`).** An agent announces "this just happened"
by calling `emit("event.name", ...)`. Every announcement is saved as an `EventLog` row
in the database (a permanent record), and then every function that *subscribed* to that
event name runs immediately. The announcer doesn't know or care who is listening.
Subscriptions live in each app's `apps.py` and are registered at server startup.

**Way 2 — Direct calls.** One agent simply calls another agent's service function or
reads its models. Used when the caller needs an answer *right now* (e.g. the front desk
asking scheduling "what appointments does this patient have?").

Rule of thumb in this codebase: **"something finished, others may care" → event bus;
"I need data or an action right now" → direct call.**

---

## 2. The big picture

```
                         ┌──────────────────────┐
                         │  9. FRONT DESK (hub) │  understands any message,
                         │  intent router       │  then calls the right agent
                         └──────────┬───────────┘
        direct calls into: 1,3,4,5,6,8 + knowledge base + staff tasks
                                    │
  ┌─────────────┐  registration.completed   ┌─────────────┐
  │ 2. REGISTER ├──────────────┬───────────►│ 3. TRIAGE   │
  └──────┬──────┘              │            └──────┬──────┘
         │ chat handoff        ▼                   │ triage.disposition
         │ (symptoms)   ┌─────────────┐            ├──────────► 1. SCHEDULING (book offer)
         └─────────────►│1. SCHEDULING│◄───────────┤──────────► 5. REFERRALS  (draft referral)
                        └──────┬──────┘            └──────────► 6. PRIORAUTH  (imaging order)
     appointment.booked/       │
     completed/cancelled       │ appointment.completed
                               ▼
  ┌─────────────┐        ┌─────────────┐   priorauth.needed   ┌─────────────┐
  │ 4. REFILLS  │        │ 8. CAREGAPS │◄──(from referrals)──►│ 6. PRIORAUTH│
  └──────┬──────┘        └──────┬──────┘                      └──────┬──────┘
         │ refill.visit_required│ push plans as campaigns            │ priorauth.approved
         ▼                      ▼                                    ▼
   1. SCHEDULING          ┌─────────────┐  outreach.member_booked  1. SCHEDULING
   (book offer)           │ 7. OUTREACH ├────────► 8. CAREGAPS     (book offer)
                          └─────────────┘  (care plan advances)
```

---

## 3. Every event, who sends it, who reacts

This is the complete event-bus wiring, verified against the code.

| Event | Sent by | Who listens | What the listener does |
|-------|---------|-------------|------------------------|
| `registration.completed` | **2 Registration** (`registration/services.py`) when all steps are done | **1 Scheduling** | Sends the patient a "you can book an appointment now" notification |
| | | **3 Triage** | Pre-loads a triage assessment from the intake symptoms so the patient never repeats them; red-flag symptoms escalate immediately (`triage/apps.py`) |
| `appointment.booked` | **1 Scheduling** (also fired when referrals or outreach book through it) | **1 Scheduling** (itself) | Sends the booking confirmation to the patient |
| `appointment.completed` | **1 Scheduling** (service + the staff PATCH endpoint) | **8 Care Gaps** | Marks the patient's scheduled gaps "completed" and rescans for evidence (`caregaps/apps.py`) |
| `appointment.cancelled` | **1 Scheduling** | **1 Scheduling** (itself) | Sends the cancellation notice |
| `triage.disposition` | **3 Triage** (`route_disposition()`) with a `route_to` target | **1 Scheduling** (when `route_to="scheduling"`) | Invites the patient to book with the right urgency (same-day / 24-48h / routine) |
| | | **5 Referrals** (when `route_to="referrals"`) | Auto-creates a **draft** referral from the assessment — a physician still has to accept it |
| | | **6 Prior Auth** (when `route_to="priorauth"`) | Opens an imaging treatment order and runs authorization detection |
| `priorauth.needed` | **5 Referrals** (`accept_referral()`) the moment a referral is accepted | **6 Prior Auth** | Creates a treatment order linked to the referral and starts the authorization check |
| `priorauth.approved` | **6 Prior Auth** (`poll_status()`) | **1 Scheduling** | Invites the patient to book the now-approved treatment |
| `refill.visit_required` | **4 Refills** (physician says "see me first") | **1 Scheduling** | Invites the patient to book that visit |
| `outreach.member_booked` | **7 Outreach** (patient replied "book" and an appointment was auto-created) | **8 Care Gaps** | Advances the patient's care plan to "in progress" and their gaps to "scheduled" |

**Events that are recorded but nobody reacts to (by design or as known gaps):**

| Event | Sent by | Situation |
|-------|---------|-----------|
| `escalation.created` | 3 Triage, 4 Refills, 5 Referrals, 6 Prior Auth | No subscriber — escalation already notifies on-call staff *directly* inside `escalate()`; the event is the audit record |
| `refill.approved` | 4 Refills | No subscriber — the refill flow itself notifies the patient; the event is the audit record |
| `priorauth.denied` | 6 Prior Auth | No subscriber — denial handling (appeal/tasks) happens inside prior auth itself |
| `outreach.booking_requested` | 7 Outreach | No subscriber — recorded for campaign analytics |
| `triage.disposition` with `route_to="refills"` or `"caregaps"` | 3 Triage | **Known dead routes**: triage can emit these hints (`ROUTE_FOR_HINT` in `triage/services.py`), but refills and caregaps never subscribed. Documented as deliberate in `steps/BUILD_STEPS_Agent_3_Clinical_Triage.md`; wiring them up is a small future task |

---

## 4. Direct calls (agent A uses agent B's code right now)

| From → To | Where | What happens |
|-----------|-------|--------------|
| **9 Front Desk → almost everyone** | `frontdesk/services.py` `REGISTRY` | The heart of orchestration. The AI router classifies any patient message into an intent, and the registry maps each intent to an agent: `appointment`→Scheduling, `refill`→Refills, `referral_status`→Referrals, `pa_status`→Prior Auth, `care_gap`→Care Gaps, `symptoms`→Triage, `faq`→knowledge base, `other`→staff task. Each handler reads that agent's models directly to answer |
| **9 Front Desk → 2 Registration** | `frontdesk/services.py` | Reuses registration's OTP functions (`create_otp` / `verify_otp`) to verify a patient's identity before showing any personal data |
| **9 Front Desk → 3 Triage** | `frontdesk/ai.py` | On emergency symptoms: creates a triage `EscalationAlert` and calls `notify_on_call()` — the same emergency machinery triage uses |
| **2 Registration → 1 Scheduling** | chat handoff | When registration finishes, the conversation's `agent_context` is marked `active_agent: "scheduling"` with the patient's symptoms; the web UI then auto-opens the booking flow with those symptoms (no re-asking) |
| **5 Referrals → 1 Scheduling** | `referrals/services.py` | `book_specialist_visit()` calls scheduling's `find_available_slots()` / `book_appointment()` to book the specialist appointment |
| **7 Outreach → 1 Scheduling** | `outreach/services.py` | A patient replying "book" to a campaign gets an appointment auto-created through scheduling's real booking functions |
| **7 Outreach → 8 Care Gaps** | `outreach/services.py` | Cohort building ("who should this campaign target?") reads care-gap clinical data (`ClinicalEvent`, `CarePlan`) |
| **8 Care Gaps → 7 Outreach** | `caregaps/services.py` | `push_plans_to_outreach()` turns finished care plans into a real outreach campaign with members — outreach then does the messaging |
| **7 Outreach → 9 Front Desk** | `outreach/views.py` webhook | An inbound SMS/WhatsApp from a number that doesn't match any campaign falls through to the front desk (`handle_channel_message`) instead of being dropped |
| **3 Triage → 2 Registration** | `triage/services.py` | Reads the patient's `IntakeSummary` so the assessment starts from what registration already collected |
| **5 Referrals / 6 Prior Auth / 4 Refills → 2 Registration** | various | Read registration's `InsurancePolicy`, `IntakeSummary`, and `UploadedDocument` records to build referral packages and run insurance checks |
| **6 Prior Auth → 5 Referrals / 4 Refills** | `priorauth/services.py` | Reads `Referral`, `ConsultationReport`, and `Prescription` records to link authorizations to what triggered them |

---

## 5. Each agent's neighborhood at a glance

- **1 Scheduling** — the most-connected agent. It *hears from* registration, triage,
  refills, and prior auth (all four end with "invite the patient to book"), and it is
  *called directly* by referrals, outreach, and the front desk. It announces every
  booking, completion, and cancellation.
- **2 Registration** — the entry point. It only *announces* (`registration.completed`)
  and hands its chat to scheduling; it never listens. Its data (insurance, intake,
  documents) is read by almost everyone.
- **3 Triage** — the router-by-urgency. Wakes up when registration completes, then fans
  patients out to scheduling, referrals, or prior auth via `triage.disposition`.
  Owns the emergency escalation machinery that front desk reuses.
- **4 Refills** — mostly self-contained. Its one outward connection: "physician wants a
  visit first" → scheduling offers a booking.
- **5 Referrals** — receives drafts from triage, asks prior auth for approval the moment
  a referral is accepted (`priorauth.needed`), and books specialist visits through
  scheduling.
- **6 Prior Auth** — sits between referrals/triage (which trigger it) and scheduling
  (which it hands approved treatments to).
- **7 Outreach** — the outbound messenger. Care gaps feeds it campaigns; it books through
  scheduling; it tells care gaps when a patient booked; unrecognized inbound texts go to
  the front desk.
- **8 Care Gaps** — watches `appointment.completed` and `outreach.member_booked` to move
  gaps through their lifecycle, and pushes plans out through outreach.
- **9 Front Desk** — the hub. It doesn't own clinical workflows; it *routes into* six
  other agents through one registry, borrows registration's OTP verification and
  triage's emergency path, and catches whatever no one else recognizes (→ staff task).

---

## 6. One worked example (the primary patient journey)

What actually fires when a new patient registers with "fever and headache", verifies OTP,
and gives insurance:

1. **2 Registration** finishes → emits `registration.completed`.
2. **1 Scheduling** hears it → sends "you can book an appointment" notification.
3. **3 Triage** hears it → creates a pending assessment pre-loaded with "fever, headache"
   (red-flag check first — a chest-pain patient would be escalated here instead).
4. The web UI (same chat window) auto-starts booking: symptoms go to **1 Scheduling**'s
   chat agent, which matches a doctor and offers slots.
5. Patient taps a slot → appointment created → `appointment.booked` fires → confirmation
   notification goes out.
6. After the visit, staff marks it completed → `appointment.completed` fires →
   **8 Care Gaps** advances any scheduled gaps and rescans the patient.

Six agents touched, and no agent ever asked the patient to repeat themselves — that's
what the wiring above buys.

---

*Sources: `core/events.py`, each app's `apps.py` (subscribers), `*/services.py` (emitters
and direct calls), `frontdesk/services.py` REGISTRY. Generated from the code as of this
commit; if you add a subscriber or emitter, please update the tables here.*
