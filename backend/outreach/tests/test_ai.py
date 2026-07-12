"""Guards on the outreach AI layer: tool schemas, tracing, the
never-block-a-wave fallback, the hard-stop keyword safety net, and 20+
real-world reply phrasings classifying correctly -- misclassifying an
opt-out as anything else is the failure mode to guard hardest against."""

import datetime
from unittest.mock import patch

import pytest
from django.utils import timezone

from core.models import Patient
from outreach.ai import CLASSIFY_RESPONSE, RENDER_OUTREACH_MESSAGE
from outreach.models import Campaign, CampaignMember, InboundResponse
from outreach.services import (
    _looks_like_hard_stop,
    classify_and_handle_response,
    render_message,
)


@pytest.fixture
def patient(db):
    return Patient.objects.create(
        first_name="Rahul", last_name="Sharma", contact_number="9876543210",
        email="rahul@example.com", dob=datetime.date(1955, 5, 17),
        registration_status="complete",
    )


@pytest.fixture
def campaign(db):
    return Campaign.objects.create(
        name="Flu shot 65+", clinical_goal="Get 65+ patients their flu shot",
        cohort_criteria={"age_min": 65}, channel_plan=[{"channel": "sms", "wait_days": 0}],
    )


@pytest.fixture
def member(campaign, patient):
    return CampaignMember.objects.create(
        campaign=campaign, patient=patient, state="contacted", outreach_reason="flu shot",
    )


class TestToolSchemas:
    def test_classify_response_is_strict_with_enum_intent(self):
        assert CLASSIFY_RESPONSE["strict"] is True
        assert CLASSIFY_RESPONSE["input_schema"]["required"] == ["intent", "snooze_until", "question_text"]
        assert set(CLASSIFY_RESPONSE["input_schema"]["properties"]["intent"]["enum"]) == {
            "book", "snooze", "opt_out", "question", "unclear",
        }

    def test_render_outreach_message_is_strict(self):
        assert RENDER_OUTREACH_MESSAGE["strict"] is True
        assert RENDER_OUTREACH_MESSAGE["input_schema"]["required"] == ["body"]


class TestHardStopKeywordSafetyNet:
    @pytest.mark.parametrize("text", [
        "stop", "STOP", "Stop.", "stop!", "  stop  ",
        "stopall", "unsubscribe", "cancel", "end", "quit",
    ])
    def test_exact_carrier_keywords_match(self, text):
        assert _looks_like_hard_stop(text) is True

    @pytest.mark.parametrize("text", [
        "please don't stop asking, I'll book eventually",
        "can we cancel and rebook for next week instead?",
        "what happens at the end of the appointment?",
        "yes ok",
        "",
    ])
    def test_natural_sentences_containing_the_word_do_not_match(self, text):
        assert _looks_like_hard_stop(text) is False

    def test_hard_stop_short_circuits_without_calling_ai(self, member):
        with patch("outreach.ai.call_tool") as mock_call:
            intent = classify_and_handle_response(member, "STOP")
        mock_call.assert_not_called()
        assert intent == "opt_out"
        member.refresh_from_db()
        assert member.state == "opted_out"
        assert member.patient.communication_preferences["sms"] is False


class TestClassifyAndHandleResponse:
    def test_ai_failure_falls_back_to_unclear(self, member):
        with patch("outreach.ai.classify_response", side_effect=RuntimeError("network down")):
            intent = classify_and_handle_response(member, "hmm not sure")
        assert intent == "unclear"
        member.refresh_from_db()
        assert member.state == "responded"

    def test_snooze_intent_without_resolvable_date_falls_back_to_unclear(self, member):
        with patch("outreach.ai.classify_response",
                  return_value={"intent": "snooze", "snooze_until": None, "question_text": None}):
            intent = classify_and_handle_response(member, "remind me sometime")
        assert intent == "unclear"

    def test_snooze_intent_with_unparseable_date_falls_back_to_unclear(self, member):
        with patch("outreach.ai.classify_response",
                  return_value={"intent": "snooze", "snooze_until": "not-a-date", "question_text": None}):
            intent = classify_and_handle_response(member, "remind me later")
        assert intent == "unclear"

    def test_snooze_intent_with_valid_date_applies(self, member):
        until = (timezone.localdate() + datetime.timedelta(days=30)).isoformat()
        with patch("outreach.ai.classify_response",
                  return_value={"intent": "snooze", "snooze_until": until, "question_text": None}):
            intent = classify_and_handle_response(member, "call me back next month")
        assert intent == "snooze"
        member.refresh_from_db()
        assert member.state == "snoozed"
        assert member.snooze_until.isoformat() == until

    def test_marks_inbound_response_handled_with_classified_intent(self, member):
        response = InboundResponse.objects.create(member=member, raw_text="yes")
        with patch("outreach.ai.classify_response",
                  return_value={"intent": "book", "snooze_until": None, "question_text": None}):
            classify_and_handle_response(member, "yes", response=response)
        response.refresh_from_db()
        assert response.handled is True
        assert response.classified_intent == "book"

    def test_passes_today_to_the_model_for_relative_date_resolution(self, member):
        with patch("outreach.ai.classify_response",
                  return_value={"intent": "unclear", "snooze_until": None, "question_text": None}) as mock:
            classify_and_handle_response(member, "later")
        called_today = mock.call_args[0][1]
        assert called_today == timezone.localdate().isoformat()


class TestRenderMessageCaching:
    def test_caches_per_language_and_goal(self, member):
        with patch("outreach.ai.render_outreach_message_body",
                  return_value={"body": "please come in for your flu shot"}) as mock:
            first = render_message(member, "flu shot goal")
            second = render_message(member, "flu shot goal")
        mock.assert_called_once()
        assert first == second == "Hi Rahul, please come in for your flu shot"

    def test_different_language_or_goal_calls_again(self, campaign, patient):
        other_patient = Patient.objects.create(
            first_name="Meera", last_name="Iyer", contact_number="9111111112",
            dob=datetime.date(1950, 1, 1), registration_status="complete",
            preferred_language="hi",
        )
        member_en = CampaignMember.objects.create(campaign=campaign, patient=patient,
                                                   outreach_reason="flu shot")
        member_hi = CampaignMember.objects.create(campaign=campaign, patient=other_patient,
                                                   outreach_reason="flu shot")
        with patch("outreach.ai.render_outreach_message_body",
                  return_value={"body": "come in for your shot"}) as mock:
            render_message(member_en, "flu shot goal")
            render_message(member_hi, "flu shot goal")
        assert mock.call_count == 2

    def test_ai_failure_falls_back_without_blocking(self, member):
        with patch("outreach.ai.render_outreach_message_body", side_effect=RuntimeError("down")):
            text = render_message(member, "flu shot goal")
        assert "flu shot goal" in text
        assert text.startswith("Hi Rahul,")
