# MediAssist AI — Interview Prep

How to explain the project, and the questions you should expect. Built from your resume bullet and the actual code/architecture in this repo (`AGENT_RELATIONSHIPS.md`, `TRIAGE_AGENT_FLOW.md`, `frontdesk/ai.py`, `core/safety.py`, `core/events.py`).

---

## 1. The one-line pitch (memorize this)

> "MediAssist AI is a multi-agent healthcare orchestration platform — 9 specialized LLM-driven agents that handle a patient's full journey (intake, scheduling, triage, refills, referrals, prior auth, outreach, care-gap closure, and a 24/7 after-hours front desk). The agents coordinate through an event bus and direct service calls, with FHIR-based EHR integration, across chat, SMS, and WhatsApp. The core design principle is *rules decide, the AI assists* — every safety-critical decision is deterministic, and the LLM can only escalate risk, never lower it."

That last sentence is your differentiator. Lead with it. It shows you thought about safety, not just wiring LLMs together.

## 2. The 60-second walkthrough (when they say "tell me about this project")

Structure it as **Problem → Architecture → Your design decisions → Impact**:

1. **Problem** — Clinics drown in repetitive coordination: booking, refill approvals, insurance prior-auth, chasing overdue screenings, after-hours calls. Each is a workflow with clinical-safety stakes, so you can't just drop a chatbot on it.

2. **Architecture** — 9 agents, each its own Django app with its own models and APIs. They talk two ways: (a) an **event bus** — an agent emits `"something.happened"`, it's persisted as an `EventLog` row, and subscribers react; used for "something finished, others may care." (b) **direct service calls** — when a caller needs an answer right now. The **front desk (agent 9)** is the hub: an AI intent-router classifies any patient message and dispatches through a registry to the right agent.

3. **Your key design decisions** — deterministic safety first (red-flag screen runs before any AI call), the AI can only raise acuity never lower it, and every agent is decoupled so the announcer doesn't know who's listening.

4. **Impact** — a new patient with "fever and headache" gets registered, triaged, and booked touching 6 agents without ever repeating themselves. Tie back to the resume metrics where relevant (the NL2SQL agent's 60% effort reduction / 85%+ accuracy is a separate but related WebMD project).

## 3. The worked example (have this ready — interviewers love a concrete trace)

New patient types "fever and headache", verifies OTP, gives insurance:

1. Registration finishes → emits `registration.completed`.
2. Scheduling hears it → sends "you can book now."
3. Triage hears it → pre-loads an assessment with "fever, headache" (red-flag check first — chest pain would escalate here instead).
4. UI auto-starts booking; symptoms flow to Scheduling's chat agent, which matches a doctor and offers slots.
5. Patient taps a slot → `appointment.booked` → confirmation sent.
6. Visit completed → `appointment.completed` → Care Gaps advances screenings and rescans.

Punchline: "Six agents, zero repeated questions — that's what the decoupled wiring buys you."

---

## 4. Questions you should expect, by category

### A. Architecture & "why multi-agent"

**Q: Why 9 separate agents instead of one big agent with many tools?**
Separation of concerns and blast radius. Each agent owns its domain models, APIs, and safety rules. A change to refill logic can't break triage. It also mirrors how a clinic is actually organized (front desk, nurses, referral coordinators), and lets each agent's prompt/tools stay small and testable. One giant agent would have an unwieldy prompt, tangled state, and no clean audit boundary.

**Q: Event bus vs. direct calls — how do you decide?**
Rule of thumb: *"something finished, others may care" → event bus; "I need data or an action right now" → direct call.* Booking completion fans out to multiple listeners (confirmation, care-gaps) → event. The front desk asking "what appointments does this patient have?" needs an answer synchronously → direct call.

**Q: What are the downsides of the event bus, and how do you handle them?**
Decoupling makes flow harder to trace and can create "dead" events (emitted but nobody subscribed). We handle traceability by persisting every emit as an `EventLog` row (permanent audit trail) and documenting every event/subscriber pair. We knowingly have a couple of dead routes (triage can hint `route_to="refills"` but refills never subscribed) — documented as deliberate future work rather than hidden.

**Q: How does adding a new agent work?**
Add its Django app + models, register subscribers in its `apps.py`, and add it to the front-desk `REGISTRY`. The router's intent enum is *derived* from the registry, so the router learns about the new agent automatically.

### B. Safety & reliability (this is where healthcare interviews get serious)

**Q: How do you stop the LLM from making an unsafe medical decision?**
Two independent deterministic layers, both before/around the AI: (1) a **red-flag keyword screen** (`core.safety.red_flag_check`) runs on every raw message *before any AI call* — chest pain, can't breathe, slurred speech, suicidal ideation → instant escalation, no further questions. (2) a **rules engine** computes acuity from a data-driven JSON rulebook (`ClinicalProtocol.disposition_rules`). The AI's opinion is folded in **last and only upward** — it can raise acuity, never lower it. So a hallucinating or over-reassuring model can't talk an emergency down to "self-care."

**Q: What if the AI router fails or times out?**
It degrades gracefully to a `manual_review` staff task — a router failure never blocks the patient. The FAQ answerer is constrained to answer *only* from retrieved knowledge articles; if they don't contain the answer, it says so and opens an `unanswered_question` staff task rather than improvising a clinic fact.

**Q: Red-flag screening is just keywords — isn't that brittle?**
It's intentionally deterministic as the *floor*, not the ceiling. The LLM router provides a second net (`emergency_symptoms_detected`) that can *add* escalations the keywords missed — but it's never allowed to *remove* one. Defense in depth: cheap deterministic check first, model as backup, never the reverse. Also, the keyword matcher isn't naive substring — it respects negation ("no fever" won't match "fever") and word order.

**Q: A patient says "mild headache" then later "my vision just went black" — what happens?**
Every answer, not just the first message, is re-run through the red-flag screen. They get escalated mid-interview, not after finishing the questionnaire.

### C. Deep dive on triage (your most technically interesting agent)

**Q: Walk me through one triage assessment end to end.**
(a) **Match** symptoms to a `ClinicalProtocol` via keyword matching that respects negation, word order, and prefixes; best match wins (most keywords, then longest). No match → tell the patient we couldn't classify rather than guess. (b) **Interview** — ask the protocol's ordered follow-ups one at a time; coerce free-text answers to typed values (`"104 F"→104`, `"2 years old"→24 months`, `"3 days"→72 hours`) so a protocol rule like `duration_hours >= 48` fires regardless of the unit the patient used. (c) **Score** — protocol red-flags first, then rules, then default; then patient-specific risk overrides (age, diabetes/cardiac/immunocompromised, blood thinners) that can only push acuity *up*; then the AI, also upward-only. (d) **Route** via `triage.disposition` to scheduling, referrals, or prior auth.

**Q: Why a JSON rulebook instead of hardcoding logic?**
Clinical protocols change and are owned by clinical staff, not engineers. A data-driven `disposition_rules` field lets a protocol author write a rule once and have it evaluated consistently, without a code deploy. Keeps medical logic auditable and out of Python.

### D. Front desk / orchestration

**Q: How does the front desk route a message that contains two requests?**
The router (`route_message`) returns an array of intents — "refill my BP meds and book my checkup" is two intents, each with its own summary payload. Code validates every intent against the registry before dispatching. Each dispatch still passes through the auth gate, so a protected intent from an anonymous caller is queued for verification.

**Q: How do you verify patient identity before showing personal data?**
The front desk reuses Registration's OTP functions (`create_otp`/`verify_otp`) — one identity mechanism, not reimplemented per agent.

**Q: An SMS comes in from an unknown number — what happens?**
If it doesn't match any outreach campaign it falls through to the front desk's `handle_channel_message` instead of being dropped.

### E. Data model & integration

**Q: How does FHIR fit in?** / **Q: How is EHR data represented?**
Be ready to point to `SCHEMA.md` and the per-agent models. Frame it as: patient demographics, insurance policies, intake summaries, clinical events, and care plans modeled as Django models, with FHIR as the interoperability layer for EHR sync. *(Skim `SCHEMA.md` before the interview so you can speak to specific tables — see the "prep gaps" note below.)*

**Q: How do agents share patient data without re-asking?**
Direct reads across app boundaries: triage reads Registration's `IntakeSummary`; referrals/prior-auth/refills read `InsurancePolicy`, `IntakeSummary`, `UploadedDocument`. Data lives with the agent that owns it; others read it directly.

### F. LLM engineering (they'll probe your resume skills: LangGraph, RAG, evals)

**Q: How do you keep the model's output structured/reliable?**
Tool-calling with strict schemas (`strict_tool`, `call_tool`), and the pattern "model states, code decides" — the model classifies/proposes, deterministic code validates against a registry/allowlist before any action. Traced with LangSmith (`@traceable`) for observability.

**Q: How would you evaluate these agents?**
Two tiers already exist: a fast test suite where AI calls are blocked (deterministic logic), and live-model safety suites (`pytest -m live_model`) that cost API credits and verify emergency paths. For deeper eval you'd add LLM-as-a-judge / RAGAS on the FAQ retrieval and router accuracy (skills on your resume — connect them).

**Q: The RAG / few-shot and NL2SQL bits on your resume — where are those?**
Be clear these are *related WebMD projects*, not this repo. Prescriber Lens (NL2SQL, LangGraph + BigQuery + ChromaDB few-shot retrieval + human-in-the-loop, 60% effort reduction, 85%+ accuracy) is a separate agent. Don't conflate them, but do connect the *patterns* (human-in-the-loop, retrieval-grounded generation, deterministic validation) that recur across both.

### G. Behavioral / ownership

- **"What was the hardest part?"** → Designing the safety model so the LLM genuinely *can't* cause harm (upward-only acuity, deterministic red-flags), while still using it for the fuzzy language work it's good at.
- **"What would you do differently / what's next?"** → Wire up the dead triage routes (refills/caregaps), add richer eval harnesses, and move from keyword red-flags toward a hybrid classifier while keeping the deterministic floor.
- **"What did *you* build vs. the team?"** → Have a crisp boundary ready. Your resume claims architecting the platform and designing triage + closed-loop referral/prior-auth agents — be ready to go deep on exactly those.

---

## 5. Traps to avoid

- **Don't oversell the AI.** The whole story's strength is that AI is *bounded*. If you say "the AI decides urgency," you've undercut your best design decision.
- **Don't conflate MediAssist AI with Prescriber Lens.** Different projects. Know which metric belongs to which.
- **Don't claim FHIR depth you can't back up.** If integration is lighter than "FHIR-based" implies, describe what's actually built and how FHIR would/does slot in. Interviewers dig here.
- **Have real numbers per agent.** 9 agents, 5 acuity levels (Emergency/High/Medium/Low/Minimal), 3 channels (chat/SMS/WhatsApp).

## 6. Prep gaps to close before the interview

1. Read `SCHEMA.md` so you can name specific models/tables and the FHIR mapping.
2. Re-read `TRIAGE_AGENT_FLOW.md` (your deep-dive agent) and one of the referral/prior-auth specs in `specifications/`.
3. Be able to state, in one sentence each, what *you personally* designed vs. inherited.
4. Rehearse the 60-second pitch and the worked example out loud until they're smooth.
