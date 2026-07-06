# SPEC_Agent_2 — Patient Registration & Intake

Technical spec for `BUILD_STEPS_Agent_2_Registration_Intake.md`. Shared conventions: `SPEC_Core.md`. Tables: `SCHEMA.md` §core, §registration.

## Backend architecture

```
patient ──▶ /api/registration/chat/ (SSE)
  └▶ handle_registration_message()                       registration/ai.py
       state machine over Patient.registration_status:
       demographics ─▶ identity (OTP) ─▶ duplicate check ─▶ insurance ─▶ intake ─▶ done
       │                                                                   │
       │  call_tool(record_registration_data) each turn                    │
       ▼                                                                   ▼
  services.find_matching_patients / create_or_update_patient_record   generate_intake_summary()
                                                                           │
  document upload ──▶ POST /upload ──▶ ai.extract_document_data (vision)   │
                        └▶ InsurancePolicy / UploadedDocument.extracted    ▼
                                                    emit("registration.completed")
```

The conversation is **model-driven but state-gated**: the model chooses the next question inside the current stage; your code decides stage transitions (OTP verified? duplicate resolved? insurance active?).

## Folder structure

```
registration/
├── models.py            # InsurancePolicy, IntakeSummary, UploadedDocument
├── services.py          # find_matching_patients, verify_insurance_eligibility,
│                        # create_or_update_patient_record, complete_registration
├── ai.py                # record_registration_data + extract_document_data tools,
│                        # handle_registration_message, generate_intake_summary
├── eligibility.py       # PayerEligibilityGateway interface + StubGateway
├── serializers.py  views.py  urls.py  admin.py
└── tests/  test_services.py  test_api.py  test_prompts.py  fixtures/cards/*.png
```

(OTP lives in `core/identity.py` — shared with Agents 4 and 9.)

## API design

| Method | Path | Auth | Body → Response |
|---|---|---|---|
| POST | `/api/registration/start/` | none | `{channel}` → `201 {session_token, conversation_id}` |
| POST | `/api/registration/chat/` | session | `{message}` → SSE stream; `ui_hints` may request `{"otp_required"}`, `{"upload": "insurance_card"}` |
| POST | `/api/registration/otp/request/` | session | `{channel}` → `202` |
| POST | `/api/registration/otp/verify/` | session | `{code}` → `{verified: true}`; `400 {code:"otp_expired"|"otp_invalid"}` |
| POST | `/api/registration/documents/` | session | multipart `{file, doc_type}` → `201 {id, extraction_status}` |
| GET  | `/api/registration/status/` | session | → `{registration_status, missing: ["insurance", ...]}` |
| GET  | `/api/staff/registration/analytics/` | staff | → FR-R10 aggregates |

Example — document upload response after extraction:

```json
{
  "id": 41, "doc_type": "insurance_card", "extraction_status": "done",
  "extracted_data": {"provider": "BlueShield", "policy_number": "BS-448291",
                      "member_id": "M-99213", "coverage_start": "2026-01-01"},
  "eligibility_status": "active"
}
```

## Code examples

Duplicate detection (`services.py`) — deterministic, tested first:

```python
from django.db.models import Q

def find_matching_patients(name: str, dob, phone: str) -> tuple[str, list]:
    phone_n = normalize_e164(phone)
    exact = Patient.objects.filter(phone=phone_n, dob=dob)
    if exact.exists():
        return "existing", list(exact)
    fuzzy = Patient.objects.filter(dob=dob).filter(
        Q(last_name__iexact=name.split()[-1]) | Q(phone=phone_n))
    if fuzzy.exists():
        return "possible_duplicate", list(fuzzy)     # never auto-create (Edge Case 4)
    return "new", []
```

Document extraction with vision (`ai.py`) — replaces a separate OCR service (FR-R4/R6):

```python
import base64
from core.ai import client, MODEL, strict_tool

EXTRACT_INSURANCE = strict_tool(
    "extract_document_data", "Extract structured fields from the document image.",
    properties={
        "provider": {"type": ["string", "null"]},
        "policy_number": {"type": ["string", "null"]},
        "member_id": {"type": ["string", "null"]},
        "coverage_start": {"type": ["string", "null"], "format": "date"},
        "coverage_end": {"type": ["string", "null"], "format": "date"},
        "legible": {"type": "boolean"},
    },
    required=["provider", "policy_number", "member_id",
              "coverage_start", "coverage_end", "legible"],
)

def extract_document_data(document: UploadedDocument) -> dict:
    data = base64.standard_b64encode(document.file.read()).decode()
    resp = client.messages.create(
        model=MODEL, max_tokens=1024,
        tools=[EXTRACT_INSURANCE],
        tool_choice={"type": "tool", "name": "extract_document_data"},
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64",
             "media_type": "image/png", "data": data}},
            {"type": "text", "text": "Extract the insurance card fields."},
        ]}],
    )
    return next(b for b in resp.content if b.type == "tool_use").input
```

Registration turn tool — all-optional capture + model-suggested next step:

```python
RECORD_REGISTRATION_DATA = strict_tool(
    "record_registration_data",
    "Record any registration fields the patient just provided and pick the next topic.",
    properties={
        "captured": {"type": "object", "additionalProperties": False, "properties": {
            "first_name": {"type": ["string", "null"]}, "last_name": {"type": ["string", "null"]},
            "dob": {"type": ["string", "null"], "format": "date"},
            "phone": {"type": ["string", "null"]}, "email": {"type": ["string", "null"]},
            "address": {"type": ["string", "null"]},
            "emergency_contact": {"type": ["string", "null"]},
            "preferred_language": {"type": ["string", "null"]},
            "preferred_pharmacy": {"type": ["string", "null"]},
            "intake_answers": {"type": ["object", "null"], "additionalProperties": True},
        }, "required": ["first_name","last_name","dob","phone","email","address",
                         "emergency_contact","preferred_language","preferred_pharmacy",
                         "intake_answers"]},
        "next_question": {"type": ["string", "null"]},
        "stage_complete": {"type": "boolean"},
    },
    required=["captured", "next_question", "stage_complete"],
)
```

Completion emits the platform event (ORCHESTRATION §3):

```python
from core.events import emit

def complete_registration(patient):
    patient.registration_status = "complete"
    patient.save(update_fields=["registration_status"])
    ehr.record_encounter(patient, kind="registration")           # audit trail
    emit("registration.completed", patient_id=patient.id,
         has_symptoms=bool(patient.intakesummary.symptoms))
```

## Tech stack additions

- `Pillow` (image handling for uploads); `django-storages` in prod for the documents bucket
- Claude vision (image/document content blocks) instead of a dedicated OCR service — one fewer dependency and it returns structured JSON directly
- Eligibility gateway: interface + stub now; a clearinghouse API later (unspecified in PRD)
