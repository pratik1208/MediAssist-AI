# SPEC_Agent_7 — Outreach Campaigns

Technical spec for `BUILD_STEPS_Agent_7_Outreach_Campaigns.md`. Shared conventions: `SPEC_Core.md`. Tables: `SCHEMA.md` §outreach.

## Backend architecture

Population-scale batch pipeline (NFR-9: 3,500–5,000-patient cohorts) — bulk queries + queued sends, never per-patient synchronous loops:

```
staff defines Campaign (criteria JSON + channel plan)
        ▼
cohort.build_cohort(criteria) ─▶ ONE queryset ─▶ preview count
        ▼ launch
enroll_cohort(): bulk_create CampaignMembers (opted-out excluded at enrollment)
        ▼
daily cron dispatch_wave():
   members due for next attempt ─▶ render message (cached per language/template)
   ─▶ core.notifications.notify() (opt-out re-checked at send)
   escalation: sms → email(+3d) → voice(+7d) per channel_plan (Edge Case 15)
        ▼
inbound reply webhook ─▶ ai.classify_response()
   ├─ book     ─▶ scheduling handoff ─▶ state: scheduled ─▶ completed on appointment.completed
   ├─ snooze   ─▶ snooze_until (Edge Case 14)
   ├─ opt_out  ─▶ Patient.communication_preferences updated GLOBALLY (Edge Case 13, NFR-8)
   ├─ question ─▶ frontdesk (A9) or StaffTask
   └─ unclear  ─▶ one gentle re-ask, then unreachable
        ▼
campaign_stats(): funnel aggregates (FR-O7)
```

**The criteria engine lives in `outreach/cohort.py` and is shared with Agent 8** — same JSON schema for `Campaign.cohort_criteria` and `ClinicalGuideline.population_criteria`.

## Folder structure

```
outreach/
├── models.py            # Campaign, CampaignMember, OutboundMessage, InboundResponse
├── cohort.py            # criteria JSON schema + build_cohort() — SHARED with caregaps
├── services.py          # enroll_cohort, dispatch_wave, handle_response_action, campaign_stats
├── ai.py                # classify_response tool, render_message
├── serializers.py  views.py  urls.py  admin.py
├── management/commands/  dispatch_waves.py
└── tests/  test_cohort.py  test_waves.py  test_api.py  test_prompts.py
```

## Criteria JSON schema (`cohort.py`)

```json
{
  "all": [
    {"field": "age", "op": "gte", "value": 65},
    {"field": "condition_code", "op": "in", "value": ["E11"]},
    {"field": "lab", "code": "hba1c", "op": "gt", "value": 8.0, "within_days": 365},
    {"field": "last_visit", "op": "older_than_days", "value": 180},
    {"field": "vaccination", "code": "flu", "op": "missing", "within_days": 365}
  ]
}
```

Each predicate compiles to a queryset filter/annotation against `core.Patient` + `caregaps.ClinicalEvent`. Validate the JSON against this schema before saving a campaign; reject unknown fields/ops.

## API design

| Method | Path | Auth | Body → Response |
|---|---|---|---|
| POST | `/api/staff/outreach/campaigns/` | staff (coordinator) | `{name, clinical_goal, cohort_criteria, channel_plan}` → `201 {id, status:"draft"}` |
| GET  | `/api/staff/outreach/campaigns/{id}/preview/` | staff | → `{count, sample:[{name, reason}]}` — always preview before launch |
| POST | `/api/staff/outreach/campaigns/{id}/launch/` | staff | → `{status:"running", enrolled}` |
| POST | `/api/staff/outreach/campaigns/{id}/pause/` | staff | → `{status:"paused"}` |
| GET  | `/api/staff/outreach/campaigns/{id}/stats/` | staff | → funnel (below) |
| POST | `/api/outreach/inbound/` | webhook (signed) | `{from, text, provider_id}` → `202` |

Funnel response (FR-O7):

```json
{"identified": 4210, "contacted": 4180, "delivered": 4010, "responded": 917,
 "scheduled": 512, "completed": 388, "opted_out": 63, "snoozed": 141,
 "conversion_rate": 0.092, "by_channel": {"sms": {...}, "email": {...}, "voice": {...}}}
```

## Code examples

Wave dispatch — bulk, escalating (`services.py`):

```python
def dispatch_wave(campaign: Campaign):
    plan = campaign.channel_plan                      # [{"channel","wait_days"}, ...]
    due = (CampaignMember.objects
           .filter(campaign=campaign, state__in=["identified", "contacted"])
           .exclude(patient__communication_preferences__opted_out__sms=True)
           .select_related("patient"))
    for member in due.iterator(chunk_size=500):
        step = next_step(member, plan)                # first unsent step whose wait elapsed
        if step is None:
            continue
        if step_is_last_and_exhausted(member, plan):
            member.state = "unreachable"; member.save(); continue
        content_key = (member.patient.preferred_language, campaign.id, step["channel"])
        text = render_cached(content_key, campaign, member)     # one AI call per language, not per patient
        n = notify(member.patient, f"campaign_{campaign.id}", {"text": text},
                   channel=step["channel"])
        if n:                                          # None = opted out at send time
            OutboundMessage.objects.create(member=member, notification=n,
                                           wave_number=len(member.channel_attempts))
            member.channel_attempts.append({"channel": step["channel"], "at": now().isoformat()})
            member.state = "contacted"; member.save()
```

Reply classification — the safety-critical direction is opt-out (`ai.py`):

```python
CLASSIFY_RESPONSE = strict_tool(
    "classify_response", "Classify a patient's reply to an outreach message.",
    properties={
        "intent": {"type": "string", "enum": ["book", "snooze", "opt_out", "question", "unclear"]},
        "snooze_until": {"type": ["string", "null"], "format": "date",
                          "description": "resolve phrases like 'next month' to a date"},
        "question_text": {"type": ["string", "null"]},
    },
    required=["intent", "snooze_until", "question_text"],
)

OPT_OUT_LITERALS = {"stop", "unsubscribe", "stop texting me", "remove me", "opt out"}

def classify_response(member, raw_text) -> dict:
    if raw_text.strip().lower() in OPT_OUT_LITERALS:            # deterministic fast-path:
        return {"intent": "opt_out", "snooze_until": None,      # never let the model miss STOP
                "question_text": None}
    return call_tool(OUTREACH_SYSTEM_PROMPT,
                     [{"role": "user", "content":
                       f"Campaign: {member.campaign.clinical_goal}\nReply: {raw_text}"}],
                     CLASSIFY_RESPONSE)
```

Opt-out propagates globally (Edge Case 13 / NFR-8):

```python
def handle_response_action(member, parsed):
    match parsed["intent"]:
        case "opt_out":
            prefs = member.patient.communication_preferences
            prefs.setdefault("opted_out", {})[last_channel(member)] = True
            member.patient.save(update_fields=["communication_preferences"])
            member.state = "opted_out"                 # core.notifications now blocks ALL modules
        case "snooze":
            member.state, member.snooze_until = "snoozed", parsed["snooze_until"]
        case "book":
            emit("outreach.response_action", patient_id=member.patient_id,
                 action="book", campaign_id=member.campaign_id)   # scheduling books
            member.state = "responded"
        case "question":
            create_staff_or_frontdesk_task(member, parsed["question_text"])
    member.save()
```

## Tech stack additions

- Inbound webhook endpoint with provider signature verification (Twilio-style `X-Twilio-Signature`) — stub verifier in dev
- Message-render cache: plain Django cache keyed `(language, campaign, channel)` — 5,000 sends ≠ 5,000 AI calls
- This is the first agent that justifies moving `dispatch_wave` to a real queue (Celery + Redis) if send volume makes the cron run long (ORCHESTRATION §3 Stage 3)
