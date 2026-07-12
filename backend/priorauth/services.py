"""Prior authorization business logic (Agent 6, Phase 2) — no AI yet.

Same architectural rules as referrals/services.py: every write leaves an
AuditEvent; cross-agent effects are events, never direct behavior imports;
reading another agent's models to assemble evidence (registration's
IntakeSummary/UploadedDocument, refills' Prescription, referrals'
ConsultationReport) is the same established read-only-aggregation pattern
referrals' _collect_chart_items already uses — not a rule violation.
"""

import logging
import re
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from core.events import emit
from core.models import AuditEvent
from core.notifications import notify
from priorauth.gateway import PayerGateway, default_gateway
from priorauth.models import (
    AuthorizationPackage,
    AuthorizationRequest,
    PayerMessage,
    PayerRule,
    TreatmentOrder,
)
from referrals.models import ConsultationReport
from refills.models import Prescription
from registration.models import InsurancePolicy, IntakeSummary, UploadedDocument
from triage.models import EscalationAlert

log = logging.getLogger("priorauth")


def _audit(patient, action: str, payload: dict) -> None:
    AuditEvent.objects.create(
        actor_type="agent", actor_id="priorauth", patient=patient,
        action=action, payload=payload,
    )


# -- FR-P1: detection ---------------------------------------------------------

@dataclass
class DetectionResult:
    requires_auth: bool
    rule: PayerRule | None = None
    required_documentation: list[str] = field(default_factory=list)


def _pattern_matches(pattern: str | None, value: str | None) -> bool:
    if not pattern or not value:
        return False
    try:
        return re.search(pattern, value, re.IGNORECASE) is not None
    except re.error:  # a malformed rule pattern must never crash detection
        return False


def detect_authorization_requirement(order: TreatmentOrder) -> DetectionResult:
    """FR-P1: determine whether prior authorization is required — fully
    automatically, no manual verification step.

    Matches the order's CPT/ICD-10/medication against PayerRules for the
    patient's insurance. No policy on file, or nothing matches, means "not
    required" — there's nothing configured to check against (same
    philosophy as registration's inactive-insurance handling: missing data
    never invents a requirement that isn't in the rules).
    """
    policy = InsurancePolicy.objects.filter(patient=order.patient).order_by("-id").first()
    if policy is None:
        return DetectionResult(requires_auth=False)

    candidates = PayerRule.objects.filter(payer_name__iexact=policy.provider_name)
    matched = []
    for rule in candidates:
        # A plan-specific rule only applies when the patient's own plan is
        # known and matches it; a rule with no plan set applies to any plan.
        if rule.plan and rule.plan.lower() != (policy.plan or "").lower():
            continue
        if (_pattern_matches(rule.cpt_pattern, order.cpt_code)
                or _pattern_matches(rule.icd10_pattern, order.icd10_code)
                or _pattern_matches(rule.medication_pattern, order.medication)):
            matched.append(rule)

    if not matched:
        return DetectionResult(requires_auth=False)

    # Most specific first: a plan-scoped rule outranks a payer-wide one —
    # same "specific beats generic" tie-break triage's select_protocol uses.
    matched.sort(key=lambda r: r.plan is None)
    rule = matched[0]
    return DetectionResult(
        requires_auth=rule.requires_auth, rule=rule,
        required_documentation=list(rule.required_documentation or []),
    )


@transaction.atomic
def initiate_authorization(order: TreatmentOrder) -> AuthorizationRequest | None:
    """The connective tissue FR-P1 and FR-P2 describe as one continuous
    automated flow: detect, and if required, open the request and gather
    evidence immediately. Returns None when no authorization is required —
    the order simply proceeds with no AuthorizationRequest at all.
    """
    result = detect_authorization_requirement(order)
    if not result.requires_auth:
        return None

    policy = InsurancePolicy.objects.filter(patient=order.patient).order_by("-id").first()
    auth_request = AuthorizationRequest.objects.create(
        order=order, policy=policy, matched_rule=result.rule, status="detected",
        status_history=[{"status": "detected", "at": timezone.now().isoformat()}],
    )
    _audit(order.patient, "priorauth.detected",
           {"request_id": auth_request.id, "order_id": order.id})
    log.info("[PA DETECTED] request %s for order %s (patient %s)",
              auth_request.id, order.id, order.patient_id)
    package = gather_evidence(auth_request)
    write_package_summary(package)
    return auth_request


# -- status machine ------------------------------------------------------------

PIPELINE = [
    "detected", "gathering_evidence", "ready_for_review", "submitted",
    "under_review", "info_requested",
]

# Forward-only; the later stages are deliberately permissive about which
# terminal/near-terminal state comes next — a real (or simulated) payer
# doesn't always pass through every conceptual stage explicitly (an instant
# approval can skip "under_review").
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "detected": {"gathering_evidence"},
    "gathering_evidence": {"ready_for_review"},
    "ready_for_review": {"submitted"},
    "submitted": {"under_review", "info_requested", "approved", "denied"},
    "under_review": {"info_requested", "approved", "denied"},
    "info_requested": {"under_review", "approved", "denied"},
    "approved": set(),  # terminal
    "denied": set(),  # terminal
}


class IllegalStatusTransition(Exception):
    """Raised when new_status isn't reachable from the request's current status."""


@transaction.atomic
def advance_status(auth_request: AuthorizationRequest, new_status: str) -> AuthorizationRequest:
    if new_status not in ALLOWED_TRANSITIONS.get(auth_request.status, set()):
        raise IllegalStatusTransition(
            f"cannot move authorization request #{auth_request.id} from "
            f"{auth_request.status!r} to {new_status!r}"
        )
    old_status = auth_request.status
    auth_request.status = new_status
    auth_request.status_history = [
        *auth_request.status_history,
        {"status": new_status, "at": timezone.now().isoformat()},
    ]
    auth_request.save(update_fields=["status", "status_history"])
    _audit(auth_request.order.patient, "priorauth.status_changed",
           {"request_id": auth_request.id, "from": old_status, "to": new_status})
    return auth_request


# -- FR-P2: evidence gathering -------------------------------------------------

def _collect_diagnosis(patient, order) -> list[str]:
    items = [order.icd10_code] if order.icd10_code else []
    intake = IntakeSummary.objects.filter(patient=patient).order_by("-id").first()
    if intake:
        items += list((intake.clinical_profile or {}).get("medical_history") or [])
    return items


def _collect_physician_notes(patient, order) -> list[str]:
    notes = []
    intake = IntakeSummary.objects.filter(patient=patient).order_by("-id").first()
    if intake and intake.summary_text:
        notes.append(intake.summary_text)
    if order.referral_id:
        report = ConsultationReport.objects.filter(referral_id=order.referral_id).first()
        if report and report.diagnosis:
            notes.append(f"Specialist note: {report.diagnosis}")
    return notes


def _collect_labs(patient, order) -> list[dict]:
    labs = []
    for doc in UploadedDocument.objects.filter(
        patient=patient, document_type="lab_report", extraction_status="done",
    ):
        report = (doc.extracted_data or {}).get("lab_report") or {}
        if report.get("test_name"):
            labs.append({"test": report.get("test_name"), "date": report.get("date"),
                        "findings": report.get("findings")})
    return labs


def _collect_imaging_reports(patient, order) -> list[dict]:
    reports = []
    for doc in UploadedDocument.objects.filter(
        patient=patient, document_type="imaging_report", extraction_status="done",
    ):
        reports.append({"document_id": doc.id,
                        "extracted": doc.extracted_data or {}})
    return reports


def _collect_medication_history(patient, order) -> list[str]:
    return [f"{rx.medication_name} {rx.dose}"
            for rx in Prescription.objects.filter(patient=patient)]


def _collect_prior_treatments(patient, order) -> list[str]:
    treatments = []
    for report in ConsultationReport.objects.filter(referral__patient=patient):
        if report.treatment_plan:
            treatments.append(report.treatment_plan)
    return treatments


def _collect_allergies(patient, order) -> list[str]:
    intake = IntakeSummary.objects.filter(patient=patient).order_by("-id").first()
    if intake:
        return list((intake.clinical_profile or {}).get("allergies") or [])
    return []


# Config, not code — extend this, not gather_evidence, as new categories
# appear in payer rules' required_documentation.
EVIDENCE_COLLECTORS = {
    "diagnosis": _collect_diagnosis,
    "physician_notes": _collect_physician_notes,
    "labs": _collect_labs,
    "imaging_reports": _collect_imaging_reports,
    "medication_history": _collect_medication_history,
    "prior_treatments": _collect_prior_treatments,
    "allergies": _collect_allergies,
}


@transaction.atomic
def gather_evidence(auth_request: AuthorizationRequest) -> AuthorizationPackage:
    """FR-P2: deterministic collection by category, from the patient's own
    record — the AI only summarizes this later (Phase 4); it never invents
    evidence that isn't actually on file.
    """
    order = auth_request.order
    patient = order.patient
    categories = auth_request.matched_rule.required_documentation if auth_request.matched_rule else []

    evidence = {}
    for category in categories:
        collector = EVIDENCE_COLLECTORS.get(category)
        evidence[category] = collector(patient, order) if collector else []

    package, _created = AuthorizationPackage.objects.update_or_create(
        request=auth_request,
        defaults={
            "demographics_snapshot": {
                "first_name": patient.first_name, "last_name": patient.last_name,
                "dob": patient.dob.isoformat(), "contact_number": patient.contact_number,
            },
            "codes": {"cpt_code": order.cpt_code, "icd10_code": order.icd10_code,
                     "medication": order.medication},
            "evidence": evidence,
        },
    )
    if auth_request.status == "detected":
        advance_status(auth_request, "gathering_evidence")
    if auth_request.status == "gathering_evidence":
        advance_status(auth_request, "ready_for_review")
    return package


# -- FR-P3: AI reviewer summary (Phase 4) -------------------------------------

def _fallback_reviewer_summary(package: AuthorizationPackage) -> str:
    """A plain deterministic summary built straight from the gathered
    evidence — used when the AI is unavailable. An AI outage must never
    leave a package without SOME reviewer-readable summary."""
    parts = []
    codes = package.codes or {}
    if codes.get("cpt_code"):
        parts.append(f"CPT {codes['cpt_code']}")
    if codes.get("icd10_code"):
        parts.append(f"ICD-10 {codes['icd10_code']}")
    if codes.get("medication"):
        parts.append(f"Medication: {codes['medication']}")
    for category, items in (package.evidence or {}).items():
        if items:
            preview = "; ".join(str(i) for i in items[:3])
            parts.append(f"{category.replace('_', ' ').title()}: {preview}")
    return (" | ".join(parts) if parts else
            "No supporting evidence on file — AI summary unavailable, please review manually.")


def write_package_summary(package: AuthorizationPackage) -> AuthorizationPackage:
    """FR-P3: the AI-written medical-necessity summary a payer reviewer
    reads. An AI outage must never block a request from reaching
    ready_for_review — same never-block philosophy as referrals'
    build_referral_package — so failure falls back to a plain deterministic
    summary instead of leaving reviewer_summary blank.
    """
    try:
        from priorauth.ai import write_reviewer_summary  # local: keeps AI optional
        result = write_reviewer_summary(package)
        lines = [result.get("clinical_justification") or ""]
        if result.get("relevant_history_points"):
            lines.append("Relevant history: " + "; ".join(result["relevant_history_points"]))
        if result.get("guideline_citations"):
            lines.append("Guidelines: " + "; ".join(result["guideline_citations"]))
        summary = "\n".join(line for line in lines if line)
    except Exception:
        log.warning("[PA SUMMARY] AI summary failed for package %s — using fallback", package.id)
        summary = _fallback_reviewer_summary(package)
    package.reviewer_summary = summary or _fallback_reviewer_summary(package)
    package.save(update_fields=["reviewer_summary"])
    return package


# -- FR-P4: submission ----------------------------------------------------------

@transaction.atomic
def submit(auth_request: AuthorizationRequest, gateway: PayerGateway | None = None) -> AuthorizationRequest:
    """Dispatch through the rule's channel via the gateway; record the
    submission (PayerMessage) and advance status."""
    gateway = gateway or default_gateway()
    package = auth_request.package
    reference = gateway.submit(auth_request, package)
    auth_request.external_reference = reference
    auth_request.save(update_fields=["external_reference"])

    channel = auth_request.matched_rule.submission_channel if auth_request.matched_rule else "unknown"
    PayerMessage.objects.create(
        request=auth_request, direction="outbound",
        content=(f"Submitted via {channel}: order #{auth_request.order_id}, "
                 f"codes={package.codes}, reference={reference}"),
    )
    advance_status(auth_request, "submitted")
    log.info("[PA SUBMITTED] request %s -> %s (ref %s)",
              auth_request.id, channel, reference)
    return auth_request


# -- FR-P5: polling ---------------------------------------------------------

def _interpret_raw_payer_message(raw_text: str) -> dict:
    """FR-P5/P6 (Phase 4): a real payer channel hands back unstructured
    text, not neat JSON — AI-interpret it into the same {status,
    requested_items} shape the rest of the pipeline already understands. An
    interpretation failure must never invent a decision: it falls back to
    "under_review" (keep waiting), never to "approved"/"denied"."""
    try:
        from priorauth.ai import interpret_payer_message
        parsed = interpret_payer_message(raw_text)
        requested_items = parsed.get("info_requested") or []
        decision = parsed.get("decision")
        # Trust the structural signal over the free-text label: a live
        # provider run caught the model naming concrete requested_items
        # while giving a "decision" that wasn't literally "info_requested"
        # — those extracted items are what functionally matters, so they
        # must not go unused just because the label didn't match exactly.
        # An explicit approved/denied still wins outright (unambiguous).
        if decision in ("approved", "denied"):
            status = decision
        elif requested_items:
            status = "info_requested"
        else:
            status = decision or "under_review"
        return {
            "status": status,
            "requested_items": requested_items,
            "deadline": parsed.get("deadline"),
        }
    except Exception:
        log.warning("[PA MESSAGE] AI interpretation failed for raw payer text — "
                    "treating as still under review")
        return {"status": "under_review"}


def poll_status(auth_request: AuthorizationRequest, gateway: PayerGateway | None = None) -> AuthorizationRequest:
    """Ask the gateway what's happening and react. Safe to call repeatedly
    (a management command now; a scheduled job later, Phase 7) — a request
    already at approved/denied is left alone."""
    if auth_request.status in ("approved", "denied"):
        return auth_request
    gateway = gateway or default_gateway()
    result = gateway.check_status(auth_request)

    raw_text = result.get("raw_text")
    if raw_text is not None and "status" not in result:
        result = {**_interpret_raw_payer_message(raw_text), "raw_text": raw_text}
    payer_status = result.get("status", "under_review")

    PayerMessage.objects.create(
        request=auth_request, direction="inbound",
        content=raw_text or f"Payer status check: {payer_status}", parsed=result,
    )

    if payer_status == "info_requested":
        advance_status(auth_request, "info_requested")
        handle_info_request(auth_request, result.get("requested_items", []))
    elif payer_status == "denied":
        auth_request.denial_reason = result.get("denial_reason", "")
        auth_request.appeal_suggested = bool(result.get("appeal_suggested", False))
        auth_request.save(update_fields=["denial_reason", "appeal_suggested"])
        advance_status(auth_request, "denied")
        on_decision(auth_request)
    elif payer_status == "approved":
        advance_status(auth_request, "approved")
        on_decision(auth_request)
    elif payer_status == "under_review" and auth_request.status != "under_review":
        advance_status(auth_request, "under_review")
    return auth_request


# -- FR-P6: additional-information requests (PRD Edge Case 10) ---------------

def handle_info_request(auth_request: AuthorizationRequest, requested_items: list[str]) -> dict:
    """Try to auto-answer every requested item from the patient's record;
    anything not found is staged for a human instead of resubmitting an
    incomplete package or failing silently."""
    order = auth_request.order
    patient = order.patient
    package = auth_request.package

    found, missing = {}, []
    for category in requested_items:
        collector = EVIDENCE_COLLECTORS.get(category)
        items = collector(patient, order) if collector else []
        if items:
            found[category] = items
        else:
            missing.append(category)

    if missing:
        alert = EscalationAlert.objects.create(
            assessment=None, patient=patient, source_agent="priorauth",
            category="other", priority="medium",
            summary=(
                f"Authorization request #{auth_request.id} — the payer requested "
                f"{', '.join(missing)}, which couldn't be found in "
                f"{patient.first_name} {patient.last_name}'s record. Staff review needed."
            ),
        )
        emit("escalation.created", alert_id=alert.id, patient_id=patient.id,
             category="priorauth_info_missing")
        log.warning("[PA INFO REQUEST] request %s missing %s — staged for staff",
                    auth_request.id, missing)
        return {"action": "staged_for_staff", "missing": missing, "found": list(found)}

    package.evidence = {**package.evidence, **found}
    package.save(update_fields=["evidence"])
    PayerMessage.objects.create(
        request=auth_request, direction="outbound",
        content=f"Auto-resubmitted requested items: {', '.join(requested_items)}",
    )
    advance_status(auth_request, "under_review")
    log.info("[PA INFO REQUEST] request %s auto-resubmitted %s",
              auth_request.id, requested_items)
    return {"action": "auto_resubmitted", "items": requested_items}


# -- FR-P7: final decision ---------------------------------------------------

def on_decision(auth_request: AuthorizationRequest) -> None:
    """React to a final payer decision.

    Doctor has no notification channel modeled yet (same limitation noted
    in referrals.services.close_loop) — "notify the physician" surfaces via
    the audit trail + log; the patient gets a real message. Approval also
    emits priorauth.approved (ORCHESTRATION §3: Scheduling books the
    treatment) — nobody consumes it yet, forward-compatible like referrals'
    priorauth.needed was before this agent existed.
    """
    order = auth_request.order
    patient = order.patient
    treatment = order.medication or order.cpt_code or order.order_type

    if auth_request.status == "approved":
        notify(patient, "priorauth_approved", {"name": patient.first_name, "treatment": treatment})
        _audit(patient, "priorauth.approved", {"request_id": auth_request.id})
        emit("priorauth.approved", request_id=auth_request.id, patient_id=patient.id,
             order_id=order.id, treatment=treatment)
        log.info("[PA APPROVED] request %s patient %s — physician notified, "
                  "Scheduling can book the treatment", auth_request.id, patient.id)
    elif auth_request.status == "denied":
        notify(patient, "priorauth_denied", {
            "name": patient.first_name, "treatment": treatment,
            "reason": auth_request.denial_reason or "no reason given",
        })
        _audit(patient, "priorauth.denied", {
            "request_id": auth_request.id, "reason": auth_request.denial_reason,
            "appeal_suggested": auth_request.appeal_suggested,
        })
        emit("priorauth.denied", request_id=auth_request.id, patient_id=patient.id,
             reason=auth_request.denial_reason, appeal_suggested=auth_request.appeal_suggested)
        log.info("[PA DENIED] request %s patient %s — physician notified (reason: %s)",
                  auth_request.id, patient.id, auth_request.denial_reason)


# -- FR-P7 / Edge Case 9: appeal suggestion (Phase 4, suggest only) ----------

def suggest_appeal_for(auth_request: AuthorizationRequest) -> dict:
    """On denial, an appeal recommendation + draft argument for the
    physician to review. Suggest only — the PRD explicitly marks automated
    appeal SUBMISSION as a future enhancement; nothing here submits
    anything or changes the request's own status/appeal_suggested flag
    (that flag reflects the PAYER's signal from poll_status, a separate,
    earlier fact from this AI recommendation).
    """
    if auth_request.status != "denied":
        raise ValueError(f"authorization request #{auth_request.id} is not denied")

    package = auth_request.package
    try:
        from priorauth.ai import suggest_appeal
        return suggest_appeal(auth_request.denial_reason or "", {
            "codes": package.codes, "evidence": package.evidence,
        })
    except Exception:
        log.warning("[PA APPEAL] AI appeal suggestion failed for request %s", auth_request.id)
        return {
            "should_appeal": None,
            "recommendation": "AI appeal suggestion unavailable — please review the denial manually.",
            "draft_argument": None,
        }
