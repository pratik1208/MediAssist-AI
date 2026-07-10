"""Guard rails on SYSTEM_PROMPT: the safety-critical instructions must
survive every future prompt edit. If one of these fails, a required
clinical safety line was weakened or removed — restore it before shipping.
"""

from triage.ai import SYSTEM_PROMPT

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
