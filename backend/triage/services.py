"""Triage business logic (Agent 3, Phase 2) — no AI in this module.

The deterministic emergency screen lives in core.safety so every agent can
run it (Edge Case 11 invariant); triage re-exports it as the first gate of
every assessment. Coming next in this module: assign_acuity, escalate,
route_disposition.
"""

import datetime
import logging

from core.events import emit
from core.safety import find_red_flags, red_flag_check  # noqa: F401
from registration.models import IntakeSummary
from triage.models import ClinicalProtocol, EscalationAlert

log = logging.getLogger("triage")


def select_protocol(symptoms_text: str) -> ClinicalProtocol | None:
    """Match the patient's complaint to an active ClinicalProtocol (FR-T2).

    Case-insensitive substring match of each protocol's symptom_keywords
    against the reported text. The protocol with the most matched keywords
    wins (total matched length breaks ties, so a specific multi-word match
    beats a generic one). Returns None when nothing matches — the caller
    decides the fallback (generic questioning or human handoff), never a
    wrong protocol.
    """
    text = (symptoms_text or "").lower()
    if not text.strip():
        return None

    best, best_score = None, (0, 0)
    for protocol in ClinicalProtocol.objects.filter(is_active=True):
        matched = [k for k in protocol.symptom_keywords if k.lower() in text]
        score = (len(matched), sum(len(k) for k in matched))
        if matched and score > best_score:
            best, best_score = protocol, score
    return best
#can be improved by using a more sophisticated matching algorithm, such as TF-IDF or word embeddings, to capture semantic similarity rather than just substring matches.


# -- acuity (FR-T4) ---------------------------------------------------------
# Rules decide the acuity; the model's suggestion may only RAISE the result,
# never lower it. Order matters: index = severity.
ACUITY_ORDER = ["minimal", "low", "medium", "high", "emergency"]

DISPOSITION_FOR = {
    "emergency": "ed_now",     # ED / call 911 now
    "high": "same_day",
    "medium": "24_48h",
    "low": "routine",
    "minimal": "self_care",
}

# Terms that map a patient's history/medications to the risk-factor slugs
# the protocol JSON uses in risk_overrides.
_CARDIAC_TERMS = ("heart", "cardiac", "angina", "coronary", "stent", "bypass", "arrhythmia")
_IMMUNO_TERMS = ("immunocompromised", "immunosuppress", "chemotherapy", "transplant", "hiv")
_BLOOD_THINNERS = ("warfarin", "heparin", "apixaban", "rivaroxaban", "dabigatran", "clopidogrel")


def patient_risk_factors(patient) -> set[str]:
    """Risk-factor slugs derived from the patient record (age, chronic
    conditions, medications) — the vocabulary protocols use in risk_overrides."""
    factors = set()

    today = datetime.date.today()
    age = today.year - patient.dob.year - (
        (today.month, today.day) < (patient.dob.month, patient.dob.day)
    )
    if age >= 50:
        factors.add("age_gte_50")
    if age >= 65:
        factors.add("age_gte_65")

    summary = IntakeSummary.objects.filter(patient=patient).order_by("-id").first()
    profile = summary.clinical_profile if summary else {}
    history = " ".join(profile.get("medical_history", [])).lower()
    medications = " ".join(profile.get("medications", [])).lower()

    if "diabet" in history:
        factors.add("diabetes")
    if any(term in history for term in _CARDIAC_TERMS):
        factors.add("cardiac_history")
    if any(term in history for term in _IMMUNO_TERMS):
        factors.add("immunocompromised")
    if any(drug in medications for drug in _BLOOD_THINNERS):
        factors.add("on_blood_thinners")
    return factors


def _condition_met(condition: dict, findings: dict) -> bool:
    """Evaluate one {finding, op, value} condition against the findings."""
    value = findings.get(condition["finding"])
    if value is None:
        return False
    op = condition["op"]
    if op == "is_true":
        # Strictly boolean True: a non-empty string like "no, similar to
        # before" must never assert a red-flag fact (found by the Phase 3
        # curl drive — it truthy-matched worst_ever and forced emergency).
        return value is True
    if op == "contains":
        needle = str(condition["value"]).lower()
        if isinstance(value, (list, tuple)):
            return any(needle in str(item).lower() for item in value)
        return needle in str(value).lower()
    try:
        actual, target = float(value), float(condition["value"])
    except (TypeError, ValueError):
        return False  # non-numeric answer can't satisfy a numeric rule
    return {"gte": actual >= target, "lte": actual <= target, "eq": actual == target}[op]


def _raise_to(acuity: str, at_least: str) -> str:
    return max(acuity, at_least, key=ACUITY_ORDER.index)


def evaluate_disposition_rules(rules: dict, findings: dict, risk_factors: set) -> str:
    """The protocol JSON evaluated deterministically:
    red_flags first, then rules (first match wins), then default_acuity;
    risk_overrides can only raise the result."""
    acuity = None
    for condition in rules.get("red_flags", []):
        if _condition_met(condition, findings):
            acuity = condition["acuity"]
            break
    if acuity is None:
        for condition in rules.get("rules", []):
            if _condition_met(condition, findings):
                acuity = condition["acuity"]
                break
    if acuity is None:
        acuity = rules.get("default_acuity", "low")

    for override in rules.get("risk_overrides", []):
        if override["risk_factor"] in risk_factors:
            acuity = _raise_to(acuity, override["raise_to_at_least"])
    return acuity


def assign_acuity(assessment) -> str:
    """Acuity + FR-T4 disposition for a completed assessment.

    rule_acuity comes from the protocol's disposition_rules + the patient's
    risk factors; the model's suggested_acuity (in findings) may only raise
    it. The result is saved onto the assessment.
    """
    rule_acuity = evaluate_disposition_rules(
        assessment.clinical_protocol.disposition_rules,
        assessment.findings,
        patient_risk_factors(assessment.patient),
    )
    model_acuity = assessment.findings.get("suggested_acuity", "minimal")
    if model_acuity not in ACUITY_ORDER:
        model_acuity = "minimal"
    final = _raise_to(rule_acuity, model_acuity)

    assessment.acuity = final
    assessment.disposition = DISPOSITION_FOR[final]
    assessment.save(update_fields=["acuity", "disposition"])
    return final


# -- disposition routing (FR-T7) --------------------------------------------
# ORCHESTRATION §3: triage emits ONE event name, triage.disposition; the
# downstream agents subscribe to it and filter on route_to / disposition.
# An agent that doesn't exist yet simply has no subscriber — the EventLog
# row is still written, so nothing is lost.

# Which agent should act, by appointment urgency.
ROUTE_FOR_DISPOSITION = {
    "same_day": "scheduling",
    "24_48h": "scheduling",
    "routine": "scheduling",
    "ed_now": None,      # emergency path is escalate(), not a booking
    "self_care": None,   # advice only; nothing to book
}

# Routing reasons beyond urgency (FR-T7). The AI layer can set
# findings["route_hint"] when the complaint is really about one of these.
ROUTE_FOR_HINT = {
    "specialist": "referrals",
    "meds_issue": "refills",
    "preventive": "caregaps",
}


def route_disposition(assessment):
    """Emit triage.disposition so the right downstream agent reacts.

    A route_hint in the findings (specialist / meds_issue / preventive)
    outranks the urgency-based default, e.g. a routine complaint that is
    really a refill request goes to the refill agent, not scheduling.
    Returns the EventLog entry.
    """
    hint = (assessment.findings or {}).get("route_hint")
    route_to = ROUTE_FOR_HINT.get(hint) or ROUTE_FOR_DISPOSITION.get(assessment.disposition)
    return emit(
        "triage.disposition",
        patient_id=assessment.patient_id,
        assessment_id=assessment.id,
        acuity=assessment.acuity,
        disposition=assessment.disposition,
        route_to=route_to,
    )


# -- escalation (FR-T6, FR-T8) ----------------------------------------------

def notify_on_call(alert: EscalationAlert) -> None:
    """Alert the on-call clinician. Dev stub: console + log only.

    Production swap: staff channel through a real pager/SMS integration.
    (core.notifications.notify is patient-facing and enforces patient
    opt-outs, so it is deliberately NOT used for staff alerts.)
    """
    message = (
        f"[ON-CALL ALERT] {alert.category}/{alert.priority} — "
        f"patient {alert.patient_id} ({alert.patient.first_name} "
        f"{alert.patient.last_name}): {alert.summary}"
    )
    print(message)
    log.warning(message)


def escalate(assessment, category: str = "emergency") -> EscalationAlert:
    """Emergency path: create the alert, page on-call, mark the assessment.

    Called whenever red_flag_check() fires or the model reports
    emergency_detected. The alert summary is the AI-written clinician
    hand-off when it can be generated — but an AI failure must NEVER delay
    an emergency alert, so any exception falls back to the deterministic
    text.
    """
    try:
        from triage.ai import generate_triage_summary  # local: avoids cycle
        summary = generate_triage_summary(assessment)["summary_text"]
    except Exception:
        log.exception("summary generation failed; using deterministic fallback")
        summary = assessment.summary_text or (
            f"Red-flag escalation. Reported: {assessment.reported_symptoms}. "
            f"Findings so far: {assessment.findings}"
        )
    alert = EscalationAlert.objects.create(
        assessment=assessment,
        patient=assessment.patient,
        source_agent="triage",
        category=category,
        priority="high",
        summary=summary,
    )
    notify_on_call(alert)

    assessment.status = "escalated"
    assessment.acuity = "emergency"
    assessment.disposition = DISPOSITION_FOR["emergency"]
    assessment.save(update_fields=["status", "acuity", "disposition"])

    emit("escalation.created", alert_id=alert.id, patient_id=alert.patient_id,
         category=category)
    return alert
