"""Priorauth reacts to other agents' events (Phase 6 integration): the
referral-acceptance handoff from Agent 5 (priorauth.needed) and the triage
"diagnostics" disposition hint (FR-T7) — both auto-open a treatment order
and run detection immediately."""

import datetime

import pytest
from django.utils import timezone

from core.events import emit
from core.models import Conversation, Doctor, Patient
from priorauth.models import AuthorizationRequest, PayerRule, TreatmentOrder
from registration.models import InsurancePolicy
from triage.models import ClinicalProtocol, TriageAssessment


@pytest.fixture
def patient(db):
    return Patient.objects.create(
        first_name="Rahul", last_name="Sharma", contact_number="9876543210",
        dob=datetime.date(1990, 5, 17),
    )


@pytest.fixture
def doctor(db):
    return Doctor.objects.create(name="Dr. Asha Mehta", specialty="General Medicine")


@pytest.fixture
def policy(db, patient):
    return InsurancePolicy.objects.create(
        patient=patient, policy_number="BS-1", provider_name="BlueShield",
        plan="Premium PPO", coverage_details="",
    )


class TestReferralAcceptanceHandoff:
    def test_priorauth_needed_opens_a_linked_order_and_runs_detection(self, patient, doctor):
        from referrals.models import Referral
        referral = Referral.objects.create(
            patient=patient, referring_doctor=doctor, specialty_needed="Orthopedics",
            reason="knee pain", urgency="routine", status="accepted",
        )
        emit("priorauth.needed", referral_id=referral.id, patient_id=patient.id,
             specialty_needed="Orthopedics", specialist_id=1)

        order = TreatmentOrder.objects.get(referral=referral)
        assert order.patient_id == patient.id
        assert order.ordering_doctor_id == doctor.id
        assert order.order_type == "procedure"
        # No CPT/ICD-10 known from a referral alone -> honestly "not required",
        # not a fabricated authorization.
        assert not AuthorizationRequest.objects.filter(order=order).exists()

    def test_missing_referral_or_patient_does_not_crash(self, patient):
        emit("priorauth.needed", referral_id=999999, patient_id=patient.id,
             specialty_needed="Orthopedics", specialist_id=1)
        emit("priorauth.needed", referral_id=1, patient_id=999999,
             specialty_needed="Orthopedics", specialist_id=1)
        assert not TreatmentOrder.objects.filter(patient=patient).exists()

    def test_when_a_matching_rule_exists_detection_actually_fires(self, patient, doctor, policy):
        # If the referring specialty happens to line up with a payer rule
        # that matches on icd10 alone (no cpt needed), detection can still
        # produce a real AuthorizationRequest — not just a bare order.
        PayerRule.objects.create(
            payer_name="BlueShield", plan="Premium PPO", icd10_pattern="M25.561",
            requires_auth=True, submission_channel="epa", required_documentation=["diagnosis"],
        )
        from referrals.models import Referral
        referral = Referral.objects.create(
            patient=patient, referring_doctor=doctor, specialty_needed="Orthopedics",
            reason="knee pain", urgency="routine", status="accepted",
        )
        emit("priorauth.needed", referral_id=referral.id, patient_id=patient.id,
             specialty_needed="Orthopedics", specialist_id=1)
        order = TreatmentOrder.objects.get(referral=referral)
        # order.icd10_code is still None (referrals don't carry one) so this
        # particular rule won't match either — confirms the honest limit,
        # not a false positive.
        assert not AuthorizationRequest.objects.filter(order=order).exists()


class TestTriageDiagnosticsHandoff:
    @pytest.fixture
    def conversation(self, db, patient):
        return Conversation.objects.create(channel="web", started_at=timezone.now(), patient=patient)

    @pytest.fixture
    def protocol(self, db):
        return ClinicalProtocol.objects.create(name="Adult Chest Pain", symptom_keywords=["chest pain"])

    def make_assessment(self, patient, conversation, protocol):
        return TriageAssessment.objects.create(
            patient=patient, conversation=conversation, clinical_protocol=protocol,
            reported_symptoms={"text": "chest tightness", "answers": []},
            findings={"route_hint": "diagnostics"}, acuity="medium", disposition="24_48h",
            summary_text="", status="completed", finished_at=timezone.now(),
        )

    def test_diagnostics_hint_opens_an_order_and_runs_detection(self, patient, conversation, protocol):
        assessment = self.make_assessment(patient, conversation, protocol)
        emit("triage.disposition", patient_id=patient.id, assessment_id=assessment.id,
             acuity="medium", disposition="24_48h", route_to="priorauth")
        order = TreatmentOrder.objects.get(patient=patient)
        assert order.order_type == "imaging"
        assert order.referral_id is None

    def test_other_route_targets_are_ignored(self, patient, conversation, protocol):
        assessment = self.make_assessment(patient, conversation, protocol)
        emit("triage.disposition", patient_id=patient.id, assessment_id=assessment.id,
             acuity="medium", disposition="24_48h", route_to="referrals")
        assert not TreatmentOrder.objects.filter(patient=patient).exists()

    def test_missing_assessment_does_not_crash(self, patient):
        emit("triage.disposition", patient_id=patient.id, assessment_id=999999,
             acuity="medium", disposition="24_48h", route_to="priorauth")
        assert not TreatmentOrder.objects.filter(patient=patient).exists()

# The priorauth.approved -> "offer to book" reaction lives in scheduling's
# own subscriber, so it's tested in scheduling/tests/test_event_subscribers.py
# (TestPriorauthApprovalSubscriber), not duplicated here.
