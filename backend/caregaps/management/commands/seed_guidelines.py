"""seed_guidelines — the five starter clinical guidelines (Agent 8, Phase 1).

Each row is one preventive-care rule the Phase 2 scanner will evaluate:
"is the patient in this population, and is a ClinicalEvent with this code
missing or older than frequency_days?"

population_criteria uses the shared cohort schema (outreach.build_cohort).
Two rows use `has_diagnosis_code` — a planned Phase 2 extension of
_SUPPORTED_CRITERIA_KEYS backed by ClinicalEvent(event_type="diagnosis")
rows, exactly the extension path build_cohort's docstring reserves. The
post-discharge rule likewise anchors on a discharge event rather than a
calendar cycle; its scanner semantics land in Phase 2.

Known limitation: Patient has no sex/gender field, so the mammogram rule is
scoped by age band only.

Idempotent: keyed on guideline name; reruns update in place.
"""

from django.core.management.base import BaseCommand

from caregaps.models import ClinicalGuideline

# LOINC (labs) / CPT (procedures, visits) / CVX (vaccines) style codes —
# these are what seeded/extracted ClinicalEvent rows must use to match.
GUIDELINES = [
    {"name": "HbA1c every 6 months for diabetics",
     "population_criteria": {"has_diagnosis_code": "E11"},  # ICD-10 type 2 diabetes
     "care_item_type": "test", "care_item_code": "4548-4",  # LOINC HbA1c
     "frequency_days": 182, "risk_tier": "high"},

    {"name": "Annual diabetic eye exam",
     "population_criteria": {"has_diagnosis_code": "E11"},
     "care_item_type": "screening", "care_item_code": "92014",  # CPT eye exam
     "frequency_days": 365, "risk_tier": "medium"},

    {"name": "Annual flu vaccine for 65+",
     "population_criteria": {"age_min": 65},
     "care_item_type": "vaccination", "care_item_code": "140",  # CVX influenza
     "frequency_days": 365, "risk_tier": "medium"},

    {"name": "Mammogram screening every 2 years (40-74)",
     "population_criteria": {"age_min": 40, "age_max": 74},
     "care_item_type": "screening", "care_item_code": "77067",  # CPT screening mammography
     "frequency_days": 730, "risk_tier": "high"},

    {"name": "Post-discharge follow-up visit within 14 days",
     "population_criteria": {"has_event_code": "99238"},  # CPT hospital discharge
     "care_item_type": "followup", "care_item_code": "99495",  # CPT transitional care visit
     "frequency_days": 14, "risk_tier": "high"},
]


class Command(BaseCommand):
    help = "Seed the starter clinical guidelines (idempotent — keyed on name)."

    def handle(self, *args, **options):
        created = 0
        for spec in GUIDELINES:
            _, was_created = ClinicalGuideline.objects.update_or_create(
                name=spec["name"],
                defaults={k: v for k, v in spec.items() if k != "name"},
            )
            created += was_created
            self.stdout.write(f"{'created' if was_created else 'updated'}: {spec['name']}")
        self.stdout.write(self.style.SUCCESS(
            f"seeded {len(GUIDELINES)} clinical guidelines ({created} new)"))
