from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from core.models import Conversation, Message, SentNotification
from registration import services
from registration.tests.test_api import start_session

CHAT_URL = "/api/registration/chat"

HANDLER_RESULT = {
    "stage": "demographics",
    "next_question_topic": "demographics",
    "registration_complete": False,
    "ui_hints": [],
    "patient_id": None,
    "extracted": {},
}


def chat(client, token, message="hi"):
    with patch("registration.views.handle_registration_message",
               return_value=HANDLER_RESULT) as handler, \
         patch("registration.views.stream_reply",
               return_value=iter(["Hello! ", "What's your name?"])):
        response = client.post(CHAT_URL, {"message": message},
                               content_type="application/json",
                               headers={"X-Session-Token": token})
        body = b"".join(response.streaming_content).decode() if response.status_code == 200 else ""
    return response, body, handler


class TestRegistrationChat:
    def test_requires_session_token(self, client, db):
        assert client.post(CHAT_URL, {"message": "hi"},
                           content_type="application/json").status_code == 403

    def test_empty_message_is_rejected(self, client, db):
        token = start_session(client)["session_token"]
        with patch("registration.views.handle_registration_message"):
            response = client.post(CHAT_URL, {"message": "  "},
                                   content_type="application/json",
                                   headers={"X-Session-Token": token})
        assert response.status_code == 400

    def test_streams_deltas_then_stage_metadata(self, client, db):
        token = start_session(client)["session_token"]
        response, body, _ = chat(client, token)
        assert response.status_code == 200
        assert response.headers["Content-Type"] == "text/event-stream"
        assert '"delta": "Hello! "' in body
        # Final event carries what the frontend needs to render OTP box / upload button.
        assert '"done": true' in body
        assert '"stage": "demographics"' in body

    def test_both_sides_of_the_turn_are_persisted(self, client, db):
        session = start_session(client)
        _, _, _ = chat(client, session["session_token"], message="I want to register")
        conversation = Conversation.objects.get(id=session["conversation_id"])
        roles = list(Message.objects.filter(conversation=conversation)
                     .order_by("id").values_list("role", "content"))
        assert roles == [("Patient", "I want to register"),
                         ("Assistant", "Hello! What's your name?")]

    def test_handler_receives_the_full_history(self, client, db):
        session = start_session(client)
        token = session["session_token"]
        chat(client, token, message="first")
        _, _, handler = chat(client, token, message="second")
        history = handler.call_args.args[1]
        assert [m["content"] for m in history] == [
            "first", "Hello! What's your name?", "second",
        ]

    def test_on_file_data_is_injected_into_the_history(self, client, rahul):
        # Demographics submitted via the REST endpoint are invisible in the
        # chat history; a context note must tell the model not to re-ask.
        session = start_session(client)
        Conversation.objects.filter(id=session["conversation_id"]).update(patient=rahul)
        _, _, handler = chat(client, session["session_token"], message="hello")
        history = handler.call_args.args[1]
        note = history[0]["content"]
        assert note.startswith("[Clinic system note")
        assert "date of birth" in note and "phone number" in note
        assert "Rahul" in note
        assert history[1] == {"role": "user", "content": "hello"}


class TestStageGuardInReplyPrompt:
    """The stage machine outranks conversational momentum: until the gate says
    "done", the reply prompt must carry the hard don't-wrap-up guard (the model
    otherwise says "you're all set" right after OTP while insurance is pending)."""

    def _system_for(self, client, stage):
        token = start_session(client)["session_token"]
        result = {**HANDLER_RESULT, "stage": stage}
        with patch("registration.views.handle_registration_message", return_value=result), \
             patch("registration.views.stream_reply", return_value=iter(["ok"])) as stream:
            response = client.post(CHAT_URL, {"message": "hi"},
                                   content_type="application/json",
                                   headers={"X-Session-Token": token})
            b"".join(response.streaming_content)  # drain so stream_reply runs
        return stream.call_args.kwargs["system"]

    def test_not_done_stages_carry_the_guard(self, client, db):
        system = self._system_for(client, "insurance")
        assert "NOT finished" in system
        assert "insurance" in system

    def test_done_stage_does_not_carry_the_guard(self, client, db):
        system = self._system_for(client, "done")
        assert "NOT finished" not in system
        assert "registration is complete" in system


class TestRegistrationCompletedWiring:
    def test_completion_notifies_the_patient_to_book(self, rahul):
        # complete_registration -> emit() -> scheduling subscriber -> notify()
        event = services.complete_registration(rahul)
        assert event.processed is True
        assert event.error == ""
        note = SentNotification.objects.filter(patient=rahul).latest("id")
        assert "book an appointment" in note.rendered_content


class TestAnalytics:
    URL = "/api/staff/registration/analytics"

    def test_staff_only(self, client, db):
        assert client.get(self.URL).status_code == 403

    def test_returns_the_fr_r10_aggregates(self, client, rahul):
        staff = get_user_model().objects.create_user("staff", password="x", is_staff=True)
        client.force_login(staff)
        body = client.get(self.URL).json()
        assert body["patients"]["total"] == 1
        assert body["patients"]["completed"] == 1  # rahul's fixture status
        assert body["patients"]["completion_rate"] == 1.0
        assert set(body) == {"patients", "otp", "duplicates_prevented", "insurance", "documents"}
