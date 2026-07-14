"""seed_assessments — triage assessment variety for manual testing.

Ten patients spanning acuity/disposition (self_care through emergency) and
every FR-T7 route_hint. Creates each TriageAssessment directly (there's no
services-layer creator — the same shape triage/views.py's
StartAssessmentAPIView builds), then calls the real
triage.services.route_disposition(assessment) so the full triage.disposition
fan-out fires for real: scheduling offers a booking, referrals auto-drafts a
Referral (specialist hint), priorauth auto-opens a TreatmentOrder
(diagnostics hint). The meds_issue/preventive hints are included too, on
purpose — nothing currently subscribes to them (a known gap), and leaving
them in this seed means the moment that gap is closed, this data starts
exercising it for free. Two are pushed straight to triage.services.escalate()
to populate the EscalationAlert queue.

Requires patients (seed_patients) and protocols (seed_protocols) to exist;
no-ops with a warning otherwise. Idempotent: skips a patient who already has
a seeded assessment (tagged via a fixed marker in summary_text).
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Conversation, Patient
from triage.models import ClinicalProtocol, TriageAssessment
from triage.services import escalate, route_disposition

MARKER = "[seed_assessments]"

# (phone, acuity, disposition, route_hint, protocol_name, symptoms_text, summary)
CASES = [
    ("9820030001", "low", "routine", None, None,
     "mild seasonal allergy symptoms, sneezing and itchy eyes for a week",
     "Mild seasonal allergies; routine follow-up if it persists."),
    ("9820030002", "low", "routine", None, None,
     "minor lower back strain after starting a new gym routine",
     "Likely muscular strain; routine visit recommended."),
    ("9820030003", "medium", "same_day", None, None,
     "persistent low-grade fever for three days, feeling run down",
     "Low-grade fever x3 days — should be seen today."),
    ("9820030006", "medium", "routine", "specialist", "Adult Chest Pain",
     "occasional palpitations on exertion over the past two weeks",
     "Recurring palpitations on exertion — referred for cardiology workup."),
    ("9820030007", "medium", "routine", "diagnostics", None,
     "recurring abdominal pain, worse after meals, for the past month",
     "Recurring post-prandial abdominal pain — imaging recommended."),
    ("9820030008", "low", "routine", "meds_issue", None,
     "ran out of blood pressure medication and isn't sure how to get a refill",
     "Needs guidance on renewing a blood-pressure prescription."),
    ("9820030009", "minimal", "self_care", "preventive", None,
     "no acute complaint, asked whether she is due for any routine screenings",
     "Asked about overdue preventive screenings."),
    ("9820030010", "minimal", "self_care", None, None,
     "mild cold symptoms, runny nose and slight cough since yesterday",
     "Mild cold — self-care advised."),
]

# (phone, symptoms_text, summary) -- pushed straight to escalate().
EMERGENCY_CASES = [
    ("9820030011", "sudden severe chest pain and shortness of breath",
     "Sudden severe chest pain with shortness of breath — red-flag escalation."),
    ("9820030012", "reports thoughts of self-harm and feeling hopeless",
     "Patient reports self-harm ideation — red-flag escalation."),
]


class Command(BaseCommand):
    help = "Seed triage assessment variety across acuity/disposition/route hints (idempotent)."

    def _conversation_for(self, patient):
        return Conversation.objects.create(
            patient=patient, channel="web", started_at=timezone.now())

    def handle(self, *args, **options):
        created = skipped = 0

        for phone, acuity, disposition, hint, protocol_name, symptoms, summary in CASES:
            patient = Patient.objects.filter(contact_number=phone).first()
            if patient is None:
                skipped += 1
                continue
            if TriageAssessment.objects.filter(
                    patient=patient, summary_text__startswith=MARKER).exists():
                continue

            protocol = (ClinicalProtocol.objects.filter(name=protocol_name).first()
                       if protocol_name else None)
            findings = {"route_hint": hint} if hint else {}
            assessment = TriageAssessment.objects.create(
                patient=patient, conversation=self._conversation_for(patient),
                clinical_protocol=protocol, reported_symptoms={"text": symptoms},
                findings=findings, acuity=acuity, disposition=disposition,
                summary_text=f"{MARKER} {summary}", status="completed",
                finished_at=timezone.now(),
            )
            route_disposition(assessment)
            created += 1

        for phone, symptoms, summary in EMERGENCY_CASES:
            patient = Patient.objects.filter(contact_number=phone).first()
            if patient is None:
                skipped += 1
                continue
            # escalate() overwrites summary_text with an AI-written hand-off
            # note, so the MARKER prefix doesn't survive on these rows —
            # reported_symptoms is untouched and unique per case, so it's
            # the stable idempotency key here instead.
            if TriageAssessment.objects.filter(
                    patient=patient, reported_symptoms__text=symptoms).exists():
                continue

            assessment = TriageAssessment.objects.create(
                patient=patient, conversation=self._conversation_for(patient),
                clinical_protocol=None, reported_symptoms={"text": symptoms},
                findings={}, acuity="high", disposition="same_day",
                summary_text=f"{MARKER} {summary}", status="pending",
            )
            escalate(assessment)
            created += 1

        if skipped:
            self.stdout.write(self.style.WARNING(
                f"{skipped} roster patients/protocols missing — run seed_patients "
                "and seed_protocols first"))
        self.stdout.write(self.style.SUCCESS(
            f"seeded {created} new triage assessments "
            f"({len(CASES)} routed + {len(EMERGENCY_CASES)} escalated)"))
