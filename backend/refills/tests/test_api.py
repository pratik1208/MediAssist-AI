"""Refill API — full lifecycle over HTTP, plus auth and CRUD (Phase 3)."""

import datetime

import pytest
from django.contrib.auth import get_user_model
from django.core import signing
from django.utils import timezone

from core.models import Conversation, EventLog, Patient
from core.sessions import SESSION_SALT
from refills.models import RefillRequest
from refills.tests.test_eligibility import add_lab, make_rx
from triage.models import EscalationAlert

REQUESTS_URL = "/api/refills/requests/"


@pytest.fixture
def doctor(db):
    from core.models import Doctor
    return Doctor.objects.create(name="Dr. Asha Mehta", specialty="General Medicine")


@pytest.fixture
def pharmacy(db):
    from refills.models import Pharmacy
    return Pharmacy.objects.create(name="Apollo Pharmacy", phone="020-0000")


@pytest.fixture
def session(db):
    patient = Patient.objects.create(
        first_name="Rahul", last_name="Sharma", contact_number="9876543210",
        dob=datetime.date(1990, 5, 17), identity_verified=True,
    )
    conversation = Conversation.objects.create(
        channel="web", started_at=timezone.now(), patient=patient,
    )
    token = signing.dumps({"conversation_id": conversation.id}, salt=SESSION_SALT)
    return {"token": token, "patient": patient}


@pytest.fixture
def staff_client(client, db):
    staff = get_user_model().objects.create_user("physician", password="x", is_staff=True)
    client.force_login(staff)
    return client


def post_json(client, url, data, token):
    return client.post(url, data, content_type="application/json",
                       headers={"X-Session-Token": token})


class TestAuth:
    def test_patient_endpoints_require_session_token(self, client, db):
        assert client.post(REQUESTS_URL, {}, content_type="application/json").status_code == 403
        assert client.get("/api/refills/prescriptions/").status_code == 403

    def test_patient_endpoints_require_verified_identity(self, client, session):
        session["patient"].identity_verified = False
        session["patient"].save(update_fields=["identity_verified"])
        response = post_json(client, REQUESTS_URL, {"prescription_id": 1}, session["token"])
        assert response.status_code == 403
        assert "identity" in response.json()["error"]

    def test_staff_endpoints_require_staff_login(self, client, db):
        assert client.get("/api/staff/refills/queue/").status_code == 403
        assert client.post("/api/staff/refills/1/approve/").status_code == 403


class TestPatientPrescriptions:
    def test_lists_only_active_prescriptions(self, client, session, doctor):
        make_rx(session["patient"], doctor)
        make_rx(session["patient"], doctor, medication_name="Losartan", status="expired")
        body = client.get("/api/refills/prescriptions/",
                          headers={"X-Session-Token": session["token"]}).json()
        assert [p["medication"] for p in body] == ["Amlodipine 5 mg"]
        assert body[0]["refills_remaining"] == 4


class TestCreateRefillRequest:
    def test_eligible_request_lands_in_the_queue(self, client, session, doctor, pharmacy):
        rx = make_rx(session["patient"], doctor)
        response = post_json(client, REQUESTS_URL,
                             {"prescription_id": rx.id, "pharmacy_id": pharmacy.id},
                             session["token"])
        assert response.status_code == 201
        assert response.json()["status"] == "pending_approval"
        assert response.json()["is_renewal"] is False

    def test_ineligible_request_returns_409_paused(self, client, session, doctor, pharmacy):
        rx = make_rx(session["patient"], doctor, followup_required=True)
        response = post_json(client, REQUESTS_URL,
                             {"prescription_id": rx.id, "pharmacy_id": pharmacy.id},
                             session["token"])
        assert response.status_code == 409
        body = response.json()
        assert body["code"] == "paused"
        assert "follow-up visit" in body["reason"]

    def test_zero_refills_flags_renewal(self, client, session, doctor, pharmacy):
        rx = make_rx(session["patient"], doctor, refills_allowed=2, refills_used=2)
        response = post_json(client, REQUESTS_URL,
                             {"prescription_id": rx.id, "pharmacy_id": pharmacy.id},
                             session["token"])
        assert response.status_code == 201
        assert response.json()["is_renewal"] is True

    def test_controlled_substance_escalates_but_queues_for_human(self, client, session, doctor, pharmacy):
        rx = make_rx(session["patient"], doctor, medication_name="Alprazolam",
                     is_controlled_substance=True)
        response = post_json(client, REQUESTS_URL,
                             {"prescription_id": rx.id, "pharmacy_id": pharmacy.id},
                             session["token"])
        assert response.status_code == 201
        assert response.json()["status"] == "pending_approval"
        assert EscalationAlert.objects.filter(
            patient=session["patient"], category="controlled_substance").exists()

    def test_someone_elses_prescription_is_invisible(self, client, session, doctor, pharmacy):
        other = Patient.objects.create(first_name="Meera", last_name="Iyer",
                                       contact_number="9111111111",
                                       dob=datetime.date(1985, 1, 1))
        rx = make_rx(other, doctor)
        response = post_json(client, REQUESTS_URL,
                             {"prescription_id": rx.id, "pharmacy_id": pharmacy.id},
                             session["token"])
        assert response.status_code == 404

    def test_missing_pharmacy_is_a_clear_400(self, client, session, doctor):
        rx = make_rx(session["patient"], doctor)
        response = post_json(client, REQUESTS_URL, {"prescription_id": rx.id},
                             session["token"])
        assert response.status_code == 400
        assert "pharmacy" in response.json()["error"]

    def test_preferred_pharmacy_name_resolves(self, client, session, doctor, pharmacy):
        session["patient"].preferred_pharmacy = "Apollo"
        session["patient"].save(update_fields=["preferred_pharmacy"])
        rx = make_rx(session["patient"], doctor)
        response = post_json(client, REQUESTS_URL, {"prescription_id": rx.id},
                             session["token"])
        assert response.status_code == 201

    def test_duplicate_request_while_pending_is_refused(self, client, session, doctor, pharmacy):
        # Regression: a patient tapping "Request refill" twice (or checking
        # back and retrying) must not pile up a second row in the physician
        # queue for the same prescription.
        rx = make_rx(session["patient"], doctor)
        first = post_json(client, REQUESTS_URL,
                          {"prescription_id": rx.id, "pharmacy_id": pharmacy.id},
                          session["token"])
        assert first.status_code == 201
        second = post_json(client, REQUESTS_URL,
                           {"prescription_id": rx.id, "pharmacy_id": pharmacy.id},
                           session["token"])
        assert second.status_code == 409
        body = second.json()
        assert body["code"] == "already_requested"
        assert body["id"] == first.json()["id"]
        assert RefillRequest.objects.filter(prescription=rx).count() == 1

    def test_duplicate_request_while_visit_required_is_refused(
        self, client, session, doctor, pharmacy,
    ):
        from refills import services
        rx = make_rx(session["patient"], doctor)
        first = post_json(client, REQUESTS_URL,
                          {"prescription_id": rx.id, "pharmacy_id": pharmacy.id},
                          session["token"]).json()
        request = RefillRequest.objects.get(id=first["id"])
        services.request_visit(request, doctor)

        second = post_json(client, REQUESTS_URL,
                           {"prescription_id": rx.id, "pharmacy_id": pharmacy.id},
                           session["token"])
        assert second.status_code == 409
        assert second.json()["code"] == "already_requested"

    def test_new_request_allowed_after_rejection_or_pause(self, client, session, doctor, pharmacy):
        # Closed outcomes (rejected) and recoverable ones (paused, once the
        # patient has addressed the reason) must NOT block trying again.
        from refills import services
        rx = make_rx(session["patient"], doctor)
        first = post_json(client, REQUESTS_URL,
                          {"prescription_id": rx.id, "pharmacy_id": pharmacy.id},
                          session["token"]).json()
        services.reject(RefillRequest.objects.get(id=first["id"]), doctor, "not due yet")

        second = post_json(client, REQUESTS_URL,
                           {"prescription_id": rx.id, "pharmacy_id": pharmacy.id},
                           session["token"])
        assert second.status_code == 201  # rejection doesn't block a fresh attempt

        paused_rx = make_rx(session["patient"], doctor, medication_name="Losartan",
                            followup_required=True)
        paused = post_json(client, REQUESTS_URL,
                           {"prescription_id": paused_rx.id, "pharmacy_id": pharmacy.id},
                           session["token"])
        assert paused.status_code == 409 and paused.json()["code"] == "paused"
        retry = post_json(client, REQUESTS_URL,
                          {"prescription_id": paused_rx.id, "pharmacy_id": pharmacy.id},
                          session["token"])
        assert retry.status_code == 409  # still paused (nothing changed), but not "already_requested"
        assert retry.json()["code"] == "paused"


class TestRequestStatus:
    def test_status_and_pause_reason(self, client, session, doctor, pharmacy):
        rx = make_rx(session["patient"], doctor, followup_required=True)
        created = post_json(client, REQUESTS_URL,
                            {"prescription_id": rx.id, "pharmacy_id": pharmacy.id},
                            session["token"]).json()
        body = client.get(f"{REQUESTS_URL}{created['id']}/",
                          headers={"X-Session-Token": session["token"]}).json()
        assert body["status"] == "paused"
        assert body["status_display"] == "Paused"
        assert "follow-up visit" in body["pause_reason"]

    def test_other_patients_requests_are_invisible(self, client, session, doctor, pharmacy):
        other = Patient.objects.create(first_name="Meera", last_name="Iyer",
                                       contact_number="9111111111",
                                       dob=datetime.date(1985, 1, 1))
        request = RefillRequest.objects.create(
            prescription=make_rx(other, doctor), patient=other, pharmacy=pharmacy)
        response = client.get(f"{REQUESTS_URL}{request.id}/",
                              headers={"X-Session-Token": session["token"]})
        assert response.status_code == 404


class TestPhysicianQueueAndActions:
    def queue_request(self, client, session, doctor, pharmacy, **rx_overrides):
        rx = make_rx(session["patient"], doctor, **rx_overrides)
        created = post_json(client, REQUESTS_URL,
                            {"prescription_id": rx.id, "pharmacy_id": pharmacy.id},
                            session["token"]).json()
        return created["id"]

    def test_queue_shows_pending_with_summaries(self, staff_client, session, doctor, pharmacy):
        request_id = self.queue_request(staff_client, session, doctor, pharmacy)
        queue = staff_client.get("/api/staff/refills/queue/").json()
        assert [item["id"] for item in queue] == [request_id]
        item = queue[0]
        assert item["patient"] == "R. Sharma"
        assert item["medication"] == "Amlodipine 5 mg"
        assert item["renewal_summary"]["refills_remaining"] == 4
        assert item["actions"] == ["approve", "reject", "request_visit"]

    def test_approve_is_one_click_and_reaches_the_pharmacy(self, staff_client, session, doctor, pharmacy):
        request_id = self.queue_request(staff_client, session, doctor, pharmacy)
        body = staff_client.post(f"/api/staff/refills/{request_id}/approve/").json()
        assert body == {"status": "sent_to_pharmacy"}
        assert EventLog.objects.filter(name="refill.approved").exists()
        # approved requests leave the queue
        assert staff_client.get("/api/staff/refills/queue/").json() == []

    def test_reject_requires_a_reason(self, staff_client, session, doctor, pharmacy):
        request_id = self.queue_request(staff_client, session, doctor, pharmacy)
        assert staff_client.post(f"/api/staff/refills/{request_id}/reject/",
                                 {}, content_type="application/json").status_code == 400
        body = staff_client.post(f"/api/staff/refills/{request_id}/reject/",
                                 {"reason": "BP recheck needed"},
                                 content_type="application/json").json()
        assert body == {"status": "rejected"}

    def test_request_visit_emits_the_scheduling_event(self, staff_client, session, doctor, pharmacy):
        request_id = self.queue_request(staff_client, session, doctor, pharmacy)
        body = staff_client.post(f"/api/staff/refills/{request_id}/request-visit/").json()
        assert body == {"status": "visit_required"}
        event = EventLog.objects.filter(name="refill.visit_required").latest("id")
        assert event.payload["request_id"] == request_id

    def test_decided_requests_refuse_further_actions(self, staff_client, session, doctor, pharmacy):
        request_id = self.queue_request(staff_client, session, doctor, pharmacy)
        staff_client.post(f"/api/staff/refills/{request_id}/approve/")
        response = staff_client.post(f"/api/staff/refills/{request_id}/approve/")
        assert response.status_code == 400
        # A second approve() must never mint a second active prescription.
        from refills.models import Prescription
        rx = RefillRequest.objects.get(id=request_id).prescription
        assert Prescription.objects.filter(
            medication_name=rx.medication_name, patient=session["patient"], status="active",
        ).count() == 1

    def test_service_layer_guards_a_second_decision_even_bypassing_the_view(
        self, session, doctor, pharmacy,
    ):
        # Regression: services.approve() used to trust its caller and had no
        # status check of its own — calling it twice created two active
        # prescriptions for the same medication. The view already guards the
        # common case (must_be_pending); this proves the service itself is
        # now also safe against a caller that skips that check (e.g. a race
        # between two near-simultaneous clicks).
        from refills import services
        from refills.models import Prescription
        rx = make_rx(session["patient"], doctor)
        request = RefillRequest.objects.create(
            prescription=rx, patient=session["patient"], pharmacy=pharmacy,
            status="pending_approval",
        )
        services.approve(request, doctor)
        with pytest.raises(services.RefillRequestNotPending):
            services.approve(request, doctor)
        assert Prescription.objects.filter(
            medication_name=rx.medication_name, patient=session["patient"], status="active",
        ).count() == 1

        request2 = RefillRequest.objects.create(
            prescription=make_rx(session["patient"], doctor, medication_name="Losartan"),
            patient=session["patient"], pharmacy=pharmacy, status="rejected",
        )
        with pytest.raises(services.RefillRequestNotPending):
            services.reject(request2, doctor, "already handled")
        with pytest.raises(services.RefillRequestNotPending):
            services.request_visit(request2, doctor)


class TestGenericCRUD:
    def test_crud_endpoints_list(self, client, db, doctor, pharmacy, session):
        make_rx(session["patient"], doctor)
        assert len(client.get("/api/pharmacy").json()) == 1
        assert len(client.get("/api/prescription").json()) == 1
        assert client.get("/api/refillrequest").json() == []


class TestIdentityStepUp:
    """FR-M2: an unverified session is blocked, verifies through
    registration's OTP endpoints on the SAME session token, then proceeds."""

    def test_otp_step_up_unlocks_refills(self, client, session, doctor, pharmacy):
        from registration.tests.test_services import sent_code

        patient = session["patient"]
        patient.identity_verified = False
        patient.save(update_fields=["identity_verified"])
        rx = make_rx(patient, doctor)

        # blocked before verification
        blocked = post_json(client, REQUESTS_URL,
                            {"prescription_id": rx.id, "pharmacy_id": pharmacy.id},
                            session["token"])
        assert blocked.status_code == 403

        # step up via registration's OTP endpoints, same token
        assert post_json(client, "/api/registration/otp/request",
                         {"channel": "SMS"}, session["token"]).status_code == 202
        verified = post_json(client, "/api/registration/otp/verify",
                             {"code": sent_code(patient)}, session["token"])
        assert verified.json() == {"verified": True}

        # the very same refill call now succeeds
        allowed = post_json(client, REQUESTS_URL,
                            {"prescription_id": rx.id, "pharmacy_id": pharmacy.id},
                            session["token"])
        assert allowed.status_code == 201
