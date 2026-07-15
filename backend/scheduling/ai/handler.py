from core.safety import red_flag_check
from scheduling.ai.extract import extract_intent
from scheduling.ai.time_parser import parse_preferred_timeframe
from scheduling.models import Doctor
from scheduling.services import find_available_slots

EMERGENCY_RESPONSE = (
    "Your symptoms may indicate a medical emergency. "
    "Please seek immediate medical attention or call your local emergency services. "
    "I cannot schedule an appointment for these symptoms."
)

# How many doctors of the matched specialty to offer per search — enough
# for a real choice without flooding the chat.
MAX_DOCTOR_OPTIONS = 3


def handle_patient_message(conversation_history):
    """
    Orchestrates the complete scheduling workflow.

    Returns a list of chat events; the view streams one SSE event per entry.
    Most turns produce a single event, but a slot search yields one "slots"
    event per available doctor so the patient picks a doctor, not just a time.
    """

    # Step 0: deterministic red-flag screen BEFORE any model call (PRD Edge
    # Case 11) — emergency symptoms mentioned mid-scheduling must never
    # depend on the model alone.
    latest = conversation_history[-1]["content"] if conversation_history else ""
    if red_flag_check(latest):
        return [{
            "type": "emergency",
            "message": EMERGENCY_RESPONSE,
        }]

    # Step 1: Extract structured intent
    intent = extract_intent(conversation_history)

    # Step 2: Ask for clarification if required
    if intent.get("needs_clarification"):
        return [{
            "type": "clarification",
            "message": ("Could you tell me a little more about your symptoms " "and when they started?"),
        }]

    # Step 3: Emergency check
    if intent.get("urgency") == "emergency":
        return [{
            "type": "emergency",
            "message": EMERGENCY_RESPONSE,
        }]
    preferred_timeframe = intent.get("preferred_timeframe")
    if not preferred_timeframe:
        return [{
            "type": "clarification",
            "message": ("When would you like to schedule your appointment? " "For example: today, tomorrow morning, or tomorrow afternoon."),
        }]
    try:
        date_from, date_to = parse_preferred_timeframe(preferred_timeframe)
    except ValueError:
        # A phrasing the parser can't place must become a question,
        # never a 500 to the patient.
        return [{
            "type": "clarification",
            "message": (
                "I couldn't quite work out when you'd like to come in. "
                "Could you say something like 'today', 'tomorrow morning', "
                "or a day of the week, e.g. 'Monday afternoon'?"
            ),
        }]

    # Step 4: gather openings across the specialty's doctors — the patient
    # chooses between doctors, not just between one doctor's times.
    doctors = Doctor.objects.filter(specialty=intent.get("specialty"), is_active=True)

    if not doctors.exists():
        return [{
            "type": "no_doctor",
            "message": (f"No doctors are currently available for " f"{intent.get('specialty')}."),
        }]

    events = []
    for doctor in doctors:
        slots = find_available_slots(
            doctor=doctor,
            date_from=date_from,
            date_to=date_to,
        )
        if slots:
            events.append({
                "type": "slots",
                "doctor": doctor.name,
                "specialty": doctor.specialty,
                "slots": slots,
            })
        if len(events) == MAX_DOCTOR_OPTIONS:
            break

    if not events:
        # Nobody has an opening in that window — one empty slots event keeps
        # the frontend's "no open slots, try another time" message working.
        first = doctors.first()
        events.append({
            "type": "slots",
            "doctor": first.name,
            "specialty": first.specialty,
            "slots": [],
        })
    return events
