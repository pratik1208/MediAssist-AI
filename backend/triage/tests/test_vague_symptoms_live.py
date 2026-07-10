"""Vague-symptom suite: ambiguous input must produce a follow-up question,
never a guessed finding and never a premature completion.

Run after prompt/tool changes:  pytest -m live_model triage/tests/test_vague_symptoms_live.py
Makes real model calls (excluded from the default run by pytest.ini).
"""

import pytest
from django.core.management import call_command

from core.ai import call_tool as real_call_tool
from triage.ai import handle_triage_message
from triage.tests.test_services import make_assessment, make_patient

pytestmark = pytest.mark.live_model

# (protocol, vague opener) — none of these state a severity number, a
# concrete onset, or an emergency; the only correct move is to ask.
VAGUE_OPENERS = [
    ("Headache", "my head just feels weird sometimes"),
    ("Headache", "it hurts a bit, I don't know, on and off I guess"),
    ("Abdominal Pain", "my stomach has been off lately"),
    ("Abdominal Pain", "something doesn't feel right in my belly"),
    ("Pediatric Fever", "my daughter seems a little warm and cranky"),
    ("Headache", "I've been feeling generally unwell for a while now"),
]


@pytest.fixture
def seeded(db):
    call_command("seed_protocols", verbosity=0)


@pytest.fixture(autouse=True)
def _real_model(monkeypatch):
    monkeypatch.setattr("triage.ai.call_tool", real_call_tool)


class TestVagueInputGetsAFollowUpNeverAGuess:
    @pytest.mark.parametrize("protocol, opener", VAGUE_OPENERS)
    def test_asks_instead_of_guessing(self, seeded, protocol, opener):
        assessment = make_assessment(make_patient(35), protocol, {})
        result = handle_triage_message(
            assessment, [{"role": "user", "content": opener}]
        )

        # must keep interviewing, with a real question
        assert result["complete"] is False, (
            f"PREMATURE COMPLETION on vague input: {opener!r} -> {result}"
        )
        assert result["emergency"] is False
        assert result["next_question"], "a vague answer demands a follow-up question"
        assert result["next_question"].strip().endswith("?")

        # and must not have invented hard findings the patient never stated
        assessment.refresh_from_db()
        assert assessment.findings.get("severity_1_10") is None, (
            f"GUESSED a severity from: {opener!r}"
        )
