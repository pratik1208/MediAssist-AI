# Xcaliber

# Patient management system

**Goal:** To reduce patient waiting time and doctors dwell time

## **Intelligent Scheduling**

1. Appointment booking over call as well as chat
2. Booking appointment as per requirement of doctor
3. Detemination of disease based on the description provided by patient
4. appointing doctor based on patient disease description
5. Determining urgency based on patient dewscription
6. AUtomatic cancellation of appointment and alloting same slots to another patient
7. Management of waitlisted patients
8. Prescription  renewal of old patients

The **Intelligent Scheduling** module is an AI-powered appointment management system. Instead of a patient navigating menus or talking to a receptionist, they interact with an AI agent via phone, chat, or WhatsApp. The AI understands the request, determines the urgency, finds the appropriate doctor, and books the appointment automatically.

<aside>
💡

> Patient
│
▼
AI Conversational Agent
│
├── Understand symptoms
├── Determine urgency
├── Identify specialty/doctor
├── Check doctor availability (EHR/EMR)
├── Suggest available slots
├── Book/Reschedule/Cancel
└── Send confirmation & reminders
> 
</aside>

### Feartures

1. Natural Language Booking
    
    Instead of filling forms, the patient simply says:
    
    > "I have had chest pain since yesterday. I need to see a cardiologist this week."
    > 
    
    The AI extracts:
    
    - Symptom: Chest pain
    - Duration: 1 day
    - Specialty: Cardiology
    - Preferred time: This week
    
    and searches for suitable appointments.
    
2. Smart Doctor Selection
    
    Rather than asking the patient to choose a doctor, the AI recommends one.
    
    Example:
    
    Patient:
    
    "My daughter has had a fever for three days."
    
    AI determines:
    
    Patient type → Child
    
    Disease → Fever
    
    Required specialist → Pediatrician
    
    It books with an available pediatrician.
    
3. Urgency Detection
4. Real-Time Calendar Integration
    
    The AI connects to the hospital's scheduling system (EHR/EMR).
    
    It checks:
    
    - Doctor availability
    - Holidays
    - Existing appointments
    - Appointment duration
    - Buffer time
    - Room availability (if needed)
    
    It never offers an already-booked slot.
    
5. Automatic Rescheduling
6. **Intelligent Cancellation**
    1. Slot becomes available.
    2. AI checks the waitlist.
    3. Offers the slot to the highest-priority patient.
    4. Confirms the new booking automatically.
    
    This reduces unused appointment slots.
    
7. Appointment Reminders
    
    The AI sends reminders via:
    
    - SMS
    - WhatsApp
    - Email
    - Voice call
8. Follow-up Scheduling
    
    After the consultation:
    
    Doctor recommends a follow-up in 30 days.
    
    AI automatically schedules it or reminds the patient when due.
    

### AI Components

| Component | Purpose |
| --- | --- |
| Speech-to-Text | Converts phone conversation to text |
| LLM | Understands patient requests |
| Medical Intent Classifier | Identifies symptoms and intent |
| Triage Model | Determines urgency |
| Recommendation Engine | Selects the appropriate doctor |
| Scheduling Engine | Finds the best appointment slot |
| Calendar/EHR Integration | Books directly into the hospital system |
| Notification Service | Sends confirmations and reminders |

### Business Value

For healthcare providers, this module helps:

- Reduce receptionist workload.
- Enable 24/7 appointment booking.
- Decrease patient wait times.
- Reduce no-shows through automated reminders.
- Improve doctor utilization by automatically filling cancelled slots.
- Enhance patient experience with faster, conversational scheduling.

## Automated Refill Coordination

### What problem does it solve?

Patients with chronic diseases (diabetes, hypertension, asthma, etc.) often take medications for months or years. When their medication runs out, they need a refill.

Today, this process is largely manual:

- Patient calls the clinic or pharmacy.
- Staff verify if the patient is eligible.
- They check if the patient has remaining refills.
- The doctor reviews the request.
- The prescription is renewed.
- The pharmacy is notified.

This can take hours or even days.

**Automated Refill Coordination** uses AI to automate most of this workflow.

<aside>
💡

Patient
│
▼
AI receives refill request
│
├── Verify patient identity
├── Check prescription history
├── Check refill eligibility
├── Check refill limits
├── Prepare clinical summary
├── Send to physician for approval
├── Physician approves/rejects
├── Update EHR
└── Notify pharmacy & patient

</aside>

### Features

1. Patient Requests a Refill
    
    patient can say
    
    > "Refill my blood pressure medicine."
    > 
    
    The AI identifies:
    
    - Patient
    - Medication
    - Quantity
    - Preferred pharmacy
2. Evaluate Eligibility
    
    The AI checks several rules.
    
    Example:
    
    - Is the prescription still active?
    - Has it expired?
    - Has the doctor discontinued it?
    - Is the patient due for another refill?
    - Has the patient completed required lab tests?
    - Is a follow-up visit required?
    
    If any condition fails, the refill is paused.
    
3. Check Refills 
    
    Many prescriptions specify:
    
    ```
    Medicine:
    Metformin
    
    Initial Prescription:
    30 tablets
    
    Allowed Refills:
    5
    ```
    
    Suppose the patient has already used:
    
    ```
    Refill 1 ✔
    Refill 2 ✔
    Refill 3 ✔
    Refill 4 ✔
    Refill 5 ✔
    ```
    
    No refills remain.
    
    The AI automatically detects that a new prescription is needed.
    
4. Prepare Renewal Summary
    
    Instead of the physician reviewing the entire medical record, the AI creates a concise summary.
    
    Example:
    
    ```
    Medication:
    Metformin 500 mg
    
    Last prescribed:
    45 days ago
    
    Remaining refills:
    0
    
    Recent HbA1c:
    6.8%
    
    No allergies
    
    No adverse events reported
    
    Medication adherence:
    95%
    ```
    
    The doctor can review this summary in seconds.
    
5. Route for Provider Approval
    
    Some medications require physician approval.
    
    The AI sends the summary to the doctor.
    
    Doctor sees:
    
    ```
    Patient:
    John Smith
    
    Medication:
    Metformin
    
    Summary:
    ✓ Diabetes controlled
    ✓ Labs normal
    ✓ No side effects
    
    Approve?
    ```
    
    The doctor simply clicks:
    
    - Approve
    - Reject
    - Request Visit
6. EHR Write-Back
    
    Once approved, the AI updates the Electronic Health Record automatically.
    
    It records:
    
    - New prescription
    - Approval date
    - Prescribing physician
    - Number of refills
    - Medication history
    
    This keeps the patient's record up to date.
    
7. Notify Pharmacy & Patient
    
    The AI sends the approved prescription electronically to the patient's pharmacy.
    
    The patient receives a message such as:
    
    > "Your Metformin refill has been approved and sent to ABC Pharmacy. It will be ready after 4 PM."
    > 
    
    ---
    

### AI Components

| Component | Purpose |
| --- | --- |
| Conversational AI | Understands refill requests |
| Rules Engine | Validates refill eligibility |
| Medication Database | Checks prescription details |
| Clinical Summary Generator | Creates physician-ready summaries |
| EHR Integration | Reads and updates patient records |
| Notification Service | Sends updates to patients and pharmacies |

### Example End-to-End Scenario

**Patient:**

> "I need a refill for my blood pressure medicine."
> 

The AI:

1. Identifies the medication (e.g., Lisinopril).
2. Confirms the prescription is active.
3. Checks that 2 refills remain.
4. Verifies the patient recently had a blood pressure check.
5. Generates a one-page clinical summary.
6. Sends it to the physician.
7. The physician approves with one click.
8. The EHR is updated.
9. The prescription is sent electronically to the pharmacy.
10. The patient receives a confirmation message.

### Business Value

For healthcare providers, Automated Refill Coordination:

- Reduces manual work for nurses and administrative staff.
- Speeds up prescription renewals.
- Improves medication adherence for chronic disease patients.
- Reduces physician review time with AI-generated summaries.
- Maintains accurate EHR records through automatic write-back.
- Enhances patient satisfaction by delivering faster, more convenient refill processing.

## Referral Execution

### What problem does it solve?

When a primary care physician (PCP) determines that a patient needs specialist care, the patient is referred to another doctor (e.g., a cardiologist, neurologist, or orthopedist).

Today, the process is largely manual:

- The PCP creates a referral.
- Staff collect medical records.
- They fax or email documents.
- They contact the specialist’s office.
- They schedule the appointment.
- They follow up to ensure the patient attended.

Patients often fail to complete referrals because of delays, poor communication, or missing documentation.

**Referral Execution** automates the entire process, from referral creation to confirmation that the specialist visit has occurred.

### Workflow

<aside>
💡

Patient visits Primary Care Physician
│
▼
Doctor creates referral
│
▼
AI extracts relevant medical records
│
▼
AI contacts specialist office
│
▼
AI schedules appointment
│
▼
AI shares required documents
│
▼
Patient visits specialist
│
▼
Specialist sends consultation notes
│
▼
AI updates EHR and closes referral

</aside>

### Features

1.  Referral Created

During consultation:

Doctor says

> "You should see a cardiologist."
> 

The physician clicks

**Create Referral**

The AI starts the workflow automatically.

       During consultation:

Doctor says:

> "You should see a cardiologist."
> 

The physician clicks **Create Referral**.

The AI starts the workflow automatically.

---

2. Extract Relevant Chart Data

The patient's EHR may contain hundreds of pages.

The specialist doesn't need everything.

The AI extracts only the relevant information.

Example: For a cardiologist referral:

- Current diagnosis
- Blood pressure history
- ECG reports
- Echocardiogram
- Lipid profile
- Current medications
- Allergies
- Recent consultation notes

Instead of sending 200 pages, the AI prepares a concise referral package.

1. Contact Specialist Office
    
    Instead of staff making phone calls,
    
    the AI can:
    
    - Call automatically
    - Send referral electronically
    - Email documents
    - Use FHIR/API integration
    - Send secure messages
    
    The AI checks:
    
    - Is the specialist accepting patients?
    - Earliest available appointment
    - Insurance accepted
    - Location
    - Consultation fees (if applicable)
2. Coordinate Medical Records
    
    Specialists usually request supporting documents.
    
    Example
    
    Orthopedic referral may require:
    
    - X-ray
    - MRI
    - Previous surgery notes
    
    Cardiology referral may require:
    
    - ECG
    - Echo
    - Blood reports
    
    The AI automatically attaches the required files.
    
    No manual searching.
    
3. Schedule Appointment
    
    The AI finds suitable appointment slots.
    
    Patient says
    
    > "Nearest hospital."
    > 
    
    AI filters by:
    
    - Distance
    - Insurance
    - Doctor specialty
    - Availability
    - Patient preference
    - Language preference
    
    Appointment gets booked automatically.
    
1. Patient Notifications

The patient receives:

> "Your cardiology appointment has been scheduled for Tuesday at 3:30 PM."
> 

The AI can also:

- Send reminders
- Provide hospital directions
- Share preparation instructions (e.g., fasting before a test)

1. Track Referral Status

Many referrals never get completed.

The AI continuously tracks the referral.

Possible statuses:

Referral Created
│
Accepted
│
Appointment Scheduled
│
Patient Confirmed
│
Visit Completed
│
Consultation Report Received
│
Referral Closed

If the patient misses the appointment, the AI can:

- Send reminders.
- Offer rescheduling.
- Notify the referring physician if no action is taken.

1. Close the Referral Loop

After the specialist consultation:

The specialist uploads:

- Diagnosis
- Treatment plan
- Medications
- Follow-up recommendations

The AI:

- Imports the consultation into the patient's EHR.
- Notifies the primary care physician.
- Marks the referral as completed.

This ensures continuity of care and prevents referrals from being lost.

### AI Components

| Component | Purpose |
| --- | --- |
| Referral Management Engine | Manages the referral lifecycle |
| LLM | Extracts relevant clinical information from the EHR |
| Clinical Summarization | Generates a concise referral summary |
| Scheduling Engine | Books appointments with specialists |
| Communication Service | Contacts specialist offices and patients |
| EHR/FHIR Integration | Shares records and updates patient charts |
| Status Tracker | Monitors referral progress and completion |

### Example End-to-End Scenario

**Patient:**

> "I've been experiencing chest pain during exercise."
> 

The PCP evaluates the patient and decides to refer them to a cardiologist.

The AI:

1. Creates the referral.
2. Extracts relevant records (ECG, medications, blood pressure history).
3. Generates a referral summary.
4. Finds cardiologists who accept the patient's insurance.
5. Books an appointment for the next available slot.
6. Sends the referral package electronically.
7. Notifies the patient with appointment details.
8. Tracks whether the appointment occurs.
9. Receives the cardiologist's consultation report.
10. Updates the EHR and marks the referral as completed.

### Business Value

For healthcare providers, Referral Execution:

- Reduces administrative workload by automating coordination tasks.
- Minimizes delays caused by missing records or manual communication.
- Increases referral completion rates through proactive scheduling and reminders.
- Improves continuity of care by ensuring specialists and primary care physicians share information.
- Provides end-to-end visibility into referral status, reducing the risk of patients being lost during the referral process.

## Outreach Campaigns

### What problem does it solve?

Healthcare organizations have thousands of patients, but only a subset may need action at any given time—for example:

- Patients overdue for annual checkups
- Patients with uncontrolled diabetes
- Patients due for vaccinations
- Patients who missed appointments
- Patients eligible for a new treatment

Finding these patients and contacting them manually is time-consuming.

**Outreach Campaigns** automate this process by identifying eligible patients, contacting them through multiple channels, and tracking the results.

### Workflow

Clinical Goal
│
▼
Define Patient Cohort
│
▼
Identify Eligible Patients
│
▼
Generate Outreach List
│
▼
Launch Multi-Channel Campaign
│
▼
Patients Respond
│
▼
Book Appointment / Complete Action
│
▼
Track Campaign Outcomes

### Features

1. Define Patient Cohort
    
    The first step is deciding **who should receive the outreach**.
    
    Examples:
    
    Diabetes Campaign
    
    Criteria:
    
    - Age > 18
    - Type 2 Diabetes
    - HbA1c > 8%
    - No visit in last 6 months
    
    ---
    
    Vaccination Campaign
    
    Criteria:
    
    - Age > 65
    - Flu vaccine not received
    - Active patient
    
    ---
    
    Missed Appointment Campaign
    
    Criteria:
    
    - Missed appointment
    - No reschedule
    - Last 30 days
    
    The AI builds these cohorts automatically from EHR data.
    
2. Identify Qualifying Patients
    
    The AI searches the EHR for patients who match the criteria.
    
3. Generate Outreach List
    
    The AI prepares a campaign list with details such as:
    
    - Patient name
    - Contact information
    - Reason for outreach
    - Preferred language
    - Preferred communication channel
    - Assigned physician
    
    Example:
    
    | Patient | Reason |
    | --- | --- |
    | John | Diabetes follow-up |
    | Emma | Mammogram overdue |
    | David | Annual wellness visit |
4. Launch Multi-Channel Campaign
    
    The system contacts patients through multiple communication channels.
    
    Supported channels:
    
    - SMS
    - Email
    - Phone call (AI voice agent)
    - WhatsApp
    - Patient Portal
    - Mobile App notifications
    
    Example SMS:
    
    > "Hello John, you're due for your diabetes follow-up. Reply YES to schedule your appointment."
    > 
    
    Example Voice Agent:
    
    > "Hi John, this is your healthcare provider. You're due for your annual diabetes checkup. Would you like to schedule an appointment?"
    > 
5. Patient Response Handling
    
    The AI understands patient responses.
    
    Examples:
    
    Patient:
    
    > "Book me next Tuesday."
    > 
    
    AI books the appointment.
    
    ---
    
    Patient:
    
    > "Remind me next month."
    > 
    
    The campaign pauses until the requested date.
    
    ---
    
    Patient:
    
    > "I'm no longer interested."
    > 
    
    The AI records the opt-out and updates communication preferences.
    
6. Appointment Scheduling
    
    If the campaign's goal is to bring the patient into the clinic, the AI schedules the appointment automatically using the Intelligent Scheduling module.
    
7. Track Campaign Outcomes
    
    The platform measures campaign performance in real time.
    
    Example dashboard:
    
    Campaign:
    Diabetes Follow-up
    
    Patients Identified:
    5,000
    
    Messages Sent:
    4,950
    
    Delivered:
    4,900
    
    Responses:
    2,300
    
    Appointments Scheduled:
    1,450
    
    Appointments Completed:
    1,210
    
    Conversion Rate:
    24%
    
    This helps healthcare organizations understand how effective the campaign is.
    

### AI Components

| Component | Purpose |
| --- | --- |
| Cohort Builder | Creates patient groups based on clinical criteria |
| Clinical Rules Engine | Evaluates patient eligibility |
| AI Segmentation | Identifies high-priority patients |
| Campaign Manager | Creates and launches campaigns |
| Conversational AI | Handles patient interactions |
| Scheduling Engine | Books appointments automatically |
| Analytics Dashboard | Tracks campaign performance |

### **Example End-to-End Scenario**

**Goal:** Increase flu vaccination rates.

The AI:

1. Finds all patients aged 65+ who haven't received this year's flu vaccine.
2. Creates a list of 3,500 eligible patients.
3. Sends SMS and email reminders.
4. Uses an AI voice agent for patients who don't respond.
5. Patients reply with their preferred appointment times.
6. Appointments are booked automatically.
7. After vaccination, the patient's EHR is updated.
8. The dashboard shows vaccination completion rates and campaign ROI.

### Business Value

For healthcare providers, Outreach Campaigns:

- Improve preventive care by proactively engaging patients.
- Increase appointment bookings and treatment adherence.
- Reduce no-shows with reminders and follow-ups.
- Support value-based care initiatives by closing care gaps.
- Reduce administrative effort through automated patient communication.
- Provide measurable insights into campaign effectiveness and patient engagement.

## Prior Authorization

### What problem does it solve?

Many insurance companies require **approval before they will pay** for certain:

- Medications (e.g., specialty drugs)
- Imaging (MRI, CT scans)
- Surgical procedures
- Medical devices
- Therapies

This approval process is called **Prior Authorization (PA)**.

Without approval:

- Insurance may deny payment.
- The patient may have to pay out of pocket.
- Treatment can be delayed.

Today, clinic staff manually:

- Determine if PA is required.
- Gather clinical documents.
- Complete payer-specific forms.
- Submit the request.
- Respond to additional information requests.
- Monitor approval status.

This process often takes several days.

The AI automates most of these steps.

### Workflow

<aside>
💡

Doctor Orders Treatment
│
▼
AI Detects Prior Authorization Requirement
│
▼
Collect Clinical Evidence
│
▼
Generate Prior Authorization Package
│
▼
Submit to Insurance Company
│
▼
Track Status
│
▼
Approval / Denial / More Information
│
▼
Update EHR & Notify Care Team

</aside>

### Features

1. Doctor Orders Treatment
    
    Example:
    
    Doctor orders
    
    > MRI of the lumbar spine
    > 
    
    or
    
    > Ozempic
    > 
    
    or
    
    > Knee replacement surgery
    > 
    
    Immediately after the order is placed, the AI checks whether prior authorization is required.
    
2. Detect Prior Authorization Requirement
    
    The AI checks:
    
    - Patient's insurance plan
    - Insurance rules
    - Procedure code (CPT)
    - Diagnosis code (ICD-10)
    - Medication
    - Provider network
    
    Example:
    
    ```
    Treatment:
    MRI Lumbar Spine
    
    Insurance:
    Blue Cross
    
    PA Required?
    YES
    ```
    
    No staff member needs to manually verify this.
    
3. Collect Clinical Documentation
    
    The insurance company requires evidence that the treatment is medically necessary.
    
    Instead of staff searching through the patient's chart, the AI automatically gathers:
    
    - Diagnosis
    - Physician notes
    - Lab results
    - Imaging reports
    - Medication history
    - Previous treatments
    - Allergies
    - Relevant clinical guidelines
    
    Example:
    
    For an MRI request:
    
    - Back pain for 8 weeks
    - Physical therapy completed
    - NSAIDs ineffective
    - Neurological symptoms documented
    - X-ray completed
    
    The AI compiles all supporting evidence.
    
4. **Generate Prior Authorization Package**

    
    Different insurers require different forms.
    
    The AI automatically:
    
    - Completes payer-specific forms.
    - Inserts patient demographics.
    - Adds diagnosis and procedure codes.
    - Attaches supporting clinical documents.
    - Creates a structured summary for the reviewer.
    
    Example summary:
    
    ```
    Patient:
    John Smith
    
    Diagnosis:
    Lumbar Radiculopathy
    
    Requested Procedure:
    MRI Lumbar Spine
    
    Reason:
    Persistent pain despite conservative treatment
    
    Supporting Documents:
    ✓ Physician Notes
    ✓ Physical Therapy Report
    ✓ X-ray
    ✓ Medication History
    ```
    
5. Submit to Insurance Company
    
    The AI submits the request through the appropriate channel:
    
    - Payer API
    - Electronic Prior Authorization (ePA)
    - Insurance portal
    - Fax (if required)
    
    The submission is recorded in the EHR.
    
6. Track Status
    
    Insurance companies may take hours or days to respond.
    
    The AI continuously monitors the request.
    
    Example statuses:
    
    ```
    Submitted
          │
    Under Review
          │
    Additional Information Requested
          │
    Approved
    ```
    
    or
    
    ```
    Submitted
          │
    Denied
    ```
    
    No manual follow-up is needed.
    
7. Handle Additional Information Requests
    
    Sometimes insurers ask for more evidence.
    
    Example:
    
    > Please provide the patient's physical therapy records.
    > 
    
    The AI:
    
    - Identifies the requested documents.
    - Retrieves them from the EHR.
    - Sends them automatically or prepares them for staff review.
8. Notify Care Team
    
    Once the payer responds:
    
    If Approved:
    
    - Notify physician.
    - Notify patient.
    - Schedule treatment.
    - Update EHR.
    
    If Denied:
    
    - Notify physician.
    - Explain denial reason.
    - Suggest appeal if appropriate.

### AI Components

| Component | Purpose |
| --- | --- |
| Rules Engine | Determines whether PA is required based on payer rules |
| EHR Integration | Retrieves patient records and updates authorization status |
| Clinical Summarization | Creates concise medical necessity summaries |
| Document Assembly | Collects and organizes required clinical documents |
| Workflow Engine | Submits requests and manages the authorization lifecycle |
| Status Tracker | Monitors payer responses and triggers follow-up actions |
| Notification Service | Alerts physicians, staff, and patients about status changes |

### Example End-to-End Scenario

**Doctor:** Orders an MRI for chronic lower back pain.

The AI:

1. Detects that the patient's insurance requires prior authorization.
2. Retrieves diagnosis, physician notes, previous treatments, and imaging history.
3. Generates the insurer-specific authorization package.
4. Submits the request electronically.
5. Tracks the authorization status.
6. Receives a request for additional physical therapy documentation.
7. Retrieves and submits the required records.
8. Receives approval.
9. Updates the EHR and notifies the physician and scheduling team.
10. The MRI appointment is scheduled.

### Business Value

Prior Authorization automation:

- Reduces administrative workload for clinical staff.
- Speeds up insurance approvals and reduces treatment delays.
- Improves approval rates by ensuring complete, accurate documentation.
- Decreases claim denials caused by missing or incorrect information.
- Provides transparency into authorization status for providers and patients.
- Accelerates patient access to medications, procedures, and diagnostic tests.

### Roles

1. Care co-ordinator
    1. post visit followups
    2. chronic diseace outreach
2. AI-Nurse
    1. Provides clinical triage support
    2. answers foundational medical questions  all within strict clinical guardrails and immediate escalation to licensed staff.

## Potential Features for Xcaliber

Based on this workflow, your product could include:

- **AI Referral Summary:** Automatically generate a concise clinical summary for the specialist.
- **Smart Specialist Matching:** Recommend specialists based on specialty, insurance, location, ratings, and availability.
- **Automated Record Packaging:** Attach only the relevant reports, lab results, and imaging studies.
- **Conversational Appointment Scheduling:** Allow patients to confirm or reschedule via chat or voice.
- **Referral Status Dashboard:** Display referral progress from creation through completion.
- **Patient Reminder System:** Send automated reminders and preparation instructions.
- **Closed-Loop Tracking:** Automatically collect specialist consultation notes and update the referring physician's EHR.
- **Escalation Rules:** Alert care coordinators if a referral remains incomplete beyond a defined timeframe (e.g., 14 days). These features together provide a comprehensive, automated referral management solution.

## **Care Gap Closure**

### What problem does it solve?

A **care gap** is any recommended healthcare service that a patient has not yet completed according to clinical guidelines.

Examples:

- A diabetic patient hasn't had an **HbA1c test** in the last 6 months.
- A woman over 50 hasn't had a **mammogram**.
- A patient with hypertension missed a follow-up visit.
- A patient is due for a flu vaccine.
- A patient hasn't completed a prescribed care plan.

Instead of waiting for providers to manually identify these patients, the AI continuously monitors patient records and proactively ensures they receive the recommended care.

### Workflow

Patient EHR
│
▼
AI analyzes patient history
│
▼
Identify missing screenings/tests/follow-ups
│
▼
Prioritize patients based on risk
│
▼
Generate personalized care plan
│
▼
Reach out to patient
│
▼
Schedule appointment/lab/screening
│
▼
Update EHR
│
▼
Care Gap Closed

### Features

1. The AI continuously scans patient records.
    
    It reads:
    
    - Diagnoses
    - Lab results
    - Medications
    - Procedures
    - Visit history
    - Vaccination records
    - Physician notes
    
    Patient:
    
    Age : 58
    
    Condition:
    Type 2 Diabetes
    
    Last HbA1c:
    10 months ago
    
    Eye Exam:
    2 years ago
    
    Flu Vaccine:
    Missing
    
    Immediately the AI detects multiple care gaps.
    
2. Compare Against Clinical Guidelines

The AI compares patient history with standard clinical guidelines.

Example

| Guideline | Patient Status |
| --- | --- |
| HbA1c every 6 months | ❌ Overdue |
| Annual Eye Exam | ❌ Overdue |
| Kidney Function Test | ❌ Missing |
| Blood Pressure Check | ❌ Missed |
| Colonoscopy | ✅ Completed |

These become **Open Care Gaps**.

1. Risk Prioritization
    
    Not every care gap is equally important.
    
    The AI calculates patient risk.
    
    Example
    
    High Priority
    
    - Cancer screening overdue
    - Uncontrolled Diabetes
    - Abnormal laboratory values
    - Heart failure follow-up
    
    Medium Priority
    
    - Annual wellness visit
    - Vaccinations
    
    Low Priority
    
    - Lifestyle counselling
    
    This helps care coordinators focus first on patients with the greatest clinical need.
    
2. AI Generates Care Plan
    
    Instead of creating multiple independent tasks, the AI bundles them into one care plan.
    
    Example
    
    ```
    Patient:
    John Smith
    
    Required Care
    
    ✓ HbA1c Test
    ✓ Eye Examination
    ✓ Kidney Function Test
    ✓ Blood Pressure Follow-up
    ```
    
    Everything can be completed during one coordinated visit.
    
3. Automated Patient Outreach
    
    Now the Outreach Agent takes over.
    
    Examples
    
    SMS
    
    > Hi John, you're due for your diabetes follow-up, HbA1c test and eye examination. Reply YES to schedule.
    > 
    
    Voice Agent
    
    > Hello John. Our records show you're due for several preventive services. Would you like me to schedule them together?
    > 
4. Intelligent Scheduling
    
    If the patient agrees,
    
    the AI automatically schedules
    
    - Lab appointment
    - Primary care visit
    - Imaging
    - Specialist consultation
    - Vaccination
    
    based on
    
    - Provider availability
    - Patient preference
    - Insurance
    - Location
5. Track Completion
    
    The AI monitors whether the patient actually completed the recommended care.
    
    Example
    
    ```
    HbA1c ✓
    
    Eye Exam ✓
    
    Kidney Test Pending
    
    Follow-up Scheduled
    ```
    
    If something remains incomplete,
    
    the AI automatically starts another outreach cycle.
    
6. Update EHR
    
    After completion,
    
    the AI automatically updates
    
    - Care Plan
    - Clinical Quality Measures
    - Population Health Dashboard
    - Provider Dashboard
    
    The care gap status changes from
    
    ```
    Open
    ```
    
    to
    
    ```
    Closed
    ```
    

### AI Components

| Component | Purpose |
| --- | --- |
| Population Health Engine | Continuously scans all patients |
| Clinical Rules Engine | Applies evidence-based care guidelines |
| Risk Stratification Model | Prioritizes patients by clinical risk |
| LLM | Generates personalized care plans and patient communication |
| Outreach Engine | Sends SMS, Email, WhatsApp, Voice reminders |
| Scheduling Agent | Books appointments and lab tests |
| EHR/FHIR Integration | Reads and updates patient records |
| Analytics Dashboard | Measures care gap closure performance |

### Example End-to-End Scenario

**Patient:** Maria (62 years old) with Type 2 Diabetes.

The AI identifies:

- HbA1c overdue (8 months)
- Annual retinal eye exam overdue
- Kidney function test not completed
- Flu vaccine pending

The AI:

1. Detects four open care gaps.
2. Prioritizes Maria because she has diabetes and multiple overdue services.
3. Generates a personalized care plan.
4. Sends an SMS inviting her to schedule all services.
5. Maria replies, "Next Monday morning."
6. The AI books a lab visit, primary care appointment, and eye exam.
7. After completion, the EHR is updated automatically.
8. The patient's care gaps are marked as closed.

### Business Value

Care Gap Closure helps healthcare organizations improve preventive care, increase compliance with evidence-based guidelines, reduce avoidable hospitalizations, and meet value-based care quality metrics. By combining AI-driven patient identification, outreach, scheduling, and EHR integration, it transforms a manual quality improvement process into a proactive, automated workflow.

### **Analytics Dashboard**

Track:

- Total open care gaps.
- Care gap closure rate.
- Outreach response rate.
- Appointment completion rate.
- Quality measure performance by provider or clinic.

## **Patient Registration & Intake**

### What problem does it solve?

Before any appointment, referral, prior authorization, or treatment, healthcare providers must collect patient information.

Traditionally, patients fill out paper forms or lengthy online questionnaires, and front-desk staff manually verify and enter the data into the EHR.

This process often leads to:

- Long waiting times.
- Incomplete or inaccurate information.
- Duplicate patient records.
- Manual data entry errors.
- Delays in downstream workflows.

The **Patient Registration & Intake Agent** automates this process using conversational AI, verifies the information, and creates or updates the patient's EHR record.

### Workflow

Patient Starts Registration
│
▼
Conversational AI Intake
│
▼
Collect Demographics
│
▼
Verify Identity & Insurance
│
▼
Collect Medical History
│
▼
Generate Structured Intake Summary
│
▼
Create/Update EHR
│
▼
Trigger Other AI Agents

Once intake is complete, the agent automatically enables:

- Intelligent Scheduling
- Referral Execution
- Prior Authorization
- Medication Refill
- Care Gap Detection
- Outreach Campaigns

### Features

1. Conversational Registration
    
    Instead of forms, the patient simply talks to the AI.
    
    Example
    
    Patient:
    
    > "I'm Pratik. I'm a new patient and I'd like to see a cardiologist."
    > 
    
    AI asks naturally:
    
    - Full name
    - Date of birth
    - Phone number
    - Address
    - Emergency contact
    - Preferred language
    - Preferred pharmacy
    
    The conversation feels like speaking to a receptionist.
    
2. Identity Verification
    
    The AI verifies:
    
    - Phone number (OTP)
    - Email
    - Government ID (optional)
    - Existing patient records
    - Duplicate patient detection
    
    Example
    
    Patient:
    
    > "My name is John Smith."
    > 
    
    AI searches the EHR.
    
    Possible outcomes:
    
    - Existing patient found
    - New patient
    - Duplicate detected
    
    This prevents duplicate medical records.
    
3. **Insurance Verification**

    
    The AI asks:
    
    > "Can you upload your insurance card?"
    > 
    
    Then automatically extracts:
    
    - Insurance Provider
    - Policy Number
    - Member ID
    - Coverage dates
    
    The AI verifies eligibility through payer APIs.
    
    If insurance is inactive,
    
    the patient is notified immediately.
    
4. Medical Intake
    
    Now the AI collects clinical information.
    
    Examples
    
    Current symptoms
    
    > "I've had chest pain for two days."
    > 
    
    Past Medical History
    
    - Diabetes
    - Hypertension
    
    Current Medications
    
    - Metformin
    - Aspirin
    
    Allergies
    
    - Penicillin
    
    Family History
    
    - Heart Disease
    
    Lifestyle
    
    - Smoking
    - Alcohol
    - Exercise
    
    Instead of a long questionnaire,
    
    the AI asks only relevant follow-up questions.
    
5. Intelligent Clinical Questioning
    
    The LLM dynamically asks follow-up questions.
    
    Example
    
    Patient:
    
    > "My knee hurts."
    > 
    
    AI:
    
    - Which knee?
    - Pain severity?
    - Injury?
    - Swelling?
    - Fever?
    - Difficulty walking?
    
    This produces much richer clinical information than static forms.
    
6. Document Processing
    
    Patients can upload:
    
    - Insurance cards
    - Driver's License
    - Previous prescriptions
    - Lab reports
    - Referral letters
    - Imaging reports
    
    The AI uses OCR and document understanding to extract structured information.
    
    Example
    
    Upload:
    
    MRI Report (PDF)
    
    AI extracts:
    
    - Diagnosis
    - Date
    - Findings
    - Physician
    - Hospital
7. Generate Intake Summary
    
    Instead of physicians reading multiple pages,
    
    the AI creates
    
    ```
    Patient Summary
    
    Age:
    58
    
    Chief Complaint:
    Chest Pain
    
    Duration:
    2 Days
    
    History:
    Hypertension
    
    Medications:
    Aspirin
    
    Allergy:
    Penicillin
    
    Insurance:
    Blue Cross
    ```
    
    This summary is attached to the EHR.
    
8. Update EHR
    
    The AI creates or updates:
    
    - Demographics
    - Insurance
    - Medical History
    - Allergies
    - Medication List
    - Problem List
    - Intake Notes
    
    Everything is written back using FHIR APIs.
    
9. Trigger Other AI Agents

### AI Components

| Component | Purpose |
| --- | --- |
| Conversational AI | Collect patient information naturally |
| Identity Verification Engine | Verify patient identity and detect duplicates |
| OCR & Document AI | Extract data from insurance cards, IDs, and medical documents |
| Clinical Intake LLM | Conduct adaptive medical interviews |
| Insurance Verification Service | Validate payer eligibility |
| EHR/FHIR Integration | Create or update structured patient records |
| Workflow Orchestrator | Trigger downstream AI agents automatically |

### Example End-to-End Scenario

A new patient visits the clinic and says:

> "I've been having chest pain for three days."
> 

The AI:

1. Collects demographic details through conversation.
2. Verifies identity and insurance.
3. Captures symptoms, medical history, medications, and allergies.
4. Extracts data from the uploaded insurance card.
5. Generates a structured intake summary.
6. Creates a new patient record in the EHR.
7. Automatically schedules an appointment with a cardiologist.
8. Detects any overdue preventive care (if historical data exists).
9. If advanced imaging is ordered later, the Prior Authorization Agent can immediately use the intake data without requiring re-entry.

### **Relationship to Previous Agents**

<aside>
💡

```html
Patient Registration & Intake
│
▼
Patient Profile Created
│
┌───────────┼────────────┐
▼           ▼            ▼
Scheduling  Referral   Prior Authorization
▼           ▼            ▼
Refill    Care Gap    Outreach
						▼
			Clinical Triage
```

</aside>

### Potential Features

1. Conversational Registration

- Voice and chat-based patient registration.
- Multi-language support.
- Dynamic question flow based on patient responses.

2. Identity & Duplicate Detection

- OTP-based verification.
- Duplicate patient record detection using demographics and identifiers.

3. Insurance Verification

- OCR extraction from insurance cards.
- Real-time eligibility verification through payer APIs.

4. Intelligent Clinical Intake

- Adaptive symptom collection.
- Medical history, medications, allergies, family history, and social history capture.
- AI-generated intake summaries.

5. Document Processing

- Upload and process IDs, referrals, prescriptions, lab reports, and imaging reports.
- OCR with structured data extraction.

6. EHR Integration

- FHIR-based creation and update of patient demographics, encounters, conditions, medications, allergies, and documents.

7. Workflow Orchestration

- Automatically trigger downstream agents (Scheduling, Care Gap Closure, Outreach, Referral, Prior Authorization, and Refill Coordination) once registration is complete.

8. Analytics Dashboard

Track:

- Average registration time.
- Registration completion rate.
- Identity verification success rate.
- Insurance verification success rate.
- Duplicate record prevention.
- Intake data completeness.
- Average time saved compared to manual registration.

## After-Hours Automation

### What problem does it solve?

Most clinics operate only during business hours, but patients often need assistance:

- Late at night
- Early morning
- Weekends
- Holidays

Outside office hours, patients typically reach voicemail, leading to:

- Missed appointments
- Delayed medication refills
- Unanswered questions
- Lost referrals
- Poor patient experience

The **After-Hours Automation Agent** acts as a 24/7 virtual front desk, handling routine requests autonomously and escalating urgent cases when necessary.

### Workflow

Patient Calls/Chats (24×7)
│
▼
Conversational AI
│
▼
Identify Patient Intent
│
├── Appointment
├── Medication Refill
├── Referral Status
├── Care Gap Reminder
├── General Questions
└── Clinical Symptoms
│
▼
Route to Appropriate AI Agent
│
▼
Execute Workflow
│
▼
Update EHR & Notify Patient

Unlike previous agents, this one acts as an **AI Orchestrator**.

### Features

1. Patient Initiates Contact
    
    A patient contacts the clinic after hours through:
    
    - Phone
    - Website chatbot
    - Mobile app
    - WhatsApp
    - Patient portal
    
    Example:
    
    > "I'd like to book an appointment."
    > 
2. Intent Detection
    
    The AI classifies the patient's request.
    
    Examples:
    
    | Patient Request | Routed To |
    | --- | --- |
    | Book appointment | Intelligent Scheduling Agent |
    | Refill my medication | Refill Coordination Agent |
    | I need a specialist | Referral Agent |
    | Am I due for my diabetes test? | Care Gap Closure Agent |
    | Why was my MRI denied? | Prior Authorization Agent |
    | I have chest pain | Clinical Triage Agent |
    
    The After-Hours Agent doesn't execute every workflow itself—it delegates to specialized agents.
    
3. Authenticate Patient
    
    Before accessing medical information, the AI verifies:
    
    - Date of birth
    - Phone/email OTP
    - Patient ID
    - Security questions (if needed)
    
    This protects patient privacy and complies with healthcare regulations.
    
4. Execute the Appropriate Workflow
    1. Appointment Scheduling
    
    Patient:
    
    "Book me with my cardiologist next Monday."
    
    The AI invokes the **Scheduling Agent**, books the appointment, updates the EHR, and sends confirmation.
    
    b.  Medication Refill
    
    Patient:
    
    "I need a refill for Metformin."
    
    The AI invokes the **Refill Coordination Agent**, checks eligibility, prepares the refill request, routes it for provider approval if necessary, and informs the patient.
    
    c.  Referral Status
    
    Patient:
    
    "Has my orthopedic referral been approved?"
    
    The AI invokes the **Referral Agent**, retrieves the latest status, and informs the patient.
    
    d. Care Gap Inquiry
    
    Patient:
    
    "Am I due for any tests?"
    
    The AI invokes the **Care Gap Closure Agent**, identifies overdue services, and offers to schedule them immediately.
    
    e. Prior Authorization Status
    
    Patient:
    
    > "Has my MRI been approved by insurance?"
    > 
    
    The AI invokes the **Prior Authorization Agent**, checks the authorization status, and provides an update.
    
5. Answer Common Questions
    
    The AI also handles frequently asked questions.
    
    Examples:
    
    - Clinic hours
    - Provider availability
    - Office location
    - Accepted insurance
    - Prescription pickup
    - Appointment preparation instructions
    - Billing FAQs
    
    These responses come from a knowledge base using **RAG**.
    
6. Clinical Safety Check
    
    If a patient reports symptoms, the AI performs an initial assessment.
    
    Example:
    
    Patient:
    
    > "I'm having chest pain."
    > 
    
    The AI asks follow-up questions:
    
    - When did it start?
    - Pain severity?
    - Shortness of breath?
    - Dizziness?
    
    If emergency symptoms are detected:
    
    - Advise immediate emergency care.
    - Recommend calling emergency services.
    - Notify the on-call provider if configured.
    
    Routine cases are forwarded to the Clinical Triage Agent.
    

7. Escalation

Some requests require human intervention.

Examples:

- Mental health crisis
- Suspected stroke
- Complex insurance disputes
- Controlled substance refill requests

The AI:

- Creates a high-priority task.
- Alerts the on-call provider or nurse.
- Logs the interaction in the EHR.
1. Update EHR
    
    Every interaction is documented automatically.
    
    Examples:
    
    - Conversation transcript
    - Appointment booked
    - Refill requested
    - Referral status checked
    - Patient questions answered
    - Escalations created
    
    The patient's medical record remains up to date before staff return.
    

### AI Components

| Component | Purpose |
| --- | --- |
| Conversational AI | Understands patient requests via voice or chat |
| Intent Classification | Identifies the requested workflow |
| Agent Orchestrator | Routes requests to Scheduling, Referral, Refill, Care Gap, or Prior Authorization agents |
| RAG Knowledge Base | Answers clinic, billing, and policy questions |
| Authentication Service | Verifies patient identity |
| Clinical Safety Engine | Detects urgent symptoms and initiates escalation |
| EHR/FHIR Integration | Records interactions and workflow outcomes |

### **Example End-to-End Scenario**

At **10:30 PM**, a patient messages:

> "I need to refill my blood pressure medicine and also schedule my annual checkup."
> 

The After-Hours Automation Agent:

1. Authenticates the patient.
2. Detects two intents: medication refill and appointment scheduling.
3. Invokes the **Refill Coordination Agent** to process the refill.
4. Invokes the **Scheduling Agent** to book the annual checkup.
5. The Scheduling Agent identifies an overdue cholesterol screening through the **Care Gap Closure Agent**.
6. The appointment is updated to include the required lab work.
7. The patient receives confirmation immediately.
8. All actions are documented in the EHR.

No clinic staff are involved, even though the request occurred outside business hours.

### Relationship with Previous Agents

Patient Contacts AI (24×7)
│
▼
After-Hours Automation Agent
│
┌───────┼────────┬────────┬─────────┬─────────┐
▼       ▼        ▼        ▼         ▼
Scheduling Refill  Referral Care Gap Prior Auth
         │
        ▼
Clinical Triage (if symptoms reported)

**Think of this agent as the "control tower" of your platform.** It is not another standalone workflow; it is the **24/7 orchestration layer** that receives patient requests, invokes the appropriate specialized agent, and provides a seamless patient experience regardless of the time of day.

### Potential Features for Your PRD

1. 24×7 Omnichannel AI Assistant

- Voice, chat, WhatsApp, mobile app, and patient portal support.
- Natural language understanding for patient requests.

1. Intent Detection & Agent Orchestration
    
    Classify patient intent.
    
    Route requests to Scheduling, Refill, Referral, Care Gap, Prior Authorization, or Clinical Triage agents.
    
    Support multiple intents within a single conversation.
    
2. Knowledge Assistant
    - Answer FAQs using RAG.
    - Clinic hours, locations, insurance, billing, provider information, and preparation instructions.
3. Patient Authentication
    - OTP verification.
    - Secure access to patient-specific information.
4. Clinical Safety & Escalation
    - Screen reported symptoms.
    - Detect emergencies.
    - Escalate high-risk cases to on-call clinicians.
5. Workflow Automation
    - Complete supported workflows without human intervention whenever possible.
    - Create tasks for staff when manual review is required.
6. EHR Integration
    - Record conversations.
    - Update appointments, refill requests, referrals, and authorization status.
    - Maintain a complete audit trail.
7. **Analytics Dashboard**
    
    Track:
    
    - After-hours conversations.
    - Automation rate.
    - Requests resolved without staff intervention.
    - Average response time.
    - Escalation rate.
    - Patient satisfaction.
    - Most common after-hours requests.

## Clinical Triage Support

### What problem does it solve?

When patients contact a healthcare provider, the first question is often:

> **"How urgent is this case?"**
> 

Today, nurses or clinical staff manually assess symptoms over the phone and determine whether the patient should:

- Go to the Emergency Department (ED)
- Visit urgent care
- Schedule a same-day appointment
- Book a routine appointment
- Follow self-care instructions

This process is time-consuming and not available 24×7.

The **Clinical Triage Support Agent** uses AI to assess symptoms, determine clinical urgency, recommend the appropriate level of care, and seamlessly trigger the next workflow.

### Workflow

Patient Reports Symptoms
│
▼
Conversational AI Assessment
│
▼
Adaptive Clinical Questioning
│
▼
Risk Stratification
│
▼
Determine Acuity Level
│
▼
Recommended Next Action
│
┌────────┼────────┬───────────┬──────────┐
▼                                ▼                              ▼                                          ▼
Emergency      Same-Day                  Routine                              Self-Care
Care                      Visit                           Visit                                   Advice
                                │
                                 ▼
              Trigger Appropriate AI Agent
                              │
                             ▼
            Update EHR & Notify Care Team

### Features

1. Patient Report Symptoms
    
    The patient interacts through:
    
    - Phone
    - Chatbot
    - Mobile App
    - WhatsApp
    - Patient Portal
    
    Example:
    
    > "I've had chest pain since this morning."
    > 
    
    The Clinical Triage Agent is automatically invoked.
    
2. Adaptive Clinical Questioning
    
    Example:
    
    Patient:
    
    > "My chest hurts."
    > 
    
    AI asks:
    
    - When did it start?
    - Pain severity (1–10)?
    - Is the pain constant or intermittent?
    - Shortness of breath?
    - Pain radiating to the arm or jaw?
    - Fever?
    - Existing heart disease?
    
    The questions depend on previous answers.
    
3. Risk Stratification
    
    The AI combines:
    
    - Current symptoms
    - Age
    - Medical history
    - Chronic diseases
    - Medications
    - Allergies
    - Recent lab results
    - Previous encounters
    
    to estimate clinical urgency.
    
    Example
    
    Patient
    
    ```
    Age:
    72
    
    History:
    Heart Disease
    
    Symptoms:
    Chest Pain
    Shortness of Breath
    ```
    
    Risk Score:
    
    **High**
    
4. Determine Acuity Level
    
    The AI classifies patients into priority levels.
    
    | Level | Action |
    | --- | --- |
    | Emergency | Immediate Emergency Department / 911 |
    | High | Same-day physician visit |
    | Medium | Appointment within 24–48 hours |
    | Low | Routine appointment |
    | Minimal | Self-care guidance |
5. Evidence-Based Guidance
    
    The AI provides guidance based on approved clinical protocols.
    
    Example
    
    Patient:
    
    > "I have a sore throat for one day."
    > 
    
    AI:
    
    - Drink fluids
    - Monitor fever
    - Seek medical attention if symptoms worsen
    
    Another example
    
    Patient:
    
    > "Chest pain with difficulty breathing."
    > 
    
    AI:
    
    > Your symptoms may indicate a medical emergency. Please call emergency services immediately or visit the nearest emergency department.
    > 
    
    The AI **supports** decision-making but does **not replace clinical judgment**.
    
6. Trigger Downstream Agents
    
    Once triage is complete, the Clinical Triage Agent coordinates with the rest of the platform.
    
    - Emergency Case
    - Notify on-call clinician
    - Create high-priority alert
    - Document assessment
    
    1. Same-Day Visit
    
    - Invoke the **Scheduling Agent**.
    - Book the earliest available appointment.
    
    2. Specialist Needed
    
    Invoke the **Referral Agent, Generate referral request.**
    
    1. Diagnostic Test Needed
        
        Invoke the **Prior Authorization Agent** if insurance approval is required.
        
    2. Routine Follow-up
        
        Invoke the **Care Gap Closure Agent,** Schedule overdue preventive services if applicable.
        
    3. Medication Issue
        
        Invoke the **Medication Refill Coordination Agent**.
        
7. Notify Clinical Staff
    
    If escalation is required,
    
    the AI sends:
    
    - Symptom summary
    - Risk assessment
    - Recommended action
    - Patient contact information
    
    Example
    

```
Patient:
John Smith

Chief Complaint:
Chest Pain

Risk:
High

Recommendation:
Immediate Evaluation

Appointment:
Today 2:30 PM
```

1. Update EHR
    
    Everything is documented automatically.
    
    Stored information:
    
    - Symptoms
    - AI assessment
    - Triage questions
    - Recommended disposition
    - Risk level
    - Escalation actions
    - Conversation transcript
    
    The provider reviews a structured summary instead of reading the full conversation.
    

### AI Components

| Component | Purpose |
| --- | --- |
| Conversational AI | Collect patient symptoms naturally |
| Clinical Questioning Engine | Ask adaptive, symptom-specific questions |
| LLM + Clinical Rules Engine | Interpret symptoms using evidence-based guidelines |
| Risk Stratification Model | Estimate urgency and prioritize patients |
| Workflow Orchestrator | Trigger Scheduling, Referral, Prior Authorization, Care Gap, or Refill agents |
| Notification Service | Alert clinicians for urgent cases |
| EHR/FHIR Integration | Store assessments and update patient records |

### **Example End-to-End Scenario**

At **8:00 PM**, a patient messages:

> "I've been experiencing severe abdominal pain and vomiting."
> 

The Clinical Triage Agent:

1. Authenticates the patient (if required).
2. Collects symptom details through adaptive questioning.
3. Reviews relevant medical history from the EHR.
4. Assigns a **high-acuity** risk level.
5. Advises immediate evaluation at the emergency department.
6. Notifies the on-call physician.
7. Documents the complete triage assessment in the EHR.

Another example:

A patient reports:

> "My blood sugar has been high for several days."
> 

The agent:

1. Determines that this is **non-emergent**.
2. Invokes the **Scheduling Agent** to arrange a same-week appointment.
3. Invokes the **Care Gap Closure Agent** to check for overdue HbA1c testing.
4. If medication adjustments may be needed, flags the **Medication Refill Coordination Agent**.
5. Records all actions in the EHR.

### Relationship with the Other Agents

The **Clinical Triage Support Agent** acts as the **clinical decision hub** of your multi-agent platform.

```
                 Patient Reports Symptoms
                           │
                           ▼
              Clinical Triage Support Agent
                           │
      ┌──────────┬─────────┼──────────┬──────────┐
      ▼          ▼         ▼          ▼          ▼
 Scheduling   Referral  Prior Auth  Care Gap   Medication
    Agent       Agent      Agent      Agent      Refill
                           │
                           ▼
                After-Hours Automation
                           │
                           ▼
                 EHR / Care Team Updates
```

Unlike the previous agents, which automate operational tasks, the **Clinical Triage Support Agent** makes the **first clinical decision** about the patient's urgency and uses that decision to orchestrate the appropriate downstream workflow. It serves as the intelligent entry point for symptom-driven patient care while ensuring every action is documented in the EHR.

### **Potential Features for Your PRD**

1. AI Symptom Assessment
    - Natural language symptom collection.
    - Adaptive follow-up questioning.
    - Support for voice and chat interactions.
2. Clinical Risk Stratification
    - Categorize patients by acuity (Emergency, High, Medium, Low).
    - Incorporate demographics, medical history, medications, allergies, and recent clinical data.
3. Evidence-Based Decision Support
    - Recommendations aligned with configurable clinical protocols.
    - Explain recommended next steps to patients in plain language.
4. Multi-Agent Orchestration
    - Trigger Scheduling for appointments.
    - Trigger Referral for specialist care.
    - Trigger Prior Authorization when diagnostics or procedures require approval.
    - Trigger Care Gap Closure for overdue preventive care.
    - Trigger Medication Refill for prescription-related requests.
5. Escalation Management
    - Alert on-call clinicians or nurses for high-risk cases.
    - Generate high-priority tasks within the care team's workflow.
6. Clinical Documentation
    - Generate structured triage summaries.
    - Store conversation transcripts and recommendations in the EHR.
7. EHR/FHIR Integration
    - Read patient history before assessment.
    - Write triage outcomes, encounter notes, and follow-up recommendations back to the EHR.
8. Analytics Dashboard
    - Track number of triage assessments.
    - Track acuity distribution.
    - Track emergency escalation rate.
    - Track average triage time.
    - Track same-day appointment conversion rate.
    - Track referral generation rate.
    - Track triage-to-treatment turnaround time.