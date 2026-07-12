"""Scheduling reacts to other agents' events (Phase 6 integrations)."""

import datetime

import pytest

from core.events import emit
from core.models import Patient, SentNotification


@pytest.fixture
def patient(db):
    return Patient.objects.create(
        first_name="Rahul", last_name="Sharma", contact_number="9876543210",
        dob=datetime.date(1990, 5, 17),
    )


class TestTriageDispositionSubscriber:
    def test_same_day_disposition_offers_urgent_booking(self, patient):
        emit("triage.disposition", patient_id=patient.id, assessment_id=1,
             acuity="high", disposition="same_day", route_to="scheduling")
        note = SentNotification.objects.filter(patient=patient).latest("id")
        assert "see a doctor today" in note.rendered_content
        assert "book an appointment" in note.rendered_content

    def test_routine_disposition_relaxed_wording(self, patient):
        emit("triage.disposition", patient_id=patient.id, assessment_id=1,
             acuity="low", disposition="routine", route_to="scheduling")
        note = SentNotification.objects.filter(patient=patient).latest("id")
        assert "at a convenient time" in note.rendered_content

    def test_dispositions_routed_elsewhere_are_ignored(self, patient):
        emit("triage.disposition", patient_id=patient.id, assessment_id=1,
             acuity="emergency", disposition="ed_now", route_to=None)
        assert not SentNotification.objects.filter(patient=patient).exists()


class TestRefillVisitSubscriber:
    def test_visit_required_offers_booking_with_the_medication(self, patient):
        emit("refill.visit_required", patient_id=patient.id, request_id=7,
             medication="Amlodipine")
        note = SentNotification.objects.filter(patient=patient).latest("id")
        assert "before refilling Amlodipine" in note.rendered_content
        assert "book an appointment" in note.rendered_content


class TestPriorauthApprovalSubscriber:
    """FR-P7 "hand off to Scheduling" (Agent 6 Phase 6) — an offer, not a
    silent auto-booked appointment, same pattern as the other two above."""

    def test_priorauth_approved_offers_booking(self, patient):
        emit("priorauth.approved", request_id=1, patient_id=patient.id,
             order_id=1, treatment="MRI 70551")
        note = SentNotification.objects.filter(patient=patient).latest("id")
        assert "MRI 70551" in note.rendered_content
        assert "book" in note.rendered_content.lower()

    def test_missing_treatment_falls_back_to_generic_wording(self, patient):
        emit("priorauth.approved", request_id=1, patient_id=patient.id, order_id=1)
        note = SentNotification.objects.filter(patient=patient).latest("id")
        assert "your approved treatment" in note.rendered_content
