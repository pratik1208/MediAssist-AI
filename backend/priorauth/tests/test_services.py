"""Phase 2 exit tests: the detection matrix (auth vs no-auth rules),
evidence-gathering completeness, info-request auto-response vs
staff-staging, and both decision paths."""

import datetime

import pytest
from django.utils import timezone

from core.models import AuditEvent, Doctor, EventLog, Patient, SentNotification
from priorauth import services
from priorauth.gateway import SimulatedPayerGateway
from priorauth.models import AuthorizationRequest, PayerMessage, PayerRule, TreatmentOrder
from referrals.models import ConsultationReport, Referral
from refills.models import Prescription
from registration.models import InsurancePolicy, IntakeSummary
from triage.models import EscalationAlert

TODAY = datetime.date.today()


@pytest.fixture
def patient(db):
    return Patient.objects.create(
        first_name="Rahul", last_name="Sharma", contact_number="9876543210",
        dob=datetime.date(1990, 5, 17),
    )


@pytest.fixture
def doctor(db):
    return Doctor.objects.create(name="Dr. Asha Mehta", specialty="General Medicine")


@pytest.fixture
def policy(db, patient):
    return InsurancePolicy.objects.create(
        patient=patient, policy_number="BS-1", provider_name="BlueShield",
        plan="Premium PPO", coverage_details="",
    )


def make_rule(**overrides):
    defaults = dict(payer_name="BlueShield", requires_auth=True, submission_channel="epa",
                    required_documentation=["diagnosis"])
    defaults.update(overrides)
    return PayerRule.objects.create(**defaults)


def make_order(patient, doctor, **overrides):
    defaults = dict(patient=patient, ordering_doctor=doctor, order_type="imaging",
                    cpt_code="70551")
    defaults.update(overrides)
    return TreatmentOrder.objects.create(**defaults)


class TestDetectAuthorizationRequirement:
    def test_matching_rule_requires_auth(self, patient, doctor, policy):
        make_rule(cpt_pattern="7055[1-3]", required_documentation=["diagnosis", "imaging_reports"])
        order = make_order(patient, doctor, cpt_code="70551")
        result = services.detect_authorization_requirement(order)
        assert result.requires_auth is True
        assert result.required_documentation == ["diagnosis", "imaging_reports"]

    def test_matching_rule_says_no_auth_required(self, patient, doctor, policy):
        make_rule(requires_auth=False, medication_pattern="atorvastatin", cpt_pattern=None)
        order = make_order(patient, doctor, order_type="medication", cpt_code=None,
                           medication="atorvastatin 20mg")
        result = services.detect_authorization_requirement(order)
        assert result.requires_auth is False

    def test_no_matching_rule_is_not_required(self, patient, doctor, policy):
        make_rule(cpt_pattern="99999")  # doesn't match
        order = make_order(patient, doctor, cpt_code="70551")
        result = services.detect_authorization_requirement(order)
        assert result.requires_auth is False
        assert result.rule is None

    def test_no_policy_on_file_is_not_required(self, patient, doctor):
        make_rule(cpt_pattern="7055[1-3]")
        order = make_order(patient, doctor)
        result = services.detect_authorization_requirement(order)
        assert result.requires_auth is False

    def test_wrong_plan_excludes_a_plan_specific_rule(self, patient, doctor, policy):
        # policy.plan == "Premium PPO"; rule targets a different plan.
        make_rule(plan="Basic HMO", cpt_pattern="7055[1-3]")
        order = make_order(patient, doctor, cpt_code="70551")
        result = services.detect_authorization_requirement(order)
        assert result.requires_auth is False

    def test_missing_patient_plan_excludes_a_plan_specific_rule(self, patient, doctor):
        InsurancePolicy.objects.create(patient=patient, policy_number="BS-2",
                                       provider_name="BlueShield", coverage_details="")  # no plan
        make_rule(plan="Premium PPO", cpt_pattern="7055[1-3]")
        order = make_order(patient, doctor, cpt_code="70551")
        result = services.detect_authorization_requirement(order)
        assert result.requires_auth is False

    def test_plan_specific_rule_wins_over_payer_wide_rule(self, patient, doctor, policy):
        make_rule(plan=None, cpt_pattern="7055[1-3]", requires_auth=False,
                  required_documentation=[])
        specific = make_rule(plan="Premium PPO", cpt_pattern="7055[1-3]", requires_auth=True,
                             required_documentation=["diagnosis"])
        order = make_order(patient, doctor, cpt_code="70551")
        result = services.detect_authorization_requirement(order)
        assert result.rule.id == specific.id
        assert result.requires_auth is True


class TestInitiateAuthorization:
    def test_requires_auth_creates_request_and_gathers_evidence(self, patient, doctor, policy):
        make_rule(cpt_pattern="7055[1-3]", required_documentation=["diagnosis"])
        order = make_order(patient, doctor, cpt_code="70551")
        auth_request = services.initiate_authorization(order)
        assert auth_request is not None
        assert auth_request.status == "ready_for_review"  # gather_evidence auto-advances
        assert auth_request.policy_id == policy.id
        assert AuditEvent.objects.filter(action="priorauth.detected").exists()

    def test_not_required_creates_nothing(self, patient, doctor, policy):
        make_rule(cpt_pattern="99999")
        order = make_order(patient, doctor, cpt_code="70551")
        assert services.initiate_authorization(order) is None
        assert not AuthorizationRequest.objects.filter(order=order).exists()


class TestGatherEvidence:
    def _rich_patient_record(self, patient, doctor):
        IntakeSummary.objects.create(
            patient=patient,
            clinical_profile={"medical_history": ["Osteoarthritis, right knee"],
                              "allergies": ["penicillin"]},
            summary_text="Chronic right knee pain, failed conservative therapy.",
        )
        Prescription.objects.create(
            patient=patient, prescriber=doctor, medication_name="Naproxen", dose="500mg",
            quantity="30 tablets", refills_allowed=2, refills_used=0,
            prescribed_date=TODAY, expiry_date=TODAY + datetime.timedelta(days=300),
            status="active",
        )
        referring_doctor = Doctor.objects.create(name="Dr. Referring", specialty="Orthopedics")
        referral = Referral.objects.create(
            patient=patient, referring_doctor=referring_doctor, specialty_needed="Orthopedics",
            reason="knee pain", urgency="routine", status="closed",
        )
        ConsultationReport.objects.create(
            referral=referral, diagnosis="Severe osteoarthritis",
            treatment_plan="Recommend total knee arthroplasty",
        )

    def test_collects_every_requested_category(self, patient, doctor, policy):
        self._rich_patient_record(patient, doctor)
        rule = make_rule(
            cpt_pattern="27447",
            required_documentation=["diagnosis", "physician_notes", "medication_history",
                                    "prior_treatments", "allergies", "labs", "imaging_reports"],
        )
        order = make_order(patient, doctor, order_type="procedure", cpt_code="27447")
        auth_request = AuthorizationRequest.objects.create(
            order=order, policy=policy, matched_rule=rule, status="detected",
            status_history=[{"status": "detected", "at": "x"}],
        )

        package = services.gather_evidence(auth_request)

        assert "Osteoarthritis, right knee" in package.evidence["diagnosis"]
        assert any("Chronic right knee pain" in n for n in package.evidence["physician_notes"])
        assert any("Naproxen" in m for m in package.evidence["medication_history"])
        assert any("arthroplasty" in t for t in package.evidence["prior_treatments"])
        assert "penicillin" in package.evidence["allergies"]
        assert package.evidence["labs"] == []  # none on file — empty, not missing/crashed
        assert package.evidence["imaging_reports"] == []
        assert package.codes == {"cpt_code": "27447", "icd10_code": None, "medication": None}
        assert package.demographics_snapshot["first_name"] == "Rahul"

    def test_unmapped_category_is_an_empty_list_not_a_crash(self, patient, doctor, policy):
        rule = make_rule(cpt_pattern="70551", required_documentation=["some_future_category"])
        order = make_order(patient, doctor, cpt_code="70551")
        auth_request = AuthorizationRequest.objects.create(
            order=order, policy=policy, matched_rule=rule, status="detected",
            status_history=[{"status": "detected", "at": "x"}],
        )
        package = services.gather_evidence(auth_request)
        assert package.evidence["some_future_category"] == []

    def test_advances_status_to_ready_for_review(self, patient, doctor, policy):
        rule = make_rule(cpt_pattern="70551", required_documentation=["diagnosis"])
        order = make_order(patient, doctor, cpt_code="70551")
        auth_request = AuthorizationRequest.objects.create(
            order=order, policy=policy, matched_rule=rule, status="detected",
            status_history=[{"status": "detected", "at": "x"}],
        )
        services.gather_evidence(auth_request)
        auth_request.refresh_from_db()
        assert auth_request.status == "ready_for_review"
        statuses = [e["status"] for e in auth_request.status_history]
        assert statuses == ["detected", "gathering_evidence", "ready_for_review"]


def make_ready_request(patient, doctor, policy, **rule_overrides):
    rule = make_rule(cpt_pattern="70551", required_documentation=["diagnosis"], **rule_overrides)
    order = make_order(patient, doctor, cpt_code="70551")
    auth_request = AuthorizationRequest.objects.create(
        order=order, policy=policy, matched_rule=rule, status="detected",
        status_history=[{"status": "detected", "at": "x"}],
    )
    services.gather_evidence(auth_request)
    auth_request.refresh_from_db()
    return auth_request


class TestSubmit:
    def test_submit_records_outbound_message_and_advances(self, patient, doctor, policy):
        auth_request = make_ready_request(patient, doctor, policy, submission_channel="epa")
        services.submit(auth_request)
        auth_request.refresh_from_db()
        assert auth_request.status == "submitted"
        assert auth_request.external_reference
        message = PayerMessage.objects.get(request=auth_request)
        assert message.direction == "outbound"
        assert "epa" in message.content


class TestPollStatus:
    def test_approved_response_triggers_on_decision(self, patient, doctor, policy):
        auth_request = make_ready_request(patient, doctor, policy)
        services.submit(auth_request)
        SimulatedPayerGateway.force_response(auth_request.id, "approved")

        services.poll_status(auth_request)

        auth_request.refresh_from_db()
        assert auth_request.status == "approved"
        assert EventLog.objects.filter(name="priorauth.approved").exists()
        assert SentNotification.objects.filter(patient=patient).exists()
        SimulatedPayerGateway.clear_forced()

    def test_denied_response_sets_reason_and_appeal_flag(self, patient, doctor, policy):
        auth_request = make_ready_request(patient, doctor, policy)
        services.submit(auth_request)
        SimulatedPayerGateway.force_response(
            auth_request.id, "denied", denial_reason="not medically necessary",
            appeal_suggested=True,
        )

        services.poll_status(auth_request)

        auth_request.refresh_from_db()
        assert auth_request.status == "denied"
        assert auth_request.denial_reason == "not medically necessary"
        assert auth_request.appeal_suggested is True
        assert EventLog.objects.filter(name="priorauth.denied").exists()
        SimulatedPayerGateway.clear_forced()

    def test_info_requested_triggers_handle_info_request(self, patient, doctor, policy):
        auth_request = make_ready_request(patient, doctor, policy)
        services.submit(auth_request)
        SimulatedPayerGateway.force_response(
            auth_request.id, "info_requested", requested_items=["diagnosis"],
        )
        # diagnosis IS collectible (order.cpt_code set, but no icd10/history —
        # collector returns [] here) -> should stage for staff since nothing found
        services.poll_status(auth_request)
        auth_request.refresh_from_db()
        assert auth_request.status == "info_requested"
        assert EscalationAlert.objects.filter(patient=patient, source_agent="priorauth").exists()
        SimulatedPayerGateway.clear_forced()

    def test_already_decided_request_is_left_alone(self, patient, doctor, policy):
        auth_request = make_ready_request(patient, doctor, policy)
        services.submit(auth_request)
        SimulatedPayerGateway.force_response(auth_request.id, "approved")
        services.poll_status(auth_request)
        auth_request.refresh_from_db()
        count_before = PayerMessage.objects.filter(request=auth_request).count()

        services.poll_status(auth_request)  # already approved -> no-op

        assert PayerMessage.objects.filter(request=auth_request).count() == count_before
        SimulatedPayerGateway.clear_forced()


class TestHandleInfoRequest:
    def test_auto_resubmits_when_everything_is_found(self, patient, doctor, policy):
        IntakeSummary.objects.create(
            patient=patient, clinical_profile={"allergies": ["latex"]}, summary_text="",
        )
        auth_request = make_ready_request(patient, doctor, policy)
        services.submit(auth_request)

        result = services.handle_info_request(auth_request, ["allergies"])

        assert result["action"] == "auto_resubmitted"
        auth_request.refresh_from_db()
        assert auth_request.status == "under_review"
        assert "latex" in auth_request.package.evidence["allergies"]
        assert not EscalationAlert.objects.filter(patient=patient).exists()

    def test_stages_for_staff_when_something_is_missing(self, patient, doctor, policy):
        auth_request = make_ready_request(patient, doctor, policy)
        services.submit(auth_request)

        result = services.handle_info_request(auth_request, ["imaging_reports"])

        assert result["action"] == "staged_for_staff"
        assert result["missing"] == ["imaging_reports"]
        auth_request.refresh_from_db()
        assert auth_request.status == "submitted"  # unchanged — not resubmitted
        alert = EscalationAlert.objects.get(patient=patient, source_agent="priorauth")
        assert "imaging_reports" in alert.summary


class TestOnDecision:
    def test_approved_notifies_patient_and_emits(self, patient, doctor, policy):
        auth_request = make_ready_request(patient, doctor, policy)
        auth_request.status = "approved"
        auth_request.save(update_fields=["status"])
        services.on_decision(auth_request)
        note = SentNotification.objects.filter(patient=patient).latest("id")
        assert "approved" in note.rendered_content
        assert EventLog.objects.filter(name="priorauth.approved",
                                       payload__request_id=auth_request.id).exists()

    def test_denied_notifies_with_reason(self, patient, doctor, policy):
        auth_request = make_ready_request(patient, doctor, policy)
        auth_request.status = "denied"
        auth_request.denial_reason = "step therapy required first"
        auth_request.appeal_suggested = True
        auth_request.save(update_fields=["status", "denial_reason", "appeal_suggested"])
        services.on_decision(auth_request)
        note = SentNotification.objects.filter(patient=patient).latest("id")
        assert "step therapy required first" in note.rendered_content
        event = EventLog.objects.filter(name="priorauth.denied",
                                       payload__request_id=auth_request.id).latest("id")
        assert event.payload["appeal_suggested"] is True


class TestAdvanceStatus:
    @pytest.mark.parametrize("start, target", [
        ("detected", "gathering_evidence"),
        ("gathering_evidence", "ready_for_review"),
        ("ready_for_review", "submitted"),
        ("submitted", "under_review"),
        ("submitted", "approved"),   # instant decision, no explicit review stage
        ("submitted", "denied"),
        ("submitted", "info_requested"),
        ("under_review", "approved"),
        ("under_review", "denied"),
        ("info_requested", "under_review"),
        ("info_requested", "approved"),
    ])
    def test_legal_transitions(self, patient, doctor, policy, start, target):
        auth_request = make_ready_request(patient, doctor, policy)
        auth_request.status = start
        auth_request.status_history = [{"status": start, "at": "x"}]
        auth_request.save(update_fields=["status", "status_history"])
        services.advance_status(auth_request, target)
        auth_request.refresh_from_db()
        assert auth_request.status == target

    @pytest.mark.parametrize("start, target", [
        ("detected", "approved"),        # skipping steps
        ("approved", "denied"),          # terminal
        ("denied", "approved"),          # terminal
        ("ready_for_review", "detected"),  # backward
    ])
    def test_illegal_transitions(self, patient, doctor, policy, start, target):
        auth_request = make_ready_request(patient, doctor, policy)
        auth_request.status = start
        auth_request.status_history = [{"status": start, "at": "x"}]
        auth_request.save(update_fields=["status", "status_history"])
        with pytest.raises(services.IllegalStatusTransition):
            services.advance_status(auth_request, target)
