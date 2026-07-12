"""seed_prescriptions — fixture pharmacies and prescriptions (Agent 4, Phase 1).

One prescription per eligibility branch of FR-M3, so Phase 2's
check_eligibility() and every edge case (PRD 1, 2, 12) have fixture data:

  - eligible: active, unexpired, refills remaining, no labs/follow-up due
  - zero refills left           -> renewal path (Edge Case 1)
  - required labs outstanding   -> paused path (Edge Case 2)
  - follow-up visit outstanding -> paused path
  - expired prescription        -> ineligible
  - controlled substance        -> NEVER auto-processed (Edge Case 12)

Idempotent: rerunning updates by (patient, medication_name), never duplicates.
Spreads the prescriptions across the first few existing patients (or creates a
single demo patient/doctor on an otherwise-empty DB).
"""

import datetime

from django.core.management.base import BaseCommand

from core.models import Doctor, Patient
from refills.models import Pharmacy, Prescription

TODAY = datetime.date.today()

PHARMACIES = [
    {"name": "Apollo Pharmacy, MG Road", "phone": "020-2612-0000",
     "address": {"line1": "12 MG Road", "city": "Pune", "state": "MH", "zip": "411001"},
     "erx_identifier": "APOLLO-MG-411001"},
    {"name": "Wellness Forever, FC Road", "phone": "020-2567-0000",
     "address": {"line1": "88 FC Road", "city": "Pune", "state": "MH", "zip": "411004"},
     "erx_identifier": "WF-FC-411004"},
]

# (medication, dose, quantity, overrides) — one row per eligibility branch.
PRESCRIPTIONS = [
    ("Amlodipine", "5 mg", "30 tablets", {
        # the clean, eligible refill
        "refills_allowed": 5, "refills_used": 1,
    }),
    ("Metformin", "500 mg", "60 tablets", {
        # zero refills remaining -> renewal, not refill (Edge Case 1)
        "refills_allowed": 3, "refills_used": 3,
    }),
    ("Atorvastatin", "20 mg", "30 tablets", {
        # labs must be current before refilling (Edge Case 2)
        "refills_allowed": 4, "refills_used": 1,
        "required_labs": [{"test": "lipid_panel", "max_age_days": 180},
                          {"test": "liver_function", "max_age_days": 365}],
    }),
    ("Levothyroxine", "50 mcg", "90 tablets", {
        # outstanding follow-up visit blocks the refill
        "refills_allowed": 4, "refills_used": 2,
        "followup_required": True,
    }),
    ("Losartan", "50 mg", "30 tablets", {
        # expired prescription -> ineligible
        "refills_allowed": 5, "refills_used": 2,
        "prescribed_date": TODAY - datetime.timedelta(days=500),
        "expiry_date": TODAY - datetime.timedelta(days=135),
        "status": "expired",
    }),
    ("Alprazolam", "0.5 mg", "30 tablets", {
        # controlled substance: never auto-processed (Edge Case 12)
        "refills_allowed": 2, "refills_used": 0,
        "is_controlled_substance": True,
    }),
]


class Command(BaseCommand):
    help = ("Load fixture pharmacies and prescriptions covering every "
            "eligibility branch. Idempotent — matches on (patient, medication).")

    def handle(self, *args, **options):
        patient = Patient.objects.order_by("id").first()
        if patient is None:
            patient = Patient.objects.create(
                first_name="Rahul", last_name="Sharma",
                contact_number="9876543210", dob=datetime.date(1990, 5, 17),
            )
            self.stdout.write("created demo patient Rahul Sharma")

        # Spread the prescriptions across the first few patients so more than
        # one chart has medications (falls back to the single demo patient on
        # an otherwise-empty DB). Each (patient, medication) pair stays stable
        # across reruns, so idempotency holds.
        patients = list(Patient.objects.order_by("id")[:3]) or [patient]

        doctor = Doctor.objects.order_by("id").first()
        if doctor is None:
            doctor = Doctor.objects.create(
                name="Dr. Asha Mehta", specialty="General Medicine",
                working_hours={"mon": [["09:00", "17:00"]],
                               "tue": [["09:00", "17:00"]],
                               "wed": [["09:00", "17:00"]],
                               "thu": [["09:00", "17:00"]],
                               "fri": [["09:00", "17:00"]]},
            )
            self.stdout.write("created demo doctor Dr. Asha Mehta")

        for spec in PHARMACIES:
            _, created = Pharmacy.objects.update_or_create(
                name=spec["name"], defaults={k: v for k, v in spec.items() if k != "name"},
            )
            self.stdout.write(f"{'created' if created else 'updated'} pharmacy: {spec['name']}")

        for i, (medication, dose, quantity, overrides) in enumerate(PRESCRIPTIONS):
            patient = patients[i % len(patients)]
            defaults = {
                "prescriber": doctor,
                "dose": dose,
                "quantity": quantity,
                "prescribed_date": TODAY - datetime.timedelta(days=60),
                "expiry_date": TODAY + datetime.timedelta(days=305),
                "status": "active",
                "required_labs": [],
                "followup_required": False,
                "is_controlled_substance": False,
                **overrides,
            }
            # An approval writes back a NEW row for the same medication (see
            # services.approve), so (patient, medication) is not unique —
            # update the newest row and retire any older active duplicates,
            # the same invariant approve() maintains.
            rows = Prescription.objects.filter(
                patient=patient, medication_name=medication,
            ).order_by("-id")
            prescription = rows.first()
            created = prescription is None
            if created:
                prescription = Prescription.objects.create(
                    patient=patient, medication_name=medication, **defaults,
                )
            else:
                for field, value in defaults.items():
                    setattr(prescription, field, value)
                prescription.save()
                rows.exclude(id=prescription.id).filter(status="active").update(
                    status="superseded",
                )
            flags = []
            if prescription.is_controlled_substance:
                flags.append("CONTROLLED")
            if prescription.refills_used >= prescription.refills_allowed:
                flags.append("no refills left")
            if prescription.required_labs:
                flags.append("labs required")
            if prescription.followup_required:
                flags.append("follow-up required")
            if prescription.status != "active":
                flags.append(prescription.status)
            note = f" [{', '.join(flags)}]" if flags else " [eligible]"
            self.stdout.write(
                f"{'created' if created else 'updated'}: {medication} {dose}{note}"
            )

        self.stdout.write(self.style.SUCCESS(
            f"seeded {len(PHARMACIES)} pharmacies and {len(PRESCRIPTIONS)} "
            f"prescriptions across {len(patients)} patient(s)"
        ))
