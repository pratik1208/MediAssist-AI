"""Document extraction for the registration agent (FR-R4, FR-R6).

Sends an uploaded document (insurance card, ID, lab report, ...) to the
model as an image/document content block and gets structured fields back
via the strict extract_document_data tool. This replaces a separate OCR
service.

NOTE: this path needs a vision-capable provider. The build steps target
claude-opus-4-8, so run it with AI_PROVIDER=anthropic — the content blocks
below use the Anthropic image/document format.
"""

import base64
import mimetypes

from django.utils import timezone
from langsmith import traceable

from core.ai import call_tool

from registration.ai.tools import EXTRACT_DOCUMENT_DATA_TOOL
from registration.models import UploadedDocument

EXTRACTION_SYSTEM_PROMPT = (
    "You are a medical-document transcription assistant. You read uploaded "
    "documents (insurance cards, IDs, prescriptions, lab reports, referral "
    "letters) and extract the fields exactly as printed. You only transcribe "
    "what is visible — you never guess at missing or unreadable values."
)


def _content_block(filename: str, data: bytes) -> dict:
    """Wrap file bytes as an Anthropic image or document content block."""
    media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    encoded = base64.standard_b64encode(data).decode("utf-8")
    if media_type == "application/pdf":
        return {"type": "document", "source": {"type": "base64", "media_type": media_type, "data": encoded}}
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": encoded}}


@traceable(name="extract_document_data", run_type="chain")
def extract_document_fields(document: UploadedDocument) -> dict:
    """Return the structured fields the model read off the document."""
    with document.file.open("rb") as f:
        data = f.read()
    return call_tool(
        system=EXTRACTION_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                _content_block(document.file.name, data),
                {"type": "text",
                 "text": f"The patient uploaded this as: {document.document_type}. "
                         "Extract the structured fields."},
            ],
        }],
        tool=EXTRACT_DOCUMENT_DATA_TOOL,
    )


def run_document_extraction(document: UploadedDocument) -> dict:
    """Extract, then persist the result onto the UploadedDocument row.

    Fills extracted_data and flips extraction_status to done/failed —
    the fields Phase 1 added exactly for this.
    """
    try:
        extracted = extract_document_fields(document)
    except Exception:
        document.extraction_status = "failed"
        document.save(update_fields=["extraction_status"])
        raise
    document.extracted_data = {**extracted, "extracted_at": timezone.now().isoformat()}
    document.extraction_status = "done" if extracted.get("legible", False) else "failed"
    document.save(update_fields=["extracted_data", "extraction_status"])
    return extracted
