# MediAssist AI — Product Roadmap & Synthetic Data Plan

_Prepared 2026-07-14 · backend: Django 6 + DRF · frontend: React 19 + Vite · dev DB: Postgres_

Nine agents are built and tested end to end. This is what's actually left before this is a product —
and, separately, a detailed plan for building the synthetic patient dataset that everything below needs
in order to be tested at real scale.

## Current snapshot

| | |
|---|---|
| **830** | automated tests passing |
| **9** | agents built end to end |
| **37** | patients in the dev database — hand-curated, not load-test scale |
| **0** | real message channels wired — SMS / WhatsApp / email / voice all print to console |
| **`DEBUG=True`** | is the `settings.py` default — `SECRET_KEY` also ships hardcoded |
| **none** | CI pipeline or Dockerfile yet |

---

## Part 1 — Product roadmap

This is organized as workstreams (tracks), not one linear list — two of them turn on a decision only you
can make, so forcing a single order would be dishonest. Each track says what's already true in the
codebase today and what changes. A recommended sequence closes out the section.

### Track A — Finish what's already scoped

Agent 9 (the after-hours front desk) has three phases left in your own build doc, and Agent 8 has one.
None of this is new design work — it's already broken down.

- **Agent 9 Phase 5 (frontend):** make the front-desk chat the default patient-facing surface, with the
  auth step-up (DOB + OTP) built into the chat itself, and a staff task queue page reusing the Agent 3
  escalation-queue pattern you already have.
- **Agent 9 Phase 6 (integration):** wire Agent 7's inbound SMS/WhatsApp webhook into the same
  front-desk handler, so a reply outside a campaign lands in the one front door too — plus the FR-A9
  analytics (automation rate, escalation rate, average response time).
- **Agent 9 Phase 7 + Agent 8 Phase 7 (deploy):** migrate, deploy, seed the knowledge base — whatever
  "production" ends up meaning after Track E below.

> **Why first:** it's lower-risk than everything else on this page — the design decisions are already
> made, you're just building against a spec you wrote.

### Track B — Make it actually send a message

This is the real gap. `core/notifications.py`'s `ConsoleProvider` just prints every message to the
console — no patient has ever received a real SMS, WhatsApp message, email, or call out of this system.
Nothing above is a "product" until this changes.

- Swap in real providers behind the existing `provider.send(channel, recipient, content)` interface —
  every call site (registration OTPs, outreach waves, on-call pages) stays untouched.
- **SMS:** an India-first aggregator (Gupshup, Kaleyra, Exotel) rather than Twilio alone — see the
  regulatory note below.
- **WhatsApp:** the WhatsApp Business API (via Gupshup, or Meta's Cloud API directly). This changes how
  Agent 7's AI-written outreach messages get sent — anything outside a 24-hour customer-initiated window
  has to be a pre-approved template, not freeform model output.
- **Email:** SendGrid, Postmark, or Amazon SES. The abandoned Anymail attempt in the repo (commit
  `b76ec42`) was heading here and is worth finishing — Anymail already abstracts several providers
  behind one Django-native API.
- **Voice:** Exotel or Twilio Voice, for `notify_on_call`'s on-call page in triage and the front desk's
  emergency path.
- Add delivery status webhooks so `SentNotification.status` reflects reality (delivered / failed /
  bounced, not just "sent"), plus retry-with-backoff on transient failures.

> **India-specific:** TRAI requires **DLT (Distributed Ledger Technology) registration** before any
> commercial SMS sender can legally send transactional or promotional SMS in India — your templates have
> to be pre-registered. WhatsApp Business API similarly requires **template pre-approval** for any
> message sent outside a 24-hour window opened by the patient — which covers nearly all of Agent 7's
> proactive outreach, not just edge cases.

### Track C — Security & compliance hardening

Nothing here is exotic — it's the standard list, but it's currently all in the "not done yet" state, and
some of it is a genuinely quick fix.

- `SECRET_KEY` is hardcoded in `settings.py` with an "insecure" placeholder value — move to env-only,
  generate a real one, rotate it, never commit it again.
- `DEBUG = True` is the hardcoded default, and `ALLOWED_HOSTS` / `CORS_ALLOWED_ORIGINS` are empty lists.
  Fine for a laptop; these need real, environment-driven values before anything is reachable from
  outside your machine.
- The dev OTP shortcut (`123456` under `DEBUG=True`) is already gated correctly by design — add a
  second, explicit `ENVIRONMENT != "production"` check as a belt-and-suspenders guard, since a
  misconfigured `DEBUG` flag in prod shouldn't be the only thing standing between the real world and a
  universal OTP.
- Staff access is currently one `is_staff` boolean. A real product needs actual roles — front-desk,
  clinician, admin — so a receptionist can't open clinical notes and a nurse can't resolve an insurance
  dispute.
- Move secrets out of the plain `.env` file and into a real secrets manager (Doppler, or your deployment
  platform's own secret store) once Track E gives you a real target to deploy to.

> **India-specific:** the relevant law is India's **DPDP Act, 2023** (Digital Personal Data Protection
> Act) — not HIPAA. It requires explicit, informed patient consent for processing, a documented purpose
> for every use of personal data, and breach notification, with data-localization rules still evolving.
> Worth a short compliance review before any real patient's data touches this system.

### Track D — One clinic, or many?

This is a decision, not a task — and it changes what "onboarding" means in Track G, so it's worth
settling before you go much further.

> **Open question:** Everything built so far assumes **one clinic**. If the plan is to run MediAssist
> for just this one clinic, skip this track entirely — the rest of the roadmap holds exactly as-is.
>
> If the plan is to **sell this to multiple clinics**, you need a `Clinic`/`Tenant` model and every
> query — patients, appointments, staff tasks, knowledge articles, campaigns — scoped to it. That's a
> schema change threaded through every agent, not a bolt-on, so it's much cheaper to decide now than to
> retrofit after Track G.

### Track E — Observability & ops

Right now "staging" and "your laptop on port 8002" are the same environment. This track is what makes
that stop being true.

- Structured logging plus an error tracker (Sentry is the low-effort standard choice) — right now
  failures surface only as `log.exception` calls in whichever terminal happens to be running the server.
- **CI:** a GitHub Actions workflow running `pytest`, `manage.py check`, and the migration-drift check on
  every PR. You already run this exact trio by hand after every phase — automating it costs an afternoon
  and catches regressions before they reach the seeded dev database.
- A `Dockerfile` + `docker-compose.yml` (Django + Postgres), so this stops being reproducible only on one
  machine.
- A real deployment target (Railway or Render for a fast start; AWS/GCP if you need more control) and a
  staging environment that actually mirrors production.
- Postgres backups with a documented, *tested* restore drill — non-negotiable the day a real patient's
  data lands in this database.

### Track F — Frontend polish & product surface

Agent 9 Phase 5 (Track A) already covers making the chat the default patient-facing surface. This track
is the polish pass that comes after that's working end to end.

- Accessibility on the auth step-up form especially — it's the one place a screen-reader user must never
  get stuck between "anonymous" and "verified."
- Mobile layout for the chat and the staff console.
- A single consistent shell for the staff/admin console — the caregaps dashboard, staff queues, and
  escalation lists have grown organically across four separate agents and would benefit from one shared
  frame now that the pieces all exist.

### Track G — Business layer — only if you're selling this

Skip this entirely if MediAssist is staying in-house for one clinic.

- An onboarding flow for a new clinic: branding, WhatsApp Business number linking, staff accounts,
  initial knowledge-base seeding.
- Billing/subscription, if this becomes a SaaS product.
- Terms of service, a real privacy policy, and patient-facing consent language — this ties directly back
  to the DPDP Act work in Track C.
- A support runbook for whoever is on call when the emergency page from Track B actually fires at 2 a.m.

### Recommended sequence

Unlike the tracks above, this part really is an order — each step assumes the previous one is done.

1. **Track C's non-negotiables first** — `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`. Minutes of work that
   prevents the worst possible outcome.
2. **Track A** to close out the build docs — you're most of the way there and it's already designed.
3. **Track B** — nothing else on this page matters if no patient ever receives a real message.
4. **Answer Track D**, then pick E/F/G based on the answer: a single clinic needs E before G; a
   multi-clinic product needs G running alongside E.

---

## Part 2 — Synthetic data plan

Your 37 hand-curated patients are great deterministic test fixtures — several tests depend on their
exact values, and that's a feature, not a problem to fix. But they're not enough once you're validating
a product: load-testing the caregaps scanner and the outreach cohort engine needs real volume, and the
router-accuracy tests need more variety than 30 curated messages can cover. Here's the concrete build
order.

### 1. Write the population spec before writing any code

Decide the numbers on paper first — it's the difference between a generator that produces a believable
clinic and one that produces random noise that happens to satisfy field types.

- **Scale:** 2,000–5,000 patients for a realistic single-clinic dataset — enough to stress-test queries
  and get statistically meaningful gap/no-show rates. 10x that if Track D above lands on multi-clinic.
- **Demographics:** age/gender spread and all 10 `preferred_language` codes, weighted for a Pune clinic
  (en/hi/mr heavier, the rest present but thin) rather than uniform.
- **Clinical prevalence:** reflect real urban-India rates (roughly 10–20% hypertension/diabetes
  prevalence in the 40+ bracket) instead of uniform randomness, so care-gap and refill logic gets
  exercised the way it would in a real chart mix.
- **Payer mix:** a self-pay vs. insured ratio matching the providers already in your seeded `PayerRule`
  table.

### 2. Build a parametric generator — not a bigger hand-curated seed

- Keep `seed_patients.py`'s curated 30 exactly as they are; several tests depend on their specific
  values. Add a separate command — `generate_synthetic_population --count 3000 --seed 42` — so test
  determinism and synthetic volume never fight each other.
- Use Faker for names/addresses/phone-shaped values, but pair it with a small curated list of common
  Indian first/last names — Faker's `en_IN` locale is thin on its own.
- Model correlation, not independence: sample age first, then let disease prevalence and visit frequency
  depend on it. A simple conditional-probability table is enough at this scale — you don't need a real
  statistical model.
- Generate longitudinal history, not a snapshot: multiple years of `Appointment` rows per patient
  (completed/no-show/cancelled) with seasonal clustering — monsoon and winter upticks are realistic for
  a Pune clinic and exercise `months_since_last_visit_gte` / `missed_appointments_gte` far better than
  evenly-spaced fake visits.
- Generate matching `ClinicalEvent` rows so the caregaps scanner lands at a realistic overdue rate — aim
  for roughly 15–20% overdue per guideline, not 0% or 100%. The scanner's truth table only proves itself
  against varied input.

### 3. Draw a hard line around privacy, even though it's synthetic

- Never seed the generator from real patient records, de-identified or not — pure generation from a
  population spec is simpler and carries zero re-identification risk.
- Mark every synthetic row unambiguously — an `is_synthetic` flag, or a reserved phone-number prefix
  like the `90000xxxxx` range your test fixtures already use — so synthetic and real patients can never
  be confused if this environment is ever pointed at a production database.
- Hard-gate the command itself: refuse to run when `ENVIRONMENT=production`, the same way you'd want any
  dev-only seed to behave.

### 4. Validate the output before trusting it

- Add a small report command that prints the actual resulting distributions — age histogram, language
  mix, % overdue per guideline, no-show rate — so you can compare against the Step 1 spec and catch
  generator bugs before they quietly poison every test built on top of the data.
- Spot-check a handful of generated patients by hand: does this specific person's five-year history make
  clinical sense, or does it just satisfy the field types?

### 5. Put it to work on the three things it's actually for

- **Load-testing:** does the caregaps scanner, the outreach cohort builder, and the frontdesk router
  still hold up at 3,000+ patients, not 37?
- **Demos:** a varied, realistic dataset tells a far better story to a clinic owner or investor than the
  same 30 hand-picked patients they'll eventually notice repeating.
- **AI evaluation:** `test_router_live.py` and `test_plan_message_live.py` are currently checked against
  a curated fixture list — a larger synthetic pool of realistic patient messages gives you a bigger, more
  honest sample to catch edge cases the curated list doesn't cover.

---

Part 2 doesn't block Part 1 — they're independent workstreams you can run in either order. If you want a
concrete next step: Track A finishes fastest and is already fully designed, or the population spec in
Part 2, Step 1 is a good place to start on the data side.
