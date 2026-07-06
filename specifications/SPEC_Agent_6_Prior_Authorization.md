# SPEC_Agent_6 — Prior Authorization

Technical spec for `BUILD_STEPS_Agent_6_Prior_Authorization.md`. Shared conventions: `SPEC_Core.md`. Tables: `SCHEMA.md` §priorauth.

## Backend architecture

```
TreatmentOrder created (referral / triage / physician) or emit("priorauth.needed")
        ▼
services.detect_authorization_requirement()      ← PayerRule match, deterministic (FR-P1)
        │ not required ─▶ done (recorded)
        ▼ required
services.gather_evidence()                       ← collect by rule's documentation list (FR-P2)
        ▼
ai.write_reviewer_summary()                      ← AI: medical-necessity summary (FR-P3)
        ▼
PayerGateway.submit()                            ← channel per rule: api/epa/portal/fax (FR-P4)
        ▼                    ┌──────────────────────────────┐
hourly cron poll_status() ──▶│  SimulatedPayerGateway (dev) │  (FR-P5)
        ▼                    └──────────────────────────────┘
ai.interpret_payer_message()                     ← AI: parse payer responses
   ├─ info_requested ─▶ handle_info_request(): auto-retrieve docs OR StaffTask (FR-P6)
   ├─ approved ─▶ notify + emit("priorauth.approved") ─▶ scheduling books (FR-P7)
   └─ denied   ─▶ notify physician + ai.suggest_appeal() (suggest only — Future Enhancement)
```

Everything payer-facing sits behind `PayerGateway`; the simulator is the only implementation until real integrations exist (the PRD names none).

## Folder structure

```
priorauth/
├── models.py            # PayerRule, TreatmentOrder, AuthorizationRequest,
│                        # AuthorizationPackage, PayerMessage
├── services.py          # detect_authorization_requirement, gather_evidence,
│                        # submit, poll_status, handle_info_request, on_decision
├── ai.py                # write_reviewer_summary, interpret_payer_message, suggest_appeal
├── gateway.py           # PayerGateway interface + SimulatedPayerGateway
├── serializers.py  views.py  urls.py  admin.py
├── management/commands/  seed_payer_rules.py  poll_pa_status.py
└── tests/  test_detection.py  test_workflow.py  test_api.py  test_prompts.py
```

## API design

| Method | Path | Auth | Body → Response |
|---|---|---|---|
| POST | `/api/staff/priorauth/orders/` | staff (physician) | `{patient_id, order_type, cpt_code?, icd10_code?, medication?, referral_id?}` → `201 {order_id, auth_required, auth_request_id?}` |
| GET  | `/api/staff/priorauth/requests/{id}/` | staff | → full status + history + package |
| GET  | `/api/priorauth/mine/` | session (verified) | → patient view: `{treatment, status_plain, next_step}` (FR-P7 "visible at any time") |
| GET  | `/api/staff/priorauth/tasks/` | staff | → staged info-requests needing review |
| POST | `/api/staff/priorauth/requests/{id}/submit/` | staff | → `{status:"submitted"}` (auto in normal flow; manual re-submit) |
| POST | `/api/dev/priorauth/simulator/` | dev only | `{request_id, next_response: "approve"\|"deny"\|"request_info", items?}` — drive the fake payer in manual tests |

## Code examples

Detection (`services.py`):

```python
from fnmatch import fnmatch

def detect_authorization_requirement(order: TreatmentOrder) -> AuthorizationRequest | None:
    policy = order.patient.insurancepolicy_set.filter(eligibility_status="active").first()
    if not policy:
        return stage_task(order, "no_active_policy")
    for rule in PayerRule.objects.filter(payer_name__iexact=policy.provider_name):
        if _rule_matches(rule, order) and rule.requires_auth:
            req = AuthorizationRequest.objects.create(
                order=order, policy=policy, matched_rule=rule, status="detected",
                status_history=[{"status": "detected", "at": now().isoformat()}])
            gather_evidence(req)
            return req
    return None                                        # no auth needed — record and done

def _rule_matches(rule, order) -> bool:
    return any([
        rule.cpt_pattern and order.cpt_code and fnmatch(order.cpt_code, rule.cpt_pattern),
        rule.icd10_pattern and order.icd10_code and fnmatch(order.icd10_code, rule.icd10_pattern),
        rule.medication_pattern and order.medication and
            fnmatch(order.medication.lower(), rule.medication_pattern.lower()),
    ])
```

Gateway interface + simulator (`gateway.py`) — what all tests run against:

```python
class PayerGateway:
    def submit(self, request: AuthorizationRequest) -> str: ...      # returns external ref
    def poll(self, request) -> dict: ...                              # {status, message?}
    def send_documents(self, request, items: list) -> None: ...

class SimulatedPayerGateway(PayerGateway):
    """Scripted payer: reads its next move from request.order.metadata or the
    /api/dev simulator endpoint. Deterministic → every branch is testable."""
    def submit(self, request):
        PayerMessage.objects.create(request=request, direction="outbound",
                                    content=json.dumps(request.package_payload()))
        return f"SIM-{request.id}"
    def poll(self, request):
        return self._scripted_response(request)   # approve / deny / request_info fixtures
```

Payer-message interpretation (`ai.py`):

```python
INTERPRET_PAYER_MESSAGE = strict_tool(
    "interpret_payer_message", "Classify a payer response and extract requested items.",
    properties={
        "decision": {"type": "string",
                     "enum": ["approved", "denied", "info_requested", "under_review", "unclear"]},
        "info_requested": {"type": "array", "items": {"type": "string"}},
        "denial_reason": {"type": ["string", "null"]},
        "deadline": {"type": ["string", "null"], "format": "date"},
    },
    required=["decision", "info_requested", "denial_reason", "deadline"],
)

def handle_payer_message(request, raw_text):
    msg = PayerMessage.objects.create(request=request, direction="inbound", content=raw_text)
    parsed = call_tool(PA_SYSTEM_PROMPT,
                       [{"role": "user", "content": raw_text}], INTERPRET_PAYER_MESSAGE)
    msg.parsed = parsed; msg.save()
    if parsed["decision"] == "info_requested":
        handle_info_request(request, parsed["info_requested"])       # auto or StaffTask
    elif parsed["decision"] in ("approved", "denied"):
        on_decision(request, parsed)
```

Decision handling (FR-P7 + Edge Case 9):

```python
def on_decision(request, parsed):
    if parsed["decision"] == "approved":
        advance(request, "approved")
        notify(request.order.patient, "pa_approved", {...})
        emit("priorauth.approved", patient_id=request.order.patient_id,
             order_id=request.order_id)               # scheduling subscribes → books treatment
    else:
        request.denial_reason = parsed["denial_reason"] or "unspecified"
        request.appeal_suggested = should_suggest_appeal(request)     # + ai.suggest_appeal draft
        advance(request, "denied")
        notify_physician(request.order.ordering_doctor, "pa_denied", request)
```

## Tech stack additions

- None new — the simulator IS the integration for now. Real ePA/payer APIs and a fax provider (Phaxio-class) slot in later as additional `PayerGateway` implementations, chosen per `PayerRule.submission_channel`.
- Cron: `poll_pa_status` hourly.
