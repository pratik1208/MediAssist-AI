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
]


class Command(BaseCommand):
    help = (
        "Load or update the starter clinical triage protocols (chest pain, "
        "pediatric fever, headache, abdominal pain). Idempotent — matches on "
        "protocol name. Dev seed data: pending clinical approval."
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
