# How the Triage Agent (Agent 3) Works

This explains, in plain English, exactly what happens inside the triage agent — from a
patient describing symptoms to a final "see a doctor today / this week / not urgent"
decision — and how it plugs into the rest of the system. Every claim below is backed by
a specific line in `backend/triage/services.py` or `backend/triage/views.py`.

---

## 1. The one thing to remember: rules decide, not the AI

Triage is deliberately **not** "ask the AI what's wrong and trust the answer." The acuity
(how serious this is) is computed by a deterministic scoring function reading a
data-driven rulebook (`ClinicalProtocol.disposition_rules`, a JSON field). The AI layer
can only ever **raise** that score, never lower it — so a hallucinating or overly
reassuring model can never talk a genuine emergency down to "self care."

Two independent safety layers enforce this:

1. **The red-flag screen** (`core.safety.red_flag_check`) — a keyword scan that runs on
   every raw thing the patient types, before any question flow or AI call. Chest pain,
   can't breathe, slurred speech, suicidal thoughts → instant escalation, no further
   questions, ever.
2. **The rules engine** (`evaluate_disposition_rules`) — after the interview, the
   protocol's own red-flag conditions and rules run in order; only if nothing else
   fires does a plain default apply. The AI's opinion is folded in last, and only
   upward.

---

## 2. Step by step: one assessment from start to finish

### Step A — Match symptoms to a protocol (`select_protocol`)

The patient's free-text symptoms ("my baby has a fever") are matched against every
active `ClinicalProtocol`'s `symptom_keywords` list. Matching is done by
`phrase_in_text()`, which is smarter than a plain substring search:

- **Word order doesn't matter** — "stiff neck" matches "my neck feels stiff."
- **Negation is respected** — "no fever, just a headache" will *not* match "fever",
  because "no" appears before it in the same clause. This is the single most important
  correctness rule in the file: a naive substring match would wrongly flag every "no
  fever" sentence as reporting a fever.
- **Prefixes count** — the keyword "vomit" matches "vomiting"; "sudden" matches
  "suddenly."
- **Best match wins** — if two protocols both match, the one with more matched
  keywords wins; ties break on total matched length (a specific multi-word match beats
  a generic one-word match).

If nothing matches, `select_protocol` returns `None` — the caller (the API view) then
tells the patient it couldn't classify their symptoms rather than guessing wrong.

### Step B — The interview (`question_flow`)

Each protocol carries its own ordered list of follow-up questions
(`ClinicalProtocol.question_flow`), asked one at a time via
`POST /api/triage/assessments/{id}/answer/`. Every single answer — not just the first
message — is run through the red-flag screen again (line 194 of `triage/views.py`):
a patient who starts with "mild headache" but later says "actually my vision just went
black" gets escalated mid-interview, not after finishing the questionnaire.

Answers arrive as free text but the rules need real numbers/booleans, so `_coerce()`
converts them:
- `"yes"` / `"no"` → `True` / `False`.
- `"It's around 104 F"` → `104` (first number in the sentence wins).
- `"2 years old"` → `24` when the question expects **months**; `"3 days"` → `72` when
  it expects **hours**. This unit conversion means the protocol author can write a
  rule like "duration_hours >= 48" once, and it still fires correctly whether the
  patient answered in days, weeks, or hours.

### Step C — Score the answers (`assign_acuity`)

Once every question is answered, three things get combined, in this exact order and
this exact precedence:

1. **The protocol's own rules** (`evaluate_disposition_rules`): first check `red_flags`
   (first match wins), then `rules` (first match wins), then fall back to
   `default_acuity` if nothing matched.
2. **Risk overrides**: things about *this specific patient* — age ≥ 50 or ≥ 65, a
   diabetes/cardiac/immunocompromised history, being on blood thinners — can only push
   the acuity **up** (`risk_overrides` in the protocol JSON), never down. A 70-year-old
   with a "low" acuity finding might get raised to "medium" because of age alone.
3. **The AI's suggestion** (`findings["suggested_acuity"]`, when the AI layer is
   involved) — again, can only raise the result, via the same `_raise_to()` helper
   used for risk overrides.

The final acuity (`minimal` → `low` → `medium` → `high` → `emergency`) maps directly to
a disposition:

| Acuity | Disposition | Meaning shown to the patient |
|--------|-------------|-------------------------------|
| `emergency` | `ed_now` | Call 911 / go to the ER now — on-call clinician alerted |
| `high` | `same_day` | Book an appointment for today |
| `medium` | `24_48h` | Be seen within 24–48 hours |
| `low` | `routine` | A routine appointment is fine, whenever suits |
| `minimal` | `self_care` | Manage at home; come back if it worsens |

### Step D — Route it (`route_disposition`)

This is the handoff to the rest of the system. Triage doesn't call other agents
directly — it announces one event, `triage.disposition`, on the event bus
(`core/events.py`), carrying the patient, the assessment, the acuity, the disposition,
and a computed `route_to` target. Whoever is listening reacts; triage doesn't know or
care who that is.

`route_to` is decided by **two** tables, checked in this order:

1. `ROUTE_FOR_HINT` — if the AI set `findings["route_hint"]` to flag that the real
   issue is a **specialist referral**, a **medication problem**, a **preventive-care
   gap**, or a **diagnostic/imaging need**, that outranks the plain urgency-based
   routing below. (Example: a "routine" complaint that's really a refill request goes
   to Refills, not Scheduling.)
2. `ROUTE_FOR_DISPOSITION` — otherwise, urgency decides: `same_day` / `24_48h` /
   `routine` all route to Scheduling; `ed_now` and `self_care` route to **nobody**
   (an emergency doesn't get "booked," and self-care needs no downstream action).

### Step E — Emergency path (`escalate`), whenever a red flag fires

Whether the red flag was caught before the interview even started, mid-interview, or
computed as the final acuity, the exact same function runs:

1. Creates an `EscalationAlert` row — the durable record staff see in the escalation
   queue.
2. Tries to get an AI-written clinical summary for the on-call clinician
   (`generate_triage_summary`) — but if that call fails for any reason, it falls back
   to a deterministic plain-text summary instead. **An AI outage must never delay or
   block an emergency alert** — this is the one place in the whole file where a
   try/except swallows an AI failure on purpose.
3. Calls `notify_on_call()` — currently a console/log print (a dev stub for a real
   pager/SMS integration later). This deliberately does **not** reuse the
   patient-facing `notify()` used everywhere else, because that function respects
   patient opt-outs — an emergency alert to a clinician must never be silenced by a
   patient's notification preference.
4. Marks the assessment `escalated`, forces acuity to `emergency`, and stamps
   `finished_at`.
5. Emits `escalation.created` (currently just an audit record — nothing subscribes to
   it, since the alert and the page already happened synchronously above).

---

## 3. How triage connects to the other 8 agents

Triage sits in the middle of the system: it's fed by Registration, and it feeds
Scheduling, Referrals, and Prior Auth. Front Desk borrows its emergency machinery.

```
                 registration.completed
  2 REGISTRATION ───────────────────────► 3 TRIAGE
                                             │
                               triage.disposition (route_to = ...)
                                             │
                  ┌──────────────┬───────────┼───────────────┐
                  ▼              ▼           ▼               ▼
            1 SCHEDULING   5 REFERRALS  6 PRIOR AUTH    (refills / caregaps:
           (book offer,    (draft        (imaging order   routed but no
            urgency-aware)  referral)     + auth check)    listener yet)

  9 FRONT DESK  ── borrows ──►  escalate() / notify_on_call()  (emergency path)
```

**From Registration (input):** the moment registration finishes, it emits
`registration.completed`. Triage's subscriber (`triage/apps.py`) reacts by
pre-loading a pending assessment from the patient's intake symptoms — protocol
already selected, symptoms already recorded — so the patient never has to describe
their symptoms twice. If those intake symptoms already trip a red flag, `escalate()`
runs immediately, before the patient ever opens the triage chat.

**To Scheduling (the most common destination):** `same_day` / `24_48h` / `routine`
dispositions all route here. Scheduling's subscriber sends a booking invitation
worded to match the urgency ("today," "within 24–48 hours," "at a convenient time").

**To Referrals:** when the AI sets `route_hint = "specialist"`, referrals'
subscriber auto-creates a **draft** referral straight from the assessment — a
physician still has to accept it before anything moves forward.

**To Prior Authorization:** when `route_hint = "diagnostics"`, prior auth's
subscriber opens an imaging treatment order and immediately starts the
authorization-detection check.

**Two routes exist on paper but currently go nowhere** (a documented, known gap, not
a bug): `route_hint = "meds_issue"` should reach Refills and `"preventive"` should
reach Care Gaps, but neither agent ever subscribed to `triage.disposition`. The event
still fires and is logged — it's just that nothing acts on it yet.

**From Front Desk (borrowed machinery, not an event):** when the after-hours front
desk agent detects emergency symptoms in any channel (SMS, WhatsApp, chat), it does
not reinvent an emergency path — it directly creates a triage `EscalationAlert` and
calls triage's own `notify_on_call()`, the same function triage uses internally.

---

## 4. What the patient/staff actually see

- **Patient side** (`/api/triage/assessments/`): start an assessment with free-text
  symptoms, answer one question at a time, and either get escalated mid-way (with the
  fixed `EMERGENCY_MESSAGE` telling them to call 911 / go to the ER) or reach a
  completion payload with the disposition, a plain-English explanation
  (`EXPLANATION_FOR`), and `ui_hints.offer_booking` — the flag the frontend uses to
  show a "Book an appointment" prompt for anything bookable.
- **Staff side** (`/api/staff/triage/...`, admin-only):
  - An escalation queue (`EscalationListAPIView`) staff can filter by status and
    acknowledge (`EscalationAckAPIView`).
  - An analytics endpoint (`TriageAnalyticsAPIView`) reporting assessment counts,
    the acuity distribution, escalation rate, average time to finish an assessment,
    and — as a proxy for "did the urgent case actually get seen" — what fraction of
    same-day dispositions turned into a real, non-cancelled appointment.

---

## 5. Worked example — traced from a real chat (patient #66, "Maroti")

This is not a hypothetical — it's what the database actually shows for a real UI
registration chat, so you can see exactly how far triage got and where it stopped.

1. During registration, the patient reported symptoms "**extreme headache, nausea**"
   (captured into `Conversation(id=108).agent_context["intake"]`).
2. Registration finished → `registration.completed` fired
   (`EventLog #151`, `{"patient_id": 66, "identity_verified": true}`).
3. Triage's subscriber (`triage/apps.py`) reacted **silently** — no API call, no chat
   message, just a background event handler — and created
   `TriageAssessment #65`:
   - `clinical_protocol`: **"Headache"** (auto-matched from the reported symptoms)
   - `reported_symptoms`: `{"text": "extreme headache, nausea", "source": "registration_intake", "answers": []}`
   - `status`: **"pending"**
4. The red-flag screen ran on "extreme headache, nausea" and found nothing on the
   emergency keyword list (things like "worst headache of my life," sudden vision
   loss, or slurred speech would have tripped it) — so no `escalate()`, no alert.
5. **That's where it stopped.** The assessment is still `pending` in the database
   right now, with `acuity: "minimal"` and `disposition: "self_care"`. Those two
   fields are important to read correctly: **they are placeholder defaults written
   the moment the row is created** (`triage/apps.py`), not a real clinical verdict —
   `assign_acuity` (the actual scoring function) never ran, because that only happens
   after `SubmitAnswerAPIView` receives every one of the protocol's follow-up
   question answers. In this session, the patient's registration handed off straight
   into the **scheduling** auto-booking flow (see `PATIENT_CHAT_FLOW.md`), not into
   the `/triage` chat — so the "Headache" protocol's actual questions (temperature?
   how long? any vision changes?) were never asked, and `route_disposition` never
   fired. No `triage.disposition` event exists for assessment #65.

**What this demonstrates:** triage's registration hook does real, useful work even
when the patient never visits the triage page — it pre-classifies the complaint and
clears (or doesn't clear) the emergency screen immediately — but the acuity/disposition
scoring, and the handoff to Scheduling/Referrals/Prior Auth, only happens once the
patient actually completes the interview. Pre-loading and scoring are two separate
steps, and only the first one is automatic.

For comparison, here is what *would* have happened if the patient had continued into
`/triage` and answered its questions with, say, a temperature of 104°F: the protocol's
own rule ("temp ≥ 103°F → high") would set `rule_acuity = "high"`; `assign_acuity`
would finalize `acuity = "high"`, `disposition = "same_day"`; `route_disposition`
would emit `triage.disposition` with `route_to = "scheduling"`; and scheduling's
subscriber would notify the patient "you should be seen today" with
`ui_hints.offer_booking = True` in the response. And if any answer along the way had
been "actually I can't feel the left side of my face," the red-flag screen would have
caught it on that single answer — no rules engine needed, no waiting for the
interview to finish — and jumped straight to `escalate()`.

---

*Sources: `backend/triage/services.py`, `backend/triage/views.py`,
`backend/triage/apps.py`, `backend/triage/models.py`, `backend/core/safety.py`,
`backend/core/events.py`. See also `AGENT_RELATIONSHIPS.md` for how this fits with
all 9 agents, and `PATIENT_CHAT_FLOW.md` for the registration side of the handoff.*
