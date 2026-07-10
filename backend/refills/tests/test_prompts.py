"""Guards on the refill AI layer: tool schemas, tracing, and the
never-block-the-queue fallback."""

import datetime
from unittest.mock import patch

import pytest

from core.models import Doctor, Patient
from refills import services
from refills.ai import EXTRACT_REFILL_INTENT, SUMMARIZE_FOR_PHYSICIAN
from refills.models import Pharmacy
from refills.tests.test_eligibility import make_request, make_rx


class TestExtractRefillIntentTool:
    SCHEMA = EXTRACT_REFILL_INTENT["input_schema"]

    def test_is_strict_and_fully_required(self):
        assert EXTRACT_REFILL_INTENT["strict"] is True
        assert self.SCHEMA["additionalProperties"] is False
        assert set(self.SCHEMA["required"]) == set(self.SCHEMA["properties"]) == {
            "medication_stated", "dose_stated", "quantity_stated",
            "pharmacy_stated", "needs_clarification",
        }

    def test_unknowns_are_null_not_omitted(self):
        for field in ("medication_stated", "dose_stated", "quantity_stated",
                      "pharmacy_stated"):
            assert "null" in self.SCHEMA["properties"][field]["type"]

    def test_description_forbids_guessing(self):
        assert "NEVER substitute" in EXTRACT_REFILL_INTENT["description"]


class TestSummarizeTool:
    def test_is_strict_with_summary_text(self):
        assert SUMMARIZE_FOR_PHYSICIAN["strict"] is True
        assert SUMMARIZE_FOR_PHYSICIAN["input_schema"]["required"] == ["summary_text"]


class TestTracing:
    def test_ai_entry_points_are_traced_chains(self):
        from langsmith.run_helpers import is_traceable_function

        from refills import ai
        assert is_traceable_function(ai.extract_refill_intent)
        assert is_traceable_function(ai.summarize_for_physician)


@pytest.fixture
def pending_request(db):
    patient = Patient.objects.create(
        first_name="Rahul", last_name="Sharma", contact_number="9876543210",
        dob=datetime.date(1990, 5, 17))
    doctor = Doctor.objects.create(name="Dr. Mehta", specialty="General Medicine")
    pharmacy = Pharmacy.objects.create(name="Apollo")
    return make_request(make_rx(patient, doctor), pharmacy)


class TestPhysicianSummaryWiring:
    def test_ai_summary_lands_on_the_request(self, pending_request):
        with patch("refills.ai.call_tool",
                   return_value={"summary_text": "Stable on amlodipine 2 months; adherence unknown; 4 refills left."}):
            services.run_eligibility_check(pending_request)
        pending_request.refresh_from_db()
        assert pending_request.status == "pending_approval"
        assert pending_request.summary_text.startswith("Stable on amlodipine")

    def test_ai_failure_falls_back_and_never_blocks_the_queue(self, pending_request):
        # conftest blocks the model -> the deterministic fallback line is used
        services.run_eligibility_check(pending_request)
        pending_request.refresh_from_db()
        assert pending_request.status == "pending_approval"
        assert "Amlodipine 5 mg" in pending_request.summary_text
        assert "refills remaining: 4" in pending_request.summary_text
