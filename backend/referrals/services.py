"""Referral execution business logic (Agent 5, Phase 2) — no AI yet.

Every write leaves an AuditEvent; cross-agent effects are events only
(referral.created / referral.status_changed — ORCHESTRATION §3 lists these
as the two events this agent emits), never direct imports into other
agents' modules. The one exception is booking: FR-F5 explicitly says to
reuse Agent 1's calendar, so this module calls scheduling.services directly,
the same way scheduling.services calls core.notifications directly — both
are the designated single door for that concern.
"""

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from core.events import emit
from core.models import AuditEvent, Specialty
from core.notifications import notify
from registration.models import InsurancePolicy
from referrals.models import ConsultationReport, Referral, Specialist
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
    log.info("[REFERRAL CLOSED] referral %s patient %s -> Dr. %s notified",
              referral.id, referral.patient_id, referral.referring_doctor.name)
    return report
