"""Triage API — a full scripted assessment with zero AI (Phase 3 exit)."""

import pytest
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.management import call_command
from django.utils import timezone

from core.models import Conversation
from core.sessions import SESSION_SALT
from triage.models import EscalationAlert, TriageAssessment

START_URL = "/api/triage/assessments/"


@pytest.fixture
def seeded(db):
    call_command("seed_protocols", verbosity=0)


@pytest.fixture
def session(db):
    """A session whose conversation has a verified patient (spec auth)."""
    import datetime

    from core.models import Patient
    patient = Patient.objects.create(
        first_name="Rahul", last_name="Sharma", contact_number="9876543210",
        dob=datetime.date(1990, 5, 17), identity_verified=True,
    )
    conversation = Conversation.objects.create(
        channel="web", started_at=timezone.now(), patient=patient
    )
    token = signing.dumps({"conversation_id": conversation.id}, salt=SESSION_SALT)
    return {"token": token, "conversation": conversation, "patient": patient}


def post_json(client, url, data, token):
    return client.post(url, data, content_type="application/json",
                       headers={"X-Session-Token": token})


class TestAuth:
    def test_requires_session_token(self, client, db):
        assert client.post(START_URL, {}, content_type="application/json").status_code == 403

    def test_requires_verified_identity(self, client, session):
        session["patient"].identity_verified = False
        session["patient"].save(update_fields=["identity_verified"])
        response = post_json(client, START_URL, {"symptoms_text": "headache"},
                             session["token"])
        assert response.status_code == 403
        assert "identity" in response.json()["error"]

    def test_other_sessions_assessments_are_invisible(self, client, seeded, session):
        other = Conversation.objects.create(channel="web", started_at=timezone.now(),
                                            patient=session["patient"])
        assessment = TriageAssessment.objects.create(
            patient=session["patient"], conversation=other,
            reported_symptoms={}, acuity="minimal", disposition="self_care",
            summary_text="",
        )
        response = client.get(f"{START_URL}{assessment.id}/",
                              headers={"X-Session-Token": session["token"]})
        assert response.status_code == 404


class TestStartAssessment:
    def test_starts_with_the_protocols_first_question(self, client, seeded, session):
        response = post_json(client, START_URL,
                             {"symptoms_text": "bad headache since morning"},
                             session["token"])
        assert response.status_code == 201
        body = response.json()
        assert body["protocol"] == "Headache"
        assert body["first_question"].startswith("Did the headache come on suddenly")

    def test_red_flag_text_escalates_immediately_no_questions(self, client, seeded, session):
        response = post_json(client, START_URL,
                             {"symptoms_text": "crushing pain in my chest"},
                             session["token"])
        assert response.status_code == 201
        body = response.json()
        assert body["complete"] is True
        assert body["acuity"] == "emergency"
        assert body["ui_hints"] == {"emergency": True}
        assert "911" in body["message"]
        assert EscalationAlert.objects.filter(assessment_id=body["id"]).exists()

    def test_red_flag_without_matching_protocol_still_escalates(self, client, seeded, session):
        response = post_json(client, START_URL,
                             {"symptoms_text": "I want to end my life"},
                             session["token"])
        assert response.status_code == 201
        assert response.json()["acuity"] == "emergency"
        assessment = TriageAssessment.objects.get(id=response.json()["id"])
        assert assessment.clinical_protocol is None

    def test_unmatched_symptoms_get_422_not_a_wrong_protocol(self, client, seeded, session):
        response = post_json(client, START_URL,
                             {"symptoms_text": "I twisted my ankle"},
                             session["token"])
        assert response.status_code == 422

    def test_empty_symptoms_rejected(self, client, seeded, session):
        assert post_json(client, START_URL, {"symptoms_text": "  "},
                         session["token"]).status_code == 400


class TestScriptedInterview:
    """The Phase 3 exit criterion: a full assessment with scripted answers."""

    def drive(self, client, session, symptoms, answers):
        start = post_json(client, START_URL, {"symptoms_text": symptoms},
                          session["token"]).json()
        url = f"{START_URL}{start['id']}/answer/"
        response = None
        for answer in answers:
            response = post_json(client, url, {"answer": answer}, session["token"])
        return start, response.json()

    def test_routine_headache_end_to_end(self, client, seeded, session):
        # Wordy negatives ("no, similar to before") must not trip is_true
        # red flags — regression from the live curl drive.
        start, final = self.drive(
            client, session, "mild headache for two days",
            ["it came on gradually", "no, similar to before", "3",
             "none of those", "no"],
        )
        assert final["complete"] is True
        assert final["acuity"] == "low"
        assert final["disposition"] == "routine"
        assert final["ui_hints"]["offer_booking"] is True
        assessment = TriageAssessment.objects.get(id=start["id"])
        assert assessment.status == "completed"
        assert assessment.findings["severity_1_10"] == 3

    def test_severe_findings_complete_as_emergency_and_escalate(self, client, seeded, session):
        start, final = self.drive(
            client, session, "headache behind my eyes",
            # sudden onset is a protocol red-flag finding -> emergency at completion
            ["it was sudden, within seconds", "no", "9", "none", "no"],
        )
        assert final["acuity"] == "emergency"
        assert EscalationAlert.objects.filter(assessment_id=start["id"]).exists()

    def test_mid_interview_red_flag_answer_escalates(self, client, seeded, session):
        start = post_json(client, START_URL,
                          {"symptoms_text": "stomach pain after eating"},
                          session["token"]).json()
        url = f"{START_URL}{start['id']}/answer/"
        post_json(client, url, {"answer": "lower left side"}, session["token"])
        response = post_json(client, url, {"answer": "it's so bad I can't breathe"},
                             session["token"])
        assert response.json()["acuity"] == "emergency"
        assessment = TriageAssessment.objects.get(id=start["id"])
        assert assessment.status == "escalated"

    def test_adult_fever_interview_completes(self, client, seeded, session):
        # Regression: the legacy hand-made fever protocol 500'd on the first
        # answer (no "capture" keys); the seeded replacement must run through.
        start, final = self.drive(
            client, session, "I have a fever and chills",
            ["101, with a thermometer", "about a day", "none of those",
             "no", "keeping fluids down fine"],
        )
        assert final["complete"] is True
        assert final["acuity"] == "low"

    def test_reworded_stiff_neck_still_ends_as_emergency(self, client, seeded, session):
        # Round-2 live-test regression: "my neck feels stiff" (word order
        # flipped) missed the meningitis red flag and came out low/routine.
        start, final = self.drive(
            client, session, "I've had a fever since this morning",
            ["102 measured with a thermometer", "about 10 hours",
             "my neck feels stiff and it hurts to look down", "no",
             "keeping fluids down"],
        )
        assert final["acuity"] == "emergency"
        assert EscalationAlert.objects.filter(assessment_id=start["id"]).exists()

    def test_numbers_inside_sentences_are_understood(self, client, seeded, session):
        # Round-2 live-test regression: "It's around 104 F" parsed as text,
        # so the >=104 rule never fired and a 104° fever came out routine.
        _, final = self.drive(
            client, session, "I have a fever and chills",
            ["It's around 104 F", "about half a day", "none of those",
             "no", "fluids are fine"],
        )
        assert final["acuity"] == "high"
        assert final["disposition"] == "same_day"

    def test_negated_symptom_does_not_raise_acuity(self, client, seeded, session):
        # Round-1 live-test regression: "No fever or anything else" matched
        # the fever rule and pushed a mild headache to medium.
        start, final = self.drive(
            client, session, "I've had a mild headache since this afternoon",
            ["it built up gradually over a few hours",
             "no, it's similar to headaches I've had before",
             "about a 3 out of 10",
             "no fever or anything else, just the headache",
             "no, I haven't hit my head"],
        )
        assert final["acuity"] == "low"
        assert final["disposition"] == "routine"
        assessment = TriageAssessment.objects.get(id=start["id"])
        assert assessment.findings["severity_1_10"] == 3

    def test_infant_fever_routes_pediatric_and_ends_emergency(self, client, seeded, session):
        # Round-1 live-test regression: "my baby has a fever" landed on the
        # ADULT protocol and skipped the <=3-months emergency rule.
        start = post_json(client, START_URL,
                          {"symptoms_text": "My baby has a fever, she seems warm"},
                          session["token"]).json()
        assert start["protocol"] == "Pediatric Fever"
        url = f"{START_URL}{start['id']}/answer/"
        final = None
        for answer in ["She is 2 months old", "101.5F forehead thermometer",
                       "about 12 hours", "a bit sleepy but drinking milk",
                       "no rash or anything else"]:
            final = post_json(client, url, {"answer": answer}, session["token"]).json()
        assert final["acuity"] == "emergency"

    def test_toddler_age_in_years_is_not_an_infant(self, client, seeded, session):
        # "2 years old" must convert to 24 months, not read as 2 months.
        start = post_json(client, START_URL,
                          {"symptoms_text": "my child has a fever"},
                          session["token"]).json()
        assert start["protocol"] == "Pediatric Fever"
        url = f"{START_URL}{start['id']}/answer/"
        post_json(client, url, {"answer": "he is 2 years old"}, session["token"])
        assessment = TriageAssessment.objects.get(id=start["id"])
        assert assessment.findings["age_months"] == 24

    def test_protocol_without_capture_keys_never_500s(self, client, session):
        # Protocols are editable data; a row missing "capture" must degrade
        # gracefully, not crash the interview.
        from triage.models import ClinicalProtocol
        ClinicalProtocol.objects.create(
            name="Legacy", symptom_keywords=["wobbly knee"],
            question_flow=[{"id": 1, "ask": "How long?"},
                           {"id": 2, "ask": "How bad?"}],
            disposition_rules={"default_acuity": "low"},
            version="0.1", is_active=True,
        )
        start = post_json(client, START_URL, {"symptoms_text": "wobbly knee"},
                          session["token"]).json()
        url = f"{START_URL}{start['id']}/answer/"
        first = post_json(client, url, {"answer": "two days"}, session["token"])
        assert first.status_code == 200
        assert first.json() == {"next_question": "How bad?"}
        final = post_json(client, url, {"answer": "not too bad"}, session["token"])
        assert final.status_code == 200
        assert final.json()["complete"] is True

    def test_finished_assessment_refuses_more_answers(self, client, seeded, session):
        start, _ = self.drive(client, session, "mild headache",
                              ["gradually", "no", "2", "none", "no"])
        response = post_json(client, f"{START_URL}{start['id']}/answer/",
                             {"answer": "one more"}, session["token"])
        assert response.status_code == 400

    def test_detail_endpoint_tracks_progress(self, client, seeded, session):
        start = post_json(client, START_URL, {"symptoms_text": "stomach pain"},
                          session["token"]).json()
        post_json(client, f"{START_URL}{start['id']}/answer/",
                  {"answer": "lower left"}, session["token"])
        body = client.get(f"{START_URL}{start['id']}/",
                          headers={"X-Session-Token": session["token"]}).json()
        assert body["status"] == "pending"
        assert (body["questions_answered"], body["questions_total"]) == (1, 5)
        assert body["acuity"] is None  # not revealed until finished


class TestStaffEscalations:
    URL = "/api/staff/triage/escalations/"

    @pytest.fixture
    def staff_client(self, client, db):
        staff = get_user_model().objects.create_user("nurse", password="x", is_staff=True)
        client.force_login(staff)
        return client

    def make_alert(self, client, seeded, session):
        response = post_json(client, START_URL,
                             {"symptoms_text": "crushing chest pain"},
                             session["token"])
        return EscalationAlert.objects.get(assessment_id=response.json()["id"])

    def test_staff_only(self, client, db):
        assert client.get(self.URL).status_code == 403

    def test_list_and_filter_by_status(self, staff_client, seeded, session):
        alert = self.make_alert(staff_client, seeded, session)
        listed = staff_client.get(self.URL + "?status=open").json()
        assert [a["id"] for a in listed] == [alert.id]
        assert listed[0]["priority"] == "high"
        assert staff_client.get(self.URL + "?status=resolved").json() == []

    def test_acknowledge(self, staff_client, seeded, session):
        alert = self.make_alert(staff_client, seeded, session)
        body = staff_client.post(f"{self.URL}{alert.id}/ack/").json()
        assert body == {"status": "acknowledged"}
        alert.refresh_from_db()
        assert alert.acknowledged_at is not None
        # second ack is a no-op, not an error
        assert staff_client.post(f"{self.URL}{alert.id}/ack/").json() == {"status": "acknowledged"}


class TestAnalytics:
    URL = "/api/staff/triage/analytics/"

    def test_staff_only(self, client, db):
        assert client.get(self.URL).status_code == 403

    def test_fr_t10_aggregates(self, client, seeded, session):
        staff = get_user_model().objects.create_user("t-staff", password="x", is_staff=True)

        # one routine completion (full scripted interview)
        start = post_json(client, START_URL, {"symptoms_text": "mild headache"},
                          session["token"]).json()
        for answer in ["gradually", "no, as usual", "3", "none", "no"]:
            post_json(client, f"{START_URL}{start['id']}/answer/",
                      {"answer": answer}, session["token"])
        # one emergency escalation
        post_json(client, START_URL, {"symptoms_text": "crushing chest pain"},
                  session["token"])

        client.force_login(staff)
        body = client.get(self.URL).json()
        assert body["assessments"]["total"] == 2
        assert body["assessments"]["completed"] == 1
        assert body["acuity_distribution"] == {"low": 1, "emergency": 1}
        assert body["escalations"] == {"total": 1, "rate": 0.5}
        assert body["avg_triage_seconds"] is not None
        assert body["same_day"]["dispositions"] == 0
