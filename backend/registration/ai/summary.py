"""Intake summary generation for the registration agent (FR-R7).

One API call that turns the raw intake collected during the conversation
into (a) a cleaned, structured clinical profile and (b) a short
physician-readable paragraph. Both are saved onto the patient's
IntakeSummary row (clinical_profile / summary_text).
"""

import json

from django.utils import timezone
from langsmith import traceable

from core.ai import call_tool
from core.models import Patient
from registration.ai.tools import GENERATE_INTAKE_SUMMARY_TOOL
from registration.models import IntakeSummary

SUMMARY_SYSTEM_PROMPT = (
    "You are a clinical intake summarizer for a medical clinic. You receive "
    "the raw intake a patient gave during conversational registration and "
    "produce a cleaned structured profile plus a short paragraph for the "
    "treating physician. You only restate what the patient reported — you "
    "never add findings, interpret symptoms, or suggest diagnoses."
)


def _age(patient: Patient) -> int | None:
    if not patient.dob:
        return None
    return (timezone.now().date() - patient.dob).days // 365




@traceable(name="generate_intake_summary", run_type="chain")
def generate_intake_summary(patient: Patient) -> IntakeSummary:
    """Fill in the patient's latest IntakeSummary with one API call.

    Reads the raw accumulated intake from the row the conversation handler
    wrote at completion, and saves back the normalized clinical_profile and
    the physician-readable summary_text.
    """
    summary = (
        IntakeSummary.objects.filter(patient=patient).order_by("-created_at").first()
    )
    if summary is None:
        raise ValueError(f"No intake recorded for patient {patient.id}")

    payload = {
        "patient_age": _age(patient),
        "raw_intake": summary.clinical_profile,
    }
    result = call_tool(
        system=SUMMARY_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": "Summarize this registration intake:\n" + json.dumps(payload),
        }],
        tool=GENERATE_INTAKE_SUMMARY_TOOL,
    )

    summary.clinical_profile = result["clinical_profile"]
    summary.summary_text = result["summary_text"]
    summary.save(update_fields=["clinical_profile", "summary_text"])
    return summary
