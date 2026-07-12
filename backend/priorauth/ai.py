"""AI layer for the prior authorization agent (Agent 6, Phase 4).

Three forced tool calls, same "the model states, the code decides" split as
every other agent's AI layer:

  write_reviewer_summary — turns gathered evidence into a payer-reviewer-
  facing medical necessity summary (FR-P3). Grounded only in the evidence
  actually gathered; guideline_citations may name well-known clinical
  practice guidelines in general terms (ordinary domain knowledge), but the
  clinical facts about THIS patient must come only from the evidence given.

  interpret_payer_message — a raw, unstructured payer response (simulated
  fax/portal text) -> the structured {decision, info_requested, deadline}
  services.poll_status() needs. Real payer channels don't hand back neat
  JSON; this is the parsing step that makes them look like they did.

  suggest_appeal — on denial, a recommendation + draft argument for the
  physician. Suggest only: automated appeal SUBMISSION is a documented PRD
  future enhancement, never built here — a human always reviews and sends
  any appeal themselves.
"""

import json

from langsmith import traceable

from core.ai import call_tool, strict_tool

# -- FR-P3: the payer-reviewer-facing summary --------------------------------

WRITE_REVIEWER_SUMMARY = strict_tool(
    "write_reviewer_summary",
    "Turn gathered clinical evidence into a structured medical-necessity "
    "summary a payer reviewer can read in under a minute. clinical_justification "
    "and relevant_history_points must be grounded ONLY in the evidence "
    "provided — never invent a finding about this patient that isn't there. "
    "guideline_citations may name well-established clinical practice "
    "guidelines relevant to this case in general terms (e.g. 'ACR "
    "Appropriateness Criteria for low back pain imaging') — that is ordinary "
    "clinical domain knowledge, not a patient-specific fact, so it doesn't "
    "need to come from the evidence itself. You never recommend approving "
    "or denying — that's the payer's decision.",
    {
        "clinical_justification": {
            "type": "string",
            "description": "2-4 sentences: why this treatment is medically necessary, "
                           "citing only the evidence given.",
        },
        "relevant_history_points": {
            "type": "array", "items": {"type": "string"},
            "description": "The specific evidence items that matter most, in the "
                           "reviewer's own scanning order.",
        },
        "guideline_citations": {
            "type": "array", "items": {"type": "string"},
            "description": "Relevant clinical practice guidelines, named in general "
                           "terms; empty list if none apply.",
        },
    },
    ["clinical_justification", "relevant_history_points", "guideline_citations"],
)

REVIEWER_SUMMARY_PROMPT = (
    "You write medical-necessity summaries for payer reviewers deciding on "
    "prior authorization requests. You use ONLY the codes and evidence "
    "given for this specific patient — you never add clinical claims about "
    "them beyond what's provided, and you never recommend a decision."
)


@traceable(name="write_reviewer_summary", run_type="chain")
def write_reviewer_summary(package) -> dict:
    """One forced tool call: the package's codes/evidence -> a structured
    medical-necessity summary."""
    context = {
        "codes": package.codes, "evidence": package.evidence,
        "demographics": package.demographics_snapshot,
    }
    return call_tool(
        system=REVIEWER_SUMMARY_PROMPT,
        messages=[{"role": "user", "content": json.dumps(context)}],
        tool=WRITE_REVIEWER_SUMMARY,
    )


# -- FR-P5/P6: interpreting a raw payer response ------------------------------

INTERPRET_PAYER_MESSAGE = strict_tool(
    "interpret_payer_message",
    "Read a payer's response message (fax text, portal copy, email) and "
    "extract its decision, any additional items it's asking for, and any "
    "response deadline. Transcribe only what the message actually says — "
    "never guess a decision the message doesn't clearly state.",
    {
        "decision": {
            "type": ["string", "null"],
            "description": "One of 'approved', 'denied', 'info_requested', "
                           "'under_review', or null if the message doesn't "
                           "clearly state one — never guess.",
        },
        "info_requested": {
            "type": "array", "items": {"type": "string"},
            "description": "Evidence categories the payer is asking for (e.g. "
                           "'labs', 'imaging_reports'), empty if none.",
        },
        "deadline": {
            "type": ["string", "null"],
            "description": "ISO date the response is due back, or null if none stated.",
        },
    },
    ["decision", "info_requested", "deadline"],
)

INTERPRET_MESSAGE_PROMPT = (
    "You read payer authorization responses (fax, portal, email text) and "
    "extract exactly what they say — the decision, any requested items, "
    "any deadline. You never infer a decision the text doesn't state."
)


@traceable(name="interpret_payer_message", run_type="chain")
def interpret_payer_message(message: str) -> dict:
    """One forced tool call: raw payer response text -> structured fields."""
    return call_tool(
        system=INTERPRET_MESSAGE_PROMPT,
        messages=[{"role": "user", "content": message}],
        tool=INTERPRET_PAYER_MESSAGE,
    )


# -- FR-P7 / Edge Case 9: appeal suggestion (suggest only) --------------------

SUGGEST_APPEAL = strict_tool(
    "suggest_appeal",
    "Given a denial reason and the original evidence, recommend whether "
    "appealing is likely worthwhile and draft a starting argument for the "
    "physician to review and edit. This is a SUGGESTION ONLY — you are not "
    "submitting anything; the physician decides and submits any appeal "
    "themselves.",
    {
        "should_appeal": {
            "type": "boolean",
            "description": "Whether an appeal looks worth pursuing given the "
                           "denial reason and the evidence on file.",
        },
        "recommendation": {
            "type": "string",
            "description": "1-3 sentences explaining the should_appeal call.",
        },
        "draft_argument": {
            "type": ["string", "null"],
            "description": "A starting appeal argument for the physician to edit, "
                           "or null when should_appeal is false.",
        },
    },
    ["should_appeal", "recommendation", "draft_argument"],
)

SUGGEST_APPEAL_PROMPT = (
    "You help physicians decide whether to appeal a denied prior "
    "authorization. You use only the denial reason and evidence given. You "
    "never submit an appeal yourself — you only suggest whether to appeal "
    "and draft a starting argument for a human to review."
)


@traceable(name="suggest_appeal", run_type="chain")
def suggest_appeal(denial_reason: str, package_context: dict) -> dict:
    """One forced tool call: denial reason + evidence -> appeal suggestion."""
    context = {"denial_reason": denial_reason, **package_context}
    return call_tool(
        system=SUGGEST_APPEAL_PROMPT,
        messages=[{"role": "user", "content": json.dumps(context)}],
        tool=SUGGEST_APPEAL,
    )
