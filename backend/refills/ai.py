"""AI layer for the refill agent (Agent 4, Phase 4).

Deliberately thin: the AI only (a) extracts what the patient SAID and
(b) writes the physician's one-glance summary. Everything decisional —
which prescription, eligibility, approval — is deterministic code
(services.py). The model states; the code resolves.
"""

from langsmith import traceable

from core.ai import call_tool, strict_tool

# What the patient asked for, verbatim-ish (FR-M1). Strict: unknown = null,
# never omitted, so the handler can distinguish "not mentioned" reliably.
EXTRACT_REFILL_INTENT = strict_tool(
    "extract_refill_intent",
    "Extract the refill request details exactly as the patient stated them. "
    "Record the medication name in the patient's own words — NEVER substitute "
    "a drug name they did not say, never correct spelling, never guess. Use "
    "null for anything not mentioned. Set needs_clarification when no "
    "medication is identifiable from the message.",
    {
        "medication_stated": {
            "type": ["string", "null"],
            "description": "The medication as the patient said it ('my blood "
                           "pressure meds', 'metforman', 'Lipitor'), or null.",
        },
        "dose_stated": {"type": ["string", "null"],
                        "description": "Dose if mentioned, e.g. '5 mg'."},
        "quantity_stated": {"type": ["string", "null"],
                            "description": "Quantity if mentioned, e.g. '30 tablets'."},
        "pharmacy_stated": {"type": ["string", "null"],
                            "description": "Preferred pharmacy if mentioned."},
        "needs_clarification": {
            "type": "boolean",
            "description": "True when the message does not identify a "
                           "medication well enough to look it up.",
        },
    },
    ["medication_stated", "dose_stated", "quantity_stated", "pharmacy_stated",
     "needs_clarification"],
)

EXTRACT_PROMPT = (
    "You extract prescription refill requests for a medical clinic. You only "
    "record what the patient actually said — you never guess, complete, or "
    "correct medication names. You never give medical advice."
)

# The physician's one-glance summary (NFR-10: review in seconds).
SUMMARIZE_FOR_PHYSICIAN = strict_tool(
    "summarize_for_physician",
    "Turn the structured renewal data into a 3-4 line plain-language summary "
    "a physician reads in seconds before deciding. Use ONLY the data given — "
    "never add clinical claims, never recommend a decision. Lead with the "
    "medication and how long the patient has been on it; mention adherence, "
    "relevant labs, and refills remaining / renewal status.",
    {
        "summary_text": {
            "type": "string",
            "description": "3-4 short lines, neutral clinical tone.",
        },
    },
    ["summary_text"],
)

SUMMARY_PROMPT = (
    "You write concise refill-review summaries for physicians. Every "
    "statement must come from the structured data provided; you never add "
    "findings and never recommend approving or rejecting."
)


@traceable(name="extract_refill_intent", run_type="chain")
def extract_refill_intent(conversation_history: list[dict]) -> dict:
    """One forced tool call: what did the patient ask for, verbatim-ish."""
    return call_tool(
        system=EXTRACT_PROMPT,
        messages=conversation_history,
        tool=EXTRACT_REFILL_INTENT,
    )


@traceable(name="summarize_for_physician", run_type="chain")
def summarize_for_physician(renewal_summary: dict) -> str:
    """One call: Phase 2's structured renewal_summary -> 3-4 line paragraph."""
    result = call_tool(
        system=SUMMARY_PROMPT,
        messages=[{"role": "user", "content": f"Renewal data: {renewal_summary}"}],
        tool=SUMMARIZE_FOR_PHYSICIAN,
    )
    return result["summary_text"]
