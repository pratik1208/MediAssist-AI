"""Phase 2: registry dispatch (every intent), the auth gate (patient-data
intents queued pre-auth, FAQ allowed, neutral failure messages, resume after
verification), knowledge search relevance on the seeded fixtures, and the
mandatory-escalation categories (always a task, fixed priority)."""

import datetime

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from core.models import Conversation, Patient, SentNotification
from frontdesk import services
from frontdesk.models import IntentRoute, PatientSession, StaffTask

pytestmark = pytest.mark.django_db

DOB = datetime.date(1990, 5, 17)


@pytest.fixture
def patient(db):
    return Patient.objects.create(
        first_name="Rahul", last_name="Sharma", contact_number="9876543210",
        dob=DOB, registration_status="complete",
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


# -- auth gate --------------------------------------------------------------------

class TestAuthGate:
    def test_protected_intent_pre_auth_is_queued_not_routed(self, session):
        result = services.dispatch_intent(session, "refill", {"text": "refill my meds"})
        assert result["status"] == "auth_required"
        session.refresh_from_db()
        assert session.pending_intents == [
            {"intent": "refill", "payload": {"text": "refill my meds"}}]
        assert IntentRoute.objects.count() == 0  # nothing was routed

    def test_faq_allowed_pre_auth(self, session):
        call_command("seed_knowledge")
        result = services.dispatch_intent(session, "faq", {"question": "what are your hours"})
        assert result["status"] == "completed"
        assert "9:00 AM" in result["reply"]

    def test_every_patient_data_intent_is_gated(self, session):
        for intent in ("appointment", "refill", "referral_status",
                       "pa_status", "care_gap", "symptoms"):
            assert services.REGISTRY[intent].requires_auth is True
            assert services.dispatch_intent(session, intent)["status"] == "auth_required"
        assert IntentRoute.objects.count() == 0

    def test_start_authentication_neutral_on_unknown_phone_and_wrong_dob(self, session, patient):
        unknown = services.start_authentication(session, "0000000000", DOB)
        wrong_dob = services.start_authentication(
            session, patient.contact_number, datetime.date(1980, 1, 1))
        assert unknown["ok"] is False and wrong_dob["ok"] is False
        # NFR-2: the two failures must be indistinguishable
        assert unknown["message"] == wrong_dob["message"]
        assert SentNotification.objects.count() == 0  # no OTP went anywhere

    def test_happy_path_sends_otp_then_verifies(self, session, patient):
        started = services.start_authentication(session, patient.contact_number, DOB)
        assert started["ok"] is True
        assert SentNotification.objects.filter(patient=patient).exists()
        # no patient data leaks in the message
        assert patient.first_name not in started["message"]

        with override_settings(DEBUG=True):
            result = services.authenticate_session(session, DOB, "123456")
        assert result["ok"] is True
        session.refresh_from_db()
        assert session.authenticated is True
        assert session.patient == patient

    def test_wrong_otp_keeps_session_anonymous(self, session, patient):
        services.start_authentication(session, patient.contact_number, DOB)
        result = services.authenticate_session(session, DOB, "000000")
        assert result["ok"] is False
        session.refresh_from_db()
        assert session.authenticated is False
        assert session.patient is None

    def test_resume_pending_after_auth(self, session, patient):
        services.dispatch_intent(session, "appointment")
        services.dispatch_intent(session, "care_gap")
        services.start_authentication(session, patient.contact_number, DOB)
        with override_settings(DEBUG=True):
            services.authenticate_session(session, DOB, "123456")

        results = services.resume_pending_intents(session)
        assert len(results) == 2
        assert [r["status"] for r in results] == ["completed", "completed"]
        session.refresh_from_db()
        assert session.pending_intents == []
        assert list(IntentRoute.objects.values_list("intent", flat=True)) == [
            "appointment", "care_gap"]

    def test_resume_does_nothing_while_anonymous(self, session):
        services.dispatch_intent(session, "refill")
        assert services.resume_pending_intents(session) == []
        session.refresh_from_db()
        assert len(session.pending_intents) == 1  # still queued


# -- registry dispatch --------------------------------------------------------------

class TestRegistryDispatch:
    def test_every_intent_has_a_route(self):
        assert set(services.REGISTRY) == {
            "appointment", "refill", "referral_status", "pa_status",
            "care_gap", "symptoms", "faq", "other"}

    def test_dispatch_writes_an_audit_row_per_intent(self, auth_session):
        services.dispatch_intent(auth_session, "appointment")
        services.dispatch_intent(auth_session, "referral_status")
        routes = IntentRoute.objects.order_by("id")
        assert [(r.intent, r.target_agent, r.status) for r in routes] == [
            ("appointment", "scheduling", "completed"),
            ("referral_status", "referrals", "completed"),
        ]

    def test_unknown_intent_falls_back_to_staff_task(self, auth_session):
        result = services.dispatch_intent(auth_session, "teleportation", {"text": "beam me up"})
        assert result["status"] == "escalated"
        task = StaffTask.objects.get()
        assert task.category == "manual_review"
        assert IntentRoute.objects.get().intent == "other"

    def test_handler_crash_escalates_instead_of_raising(self, auth_session, monkeypatch):
        def _boom(session, payload):
            raise RuntimeError("agent down")
        monkeypatch.setitem(
            services.REGISTRY, "appointment",
            services.AgentRoute("scheduling", _boom))
        result = services.dispatch_intent(auth_session, "appointment")
        assert result["status"] == "escalated"
        assert StaffTask.objects.filter(category="manual_review").exists()
        assert IntentRoute.objects.get().status == "escalated"

    def test_appointment_handler_lists_upcoming(self, auth_session):
        from core.models import Doctor
        from scheduling.models import Appointment
        doctor = Doctor.objects.create(name="Dr. Mehta", specialty="General Medicine",
                                       working_hours={"mon": [["09:00", "17:00"]]})
        start = timezone.now() + datetime.timedelta(days=2)
        Appointment.objects.create(
            doctor=doctor, patient=auth_session.patient, start_time=start,
            end_time=start + datetime.timedelta(minutes=20), reason="checkup",
            urgency="routine", status="booked", source="scheduling")
        result = services.dispatch_intent(auth_session, "appointment")
        assert len(result["appointments"]) == 1
        assert result["appointments"][0]["doctor"] == "Dr. Mehta"

    @pytest.fixture
    def prescriber(self, db):
        from core.models import Doctor
        return Doctor.objects.create(name="Dr. Rao", specialty="General Medicine",
                                     working_hours={"mon": [["09:00", "17:00"]]})

    def test_refill_handler_lists_medications(self, auth_session, prescriber):
        from refills.models import Prescription
        Prescription.objects.create(
            patient=auth_session.patient, prescriber=prescriber,
            medication_name="Amlodipine", dose="5 mg",
            quantity="30", prescribed_date=timezone.localdate(),
            expiry_date=timezone.localdate() + datetime.timedelta(days=300),
            refills_allowed=5, refills_used=1)
        result = services.dispatch_intent(auth_session, "refill")
        assert result["prescriptions"][0]["medication"] == "Amlodipine"
        assert result["prescriptions"][0]["refills_left"] == 4

    def test_refill_handler_controlled_only_escalates(self, auth_session, prescriber):
        """Edge Case 12: a chart with ONLY a controlled substance never gets
        an automated refill path — straight to a human, high priority."""
        from refills.models import Prescription
        Prescription.objects.create(
            patient=auth_session.patient, prescriber=prescriber,
            medication_name="Alprazolam", dose="0.5 mg",
            quantity="30", prescribed_date=timezone.localdate(),
            expiry_date=timezone.localdate() + datetime.timedelta(days=300),
            refills_allowed=2, refills_used=0, is_controlled_substance=True)
        result = services.dispatch_intent(auth_session, "refill")
        task = StaffTask.objects.get()
        assert task.category == "controlled_substance"
        assert task.priority == "high"
        assert result["status"] == "escalated"

    def test_care_gap_handler_uses_agent8(self, auth_session):
        from caregaps.models import ClinicalGuideline
        from caregaps.services import scan_patient
        ClinicalGuideline.objects.create(
            name="Flu vaccine", population_criteria={}, care_item_type="vaccination",
            care_item_code="140", frequency_days=365, risk_tier="medium")
        scan_patient(auth_session.patient)
        result = services.dispatch_intent(auth_session, "care_gap")
        assert result["care_gaps"][0]["guideline"] == "Flu vaccine"

    def test_symptoms_hands_off_to_triage(self, auth_session):
        result = services.dispatch_intent(auth_session, "symptoms")
        assert result["handoff"] == "triage"


# -- knowledge search ----------------------------------------------------------------

class TestKnowledgeSearch:
    @pytest.fixture(autouse=True)
    def _seed(self, db):
        call_command("seed_knowledge")

    @pytest.mark.parametrize("query,expected_title_fragment", [
        ("are you open on sunday?", "Clinic hours"),
        ("where can I park", "locations"),
        ("do you take Star Health insurance", "insurance"),
        ("how much is a consultation", "fees"),
        ("can I eat before my blood test", "Fasting"),
        ("how do I cancel my appointment", "Cancelling"),
    ])
    def test_natural_questions_find_the_right_article(self, query, expected_title_fragment):
        articles = services.search_knowledge(query)
        assert articles, f"no hit for {query!r}"
        assert expected_title_fragment.lower() in articles[0].title.lower()

    def test_no_match_returns_empty_and_faq_escalates(self, session):
        assert services.search_knowledge("quantum entanglement discounts") == []
        result = services.dispatch_intent(
            session, "faq", {"question": "quantum entanglement discounts"})
        assert result["status"] == "escalated"
        assert StaffTask.objects.get().category == "unanswered_question"


# -- mandatory escalation --------------------------------------------------------------

class TestMandatoryEscalation:
    @pytest.mark.parametrize("category,priority", [
        ("mental_health", "critical"),
        ("stroke", "critical"),
        ("insurance_dispute", "high"),
        ("controlled_substance", "high"),
    ])
    def test_mandatory_categories_always_create_a_task(self, session, category, priority):
        task = services.create_staff_task(session, category)
        assert task.status == "open"
        assert task.priority == priority

    def test_caller_cannot_downgrade_a_mandatory_priority(self, session):
        task = services.create_staff_task(session, "stroke", priority="normal")
        assert task.priority == "critical"

    def test_task_links_patient_when_authenticated(self, auth_session):
        task = services.create_staff_task(auth_session, "insurance_dispute",
                                          summary="disputes co-pay")
        assert task.patient == auth_session.patient
        from core.models import AuditEvent
        assert AuditEvent.objects.filter(action="frontdesk.staff_task_created").exists()
