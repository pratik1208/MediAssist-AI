"""Phase 4 AI plumbing (mocked — conftest blocks real calls): tool schema
strictness, payload wiring, the never-block-on-AI fallback in
render_plan_message, and the code-decides validation in
backfill_events_from_document."""

import datetime
import json
from unittest.mock import patch

import pytest
from django.utils import timezone

from caregaps import services
from caregaps.ai import EXTRACT_CLINICAL_EVENTS, WRITE_CARE_PLAN_MESSAGE
from caregaps.models import CareGap, ClinicalEvent, ClinicalGuideline
from core.models import Patient

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()


@pytest.fixture
def patient(db):
    return Patient.objects.create(
        first_name="Kamala", last_name="Iyer", contact_number="9000000001",
        dob=datetime.date(TODAY.year - 72, 1, 15), preferred_language="ta",
        registration_status="complete",
    )


@pytest.fixture
def plan(patient):
    lab = ClinicalGuideline.objects.create(
        name="HbA1c check", population_criteria={}, care_item_type="test",
        care_item_code="4548-4", frequency_days=182, risk_tier="high")
    screening = ClinicalGuideline.objects.create(
        name="Mammogram", population_criteria={}, care_item_type="screening",
        care_item_code="77067", frequency_days=730, risk_tier="high")
    for g in (lab, screening):
        CareGap.objects.create(patient=patient, guideline=g, due_since=TODAY)
    return services.bundle_care_plan(patient)


class TestToolSchemas:
    def test_write_message_tool_is_strict(self):
        assert WRITE_CARE_PLAN_MESSAGE["name"] == "write_care_plan_message"
        assert WRITE_CARE_PLAN_MESSAGE["strict"] is True
        assert WRITE_CARE_PLAN_MESSAGE["input_schema"]["additionalProperties"] is False
        assert WRITE_CARE_PLAN_MESSAGE["input_schema"]["required"] == ["body"]

    def test_extract_tool_constrains_event_types(self):
        schema = EXTRACT_CLINICAL_EVENTS["input_schema"]
        item_props = schema["properties"]["events"]["items"]["properties"]
        assert set(item_props["event_type"]["enum"]) == {
            "lab", "vaccination", "visit", "procedure", "diagnosis"}
        assert schema["required"] == ["legible", "events"]


class TestRenderPlanMessage:
    def test_success_prepends_greeting_and_saves_body(self, plan):
        with patch("caregaps.ai.call_tool",
                   return_value={"body": "you are due for your HbA1c and mammogram."}) as mocked:
            message = services.render_plan_message(plan)

        assert message == "Hi Kamala, you are due for your HbA1c and mammogram."
        plan.refresh_from_db()
        assert plan.plan_text == "you are due for your HbA1c and mammogram."
        payload = json.loads(mocked.call_args.kwargs["messages"][0]["content"])
        assert payload["shared_visit_items"] == ["HbA1c check"]
        assert payload["separate_items"] == ["Mammogram"]
        assert payload["language"] == "ta"

    def test_ai_failure_falls_back_to_deterministic_text(self, plan):
        deterministic = plan.plan_text
        assert "single visit" in deterministic
        # conftest blocks the real call -> the fallback path runs
        message = services.render_plan_message(plan)
        assert message == f"Hi Kamala, {deterministic}"
        plan.refresh_from_db()
        assert plan.plan_text == deterministic  # untouched on failure

    def test_closed_gaps_are_not_mentioned(self, plan, patient):
        gap = plan.gaps.get(guideline__name="HbA1c check")
        services.close_gap(gap)
        with patch("caregaps.ai.call_tool", return_value={"body": "b"}) as mocked:
            services.render_plan_message(plan)
        payload = json.loads(mocked.call_args.kwargs["messages"][0]["content"])
        assert payload["shared_visit_items"] == []
        assert payload["separate_items"] == ["Mammogram"]


class TestBackfillEvents:
    def _run(self, patient, result):
        with patch("caregaps.ai.call_tool", return_value=result):
            return services.backfill_events_from_document(patient, "fixture text")

    def test_valid_events_created(self, patient):
        result = self._run(patient, {"legible": True, "events": [
            {"event_type": "lab", "code": "4548-4", "date": "2026-05-01",
             "value": {"hba1c": 7.9}},
            {"event_type": "vaccination", "code": "140", "date": "2025-11-10", "value": {}},
        ]})
        assert result == {"created": 2, "skipped": 0, "failed": False}
        lab = ClinicalEvent.objects.get(code="4548-4")
        assert lab.value == {"hba1c": 7.9}
        assert timezone.localtime(lab.occurred_at).date() == datetime.date(2026, 5, 1)

    @pytest.mark.parametrize("bad", [
        {"event_type": "surgery", "code": "X", "date": "2026-01-01", "value": {}},  # unknown type
        {"event_type": "lab", "code": "", "date": "2026-01-01", "value": {}},       # no code
        {"event_type": "lab", "code": "X", "date": None, "value": {}},              # no date
        {"event_type": "lab", "code": "X", "date": "last spring", "value": {}},     # bad date
    ])
    def test_malformed_entries_skipped_never_guessed(self, patient, bad):
        result = self._run(patient, {"legible": True, "events": [bad]})
        assert result == {"created": 0, "skipped": 1, "failed": False}
        assert ClinicalEvent.objects.count() == 0

    def test_illegible_document_creates_nothing(self, patient):
        result = self._run(patient, {"legible": False, "events": [
            {"event_type": "lab", "code": "4548-4", "date": "2026-05-01", "value": {}}]})
        assert result["created"] == 0
        assert ClinicalEvent.objects.count() == 0

    def test_reupload_is_idempotent(self, patient):
        payload = {"legible": True, "events": [
            {"event_type": "lab", "code": "4548-4", "date": "2026-05-01", "value": {}}]}
        assert self._run(patient, payload)["created"] == 1
        again = self._run(patient, payload)
        assert again == {"created": 0, "skipped": 1, "failed": False}
        assert ClinicalEvent.objects.count() == 1

    def test_ai_failure_reports_failed_not_raises(self, patient):
        # conftest's block makes the call raise -> the guard catches it
        result = services.backfill_events_from_document(patient, "text")
        assert result == {"created": 0, "skipped": 0, "failed": True}

    def test_backfilled_event_closes_gap_on_rescan(self, patient):
        """The whole point: extraction feeds the deterministic scanner."""
        ClinicalGuideline.objects.create(
            name="HbA1c", population_criteria={}, care_item_type="test",
            care_item_code="4548-4", frequency_days=182, risk_tier="high")
        services.scan_patient(patient)
        assert CareGap.objects.get().status == "open"

        recent = (TODAY - datetime.timedelta(days=10)).isoformat()
        self._run(patient, {"legible": True, "events": [
            {"event_type": "lab", "code": "4548-4", "date": recent, "value": {}}]})
        result = services.scan_patient(patient)
        assert result["closed"] == 1
        gap = CareGap.objects.get()
        assert gap.status == "closed"
        assert gap.closing_event.code == "4548-4"
