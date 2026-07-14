"""seed_refill_pipeline — the full refill-request lifecycle, for real.

RefillRequest has no seed path at all today (it's only ever created from
refills/views.py's live "request a refill" endpoint), so the refill queue
is empty on a fresh clinic. This creates a request for each of the six
seeded eligibility-branch prescriptions (refills/seed_prescriptions.py),
mirroring exactly how the real view creates one, then runs
services.run_eligibility_check() for a genuine outcome: Atorvastatin
(missing labs), Levothyroxine (follow-up required), and Losartan (expired)
auto-pause for real, no fixture-faking needed. Amlodipine and Alprazolam
(controlled) reach pending_approval; Amlodipine is driven through approve()
to sent_to_pharmacy, Alprazolam is left untouched (the human-must-review
case, Edge Case 12). Metformin is driven through reject(), then a second
request for the same prescription is driven through request_visit() —
showing both physician decisions on the one eligible-but-zero-refills-left
chart.

Requires patients, doctors, and prescriptions to exist; no-ops with a
warning otherwise. Idempotent: each medication is capped at its intended
request count (2 for Metformin, 1 for everything else).
"""

from django.core.management.base import BaseCommand

from core.models import Doctor
from refills.models import Pharmacy, Prescription, RefillRequest
from refills.services import approve, reject, request_visit, run_eligibility_check

# medication -> how many RefillRequests this command intends to leave behind.
TARGET_COUNTS = {
    "Amlodipine": 1, "Metformin": 2, "Atorvastatin": 1,
    "Levothyroxine": 1, "Losartan": 1, "Alprazolam": 1,
}


class Command(BaseCommand):
    help = "Seed refill requests across every status via real service calls (idempotent)."

    def handle(self, *args, **options):
        doctor = Doctor.objects.filter(specialty="General Medicine").first()
        pharmacy = Pharmacy.objects.first()
        if doctor is None or pharmacy is None:
            self.stdout.write(self.style.WARNING(
                "missing a doctor or pharmacy — run seed_doctors and "
                "seed_prescriptions first"))
            return

        created = skipped = 0
        for medication, target in TARGET_COUNTS.items():
            prescription = (Prescription.objects
                            .filter(medication_name=medication, status__in=("active", "expired"))
                            .order_by("-id").first())
            if prescription is None:
                skipped += 1
                continue
            # approve() writes back a NEW Prescription row for the same
            # medication (marking the old one superseded), so counting
            # requests against just THIS prescription row would chase a
            # moving target on every rerun — scope the idempotency check to
            # the (patient, medication) pair across all of that patient's
            # prescription rows for it instead.
            existing = RefillRequest.objects.filter(
                patient=prescription.patient,
                prescription__medication_name=medication).count()
            while existing < target:
                request = RefillRequest.objects.create(
                    prescription=prescription, patient=prescription.patient, pharmacy=pharmacy,
                )
                run_eligibility_check(request)
                request.refresh_from_db()
                self._decide(medication, existing, request, doctor)
                created += 1
                existing += 1

        if skipped:
            self.stdout.write(self.style.WARNING(
                f"{skipped} target prescriptions missing — run seed_prescriptions first"))
        self.stdout.write(self.style.SUCCESS(f"seeded {created} new refill requests"))

    def _decide(self, medication, index, request, doctor):
        """index is 0 for the first request on this prescription, 1 for the second."""
        if request.status != "pending_approval":
            return  # auto-paused (labs/follow-up/expired) -- leave as-is
        if medication == "Amlodipine":
            approve(request, doctor)
        elif medication == "Metformin":
            if index == 0:
                reject(request, doctor, "Renewal requires an in-person visit first.")
            else:
                request_visit(request, doctor)
        # Alprazolam: controlled substance -- left at pending_approval on purpose.
