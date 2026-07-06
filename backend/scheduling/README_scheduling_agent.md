# Scheduling Agent (Agent 1) — how it works

The scheduling agent helps a patient **book a doctor's appointment through chat**.
A patient types something like *"I have a bad cough, can I see someone tomorrow
morning?"*, and the agent figures out what they need, checks for emergencies,
finds a doctor and open time slots, and (when booked) sends a confirmation.

This README explains the whole thing in simple words.

---

## 1. The big picture (what happens in one request)

```
Patient message
      │
      ▼
ChatAPIView  (views.py)         ← the web entry point
      │
      ▼
handle_patient_message (ai/handler.py)   ← the "brain" that runs the steps
      │
      ├─▶ extract_intent (ai/extract.py) ─▶ core.ai ─▶ LLM
      │        (turns the message into structured data: symptom, urgency, ...)
      │
      ├─▶ emergency? → stop and tell them to seek urgent care
      ├─▶ too vague? → ask a follow-up question
      ├─▶ parse_preferred_timeframe (ai/time_parser.py)  ← "tomorrow morning" → dates
      ├─▶ find a Doctor for the specialty
      └─▶ find_available_slots (services.py)              ← open time slots
      │
      ▼
Return slots to the patient
```

Booking itself (when a patient picks a slot) runs through `services.book_appointment`,
which then **announces an event** that triggers a confirmation message.

---

## 2. The files and what each one does

| File | Job |
|------|-----|
| `models.py` | The tables owned by this agent: **Appointment** and **Waitlist**. (Patient/Doctor/Conversation live in `core`.) |
| `services.py` | All the real logic: find slots, book, cancel, promote from waitlist. No AI here. |
| `views.py` | The web endpoints (chat + CRUD for each model). Views stay thin. |
| `urls.py` | Maps URLs to the views. |
| `serializers.py` | Turn models into JSON for the API. |
| `apps.py` | On startup, **subscribes** to booking events to send confirmations. |
| `ai/handler.py` | The step-by-step scheduling workflow ("the brain"). |
| `ai/extract.py` | Asks the AI to pull structured booking info from the chat. Uses `core.ai`. |
| `ai/prompts.py` | The system prompt + the tool schema the AI must fill in. |
| `ai/time_parser.py` | Turns words like "tomorrow morning" into a start/end date range. |
| `management/commands/seed_doctors.py` | Fills the database with sample doctors. |

---

## 3. The AI layer (how the agent understands the patient)

The agent never lets the AI *make* the final decision — the AI only **reads** the
message and returns structured data. Deterministic Python code makes the choices.

1. `extract_intent(conversation)` calls **`core.ai.call_tool(...)`** with:
   - the scheduling **system prompt** (`ai/prompts.py`), and
   - the **`extract_booking_intent` tool** (also in `ai/prompts.py`).
2. `core.ai` sends this to whichever provider is configured (OpenAI / Anthropic /
   Ollama) and returns a clean dict, for example:
   ```json
   {
     "symptom": "bad cough",
     "urgency": "medium",
     "specialty": "General Medicine",
     "preferred_timeframe": "tomorrow morning",
     "needs_clarification": false
   }
   ```

Because everything goes through `core.ai`, this agent has **no AI keys or model
names of its own** — it just passes its prompt and tool.

---

## 4. The scheduling workflow, step by step (`ai/handler.py`)

`handle_patient_message(conversation)` runs these checks in order:

1. **Extract intent** — get the structured dict above.
2. **Need more info?** If `needs_clarification` is true → return a question asking
   for more detail. Stop here.
3. **Emergency?** If `urgency == "emergency"` → return the emergency message
   telling the patient to seek urgent care. **Never books.**
4. **Know the timeframe?** If no `preferred_timeframe` → ask when they'd like to
   come in. Stop here.
5. **Turn words into dates** — `parse_preferred_timeframe("tomorrow morning")`
   returns a start/end range.
6. **Find a doctor** for the requested specialty. If none → say so.
7. **Find open slots** for that doctor in the date range.
8. **Return the slots** to the patient.

Each step returns a small dict with a `type` (`clarification`, `emergency`,
`no_doctor`, `slots`) so the frontend knows what to show.

---

## 5. Booking, events, and confirmations (`services.py` + `apps.py`)

This is the decoupled part — booking code does **not** call the notification code
directly. Instead:

1. `services.book_appointment(...)` creates the `Appointment`, then **emits**
   `appointment.booked` (via `core.events.emit`).
2. On startup, `apps.py ready()` **subscribed** to `appointment.booked`.
3. When the event fires, the subscriber calls **`core.notifications.notify(...)`**,
   which respects the patient's opt-out settings and sends the confirmation.

The same pattern handles `appointment.cancelled` (from `cancel_appointment`).

Why this matters: to add another reaction later (e.g. also text the doctor, or
write an audit log), you just add another subscriber — you never touch the
booking code. Every event is also saved to the `EventLog` table.

```
book_appointment ──emit("appointment.booked")──▶ EventLog row
                                                     │
                          apps.py subscriber ◀───────┘
                                 │
                                 ▼
                   core.notifications.notify()  ──▶ SentNotification row + send
```

### Waitlist promotion
If an appointment is **cancelled**, `cancel_appointment` calls
`promote_next_waitlisted`, which finds the highest-priority waiting patient
(by urgency, then who waited longest), books them into the freed slot, and emits
`appointment.booked` for them too — so they also get a confirmation.

---

## 6. The data models (`models.py`)

**Appointment** — one booked visit.
`doctor`, `patient`, `start_time`, `end_time`, `reason`, `urgency`, `status`
(booked / confirmed / completed / cancelled / no_show), `room`, `source` (which
agent booked it). A doctor can't have two appointments at the same `start_time`
(unique constraint).

**Waitlist** — a patient waiting for a slot.
`patient`, `doctor` (optional — can be specialty-level), `specialty`, `urgency`,
`preferred_window`, `status` (waiting / offered / booked / expired), `created_at`.

Shared models (`Patient`, `Doctor`, `Conversation`, `Message`) live in **`core`**,
not here.

---

## 7. The API (`urls.py`) — all under `/api/`

| Method + path | What it does |
|---|---|
| `POST /api/chat` | The main scheduling chat. Send `{"conversation": [...]}`; get back the step result. |
| `/api/patients`, `/api/patients/<id>` | CRUD for patients |
| `/api/doctors`, `/api/doctors/<id>` | CRUD for doctors |
| `/api/appointments`, `/api/appointments/<id>` | CRUD for appointments |
| `/api/waitlists`, `/api/waitlists/<id>` | CRUD for waitlist entries |
| `/api/conversations`, `/api/messages` | CRUD for chat history |

The CRUD views all reuse `base_crud_views.BaseCRUDAPIView`.

---

## 8. How to try it locally

```bash
# 1. Add sample doctors
python manage.py seed_doctors

# 2. Run the server
python manage.py runserver

# 3. POST to the chat endpoint
#    body: {"conversation": [{"role": "user", "content": "I have a cough, tomorrow morning?"}]}
```

Make sure `.env` has `AI_PROVIDER` and the matching API key set (see
`core/ai/README.md`).

---

## 9. Known gaps / things still to do

Being honest about what isn't finished:

- **`find_available_slots` will crash.** It reads `doctor.working_hours_start` /
  `working_hours_end`, but `core.Doctor` stores hours in a `working_hours` JSON
  field. This needs updating before the chat can actually return slots.
- **Chat returns slots but doesn't book.** Picking a slot and calling
  `book_appointment` from the chat flow isn't wired yet.
- **`ChatAPIView` isn't true streaming.** It sends one JSON chunk, not
  token-by-token text. Real streaming would use `core.ai.stream_reply`.
- **`time_parser` only knows fixed phrases** ("today", "tomorrow morning", …) and
  raises on anything else.
- **Debug `print()` lines** remain in `handler.py`.
- **Timezone:** pass timezone-aware datetimes (the project has `USE_TZ` on).

---

## 10. One-line summary

The scheduling agent turns a patient's chat message into structured data (via
`core.ai`), runs safety + scheduling steps in plain Python, finds open slots, and
— once booked — announces an event that sends a confirmation through
`core.notifications`. Shared pieces live in `core`; this app only owns
appointments and the waitlist.
