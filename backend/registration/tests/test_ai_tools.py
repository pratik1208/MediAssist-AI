from registration.ai.tools import (
    EXTRACT_DOCUMENT_DATA_TOOL,
    NEXT_QUESTION_TOPICS,
    RECORD_REGISTRATION_DATA_TOOL,
)
from registration.models import UploadedDocument


class TestRecordRegistrationDataSchema:
    def test_is_strict_with_closed_schema(self):
        assert RECORD_REGISTRATION_DATA_TOOL["strict"] is True
        assert RECORD_REGISTRATION_DATA_TOOL["input_schema"]["additionalProperties"] is False

    def test_only_control_fields_are_required(self):
        # Data fields must all be optional — the patient provides them in any order.
        assert RECORD_REGISTRATION_DATA_TOOL["input_schema"]["required"] == [
            "next_question_topic", "registration_complete",
        ]

    def test_next_question_topic_is_a_closed_enum(self):
        prop = RECORD_REGISTRATION_DATA_TOOL["input_schema"]["properties"]["next_question_topic"]
        assert prop["enum"] == NEXT_QUESTION_TOPICS
        assert "none" in prop["enum"]

    def test_covers_the_fr_r5_intake_areas(self):
        props = RECORD_REGISTRATION_DATA_TOOL["input_schema"]["properties"]
        for field in ["symptoms", "medical_history", "medications",
                      "allergies", "family_history", "lifestyle"]:
            assert field in props


class TestExtractDocumentDataSchema:
    def test_is_strict_with_closed_schema(self):
        assert EXTRACT_DOCUMENT_DATA_TOOL["strict"] is True
        assert EXTRACT_DOCUMENT_DATA_TOOL["input_schema"]["additionalProperties"] is False

    def test_document_types_match_the_model_choices(self):
        schema_types = set(
            EXTRACT_DOCUMENT_DATA_TOOL["input_schema"]["properties"]["document_type"]["enum"]
        )
        model_types = {value for value, _ in
                       UploadedDocument._meta.get_field("document_type").choices}
        assert schema_types == model_types

    def test_insurance_and_lab_report_fields_from_the_spec(self):
        props = EXTRACT_DOCUMENT_DATA_TOOL["input_schema"]["properties"]
        assert set(props["insurance"]["properties"]) == {
            "provider", "policy_number", "member_id", "coverage_start", "coverage_end",
        }
        assert set(props["lab_report"]["properties"]) == {
            "test_name", "date", "findings", "physician",
        }
