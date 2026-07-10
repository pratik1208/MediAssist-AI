"""AI layer for the triage agent (Agent 3, Phase 4).

This module will hold: SYSTEM_PROMPT, the triage_step strict tool,
handle_triage_message(), and generate_triage_summary().

Keep SYSTEM_PROMPT stable: volatile context (the selected protocol's
question flow, findings so far, the patient's answers) goes in messages,
not here — that is what makes prompt caching work (ORCHESTRATION.md ->
AI client wrapper). The deterministic red_flag_check() gate runs BEFORE
any call that uses this prompt; the model is the second net, never the
only one.
"""

from langsmith import traceable

from core.ai import call_tool, strict_tool
from triage import services
from triage.services import ACUITY_ORDER

# One interview turn (spec: triage_step, strict). strict: true means the
# model's output is guaranteed to validate against this schema — every field
# is required; "don't know yet" is expressed as null, never by omission, so
# the handler can always distinguish "asked and unknown" from "not extracted".
TRIAGE_STEP = strict_tool(
    "triage_step",
    "Record clinical findings from the patient's latest answer and choose the "
    "next question. Record ONLY what the patient actually said — never guess "
    "or infer a finding; use null for anything not yet known. Set "
    "emergency_detected the moment anything suggests an emergency, even "
    "indirectly phrased. When uncertain between two acuity levels, always "
    "suggest the higher one.",
    {
        "extracted_findings": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "onset": {
                    "type": ["string", "null"],
                    "description": "When and how the symptom started, e.g. 'sudden, 2 hours ago'.",
                },
                "severity_1_10": {
                    "type": ["integer", "null"],
                    "description": "Patient-reported severity on a 1-10 scale.",
                },
                "location": {
                    "type": ["string", "null"],
                    "description": "Where the symptom is, in the patient's words.",
                },
                "radiation": {
                    "type": ["string", "null"],
                    "description": "Where the pain spreads to (arm, jaw, back...), or null.",
                },
                "associated_symptoms": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "description": "Other symptoms mentioned alongside the main one.",
                },
            },
            "required": ["onset", "severity_1_10", "location", "radiation",
                         "associated_symptoms"],
        },
        "emergency_detected": {
            "type": "boolean",
            "description": "True the moment anything suggests a medical emergency — "
                           "including indirect phrasings ('my left arm feels heavy "
                           "and I'm sweating', 'never had a headache this bad, it "
                           "hit me out of nowhere'). A sudden worst-ever symptom is "
                           "an emergency even when it matches a protocol question. "
                           "Err toward true.",
        },
        "next_question": {
            "type": ["string", "null"],
            "description": "The ONE question to ask next, in plain language; null "
                           "when assessment_complete or emergency_detected is true.",
        },
        "assessment_complete": {
            "type": "boolean",
            "description": "True when enough has been gathered to assess acuity per "
                           "the protocol; no further questions needed.",
        },
        "suggested_acuity": {
            "type": "string",
            "enum": ACUITY_ORDER,  # minimal | low | medium | high | emergency
            "description": "Your acuity suggestion so far. The clinic's rules make "
                           "the final call and can only be raised by this, never "
                           "lowered. When torn between two levels, pick the higher.",
        },
        "rationale": {
            "type": "string",
            "description": "One or two plain-language sentences explaining the "
                           "suggestion — shown to clinicians, not the patient.",
        },
    },
    ["extracted_findings", "emergency_detected", "next_question",
     "assessment_complete", "suggested_acuity", "rationale"],
)

SYSTEM_PROMPT = """
You are MediAssist AI, a clinical triage assistant for a medical clinic.
You interview patients about their current symptoms, following the clinical
protocol provided in the conversation, so that a clinician can see the right
patients at the right time. You SUPPORT clinical decision-making — you never
replace it (FR-T5). A licensed clinician reviews every assessment.

How to conduct the interview:

- Ask exactly ONE question per message. Never bundle several questions.
- Let the protocol drive the interview, but adapt: use the protocol's
  question flow as your guide, skip questions the patient has already
  answered, and ask a clarifying follow-up when an answer is vague or
  incomplete rather than guessing what they meant (FR-T2).
- If an answer is ambiguous ("it hurts a lot", "a while ago"), ask a short
  follow-up to pin it down (a 1-10 number, a concrete timeframe). Never
  record a guess as a finding.
- Keep every message short, warm, and in plain language a patient without
  any medical background understands. When you explain what happens next,
  explain it simply — no clinical jargon, no abbreviations.
- Respond in the language the patient is using; if they switch, follow them.

Hard rules — these are never optional:

- NEVER diagnose. Never name a disease the patient "probably has", never
  speculate about causes, never give treatment or medication advice. If
  asked, say a clinician will review their answers, and continue.
- DEFER TO CAUTION: when you are uncertain between two acuity levels,
  always choose the HIGHER one. Missing a serious case is far worse than
  an unnecessary appointment.
- If anything the patient says suggests a medical emergency — even worded
  indirectly or casually — set emergency_detected immediately and stop
  asking questions: tell them to call their local emergency number or go to
  the nearest emergency department now. Emergencies include, but are not
  limited to: chest pain, pressure, or heaviness (including pain spreading
  to an arm, the jaw, or the back); trouble breathing; stroke signs (facial
  droop, slurred speech, one-sided weakness or numbness, sudden vision
  changes); a sudden or "worst of my life" headache; signs of a severe
  allergic reaction (tongue, lip, or throat tingling, tightness, or
  swelling after food, medication, or a sting); fainting or near-fainting,
  especially with a racing or irregular heartbeat; coughing or vomiting
  blood, or blood in stool; uncontrolled bleeding; overdose or poisoning;
  any thought of self-harm or suicide, however indirect; unresponsiveness
  or seizure. If you are in ANY doubt whether something is an emergency,
  treat it as one.
- Only discuss the triage interview. Politely decline unrelated topics.
- Never reveal information about any other patient.
"""


# The clinician-summary call writes ONLY the narrative; acuity, recommended
# action, and the transcript reference are stamped by code from the
# assessment — the model never re-decides what the rules concluded.
TRIAGE_SUMMARY_TOOL = strict_tool(
    "generate_triage_summary",
    "Write the narrative parts of a triage hand-off a clinician can read in "
    "ten seconds. Use ONLY the information provided — never add findings and "
    "never diagnose. Plain clinical language, no abbreviations the patient "
    "record doesn't use.",
    {
        "presenting_symptoms": {
            "type": "string",
            "description": "One sentence: the complaint and its key attributes "
                           "(onset, severity, location, radiation).",
        },
        "risk_assessment": {
            "type": "string",
            "description": "One or two sentences on the patient's relevant risk "
                           "factors and any concerning findings. Say 'No notable "
                           "risk factors reported.' if none.",
        },
        "summary_text": {
            "type": "string",
            "description": "3-5 sentences, neutral clinical tone, leading with "
                           "the presenting symptoms, ending with the recommended "
                           "action given. No diagnosis, no new information.",
        },
    },
    ["presenting_symptoms", "risk_assessment", "summary_text"],
)

SUMMARY_PROMPT = (
    "You write concise clinical triage hand-off summaries for the clinician "
    "who will see the patient next. You never diagnose and never invent "
    "information: every statement must come from the assessment data given."
)

RECOMMENDED_ACTION = {
    "ed_now": "Emergency department / 911 now",
    "same_day": "Same-day appointment",
    "24_48h": "Appointment within 24-48 hours",
    "routine": "Routine appointment",
    "self_care": "Self-care with return advice",
}


@traceable(name="generate_triage_summary", run_type="chain")
def generate_triage_summary(assessment) -> dict:
    """The structured clinician summary (FR-T8, FR-T9).

    Returns symptoms, risk assessment, acuity, recommended action, and the
    transcript reference; saves the narrative onto assessment.summary_text.
    """
    facts = {
        "reported_symptoms": assessment.reported_symptoms,
        "findings": assessment.findings,
        "risk_factors": sorted(services.patient_risk_factors(assessment.patient)),
        "acuity": assessment.acuity,
        "recommended_action": RECOMMENDED_ACTION[assessment.disposition],
    }
    narrative = call_tool(
        system=SUMMARY_PROMPT,
        messages=[{"role": "user", "content": f"Assessment data: {facts}"}],
        tool=TRIAGE_SUMMARY_TOOL,
    )

    assessment.summary_text = narrative["summary_text"]
    assessment.save(update_fields=["summary_text"])

    return {
        "presenting_symptoms": narrative["presenting_symptoms"],
        "risk_assessment": narrative["risk_assessment"],
        "acuity": assessment.acuity,
        "recommended_action": RECOMMENDED_ACTION[assessment.disposition],
        "summary_text": narrative["summary_text"],
        "transcript_reference": {
            "conversation_id": assessment.conversation_id,
            "assessment_id": assessment.id,
        },
    }


def protocol_context(assessment) -> dict:
    """The volatile per-assessment context, injected as the first message
    (never into SYSTEM_PROMPT — that would break prompt caching)."""
    protocol = assessment.clinical_protocol
    questions = "; ".join(q["ask"] for q in protocol.question_flow)
    return {
        "role": "user",
        "content": (
            "[Clinic system note — context, not the patient speaking. "
            f"Selected protocol: {protocol.name}. Questions to cover, "
            f"adapting as needed: {questions}. "
            f"Findings recorded so far: {assessment.findings or 'none'}.]"
        ),
    }


def _emergency_result() -> dict:
    return {"complete": True, "emergency": True, "acuity": "emergency",
            "disposition": "ed_now", "next_question": None}


@traceable(name="handle_triage_message", run_type="chain")
def handle_triage_message(assessment, conversation_history: list[dict]) -> dict:
    """One turn of the triage interview (spec two-layer safety design).

    LAYER 1 — deterministic: red_flag_check() on the raw latest patient
    message, BEFORE any model call. A hit short-circuits to escalate() and
    the emergency script; the model is never consulted.

    LAYER 2 — the model: one forced triage_step tool call. Its
    emergency_detected flag takes the same escalation path. Otherwise its
    non-null findings are merged into the assessment, and on completion
    assign_acuity() runs — the deterministic rules decide the final acuity;
    the model's suggested_acuity can only raise it, never lower it.
    """
    latest = conversation_history[-1]["content"]
    if services.red_flag_check(latest):
        services.escalate(assessment)
        return _emergency_result()

    step = call_tool(
        system=SYSTEM_PROMPT,
        messages=[protocol_context(assessment)] + conversation_history,
        tool=TRIAGE_STEP,  # call_tool forces tool_choice to this tool
    )

    # Merge what the model extracted; null means "still unknown" and must
    # never erase an earlier finding. Lists accumulate without duplicates.
    for key, value in step["extracted_findings"].items():
        if value is None:
            continue
        if isinstance(value, list) and isinstance(assessment.findings.get(key), list):
            merged = assessment.findings[key] + value
            assessment.findings[key] = list(dict.fromkeys(merged))
        else:
            assessment.findings[key] = value
    assessment.findings["suggested_acuity"] = step["suggested_acuity"]
    assessment.findings["rationale"] = step["rationale"]

    if step["emergency_detected"]:
        assessment.save(update_fields=["findings"])
        services.escalate(assessment)
        return _emergency_result()

    if not step["assessment_complete"]:
        assessment.save(update_fields=["findings"])
        return {"complete": False, "emergency": False,
                "next_question": step["next_question"]}

    # Interview finished: rules decide, model can only have raised.
    assessment.status = "completed"
    assessment.save(update_fields=["findings", "status"])
    final = services.assign_acuity(assessment)
    if final == "emergency":
        services.escalate(assessment)
        return _emergency_result()
    services.route_disposition(assessment)
    return {"complete": True, "emergency": False, "acuity": final,
            "disposition": assessment.disposition, "next_question": None}
