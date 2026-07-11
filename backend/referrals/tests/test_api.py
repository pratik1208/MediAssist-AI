"""Referral API — auth, CRUD, and a full lifecycle over HTTP (Phase 3 exit:
drive created -> closed end to end, the same steps a curl session would run).
"""

import datetime

import pytest
from django.contrib.auth import get_user_model
from django.core import signing
from django.utils import timezone

from core.models import Conversation, Doctor, EventLog, Patient, Specialty
from core.sessions import SESSION_SALT
from referrals.models import ConsultationReport, Referral, Specialist

REFERRALS_URL = "/api/referrals/"
STAFF_REFERRALS_URL = "/api/staff/referrals/"


@pytest.fixture
def doctor(db):
    return Doctor.objects.create(name="Dr. Asha Mehta", specialty="General Medicine")


@pytest.fixture
def internal_doctor(db):
    return Doctor.objects.create(name="Dr. Rohan Kulkarni", specialty="Cardiology")


@pytest.fixture
def specialist(db, internal_doctor):
    return Specialist.objects.create(
        name="Dr. Rohan Kulkarni", specialty=Specialty.CARDIOLOGY,
        address={"city": "Pune", "postal_code": "411005"},
        accepting_new_patients=True, contact_channel="e_referral",
        internal_doctor=internal_doctor,
    )


@pytest.fixture
def patient(db):
    return Patient.objects.create(
        first_name="Rahul", last_name="Sharma", contact_number="9876543210",
        dob=datetime.date(1990, 5, 17), identity_verified=True,
        address={"city": "Pune", "zip": "411005"},
    )


@pytest.fixture
def session(db, patient):
    conversation = Conversation.objects.create(
        channel="web", started_at=timezone.now(), patient=patient,
    )
    token = signing.dumps({"conversation_id": conversation.id}, salt=SESSION_SALT)
    return {"token": token, "patient": patient}


@pytest.fixture
def staff_client(client, db):
    staff = get_user_model().objects.create_user("coordinator", password="x", is_staff=True)
    client.force_login(staff)
    return client


def post_json(client, url, data, token=None):
    headers = {"X-Session-Token": token} if token else {}
    return client.post(url, data, content_type="application/json", headers=headers)


class TestCreateReferral:
    def test_requires_staff_login(self, client, db):
        assert client.post(REFERRALS_URL, {}, content_type="application/json").status_code == 403

    def test_missing_fields_is_a_clear_400(self, staff_client, patient, doctor):
        response = post_json(staff_client, REFERRALS_URL, {"patient_id": patient.id})
        assert response.status_code == 400
        assert "doctor_id" in response.json()["error"]

    def test_unknown_patient_is_404(self, staff_client, doctor):
        response = post_json(staff_client, REFERRALS_URL, {
            "patient_id": 99999, "doctor_id": doctor.id,
            "specialty": Specialty.CARDIOLOGY, "reason": "chest pain", "urgency": "routine",
        })
        assert response.status_code == 404

    def test_one_click_creation(self, staff_client, patient, doctor):
        response = post_json(staff_client, REFERRALS_URL, {
            "patient_id": patient.id, "doctor_id": doctor.id,
            "specialty": Specialty.CARDIOLOGY, "reason": "chest pain on exertion",
            "urgency": "routine",
        })
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "created"
        assert EventLog.objects.filter(name="referral.created",
                                       payload__referral_id=body["id"]).exists()


class TestReferralQueue:
    def test_requires_staff_login(self, client, db):
        assert client.get(STAFF_REFERRALS_URL).status_code == 403

    def test_lists_with_stalled_flag(self, staff_client, patient, doctor):
        normal = Referral.objects.create(
            patient=patient, referring_doctor=doctor, specialty_needed=Specialty.CARDIOLOGY,
            reason="r", urgency="routine", status="accepted",
        )
        stalled = Referral.objects.create(
            patient=patient, referring_doctor=doctor, specialty_needed=Specialty.CARDIOLOGY,
            reason="r", urgency="routine", status="stalled",
        )
        body = {item["id"]: item for item in staff_client.get(STAFF_REFERRALS_URL).json()}
        assert body[normal.id]["stalled"] is False
        assert body[stalled.id]["stalled"] is True

    def test_filters_by_status(self, staff_client, patient, doctor):
        Referral.objects.create(patient=patient, referring_doctor=doctor,
                                specialty_needed=Specialty.CARDIOLOGY, reason="r",
                                urgency="routine", status="created")
        Referral.objects.create(patient=patient, referring_doctor=doctor,
                                specialty_needed=Specialty.CARDIOLOGY, reason="r",
                                urgency="routine", status="closed")
        response = staff_client.get(STAFF_REFERRALS_URL, {"status": "closed"})
        assert [r["status"] for r in response.json()] == ["closed"]


class TestPatientReferrals:
    def test_requires_session_token(self, client, db):
        assert client.get("/api/referrals/status/").status_code == 403

    def test_only_the_sessions_own_referrals(self, client, session, patient, doctor):
        other_patient = Patient.objects.create(
            first_name="Meera", last_name="Iyer", contact_number="9111111111",
            dob=datetime.date(1985, 1, 1), identity_verified=True,
        )
        mine = Referral.objects.create(patient=patient, referring_doctor=doctor,
                                       specialty_needed=Specialty.CARDIOLOGY, reason="r",
                                       urgency="routine", status="created")
        Referral.objects.create(patient=other_patient, referring_doctor=doctor,
                                specialty_needed=Specialty.CARDIOLOGY, reason="r",
                                urgency="routine", status="created")
        response = client.get("/api/referrals/status/", headers={"X-Session-Token": session["token"]})
        assert [r["id"] for r in response.json()] == [mine.id]


class TestFullLifecycle:
    """Phase 3 exit criterion: drive a referral from created to closed."""

    def test_created_to_closed(self, staff_client, client, session, patient, doctor, specialist):
        # 1. physician creates (FR-F1)
        created = post_json(staff_client, REFERRALS_URL, {
            "patient_id": patient.id, "doctor_id": doctor.id,
            "specialty": Specialty.CARDIOLOGY, "reason": "chest pain on exertion",
            "urgency": "routine",
        }).json()
        referral_id = created["id"]
        assert created["status"] == "created"

        # 2. care coordinator sees ranked specialist candidates
        candidates = staff_client.get(f"{STAFF_REFERRALS_URL}{referral_id}/candidates/").json()
        assert candidates[0]["id"] == specialist.id

        # 3. specialist-side (simulated): accept
        accepted = staff_client.post(
            f"{STAFF_REFERRALS_URL}{referral_id}/accept/",
            {"specialist_id": specialist.id}, content_type="application/json",
        ).json()
        assert accepted == {"status": "accepted", "specialist": specialist.name}

        # 4. book the specialist visit (FR-F5, reuses Agent 1's calendar)
        start = (timezone.now() + datetime.timedelta(days=1)).replace(microsecond=0)
        end = start + datetime.timedelta(minutes=30)
        booked = staff_client.post(
            f"{STAFF_REFERRALS_URL}{referral_id}/book/",
            {"start": start.isoformat(), "end": end.isoformat()},
            content_type="application/json",
        ).json()
        assert booked["status"] == "appointment_scheduled"
        assert booked["appointment_id"]

        # 5. patient confirms
        confirmed = client.post(
            f"{REFERRALS_URL}{referral_id}/confirm/", {}, content_type="application/json",
            headers={"X-Session-Token": session["token"]},
        ).json()
        assert confirmed == {"status": "patient_confirmed"}

        # 6. specialist-side (simulated): visit completed
        visited = staff_client.post(f"{STAFF_REFERRALS_URL}{referral_id}/visit-completed/").json()
        assert visited == {"status": "visit_completed"}

        # 7. specialist-side (simulated): upload consultation report -> closes the loop (FR-F10)
        closed = staff_client.post(
            f"{STAFF_REFERRALS_URL}{referral_id}/report/",
            {"diagnosis": "Stable angina", "treatment_plan": "atenolol 25mg daily",
             "medications": ["atenolol 25mg"], "followup_recommendations": ["repeat ECG in 3 months"]},
            content_type="application/json",
        ).json()
        assert closed["status"] == "closed"
        report = ConsultationReport.objects.get(id=closed["report_id"])
        assert report.diagnosis == "Stable angina"

        # full timeline reflects every step in order
        timeline = staff_client.get(f"{STAFF_REFERRALS_URL}{referral_id}/").json()
        assert [entry["status"] for entry in timeline["status_history"]] == [
            "created", "accepted", "appointment_scheduled", "patient_confirmed",
            "visit_completed", "report_received", "closed",
        ]

        # and the patient can see their own referral reflects the same status
        mine = client.get("/api/referrals/status/",
                          headers={"X-Session-Token": session["token"]}).json()
        assert mine[0]["status"] == "closed"
        assert mine[0]["specialist"] == specialist.name


class TestAcceptReferral:
    def test_unknown_specialist_is_404(self, staff_client, patient, doctor):
        referral = Referral.objects.create(patient=patient, referring_doctor=doctor,
                                           specialty_needed=Specialty.CARDIOLOGY, reason="r",
                                           urgency="routine", status="created")
        response = staff_client.post(f"{STAFF_REFERRALS_URL}{referral.id}/accept/",
                                     {"specialist_id": 99999}, content_type="application/json")
        assert response.status_code == 404

    def test_wrong_starting_status_is_400(self, staff_client, patient, doctor, specialist):
        referral = Referral.objects.create(patient=patient, referring_doctor=doctor,
                                           specialty_needed=Specialty.CARDIOLOGY, reason="r",
                                           urgency="routine", status="closed")
        response = staff_client.post(f"{STAFF_REFERRALS_URL}{referral.id}/accept/",
                                     {"specialist_id": specialist.id}, content_type="application/json")
        assert response.status_code == 400

    def test_draft_referral_refuses_accept_without_a_doctor_id(
        self, staff_client, patient, specialist,
    ):
        # Phase 6: a triage-originated draft has no referring_doctor yet.
        draft = Referral.objects.create(patient=patient, referring_doctor=None,
                                        specialty_needed=Specialty.CARDIOLOGY, reason="r",
                                        urgency="routine", status="created")
        response = staff_client.post(f"{STAFF_REFERRALS_URL}{draft.id}/accept/",
                                     {"specialist_id": specialist.id}, content_type="application/json")
        assert response.status_code == 400
        assert "referring physician" in response.json()["error"]

    def test_draft_referral_accepted_once_a_doctor_confirms(
        self, staff_client, patient, doctor, specialist,
    ):
        draft = Referral.objects.create(patient=patient, referring_doctor=None,
                                        specialty_needed=Specialty.CARDIOLOGY, reason="r",
                                        urgency="routine", status="created")
        response = staff_client.post(
            f"{STAFF_REFERRALS_URL}{draft.id}/accept/",
            {"specialist_id": specialist.id, "doctor_id": doctor.id},
            content_type="application/json",
        )
        assert response.status_code == 200
        draft.refresh_from_db()
        assert draft.referring_doctor_id == doctor.id
        assert draft.status == "accepted"


class TestResumeReferral:
    def test_resumes_and_then_the_normal_action_works(self, staff_client, patient, doctor, specialist):
        referral = Referral.objects.create(
            patient=patient, referring_doctor=doctor, specialist=specialist,
            specialty_needed=Specialty.CARDIOLOGY, reason="r", urgency="routine",
            status="stalled",
            status_history=[{"status": "created", "at": "1"}, {"status": "accepted", "at": "2"},
                            {"status": "stalled", "at": "3"}],
        )
        resumed = staff_client.post(f"{STAFF_REFERRALS_URL}{referral.id}/resume/")
        assert resumed.status_code == 200
        assert resumed.json() == {"status": "accepted"}

    def test_refuses_when_not_stalled(self, staff_client, patient, doctor):
        referral = Referral.objects.create(patient=patient, referring_doctor=doctor,
                                           specialty_needed=Specialty.CARDIOLOGY, reason="r",
                                           urgency="routine", status="accepted")
        response = staff_client.post(f"{STAFF_REFERRALS_URL}{referral.id}/resume/")
        assert response.status_code == 400


class TestBookReferralVisit:
    def test_missing_start_end_is_400(self, staff_client, patient, doctor, specialist):
        referral = Referral.objects.create(patient=patient, referring_doctor=doctor,
                                           specialist=specialist, specialty_needed=Specialty.CARDIOLOGY,
                                           reason="r", urgency="routine", status="accepted")
        assert staff_client.post(f"{STAFF_REFERRALS_URL}{referral.id}/book/", {},
                                 content_type="application/json").status_code == 400

    def test_utc_offset_input_is_converted_to_local_time_not_just_stripped(
        self, staff_client, patient, doctor, specialist,
    ):
        # Regression: TIME_ZONE is Asia/Kolkata (UTC+5:30). A client sending
        # a UTC-offset ISO string must land at the correct LOCAL wall-clock
        # time on the Appointment, not have its offset silently chopped off
        # (which would book 5.5 hours away from what was actually requested).
        referral = Referral.objects.create(patient=patient, referring_doctor=doctor,
                                           specialist=specialist, specialty_needed=Specialty.CARDIOLOGY,
                                           reason="r", urgency="routine", status="accepted")
        start_utc = timezone.now().astimezone(datetime.timezone.utc).replace(
            microsecond=0) + datetime.timedelta(days=1)
        end_utc = start_utc + datetime.timedelta(minutes=30)

        response = staff_client.post(
            f"{STAFF_REFERRALS_URL}{referral.id}/book/",
            {"start": start_utc.isoformat(), "end": end_utc.isoformat()},
            content_type="application/json",
        )
        assert response.status_code == 200
        referral.refresh_from_db()
        # Django reads DateTimeField values back as UTC-aware when USE_TZ is
        # on, regardless of what was stored — compare in local time on both
        # sides rather than assuming the naive value round-trips as-is.
        assert timezone.localtime(referral.appointment.start_time) == timezone.localtime(start_utc)

    def test_no_specialist_matched_yet_is_400(self, staff_client, patient, doctor):
        referral = Referral.objects.create(patient=patient, referring_doctor=doctor,
                                           specialty_needed=Specialty.CARDIOLOGY, reason="r",
                                           urgency="routine", status="accepted")
        start = timezone.now() + datetime.timedelta(days=1)
        response = staff_client.post(
            f"{STAFF_REFERRALS_URL}{referral.id}/book/",
            {"start": start.isoformat(), "end": (start + datetime.timedelta(minutes=30)).isoformat()},
            content_type="application/json",
        )
        assert response.status_code == 400


class TestUploadConsultationReport:
    def test_refuses_before_visit_completed(self, staff_client, patient, doctor):
        referral = Referral.objects.create(patient=patient, referring_doctor=doctor,
                                           specialty_needed=Specialty.CARDIOLOGY, reason="r",
                                           urgency="routine", status="appointment_scheduled")
        response = staff_client.post(f"{STAFF_REFERRALS_URL}{referral.id}/report/",
                                     {"diagnosis": "x"}, content_type="application/json")
        assert response.status_code == 400

    def test_file_upload_extracts_and_closes_the_loop(self, staff_client, patient, doctor,
                                                       settings, tmp_path):
        from unittest.mock import patch

        from django.core.files.uploadedfile import SimpleUploadedFile
        settings.MEDIA_ROOT = tmp_path
        referral = Referral.objects.create(patient=patient, referring_doctor=doctor,
                                           specialty_needed=Specialty.CARDIOLOGY, reason="r",
                                           urgency="routine", status="visit_completed")
        with patch("referrals.ai.call_tool", return_value={
            "diagnosis": "Stable angina", "treatment_plan": "atenolol 25mg daily",
            "medications": ["atenolol 25mg"], "followup_recommendations": ["repeat ECG in 3 months"],
            "legible": True,
        }):
            response = staff_client.post(
                f"{STAFF_REFERRALS_URL}{referral.id}/report/",
                {"file": SimpleUploadedFile("report.png", b"png-bytes", "image/png")},
            )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "closed"
        report = ConsultationReport.objects.get(id=body["report_id"])
        assert report.diagnosis == "Stable angina"

    def test_illegible_upload_returns_422_and_does_not_close(self, staff_client, patient, doctor,
                                                             settings, tmp_path):
        from unittest.mock import patch

        from django.core.files.uploadedfile import SimpleUploadedFile
        settings.MEDIA_ROOT = tmp_path
        referral = Referral.objects.create(patient=patient, referring_doctor=doctor,
                                           specialty_needed=Specialty.CARDIOLOGY, reason="r",
                                           urgency="routine", status="visit_completed")
        with patch("referrals.ai.call_tool", return_value={
            "diagnosis": None, "treatment_plan": None, "medications": None,
            "followup_recommendations": None, "legible": False,
        }):
            response = staff_client.post(
                f"{STAFF_REFERRALS_URL}{referral.id}/report/",
                {"file": SimpleUploadedFile("report.png", b"png-bytes", "image/png")},
            )
        assert response.status_code == 422
        referral.refresh_from_db()
        assert referral.status == "visit_completed"  # unchanged


class TestGenericCRUD:
    def test_specialist_crud_list(self, client, specialist):
        response = client.get("/api/specialist")
        assert response.status_code == 200
        assert any(s["id"] == specialist.id for s in response.json())
