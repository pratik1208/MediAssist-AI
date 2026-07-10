"""Registration -> Triage handoff: intake symptoms pre-load an assessment."""

import datetime

import pytest
from django.core.management import call_command
from django.utils import timezone

from core.models import Conversation, Patient
from registration.models import IntakeSummary
from registration.services import complete_registration
from triage.models import EscalationAlert, TriageAssessment


@pytest.fixture
def seeded(db):
    call_command("seed_protocols", verbosity=0)


def registered_patient(symptoms):
    patient = Patient.objects.create(
        first_name="Rahul", last_name="Sharma", contact_number="9876543210",
        dob=datetime.date(1990, 5, 17), identity_verified=True,
    )
    Conversation.objects.create(channel="web", started_at=timezone.now(),
                                patient=patient)
    if symptoms is not None:
        IntakeSummary.objects.create(patient=patient,
                                     clinical_profile={"symptoms": symptoms},
                                     summary_text="")
    return patient


class TestRegistrationToTriageHandoff:
    def test_intake_symptoms_preload_an_assessment(self, seeded):
        patient = registered_patient(["headache", "sensitivity to light"])
        complete_registration(patient)

        assessment = TriageAssessment.objects.get(patient=patient)
        assert assessment.status == "pending"
        assert assessment.clinical_protocol.name == "Headache"
        assert assessment.reported_symptoms["source"] == "registration_intake"
        assert "headache" in assessment.reported_symptoms["text"]

    def test_red_flag_intake_symptoms_escalate_immediately(self, seeded):
        patient = registered_patient(["crushing chest pain", "sweating"])
        complete_registration(patient)

        assessment = TriageAssessment.objects.get(patient=patient)
        assert assessment.status == "escalated"
        assert EscalationAlert.objects.filter(assessment=assessment).exists()

    def test_no_symptoms_no_assessment(self, seeded):
        patient = registered_patient(None)
        complete_registration(patient)
        assert not TriageAssessment.objects.filter(patient=patient).exists()

    def test_no_duplicate_open_assessments(self, seeded):
        patient = registered_patient(["headache"])
        complete_registration(patient)
        complete_registration(patient)  # event fires twice
        assert TriageAssessment.objects.filter(patient=patient).count() == 1
