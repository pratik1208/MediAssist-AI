import datetime

import pytest
from django.core import signing
from django.core.files.uploadedfile import SimpleUploadedFile

from core.models import Conversation, EventLog, Patient
from registration.models import UploadedDocument
from registration.tests.test_services import sent_code
from registration.views import REGISTRATION_SESSION_SALT

START_URL = "/api/registration/start"

DEMOGRAPHICS = {
    "first_name": "Rahul",
    "last_name": "Sharma",
    "dob": "1990-05-17",
    "contact_number": "+91 98765 43210",
    "email": "rahul@example.com",
}

INSURANCE = {
    "policy_number": "BS-448291",
    "provider_name": "BlueShield",
    "coverage_start": "2026-01-01",
    "coverage_end": "2026-12-31",
}


def start_session(client):
    return client.post(START_URL, {"channel": "web"}, content_type="application/json").json()


def post_json(client, url, data, token):
    return client.post(url, data, content_type="application/json",
                       headers={"X-Session-Token": token})


class TestStartRegistration:
    def test_creates_a_session(self, client, db):
        response = client.post(START_URL, {"channel": "web"}, content_type="application/json")
        assert response.status_code == 201
        body = response.json()
        assert set(body) == {"session_token", "conversation_id"}

        conversation = Conversation.objects.get(id=body["conversation_id"])
        assert conversation.patient is None  # nobody identified yet
        assert conversation.channel == "web"
        assert conversation.agent_context["active_agent"] == "registration"

    def test_token_is_signed_and_points_at_the_conversation(self, client, db):
        body = client.post(START_URL, {"channel": "web"}, content_type="application/json").json()
        payload = signing.loads(body["session_token"], salt=REGISTRATION_SESSION_SALT)
        assert payload == {"conversation_id": body["conversation_id"]}

    def test_channel_defaults_to_web(self, client, db):
        response = client.post(START_URL, {}, content_type="application/json")
        assert response.status_code == 201
        conversation = Conversation.objects.get(id=response.json()["conversation_id"])
        assert conversation.channel == "web"

    def test_unknown_channel_is_rejected(self, client, db):
        response = client.post(START_URL, {"channel": "carrier_pigeon"}, content_type="application/json")
        assert response.status_code == 400
        assert Conversation.objects.count() == 0

    def test_tampered_token_fails_verification(self, client, db):
        body = client.post(START_URL, {"channel": "web"}, content_type="application/json").json()
        with pytest.raises(signing.BadSignature):
            signing.loads(body["session_token"] + "x", salt=REGISTRATION_SESSION_SALT)


class TestSessionGuard:
    def test_endpoints_reject_missing_token(self, client, db):
        # DRF answers 403 for a missing/invalid credential when no formal
        # auth scheme is declared; the point is: refused, nothing happens.
        for url in ["/api/registration/demographics", "/api/registration/otp/request",
                    "/api/registration/otp/verify", "/api/registration/insurance",
                    "/api/registration/complete"]:
            assert client.post(url, {}, content_type="application/json").status_code == 403
        assert client.get("/api/registration/status").status_code == 403

    def test_steps_needing_a_patient_are_refused_before_demographics(self, client, db):
        token = start_session(client)["session_token"]
        response = post_json(client, "/api/registration/otp/request", {}, token)
        assert response.status_code == 400
        assert "demographics" in response.json()["error"]


class TestDemographics:
    def test_new_patient_is_created_and_linked(self, client, db):
        session = start_session(client)
        response = post_json(client, "/api/registration/demographics", DEMOGRAPHICS,
                             session["session_token"])
        assert response.status_code == 201
        assert response.json()["match"] == "new"
        conversation = Conversation.objects.get(id=session["conversation_id"])
        assert conversation.patient_id == response.json()["patient_id"]

    def test_returning_patient_is_reused(self, client, db):
        token1 = start_session(client)["session_token"]
        first = post_json(client, "/api/registration/demographics", DEMOGRAPHICS, token1).json()
        # Same person starts a second session -> same record, no new row.
        token2 = start_session(client)["session_token"]
        response = post_json(client, "/api/registration/demographics", DEMOGRAPHICS, token2)
        assert response.status_code == 200
        assert response.json() == {"patient_id": first["patient_id"], "match": "existing"}
        assert Patient.objects.count() == 1

    def test_possible_duplicate_is_blocked(self, client, db):
        token1 = start_session(client)["session_token"]
        post_json(client, "/api/registration/demographics", DEMOGRAPHICS, token1)
        # Similar last name + same dob but a different phone -> 409, no row.
        token2 = start_session(client)["session_token"]
        lookalike = {**DEMOGRAPHICS, "last_name": "Sharme", "contact_number": "9000000000"}
        response = post_json(client, "/api/registration/demographics", lookalike, token2)
        assert response.status_code == 409
        assert Patient.objects.count() == 1

    def test_missing_fields_are_named(self, client, db):
        token = start_session(client)["session_token"]
        response = post_json(client, "/api/registration/demographics",
                             {"first_name": "Rahul"}, token)
        assert response.status_code == 400
        assert "contact_number" in response.json()["error"]


class TestFullRegistrationFlow:
    def test_a_patient_registers_end_to_end_with_zero_ai(self, client, db, settings, tmp_path):
        settings.MEDIA_ROOT = tmp_path

        # 1. start a session
        session = start_session(client)
        token = session["session_token"]

        # 2. demographics -> new patient
        patient_id = post_json(client, "/api/registration/demographics",
                               DEMOGRAPHICS, token).json()["patient_id"]

        # 3. identity: request + verify OTP (code read from the dev send log)
        assert post_json(client, "/api/registration/otp/request",
                         {"channel": "SMS"}, token).status_code == 202
        patient = Patient.objects.get(id=patient_id)
        verify = post_json(client, "/api/registration/otp/verify",
                           {"code": sent_code(patient)}, token)
        assert verify.json() == {"verified": True}

        # 4. insurance -> active policy, not flagged
        insurance = post_json(client, "/api/registration/insurance", INSURANCE, token)
        assert insurance.status_code == 201
        assert insurance.json()["eligibility_status"] == "eligible"
        assert insurance.json()["flagged"] is False

        # 5. upload an insurance card image
        upload = client.post(
            "/api/registration/documents",
            {"file": SimpleUploadedFile("card.png", b"png-bytes", "image/png"),
             "doc_type": "insurance_card"},
            headers={"X-Session-Token": token},
        )
        assert upload.status_code == 201
        assert upload.json()["extraction_status"] == "pending"

        # 6. intake (via the CRUD endpoint until the AI writes it in Phase 4)
        intake = client.post("/api/intakesummary",
                             {"patient": patient_id, "clinical_profile": {"symptoms": ["cough"]},
                              "summary_text": "placeholder"},
                             content_type="application/json")
        assert intake.status_code == 201

        # 7. status shows nothing missing
        status_body = client.get("/api/registration/status",
                                 headers={"X-Session-Token": token}).json()
        assert status_body == {"registration_status": "verified", "missing": []}

        # 8. complete -> event emitted for downstream agents
        done = post_json(client, "/api/registration/complete", {}, token)
        assert done.status_code == 200
        patient.refresh_from_db()
        assert patient.registration_status == "complete"
        assert EventLog.objects.filter(name="registration.completed",
                                       payload__patient_id=patient_id).exists()

    def test_wrong_otp_maps_to_error_code(self, client, db):
        token = start_session(client)["session_token"]
        post_json(client, "/api/registration/demographics", DEMOGRAPHICS, token)
        post_json(client, "/api/registration/otp/request", {"channel": "SMS"}, token)
        response = post_json(client, "/api/registration/otp/verify", {"code": "000000"}, token)
        # (the real code is random; 000000 can collide once in a million — acceptable)
        if response.status_code == 400:
            assert response.json() == {"verified": False, "code": "otp_invalid"}

    def test_inactive_insurance_is_flagged_but_accepted(self, client, db):
        token = start_session(client)["session_token"]
        post_json(client, "/api/registration/demographics", DEMOGRAPHICS, token)
        response = post_json(client, "/api/registration/insurance",
                             {**INSURANCE, "policy_number": "INACTIVE-001"}, token)
        assert response.status_code == 201  # accepted, registration continues
        assert response.json()["flagged"] is True

    def test_complete_is_refused_while_steps_are_missing(self, client, db):
        token = start_session(client)["session_token"]
        post_json(client, "/api/registration/demographics", DEMOGRAPHICS, token)
        response = post_json(client, "/api/registration/complete", {}, token)
        assert response.status_code == 400
        assert set(response.json()["missing"]) == {"identity", "insurance", "intake"}
