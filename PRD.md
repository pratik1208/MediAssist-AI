# MediAssist AI — Product Requirements Document (PRD)

> **Naming note:** The source specification is titled "Xcaliber — Patient Management System"; the project uses the name "MediAssist AI". This PRD uses **MediAssist AI** throughout. Final product naming is an open decision (see Assumptions).

---

# Product Overview

MediAssist AI is an AI-powered patient management platform for healthcare providers. Patients interact with conversational AI agents — over phone, chat, WhatsApp, mobile app, and patient portal — instead of navigating menus, filling forms, or waiting for front-desk staff. The platform automates the administrative and coordination workflows that surround patient care:

1. **Patient Registration & Intake** — conversational onboarding, identity/insurance verification, medical intake
2. **Intelligent Scheduling** — natural-language appointment booking, rescheduling, cancellation, waitlists, reminders
3. **Clinical Triage Support** — AI symptom assessment, urgency determination, and routing to the right level of care
4. **Automated Refill Coordination** — prescription refill requests, eligibility checks, physician approval, pharmacy notification
5. **Referral Execution** — end-to-end referral management from creation to closed-loop confirmation
6. **Prior Authorization** — automatic detection, documentation, submission, and tracking of insurance approvals
7. **Outreach Campaigns** — cohort-based, multi-channel proactive patient engagement
8. **Care Gap Closure** — continuous monitoring of patient records against clinical guidelines and proactive gap resolution
9. **After-Hours Automation** — a 24×7 orchestration layer ("virtual front desk") that routes any patient request to the right agent at any time

All agents read from and write back to the provider's EHR/EMR (via FHIR integration), keep a complete record of every interaction, and escalate to licensed clinical staff whenever safety or policy requires it.

**Primary goal (from specification):** reduce patient waiting time and doctors' dwell time.

# Problem Statement

Healthcare providers run patient-facing operations largely by hand, which creates delays, errors, and lost revenue:

- **Scheduling** requires receptionists; patients wait on hold, slots freed by cancellations go unused, and no-shows are common.
- **Prescription refills** involve calls, manual eligibility checks, and physician chart review — taking hours or days for what should be minutes.
- **Referrals** depend on staff faxing records and phoning specialist offices; many referrals are never completed and patients are lost in the process.
- **Prior authorization** is a multi-day, error-prone paperwork exercise that delays treatment and causes claim denials.
- **Preventive care and outreach** rely on staff manually finding overdue patients among thousands of records, so care gaps stay open.
- **Registration** uses paper forms and manual data entry, producing long waits, incomplete data, and duplicate records.
- **After hours**, patients reach voicemail: missed appointments, delayed refills, unanswered questions, and a poor experience.
- **Triage** by phone is staff-intensive and unavailable 24×7, so urgency decisions are delayed.

The net effect is long patient waiting times, high administrative workload, underutilized physicians, and gaps in continuity of care.

# Goals

1. Reduce patient waiting time and doctors' dwell time (primary specification goal).
2. Enable 24×7 self-service for booking, refills, referrals, status inquiries, and common questions.
3. Reduce receptionist, nursing, and administrative workload by automating routine coordination tasks.
4. Reduce no-shows (automated reminders) and unused slots (automatic backfill from waitlists).
5. Improve doctor utilization and reduce physician review time via AI-generated clinical summaries.
6. Speed up refills, referrals, and prior authorizations; increase referral completion and PA approval rates.
7. Improve preventive care, medication adherence, and value-based care quality metrics by closing care gaps.
8. Keep the EHR accurate and current through automatic write-back of every interaction and outcome.
9. Provide measurable operational visibility through per-module analytics dashboards.

# Target Users

| User | How they use MediAssist AI |
| --- | --- |
| **Patients** (including caregivers acting for children or family members) | Register, book/reschedule/cancel appointments, request refills, check referral and authorization status, report symptoms, receive reminders — by phone, chat, WhatsApp, mobile app, or portal |
| **Physicians / Providers** (PCPs and specialists) | Review AI-prepared summaries; one-click approve/reject refill renewals; create referrals; receive triage escalations and closed-loop referral reports |
| **Care Coordinators** | Post-visit follow-ups and chronic disease outreach; monitor referral progress and care gap closure; act on escalations |
| **AI-Nurse (platform role)** | Provides clinical triage support and answers foundational medical questions within strict clinical guardrails, with immediate escalation to licensed staff |
| **Nurses / clinical staff (on-call)** | Receive escalated urgent cases with AI-prepared symptom summaries and risk assessments |
| **Front-desk / administrative staff** | Handle exceptions the AI stages for manual review (e.g., insurance disputes, document review) |
| **Healthcare organization leadership** | Track dashboards: utilization, campaign outcomes, care gap closure, quality measure performance |

# Core Features

> **Priority note:** The specification does not assign priorities or phases. Priorities below are the author's proposal based on dependency order and the primary goal, and are marked as an assumption (see Assumptions).

## 1. Patient Registration & Intake
- **Purpose:** Replace paper forms and manual data entry with a conversational AI intake that collects demographics, verifies identity and insurance, captures medical history, processes uploaded documents (OCR), generates a structured intake summary, and creates/updates the EHR record — then triggers downstream agents.
- **User Value:** Patients register naturally by talking instead of filling long forms; staff stop re-keying data; duplicate records and data-entry errors are prevented; downstream workflows (scheduling, refills, referrals, prior auth) start with complete, verified data.
- **Priority:** Must Have (foundational — every other agent depends on a verified patient profile).

## 2. Intelligent Scheduling
- **Purpose:** Let patients book, reschedule, and cancel appointments in natural language over call or chat. The AI extracts symptoms, duration, specialty, and time preference; determines the likely condition and urgency from the patient's description; selects the appropriate doctor; checks real-time availability in the EHR/EMR; books the slot; manages waitlists; backfills cancelled slots automatically; and sends confirmations, reminders, and follow-up scheduling.
- **User Value:** Patients book in one conversation, 24×7, without choosing among doctors themselves; providers get fewer no-shows, fuller calendars, and no double-bookings; receptionist workload drops.
- **Priority:** Must Have (directly serves the primary goal of reducing waiting time).

## 3. Clinical Triage Support
- **Purpose:** Assess reported symptoms through adaptive clinical questioning, combine them with the patient's history to stratify risk, assign an acuity level (Emergency / High / Medium / Low / Minimal), give evidence-based next-step guidance from approved clinical protocols, and trigger the appropriate downstream agent — escalating emergencies to on-call clinicians immediately.
- **User Value:** Patients get an immediate, safe answer to "how urgent is this?" at any hour; clinical staff receive structured summaries instead of raw conversations; urgent cases are never left waiting for office hours.
- **Priority:** Must Have (safety-critical; urgency determination is also a stated requirement of scheduling).

## 4. Automated Refill Coordination
- **Purpose:** Accept natural-language refill requests; verify patient identity; check prescription status, refill limits, required labs, and follow-up requirements against eligibility rules; prepare a concise renewal summary; route to the physician for one-click Approve / Reject / Request Visit; write the outcome back to the EHR; and notify the pharmacy and patient.
- **User Value:** Chronic-disease patients get refills in minutes instead of days; physicians review a few lines instead of a full chart; nurses and admin staff are freed from manual verification.
- **Priority:** Should Have.

## 5. Referral Execution
- **Purpose:** Automate the referral lifecycle: the physician clicks "Create Referral"; the AI extracts only the specialty-relevant chart data into a concise referral package, contacts the specialist office (checking acceptance, availability, insurance, location, fees), attaches required documents, books the appointment, notifies and reminds the patient, tracks status through completion, imports the specialist's consultation report, and closes the loop with the referring physician.
- **User Value:** Patients actually complete referrals instead of being lost to delays and missing paperwork; PCPs get consultation results back reliably; staff no longer fax records or chase specialist offices.
- **Priority:** Should Have.

## 6. Prior Authorization
- **Purpose:** When a physician orders a treatment, automatically detect whether the patient's insurance requires prior authorization (plan, payer rules, CPT, ICD-10, medication, network); gather the clinical evidence of medical necessity; generate the payer-specific package; submit through the appropriate channel; track status; respond to additional-information requests; and notify the care team and patient of approval or denial (with denial reason and appeal suggestion).
- **User Value:** Treatment starts days sooner; staff stop assembling paperwork; denials from incomplete documentation drop; providers and patients can see authorization status at any time.
- **Priority:** Should Have.

## 7. Outreach Campaigns
- **Purpose:** Let the organization define patient cohorts by clinical criteria (e.g., diabetics with HbA1c > 8% and no visit in 6 months); automatically identify qualifying patients from the EHR; run multi-channel campaigns (SMS, email, AI voice, WhatsApp, portal, app push); understand and act on patient replies (book, snooze, opt out); and track outcomes in a real-time dashboard.
- **User Value:** Preventive care reaches the patients who need it without staff combing through records; organizations close care gaps at scale and can measure conversion, completion, and ROI.
- **Priority:** Should Have.

## 8. Care Gap Closure
- **Purpose:** Continuously scan patient records against clinical guidelines to find overdue screenings, tests, vaccinations, and follow-ups; prioritize patients by clinical risk; bundle multiple gaps into a single personalized care plan; reach out via the Outreach agent; schedule the needed services via the Scheduling agent; track completion (re-engaging automatically if incomplete); and update the EHR and quality dashboards when gaps close.
- **User Value:** Patients receive recommended care proactively, often in one coordinated visit; providers improve guideline compliance, avoid preventable hospitalizations, and meet value-based care quality metrics.
- **Priority:** Should Have.

## 9. After-Hours Automation (24×7 Orchestration)
- **Purpose:** Act as the platform's "control tower": a 24×7 omnichannel entry point that authenticates the patient, detects intent (including multiple intents in one conversation), delegates to the appropriate specialized agent, answers common questions from a RAG knowledge base, screens reported symptoms for emergencies, escalates cases that need humans, and documents everything in the EHR.
- **User Value:** Patients get real help at 10:30 PM instead of voicemail; clinics capture appointments and refills they would otherwise lose; on-call staff are engaged only for genuinely urgent or sensitive cases.
- **Priority:** Should Have (depends on the specialized agents it orchestrates).

# Feature Matrix

> Status phasing is a proposal (see Assumptions); the specification does not define phases.

| Agent | Purpose | Inputs | Outputs | Dependencies | Status |
| --- | --- | --- | --- | --- | --- |
| Registration & Intake Agent | Conversational registration, identity/insurance verification, medical intake, document OCR | Patient conversation (voice/chat), uploaded documents (insurance card, ID, reports), existing EHR records | Verified patient profile, structured intake summary, EHR create/update, triggers to downstream agents | None (entry point) | MVP |
| Intelligent Scheduling Agent | Book/reschedule/cancel appointments, doctor selection, waitlist and cancellation backfill, reminders, follow-ups | Patient request (symptoms, specialty, time preference), doctor calendars/EHR availability, waitlist | Booked/updated appointment in EHR, confirmations and reminders (SMS/WhatsApp/email/voice) | Registration & Intake | MVP |
| Clinical Triage Agent | Symptom assessment, risk stratification, acuity assignment, care-level recommendation, emergency escalation | Reported symptoms, patient history/medications/allergies/labs from EHR | Acuity level, recommended disposition, triage summary in EHR, downstream agent triggers, on-call alerts | Registration & Intake; triggers Scheduling, Referral, Prior Auth, Care Gap, Refill | MVP |
| Refill Coordination Agent | Refill eligibility checks, renewal summaries, physician approval routing, pharmacy notification | Refill request, prescription history, refill limits, lab results, eligibility rules | Physician-ready renewal summary, approved e-prescription, EHR write-back, pharmacy & patient notifications | Registration & Intake | Phase 2 |
| Referral Execution Agent | End-to-end referral lifecycle, record packaging, specialist coordination, closed-loop tracking | Physician referral order, patient chart, specialist directories (availability, insurance, location) | Referral package, booked specialist appointment, status updates, imported consultation report, closed referral in EHR | Registration & Intake, Scheduling | Phase 2 |
| Outreach Campaign Agent | Cohort building, multi-channel campaigns, response handling, outcome tracking | Clinical goal & cohort criteria, EHR population data, patient contact/channel/language preferences | Outreach list, sent messages, handled responses (bookings/snoozes/opt-outs), campaign analytics | Registration & Intake, Scheduling | Phase 2 |
| Prior Authorization Agent | PA requirement detection, evidence assembly, payer submission, status tracking, care-team notification | Treatment order (CPT/ICD-10/medication), insurance plan & payer rules, clinical records | Payer-specific PA package, submission record, status updates, approval/denial notifications, EHR updates | Registration & Intake; invoked by Referral, Triage, Scheduling | Phase 3 |
| Care Gap Closure Agent | Continuous guideline-based gap detection, risk prioritization, care plans, closure tracking | Full patient records (diagnoses, labs, meds, visits, vaccinations), clinical guidelines | Open/closed care gaps, prioritized patient lists, personalized care plans, quality dashboard updates | Registration & Intake, Outreach, Scheduling | Phase 3 |
| After-Hours Automation Agent | 24×7 omnichannel intake, authentication, intent detection, orchestration, FAQ answering, safety screening | Patient contact on any channel, RAG knowledge base, all specialized agents | Routed and completed workflows, FAQ answers, escalation tasks, complete EHR documentation | All other agents (orchestrator) | Phase 3 |

# User Journey

**Primary journey — new patient with symptoms (touches Registration, Triage, Scheduling):**

1. A new patient contacts the clinic by chat: *"I'm Pratik. I'm a new patient and I've been having chest pain for three days."*
2. The **Registration & Intake Agent** conversationally collects demographics (name, DOB, phone, address, emergency contact, preferred language, preferred pharmacy), verifies identity via OTP, checks for duplicate records, and extracts insurance details from an uploaded insurance card, verifying eligibility in real time.
3. Medical intake follows with adaptive questions (symptoms, history, medications, allergies, family history, lifestyle). A structured intake summary is generated and the EHR record is created.
4. Because symptoms were reported, the **Clinical Triage Agent** asks adaptive clinical questions (onset, severity, radiation, shortness of breath), combines answers with history, and assigns an acuity level. Emergency signs → the patient is told to seek emergency care and the on-call provider is alerted. Non-emergent → triage recommends a cardiology visit.
5. The **Intelligent Scheduling Agent** selects an appropriate available cardiologist, books the earliest suitable slot (never offering a taken one), and sends confirmation and reminders via the patient's preferred channel.
6. Every step — transcript, intake summary, triage assessment, appointment — is written to the EHR before any staff member is involved.

**Secondary journeys:**

- **Chronic patient, after hours:** At 10:30 PM a patient messages *"I need to refill my blood pressure medicine and also schedule my annual checkup."* The **After-Hours Agent** authenticates the patient, detects both intents, invokes the **Refill Agent** (eligibility check → renewal summary → physician approval queue) and the **Scheduling Agent** (annual checkup). The Scheduling Agent surfaces an overdue cholesterol screening via the **Care Gap Agent** and adds the lab work to the visit. The patient gets immediate confirmation; the EHR is fully documented; no staff are involved.
- **Referral with prior authorization:** A PCP evaluates exercise-related chest pain and clicks **Create Referral**. The **Referral Agent** packages relevant records (ECG, medications, BP history), finds an in-network cardiologist, books the visit, and tracks it to completion. When the cardiologist orders an MRI, the **Prior Authorization Agent** detects the PA requirement, assembles evidence, submits, answers the payer's request for additional records, and on approval the MRI is scheduled and everyone is notified.
- **Proactive outreach:** The organization launches a flu-vaccination campaign for patients 65+. The **Outreach Agent** builds the cohort from the EHR, sends SMS/email, follows up non-responders with an AI voice agent, books appointments from replies, honors opt-outs, and reports conversion on the campaign dashboard.

# Screens / Pages

The patient experience is **conversation-first** (chat and voice), so patient-facing "screens" are primarily conversational surfaces plus notifications; staff-facing surfaces are dashboards and queues.

**Patient-facing**
1. **Conversational assistant** — chat UI embedded in the website, patient portal, and mobile app; also reachable by phone (voice), SMS, and WhatsApp. Used for registration, booking, refills, triage, status inquiries, and FAQs.
2. **Document upload** — within the conversation: insurance card, driver's license, prescriptions, lab reports, referral letters, imaging reports.
3. **Notifications** — confirmations, reminders, preparation instructions, directions, refill-ready and authorization-status messages via SMS, WhatsApp, email, voice call, portal, and app push.

**Provider / staff-facing**
4. **Provider approval queue** — one-click review of refill renewal summaries (Approve / Reject / Request Visit) and prior-authorization packages.
5. **Referral status dashboard** — referral progress from creation through closure, with alerts for stalled or missed referrals.
6. **Population health / care gap dashboard** — open care gaps, closure rates, risk-prioritized patient lists, quality measure performance by provider or clinic.
7. **Campaign manager & analytics dashboard** — cohort definition, campaign launch, and real-time funnel metrics (identified → sent → delivered → responded → scheduled → completed, conversion, ROI).
8. **Escalation / task queue** — high-priority alerts for on-call clinicians and care coordinators with AI-prepared symptom summaries, risk levels, and recommended actions.
9. **Provider dashboard** — per-provider view of appointments, triage summaries, and care plan updates.
10. **Module analytics dashboards** — registration (completion rate, verification success, time saved), after-hours (volume, automation rate, escalation rate, satisfaction), and triage (acuity distribution, escalation rate, triage-to-treatment time).

# Functional Requirements

## Registration & Intake (FR-R)
- **FR-R1.** Support conversational registration by voice and chat, with multi-language support and a dynamic question flow driven by patient responses.
- **FR-R2.** Collect demographics: full name, date of birth, phone, address, emergency contact, preferred language, preferred pharmacy.
- **FR-R3.** Verify identity via phone OTP and email; optionally government ID. Search existing records and classify the outcome: existing patient, new patient, or duplicate detected — preventing duplicate record creation.
- **FR-R4.** Extract insurance details (provider, policy number, member ID, coverage dates) from an uploaded insurance card via OCR, and verify eligibility in real time through payer APIs. Notify the patient immediately if coverage is inactive.
- **FR-R5.** Conduct adaptive medical intake: current symptoms, past medical history, current medications, allergies, family history, and lifestyle (smoking, alcohol, exercise) — asking only relevant follow-up questions.
- **FR-R6.** Accept and process uploaded documents (insurance cards, driver's license, prescriptions, lab reports, referral letters, imaging reports) using OCR/document understanding, extracting structured data (e.g., diagnosis, date, findings, physician, hospital).
- **FR-R7.** Generate a structured intake summary attached to the patient record.
- **FR-R8.** Create or update the EHR (demographics, insurance, medical history, allergies, medication list, problem list, intake notes, encounters, conditions, documents) via FHIR.
- **FR-R9.** Trigger downstream agents automatically once registration completes (Scheduling, Referral, Prior Authorization, Refill, Care Gap Detection, Outreach).
- **FR-R10.** Report analytics: average registration time, completion rate, identity- and insurance-verification success rates, duplicates prevented, intake data completeness, time saved vs. manual registration.

## Intelligent Scheduling (FR-S)
- **FR-S1.** Accept appointment requests in natural language over phone call, chat, and WhatsApp; extract symptom, duration, specialty, and preferred time from free text.
- **FR-S2.** Determine the likely condition from the patient's description and select the appropriate specialty and doctor automatically (e.g., child with fever → pediatrician), factoring in doctor requirements for the booking.
- **FR-S3.** Detect urgency from the patient's description and prioritize accordingly.
- **FR-S4.** Integrate with the hospital scheduling system (EHR/EMR) in real time, checking doctor availability, holidays, existing appointments, appointment duration, buffer time, and room availability (if needed). Never offer an already-booked slot.
- **FR-S5.** Support booking, rescheduling (including automatic rescheduling), and cancellation.
- **FR-S6.** On cancellation, automatically check the waitlist, offer the freed slot to the highest-priority waitlisted patient, and confirm the new booking.
- **FR-S7.** Manage waitlisted patients.
- **FR-S8.** Send confirmations and reminders via SMS, WhatsApp, email, and voice call.
- **FR-S9.** Schedule doctor-recommended follow-ups automatically (e.g., in 30 days) or remind the patient when due.
- **FR-S10.** Support prescription renewal requests from returning patients by handing off to the Refill Coordination agent.

## Clinical Triage Support (FR-T)
- **FR-T1.** Accept symptom reports via phone, chatbot, mobile app, WhatsApp, and patient portal.
- **FR-T2.** Ask adaptive, symptom-specific clinical questions where each question depends on previous answers.
- **FR-T3.** Stratify risk by combining current symptoms with age, medical history, chronic diseases, medications, allergies, recent lab results, and previous encounters from the EHR.
- **FR-T4.** Assign an acuity level with a corresponding action: Emergency (ED/911 immediately), High (same-day visit), Medium (24–48 hours), Low (routine appointment), Minimal (self-care guidance).
- **FR-T5.** Provide evidence-based guidance from approved, configurable clinical protocols, explained in plain language. The AI supports clinical decision-making and never replaces clinical judgment.
- **FR-T6.** For emergencies: advise immediate emergency care / calling emergency services, notify the on-call clinician, and create a high-priority alert.
- **FR-T7.** Trigger the appropriate downstream agent by disposition: Scheduling (same-day or routine visit), Referral (specialist needed), Prior Authorization (diagnostics requiring approval), Care Gap Closure (overdue preventive services), Refill Coordination (medication issues).
- **FR-T8.** Notify clinical staff on escalation with the symptom summary, risk assessment, recommended action, and patient contact information.
- **FR-T9.** Document everything in the EHR: symptoms, triage questions, AI assessment, risk level, recommended disposition, escalation actions, and conversation transcript — with a structured summary for provider review.
- **FR-T10.** Report analytics: assessment volume, acuity distribution, emergency escalation rate, average triage time, same-day appointment conversion rate, referral generation rate, triage-to-treatment turnaround.

## Automated Refill Coordination (FR-M)
- **FR-M1.** Accept natural-language refill requests and identify the patient, medication, quantity, and preferred pharmacy.
- **FR-M2.** Verify patient identity before processing.
- **FR-M3.** Evaluate eligibility rules: prescription active and unexpired, not discontinued by the doctor, refill due, required lab tests completed, follow-up visit not required. If any condition fails, pause the refill.
- **FR-M4.** Track refill counts against the prescription's allowed refills; when none remain, automatically detect that a new prescription is needed.
- **FR-M5.** Generate a concise renewal summary for the physician: medication and dose, last prescribed date, remaining refills, relevant recent labs, allergies, adverse events, medication adherence.
- **FR-M6.** Route medications requiring physician approval to the provider with one-click actions: Approve, Reject, Request Visit.
- **FR-M7.** On approval, write back to the EHR: new prescription, approval date, prescribing physician, number of refills, medication history.
- **FR-M8.** Send the approved prescription electronically to the patient's pharmacy and notify the patient (including pickup readiness).

## Referral Execution (FR-F)
- **FR-F1.** Let the physician create a referral with one click during consultation; the AI starts the workflow automatically.
- **FR-F2.** Extract only the specialty-relevant chart data (e.g., for cardiology: diagnosis, BP history, ECG, echo, lipid profile, medications, allergies, recent notes) into a concise referral package with an AI-generated referral summary.
- **FR-F3.** Contact the specialist office via automated call, electronic referral, email, FHIR/API integration, or secure message; verify the specialist is accepting patients, earliest availability, insurance accepted, location, and consultation fees (if applicable).
- **FR-F4.** Automatically attach the specialty-specific supporting documents specialists require (e.g., X-ray/MRI/surgery notes for orthopedics; ECG/echo/blood reports for cardiology).
- **FR-F5.** Book the specialist appointment, filtering by distance, insurance, specialty, availability, patient preference, and language preference (supporting requests like "nearest hospital").
- **FR-F6.** Notify the patient with appointment details, reminders, directions, and preparation instructions.
- **FR-F7.** Track referral status through the lifecycle: Created → Accepted → Appointment Scheduled → Patient Confirmed → Visit Completed → Consultation Report Received → Closed.
- **FR-F8.** If the patient misses the appointment: send reminders, offer rescheduling, and notify the referring physician if no action is taken.
- **FR-F9.** Alert care coordinators if a referral remains incomplete beyond a configurable timeframe (e.g., 14 days).
- **FR-F10.** Close the loop: import the specialist's diagnosis, treatment plan, medications, and follow-up recommendations into the EHR, notify the referring physician, and mark the referral completed.

## Prior Authorization (FR-P)
- **FR-P1.** Immediately after a treatment order (medication, imaging, procedure, device, therapy), determine whether prior authorization is required based on the patient's insurance plan, payer rules, procedure code (CPT), diagnosis code (ICD-10), medication, and provider network — with no manual verification.
- **FR-P2.** Automatically gather clinical evidence of medical necessity: diagnosis, physician notes, lab results, imaging reports, medication history, previous treatments, allergies, and relevant clinical guidelines.
- **FR-P3.** Generate the payer-specific authorization package: completed forms, patient demographics, diagnosis and procedure codes, attached supporting documents, and a structured reviewer summary.
- **FR-P4.** Submit through the appropriate channel — payer API, electronic prior authorization (ePA), insurance portal, or fax — and record the submission in the EHR.
- **FR-P5.** Continuously track status (Submitted → Under Review → Additional Information Requested → Approved / Denied) without manual follow-up.
- **FR-P6.** Handle additional-information requests: identify the requested documents, retrieve them from the EHR, and send automatically or stage for staff review.
- **FR-P7.** On approval: notify the physician and patient, schedule the treatment, and update the EHR. On denial: notify the physician, explain the denial reason, and suggest an appeal if appropriate.

## Outreach Campaigns (FR-O)
- **FR-O1.** Define patient cohorts from clinical criteria (e.g., age, condition, lab thresholds such as HbA1c > 8%, visit recency, vaccination status, missed appointments) and build them automatically from EHR data.
- **FR-O2.** Identify all qualifying patients by searching the EHR against the criteria.
- **FR-O3.** Generate an outreach list including patient name, contact information, reason for outreach, preferred language, preferred communication channel, and assigned physician.
- **FR-O4.** Launch multi-channel campaigns across SMS, email, AI voice calls, WhatsApp, patient portal, and mobile app notifications — escalating channels for non-responders (e.g., voice agent after unanswered SMS/email).
- **FR-O5.** Understand and act on patient responses: book appointments, pause the campaign until a requested date ("remind me next month"), and record opt-outs with updated communication preferences.
- **FR-O6.** Schedule resulting appointments automatically via the Intelligent Scheduling module.
- **FR-O7.** Track campaign performance in real time: patients identified, messages sent, delivered, responses, appointments scheduled and completed, conversion rate, and campaign ROI.

## Care Gap Closure (FR-G)
- **FR-G1.** Continuously scan all patient records — diagnoses, lab results, medications, procedures, visit history, vaccination records, physician notes — for missing recommended care.
- **FR-G2.** Compare patient history against standard clinical guidelines (e.g., HbA1c every 6 months for diabetics, annual eye exam, screening schedules) and record unmet items as Open Care Gaps.
- **FR-G3.** Prioritize patients by clinical risk (High: overdue cancer screening, uncontrolled diabetes, abnormal labs, heart-failure follow-up; Medium: wellness visits, vaccinations; Low: lifestyle counselling).
- **FR-G4.** Bundle a patient's open gaps into one personalized care plan, completable in a single coordinated visit where possible.
- **FR-G5.** Reach out via the Outreach agent (SMS, voice, and other channels) with the bundled plan.
- **FR-G6.** On patient agreement, automatically schedule labs, primary care visits, imaging, specialist consultations, and vaccinations based on provider availability, patient preference, insurance, and location.
- **FR-G7.** Track completion of each item; if anything remains incomplete, automatically start another outreach cycle.
- **FR-G8.** On completion, update the EHR: care plan, clinical quality measures, population health dashboard, and provider dashboard; transition the gap from Open to Closed.
- **FR-G9.** Report analytics: total open care gaps, closure rate, outreach response rate, appointment completion rate, quality measure performance by provider or clinic.

## After-Hours Automation (FR-A)
- **FR-A1.** Provide a 24×7 entry point across phone, website chatbot, mobile app, WhatsApp, and patient portal with natural language understanding.
- **FR-A2.** Classify patient intent (appointment, refill, referral status, care gap inquiry, prior authorization status, general questions, clinical symptoms) and route to the appropriate specialized agent — supporting multiple intents within a single conversation.
- **FR-A3.** Authenticate the patient before accessing medical information: date of birth, phone/email OTP, patient ID, and security questions if needed.
- **FR-A4.** Execute supported workflows end-to-end without human intervention where possible; create staff tasks when manual review is required.
- **FR-A5.** Answer common questions from a RAG-backed knowledge base: clinic hours, provider availability, office location, accepted insurance, prescription pickup, appointment preparation instructions, billing FAQs.
- **FR-A6.** Perform a clinical safety check on any reported symptoms; on detecting emergency symptoms, advise immediate emergency care / calling emergency services and notify the on-call provider if configured; forward routine cases to the Clinical Triage agent.
- **FR-A7.** Escalate to humans for cases requiring intervention — mental health crisis, suspected stroke, complex insurance disputes, controlled substance refill requests — by creating a high-priority task, alerting the on-call provider or nurse, and logging the interaction.
- **FR-A8.** Document every interaction in the EHR: conversation transcript, appointments booked, refills requested, statuses checked, questions answered, escalations created — maintaining a complete audit trail.
- **FR-A9.** Report analytics: after-hours conversation volume, automation rate, requests resolved without staff, average response time, escalation rate, patient satisfaction, most common request types.

# Non-Functional Requirements

- **NFR-1 — Availability:** Patient-facing channels operate 24×7, including nights, weekends, and holidays.
- **NFR-2 — Privacy & compliance:** Patient identity must be verified before any patient-specific information is disclosed or acted on; the system must comply with applicable healthcare privacy regulations. *(Specific regime, e.g., HIPAA, is assumed — see Assumptions.)*
- **NFR-3 — Clinical safety:** All AI guidance operates within strict clinical guardrails, follows approved/configurable clinical protocols, supports but never replaces clinical judgment, and provides immediate escalation paths to licensed staff for emergencies and sensitive cases.
- **NFR-4 — Auditability:** Every AI interaction, decision, and workflow outcome is documented in the EHR, including conversation transcripts, forming a complete audit trail.
- **NFR-5 — Scheduling integrity:** Calendar data is real-time; an already-booked slot is never offered; holidays, appointment durations, and buffer times are always respected.
- **NFR-6 — Omnichannel consistency:** The same capabilities behave consistently across phone/voice, chat, SMS, WhatsApp, email, patient portal, and mobile app, with speech-to-text supporting voice interactions.
- **NFR-7 — Multi-language:** Conversations and outreach respect the patient's preferred language. *(Supported language list unspecified — see Assumptions.)*
- **NFR-8 — Communication preferences:** Opt-outs and preferred channels are recorded and honored across all modules.
- **NFR-9 — Scale:** Outreach and care gap workflows must operate at population scale (specification examples reference cohorts of 3,500–5,000 patients).
- **NFR-10 — Timeliness:** AI-generated summaries must allow physicians to review requests "in seconds"; refill, referral, and prior authorization turnaround must be substantially faster than the manual baselines described (hours/days). *(No quantitative targets in specification — see Assumptions.)*

# Edge Cases

1. **No refills remaining** — the AI detects that a new prescription (not a refill) is needed and routes accordingly.
2. **Refill eligibility failure** — prescription expired/discontinued, refill not yet due, required labs missing, or follow-up visit required → refill is paused and the patient is informed.
3. **Inactive insurance at registration** — the patient is notified immediately.
4. **Duplicate patient detected** — registration prevents creating a second record; the existing record is used.
5. **Slot race/conflict** — an already-booked slot is never offered; bookings respect holidays, durations, buffers, and room availability.
6. **Cancellation backfill** — a freed slot triggers a waitlist check and is offered to the highest-priority patient with automatic confirmation.
7. **Missed specialist appointment** — reminders are sent, rescheduling offered, and the referring physician notified if no action is taken.
8. **Stalled referral** — a referral incomplete beyond the configured timeframe (e.g., 14 days) alerts care coordinators.
9. **Prior authorization denial** — the physician is notified with the denial reason and an appeal suggestion where appropriate.
10. **Payer requests additional information** — the AI retrieves and submits the requested documents, or stages them for staff review.
11. **Emergency symptoms in any conversation** — the patient is directed to emergency care/911 and the on-call provider is alerted, regardless of which agent the conversation started in.
12. **Cases the AI must not handle autonomously** — mental health crisis, suspected stroke, complex insurance disputes, controlled substance refills → immediate human escalation with a high-priority task.
13. **Patient opts out of outreach** — the opt-out is recorded and communication preferences updated across campaigns.
14. **Patient defers outreach** ("remind me next month") — the campaign pauses until the requested date.
15. **Campaign non-responders** — follow-up escalates to an AI voice agent after unanswered SMS/email.
16. **Multiple intents in one conversation** — e.g., a refill plus an appointment request are both detected and both fulfilled.
17. **Care plan partially completed** — pending items automatically trigger a new outreach cycle until closed.

# Assumptions

The specification omits the following; each item below is an assumption or open question rather than specified functionality:

1. **Product name** — the specification says "Xcaliber", the project is "MediAssist AI"; this PRD assumes MediAssist AI pending a naming decision.
2. **Priorities and phasing** — no priorities, phases, or MVP scope are defined in the specification. The Must/Should ratings and MVP/Phase 2/Phase 3 statuses here are the author's proposal based on dependencies (Registration → Scheduling/Triage → coordination agents → orchestration) and require stakeholder confirmation.
3. **Regulatory regime** — the specification says only "complies with healthcare regulations". HIPAA (US) is implied by the insurance/CPT/ICD-10 context but not stated; jurisdiction and certification requirements are unconfirmed.
4. **Quantitative targets** — no numeric goals are given for wait-time reduction, automation rate, response latency, PA turnaround, or care gap closure; success metrics need definition.
5. **EHR/EMR and payer specifics** — FHIR is named as the integration standard, but target EHR vendors, payer APIs, and e-prescription networks are unspecified.
6. **Provider-side access control** — patient authentication (OTP etc.) is specified, but staff/physician authentication, roles, and permissions are not.
7. **Escalation staffing** — on-call provider/nurse coverage is assumed to exist and be configurable ("if configured" per specification); the staffing model is out of scope.
8. **Clinical protocol source** — triage guidance follows "approved, configurable clinical protocols"; which guideline sets and who approves/maintains them is undefined.
9. **Supported languages** — multi-language support is required but the language list is unspecified.
10. **Patient consent** — consent flows for AI interaction, call recording, and data processing are not described.
11. **Billing and payments** — out of scope; only billing FAQs (via the knowledge base) are mentioned.
12. **Care Coordinator & AI-Nurse roles** — the specification names these roles with brief responsibilities (post-visit follow-ups and chronic disease outreach; triage support and foundational medical Q&A within guardrails). Their detailed workflows are assumed to be delivered through the Outreach/Care Gap and Triage/After-Hours modules respectively.
13. **Waitlist priority rules** — "highest-priority patient" ordering for freed slots is unspecified (e.g., urgency vs. wait time).
14. **Patient satisfaction measurement** — the after-hours dashboard tracks patient satisfaction, but the collection method (e.g., post-conversation survey) is unspecified.

# Future Enhancements

Items the specification marks as optional or mentions only peripherally — not required for the phases above:

1. **Government ID verification** during registration (explicitly "optional" in the specification).
2. **Room-availability-aware scheduling** (specification: "if needed").
3. **Specialist ratings** as a factor in smart specialist matching (listed among potential matching criteria).
4. **Consultation fee display** during specialist selection (specification: "if applicable").
5. **Automated prior-authorization appeals** — the specification requires only *suggesting* an appeal on denial; preparing and submitting appeals automatically is a natural extension.
6. **Expanded AI-Nurse capabilities** — richer foundational medical Q&A beyond triage protocols, within the same guardrails and escalation rules.
