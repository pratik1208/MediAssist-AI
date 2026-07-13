"""Care gap business logic (Agent 8, Phase 2) — deterministic, no AI.

The scanner is rules-over-data and must stay auditable (NFR-4): every
decision is "was there a ClinicalEvent with this code recently enough?",
never a model's opinion. Population membership reuses Agent 7's
build_cohort() — one criteria schema across outreach and caregaps, as
SCHEMA.md requires.

NFR-9: scan_all() must not do per-patient work for the whole clinic. The
heavy lifting is a set-based prefilter per guideline (cohort ∩ "no recent
satisfying event OR has a live gap" via Exists subqueries); only those
candidates — patients who actually need a decision — get the per-patient
evaluation. Cost scales with the number of gaps, not the number of patients.
"""

import logging
from datetime import timedelta

from django.db.models import Case, Exists, IntegerField, OuterRef, Q, Value, When
from django.utils import timezone

from caregaps.models import CareGap, CarePlan, ClinicalEvent, ClinicalGuideline
from core.models import AuditEvent, Patient
from outreach.services import build_cohort

log = logging.getLogger("caregaps")

# Everything except "closed" counts as live — the partial unique constraint
# and every "does this patient already have a gap?" check share this list.
LIVE_GAP_STATUSES = ("open", "outreach", "scheduled", "completed")

# Care items that can share one visit (FR-G4): labs, vaccines and plain
# visits happen in the same room on the same day. Screenings (mammogram,
# dilated eye exam) need their own equipment/appointment.
_SHAREABLE_CARE_ITEM_TYPES = frozenset({"test", "vaccination", "visit", "followup"})

# Plans still pending after this many days re-enter outreach (FR-G7,
# PRD Edge Case 17).
RECYCLE_WINDOW_DAYS = 30


def _audit(patient, action: str, payload: dict) -> None:
    AuditEvent.objects.create(
        actor_type="agent", actor_id="caregaps", patient=patient,
        action=action, payload=payload,
    )

# Convert a datetime into the patient's/local calendar date.
def _local_date(dt):
    """The event's LOCAL calendar date. occurred_at.date() would be the UTC
    date, which near midnight local time is a day off — and 'overdue by one
    day' decisions live exactly on that boundary."""
    return timezone.localtime(dt).date()

# Get the patient's most recent clinical event for a particular medical code.
def _latest_event(patient: Patient, code: str) -> ClinicalEvent | None:
    if not code:
        return None
    return (
        ClinicalEvent.objects
        .filter(patient=patient, code=code)
        .order_by("-occurred_at")
        .first()
    )


def _evaluate(patient: Patient, guideline: ClinicalGuideline, today):
    """The deterministic truth table for one patient against one guideline.

    Returns one of:
      ("satisfied", evidence_event)  — requirement met; event proves it (FR-G8)
      ("overdue",   due_since_date)  — gap should be open since that date;
                                       None when never done (no event to date
                                       the debt from — the gap starts aging
                                       the day it is DETECTED, and must not
                                       re-anchor to "today" on every rescan)
      ("not_due",   None)            — inside the allowed window, nothing owed yet

    Two timing models:
      * periodic (screening/test/vaccination/visit): the newest matching
        event must be no older than frequency_days. The boundary day itself
        still satisfies — "every 182 days" means day 183 is the first
        overdue day. Never-done patients are overdue with no anchor date —
        their gap starts aging the day the scanner first detects it.
      * anchored (followup): the requirement is triggered by the newest
        population trigger event (population_criteria.has_event_code, e.g. a
        hospital discharge) and must happen ON/AFTER that trigger, within
        frequency_days of it. A follow-up that satisfied a *previous*
        discharge does not satisfy a new one. Without a recorded trigger it
        degrades to the periodic check rather than guessing.
    """
    # Find the most recent evidence that this patient completed the required care item.
    last_item = _latest_event(patient, guideline.care_item_code)

    if guideline.care_item_type == "followup":
        trigger_code = (guideline.population_criteria or {}).get("has_event_code")
        trigger = _latest_event(patient, trigger_code)
        if trigger is not None:
            if last_item is not None and last_item.occurred_at >= trigger.occurred_at:
                return "satisfied", last_item
            deadline = _local_date(trigger.occurred_at) + timedelta(days=guideline.frequency_days)
            if today > deadline:
                return "overdue", deadline
            return "not_due", None

    if last_item is not None:
        if _local_date(last_item.occurred_at) >= today - timedelta(days=guideline.frequency_days):
            return "satisfied", last_item
        return "overdue", _local_date(last_item.occurred_at) + timedelta(days=guideline.frequency_days)

    return "overdue", None


# -- FR-G1/G2: the scanner ------------------------------------------------------

def scan_patient(patient: Patient) -> dict:
    """Evaluate every active guideline for one patient: open gaps that are
    owed, refresh stale due_since on open gaps, and close live gaps whose
    satisfying event has since appeared (the scan is self-healing in both
    directions). Never duplicates — one live gap per patient+guideline,
    enforced here by lookup and by the DB partial unique constraint.

    A patient who has LEFT a guideline's population (aged out, criteria
    edited) keeps any existing live gap: silently discarding a detected gap
    is a clinical call, so staff close it, not the scanner.
    """
    today = timezone.localdate()
    opened = refreshed = closed = 0

    for guideline in ClinicalGuideline.objects.filter(is_active=True):
        if not build_cohort(guideline.population_criteria).filter(pk=patient.pk).exists():
            continue
        # What is the patient's status?- verdict
        # John became overdue on June 30. - Info
        verdict, info = _evaluate(patient, guideline, today)
        live = (
            CareGap.objects
            .filter(patient=patient, guideline=guideline)
            .exclude(status="closed")
            .first()
        )

        if verdict == "satisfied":
            if live is not None:
                close_gap(live, info)
                closed += 1
        elif verdict == "overdue":
            if live is None:
                # info is None for never-done items: the gap starts aging at
                # detection time and must keep that anchor on later rescans
                # (re-anchoring to "today" would make it never look overdue).
                CareGap.objects.create(patient=patient, guideline=guideline,
                                       due_since=info or today)
                opened += 1
            elif live.status == "open" and info is not None and live.due_since != info:
                # A newer (but still too old) event moved the overdue date.
                # Only plain "open" gaps are touched — once a gap is in a
                # workflow (outreach/scheduled) its dates belong to that flow.
                live.due_since = info
                live.save(update_fields=["due_since"])
                refreshed += 1
        # "not_due": nothing owed, nothing to close.

    return {"opened": opened, "refreshed": refreshed, "closed": closed}

# Scan the entire clinic and update care gaps for all relevant patients.
def scan_all() -> dict:
    """Bulk scan (nightly job from Phase 7; management command until then).

    Set-based candidate selection per guideline, then per-patient evaluation
    only for candidates (see module docstring for the NFR-9 shape).
    """
    today = timezone.localdate()
    candidate_ids: set[int] = set()

    for guideline in ClinicalGuideline.objects.filter(is_active=True):
        # Find patients who recently completed the care item.
        recent_item = ClinicalEvent.objects.filter(
            patient=OuterRef("pk"), code=guideline.care_item_code,
            occurred_at__date__gte=today - timedelta(days=guideline.frequency_days),
        )
        # Find patients who already have an active gap.
        live_gap = (
            CareGap.objects
            .filter(patient=OuterRef("pk"), guideline=guideline)
            .exclude(status="closed")
        )
        candidate_ids.update(
            build_cohort(guideline.population_criteria)
            .annotate(_recent=Exists(recent_item), _live=Exists(live_gap))
            .filter(Q(_recent=False) | Q(_live=True))
            .values_list("id", flat=True)
        )

    totals = {"patients_scanned": 0, "opened": 0, "refreshed": 0, "closed": 0}
    for patient in Patient.objects.filter(id__in=candidate_ids).iterator():
        result = scan_patient(patient)
        totals["patients_scanned"] += 1
        for key in ("opened", "refreshed", "closed"):
            totals[key] += result[key]

    log.info("[CAREGAPS SCAN] %s", totals)
    return totals


# -- FR-G3: prioritization ------------------------------------------------------

_RISK_RANK = Case(
    When(guideline__risk_tier="high", then=Value(0)),
    When(guideline__risk_tier="medium", then=Value(1)),
    default=Value(2),
    output_field=IntegerField(),
)


def prioritize(statuses: tuple = ("open",)):
    """Open gaps ordered by guideline risk tier, then by how long overdue
    (oldest due_since first). One query; the staff work list and the Phase 3
    prioritized-patient endpoint both read straight from this."""
    return (
        CareGap.objects
        .filter(status__in=statuses)
        .select_related("patient", "guideline")
        .annotate(_risk_rank=_RISK_RANK)
        .order_by("_risk_rank", "due_since", "id")
    )


# -- FR-G4: bundling ------------------------------------------------------------

def bundle_breakdown(gaps) -> dict:
    """Split a set of gaps into what can share one visit vs. what needs its
    own appointment."""
    shared, separate = [], []
    for gap in gaps:
        target = shared if gap.guideline.care_item_type in _SHAREABLE_CARE_ITEM_TYPES else separate
        target.append(gap)
    return {"shared_visit": shared, "separate": separate}

# Create one care plan for a patient by combining all their open care gaps into an actionable plan.
def bundle_care_plan(patient: Patient) -> CarePlan | None:
    """Group the patient's OPEN gaps into one CarePlan (FR-G4). Reuses the
    patient's active plan if one exists (adding newly detected gaps to it)
    rather than stacking a second plan; returns None when there is nothing
    to bundle. plan_text gets a plain deterministic summary — Phase 4's AI
    rewrites it warmly, but the plan must read sensibly without AI too.
    """
    open_gaps = list(
        CareGap.objects
        .filter(patient=patient, status="open")
        .select_related("guideline")
        .order_by("id")
    )
    active_plan = (
        CarePlan.objects
        .filter(patient=patient, status__in=("draft", "sent", "accepted", "in_progress"))
        .order_by("-id")
        .first()
    )
    if not open_gaps and active_plan is None:
        return None

    plan = active_plan or CarePlan.objects.create(patient=patient)
    if open_gaps:
        plan.gaps.add(*open_gaps)

    breakdown = bundle_breakdown(plan.gaps.exclude(status="closed").select_related("guideline"))
    lines = []
    if breakdown["shared_visit"]:
        items = ", ".join(g.guideline.name for g in breakdown["shared_visit"])
        lines.append(f"Can be done in a single visit: {items}.")
    if breakdown["separate"]:
        items = ", ".join(g.guideline.name for g in breakdown["separate"])
        lines.append(f"Needs its own appointment: {items}.")
    plan.plan_text = " ".join(lines)
    plan.save(update_fields=["plan_text"])
    return plan


# -- Phase 4: the patient-facing message + document backfill --------------------

def render_plan_message(plan: CarePlan) -> str:
    """The outreach message for a care plan: an AI-written warm body in the
    patient's preferred language, with "Hi {name}," prepended (same
    convention as outreach's render_message). An AI outage never blocks —
    it falls back to the deterministic plan_text, which bundle_care_plan
    guarantees reads sensibly on its own. The AI version is also saved back
    to plan_text (the model's help text calls it the "AI patient-facing
    plan") so staff preview and the Phase 6 campaign send the same words."""
    patient = plan.patient
    breakdown = bundle_breakdown(plan.gaps.exclude(status="closed").select_related("guideline"))
    shared = [g.guideline.name for g in breakdown["shared_visit"]]
    separate = [g.guideline.name for g in breakdown["separate"]]

    try:
        from caregaps.ai import write_care_plan_message  # local: keeps AI optional
        body = write_care_plan_message(shared, separate, patient.preferred_language)["body"]
        plan.plan_text = body
        plan.save(update_fields=["plan_text"])
    except Exception:
        log.warning("[CAREGAPS MESSAGE] AI plan message failed for plan %s — "
                    "using deterministic plan_text", plan.id)
        body = plan.plan_text
    return f"Hi {patient.first_name}, {body}"


def backfill_events_from_document(patient: Patient, document_text: str) -> dict:
    """Optional FR pipeline: lab report / visit summary text -> ClinicalEvent
    rows the scanner can read. The model only STATES what the document says;
    this function DECIDES what's usable: a known event_type, a non-empty
    code, and a parseable date are all required — anything else is skipped
    and counted, never guessed at. Idempotent: an identical event (same
    patient, type, code, date) is not duplicated on re-upload."""
    from datetime import date as date_cls, datetime, time

    try:
        from caregaps.ai import extract_clinical_events  # local: keeps AI optional
        result = extract_clinical_events(document_text)
    except Exception:
        log.warning("[CAREGAPS EXTRACT] AI extraction failed — nothing backfilled")
        return {"created": 0, "skipped": 0, "failed": True}

    if not result.get("legible", False):
        return {"created": 0, "skipped": len(result.get("events") or []), "failed": False}

    valid_types = {choice for choice, _ in ClinicalEvent.EVENT_TYPE_CHOICES}
    created = skipped = 0
    for entry in result.get("events") or []:
        event_type = entry.get("event_type")
        code = (entry.get("code") or "").strip()
        raw_date = entry.get("date")
        try:
            occurred_date = date_cls.fromisoformat(raw_date) if raw_date else None
        except (TypeError, ValueError):
            occurred_date = None
        if event_type not in valid_types or not code or occurred_date is None:
            skipped += 1
            continue
        occurred_at = timezone.make_aware(datetime.combine(occurred_date, time(12, 0)))
        _, was_created = ClinicalEvent.objects.get_or_create(
            patient=patient, event_type=event_type, code=code, occurred_at=occurred_at,
            defaults={"value": entry.get("value") or {}},
        )
        created += was_created
        skipped += not was_created
    return {"created": created, "skipped": skipped, "failed": False}


# -- Phase 6: scheduling surface hook + outreach delivery -----------------------

def open_gaps_for(patient: Patient) -> list[dict]:
    """The scheduling-surface hook (PRD secondary journey): a compact,
    priority-ordered list of what this patient is due for, cheap enough to
    attach to any booking response so the conversation can offer "you're
    also due for a cholesterol screening while you're here"."""
    today = timezone.localdate()
    return [{
        "gap_id": gap.id,
        "guideline": gap.guideline.name,
        "care_item_type": gap.guideline.care_item_type,
        "risk_tier": gap.guideline.risk_tier,
        "days_overdue": (today - gap.due_since).days,
    } for gap in prioritize(statuses=("open", "outreach")).filter(patient=patient)]


def bundle_all() -> int:
    """Bundle every patient who has open gaps into a care plan (creating or
    refreshing their active plan). The step between the nightly scan and
    pushing plans into outreach."""
    patient_ids = (
        CareGap.objects.filter(status="open").values_list("patient_id", flat=True).distinct()
    )
    bundled = 0
    for patient in Patient.objects.filter(id__in=patient_ids).iterator():
        if bundle_care_plan(patient) is not None:
            bundled += 1
    return bundled


CAREGAP_CAMPAIGN_NAME = "Care plan follow-up"


def push_plans_to_outreach() -> dict:
    """FR-G5: care-gap outreach runs AS an Agent 7 campaign — one dedicated,
    always-running campaign whose cohort is "patients with a live care
    plan". No second sender: enrollment, channel escalation, AI reply
    classification, auto-booking (FR-G6, via Agent 1's booking door) and
    opt-out compliance are all outreach's existing machinery.

    Each member's outreach_reason is set to THEIR plan's summary, which
    dispatch_wave uses as the per-member message goal — so every patient
    hears about their own items. Draft plans go to "sent" and their gaps to
    "outreach"; a patient recycled by FR-G7 is re-enrolled at the top of the
    escalation ladder via outreach.re_enroll_member (which refuses for
    opted-out patients — a recycle loop never overrides an opt-out)."""
    from outreach import services as outreach
    from outreach.models import Campaign, CampaignMember

    draft_plans = list(
        CarePlan.objects.filter(status="draft").select_related("patient").order_by("id")
    )
    if not draft_plans:
        return {"campaign_id": None, "sent": 0, "skipped_opted_out": 0,
                "wave": {"queued": 0, "unreachable": 0}}

    campaign, created = Campaign.objects.get_or_create(
        name=CAREGAP_CAMPAIGN_NAME,
        defaults={
            "clinical_goal": "complete the preventive care items on your care plan",
            "cohort_criteria": {"has_open_care_plan": True},
            "channel_plan": [
                {"channel": "sms", "wait_days": 0},
                {"channel": "email", "wait_days": 3},
                {"channel": "voice", "wait_days": 7},
            ],
            "status": "running",
            "launched_at": timezone.now(),
        },
    )
    if campaign.status == "paused":
        # Staff paused care-gap outreach deliberately; honor it.
        return {"campaign_id": campaign.id, "sent": 0, "skipped_opted_out": 0,
                "paused": True, "wave": {"queued": 0, "unreachable": 0}}
    if campaign.status != "running":
        campaign.status = "running"
        campaign.launched_at = campaign.launched_at or timezone.now()
        campaign.save(update_fields=["status", "launched_at"])

    sent = skipped_opted_out = 0
    for plan in draft_plans:
        patient = plan.patient
        reason = (plan.plan_text or campaign.clinical_goal)[:200]
        member = CampaignMember.objects.filter(campaign=campaign, patient=patient).first()
        if member is None:
            if outreach._is_fully_opted_out(patient):
                skipped_opted_out += 1
                continue
            member = CampaignMember.objects.create(
                campaign=campaign, patient=patient, outreach_reason=reason,
            )
        else:
            member.outreach_reason = reason
            member.save(update_fields=["outreach_reason"])
            if not outreach.re_enroll_member(member):
                skipped_opted_out += 1
                continue
        plan.status = "sent"
        plan.save(update_fields=["status"])
        plan.gaps.filter(status="open").update(status="outreach")
        sent += 1

    wave = outreach.dispatch_wave(campaign)
    log.info("[CAREGAPS OUTREACH] pushed %s plan(s), wave: %s", sent, wave)
    return {"campaign_id": campaign.id, "sent": sent,
            "skipped_opted_out": skipped_opted_out, "wave": wave}


# -- FR-G8: close on evidence ---------------------------------------------------

def close_gap(gap: CareGap, evidence_event: ClinicalEvent | None = None) -> CareGap:
    """Completion detected (lab resulted, vaccine given, visit completed) —
    close the gap WITH the evidence event attached, so every closure is
    traceable to a real clinical record. Any care plan whose gaps are now
    all closed completes with it, which is what the dashboards read."""
    gap.status = "closed"
    gap.closed_at = timezone.now()
    gap.closing_event = evidence_event
    gap.save(update_fields=["status", "closed_at", "closing_event"])
    _audit(gap.patient, "caregaps.gap_closed", {
        "gap_id": gap.id, "guideline_id": gap.guideline_id,
        "closing_event_id": evidence_event.id if evidence_event else None,
    })

    for plan in gap.care_plans.exclude(status__in=("completed", "recycled")):
        if not plan.gaps.exclude(status="closed").exists():
            plan.status = "completed"
            plan.save(update_fields=["status"])

    return gap


# -- FR-G7 / Edge Case 17: the recycle loop -------------------------------------

def recycle_incomplete(window_days: int = RECYCLE_WINDOW_DAYS) -> list[CarePlan]:
    """Care plans still pending past the window re-enter outreach: the plan
    is marked recycled and its unfinished gaps are reset to "open", so the
    next bundle/outreach cycle picks them up fresh. A stale plan whose gaps
    all quietly closed in the meantime just completes. Returns the plans
    that were actually recycled (Phase 6 feeds these into an Agent 7
    campaign)."""
    cutoff = timezone.now() - timedelta(days=window_days)
    stale = CarePlan.objects.filter(
        status__in=("sent", "accepted", "in_progress"), created_at__lt=cutoff,
    )

    recycled = []
    for plan in stale:
        unfinished = plan.gaps.exclude(status="closed")
        if not unfinished.exists():
            plan.status = "completed"
            plan.save(update_fields=["status"])
            continue
        unfinished.exclude(status="open").update(status="open")
        plan.status = "recycled"
        plan.save(update_fields=["status"])
        _audit(plan.patient, "caregaps.plan_recycled", {
            "plan_id": plan.id, "reopened_gaps": [g.id for g in plan.gaps.filter(status="open")],
        })
        recycled.append(plan)

    return recycled
