"""The deterministic screen must catch every red-flag phrasing (NFR-3).

These tests are the audit trail for the pre-AI emergency gate: every listed
phrasing MUST trip the screen, with zero model involvement.
"""

import pytest

from triage.services import find_red_flags, red_flag_check

EMERGENCY_PHRASES = [
    # cardiac
    "I have a crushing pain in my chest",
    "chest pain since this morning",
    "there's a pressure in my chest and it spreads to my left arm",
    "chest tightness when I climb stairs",
    # breathing
    "I can't breathe properly",
    "my father is struggling to breathe",
    "shortness of breath at rest",
    "her lips are turning blue",
    "he is choking on something",
    # stroke
    "my mother's face is drooping on one side",
    "he has slurred speech since an hour ago",
    "one side of my body feels weak",
    "she suddenly can't speak",
    # mental health crisis
    "I want to end my life",
    "I've been having suicidal thoughts",
    "I am going to kill myself",
    "I want to hurt myself",
    # consciousness / neuro
    "my son is unconscious",
    "she is unresponsive and won't wake up",
    "he had a seizure a few minutes ago",
    # bleeding
    "there is heavy bleeding from the wound",
    "the cut is bleeding and won't stop",
    "she is vomiting blood",
    "uncontrolled bleeding after the fall",
    # poisoning / allergy
    "I think he took an overdose",
    "my daughter swallowed bleach",
    "his throat is swelling shut",
    "she's having an anaphylactic reaction",
]

ROUTINE_PHRASES = [
    "I have a mild headache since yesterday",
    "my child has a runny nose and a slight cough",
    "I need a refill for my blood pressure medication",
    "there is a small rash on my elbow",
    "I twisted my ankle playing football",
    "I've had a low fever and a sore throat for two days",
    "my knee hurts when I walk long distances",
    "",  # empty input must not crash or trigger
]


class TestRedFlagCheck:
    @pytest.mark.parametrize("phrase", EMERGENCY_PHRASES)
    def test_every_emergency_phrase_trips_the_screen(self, phrase):
        assert red_flag_check(phrase) is True

    @pytest.mark.parametrize("phrase", ROUTINE_PHRASES)
    def test_routine_complaints_pass_through(self, phrase):
        assert red_flag_check(phrase) is False

    def test_case_insensitive(self):
        assert red_flag_check("CHEST PAIN AND SWEATING")
        assert red_flag_check("Suicidal Thoughts")

    def test_none_input_is_safe(self):
        assert red_flag_check(None) is False

    def test_find_red_flags_names_the_matches_for_the_audit_trail(self):
        matches = find_red_flags("crushing pain in my chest and I can't breathe")
        assert len(matches) >= 2  # cardiac + breathing patterns both identified

    def test_find_red_flags_empty_when_clean(self):
        assert find_red_flags("mild headache") == []
