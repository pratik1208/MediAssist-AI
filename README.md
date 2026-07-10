# MediAssist AI

A multi-agent medical clinic assistant. Patients chat with AI agents that handle
scheduling, registration, clinical triage, and prescription refills — with
deterministic safety checks (red-flag symptom screening) running **before** any
AI call.

## Repo layout

```
backend/    Django + DRF API (all agents live here)
frontend/   React (Vite + TypeScript + Tailwind) chat UI
steps/      Build-plan documents (one per agent)
specifications/  Detailed specs referenced by the build plans
PRD.md, SCHEMA.md  Product and data-model docs
```

## Prerequisites

- Python 3.12+ (the project venv already exists at `backend/venv`)
- Node.js 22 LTS
- PostgreSQL running locally (the backend reads connection details from `backend/.env`)

## 1. Run the backend

```bash
cd backend

# If the venv doesn't exist yet:
python3 -m venv venv
./venv/bin/pip install -r requirements.txt

# Environment — create backend/.env with:
#   DB_ENGINE=django.db.backends.postgresql
#   DATABASE_NAME=mediassist
#   DB_USER=postgres
#   DB_PASSWORD=devpass
#   DB_HOST=localhost
#   DB_PORT=5432
#   AI_PROVIDER=openai            # or anthropic / ollama
#   OPENAI_API_KEY=sk-...         # key for whichever provider you chose
#   LANGSMITH_API_KEY=lsv2_...    # tracing (project: MediAssist-AI)

./venv/bin/python manage.py migrate

# Seed demo data (all idempotent — safe to re-run):
./venv/bin/python manage.py seed_doctors
./venv/bin/python manage.py seed_protocols
./venv/bin/python manage.py seed_prescriptions

# Admin access (first time only):
./venv/bin/python manage.py createsuperuser

# Start the API on port 8001 (the frontend expects this port):
./venv/bin/python manage.py runserver 8001
```

Useful backend URLs:

- `http://localhost:8001/admin/` — Django admin
- `http://localhost:8001/scalar/` — interactive API docs

### Backend tests

```bash
cd backend
./venv/bin/python -m pytest            # fast suite (AI calls are blocked)
./venv/bin/python -m pytest -m live_model   # live AI safety suites (costs API credits)
```

## 2. Run the frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. You get the scheduling chat: describe symptoms
and a preferred time (e.g. *"I've had a mild fever since yesterday, can I see
someone tomorrow morning?"*), the AI proposes appointment slots, and clicking a
slot books it. Pick a patient in the top-right corner first — booking needs one.

Notes:

- In dev, Vite proxies every `/api/*` request to `http://localhost:8001`, so
  there is **no CORS setup needed**. If your backend runs elsewhere, start the
  frontend with `BACKEND_URL=http://localhost:9000 npm run dev`.
- `frontend/.env` has `VITE_API_BASE_URL` — leave it empty in dev (the proxy
  handles it); set it to the deployed backend URL in production.
- Emergency check: type a red-flag symptom (e.g. "crushing chest pain") — you
  should see the emergency message and no booking options. This path is
  deterministic and never calls the AI.

## 3. Production build (frontend)

```bash
cd frontend
npm run build     # type-checks and outputs dist/
```

When deploying, set `VITE_API_BASE_URL` to the live backend URL and add the
frontend's origin to `CORS_ALLOWED_ORIGINS` in `backend/config/settings.py`.
