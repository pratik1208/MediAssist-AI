"""seed_clinical_events — diagnosis history for the diabetic cohort.

Two of the five seeded ClinicalGuidelines ("HbA1c every 6 months for
diabetics", "Annual diabetic eye exam") are keyed on
population_criteria={"has_diagnosis_code": "E11"} — but nothing seeds any
ClinicalEvent rows, so those two guidelines can never match a single
patient no matter how many times the gap scanner runs. This tags a handful
of the existing 40+ roster patients as diabetic (a real ClinicalEvent, the
same shape document extraction would produce) so the full guideline set has
real coverage.

Requires patients (seed_patients) to exist; no-ops with a warning otherwise.
Idempotent: keyed on (patient, event_type, code). Must run before
scan_care_gaps.
"""

import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from caregaps.models import ClinicalEvent
from core.models import Patient

# 40+ patients tagged diabetic (E11) -- spans both the 65+ and 40-64 seed_patients bands.
DIABETIC_PHONES = [
    "9820010001",  # Kamala Iyer, 72
    "9820010006",  # Lakshmi Rao, 69
    "9820020001",  # Sunita Patil, 54
    "9820020004",  # Anil Verma, 58
    "9820020006",  # Subhash Ghosh, 63
    "9820020010",  # Thomas Mathew, 60
]


class Command(BaseCommand):
    help = "Seed diagnosis ClinicalEvents (E11) for the diabetic cohort (idempotent)."

    def handle(self, *args, **options):
        created = skipped = 0
        occurred_at = timezone.now() - datetime.timedelta(days=400)
        for phone in DIABETIC_PHONES:
            patient = Patient.objects.filter(contact_number=phone).first()
            if patient is None:
                skipped += 1
                continue
            _, was_created = ClinicalEvent.objects.get_or_create(
                patient=patient, event_type="diagnosis", code="E11",
                defaults={"value": {}, "occurred_at": occurred_at},
            )
            created += was_created

        if skipped:
            self.stdout.write(self.style.WARNING(
                f"{skipped} roster patients missing — run seed_patients first"))
        self.stdout.write(self.style.SUCCESS(
            f"seeded {created} new diagnosis events across {len(DIABETIC_PHONES)} patients"))
