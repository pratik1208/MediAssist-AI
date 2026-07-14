"""seed_priorauth_pipeline — the full authorization lifecycle, for real.

TreatmentOrder and AuthorizationRequest have no seed at all today, so the
prior-auth queue is empty on a fresh clinic. This creates a TreatmentOrder
for four patients whose seeded InsurancePolicy actually matches a seeded
PayerRule (cross-referenced with registration/seed_insurance.py and
priorauth/seed_payer_rules.py so initiate_authorization() gets a real hit
instead of returning None), then drives each through real service calls
(initiate_authorization, submit, poll_status) to a different stopping
point: one left at "ready_for_review" for staff to submit, one "submitted"
(mid-flight), one driven to "approved", one to "denied" (via the
SimulatedPayerGateway's force_response fixture hook).

Requires patients, doctors, insurance policies, and payer rules to exist;
no-ops with a warning otherwise. Idempotent: skips a patient who already has
an AuthorizationRequest.
"""

from django.core.management.base import BaseCommand

from core.models import Doctor, Patient
from priorauth.gateway import SimulatedPayerGateway
from priorauth.models import AuthorizationRequest, TreatmentOrder
from priorauth.services import initiate_authorization, poll_status, submit

# (phone, order_type, code_field, code) -- each patient's insurance matches a
# real PayerRule with requires_auth=True (see priorauth/seed_payer_rules.py).
CASES = [
    ("9820010001", "imaging", "cpt_code", "70551"),      # Kamala: BlueShield Premium PPO, MRI brain
    ("9820010007", "device", "icd10_code", "G47.33"),    # Ashok: HDFC Ergo, CPAP for sleep apnea
    ("9820010005", "procedure", "cpt_code", "27447"),    # Harold: Apollo Munich, knee arthroplasty
    ("9820010003", "imaging", "cpt_code", "74176"),      # Gurpreet: Star Health, CT abdomen
]


class Command(BaseCommand):
    help = "Seed prior-auth requests across every status via real service calls (idempotent)."

    def handle(self, *args, **options):
        doctor = Doctor.objects.filter(specialty="General Medicine").first()
        if doctor is None:
            self.stdout.write(self.style.WARNING(
                "no General Medicine doctor found — run seed_doctors first"))
            return

        created = skipped = 0
        for phone, order_type, code_field, code in CASES:
            patient = Patient.objects.filter(contact_number=phone).first()
            if patient is None:
                skipped += 1
                continue
            if AuthorizationRequest.objects.filter(order__patient=patient).exists():
                continue

            order = TreatmentOrder.objects.create(
                patient=patient, ordering_doctor=doctor, order_type=order_type,
                **{code_field: code},
            )
            auth_request = initiate_authorization(order)
            created += 1
            if auth_request is None:
                self.stdout.write(self.style.WARNING(
                    f"no PayerRule match for {patient.first_name} — left as a plain "
                    "TreatmentOrder with no authorization request"))
                continue
            self._advance(auth_request, phone)

        if skipped:
            self.stdout.write(self.style.WARNING(
                f"{skipped} roster patients missing — run seed_patients first"))
        self.stdout.write(self.style.SUCCESS(f"seeded {created} new treatment orders"))

    def _advance(self, auth_request, phone):
        """ready_for_review (Kamala, untouched) / submitted (Gurpreet) /
        approved (Ashok) / denied (Harold, forced via the sim gateway)."""
        if phone == "9820010001":
            return  # leave at ready_for_review
        submit(auth_request)
        if phone == "9820010007":
            poll_status(auth_request)  # default sim response: approved
        elif phone == "9820010005":
            SimulatedPayerGateway.force_response(
                auth_request.id, "denied",
                denial_reason="Conservative treatment not yet attempted for 6 weeks.",
                appeal_suggested=True,
            )
            poll_status(auth_request)
        # Gurpreet (9820010003): left at "submitted" -- mid-flight, no poll.
