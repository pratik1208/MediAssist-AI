# `handler.py` — how one registration chat turn works

`registration/ai/handler.py` contains one public function,
`handle_registration_message(conversation, conversation_history)`. It is the
brain of the registration agent: every chat message the patient sends passes
through it exactly once. This document explains **every dependency the file
imports, every constant it defines, and every step it takes**, in plain
language.

---

## 1. The imports — what each dependency is and why the handler needs it

```python
from langsmith import traceable
```
**What it is:** LangSmith's tracing decorator (observability for AI apps).
**Why here:** `@traceable(name="handle_registration_message", run_type="chain")`
wraps the function so every turn shows up in the LangSmith dashboard as one
named span, with the model call nested inside it. Without it you'd only see
anonymous `call_tool` runs and couldn't tell registration traffic from
scheduling traffic. It changes nothing about behavior — pure observability.

```python
from core.ai import call_tool
```
**What it is:** the project's single "AI door" (`core/ai/__init__.py`). Every
agent talks to the model only through this function — never through the
OpenAI/Anthropic SDKs directly.
**Why here:** the handler makes exactly one model call per turn. `call_tool`
picks the provider from `AI_PROVIDER` in `.env`, **forces** the model to
answer via the given tool (`tool_choice` is set for you), and returns the
tool's input as a plain validated dict. That's why the handler never parses
model text — it always receives structured data.

```python
from core.models import Conversation
```
**What it is:** the shared conversation model (lives in `core` because every
agent uses it). Key fields the handler touches:
- `patient` — FK to the patient, **nullable**: a registration conversation
  starts before we know who is talking.
- `agent_context` — a JSON scratchpad that survives between turns. The
  handler's memory lives here (see §3).
**Why here:** the handler's first argument is a `Conversation`; it reads and
writes both fields and saves them at the end of the turn.

```python
from registration import services
```
**What it is:** the Phase 2 business-logic layer (`registration/services.py`)
— duplicate detection, record writes, completion. All fully tested with no AI.
**Why here:** the golden rule of this agent is *the AI layer never touches the
database directly*. Everything the model extracts is persisted through these
service functions, which give the handler for free:
- `find_matching_patients(...)` — the FR-R3 duplicate check,
- `create_or_update_patient_record(...)` — audited, transactional writes with
  a field whitelist (chat data can never set `identity_verified`),
- `complete_registration(...)` — status flip + `registration.completed` event
  through the dispatcher.

```python
from registration.ai.prompts import REGISTRATION_SYSTEM_PROMPT
```
**What it is:** the assistant's standing instructions (one question per
message, only relevant follow-ups, never give medical advice, emergency
red-flag rule, answer in the patient's language).
**Why here:** passed as the `system` argument of the model call, so the
extraction happens in the context of those rules. It's a stable constant —
no per-turn data is ever formatted into it (that keeps prompt caching
effective).

```python
from registration.ai.tools import RECORD_REGISTRATION_DATA_TOOL
```
**What it is:** the strict tool schema (built with `core.ai.strict_tool`)
that shapes the model's answer. Every *data* field is optional; two *control*
fields are always required: `next_question_topic` (a closed enum) and
`registration_complete` (a boolean).
**Why here:** this schema is what makes the conversation "model-driven but
structured": the model can record whatever the patient happened to say, but
it must always tell the code what to ask next and whether it thinks intake
is finished. `strict: true` guarantees the returned dict matches the schema.

```python
from registration.models import InsurancePolicy
```
**What it is:** the insurance policy table (one row per patient + policy
number, with eligibility status).
**Why here:** used by the state gate for one read-only question: *"does this
patient have any insurance on file yet?"* If not, the stage is `insurance`.
The handler never writes policies itself — the insurance endpoint and
document extraction do that, because they have the coverage dates.

---

## 2. The module constants

| Constant | What it means |
|---|---|
| `DEMOGRAPHIC_MINIMUM = ("first_name", "last_name", "dob", "contact_number")` | The four fields duplicate detection needs. Until all four are known, no patient record is created — partial answers just accumulate. |
| `DEMOGRAPHIC_FIELDS` | Every patient field the conversation is allowed to fill (name, dob, phone, email, address, emergency contact, language, pharmacy). Anything else the model returns is ignored for demographics. |
| `INTAKE_LIST_FIELDS = ("symptoms", "medical_history", "medications", "allergies", "family_history")` | The list-shaped intake areas (FR-R5). Each accumulates across turns with de-duplication. (`lifestyle` is handled separately because it's a dict, not a list.) |
| `INSURANCE_CHAT_FIELDS` | Maps tool field names → model field names (`insurance_provider` → `provider_name`, ...) for insurance details a patient *dictates* in chat rather than uploading a card. |

---

## 3. The conversation's memory — `agent_context` keys

The handler is stateless between requests; everything it must remember lives
in `conversation.agent_context` (a JSON field):

| Key | Meaning |
|---|---|
| `pending_demographics` | Partial demographics collected before a patient record exists. Deleted once the record is created. |
| `duplicate_candidate_ids` | Set when the duplicate check said "possible duplicate" — the ids a staff member must review. Its presence puts the conversation in `duplicate_hold`. |
| `intake` | The accumulating medical intake (lists + `lifestyle` dict). Written to the database as an `IntakeSummary` only at completion. |
| `pending_insurance` | Insurance details dictated in chat, stashed for the policy writers (the insurance endpoint / card extraction). |
| `registration_stage` | The stage computed this turn (informational, e.g. for debugging). |
| `active_agent` / `handoff` | Set on completion: the conversation is handed to the scheduling agent, with the reported symptoms in the handoff payload, so booking starts without re-asking identity. |

---

## 4. Step-by-step: what one call does

**Inputs:** the `Conversation` object, and `conversation_history` — the chat
as a list of `{"role": "user"/"assistant", "content": ...}` dicts (the chat
endpoint rebuilds it from the stored `Message` rows).

1. **One model call.** `call_tool(system=..., messages=history, tool=...)`
   forces the model to answer through `record_registration_data`. Result:
   a dict like `{"first_name": "Meera", "next_question_topic": "demographics",
   "registration_complete": false}`.

2. **Refresh the patient.** If a patient is linked, `patient.refresh_from_db()`
   re-reads it — the OTP and insurance **endpoints** change the patient
   between chat turns, and the gate must see the current flags. (This line
   exists because the live shell test caught the handler trusting a stale
   in-memory copy and getting stuck at the OTP gate forever.)

3. **Persist demographics.**
   - Patient already linked → any newly-extracted demographic fields are
     written through `create_or_update_patient_record`.
   - No patient yet → merge new fields into `pending_demographics`. Once the
     `DEMOGRAPHIC_MINIMUM` four are present, run `find_matching_patients`:
     - `existing` → link the existing record (updated with the new details),
     - `possible_duplicate` → store `duplicate_candidate_ids`, create
       **nothing** (a human decides — PRD Edge Case 4),
     - `new` → create the record and link it.

4. **Accumulate intake.** Each list field is appended and de-duplicated
   (order preserved); `lifestyle` is dict-merged. Nothing is written to the
   database yet — intake lands as one `IntakeSummary` at completion.

5. **Stash chat-dictated insurance** into `pending_insurance` (see the
   `InsurancePolicy` note above for why the row isn't created here).

6. **The state gate** — the heart of the file. Checked strictly in order;
   the *code*, never the model, decides the stage:

   | Order | Condition | Stage | UI hint sent to frontend |
   |---|---|---|---|
   | 1 | no patient, lookalike found | `duplicate_hold` | — |
   | 2 | no patient yet | `demographics` | — |
   | 3 | patient not OTP-verified | `identity_verification` | `"otp_required"` |
   | 4 | no insurance policy on file | `insurance` | `{"upload": "insurance_card"}` |
   | 5 | model says intake not finished | `intake` | — |
   | 6 | everything satisfied | `done` | — |

   On `done`: the accumulated intake is written
   (`create_or_update_patient_record(intake=...)`), `complete_registration`
   runs (status → `complete`, `registration.completed` emitted → scheduling
   notifies the patient they can book), and the conversation is handed off
   (`active_agent = "scheduling"`, symptoms in `handoff`).

   Because the gate is ordered, the model claiming "registration complete"
   early changes nothing — an unverified patient can never get past gate 3.

7. **Save and return.** `agent_context` and the patient link are saved on the
   conversation. Return value:

   ```python
   {
       "stage": "identity_verification",     # from the gate (code-decided)
       "next_question_topic": "demographics",# the model's pick for what to ask
       "registration_complete": False,       # True only when stage == "done"
       "ui_hints": ["otp_required"],         # what the frontend should show
       "patient_id": 7,                      # None until a record is linked
       "extracted": {...},                   # the raw tool result (debugging)
   }
   ```

   The caller (`RegistrationChatAPIView`) uses `stage` to pick the reply
   instruction for the visible assistant message, and forwards `ui_hints` in
   the final SSE event.

---

## 5. What the handler deliberately does NOT do

- **No direct DB writes** — everything goes through `services.py` (audited,
  transactional, whitelisted).
- **No OTP sending/checking** — that's the OTP endpoints' job; the handler
  only *gates* on the resulting `identity_verified` flag.
- **No insurance policy creation** — the insurance endpoint and card
  extraction own that (they have the coverage dates).
- **No reply text** — it returns structure; the chat endpoint makes a second
  model call to write the patient-visible message.

## 6. Where it's tested

`registration/tests/test_ai_handler.py` — 11 tests with the model mocked
(`patch("registration.ai.handler.call_tool")`): accumulation before a patient
exists, create/link/reuse/duplicate-hold, every gate transition, the
stale-patient regression, intake dedup across turns, and the completion turn
(intake row + status flip + event + handoff). The live end-to-end run with
real model calls is described in `README_REGISTRATION.md` → Build journal →
Phase 4.
