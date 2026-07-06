# SPEC_Agent_3 — Clinical Triage Support

Technical spec for `BUILD_STEPS_Agent_3_Clinical_Triage.md`. Shared conventions: `SPEC_Core.md`. Tables: `SCHEMA.md` §triage.

## Backend architecture — the two-layer safety design

```
patient text ─▶ LAYER 1: core.safety.red_flag_check()      deterministic, pre-AI
                  │ hit ─▶ EMERGENCY_SCRIPT + EscalationAlert(critical) + on-call notify
                  ▼ miss
               LAYER 2: call_tool(triage_step)              adaptive questioning
                  │ emergency_detected=true ─▶ same emergency path
                  ▼ assessment_complete
               services.assign_acuity()                     protocol rules decide
                  │  (model's suggested_acuity may only RAISE the rule result)
                  ▼
               route_disposition() ─▶ emit("triage.disposition", ...)
                  ├─ same_day/routine ─▶ scheduling
                  ├─ specialist       ─▶ referrals (draft)
                  ├─ meds issue       ─▶ refills
                  └─ preventive       ─▶ caregaps
```

Why two layers: the deterministic screen is auditable and immune to prompt drift (NFR-3); the model layer catches indirect phrasings. Both must fire in tests.

## Folder structure

```
triage/
├── models.py            # ClinicalProtocol, TriageAssessment, EscalationAlert
├── services.py          # select_protocol, assign_acuity, escalate, route_disposition
├── ai.py                # SYSTEM_PROMPT, triage_step tool, handle_triage_message,
│                        # generate_triage_summary
├── serializers.py  views.py  urls.py  admin.py
├── management/commands/seed_protocols.py
└── tests/  test_services.py  test_api.py  test_red_flags.py  test_prompts.py
```

`red_flag_check` itself lives in **`core/safety.py`** so every agent imports it (Edge Case 11 as an invariant).

## API design

| Method | Path | Auth | Body → Response |
|---|---|---|---|
| POST | `/api/triage/assessments/` | session (verified) | `{symptoms_text}` → `201 {id, first_question}` or emergency payload |
| POST | `/api/triage/assessments/{id}/answer/` | session | `{answer}` → `{next_question}` \| `{complete: true, acuity, disposition, explanation, ui_hints}` |
| GET  | `/api/triage/assessments/{id}/` | session | → assessment state |
| GET  | `/api/staff/triage/escalations/?status=open` | staff (nurse+) | → alerts with summaries |
| POST | `/api/staff/triage/escalations/{id}/ack/` | staff | → `{status:"acknowledged"}` |
| GET  | `/api/staff/triage/analytics/` | staff | → FR-T10 aggregates |

Emergency response shape (no follow-ups, ever):

```json
{"complete": true, "acuity": "emergency",
 "message": "Based on what you've described, please call 911 or go to the nearest emergency department now. Our on-call clinician has been alerted.",
 "ui_hints": {"emergency": true}}
```

## Code examples

Deterministic screen (`core/safety.py`):

```python
import re

RED_FLAG_PATTERNS = [
    r"crush(ing)? .*chest", r"chest (pain|pressure|tight)",  # pair with context rules
    r"can'?t breathe|struggling to breathe|short(ness)? of breath at rest",
    r"face .*(droop|numb)|slurr(ed|ing) speech|one side .*(weak|numb)",
    r"(end|take) my (life|own life)|suicid|kill myself",
    r"unconscious|unresponsive|seizure", r"(heavy|severe|uncontrolled) bleeding",
]
_COMPILED = [re.compile(p, re.I) for p in RED_FLAG_PATTERNS]

def red_flag_check(text: str) -> bool:
    return any(p.search(text) for p in _COMPILED)
```

Triage step tool (`triage/ai.py`):

```python
TRIAGE_STEP = strict_tool(
    "triage_step", "Record clinical findings from the patient's answer and choose the next question.",
    properties={
        "extracted_findings": {"type": "object", "additionalProperties": False, "properties": {
            "onset": {"type": ["string", "null"]},
            "severity_1_10": {"type": ["integer", "null"]},
            "location": {"type": ["string", "null"]},
            "radiation": {"type": ["string", "null"]},
            "associated_symptoms": {"type": ["array", "null"], "items": {"type": "string"}},
        }, "required": ["onset", "severity_1_10", "location", "radiation", "associated_symptoms"]},
        "emergency_detected": {"type": "boolean"},
        "next_question": {"type": ["string", "null"]},
        "assessment_complete": {"type": "boolean"},
        "suggested_acuity": {"type": "string",
            "enum": ["emergency", "high", "medium", "low", "minimal"]},
        "rationale": {"type": "string"},
    },
    required=["extracted_findings", "emergency_detected", "next_question",
              "assessment_complete", "suggested_acuity", "rationale"],
)

SYSTEM_PROMPT = """You are a clinical triage assistant following the provided protocol.
Ask ONE question at a time. You support clinical decision-making and never replace it.
You never diagnose. When uncertain between two acuity levels, choose the higher.
Explain in plain language."""
```

Acuity decision — rules win, model can only raise (`services.py`):

```python
ACUITY_ORDER = ["minimal", "low", "medium", "high", "emergency"]

def assign_acuity(assessment) -> str:
    rule_acuity = evaluate_disposition_rules(          # protocol JSON + patient risk factors
        assessment.protocol.disposition_rules,
        assessment.findings,
        patient_risk_factors(assessment.patient),      # age, chronic dx, meds from record
    )
    model_acuity = assessment.findings.get("suggested_acuity", "minimal")
    final = max(rule_acuity, model_acuity, key=ACUITY_ORDER.index)   # never lowered by AI
    assessment.acuity = final
    assessment.disposition = DISPOSITION_FOR[final]     # FR-T4 mapping
    assessment.save()
    return final
```

Escalation + routing:

```python
def escalate(assessment, category="emergency"):
    alert = EscalationAlert.objects.create(
        assessment=assessment, patient=assessment.patient, source_agent="triage",
        category=category, priority="critical",
        summary=generate_triage_summary(assessment))
    notify_on_call(alert)                               # core.notifications, staff channel
    emit("escalation.created", alert_id=alert.id)

DISPOSITION_EVENTS = {"same_day": "triage.disposition", "routine": "triage.disposition",
                      "specialist": "triage.disposition", ...}

def route_disposition(assessment):
    emit("triage.disposition", patient_id=assessment.patient_id,
         disposition=assessment.disposition, acuity=assessment.acuity,
         assessment_id=assessment.id)                   # consumers per ORCHESTRATION §3 table
```

## Tech stack additions

- None beyond shared stack. Protocols and disposition rules are **data** (jsonb rows editable in admin), not code — that's the FR-T5 "approved, configurable" requirement, and it means clinical governance changes don't need deploys.
