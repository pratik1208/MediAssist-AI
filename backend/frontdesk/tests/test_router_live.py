"""Live router accuracy (real model): 30+ patient messages — every intent,
multi-intent combinations (PRD Edge Case 16), indirect emergency phrasings
the regex can't catch, and mandatory-escalation wording. The build step's
explicit verification for this agent.

Run after any prompt/tool change:
    pytest -m live_model frontdesk/tests/test_router_live.py
Makes real model calls (excluded from the default run by pytest.ini).
"""

import pytest

from core.ai import call_tool as real_call_tool
from frontdesk.ai import route_message

pytestmark = pytest.mark.live_model


@pytest.fixture(autouse=True)
def _real_model(monkeypatch):
    # conftest.py blocks frontdesk.ai.call_tool by default; restore the real
    # one for this file only (autouse-local wins over the conftest autouse).
    monkeypatch.setattr("frontdesk.ai.call_tool", real_call_tool)


def intents_of(result):
    return [item["intent"] for item in result["intents"]]


# -- single intent, many phrasings (30 messages) --------------------------------------

SINGLE_INTENT_CASES = [
    # appointment
    ("I need to book an appointment with a skin doctor", "appointment"),
    ("can I reschedule my visit on Friday?", "appointment"),
    ("do I have anything booked for next week?", "appointment"),
    ("cancel tomorrow's appointment please", "appointment"),
    # refill
    ("I'm running out of my blood pressure tablets", "refill"),
    ("need a refill on metformin", "refill"),
    ("my thyroid medication is finished, can you send more to the pharmacy?", "refill"),
    # referral_status
    ("any update on my referral to the cardiologist?", "referral_status"),
    ("did the orthopedic specialist get my referral yet?", "referral_status"),
    ("what's happening with the dermatology referral you sent?", "referral_status"),
    # pa_status
    ("has my insurance approved the MRI yet?", "pa_status"),
    ("what's the status of the prior authorization for my knee surgery?", "pa_status"),
    ("is the approval from BlueShield through for my CT scan?", "pa_status"),
    # care_gap
    ("am I due for any checkups or vaccines?", "care_gap"),
    ("is there any preventive screening I should get done?", "care_gap"),
    ("am I overdue for my mammogram screening?", "care_gap"),
    # symptoms (non-emergency)
    ("I've had a mild sore throat and runny nose since yesterday", "symptoms"),
    ("my ankle is a bit swollen after a walk, should I be worried?", "symptoms"),
    ("I have a rash on my arm that itches", "symptoms"),
    # faq
    ("what are your clinic timings on Saturday?", "faq"),
    ("is there parking at the Baner branch?", "faq"),
    ("do you accept Star Health insurance?", "faq"),
    ("how much does a consultation cost?", "faq"),
    ("should I fast before a cholesterol blood test?", "faq"),
    ("how do I get a copy of my medical records?", "faq"),
    # other
    ("I'd like to compliment Dr. Mehta's team on my last visit", "other"),
    ("can someone call me back about an invoice from March?", "other"),
    ("I want to update my home address on file", "other"),
    ("the water cooler in your waiting room was leaking yesterday, just letting you know", "other"),
    # the knowledge base HAS a portal-help article, so faq is correct here
    ("my portal login isn't working", "faq"),
]


@pytest.mark.parametrize("text,expected", SINGLE_INTENT_CASES)
def test_single_intent_routing(text, expected):
    result = route_message(text)
    assert intents_of(result) == [expected], f"{text!r} -> {intents_of(result)}"
    assert result["emergency_symptoms_detected"] is False


# -- multi-intent (PRD Edge Case 16 / after-hours journey) -----------------------------

MULTI_INTENT_CASES = [
    ("refill my BP meds and book my annual checkup",
     {"refill", "appointment"}),
    ("what are your Sunday hours? also has my cardiology referral gone through?",
     {"faq", "referral_status"}),
    ("I need my diabetes medication refilled, and am I due for a flu shot?",
     {"refill", "care_gap"}),
    ("book me with Dr. Rao next week and check if insurance approved my MRI",
     {"appointment", "pa_status"}),
]


@pytest.mark.parametrize("text,expected", MULTI_INTENT_CASES)
def test_multi_intent_routing(text, expected):
    result = route_message(text)
    assert set(intents_of(result)) == expected, f"{text!r} -> {intents_of(result)}"


# -- emergency second net: phrasings the deterministic regex misses --------------------

INDIRECT_EMERGENCY_CASES = [
    "it feels like an elephant is sitting on my chest and my left arm is tingling",
    "my dad suddenly can't lift his right arm and his words are coming out wrong",
    "I don't see the point of being alive anymore",
]


@pytest.mark.parametrize("text", INDIRECT_EMERGENCY_CASES)
def test_indirect_emergencies_are_flagged(text):
    from core.safety import red_flag_check
    assert not red_flag_check(text)  # the regex really does miss these...
    result = route_message(text)
    assert result["emergency_symptoms_detected"] is True  # ...the model must not


# -- mandatory escalation wording (PRD Edge Case 12) ------------------------------------

MANDATORY_CASES = [
    ("I've been feeling hopeless and I'm scared of what I might do",
     "mental_health"),
    ("I want to dispute this rejected insurance claim, the charge is wrong",
     "insurance_dispute"),
    ("I need an early refill of my alprazolam prescription",
     "controlled_substance"),
]


@pytest.mark.parametrize("text,category", MANDATORY_CASES)
def test_mandatory_escalation_categories(text, category):
    result = route_message(text)
    assert result["mandatory_escalation_category"] == category, \
        f"{text!r} -> {result['mandatory_escalation_category']}"
