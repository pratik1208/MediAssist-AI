from unittest.mock import patch

import pytest
from django.utils import timezone

from registration.ai.summary import generate_intake_summary
from registration.models import IntakeSummary
from registration.tests.conftest import DOB

MODEL_RESULT = {
    "clinical_profile": {
        "symptoms": ["headache for 3 days"],
        "medications": ["paracetamol (Panadol)"],
        "allergies": ["penicillin"],
    },
    "summary_text": "Patient reports a headache persisting for three days, "
                    "self-treated with paracetamol. Known allergy to penicillin.",
}


class TestGenerateIntakeSummary:
    def test_fills_profile_and_physician_paragraph(self, rahul):
        raw = IntakeSummary.objects.create(
            patient=rahul,
            clinical_profile={"symptoms": ["headache 3 days"], "medications": ["panadol"]},
            summary_text="",
        )
        with patch("registration.ai.summary.call_tool", return_value=MODEL_RESULT) as mocked:
            summary = generate_intake_summary(rahul)

        # One API call, updating the existing row in place.
        assert mocked.call_count == 1
        assert summary.pk == raw.pk
        raw.refresh_from_db()
        assert raw.summary_text == MODEL_RESULT["summary_text"]
        assert raw.clinical_profile == MODEL_RESULT["clinical_profile"]

    def test_the_raw_intake_is_what_gets_sent_to_the_model(self, rahul):
        IntakeSummary.objects.create(
            patient=rahul, clinical_profile={"symptoms": ["cough"]}, summary_text="",
        )
        with patch("registration.ai.summary.call_tool", return_value=MODEL_RESULT) as mocked:
            generate_intake_summary(rahul)
        sent = mocked.call_args.kwargs["messages"][0]["content"]
        assert "cough" in sent
        expected_age = (timezone.now().date() - DOB).days // 365
        assert str(expected_age) in sent

    def test_uses_the_latest_intake_when_there_are_several(self, rahul):
        IntakeSummary.objects.create(patient=rahul, clinical_profile={"symptoms": ["old"]}, summary_text="done")
        newest = IntakeSummary.objects.create(patient=rahul, clinical_profile={"symptoms": ["new"]}, summary_text="")
        with patch("registration.ai.summary.call_tool", return_value=MODEL_RESULT):
            summary = generate_intake_summary(rahul)
        assert summary.pk == newest.pk

    def test_no_intake_is_a_clear_error(self, rahul):
        with pytest.raises(ValueError, match="No intake recorded"):
            generate_intake_summary(rahul)
