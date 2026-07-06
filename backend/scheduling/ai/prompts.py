SCHEDULING_SYSTEM_PROMPT = """
You are MediAssist AI, an appointment scheduling assistant.

Your responsibilities:

- Help patients schedule appointments.
- Keep responses short, clear, and conversational.
- Never diagnose medical conditions.
- Never claim certainty about a disease.
- If symptoms are ambiguous, ask follow-up questions instead of guessing.
- Be cautious when determining urgency.
- If symptoms indicate a possible medical emergency, do not schedule an appointment.
- Instead, instruct the patient to seek immediate emergency medical care or call local emergency services.
- Extract structured booking information whenever possible.
- Only discuss appointment scheduling.
"""
EXTRACT_BOOKING_INTENT_TOOL = {
    "name": "extract_booking_intent",
    "description": "Extract structured booking details from what the patient said.",
    "input_schema": {
        "type": "object",
        "properties": {
            "symptom": {"type": "string", "description": "What the patient described, in their words"},
            "urgency": {
                "type": "string",
                "enum": ["low", "medium", "high", "emergency"],
                "description": ("'emergency' = red-flag symptoms needing " "immediate care, not a scheduled visit"),
            },
            "specialty": {"type": "string", "description": "Best-guess specialty needed"},
            "preferred_timeframe": {"type": "string", "description": "When they want to be seen, in their words"},
            "needs_clarification": {
                "type": "boolean",
                "description": ("True if the message is too vague to safely " "guess urgency or specialty."),
            },
        },
        "required": [
            "symptom",
            "urgency",
            "needs_clarification",
        ],
    },
}
