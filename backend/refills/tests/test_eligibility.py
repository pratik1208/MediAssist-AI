"""Phase 2 exit tests: every eligibility rule failing individually,
zero-refills routing, controlled-substance escalation, and the
approve -> write-back -> pharmacy chain."""

import datetime

import pytest
from django.utils import timezone

from core.models import AuditEvent, Doctor, EventLog, Patient, SentNotification
from refills import services
from refills.models import Pharmacy, Prescription, RefillRequest
from registration.models import UploadedDocument
from triage.models import EscalationAlert

TODAY = datetime.date.today()


@pytest.fixture
def patient(db):
    return Patient.objects.create(
        first_name="Rahul", last_name="Sharma", contact_number="9876543210",
        dob=datetime.date(1990, 5, 17),
    )


@pytest.fixture
def doctor(db):
    return Doctor.objects.create(name="Dr. Asha Mehta", specialty="General Medicine")


@pytest.fixture
def pharmacy(db):
    return Pharmacy.objects.create(name="Apollo Pharmacy", phone="020-0000")


def make_rx(patient, doctor, **overrides):
    defaults = dict(
        medication_name="Amlodipine", dose="5 mg", quantity="30 tablets",
        refills_allowed=5, refills_used=1,
        prescribed_date=TODAY - datetime.timedelta(days=60),
        expiry_date=TODAY + datetime.timedelta(days=300),
        status="active", required_labs=[], followup_required=False,
        is_controlled_substance=False,
    )
    defaults.update(overrides)
    return Prescription.objects.create(patient=patient, prescriber=doctor, **defaults)


def make_request(rx, pharmacy, **overrides):
    return RefillRequest.objects.create(
        prescription=rx, patient=rx.patient, pharmacy=pharmacy, **overrides,
    )


def add_lab(patient, test_name, age_days):
    UploadedDocument.objects.create(
        patient=patient, document_type="lab_report", extraction_status="done",
        extracted_data={"lab_report": {
            "test_name": test_name,
            "date": (TODAY - datetime.timedelta(days=age_days)).isoformat(),
        }},
    )


class TestEachRuleFailsIndividually:
    def test_clean_prescription_is_eligible(self, patient, doctor, pharmacy):
        result = services.check_eligibility(make_request(make_rx(patient, doctor), pharmacy))
        assert (result.eligible, result.failures, result.needs_new_prescription) == (True, [], False)

    def test_discontinued(self, patient, doctor, pharmacy):
        rx = make_rx(patient, doctor, status="discontinued")
        result = services.check_eligibility(make_request(rx, pharmacy))
        assert result.failures == ["discontinued_by_doctor"]

    def test_expired(self, patient, doctor, pharmacy):
        rx = make_rx(patient, doctor, status="expired",
                     expiry_date=TODAY - datetime.timedelta(days=10))
        result = services.check_eligibility(make_request(rx, pharmacy))
        assert result.failures == ["prescription_expired"]

    def test_too_early(self, patient, doctor, pharmacy):
        rx = make_rx(patient, doctor)  # 30-day supply
        make_request(rx, pharmacy, status="approved")  # filled today
        result = services.check_eligibility(make_request(rx, pharmacy))
        assert result.failures == ["too_early"]

    def test_due_again_after_the_supply_window(self, patient, doctor, pharmacy):
        rx = make_rx(patient, doctor)
        old_fill = make_request(rx, pharmacy, status="approved")
        RefillRequest.objects.filter(id=old_fill.id).update(
            created_at=timezone.now() - datetime.timedelta(days=25))  # >75% of 30
        result = services.check_eligibility(make_request(rx, pharmacy))
        assert result.eligible is True

    def test_missing_lab(self, patient, doctor, pharmacy):
        rx = make_rx(patient, doctor,
                     required_labs=[{"test": "lipid_panel", "max_age_days": 180}])
        result = services.check_eligibility(make_request(rx, pharmacy))
        assert result.failures == ["missing_lab:lipid_panel"]

    def test_recent_lab_satisfies_the_rule(self, patient, doctor, pharmacy):
        rx = make_rx(patient, doctor,
                     required_labs=[{"test": "lipid_panel", "max_age_days": 180}])
        add_lab(patient, "Lipid Panel", age_days=90)  # name normalization too
        result = services.check_eligibility(make_request(rx, pharmacy))
        assert result.eligible is True

    def test_stale_lab_does_not(self, patient, doctor, pharmacy):
        rx = make_rx(patient, doctor,
                     required_labs=[{"test": "lipid_panel", "max_age_days": 180}])
        add_lab(patient, "Lipid Panel", age_days=200)
        result = services.check_eligibility(make_request(rx, pharmacy))
        assert result.failures == ["missing_lab:lipid_panel"]

    def test_followup_outstanding(self, patient, doctor, pharmacy):
        rx = make_rx(patient, doctor, followup_required=True)
        result = services.check_eligibility(make_request(rx, pharmacy))
        assert result.failures == ["followup_visit_required"]


class TestZeroRefillsRouting:
    def test_out_of_refills_is_a_renewal_not_a_refill(self, patient, doctor, pharmacy):
        rx = make_rx(patient, doctor, refills_allowed=3, refills_used=3)
        result = services.check_eligibility(make_request(rx, pharmacy))
        assert result.eligible is True
        assert result.needs_new_prescription is True

    def test_renewal_flag_reaches_the_physician_queue(self, patient, doctor, pharmacy):
        rx = make_rx(patient, doctor, refills_allowed=3, refills_used=3)
        request = make_request(rx, pharmacy)
        services.run_eligibility_check(request)
        request.refresh_from_db()
        assert request.status == "pending_approval"
        assert request.renewal_summary["is_renewal"] is True
        assert request.renewal_summary["refills_remaining"] == 0


class TestPausedPath:
    def test_failure_pauses_and_notifies_the_patient(self, patient, doctor, pharmacy):
        rx = make_rx(patient, doctor, followup_required=True)
        request = make_request(rx, pharmacy)
        result = services.run_eligibility_check(request)
        request.refresh_from_db()
        assert result.eligible is False
        assert request.status == "paused"
        assert "follow-up visit" in request.pause_reason
        note = SentNotification.objects.filter(patient=patient).latest("id")
        assert "on hold" in note.rendered_content
        assert "follow-up visit" in note.rendered_content


class TestControlledSubstance:
    def test_never_auto_processed_always_escalated(self, patient, doctor, pharmacy):
        rx = make_rx(patient, doctor, medication_name="Alprazolam",
                     is_controlled_substance=True)
        request = make_request(rx, pharmacy)
        result = services.run_eligibility_check(request)
        request.refresh_from_db()

        assert result.failures == ["controlled_substance"]
        assert request.status == "pending_approval"  # human queue, no auto path
        alert = EscalationAlert.objects.get(patient=patient)
        assert alert.source_agent == "refills"
        assert alert.category == "controlled_substance"
        assert alert.assessment is None
        assert "Alprazolam" in alert.summary
        event = EventLog.objects.filter(name="escalation.created").latest("id")
        assert event.payload["category"] == "controlled_substance"


class TestRenewalSummary:
    def test_contains_the_fr_m5_facts(self, patient, doctor, pharmacy):
        rx = make_rx(patient, doctor,
                     required_labs=[{"test": "lipid_panel", "max_age_days": 180}])
        add_lab(patient, "Lipid Panel", age_days=60)
        summary = services.build_renewal_summary(make_request(rx, pharmacy))
        assert summary["medication"] == "Amlodipine 5 mg"
        assert summary["refills_remaining"] == 4
        assert summary["recent_labs"][0]["test"] == "Lipid Panel"
        assert summary["adherence"] == "unknown"  # <2 fills on record
        assert summary["controlled_substance"] is False

    def test_adherence_good_and_poor(self, patient, doctor, pharmacy):
        rx = make_rx(patient, doctor)  # 30-day supply
        for days_ago in (90, 60, 30):  # regular ~30-day gaps -> good
            fill = make_request(rx, pharmacy, status="approved")
            RefillRequest.objects.filter(id=fill.id).update(
                created_at=timezone.now() - datetime.timedelta(days=days_ago))
        assert services.compute_adherence(rx) == "good"

        late_rx = make_rx(patient, doctor, medication_name="Metformin")
        for days_ago in (120, 60):  # 60-day gap on a 30-day supply -> poor
            fill = make_request(late_rx, pharmacy, status="approved")
            RefillRequest.objects.filter(id=fill.id).update(
                created_at=timezone.now() - datetime.timedelta(days=days_ago))
        assert services.compute_adherence(late_rx) == "poor"


class TestPhysicianDecisions:
    def pending_request(self, patient, doctor, pharmacy):
        request = make_request(make_rx(patient, doctor), pharmacy)
        services.run_eligibility_check(request)
        return request

    def test_approve_writes_back_and_sends_to_pharmacy(self, patient, doctor, pharmacy):
        request = self.pending_request(patient, doctor, pharmacy)
        new_rx = services.approve(request, doctor)
        request.refresh_from_db()

        # write-back (FR-M7): fresh prescription row
        assert new_rx.id != request.prescription_id
        assert new_rx.prescriber == doctor
        assert new_rx.refills_used == 0
        assert new_rx.prescribed_date == TODAY
        # decision recorded
        assert request.decided_by == doctor
        assert request.decided_at is not None
        # pharmacy leg + patient notification (FR-M8)
        assert request.status == "sent_to_pharmacy"
        note = SentNotification.objects.filter(patient=patient).latest("id")
        assert "sent to Apollo Pharmacy" in note.rendered_content
        # audit + downstream event
        assert AuditEvent.objects.filter(action="refill.approved",
                                         patient=patient).exists()
        assert EventLog.objects.filter(name="refill.approved").exists()

    def test_reject_records_reason_and_notifies(self, patient, doctor, pharmacy):
        request = self.pending_request(patient, doctor, pharmacy)
        services.reject(request, doctor, "needs blood pressure recheck first")
        request.refresh_from_db()
        assert request.status == "rejected"
        assert request.pause_reason == "needs blood pressure recheck first"
        note = SentNotification.objects.filter(patient=patient).latest("id")
        assert "not approved" in note.rendered_content

    def test_request_visit_emits_the_scheduling_event(self, patient, doctor, pharmacy):
        request = self.pending_request(patient, doctor, pharmacy)
        services.request_visit(request, doctor)
        request.refresh_from_db()
        assert request.status == "visit_required"
        event = EventLog.objects.filter(name="refill.visit_required").latest("id")
        assert event.payload == {"patient_id": patient.id, "request_id": request.id,
                                 "medication": "Amlodipine"}

    def test_ready_for_pickup_notifies(self, patient, doctor, pharmacy):
        request = self.pending_request(patient, doctor, pharmacy)
        services.approve(request, doctor)
        request.refresh_from_db()
        services.mark_ready_for_pickup(request)
        request.refresh_from_db()
        assert request.status == "ready_for_pickup"
        note = SentNotification.objects.filter(patient=patient).latest("id")
        assert "ready for pickup" in note.rendered_content
