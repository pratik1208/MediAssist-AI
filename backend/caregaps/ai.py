"""AI layer for the care gap agent (Agent 8, Phase 4).

Deliberately the smallest AI surface of any agent: gap DETECTION stays 100%
deterministic (auditable, NFR-4 — a model never decides whether a patient is
overdue). The model only ever:

  write_care_plan_message — turn an already-bundled care plan into ONE warm,
  plain-language outreach message in the patient's language ("you're due for
  A, B and C — we can do all three in one visit"). Grounded hard: the message
  may mention ONLY the listed items; it must never add a clinical claim,
  urgency, or promise beyond them. The caller prepends "Hi {name}," itself
  (same convention as outreach) and falls back to the deterministic
  plan_text if the model is unreachable — a wave never blocks on AI.

  extract_clinical_events — Agent 2's document-extraction discipline applied
  to lab reports / visit summaries: pull out ONLY events actually stated in
  the text, so the scanner has ClinicalEvent rows to read. The model states
  what the document says; services.backfill_events_from_document validates
  every row in code (known event_type, parseable date, non-empty code) and
  silently skips anything malformed rather than guessing.
"""

import json

from langsmith import traceable

from core.ai import call_tool, strict_tool

# -- FR-G5 prep: the patient-facing care plan message ---------------------------

WRITE_CARE_PLAN_MESSAGE = strict_tool(
    "write_care_plan_message",
    "Write ONE short, warm, plain-language message (SMS/email length) "
    "telling a patient which preventive care items they are due for, in the "
    "requested language. shared_visit_items can all be done in a single "
    "visit -- say so, it's the selling point. separate_items each need "
    "their own appointment. Mention EVERY item given and NOTHING else: no "
    "extra tests, no diagnoses, no urgency or health claims beyond 'you're "
    "due'. Do NOT include a greeting or the patient's name -- the caller "
    "adds 'Hi {name},' itself. End by inviting them to reply to book.",
    {
        "body": {
            "type": "string",
            "description": "The message body only (no greeting/name), in the target language.",
        },
    },
    ["body"],
)

WRITE_PLAN_MESSAGE_PROMPT = (
    "You write short, friendly preventive-care reminder messages for a "
    "clinic, in the requested language. You mention exactly the care items "
    "you are given -- never any other test, condition, or medical claim -- "
    "and you highlight when several items can be done in one visit."
)


@traceable(name="write_care_plan_message", run_type="chain")
def write_care_plan_message(shared_visit_items: list[str], separate_items: list[str],
                            language: str) -> dict:
    """One forced tool call: bundled item names + language -> a message body."""
    return call_tool(
        system=WRITE_PLAN_MESSAGE_PROMPT,
        messages=[{"role": "user", "content": json.dumps({
            "shared_visit_items": shared_visit_items,
            "separate_items": separate_items,
            "language": language,
        })}],
        tool=WRITE_CARE_PLAN_MESSAGE,
    )


# -- optional: backfill ClinicalEvents from an uploaded document ----------------

EXTRACT_CLINICAL_EVENTS = strict_tool(
    "extract_clinical_events",
    "Extract clinical events from the text of a lab report, visit summary, "
    "or discharge note. Report ONLY events explicitly stated in the text -- "
    "never infer, never guess a code or date that isn't there. If the text "
    "names a test/vaccine/visit but gives no standard code, leave code as "
    "an empty string; if it gives no date, leave date null (the caller "
    "skips undated events rather than inventing a date). Set legible=false "
    "if the text is too garbled to read reliably.",
    {
        "legible": {
            "type": "boolean",
            "description": "False if the text can't be read reliably; events must be [] then.",
        },
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "event_type": {
                        "type": "string",
                        "enum": ["lab", "vaccination", "visit", "procedure", "diagnosis"],
                    },
                    "code": {
                        "type": "string",
                        "description": "LOINC/CPT/CVX/ICD-style code AS PRINTED, or '' if none given.",
                    },
                    "date": {
                        "type": ["string", "null"],
                        "description": "ISO date (YYYY-MM-DD) the event occurred, exactly as stated; null if not stated.",
                    },
                    "value": {
                        "type": "object",
                        "description": 'Result values as stated, e.g. {"hba1c": 8.4}; {} if none.',
                        "additionalProperties": True,
                    },
                },
                "required": ["event_type", "code", "date", "value"],
                "additionalProperties": False,
            },
        },
    },
    ["legible", "events"],
)

EXTRACT_EVENTS_PROMPT = (
    "You extract clinical events (labs, vaccinations, visits, procedures, "
    "diagnoses) from medical document text. You only report what the text "
    "explicitly states -- no inferred codes, no guessed dates, no assumed "
    "results. When in doubt, leave it out."
)


@traceable(name="extract_clinical_events", run_type="chain")
def extract_clinical_events(document_text: str) -> dict:
    """One forced tool call: raw document text -> stated events only."""
    return call_tool(
        system=EXTRACT_EVENTS_PROMPT,
        messages=[{"role": "user", "content": json.dumps({"document_text": document_text})}],
        tool=EXTRACT_CLINICAL_EVENTS,
    )
