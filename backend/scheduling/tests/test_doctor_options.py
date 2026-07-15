"""A slot search offers a choice of doctors, not just one doctor's times:
one "slots" event per doctor of the matched specialty (capped), skipping
doctors with nothing open in the window."""

from unittest.mock import patch

import pytest

from core.models import Doctor, Specialty
from scheduling.ai.handler import MAX_DOCTOR_OPTIONS, handle_patient_message

INTENT = {
    "symptom": "routine heart checkup",
    "urgency": "low",
    "specialty": "Cardiology",
    "preferred_timeframe": "tomorrow morning",
    "needs_clarification": False,
}

# Deliberately mild wording — anything like "chest pain" would trip the
# deterministic red-flag screen before the mocked model is ever consulted.
HISTORY = [{"role": "user", "content": "routine heart checkup, tomorrow morning please"}]

FAKE_SLOT = [("2026-07-16T09:00:00", "2026-07-16T09:20:00")]


def make_cardiologists(n):
    return [Doctor.objects.create(name=f"Dr. Cardio {i}", specialty=Specialty.CARDIOLOGY)
            for i in range(n)]


class TestDoctorOptions:
    def test_each_available_doctor_gets_its_own_slots_event(self, db):
        make_cardiologists(2)
        with patch("scheduling.ai.handler.extract_intent", return_value=INTENT), \
             patch("scheduling.ai.handler.find_available_slots", return_value=FAKE_SLOT):
            results = handle_patient_message(HISTORY)
        assert [r["type"] for r in results] == ["slots", "slots"]
        assert {r["doctor"] for r in results} == {"Dr. Cardio 0", "Dr. Cardio 1"}

    def test_offers_are_capped(self, db):
        make_cardiologists(MAX_DOCTOR_OPTIONS + 2)
        with patch("scheduling.ai.handler.extract_intent", return_value=INTENT), \
             patch("scheduling.ai.handler.find_available_slots", return_value=FAKE_SLOT):
            results = handle_patient_message(HISTORY)
        assert len(results) == MAX_DOCTOR_OPTIONS

    def test_doctors_with_no_openings_are_skipped(self, db):
        free, busy = make_cardiologists(2)
        with patch("scheduling.ai.handler.extract_intent", return_value=INTENT), \
             patch("scheduling.ai.handler.find_available_slots",
                   side_effect=lambda doctor, **_: FAKE_SLOT if doctor == free else []):
            results = handle_patient_message(HISTORY)
        assert [r["doctor"] for r in results] == [free.name]

    def test_fully_booked_specialty_still_returns_one_empty_slots_event(self, db):
        # The frontend's "no open slots in that window" message hangs off a
        # slots event with an empty list — never zero events.
        make_cardiologists(2)
        with patch("scheduling.ai.handler.extract_intent", return_value=INTENT), \
             patch("scheduling.ai.handler.find_available_slots", return_value=[]):
            results = handle_patient_message(HISTORY)
        assert len(results) == 1
        assert results[0]["type"] == "slots"
        assert results[0]["slots"] == []

    def test_inactive_doctors_are_never_offered(self, db):
        active, retired = make_cardiologists(2)
        retired.is_active = False
        retired.save(update_fields=["is_active"])
        with patch("scheduling.ai.handler.extract_intent", return_value=INTENT), \
             patch("scheduling.ai.handler.find_available_slots", return_value=FAKE_SLOT):
            results = handle_patient_message(HISTORY)
        assert [r["doctor"] for r in results] == [active.name]
