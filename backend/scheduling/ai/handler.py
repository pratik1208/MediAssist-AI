from scheduling.ai.extract import extract_intent
from scheduling.ai.time_parser import parse_preferred_timeframe
from scheduling.models import Doctor
from scheduling.services import find_available_slots

EMERGENCY_RESPONSE = (
    "Your symptoms may indicate a medical emergency. "
    "Please seek immediate medical attention or call your local emergency services. "
    "I cannot schedule an appointment for these symptoms."
)


def handle_patient_message(conversation_history):
    """
    Orchestrates the complete scheduling workflow.
    """

    # Step 1: Extract structured intent
    intent = extract_intent(conversation_history)
    print(type(intent))
    print(intent)
    # Depending on your provider, you may need to extract the JSON
    # from the model response. Here we assume intent is already a dict.

    # Step 2: Ask for clarification if required
    if intent.get("needs_clarification"):
        return {
            "type": "clarification",
            "message": ("Could you tell me a little more about your symptoms " "and when they started?"),
        }

    # Step 3: Emergency check
    if intent.get("urgency") == "emergency":
        return {
            "type": "emergency",
            "message": EMERGENCY_RESPONSE,
        }
    preferred_timeframe = intent.get("preferred_timeframe")
    if not preferred_timeframe:
        return {
            "type": "clarification",
            "message": ("When would you like to schedule your appointment? " "For example: today, tomorrow morning, or tomorrow afternoon."),
        }
    date_from, date_to = parse_preferred_timeframe(preferred_timeframe)
    # Step 4: Find doctors for the specialty
    doctors = Doctor.objects.filter(specialty=intent.get("specialty"))

    if not doctors.exists():
        return {
            "type": "no_doctor",
            "message": (f"No doctors are currently available for " f"{intent.get('specialty')}."),
        }

    doctor = doctors.first()
    slots = find_available_slots(
        doctor=doctor,
        date_from=date_from,
        date_to=date_to,
    )
    # Step 5: Find available slots

    # Step 6: Return slots
    return {
        "type": "slots",
        "doctor": doctor.name,
        "specialty": doctor.specialty,
        "slots": slots,
    }
