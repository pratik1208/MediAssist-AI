"""Phase 3 API tests: the front-door session (/frontdesk/start), the single
chat entry point (SSE envelope, auth step-up over HTTP, queued intents
resumed after verification, transcript rows with no secrets in them), the
staff task queue (list order, claim/resolve transitions, auth gating), and
the KnowledgeArticle CRUD keeping the search vector fresh."""

import datetime
import json

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import override_settings

from core.models import Conversation, Message, Patient
from frontdesk import services
from frontdesk.models import IntentRoute, PatientSession, StaffTask

pytestmark = pytest.mark.django_db

START_URL = "/api/frontdesk/start"
CHAT_URL = "/api/frontdesk/chat"
TASKS_URL = "/api/staff/frontdesk/tasks/"

DOB = "1990-05-17"
PHONE = "9876543210"


@pytest.fixture
def patient(db):
    return Patient.objects.create(
        first_name="Rahul", last_name="Sharma", contact_number=PHONE,
        dob=datetime.date(1990, 5, 17), registration_status="complete",
    )


@pytest.fixture
def staff_client(client, db):
    staff = get_user_model().objects.create_user("frontdesk_staff", password="x", is_staff=True)
    client.force_login(staff)
    return client


def start(client, channel="web"):
    response = client.post(START_URL, {"channel": channel},
                           content_type="application/json")
    assert response.status_code == 201, response.content
    return response.json()


def chat(client, token, body):
    """POST to the chat endpoint and return (status_code, final SSE event)."""
    response = client.post(CHAT_URL, body, content_type="application/json",
                           headers={"X-Session-Token": token})
    if response.status_code != 200:
        return response.status_code, response.json()
    raw = b"".join(response.streaming_content).decode()
    assert response.headers["Content-Type"] == "text/event-stream"
    event = json.loads(raw.split("data: ", 1)[1].split("\n\n", 1)[0])
    assert event["done"] is True
    return 200, event


# -- the front door -------------------------------------------------------------------

class TestStart:
    def test_start_creates_conversation_and_session(self, client, db):
        data = start(client, channel="whatsapp")
        assert data["session_token"]
        session = PatientSession.objects.get(id=data["session_id"])
        assert session.conversation_id == data["conversation_id"]
        assert session.channel == "whatsapp"
        assert session.authenticated is False

    def test_bad_channel_rejected(self, client, db):
        response = client.post(START_URL, {"channel": "carrier_pigeon"},
                               content_type="application/json")
        assert response.status_code == 400


# -- the chat entry point -------------------------------------------------------------

class TestChat:
    def test_requires_session_token(self, client, db):
        assert client.post(CHAT_URL, {"intent": "faq"},
                           content_type="application/json").status_code == 403

    def test_needs_an_intent_or_action(self, client, db):
        token = start(client)["session_token"]
        code, body = chat(client, token, {"message": "hello?"})
        assert code == 400

    def test_faq_answers_pre_auth(self, client, db):
        call_command("seed_knowledge")
        token = start(client)["session_token"]
        code, event = chat(client, token, {
            "intent": "faq", "payload": {"question": "what are your hours"}})
        assert code == 200
        assert event["status"] == "completed"
        assert "9:00 AM" in event["reply"]

    def test_protected_intent_pre_auth_asks_for_verification(self, client, db):
        data = start(client)
        code, event = chat(client, data["session_token"],
                           {"intent": "refill", "message": "refill my meds"})
        assert code == 200
        assert event["status"] == "auth_required"
        session = PatientSession.objects.get(id=data["session_id"])
        assert session.pending_intents[0]["intent"] == "refill"
        assert IntentRoute.objects.count() == 0

    def test_start_auth_validates_input(self, client, db):
        token = start(client)["session_token"]
        code, body = chat(client, token, {"action": "start_auth", "dob": DOB})
        assert code == 400

    def test_auth_failures_stay_neutral_over_http(self, client, patient):
        token = start(client)["session_token"]
        _, unknown = chat(client, token, {
            "action": "start_auth", "contact_number": "0000000000", "dob": DOB})
        _, wrong_dob = chat(client, token, {
            "action": "start_auth", "contact_number": PHONE, "dob": "1980-01-01"})
        assert unknown["status"] == wrong_dob["status"] == "auth_failed"
        assert unknown["reply"] == wrong_dob["reply"]  # NFR-2: indistinguishable

    def test_step_up_then_resume_queued_intents(self, client, patient):
        data = start(client)
        token = data["session_token"]
        chat(client, token, {"intent": "appointment"})   # queued behind the gate
        chat(client, token, {"intent": "care_gap"})      # queued behind the gate

        _, started = chat(client, token, {
            "action": "start_auth", "contact_number": PHONE, "dob": DOB})
        assert started["status"] == "auth_started"

        with override_settings(DEBUG=True):
            _, verified = chat(client, token, {
                "action": "verify_otp", "dob": DOB, "otp": "123456"})
        assert verified["status"] == "authenticated"
        assert [r["status"] for r in verified["resumed"]] == ["completed", "completed"]

        session = PatientSession.objects.get(id=data["session_id"])
        assert session.authenticated is True
        assert session.patient == patient
        assert session.pending_intents == []

    def test_transcript_rows_written_without_secrets(self, client, patient):
        data = start(client)
        token = data["session_token"]
        chat(client, token, {"intent": "refill", "message": "refill my meds"})
        chat(client, token, {"action": "start_auth", "contact_number": PHONE, "dob": DOB})
        with override_settings(DEBUG=True):
            chat(client, token, {"action": "verify_otp", "dob": DOB, "otp": "123456"})

        contents = list(Message.objects.filter(
            conversation_id=data["conversation_id"]).order_by("id")
            .values_list("role", "content"))
        assert ("Patient", "refill my meds") in contents
        # FR-A8: both sides of every turn are persisted...
        assert sum(1 for role, _ in contents if role == "Assistant") == 3
        # ...but DOB / phone / OTP never land in the transcript
        joined = " ".join(content for _, content in contents)
        assert DOB not in joined and PHONE not in joined and "123456" not in joined

    def test_unknown_intent_escalates_to_a_task(self, client, patient):
        token = start(client)["session_token"]
        code, event = chat(client, token, {
            "intent": "teleportation", "message": "beam me up"})
        assert event["status"] == "escalated"
        assert StaffTask.objects.get().category == "manual_review"


# -- the staff task queue --------------------------------------------------------------

class TestTaskQueue:
    @pytest.fixture
    def session(self, db):
        conversation = Conversation.objects.create(
            channel="web", started_at=datetime.datetime.now(datetime.timezone.utc))
        return PatientSession.objects.create(conversation=conversation, channel="web")

    def test_rejects_anonymous(self, client, db):
        assert client.get(TASKS_URL).status_code in (401, 403)
        assert client.post(f"{TASKS_URL}1/claim/").status_code in (401, 403)
        assert client.post(f"{TASKS_URL}1/resolve/").status_code in (401, 403)

    def test_queue_orders_by_priority_then_age(self, staff_client, session):
        normal = services.create_staff_task(session, "manual_review", summary="later")
        critical = services.create_staff_task(session, "stroke", summary="now")
        high = services.create_staff_task(session, "insurance_dispute", summary="soon")
        rows = staff_client.get(TASKS_URL).json()
        assert [r["id"] for r in rows] == [critical.id, high.id, normal.id]

    def test_status_filter(self, staff_client, session):
        open_task = services.create_staff_task(session, "manual_review")
        done = services.create_staff_task(session, "manual_review")
        done.status = "resolved"
        done.save()
        rows = staff_client.get(f"{TASKS_URL}?status=open").json()
        assert [r["id"] for r in rows] == [open_task.id]

    def test_claim_then_resolve(self, staff_client, session):
        task = services.create_staff_task(session, "insurance_dispute", summary="co-pay")
        claimed = staff_client.post(f"{TASKS_URL}{task.id}/claim/").json()
        assert claimed["status"] == "claimed"
        assert claimed["claimed_by"] == "frontdesk_staff"
        # a claimed task can't be claimed again
        assert staff_client.post(f"{TASKS_URL}{task.id}/claim/").status_code == 409

        resolved = staff_client.post(f"{TASKS_URL}{task.id}/resolve/").json()
        assert resolved["status"] == "resolved"
        assert resolved["resolved_at"] is not None
        assert staff_client.post(f"{TASKS_URL}{task.id}/resolve/").status_code == 409

    def test_unknown_task_is_404(self, staff_client, db):
        assert staff_client.post(f"{TASKS_URL}424242/claim/").status_code == 404


# -- knowledge CRUD keeps the vector fresh ----------------------------------------------

class TestKnowledgeCRUD:
    def test_create_is_immediately_searchable(self, client, db):
        response = client.post("/api/knowledgearticle", {
            "title": "Wheelchair access",
            "body": "Both clinic locations have step-free wheelchair access and lifts.",
            "tags": ["access"],
        }, content_type="application/json")
        assert response.status_code == 201
        hits = services.search_knowledge("is the clinic wheelchair accessible")
        assert hits and hits[0].title == "Wheelchair access"

    def test_update_refreshes_the_vector(self, client, db):
        created = client.post("/api/knowledgearticle", {
            "title": "Parking", "body": "Street parking only.",
        }, content_type="application/json").json()
        client.patch(f"/api/knowledgearticle/{created['id']}",
                     {"body": "We have a rooftop helipad for drone deliveries."},
                     content_type="application/json")
        hits = services.search_knowledge("helipad drone")
        assert hits and hits[0].id == created["id"]
