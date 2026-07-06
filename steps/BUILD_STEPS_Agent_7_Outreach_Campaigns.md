# BUILD_STEPS_Agent_7

# BUILD_STEPS — MediAssist AI: Outreach Campaigns

Covers PRD → "Outreach Campaigns" (FR-O1…FR-O7). A *population-scale batch* agent: cohort queries, message fan-out, and response handling. NFR-9 says design for cohorts of 3,500–5,000 patients — so everything here is bulk queries and queued sends, never per-patient loops of synchronous work.

**Prerequisites:** Agents 1–2 (books appointments from replies; needs patient contact/language/channel preferences). Extend `core.Patient` with `communication_preferences` (preferred channel, opted_out flags per channel) if not already present.

## Phase 1 — Data models

- [ ]  `python manage.py startapp outreach`; add to `INSTALLED_APPS`
- [ ]  Models: `Campaign` (name, clinical goal, cohort criteria JSON, channel escalation plan JSON e.g. `["sms", "email", "voice"]`, status — `draft` / `running` / `paused` / `completed`, schedule), `CampaignMember` (FK → Campaign + Patient; state — `identified` / `contacted` / `responded` / `scheduled` / `completed` / `snoozed` / `opted_out` / `unreachable`; snooze_until; channel attempts JSON), `OutboundMessage` (FK → CampaignMember; channel, template, rendered content, status — `queued` / `sent` / `delivered` / `failed`, provider message id), `InboundResponse` (FK → CampaignMember; raw text, classified intent, handled bool)
- [ ]  `makemigrations && migrate`; admin (make `Campaign` nicely editable — it's a real staff surface until the dashboard exists)

## Phase 2 — Core business logic (no AI yet)

`outreach/services.py`:

- [ ]  `build_cohort(criteria)` — translate a **criteria JSON** (age range, condition codes, lab thresholds like HbA1c > 8, months since last visit, vaccination status, missed appointments) into a Django queryset (FR-O1/O2). Define the criteria schema yourself and validate it — this same engine gets reused by Agent 8, so keep it in a shareable module
- [ ]  `enroll_cohort(campaign)` — bulk-create `CampaignMember`s with the outreach-list fields (name, contact, reason, language, channel, assigned physician — FR-O3); EXCLUDE already-opted-out patients at enrollment time
- [ ]  `dispatch_wave(campaign)` — queue `OutboundMessage`s for members due for their next attempt, honoring the channel escalation plan: non-responders move to the next channel after N days (FR-O4, PRD Edge Case 15). Send via the shared notification service (see `ORCHESTRATION.md`) — console/log stub in dev
- [ ]  `handle_response_action(member, intent)` — state machine: `book` → hand off to Scheduling; `snooze(date)` → pause until date (Edge Case 14); `opt_out` → record + update `core.Patient.communication_preferences` so ALL modules honor it (FR-O5, NFR-8, Edge Case 13)
- [ ]  `campaign_stats(campaign)` — funnel counts: identified → sent → delivered → responded → scheduled → completed, conversion rate (FR-O7)
- [ ]  Tests: criteria → queryset correctness on fixtures, opt-out excluded from every later wave, escalation timing, snooze resume, funnel math. Test `build_cohort` with 5,000 fixture patients to confirm it's one query, not N. `pytest` green.

## Phase 3 — API layer

- [ ]  Staff endpoints: create campaign (criteria + channels), preview cohort (count + sample before launching!), launch, pause, stats
- [ ]  Inbound webhook endpoint: where SMS/email replies land (in dev, a simple POST you curl manually)

## Phase 4 — AI integration

- [ ]  `classify_response(text)` — the core AI task: patient reply → `strict: true` tool output `intent` (`book` / `snooze` / `opt_out` / `question` / `unclear`), `snooze_until` if stated ("remind me next month"), `question_text`. Feeds `handle_response_action`
- [ ]  `render_message(member, template_goal)` — generate the per-patient message in their preferred language from the campaign goal + patient context; cache per (language, template) where personalization is light — don't make 5,000 identical API calls
- [ ]  `question` intents route into the normal chat flow (After-Hours agent once it exists; until then, staff task)
- [ ]  LangSmith tracing
- [ ]  Test suite: 20+ real-world reply phrasings ("yes ok", "stop texting me", "can't till after the 15th", "what is this about?") classify correctly — misclassifying an opt-out as anything else is the failure mode to guard hardest against

## Phase 5 — Frontend

- [ ]  Campaign manager page (PRD Screens #7): criteria builder form (start with a JSON textarea + cohort preview count; a pretty query builder is polish), channel plan, launch button
- [ ]  Campaign analytics dashboard: live funnel (identified → sent → delivered → responded → scheduled → completed), conversion, per-channel breakdown
- [ ]  Manual E2E: define flu-shot-65+ campaign on fixtures → preview → launch → simulate an SMS reply via the webhook → member books through Scheduling → funnel updates (PRD "Proactive outreach" journey)

## Phase 6 — Integration + edge cases

- [ ]  Booking handoff creates a real appointment via Agent 1 (FR-O6) and advances member state on confirmation
- [ ]  Opt-out propagation test: an opted-out patient is excluded from reminders in Scheduling and future campaigns (NFR-8 is cross-module)
- [ ]  Edge-case tests: PRD Edge Cases 13, 14, 15
- [ ]  Wave dispatch as a scheduled job (daily), not a request-triggered action

## Phase 7 — Deploy

- [ ]  Migrate + deploy; schedule the wave dispatcher
- [ ]  Later swap-ins: Twilio SMS + programmable voice, SendGrid email, WhatsApp Business API — all behind the shared notification service so campaign code doesn't change
