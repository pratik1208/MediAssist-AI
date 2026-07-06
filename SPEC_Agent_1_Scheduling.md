# SPEC_Agent_1 — Intelligent Scheduling

Technical spec for `BUILD_STEPS_Agent_1.md`. Where that doc says "see `SPEC.md`", it means this file (+ `SCHEMA.md` for tables). Shared stack/architecture/conventions: `SPEC_Core.md`.

## Data model

Tables: `core.Doctor`, `core.Patient`, `core.Conversation`, `core.Message`, `scheduling.Appointment`, `scheduling.Waitlist` — full field lists in **`SCHEMA.md`** (§core, §scheduling).

## Backend architecture

```
patient message ──▶ /api/scheduling/chat/ (SSE view)
   └▶ handle_patient_message()                     scheduling/ai.py
        1. core.safety.red_flag_check(text) ──▶ emergency script + escalate (STOP)
        2. call_tool(extract_booking_intent)  ──▶ structured intent
        3. needs_clarification? ──▶ ask follow-up question
        4. services.find_available_slots(...) ──▶ slot list (deterministic)
        5. stream reply + ui_hints={"slots": [...]}
patient picks slot ──▶ POST /api/scheduling/appointments/ ──▶ services.book_appointment()
cancellation      ──▶ services.cancel_appointment() ──▶ promote_next_waitlisted() ──▶ notify()
```

AI extracts; **`services.py` decides and books**. The model never selects the final slot or writes the DB.

## Folder structure

```
scheduling/
├── models.py            # Appointment, Waitlist
├── services.py          # generate_blocks, find_available_slots, book_appointment,
│                        # cancel_appointment, promote_next_waitlisted
├── ai.py                # SYSTEM_PROMPT, extract_booking_intent tool, handle_patient_message
├── serializers.py  views.py  urls.py  admin.py
├── management/commands/seed_doctors.py
└── tests/ test_services.py  test_api.py  test_prompts.py   # red-flag + vague-phrase suites
```

## Core algorithms

**`find_available_slots(doctor, date_from, date_to) -> list[Slot]`**

1. For each day in range: skip if in `doctor.holidays`; read `doctor.working_hours[weekday]`.
2. Split each working window into candidate blocks of `avg_consult_minutes`, stepping by `avg_consult_minutes + buffer_minutes` (`generate_blocks`).
3. Fetch that day's non-cancelled appointments once; drop any block overlapping `[appt.start, appt.end)`.
4. Drop blocks in the past; return first N (default 6) as `{doctor_id, start, end}`.

**`book_appointment(doctor, patient, start, end, reason, urgency, source)`** — inside `transaction.atomic()` with `select_for_update()` on the doctor's same-day appointments; re-check overlap, then create. This is the NFR-5 guarantee (never offer/book a taken slot) — every agent that books goes through this function.

**`promote_next_waitlisted(doctor, freed_start, freed_end)`** — pick `Waitlist.objects.filter(status="waiting", doctor=doctor or specialty match)` ordered by urgency rank then `created_at`; book via `book_appointment`, set entry `booked`, `notify(patient, "waitlist_promoted", ...)` (FR-S6, Edge Case 6).

**Django Admin cancel** — `admin.py` action `cancel_and_promote` on Appointment: set status `cancelled`, call `promote_next_waitlisted`. Gives staff a working cancellation path before any staff UI exists.

## API contract

| Method | Path | Auth | Body → Response |
|---|---|---|---|
| GET | `/api/scheduling/doctors/` | session | → `[{id, name, specialty}]` |
| GET | `/api/scheduling/doctors/{id}/slots/?from=&to=` | session | → `[{start, end}]` |
| POST | `/api/scheduling/chat/` | session | `{message}` → SSE stream (`delta`, final `ui_hints`) |
| POST | `/api/scheduling/appointments/` | session (verified) | `{doctor_id, start, reason, urgency}` → `201 {id, status:"booked"}`; `409 {code:"slot_taken"}` |
| POST | `/api/scheduling/appointments/{id}/cancel/` | session (verified) | → `{status:"cancelled", waitlist_promoted: bool}` |
| GET | `/api/scheduling/waitlist/` | staff | → waitlist entries |
| POST | `/api/scheduling/waitlist/` | session | `{specialty, urgency, preferred_window}` → `201` |

## Code examples

Tool schema (`scheduling/ai.py`) — the exact `extract_booking_intent` the BUILD_STEPS references:

```python
from core.ai import strict_tool, call_tool

EXTRACT_BOOKING_INTENT = strict_tool(
    "extract_booking_intent",
    "Extract appointment-booking details from the patient's messages.",
    properties={
        "action": {"type": "string", "enum": ["book", "reschedule", "cancel", "refill", "other"]},
        "symptom": {"type": ["string", "null"]},
        "duration": {"type": ["string", "null"], "description": "how long symptoms present"},
        "specialty": {"type": ["string", "null"], "enum_hint": None},
        "urgency": {"type": "string", "enum": ["emergency", "high", "medium", "low", "routine"]},
        "preferred_time": {"type": ["string", "null"], "description": "e.g. 'tomorrow morning'"},
        "needs_clarification": {"type": "boolean"},
        "clarifying_question": {"type": ["string", "null"]},
    },
    required=["action", "symptom", "duration", "specialty", "urgency",
              "preferred_time", "needs_clarification", "clarifying_question"],
)

SYSTEM_PROMPT = """You are a medical scheduling assistant. You never diagnose.
When urgency is ambiguous, choose the higher level. If the request is vague,
set needs_clarification=true and ask exactly one question."""
```

Orchestration function:

```python
from core.safety import red_flag_check
from core.ai import call_tool
from scheduling import services
from core.agent_reply import AgentReply

def handle_patient_message(conversation, history, text) -> AgentReply:
    if red_flag_check(text):
        services.escalate_emergency(conversation)
        return AgentReply(text=EMERGENCY_SCRIPT, followup_needed=False)

    intent = call_tool(SYSTEM_PROMPT, history + [{"role": "user", "content": text}],
                       EXTRACT_BOOKING_INTENT)
    if intent["urgency"] == "emergency":
        services.escalate_emergency(conversation)
        return AgentReply(text=EMERGENCY_SCRIPT)
    if intent["needs_clarification"]:
        return AgentReply(text=intent["clarifying_question"], followup_needed=True)
    if intent["action"] == "refill":
        return AgentReply(text="", handoff="refill")          # ORCHESTRATION §4

    doctor = services.select_doctor(intent["specialty"], intent["symptom"])
    slots = services.find_available_slots(doctor, *services.window_for(intent))
    if not slots:
        return AgentReply(text=NO_SLOTS_TEXT, ui_hints={"offer_waitlist": True})
    return AgentReply(text=f"Dr. {doctor.name} has these times:",
                      ui_hints={"slots": [s.as_dict() for s in slots]})
```

Prompt-regression test pattern (`tests/test_prompts.py`):

```python
RED_FLAGS = ["crushing chest pain", "my left arm is numb and I'm sweating",
             "I can't breathe", "I want to end my life", ...]  # 25+ phrasings

@pytest.mark.parametrize("phrase", RED_FLAGS)
def test_red_flags_always_emergency(phrase, conversation):
    reply = handle_patient_message(conversation, [], phrase)
    assert EMERGENCY_SCRIPT in reply.text
    assert EscalationAlert.objects.filter(priority="critical").exists()
```

## Tech stack additions (beyond SPEC_Core)

None — this agent uses only the shared stack. First agent to exercise: `core.ai.call_tool`, `stream_reply`, `red_flag_check` (imported from triage's extraction in Phase 6), and the booking transaction pattern every later agent reuses.
