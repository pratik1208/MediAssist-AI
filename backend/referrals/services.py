"""Referral execution business logic (Agent 5, Phases 2 + 4).

Every write leaves an AuditEvent; cross-agent effects are events only
(referral.created / referral.status_changed — ORCHESTRATION §3 lists these
as the two events this agent emits), never direct imports into other
agents' modules for BEHAVIOR. Reading another agent's models to assemble a
view is already established elsewhere (refills' build_renewal_summary reads
registration.IntakeSummary/UploadedDocument the same way _collect_chart_items
below does) — the rule is about not triggering another agent's logic
directly, not about read-only aggregation. The one exception for behavior is
booking: FR-F5 explicitly says to reuse Agent 1's calendar, so this module
calls scheduling.services directly, the same way scheduling.services calls
core.notifications directly — both are the designated single door for that
concern.

AI entry points (build_referral_package, parse_consultation_report) import
referrals.ai lazily inside the function, exactly like refills' _physician_summary
— this keeps the AI dependency optional and makes the never-block-on-AI-
failure fallback path obvious at the call site.
"""

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from core.events import emit
from core.models import AuditEvent, Doctor, Specialty
from core.notifications import notify
from refills.models import Prescription
from registration.models import InsurancePolicy, IntakeSummary, UploadedDocument
from referrals.models import (
    ConsultationReport,
    Referral,
    ReferralPackage,
    Specialist,
    SpecialistOutreachTask,
)
from scheduling.models import Appointment
from scheduling.services import book_appointment
from triage.models import EscalationAlert

log = logging.getLogger("referrals")

STALLED_THRESHOLD_DAYS = 14


def _audit(patient, action: str, payload: dict) -> None:
    AuditEvent.objects.create(
        actor_type="agent", actor_id="referrals", patient=patient,
        action=action, payload=payload,
    )


# -- FR-F1: one-click creation ------------------------------------------------

@transaction.atomic
def create_referral(doctor, patient, specialty: str, reason: str, urgency: str) -> Referral:
    """The physician's one-click entry point (FR-F1)."""
    referral = Referral.objects.create(
        patient=patient, referring_doctor=doctor, specialty_needed=specialty,
        reason=reason, urgency=urgency, status="created",
        status_history=[{"status": "created", "at": timezone.now().isoformat()}],
    )
    _audit(patient, "referral.created", {"referral_id": referral.id, "specialty": specialty})
    emit("referral.created", referral_id=referral.id, patient_id=patient.id, specialty=specialty)
    return referral


# -- Phase 6: triage handoff (FR-T7 route_hint "specialist" -> FR-F1) --------

# Protocols carry no specialty of their own (they're symptom-matching data,
# not clinical routing data) — this is deliberately local to referrals
# rather than a new field on triage.ClinicalProtocol, so Agent 3's already-
# shipped model stays untouched. Extend this, not triage, as protocols grow.
_SPECIALTY_FOR_PROTOCOL = {
    "Adult Chest Pain": Specialty.CARDIOLOGY,
    "Pediatric Fever": Specialty.PEDIATRICS,
    "Headache": Specialty.NEUROLOGY,
    "Abdominal Pain": Specialty.GASTROENTEROLOGY,
    "Adult Fever Protocol": Specialty.GENERAL_MEDICINE,
}

# TriageAssessment.acuity has "minimal"; Referral.urgency (scheduling's
# enum) has "routine" instead — everything else lines up directly.
_URGENCY_FOR_ACUITY = {
    "minimal": "routine", "low": "low", "medium": "medium",
    "high": "high", "emergency": "emergency",
}


@transaction.atomic
def create_draft_referral_from_triage(patient, assessment) -> Referral:
    """Triage flagged a specialist need (findings.route_hint == "specialist")
    -> auto-create a draft referral so the patient never repeats their story.

    referring_doctor is deliberately left null: a physician must still
    confirm this draft (see accept_referral) before it can proceed — triage
    decided a specialist MIGHT be warranted, not that a doctor already
    reviewed and agreed.
    """
    protocol_name = assessment.clinical_protocol.name if assessment.clinical_protocol else None
    specialty = _SPECIALTY_FOR_PROTOCOL.get(protocol_name, Specialty.GENERAL_MEDICINE)
    symptoms_text = (assessment.reported_symptoms or {}).get("text", "").strip()
    reason = assessment.summary_text.strip() if assessment.summary_text else (
        f"Triage-flagged referral: {symptoms_text}" if symptoms_text
        else "Referred from symptom triage"
    )
    urgency = _URGENCY_FOR_ACUITY.get(assessment.acuity, "routine")

    referral = Referral.objects.create(
        patient=patient, referring_doctor=None, specialty_needed=specialty,
        reason=reason, urgency=urgency, status="created",
        status_history=[{"status": "created", "at": timezone.now().isoformat()}],
    )
    _audit(patient, "referral.created", {
        "referral_id": referral.id, "specialty": specialty,
        "source": "triage_handoff", "assessment_id": assessment.id,
    })
    emit("referral.created", referral_id=referral.id, patient_id=patient.id, specialty=specialty)
    log.info("[TRIAGE HANDOFF] draft referral %s created for patient %s from assessment %s",
              referral.id, patient.id, assessment.id)
    return referral


# -- FR-F3/F5: matching -------------------------------------------------------

def _zip_distance(patient_zip, specialist_postal) -> int:
    """A deterministic stand-in for real geocoding (no lat/lng service in
    dev): the numeric gap between two postal codes. Not real distance —
    just consistent and testable. A missing or non-numeric code sorts last,
    never treated as "close"."""
    try:
        return abs(int(str(patient_zip)) - int(str(specialist_postal)))
    except (TypeError, ValueError):
        return 10**9


def match_specialists(referral: Referral, patient) -> list[Specialist]:
    """Filter + rank specialists for a referral (FR-F3, FR-F5).

    Hard filters (excluded entirely): wrong specialty, not accepting new
    patients, and — only when the patient HAS an insurance policy on file —
    no overlap with the specialist's accepted insurances. An uninsured
    patient is never blocked; there is nothing yet to check compatibility
    against (same philosophy as registration's inactive-insurance handling:
    missing/imperfect insurance data never stops the workflow).

    Ranking (best first): same city as the patient, then nearest postal
    code, then a language-match bonus, then id for a stable order.
    """
    candidates = list(Specialist.objects.filter(
        specialty=referral.specialty_needed, accepting_new_patients=True,
    ))

    patient_insurances = {
        name.lower() for name in InsurancePolicy.objects
        .filter(patient=patient).values_list("provider_name", flat=True)
    }
    if patient_insurances:
        candidates = [
            s for s in candidates
            if patient_insurances & {i.lower() for i in (s.accepted_insurances or [])}
        ]

    patient_address = patient.address or {}
    patient_city = str(patient_address.get("city", "")).strip().lower()
    patient_zip = patient_address.get("zip")

    def rank_key(specialist: Specialist):
        s_address = specialist.address or {}
        same_city = 0 if patient_city and str(s_address.get("city", "")).strip().lower() == patient_city else 1
        distance = _zip_distance(patient_zip, s_address.get("postal_code"))
        language_bonus = 0 if patient.preferred_language in (specialist.languages or []) else 1
        return (same_city, distance, language_bonus, specialist.id)

    return sorted(candidates, key=rank_key)


# -- FR-F4: specialty-specific supporting documents ---------------------------

# Config, not code: which document categories a specialty's office typically
# needs attached to the referral package. Extend this dict, don't branch on
# specialty elsewhere.
REQUIRED_DOCUMENTS_BY_SPECIALTY: dict[str, list[str]] = {
    Specialty.CARDIOLOGY: ["ecg", "echocardiogram", "lipid_panel", "recent_progress_notes"],
    Specialty.ORTHOPEDICS: ["imaging_xray_or_mri", "surgery_notes", "recent_progress_notes"],
    Specialty.NEUROLOGY: ["imaging_ct_or_mri", "recent_progress_notes", "medication_list"],
    Specialty.GASTROENTEROLOGY: ["recent_labs", "imaging_abdominal", "recent_progress_notes"],
    Specialty.ENDOCRINOLOGY: ["recent_labs", "medication_list"],
    Specialty.PULMONOLOGY: ["pulmonary_function_test", "imaging_chest_xray", "recent_progress_notes"],
    Specialty.DERMATOLOGY: ["lesion_photos", "recent_progress_notes"],
    Specialty.GYNECOLOGY: ["recent_labs", "imaging_ultrasound", "recent_progress_notes"],
    Specialty.UROLOGY: ["recent_labs", "imaging_renal", "recent_progress_notes"],
    Specialty.ONCOLOGY: ["pathology_report", "imaging", "recent_labs", "recent_progress_notes"],
    Specialty.PSYCHIATRY: ["recent_progress_notes", "medication_list"],
    Specialty.OPHTHALMOLOGY: ["recent_progress_notes"],
    Specialty.ENT: ["imaging", "recent_progress_notes"],
    Specialty.PEDIATRICS: ["growth_chart", "immunization_record", "recent_progress_notes"],
    Specialty.GENERAL_MEDICINE: ["recent_labs", "recent_progress_notes"],
}
DEFAULT_REQUIRED_DOCUMENTS = ["recent_progress_notes"]


def required_documents_for(specialty: str) -> list[str]:
    return REQUIRED_DOCUMENTS_BY_SPECIALTY.get(specialty, DEFAULT_REQUIRED_DOCUMENTS)


# -- status machine (FR-F7) ---------------------------------------------------

PIPELINE = [
    "created", "accepted", "appointment_scheduled", "patient_confirmed",
    "visit_completed", "report_received", "closed",
]

# Forward one step, or sideways into "stalled" from anywhere active.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    status: {PIPELINE[i + 1], "stalled"} for i, status in enumerate(PIPELINE[:-1])
}
ALLOWED_TRANSITIONS["closed"] = set()  # terminal — nothing leaves it
# A stalled referral resumes wherever a coordinator determines is accurate —
# any pipeline step except back to the very start.
ALLOWED_TRANSITIONS["stalled"] = set(PIPELINE[1:])


class IllegalStatusTransition(Exception):
    """Raised when new_status isn't reachable from the referral's current status."""


@transaction.atomic
def advance_status(referral: Referral, new_status: str) -> Referral:
    if new_status not in ALLOWED_TRANSITIONS.get(referral.status, set()):
        raise IllegalStatusTransition(
            f"cannot move referral #{referral.id} from {referral.status!r} to {new_status!r}"
        )
    old_status = referral.status
    referral.status = new_status
    referral.status_history = [
        *referral.status_history,
        {"status": new_status, "at": timezone.now().isoformat()},
    ]
    referral.save(update_fields=["status", "status_history"])
    _audit(referral.patient, "referral.status_changed",
           {"referral_id": referral.id, "from": old_status, "to": new_status})
    emit("referral.status_changed", referral_id=referral.id, patient_id=referral.patient_id,
         old_status=old_status, new_status=new_status)
    return referral


def resume_referral(referral: Referral) -> Referral:
    """Move a stalled referral back to whatever status it was in right
    before it stalled.

    The generic transition graph lets "stalled" jump to any pipeline step
    (a coordinator's call), but the specific action functions below
    (book_specialist_visit, close_loop) each have their own STRICTER
    precondition than the graph — book requires exactly "accepted", close
    requires the visit to actually be done — on purpose, so a stalled
    referral can never skip a real step (e.g. jump straight to "closed"
    without a visit ever happening). Resuming first, then using the normal
    action, is what keeps those preconditions meaningful instead of working
    around them.
    """
    if referral.status != "stalled":
        raise IllegalStatusTransition(f"referral #{referral.id} is not stalled")
    previous = next(
        (entry["status"] for entry in reversed(referral.status_history)
         if entry["status"] != "stalled"),
        None,
    )
    # "created" is deliberately never a resume target (ALLOWED_TRANSITIONS
    # never allows it) — a real referral's history always has a prior step
    # since create_referral() seeds "created" first; missing/only-stalled
    # history means the data itself is inconsistent, so this must raise
    # rather than guess a status the referral was never actually in.
    if previous is None or previous == "created":
        raise IllegalStatusTransition(
            f"referral #{referral.id} has no valid prior status to resume to"
        )
    return advance_status(referral, previous)


# -- specialist-side (simulated): accept + prior-auth signal (Phase 6) ------

@transaction.atomic
def accept_referral(referral: Referral, specialist: Specialist, doctor: Doctor | None = None) -> Referral:
    """Specialist's office accepts the referral (FR-F3), simulated by a
    coordinator's click.

    A draft with no referring_doctor (Phase 6 triage handoff) MUST be
    confirmed with a real doctor here — physician confirmation is the gate
    that turns "triage thinks a specialist might help" into an actual
    referral, so it can never be skipped. A referral that already has a
    referring_doctor (the normal FR-F1 physician-created path) ignores a
    passed-in doctor rather than silently reassigning it.
    """
    if referral.referring_doctor is None:
        if doctor is None:
            raise ValueError(
                f"referral #{referral.id} is a draft from triage — a referring "
                "physician must confirm it (doctor_id) before it can be accepted"
            )
        referral.referring_doctor = doctor

    referral.specialist = specialist
    referral.save(update_fields=["specialist", "referring_doctor"])
    advance_status(referral, "accepted")

    # Forward-compatible signal (Agent 6 doesn't exist yet): emitted for
    # every acceptance, not filtered here — deciding whether THIS specialty/
    # payer combination actually requires authorization is Agent 6's own
    # PayerRule matching job, not something Agent 5 should guess at.
    emit("priorauth.needed", referral_id=referral.id, patient_id=referral.patient_id,
         specialty_needed=referral.specialty_needed, specialist_id=specialist.id)
    return referral


# -- FR-F5 (booking half): reuse Agent 1's calendar ---------------------------

@transaction.atomic
def book_specialist_visit(referral: Referral, slot: tuple) -> Appointment:
    """Book the specialist appointment and advance the referral.

    slot is a (start, end) datetime pair, the same shape
    scheduling.services.find_available_slots returns. Only in-network
    specialists (Specialist.internal_doctor set) are bookable this way —
    contacting an out-of-network office (FR-F3's automated call/email/API)
    is a simulated outreach channel that is explicitly Phase 4 scope.
    """
    if referral.status != "accepted":
        raise IllegalStatusTransition(
            f"cannot book referral #{referral.id}: status is {referral.status!r}, "
            "expected 'accepted'"
        )
    if referral.specialist is None:
        raise ValueError(f"referral #{referral.id} has no matched specialist yet")
    doctor = referral.specialist.internal_doctor
    if doctor is None:
        raise ValueError(
            f"{referral.specialist.name} is out-of-network (no internal_doctor) — "
            "booking their calendar directly isn't supported yet; contact them "
            "via their contact_channel instead"
        )

    start, end = slot
    appointment = book_appointment(
        doctor=doctor, patient=referral.patient, start=start, end=end,
        reason=f"Specialist referral: {referral.reason}", urgency=referral.urgency,
        source="referrals",
    )
    referral.appointment = appointment
    referral.save(update_fields=["appointment"])
    advance_status(referral, "appointment_scheduled")
    return appointment


# -- FR-F9: stalled referrals --------------------------------------------------

def check_stalled_referrals(threshold_days: int = STALLED_THRESHOLD_DAYS) -> list[Referral]:
    """Anything not closed and created more than threshold_days ago is
    flagged stalled and raises a care-coordinator alert. Safe to run
    repeatedly (a management command now; a scheduled job later, Phase 7) —
    an already-stalled or already-closed referral is left alone.
    """
    cutoff = timezone.now() - timedelta(days=threshold_days)
    overdue = Referral.objects.filter(created_at__lte=cutoff).exclude(
        status__in=["closed", "stalled"],
    )

    flagged = []
    for referral in overdue:
        last_status = referral.status
        advance_status(referral, "stalled")
        alert = EscalationAlert.objects.create(
            assessment=None, patient=referral.patient, source_agent="referrals",
            # No dedicated category exists for this yet — "other" is the
            # established bucket other agents use for cases outside the
            # fixed clinical categories (see refills' controlled_substance
            # alert for the pattern this follows).
            category="other",
            priority="high" if referral.urgency in ("emergency", "high") else "medium",
            summary=(
                f"Referral #{referral.id} for {referral.patient.first_name} "
                f"{referral.patient.last_name} ({referral.specialty_needed}) has been "
                f"incomplete for over {threshold_days} days — was stuck at {last_status!r}."
            ),
        )
        log.warning("[STALLED REFERRAL] referral %s patient %s (was %s)",
                    referral.id, referral.patient_id, last_status)
        emit("escalation.created", alert_id=alert.id, patient_id=referral.patient_id,
             category="stalled_referral")
        flagged.append(referral)
    return flagged


# -- FR-F8: missed specialist appointment -------------------------------------
# handle_missed_appointment() implements a progressive follow-up workflow: first a patient reminder, then escalation to the physician and stalling of the referral if the patient continues to miss the specialist appointment.
def handle_missed_appointment(referral: Referral, attempt: int = 1) -> dict:
    """The missed-appointment chain: attempt 1 reminds the patient and
    offers to reschedule; attempt 2+ (nothing changed) escalates to the
    referring physician and stalls the referral.

    Doctor has no notification channel modeled yet (no email/phone field),
    so "notify the referring physician" surfaces as a staff-visible
    escalation alert — the same mechanism refills already uses when a
    decision needs a human, not an automated patient-facing message.
    """
    notify(referral.patient, "referral_missed_appointment", {
        "name": referral.patient.first_name, "specialty": referral.specialty_needed,
    })
    _audit(referral.patient, "referral.appointment_missed",
           {"referral_id": referral.id, "attempt": attempt})

    if attempt <= 1:
        log.info("[MISSED APPOINTMENT] referral %s patient %s — reminder sent",
                  referral.id, referral.patient_id)
        return {"action": "reminder_sent"}

    alert = EscalationAlert.objects.create(
        assessment=None, patient=referral.patient, source_agent="referrals",
        category="other", priority="medium",
        summary=(
            f"Referral #{referral.id} ({referral.specialty_needed}) — patient "
            f"{referral.patient.first_name} {referral.patient.last_name} missed the "
            "specialist appointment and has not requested a reschedule. Referring "
            # A missed appointment can only happen once a visit was booked,
            # which requires accept_referral() to have already confirmed a
            # referring_doctor — this is never null here.
            f"physician Dr. {referral.referring_doctor.name} should follow up."
        ),
    )
    log.warning("[MISSED APPOINTMENT] referral %s patient %s — physician notified",
                referral.id, referral.patient_id)
    emit("escalation.created", alert_id=alert.id, patient_id=referral.patient_id,
         category="missed_appointment")
    if "stalled" in ALLOWED_TRANSITIONS.get(referral.status, set()):
        advance_status(referral, "stalled")
    return {"action": "physician_notified", "alert_id": alert.id}


# -- FR-F10: close the loop ---------------------------------------------------
# close_loop() imports the specialist's consultation report, updates the referral to report_received and closed, records an audit trail, and completes the referral lifecycle so the primary physician receives the specialist's findings.
@transaction.atomic
def close_loop(referral: Referral, report_data: dict) -> ConsultationReport:
    """Import the specialist's consultation report and close the referral.

    report_data: {"diagnosis", "treatment_plan", "medications",
    "followup_recommendations", "source_document"} — the shape Phase 4's
    parse_consultation_report() will produce from an uploaded report.

    "Notify the referring physician" here is a passive FYI (the loop is
    closed, nothing needs the physician to act), unlike the missed-
    appointment case — so this doesn't raise an EscalationAlert. The
    referral.status_changed event (new_status="closed") plus the AuditEvent
    trail are the physician-visible signal; a dedicated inbox is Phase 5's
    provider dashboard, not Phase 2 scope.
    """
    if referral.status not in ("visit_completed", "report_received"):
        raise IllegalStatusTransition(
            f"cannot close referral #{referral.id} from status {referral.status!r} "
            "— the visit must be completed first"
        )

    report, _created = ConsultationReport.objects.update_or_create(
        referral=referral,
        defaults={
            "diagnosis": report_data.get("diagnosis", ""),
            "treatment_plan": report_data.get("treatment_plan", ""),
            "medications": report_data.get("medications", []),
            "followup_recommendations": report_data.get("followup_recommendations", []),
            "source_document": report_data.get("source_document"),
        },
    )
    if referral.status == "visit_completed":
        advance_status(referral, "report_received")
    advance_status(referral, "closed")
    _audit(referral.patient, "referral.closed",
           {"referral_id": referral.id, "report_id": report.id})
    # Reaching "closed" requires having passed through accept_referral(),
    # which never lets a referral become "accepted" without a
    # referring_doctor — never null here.
    log.info("[REFERRAL CLOSED] referral %s patient %s -> Dr. %s notified",
              referral.id, referral.patient_id, referral.referring_doctor.name)
    return report


# -- FR-F2: AI-selected referral package (Phase 4) ---------------------------

# Which IntakeSummary.clinical_profile list fields become individually
# selectable chart items — mirrors registration/ai/handler.py's
# INTAKE_LIST_FIELDS (lifestyle is a dict, handled separately below).
_INTAKE_ITEM_FIELDS = ("symptoms", "medical_history", "medications", "allergies", "family_history")


def _collect_chart_items(patient) -> list[dict]:
    """Every discrete, taggable fact on the patient's record, each with a
    stable id and category — so build_referral_package can filter by
    whatever the model selects without ever trusting the model to
    reproduce chart content itself (only ids cross that boundary)."""
    items = []

    intake = IntakeSummary.objects.filter(patient=patient).order_by("-id").first()
    if intake:
        profile = intake.clinical_profile or {}
        for category in _INTAKE_ITEM_FIELDS:
            for i, entry in enumerate(profile.get(category) or []):
                items.append({"id": f"intake:{category}:{i}", "category": category, "text": str(entry)})
        for key, value in (profile.get("lifestyle") or {}).items():
            items.append({"id": f"intake:lifestyle:{key}", "category": "lifestyle",
                          "text": f"{key}: {value}"})

    for rx in Prescription.objects.filter(patient=patient, status="active"):
        items.append({
            "id": f"prescription:{rx.id}", "category": "medication",
            "text": f"{rx.medication_name} {rx.dose}",
        })

    # Same extraction shape refills.build_renewal_summary already reads.
    for doc in UploadedDocument.objects.filter(
        patient=patient, document_type="lab_report", extraction_status="done",
    ):
        report = (doc.extracted_data or {}).get("lab_report") or {}
        if report.get("test_name"):
            items.append({
                "id": f"document:{doc.id}", "category": "lab_report",
                "text": f"{report['test_name']}: {report.get('findings', '')} "
                        f"(date: {report.get('date', 'unknown')})",
            })
    return items

# Generate a summary when AI summary generation fails.
def _fallback_package_summary(referral: Referral, items: list[dict]) -> str:
    return (
        f"Referral to {referral.specialty_needed} for {referral.patient.first_name} "
        f"{referral.patient.last_name}: {referral.reason}. {len(items)} chart item(s) on "
        "file — AI summary unavailable, please review the patient's chart manually."
    )


@transaction.atomic
def build_referral_package(referral: Referral) -> ReferralPackage:
    """Select only the specialty-relevant chart items and write a concise
    referral summary (FR-F2).

    An AI outage must never block a referral from reaching a specialist —
    same resilience philosophy as refills' physician summary — so failure
    falls back to attaching EVERYTHING (over-sharing full context is safer
    for continuity of care than a package that looks empty) with a plain
    deterministic summary line.
    """
    items = _collect_chart_items(referral.patient)
    known_ids = {item["id"] for item in items}
    try:
        from referrals.ai import select_referral_content  # local: keeps AI optional
        result = select_referral_content(referral.specialty_needed, referral.reason, items)
        selected_ids = [i for i in (result.get("selected_item_ids") or []) if i in known_ids]
        summary_text = result.get("summary_text") or _fallback_package_summary(referral, items)
    except Exception:
        log.warning("[REFERRAL PACKAGE] AI selection failed for referral %s — attaching everything",
                    referral.id)
        selected_ids = list(known_ids)
        summary_text = _fallback_package_summary(referral, items)

    selected_items = [item for item in items if item["id"] in selected_ids]
    attached_documents = [
        int(item["id"].split(":", 1)[1]) for item in selected_items
        if item["category"] == "lab_report"
    ]
    package, _created = ReferralPackage.objects.update_or_create(
        referral=referral,
        defaults={
            "selected_chart_data": {"items": selected_items},
            "summary_text": summary_text,
            "attached_documents": attached_documents,
        },
    )
    _audit(referral.patient, "referral.package_built",
           {"referral_id": referral.id, "item_count": len(selected_items)})
    return package


# -- FR-F10 (AI half): reading an uploaded consultation report --------------

def parse_consultation_report(document: UploadedDocument) -> dict:
    """Extract diagnosis/treatment_plan/medications/followups from an
    uploaded consultation report, in the exact shape close_loop() expects.

    Persists onto the UploadedDocument the same way registration's
    run_document_extraction does (extracted_data + extraction_status), so
    extraction bookkeeping stays consistent across agents. Unlike
    build_referral_package, a failure here is NOT swallowed — closing a
    referral with hallucinated or garbled clinical content is far worse
    than not closing it yet, so the caller must see the error and fall back
    to the structured-JSON path (a human types the fields) instead.
    """
    from referrals.ai import extract_consultation_report_fields  # local: keeps AI optional

    try:
        extracted = extract_consultation_report_fields(document)
    except Exception:
        document.extraction_status = "failed"
        document.save(update_fields=["extraction_status"])
        raise
    document.extracted_data = {**extracted, "extracted_at": timezone.now().isoformat()}
    document.extraction_status = "done" if extracted.get("legible", False) else "failed"
    document.save(update_fields=["extracted_data", "extraction_status"])

    if not extracted.get("legible", False):
        raise ValueError("consultation report could not be read reliably; re-upload or enter details manually")

    return {
        "diagnosis": extracted.get("diagnosis") or "",
        "treatment_plan": extracted.get("treatment_plan") or "",
        "medications": extracted.get("medications") or [],
        "followup_recommendations": extracted.get("followup_recommendations") or [],
        "source_document": document,
    }


# -- FR-F3: specialist-office outreach queue (Phase 4) -----------------------

# Templated messages only, per contact channel — a deliberate simplification.
# A voice agent placing real automated calls is a later enhancement; this
# queue just records what WOULD be sent (FR-F3's "automated call/email").
OUTREACH_TEMPLATES = {
    "phone": "Referral for {patient_name} ({specialty_needed}, urgency: {urgency}) — "
             "please call {practice_name} to confirm acceptance. Reason: {reason}",
    "email": "Referral request: {patient_name} ({specialty_needed}). Reason: {reason}. "
             "Please reply to confirm acceptance, earliest availability, and any "
             "documentation needed.",
    "e_referral": "Electronic referral submitted for {patient_name} ({specialty_needed}). "
                 "Reason: {reason}. Awaiting acceptance confirmation from {practice_name}.",
    "api": "Referral request transmitted via API integration to {practice_name} for "
          "{patient_name} ({specialty_needed}).",
}


def queue_specialist_outreach(referral: Referral, specialist: Specialist) -> SpecialistOutreachTask:
    """Queue the outbound contact-the-specialist's-office message (FR-F3)."""
    template = OUTREACH_TEMPLATES.get(specialist.contact_channel, OUTREACH_TEMPLATES["email"])
    message = template.format(
        practice_name=specialist.practice_name or specialist.name,
        patient_name=f"{referral.patient.first_name} {referral.patient.last_name}",
        specialty_needed=referral.specialty_needed, reason=referral.reason,
        urgency=referral.urgency,
    )
    task = SpecialistOutreachTask.objects.create(
        referral=referral, specialist=specialist, channel=specialist.contact_channel,
        message=message, status="queued",
    )
    log.info("[OUTREACH QUEUED] referral %s -> %s via %s",
              referral.id, specialist.name, specialist.contact_channel)
    return task


def mark_outreach_sent(task: SpecialistOutreachTask) -> SpecialistOutreachTask:
    task.status = "sent"
    task.sent_at = timezone.now()
    task.save(update_fields=["status", "sent_at"])
    return task


def mark_outreach_failed(task: SpecialistOutreachTask) -> SpecialistOutreachTask:
    task.status = "failed"
    task.save(update_fields=["status"])
    return task
