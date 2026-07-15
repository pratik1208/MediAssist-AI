"""seed_protocols — load the starter ClinicalProtocol rows (Agent 3, Phase 1).

Protocols are configurable DATA, not code (FR-T5): symptom keywords route a
complaint to a protocol, question_flow drives the interview, and
disposition_rules are evaluated by services.assign_acuity() — rules decide
the acuity; the model may only raise it, never lower it.

disposition_rules shape (consumed by evaluate_disposition_rules later):

    {
      "red_flags":  [ {condition..., "acuity": "emergency"} ],   # checked first
      "rules":      [ {condition..., "acuity": "..."} ],         # first match wins
      "risk_overrides": [ {"risk_factor": ..., "raise_to_at_least": ...} ],
      "default_acuity": "low"
    }

    condition = {"finding": <key in assessment.findings>,
                 "op": "gte" | "lte" | "eq" | "contains" | "is_true",
                 "value": ...}

Acuity -> disposition mapping is fixed by FR-T4: emergency -> ed_now,
high -> same_day, medium -> 24_48h, low -> routine, minimal -> self_care.

NOTE: these are development starter protocols. Before production use they
must be reviewed and approved by clinical governance (set approved_by then).

Idempotent: rerunning updates the existing rows by name, never duplicates.
"""

from django.core.management.base import BaseCommand

from triage.models import ClinicalProtocol

PROTOCOLS = [
    {
        "name": "Adult Chest Pain",
        "symptom_keywords": [
            "chest pain", "chest pressure", "chest tightness", "chest discomfort",
            "heart pain", "angina",
        ],
        "question_flow": [
            {"id": 1, "ask": "When did the chest pain start, and what were you doing?", "capture": "onset"},
            {"id": 2, "ask": "On a scale of 1 to 10, how severe is the pain right now?", "capture": "severity_1_10"},
            {"id": 3, "ask": "Does the pain spread to your arm, jaw, neck, or back?", "capture": "radiation"},
            {"id": 4, "ask": "Are you sweating, nauseous, or short of breath with it?", "capture": "associated_symptoms"},
            {"id": 5, "ask": "Does it get worse with exertion or ease with rest?", "capture": "exertional"},
        ],
        "disposition_rules": {
            "red_flags": [
                {"finding": "character", "op": "contains", "value": "crushing", "acuity": "emergency"},
                {"finding": "radiation", "op": "contains", "value": "arm", "acuity": "emergency"},
                {"finding": "radiation", "op": "contains", "value": "jaw", "acuity": "emergency"},
                {"finding": "associated_symptoms", "op": "contains", "value": "shortness of breath", "acuity": "emergency"},
                {"finding": "associated_symptoms", "op": "contains", "value": "sweating", "acuity": "emergency"},
            ],
            "rules": [
                {"finding": "severity_1_10", "op": "gte", "value": 7, "acuity": "high"},
                {"finding": "exertional", "op": "is_true", "acuity": "high"},
                {"finding": "severity_1_10", "op": "gte", "value": 4, "acuity": "medium"},
            ],
            "risk_overrides": [
                {"risk_factor": "age_gte_50", "raise_to_at_least": "high"},
                {"risk_factor": "cardiac_history", "raise_to_at_least": "high"},
                {"risk_factor": "diabetes", "raise_to_at_least": "medium"},
            ],
            "default_acuity": "medium",
        },
    },
    {
        "name": "Pediatric Fever",
        "symptom_keywords": [
            "child fever", "baby fever", "kid fever", "infant fever",
            "fever in child", "my son has a fever", "my daughter has a fever",
        ],
        "question_flow": [
            {"id": 1, "ask": "How old is your child?", "capture": "age_months"},
            {"id": 2, "ask": "What is the temperature, and how did you measure it?", "capture": "temperature_f"},
            {"id": 3, "ask": "How long has the fever lasted?", "capture": "duration_hours"},
            {"id": 4, "ask": "Is your child alert and drinking fluids, or unusually drowsy?", "capture": "alertness"},
            {"id": 5, "ask": "Any rash, stiff neck, trouble breathing, or a seizure?", "capture": "associated_symptoms"},
        ],
        "disposition_rules": {
            "red_flags": [
                # Any fever under 3 months old is an emergency workup.
                {"finding": "age_months", "op": "lte", "value": 3, "acuity": "emergency"},
                {"finding": "associated_symptoms", "op": "contains", "value": "stiff neck", "acuity": "emergency"},
                {"finding": "associated_symptoms", "op": "contains", "value": "seizure", "acuity": "emergency"},
                {"finding": "associated_symptoms", "op": "contains", "value": "trouble breathing", "acuity": "emergency"},
                {"finding": "alertness", "op": "contains", "value": "unresponsive", "acuity": "emergency"},
                {"finding": "temperature_f", "op": "gte", "value": 104, "acuity": "high"},
            ],
            "rules": [
                {"finding": "alertness", "op": "contains", "value": "drowsy", "acuity": "high"},
                {"finding": "duration_hours", "op": "gte", "value": 72, "acuity": "high"},
                {"finding": "temperature_f", "op": "gte", "value": 102, "acuity": "medium"},
                {"finding": "duration_hours", "op": "gte", "value": 24, "acuity": "medium"},
            ],
            "risk_overrides": [
                {"risk_factor": "immunocompromised", "raise_to_at_least": "high"},
                {"risk_factor": "unvaccinated", "raise_to_at_least": "medium"},
            ],
            "default_acuity": "low",
        },
    },
    {
        # Named to match (and repair) the hand-created legacy row that had
        # capture-less questions and an incompatible rules format.
        "name": "Adult Fever Protocol",
        "symptom_keywords": [
            "fever", "high temperature", "chills", "feverish", "temperature",
        ],
        "question_flow": [
            {"id": 1, "ask": "What is your temperature, and how did you measure it?", "capture": "temperature_f"},
            {"id": 2, "ask": "How long have you had the fever?", "capture": "duration_hours"},
            {"id": 3, "ask": "Any stiff neck, confusion, trouble breathing, or a new rash?", "capture": "associated_symptoms"},
            {"id": 4, "ask": "Do you have a weakened immune system (e.g. chemotherapy, transplant, HIV)?", "capture": "immunocompromised"},
            {"id": 5, "ask": "Are you keeping fluids down, or vomiting?", "capture": "hydration"},
        ],
        "disposition_rules": {
            "red_flags": [
                {"finding": "associated_symptoms", "op": "contains", "value": "stiff neck", "acuity": "emergency"},
                {"finding": "associated_symptoms", "op": "contains", "value": "confusion", "acuity": "emergency"},
                {"finding": "associated_symptoms", "op": "contains", "value": "trouble breathing", "acuity": "emergency"},
                {"finding": "immunocompromised", "op": "is_true", "acuity": "high"},
                {"finding": "temperature_f", "op": "gte", "value": 104, "acuity": "high"},
            ],
            "rules": [
                {"finding": "associated_symptoms", "op": "contains", "value": "rash", "acuity": "medium"},
                {"finding": "hydration", "op": "contains", "value": "vomit", "acuity": "medium"},
                {"finding": "temperature_f", "op": "gte", "value": 103, "acuity": "medium"},
                {"finding": "duration_hours", "op": "gte", "value": 72, "acuity": "medium"},
            ],
            "risk_overrides": [
                {"risk_factor": "age_gte_65", "raise_to_at_least": "medium"},
                {"risk_factor": "immunocompromised", "raise_to_at_least": "high"},
            ],
            "default_acuity": "low",
        },
    },
    {
        "name": "Headache",
        "symptom_keywords": [
            "headache", "head pain", "migraine", "head hurts", "pressure in my head",
        ],
        "question_flow": [
            {"id": 1, "ask": "Did the headache come on suddenly (within seconds), or build up gradually?", "capture": "onset"},
            {"id": 2, "ask": "Is this the worst headache of your life, or similar to ones you've had before?", "capture": "worst_ever"},
            {"id": 3, "ask": "On a scale of 1 to 10, how bad is it right now?", "capture": "severity_1_10"},
            {"id": 4, "ask": "Any fever, stiff neck, vision changes, weakness, or confusion?", "capture": "associated_symptoms"},
            {"id": 5, "ask": "Have you hit your head recently?", "capture": "recent_head_injury"},
        ],
        "disposition_rules": {
            "red_flags": [
                # Thunderclap onset or worst-ever headache -> rule out bleed.
                {"finding": "onset", "op": "contains", "value": "sudden", "acuity": "emergency"},
                {"finding": "worst_ever", "op": "is_true", "acuity": "emergency"},
                {"finding": "associated_symptoms", "op": "contains", "value": "stiff neck", "acuity": "emergency"},
                {"finding": "associated_symptoms", "op": "contains", "value": "confusion", "acuity": "emergency"},
                {"finding": "associated_symptoms", "op": "contains", "value": "weakness", "acuity": "emergency"},
                {"finding": "recent_head_injury", "op": "is_true", "acuity": "high"},
            ],
            "rules": [
                {"finding": "associated_symptoms", "op": "contains", "value": "vision changes", "acuity": "high"},
                {"finding": "severity_1_10", "op": "gte", "value": 8, "acuity": "medium"},
                {"finding": "associated_symptoms", "op": "contains", "value": "fever", "acuity": "medium"},
            ],
            "risk_overrides": [
                # A brand-new headache pattern after 50 warrants prompt review.
                {"risk_factor": "age_gte_50", "raise_to_at_least": "medium"},
                {"risk_factor": "on_blood_thinners", "raise_to_at_least": "high"},
            ],
            "default_acuity": "low",
        },
    },
    {
        "name": "Abdominal Pain",
        "symptom_keywords": [
            "stomach pain", "abdominal pain", "belly pain", "stomach ache",
            "tummy ache", "abdomen hurts", "cramps",
        ],
        "question_flow": [
            {"id": 1, "ask": "Where exactly is the pain — upper, lower, left, right, or all over?", "capture": "location"},
            {"id": 2, "ask": "On a scale of 1 to 10, how severe is it?", "capture": "severity_1_10"},
            {"id": 3, "ask": "When did it start, and is it constant or does it come and go?", "capture": "onset"},
            {"id": 4, "ask": "Any vomiting, blood in vomit or stool, or a fever?", "capture": "associated_symptoms"},
            {"id": 5, "ask": "Is your belly rigid or extremely tender to touch? Any chance of pregnancy?", "capture": "exam_flags"},
        ],
        "disposition_rules": {
            "red_flags": [
                {"finding": "exam_flags", "op": "contains", "value": "rigid", "acuity": "emergency"},
                {"finding": "associated_symptoms", "op": "contains", "value": "blood", "acuity": "emergency"},
                {"finding": "exam_flags", "op": "contains", "value": "pregnan", "acuity": "high"},
                {"finding": "location", "op": "contains", "value": "lower right", "acuity": "high"},
            ],
            "rules": [
                {"finding": "severity_1_10", "op": "gte", "value": 8, "acuity": "high"},
                {"finding": "associated_symptoms", "op": "contains", "value": "fever", "acuity": "high"},
                {"finding": "associated_symptoms", "op": "contains", "value": "vomiting", "acuity": "medium"},
                {"finding": "severity_1_10", "op": "gte", "value": 5, "acuity": "medium"},
            ],
            "risk_overrides": [
                {"risk_factor": "age_gte_65", "raise_to_at_least": "high"},
                {"risk_factor": "immunocompromised", "raise_to_at_least": "high"},
            ],
            "default_acuity": "low",
        },
    },
    {
        "name": "Sore Throat",
        "symptom_keywords": [
            "sore throat", "throat pain", "throat hurts", "difficulty swallowing", "strep",
        ],
        "question_flow": [
            {"id": 1, "ask": "How long have you had the sore throat?", "capture": "duration_hours"},
            {"id": 2, "ask": "Do you have a fever? If so, what's the temperature?", "capture": "temperature_f"},
            {"id": 3, "ask": "Are you having any difficulty breathing, or trouble swallowing your own saliva?", "capture": "associated_symptoms"},
            {"id": 4, "ask": "Any swollen glands, white patches on your tonsils, or a rash?", "capture": "exam_flags"},
            {"id": 5, "ask": "Any recent exposure to someone with strep throat or a similar illness?", "capture": "exposure"},
        ],
        "disposition_rules": {
            "red_flags": [
                {"finding": "associated_symptoms", "op": "contains", "value": "difficulty breathing", "acuity": "emergency"},
                {"finding": "associated_symptoms", "op": "contains", "value": "can't swallow", "acuity": "emergency"},
                {"finding": "temperature_f", "op": "gte", "value": 104, "acuity": "high"},
            ],
            "rules": [
                {"finding": "exam_flags", "op": "contains", "value": "white patches", "acuity": "medium"},
                {"finding": "temperature_f", "op": "gte", "value": 101, "acuity": "medium"},
                {"finding": "duration_hours", "op": "gte", "value": 72, "acuity": "medium"},
            ],
            "risk_overrides": [
                {"risk_factor": "immunocompromised", "raise_to_at_least": "high"},
            ],
            "default_acuity": "low",
        },
    },
    {
        "name": "Back Pain",
        "symptom_keywords": [
            "back pain", "lower back pain", "spine pain", "backache",
        ],
        "question_flow": [
            {"id": 1, "ask": "Where is the pain — upper back, lower back, or does it radiate down a leg?", "capture": "location"},
            {"id": 2, "ask": "On a scale of 1 to 10, how severe is the pain?", "capture": "severity_1_10"},
            {"id": 3, "ask": "Did it start after an injury or lifting something heavy?", "capture": "onset"},
            {"id": 4, "ask": "Any numbness, tingling, or weakness in your legs, or loss of bladder or bowel control?", "capture": "associated_symptoms"},
            {"id": 5, "ask": "Any fever or unexplained weight loss along with the back pain?", "capture": "exam_flags"},
        ],
        "disposition_rules": {
            "red_flags": [
                {"finding": "associated_symptoms", "op": "contains", "value": "bladder", "acuity": "emergency"},
                {"finding": "associated_symptoms", "op": "contains", "value": "bowel", "acuity": "emergency"},
                {"finding": "associated_symptoms", "op": "contains", "value": "weakness", "acuity": "high"},
            ],
            "rules": [
                {"finding": "exam_flags", "op": "contains", "value": "fever", "acuity": "high"},
                {"finding": "severity_1_10", "op": "gte", "value": 8, "acuity": "medium"},
                {"finding": "location", "op": "contains", "value": "radiate", "acuity": "medium"},
            ],
            "risk_overrides": [
                {"risk_factor": "age_gte_65", "raise_to_at_least": "medium"},
                {"risk_factor": "on_blood_thinners", "raise_to_at_least": "medium"},
            ],
            "default_acuity": "low",
        },
    },
    {
        "name": "Shortness of Breath",
        "symptom_keywords": [
            "shortness of breath", "trouble breathing", "can't breathe", "breathless",
            "wheezing", "difficulty breathing",
        ],
        "question_flow": [
            {"id": 1, "ask": "When did the breathing trouble start, and did it come on suddenly?", "capture": "onset"},
            {"id": 2, "ask": "On a scale of 1 to 10, how severe is it right now?", "capture": "severity_1_10"},
            {"id": 3, "ask": "Any chest pain, blue lips, or swelling in your legs?", "capture": "associated_symptoms"},
            {"id": 4, "ask": "Do you have a history of asthma, COPD, or heart failure?", "capture": "history"},
            {"id": 5, "ask": "Can you speak in full sentences, or only a few words at a time?", "capture": "speech"},
        ],
        "disposition_rules": {
            "red_flags": [
                {"finding": "associated_symptoms", "op": "contains", "value": "blue lips", "acuity": "emergency"},
                {"finding": "associated_symptoms", "op": "contains", "value": "chest pain", "acuity": "emergency"},
                {"finding": "speech", "op": "contains", "value": "few words", "acuity": "emergency"},
                {"finding": "onset", "op": "contains", "value": "sudden", "acuity": "high"},
            ],
            "rules": [
                {"finding": "severity_1_10", "op": "gte", "value": 7, "acuity": "high"},
                {"finding": "history", "op": "contains", "value": "asthma", "acuity": "medium"},
                {"finding": "associated_symptoms", "op": "contains", "value": "swelling", "acuity": "medium"},
            ],
            "risk_overrides": [
                {"risk_factor": "age_gte_65", "raise_to_at_least": "high"},
                {"risk_factor": "cardiac_history", "raise_to_at_least": "high"},
            ],
            "default_acuity": "medium",
        },
    },
    {
        "name": "Dizziness",
        "symptom_keywords": [
            "dizziness", "dizzy", "vertigo", "lightheaded", "room spinning",
        ],
        "question_flow": [
            {"id": 1, "ask": "Does it feel like the room is spinning, or more like you might faint?", "capture": "character"},
            {"id": 2, "ask": "When did it start, and is it constant or does it come and go?", "capture": "onset"},
            {"id": 3, "ask": "Any chest pain, slurred speech, weakness on one side, or trouble walking?", "capture": "associated_symptoms"},
            {"id": 4, "ask": "Does it happen mainly when you stand up quickly?", "capture": "positional"},
            {"id": 5, "ask": "Any recent head injury, ear infection, or new medication?", "capture": "exam_flags"},
        ],
        "disposition_rules": {
            "red_flags": [
                {"finding": "associated_symptoms", "op": "contains", "value": "slurred speech", "acuity": "emergency"},
                {"finding": "associated_symptoms", "op": "contains", "value": "weakness", "acuity": "emergency"},
                {"finding": "associated_symptoms", "op": "contains", "value": "trouble walking", "acuity": "emergency"},
                {"finding": "associated_symptoms", "op": "contains", "value": "chest pain", "acuity": "emergency"},
            ],
            "rules": [
                {"finding": "positional", "op": "is_true", "acuity": "medium"},
                {"finding": "character", "op": "contains", "value": "spinning", "acuity": "medium"},
            ],
            "risk_overrides": [
                {"risk_factor": "age_gte_65", "raise_to_at_least": "medium"},
                {"risk_factor": "cardiac_history", "raise_to_at_least": "medium"},
            ],
            "default_acuity": "low",
        },
    },
    {
        "name": "Skin Rash",
        "symptom_keywords": [
            "rash", "skin rash", "hives", "itchy skin", "red spots",
        ],
        "question_flow": [
            {"id": 1, "ask": "When did the rash start, and where on your body is it?", "capture": "location"},
            {"id": 2, "ask": "Is it itchy, painful, or spreading quickly?", "capture": "character"},
            {"id": 3, "ask": "Any fever, difficulty breathing, or swelling of the face, lips, or tongue?", "capture": "associated_symptoms"},
            {"id": 4, "ask": "Did you start any new medication, food, or product recently?", "capture": "exposure"},
            {"id": 5, "ask": "Are there blisters, or does the skin look like it's peeling?", "capture": "exam_flags"},
        ],
        "disposition_rules": {
            "red_flags": [
                {"finding": "associated_symptoms", "op": "contains", "value": "difficulty breathing", "acuity": "emergency"},
                {"finding": "associated_symptoms", "op": "contains", "value": "swelling", "acuity": "emergency"},
                {"finding": "exam_flags", "op": "contains", "value": "peeling", "acuity": "emergency"},
            ],
            "rules": [
                {"finding": "character", "op": "contains", "value": "spreading quickly", "acuity": "high"},
                {"finding": "associated_symptoms", "op": "contains", "value": "fever", "acuity": "medium"},
                {"finding": "exam_flags", "op": "contains", "value": "blisters", "acuity": "medium"},
            ],
            "risk_overrides": [
                {"risk_factor": "immunocompromised", "raise_to_at_least": "medium"},
            ],
            "default_acuity": "low",
        },
    },
    {
        "name": "Urinary Tract Infection",
        "symptom_keywords": [
            "burning urination", "painful urination", "uti", "urinary tract infection",
            "frequent urination", "blood in urine",
        ],
        "question_flow": [
            {"id": 1, "ask": "How long have you had these urinary symptoms?", "capture": "duration_hours"},
            {"id": 2, "ask": "Do you have a fever, or pain in your back or side (flank)?", "capture": "associated_symptoms"},
            {"id": 3, "ask": "Is there any blood in your urine?", "capture": "exam_flags"},
            {"id": 4, "ask": "Any nausea or vomiting along with it?", "capture": "gi_symptoms"},
            {"id": 5, "ask": "Are you currently pregnant, or is there a chance you could be?", "capture": "pregnancy"},
        ],
        "disposition_rules": {
            "red_flags": [
                {"finding": "associated_symptoms", "op": "contains", "value": "flank", "acuity": "high"},
            ],
            "rules": [
                {"finding": "associated_symptoms", "op": "contains", "value": "fever", "acuity": "medium"},
                {"finding": "exam_flags", "op": "contains", "value": "blood", "acuity": "medium"},
                {"finding": "gi_symptoms", "op": "contains", "value": "vomit", "acuity": "medium"},
            ],
            "risk_overrides": [
                {"risk_factor": "diabetes", "raise_to_at_least": "medium"},
                {"risk_factor": "immunocompromised", "raise_to_at_least": "high"},
            ],
            "default_acuity": "low",
        },
    },
    {
        "name": "Cough",
        "symptom_keywords": [
            "cough", "coughing", "chest cold", "persistent cough",
        ],
        "question_flow": [
            {"id": 1, "ask": "How long have you had the cough?", "capture": "duration_hours"},
            {"id": 2, "ask": "Are you coughing up blood, or thick discolored mucus?", "capture": "associated_symptoms"},
            {"id": 3, "ask": "Any fever, chest pain, or shortness of breath with it?", "capture": "exam_flags"},
            {"id": 4, "ask": "Do you have a history of asthma, COPD, or smoking?", "capture": "history"},
            {"id": 5, "ask": "On a scale of 1 to 10, how much is it affecting your breathing?", "capture": "severity_1_10"},
        ],
        "disposition_rules": {
            "red_flags": [
                {"finding": "associated_symptoms", "op": "contains", "value": "blood", "acuity": "emergency"},
                {"finding": "exam_flags", "op": "contains", "value": "shortness of breath", "acuity": "high"},
                {"finding": "exam_flags", "op": "contains", "value": "chest pain", "acuity": "high"},
            ],
            "rules": [
                {"finding": "duration_hours", "op": "gte", "value": 336, "acuity": "medium"},
                {"finding": "exam_flags", "op": "contains", "value": "fever", "acuity": "medium"},
                {"finding": "severity_1_10", "op": "gte", "value": 7, "acuity": "medium"},
            ],
            "risk_overrides": [
                {"risk_factor": "age_gte_65", "raise_to_at_least": "medium"},
                {"risk_factor": "immunocompromised", "raise_to_at_least": "high"},
            ],
            "default_acuity": "low",
        },
    },
    {
        "name": "Diarrhea",
        "symptom_keywords": [
            "diarrhea", "loose stools", "watery stools",
        ],
        "question_flow": [
            {"id": 1, "ask": "How long have you had diarrhea, and how many episodes per day?", "capture": "duration_hours"},
            {"id": 2, "ask": "Any blood, or black tarry stool?", "capture": "associated_symptoms"},
            {"id": 3, "ask": "Any fever, severe abdominal pain, or signs of dehydration like dizziness or a dry mouth?", "capture": "exam_flags"},
            {"id": 4, "ask": "Have you traveled recently or eaten anything unusual?", "capture": "exposure"},
            {"id": 5, "ask": "Are you able to keep fluids down?", "capture": "hydration"},
        ],
        "disposition_rules": {
            "red_flags": [
                {"finding": "associated_symptoms", "op": "contains", "value": "blood", "acuity": "high"},
                {"finding": "exam_flags", "op": "contains", "value": "severe abdominal pain", "acuity": "high"},
                {"finding": "exam_flags", "op": "contains", "value": "dizz", "acuity": "high"},
            ],
            "rules": [
                {"finding": "exam_flags", "op": "contains", "value": "fever", "acuity": "medium"},
                {"finding": "duration_hours", "op": "gte", "value": 72, "acuity": "medium"},
                {"finding": "hydration", "op": "contains", "value": "vomit", "acuity": "medium"},
            ],
            "risk_overrides": [
                {"risk_factor": "age_gte_65", "raise_to_at_least": "medium"},
                {"risk_factor": "immunocompromised", "raise_to_at_least": "high"},
            ],
            "default_acuity": "low",
        },
    },
    {
        "name": "Vomiting and Nausea",
        "symptom_keywords": [
            "vomiting", "throwing up", "nausea", "can't keep food down",
        ],
        "question_flow": [
            {"id": 1, "ask": "How long has the vomiting been going on?", "capture": "duration_hours"},
            {"id": 2, "ask": "Are you able to keep any fluids down?", "capture": "hydration"},
            {"id": 3, "ask": "Any blood in the vomit, or does it look like coffee grounds?", "capture": "associated_symptoms"},
            {"id": 4, "ask": "Any severe abdominal pain, fever, or headache with it?", "capture": "exam_flags"},
            {"id": 5, "ask": "Could you be pregnant, or do you have diabetes?", "capture": "context"},
        ],
        "disposition_rules": {
            "red_flags": [
                {"finding": "associated_symptoms", "op": "contains", "value": "blood", "acuity": "emergency"},
                {"finding": "associated_symptoms", "op": "contains", "value": "coffee grounds", "acuity": "emergency"},
                {"finding": "exam_flags", "op": "contains", "value": "severe abdominal pain", "acuity": "high"},
            ],
            "rules": [
                {"finding": "hydration", "op": "contains", "value": "nothing", "acuity": "high"},
                {"finding": "duration_hours", "op": "gte", "value": 24, "acuity": "medium"},
                {"finding": "exam_flags", "op": "contains", "value": "fever", "acuity": "medium"},
            ],
            "risk_overrides": [
                {"risk_factor": "diabetes", "raise_to_at_least": "high"},
                {"risk_factor": "age_gte_65", "raise_to_at_least": "medium"},
            ],
            "default_acuity": "low",
        },
    },
    {
        "name": "Joint Pain",
        "symptom_keywords": [
            "joint pain", "knee pain", "shoulder pain", "joint swelling", "arthritis flare",
        ],
        "question_flow": [
            {"id": 1, "ask": "Which joint or joints are affected?", "capture": "location"},
            {"id": 2, "ask": "Is the joint red, hot, and swollen, or just painful?", "capture": "exam_flags"},
            {"id": 3, "ask": "Did it start after an injury, or gradually with no clear cause?", "capture": "onset"},
            {"id": 4, "ask": "Any fever along with the joint pain?", "capture": "associated_symptoms"},
            {"id": 5, "ask": "On a scale of 1 to 10, how severe is the pain?", "capture": "severity_1_10"},
        ],
        "disposition_rules": {
            "red_flags": [
                {"finding": "exam_flags", "op": "contains", "value": "hot", "acuity": "high"},
                {"finding": "associated_symptoms", "op": "contains", "value": "fever", "acuity": "high"},
            ],
            "rules": [
                {"finding": "onset", "op": "contains", "value": "injury", "acuity": "medium"},
                {"finding": "severity_1_10", "op": "gte", "value": 8, "acuity": "medium"},
                {"finding": "exam_flags", "op": "contains", "value": "swollen", "acuity": "medium"},
            ],
            "risk_overrides": [
                {"risk_factor": "immunocompromised", "raise_to_at_least": "high"},
                {"risk_factor": "on_blood_thinners", "raise_to_at_least": "medium"},
            ],
            "default_acuity": "low",
        },
    },
    {
        "name": "Eye Problem",
        "symptom_keywords": [
            "eye pain", "red eye", "eye infection", "vision problem", "eye injury",
        ],
        "question_flow": [
            {"id": 1, "ask": "Which eye is affected, and when did the symptoms start?", "capture": "onset"},
            {"id": 2, "ask": "Any sudden vision loss, or does your vision look blurry?", "capture": "associated_symptoms"},
            {"id": 3, "ask": "Any eye pain, discharge, or sensitivity to light?", "capture": "exam_flags"},
            {"id": 4, "ask": "Did you get anything in your eye, or have a recent injury or chemical exposure?", "capture": "exposure"},
            {"id": 5, "ask": "Are you a contact lens wearer?", "capture": "history"},
        ],
        "disposition_rules": {
            "red_flags": [
                {"finding": "associated_symptoms", "op": "contains", "value": "sudden vision loss", "acuity": "emergency"},
                {"finding": "exposure", "op": "contains", "value": "chemical", "acuity": "emergency"},
                {"finding": "exam_flags", "op": "contains", "value": "severe pain", "acuity": "high"},
            ],
            "rules": [
                {"finding": "associated_symptoms", "op": "contains", "value": "blurry", "acuity": "medium"},
                {"finding": "exam_flags", "op": "contains", "value": "light", "acuity": "medium"},
                {"finding": "history", "op": "contains", "value": "contact", "acuity": "medium"},
            ],
            "risk_overrides": [
                {"risk_factor": "diabetes", "raise_to_at_least": "medium"},
                {"risk_factor": "immunocompromised", "raise_to_at_least": "high"},
            ],
            "default_acuity": "low",
        },
    },
    {
        "name": "Ear Pain",
        "symptom_keywords": [
            "ear pain", "earache", "ear infection", "ear discharge",
        ],
        "question_flow": [
            {"id": 1, "ask": "How long has the ear pain lasted?", "capture": "duration_hours"},
            {"id": 2, "ask": "Any fever, hearing loss, or discharge from the ear?", "capture": "associated_symptoms"},
            {"id": 3, "ask": "On a scale of 1 to 10, how severe is the pain?", "capture": "severity_1_10"},
            {"id": 4, "ask": "Any swelling or redness behind the ear?", "capture": "exam_flags"},
            {"id": 5, "ask": "Any recent water exposure (like swimming) or a cold?", "capture": "exposure"},
        ],
        "disposition_rules": {
            "red_flags": [
                {"finding": "exam_flags", "op": "contains", "value": "behind", "acuity": "emergency"},
            ],
            "rules": [
                {"finding": "associated_symptoms", "op": "contains", "value": "discharge", "acuity": "medium"},
                {"finding": "associated_symptoms", "op": "contains", "value": "fever", "acuity": "medium"},
                {"finding": "severity_1_10", "op": "gte", "value": 7, "acuity": "medium"},
            ],
            "risk_overrides": [
                {"risk_factor": "immunocompromised", "raise_to_at_least": "high"},
                {"risk_factor": "diabetes", "raise_to_at_least": "medium"},
            ],
            "default_acuity": "low",
        },
    },
    {
        "name": "Allergic Reaction",
        "symptom_keywords": [
            "allergic reaction", "allergy", "swelling after eating", "hives after", "bee sting reaction",
        ],
        "question_flow": [
            {"id": 1, "ask": "What triggered the reaction, if you know (food, medication, insect sting)?", "capture": "exposure"},
            {"id": 2, "ask": "Any swelling of the lips, tongue, throat, or trouble breathing?", "capture": "associated_symptoms"},
            {"id": 3, "ask": "Any hives or rash, and is it spreading?", "capture": "exam_flags"},
            {"id": 4, "ask": "Do you have an epinephrine auto-injector (EpiPen), and have you used it?", "capture": "intervention"},
            {"id": 5, "ask": "Any dizziness, fainting, or a fast heartbeat?", "capture": "severity_signs"},
        ],
        "disposition_rules": {
            "red_flags": [
                {"finding": "associated_symptoms", "op": "contains", "value": "trouble breathing", "acuity": "emergency"},
                {"finding": "associated_symptoms", "op": "contains", "value": "throat", "acuity": "emergency"},
                {"finding": "severity_signs", "op": "contains", "value": "fainting", "acuity": "emergency"},
            ],
            "rules": [
                {"finding": "exam_flags", "op": "contains", "value": "spreading", "acuity": "high"},
                {"finding": "intervention", "op": "contains", "value": "used", "acuity": "high"},
            ],
            "risk_overrides": [
                {"risk_factor": "immunocompromised", "raise_to_at_least": "medium"},
            ],
            "default_acuity": "medium",
        },
    },
    {
        "name": "Anxiety and Panic Attack",
        "symptom_keywords": [
            "anxiety", "panic attack", "feeling anxious", "heart racing panic",
        ],
        "question_flow": [
            {"id": 1, "ask": "When did these feelings start, and have you had panic attacks before?", "capture": "history"},
            {"id": 2, "ask": "Are you having chest pain, trouble breathing, or numbness and tingling?", "capture": "associated_symptoms"},
            {"id": 3, "ask": "On a scale of 1 to 10, how distressing does this feel right now?", "capture": "severity_1_10"},
            {"id": 4, "ask": "Are you having any thoughts of harming yourself or others?", "capture": "safety"},
            {"id": 5, "ask": "Is this the first time, or does this happen often?", "capture": "frequency"},
        ],
        "disposition_rules": {
            "red_flags": [
                {"finding": "safety", "op": "is_true", "acuity": "emergency"},
                {"finding": "associated_symptoms", "op": "contains", "value": "chest pain", "acuity": "high"},
            ],
            "rules": [
                {"finding": "associated_symptoms", "op": "contains", "value": "numbness", "acuity": "medium"},
                {"finding": "severity_1_10", "op": "gte", "value": 8, "acuity": "medium"},
            ],
            "risk_overrides": [
                {"risk_factor": "cardiac_history", "raise_to_at_least": "high"},
            ],
            "default_acuity": "low",
        },
    },
    {
        "name": "Insomnia",
        "symptom_keywords": [
            "can't sleep", "insomnia", "trouble sleeping", "sleep problems",
        ],
        "question_flow": [
            {"id": 1, "ask": "How long has this been going on?", "capture": "duration_hours"},
            {"id": 2, "ask": "Is stress, pain, or a medical condition keeping you awake?", "capture": "cause"},
            {"id": 3, "ask": "Any low mood, hopelessness, or thoughts of self-harm along with the sleep trouble?", "capture": "safety"},
            {"id": 4, "ask": "Are you using any new medications, caffeine, or alcohol close to bedtime?", "capture": "exposure"},
            {"id": 5, "ask": "How is this affecting your daily functioning — work, driving, mood?", "capture": "impact"},
        ],
        "disposition_rules": {
            "red_flags": [
                {"finding": "safety", "op": "is_true", "acuity": "emergency"},
            ],
            "rules": [
                {"finding": "impact", "op": "contains", "value": "can't function", "acuity": "medium"},
                {"finding": "duration_hours", "op": "gte", "value": 720, "acuity": "medium"},
            ],
            "risk_overrides": [],
            "default_acuity": "minimal",
        },
    },
    {
        "name": "Minor Injury",
        "symptom_keywords": [
            "cut", "laceration", "sprain", "twisted ankle", "fell down", "minor injury",
        ],
        "question_flow": [
            {"id": 1, "ask": "What happened, and when did the injury occur?", "capture": "onset"},
            {"id": 2, "ask": "Is there heavy bleeding that won't stop with firm pressure?", "capture": "associated_symptoms"},
            {"id": 3, "ask": "Can you move and bear weight on the injured area?", "capture": "function"},
            {"id": 4, "ask": "Is there any visible deformity, or bone showing?", "capture": "exam_flags"},
            {"id": 5, "ask": "On a scale of 1 to 10, how severe is the pain?", "capture": "severity_1_10"},
        ],
        "disposition_rules": {
            "red_flags": [
                {"finding": "associated_symptoms", "op": "contains", "value": "won't stop", "acuity": "emergency"},
                {"finding": "exam_flags", "op": "contains", "value": "bone", "acuity": "emergency"},
                {"finding": "exam_flags", "op": "contains", "value": "deformity", "acuity": "high"},
            ],
            "rules": [
                {"finding": "function", "op": "contains", "value": "can't", "acuity": "medium"},
                {"finding": "severity_1_10", "op": "gte", "value": 7, "acuity": "medium"},
            ],
            "risk_overrides": [
                {"risk_factor": "on_blood_thinners", "raise_to_at_least": "high"},
                {"risk_factor": "age_gte_65", "raise_to_at_least": "medium"},
            ],
            "default_acuity": "low",
        },
    },
    {
        "name": "Pregnancy Concern",
        "symptom_keywords": [
            "pregnant and bleeding", "pregnancy pain", "morning sickness severe",
            "pregnancy concern", "reduced baby movement",
        ],
        "question_flow": [
            {"id": 1, "ask": "How many weeks pregnant are you?", "capture": "gestation_weeks"},
            {"id": 2, "ask": "Are you having any vaginal bleeding or fluid leakage?", "capture": "associated_symptoms"},
            {"id": 3, "ask": "Any severe abdominal pain, contractions, or reduced baby movement?", "capture": "exam_flags"},
            {"id": 4, "ask": "Any severe headache, vision changes, or swelling of your hands or face?", "capture": "preeclampsia_signs"},
            {"id": 5, "ask": "On a scale of 1 to 10, how would you rate your pain or discomfort?", "capture": "severity_1_10"},
        ],
        "disposition_rules": {
            "red_flags": [
                {"finding": "associated_symptoms", "op": "contains", "value": "bleeding", "acuity": "emergency"},
                {"finding": "exam_flags", "op": "contains", "value": "reduced", "acuity": "emergency"},
                {"finding": "preeclampsia_signs", "op": "contains", "value": "vision", "acuity": "emergency"},
            ],
            "rules": [
                {"finding": "exam_flags", "op": "contains", "value": "contractions", "acuity": "high"},
                {"finding": "preeclampsia_signs", "op": "contains", "value": "swelling", "acuity": "high"},
                {"finding": "severity_1_10", "op": "gte", "value": 7, "acuity": "medium"},
            ],
            "risk_overrides": [
                {"risk_factor": "diabetes", "raise_to_at_least": "medium"},
            ],
            "default_acuity": "medium",
        },
    },
    {
        "name": "Diabetes Blood Sugar Issue",
        "symptom_keywords": [
            "blood sugar high", "blood sugar low", "hyperglycemia", "hypoglycemia", "diabetic emergency",
        ],
        "question_flow": [
            {"id": 1, "ask": "What is your current blood sugar reading, if you've checked?", "capture": "glucose_mg_dl"},
            {"id": 2, "ask": "Are you feeling shaky, sweaty, confused, or like you might pass out?", "capture": "associated_symptoms"},
            {"id": 3, "ask": "Are you able to eat or drink normally right now?", "capture": "hydration"},
            {"id": 4, "ask": "Any nausea, vomiting, or fruity-smelling breath?", "capture": "exam_flags"},
            {"id": 5, "ask": "Have you taken your insulin or diabetes medication as usual today?", "capture": "medication_adherence"},
        ],
        "disposition_rules": {
            "red_flags": [
                {"finding": "glucose_mg_dl", "op": "lte", "value": 54, "acuity": "emergency"},
                {"finding": "glucose_mg_dl", "op": "gte", "value": 400, "acuity": "emergency"},
                {"finding": "associated_symptoms", "op": "contains", "value": "pass out", "acuity": "emergency"},
                {"finding": "associated_symptoms", "op": "contains", "value": "confused", "acuity": "emergency"},
                {"finding": "exam_flags", "op": "contains", "value": "fruity", "acuity": "emergency"},
            ],
            "rules": [
                {"finding": "glucose_mg_dl", "op": "lte", "value": 70, "acuity": "high"},
                {"finding": "glucose_mg_dl", "op": "gte", "value": 300, "acuity": "high"},
                {"finding": "associated_symptoms", "op": "contains", "value": "shaky", "acuity": "medium"},
            ],
            "risk_overrides": [
                {"risk_factor": "age_gte_65", "raise_to_at_least": "medium"},
            ],
            "default_acuity": "low",
        },
    },
    {
        "name": "Asthma Flare",
        "symptom_keywords": [
            "asthma attack", "wheezing", "asthma flare", "inhaler not working",
        ],
        "question_flow": [
            {"id": 1, "ask": "Are you using your rescue inhaler, and is it helping?", "capture": "intervention"},
            {"id": 2, "ask": "Can you speak in full sentences, or only a few words at a time?", "capture": "speech"},
            {"id": 3, "ask": "Are your lips or fingertips turning blue?", "capture": "associated_symptoms"},
            {"id": 4, "ask": "On a scale of 1 to 10, how hard is it to breathe right now?", "capture": "severity_1_10"},
            {"id": 5, "ask": "How many times have you needed your rescue inhaler in the last 24 hours?", "capture": "inhaler_uses_24h"},
        ],
        "disposition_rules": {
            "red_flags": [
                {"finding": "associated_symptoms", "op": "contains", "value": "blue", "acuity": "emergency"},
                {"finding": "speech", "op": "contains", "value": "few words", "acuity": "emergency"},
                {"finding": "intervention", "op": "contains", "value": "not helping", "acuity": "high"},
            ],
            "rules": [
                {"finding": "severity_1_10", "op": "gte", "value": 7, "acuity": "high"},
                {"finding": "inhaler_uses_24h", "op": "gte", "value": 4, "acuity": "high"},
            ],
            "risk_overrides": [
                {"risk_factor": "age_gte_65", "raise_to_at_least": "high"},
            ],
            "default_acuity": "medium",
        },
    },
    {
        "name": "Low Mood Check-in",
        "symptom_keywords": [
            "feeling depressed", "low mood", "sad all the time", "no motivation", "depression",
        ],
        "question_flow": [
            {"id": 1, "ask": "How long have you been feeling this way?", "capture": "duration_hours"},
            {"id": 2, "ask": "Have you had any thoughts of harming yourself or ending your life?", "capture": "safety"},
            {"id": 3, "ask": "Do you have a specific plan or means to harm yourself?", "capture": "plan"},
            {"id": 4, "ask": "Is this affecting your ability to work, eat, or sleep?", "capture": "impact"},
            {"id": 5, "ask": "Do you have support around you right now — family or friends?", "capture": "support"},
        ],
        "disposition_rules": {
            "red_flags": [
                {"finding": "plan", "op": "is_true", "acuity": "emergency"},
                {"finding": "safety", "op": "is_true", "acuity": "high"},
            ],
            "rules": [
                {"finding": "impact", "op": "contains", "value": "can't", "acuity": "medium"},
                {"finding": "duration_hours", "op": "gte", "value": 336, "acuity": "medium"},
            ],
            "risk_overrides": [],
            "default_acuity": "low",
        },
    },
]


class Command(BaseCommand):
    help = (
        "Load or update the clinical triage protocols: the original 5 "
        "(chest pain, adult/pediatric fever, headache, abdominal pain) plus "
        "20 more spanning common complaints (sore throat, back pain, "
        "shortness of breath, dizziness, skin rash, UTI, cough, diarrhea, "
        "vomiting, joint pain, eye/ear problems, allergic reaction, anxiety, "
        "insomnia, minor injury, pregnancy concern, diabetes/blood sugar, "
        "asthma flare, low mood). Idempotent — matches on protocol name. "
        "Dev seed data: pending clinical approval."
    )

    def handle(self, *args, **options):
        for spec in PROTOCOLS:
            protocol, created = ClinicalProtocol.objects.update_or_create(
                name=spec["name"],
                defaults={
                    "symptom_keywords": spec["symptom_keywords"],
                    "question_flow": spec["question_flow"],
                    "disposition_rules": spec["disposition_rules"],
                    "version": "1.0",
                    "is_active": True,
                },
            )
            self.stdout.write(
                f"{'created' if created else 'updated'}: {protocol.name} "
                f"({len(protocol.question_flow)} questions, "
                f"{len(protocol.disposition_rules['red_flags'])} red flags)"
            )
        self.stdout.write(self.style.SUCCESS(
            f"{len(PROTOCOLS)} protocols seeded. Review and set approved_by "
            "in /admin/ before clinical use."
        ))
