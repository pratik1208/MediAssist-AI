# Outreach Agent (Agent 7) — Campaigns

The outreach agent lets clinic staff run **proactive campaigns**: instead of waiting for
patients to call, the clinic picks a group of patients (a *cohort*), sends them a personalized
message ("time for your flu shot"), escalates through channels if they don't reply
(SMS → email → voice call), understands their replies with AI, and — when a patient says
"yes, book me" — schedules the appointment automatically.

Everything below is in plain English, in the order things actually happen.

---

## 1. The pieces (file map)

| File | What it does |
|---|---|
| `outreach/models.py` | The 4 database tables (Campaign, CampaignMember, OutboundMessage, InboundResponse) |
| `outreach/services.py` | All the business logic — cohorts, enrollment, waves, replies, auto-booking, stats |
| `outreach/ai.py` | The 2 AI tools — reply classification and message writing |
| `outreach/views.py` | The REST API (staff endpoints + the inbound webhook + generic CRUD) |
| `outreach/urls.py` | URL routes for everything above |
| `outreach/serializers.py` | Plain DRF model serializers for the CRUD endpoints |
| `outreach/management/commands/dispatch_campaign_waves.py` | The "daily cron" that escalates every running campaign |
| `outreach/management/commands/seed_campaigns.py` | 3 demo draft campaigns for testing |
| `outreach/tests/` | 115 fast tests + 26 live-AI tests (see §10) |
| Frontend: `frontend/src/pages/CampaignManagerPage.tsx` | Staff UI at `/staff/outreach` — list, create, preview, launch |
| Frontend: `frontend/src/pages/CampaignAnalyticsPage.tsx` | Per-campaign UI at `/staff/outreach/:id` — funnel, members, actions |

---

## 2. The data model

Four tables, all in `outreach/models.py`:

**Campaign** — one outreach program.
- `name`, `clinical_goal` (the human sentence the messages are built from)
- `cohort_criteria` (JSON — who to target, see §4)
- `channel_plan` (JSON — the escalation ladder, e.g.
  `[{"channel":"sms","wait_days":0},{"channel":"email","wait_days":3},{"channel":"voice","wait_days":7}]`)
- `status`: `draft → running ⇄ paused → completed`
- `schedule`, `launched_at`, `created_at`

**CampaignMember** — one patient inside one campaign (unique per campaign+patient).
- `state` — the per-patient funnel (see the state machine below)
- `snooze_until` — "ask me again after this date"
- `channel_attempts` — JSON log of every contact try: `[{"channel","at","message_id"}, ...]`
  (`message_id` is the **SentNotification** id in core, i.e. the actual sent message record)
- `outreach_reason` — why this patient is being contacted (shown on the staff list, FR-O3)
- `assigned_physician` — optional doctor to book with

**OutboundMessage** — links a member to the `core.SentNotification` that was actually sent,
plus which `wave_number` (escalation step) it belonged to.

**InboundResponse** — a raw patient reply: `raw_text`, the `classified_intent`
(`book / snooze / opt_out / question / unclear`), optional `snooze_until`, and `handled`.

Foreign-key rules follow SCHEMA.md: `patient` is **PROTECT** (outreach history must never
silently vanish), `assigned_physician` is **SET_NULL**, and child rows
(members/messages/responses) **CASCADE** — delete a campaign and its children go with it.

### Member state machine

```
identified ──wave sent──▶ contacted ──reply──▶ responded / snoozed / opted_out / scheduled
     │                        │
     └──── plan exhausted ────┴──▶ unreachable          scheduled ──visit done──▶ completed
```

- `identified` — enrolled, nothing sent yet
- `contacted` — at least one message went out
- `responded` — replied, but needs a human (question / unclear / booking fell through)
- `scheduled` — appointment auto-booked ✅ (this is the conversion the funnel counts)
- `snoozed` — "contact me later"; waves skip them until `snooze_until` passes
- `opted_out` — never contact again (also flips their global preferences, see §7)
- `unreachable` — every channel in the plan was tried, no reply

---

## 3. Step-by-step: the life of a campaign

### Step 1 — Staff creates a draft
`POST /api/staff/outreach/` with `{name, clinical_goal, cohort_criteria, channel_plan}`.
Validation is strict *up front*: an unknown criteria key, a bad channel name, or a negative
`wait_days` is a 400 **here**, not a surprise at launch time.

### Step 2 — Staff previews the cohort
`POST /api/staff/outreach/preview-cohort/` with just `{cohort_criteria}` returns
`{count, sample}` (first 10 matching patients). It's stateless on purpose — the UI can
preview while the staff member is still composing, before any campaign row exists.

### Step 3 — Launch
`POST /api/staff/outreach/{id}/launch/` does three things in one go:
1. flips the campaign `draft → running` and stamps `launched_at`,
2. **enrolls the cohort** (`services.enroll_cohort`) — bulk-creates a CampaignMember for every
   matching patient, skipping anyone already enrolled and anyone who has opted out of *every*
   channel. It's 2 SELECTs + 1 bulk INSERT — never a per-patient query (NFR-9, built for
   thousands of patients),
3. **dispatches wave 0** immediately (the first plan step is normally `wait_days: 0`).

Launching a *paused* campaign just resumes it (`paused → running`) **without re-enrolling** —
resuming shouldn't quietly pull in patients who newly match the criteria.

### Step 4 — Waves escalate over the following days
`services.dispatch_wave(campaign)` is the heart of escalation. For every member still in
`identified`/`contacted` (and not currently snoozed):
- The number of attempts already logged tells us which plan step they're on.
- If enough days have passed since the last attempt (`wait_days`), send the next channel's
  message via `core.notifications.notify()`.
- If the patient has opted out of *that* channel, `notify()` returns nothing — a message-less
  attempt is still recorded, so escalation **moves on to the next channel** instead of
  retrying a blocked one forever.
- A member who exhausts the whole plan becomes `unreachable`.

This runs two ways:
- automatically for **all** running campaigns:
  `./venv/bin/python manage.py dispatch_campaign_waves` (this is the daily cron job —
  a 5,000-patient escalation pass is background work, never a staff click),
- manually for one campaign: `POST /api/staff/outreach/{id}/dispatch-wave/` (a staff button).

### Step 5 — The patient replies
Replies land on the **webhook**: `POST /api/outreach/webhook/` (unauthenticated — a real
SMS/email provider posts here with its own signature scheme, not a staff session).

Body: `{"from": "<phone>", "text": "..."}` the way a provider sends it, or
`{"member_id": N, "text": "..."}` for precise dev testing. A phone number resolves to that
patient's most recently contacted active membership in a running campaign.

Every reply is stored as an `InboundResponse`, then understood in this order:

1. **Hard-stop keywords first, no AI.** If the whole message is `STOP`, `UNSUBSCRIBE`,
   `CANCEL`, `END`, `QUIT`, or `STOPALL` (standard SMS-compliance keywords), it's an opt-out
   — period. Opt-out compliance must never depend on an LLM being reachable. It's an exact
   whole-message match, so "please don't stop asking" does NOT trip it.
2. **Otherwise the AI classifier** (`outreach/ai.py::classify_response`) reads the text and
   returns one intent: `book / snooze / opt_out / question / unclear`, plus a resolved
   `snooze_until` date for snoozes ("after Diwali" → an actual date).
3. **Code decides, model only states** (house AI pattern): if the AI fails, or claims
   "snooze" without a date it could actually resolve, the intent falls back to `unclear` —
   the one intent with zero side effects. Nothing is ever guessed.
4. An explicit `"intent"` in the webhook body **bypasses the classifier entirely** —
   dev/testing use this for deterministic control over exactly which branch runs.

### Step 6 — The intent runs the state machine (`handle_response_action`)

| Intent | What happens |
|---|---|
| `book` | **Auto-book (FR-O6):** find a doctor (assigned physician → any active General Medicine doctor → any active doctor), find the first open slot in the next 14 days via Agent 1's `scheduling.services`, and book it with `source="outreach"`. Success → member `scheduled` + audit entry. If no doctor/slot → member `responded` + an `outreach.booking_requested` event is emitted so staff can finish the job. Booking problems never raise — a scheduling hiccup must not break reply handling. |
| `snooze` | Member `snoozed`, `snooze_until` saved; waves skip them until that date. Requires a date (400 without one). |
| `opt_out` | Member `opted_out`, **and** the patient's global `communication_preferences` are set to `false` for all four channels — so *every* agent in the system stops messaging them (NFR-8), not just this campaign. Audited. |
| `question` / `unclear` | Member `responded` — a human decides. (Once the After-Hours agent exists, `question` routes into chat; until then staff query `state=responded` + unhandled responses.) |

### Step 7 — Staff watches the funnel
`GET /api/staff/outreach/{id}/stats/` returns the FR-O7 funnel:
`identified → sent → delivered → responded → scheduled → completed`, plus
`conversion_rate` (scheduled ÷ sent) and a `by_channel` breakdown of messages sent.
The detail endpoint (`GET /api/staff/outreach/{id}/`) includes the same stats inline;
the analytics page polls the stats endpoint on its own.

---

## 4. Cohort criteria reference (`build_cohort`)

`cohort_criteria` is a JSON object. **Unknown keys are rejected loudly**
(`UnsupportedCriteriaError` → API 400) — never silently ignored. Supported keys:

| Key | Meaning |
|---|---|
| `age_min` / `age_max` | Age band, computed from `dob`, leap-year-safe (a Feb-29 birthday is handled) |
| `months_since_last_visit_gte` | Last **completed** appointment is at least N months ago — patients with *no* visits at all also match (they're the most overdue of all) |
| `missed_appointments_gte` | At least N `no_show` appointments |
| `preferred_language_in` | Patient's preferred language is in the list |
| `exclude_patient_ids` | Explicit exclusions |
| `has_diagnosis_code` | Has a diagnosis `ClinicalEvent` with this code (added by Agent 8, e.g. `E11` = diabetes) |
| `has_event_code` | Has any `ClinicalEvent` with this code (e.g. a hospital discharge) |

Criteria combine with AND. Example: `{"age_min": 65, "months_since_last_visit_gte": 12}` =
"seniors overdue for a visit."

`build_cohort` is deliberately shared — Agent 8 (care gaps) imports it for its guideline
population criteria, and contributed the two clinical-event keys above.

---

## 5. AI integration (`outreach/ai.py`)

Two tools, both following the house pattern (`strict_tool`/`call_tool` from `core.ai`,
`@traceable` for tracing, JSON-schema-validated output):

1. **`classify_response(text, today)`** → `{intent, snooze_until?}`.
   Gets today's date so it can resolve relative phrases ("next month", "after the 15th")
   into real dates.
2. **`render_outreach_message_body(clinical_goal, language)`** → `{body}`.
   Writes one friendly, SMS-length message body in the patient's preferred language for the
   campaign's clinical goal.

**Cost & scale discipline (NFR-9):** message bodies are cached per
`(language, clinical_goal)` — a 5,000-patient wave makes at most a handful of AI calls
(one per language actually present in the cohort), never one per patient. The final text is
just `"Hi {first_name}, " + cached body`.

**Failure discipline:** the AI is never allowed to block outreach.
- Message rendering fails → a plain non-AI fallback wording is used
  ("<goal>. Reply to let us know… Reply STOP to opt out.").
- Classification fails → intent `unclear` (no side effects, human follows up).
- Opt-out keywords are checked **before** the AI ever runs (see §3 step 5).

---

## 6. API reference (`outreach/urls.py`)

Staff endpoints require an **admin/staff login** (same convention as the other agents).
The webhook is open. The generic CRUD routes are a dev/admin convenience.

| Method + path | Auth | What it does |
|---|---|---|
| `GET /api/staff/outreach/` | staff | List campaigns (optional `?status=`) |
| `POST /api/staff/outreach/` | staff | Create a draft (validates criteria + channel plan) |
| `POST /api/staff/outreach/preview-cohort/` | staff | `{cohort_criteria}` → `{count, sample}` |
| `GET /api/staff/outreach/{id}/` | staff | Campaign summary + live funnel stats |
| `POST /api/staff/outreach/{id}/launch/` | staff | Draft → running (enroll + wave 0); paused → running (resume, no re-enroll) |
| `POST /api/staff/outreach/{id}/pause/` | staff | Running → paused (waves skip it) |
| `GET /api/staff/outreach/{id}/stats/` | staff | Funnel only (the analytics page polls this) |
| `POST /api/staff/outreach/{id}/dispatch-wave/` | staff | Manual escalation pass for one campaign |
| `GET /api/staff/outreach/{id}/members/` | staff | The outreach list (FR-O3): name, contact, reason, language, attempts, physician; optional `?state=` |
| `POST /api/outreach/webhook/` | **open** | Where replies land (see §3 step 5) |
| `GET/POST /api/campaign`, `GET/PATCH/PUT/DELETE /api/campaign/{id}` | open (dev) | Generic CRUD |
| same for `/api/campaignmember`, `/api/outboundmessage`, `/api/inboundresponse` | open (dev) | Generic CRUD |

Lifecycle rules the API enforces (each returns a clear 400):
you can't launch a running campaign, pause a draft or an already-paused campaign, or
dispatch waves for anything that isn't running.

---

## 7. Safety rules (the non-negotiables)

- **Opt-out is global and absolute (NFR-8).** All outbound goes through the single door
  `core.notifications.notify()`, which checks the patient's channel preferences on *every*
  send. An outreach opt-out flips all four channels to `false` on the Patient record itself,
  silencing every agent.
- **Fully-opted-out patients are never even enrolled.** `enroll_cohort` excludes them with a
  single JSONB containment check (`communication_preferences @> {all four channels: false}`).
- **Opt-out keywords beat the AI.** `STOP` etc. are handled deterministically before any
  model call.
- **The AI never blocks and never decides alone.** Every AI failure has a safe fallback
  (plain wording / `unclear`); every AI answer is schema-validated and then re-checked by
  code before it has side effects.
- **Auto-booking never breaks reply handling.** Any booking failure degrades to
  `responded` + an event for staff.
- **Sensitive actions are audited**: opt-outs and auto-booked appointments write audit
  entries via `core`'s audit helper.

---

## 8. Frontend (staff UI)

- **`/staff/outreach` — Campaign Manager.** Campaign list with status chips, a create form
  (criteria builder + channel plan), and live cohort preview before anything is saved.
- **`/staff/outreach/:id` — Campaign Analytics.** The funnel (identified → sent → responded →
  scheduled → completed, conversion rate, per-channel counts), the member list with state
  filtering, and action buttons: Launch / Pause / Resume / Dispatch wave, plus a
  "simulate reply" box that posts to the webhook — the full demo loop without a real
  SMS provider.

In dev, Vite proxies `/api` to the backend (port 8001 by default; set `BACKEND_URL` to point
elsewhere).

---

## 9. Cross-agent connections

- **Agent 1 (Scheduling):** auto-booking calls `scheduling.services.find_available_slots` +
  `book_appointment(source="outreach")` directly — the same shared booking door referrals
  use. Slots are fixed 20-minute blocks inside each doctor's `working_hours`.
- **Core notifications:** all sends go through `notify()`; each successful send creates a
  `core.SentNotification`, which `OutboundMessage` links back to.
- **Events:** emits `outreach.booking_requested` (a "book" reply that could not be
  auto-booked) via `core.events.emit()` — subscribers can't break the emitter (one bad
  handler is caught and logged).
- **Agent 8 (future):** `build_cohort` is the shared criteria engine care gaps will reuse.

---

## 10. Testing

```bash
# fast suite (AI is mocked; the conftest blocks real model calls)
./venv/bin/python -m pytest outreach/ -q          # 115 tests

# live AI tests (real OpenAI calls; excluded by default via pytest.ini)
./venv/bin/python -m pytest outreach/ -m live_model  # 26 tests
```

- `tests/conftest.py` blocks `outreach.ai.call_tool` for the whole suite (no accidental paid
  calls) and clears the per-language message cache between tests.
- `test_models.py`, `test_services.py`, `test_api.py`, `test_ai.py`, `test_integration.py`
  cover the models, every service branch, every endpoint, the AI plumbing, and the
  end-to-end flows. The outreach modules sit at **100% statement and branch coverage**.
- `test_classify_response_live.py` runs the real classifier against tricky phrasings
  (8 different ways of saying "stop texting me" all classify as opt-out).

The full API surface was also verified live against a running server: every endpoint,
every validation error, the full lifecycle (draft → launch → escalate → replies → pause →
resume), all five reply intents including a real AI classification, and cascade delete.

---

## 11. Demo data & useful commands

```bash
./venv/bin/python manage.py seed_all                 # bootstrap the whole clinic
./venv/bin/python manage.py seed_campaigns           # just the 3 demo draft campaigns
./venv/bin/python manage.py dispatch_campaign_waves  # the daily escalation pass ("cron")
```

`seed_all` gives you 30 curated patients whose ages, languages, visit history, and no-show
history deliberately land in and out of every cohort criterion, plus 3 draft campaigns
("Flu shot 65+", "Overdue annual check-up", "Missed-appointment follow-up") ready to
preview → launch → simulate a reply at `/staff/outreach`. Re-seeding never resets a campaign
a user has already launched back to draft.

**Not wired up yet (Phase 7 / deploy):** a real scheduler calling
`dispatch_campaign_waves` daily, and real SMS/email/voice providers (Twilio, SendGrid, …)
behind `core.notifications` — in dev, sends are recorded as `SentNotification` rows instead
of leaving the machine.
