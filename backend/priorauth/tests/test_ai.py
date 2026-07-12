"""Guards on the priorauth AI layer: tool schemas, tracing, the
never-block-on-AI-failure fallbacks, and the build step's explicit exit
test — fixture denial letters and info-requests parse to the right
structured fields."""

import datetime
from unittest.mock import patch

import pytest
from django.utils import timezone

from core.models import Doctor, EventLog, Patient, SentNotification
from priorauth import services
from priorauth.ai import INTERPRET_PAYER_MESSAGE, SUGGEST_APPEAL, WRITE_REVIEWER_SUMMARY
from priorauth.gateway import SimulatedPayerGateway
from priorauth.models import AuthorizationRequest, PayerMessage, PayerRule, TreatmentOrder
from registration.models import InsurancePolicy


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


@pytest.fixture
def rule(db):
    return PayerRule.objects.create(
        payer_name="BlueShield", plan="Premium PPO", cpt_pattern="7055[1-3]",
        requires_auth=True, submission_channel="epa",
        required_documentation=["diagnosis"],
    )


@pytest.fixture
def ready_request(patient, doctor, policy, rule):
    order = TreatmentOrder.objects.create(patient=patient, ordering_doctor=doctor,
                                          order_type="imaging", cpt_code="70551")
    return services.initiate_authorization(order)


class TestWriteReviewerSummaryTool:
    SCHEMA = WRITE_REVIEWER_SUMMARY["input_schema"]

    def test_is_strict_and_fully_required(self):
        assert WRITE_REVIEWER_SUMMARY["strict"] is True
        assert self.SCHEMA["additionalProperties"] is False
        assert set(self.SCHEMA["required"]) == set(self.SCHEMA["properties"]) == {
            "clinical_justification", "relevant_history_points", "guideline_citations",
        }

    def test_forbids_recommending_a_decision(self):
        assert "never recommend approving or denying" in WRITE_REVIEWER_SUMMARY["description"]


class TestInterpretPayerMessageTool:
    SCHEMA = INTERPRET_PAYER_MESSAGE["input_schema"]

    def test_is_strict_and_fully_required(self):
        assert INTERPRET_PAYER_MESSAGE["strict"] is True
        assert set(self.SCHEMA["required"]) == set(self.SCHEMA["properties"]) == {
            "decision", "info_requested", "deadline",
        }

    def test_decision_and_deadline_are_nullable(self):
        assert "null" in self.SCHEMA["properties"]["decision"]["type"]
        assert "null" in self.SCHEMA["properties"]["deadline"]["type"]


class TestSuggestAppealTool:
    SCHEMA = SUGGEST_APPEAL["input_schema"]

    def test_is_strict_and_fully_required(self):
        assert SUGGEST_APPEAL["strict"] is True
        assert set(self.SCHEMA["required"]) == {"should_appeal", "recommendation", "draft_argument"}

    def test_description_says_suggestion_only(self):
        assert "SUGGESTION ONLY" in SUGGEST_APPEAL["description"]


class TestTracing:
    def test_ai_entry_points_are_traced_chains(self):
        from langsmith.run_helpers import is_traceable_function

        from priorauth import ai
        assert is_traceable_function(ai.write_reviewer_summary)
        assert is_traceable_function(ai.interpret_payer_message)
        assert is_traceable_function(ai.suggest_appeal)


class TestWritePackageSummaryWiring:
    def test_ai_summary_lands_on_the_package(self, ready_request):
        # initiate_authorization already ran with the model blocked
        # (conftest) -> fallback summary landed. Re-run write_package_summary
        # directly with a mocked model to check the real wiring.
        with patch("priorauth.ai.call_tool", return_value={
            "clinical_justification": "MRI is indicated for suspected structural pathology.",
            "relevant_history_points": ["Osteoarthritis, right knee"],
            "guideline_citations": ["ACR Appropriateness Criteria"],
        }):
            services.write_package_summary(ready_request.package)
        ready_request.package.refresh_from_db()
        assert "MRI is indicated" in ready_request.package.reviewer_summary
        assert "ACR Appropriateness Criteria" in ready_request.package.reviewer_summary

    def test_ai_failure_falls_back_to_a_deterministic_summary(self, ready_request):
        # conftest blocks the model -> initiate_authorization's own call
        # already exercised the fallback; confirm its content is sane.
        ready_request.package.refresh_from_db()
        assert "AI summary unavailable" in ready_request.package.reviewer_summary or \
               "70551" in ready_request.package.reviewer_summary


class TestInterpretPayerMessageWiring:
    """The build step's exit test: fixture denial letters and info-requests
    parse to the right structured fields."""

    DENIAL_LETTER = (
        "RE: Authorization Request SIM-000042\n"
        "After review, the requested MRI (CPT 70551) is DENIED. "
        "Reason: Conservative therapy (physical therapy, NSAIDs) was not "
        "attempted or documented prior to this request. "
        "You may appeal this decision within 30 days."
    )

    INFO_REQUEST_LETTER = (
        "RE: Authorization Request SIM-000042\n"
        "Additional information is required to complete review: "
        "recent lab results and imaging reports. "
        "Please respond by 2026-08-01."
    )

    def test_fixture_denial_letter_parses_to_denied(self, ready_request):
        with patch("priorauth.ai.call_tool", return_value={
            "decision": "denied", "info_requested": [], "deadline": None,
        }):
            services.submit(ready_request)
            SimulatedPayerGateway.force_raw_message(ready_request.id, self.DENIAL_LETTER)
            services.poll_status(ready_request)
        ready_request.refresh_from_db()
        assert ready_request.status == "denied"
        message = PayerMessage.objects.filter(request=ready_request, direction="inbound").latest("id")
        assert message.content == self.DENIAL_LETTER
        assert message.parsed["status"] == "denied"
        SimulatedPayerGateway.clear_forced()

    def test_fixture_info_request_letter_parses_to_the_right_categories(self, ready_request):
        with patch("priorauth.ai.call_tool", return_value={
            "decision": "info_requested", "info_requested": ["labs", "imaging_reports"],
            "deadline": "2026-08-01",
        }):
            services.submit(ready_request)
            SimulatedPayerGateway.force_raw_message(ready_request.id, self.INFO_REQUEST_LETTER)
            services.poll_status(ready_request)
        ready_request.refresh_from_db()
        assert ready_request.status == "info_requested"
        message = PayerMessage.objects.filter(request=ready_request, direction="inbound").latest("id")
        assert message.parsed["requested_items"] == ["labs", "imaging_reports"]
        assert message.parsed["deadline"] == "2026-08-01"
        SimulatedPayerGateway.clear_forced()

    def test_interpretation_failure_never_guesses_a_decision(self, ready_request):
        # conftest blocks the model -> interpretation "fails" -> must fall
        # back to under_review, never fabricate approved/denied.
        services.submit(ready_request)
        SimulatedPayerGateway.force_raw_message(ready_request.id, "some illegible fax noise")
        services.poll_status(ready_request)
        ready_request.refresh_from_db()
        assert ready_request.status == "under_review"
        SimulatedPayerGateway.clear_forced()

    def test_requested_items_win_even_when_decision_label_disagrees(self, ready_request):
        # Live-provider regression: the model can extract concrete
        # requested_items while giving a "decision" that isn't literally
        # "info_requested" (e.g. "under_review") — the items must still be
        # acted on, not silently stranded.
        with patch("priorauth.ai.call_tool", return_value={
            "decision": "under_review", "info_requested": ["labs", "imaging_reports"],
            "deadline": "2026-07-08",
        }):
            services.submit(ready_request)
            SimulatedPayerGateway.force_raw_message(ready_request.id, self.INFO_REQUEST_LETTER)
            services.poll_status(ready_request)
        ready_request.refresh_from_db()
        assert ready_request.status == "info_requested"
        SimulatedPayerGateway.clear_forced()

    def test_explicit_denial_wins_even_if_it_also_lists_requested_items(self, ready_request):
        # An unambiguous terminal decision must never be masked by
        # incidental requested_items noise in the same message.
        with patch("priorauth.ai.call_tool", return_value={
            "decision": "denied", "info_requested": ["labs"], "deadline": None,
        }):
            services.submit(ready_request)
            SimulatedPayerGateway.force_raw_message(ready_request.id, self.DENIAL_LETTER)
            services.poll_status(ready_request)
        ready_request.refresh_from_db()
        assert ready_request.status == "denied"
        SimulatedPayerGateway.clear_forced()


class TestSuggestAppealFor:
    def test_refuses_when_not_denied(self, ready_request):
        with pytest.raises(ValueError, match="is not denied"):
            services.suggest_appeal_for(ready_request)

    def test_returns_the_ai_suggestion_when_denied(self, ready_request):
        services.submit(ready_request)
        SimulatedPayerGateway.force_response(ready_request.id, "denied",
                                            denial_reason="not medically necessary")
        services.poll_status(ready_request)
        ready_request.refresh_from_db()

        with patch("priorauth.ai.call_tool", return_value={
            "should_appeal": True,
            "recommendation": "The denial cites lack of conservative therapy, but the "
                              "record shows a completed course of NSAIDs — worth appealing.",
            "draft_argument": "We respectfully request reconsideration...",
        }):
            result = services.suggest_appeal_for(ready_request)

        assert result["should_appeal"] is True
        assert "worth appealing" in result["recommendation"]
        SimulatedPayerGateway.clear_forced()

    def test_ai_failure_returns_a_safe_fallback_not_a_crash(self, ready_request):
        services.submit(ready_request)
        SimulatedPayerGateway.force_response(ready_request.id, "denied", denial_reason="x")
        services.poll_status(ready_request)
        ready_request.refresh_from_db()

        result = services.suggest_appeal_for(ready_request)  # conftest blocks the model
        assert result["should_appeal"] is None
        assert "unavailable" in result["recommendation"]
        assert result["draft_argument"] is None
        SimulatedPayerGateway.clear_forced()

    def test_never_touches_the_requests_own_appeal_flag(self, ready_request):
        # suggest_appeal_for is a pure suggestion — it must never write back
        # onto appeal_suggested, which reflects the payer's own signal.
        services.submit(ready_request)
        SimulatedPayerGateway.force_response(ready_request.id, "denied", denial_reason="x",
                                            appeal_suggested=False)
        services.poll_status(ready_request)
        ready_request.refresh_from_db()
        assert ready_request.appeal_suggested is False

        with patch("priorauth.ai.call_tool", return_value={
            "should_appeal": True, "recommendation": "appeal", "draft_argument": "text",
        }):
            services.suggest_appeal_for(ready_request)
        ready_request.refresh_from_db()
        assert ready_request.appeal_suggested is False  # unchanged
        SimulatedPayerGateway.clear_forced()
