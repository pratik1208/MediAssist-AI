"""The timeframe parser gets the patient's own words — it must handle loose
phrasing, and the handler must turn anything unparseable into a question."""

import datetime
from unittest.mock import patch

import pytest
from django.utils import timezone

from scheduling.ai.handler import handle_patient_message
from scheduling.ai.time_parser import parse_preferred_timeframe

TODAY = timezone.localtime().date()
TOMORROW = TODAY + datetime.timedelta(days=1)


class TestParsePreferredTimeframe:
    def test_empty_means_no_window(self):
        assert parse_preferred_timeframe(None) == (None, None)
        assert parse_preferred_timeframe("") == (None, None)

    def test_exact_phrases_still_work(self):
        start, end = parse_preferred_timeframe("tomorrow morning")
        assert (start.date(), start.time()) == (TOMORROW, datetime.time(8, 0))
        assert end.time() == datetime.time(12, 0)

    @pytest.mark.parametrize("phrase", [
        "sometime tomorrow morning please",
        "Tomorrow Morning",
        "tomorrow, in the morning if possible",
    ])
    def test_loose_phrasing_around_tomorrow_morning(self, phrase):
        start, end = parse_preferred_timeframe(phrase)
        assert start.date() == TOMORROW
        assert (start.time(), end.time()) == (datetime.time(8, 0), datetime.time(12, 0))

    def test_asap_means_today(self):
        start, end = parse_preferred_timeframe("as soon as possible")
        assert start.date() == TODAY
        assert end.date() == TODAY

    def test_weekday_is_the_next_occurrence(self):
        start, end = parse_preferred_timeframe("monday afternoon")
        assert start.date().weekday() == 0
        assert start.date() > TODAY  # never in the past
        assert (start.time(), end.time()) == (datetime.time(12, 0), datetime.time(17, 0))

    def test_next_week_spans_monday_to_sunday(self):
        start, end = parse_preferred_timeframe("next week")
        assert start.date().weekday() == 0
        assert end.date().weekday() == 6
        assert start.date() > TODAY

    def test_this_week_runs_to_sunday(self):
        start, end = parse_preferred_timeframe("later this week")
        assert start.date() == TODAY
        assert end.date().weekday() == 6

    def test_gibberish_raises(self):
        with pytest.raises(ValueError):
            parse_preferred_timeframe("whenever the stars align")


class TestHandlerTimeframeSafetyNet:
    def test_unparseable_timeframe_becomes_a_question_not_a_500(self):
        intent = {
            "symptom": "mild rash",
            "urgency": "low",
            "specialty": "Dermatology",
            "preferred_timeframe": "whenever the stars align",
            "needs_clarification": False,
        }
        with patch("scheduling.ai.handler.extract_intent", return_value=intent):
            result = handle_patient_message(
                [{"role": "user", "content": "I have a mild rash"}]
            )
        assert result["type"] == "clarification"
        assert "tomorrow morning" in result["message"]
