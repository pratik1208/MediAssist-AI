# SPEC_Agent_8 — Care Gap Closure

Technical spec for `BUILD_STEPS_Agent_8_Care_Gap_Closure.md`. Shared conventions: `SPEC_Core.md`. Tables: `SCHEMA.md` §caregaps.

## Backend architecture

Deterministic rules-over-data scanner; AI only writes patient-facing language. Reuses Agent 7 for delivery and Agent 1 for booking — this agent adds almost no new plumbing:

```
nightly cron scan_all():
  for each active ClinicalGuideline:
     population = cohort.build_cohort(guideline.population_criteria)     ← Agent 7's engine
     for patients missing/overdue care_item (latest ClinicalEvent older than frequency_days):
        open CareGap (partial-unique: one live gap per patient+guideline)
        ▼
prioritize() by risk_tier + overdue duration (FR-G3)
        ▼
bundle_care_plan(): group a patient's open gaps → CarePlan + single-visit flag (FR-G4)
        ▼
ai.write_care_plan_message() ─▶ delivered AS an outreach campaign (FR-G5, Agent 7 pipes)
        ▼
patient accepts ─▶ scheduling books labs/visits/vaccinations (FR-G6)
        ▼
appointment.completed / new ClinicalEvent ─▶ close_gap() ─▶ dashboards (FR-G8)
weekly cron recycle_incomplete() ─▶ pending items re-enter outreach (FR-G7, Edge Case 17)
```

Scanning must stay deterministic and auditable (NFR-4): the model never decides whether a gap exists.

## Folder structure

```
caregaps/
├── models.py            # ClinicalGuideline, ClinicalEvent, CareGap, CarePlan
├── services.py          # scan_patient, scan_all, prioritize, bundle_care_plan,
│                        # close_gap, recycle_incomplete, open_gaps_for
├── ai.py                # write_care_plan_message
├── serializers.py  views.py  urls.py  admin.py
├── management/commands/  seed_guidelines.py  scan_gaps.py  recycle_plans.py
└── tests/  test_scanner.py  test_bundling.py  test_api.py
```

## API design

| Method | Path | Auth | Body → Response |
|---|---|---|---|
| GET | `/api/staff/caregaps/patients/?risk=high` | staff | → prioritized list `[{patient, open_gaps, risk, overdue_days}]` |
| GET | `/api/staff/caregaps/patients/{id}/gaps/` | staff | → gaps + plan for one patient |
| GET | `/api/staff/caregaps/metrics/` | staff (leadership) | → FR-G9 quality metrics (below) |
| POST | `/api/staff/caregaps/scan/` | staff/dev | trigger scan (normally cron) → `{gaps_opened, gaps_closed}` |
| GET | `/api/caregaps/mine/` | session (verified) | → patient's open plan in plain language |
| GET | `/api/staff/caregaps/open-gaps-for/{patient_id}/` | staff/internal | → hook other agents call during booking ("also due for…") |

Metrics response (FR-G9):

```json
{"open_gaps": 1231, "closed_this_quarter": 402, "closure_rate": 0.246,
 "outreach_response_rate": 0.31, "appointment_completion_rate": 0.78,
 "by_guideline": {"hba1c_6mo": {"open": 210, "closed": 88}},
 "by_provider": {"dr_chen": {"open": 61, "closure_rate": 0.29}}}
```

## Code examples

The scanner (`services.py`) — pure rules:

```python
from datetime import timedelta
from outreach.cohort import build_cohort               # shared criteria engine

def scan_patient(patient, guidelines=None):
    opened = []
    for g in guidelines or ClinicalGuideline.objects.filter(is_active=True):
        if not build_cohort(g.population_criteria).filter(id=patient.id).exists():
            continue                                    # not in population
        latest = (ClinicalEvent.objects
                  .filter(patient=patient, code=g.care_item_code)
                  .order_by("-occurred_at").first())
        due = latest is None or \
              latest.occurred_at.date() < date.today() - timedelta(days=g.frequency_days)
        live = CareGap.objects.filter(patient=patient, guideline=g).exclude(status="closed")
        if due and not live.exists():
            opened.append(CareGap.objects.create(
                patient=patient, guideline=g, status="open",
                due_since=(latest.occurred_at.date() + timedelta(days=g.frequency_days))
                          if latest else date.today()))
            emit("caregap.opened", patient_id=patient.id, guideline=g.name)
        elif not due and live.exists():
            close_gap(live.first(), latest)             # evidence arrived out-of-band
    return opened

def scan_all():
    gs = list(ClinicalGuideline.objects.filter(is_active=True))
    population_ids = set()
    for g in gs:                                        # bulk: union of populations, one query each
        population_ids |= set(build_cohort(g.population_criteria).values_list("id", flat=True))
    for pid in population_ids:
        scan_patient(Patient.objects.get(id=pid), gs)
```

Bundling + single-visit flag (FR-G4):

```python
BUNDLEABLE = {"lab", "vaccination", "visit"}            # can share one appointment

def bundle_care_plan(patient) -> CarePlan | None:
    gaps = list(CareGap.objects.filter(patient=patient, status="open")
                                .select_related("guideline"))
    if not gaps:
        return None
    plan = CarePlan.objects.create(patient=patient, status="draft")
    plan.gaps.set(gaps)
    plan.plan_text = write_care_plan_message(plan)      # AI, patient's language
    plan.single_visit_possible = all(
        g.guideline.care_item_type in BUNDLEABLE for g in gaps)
    plan.save()
    return plan
```

Patient-facing message — grounded generation (`ai.py`):

```python
def write_care_plan_message(plan) -> str:
    items = [{"name": g.guideline.name, "type": g.guideline.care_item_type,
              "overdue_days": (date.today() - g.due_since).days} for g in plan.gaps.all()]
    out = call_tool(
        """Write a short, warm message telling the patient what preventive care they are
        due for. Use ONLY the items provided — never add clinical claims, diagnoses, or
        urgency not present in the data. Mention one-visit bundling if single_visit=true.
        Write in the given language.""",
        [{"role": "user", "content": json.dumps({
            "items": items, "single_visit": plan.single_visit_possible,
            "language": plan.patient.preferred_language})}],
        strict_tool("care_plan_message", "The message.",
                    {"message": {"type": "string"}}, ["message"]),
    )
    return out["message"]
```

Closure via events (FR-G8):

```python
# caregaps/apps.py ready():
@subscribe("appointment.completed")
def _maybe_close_gaps(patient_id, appointment_id, **_):
    for gap in CareGap.objects.filter(patient_id=patient_id, status="scheduled"):
        evt = matching_clinical_event(gap, appointment_id)   # visit/vaccination recorded by EHR layer
        if evt:
            close_gap(gap, evt)

def close_gap(gap, evidence):
    gap.status, gap.closed_at, gap.closing_event = "closed", now(), evidence
    gap.save()
    emit("caregap.closed", patient_id=gap.patient_id, guideline=gap.guideline.name)
```

## Tech stack additions

- None — deliberately. Delivery = Agent 7, booking = Agent 1, criteria = shared `cohort.py`, data = `ClinicalEvent` populated by `core.ehr` + Agent 2's document extraction.
- Cron: `scan_gaps` nightly, `recycle_plans` weekly.
