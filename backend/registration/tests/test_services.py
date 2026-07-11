import datetime
import re
from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone

from core.models import AuditEvent, EventLog, Patient, SentNotification
from registration.eligibility import EligibilityResult, PayerEligibilityGateway
from registration.models import InsurancePolicy, IntakeSummary
from registration.services import (
    complete_registration,
    create_or_update_patient_record,
    create_otp,
    find_matching_patients,
    normalize_phone,
    verify_insurance_eligibility,
    verify_otp,
)

DOB = datetime.date(1990, 5, 17)  # matches the shared `rahul` fixture in conftest.py
OTHER_DOB = datetime.date(1985, 1, 2)


class TestNormalizePhone:
    @pytest.mark.parametrize(
        "raw",
        ["+91 98765-43210", "098765 43210", "9876543210", "(987) 654-3210"],
    )
    def test_formats_reduce_to_same_10_digits(self, raw):
        assert normalize_phone(raw) == "9876543210"

    def test_empty_input_is_empty(self):
        assert normalize_phone("") == ""
        assert normalize_phone(None) == ""


class TestFindMatchingPatients:
    def test_same_phone_and_dob_is_existing(self, rahul):
        # Different formatting of the same number must still match.
        status, matches = find_matching_patients("Rahul Sharma", DOB, "9876543210")
        assert status == "existing"
        assert matches == [rahul]

    def test_existing_wins_even_if_name_differs(self, rahul):
        # Phone + dob identify the person; a changed/misspelled name doesn't matter.
        status, matches = find_matching_patients("R. Kumar", DOB, "+919876543210")
        assert status == "existing"
        assert matches == [rahul]

    def test_same_dob_similar_name_different_phone_is_possible_duplicate(self, rahul):
        # Typo in the last name ("Sharme") with a new phone -> flag, never auto-create.
        status, matches = find_matching_patients("Rahul Sharme", DOB, "9000000000")
        assert status == "possible_duplicate"
        assert matches == [rahul]

    def test_same_dob_unrelated_name_and_phone_is_new(self, rahul):
        status, matches = find_matching_patients("Priya Patel", DOB, "9000000000")
        assert status == "new"
        assert matches == []

    def test_same_phone_but_different_dob_is_new(self, rahul):
        # dob is the anchor: a shared/family phone alone is not a match.
        status, matches = find_matching_patients("Rahul Sharma", OTHER_DOB, "9876543210")
        assert status == "new"
        assert matches == []

    def test_empty_database_is_new(self, db):
        status, matches = find_matching_patients("Rahul Sharma", DOB, "9876543210")
        assert status == "new"
        assert matches == []


def sent_code(patient):
    """Read the plaintext code back out of the dev 'send' log."""
    body = SentNotification.objects.filter(patient=patient).latest("id").rendered_content
    return re.search(r"\b(\d{6})\b", body).group(1)


class TestOtp:
    def test_create_otp_logs_a_notification_with_a_6_digit_code(self, rahul):
        challenge = create_otp(rahul, "SMS")
        code = sent_code(rahul)
        assert len(code) == 6
        # Only the hash is stored, never the code itself.
        assert code not in challenge.code_hash
        assert challenge.expires_at > timezone.now()

    def test_correct_code_verifies_and_marks_patient(self, rahul):
        create_otp(rahul, "SMS")
        ok, reason = verify_otp(rahul, sent_code(rahul))
        assert (ok, reason) == (True, "verified")
        rahul.refresh_from_db()
        assert rahul.identity_verified is True

    def test_code_is_single_use(self, rahul):
        create_otp(rahul, "SMS")
        code = sent_code(rahul)
        verify_otp(rahul, code)
        ok, reason = verify_otp(rahul, code)
        assert (ok, reason) == (False, "no_active_code")

    def test_wrong_code_fails(self, rahul):
        create_otp(rahul, "SMS")
        ok, reason = verify_otp(rahul, "000000" if sent_code(rahul) != "000000" else "111111")
        assert (ok, reason) == (False, "invalid_code")

    def test_expired_code_fails(self, rahul):
        challenge = create_otp(rahul, "SMS")
        challenge.expires_at = timezone.now() - timedelta(seconds=1)
        challenge.save(update_fields=["expires_at"])
        ok, reason = verify_otp(rahul, sent_code(rahul))
        assert (ok, reason) == (False, "expired")

    def test_sixth_attempt_is_blocked_even_with_the_right_code(self, rahul):
        create_otp(rahul, "SMS")
        code = sent_code(rahul)
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(5):
            verify_otp(rahul, wrong)
        ok, reason = verify_otp(rahul, code)
        assert (ok, reason) == (False, "too_many_attempts")

    def test_new_code_cancels_the_old_one(self, rahul):
        create_otp(rahul, "SMS")
        old_code = sent_code(rahul)
        create_otp(rahul, "SMS")
        ok, reason = verify_otp(rahul, old_code)
        assert ok is False

    @override_settings(DEBUG=True)
    def test_dev_master_code_verifies_in_debug_mode(self, rahul):
        # No challenge needed at all — 123456 is a dev-only shortcut.
        ok, reason = verify_otp(rahul, "123456")
        assert (ok, reason) == (True, "verified")
        rahul.refresh_from_db()
        assert rahul.identity_verified is True

    def test_dev_master_code_is_rejected_when_debug_is_off(self, rahul):
        # Tests run with DEBUG=False, i.e. production behaviour.
        ok, reason = verify_otp(rahul, "123456")
        assert (ok, reason) == (False, "no_active_code")

    def test_no_challenge_at_all(self, rahul):
        ok, reason = verify_otp(rahul, "123456")
        assert (ok, reason) == (False, "no_active_code")


def make_policy(patient, policy_number):
    return InsurancePolicy.objects.create(
        patient=patient,
        policy_number=policy_number,
        provider_name="BlueShield",
        coverage_details="basic plan",
        coverage_start=datetime.date(2026, 1, 1),
        coverage_end=datetime.date(2026, 12, 31),
        eligibility_status="unknown",
    )


class TestVerifyInsuranceEligibility:
    def test_active_policy_is_marked_eligible(self, rahul):
        policy = make_policy(rahul, "BS-448291")
        result = verify_insurance_eligibility(policy)
        assert result.status == "eligible"
        policy.refresh_from_db()
        assert policy.eligibility_status == "eligible"
        assert policy.eligibility_checked_at is not None

    def test_inactive_policy_is_flagged_not_deleted(self, rahul):
        policy = make_policy(rahul, "INACTIVE-001")
        result = verify_insurance_eligibility(policy)
        assert result.status == "ineligible"
        policy.refresh_from_db()
        assert policy.eligibility_status == "ineligible"
        # Flagged, but the policy row still exists — registration continues.
        assert InsurancePolicy.objects.filter(pk=policy.pk).exists()

    def test_missing_policy_number_is_unknown(self, rahul):
        policy = make_policy(rahul, "")
        assert verify_insurance_eligibility(policy).status == "unknown"

    def test_a_custom_gateway_can_be_injected(self, rahul):
        # Proves the Phase 7 swap-in: services code runs unchanged against
        # any gateway that implements the interface.
        class AlwaysDown(PayerEligibilityGateway):
            def check(self, *, provider_name, policy_number, member_id=None):
                return EligibilityResult("unknown", reason="payer API timeout")

        policy = make_policy(rahul, "BS-448291")
        result = verify_insurance_eligibility(policy, gateway=AlwaysDown())
        assert result.status == "unknown"
        assert result.reason == "payer API timeout"


class TestCreateOrUpdatePatientRecord:
    def test_creates_a_new_patient_from_demographics(self, db):
        patient = create_or_update_patient_record(demographics={
            "first_name": "Priya",
            "last_name": "Patel",
            "dob": DOB,
            "contact_number": "9000000000",
        })
        assert patient.pk is not None
        assert patient.registration_status == "in_process"
        assert AuditEvent.objects.filter(patient=patient, action="patient.created").exists()

    def test_updates_an_existing_patient_without_creating_a_row(self, rahul):
        create_or_update_patient_record(rahul, demographics={"email": "rahul@example.com"})
        rahul.refresh_from_db()
        assert rahul.email == "rahul@example.com"
        assert Patient.objects.count() == 1
        assert AuditEvent.objects.filter(patient=rahul, action="patient.updated").exists()

    def test_protected_fields_cannot_be_written_through_demographics(self, rahul):
        # Chat-extracted data must never flip verification/status flags.
        create_or_update_patient_record(rahul, demographics={
            "email": "rahul@example.com",
            "identity_verified": True,
            "registration_status": "complete",
        })
        rahul.refresh_from_db()
        assert rahul.identity_verified is False
        # email (allowed) was still applied
        assert rahul.email == "rahul@example.com"

    def test_insurance_is_written_once_then_updated(self, rahul):
        create_or_update_patient_record(rahul, insurance={
            "policy_number": "BS-448291",
            "provider_name": "BlueShield",
            "coverage_details": "basic",
            "coverage_start": datetime.date(2026, 1, 1),
            "coverage_end": datetime.date(2026, 12, 31),
        })
        # Same policy number again -> update, not a second row.
        create_or_update_patient_record(rahul, insurance={
            "policy_number": "BS-448291",
            "provider_name": "BlueShield Gold",
            "coverage_details": "upgraded",
            "coverage_start": datetime.date(2026, 1, 1),
            "coverage_end": datetime.date(2026, 12, 31),
        })
        policies = InsurancePolicy.objects.filter(patient=rahul)
        assert policies.count() == 1
        assert policies.get().provider_name == "BlueShield Gold"

    def test_intake_is_stored_as_clinical_profile(self, rahul):
        intake = {"symptoms": ["headache"], "allergies": ["penicillin"]}
        create_or_update_patient_record(rahul, intake=intake)
        summary = IntakeSummary.objects.get(patient=rahul)
        assert summary.clinical_profile == intake

    def test_all_sections_in_one_call(self, db):
        patient = create_or_update_patient_record(
            demographics={"first_name": "Asha", "last_name": "Rao",
                          "dob": DOB, "contact_number": "9111111111"},
            insurance={"policy_number": "P-1", "provider_name": "Star",
                       "coverage_details": "", "coverage_start": datetime.date(2026, 1, 1),
                       "coverage_end": datetime.date(2026, 12, 31)},
            intake={"symptoms": ["cough"]},
        )
        assert InsurancePolicy.objects.filter(patient=patient).exists()
        assert IntakeSummary.objects.filter(patient=patient).exists()


class TestCompleteRegistration:
    def test_flips_status_and_emits_event(self, rahul):
        event = complete_registration(rahul)
        rahul.refresh_from_db()
        assert rahul.registration_status == "complete"
        assert event.name == "registration.completed"
        assert event.payload["patient_id"] == rahul.id
        assert EventLog.objects.filter(name="registration.completed").count() == 1

    def test_event_payload_carries_verification_state(self, rahul):
        rahul.identity_verified = True
        rahul.save(update_fields=["identity_verified"])
        event = complete_registration(rahul)
        assert event.payload["identity_verified"] is True
