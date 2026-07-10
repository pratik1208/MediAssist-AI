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
            "specialty": {
                "type": "string",
                "enum": [
                    "General Medicine",
                    "Cardiology",
                    "Dermatology",
                    "Pediatrics",
                    "Orthopedics",
                    "Gynecology",
                    "Neurology",
                    "Psychiatry",
                    "Ophthalmology",
                    "ENT",
                    "Gastroenterology",
                    "Endocrinology",
                    "Pulmonology",
                    "Urology",
                    "Oncology",
                    "Nephrology",
                    "Rheumatology",
                    "Infectious Disease",
                    "Allergy & Immunology",
                    "Emergency Medicine",
                ],
            },
            "preferred_timeframe": {"type": "string", "description": "When they want to be seen, in their words"},
            "needs_clarification": {
                "type": "boolean",
                "description": ("True if the message is too vague to safely " "guess urgency or specialty."),
            },
        },
        "required": [
            "symptom",
            "urgency",
            # Without specialty the doctor lookup filters on None and always
            # returns "no doctors" — the model must commit to a specialty.
            "specialty",
            "needs_clarification",
        ],
    },
}

