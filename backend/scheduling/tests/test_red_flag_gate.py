"""PRD Edge Case 11: emergency symptoms mentioned mid-scheduling must trip
the deterministic red-flag path — before and independently of the model."""

from unittest.mock import patch

import pytest

from scheduling.ai.handler import EMERGENCY_RESPONSE, handle_patient_message

EMERGENCY_PHRASES = [
    "actually I'm having crushing chest pain right now",
    "wait, my father can't breathe",
    "her speech is slurred all of a sudden, forget the appointment",
    "I want to end my life",
]


class TestSchedulingRedFlagGate:
    @pytest.mark.parametrize("phrase", EMERGENCY_PHRASES)
    def test_red_flag_short_circuits_before_the_model(self, phrase):
        history = [
            {"role": "user", "content": "I want to book an appointment"},
            {"role": "assistant", "content": "Sure — what brings you in?"},
            {"role": "user", "content": phrase},
        ]
        with patch("scheduling.ai.handler.extract_intent") as model:
            result = handle_patient_message(history)
        model.assert_not_called()  # the model is never consulted on a red flag
        assert result == [{"type": "emergency", "message": EMERGENCY_RESPONSE}]

    def test_routine_booking_still_reaches_the_model(self):
        history = [{"role": "user", "content": "I need a skin checkup next week"}]
        with patch("scheduling.ai.handler.extract_intent",
                   return_value={"needs_clarification": True}) as model:
            result = handle_patient_message(history)
        model.assert_called_once()
        assert result[0]["type"] == "clarification"

    def test_empty_history_is_safe(self):
        with patch("scheduling.ai.handler.extract_intent",
                   return_value={"needs_clarification": True}):
            assert handle_patient_message([])[0]["type"] == "clarification"
