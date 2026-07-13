"""Live spot-check (real model): generated care-plan messages must mention
every bundled item and must NEVER invent clinical claims that aren't in the
plan — the build step's explicit verification for this agent.

Run after any prompt/tool change:
    pytest -m live_model caregaps/tests/test_plan_message_live.py
Makes real model calls (excluded from the default run by pytest.ini).
"""

import pytest

from caregaps.ai import write_care_plan_message
from core.ai import call_tool as real_call_tool

pytestmark = pytest.mark.live_model


@pytest.fixture(autouse=True)
def _real_model(monkeypatch):
    # conftest.py blocks caregaps.ai.call_tool by default; restore the real
    # one for this file only (autouse-local wins over the conftest autouse).
    monkeypatch.setattr("caregaps.ai.call_tool", real_call_tool)


# Clinical vocabulary that must NOT appear unless the plan contains it —
# the "never invent clinical claims" guard, checked against fixture plans
# that deliberately exclude these topics.
FORBIDDEN_WHEN_ABSENT = [
    "hba1c", "diabet", "cholesterol", "blood pressure", "cancer",
    "urgent", "immediately", "serious condition",
]


def test_mentions_every_item_and_the_single_visit_bundle():
    body = write_care_plan_message(
        ["Annual flu vaccine", "Blood test panel"], ["Mammogram screening"], "en",
    )["body"].lower()
    assert "flu" in body
    assert "blood test" in body or "blood panel" in body or "lab" in body
    assert "mammogram" in body
    # the FR-G4 selling point must come through
    assert "one visit" in body or "single visit" in body or "same visit" in body


def test_never_invents_clinical_claims():
    body = write_care_plan_message(
        ["Annual flu vaccine"], ["Mammogram screening"], "en",
    )["body"].lower()
    for term in FORBIDDEN_WHEN_ABSENT:
        assert term not in body, f"invented clinical content: {term!r}"


def test_no_greeting_or_name_in_body():
    body = write_care_plan_message(["Annual flu vaccine"], [], "en")["body"]
    assert not body.lower().startswith(("hi ", "hello", "dear", "namaste"))


def test_renders_in_patient_language():
    body = write_care_plan_message(
        ["Annual flu vaccine", "Blood test"], [], "hi",
    )["body"]
    # Hindi output must actually be in Devanagari, not English.
    assert any("ऀ" <= ch <= "ॿ" for ch in body), body
