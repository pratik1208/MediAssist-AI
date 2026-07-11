"""AI layer for the referral agent (Agent 5, Phase 4).

Two forced tool calls, same "the model states, the code decides" split as
every other agent's AI layer:

  select_referral_content — given every chart item and the target specialty,
  the model picks WHICH item ids are relevant and writes the summary. Only
  the ids are trusted; services.build_referral_package() re-fetches the
  actual item content by id rather than letting the model reproduce chart
  data itself (FR-F2).

  extract_consultation_report — a vision call reading an uploaded
  consultation report, mirroring registration.ai.extract's document
  extraction (same content-block helper, same legible-flag convention).

NOTE: the report extraction path needs a vision-capable provider
(AI_PROVIDER=anthropic), same as registration's document extraction.
"""

import base64
import json
import mimetypes

from langsmith import traceable

from core.ai import call_tool, strict_tool

# -- FR-F2: which chart items go in the package, plus the summary -----------

SELECT_REFERRAL_CONTENT = strict_tool(
    "select_referral_content",
    "Given a list of chart items (each with an id, category, and text) and "
    "the specialty a referral is being sent to, select ONLY the item ids "
    "that specialist actually needs to review, and write a concise 3-5 line "
    "referral summary using ONLY the selected items. Never invent findings "
    "not present in the items. Current medications are usually relevant to "
    "any specialist (drug interactions) unless clearly unrelated (e.g. a "
    "topical cream for an unrelated specialty). Exclude items about a "
    "clearly different body system or specialty (e.g. a dermatology note on "
    "a cardiology referral) unless the item itself says it's relevant.",
    {
        "selected_item_ids": {
            "type": "array", "items": {"type": "string"},
            "description": "The ids (verbatim from the input) of every chart "
                           "item relevant to this referral's specialty.",
        },
        "summary_text": {
            "type": "string",
            "description": "3-5 short lines, neutral clinical tone, built only "
                           "from the selected items.",
        },
    },
    ["selected_item_ids", "summary_text"],
)

SELECT_REFERRAL_CONTENT_PROMPT = (
    "You are a clinical referral coordinator preparing a specialist referral "
    "package. You select only the chart items the receiving specialist needs "
    "and write a short, neutral summary. You never add clinical claims beyond "
    "what the provided items state, and you never recommend a diagnosis or "
    "treatment."
)


@traceable(name="select_referral_content", run_type="chain")
def select_referral_content(specialty: str, reason: str, items: list[dict]) -> dict:
    """One forced tool call: which chart item ids matter + the summary."""
    context = {"specialty_needed": specialty, "referral_reason": reason, "chart_items": items}
    return call_tool(
        system=SELECT_REFERRAL_CONTENT_PROMPT,
        messages=[{"role": "user", "content": json.dumps(context)}],
        tool=SELECT_REFERRAL_CONTENT,
    )


# -- FR-F10: reading a specialist's consultation report ----------------------

def _content_block(filename: str, data: bytes) -> dict:
    """Wrap file bytes as an Anthropic image or document content block
    (same helper as registration.ai.extract — kept local rather than
    imported so this agent's AI layer stays self-contained)."""
    media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    encoded = base64.standard_b64encode(data).decode("utf-8")
    if media_type == "application/pdf":
        return {"type": "document", "source": {"type": "base64", "media_type": media_type, "data": encoded}}
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": encoded}}


EXTRACT_CONSULTATION_REPORT = strict_tool(
    "extract_consultation_report",
    "Extract the diagnosis, treatment plan, medications, and follow-up "
    "recommendations from an uploaded specialist consultation report, "
    "exactly as written. Only transcribe what is visible — never infer or "
    "add clinical content beyond what's on the page. Set legible to false "
    "if the document can't be read reliably.",
    {
        "diagnosis": {"type": ["string", "null"], "description": "The diagnosis as stated, or null."},
        "treatment_plan": {"type": ["string", "null"], "description": "The treatment plan as stated, or null."},
        "medications": {
            "type": ["array", "null"], "items": {"type": "string"},
            "description": "Medications prescribed/adjusted by the specialist, or null.",
        },
        "followup_recommendations": {
            "type": ["array", "null"], "items": {"type": "string"},
            "description": "Follow-up instructions (e.g. 'repeat ECG in 3 months'), or null.",
        },
        "legible": {
            "type": "boolean",
            "description": "False if the document cannot be read reliably and should be re-uploaded.",
        },
    },
    ["diagnosis", "treatment_plan", "medications", "followup_recommendations", "legible"],
)

EXTRACTION_SYSTEM_PROMPT = (
    "You are a medical-document transcription assistant reading a "
    "specialist's consultation report. You only transcribe what is visible "
    "— you never guess at missing or unreadable values, and you never add "
    "clinical judgment of your own."
)


@traceable(name="extract_consultation_report", run_type="chain")
def extract_consultation_report_fields(document) -> dict:
    """Vision call: an uploaded consultation report -> structured fields."""
    with document.file.open("rb") as f:
        data = f.read()
    return call_tool(
        system=EXTRACTION_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                _content_block(document.file.name, data),
                {"type": "text", "text": "Extract the structured fields from this consultation report."},
            ],
        }],
        tool=EXTRACT_CONSULTATION_REPORT,
    )
