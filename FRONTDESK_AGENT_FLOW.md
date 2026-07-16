# How the Front Desk Agent (Agent 9) Works

This explains, in plain English, what the after-hours front desk agent actually does —
from a patient's free-text message arriving through any channel, to it landing with the
right specialist agent or a human — and how it fits with the rest of the system. Every
claim below is backed by a specific line in `backend/frontdesk/services.py`,
`backend/frontdesk/ai.py`, or `backend/frontdesk/views.py`.

---

## 1. The one thing to remember: Front Desk is a router, not a specialist

Every other agent in this system *does* something clinical — triage assesses, refills
approves prescriptions, referrals books specialists. **Front Desk does none of that.**
Its entire job is: understand what the patient wants, prove who they are if it matters,
and get the request to the right place — either an existing agent's data, or a human,
never by guessing a clinical answer itself.

It exists because a patient contacting the clinic at 11pm doesn't know (and shouldn't
need to know) that "is my referral approved" is a different agent than "can I get a
refill." One door, nine rooms behind it.

---

## 2. The three deterministic pillars everything else stands on

These three pieces of code-owned logic exist *before* any AI is involved, and the AI
layer (added later, Phase 4) sits on top of them without changing them:

### The auth gate (`start_authentication` / `authenticate_session`)
A session starts **anonymous**. Anything that touches patient data is queued, not
answered, until the patient proves who they are with phone number + date of birth,
then an OTP (reusing Registration's exact OTP machinery — same codes, same hashing).

The gate is deliberately paranoid about leaking information: whether the phone number
doesn't exist, or it exists but the DOB doesn't match, the patient sees the **exact
same message** — `"We couldn't verify those details."` Telling them "no account with
that phone number" would let an attacker probe which phone numbers are registered
patients; telling them "DOB doesn't match" would confirm the phone number IS a real
patient. Neither leak is acceptable, so both fail identically.

### The agent registry (`REGISTRY`, a plain dict)
One dictionary maps each intent name to which agent owns it, which function handles
it, and whether it needs authentication:

```python
REGISTRY = {
    "appointment":     AgentRoute("scheduling", _handle_appointment),
    "refill":          AgentRoute("refills", _handle_refill),
    "referral_status": AgentRoute("referrals", _handle_referral_status),
    "pa_status":       AgentRoute("priorauth", _handle_pa_status),
    "care_gap":        AgentRoute("caregaps", _handle_care_gap),
    "symptoms":        AgentRoute("triage", _handle_symptoms),
    "faq":             AgentRoute("knowledge", _handle_faq, requires_auth=False),
    "other":           AgentRoute("staff", _handle_other, requires_auth=False),
}
```
Adding a new agent to the front desk is one line in this dict — the AI router's list of
valid intents is generated **from this same dictionary** (`INTENTS = list(REGISTRY)`),
so the model automatically learns about a new agent the moment it's registered here;
nobody has to update a prompt by hand.

Only `faq` and `other` opt out of authentication — clinic hours and "I don't know what
this is, a human will look" are not patient data.

### The mandatory escalation list (`MANDATORY_ESCALATION_PRIORITIES`)
Four categories can **never** be resolved by automation, no matter how confident the AI
is, and their priority is fixed — a caller can't downgrade it:

| Category | Priority | Example |
|---|---|---|
| `mental_health` | critical | crisis language |
| `stroke` | critical | suspected stroke symptoms |
| `insurance_dispute` | high | a disputed claim or charge |
| `controlled_substance` | high | refill request for opioids, benzodiazepines, stimulants |

This list is plain Python data, checked in code (`if category in MANDATORY_ESCALATION_PRIORITIES`)
— the AI can *suggest* a category, but code decides whether that suggestion is honored,
exactly like triage's acuity rules.

---

## 3. The AI layer: two narrow jobs, nothing more

### Job 1 — the router (`route_message`)
One model call classifies a single patient message into a list of **intents** (a
message can carry more than one — "refill my BP meds and book my checkup" is two
separate intents, handled as two separate dispatches), plus two safety flags:

- `emergency_symptoms_detected` — a second, AI-based check for life-threatening
  symptoms phrased indirectly, layered **on top of** (never instead of) the
  deterministic red-flag regex.
- `mandatory_escalation_category` — the model's guess at which of the four fixed
  categories applies, or `null`.

The router's tool description is deliberately specific about ambiguous terms — for
example it spells out that `pa_status` means "has **insurance** approved a test/scan/
procedure," not "where does my specialist referral stand" (that's `referral_status`),
and it names actual controlled-substance drug classes (opioids, benzodiazepines like
alprazolam/Xanax, stimulants) so the model doesn't miss an indirect mention.

**Two safety rules the router itself enforces by construction:** every `intent` value
must be one of the registry's real keys (the JSON schema's `enum` is generated from
`INTENTS`, so the model literally cannot invent an intent that doesn't exist), and code
re-checks this anyway when dispatching (`if item.get("intent") in REGISTRY`) — belt and
suspenders.

### Job 2 — grounded FAQ answering (`answer_faq`)
For clinic-fact questions, the model is handed the retrieved knowledge articles and told
explicitly: answer using **only** these articles, and if they don't actually contain the
answer, say so (`answered: false`) rather than guessing. This is the same "never invent
a fact" discipline triage uses for clinical rules — the model is a phrasing layer over
retrieved truth, not a source of truth itself.

**If the AI is unreachable, the patient still gets an answer:** the FAQ handler catches
any exception and falls back to the top retrieved article's raw text; the router catches
any exception and creates a `manual_review` staff task instead of leaving the patient
hanging. Neither AI call is ever allowed to block a response.

---

## 4. One message, start to finish (`handle_frontdesk_message`)

This is the fixed order every single message goes through, and the order is the whole
point — a faster or "smarter" ordering would be less safe:

```
1. Deterministic red-flag regex on the raw text        (before any AI call at all)
2. route_message()                                     (classify intent(s) + flags)
3. Model's emergency_symptoms_detected flag             (second net, AI-based)
4. mandatory_escalation_category                        (code decides whether to honor it)
5. Each remaining intent dispatched through the registry, in the order the patient raised them
6. Results folded into one combined reply
```

Step 1 can short-circuit everything else — a message like "I can't breathe" never
reaches the router at all; it goes straight to the emergency script. Step 3 exists
because the regex only catches phrases it knows; the model catches things phrased
differently ("my chest has felt tight and heavy since this morning").

### The emergency short-circuit (`_emergency_result`)
Whether triggered by the regex or the model's flag, the patient sees the exact same
fixed script and gets the exact same real alert — the only difference is *who* gets
paged:

- **Authenticated patient:** a real triage `EscalationAlert` is created and the on-call
  clinician is paged via `notify_on_call()` — the identical machinery Agent 3 (Triage)
  uses for its own emergencies. Front Desk doesn't reinvent this; it borrows it.
- **Anonymous patient:** there's no patient to attach an `EscalationAlert` to (the model
  requires one), so a **critical** `manual_review` staff task is created instead. The
  patient-facing message is identical either way — an unauthenticated caller in a real
  emergency is never told to "please verify your identity first."

### The auth gate mid-conversation
If an intent needs authentication and the session isn't authenticated yet, it's **not
dropped and not answered** — it's appended to `pending_intents` on the session (a JSON
list), and the patient is asked for their phone number and DOB. The moment
`authenticate_session` succeeds, `resume_pending_intents()` dispatches everything that
was queued, in the order originally asked, then clears the queue. A patient who asks
three things anonymously and then verifies gets all three answered, in order, without
repeating themselves.

### Every dispatch is audited (`IntentRoute`)
Every time an intent actually reaches a handler, an `IntentRoute` row is written up
front (`status="routed"`), then updated to `completed` or `escalated` once the handler
returns — this is the row the analytics endpoint later counts. A handler that raises an
exception is caught, turned into a `manual_review` staff task, and the route is marked
`escalated` — the patient always gets a coherent reply, even when something breaks.

---

## 5. What the eight handlers actually do

Six of the eight registry handlers are **read-only summaries into another agent's own
data** — Front Desk never writes clinical state itself, it reads and reports:

| Intent | Reads from | Behavior worth noting |
|---|---|---|
| `appointment` | Scheduling's `Appointment` | Lists upcoming booked visits |
| `refill` | Refills' `Prescription` | **If every active prescription is a controlled substance**, it refuses to auto-handle it — creates a `controlled_substance` staff task instead, even though `refill` itself doesn't require the mandatory-category flag to be set by the router. Two independent paths can reach the same protection. |
| `referral_status` | Referrals' `Referral` | Last 5 referrals and their status |
| `pa_status` | Prior Auth's `AuthorizationRequest` | Last 5 authorization requests |
| `care_gap` | Care Gaps' `open_gaps_for()` | Same open-gap logic Care Gaps itself uses |
| `symptoms` | — | **Doesn't try to triage anything itself.** Returns `{"handoff": "triage"}` — a real guided assessment is a multi-turn protocol interview that Agent 3 owns; Front Desk just points the way. |
| `faq` | Front Desk's own `KnowledgeArticle` search | Covered above |
| `other` | — | Anything unclassified becomes a `manual_review` staff task — the deliberate catch-all so nothing silently vanishes |

---

## 6. The knowledge layer (`search_knowledge`)

FAQ retrieval is genuine Postgres full-text search (`SearchVectorField` +
`SearchRank`), not a keyword list, and it tries **two passes**:

1. **Websearch-style query** (all terms should hit) — precise for natural phrasings
   like "are you open on Sundays?"
2. **Any-term OR fallback** — patients often use verbs the articles never use
   ("do you **take** Star Health" vs. an article written as "we **accept**..."), so if
   the strict pass finds nothing, a looser any-word match still gets tried before
   giving up.

Only if **both** passes come back empty does the system admit "we genuinely don't
know" and open an `unanswered_question` staff task — never an improvised answer about
clinic policy.

---

## 7. Reaching Front Desk from anywhere (channel adapters)

Front Desk is explicitly the "one front door for everything" agent (FR-A8). Two ways in:

- **Web chat** (`POST /api/frontdesk/chat`) — a signed session token (same pattern as
  Registration/Triage), one endpoint handling four request shapes: starting
  authentication, verifying an OTP, dispatching an explicit intent, or free text that
  goes through the full AI router.
- **SMS/WhatsApp** (`handle_channel_message`) — these channels carry no signed token,
  so the **sender's raw phone number** is the correlation key instead: the same number's
  next message resumes the *same* session, including its auth state and anything still
  queued — rather than starting over every text. Critically, **arriving from a known
  phone number is not proof of identity** — a protected intent from that channel still
  hits the exact same auth gate as web chat. Convenience of channel never weakens the
  gate.

This channel adapter also catches a specific gap in Agent 7 (Outreach): if an inbound
SMS/WhatsApp reply doesn't match any running campaign, Outreach's webhook falls through
to `handle_channel_message` instead of returning a 404 — so a stray text message always
reaches *someone*, even if it wasn't a reply to an active campaign.

---

## 8. What staff actually see

- **The staff task queue** (`/api/staff/frontdesk/tasks/`) — every escalation, sorted
  **critical → high → normal**, then oldest-first within each priority. Staff can claim
  a task (`claimed_by`) and resolve it (`resolved_at` stamped).
- **Analytics** (`/api/staff/frontdesk/analytics/`) — session volume, intents routed,
  and the automation rate computed directly from `IntentRoute.status`: **automation
  rate is just "how often was `status="completed"` instead of `"escalated"`"** — the
  exact same audit trail every dispatch already writes, not a separately-tracked metric.
  It also reports the top 5 request types and the average time a staff task waited
  before being resolved — honestly scoped to "how long did the human part take,"
  since nothing on `Message` carries enough data to measure true end-to-end patient
  latency.
- **No direct CRUD for `PatientSession` or `IntentRoute`** — deliberately. Those are
  conversation state written only through the real chat flow; a raw write endpoint
  would let someone bypass the auth gate entirely.

---

## 9. How Front Desk connects to the other 8 agents

```
                 ┌───────────────────────────┐
   any channel ─►│   9 FRONT DESK (the hub)  │
 (web/SMS/WA)    └─────────────┬─────────────┘
                                │ dispatch_intent() — direct calls, not events
        ┌───────────┬──────────┼───────────┬───────────┬────────────┐
        ▼           ▼          ▼           ▼           ▼            ▼
  1 SCHEDULING  4 REFILLS  5 REFERRALS  6 PRIORAUTH  8 CAREGAPS  3 TRIAGE
  (appointments) (refills)  (referral    (auth        (open gaps) (handoff only —
                             status)      status)                  "let's do a
                                                                    few questions")

  borrowed, not routed:
   9 → 2 REGISTRATION  (reuses create_otp / verify_otp for its own auth gate)
   9 → 3 TRIAGE         (reuses EscalationAlert + notify_on_call for emergencies)
   7 OUTREACH → 9       (unmatched inbound SMS/WhatsApp falls through here)
```

Unlike Triage or Registration, **Front Desk's connections to other agents are direct
function/data calls, not events on the bus** — it needs an answer inside the same
request-response cycle ("here are your referrals"), which the event bus's fire-and-forget
model doesn't fit. The two exceptions are genuinely borrowed machinery: it reuses
Registration's OTP functions verbatim for its own identity gate, and reuses Triage's
`EscalationAlert` + `notify_on_call()` verbatim for its own emergency path, rather than
maintaining two different implementations of the same safety-critical logic.

---

## 10. Worked example

A brand-new, anonymous WhatsApp message arrives: **"i need my bp meds refilled and also
when is my next appointment, also do you accept star health insurance"**

1. `handle_channel_message("whatsapp", "+91...", text)` finds no existing session for
   that number, creates a new anonymous `Conversation` + `PatientSession`.
2. Red-flag regex: clean, nothing life-threatening here.
3. `route_message()` returns **three intents** — `refill` ("BP meds"), `appointment`
   ("next appointment"), `faq` ("star health insurance") — and no emergency/mandatory
   flags.
4. `refill` and `appointment` both require auth; the session is anonymous, so **both**
   get appended to `pending_intents` and the patient is asked to verify. `faq` doesn't
   require auth, so it's dispatched immediately — the knowledge base has an article on
   accepted insurers, so the FAQ answer comes back in the very same reply.
5. Patient replies with phone + DOB, then the OTP. `authenticate_session` succeeds →
   `resume_pending_intents()` fires the two queued intents in original order: refill
   status, then upcoming appointments.
6. Patient gets one coherent reply covering all three original asks, despite having
   started completely anonymous — and every one of those three dispatches left an
   `IntentRoute` row for the analytics dashboard to count later.

---

*Sources: `backend/frontdesk/services.py`, `backend/frontdesk/ai.py`,
`backend/frontdesk/views.py`, `backend/frontdesk/models.py`,
`backend/outreach/views.py` (the webhook fallback). See also
`AGENT_RELATIONSHIPS.md` for how this fits with all 9 agents, and
`TRIAGE_AGENT_FLOW.md` for the emergency machinery this agent reuses.*
