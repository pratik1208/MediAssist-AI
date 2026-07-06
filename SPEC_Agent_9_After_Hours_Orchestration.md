# SPEC_Agent_9 — After-Hours Automation (24×7 Orchestration)

Technical spec for `BUILD_STEPS_Agent_9_After_Hours_Orchestration.md`. Shared conventions: `SPEC_Core.md` (esp. §4.5 `AgentReply`). Tables: `SCHEMA.md` §frontdesk.

## Backend architecture — the control tower

```
any channel ─▶ POST /api/frontdesk/chat/ (SSE)
   └▶ handle_frontdesk_message(session, history, text)
        1. core.safety.red_flag_check(text)          deterministic, pre-AI (FR-A6)
             hit ─▶ emergency script + on-call alert (STOP)
        2. call_tool(route_message)                  intents[] — multi-intent (FR-A2, EC16)
        3. mandatory_escalation_category? ─▶ StaffTask(critical) (FR-A7, EC12)
        4. auth gate: any intent requires_auth and session not authenticated?
             ─▶ queue intents in session.pending_intents, run OTP step-up, resume after
        5. for each intent, in order:
             AGENT_REGISTRY[intent].handler(conversation, history, payload) → AgentReply
             (an AgentReply.handoff re-enters this dispatch loop)
        6. merge replies into ONE response; log IntentRoute rows; write transcript (FR-A8)

faq intent ─▶ search_knowledge() (Postgres FTS) ─▶ grounded answer or StaffTask (FR-A5)
```

This agent owns **conversational** orchestration; async workflow handoffs stay on `core.events` (ORCHESTRATION §1 — don't mix the two).

## Folder structure

```
frontdesk/
├── models.py            # PatientSession, IntentRoute, KnowledgeArticle, StaffTask
├── registry.py          # AGENT_REGISTRY — the declarative intent map (below)
├── services.py          # authenticate_session, search_knowledge, create_staff_task
├── ai.py                # route_message tool, handle_frontdesk_message, answer_faq
├── serializers.py  views.py  urls.py  admin.py
├── management/commands/seed_knowledge.py
└── tests/  test_registry.py  test_router.py  test_auth_gate.py  test_faq.py
```

## The agent registry (`registry.py`)

```python
from dataclasses import dataclass
from typing import Callable

@dataclass(frozen=True)
class Route:
    handler: Callable          # (conversation, history, payload) -> AgentReply
    requires_auth: bool

from scheduling.ai import handle_patient_message as scheduling_handler
from refills.ai import handle_refill_message as refills_handler
from triage.ai import handle_triage_message as triage_handler
# status lookups are thin read-services, not chats:
from referrals.services import referral_status_reply
from priorauth.services import pa_status_reply
from caregaps.services import care_gap_reply

AGENT_REGISTRY: dict[str, Route] = {
    "appointment":     Route(scheduling_handler, requires_auth=True),
    "refill":          Route(refills_handler, requires_auth=True),
    "symptoms":        Route(triage_handler, requires_auth=True),
    "referral_status": Route(referral_status_reply, requires_auth=True),
    "pa_status":       Route(pa_status_reply, requires_auth=True),
    "care_gap":        Route(care_gap_reply, requires_auth=True),
    "faq":             Route(answer_faq, requires_auth=False),
    "other":           Route(route_to_staff_task, requires_auth=False),
}
```

Adding an agent to the platform = one import + one line. Registration is reached via `/api/registration/start/` for brand-new patients (no auth to gate).

## API design

| Method | Path | Auth | Body → Response |
|---|---|---|---|
| POST | `/api/frontdesk/sessions/` | none | `{channel}` → `201 {session_token}` |
| POST | `/api/frontdesk/chat/` | session | `{message}` → SSE; `ui_hints` may include `{"otp_required"}`, `{"slots"}`, `{"status_card"}`, `{"emergency"}` |
| POST | `/api/frontdesk/authenticate/` | session | `{dob, otp_code}` → `{authenticated: true}`; resumes `pending_intents` |
| GET  | `/api/staff/frontdesk/tasks/?status=open` | staff | → task queue |
| POST | `/api/staff/frontdesk/tasks/{id}/claim/` `/resolve/` | staff | → status change |
| GET  | `/api/staff/frontdesk/analytics/` | staff | → FR-A9: `{volume, automation_rate, escalation_rate, avg_response_ms, top_intents}` |

## Code examples

Router tool (`ai.py`):

```python
INTENTS = ["appointment", "refill", "symptoms", "referral_status",
           "pa_status", "care_gap", "faq", "other"]

ROUTE_MESSAGE = strict_tool(
    "route_message", "Classify every intent in the patient's message.",
    properties={
        "intents": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "intent": {"type": "string", "enum": INTENTS},
                "payload": {"type": "string", "description": "the part of the message for this intent"},
            }, "required": ["intent", "payload"]}},
        "emergency_symptoms_detected": {"type": "boolean"},
        "mandatory_escalation_category": {"type": ["string", "null"],
            "enum": ["mental_health", "stroke", "insurance_dispute",
                     "controlled_substance", None]},
    },
    required=["intents", "emergency_symptoms_detected", "mandatory_escalation_category"],
)
```

The dispatch loop:

```python
def handle_frontdesk_message(session, history, text) -> AgentReply:
    if red_flag_check(text):                                     # layer 1, always first
        create_staff_task(session, "emergency", "critical", text)
        return AgentReply(text=EMERGENCY_SCRIPT, ui_hints={"emergency": True})

    route = call_tool(ROUTER_SYSTEM_PROMPT, history + [{"role": "user", "content": text}],
                      ROUTE_MESSAGE)
    if route["emergency_symptoms_detected"]:
        create_staff_task(session, "emergency", "critical", text)
        return AgentReply(text=EMERGENCY_SCRIPT, ui_hints={"emergency": True})
    if cat := route["mandatory_escalation_category"]:
        create_staff_task(session, cat, "critical", text)        # Edge Case 12 — always human
        return AgentReply(text=ESCALATION_ACK[cat])

    protected = [i for i in route["intents"] if AGENT_REGISTRY[i["intent"]].requires_auth]
    if protected and not session.authenticated:
        session.pending_intents = route["intents"]; session.save()
        return AgentReply(text="I can help with that — first let me verify it's you.",
                          ui_hints={"otp_required": True}, followup_needed=True)

    replies, hints = [], {}
    for item in route["intents"]:
        r = dispatch(session, history, item)                     # follows AgentReply.handoff
        IntentRoute.objects.create(session=session, intent=item["intent"],
                                   target_agent=item["intent"], status="completed",
                                   payload=item)
        replies.append(r.text); hints |= r.ui_hints
    return AgentReply(text="\n\n".join(filter(None, replies)), ui_hints=hints,
                      followup_needed=any_followup(replies))
```

Grounded FAQ (`services.py` + `ai.py`):

```python
from django.contrib.postgres.search import SearchQuery, SearchRank

def search_knowledge(query, limit=3):
    q = SearchQuery(query)
    return (KnowledgeArticle.objects.filter(search_vector=q)
            .annotate(rank=SearchRank("search_vector", q))
            .order_by("-rank")[:limit])

def answer_faq(conversation, history, payload) -> AgentReply:
    articles = search_knowledge(payload)
    if not articles:
        create_staff_task(conversation.patientsession, "unanswered_question", "normal", payload)
        return AgentReply(text="I don't have that answer on hand — I've passed your question to our team and they'll get back to you.")
    context = "\n---\n".join(f"{a.title}\n{a.body}" for a in articles)
    out = call_tool(
        "Answer ONLY from the provided articles. If they don't contain the answer, "
        "set answerable=false. Never invent clinic facts.",
        [{"role": "user", "content": f"Articles:\n{context}\n\nQuestion: {payload}"}],
        strict_tool("faq_answer", "Grounded answer.",
                    {"answerable": {"type": "boolean"}, "answer": {"type": ["string", "null"]}},
                    ["answerable", "answer"]))
    if not out["answerable"]:
        create_staff_task(conversation.patientsession, "unanswered_question", "normal", payload)
        return AgentReply(text="I've sent that question to our staff — they'll follow up.")
    return AgentReply(text=out["answer"])
```

## Tech stack additions

- Postgres full-text search (`SearchVectorField` + GIN index, trigger or save-signal to refresh) — the RAG layer; upgrade to `pgvector` embeddings only if FTS quality proves insufficient
- Channel adapters later: Twilio SMS/WhatsApp webhooks and telephony + STT (voice) all normalize into `POST /api/frontdesk/chat/` — one front door
- Router-accuracy regression suite (30+ fixture messages incl. multi-intent) runs on every prompt change
