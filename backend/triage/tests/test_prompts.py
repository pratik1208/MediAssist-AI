"""Guard rails on SYSTEM_PROMPT: the safety-critical instructions must
survive every future prompt edit. If one of these fails, a required
clinical safety line was weakened or removed — restore it before shipping.
"""

from triage.ai import SYSTEM_PROMPT, TRIAGE_STEP
from triage.services import ACUITY_ORDER

# Whitespace-normalized so line wrapping in the prompt never breaks a check.
PROMPT = " ".join(SYSTEM_PROMPT.split())


class TestTriageSystemPrompt:
    def test_one_question_at_a_time(self):
        assert "ONE question per message" in PROMPT

    def test_supports_but_never_replaces_clinical_judgment(self):
        assert "SUPPORT clinical decision-making" in PROMPT
        assert "never replace" in PROMPT

    def test_never_diagnoses(self):
        assert "NEVER diagnose" in PROMPT

    def test_defers_to_caution_on_acuity(self):
        assert "uncertain between two acuity levels" in PROMPT
        assert "HIGHER" in PROMPT

    def test_emergency_short_circuit(self):
        assert "emergency_detected" in PROMPT
        assert "stop asking questions" in PROMPT

    def test_plain_language(self):
        assert "plain language" in PROMPT

    def test_no_volatile_data_in_the_prompt(self):
        # Protocol JSON / findings go in messages so prompt caching works;
        # nothing patient- or protocol-specific may leak into the constant.
        for marker in ("{", "}", "question_flow", "disposition_rules"):
            assert marker not in SYSTEM_PROMPT


class TestTriageStepTool:
    SCHEMA = TRIAGE_STEP["input_schema"]

    def test_is_strict(self):
        assert TRIAGE_STEP["strict"] is True
        assert self.SCHEMA["additionalProperties"] is False

    def test_every_top_level_field_is_required(self):
        # Strict contract: "unknown" is null, never an omitted key.
        assert set(self.SCHEMA["required"]) == {
            "extracted_findings", "emergency_detected", "next_question",
            "assessment_complete", "suggested_acuity", "rationale",
        }
        assert set(self.SCHEMA["required"]) == set(self.SCHEMA["properties"])

    def test_findings_cover_the_spec_attributes_and_are_nullable(self):
        findings = self.SCHEMA["properties"]["extracted_findings"]
        expected = {"onset", "severity_1_10", "location", "radiation",
                    "associated_symptoms"}
        assert set(findings["properties"]) == expected
        assert set(findings["required"]) == expected
        for prop in findings["properties"].values():
            assert "null" in prop["type"]

    def test_next_question_is_nullable(self):
        assert self.SCHEMA["properties"]["next_question"]["type"] == ["string", "null"]

    def test_acuity_enum_matches_the_rule_engine(self):
        # The tool vocabulary and services.ACUITY_ORDER must never drift apart.
        assert self.SCHEMA["properties"]["suggested_acuity"]["enum"] == ACUITY_ORDER


class TestLangSmithTracing:
    """Every AI entry point must be a traced span — removing a @traceable
    decorator breaks observability silently, so these tests make it loud."""

    def test_triage_operations_are_traced_chains(self):
        from langsmith.run_helpers import is_traceable_function

        from triage import ai
        assert is_traceable_function(ai.handle_triage_message)
        assert is_traceable_function(ai.generate_triage_summary)

    def test_provider_calls_are_traced_llm_runs(self):
        from langsmith.run_helpers import is_traceable_function

        from core.ai.anthropic_client import call_tool_anthropic
        from core.ai.ollama_client import call_tool_ollama
        from core.ai.openai_client import call_tool_openai
        assert is_traceable_function(call_tool_openai)
        assert is_traceable_function(call_tool_anthropic)
        assert is_traceable_function(call_tool_ollama)
