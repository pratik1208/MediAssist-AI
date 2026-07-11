"""Business logic for patient registration (Phase 2 — no AI).

Every function here takes plain Python inputs so it can be tested with
pytest before any API or AI layer is added on top.
"""

import hashlib
import re
import secrets
from datetime import timedelta
from difflib import SequenceMatcher

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.events import emit
from core.models import AuditEvent, EventLog, OTPChallenge, Patient, SentNotification
from registration.eligibility import EligibilityResult, PayerEligibilityGateway, default_gateway
from registration.models import InsurancePolicy, IntakeSummary

# How similar two last names must be (0..1) to count as a fuzzy match.
# "Sharma" vs "Sharme" scores 0.83; "Sharma" vs "Patel" scores 0.18.
NAME_SIMILARITY_THRESHOLD = 0.8


def normalize_phone(phone: str) -> str:
    """Reduce a phone number to its last 10 digits so different formats compare equal.

    '+91 98765-43210', '098765 43210' and '9876543210' all become '9876543210'.
    """
    digits = re.sub(r"\D", "", phone or "")
    return digits[-10:]


def _last_name(full_name: str) -> str:
    parts = (full_name or "").strip().split()
    return parts[-1] if parts else ""


def _names_similar(a: str, b: str) -> bool:
    if not a or not b:
        return False
    return SequenceMatcher(None, a.lower(), b.lower()).ratio() >= NAME_SIMILARITY_THRESHOLD


def find_matching_patients(name: str, dob, phone: str) -> tuple[str, list[Patient]]:
    """Duplicate check before creating a patient record (FR-R3).

    Returns (status, matches):
      - ("existing", [patients]) — same dob and same phone: treat as the
        same person returning.
      - ("possible_duplicate", [patients]) — same dob and a similar last
        name but a different phone: a human must decide; never auto-create
        a second record (PRD Edge Case 4).
      - ("new", []) — nobody with this dob looks like a match.
    """
    phone_n = normalize_phone(phone)
    last = _last_name(name)

    exact, fuzzy = [], []
    for patient in Patient.objects.filter(dob=dob):
        if phone_n and normalize_phone(patient.contact_number) == phone_n:
            exact.append(patient)
        elif _names_similar(last, patient.last_name):
            fuzzy.append(patient)

    if exact:
        return "existing", exact
    if fuzzy:
        return "possible_duplicate", fuzzy
    return "new", []


OTP_TTL_MINUTES = 10


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def create_otp(patient: Patient, channel: str) -> OTPChallenge:
    """Generate a 6-digit code for the patient and 'send' it (FR-R2).

    Only the SHA-256 hash of the code is stored on the challenge. In dev,
    sending means printing to the console and logging a SentNotification
    row; a real SMS/email provider replaces that in Phase 7.
    """
    now = timezone.now()

    # A new code cancels any older unused ones, so only the latest counts.
    OTPChallenge.objects.filter(
        patient=patient, consumed_at__isnull=True, expires_at__gt=now
    ).update(expires_at=now)

    code = f"{secrets.randbelow(10**6):06d}"
    challenge = OTPChallenge.objects.create(
        patient=patient,
        channel=channel,
        code_hash=_hash_code(code),
        expires_at=now + timedelta(minutes=OTP_TTL_MINUTES),
    )

    recipient = patient.email if channel == "email" else patient.contact_number
    body = (
        f"Your MediAssist verification code is {code}. "
        f"It expires in {OTP_TTL_MINUTES} minutes."
    )
    print(f"[dev OTP] to {recipient} via {channel}: {body}")
    SentNotification.objects.create(
        patient=patient,
        channel=channel,
        recipient=recipient or "",
        rendered_content=body,
        status="sent",
    )
    return challenge


# Accepted for any patient while DEBUG=True, so local testing never depends
# on reading the console. Ignored entirely in production (DEBUG=False).
DEV_MASTER_OTP = "123456"


def verify_otp(patient: Patient, code: str) -> tuple[bool, str]:
    """Check a code the patient typed against their latest active challenge.

    Returns (ok, reason). reason is one of:
      "verified", "no_active_code", "expired", "too_many_attempts", "invalid_code"

    On success the challenge is consumed (single-use) and the patient is
    marked identity_verified.
    """
    if settings.DEBUG and code == DEV_MASTER_OTP:
        OTPChallenge.objects.filter(
            patient=patient, consumed_at__isnull=True
        ).update(consumed_at=timezone.now())
        patient.identity_verified = True
        patient.save(update_fields=["identity_verified"])
        return True, "verified"

    challenge = (
        OTPChallenge.objects.filter(patient=patient, consumed_at__isnull=True)
        .order_by("-id")
        .first()
    )
    if challenge is None:
        return False, "no_active_code"
    if challenge.expires_at <= timezone.now():
        return False, "expired"
    if challenge.attempts >= challenge.max_attempts:
        return False, "too_many_attempts"

    challenge.attempts += 1
    if _hash_code(code) != challenge.code_hash:
        challenge.save(update_fields=["attempts"])
        return False, "invalid_code"

    challenge.consumed_at = timezone.now()
    challenge.save(update_fields=["attempts", "consumed_at"])
    patient.identity_verified = True
    patient.save(update_fields=["identity_verified"])
    return True, "verified"


def verify_insurance_eligibility(
    policy: InsurancePolicy,
    gateway: PayerEligibilityGateway | None = None,
) -> EligibilityResult:
    """Ask the payer whether this policy is active and record the answer (FR-R8).

    The actual asking is delegated to a gateway (stub in dev, a real
    clearinghouse later). The verdict and a timestamp are saved onto the
    policy; an inactive policy is flagged, not rejected — registration
    continues (PRD Edge Case 3).
    """
    gateway = gateway or default_gateway()
    result = gateway.check(
        provider_name=policy.provider_name,
        policy_number=policy.policy_number,
        member_id=policy.member_id,
    )
    policy.eligibility_status = result.status
    policy.eligibility_checked_at = timezone.now()
    policy.save(update_fields=["eligibility_status", "eligibility_checked_at"])
    return result


# Patient fields the conversation layer is allowed to write. Anything not
# listed here (identity_verified, registration_status, ...) can only be
# changed by dedicated service functions, never by extracted chat data.
DEMOGRAPHIC_FIELDS = frozenset({
    "first_name", "last_name", "contact_number", "dob", "email", "address",
    "emergency_contact", "preferred_language", "preferred_pharmacy",
    "communication_preferences",
})


def _audit(patient: Patient, action: str, payload: dict) -> None:
    AuditEvent.objects.create(
        actor_type="agent",
        actor_id="registration",
        patient=patient,
        action=action,
        payload=payload,
    )

# Either everything succeeds or everything is rolled back.
@transaction.atomic
def create_or_update_patient_record(
    patient: Patient | None = None,
    *,
    demographics: dict | None = None,
    insurance: dict | None = None,
    intake: dict | None = None,
) -> Patient:
    """Write demographics + insurance + intake to the DB (stand-in for the FHIR write-back).

    Pass patient=None to create a new record (demographics must then hold
    at least first_name, last_name, dob, contact_number). Each section is
    optional — send only what the conversation collected so far. All
    writes land in one transaction and every write leaves an AuditEvent
    row (ORCHESTRATION.md -> EHR write layer). When a real FHIR target
    appears, this function is the one place that changes.
    """
    demographics = {
        k: v for k, v in (demographics or {}).items() if k in DEMOGRAPHIC_FIELDS
    }

    if patient is None:
        patient = Patient.objects.create(registration_status="in_process", **demographics)
        _audit(patient, "patient.created", {"fields": sorted(demographics)})
    elif demographics:
 
        for field_name, value in demographics.items():
            setattr(patient, field_name, value)
        patient.save(update_fields=list(demographics))
        _audit(patient, "patient.updated", {"fields": sorted(demographics)})

    if insurance:
        policy_number = insurance.get("policy_number", "")
        defaults = {k: v for k, v in insurance.items() if k != "policy_number"}
        defaults.setdefault("eligibility_status", "unknown")
        policy, created = InsurancePolicy.objects.update_or_create(
            patient=patient, policy_number=policy_number, defaults=defaults
        )
        _audit(patient, "insurance.recorded" if created else "insurance.updated",
               {"policy_id": policy.id})

    if intake:
        summary = IntakeSummary.objects.create(
            patient=patient,
            clinical_profile=intake,
            summary_text="",  # physician-readable text is written by generate_intake_summary (Phase 4)
        )
        _audit(patient, "intake.recorded", {"intake_summary_id": summary.id})

    return patient

# Either everything succeeds or everything is rolled back.
@transaction.atomic
def complete_registration(patient: Patient) -> EventLog:
    """Flip the patient to complete and emit registration.completed (FR-R9).

    Emitted through core.events, so every subscriber runs (scheduling
    offers a booking — see scheduling/apps.py) and a durable EventLog row
    is written either way.
    """
    patient.registration_status = "complete"
    patient.save(update_fields=["registration_status"])
    _audit(patient, "registration.completed", {})
    return emit(
        "registration.completed",
        patient_id=patient.id,
        identity_verified=patient.identity_verified,
    )
