# BUILD_STEPS_Agent_1

# BUILD_STEPS — MediAssist AI: Intelligent Scheduling

Every step needed to go from an empty folder to a deployed, working product, on your own. Reference `PRD.md` for what you’re building and `SPEC.md` for exact schemas/algorithms — this document only tells you *what to do next*, not the implementation, since the point is to write it yourself.

Work top to bottom. Don’t skip ahead to Phase 6 (AI) before Phase 4 (business logic) works and is tested — each phase assumes the previous one is solid.

## Phase 0 — Install what you need

- [ ]  Install Python 3.12+ (`python3 --version` to check)
- [ ]  Install Node.js 22 LTS (`node --version` to check)
- [ ]  Install Git (`git --version` to check)
- [ ]  Install Docker Desktop (for a local Postgres that matches production — avoids “works on SQLite, breaks on Postgres” bugs later)
- [ ]  Install a code editor (VS Code or your preference)
- [ ]  Create a GitHub account if you don’t have one; create a new empty repo called `mediassist-scheduling`
- [ ]  Create an Anthropic Console account (console for API access), generate an API key, add billing
- [ ]  Create a free LangSmith account, generate an API key

## Phase 1 — Repo scaffolding

- [ ]  Inside your `MedAssist AI` folder: `git init`
- [ ]  `git remote add origin <your GitHub repo URL>`
- [ ]  Create two subfolders: `backend/` and `frontend/`
- [ ]  Create a root `.gitignore` covering: `__pycache__/`, `.pyc`, `venv/`, `node_modules/`, `.env`, `.env.local`, `dist/`, `build/`
- [ ]  Copy `PRD.md`, `SPEC.md`, and `CLAUDE.md` into the repo root (you already have these)
- [ ]  `git add -A && git commit -m "Initial repo structure and docs"`
- [ ]  `git push -u origin main`

## Phase 2 — Backend environment

- [ ]  `cd backend`
- [ ]  `python3 -m venv venv`
- [ ]  Activate it (`source venv/bin/activate` on Mac/Linux, `venv\Scripts\activate` on Windows)
- [ ]  `pip install django djangorestframework django-cors-headers anthropic langsmith psycopg[binary] python-dotenv pytest-django`
- [ ]  `pip freeze > requirements.txt`
- [ ]  `django-admin startproject config .` (note the trailing dot — keeps `manage.py` at `backend/` root)
- [ ]  `python manage.py startapp scheduling`
- [ ]  In `config/settings.py`: add `'rest_framework'`, `'corsheaders'`, `'scheduling'` to `INSTALLED_APPS`
- [ ]  Add `corsheaders.middleware.CorsMiddleware` to `MIDDLEWARE` (near the top) and set `CORS_ALLOWED_ORIGINS` for later
- [ ]  Create `backend/.env` with `ANTHROPIC_API_KEY`, `LANGSMITH_API_KEY`, `DJANGO_SECRET_KEY`, `DATABASE_URL` — load it via `python-dotenv` at the top of `settings.py`
- [ ]  Start local Postgres: `docker run --name mediassist-db -e POSTGRES_PASSWORD=devpass -e POSTGRES_DB=mediassist -p 5432:5432 -d postgres`
- [ ]  Point `DATABASES` in `settings.py` at that container using your `DATABASE_URL`
- [ ]  `python manage.py migrate` — confirms Django can talk to Postgres
- [ ]  `python manage.py runserver` — confirms the server boots (you’ll see the default Django page at localhost:8000)

## Phase 3 — Data models

- [ ]  In `scheduling/models.py`, define `Doctor`, `Patient`, `Appointment`, `Waitlist`, `Conversation`, `Message` — exact fields are in `SPEC.md` → “Data model”
- [ ]  `python manage.py makemigrations scheduling`
- [ ]  `python manage.py migrate`
- [ ]  In `scheduling/admin.py`, register all six models; add the custom `cancel_and_promote` admin action on `Appointment` (see `SPEC.md` → “Django Admin cancel”)
- [ ]  `python manage.py createsuperuser`
- [ ]  Run the server, log into `/admin/`, confirm all six models appear and you can add a row manually
- [ ]  Write a management command `scheduling/management/commands/seed_doctors.py` that creates 6–8 fake doctors across specialties with working hours
- [ ]  Run it: `python manage.py seed_doctors`; confirm the doctors show up in `/admin/`

## Phase 4 — Core business logic (no AI yet)

Build and test this in complete isolation from Claude — it’s pure Python/Django and should work with hardcoded inputs before any AI touches it.

- [ ]  Create `scheduling/services.py`
- [ ]  Implement `generate_blocks()` — splits a doctor’s `working_hours` into candidate slots of `avg_consult_minutes` length
- [ ]  Implement `find_available_slots(doctor, date_from, date_to)` per the algorithm in `SPEC.md`
- [ ]  Implement `book_appointment(doctor, patient, start, end, reason, urgency)`
- [ ]  Implement `promote_next_waitlisted(doctor, freed_start, freed_end)` per `SPEC.md`
- [ ]  Implement `cancel_appointment(appointment)` — sets status to cancelled, then calls `promote_next_waitlisted`
- [ ]  Write `scheduling/tests/test_services.py` — at minimum: a slot-finding test with overlapping bookings, a booking test, and a cancel-then-promote test with two waitlisted patients of different urgency
- [ ]  `pytest` — all green before moving on. Don’t proceed to Phase 5 with failing tests.

## Phase 5 — DRF API layer (still no AI)

- [ ]  Create `scheduling/serializers.py` — serializers for `Doctor`, `Appointment`, `Waitlist`
- [ ]  Create `scheduling/views.py` — endpoints for listing doctors, listing slots, booking, cancelling, listing waitlist (contract is in `SPEC.md` → “API contract”)
- [ ]  Wire `scheduling/urls.py`, then `include()` it from `config/urls.py`
- [ ]  Manually test every endpoint with `curl` or a REST client (Insomnia/Postman) using hardcoded JSON bodies — confirm booking and cancellation work end-to-end purely through the API, with zero AI involved

## Phase 6 — AI integration layer

- [ ]  Write the system prompt as a constant (never diagnose, defer to caution on ambiguous urgency)
- [ ]  Write the `extract_booking_intent` tool schema exactly as specified in `SPEC.md`, including `needs_clarification`
- [ ]  Write `extract_intent(conversation_history)` — calls the Anthropic API with `tool_choice` forced to `extract_booking_intent`
- [ ]  Write `handle_patient_message(conversation_history)` — the orchestration function: calls `extract_intent`, checks `needs_clarification`, checks `urgency == "emergency"`, otherwise calls `find_available_slots`
- [ ]  Wrap the Claude call with LangSmith tracing
- [ ]  Test this manually via `python manage.py shell` — call `handle_patient_message` directly with a few sample message lists and print the result. No HTTP, no frontend yet.
- [ ]  Write the red-flag test suite: a fixed list of phrases that must always produce `urgency: "emergency"`
- [ ]  Write the vague-phrase test suite: phrases that must always produce `needs_clarification: true`
- [ ]  Run both suites, adjust the system prompt until they pass reliably

## Phase 7 — Chat endpoint (streaming)

- [ ]  Write an async Django view for `/api/chat/` that calls `handle_patient_message` and streams the reply via `StreamingHttpResponse` (SSE)
- [ ]  Add it to `scheduling/urls.py`
- [ ]  Test with `curl --no-buffer` (or a small Python script consuming the stream) to confirm tokens arrive incrementally, not all at once

## Phase 8 — Frontend setup

- [ ]  From the repo root: `npm create vite@latest frontend -- --template react-ts`
- [ ]  `cd frontend && npm install`
- [ ]  `npm install tailwindcss @tailwindcss/vite` (Tailwind v4 — no separate config file needed)
- [ ]  Add the Tailwind plugin to `vite.config.ts` and `@import "tailwindcss";` to `src/index.css`
- [ ]  `npm install react-router-dom @tanstack/react-query`
- [ ]  Create `frontend/.env` with `VITE_API_BASE_URL=http://localhost:8000`
- [ ]  `npm run dev`, confirm the default Vite page loads with Tailwind styling working (test with a `className="text-3xl font-bold"` on something)

## Phase 9 — Chat UI

- [ ]  Build a small typed API client (fetch wrapper reading `VITE_API_BASE_URL`)
- [ ]  Build a `ChatWindow` component: message list + input box
- [ ]  Implement SSE consumption (`EventSource` or `fetch` + `ReadableStream`) to render the streamed reply as it arrives
- [ ]  Build a slot-picker component that renders buttons when the AI proposes times
- [ ]  Wire slot selection to `POST /api/appointments/`
- [ ]  Add loading, error, and empty states
- [ ]  Manual end-to-end test: type symptoms in the browser, see the AI’s reply stream in, pick a slot, confirm, then check `/admin/` to see the appointment saved

## Phase 10 — Integration polish

- [ ]  Fix CORS between `localhost:5173` (frontend) and `localhost:8000` (backend) — add the frontend origin to `CORS_ALLOWED_ORIGINS`
- [ ]  Test the emergency path end to end: describe a red-flag symptom in the UI, confirm you see the safety message and no slots
- [ ]  Test cancel → waitlist promotion end to end via `/admin/`
- [ ]  Test edge cases: no doctors for a specialty, no slots available (should offer waitlist), ambiguous message (should ask a follow-up, not guess)

## Phase 11 — Deployment

- [ ]  Commit and push everything so far
- [ ]  Create a Railway (or Render) project; add a PostgreSQL plugin/service
- [ ]  Deploy the backend: connect the GitHub repo, set root directory to `backend/`, set env vars (`ANTHROPIC_API_KEY`, `LANGSMITH_API_KEY`, `DJANGO_SECRET_KEY`, the platform’s `DATABASE_URL`, `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`)
- [ ]  Run migrations against the deployed database (Railway/Render shell, or a release command)
- [ ]  Create a superuser and run `seed_doctors` against production
- [ ]  Deploy the frontend: connect Vercel to the repo, set root directory to `frontend/`, set `VITE_API_BASE_URL` to the deployed backend URL
- [ ]  Update the backend’s `CORS_ALLOWED_ORIGINS` to include the live Vercel URL
- [ ]  Smoke-test the full flow on the live URL, start to finish

## Phase 12 — Polish

- [ ]  Write a `README.md`: setup instructions, architecture summary, links to `PRD.md`/`SPEC.md`
- [ ]  Write a short demo script for showing it off
- [ ]  Optional: add Sentry to both frontend and backend for error visibility
- [ ]  Optional: a basic GitHub Actions workflow that runs `pytest` on every push