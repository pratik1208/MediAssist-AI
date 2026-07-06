# ORCHESTRATION — How the MediAssist AI agents work together

The BUILD_STEPS docs tell you how to build each agent in isolation. This document is the glue: the shared plumbing every agent uses, how agents hand work to each other, and the order + checkpoints for assembling the whole platform on your own. Read it once before starting Agent 2, and revisit its checklist at the end of every agent.

## 1. The architecture in one picture

```
                        ┌──────────────────────────────────────────┐
 Patient (any channel)  │  Agent 9: After-Hours / Front Desk       │
 ──────────────────────▶│  auth → intent router → agent registry   │
                        └───────┬──────────────────────────────────┘
                                │ dispatches intents to
        ┌────────────┬──────────┼───────────┬─────────────┐
        ▼            ▼          ▼           ▼             ▼
   Registration   Triage    Scheduling   Refills    "status" queries
     (A2)          (A3)       (A1)        (A4)      (A5/A6 lookups)
        │            │          ▲            │
        │ completed  │ disposition           │ visit needed
        ▼            ▼          │            ▼
   ┌─────────────────────────────────────────────────┐
   │              EVENT DISPATCHER (§3)              │
   └─────────────────────────────────────────────────┘
        ▲            ▲          ▲            ▲
        │            │          │            │
    Referrals(A5)  PriorAuth(A6)  Outreach(A7)  CareGaps(A8)
        └── priorauth.needed ──▶ A6 ── approved ──▶ A1 books
   A8 detects gaps ──▶ A7 sends campaigns ──▶ A1 books ──▶ A8 closes

   Shared services (§2): core models · notifications · EHR write layer ·
   identity/OTP · red-flag check · audit trail
```

Two kinds of orchestration exist in this system — don't confuse them:

1. **Conversational orchestration (synchronous):** one patient message may need several agents *right now*. Agent 9 owns this: classify intents, call each agent's handler, merge replies.
2. **Workflow orchestration (asynchronous):** one agent finishing its job triggers another agent later (registration completes → scheduling offers booking; referral needs auth → PA agent starts). The event dispatcher (§3) owns this.

## 2. Shared services — build once, in this order

These live in the `core` app (created in Agent 2, Phase 0). Every agent doc assumes they exist.

- [ ]  **Shared models** (`core/models.py`): `Patient`, `Doctor`, `Conversation`, `Message` — done in Agent 2 Phase 0
- [ ]  **Notification service** (`core/notifications.py`): one function `notify(patient_or_staff, channel, template, context)` behind an interface. Dev implementation writes to a `SentNotification` table + console. Twilio/SendGrid/WhatsApp are later drop-in implementations. EVERY agent sends through this — it's also where opt-outs and preferred channels are enforced globally (NFR-6, NFR-8), so no agent can accidentally message an opted-out patient
- [ ]  **EHR write layer** (`core/ehr.py`): the PRD requires every interaction written to the EHR via FHIR, but your EHR *is* Postgres for now. Still, route all clinical writes through named functions (`record_encounter`, `record_prescription`, `record_document`, `record_transcript`) instead of scattering `Model.objects.create` calls. When a real FHIR target appears, you change one module. This also gives you the audit trail (NFR-4) for free: have each function also append to an `AuditEvent` table (who/what/when/payload hash)
- [ ]  **Identity/verification** (`core/identity.py` — extracted from Agent 2): OTP creation/verification + "is this session verified?" check. Refills, front desk, and any patient-data disclosure reuse it (NFR-2)
- [ ]  **Red-flag safety check** (`core/safety.py` — extracted from Agent 3): the deterministic emergency keyword screen. Rule: **every agent that accepts free-text patient input calls this before its AI call.** That is PRD Edge Case 11 as an architectural invariant, not a per-agent feature
- [ ]  **AI client wrapper** (`core/ai.py`): one module that owns the Anthropic client, model name (`claude-opus-4-8` — one constant, never hardcoded per agent), LangSmith tracing, retry/error handling, and a helper `call_tool(system, messages, tool_schema)` that forces `tool_choice` and returns parsed input. Every agent's Phase 4 becomes "write schemas + prompts", not "re-plumb the SDK". Keep system prompts as stable constants and put volatile context in messages — that's what makes prompt caching work

## 3. The event dispatcher — asynchronous handoffs

Don't install Celery/Redis/Kafka on day one. Grow through three stages:

**Stage 1 (Agents 1–3): direct function calls.** `complete_registration()` simply imports and calls the scheduling handoff. Fine while there are two consumers.

**Stage 2 (from Agent 4 onward): an in-process dispatcher.** Build this when you start Agent 4 — it's ~50 lines:

- [ ]  `core/events.py`: `EVENT_HANDLERS: dict[str, list[callable]]`, `subscribe(event_name, handler)`, `emit(event_name, **payload)` which (a) writes an `EventLog` row (name, payload JSON, created_at, processed bool — your audit + replay + debugging tool) and (b) calls each subscriber in a try/except so one failing consumer never breaks the emitter
- [ ]  Each app registers its subscriptions in `apps.py` → `ready()`
- [ ]  Standard event names — keep this table current as you build:

| Event | Emitted by | Consumed by |
| --- | --- | --- |
| `registration.completed` | A2 | A1 (offer booking), A3 (if symptoms), A8 (initial scan) |
| `triage.disposition` | A3 | A1 / A5 / A4 / A6 / A8 per disposition |
| `appointment.booked` / `.cancelled` / `.completed` | A1 | A1 waitlist backfill; A5 status advance; A8 gap closure; A7 member state |
| `refill.visit_required` / `refill.approved` | A4 | A1 (book visit); notifications |
| `referral.created` / `.status_changed` | A5 | notifications; coordinator dashboard |
| `priorauth.needed` | A5/A3 | A6 (detection) |
| `priorauth.approved` / `.denied` | A6 | A1 (book treatment); notifications |
| `caregap.opened` / `.closed` | A8 | A7 (enroll in campaign); dashboards |
| `outreach.response_action` | A7 | A1 (book); A8 (snooze/opt-out state) |
| `escalation.created` | A3/A4/A9 | staff task queue; on-call notification |

**Stage 3 (when needed): real background workers.** When sends/scans get slow (Outreach waves, nightly gap scans), move `emit`'s consumer execution to Celery + Redis (or Django-Q / DB-backed queue). Because everything already goes through `emit()`, this is a swap, not a rewrite. Scheduled jobs you'll have accumulated by then: referral stall check (daily), PA status poll (hourly), outreach wave dispatch (daily), care-gap scan (nightly), recycle incomplete plans (weekly).

## 4. Conversational orchestration rules (Agent 9's contract)

For Agent 9 to route into an agent, each conversational agent must expose a uniform entry point. Enforce this convention from Agent 2 onward so nothing needs retrofitting:

- [ ]  Every conversational agent exposes `handle_message(conversation, history, context) -> AgentReply` where `AgentReply` = `{text, ui_hints (slots/OTP/upload/status card), followup_needed, handoff (intent or None)}`
- [ ]  Agents never talk to each other mid-conversation directly — they return a `handoff` and the caller (Agent 9, or the standalone chat view pre-Agent-9) re-dispatches. This keeps every route visible and logged
- [ ]  One `core.Conversation` spans the whole session even when multiple agents serve it — the transcript must read as one thread (FR-A8)
- [ ]  Multi-intent: Agent 9 dispatches intents sequentially in the order stated, collects each `AgentReply`, and merges into one response. If one intent needs interaction (e.g. slot choice), the others' confirmations still get delivered
- [ ]  Auth gate: the registry marks intents `requires_auth: true/false`. FAQ = false; anything patient-specific = true

## 5. Master build order and integration checkpoints

Build order (dependency-driven, matches the PRD matrix):

```
A1 Scheduling → A2 Registration (+core refactor) → A3 Triage   ← MVP
→ A4 Refills → A5 Referrals → A6 Prior Auth                    ← Phase 2
→ A7 Outreach → A8 Care Gaps → A9 After-Hours                  ← Phase 3
```

Stop and verify these cross-agent checkpoints — each is a PRD journey, and each must pass before you continue:

- [ ]  **Checkpoint 1 (after A3) — PRD primary journey:** new patient with chest pain: registers conversationally → identity + insurance verified → intake summary created → triage asks adaptive questions → non-emergency gets a cardiology slot booked; emergency phrasing gets the 911 script + on-call alert. Everything visible in admin with a full transcript
- [ ]  **Checkpoint 2 (after A6) — PRD referral journey:** PCP one-click referral → package built with only cardiology-relevant data → in-network specialist matched + booked → specialist orders MRI → PA auto-detected, evidence assembled, submitted to the simulator → info request auto-answered → approved → MRI scheduled → consultation report imported → loop closed
- [ ]  **Checkpoint 3 (after A8) — PRD outreach journey:** flu campaign for 65+ fixtures → cohort built → SMS wave → non-responders escalate to next channel → one reply books via Scheduling → one reply opts out and stays excluded everywhere → funnel dashboard correct; nightly gap scan opens/closes gaps through the same pipes
- [ ]  **Checkpoint 4 (after A9) — PRD after-hours journey:** 10:30 PM message "refill my blood pressure medicine and also schedule my annual checkup" → authenticate → both intents fulfilled → overdue cholesterol screening offered and added → confirmations sent → zero staff tasks created → automation-rate analytics reflect it

## 6. Cross-cutting invariants (test these continuously)

Keep a small `tests/test_invariants.py` at the project level and grow it as agents land:

- [ ]  No patient-specific data is ever returned on an unverified session (NFR-2)
- [ ]  Every free-text patient input path passes `core.safety.red_flag_check` before any AI call (Edge Case 11)
- [ ]  Every clinical action produces an `AuditEvent` + conversation transcript entry (NFR-4)
- [ ]  Opt-outs and preferred channels are honored by every sender (NFR-8) — one test that opts a patient out, then asserts zero sends from A1 reminders, A7 campaigns, A8 outreach
- [ ]  Booked-slot integrity holds under every caller: A1 direct, A5 specialist booking, A7 reply-booking, A8 plan booking all go through the same `book_appointment` (NFR-5)
- [ ]  Mental health crisis / stroke / insurance dispute / controlled substances ALWAYS create a human task, from any entry point (Edge Case 12)

## 7. Practical solo-developer notes

- One Django project, one Postgres, one deploy — nine apps. Resist microservices; the agent boundary is the app + its events, which is all the isolation you need at this scale.
- After every agent: commit, deploy, run the newest checkpoint on the live URL. Never let deployment drift more than one agent behind development.
- Keep every external dependency (payer, pharmacy, SMS, voice, FHIR) behind an interface with a simulator implementation — the PRD leaves all of them unspecified (see its Assumptions), so simulators are not a shortcut, they're the correct build.
- Prompt-regression suites (red-flag, router accuracy, opt-out classification) are your safety net: re-run them on every prompt or model change. They're cheap — a fixture list and an assertion loop.
- The PRD's analytics requirements (FR-R10, FR-T10, FR-O7, FR-G9, FR-A9) all reduce to aggregate queries over tables you already have. Build them as one `analytics` view module at the end of Phase 2/3 rather than polishing dashboards per agent.
