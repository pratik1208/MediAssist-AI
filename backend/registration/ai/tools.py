"""Tool schemas for the registration agent (Phase 4).

Both tools are strict (strict: true): the model's output must validate
exactly against the schema — no invented keys, no wrong types. That is what
makes the dynamic question flow model-driven while keeping data capture
structured (FR-R1, FR-R4, FR-R5, FR-R6).
"""


from core.ai import strict_tool

# Topics the conversation layer can route on. "none" = nothing left to ask.
NEXT_QUESTION_TOPICS = [
    "demographics",
    "identity_verification",
    "insurance",
    "symptoms",
    "medical_history",
    "medications",
    "allergies",
    "family_history",
    "lifestyle",
    "none",
]

RECORD_REGISTRATION_DATA_TOOL = strict_tool(
    "record_registration_data",
    "Record whichever registration fields the patient provided in their latest "
    "message and decide what to ask about next. Include ONLY fields the patient "
    "actually stated — never guess, infer, or fill in placeholder values. Every "
    "data field is optional; next_question_topic and registration_complete must "
    "always be set.",
    {
        # -- demographics (FR-R1) --
        "first_name": {"type": "string"},
        "last_name": {"type": "string"},
        "dob": {"type": "string", "format": "date", "description": "Date of birth as YYYY-MM-DD"},
        "contact_number": {"type": "string", "description": "Phone number exactly as the patient said it"},
        "email": {"type": "string", "format": "email"},
        "address": {
            "type": "object",
            "properties": {
                "line1": {"type": "string"},
                "line2": {"type": "string"},
                "city": {"type": "string"},
                "state": {"type": "string"},
                "zip": {"type": "string"},
            },
            "required": [],
            "additionalProperties": False,
        },
        "emergency_contact": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "relationship": {"type": "string"},
                "phone": {"type": "string"},
            },
            "required": [],
            "additionalProperties": False,
        },
        "preferred_language": {"type": "string", "description": "Language code, e.g. 'en', 'hi', 'mr'"},
        "preferred_pharmacy": {"type": "string"},
        # -- insurance, when dictated in chat rather than read from a card --
        "insurance_provider": {"type": "string"},
        "insurance_policy_number": {"type": "string"},
        "insurance_member_id": {"type": "string"},
        # -- medical intake (FR-R5) --
        "symptoms": {"type": "array", "items": {"type": "string"}},
        "medical_history": {"type": "array", "items": {"type": "string"}},
        "medications": {"type": "array", "items": {"type": "string"}},
        "allergies": {"type": "array", "items": {"type": "string"}},
        "family_history": {"type": "array", "items": {"type": "string"}},
        "lifestyle": {
            "type": "object",
            "properties": {
                "smoking": {"type": "string"},
                "alcohol": {"type": "string"},
                "exercise": {"type": "string"},
            },
            "required": [],
            "additionalProperties": False,
        },
        # -- control flow: these drive the dynamic question loop --
        "next_question_topic": {
            "type": "string",
            "enum": NEXT_QUESTION_TOPICS,
            "description": "What to ask the patient about next; 'none' when registration_complete is true.",
        },
        "registration_complete": {
            "type": "boolean",
            "description": "True only when demographics and the full medical intake have been collected.",
        },
    },
    ["next_question_topic", "registration_complete"],
)

GENERATE_INTAKE_SUMMARY_TOOL = strict_tool(
    "generate_intake_summary",
    "Turn the collected patient intake into (a) a cleaned, structured clinical "
    "profile and (b) a short paragraph a physician can read in ten seconds "
    "before walking into the room. Use only the information provided — never "
    "add findings, and never diagnose. Normalize obvious variants (e.g. "
    "'panadol' -> 'paracetamol (Panadol)') but keep the patient's meaning.",
    {
        "clinical_profile": {
            "type": "object",
            "properties": {
                "symptoms": {"type": "array", "items": {"type": "string"}},
                "medical_history": {"type": "array", "items": {"type": "string"}},
                "medications": {"type": "array", "items": {"type": "string"}},
                "allergies": {"type": "array", "items": {"type": "string"}},
                "family_history": {"type": "array", "items": {"type": "string"}},
                "lifestyle": {
                    "type": "object",
                    "properties": {
                        "smoking": {"type": "string"},
                        "alcohol": {"type": "string"},
                        "exercise": {"type": "string"},
                    },
                    "required": [],
                    "additionalProperties": False,
                },
            },
            "required": [],
            "additionalProperties": False,
        },
        "summary_text": {
            "type": "string",
            "description": "3-6 sentences, neutral clinical tone, leading with the "
                           "presenting symptoms. No diagnosis, no treatment advice.",
        },
    },
    ["clinical_profile", "summary_text"],
)

EXTRACT_DOCUMENT_DATA_TOOL = strict_tool(
    "extract_document_data",
    "Extract structured fields from an uploaded document image or PDF "
    "(insurance card, ID, prescription, lab report, referral letter). Transcribe "
    "ONLY text that is actually visible in the document — never guess at "
    "unreadable or missing fields; simply omit them. Set legible to false if the "
    "document is too blurry, dark, or cropped to read reliably.",
    {
        "document_type": {
            "type": "string",
            "enum": ["insurance_card", "id_card", "prescription", "lab_report", "referral_letter",
                     "consultation_report", "imaging_report", "other"],
            "description": "What kind of document this actually is (may differ from what the patient claimed).",
        },
        "legible": {
            "type": "boolean",
            "description": "False if the document cannot be read reliably and the patient should re-upload.",
        },
        "insurance": {
            "type": "object",
            "description": "Fields read off an insurance card (FR-R4).",
            "properties": {
                "provider": {"type": "string"},
                "policy_number": {"type": "string"},
                "member_id": {"type": "string"},
                "coverage_start": {"type": "string", "format": "date"},
                "coverage_end": {"type": "string", "format": "date"},
            },
            "required": [],
            "additionalProperties": False,
        },
        "lab_report": {
            "type": "object",
            "description": "Fields read off a lab report (FR-R6).",
            "properties": {
                "test_name": {"type": "string"},
                "date": {"type": "string", "format": "date"},
                "findings": {"type": "string"},
                "physician": {"type": "string"},
            },
            "required": [],
            "additionalProperties": False,
        },
        "person_name": {"type": "string", "description": "Patient/holder name printed on the document, if visible."},
        "notes": {"type": "string", "description": "Anything important that doesn't fit the structured fields."},
    },
    ["document_type", "legible"],
)
