"""Phase 6 integration: channel adapters (an SMS/WhatsApp reply outside a
campaign resolves to the SAME session across multiple inbound messages, with
auth state carried across them), the FR-A9 analytics endpoint, and edge-case
coverage proving PRD Edge Cases 11/12/16 survive the new channel-adapter
entry point exactly as they do over web chat."""

import datetime

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone

from core.models import Conversation, Message, Patient
from frontdesk import services
from frontdesk.models import IntentRoute, PatientSession, StaffTask
from triage.models import EscalationAlert

pytestmark = pytest.mark.django_db

ANALYTICS_URL = "/api/staff/frontdesk/analytics/"


@pytest.fixture
def patient(db):
    return Patient.objects.create(
        first_name="Deepak", last_name="Nair", contact_number="9900011122",
        dob=datetime.date(1985, 6, 20), registration_status="complete",
    )


@pytest.fixture
def staff_client(client, db):
    staff = get_user_model().objects.create_user("frontdesk_ops", password="x", is_staff=True)
    client.force_login(staff)
    return client


def make_authenticated_session(patient, channel="sms"):
    conversation = Conversation.objects.create(channel=channel, started_at=timezone.now())
    return PatientSession.objects.create(
        conversation=conversation, channel=channel, channel_identifier=patient.contact_number,
        patient=patient, authenticated=True,
    )


def routed(intents=(), emergency=False, category=None):
    return {
        "intents": [{"intent": i, "summary": s} for i, s in intents],
        "emergency_symptoms_detected": emergency,
        "mandatory_escalation_category": category,
    }


@pytest.fixture
def fake_router(monkeypatch):
    class Fake:
        result = routed()
        def __call__(self, system, messages, tool, max_tokens=2048):
            return self.result

    fake = Fake()
    monkeypatch.setattr("frontdesk.ai.call_tool", fake)
    return fake


# -- channel adapter: session correlation ----------------------------------------------

class TestChannelAdapterSessionCorrelation:
    def test_same_sender_resumes_the_same_session(self, db):
        first = services.handle_channel_message("sms", "9911122233", "hi")
        second = services.handle_channel_message("sms", "9911122233", "still there?")
        assert first["session_id"] == second["session_id"]
        assert PatientSession.objects.filter(
            channel="sms", channel_identifier="9911122233").count() == 1

    def test_different_channel_is_a_different_session(self, db):
        sms = services.handle_channel_message("sms", "9911122233", "hi")
        wa = services.handle_channel_message("whatsapp", "9911122233", "hi")
        assert sms["session_id"] != wa["session_id"]

    def test_invalid_channel_is_rejected(self, db):
        with pytest.raises(ValueError):
            services.handle_channel_message("voice", "9911122233", "hi")

    def test_transcript_is_written_for_channel_originated_sessions(self, db):
        outcome = services.handle_channel_message("sms", "9911122233", "what are your hours")
        session = PatientSession.objects.get(id=outcome["session_id"])
        roles = list(
            Message.objects.filter(conversation=session.conversation)
            .order_by("id").values_list("role", flat=True)
        )
        assert roles == ["Patient", "Assistant"]

    def test_auth_state_carries_across_messages_from_the_same_sender(self, patient):
        services.handle_channel_message("sms", patient.contact_number, "refill my meds")
        session = PatientSession.objects.get(
            channel="sms", channel_identifier=patient.contact_number)
        assert session.authenticated is False

        services.start_authentication(session, patient.contact_number, patient.dob)
        with override_settings(DEBUG=True):
            services.authenticate_session(session, patient.dob, "123456")
        session.refresh_from_db()
        assert session.authenticated is True

        # a later text from the same number reuses the now-authenticated session
        outcome = services.handle_channel_message("sms", patient.contact_number, "thanks")
        assert outcome["session_id"] == session.id


# -- edge cases surviving the new entry point -------------------------------------------

class TestEdgeCasesSurviveTheChannelAdapter:
    """The channel adapter changes HOW a message arrives, not the safety
    guarantees applied to it -- these mirror test_ai.py's edge-case coverage
    but drive it through handle_channel_message instead of web chat."""

    def test_edge_case_11_red_flag_short_circuits_before_any_model_call(self, patient, monkeypatch):
        def _boom(*a, **k):
            raise AssertionError("model was called before the deterministic screen")
        monkeypatch.setattr("frontdesk.ai.call_tool", _boom)

        outcome = services.handle_channel_message(
            "sms", patient.contact_number, "I have crushing chest pain")
        assert outcome["status"] == "emergency"

    def test_edge_case_11_authenticated_emergency_pages_on_call_over_sms(self, patient, monkeypatch):
        make_authenticated_session(patient)
        monkeypatch.setattr("frontdesk.ai.call_tool",
                            lambda *a, **k: pytest.fail("model must not run"))

        outcome = services.handle_channel_message(
            "sms", patient.contact_number, "severe chest pain right now")
        assert outcome["status"] == "emergency"
        alert = EscalationAlert.objects.get()
        assert alert.patient == patient
        assert alert.source_agent == "frontdesk"

    def test_edge_case_12_mandatory_category_creates_task_even_when_anonymous(self, db, fake_router):
        """FR-A7/Edge Case 12: mandatory escalation must fire "from any entry
        point" -- including a sender who has never verified their identity."""
        fake_router.result = routed(category="stroke")
        outcome = services.handle_channel_message("sms", "9955500011", "possible stroke symptoms")

        assert outcome["status"] == "escalated"
        task = StaffTask.objects.get(category="stroke")
        assert task.priority == "critical"
        session = PatientSession.objects.get(id=outcome["session_id"])
        assert session.authenticated is False

    def test_edge_case_12_caller_supplied_priority_cannot_downgrade_over_sms(self, db, fake_router):
        fake_router.result = routed(category="insurance_dispute")
        services.handle_channel_message("sms", "9955500022", "dispute this charge")
        assert StaffTask.objects.get(category="insurance_dispute").priority == "high"

    def test_edge_case_16_multi_intent_over_sms(self, patient, fake_router):
        session = make_authenticated_session(patient)
        fake_router.result = routed(intents=[
            ("refill", "refill BP meds"), ("appointment", "book annual checkup"),
        ])

        outcome = services.handle_channel_message(
            "sms", patient.contact_number, "refill my BP meds and book my checkup")
        assert outcome["session_id"] == session.id
        assert list(
            IntentRoute.objects.filter(session=session).order_by("id")
            .values_list("intent", flat=True)
        ) == ["refill", "appointment"]


# -- FR-A9 analytics -----------------------------------------------------------------

class TestAnalytics:
    def test_rejects_anonymous(self, client, db):
        assert client.get(ANALYTICS_URL).status_code in (401, 403)

    def test_aggregates_volume_and_automation_rate(self, staff_client, patient):
        session = make_authenticated_session(patient, channel="web")
        services.dispatch_intent(session, "appointment")  # completed
        services.dispatch_intent(session, "care_gap")     # completed
        services.dispatch_intent(session, "teleportation")  # unknown -> other -> escalated

        body = staff_client.get(ANALYTICS_URL).json()
        assert body["volume"]["sessions"] == 1
        assert body["volume"]["intents_routed"] == 3
        assert body["automation"]["completed"] == 2
        assert body["automation"]["escalated"] == 1
        assert body["automation"]["automation_rate"] == pytest.approx(2 / 3, rel=1e-3)
        assert body["automation"]["escalation_rate"] == pytest.approx(1 / 3, rel=1e-3)
        assert any(row["intent"] == "other" and row["count"] == 1
                   for row in body["top_request_types"])

    def test_no_activity_yields_null_rates_not_a_crash(self, staff_client, db):
        body = staff_client.get(ANALYTICS_URL).json()
        assert body["automation"]["automation_rate"] is None
        assert body["automation"]["escalation_rate"] is None
        assert body["avg_staff_response_seconds"] is None
        assert body["top_request_types"] == []

    def test_avg_staff_response_time_from_resolved_tasks(self, staff_client, patient):
        session = make_authenticated_session(patient, channel="web")
        task = services.create_staff_task(session, "insurance_dispute", summary="co-pay dispute")
        task.status = "resolved"
        task.resolved_at = task.created_at + datetime.timedelta(seconds=180)
        task.save(update_fields=["status", "resolved_at"])

        body = staff_client.get(ANALYTICS_URL).json()
        assert body["avg_staff_response_seconds"] == pytest.approx(180, rel=1e-2)

    def test_open_tasks_do_not_count_toward_response_time(self, staff_client, patient):
        session = make_authenticated_session(patient, channel="web")
        services.create_staff_task(session, "manual_review", summary="still open")

        body = staff_client.get(ANALYTICS_URL).json()
        assert body["avg_staff_response_seconds"] is None
