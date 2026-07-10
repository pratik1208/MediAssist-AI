"""handle_triage_message — the two-layer safety orchestration, model mocked."""

from unittest.mock import patch

import pytest
from django.core.management import call_command

from core.models import EventLog
from triage.ai import SYSTEM_PROMPT, generate_triage_summary, handle_triage_message
from triage.models import EscalationAlert, TriageAssessment
from triage.services import escalate
from triage.tests.test_services import make_assessment, make_patient


@pytest.fixture
def seeded(db):
    call_command("seed_protocols", verbosity=0)


def make_step(**overrides):
    """A schema-valid triage_step output with calm defaults."""
    step = {
        "extracted_findings": {
            "onset": None, "severity_1_10": None, "location": None,
            "radiation": None, "associated_symptoms": None,
        },
        "emergency_detected": False,
        "next_question": "On a scale of 1 to 10, how bad is it?",
        "assessment_complete": False,
        "suggested_acuity": "low",
        "rationale": "Mild symptoms so far.",
    }
    step.update(overrides)
    return step


def turn(assessment, message, step=None):
    history = [{"role": "user", "content": message}]
    with patch("triage.ai.call_tool", return_value=step or make_step()) as model:
        result = handle_triage_message(assessment, history)
    return result, model


class TestLayerOneRedFlagGate:
    def test_red_flag_escalates_without_asking_the_model(self, seeded):
        assessment = make_assessment(make_patient(30), "Headache", {})
        # escalate() legitimately calls the summary generator; the invariant
        # here is that no triage_step INTERVIEW call ever happens.
        with patch("triage.ai.generate_triage_summary",
                   side_effect=RuntimeError("no summary in this test")):
            result, model = turn(assessment, "and now my face is drooping")
        model.assert_not_called()  # the interview model is NEVER consulted
        assert result == {"complete": True, "emergency": True,
                          "acuity": "emergency", "disposition": "ed_now",
                          "next_question": None}
        assert EscalationAlert.objects.filter(assessment=assessment).exists()
        assessment.refresh_from_db()
        assert assessment.status == "escalated"


class TestModelTurn:
    def test_prompt_is_stable_and_protocol_context_is_a_message(self, seeded):
        assessment = make_assessment(make_patient(30), "Headache", {})
        _, model = turn(assessment, "my head hurts")
        kwargs = model.call_args.kwargs
        assert kwargs["system"] == SYSTEM_PROMPT  # nothing volatile appended
        context = kwargs["messages"][0]["content"]
        assert "Headache" in context and "Clinic system note" in context
        assert kwargs["messages"][1] == {"role": "user", "content": "my head hurts"}
        assert kwargs["tool"]["name"] == "triage_step"

    def test_non_null_findings_merge_and_null_never_erases(self, seeded):
        assessment = make_assessment(make_patient(30), "Headache",
                                     {"onset": "yesterday evening"})
        step = make_step(extracted_findings={
            "onset": None,  # unknown this turn — must not erase yesterday's
            "severity_1_10": 6, "location": "behind the eyes",
            "radiation": None, "associated_symptoms": ["nausea"],
        })
        result, _ = turn(assessment, "about a 6, behind my eyes, bit nauseous", step)
        assessment.refresh_from_db()
        assert assessment.findings["onset"] == "yesterday evening"
        assert assessment.findings["severity_1_10"] == 6
        assert assessment.findings["suggested_acuity"] == "low"
        assert result == {"complete": False, "emergency": False,
                          "next_question": "On a scale of 1 to 10, how bad is it?"}

    def test_list_findings_accumulate_without_duplicates(self, seeded):
        assessment = make_assessment(make_patient(30), "Headache",
                                     {"associated_symptoms": ["nausea"]})
        step = make_step(extracted_findings={
            "onset": None, "severity_1_10": None, "location": None,
            "radiation": None, "associated_symptoms": ["nausea", "dizziness"],
        })
        turn(assessment, "also feeling dizzy", step)
        assessment.refresh_from_db()
        assert assessment.findings["associated_symptoms"] == ["nausea", "dizziness"]

    def test_model_detected_emergency_takes_the_escalation_path(self, seeded):
        assessment = make_assessment(make_patient(30), "Headache", {})
        step = make_step(emergency_detected=True, next_question=None,
                         suggested_acuity="emergency")
        result, _ = turn(assessment, "my left arm feels heavy and I'm sweating", step)
        assert result["emergency"] is True
        assert EscalationAlert.objects.filter(assessment=assessment).exists()


class TestCompletion:
    def complete_step(self, findings, suggested):
        return make_step(assessment_complete=True, next_question=None,
                         suggested_acuity=suggested,
                         extracted_findings=findings)

    def test_rules_decide_model_cannot_lower(self, seeded):
        assessment = make_assessment(make_patient(25), "Adult Chest Pain", {})
        step = self.complete_step(
            {"onset": "this morning", "severity_1_10": 8, "location": "chest",
             "radiation": None, "associated_symptoms": None},
            suggested="minimal",  # the model tries to talk it down
        )
        result, _ = turn(assessment, "severity 8", step)
        assert result["acuity"] == "high"  # severity>=7 rule wins
        assessment.refresh_from_db()
        assert assessment.status == "completed"

    def test_model_suggestion_can_raise_the_rule_result(self, seeded):
        assessment = make_assessment(make_patient(25), "Adult Chest Pain", {})
        step = self.complete_step(
            {"onset": "this morning", "severity_1_10": 5, "location": "chest",
             "radiation": None, "associated_symptoms": None},
            suggested="high",  # rules alone say medium
        )
        result, _ = turn(assessment, "severity 5 but something feels wrong", step)
        assert result["acuity"] == "high"

    def test_completion_routes_downstream(self, seeded):
        assessment = make_assessment(make_patient(25), "Headache", {})
        step = self.complete_step(
            {"onset": "gradual", "severity_1_10": 2, "location": "temples",
             "radiation": None, "associated_symptoms": None},
            suggested="low",
        )
        result, _ = turn(assessment, "just a mild ache", step)
        assert result["disposition"] == "routine"
        event = EventLog.objects.filter(name="triage.disposition").latest("id")
        assert event.payload["route_to"] == "scheduling"

    def test_rule_emergency_at_completion_escalates(self, seeded):
        assessment = make_assessment(make_patient(30), "Headache", {})
        step = self.complete_step(
            # "sudden" onset is a protocol red-flag finding
            {"onset": "sudden, within seconds", "severity_1_10": 6,
             "location": "whole head", "radiation": None,
             "associated_symptoms": None},
            suggested="medium",
        )
        result, _ = turn(assessment, "it hit me all at once", step)
        assert result["emergency"] is True
        assert EscalationAlert.objects.filter(assessment=assessment).exists()


NARRATIVE = {
    "presenting_symptoms": "Severe chest pain, onset this morning, radiating to the left arm.",
    "risk_assessment": "70-year-old with documented cardiac history.",
    "summary_text": "Patient reports severe chest pain since this morning radiating "
                    "to the left arm. Cardiac history on record. Acuity emergency; "
                    "directed to the emergency department.",
}


class TestGenerateTriageSummary:
    def completed_assessment(self):
        assessment = make_assessment(
            make_patient(70), "Adult Chest Pain",
            {"onset": "this morning", "severity_1_10": 9, "radiation": "left arm"},
        )
        assessment.status = "completed"
        assessment.acuity = "high"
        assessment.disposition = "same_day"
        assessment.save()
        return assessment

    def test_structured_summary_facts_come_from_the_assessment(self, seeded):
        assessment = self.completed_assessment()
        with patch("triage.ai.call_tool", return_value=NARRATIVE) as model:
            summary = generate_triage_summary(assessment)

        # narrative from the model, facts stamped by code
        assert summary["presenting_symptoms"] == NARRATIVE["presenting_symptoms"]
        assert summary["risk_assessment"] == NARRATIVE["risk_assessment"]
        assert summary["acuity"] == "high"
        assert summary["recommended_action"] == "Same-day appointment"
        assert summary["transcript_reference"] == {
            "conversation_id": assessment.conversation_id,
            "assessment_id": assessment.id,
        }
        # the model saw the findings and the patient's risk factors
        sent = model.call_args.kwargs["messages"][0]["content"]
        assert "left arm" in sent and "age_gte_65" in sent

    def test_narrative_is_saved_on_the_assessment(self, seeded):
        assessment = self.completed_assessment()
        with patch("triage.ai.call_tool", return_value=NARRATIVE):
            generate_triage_summary(assessment)
        assessment.refresh_from_db()
        assert assessment.summary_text == NARRATIVE["summary_text"]

    def test_escalate_uses_the_ai_summary_when_available(self, seeded):
        assessment = self.completed_assessment()
        with patch("triage.ai.call_tool", return_value=NARRATIVE):
            alert = escalate(assessment)
        assert alert.summary == NARRATIVE["summary_text"]

    def test_escalate_falls_back_when_the_model_fails(self, seeded):
        # conftest blocks real AI calls -> generate_triage_summary raises ->
        # the alert must still be created, with the deterministic text.
        assessment = make_assessment(
            make_patient(30), "Headache", {"severity_1_10": 9})
        assessment.summary_text = ""
        alert = escalate(assessment)
        assert "Red-flag escalation" in alert.summary
        assert EscalationAlert.objects.filter(id=alert.id).exists()