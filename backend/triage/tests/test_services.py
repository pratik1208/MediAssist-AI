"""Phase 2 services: select_protocol routing and assign_acuity rules."""

import datetime

import pytest
from django.core.management import call_command
from django.utils import timezone

from core.models import Conversation, Patient
from registration.models import IntakeSummary
from triage.models import ClinicalProtocol, TriageAssessment
from core.events import subscribe
from core.models import EventLog
from triage.models import EscalationAlert
from triage.services import (
    assign_acuity,
    escalate,
    evaluate_disposition_rules,
    patient_risk_factors,
    phrase_in_text,
    red_flag_check,
    route_disposition,
    select_protocol,
)
from triage.tests.test_red_flags import EMERGENCY_PHRASES


@pytest.fixture
def seeded(db):
    """The real starter protocols, loaded by the real seed command."""
    call_command("seed_protocols", verbosity=0)


class TestSelectProtocol:
    @pytest.mark.parametrize("complaint, expected", [
        ("I've been having chest pain since last night", "Adult Chest Pain"),
        ("there is a pressure, like chest tightness", "Adult Chest Pain"),
        ("my son has a fever of 102", "Pediatric Fever"),
        ("baby fever since yesterday evening", "Pediatric Fever"),
        ("a pounding headache behind my eyes", "Headache"),
        ("I get migraine attacks every week", "Headache"),
        ("bad stomach pain after eating", "Abdominal Pain"),
        ("my abdomen hurts on the right side", "Abdominal Pain"),
    ])
    def test_complaints_route_to_the_right_protocol(self, seeded, complaint, expected):
        assert select_protocol(complaint).name == expected

    @pytest.mark.parametrize("complaint, expected", [
        # Word order must not defeat routing (round-2 live-test regressions).
        ("My baby has a fever, she seems warm", "Pediatric Fever"),
        ("my child is running a fever", "Pediatric Fever"),
        ("I have a fever and chills", "Adult Fever Protocol"),
        ("I have pain in my chest", "Adult Chest Pain"),
    ])
    def test_word_order_does_not_defeat_routing(self, seeded, complaint, expected):
        assert select_protocol(complaint).name == expected

    def test_negated_symptom_does_not_route(self, seeded):
        # "no fever" must not win over the actual complaint.
        assert select_protocol("I have no fever, just a pounding headache").name == "Headache"

    def test_no_match_returns_none_not_a_wrong_protocol(self, seeded):
        # A twisted ankle is deliberately NOT used here — the Minor Injury
        # protocol added later legitimately matches it — so this needs a
        # complaint no seeded protocol's keywords cover at all.
        assert select_protocol("my hair has been falling out a lot lately") is None

    def test_empty_and_none_input(self, seeded):
        assert select_protocol("") is None
        assert select_protocol(None) is None
        assert select_protocol("   ") is None

    def test_inactive_protocols_are_never_selected(self, seeded):
        ClinicalProtocol.objects.filter(name="Headache").update(is_active=False)
        assert select_protocol("a pounding headache") is None

    def test_matching_is_case_insensitive(self, seeded):
        assert select_protocol("CHEST PAIN AND SWEATING").name == "Adult Chest Pain"

    def test_most_keyword_hits_wins(self, db):
        # Two protocols share a keyword; the one matching more of the text wins.
        ClinicalProtocol.objects.create(
            name="Generic Pain", symptom_keywords=["pain"], question_flow=[],
            disposition_rules={},
        )
        ClinicalProtocol.objects.create(
            name="Back Pain", symptom_keywords=["pain", "back pain", "lower back"],
            question_flow=[], disposition_rules={},
        )
        chosen = select_protocol("lower back pain when bending")
        assert chosen.name == "Back Pain"


def make_patient(age_years, **kwargs):
    dob = datetime.date.today() - datetime.timedelta(days=age_years * 365 + 30)
    return Patient.objects.create(
        first_name="Test", last_name=f"Patient{age_years}",
        contact_number="9000000000", dob=dob, **kwargs,
    )


def make_assessment(patient, protocol_name, findings):
    conversation = Conversation.objects.create(channel="web", started_at=timezone.now())
    return TriageAssessment.objects.create(
        patient=patient, conversation=conversation,
        clinical_protocol=ClinicalProtocol.objects.get(name=protocol_name),
        findings=findings, acuity="minimal", disposition="self_care",
        summary_text="",
    )


class TestPatientRiskFactors:
    def test_age_thresholds(self, db):
        assert patient_risk_factors(make_patient(25)) == set()
        assert patient_risk_factors(make_patient(55)) == {"age_gte_50"}
        assert patient_risk_factors(make_patient(70)) == {"age_gte_50", "age_gte_65"}

    def test_history_and_medications_from_the_intake_record(self, db):
        patient = make_patient(40)
        IntakeSummary.objects.create(patient=patient, clinical_profile={
            "medical_history": ["type 2 diabetes", "heart attack in 2020"],
            "medications": ["warfarin 5mg daily"],
        }, summary_text="")
        assert patient_risk_factors(patient) == {
            "diabetes", "cardiac_history", "on_blood_thinners",
        }


class TestEvaluateDispositionRules:
    RULES = {
        "red_flags": [
            {"finding": "radiation", "op": "contains", "value": "arm", "acuity": "emergency"},
        ],
        "rules": [
            {"finding": "severity_1_10", "op": "gte", "value": 7, "acuity": "high"},
            {"finding": "severity_1_10", "op": "gte", "value": 4, "acuity": "medium"},
        ],
        "risk_overrides": [
            {"risk_factor": "age_gte_50", "raise_to_at_least": "high"},
        ],
        "default_acuity": "low",
    }

    def test_red_flag_beats_everything(self):
        acuity = evaluate_disposition_rules(
            self.RULES, {"radiation": "spreads to my left arm", "severity_1_10": 2}, set())
        assert acuity == "emergency"

    def test_first_matching_rule_wins(self):
        assert evaluate_disposition_rules(self.RULES, {"severity_1_10": 8}, set()) == "high"
        assert evaluate_disposition_rules(self.RULES, {"severity_1_10": 5}, set()) == "medium"

    def test_default_when_nothing_matches(self):
        assert evaluate_disposition_rules(self.RULES, {"severity_1_10": 2}, set()) == "low"

    def test_risk_override_raises_but_never_lowers(self):
        # low base raised to high by age
        assert evaluate_disposition_rules(
            self.RULES, {"severity_1_10": 2}, {"age_gte_50"}) == "high"
        # emergency is never lowered by an override capped at high
        assert evaluate_disposition_rules(
            self.RULES, {"radiation": "left arm"}, {"age_gte_50"}) == "emergency"

    def test_missing_finding_and_non_numeric_answer_are_safe(self):
        assert evaluate_disposition_rules(self.RULES, {}, set()) == "low"
        assert evaluate_disposition_rules(
            self.RULES, {"severity_1_10": "quite bad"}, set()) == "low"

    def test_is_true_requires_an_actual_boolean(self):
        # Regression: "no, similar to before" is a truthy string and must
        # never satisfy an is_true red flag.
        rules = {"red_flags": [
            {"finding": "worst_ever", "op": "is_true", "acuity": "emergency"},
        ], "rules": [], "risk_overrides": [], "default_acuity": "low"}
        assert evaluate_disposition_rules(rules, {"worst_ever": "no, similar to before"}, set()) == "low"
        assert evaluate_disposition_rules(rules, {"worst_ever": True}, set()) == "emergency"
        assert evaluate_disposition_rules(rules, {"worst_ever": False}, set()) == "low"


class TestPhraseInText:
    """The matcher behind contains rules and protocol keyword routing."""

    @pytest.mark.parametrize("answer, phrase", [
        ("my neck feels stiff and it hurts to look down", "stiff neck"),
        ("I vomited twice and I think I have a fever", "fever"),
        ("it hit me suddenly", "sudden"),
        ("she's been vomiting all night", "vomit"),
        ("no rash, but my neck is stiff", "stiff neck"),  # negation stays in its clause
        ("My baby has a fever", "baby fever"),
    ])
    def test_matches(self, answer, phrase):
        assert phrase_in_text(answer, phrase) is True

    @pytest.mark.parametrize("answer, phrase", [
        ("No fever or anything else, just the headache", "fever"),
        ("no rash or stiff neck", "stiff neck"),  # negation distributes over "or"
        ("none of those", "stiff neck"),
        ("it's very tender, no chance of pregnancy", "pregnan"),
        ("I don't have any confusion", "confusion"),
        ("my knee hurts", "stiff neck"),
    ])
    def test_does_not_match(self, answer, phrase):
        assert phrase_in_text(answer, phrase) is False

    def test_contains_rule_uses_the_matcher(self):
        rules = {"red_flags": [
            {"finding": "associated_symptoms", "op": "contains",
             "value": "stiff neck", "acuity": "emergency"},
        ], "rules": [], "risk_overrides": [], "default_acuity": "low"}
        # Round-2 live-test regression: reworded meningitis sign must fire...
        assert evaluate_disposition_rules(
            rules, {"associated_symptoms": "my neck feels stiff"}, set()) == "emergency"
        # ...and a denial must not.
        assert evaluate_disposition_rules(
            rules, {"associated_symptoms": "no stiff neck or rash"}, set()) == "low"


class TestAssignAcuity:
    def test_elderly_chest_pain_is_not_young_chest_pain(self, seeded):
        # Build-step exit criterion: same findings, different patients.
        findings = {"severity_1_10": 5}
        young = assign_acuity(make_assessment(make_patient(25), "Adult Chest Pain", findings))
        elderly = assign_acuity(make_assessment(make_patient(70), "Adult Chest Pain", findings))
        assert young == "medium"
        assert elderly == "high"   # age_gte_50 override raises it

    def test_red_flag_finding_means_emergency_and_ed_now(self, seeded):
        assessment = make_assessment(
            make_patient(30), "Adult Chest Pain",
            {"radiation": "goes into my jaw", "severity_1_10": 3},
        )
        assert assign_acuity(assessment) == "emergency"
        assessment.refresh_from_db()
        assert assessment.acuity == "emergency"
        assert assessment.disposition == "ed_now"

    def test_model_suggestion_can_raise(self, seeded):
        assessment = make_assessment(
            make_patient(25), "Adult Chest Pain",
            {"severity_1_10": 5, "suggested_acuity": "high"},
        )
        assert assign_acuity(assessment) == "high"

    def test_model_suggestion_can_never_lower(self, seeded):
        assessment = make_assessment(
            make_patient(25), "Adult Chest Pain",
            {"severity_1_10": 8, "suggested_acuity": "minimal"},
        )
        assert assign_acuity(assessment) == "high"

    def test_disposition_mapping_follows_fr_t4(self, seeded):
        # Pediatric protocol: infant fever red flag -> emergency -> ed_now.
        assessment = make_assessment(
            make_patient(30), "Pediatric Fever",
            {"age_months": 2, "temperature_f": 100.6},
        )
        assign_acuity(assessment)
        assessment.refresh_from_db()
        assert (assessment.acuity, assessment.disposition) == ("emergency", "ed_now")


class TestRouteDisposition:
    def route(self, seeded_findings, disposition, acuity="medium"):
        assessment = make_assessment(make_patient(30), "Adult Chest Pain", seeded_findings)
        assessment.disposition = disposition
        assessment.acuity = acuity
        assessment.save()
        return assessment, route_disposition(assessment)

    @pytest.mark.parametrize("disposition, expected_route", [
        ("same_day", "scheduling"),
        ("24_48h", "scheduling"),
        ("routine", "scheduling"),
        ("ed_now", None),      # emergency handled by escalate(), not booking
        ("self_care", None),   # nothing to book
    ])
    def test_urgency_routes_to_scheduling_or_nowhere(self, seeded, disposition, expected_route):
        assessment, event = self.route({}, disposition)
        assert event.name == "triage.disposition"
        assert event.payload == {
            "patient_id": assessment.patient_id,
            "assessment_id": assessment.id,
            "acuity": "medium",
            "disposition": disposition,
            "route_to": expected_route,
        }

    @pytest.mark.parametrize("hint, expected_route", [
        ("specialist", "referrals"),
        ("meds_issue", "refills"),
        ("preventive", "caregaps"),
    ])
    def test_route_hint_outranks_the_urgency_default(self, seeded, hint, expected_route):
        _, event = self.route({"route_hint": hint}, "routine")
        assert event.payload["route_to"] == expected_route

    def test_event_is_durable_even_with_no_listener(self, seeded):
        # No agent subscribes yet — the EventLog row must still exist (FR-T7).
        _, event = self.route({}, "routine")
        assert event.processed is True
        assert event.error == ""

    def test_a_subscriber_receives_the_payload(self, seeded):
        received = {}

        @subscribe("triage.disposition")
        def _capture(**payload):
            received.update(payload)

        assessment, _ = self.route({}, "same_day")
        assert received["route_to"] == "scheduling"
        assert received["assessment_id"] == assessment.id


class TestEscalation:
    """Phase 2 exit criteria: every red-flag phrase triggers escalation;
    escalation creates an alert."""

    @pytest.mark.parametrize("phrase", EMERGENCY_PHRASES)
    def test_every_red_flag_phrase_triggers_escalation(self, seeded, phrase):
        # The emergency path: deterministic screen fires -> escalate().
        assert red_flag_check(phrase) is True
        assessment = make_assessment(
            make_patient(30), "Adult Chest Pain", {})
        assessment.reported_symptoms = {"text": phrase}
        assessment.save()
        escalate(assessment)
        assert EscalationAlert.objects.filter(assessment=assessment).exists()

    def test_escalation_creates_a_complete_alert(self, seeded):
        assessment = make_assessment(
            make_patient(45), "Adult Chest Pain",
            {"severity_1_10": 9, "radiation": "left arm"},
        )
        alert = escalate(assessment)

        assert alert.source_agent == "triage"
        assert alert.category == "emergency"
        assert alert.priority == "high"
        assert alert.status == "open"
        assert alert.patient == assessment.patient
        assert "left arm" in alert.summary  # findings visible to on-call staff

    def test_escalation_marks_the_assessment(self, seeded):
        assessment = make_assessment(make_patient(30), "Adult Chest Pain", {})
        escalate(assessment)
        assessment.refresh_from_db()
        assert assessment.status == "escalated"
        assert assessment.acuity == "emergency"
        assert assessment.disposition == "ed_now"

    def test_escalation_emits_a_durable_event(self, seeded):
        assessment = make_assessment(make_patient(30), "Adult Chest Pain", {})
        alert = escalate(assessment, category="mental_health")
        event = EventLog.objects.filter(name="escalation.created").latest("id")
        assert event.payload == {
            "alert_id": alert.id,
            "patient_id": assessment.patient_id,
            "category": "mental_health",
        }

    def test_on_call_notification_is_logged(self, seeded, caplog):
        assessment = make_assessment(make_patient(30), "Adult Chest Pain", {})
        with caplog.at_level("WARNING", logger="triage"):
            escalate(assessment)
        assert "ON-CALL ALERT" in caplog.text
