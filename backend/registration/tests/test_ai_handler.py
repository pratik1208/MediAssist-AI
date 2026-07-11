from unittest.mock import patch

import pytest
from django.utils import timezone

from core.models import Conversation, EventLog, Patient
from registration.ai.handler import handle_registration_message
from registration.models import InsurancePolicy, IntakeSummary
from registration.tests.test_services import DOB

HISTORY = [{"role": "user", "content": "hi"}]  # unused by the mocked model


def extraction(**fields):
    """A record_registration_data tool result, as the model would return it."""
    return {"next_question_topic": "demographics", "registration_complete": False, **fields}


def run(conversation, **fields):
    with patch("registration.ai.handler.call_tool", return_value=extraction(**fields)):
        return handle_registration_message(conversation, HISTORY)


@pytest.fixture
def conversation(db):
    return Conversation.objects.create(
        channel="web",
        started_at=timezone.now(),
        agent_context={"active_agent": "registration"},
    )


class TestDemographicsStage:
    def test_partial_demographics_accumulate_without_creating_a_patient(self, conversation):
        result = run(conversation, first_name="Rahul", last_name="Sharma")
        assert result["stage"] == "demographics"
        assert result["patient_id"] is None
        assert Patient.objects.count() == 0
        conversation.refresh_from_db()
        assert conversation.agent_context["pending_demographics"]["first_name"] == "Rahul"

    def test_completing_the_minimum_creates_and_links_the_patient(self, conversation):
        run(conversation, first_name="Rahul", last_name="Sharma")
        result = run(conversation, dob="1990-05-17", contact_number="9876543210")
        # A brand-new patient exists, linked to the conversation, and the
        # next gate is identity verification.
        assert result["stage"] == "identity_verification"
        assert "otp_required" in result["ui_hints"]
        patient = Patient.objects.get()
        assert result["patient_id"] == patient.id
        conversation.refresh_from_db()
        assert conversation.patient_id == patient.id

    def test_returning_patient_is_linked_not_duplicated(self, conversation, rahul):
        result = run(
            conversation,
            first_name="Rahul", last_name="Sharma",
            dob=str(DOB), contact_number="+91 98765 43210",
        )
        assert result["patient_id"] == rahul.id
        assert Patient.objects.count() == 1

    def test_possible_duplicate_holds_instead_of_creating(self, conversation, rahul):
        result = run(
            conversation,
            first_name="Rahul", last_name="Sharme",  # similar name...
            dob=str(DOB), contact_number="9000000000",  # ...different phone
        )
        assert result["stage"] == "duplicate_hold"
        assert Patient.objects.count() == 1  # only rahul; nothing auto-created
        conversation.refresh_from_db()
        assert conversation.agent_context["duplicate_candidate_ids"] == [rahul.id]


class TestStateGate:
    def _linked(self, conversation, rahul, verified=False, insured=False):
        rahul.identity_verified = verified
        rahul.save(update_fields=["identity_verified"])
        conversation.patient = rahul
        conversation.save(update_fields=["patient"])
        if insured:
            InsurancePolicy.objects.create(
                patient=rahul, policy_number="BS-448291", provider_name="BlueShield",
                coverage_details="", coverage_start=DOB, coverage_end=DOB,
                eligibility_status="eligible",
            )

    def test_unverified_patient_is_gated_on_otp(self, conversation, rahul):
        self._linked(conversation, rahul)
        result = run(conversation)
        assert result["stage"] == "identity_verification"

    def test_gate_sees_verification_done_by_another_code_path(self, conversation, rahul):
        # Regression: verify_otp updates the DB row between turns; the handler
        # must not trust a stale in-memory patient (found in shell testing).
        self._linked(conversation, rahul)  # in-memory: identity_verified=False
        Patient.objects.filter(pk=rahul.pk).update(identity_verified=True)
        result = run(conversation)
        assert result["stage"] == "insurance"

    def test_verified_but_uninsured_is_gated_on_insurance(self, conversation, rahul):
        self._linked(conversation, rahul, verified=True)
        result = run(conversation)
        assert result["stage"] == "insurance"
        assert {"upload": "insurance_card"} in result["ui_hints"]

    def test_insured_but_incomplete_continues_intake(self, conversation, rahul):
        self._linked(conversation, rahul, verified=True, insured=True)
        result = run(conversation, symptoms=["headache"])
        assert result["stage"] == "intake"
        conversation.refresh_from_db()
        assert conversation.agent_context["intake"]["symptoms"] == ["headache"]

    def test_intake_answers_accumulate_and_dedupe_across_turns(self, conversation, rahul):
        self._linked(conversation, rahul, verified=True, insured=True)
        run(conversation, symptoms=["headache"], medications=["ibuprofen"])
        run(conversation, symptoms=["headache", "fever"], lifestyle={"smoking": "never"})
        conversation.refresh_from_db()
        intake = conversation.agent_context["intake"]
        assert intake["symptoms"] == ["headache", "fever"]
        assert intake["medications"] == ["ibuprofen"]
        assert intake["lifestyle"] == {"smoking": "never"}

    def test_completion_writes_intake_and_emits_the_event(self, conversation, rahul):
        self._linked(conversation, rahul, verified=True, insured=True)
        run(conversation, symptoms=["cough"])
        result = run(conversation, registration_complete=True)
        assert result["stage"] == "done"
        assert result["registration_complete"] is True
        # Intake landed in the DB, status flipped, event emitted for Phase 6.
        assert IntakeSummary.objects.get(patient=rahul).clinical_profile["symptoms"] == ["cough"]
        rahul.refresh_from_db()
        assert rahul.registration_status == "complete"
        assert EventLog.objects.filter(
            name="registration.completed", payload__patient_id=rahul.id
        ).exists()
        # Conversation handed off to scheduling, carrying the symptoms.
        conversation.refresh_from_db()
        assert conversation.agent_context["active_agent"] == "scheduling"
        assert conversation.agent_context["handoff"]["symptoms"] == ["cough"]

    def test_partially_dictated_insurance_stays_stashed(self, conversation, rahul):
        self._linked(conversation, rahul, verified=True)
        result = run(conversation, insurance_provider="BlueShield")
        assert result["stage"] == "insurance"  # still waiting on the number
        assert not InsurancePolicy.objects.filter(patient=rahul).exists()
        conversation.refresh_from_db()
        assert conversation.agent_context["pending_insurance"] == {
            "provider_name": "BlueShield",
        }

    def test_fully_dictated_insurance_writes_the_policy_and_advances(self, conversation, rahul):
        # Provider in one turn, number in the next — the moment both are in,
        # the policy row exists and the gate moves past the insurance stage.
        self._linked(conversation, rahul, verified=True)
        run(conversation, insurance_provider="BlueShield")
        result = run(conversation, insurance_policy_number="BS-448291")
        assert result["stage"] == "intake"
        policy = InsurancePolicy.objects.get(patient=rahul)
        assert policy.provider_name == "BlueShield"
        assert policy.policy_number == "BS-448291"
        assert policy.eligibility_checked_at is not None
        conversation.refresh_from_db()
        assert "pending_insurance" not in conversation.agent_context
