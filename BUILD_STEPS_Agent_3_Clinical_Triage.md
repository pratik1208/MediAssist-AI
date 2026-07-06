# BUILD_STEPS_Agent_3

# BUILD_STEPS — MediAssist AI: Clinical Triage Support

Covers PRD → "Clinical Triage Support" (FR-T1…FR-T10). **Safety-critical** — the emergency path must be the most-tested code in the project.

**Prerequisites:** Agent 1 (Scheduling) and Agent 2 (Registration, incl. the `core` app refactor). Triage reads patient history and hands off to Scheduling.

## Phase 1 — Data models

- [ ]  `python manage.py startapp triage`; add to `INSTALLED_APPS`
- [ ]  Models: `TriageAssessment` (FK → Patient + Conversation; reported symptoms JSON, question/answer transcript JSON, acuity enum — `emergency` / `high` / `medium` / `low` / `minimal`; recommended disposition; risk factors JSON; status), `ClinicalProtocol` (name, condition/symptom keywords, question flow JSON, disposition rules JSON, version, `approved_by`, active flag — protocols must be *configurable data*, not hardcoded prompts, per FR-T5), `EscalationAlert` (FK → TriageAssessment; priority, summary, acknowledged_at, assigned staff)
- [ ]  `makemigrations && migrate`; register in admin; confirm you can author a protocol row in `/admin/`
- [ ]  Management command `seed_protocols` — load 3–4 starter protocols (chest pain, fever in child, headache, abdominal pain) with red-flag criteria and acuity rules

## Phase 2 — Core business logic (no AI yet)

`triage/services.py`, tested with hardcoded inputs:

- [ ]  `red_flag_check(symptom_text)` — a **deterministic keyword/rule screen** (crushing chest pain, can't breathe, face drooping, suicidal, severe bleeding, unconscious…). This runs BEFORE and independently of any AI call — never rely on the model alone for emergency detection
- [ ]  `select_protocol(symptoms)` — match reported symptoms to an active `ClinicalProtocol`
- [ ]  `assign_acuity(assessment)` — apply the protocol's disposition rules + patient risk factors (age, chronic conditions, medications from the patient record) to produce acuity + recommended action mapping per FR-T4 (Emergency → ED/911 now, High → same-day, Medium → 24–48h, Low → routine, Minimal → self-care)
- [ ]  `escalate(assessment)` — create `EscalationAlert`, notify on-call (console/log notification stub for now), mark assessment escalated (FR-T6, FR-T8)
- [ ]  `route_disposition(assessment)` — emit the right event for downstream agents: same-day/routine → Scheduling; specialist → Referral; meds issue → Refill; overdue preventive care → Care Gap (FR-T7). Downstream agents that don't exist yet simply have no listener — that's fine
- [ ]  Tests: every red-flag phrase triggers escalation; acuity rules produce the right level for fixture patients (elderly + chest pain ≠ 25-year-old + chest pain); escalation creates an alert. `pytest` green.

## Phase 3 — API layer

- [ ]  Endpoints: start assessment, submit answer, get assessment result, list/acknowledge escalation alerts (staff)
- [ ]  Manually drive a full assessment via curl with scripted answers — no AI

## Phase 4 — AI integration

- [ ]  System prompt: clinical triage assistant; asks ONE adaptive question at a time driven by the selected protocol; supports but never replaces clinical judgment; never diagnoses; defers to caution — when uncertain between two acuity levels, always pick the higher one; plain-language explanations (FR-T2, FR-T5)
- [ ]  Tool schema `triage_step` (`strict: true`): `extracted_findings` (structured symptom attributes: onset, severity 1–10, location, radiation, associated symptoms), `emergency_detected` (bool), `next_question` (or null), `assessment_complete` (bool), `suggested_acuity` + `rationale`
- [ ]  `handle_triage_message(assessment, conversation_history)` — orchestration: run `red_flag_check` on the raw message FIRST; if flagged, short-circuit to the emergency script and `escalate()` without asking the model anything else. Otherwise call the API with `tool_choice` forced to `triage_step`, merge findings into the assessment, and when complete run `assign_acuity` — the deterministic rules decide final acuity; the model's `suggested_acuity` can only *raise* it, never lower it
- [ ]  `generate_triage_summary(assessment)` — structured summary for clinicians: symptoms, risk assessment, acuity, recommended action, transcript reference (FR-T8, FR-T9)
- [ ]  LangSmith tracing on all calls
- [ ]  **Red-flag test suite** (the most important tests in the project): a fixed list of 25+ emergency phrasings — including indirect ones ("my left arm feels heavy and I'm sweating") — that must ALWAYS end in `emergency` + escalation. Run it after every prompt change
- [ ]  Vague-symptom suite: ambiguous inputs must produce a follow-up question, never a guess

## Phase 5 — Frontend

- [ ]  Reuse `ChatWindow` for the triage conversation (patients reach it from registration handoff or directly)
- [ ]  Emergency result screen: unmistakable "seek emergency care / call 911" panel — no slot picker, no further questions
- [ ]  Non-emergency result screen: acuity explanation + inline handoff into the Agent 1 slot picker for same-day/routine booking
- [ ]  Staff escalation queue page: list of `EscalationAlert`s with AI summary, risk level, patient contact info, acknowledge button (PRD Screens #8)

## Phase 6 — Integration + edge cases

- [ ]  Registration → Triage handoff: symptoms reported during registration start an assessment with the intake context pre-loaded (PRD primary journey)
- [ ]  Triage → Scheduling handoff: disposition drives doctor specialty + urgency in `find_available_slots` (FR-S2/S3 meet FR-T7)
- [ ]  Edge case (PRD Edge Case 11): emergency symptoms mentioned mid-*scheduling* conversation must also trigger the red-flag path — export `red_flag_check` from triage and call it inside Agent 1's `handle_patient_message` too
- [ ]  Analytics endpoint (FR-T10): volume, acuity distribution, escalation rate, avg triage time, same-day conversion

## Phase 7 — Deploy

- [ ]  Migrate + deploy; seed protocols in production
- [ ]  Smoke-test on the live URL: one emergency phrase, one routine complaint, end to end
