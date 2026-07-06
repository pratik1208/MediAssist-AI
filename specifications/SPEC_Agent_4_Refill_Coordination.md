# SPEC_Agent_4 — Automated Refill Coordination

Technical spec for `BUILD_STEPS_Agent_4_Refill_Coordination.md`. Shared conventions: `SPEC_Core.md`. Tables: `SCHEMA.md` §refills.

## Backend architecture

```
"I need my BP meds" ─▶ chat ─▶ ai.extract_refill_intent (model states the medication)
                                 └▶ services.match_medication (code resolves it: 0/1/many)
identity gate: core.identity verified? ─▶ else OTP step-up (FR-M2)
                                 ▼
                    services.check_eligibility()          ← pure rules, FR-M3
        ┌──────────────┬──────────────┬───────────────────┐
        ▼              ▼              ▼                   ▼
   controlled      any rule       0 refills          eligible
   substance       fails          remaining              │
        │              │              │                   ▼
  EscalationAlert   paused +      renewal path     build_renewal_summary()
  (human only)      notify        (new Rx)          + ai.summarize_for_physician()
                                                          ▼
                                            physician queue: approve/reject/visit
                                                          ▼
                        approve ─▶ ehr write-back ─▶ send_to_pharmacy ─▶ notify pickup
                        visit   ─▶ emit("refill.visit_required") ─▶ scheduling
```

## Folder structure

```
refills/
├── models.py            # Pharmacy, Prescription, RefillRequest
├── services.py          # check_eligibility, build_renewal_summary, approve/reject/
│                        # request_visit, send_to_pharmacy, match_medication
├── ai.py                # extract_refill_intent tool, summarize_for_physician
├── erx.py               # ERxGateway interface + LogOnlyGateway (dev)
├── serializers.py  views.py  urls.py  admin.py
├── management/commands/seed_prescriptions.py
└── tests/  test_eligibility.py  test_api.py  test_prompts.py
```

## API design

| Method | Path | Auth | Body → Response |
|---|---|---|---|
| POST | `/api/refills/requests/` | session (verified) | `{prescription_id, pharmacy_id?}` → `201 {id, status}`; `409 {code:"paused", reason}` |
| GET  | `/api/refills/requests/{id}/` | session | → `{status, status_display, pause_reason?}` |
| GET  | `/api/refills/prescriptions/` | session (verified) | → patient's active prescriptions |
| GET  | `/api/staff/refills/queue/` | staff (physician) | → pending approvals with summaries |
| POST | `/api/staff/refills/{id}/approve/` | staff (physician) | → `{status:"approved"}` (one call = one click, FR-M6) |
| POST | `/api/staff/refills/{id}/reject/` | staff (physician) | `{reason}` → `{status:"rejected"}` |
| POST | `/api/staff/refills/{id}/request-visit/` | staff (physician) | → `{status:"visit_required"}` + booking offer event |

Physician queue item shape:

```json
{"id": 88, "patient": "R. Sharma", "medication": "Lisinopril 10mg",
 "summary_text": "Stable on lisinopril 12 months; BP at last 3 visits <135/85; K+ normal 2 months ago; 0 refills remaining — renewal.",
 "renewal_summary": {"last_prescribed": "2026-01-04", "refills_remaining": 0,
                      "recent_labs": [...], "allergies": [], "adherence": "good"},
 "actions": ["approve", "reject", "request_visit"]}
```

## Code examples

Eligibility engine (`services.py`) — the heart of this agent, zero AI:

```python
from dataclasses import dataclass

@dataclass
class EligibilityResult:
    eligible: bool
    failures: list[str]
    needs_new_prescription: bool = False

def check_eligibility(req: RefillRequest) -> EligibilityResult:
    rx, failures = req.prescription, []
    if rx.is_controlled_substance:
        escalate_controlled(req)                       # human only, Edge Case 12
        return EligibilityResult(False, ["controlled_substance"])
    if rx.status == "discontinued": failures.append("discontinued_by_doctor")
    if rx.expiry_date < date.today(): failures.append("prescription_expired")
    if refill_not_yet_due(rx): failures.append("too_early")
    for lab in rx.required_labs:                       # {test, max_age_days}
        if not recent_lab_exists(req.patient, lab["test"], lab["max_age_days"]):
            failures.append(f"missing_lab:{lab['test']}")
    if rx.followup_required: failures.append("followup_visit_required")
    if rx.refills_used >= rx.refills_allowed and not failures:
        return EligibilityResult(True, [], needs_new_prescription=True)   # FR-M4
    return EligibilityResult(not failures, failures)
```

Medication matching — model states, code resolves:

```python
EXTRACT_REFILL_INTENT = strict_tool(
    "extract_refill_intent", "Extract the refill request details as the patient stated them.",
    properties={
        "medication_stated": {"type": "string", "description": "verbatim-ish name"},
        "dose_stated": {"type": ["string", "null"]},
        "pharmacy_stated": {"type": ["string", "null"]},
        "needs_clarification": {"type": "boolean"},
    },
    required=["medication_stated", "dose_stated", "pharmacy_stated", "needs_clarification"],
)

def match_medication(stated: str, patient) -> Prescription | None:
    active = patient.prescription_set.filter(status="active")
    hits = [rx for rx in active
            if similar(stated, rx.medication_name) or generic_brand_match(stated, rx)]
    return hits[0] if len(hits) == 1 else None          # 0 or >1 → clarifying question
```

Approval write-back (FR-M7/M8):

```python
from django.db import transaction
from core import ehr
from core.notifications import notify
from core.events import emit

@transaction.atomic
def approve(req: RefillRequest, doctor):
    req.status, req.decided_by, req.decided_at = "approved", doctor, now()
    req.save()
    new_rx = ehr.record_prescription(                   # audit trail included
        patient=req.patient, prescriber=doctor,
        template=req.prescription, refills=req.prescription.refills_allowed)
    erx.gateway.transmit(new_rx, req.pharmacy)          # LogOnlyGateway in dev
    req.status = "sent_to_pharmacy"; req.save()
    notify(req.patient, "refill_sent", {"medication": new_rx.medication_name,
                                          "pharmacy": req.pharmacy.name})
    emit("refill.approved", patient_id=req.patient_id, request_id=req.id)
```

## Tech stack additions

- `rapidfuzz` for medication-name fuzzy matching (brand/generic table + similarity score)
- e-Rx gateway interface with a log-only dev implementation; a real network (Surescripts-class) is a later drop-in
