# `handle_registration_message()` — explained from zero

This document explains **one function**: `handle_registration_message()` in
`backend/registration/ai/handler.py`. It assumes you know basic Python and
nothing else. Read it top to bottom.

---

## 1. First, the basics you need

### What is this function's job?

MediAssist registers new patients **through a chat window**. The patient
types messages like a WhatsApp conversation:

> Patient: "Hi, I want to register. I'm Riya Sharma."
> Bot: "Nice to meet you Riya! What's your date of birth?"

Every time the patient sends **one message**, the chat endpoint calls
`handle_registration_message()` **once**. That one call is called a
**"turn"**. The function's job for each turn is:

1. **Read** what the patient just said and pull out useful data (name, DOB, symptoms...).
2. **Save** that data in the right place.
3. **Decide** which step of registration we are on (the "stage").
4. **Return** that decision so the chat endpoint knows what to reply and what to show on screen.

Important: this function does **not** write the friendly reply text the
patient sees. Another AI call (in `views.py`) does that afterwards, using
this function's output as instructions.

### The two "brains" — who decides what?

There are two decision-makers, and they deliberately have different powers:

| Decision | Who makes it | Why |
|---|---|---|
| "What should I ask the patient next?" | **The AI model** | It's good at natural conversation |
| "Which stage is registration in? Can we move on?" | **This Python code** | The AI must never be able to skip identity verification or insurance, no matter what it (or the patient) claims |

This is what the comments call **"model-driven, state-gated"**. The AI
drives the conversation; the code is the gatekeeper.

### What is `Conversation` and `agent_context`?

- **`Conversation`** is a database row representing this chat session. It has
  two fields this function cares about:
  - `conversation.patient` — a link to the `Patient` record, **empty (`None`)
    at the start** because we don't know who's talking yet.
  - `conversation.agent_context` — a JSON field, basically a free-form
    **scratchpad / notebook** where the function jots things down between
    turns. Remember: the function runs once per message and then forgets
    everything — this scratchpad is how it "remembers" across turns.

Things stored in the scratchpad (`ctx` in the code):

| Key | What it holds |
|---|---|
| `pending_demographics` | Name/DOB/phone collected so far, **before** a patient record exists |
| `duplicate_candidate_ids` | IDs of existing patients that look suspiciously similar |
| `intake` | Health answers (symptoms, medications...) collected so far |
| `pending_insurance` | Insurance details the patient typed in chat |
| `registration_stage` | The stage decided last turn |
| `active_agent` / `handoff` | Set at the end, to pass the chat to the scheduling agent |

### What is `conversation_history`?

A list of every message so far, in the format AI models expect:

```python
[
  {"role": "user", "content": "Hi, I'm Riya Sharma"},
  {"role": "assistant", "content": "Nice to meet you! What's your DOB?"},
  {"role": "user", "content": "12 March 1990, phone 9876543210"},
]
```

The **whole** history is sent to the AI every turn, so the AI always has
full context.

### What is a "tool call" (`call_tool`)?

Normally an AI replies with free text. A **tool call** forces it to reply
with **structured data matching a fixed schema** instead — like making it
fill out a form rather than write an essay. Our form is called
`record_registration_data` (defined in `ai/tools.py`). The AI fills in
whichever fields the patient just mentioned and leaves the rest out.

Example: patient says *"I'm Riya Sharma, allergic to penicillin"* → the AI
returns:

```python
{
  "first_name": "Riya",
  "last_name": "Sharma",
  "allergies": ["penicillin"],
  "next_question_topic": "date_of_birth",   # always present
  "registration_complete": False,           # always present
}
```

That dict is what the code calls `extracted`.

---

## 2. The stages (the "state gate")

Registration always moves through these stages, **in this order**, and
the *code* checks real database facts before allowing the next one:

```
demographics ──▶ identity_verification ──▶ insurance ──▶ intake ──▶ done
      │              (OTP code)          (card upload)  (health Qs)
      ▼
duplicate_hold  (side track: a lookalike patient exists → staff must resolve)
```

| Stage | Meaning | The fact the code checks |
|---|---|---|
| `demographics` | Still collecting name/DOB/phone | `conversation.patient` is `None` |
| `duplicate_hold` | A similar patient already exists; paused for staff | `duplicate_candidate_ids` in scratchpad |
| `identity_verification` | Patient must prove identity via OTP code | `patient.identity_verified` is `False` |
| `insurance` | Need insurance on file | No `InsurancePolicy` row for this patient in the DB |
| `intake` | Asking health questions | AI hasn't set `registration_complete: True` yet |
| `done` | Everything finished | All of the above passed |

Notice: three of the checks are **database lookups**, not AI opinions. If
the AI says "registration complete!" but there's no insurance row, the
gate still says `insurance`. The AI physically cannot skip steps.

---

## 3. The function, line by line

Here is the flow, matched to the code sections:

### Step 0 — Ask the AI to extract data (line 49)

```python
extracted = call_tool(system=..., messages=conversation_history, tool=...)
```

Send the full chat to the AI, get back the filled-in "form" (`extracted`).

### Step 0.5 — Refresh the patient (lines 55–60)

```python
patient.refresh_from_db()
```

Why? The OTP verification and insurance upload happen through **separate
API endpoints**, between chat turns. They change the patient row in the
database. Without a refresh, this function would look at an old in-memory
copy that still says `identity_verified = False` and get stuck asking for
OTP forever. (This was a real bug, found in live testing.)

### Step 1 — Save demographics (lines 63–86)

Two situations:

**A patient record already exists** → just save any new demographic
fields onto it via `services.create_or_update_patient_record()`.

**No patient record yet** → be careful:

1. Merge whatever came in this turn into the scratchpad's
   `pending_demographics` (data accumulates across turns).
2. Do we have the minimum 4 fields — first name, last name, DOB, phone?
   - **No** → do nothing more; keep collecting.
   - **Yes** → run `services.find_matching_patients()` (duplicate check):
     - `"existing"` (same phone + same DOB) → same person came back;
       reuse and update their existing record.
     - `"possible_duplicate"` (same DOB + very similar last name, different
       phone) → **do NOT create anything**. Store the suspect IDs and let a
       staff member decide. Creating a second record for the same human is
       one of the worst data errors in healthcare.
     - `"new"` → safe; create a fresh patient record and link it to the
       conversation.

### Step 2 — Accumulate health answers (lines 88–97)

Symptoms, medical history, medications, allergies, family history are
**lists**. Each turn, new items are appended to the scratchpad's `intake`
and duplicates removed (that's the `dict.fromkeys` trick — it deduplicates
while keeping the original order). `lifestyle` is a dict and gets merged.

Key design choice: intake data is **not written to the database yet** —
only into the scratchpad. It's written once, at the very end, when
registration completes. Until then it's a draft.

### Step 3 — Insurance typed in chat (lines 99–108)

If the patient *types* their insurance info ("I have Star Health, policy
SH-889900"), it's parked in the scratchpad as `pending_insurance`. The
real `InsurancePolicy` database row is **not** created here — the card
upload or the insurance endpoint creates it, because those flows know the
coverage dates (which the chat usually doesn't).

### Step 4 — The state gate (lines 110–132)

A simple `if/elif` chain, checked top to bottom (first match wins):

```python
if patient is None:                      # → demographics or duplicate_hold
elif not patient.identity_verified:      # → identity_verification + hint "otp_required"
elif no InsurancePolicy row exists:      # → insurance + hint {"upload": "insurance_card"}
elif AI hasn't said complete:            # → intake
else:                                    # → done
```

The `ui_hints` are little flags for the frontend: `"otp_required"` means
"show the 6-digit OTP input boxes now"; `{"upload": "insurance_card"}`
means "show the file-upload button now".

**The `done` branch** does the finishing work:

1. Write the accumulated `intake` draft to the real patient record.
2. `services.complete_registration(patient)` — flips the status and fires
   a `registration.completed` event (which triggers a "you can now book"
   notification).
3. Hand off the conversation: `active_agent = "scheduling"`, with the
   symptoms included, so the scheduling agent can suggest a doctor
   **without re-asking who the patient is**.

### Step 5 — Save and return (lines 134–145)

The scratchpad is saved back to the database, and the function returns:

```python
{
  "stage": "insurance",                        # where we are
  "next_question_topic": "insurance_provider", # AI's suggestion for what to ask
  "registration_complete": False,
  "ui_hints": [{"upload": "insurance_card"}],  # what the UI should show
  "patient_id": 57,                            # or None early on
  "extracted": {...},                          # raw AI output (debugging)
}
```

The chat endpoint uses this to (a) instruct the second AI call that writes
the visible reply, and (b) tell the frontend what widgets to show.

---

## 4. A full worked example, turn by turn

Watch three things change each turn: the **scratchpad**, the **database**,
and the **stage**.

### Turn 1 — "Hi, I'd like to register. My name is Riya Sharma."

- AI extracts: `first_name=Riya, last_name=Sharma`
- No patient exists; only 2 of 4 minimum fields → park them.
- Scratchpad: `pending_demographics = {first_name, last_name}`
- Database: unchanged. **Stage: `demographics`**
- Bot replies (separate AI call): "Nice to meet you, Riya! What's your date of birth?"

### Turn 2 — "12 March 1990, my phone is 9876543210."

- AI extracts: `dob, contact_number`. Now all 4 minimum fields are in.
- Duplicate check runs → no match → **Patient row created (id 57)** and
  linked to the conversation. `pending_demographics` cleared.
- Gate: patient exists, but `identity_verified = False`.
- **Stage: `identity_verification`**, `ui_hints = ["otp_required"]`
- Frontend shows the OTP input boxes; an OTP is sent to her phone.

*(Alternative: if a "Riya Sharma, DOB 1990-03-12" already existed with a
different phone → nothing is created, `duplicate_candidate_ids = [42]`
goes in the scratchpad, **stage: `duplicate_hold`**, staff resolves it.)*

### Between turns — Riya enters the OTP

She types the code into the OTP boxes, which hit `POST /otp/verify` — a
**different endpoint**, not this function. It sets
`identity_verified = True` in the database.

### Turn 3 — "Done, I entered the code."

- `patient.refresh_from_db()` picks up `identity_verified = True` ✓
- Gate: verified ✓, but no insurance row yet.
- **Stage: `insurance`**, `ui_hints = [{"upload": "insurance_card"}]`
- Frontend shows the upload button.

### Turn 4 — "It's Star Health, policy SH-889900" + uploads the card

- The typed info is parked: `pending_insurance = {provider_name, policy_number}`
- The **upload endpoint** (separately) creates the `InsurancePolicy` row
  and runs the eligibility check.
- Next gate check: insurance row exists ✓ → **Stage: `intake`**
- Bot starts health questions: "What brings you in today?"

### Turn 5 — "Headache and fever for two days. I take metformin daily."

- Scratchpad: `intake = {symptoms: [headache, fever], medications: [metformin]}`
- Database: **still nothing written** for intake — it's a draft.
- AI hasn't said complete → **Stage: `intake`** (keep asking)

### Turn 6 — "No allergies, nothing else."

- AI sets `registration_complete: True` (it judges the intake finished).
- Gate reaches the final `else`:
  1. Intake draft written to Riya's record ✓
  2. `complete_registration()` → status `complete`, event fired ✓
  3. Handoff: `active_agent = "scheduling"`, symptoms travel along ✓
- **Stage: `done`**
- Bot: "You're all set, Riya! Since you mentioned headache and fever,
  would you like to book an appointment?" — and the scheduling agent
  takes over from the next message, without re-verifying identity.

---

## 5. The three ideas to remember

1. **One call = one turn.** The function runs once per patient message:
   extract → save → decide stage → return.
2. **The scratchpad (`agent_context`) is the memory.** Partial data
   accumulates there across turns; permanent records are only created at
   safe moments (after the duplicate check; intake only at completion).
3. **The code is the gatekeeper, not the AI.** The stage comes from
   database facts (patient exists? OTP verified? insurance row exists?),
   so the flow can never be talked into skipping a step.

## 6. The actual code, line by line

Open `handler.py` next to this section. Every line (or small group of
lines) is shown, then explained in plain English.

### The imports (lines 10–17)

```python
from langsmith import traceable
```
LangSmith is a tracing/observability service. `traceable` is a decorator
we'll use to record every run of this function so you can inspect it later
in a dashboard (what went in, what came out, how long it took).

```python
from core.ai import call_tool
```
The project's single "door" to the AI provider. You give it a system
prompt, message history, and a tool schema; it returns the filled-in dict.
Which provider (OpenAI/Anthropic/Ollama) is decided by `.env`, not here.

```python
from core.models import Conversation
```
Only imported for the type hint on the function signature.

```python
from registration import services
```
All database writes go through `services.py` (duplicate check, record
creation, completion). This file never touches the DB directly for writes.

```python
from registration.ai.prompts import REGISTRATION_SYSTEM_PROMPT
from registration.ai.tools import RECORD_REGISTRATION_DATA_TOOL
```
The AI's standing instructions and the "form" schema it must fill in.

```python
from registration.models import InsurancePolicy
```
Needed for one read-only check in the state gate: "does this patient have
an insurance row yet?"

### The constants (lines 19–35)

```python
DEMOGRAPHIC_MINIMUM = ("first_name", "last_name", "dob", "contact_number")
```
The 4 fields we must have before it's safe to run the duplicate check and
create a patient record. Fewer than this and we can't reliably tell people
apart.

```python
DEMOGRAPHIC_FIELDS = ("first_name", "last_name", "dob", "contact_number",
                      "email", "address", "emergency_contact",
                      "preferred_language", "preferred_pharmacy")
```
*All* demographic fields the AI might extract — the minimum 4 plus the
nice-to-haves. Used to pick demographics out of the AI's output.

```python
INTAKE_LIST_FIELDS = ("symptoms", "medical_history", "medications",
                      "allergies", "family_history")
```
The health-questionnaire fields that are **lists** (a patient can have
many symptoms). These accumulate turn by turn.

```python
INSURANCE_CHAT_FIELDS = {
    "insurance_provider": "provider_name",
    "insurance_policy_number": "policy_number",
    "insurance_member_id": "member_id",
}
```
A translation table: the AI tool uses names like `insurance_provider`,
but the `InsurancePolicy` model calls that field `provider_name`. This
dict maps tool-name → model-name.

### The decorator and signature (lines 38–39)

```python
@traceable(name="handle_registration_message", run_type="chain")
def handle_registration_message(conversation: Conversation,
                                conversation_history: list[dict]) -> dict:
```
The decorator wraps the function so each run shows up in LangSmith as one
named "chain" span (with the AI call nested inside it). The function takes
the conversation row and the full message history, and returns a plain
dict (described at the end).

### The AI extraction (lines 49–53)

```python
extracted = call_tool(
    system=REGISTRATION_SYSTEM_PROMPT,
    messages=conversation_history,
    tool=RECORD_REGISTRATION_DATA_TOOL,
)
```
The **only AI call in this function**. Send the instructions + whole chat
history, force the model to answer by filling in the
`record_registration_data` form. `extracted` is a dict like
`{"first_name": "Riya", "symptoms": ["fever"], "next_question_topic": "...",
"registration_complete": False}` — fields the patient didn't mention are
simply absent.

### Loading state (lines 55–61)

```python
ctx = conversation.agent_context
```
Pull the scratchpad (a JSON dict) off the conversation. From here on,
`ctx` is the cross-turn memory.

```python
patient = conversation.patient
if patient is not None:
    patient.refresh_from_db()
```
Get the linked patient (may be `None` early on). If there is one,
**re-read it from the database**. Why: the OTP-verify and insurance
endpoints run *between* chat turns and update the patient row. Without
this refresh we'd be looking at a stale copy where
`identity_verified` is still `False`, and the state gate would keep
demanding OTP forever. (Real bug, fixed with this line.)

```python
ui_hints: list = []
```
Start with no UI hints; the state gate appends to this later.

### Section 1 — persist demographics (lines 63–86)

```python
demographics = {f: extracted[f] for f in DEMOGRAPHIC_FIELDS if extracted.get(f)}
```
From the AI's output, keep only the demographic fields that actually have
a value. E.g. `{"first_name": "Riya", "last_name": "Sharma"}`.

```python
if patient is not None:
    if demographics:
        services.create_or_update_patient_record(patient, demographics=demographics)
```
Easy case: we already know who this is → just save any new fields onto
their record (the service handles the transaction + audit trail).

```python
else:
    pending = {**ctx.get("pending_demographics", {}), **demographics}
    ctx["pending_demographics"] = pending
```
No patient yet. Merge this turn's fields into whatever was collected on
earlier turns (`{**old, **new}` = "old dict updated with new dict") and
put the merged result back in the scratchpad.

```python
    if all(pending.get(f) for f in DEMOGRAPHIC_MINIMUM):
```
"Do we now have all 4 minimum fields?" If not, this whole block is
skipped and we just keep collecting next turn.

```python
        full_name = f"{pending['first_name']} {pending['last_name']}"
        match, candidates = services.find_matching_patients(
            full_name, pending["dob"], pending["contact_number"]
        )
```
Run the duplicate check. It returns a verdict string and a list of
matching patients: `("existing", [that patient])`,
`("possible_duplicate", [lookalikes])`, or `("new", [])`.

```python
        if match == "possible_duplicate":
            ctx["duplicate_candidate_ids"] = [p.id for p in candidates]
```
Lookalike found (same DOB, similar name, different phone). **Create
nothing.** Just note the suspects' IDs in the scratchpad — the state gate
below will see this key and hold the flow for staff.

```python
        else:
            existing = candidates[0] if match == "existing" else None
            patient = services.create_or_update_patient_record(
                existing, demographics=pending
            )
            conversation.patient = patient
            ctx.pop("pending_demographics", None)
```
Safe to proceed. If the verdict was `"existing"` (same phone + DOB — it's
definitely them), pass their record in so it gets **updated**; otherwise
pass `None` so a **new** record is created. Link the patient to the
conversation and delete the now-unneeded pending pile from the scratchpad.

### Section 2 — accumulate intake (lines 88–97)

```python
intake = ctx.get("intake", {})
```
Load the intake draft collected so far (empty dict on the first turn).

```python
for field in INTAKE_LIST_FIELDS:
    if extracted.get(field):
        merged = intake.get(field, []) + extracted[field]
        intake[field] = list(dict.fromkeys(merged))
```
For each list field the AI extracted this turn: append the new items to
the existing list, then deduplicate. `dict.fromkeys(merged)` builds a dict
whose keys are the list items — dict keys are unique and keep insertion
order, so turning it back into a `list` removes duplicates without
shuffling. `["fever"] + ["fever", "cough"]` → `["fever", "cough"]`.

```python
if extracted.get("lifestyle"):
    intake["lifestyle"] = {**intake.get("lifestyle", {}), **extracted["lifestyle"]}
```
`lifestyle` is a dict (smoking, alcohol, exercise...), not a list, so it's
merged key-by-key instead of appended.

```python
if intake:
    ctx["intake"] = intake
```
Save the draft back to the scratchpad. Note: **not** to the patient record
— that only happens at completion.

### Section 3 — insurance typed in chat (lines 102–108)

```python
chat_insurance = {
    model_field: extracted[tool_field]
    for tool_field, model_field in INSURANCE_CHAT_FIELDS.items()
    if extracted.get(tool_field)
}
```
Walk the translation table from earlier: for each insurance field the AI
extracted, store its value under the *model's* field name. So
`extracted["insurance_provider"]` becomes
`chat_insurance["provider_name"]`.

```python
if chat_insurance:
    ctx["pending_insurance"] = {**ctx.get("pending_insurance", {}), **chat_insurance}
```
Park it in the scratchpad, merged with anything from earlier turns. The
actual `InsurancePolicy` row is created by the upload/insurance endpoints,
which also know the coverage dates.

### Section 4 — the state gate (lines 110–132)

An `if/elif` chain checked top to bottom; the **first** true condition
wins, which is what enforces the stage order.

```python
if patient is None:
    stage = "duplicate_hold" if ctx.get("duplicate_candidate_ids") else "demographics"
```
Still nobody linked. If the duplicate check flagged lookalikes, hold for
staff; otherwise we're just still collecting demographics.

```python
elif not patient.identity_verified:
    stage = "identity_verification"
    ui_hints.append("otp_required")
```
Patient exists but hasn't proven identity → OTP stage, and tell the
frontend to show the code-entry boxes.

```python
elif not InsurancePolicy.objects.filter(patient=patient).exists():
    stage = "insurance"
    ui_hints.append({"upload": "insurance_card"})
```
Identity done, but a database query says there's no insurance row yet →
insurance stage, show the upload button. `.exists()` is a cheap "is there
at least one row?" query.

```python
elif not extracted.get("registration_complete"):
    stage = "intake"
```
Everything structural is done; we're in the health-questions phase until
the AI judges the interview finished. This is the **one** place the AI's
opinion matters for the stage — and only after all the hard database
checks above have passed.

```python
else:
    if ctx.get("intake"):
        services.create_or_update_patient_record(patient, intake=ctx["intake"])
    services.complete_registration(patient)
```
The finish line. Write the accumulated intake draft to the real record,
then flip the patient's status to complete (which also fires the
`registration.completed` event → the patient gets a "you can now book"
notification).

```python
    ctx["active_agent"] = "scheduling"
    ctx["handoff"] = {
        "from": "registration",
        "symptoms": ctx.get("intake", {}).get("symptoms", []),
    }
    stage = "done"
```
Hand the conversation to the scheduling agent: from the next message,
scheduling answers instead of registration. The symptoms ride along in
the handoff so booking can start with context ("you mentioned fever —
shall I find you a general physician?") without re-asking anything.

### Section 5 — save and return (lines 134–145)

```python
ctx["registration_stage"] = stage
conversation.agent_context = ctx
conversation.save(update_fields=["patient", "agent_context"])
```
Record the decided stage in the scratchpad, put the scratchpad back on the
conversation, and save. `update_fields=` tells Django to write only these
two columns — safer and faster than rewriting the whole row.

```python
return {
    "stage": stage,
    "next_question_topic": extracted.get("next_question_topic"),
    "registration_complete": stage == "done",
    "ui_hints": ui_hints,
    "patient_id": patient.id if patient else None,
    "extracted": extracted,
}
```
The result the chat endpoint consumes:

- `stage` — the gate's verdict; drives the reply-writing instructions.
- `next_question_topic` — the AI's suggestion for what to ask next.
- `registration_complete` — derived from the stage (`done`), **not**
  copied from the AI's claim — one more place the code stays in charge.
- `ui_hints` — widgets for the frontend (OTP boxes / upload button).
- `patient_id` — `None` until a record is linked, then the real id.
- `extracted` — the raw AI output, handy for debugging and tests.

---

## Glossary

| Term | Meaning |
|---|---|
| Turn | One patient message + one run of this function |
| Extraction | The AI pulling structured fields out of free-form chat |
| Tool call | Forcing the AI to answer as structured data matching a schema |
| State gate | The `if/elif` chain that picks the stage from database facts |
| Scratchpad / `agent_context` | JSON field on the conversation used as cross-turn memory |
| `ui_hints` | Flags telling the frontend which widget to show (OTP boxes, upload button) |
| OTP | One-time password — the 6-digit code proving the phone belongs to the patient |
| Duplicate hold | Pause when an existing patient looks like the same person; staff decides |
| Handoff | Passing the conversation to the scheduling agent when registration is done |
| Intake | The health questionnaire part (symptoms, medications, allergies...) |
