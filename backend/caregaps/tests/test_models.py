"""Phase 1 model tests: __str__/admin display helpers (cheap to verify, and
the admin is the staff surface until the Phase 5 dashboard) plus the one
piece of real behavior the schema encodes — the partial unique constraint
that allows only ONE live gap per patient+guideline (FR-G1/G2)."""

import datetime

import pytest
from django.db import IntegrityError
from django.utils import timezone

from caregaps.admin import CarePlanAdmin, ClinicalGuidelineAdmin
from caregaps.models import CareGap, CarePlan, ClinicalEvent, ClinicalGuideline
from core.models import Patient


@pytest.fixture
def patient(db):
    return Patient.objects.create(
        first_name="Rahul", last_name="Sharma", contact_number="9876543210",
        email="r@example.com", dob=datetime.date(1955, 5, 17), registration_status="complete",
    )


@pytest.fixture
def guideline(db):
    return ClinicalGuideline.objects.create(
        name="HbA1c every 6 months for diabetics",
        population_criteria={"has_diagnosis_code": "E11"},
        care_item_type="test", care_item_code="4548-4",
        frequency_days=182, risk_tier="high",
    )


def test_guideline_str(guideline):
    assert str(guideline) == "HbA1c every 6 months for diabetics (v1, high)"


def test_clinical_event_str(patient):
    event = ClinicalEvent.objects.create(
        patient=patient, event_type="lab", code="4548-4",
        value={"hba1c": 8.4}, occurred_at=timezone.make_aware(datetime.datetime(2026, 1, 15, 9, 0)),
    )
    assert "lab 4548-4" in str(event)
    assert "2026-01-15" in str(event)


def test_care_gap_str(patient, guideline):
    gap = CareGap.objects.create(patient=patient, guideline=guideline,
                                 due_since=datetime.date(2026, 1, 1))
    assert "HbA1c" in str(gap)
    assert "(open)" in str(gap)


def test_care_plan_str_and_bundle(patient, guideline):
    gap = CareGap.objects.create(patient=patient, guideline=guideline,
                                 due_since=datetime.date(2026, 1, 1))
    plan = CarePlan.objects.create(patient=patient)
    plan.gaps.add(gap)
    assert "(draft)" in str(plan)
    assert plan.gaps.count() == 1
    assert gap.care_plans.first() == plan


def test_only_one_live_gap_per_patient_guideline(patient, guideline):
    """The partial unique constraint: a second non-closed gap for the same
    patient+guideline must be rejected, but once a gap is closed a fresh
    cycle may open a new one."""
    CareGap.objects.create(patient=patient, guideline=guideline,
                           due_since=datetime.date(2026, 1, 1))

    with pytest.raises(IntegrityError):
        CareGap.objects.create(patient=patient, guideline=guideline,
                               due_since=datetime.date(2026, 2, 1))


def test_new_gap_allowed_after_close(patient, guideline):
    first = CareGap.objects.create(patient=patient, guideline=guideline,
                                   due_since=datetime.date(2026, 1, 1))
    first.status = "closed"
    first.closed_at = timezone.now()
    first.save()

    second = CareGap.objects.create(patient=patient, guideline=guideline,
                                    due_since=datetime.date(2026, 7, 1))
    assert second.id != first.id


def test_live_gap_in_other_status_still_blocks(patient, guideline):
    """'outreach'/'scheduled'/'completed' are still live — only 'closed'
    frees the slot."""
    gap = CareGap.objects.create(patient=patient, guideline=guideline,
                                 due_since=datetime.date(2026, 1, 1))
    gap.status = "scheduled"
    gap.save()

    with pytest.raises(IntegrityError):
        CareGap.objects.create(patient=patient, guideline=guideline,
                               due_since=datetime.date(2026, 2, 1))


def test_admin_counts(patient, guideline):
    gap = CareGap.objects.create(patient=patient, guideline=guideline,
                                 due_since=datetime.date(2026, 1, 1))
    plan = CarePlan.objects.create(patient=patient)
    plan.gaps.add(gap)

    assert ClinicalGuidelineAdmin(ClinicalGuideline, None).gap_count(guideline) == 1
    assert CarePlanAdmin(CarePlan, None).gap_count(plan) == 1
