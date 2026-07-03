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
            "specialization": {"type": "string", "description": "Best-guess specialization needed"},
            "preferred_timeframe": {"type": "string", "description": "When they want to be seen, in their words"},
            "needs_clarification": {
                "type": "boolean",
                "description": ("True if the message is too vague to safely " "guess urgency or specialization."),
            },
        },
        "required": [
            "symptom",
            "urgency",
            "needs_clarification",
        ],
    },
}
