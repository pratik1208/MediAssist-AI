"""Refill business logic (Agent 4, Phase 2) — deterministic rules, no AI.

The eligibility engine is the heart of this agent (FR-M3/M4). Every write
leaves an AuditEvent; every patient-facing message goes through
core.notifications (opt-outs enforced there); cross-agent effects are
events, never imports.
"""

import datetime
import logging
import re
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from core.events import emit
from core.models import AuditEvent
from core.notifications import notify
from refills.erx import default_gateway
from refills.models import Prescription, RefillRequest
from registration.models import IntakeSummary, UploadedDocument
from triage.models import EscalationAlert

log = logging.getLogger("refills")

# Refill becomes requestable once this fraction of the supply window has
# passed (industry-common early-fill threshold).
EARLY_FILL_THRESHOLD = 0.75

FAILURE_EXPLANATIONS = {
    "discontinued_by_doctor": "this medication was discontinued by your doctor",
    "prescription_expired": "the prescription has expired",
    "too_early": "it is too early to refill this medication",
    "followup_visit_required": "a follow-up visit is needed before the next refill",
}


@dataclass
class EligibilityResult:
    eligible: bool
    failures: list[str] = field(default_factory=list)
    needs_new_prescription: bool = False


# -- rule helpers ------------------------------------------------------------

def days_supply(prescription: Prescription) -> int | None:
    """Naive supply window: the leading number of the quantity ("30 tablets").
    None when the quantity isn't parseable — the too-early rule then skips."""
    match = re.match(r"\s*(\d+)", prescription.quantity or "")
    return int(match.group(1)) if match else None


def refill_not_yet_due(prescription: Prescription) -> bool:
    """Too early = the last fulfilled request is younger than 75% of the
    supply window. No fulfilled history or unparseable quantity = not early."""
    supply = days_supply(prescription)
    if supply is None:
        return False
    last_fill = (RefillRequest.objects
                 .filter(prescription=prescription,
                         status__in=("approved", "sent_to_pharmacy", "ready_for_pickup"))
                 .order_by("-created_at").first())
    if last_fill is None:
        return False
    age = (timezone.now() - last_fill.created_at).days
    return age < supply * EARLY_FILL_THRESHOLD


def _normalize_test_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def recent_lab_exists(patient, test: str, max_age_days: int) -> bool:
    """A lab report for this test, dated within max_age_days, extracted from
    the patient's uploaded documents (registration Agent 2 owns extraction)."""
    wanted = _normalize_test_name(test)
    cutoff = datetime.date.today() - datetime.timedelta(days=max_age_days)
    documents = UploadedDocument.objects.filter(
        patient=patient, document_type="lab_report", extraction_status="done",
    )
    for doc in documents:
        report = (doc.extracted_data or {}).get("lab_report") or {}
        name = _normalize_test_name(report.get("test_name", ""))
        if not name or (wanted not in name and name not in wanted):
            continue
        try:
            report_date = datetime.date.fromisoformat(report.get("date", ""))
        except ValueError:
            continue
        if report_date >= cutoff:
            return True
    return False


# -- the eligibility engine (FR-M3/M4) ---------------------------------------

def check_eligibility(request: RefillRequest) -> EligibilityResult:
    """Pure rules, structured result. Controlled substances short-circuit to
    a human escalation and never enter the automated path (Edge Case 12)."""
    rx = request.prescription
    if rx.is_controlled_substance:
        escalate_controlled(request)
        return EligibilityResult(False, ["controlled_substance"])

    failures = []
    if rx.status == "discontinued":
        failures.append("discontinued_by_doctor")
    if rx.status == "expired" or rx.expiry_date < datetime.date.today():
        failures.append("prescription_expired")
    if refill_not_yet_due(rx):
        failures.append("too_early")
    for lab in rx.required_labs:
        if not recent_lab_exists(request.patient, lab["test"], lab["max_age_days"]):
            failures.append(f"missing_lab:{lab['test']}")
    if rx.followup_required:
        failures.append("followup_visit_required")

    if rx.refills_used >= rx.refills_allowed and not failures:
        # Out of refills but otherwise clean: a renewal (new prescription),
        # routed to the physician — not a refill (FR-M4, Edge Case 1).
        return EligibilityResult(True, [], needs_new_prescription=True)
    return EligibilityResult(not failures, failures)


def _explain(failures: list[str]) -> str:
    parts = []
    for failure in failures:
        if failure.startswith("missing_lab:"):
            parts.append(f"a recent {failure.split(':', 1)[1].replace('_', ' ')} result is needed")
        else:
            parts.append(FAILURE_EXPLANATIONS.get(failure, failure))
    return "; ".join(parts)


def run_eligibility_check(request: RefillRequest) -> EligibilityResult:
    """Drive a received request through the gate and set its status:
    controlled -> pending_approval (human only, alert already raised);
    any failure -> paused + patient notified (Edge Case 2);
    eligible -> renewal summary built, into the physician queue."""
    request.status = "eligibility_check"
    result = check_eligibility(request)

    if result.failures == ["controlled_substance"]:
        request.status = "pending_approval"
        request.renewal_summary = build_renewal_summary(request)
        request.save()
        return result

    if result.failures:
        request.status = "paused"
        request.pause_reason = _explain(result.failures)[:200]
        request.save()
        notify(request.patient, "refill_paused", {
            "name": request.patient.first_name,
            "medication": request.prescription.medication_name,
            "reason": request.pause_reason,
        })
        return result

    request.renewal_summary = build_renewal_summary(request)
    request.renewal_summary["is_renewal"] = result.needs_new_prescription
    request.status = "pending_approval"
    request.save()
    return result


def escalate_controlled(request: RefillRequest) -> EscalationAlert:
    """Immediate human escalation — the automated path never touches
    controlled substances (PRD Edge Case 12)."""
    rx = request.prescription
    alert = EscalationAlert.objects.create(
        assessment=None,
        patient=request.patient,
        source_agent="refills",
        category="controlled_substance",
        priority="high",
        summary=(f"Controlled substance refill request: {rx.medication_name} "
                 f"{rx.dose} for {request.patient.first_name} "
                 f"{request.patient.last_name}. Physician decision required — "
                 "no automated processing."),
    )
    log.warning("[ON-CALL ALERT] controlled substance refill — request %s, patient %s",
                request.id, request.patient_id)
    emit("escalation.created", alert_id=alert.id, patient_id=request.patient_id,
         category="controlled_substance")
    return alert


# -- the physician-facing summary (FR-M5) ------------------------------------

def compute_adherence(prescription: Prescription) -> str:
    """Naive adherence from refill timing: average gap between fulfilled
    requests vs. the supply window. <2 data points = unknown."""
    supply = days_supply(prescription)
    fills = list(RefillRequest.objects
                 .filter(prescription=prescription,
                         status__in=("approved", "sent_to_pharmacy", "ready_for_pickup"))
                 .order_by("created_at").values_list("created_at", flat=True))
    if supply is None or len(fills) < 2:
        return "unknown"
    gaps = [(later - earlier).days for earlier, later in zip(fills, fills[1:])]
    average_gap = sum(gaps) / len(gaps)
    if average_gap <= supply * 1.2:
        return "good"
    if average_gap <= supply * 1.5:
        return "fair"
    return "poor"


def build_renewal_summary(request: RefillRequest) -> dict:
    """The structured physician-facing data (FR-M5) the queue renders and the
    Phase 4 AI turns into a one-paragraph summary."""
    rx = request.prescription
    intake = IntakeSummary.objects.filter(patient=request.patient).order_by("-id").first()
    profile = intake.clinical_profile if intake else {}

    recent_labs = []
    for doc in UploadedDocument.objects.filter(
        patient=request.patient, document_type="lab_report", extraction_status="done",
    ):
        report = (doc.extracted_data or {}).get("lab_report") or {}
        if report.get("test_name"):
            recent_labs.append({
                "test": report.get("test_name"),
                "date": report.get("date"),
                "findings": report.get("findings"),
            })

    return {
        "medication": f"{rx.medication_name} {rx.dose}",
        "quantity": rx.quantity,
        "last_prescribed": rx.prescribed_date.isoformat(),
        "refills_remaining": max(rx.refills_allowed - rx.refills_used, 0),
        "recent_labs": recent_labs,
        "allergies": profile.get("allergies", []),
        "adverse_events": [],  # no adverse-event source yet; wired in later
        "adherence": compute_adherence(rx),
        "controlled_substance": rx.is_controlled_substance,
    }


# -- physician decisions (FR-M6/M7) ------------------------------------------

@transaction.atomic
def approve(request: RefillRequest, doctor) -> Prescription:
    """Approval writes back a fresh prescription row (the EHR-write stand-in,
    FR-M7), transmits it to the pharmacy, and notifies the patient (FR-M8)."""
    template = request.prescription
    request.status = "approved"
    request.decided_by, request.decided_at = doctor, timezone.now()
    request.save()

    new_rx = Prescription.objects.create(
        patient=request.patient,
        prescriber=doctor,
        medication_name=template.medication_name,
        dose=template.dose,
        quantity=template.quantity,
        refills_allowed=template.refills_allowed,
        refills_used=0,
        prescribed_date=datetime.date.today(),
        expiry_date=datetime.date.today() + datetime.timedelta(days=365),
        required_labs=template.required_labs,
        followup_required=False,
        is_controlled_substance=template.is_controlled_substance,
    )
    AuditEvent.objects.create(
        actor_type="staff", actor_id=str(doctor.id), patient=request.patient,
        action="refill.approved",
        payload={"request_id": request.id, "new_prescription_id": new_rx.id,
                 "medication": new_rx.medication_name},
    )

    send_to_pharmacy(request, new_rx)
    emit("refill.approved", patient_id=request.patient_id, request_id=request.id)
    return new_rx


def reject(request: RefillRequest, doctor, reason: str) -> None:
    request.status = "rejected"
    request.pause_reason = reason[:200]
    request.decided_by, request.decided_at = doctor, timezone.now()
    request.save()
    AuditEvent.objects.create(
        actor_type="staff", actor_id=str(doctor.id), patient=request.patient,
        action="refill.rejected",
        payload={"request_id": request.id, "reason": reason},
    )
    notify(request.patient, "refill_rejected", {
        "name": request.patient.first_name,
        "medication": request.prescription.medication_name,
        "reason": reason,
    })


def request_visit(request: RefillRequest, doctor) -> None:
    """The physician wants to see the patient first; Scheduling reacts to the
    event and offers a booking (FR-M6 -> Agent 1)."""
    request.status = "visit_required"
    request.decided_by, request.decided_at = doctor, timezone.now()
    request.save()
    AuditEvent.objects.create(
        actor_type="staff", actor_id=str(doctor.id), patient=request.patient,
        action="refill.visit_required",
        payload={"request_id": request.id},
    )
    emit("refill.visit_required", patient_id=request.patient_id,
         request_id=request.id,
         medication=request.prescription.medication_name)


# -- pharmacy leg (FR-M8) -----------------------------------------------------

def send_to_pharmacy(request: RefillRequest, prescription: Prescription,
                     gateway=None) -> str:
    """Transmit via the e-Rx gateway (log-only in dev) and tell the patient."""
    reference = (gateway or default_gateway()).transmit(prescription, request.pharmacy)
    request.status = "sent_to_pharmacy"
    request.save(update_fields=["status"])
    notify(request.patient, "refill_sent", {
        "name": request.patient.first_name,
        "medication": prescription.medication_name,
        "pharmacy": request.pharmacy.name,
    })
    return reference


def mark_ready_for_pickup(request: RefillRequest) -> None:
    """Called when the pharmacy confirms (webhook later; manual/admin now)."""
    request.status = "ready_for_pickup"
    request.save(update_fields=["status"])
    notify(request.patient, "refill_ready", {
        "name": request.patient.first_name,
        "medication": request.prescription.medication_name,
        "pharmacy": request.pharmacy.name,
    })
