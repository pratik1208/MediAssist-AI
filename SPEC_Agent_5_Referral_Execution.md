# SPEC_Agent_5 — Referral Execution

Technical spec for `BUILD_STEPS_Agent_5_Referral_Execution.md`. Shared conventions: `SPEC_Core.md`. Tables: `SCHEMA.md` §referrals.

## Backend architecture

A status-machine workflow agent — the interesting part is the lifecycle, not the chat:

```
physician "Create Referral" ─▶ services.create_referral()            status: created
      └▶ ai.build_referral_package()   (model SELECTS chart items; code COPIES them)
      └▶ services.match_specialists()  (queryset filter + rank)
specialist office contact (task queue / e-referral stub)             status: accepted
      └▶ services.book_specialist_visit()  → scheduling.book_appointment
                                                                     status: appointment_scheduled
patient confirms (reminder pipeline)                                 status: patient_confirmed
visit happens (appointment.completed event)                          status: visit_completed
report uploaded ─▶ ai.parse_consultation_report()                    status: report_received
      └▶ services.close_loop() ─▶ notify referring physician         status: closed

daily cron: check_stalled_referrals()  ──▶ status: stalled + coordinator alert (FR-F9)
missed appointment event ──▶ handle_missed_appointment() chain (FR-F8)
MRI/procedure ordered downstream ──▶ emit("priorauth.needed") ──▶ Agent 6
```

Status transitions only via `advance_status()` — one choke point enforcing the FR-F7 machine and timestamping `status_history`.

## Folder structure

```
referrals/
├── models.py            # Specialist, Referral, ReferralPackage, ConsultationReport
├── services.py          # create_referral, match_specialists, advance_status,
│                        # book_specialist_visit, check_stalled_referrals,
│                        # handle_missed_appointment, close_loop
├── ai.py                # select_referral_content + parse_consultation_report tools
├── documents.py         # required_documents_for(specialty) config map (FR-F4)
├── serializers.py  views.py  urls.py  admin.py
├── management/commands/  seed_specialists.py  check_stalled.py
└── tests/  test_status_machine.py  test_matching.py  test_api.py  test_prompts.py
```

## API design

| Method | Path | Auth | Body → Response |
|---|---|---|---|
| POST | `/api/staff/referrals/` | staff (physician) | `{patient_id, specialty, reason, urgency}` → `201 {id, status:"created", matched_specialists:[...]}` |
| GET  | `/api/staff/referrals/?status=&stalled=true` | staff (coordinator) | → dashboard list with timelines |
| POST | `/api/staff/referrals/{id}/select-specialist/` | staff | `{specialist_id}` → package built + booking attempted |
| GET  | `/api/referrals/mine/` | session (verified) | → patient's referrals `{specialist, appointment, status, prep_instructions}` |
| POST | `/api/staff/referrals/{id}/report/` | staff / specialist-sim | multipart `{file}` or `{text}` → parsed → `{status:"report_received"}` |
| POST | `/api/staff/referrals/{id}/close/` | staff | → `{status:"closed"}` (auto after report import) |

## Code examples

Status machine (`services.py`):

```python
ALLOWED = {
    "created": {"accepted", "stalled"},
    "accepted": {"appointment_scheduled", "stalled"},
    "appointment_scheduled": {"patient_confirmed", "stalled"},
    "patient_confirmed": {"visit_completed", "appointment_scheduled", "stalled"},  # reschedule loop
    "visit_completed": {"report_received", "stalled"},
    "report_received": {"closed"},
    "stalled": {"accepted", "appointment_scheduled", "patient_confirmed"},          # recoverable
}

def advance_status(referral, new_status):
    if new_status not in ALLOWED[referral.status]:
        raise InvalidTransition(f"{referral.status} -> {new_status}")
    referral.status_history.append({"status": new_status, "at": now().isoformat()})
    referral.status = new_status
    referral.save(update_fields=["status", "status_history", "updated_at"])
    emit("referral.status_changed", referral_id=referral.id, status=new_status)
```

Specialist matching (pure queryset, FR-F3/F5):

```python
def match_specialists(referral, patient, limit=5):
    qs = (Specialist.objects
          .filter(specialty__iexact=referral.specialty_needed,
                  accepting_new_patients=True)
          .filter(accepted_insurances__contains=[patient_insurer(patient)]))
    if patient.preferred_language != "en":
        qs = qs.filter(languages__contains=[patient.preferred_language])
    return sorted(qs, key=lambda s: distance_km(s.address, patient.address))[:limit]
```

Package building — model selects, code copies (FR-F2):

```python
SELECT_REFERRAL_CONTENT = strict_tool(
    "select_referral_content",
    "Choose ONLY the chart items relevant to the target specialty and write a referral summary.",
    properties={
        "selected_item_ids": {"type": "array", "items": {"type": "integer"}},
        "summary_text": {"type": "string"},
        "recommended_documents": {"type": "array", "items": {"type": "string"}},
    },
    required=["selected_item_ids", "summary_text", "recommended_documents"],
)

def build_referral_package(referral) -> ReferralPackage:
    chart = chart_items_for(referral.patient)           # [{id, category, summary, date}]
    out = call_tool(
        PACKAGE_SYSTEM_PROMPT,
        [{"role": "user", "content":
          f"Specialty: {referral.specialty_needed}\nReason: {referral.reason}\n"
          f"Chart items:\n{json.dumps(chart, default=str)}"}],
        SELECT_REFERRAL_CONTENT)
    selected = [c for c in chart if c["id"] in set(out["selected_item_ids"])]  # code gates
    return ReferralPackage.objects.create(
        referral=referral, selected_chart_data=selected,
        summary_text=out["summary_text"],
        attached_documents=documents.required_documents_for(referral.specialty_needed))
```

Stalled-referral cron (FR-F9):

```python
def check_stalled_referrals(threshold_days=14):
    cutoff = now() - timedelta(days=threshold_days)
    for r in Referral.objects.exclude(status__in=["closed", "stalled"]).filter(updated_at__lt=cutoff):
        advance_status(r, "stalled")
        create_coordinator_alert(r)      # EscalationAlert(source_agent="referrals", priority="high")
```

## Tech stack additions

- Distance ranking: postal-code centroid table + haversine (`math`) — skip PostGIS until you need real geo queries
- Report parsing reuses the Agent 2 document-extraction pattern (PDF/image content block → strict tool)
- Cron: `python manage.py check_stalled` daily via the platform scheduler
