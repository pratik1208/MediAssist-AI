# SPEC_Core — Shared technology stack, architecture, folder structure, and code

Everything the nine agent SPECs have in common lives here so they don't repeat it. Read this first; each `SPEC_Agent_N` assumes it.

## 1. Technology stack (recommendations + why)

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.12+ | one language across all agents; best ecosystem for the AI + web combo |
| Web framework | Django 5.x | ORM + migrations + admin (your staff UI for free) + auth; batteries matter for a solo dev |
| API | Django REST Framework | serializers/viewsets/permissions; boring and documented |
| Database | PostgreSQL 16 (`psycopg[binary]`) | jsonb for all the flexible clinical JSON, full-text search (Agent 9), partial unique indexes (Agent 8) |
| AI | `anthropic` Python SDK, model **`claude-opus-4-8`** | one model constant in `core/ai.py`; tool use with `strict: true` for all structured extraction |
| AI observability | LangSmith (`langsmith` SDK, `@traceable`) | trace every agent call; free tier is enough |
| Async/background | Django management commands + platform cron → upgrade to Celery + Redis only when Outreach waves get slow | don't run a broker before you need one (ORCHESTRATION §3) |
| Frontend | Vite + React 18 + TypeScript + Tailwind v4 | already scaffolded in Agent 1 |
| Frontend data | TanStack Query + a typed fetch wrapper; SSE via `fetch` + `ReadableStream` | streaming chat everywhere |
| Testing | `pytest-django`, `factory_boy` for fixtures | plus per-agent prompt-regression suites |
| Files | Django `FileField` → local disk in dev, S3-compatible bucket (`django-storages`) in prod | uploaded documents (Agent 2) |
| Deploy | Railway or Render (backend + Postgres + cron), Vercel (frontend) | as Agent 1 Phase 11 |
| Later swap-ins (all behind interfaces) | Twilio (SMS/voice), SendGrid (email), WhatsApp Business API, e-Rx network, payer ePA APIs, FHIR server | PRD leaves all unspecified — simulators first |

Agent-specific stack additions are one line each and listed in the agent SPECs.

## 2. Backend architecture (shared)

```
                 React SPA (Vercel)                 SMS/WhatsApp webhooks (later)
                        │ HTTPS/JSON + SSE                 │
                        ▼                                  ▼
┌───────────────────────────────────────────────────────────────────────┐
│ Django (Railway/Render)                                               │
│                                                                       │
│  DRF views (thin) ──▶ services.py (ALL business logic, per app)       │
│                          │            │                               │
│                          │            ├──▶ core/ai.py    ─▶ Anthropic │
│                          │            ├──▶ core/notifications.py      │
│                          │            ├──▶ core/ehr.py (+AuditEvent)  │
│                          │            ├──▶ core/safety.py (red flags) │
│                          │            └──▶ core/events.py emit()      │
│                          ▼                                            │
│                     PostgreSQL                                        │
│                                                                       │
│  cron: stalled referrals · PA polling · outreach waves · gap scans    │
└───────────────────────────────────────────────────────────────────────┘
```

Rules every agent follows:

1. **Views are thin.** Parse/validate → call a `services.py` function → serialize. No business logic, no AI calls in views.
2. **Services are pure-ish and tested first.** Deterministic logic before any AI (each BUILD_STEPS Phase 2).
3. **AI is an adapter, not a decision-maker for safety.** Models extract/summarize/classify via `strict` tools; deterministic code decides (acuity rules, eligibility rules, red flags).
4. **All cross-agent side effects go through `core.events.emit()`** (async) or an `AgentReply.handoff` (conversational) — never deep imports of another agent's internals beyond its `services` entry points.
5. **All sends go through `core.notifications`** (opt-out enforcement lives there once).

### Auth model

- **Patients:** conversational session token. `POST /api/frontdesk/sessions/` returns a signed token (store in `PatientSession`); sent as `X-Session-Token`. `identity_verified` on the session gates patient-specific data (NFR-2). A DRF authentication class resolves token → session → patient.
- **Staff/physicians:** Django users + DRF `TokenAuthentication`, role via Django groups (`physician`, `nurse`, `coordinator`, `frontdesk`, `admin`). Staff endpoints use `IsAuthenticated` + a role permission class.
- **API namespacing:** `/api/<app>/...` for patient-facing, `/api/staff/<app>/...` for staff. Errors: DRF default shape `{"detail": ...}` plus `{"code": "..."}` for machine-readable failures.

## 3. Repo folder structure (full project)

```
MediAssist-AI/
├── PRD.md, SCHEMA.md, ORCHESTRATION.md, SPEC_*.md, BUILD_STEPS_*.md
├── backend/
│   ├── manage.py
│   ├── requirements.txt
│   ├── .env                        # ANTHROPIC_API_KEY, LANGSMITH_API_KEY, DJANGO_SECRET_KEY, DATABASE_URL
│   ├── config/                     # settings.py, urls.py, asgi.py
│   ├── core/
│   │   ├── models.py               # Patient, Doctor, Conversation, Message, OTPChallenge, ...
│   │   ├── ai.py                   # Anthropic wrapper (below)
│   │   ├── events.py               # dispatcher (below)
│   │   ├── notifications.py        # notify() + provider interface (below)
│   │   ├── ehr.py                  # record_* functions + AuditEvent
│   │   ├── safety.py               # red_flag_check()
│   │   ├── identity.py             # OTP create/verify
│   │   └── tests/
│   ├── scheduling/  registration/  triage/  refills/  referrals/
│   ├── priorauth/   outreach/      caregaps/ frontdesk/
│   │   └── (each app, same layout:)
│   │       ├── models.py  serializers.py  views.py  urls.py  admin.py
│   │       ├── services.py         # business logic
│   │       ├── ai.py               # this agent's prompts + tool schemas + AI functions
│   │       ├── apps.py             # subscribes to events in ready()
│   │       ├── management/commands/
│   │       └── tests/              # test_services.py, test_api.py, test_prompts.py
│   └── tests/test_invariants.py    # ORCHESTRATION §6
└── frontend/
    └── src/
        ├── api/client.ts           # typed fetch + SSE helpers
        ├── components/             # ChatWindow, SlotPicker, OtpInput, StatusCard, ...
        ├── pages/patient/          # chat, registration, referral status, ...
        ├── pages/staff/            # approval queue, escalations, dashboards, campaigns
        └── hooks/
```

## 4. Shared code (canonical implementations)

### 4.1 `core/ai.py` — the only place that touches the Anthropic SDK

```python
import anthropic
from langsmith import traceable

MODEL = "claude-opus-4-8"          # one constant; never hardcode in agent code
client = anthropic.Anthropic()     # reads ANTHROPIC_API_KEY

@traceable(name="call_tool")
def call_tool(system: str, messages: list[dict], tool: dict, max_tokens: int = 2048) -> dict:
    """Force one strict tool call and return its validated input dict."""
    resp = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,                                  # stable constant → prompt-cacheable
        tools=[tool],                                   # tool defines strict:true itself
        tool_choice={"type": "tool", "name": tool["name"]},
        messages=messages,
    )
    block = next(b for b in resp.content if b.type == "tool_use")
    return block.input

@traceable(name="stream_reply")
def stream_reply(system: str, messages: list[dict], max_tokens: int = 2048):
    """Yield text deltas for SSE chat endpoints."""
    with client.messages.stream(
        model=MODEL, max_tokens=max_tokens, system=system, messages=messages,
    ) as stream:
        yield from stream.text_stream
```

Tool schema convention (used by every agent's `ai.py`):

```python
def strict_tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "name": name,
        "description": description,
        "strict": True,                                  # guaranteed-valid input
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }
```

### 4.2 `core/events.py` — the dispatcher (ORCHESTRATION §3 Stage 2)

```python
import logging
from collections import defaultdict
from core.models import EventLog

log = logging.getLogger("events")
_HANDLERS: dict[str, list] = defaultdict(list)

def subscribe(event_name: str):
    def register(fn):
        _HANDLERS[event_name].append(fn)
        return fn
    return register

def emit(event_name: str, **payload):
    entry = EventLog.objects.create(name=event_name, payload=payload)
    errors = []
    for handler in _HANDLERS[event_name]:
        try:
            handler(**payload)
        except Exception:                # one bad consumer never breaks the emitter
            log.exception("handler %s failed for %s", handler.__name__, event_name)
            errors.append(handler.__name__)
    entry.processed = True
    entry.error = ", ".join(errors) or ""
    entry.save(update_fields=["processed", "error"])
```

Usage — consumer side (`scheduling/apps.py`):

```python
class SchedulingConfig(AppConfig):
    name = "scheduling"
    def ready(self):
        from core.events import subscribe
        from scheduling import services

        @subscribe("priorauth.approved")
        def _book_approved_treatment(patient_id, order_id, **_):
            services.offer_booking_for_order(patient_id, order_id)
```

### 4.3 `core/notifications.py` — one door for every message

```python
from core.models import Patient, SentNotification

class ConsoleProvider:                       # dev; Twilio/SendGrid implement the same send()
    def send(self, channel, recipient, content) -> str:
        print(f"[{channel}] -> {recipient}: {content}")
        return "console-msg-id"

provider = ConsoleProvider()

def notify(patient: Patient, template: str, context: dict, channel: str | None = None) -> SentNotification | None:
    prefs = patient.communication_preferences or {}
    channel = channel or prefs.get("preferred_channel", "sms")
    if prefs.get("opted_out", {}).get(channel):          # NFR-8 enforced HERE, globally
        return None
    content = render_template(template, context, patient.preferred_language)
    n = SentNotification.objects.create(
        patient=patient, channel=channel,
        recipient=patient.phone if channel in ("sms", "voice", "whatsapp") else patient.email,
        template=template, rendered_content=content, status="queued",
    )
    n.provider_message_id = provider.send(channel, n.recipient, content)
    n.status = "sent"
    n.save()
    return n
```

### 4.4 SSE chat view pattern (used by Agents 1, 2, 3, 9)

```python
from django.http import StreamingHttpResponse

def chat_view(request):
    conversation, history = load_session(request)        # X-Session-Token
    def event_stream():
        for delta in handle_message_stream(conversation, history, request.data["message"]):
            yield f"data: {json.dumps({'delta': delta})}\n\n"
        yield "data: [DONE]\n\n"
    return StreamingHttpResponse(event_stream(), content_type="text/event-stream")
```

### 4.5 `AgentReply` — the conversational contract (ORCHESTRATION §4)

```python
from dataclasses import dataclass, field

@dataclass
class AgentReply:
    text: str                              # what the patient reads
    ui_hints: dict = field(default_factory=dict)   # {"slots": [...]} | {"otp_required": True} | {"upload": True} | {"status_card": {...}}
    followup_needed: bool = False          # agent expects another turn
    handoff: str | None = None             # intent name to re-dispatch, or None
```

Every conversational agent exposes `handle_message(conversation, history, text) -> AgentReply`.
