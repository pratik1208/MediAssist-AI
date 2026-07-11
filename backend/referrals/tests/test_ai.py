"""Guards on the referral AI layer: tool schemas, tracing, the
never-block-the-package fallback, and the FR-F2 mixed-history exit test."""

import datetime
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from core.models import Doctor, Patient, Specialty
from referrals import services
from referrals.ai import EXTRACT_CONSULTATION_REPORT, SELECT_REFERRAL_CONTENT
from referrals.models import ConsultationReport, Referral, Specialist
from refills.models import Prescription
from registration.models import IntakeSummary, UploadedDocument


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
def referral(db, patient, doctor):
    return Referral.objects.create(
        patient=patient, referring_doctor=doctor, specialty_needed=Specialty.CARDIOLOGY,
        reason="chest pain on exertion", urgency="routine", status="created",
    )


@pytest.fixture
def specialist(db):
    return Specialist.objects.create(
        name="Dr. Rohan Kulkarni", practice_name="Pune Heart Institute",
        specialty=Specialty.CARDIOLOGY, contact_channel="phone",
    )


class TestSelectReferralContentTool:
    SCHEMA = SELECT_REFERRAL_CONTENT["input_schema"]

    def test_is_strict_and_fully_required(self):
        assert SELECT_REFERRAL_CONTENT["strict"] is True
        assert self.SCHEMA["additionalProperties"] is False
        assert set(self.SCHEMA["required"]) == {"selected_item_ids", "summary_text"}


class TestExtractConsultationReportTool:
    SCHEMA = EXTRACT_CONSULTATION_REPORT["input_schema"]

    def test_is_strict_and_fully_required(self):
        assert EXTRACT_CONSULTATION_REPORT["strict"] is True
        assert set(self.SCHEMA["required"]) == set(self.SCHEMA["properties"]) == {
            "diagnosis", "treatment_plan", "medications", "followup_recommendations", "legible",
        }

    def test_unknowns_are_null_not_omitted(self):
        for field in ("diagnosis", "treatment_plan", "medications", "followup_recommendations"):
            assert "null" in self.SCHEMA["properties"][field]["type"]


class TestTracing:
    def test_ai_entry_points_are_traced_chains(self):
        from langsmith.run_helpers import is_traceable_function

        from referrals import ai
        assert is_traceable_function(ai.select_referral_content)
        assert is_traceable_function(ai.extract_consultation_report_fields)


def _mixed_history_setup(patient, doctor):
    """A fixture patient with mixed history (build step's exact exit test):
    a cardiology-relevant BP note sitting alongside an unrelated dermatology
    note, plus an ECG, a lipid panel, and an active medication."""
    IntakeSummary.objects.create(
        patient=patient,
        clinical_profile={
            "medical_history": [
                "Hypertension, BP averaging 150/95 over the last 3 visits",
                "Benign mole excised 2019, dermatology follow-up not required",
            ],
        },
        summary_text="",
    )
    Prescription.objects.create(
        patient=patient, prescriber=doctor, medication_name="Atenolol", dose="25mg",
        quantity="30 tablets", refills_allowed=3, refills_used=0,
        prescribed_date=datetime.date.today(),
        expiry_date=datetime.date.today() + datetime.timedelta(days=300),
        status="active",
    )
    ecg = UploadedDocument.objects.create(
        patient=patient, document_type="lab_report", extraction_status="done",
        extracted_data={"lab_report": {"test_name": "ECG", "findings": "normal sinus rhythm",
                                       "date": "2026-01-01"}},
    )
    lipids = UploadedDocument.objects.create(
        patient=patient, document_type="lab_report", extraction_status="done",
        extracted_data={"lab_report": {"test_name": "Lipid Panel", "findings": "LDL 160 mg/dL, elevated",
                                       "date": "2026-01-01"}},
    )
    return ecg, lipids


class TestBuildReferralPackage:
    def test_cardiology_package_excludes_the_unrelated_dermatology_note(
        self, patient, doctor, referral,
    ):
        ecg, lipids = _mixed_history_setup(patient, doctor)
        items = services._collect_chart_items(patient)
        bp_id = next(i["id"] for i in items if "Hypertension" in i["text"])
        derm_id = next(i["id"] for i in items if "dermatology" in i["text"])
        ecg_id = next(i["id"] for i in items if i["category"] == "lab_report" and "ECG" in i["text"])
        lipid_id = next(i["id"] for i in items if i["category"] == "lab_report" and "Lipid" in i["text"])
        med_id = next(i["id"] for i in items if i["category"] == "medication")

        with patch("referrals.ai.call_tool", return_value={
            "selected_item_ids": [bp_id, ecg_id, lipid_id, med_id],
            "summary_text": "Cardiology referral: hypertension with elevated LDL, on atenolol; ECG normal.",
        }):
            package = services.build_referral_package(referral)

        selected_ids = {item["id"] for item in package.selected_chart_data["items"]}
        assert selected_ids == {bp_id, ecg_id, lipid_id, med_id}
        assert derm_id not in selected_ids
        assert set(package.attached_documents) == {ecg.id, lipids.id}
        assert "hypertension" in package.summary_text.lower()

    def test_ai_failure_falls_back_to_attaching_everything(self, patient, doctor, referral):
        _mixed_history_setup(patient, doctor)
        # conftest blocks the model -> the never-block fallback attaches
        # every known item rather than leaving the package empty.
        package = services.build_referral_package(referral)
        items = services._collect_chart_items(patient)
        assert {item["id"] for item in package.selected_chart_data["items"]} == {i["id"] for i in items}
        assert "AI summary unavailable" in package.summary_text

    def test_model_hallucinated_id_is_dropped_not_trusted(self, patient, doctor, referral):
        _mixed_history_setup(patient, doctor)
        with patch("referrals.ai.call_tool", return_value={
            "selected_item_ids": ["not-a-real-id"], "summary_text": "x",
        }):
            package = services.build_referral_package(referral)
        assert package.selected_chart_data["items"] == []
        assert package.attached_documents == []


class TestParseConsultationReport:
    def test_extracts_and_feeds_close_loop(self, patient, referral, settings, tmp_path):
        settings.MEDIA_ROOT = tmp_path
        referral.status = "visit_completed"
        referral.save(update_fields=["status"])
        document = UploadedDocument.objects.create(
            patient=patient, document_type="consultation_report",
            file=SimpleUploadedFile("report.png", b"png-bytes", "image/png"),
        )
        with patch("referrals.ai.call_tool", return_value={
            "diagnosis": "Stable angina", "treatment_plan": "atenolol 25mg daily",
            "medications": ["atenolol 25mg"], "followup_recommendations": ["repeat ECG in 3 months"],
            "legible": True,
        }):
            report_data = services.parse_consultation_report(document)
        document.refresh_from_db()
        assert document.extraction_status == "done"
        report = services.close_loop(referral, report_data)
        assert report.diagnosis == "Stable angina"
        assert report.source_document_id == document.id

    def test_illegible_report_raises_instead_of_closing_with_garbage(
        self, patient, referral, settings, tmp_path,
    ):
        settings.MEDIA_ROOT = tmp_path
        document = UploadedDocument.objects.create(
            patient=patient, document_type="consultation_report",
            file=SimpleUploadedFile("report.png", b"png-bytes", "image/png"),
        )
        with patch("referrals.ai.call_tool", return_value={
            "diagnosis": None, "treatment_plan": None, "medications": None,
            "followup_recommendations": None, "legible": False,
        }):
            with pytest.raises(ValueError, match="could not be read reliably"):
                services.parse_consultation_report(document)
        document.refresh_from_db()
        assert document.extraction_status == "failed"
        assert not ConsultationReport.objects.filter(referral=referral).exists()

    def test_hard_extraction_failure_never_closes_the_loop(self, patient, referral, settings, tmp_path):
        settings.MEDIA_ROOT = tmp_path
        document = UploadedDocument.objects.create(
            patient=patient, document_type="consultation_report",
            file=SimpleUploadedFile("report.png", b"png-bytes", "image/png"),
        )
        with patch("referrals.ai.call_tool", side_effect=RuntimeError("provider down")):
            with pytest.raises(RuntimeError):
                services.parse_consultation_report(document)
        document.refresh_from_db()
        assert document.extraction_status == "failed"


class TestSpecialistOutreach:
    def test_queues_a_templated_message_per_channel(self, referral, specialist):
        task = services.queue_specialist_outreach(referral, specialist)
        assert task.status == "queued"
        assert task.channel == "phone"
        assert "Pune Heart Institute" in task.message
        assert referral.patient.first_name in task.message

    def test_mark_sent_and_failed(self, referral, specialist):
        task = services.queue_specialist_outreach(referral, specialist)
        services.mark_outreach_sent(task)
        task.refresh_from_db()
        assert task.status == "sent"
        assert task.sent_at is not None

        task2 = services.queue_specialist_outreach(referral, specialist)
        services.mark_outreach_failed(task2)
        task2.refresh_from_db()
        assert task2.status == "failed"

    def test_falls_back_to_the_email_template_for_an_unmapped_channel(self, referral):
        # contact_channel choices aren't DB-enforced, so a bad/legacy value
        # must still degrade gracefully rather than raising a KeyError.
        weird = Specialist.objects.create(
            name="Dr. Legacy", specialty=Specialty.CARDIOLOGY, contact_channel="fax",
        )
        task = services.queue_specialist_outreach(referral, weird)
        assert "reply to confirm" in task.message
