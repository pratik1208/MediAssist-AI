# BUILD_STEPS_Agent_9

# BUILD_STEPS — MediAssist AI: After-Hours Automation (24×7 Orchestration)

Covers PRD → "After-Hours Automation" (FR-A1…FR-A9). The "control tower": one entry point that authenticates, detects intent(s), and delegates to the specialized agents. **Build it last** — it orchestrates everything else, and by now each agent already exposes a `handle_*_message`-style entry point it can call.

**Prerequisites:** All of Agents 1–8 (it degrades gracefully if 7–8 aren't done — those intents just route to a staff task).

## Phase 1 — Data models

- [ ]  `python manage.py startapp frontdesk`; add to `INSTALLED_APPS`
- [ ]  Models: `Session` (FK → Patient nullable until authenticated; channel — web / portal / app / sms / whatsapp / voice; authenticated bool; FK → core.Conversation), `IntentRoute` (FK → Session; detected intent, target agent, status — `routed` / `completed` / `escalated`; one row per intent so multi-intent conversations are auditable), `KnowledgeArticle` (title, body, tags — clinic hours, locations, accepted insurance, prep instructions, billing FAQs; this is the RAG corpus), `StaffTask` (FK → Session; category, priority, summary, status — the "human needed" queue; reuse/extend Triage's `EscalationAlert` if you prefer one table)
- [ ]  `makemigrations && migrate`; admin; `seed_knowledge` command with ~15 articles

## Phase 2 — Core business logic (no AI yet)

`frontdesk/services.py`:

- [ ]  `authenticate_session(session, dob, otp)` — reuse Agent 2's OTP machinery; NO patient-specific data crosses this gate (FR-A3, NFR-2). Unauthenticated sessions can still get knowledge-base answers
- [ ]  The **agent registry**: a dict mapping intent → handler function (`appointment` → scheduling, `refill` → refills, `referral_status` → referrals, `pa_status` → priorauth, `care_gap` → caregaps, `symptoms` → triage, `faq` → knowledge base, `other` → staff task). This is the orchestration heart — keep it declarative so adding an agent is one line (FR-A2, FR-A4)
- [ ]  `search_knowledge(query)` — start with Postgres full-text search over `KnowledgeArticle` (SearchVector). That IS your retrieval layer; embeddings/pgvector are a later upgrade if quality demands it (FR-A5)
- [ ]  `create_staff_task(session, category, priority)` — mandatory-escalation categories hardcoded: mental health crisis, suspected stroke, complex insurance dispute, controlled-substance refill (FR-A7, PRD Edge Case 12)
- [ ]  Tests: registry dispatch, auth gate (patient-data intents blocked pre-auth, FAQ allowed), knowledge search relevance on fixtures, mandatory-escalation categories always create a task. `pytest` green.

## Phase 3 — API layer

- [ ]  `/api/frontdesk/chat/` — THE single omnichannel entry point (streaming, like Agent 1 Phase 7). Channel adapters (SMS/WhatsApp webhooks) normalize into the same handler later
- [ ]  Staff task queue endpoints (list, claim, resolve)

## Phase 4 — AI integration

- [ ]  Router tool schema `route_message` (`strict: true`): `intents[]` (array — a single message can carry multiple intents, FR-A2, PRD Edge Case 16), each with `intent` enum matching the registry + a `payload` summary; plus `emergency_symptoms_detected` (bool) and `mandatory_escalation_category` (nullable enum)
- [ ]  `handle_frontdesk_message(session, history)` — the orchestration loop:
    1. Run triage's `red_flag_check` on the raw text (deterministic, before any model call — FR-A6)
    2. Call the router with `tool_choice` forced to `route_message`
    3. Emergency → triage emergency script + on-call alert; mandatory category → `create_staff_task`
    4. Otherwise dispatch EACH intent through the registry sequentially, collecting each agent's reply into one coherent response ("I've sent your refill to Dr. Chen for approval, and here are slots for your checkup…")
    5. Unauthenticated + patient-specific intent → run the auth flow first, then resume the queued intents
- [ ]  FAQ answering: retrieved articles go into the prompt as context; instruct the model to answer ONLY from provided articles and hand off to a staff task when the answer isn't there — no improvised clinic facts
- [ ]  LangSmith tracing end to end (a routed conversation should appear as one trace with child calls)
- [ ]  Test suites: (a) router accuracy on 30+ fixture messages incl. multi-intent ("refill my BP meds and book my annual checkup" → BOTH intents, PRD after-hours journey); (b) red-flag phrases always hit the emergency path regardless of surrounding intents; (c) mandatory-escalation phrasings always create tasks; (d) FAQ answers stay grounded in articles

## Phase 5 — Frontend

- [ ]  Make the frontdesk chat the DEFAULT patient-facing conversation surface — registration/triage/scheduling/refill flows become destinations it routes into rather than separately-entered UIs
- [ ]  Auth step-up UI inside the chat (DOB + OTP) when a protected intent appears
- [ ]  Staff task queue page (reuse the Agent 3 escalation queue pattern; PRD Screens #8)
- [ ]  Manual E2E of the PRD "chronic patient, after hours" journey: authenticate → refill + checkup in one message → both fulfilled → care-gap add-on offered → confirmations sent → all documented, zero staff

## Phase 6 — Integration + edge cases

- [ ]  Every routed interaction writes back to the conversation/audit trail: transcript, actions taken, statuses checked, escalations (FR-A8, NFR-4)
- [ ]  Channel adapters: wire the Agent 7 inbound webhook so SMS/WhatsApp replies outside campaigns land here too (one front door for everything)
- [ ]  Analytics (FR-A9): volume, automation rate (resolved with zero staff tasks), escalation rate, avg response time, top request types
- [ ]  Edge-case tests: PRD Edge Cases 11, 12, 16

## Phase 7 — Deploy

- [ ]  Migrate + deploy; seed knowledge base in production
- [ ]  Full smoke-test of all three PRD journeys on the live URL — this is the acceptance test for the whole platform
- [ ]  Later: voice channel (telephony provider + speech-to-text feeding the same entry point), WhatsApp Business API
