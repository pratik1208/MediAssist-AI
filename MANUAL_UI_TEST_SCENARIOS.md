# Manual UI Test Scenarios

Four ready-to-run examples for testing the agents by hand in the browser.
Every name, phone number, and date below matches the synthetic data already
seeded in the dev database (`manage.py seed_all`), so you can follow these
steps exactly as written.

## Before you start

| What | Where |
|---|---|
| Backend | `cd backend && ./venv/bin/python manage.py runserver 8001` |
| Frontend | `cd frontend && npm run dev` → http://localhost:5173 |
| Staff pages | Log into http://localhost:8001/admin/ with a staff account first (same browser), then open the `/staff/...` pages |
| OTP code | **`123456`** works for every patient (dev shortcut, DEBUG only) |

---

## Example 1 — After-hours front desk chat (Agent 9 + refills + scheduling)

**Patient: Meera Iyer · phone `9812345670` · DOB `1992-03-14`** (6 medications on file, including a controlled substance)

1. Open **http://localhost:5173/** (the front desk chat is the home page).
2. Ask a question before verifying: `do you accept Star Health insurance?`
   → Answered immediately from the knowledge base — FAQs don't need identity.
3. Now ask for something personal, in one message:
   `I need a refill of my amlodipine and can you also check my upcoming appointments?`
   → The chat should ask you to **verify your identity** (both requests are queued, not lost).
4. In the verify card: phone `9812345670`, DOB `1992-03-14` → **Send code** → enter `123456`.
   → Both queued requests are answered automatically: her medication list (with refills left,
   Alprazolam tagged **controlled**) and her appointments.
5. Try the safety net: type `actually I am having crushing chest pain`
   → Red emergency reply, no follow-up questions; a critical task/alert is raised for staff.
6. Wrong-details check (fresh browser tab): verify with phone `9812345670` but DOB `1990-01-01`
   → The failure message must be identical to using a completely unknown phone number
   (the chat never reveals who is registered).

---

## Example 2 — New patient: register → symptom check → book (Agents 2, 3, 1)

**Patient: you invent one** — e.g. *Rohan Test, phone `9899000011`, DOB `1994-06-15`* (any unused phone works).

1. Open **http://localhost:5173/register**. Chat through registration: give the name, DOB,
   and phone above when asked; mention a symptom when the intake asks how you're feeling
   (e.g. `I've had a mild cough for two days`).
2. When the OTP box appears, enter `123456` → "Identity verified ✓".
3. After completion, follow the **Book an appointment** link (your new patient is pre-selected).
4. Or first go to **/triage** and describe symptoms: `headache and slight nausea since this morning`
   → answer the protocol's questions → you get an urgency rating and, for bookable
   dispositions, a **Book an appointment** button that hands off to scheduling with your
   symptoms pre-filled.
5. In the scheduling chat, pick one of the offered slots → booking confirmation with
   appointment number.

---

## Example 3 — Staff console sweep: work every queue (Agents 3, 4, 5, 6, 9)

**Log into `/admin` with a staff account first**, then work through the queues — each one has
seeded items waiting in a different state:

1. **Refills — http://localhost:5173/staff/refills**
   The queue holds pending requests, including **Alprazolam for Meera Iyer / Asha Verma**
   (controlled — flagged, never auto-processed). Approve one, reject another with a reason,
   and use "request a visit" on a third. Each action notifies the patient (see the backend
   console for the simulated SMS).
2. **Referrals — http://localhost:5173/staff/referrals**
   Six referrals spanning the whole lifecycle. Open **Rina Shah's Dermatology referral**
   (status *created*) and accept it with a specialist. Also look at **Vijay Menon's
   Cardiology referral** — already at *appointment scheduled* with a real booked visit —
   and **Nasreen Sheikh's** (*stalled*, the follow-up case).
3. **Prior authorizations — http://localhost:5173/staff/priorauth**
   Four requests: **Kamala Iyer's MRI** is at *ready to submit* — open it, submit it, then
   poll for the payer decision. **Harold Fernandes'** is *denied* with a denial reason and
   an appeal suggestion; **Gurpreet Singh's** sits mid-flight at *submitted*.
4. **Escalations — http://localhost:5173/staff/escalations**
   Emergency alerts from triage (chest pain, self-harm) plus controlled-substance alerts.
   Acknowledge one.
5. **Front-desk tasks — http://localhost:5173/staff/frontdesk/tasks**
   All six categories at open/claimed/resolved. Type your name in "Claiming as", claim the
   critical mental-health task, then resolve it. Toggle "Show resolved" to see history.

---

## Example 4 — Outreach campaign + care gaps closing the loop (Agents 7, 8)

1. **Care gaps — http://localhost:5173/staff/caregaps**
   The worklist shows ~35 open gaps (mammogram, flu shot, and the diabetic HbA1c / eye-exam
   gaps). Open **Kamala Iyer's** patient panel — 4 open gaps and a **draft care plan**.
   Back on the dashboard, click **Send plans to outreach** → her plan goes out as a real
   (simulated) SMS in her language (Tamil), visible in the backend console.
2. **Outreach — http://localhost:5173/staff/outreach**
   "Flu shot 65+" is already **running** with a live funnel (booked / snoozed / opted-out /
   contacted). Open the untouched draft **"Overdue annual check-up"** → **Preview cohort**
   (who matches and why) → **Launch** → messages go out per patient language.
3. **Simulate a patient replying to the SMS** (terminal):
   ```bash
   curl -s http://localhost:8001/api/outreach/webhook/ -X POST \
     -H "Content-Type: application/json" \
     -d '{"from": "9820010008", "text": "yes please book me in"}'
   ```
   (9820010008 = Farida Khan, still at *contacted* in the flu campaign.) The AI classifies
   the reply, auto-books a real appointment, and her funnel state moves to **scheduled**.
4. Reply from a number that is in **no** campaign — it lands at the front desk instead of
   being dropped:
   ```bash
   curl -s http://localhost:8001/api/outreach/webhook/ -X POST \
     -H "Content-Type: application/json" \
     -d '{"from": "9899777001", "text": "what are your clinic hours?"}'
   ```
   → a front-desk session answers the question from the knowledge base.

---

## Handy patient reference

| Patient | Phone | DOB | Good for testing |
|---|---|---|---|
| Meera Iyer | 9812345670 | 1992-03-14 | Front-desk chat: 6 medications incl. controlled |
| Kamala Iyer | 9820010001 | 1954-02-18 | 4 care gaps, draft care plan, prior-auth ready, flu campaign (booked) |
| Ramesh Deshpande | 9820010002 | 1958-03-07 | Snoozed in flu campaign, Marathi messages |
| Vijay Menon | 9820020002 | 1965-03-07 | Referral at *appointment scheduled* |
| Rina Shah | 9820020003 | 1979-04-24 | Referral at *created* (accept it in Example 3) |

Everything is safe to click. Re-running `./venv/bin/python manage.py seed_all` tops the data
back up at any time without ever duplicating rows — note it moves workflows *forward* only
(e.g. once Farida replies "book me", she stays booked; it won't rewind her to "contacted").
