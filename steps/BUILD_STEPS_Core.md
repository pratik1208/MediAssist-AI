# BUILD_STEPS_Core — first steps for the `core` app

The `core` app is the shared foundation every agent imports (`SPEC_Core.md` §3–4).
Nothing else should be built until these are in place, because Agents 1–9 all
depend on `core.ai`, `core.events`, `core.notifications`, `core.models`, etc.

Do these **in order**. Each step has a "Done when" check so you know it's finished.

---

## Step 0 — Fix the blocker: `INSTALLED_APPS` (do this first)

There is a **missing comma** in `backend/config/settings.py`:

```python
    "core"          # <-- no comma
    "scheduling",
```

Python silently concatenates these into one string `"corescheduling"`, so
**neither `core` nor `scheduling` is registered right now.** Migrations and the
admin will not work until this is fixed:

```python
    "core",
    "scheduling",
```

**Done when:** `python manage.py check` runs with no `App ... isn't installed` error.

---

## Step 1 — Reconcile the models with `SPEC_Core.md` before migrating

The canonical code in `SPEC_Core.md` §4.3 expects field names that your current
`core/models.py` does not have yet. Decide these now — changing them after data
exists is painful. Mismatches to resolve:

| Spec code expects (`notifications.py`) | Your model currently has | Action |
|---|---|---|
| `patient.phone` | `contact_number` | rename, or adjust the spec code to `contact_number` |
| `patient.preferred_language` | `default_language` | pick one name and use it everywhere |
| `prefs.get("opted_out", {}).get(channel)` — a **dict** | `opted_out` documented as a **list** `["email","voice"]` | pick one shape; dict (`{"sms": true}`) matches the spec code |
| `SentNotification(..., template=template, ...)` | `SentNotification` has **no `template` field** | add a `template = CharField(...)` field |
| `Conversation.started_at = DateTimeField()` (no default) | — | add `auto_now_add=True` or `default=timezone.now`, else every insert must pass it |

**Done when:** the field names in your models match whatever you use in
`core/notifications.py` (Step 5). Keep them consistent — that's the whole point.

---

## Step 2 — Make and apply migrations for `core`

Postgres is the target DB (`SPEC_Core.md` §1). Confirm `.env` has `DB_ENGINE` /
`DATABASE_URL` pointing at Postgres, then from `backend/`:

```bash
python manage.py makemigrations core
python manage.py migrate
```

**Done when:** tables exist for `Patient, Doctor, Conversation, Message,
OTPChallenge, SentNotification, AuditEvent, EventLog` and `migrate` reports no
pending changes.

---

## Step 3 — `core/ai.py` (the only file that touches the Anthropic SDK)

Copy the canonical implementation from `SPEC_Core.md` §4.1 verbatim:
- `MODEL = "claude-opus-4-8"` — one constant, never hardcoded elsewhere.
- `call_tool(...)` — forces one `strict` tool call, returns validated input dict.
- `stream_reply(...)` — yields text deltas for SSE chat.
- `strict_tool(...)` helper (§4.1 convention).

`anthropic` and `langsmith` are already in `requirements.txt`. Make sure
`ANTHROPIC_API_KEY` is in `.env`.

> Note: your `scheduling/ai/` folder already has provider clients
> (`anthropic_client.py`, `openai_client.py`, `ollama_client.py`). Decide whether
> the agents standardize on `core.ai` (per spec) or keep the per-agent clients.
> The spec's intent is **one** AI door in `core`.

**Done when:** `from core.ai import call_tool, stream_reply` imports cleanly and a
throwaway `call_tool` returns a dict.

---

## Step 4 — `core/events.py` (the event dispatcher)

Copy `SPEC_Core.md` §4.2 verbatim. It uses the `EventLog` model you already
added (`name`, `payload`, `processed`, `error`), so it should work immediately:
- `subscribe(event_name)` decorator
- `emit(event_name, **payload)` — writes an `EventLog` row, calls handlers, and
  never lets one bad handler break the emitter.

This is the backbone for all cross-agent side effects (§2 rule 4).

**Done when:** `emit("test.ping", x=1)` creates an `EventLog` row with
`processed=True`, and a registered `@subscribe("test.ping")` handler fires.

---

## Step 5 — `core/notifications.py` (one door for every outbound message)

Copy `SPEC_Core.md` §4.3. Uses `Patient` + `SentNotification`. This is where
opt-out (NFR-8) is enforced **once, globally**. Start with `ConsoleProvider`
(prints to stdout) — no Twilio/SendGrid yet.

⚠️ This is the file that surfaced the Step 1 mismatches — finish Step 1 first or
this won't import.

**Done when:** `notify(patient, "test", {})` creates a `SentNotification` row and
prints the console line; an opted-out patient returns `None` with no row sent.

---

## After these five — the remaining `core` modules (later, not now)

Build these when the first agent needs them (each agent SPEC says which):
- `core/identity.py` — OTP create/verify over the `OTPChallenge` model.
- `core/ehr.py` — `record_*()` helpers that also write `AuditEvent` rows.
- `core/safety.py` — `red_flag_check()` (Agent 3 Triage needs it).
- `core/tests/` — pytest coverage for the above (`pytest-django` is installed).

---

## Recommended sequence in one line

**Fix `INSTALLED_APPS` → reconcile model field names → migrate → `ai.py` →
`events.py` → `notifications.py`.** Everything else in the project sits on top of
these.
