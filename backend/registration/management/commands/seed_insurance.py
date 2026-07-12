"""seed_insurance — insurance policies + intake summaries for the roster.

Covers ~half the curated patients, with provider_name/plan values that MATCH
the seeded priorauth PayerRule rows (BlueShield "Premium PPO"/"Basic HMO",
Star Health, Apollo Munich, HDFC Ergo) so prior-auth detection has real hits
when a treatment order is created for these patients.

Requires patients (seed_patients) to exist; no-ops with a warning otherwise.
Idempotent: keyed on (patient, policy_number).
"""

import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.management.commands.seed_patients import PATIENTS
from core.models import Patient
from registration.models import InsurancePolicy, IntakeSummary

# Cycled across insured patients; None plan = "any plan" on the payer side.
PLANS = [
    ("BlueShield", "Premium PPO"),
    ("Star Health", None),
    ("Apollo Munich", None),
    ("HDFC Ergo", None),
    ("BlueShield", "Basic HMO"),
]


class Command(BaseCommand):
    help = "Seed insurance policies + intake summaries for ~half the roster (idempotent)."

    def handle(self, *args, **options):
        today = timezone.localdate()
        policies = summaries = skipped = 0

        # Every other roster patient gets insurance, cycling through the plans.
        insured = [entry for i, entry in enumerate(PATIENTS) if i % 2 == 0]
        for n, entry in enumerate(insured):
            patient = Patient.objects.filter(contact_number=entry["phone"]).first()
            if patient is None:
                skipped += 1
                continue
            provider, plan = PLANS[n % len(PLANS)]
            policy_number = f"{provider[:2].upper()}-{entry['phone'][-4:]}"
            _, created = InsurancePolicy.objects.update_or_create(
                patient=patient, policy_number=policy_number,
                defaults={
                    "member_id": f"M{entry['phone'][-6:]}",
                    "provider_name": provider,
                    "plan": plan,
                    "coverage_details": f"{provider} {plan or 'standard'} — outpatient + diagnostics.",
                    "coverage_start": today - datetime.timedelta(days=200),
                    "coverage_end": today + datetime.timedelta(days=165),
                    "eligibility_status": "eligible",
                    "eligibility_checked_at": timezone.now(),
                },
            )
            policies += created

            _, s_created = IntakeSummary.objects.get_or_create(
                patient=patient,
                defaults={
                    "clinical_profile": {"insurer": provider, "language": entry["lang"]},
                    "summary_text": (
                        f"{patient.first_name} {patient.last_name}, insured with "
                        f"{provider}. Seed intake record."),
                },
            )
            summaries += s_created

        if skipped:
            self.stdout.write(self.style.WARNING(
                f"{skipped} roster patients missing — run seed_patients first"))
        self.stdout.write(self.style.SUCCESS(
            f"seeded {policies} new policies and {summaries} new intake summaries "
            f"across {len(insured)} insured patients"))
