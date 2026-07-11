"""Phase 2 exit tests: matching filters, every legal/illegal status
transition, stalled detection at the boundary, and the missed-appointment
chain."""

import datetime

import pytest
from django.utils import timezone

from core.models import AuditEvent, Doctor, EventLog, Patient, Specialty
from referrals import services
from referrals.models import ConsultationReport, Referral, Specialist
from registration.models import InsurancePolicy
from scheduling.models import Appointment
from triage.models import EscalationAlert

TODAY = datetime.date.today()


@pytest.fixture
def patient(db):
    return Patient.objects.create(
        first_name="Rahul", last_name="Sharma", contact_number="9876543210",
        dob=datetime.date(1990, 5, 17), address={"city": "Pune", "zip": "411005"},
    )


@pytest.fixture
def doctor(db):
    return Doctor.objects.create(name="Dr. Asha Mehta", specialty="General Medicine")


@pytest.fixture
def specialist(db):
    return Specialist.objects.create(
        name="Dr. Rohan Kulkarni", specialty=Specialty.CARDIOLOGY,
        address={"city": "Pune", "postal_code": "411005"},
        accepted_insurances=["BlueShield"], languages=["en", "hi"],
        accepting_new_patients=True, contact_channel="e_referral",
    )


def make_referral(patient, doctor, **overrides):
    defaults = dict(
        patient=patient, referring_doctor=doctor, specialty_needed=Specialty.CARDIOLOGY,
        reason="chest pain on exertion", urgency="routine", status="created",
        status_history=[{"status": "created", "at": timezone.now().isoformat()}],
    )
    defaults.update(overrides)
    return Referral.objects.create(**defaults)


class TestCreateReferral:
    def test_one_click_creation(self, patient, doctor):
        referral = services.create_referral(
            doctor, patient, Specialty.CARDIOLOGY, "chest pain on exertion", "routine",
        )
        assert referral.status == "created"
        assert referral.status_history == [
            {"status": "created", "at": referral.status_history[0]["at"]},
        ]
        assert EventLog.objects.filter(name="referral.created",
                                       payload__referral_id=referral.id).exists()
        assert AuditEvent.objects.filter(
            patient=patient, action="referral.created").exists()


class TestMatchSpecialists:
    def test_wrong_specialty_is_excluded(self, patient, doctor, specialist):
        referral = make_referral(patient, doctor, specialty_needed=Specialty.DERMATOLOGY)
        assert specialist not in services.match_specialists(referral, patient)

    def test_not_accepting_new_patients_is_excluded(self, patient, doctor, specialist):
        specialist.accepting_new_patients = False
        specialist.save(update_fields=["accepting_new_patients"])
        referral = make_referral(patient, doctor)
        assert services.match_specialists(referral, patient) == []

    def test_insurance_mismatch_is_excluded(self, patient, doctor, specialist):
        InsurancePolicy.objects.create(
            patient=patient, policy_number="X1", provider_name="Star Health",
            coverage_details="",
        )
        referral = make_referral(patient, doctor)
        # specialist only accepts BlueShield — patient has Star Health only
        assert services.match_specialists(referral, patient) == []

    def test_insurance_match_is_included(self, patient, doctor, specialist):
        InsurancePolicy.objects.create(
            patient=patient, policy_number="X1", provider_name="BlueShield",
            coverage_details="",
        )
        referral = make_referral(patient, doctor)
        assert services.match_specialists(referral, patient) == [specialist]

    def test_uninsured_patient_is_never_excluded_by_insurance(self, patient, doctor, specialist):
        # No InsurancePolicy on file at all — nothing to check compatibility
        # against, so insurance must not filter this patient out.
        referral = make_referral(patient, doctor)
        assert services.match_specialists(referral, patient) == [specialist]

    def test_nearest_ranked_first(self, patient, doctor, specialist):
        far = Specialist.objects.create(
            name="Dr. Neha Kapoor", specialty=Specialty.CARDIOLOGY,
            address={"city": "Mumbai", "postal_code": "400001"},
            accepting_new_patients=True, contact_channel="phone",
        )
        referral = make_referral(patient, doctor)
        # patient is in Pune 411005 — `specialist` (same city+zip) must rank
        # ahead of `far` (different city, distant zip).
        assert services.match_specialists(referral, patient) == [specialist, far]

    def test_language_match_breaks_a_distance_tie(self, patient, doctor):
        same_city_no_lang = Specialist.objects.create(
            name="Dr. A", specialty=Specialty.CARDIOLOGY,
            address={"city": "Pune", "postal_code": "411005"},
            languages=["fr"], accepting_new_patients=True, contact_channel="phone",
        )
        same_city_with_lang = Specialist.objects.create(
            name="Dr. B", specialty=Specialty.CARDIOLOGY,
            address={"city": "Pune", "postal_code": "411005"},
            languages=["en"], accepting_new_patients=True, contact_channel="phone",
        )
        referral = make_referral(patient, doctor)  # patient.preferred_language == "en"
        ranked = services.match_specialists(referral, patient)
        assert ranked.index(same_city_with_lang) < ranked.index(same_city_no_lang)


class TestRequiredDocumentsFor:
    def test_known_specialty_mapping(self):
        docs = services.required_documents_for(Specialty.CARDIOLOGY)
        assert "ecg" in docs and "echocardiogram" in docs

    def test_unmapped_specialty_falls_back_to_default(self):
        assert services.required_documents_for("Some Future Specialty") == \
            services.DEFAULT_REQUIRED_DOCUMENTS


class TestAdvanceStatus:
    @pytest.mark.parametrize("start, target", [
        ("created", "accepted"),
        ("accepted", "appointment_scheduled"),
        ("appointment_scheduled", "patient_confirmed"),
        ("patient_confirmed", "visit_completed"),
        ("visit_completed", "report_received"),
        ("report_received", "closed"),
        ("created", "stalled"),
        ("patient_confirmed", "stalled"),
        ("stalled", "appointment_scheduled"),
        ("stalled", "closed"),
    ])
    def test_legal_transitions_succeed(self, patient, doctor, start, target):
        referral = make_referral(patient, doctor, status=start,
                                 status_history=[{"status": start, "at": "x"}])
        services.advance_status(referral, target)
        referral.refresh_from_db()
        assert referral.status == target
        assert referral.status_history[-1]["status"] == target
        assert EventLog.objects.filter(
            name="referral.status_changed",
            payload__referral_id=referral.id, payload__new_status=target,
        ).exists()

    @pytest.mark.parametrize("start, target", [
        ("created", "visit_completed"),       # skipping steps
        ("created", "closed"),                # skipping to the end
        ("report_received", "accepted"),      # going backward
        ("closed", "accepted"),               # terminal, nothing leaves it
        ("closed", "stalled"),
        ("stalled", "created"),               # never back to the very start
        ("accepted", "accepted"),             # not a transition at all
    ])
    def test_illegal_transitions_are_refused(self, patient, doctor, start, target):
        referral = make_referral(patient, doctor, status=start,
                                 status_history=[{"status": start, "at": "x"}])
        with pytest.raises(services.IllegalStatusTransition):
            services.advance_status(referral, target)
        referral.refresh_from_db()
        assert referral.status == start  # unchanged


class TestResumeReferral:
    def test_resumes_to_the_status_it_stalled_from(self, patient, doctor):
        referral = make_referral(
            patient, doctor, status="stalled",
            status_history=[{"status": "created", "at": "1"},
                            {"status": "accepted", "at": "2"},
                            {"status": "stalled", "at": "3"}],
        )
        services.resume_referral(referral)
        referral.refresh_from_db()
        assert referral.status == "accepted"
        assert referral.status_history[-1]["status"] == "accepted"

    def test_resuming_unblocks_the_stricter_action_preconditions(self, patient, doctor, specialist):
        # book_specialist_visit requires status == "accepted" exactly — a
        # referral that stalled while accepted must resume first, then book
        # works normally (it must NOT be bookable straight from "stalled").
        internal_doctor = Doctor.objects.create(name="Dr. Rohan Kulkarni (internal)",
                                                specialty="Cardiology")
        specialist.internal_doctor = internal_doctor
        specialist.save(update_fields=["internal_doctor"])
        referral = make_referral(
            patient, doctor, specialist=specialist, status="stalled",
            status_history=[{"status": "created", "at": "1"},
                            {"status": "accepted", "at": "2"},
                            {"status": "stalled", "at": "3"}],
        )
        start = timezone.now() + datetime.timedelta(days=1)
        with pytest.raises(services.IllegalStatusTransition):
            services.book_specialist_visit(referral, (start, start + datetime.timedelta(minutes=30)))

        services.resume_referral(referral)
        services.book_specialist_visit(referral, (start, start + datetime.timedelta(minutes=30)))
        referral.refresh_from_db()
        assert referral.status == "appointment_scheduled"

    def test_refuses_when_history_has_no_valid_prior_status(self, patient, doctor):
        # A real referral's history always has "created" seeded first
        # (create_referral does this); history that's only ever "stalled"
        # is inconsistent data, and "created" itself is never a legal
        # resume target — must raise, never guess a fabricated status.
        referral = make_referral(patient, doctor, status="stalled",
                                 status_history=[{"status": "stalled", "at": "1"}])
        with pytest.raises(services.IllegalStatusTransition):
            services.resume_referral(referral)
        referral.refresh_from_db()
        assert referral.status == "stalled"  # unchanged

    def test_refuses_when_not_actually_stalled(self, patient, doctor):
        referral = make_referral(patient, doctor, status="accepted")
        with pytest.raises(services.IllegalStatusTransition):
            services.resume_referral(referral)


class TestCheckStalledReferrals:
    def _backdate(self, referral, days):
        Referral.objects.filter(id=referral.id).update(
            created_at=timezone.now() - datetime.timedelta(days=days),
        )

    def test_flags_referrals_past_the_threshold(self, patient, doctor):
        referral = make_referral(patient, doctor, status="accepted")
        self._backdate(referral, days=15)
        flagged = services.check_stalled_referrals()
        assert [r.id for r in flagged] == [referral.id]
        referral.refresh_from_db()
        assert referral.status == "stalled"
        assert EscalationAlert.objects.filter(
            patient=patient, source_agent="referrals").exists()

    def test_boundary_exactly_at_threshold_is_not_yet_stalled(self, patient, doctor):
        referral = make_referral(patient, doctor, status="accepted")
        self._backdate(referral, days=14)  # created_at__lte cutoff — inclusive
        services.check_stalled_referrals()
        referral.refresh_from_db()
        assert referral.status == "stalled"  # 14 days ago IS past the cutoff (<=)

    def test_one_day_under_threshold_is_untouched(self, patient, doctor):
        referral = make_referral(patient, doctor, status="accepted")
        self._backdate(referral, days=13)
        flagged = services.check_stalled_referrals()
        assert flagged == []
        referral.refresh_from_db()
        assert referral.status == "accepted"

    def test_already_closed_or_stalled_are_never_reflagged(self, patient, doctor):
        closed = make_referral(patient, doctor, status="closed")
        self._backdate(closed, days=30)
        already_stalled = make_referral(patient, doctor, status="stalled")
        self._backdate(already_stalled, days=30)
        alerts_before = EscalationAlert.objects.count()

        flagged = services.check_stalled_referrals()

        assert flagged == []
        assert EscalationAlert.objects.count() == alerts_before

    def test_custom_threshold(self, patient, doctor):
        referral = make_referral(patient, doctor, status="accepted")
        self._backdate(referral, days=8)
        assert services.check_stalled_referrals(threshold_days=7) == [referral]


class TestHandleMissedAppointment:
    def test_first_attempt_sends_a_reminder_without_escalating(self, patient, doctor):
        referral = make_referral(patient, doctor, status="patient_confirmed",
                                 status_history=[{"status": "patient_confirmed", "at": "x"}])
        result = services.handle_missed_appointment(referral, attempt=1)
        assert result == {"action": "reminder_sent"}
        referral.refresh_from_db()
        assert referral.status == "patient_confirmed"  # untouched
        assert not EscalationAlert.objects.filter(patient=patient).exists()

    def test_second_attempt_escalates_and_stalls(self, patient, doctor):
        referral = make_referral(patient, doctor, status="patient_confirmed",
                                 status_history=[{"status": "patient_confirmed", "at": "x"}])
        result = services.handle_missed_appointment(referral, attempt=2)
        assert result["action"] == "physician_notified"
        alert = EscalationAlert.objects.get(id=result["alert_id"])
        assert alert.source_agent == "referrals"
        assert doctor.name in alert.summary
        referral.refresh_from_db()
        assert referral.status == "stalled"

    def test_escalation_on_a_status_that_cannot_stall_does_not_crash(self, patient, doctor):
        # "closed" has no legal transition to "stalled" — must degrade
        # gracefully (still escalate) rather than raise.
        referral = make_referral(patient, doctor, status="closed",
                                 status_history=[{"status": "closed", "at": "x"}])
        result = services.handle_missed_appointment(referral, attempt=2)
        assert result["action"] == "physician_notified"
        referral.refresh_from_db()
        assert referral.status == "closed"  # unchanged, no crash


class TestAcceptReferral:
    def test_normal_referral_already_has_a_referring_doctor(self, patient, doctor, specialist):
        referral = make_referral(patient, doctor, status="created")  # doctor set by make_referral
        services.accept_referral(referral, specialist)
        referral.refresh_from_db()
        assert referral.status == "accepted"
        assert referral.specialist_id == specialist.id
        assert referral.referring_doctor_id == doctor.id

    def test_draft_referral_requires_a_confirming_doctor(self, patient, specialist):
        draft = make_referral(patient, None, referring_doctor=None, status="created")
        with pytest.raises(ValueError, match="referring physician must confirm"):
            services.accept_referral(draft, specialist)
        draft.refresh_from_db()
        assert draft.status == "created"  # unchanged
        assert draft.specialist is None  # unchanged

    def test_confirming_doctor_attaches_and_proceeds(self, patient, doctor, specialist):
        draft = make_referral(patient, None, referring_doctor=None, status="created")
        services.accept_referral(draft, specialist, doctor)
        draft.refresh_from_db()
        assert draft.status == "accepted"
        assert draft.referring_doctor_id == doctor.id

    def test_emits_priorauth_needed_for_agent_6(self, patient, doctor, specialist):
        referral = make_referral(patient, doctor, status="created")
        services.accept_referral(referral, specialist)
        event = EventLog.objects.filter(name="priorauth.needed").latest("id")
        assert event.payload["referral_id"] == referral.id
        assert event.payload["specialty_needed"] == referral.specialty_needed


class TestBookSpecialistVisit:
    def test_books_against_the_in_network_calendar_and_advances_status(
        self, patient, doctor, specialist,
    ):
        internal_doctor = Doctor.objects.create(name="Dr. Rohan Kulkarni (internal)",
                                                specialty="Cardiology")
        specialist.internal_doctor = internal_doctor
        specialist.save(update_fields=["internal_doctor"])
        referral = make_referral(patient, doctor, specialist=specialist, status="accepted",
                                 status_history=[{"status": "accepted", "at": "x"}])
        start = timezone.now() + datetime.timedelta(days=1)
        end = start + datetime.timedelta(minutes=30)

        appointment = services.book_specialist_visit(referral, (start, end))

        assert isinstance(appointment, Appointment)
        assert appointment.doctor_id == internal_doctor.id
        assert appointment.source == "referrals"
        referral.refresh_from_db()
        assert referral.appointment_id == appointment.id
        assert referral.status == "appointment_scheduled"

    def test_refuses_to_book_before_the_referral_is_accepted(self, patient, doctor, specialist):
        internal_doctor = Doctor.objects.create(name="Dr. X", specialty="Cardiology")
        specialist.internal_doctor = internal_doctor
        specialist.save(update_fields=["internal_doctor"])
        referral = make_referral(patient, doctor, specialist=specialist, status="created")
        start = timezone.now() + datetime.timedelta(days=1)
        with pytest.raises(services.IllegalStatusTransition):
            services.book_specialist_visit(referral, (start, start + datetime.timedelta(minutes=30)))

    def test_refuses_when_no_specialist_matched_yet(self, patient, doctor):
        referral = make_referral(patient, doctor, status="accepted",
                                 status_history=[{"status": "accepted", "at": "x"}])
        start = timezone.now() + datetime.timedelta(days=1)
        with pytest.raises(ValueError, match="no matched specialist"):
            services.book_specialist_visit(referral, (start, start + datetime.timedelta(minutes=30)))

    def test_refuses_an_out_of_network_specialist(self, patient, doctor, specialist):
        # specialist.internal_doctor is None by default — out of network.
        referral = make_referral(patient, doctor, specialist=specialist, status="accepted",
                                 status_history=[{"status": "accepted", "at": "x"}])
        start = timezone.now() + datetime.timedelta(days=1)
        with pytest.raises(ValueError, match="out-of-network"):
            services.book_specialist_visit(referral, (start, start + datetime.timedelta(minutes=30)))


class TestCloseLoop:
    REPORT = {
        "diagnosis": "Stable angina",
        "treatment_plan": "Start atenolol 25mg daily",
        "medications": ["atenolol 25mg"],
        "followup_recommendations": ["repeat ECG in 3 months"],
    }

    def test_closes_from_visit_completed(self, patient, doctor):
        referral = make_referral(patient, doctor, status="visit_completed",
                                 status_history=[{"status": "visit_completed", "at": "x"}])
        report = services.close_loop(referral, self.REPORT)
        assert isinstance(report, ConsultationReport)
        assert report.diagnosis == "Stable angina"
        referral.refresh_from_db()
        assert referral.status == "closed"
        statuses = [entry["status"] for entry in referral.status_history]
        assert statuses[-2:] == ["report_received", "closed"]

    def test_closes_from_report_received_without_a_duplicate_history_entry(self, patient, doctor):
        referral = make_referral(patient, doctor, status="report_received",
                                 status_history=[{"status": "report_received", "at": "x"}])
        services.close_loop(referral, self.REPORT)
        referral.refresh_from_db()
        assert referral.status == "closed"
        assert referral.status_history[-1]["status"] == "closed"
        assert referral.status_history[-2]["status"] == "report_received"  # not duplicated

    def test_refuses_to_close_before_the_visit_happened(self, patient, doctor):
        referral = make_referral(patient, doctor, status="appointment_scheduled")
        with pytest.raises(services.IllegalStatusTransition):
            services.close_loop(referral, self.REPORT)
        assert not ConsultationReport.objects.filter(referral=referral).exists()
