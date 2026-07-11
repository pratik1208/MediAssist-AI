"""Conversation orchestration for the registration agent (Phase 4).

Model-driven but state-gated (see SPEC_Agent_2): the model decides WHAT to
ask next (record_registration_data.next_question_topic); this code decides
which STAGE the registration is in — demographics collected? duplicate
resolved? OTP verified? insurance on file? — and persists every extracted
field through the Phase 2 services.
"""

from langsmith import traceable

from core.ai import call_tool
from core.models import Conversation
from registration import services
from registration.ai.prompts import REGISTRATION_SYSTEM_PROMPT
from registration.ai.tools import RECORD_REGISTRATION_DATA_TOOL
from registration.models import InsurancePolicy

# The minimum needed to run duplicate detection and create a record (FR-R3).
DEMOGRAPHIC_MINIMUM = ("first_name", "last_name", "dob", "contact_number")

DEMOGRAPHIC_FIELDS = (
    "first_name", "last_name", "dob", "contact_number", "email", "address",
    "emergency_contact", "preferred_language", "preferred_pharmacy",
)

INTAKE_LIST_FIELDS = (
    "symptoms", "medical_history", "medications", "allergies", "family_history",
)

INSURANCE_CHAT_FIELDS = {
    "insurance_provider": "provider_name",
    "insurance_policy_number": "policy_number",
    "insurance_member_id": "member_id",
}


@traceable(name="handle_registration_message", run_type="chain")
def handle_registration_message(conversation: Conversation, conversation_history: list[dict]) -> dict:
    """Run one turn of the registration conversation.

    Returns a dict the chat endpoint can act on:
      stage                — demographics | duplicate_hold | identity_verification
                             | insurance | intake | done
      next_question_topic  — the model's pick for what to ask about
      ui_hints             — e.g. ["otp_required"], [{"upload": "insurance_card"}]
      patient_id           — set once a patient record is linked
    """
    extracted = call_tool(
        system=REGISTRATION_SYSTEM_PROMPT,
        messages=conversation_history,
        tool=RECORD_REGISTRATION_DATA_TOOL,
    )

    ctx = conversation.agent_context
    patient = conversation.patient
    if patient is not None:
        # The OTP/insurance endpoints update the patient between turns;
        # re-read so the state gate below sees the current flags.
        patient.refresh_from_db()
    ui_hints: list = []

    # -- 1. persist demographics ------------------------------------------
    demographics = {f: extracted[f] for f in DEMOGRAPHIC_FIELDS if extracted.get(f)}
    if patient is not None:
        if demographics:
            services.create_or_update_patient_record(patient, demographics=demographics)
    else:
        # No patient yet: accumulate across turns until we can run the
        # duplicate check, and never auto-create on a possible duplicate.
        pending = {**ctx.get("pending_demographics", {}), **demographics}
        ctx["pending_demographics"] = pending
        if all(pending.get(f) for f in DEMOGRAPHIC_MINIMUM):
            full_name = f"{pending['first_name']} {pending['last_name']}"
            match, candidates = services.find_matching_patients(
                full_name, pending["dob"], pending["contact_number"]
            )
            if match == "possible_duplicate":
                ctx["duplicate_candidate_ids"] = [p.id for p in candidates]
            else:
                existing = candidates[0] if match == "existing" else None
                patient = services.create_or_update_patient_record(
                    existing, demographics=pending
                )
                conversation.patient = patient
                ctx.pop("pending_demographics", None)

    # -- 2. accumulate intake answers (written to the DB at completion) ----
    intake = ctx.get("intake", {})
    for field in INTAKE_LIST_FIELDS:
        if extracted.get(field):
            merged = intake.get(field, []) + extracted[field]
            intake[field] = list(dict.fromkeys(merged))  # dedupe, keep order
    if extracted.get("lifestyle"):
        intake["lifestyle"] = {**intake.get("lifestyle", {}), **extracted["lifestyle"]}
    if intake:
        ctx["intake"] = intake

    # -- 3. insurance dictated in chat (a card upload is the main path;
    #       the policy row itself is written by the insurance endpoint or
    #       document extraction, which have the coverage dates) ------------
    chat_insurance = {
        model_field: extracted[tool_field]
        for tool_field, model_field in INSURANCE_CHAT_FIELDS.items()
        if extracted.get(tool_field)
    }
    if chat_insurance:
        ctx["pending_insurance"] = {**ctx.get("pending_insurance", {}), **chat_insurance}

    # Once provider + policy number are both in, write the policy row —
    # otherwise the state gate below would keep the patient on the insurance
    # stage forever (the card-upload path writes its row in the documents
    # endpoint; this is the dictated-in-chat path).
    pending_insurance = ctx.get("pending_insurance", {})
    if (
        patient is not None
        and pending_insurance.get("provider_name")
        and pending_insurance.get("policy_number")
        and not InsurancePolicy.objects.filter(patient=patient).exists()
    ):
        services.create_or_update_patient_record(
            patient, insurance={"coverage_details": "", **pending_insurance}
        )
        policy = InsurancePolicy.objects.get(
            patient=patient, policy_number=pending_insurance["policy_number"]
        )
        services.verify_insurance_eligibility(policy)
        ctx.pop("pending_insurance", None)

    # -- 4. the state gate: code, not the model, decides the stage ---------
    if patient is None:
        stage = "duplicate_hold" if ctx.get("duplicate_candidate_ids") else "demographics"
    elif not patient.identity_verified:
        stage = "identity_verification"
        ui_hints.append("otp_required")
    elif not InsurancePolicy.objects.filter(patient=patient).exists():
        stage = "insurance"
        ui_hints.append({"upload": "insurance_card"})
    elif not extracted.get("registration_complete"):
        stage = "intake"
    else:
        if ctx.get("intake"):
            services.create_or_update_patient_record(patient, intake=ctx["intake"])
        services.complete_registration(patient)
        # Hand the conversation to scheduling without re-asking identity
        # (PRD User Journey steps 4-5).
        ctx["active_agent"] = "scheduling"
        ctx["handoff"] = {
            "from": "registration",
            "symptoms": ctx.get("intake", {}).get("symptoms", []),
        }
        stage = "done"

    ctx["registration_stage"] = stage
    conversation.agent_context = ctx
    conversation.save(update_fields=["patient", "agent_context"])

    return {
        "stage": stage,
        "next_question_topic": extracted.get("next_question_topic"),
        "registration_complete": stage == "done",
        "ui_hints": ui_hints,
        "patient_id": patient.id if patient else None,
        "extracted": extracted,
    }
