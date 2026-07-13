"""Phase 4 orchestration tests (router mocked): the fixed safety order
(red-flag regex before any model call, model emergency flag as second net),
mandatory-escalation categories always creating fixed-priority tasks, code
validating everything the model states (unknown intents/categories ignored),
multi-intent dispatch combined into one response, the auth gate still holding
under routed intents, grounded FAQ answering, and never-block degradation
when the router or FAQ model is down."""

import datetime

import pytest
from django.core.management import call_command
from django.utils import timezone

from core.models import Conversation, Patient
from frontdesk import ai, services
from frontdesk.models import IntentRoute, PatientSession, StaffTask
from triage.models import EscalationAlert

pytestmark = pytest.mark.django_db


@pytest.fixture
def patient(db):
    return Patient.objects.create(
        first_name="Rahul", last_name="Sharma", contact_number="9876543210",
        dob=datetime.date(1990, 5, 17), registration_status="complete",
    )


@pytest.fixture
def session(db):
    conversation = Conversation.objects.create(channel="web", started_at=timezone.now())
    return PatientSession.objects.create(conversation=conversation, channel="web")


@pytest.fixture
def auth_session(session, patient):
    session.patient = patient
    session.authenticated = True
    session.save()
    return session


def routed(intents=(), emergency=False, category=None):
    """A route_message tool result in the schema's shape."""
    return {
        "intents": [{"intent": i, "summary": s} for i, s in intents],
        "emergency_symptoms_detected": emergency,
        "mandatory_escalation_category": category,
    }


@pytest.fixture
def fake_model(monkeypatch):
    """Patch frontdesk.ai.call_tool; set .router / .faq for each tool's reply."""
    class Fake:
        router = routed()
        faq = {"answered": True, "answer": "grounded answer"}
        calls = []

        def __call__(self, system, messages, tool, max_tokens=2048):
            self.calls.append(tool["name"])
            if tool["name"] == "route_message":
                return self.router
            return self.faq

    fake = Fake()
    monkeypatch.setattr("frontdesk.ai.call_tool", fake)
    return fake


# -- (b) the red-flag gate runs BEFORE any model call ---------------------------------

class TestEmergencyPath:
    @pytest.mark.parametrize("text", [
        "I have crushing chest pain",
        "my father can't breathe properly",
        "her speech is suddenly slurred and her face droops",
        "I want to kill myself",
        "the cut won't stop bleeding everywhere",
        "I think she took too many pills",
    ])
    def test_red_flags_short_circuit_before_the_model(self, auth_session, monkeypatch, text):
        def _model_called(*args, **kwargs):
            raise AssertionError("model was called before the deterministic screen")
        monkeypatch.setattr("frontdesk.ai.call_tool", _model_called)

        result = ai.handle_frontdesk_message(auth_session, text)
        assert result["status"] == "emergency"
        assert "emergency department" in result["reply"]

    def test_authenticated_emergency_pages_on_call(self, auth_session, monkeypatch):
        monkeypatch.setattr("frontdesk.ai.call_tool",
                            lambda *a, **k: pytest.fail("model must not run"))
        ai.handle_frontdesk_message(auth_session, "severe chest pain right now")
        alert = EscalationAlert.objects.get()
        assert alert.patient == auth_session.patient
        assert alert.source_agent == "frontdesk"
        assert alert.category == "emergency"

    def test_anonymous_emergency_becomes_a_critical_task(self, session, monkeypatch):
        monkeypatch.setattr("frontdesk.ai.call_tool",
                            lambda *a, **k: pytest.fail("model must not run"))
        result = ai.handle_frontdesk_message(session, "I can't breathe")
        assert result["status"] == "emergency"
        task = StaffTask.objects.get()
        assert task.priority == "critical"
        assert EscalationAlert.objects.count() == 0  # no patient to attach one to

    def test_model_emergency_flag_is_a_second_net(self, auth_session, fake_model):
        # phrasing the regex misses; the router still catches it
        fake_model.router = routed(emergency=True)
        result = ai.handle_frontdesk_message(
            auth_session, "there's an elephant sitting on my chest and my arm tingles")
        assert result["status"] == "emergency"
        assert EscalationAlert.objects.filter(source_agent="frontdesk").exists()


# -- (c) mandatory escalation categories ----------------------------------------------

class TestMandatoryEscalation:
    @pytest.mark.parametrize("category,priority", [
        ("mental_health", "critical"),
        ("stroke", "critical"),
        ("insurance_dispute", "high"),
        ("controlled_substance", "high"),
    ])
    def test_category_always_creates_a_fixed_priority_task(
            self, auth_session, fake_model, category, priority):
        fake_model.router = routed(category=category)
        result = ai.handle_frontdesk_message(auth_session, "please help with this")
        assert result["status"] == "escalated"
        task = StaffTask.objects.get(category=category)
        assert task.priority == priority

    def test_unknown_category_from_the_model_is_ignored(self, auth_session, fake_model):
        fake_model.router = routed(category="pizza_emergency")
        result = ai.handle_frontdesk_message(auth_session, "hmm")
        # code decides: no pizza task; the empty routing falls back to "other"
        assert not StaffTask.objects.filter(category="pizza_emergency").exists()
        assert StaffTask.objects.get().category == "manual_review"
        assert result["status"] == "escalated"


# -- (a) multi-intent dispatch + the auth gate under routing --------------------------

class TestRoutedDispatch:
    def test_schema_enum_stays_in_lockstep_with_the_registry(self):
        assert ai.INTENTS == list(services.REGISTRY)
        schema = ai.ROUTE_MESSAGE["input_schema"]["properties"]
        assert schema["intents"]["items"]["properties"]["intent"]["enum"] == ai.INTENTS

    def test_multi_intent_dispatches_each_in_order(self, auth_session, fake_model):
        fake_model.router = routed(intents=[
            ("refill", "refill BP medication"),
            ("appointment", "book annual checkup"),
        ])
        result = ai.handle_frontdesk_message(
            auth_session, "refill my BP meds and book my annual checkup")
        assert result["status"] == "completed"
        assert list(IntentRoute.objects.order_by("id")
                    .values_list("intent", flat=True)) == ["refill", "appointment"]
        # one coherent reply carrying both parts (PRD after-hours journey)
        assert "prescriptions" in result["reply"].lower() or "medication" in result["reply"].lower()
        assert "appointment" in result["reply"].lower()

    def test_routed_protected_intent_still_hits_the_auth_gate(self, session, fake_model):
        fake_model.router = routed(intents=[("care_gap", "am I due for anything")])
        result = ai.handle_frontdesk_message(session, "am I due for any checkups?")
        assert result["status"] == "auth_required"
        session.refresh_from_db()
        assert session.pending_intents[0]["intent"] == "care_gap"
        assert IntentRoute.objects.count() == 0

    def test_mixed_open_and_gated_intents(self, session, fake_model):
        call_command("seed_knowledge")
        fake_model.router = routed(intents=[
            ("faq", "what are your opening hours"),
            ("refill", "refill my thyroid medication"),
        ])
        fake_model.faq = {"answered": True, "answer": "We're open 9 to 6."}
        result = ai.handle_frontdesk_message(
            session, "what are your hours? also I need my thyroid refill")
        # the FAQ half is answered pre-auth; the refill half waits at the gate
        assert result["status"] == "auth_required"
        assert "9 to 6" in result["reply"]
        assert "verified" in result["reply"]
        session.refresh_from_db()
        assert [p["intent"] for p in session.pending_intents] == ["refill"]

    def test_unroutable_message_falls_back_to_a_human(self, auth_session, fake_model):
        fake_model.router = routed()  # the model found nothing
        result = ai.handle_frontdesk_message(auth_session, "asdf qwerty")
        assert result["status"] == "escalated"
        assert StaffTask.objects.get().category == "manual_review"

    def test_router_failure_never_blocks_the_patient(self, auth_session):
        # conftest's blocked call_tool raises -> graceful degradation
        result = ai.handle_frontdesk_message(auth_session, "refill my meds please")
        assert result["status"] == "escalated"
        assert result["reply"]
        assert StaffTask.objects.get().category == "manual_review"


# -- (d) FAQ answers stay grounded in the articles ------------------------------------

class TestGroundedFaq:
    @pytest.fixture(autouse=True)
    def _seed(self, db):
        call_command("seed_knowledge")

    def test_reply_is_the_grounded_model_answer(self, session, fake_model):
        fake_model.faq = {"answered": True,
                          "answer": "We're open 9:00 AM to 6:00 PM, Monday to Saturday."}
        result = services.dispatch_intent(session, "faq",
                                          {"question": "what are your hours"})
        assert result["reply"] == "We're open 9:00 AM to 6:00 PM, Monday to Saturday."
        assert result["articles"]  # the sources ride along

    def test_model_saying_unanswered_escalates_honestly(self, session, fake_model):
        # retrieval found articles, but none actually answer the question
        fake_model.faq = {"answered": False, "answer": ""}
        result = services.dispatch_intent(session, "faq",
                                          {"question": "do you do home visits on holidays"})
        assert result["status"] == "escalated"
        assert StaffTask.objects.get().category == "unanswered_question"

    def test_model_down_falls_back_to_the_article_verbatim(self, session):
        # conftest's blocked call_tool raises -> top article body, no task
        result = services.dispatch_intent(session, "faq",
                                          {"question": "what are your hours"})
        assert result["status"] == "completed"
        assert "9:00 AM" in result["reply"]
        assert StaffTask.objects.count() == 0
