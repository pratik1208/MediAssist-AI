"""Prior authorization API — auth, CRUD, and a full lifecycle over HTTP
(Phase 3 exit, mirroring Phase 5's manual-E2E narrative: order -> detected
-> package -> submit -> info requested -> auto-answer -> approved)."""

import datetime

import pytest
from django.contrib.auth import get_user_model
from django.core import signing
from django.utils import timezone

from core.models import Conversation, Doctor, EventLog, Patient
from core.sessions import SESSION_SALT
from priorauth.gateway import SimulatedPayerGateway
from priorauth.models import AuthorizationRequest, PayerRule, TreatmentOrder
from registration.models import IntakeSummary, InsurancePolicy
from triage.models import EscalationAlert

ORDERS_URL = "/api/priorauth/orders/"
STAFF_URL = "/api/staff/priorauth/"


@pytest.fixture
def doctor(db):
    return Doctor.objects.create(name="Dr. Asha Mehta", specialty="General Medicine")


@pytest.fixture
def patient(db):
    return Patient.objects.create(
        first_name="Rahul", last_name="Sharma", contact_number="9876543210",
        dob=datetime.date(1990, 5, 17), identity_verified=True,
    )


@pytest.fixture
def policy(db, patient):
    return InsurancePolicy.objects.create(
        patient=patient, policy_number="BS-1", provider_name="BlueShield",
        plan="Premium PPO", coverage_details="",
    )


@pytest.fixture
def rule(db, policy):
    return PayerRule.objects.create(
        payer_name="BlueShield", plan="Premium PPO", cpt_pattern="7055[1-3]",
        requires_auth=True, submission_channel="epa",
        required_documentation=["diagnosis"],
    )


@pytest.fixture
def session(db, patient):
    conversation = Conversation.objects.create(channel="web", started_at=timezone.now(), patient=patient)
    token = signing.dumps({"conversation_id": conversation.id}, salt=SESSION_SALT)
    return {"token": token, "patient": patient}


@pytest.fixture
def staff_client(client, db):
    staff = get_user_model().objects.create_user("reviewer", password="x", is_staff=True)
    client.force_login(staff)
    return client


def post_json(client, url, data, token=None):
    headers = {"X-Session-Token": token} if token else {}
    return client.post(url, data, content_type="application/json", headers=headers)


class TestCreateTreatmentOrder:
    def test_requires_staff_login(self, client, db):
        assert client.post(ORDERS_URL, {}, content_type="application/json").status_code == 403

    def test_missing_fields_is_400(self, staff_client, patient):
        response = post_json(staff_client, ORDERS_URL, {"patient_id": patient.id})
        assert response.status_code == 400
        assert "order_type" in response.json()["error"]

    def test_invalid_order_type_is_400(self, staff_client, patient):
        response = post_json(staff_client, ORDERS_URL,
                             {"patient_id": patient.id, "order_type": "surgery"})
        assert response.status_code == 400

    def test_unknown_patient_is_404(self, staff_client):
        response = post_json(staff_client, ORDERS_URL,
                             {"patient_id": 99999, "order_type": "imaging"})
        assert response.status_code == 404

    def test_order_that_needs_auth_creates_a_request(self, staff_client, patient, rule):
        response = post_json(staff_client, ORDERS_URL, {
            "patient_id": patient.id, "order_type": "imaging", "cpt_code": "70551",
        })
        assert response.status_code == 201
        body = response.json()
        assert body["authorization_required"] is True
        assert body["status"] == "ready_for_review"
        assert TreatmentOrder.objects.filter(id=body["order_id"]).exists()

    def test_order_that_does_not_need_auth_creates_no_request(self, staff_client, patient, policy):
        PayerRule.objects.create(payer_name="BlueShield", requires_auth=False,
                                 submission_channel="api", cpt_pattern="99213")
        response = post_json(staff_client, ORDERS_URL, {
            "patient_id": patient.id, "order_type": "procedure", "cpt_code": "99213",
        })
        assert response.status_code == 201
        body = response.json()
        assert body["authorization_required"] is False
        assert body["request_id"] is None


class TestPatientAuthorizations:
    def test_requires_session_token(self, client, db):
        assert client.get("/api/priorauth/status/").status_code == 403

    def test_only_the_sessions_own_requests(self, client, session, patient, doctor, rule):
        other_patient = Patient.objects.create(
            first_name="Meera", last_name="Iyer", contact_number="9111111111",
            dob=datetime.date(1985, 1, 1), identity_verified=True,
        )
        InsurancePolicy.objects.create(patient=other_patient, policy_number="BS-2",
                                       provider_name="BlueShield", plan="Premium PPO",
                                       coverage_details="")
        mine = TreatmentOrder.objects.create(patient=patient, ordering_doctor=doctor,
                                             order_type="imaging", cpt_code="70551")
        theirs = TreatmentOrder.objects.create(patient=other_patient, ordering_doctor=doctor,
                                               order_type="imaging", cpt_code="70551")
        from priorauth import services
        services.initiate_authorization(mine)
        services.initiate_authorization(theirs)

        response = client.get("/api/priorauth/status/", headers={"X-Session-Token": session["token"]})
        body = response.json()
        assert len(body) == 1
        assert body[0]["order_id"] == mine.id


class TestAuthorizationQueue:
    def test_requires_staff_login(self, client, db):
        assert client.get(STAFF_URL).status_code == 403

    def test_filters_by_status(self, staff_client, patient, doctor, rule):
        from priorauth import services
        order = TreatmentOrder.objects.create(patient=patient, ordering_doctor=doctor,
                                              order_type="imaging", cpt_code="70551")
        auth_request = services.initiate_authorization(order)
        response = staff_client.get(STAFF_URL, {"status": "ready_for_review"})
        assert [r["id"] for r in response.json()] == [auth_request.id]
        assert staff_client.get(STAFF_URL, {"status": "denied"}).json() == []


class TestAuthorizationDetail:
    def test_includes_package_and_messages(self, staff_client, patient, doctor, rule):
        from priorauth import services
        order = TreatmentOrder.objects.create(patient=patient, ordering_doctor=doctor,
                                              order_type="imaging", cpt_code="70551")
        auth_request = services.initiate_authorization(order)
        services.submit(auth_request)

        body = staff_client.get(f"{STAFF_URL}{auth_request.id}/").json()
        assert body["package"]["codes"]["cpt_code"] == "70551"
        assert len(body["messages"]) == 1
        assert body["messages"][0]["direction"] == "outbound"
        assert [e["status"] for e in body["status_history"]] == [
            "detected", "gathering_evidence", "ready_for_review", "submitted",
        ]

    def test_unknown_request_is_404(self, staff_client):
        assert staff_client.get(f"{STAFF_URL}99999/").status_code == 404


class TestStagedTasks:
    def test_lists_only_priorauth_sourced_open_alerts(self, staff_client, patient):
        EscalationAlert.objects.create(patient=patient, source_agent="priorauth",
                                       category="other", priority="medium", summary="needs review")
        EscalationAlert.objects.create(patient=patient, source_agent="refills",
                                       category="controlled_substance", priority="high", summary="x")
        body = staff_client.get(f"{STAFF_URL}tasks/").json()
        assert len(body) == 1
        assert body[0]["summary"] == "needs review"

    def test_all_filter_includes_acknowledged(self, staff_client, patient):
        EscalationAlert.objects.create(patient=patient, source_agent="priorauth",
                                       category="other", priority="medium", summary="x",
                                       status="acknowledged")
        assert staff_client.get(f"{STAFF_URL}tasks/").json() == []  # open-only default
        assert len(staff_client.get(f"{STAFF_URL}tasks/", {"status": "all"}).json()) == 1


class TestSimulatorControl:
    def test_requires_debug(self, staff_client, patient, doctor, rule, settings):
        settings.DEBUG = False
        from priorauth import services
        order = TreatmentOrder.objects.create(patient=patient, ordering_doctor=doctor,
                                              order_type="imaging", cpt_code="70551")
        auth_request = services.initiate_authorization(order)
        response = staff_client.post(f"{STAFF_URL}{auth_request.id}/simulate/",
                                     {"status": "approved"}, content_type="application/json")
        assert response.status_code == 403

    def test_invalid_status_is_400(self, staff_client, patient, doctor, rule, settings):
        # pytest-django forces DEBUG=False by default (same reason
        # registration's DEV_MASTER_OTP tests need override_settings) — the
        # simulator is only reachable in DEBUG, so tests that exercise it
        # opt back in explicitly.
        settings.DEBUG = True
        from priorauth import services
        order = TreatmentOrder.objects.create(patient=patient, ordering_doctor=doctor,
                                              order_type="imaging", cpt_code="70551")
        auth_request = services.initiate_authorization(order)
        response = staff_client.post(f"{STAFF_URL}{auth_request.id}/simulate/",
                                     {"status": "bogus"}, content_type="application/json")
        assert response.status_code == 400

    def test_forces_the_next_poll_response(self, staff_client, patient, doctor, rule, settings):
        settings.DEBUG = True
        from priorauth import services
        order = TreatmentOrder.objects.create(patient=patient, ordering_doctor=doctor,
                                              order_type="imaging", cpt_code="70551")
        auth_request = services.initiate_authorization(order)
        services.submit(auth_request)

        staff_client.post(f"{STAFF_URL}{auth_request.id}/simulate/",
                          {"status": "denied", "denial_reason": "test reason"},
                          content_type="application/json")
        poll = staff_client.post(f"{STAFF_URL}{auth_request.id}/poll/")
        assert poll.json()["status"] == "denied"
        assert poll.json()["denial_reason"] == "test reason"
        SimulatedPayerGateway.clear_forced()


class TestFullLifecycleAgainstTheSimulator:
    """Mirrors Phase 5's manual E2E: order -> detected -> package -> submit
    -> info requested -> auto-answer -> approved."""

    def test_order_to_approved(self, staff_client, patient, doctor, rule, settings):
        settings.DEBUG = True  # the simulator control endpoint is DEBUG-only
        IntakeSummary.objects.create(
            patient=patient, clinical_profile={"allergies": ["contrast dye"]}, summary_text="",
        )
        create = post_json(staff_client, ORDERS_URL, {
            "patient_id": patient.id, "doctor_id": doctor.id, "order_type": "imaging",
            "cpt_code": "70551",
        }).json()
        assert create["authorization_required"] is True
        rid = create["request_id"]
        assert create["status"] == "ready_for_review"

        # package was actually built
        detail = staff_client.get(f"{STAFF_URL}{rid}/").json()
        assert detail["package"]["codes"]["cpt_code"] == "70551"

        # submit
        submitted = staff_client.post(f"{STAFF_URL}{rid}/submit/").json()
        assert submitted["status"] == "submitted"
        assert submitted["external_reference"]

        # payer asks for something we DON'T have on file -> staged, not resubmitted
        staff_client.post(f"{STAFF_URL}{rid}/simulate/",
                          {"status": "info_requested", "requested_items": ["imaging_reports"]},
                          content_type="application/json")
        after_info = staff_client.post(f"{STAFF_URL}{rid}/poll/").json()
        assert after_info["status"] == "info_requested"
        assert EscalationAlert.objects.filter(source_agent="priorauth").exists()

        # payer approves anyway (simulated) -> final decision
        staff_client.post(f"{STAFF_URL}{rid}/simulate/",
                          {"status": "approved"}, content_type="application/json")
        approved = staff_client.post(f"{STAFF_URL}{rid}/poll/").json()
        assert approved["status"] == "approved"
        assert EventLog.objects.filter(name="priorauth.approved").exists()

        # patient can see the final status too
        token = signing.dumps(
            {"conversation_id": Conversation.objects.create(
                channel="web", started_at=timezone.now(), patient=patient).id},
            salt=SESSION_SALT,
        )
        mine = staff_client.get("/api/priorauth/status/", headers={"X-Session-Token": token}).json()
        assert mine[0]["status"] == "approved"
        SimulatedPayerGateway.clear_forced()


class TestReferralAuthorizations:
    def test_lists_requests_linked_to_the_referral(self, staff_client, patient, doctor, rule):
        from priorauth import services
        from referrals.models import Referral
        referral = Referral.objects.create(patient=patient, referring_doctor=doctor,
                                           specialty_needed="Orthopedics", reason="knee pain",
                                           urgency="routine", status="visit_completed")
        linked = TreatmentOrder.objects.create(patient=patient, ordering_doctor=doctor,
                                               order_type="imaging", cpt_code="70551",
                                               referral=referral)
        unlinked = TreatmentOrder.objects.create(patient=patient, ordering_doctor=doctor,
                                                 order_type="imaging", cpt_code="70552")
        linked_request = services.initiate_authorization(linked)
        services.initiate_authorization(unlinked)

        response = staff_client.get(f"/api/priorauth/for-referral/{referral.id}/")
        assert [r["id"] for r in response.json()] == [linked_request.id]

    def test_requires_staff_login(self, client, patient, doctor):
        from referrals.models import Referral
        referral = Referral.objects.create(patient=patient, referring_doctor=doctor,
                                           specialty_needed="Orthopedics", reason="x",
                                           urgency="routine", status="created")
        assert client.get(f"/api/priorauth/for-referral/{referral.id}/").status_code == 403


class TestSuggestAppeal:
    def test_refuses_when_not_denied(self, staff_client, patient, doctor, rule):
        from priorauth import services
        order = TreatmentOrder.objects.create(patient=patient, ordering_doctor=doctor,
                                              order_type="imaging", cpt_code="70551")
        auth_request = services.initiate_authorization(order)
        response = staff_client.post(f"{STAFF_URL}{auth_request.id}/suggest-appeal/")
        assert response.status_code == 400

    def test_returns_a_suggestion_when_denied(self, staff_client, patient, doctor, rule):
        from unittest.mock import patch

        from priorauth import services
        order = TreatmentOrder.objects.create(patient=patient, ordering_doctor=doctor,
                                              order_type="imaging", cpt_code="70551")
        auth_request = services.initiate_authorization(order)
        services.submit(auth_request)
        SimulatedPayerGateway.force_response(auth_request.id, "denied", denial_reason="x")
        services.poll_status(auth_request)

        with patch("priorauth.ai.call_tool", return_value={
            "should_appeal": True, "recommendation": "worth appealing", "draft_argument": "text",
        }):
            response = staff_client.post(f"{STAFF_URL}{auth_request.id}/suggest-appeal/")
        assert response.status_code == 200
        assert response.json()["should_appeal"] is True
        SimulatedPayerGateway.clear_forced()


class TestAnalytics:
    ANALYTICS_URL = f"{STAFF_URL}analytics/"

    def test_requires_staff_login(self, client, db):
        assert client.get(self.ANALYTICS_URL).status_code == 403

    def test_approval_rate_and_denial_reasons(self, staff_client, patient, doctor, rule):
        from priorauth import services

        def make(cpt):
            order = TreatmentOrder.objects.create(patient=patient, ordering_doctor=doctor,
                                                  order_type="imaging", cpt_code=cpt)
            return services.initiate_authorization(order)

        approved = make("70551")
        services.submit(approved)
        SimulatedPayerGateway.force_response(approved.id, "approved")
        services.poll_status(approved)

        denied_a = make("70552")
        services.submit(denied_a)
        SimulatedPayerGateway.force_response(denied_a.id, "denied", denial_reason="no prior conservative therapy")
        services.poll_status(denied_a)

        denied_b = make("70553")
        services.submit(denied_b)
        SimulatedPayerGateway.force_response(denied_b.id, "denied", denial_reason="no prior conservative therapy")
        services.poll_status(denied_b)

        make("99999")  # never matches any rule -> no request at all, doesn't count
        SimulatedPayerGateway.clear_forced()

        body = staff_client.get(self.ANALYTICS_URL).json()
        assert body["requests"] == {"total": 3, "decided": 3, "approved": 1, "denied": 2}
        assert body["approval_rate"] == round(1 / 3, 3)
        assert body["denial_reasons"] == {"no prior conservative therapy": 2}

    def test_no_reason_denial_is_labeled(self, staff_client, patient, doctor, rule):
        from priorauth import services
        order = TreatmentOrder.objects.create(patient=patient, ordering_doctor=doctor,
                                              order_type="imaging", cpt_code="70551")
        auth_request = services.initiate_authorization(order)
        services.submit(auth_request)
        SimulatedPayerGateway.force_response(auth_request.id, "denied")  # no denial_reason given
        services.poll_status(auth_request)
        SimulatedPayerGateway.clear_forced()

        body = staff_client.get(self.ANALYTICS_URL).json()
        assert body["denial_reasons"] == {"(no reason given)": 1}

    def test_avg_seconds_in_status(self, staff_client, patient, doctor, rule):
        auth_request = AuthorizationRequest.objects.create(
            order=TreatmentOrder.objects.create(patient=patient, ordering_doctor=doctor,
                                                order_type="imaging", cpt_code="70551"),
            policy=InsurancePolicy.objects.filter(patient=patient).first(),
            matched_rule=rule, status="submitted",
            status_history=[
                {"status": "detected", "at": "2026-01-01T00:00:00+00:00"},
                {"status": "gathering_evidence", "at": "2026-01-01T00:00:10+00:00"},
                {"status": "ready_for_review", "at": "2026-01-01T00:00:30+00:00"},
                {"status": "submitted", "at": "2026-01-01T00:01:30+00:00"},
            ],
        )
        body = staff_client.get(self.ANALYTICS_URL).json()
        assert body["avg_seconds_in_status"]["detected"] == 10.0
        assert body["avg_seconds_in_status"]["gathering_evidence"] == 20.0
        assert body["avg_seconds_in_status"]["ready_for_review"] == 60.0
        assert "submitted" not in body["avg_seconds_in_status"]  # no next entry yet
        assert auth_request.id  # fixture used


class TestGenericCRUD:
    def test_payer_rule_crud_list(self, client, rule):
        response = client.get("/api/payerrule")
        assert response.status_code == 200
        assert any(r["id"] == rule.id for r in response.json())
