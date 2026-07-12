"""20+ real-world reply phrasings must classify correctly against the REAL
model. Misclassifying an opt-out as anything else is the failure mode to
guard hardest against (a patient who said "stop" getting messaged again),
so every opt-out phrasing here is an all-or-nothing assertion.

Run after any prompt/tool change:
    pytest -m live_model outreach/tests/test_classify_response_live.py
Makes real model calls (excluded from the default run by pytest.ini).
"""

import pytest
from django.utils import timezone

from core.ai import call_tool as real_call_tool
from outreach.ai import classify_response

pytestmark = pytest.mark.live_model


@pytest.fixture(autouse=True)
def _real_model(monkeypatch):
    # conftest.py blocks outreach.ai.call_tool by default; restore the real
    # one for this file only (autouse-local wins over the conftest autouse).
    monkeypatch.setattr("outreach.ai.call_tool", real_call_tool)


def _classify(text: str) -> dict:
    return classify_response(text, timezone.localdate().isoformat())


BOOK_PHRASES = [
    "yes ok", "sure, book me in", "sounds good let's schedule it",
    "yes please", "ok book an appointment for me", "I'd like to come in",
]
SNOOZE_PHRASES = [
    "can't till after the 15th", "remind me next month",
    "not right now, ask me again in a few weeks", "call me back in a month",
]
OPT_OUT_PHRASES = [
    "stop texting me", "please leave me alone", "take me off this list",
    "don't contact me again", "I never signed up for this, please stop",
    "unsubscribe me", "quit messaging me", "remove me from your list",
]
QUESTION_PHRASES = [
    "what is this about?", "who is this from?", "is there a cost?",
    "do I need an appointment or can I just walk in?",
]


class TestRealWorldPhraseClassification:
    @pytest.mark.parametrize("text", BOOK_PHRASES)
    def test_book_phrasings(self, text):
        assert _classify(text)["intent"] == "book", text

    @pytest.mark.parametrize("text", SNOOZE_PHRASES)
    def test_snooze_phrasings(self, text):
        result = _classify(text)
        assert result["intent"] == "snooze", text
        # a stated timeframe should resolve to a concrete future date
        assert result["snooze_until"] is not None, text

    @pytest.mark.parametrize("text", OPT_OUT_PHRASES)
    def test_opt_out_phrasings_are_never_misclassified(self, text):
        assert _classify(text)["intent"] == "opt_out", (
            f"OPT-OUT MISCLASSIFIED: {text!r} — this is the worst failure mode"
        )

    @pytest.mark.parametrize("text", QUESTION_PHRASES)
    def test_question_phrasings(self, text):
        assert _classify(text)["intent"] == "question", text

    @pytest.mark.parametrize("text", ["ok", "k", "hmm", "?!"])
    def test_ambiguous_is_never_forced_into_opt_out_or_snooze(self, text):
        # These are genuinely ambiguous; the only hard rule is that we must
        # not fabricate an opt-out or a snooze (both have real side effects)
        # from a non-committal grunt.
        assert _classify(text)["intent"] not in ("opt_out", "snooze"), text
