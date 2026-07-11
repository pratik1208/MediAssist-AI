"""Referrals reacts to other agents' events (Phase 6 integration): the
triage handoff — findings.route_hint == "specialist" -> route_to
"referrals" -> a draft referral, auto-created, waiting on a physician."""

import datetime

import pytest
from django.utils import timezone

from core.events import emit
from core.models import Conversation, Doctor, Patient
from referrals.models import Referral
from triage.models import ClinicalProtocol, TriageAssessment


@pytest.fixture
def patient(db):
    return Patient.objects.create(
        first_name="Rahul", last_name="Sharma", contact_number="9876543210",
        dob=datetime.date(1990, 5, 17),
    )


@pytest.fixture
def conversation(db, patient):
    return Conversation.objects.create(channel="web", started_at=timezone.now(), patient=patient)


@pytest.fixture
def chest_pain_protocol(db):
    return ClinicalProtocol.objects.create(name="Adult Chest Pain", symptom_keywords=["chest pain"])


def make_assessment(patient, conversation, protocol=None, **overrides):
    defaults = dict(
        patient=patient, conversation=conversation, clinical_protocol=protocol,
        reported_symptoms={"text": "chest tightness on exertion", "answers": []},
        acuity="medium", disposition="24_48h", summary_text="",
        status="completed", finished_at=timezone.now(),
    )
    defaults.update(overrides)
    return TriageAssessment.objects.create(**defaults)


class TestTriageHandoffSubscriber:
    def test_route_to_referrals_creates_a_draft_referral(
        self, patient, conversation, chest_pain_protocol,
    ):
        assessment = make_assessment(patient, conversation, protocol=chest_pain_protocol)
        emit("triage.disposition", patient_id=patient.id, assessment_id=assessment.id,
             acuity="medium", disposition="24_48h", route_to="referrals")

        referral = Referral.objects.get(patient=patient)
        assert referral.status == "created"
        assert referral.referring_doctor is None  # a physician must confirm it
        assert referral.specialty_needed == "Cardiology"  # from the protocol mapping
        assert referral.urgency == "medium"

    def test_unmapped_protocol_falls_back_to_general_medicine(self, patient, conversation):
        unmapped = ClinicalProtocol.objects.create(name="Some Future Protocol")
        # create_draft_referral_from_triage reads acuity off the assessment
        # ROW, not the event payload — override it there to match.
        assessment = make_assessment(patient, conversation, protocol=unmapped,
                                     acuity="low", disposition="routine")
        emit("triage.disposition", patient_id=patient.id, assessment_id=assessment.id,
             acuity="low", disposition="routine", route_to="referrals")
        referral = Referral.objects.get(patient=patient)
        assert referral.specialty_needed == "General Medicine"
        assert referral.urgency == "low"

    def test_minimal_acuity_maps_to_routine_urgency(self, patient, conversation, chest_pain_protocol):
        # TriageAssessment.acuity has "minimal"; Referral.urgency doesn't.
        assessment = make_assessment(patient, conversation, protocol=chest_pain_protocol,
                                     acuity="minimal", disposition="self_care")
        emit("triage.disposition", patient_id=patient.id, assessment_id=assessment.id,
             acuity="minimal", disposition="self_care", route_to="referrals")
        referral = Referral.objects.get(patient=patient)
        assert referral.urgency == "routine"

    def test_dispositions_routed_elsewhere_are_ignored(self, patient, conversation, chest_pain_protocol):
        assessment = make_assessment(patient, conversation, protocol=chest_pain_protocol)
        emit("triage.disposition", patient_id=patient.id, assessment_id=assessment.id,
             acuity="medium", disposition="24_48h", route_to="scheduling")
        assert not Referral.objects.filter(patient=patient).exists()

    def test_missing_assessment_or_patient_does_not_crash(self, patient):
        # Defensive: an id that doesn't resolve must be a no-op, not a 500.
        emit("triage.disposition", patient_id=patient.id, assessment_id=999999,
             acuity="medium", disposition="24_48h", route_to="referrals")
        emit("triage.disposition", patient_id=999999, assessment_id=1,
             acuity="medium", disposition="24_48h", route_to="referrals")
        assert not Referral.objects.filter(patient=patient).exists()

    def test_draft_must_be_confirmed_before_it_can_be_accepted(
        self, patient, conversation, chest_pain_protocol,
    ):
        from referrals import services
        from referrals.models import Specialist
        from core.models import Specialty

        assessment = make_assessment(patient, conversation, protocol=chest_pain_protocol)
        emit("triage.disposition", patient_id=patient.id, assessment_id=assessment.id,
             acuity="medium", disposition="24_48h", route_to="referrals")
        referral = Referral.objects.get(patient=patient)
        specialist = Specialist.objects.create(
            name="Dr. Rohan Kulkarni", specialty=Specialty.CARDIOLOGY, contact_channel="phone",
        )

        with pytest.raises(ValueError, match="referring physician must confirm"):
            services.accept_referral(referral, specialist)  # no doctor -> refused

        doctor = Doctor.objects.create(name="Dr. Asha Mehta", specialty="General Medicine")
        services.accept_referral(referral, specialist, doctor)
        referral.refresh_from_db()
        assert referral.status == "accepted"
        assert referral.referring_doctor_id == doctor.id
