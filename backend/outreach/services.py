"""Outreach campaign business logic (Agent 7, Phase 2) — SCHEMA.md §outreach.

NFR-9: design for cohorts of 3,500-5,000 patients. build_cohort() and
enroll_cohort() must each be a fixed, small number of SQL queries regardless
of cohort size — never a per-patient Python loop. dispatch_wave() still has
to send one message per due member (each recipient's content/channel truly
differs), but the *candidate selection* that feeds it is one query.

build_cohort()'s criteria schema is deliberately narrower than the build
step's example list (age range, condition codes, lab thresholds like
HbA1c > 8, months since last visit, vaccination status, missed
appointments): only age, last-visit recency, and missed-appointment count
are backed by real data anywhere in this codebase today. There is no
condition/lab/immunization model yet — Agent 8 (Care Gap Closure) is where
SCHEMA.md's ClinicalGuideline/ClinicalEvent tables are expected to land, and
this schema is meant to gain those keys then, not have them faked now. An
unsupported criteria key raises loudly rather than silently building the
wrong cohort (same "never silently invent data" rule as priorauth's honest
"not required" default).
"""

import calendar
import logging
from datetime import date, timedelta

from django.db import models as django_models
from django.db.models import Count, Max, Q
from django.utils import timezone

from core.events import emit
from core.models import AuditEvent, Doctor, Patient
from core.notifications import notify
from outreach.models import Campaign, CampaignMember, InboundResponse, OutboundMessage

log = logging.getLogger("outreach")

_ALL_CHANNELS = ("sms", "email", "voice", "whatsapp")

# A patient with an explicit False on every channel asked "stop contacting me
# any way" (NFR-8/Edge Case 13); a patient with an empty/partial dict simply
# hasn't been asked yet and defaults to reachable, same as notify() assumes.
#
# This has to be a single `contains` lookup (jsonb `@>`), not an AND of four
# per-key `=False` lookups: a per-key lookup against a *missing* key compares
# against SQL NULL, so `.exclude(Q(a=False) & Q(b=False) & ...)` becomes
# `WHERE NOT (NULL AND NULL AND ...)` = `WHERE NOT NULL`, which is itself
# NULL -- and Postgres treats a NULL WHERE clause as false, silently
# excluding patients who were never asked at all. `contains` short-circuits
# missing keys to a clean `false` instead of NULL.
_FULLY_OPTED_OUT = Q(communication_preferences__contains={ch: False for ch in _ALL_CHANNELS})


def _audit(patient, action: str, payload: dict) -> None:
    AuditEvent.objects.create(
        actor_type="agent", actor_id="outreach", patient=patient,
        action=action, payload=payload,
    )


# -- FR-O1/O2: criteria -> queryset -------------------------------------------

class UnsupportedCriteriaError(ValueError):
    """Raised when cohort_criteria names a key build_cohort() can't honor."""


_SUPPORTED_CRITERIA_KEYS = frozenset({
    "age_min", "age_max",
    "months_since_last_visit_gte",
    "missed_appointments_gte",
    "preferred_language_in",
    "exclude_patient_ids",
})


def _date_years_ago(base: date, years: int) -> date:
    try:
        return base.replace(year=base.year - years)
    except ValueError:
        # base was Feb 29 and (base.year - years) isn't a leap year.
        return base.replace(month=2, day=28, year=base.year - years)


def _date_months_ago(base: date, months: int) -> date:
    month_index = base.month - 1 - months
    year = base.year + month_index // 12
    month = month_index % 12 + 1
    day = min(base.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def build_cohort(criteria: dict) -> django_models.QuerySet:
    """Translate a cohort_criteria JSON dict into a single Patient queryset.

    Shared/reusable: Agent 8's caregaps app is expected to import this for
    its own population_criteria (SCHEMA.md notes cohort_criteria as "shared
    criteria schema ... reused by caregaps"). Extend _SUPPORTED_CRITERIA_KEYS
    and the filters below when new, genuinely-backed data becomes available
    -- don't loosen the unsupported-key error to paper over missing data.
    """
    criteria = criteria or {}
    unknown = set(criteria) - _SUPPORTED_CRITERIA_KEYS
    if unknown:
        raise UnsupportedCriteriaError(
            f"unsupported cohort criteria key(s): {sorted(unknown)}. Supported: "
            f"{sorted(_SUPPORTED_CRITERIA_KEYS)}."
        )

    today = timezone.localdate()
    qs = Patient.objects.all()

    if "age_min" in criteria:
        # age >= age_min  <=>  born on/before the day that is age_min years ago.
        qs = qs.filter(dob__lte=_date_years_ago(today, int(criteria["age_min"])))
    if "age_max" in criteria:
        # age <= age_max  <=>  born strictly after the day that is (age_max+1) years ago.
        qs = qs.filter(dob__gt=_date_years_ago(today, int(criteria["age_max"]) + 1))

    if "months_since_last_visit_gte" in criteria:
        cutoff = _date_months_ago(today, int(criteria["months_since_last_visit_gte"]))
        qs = qs.annotate(
            _last_completed_visit=Max(
                "appointment__start_time", filter=Q(appointment__status="completed"),
            ),
        ).filter(Q(_last_completed_visit__isnull=True) | Q(_last_completed_visit__date__lte=cutoff))

    if "missed_appointments_gte" in criteria:
        qs = qs.annotate(
            _missed_count=Count("appointment", filter=Q(appointment__status="no_show")),
        ).filter(_missed_count__gte=int(criteria["missed_appointments_gte"]))

    if "preferred_language_in" in criteria:
        qs = qs.filter(preferred_language__in=criteria["preferred_language_in"])

    if "exclude_patient_ids" in criteria:
        qs = qs.exclude(id__in=criteria["exclude_patient_ids"])

    return qs


# -- FR-O3: bulk enrollment ----------------------------------------------------

def enroll_cohort(campaign: Campaign, assigned_physician: Doctor | None = None) -> dict:
    """Bulk-create CampaignMembers for everyone build_cohort() matches, minus
    patients already enrolled and patients who opted out of every channel.
    One SELECT to build the cohort, one SELECT for already-enrolled ids, one
    bulk INSERT — never a per-patient round trip (NFR-9).
    """
    cohort = build_cohort(campaign.cohort_criteria).exclude(_FULLY_OPTED_OUT)
    already_enrolled_ids = set(campaign.members.values_list("patient_id", flat=True))
    cohort = cohort.exclude(id__in=already_enrolled_ids)

    reason = (campaign.clinical_goal or campaign.name)[:200]
    to_create = [
        CampaignMember(
            campaign=campaign, patient=patient, outreach_reason=reason,
            assigned_physician=assigned_physician,
        )
        for patient in cohort
    ]
    CampaignMember.objects.bulk_create(to_create)
    return {"enrolled": len(to_create), "already_enrolled": len(already_enrolled_ids)}


# -- FR-O4/Edge Case 15: wave dispatch -----------------------------------------

def _parse_at(value: str):
    return timezone.datetime.fromisoformat(value)


def dispatch_wave(campaign: Campaign) -> dict:
    """Send the next due message for every member who still owes one,
    honoring the channel escalation plan. Members whose current attempt
    lands on a channel they've opted out of still get a (message-less)
    attempt recorded, so escalation moves on to the next channel instead of
    retrying a blocked one forever; exhausting the whole plan marks them
    unreachable.
    """
    plan = campaign.channel_plan or []
    if not plan:
        return {"queued": 0, "unreachable": 0}

    now = timezone.now()
    today = timezone.localdate()

    candidates = (
        campaign.members
        .filter(state__in=["identified", "contacted"])
        .exclude(Q(snooze_until__isnull=False) & Q(snooze_until__gt=today))
        .select_related("patient")
    )

    queued = 0
    newly_unreachable_ids = []
    for member in candidates:
        attempts = member.channel_attempts or []
        wave_index = len(attempts)
        if wave_index >= len(plan):
            newly_unreachable_ids.append(member.id)
            continue

        step = plan[wave_index]
        wait_days = step.get("wait_days", 0)
        anchor = _parse_at(attempts[-1]["at"]) if attempts else member.created_at
        if now < anchor + timedelta(days=wait_days):
            continue  # not due yet

        note = notify(
            member.patient, "outreach_message",
            {"name": member.patient.first_name, "reason": member.outreach_reason},
            channel=step["channel"],
        )
        if note is not None:
            OutboundMessage.objects.create(member=member, notification=note, wave_number=wave_index)
            member.state = "contacted"
            queued += 1
        attempts.append({
            "channel": step["channel"], "at": now.isoformat(),
            "message_id": note.id if note is not None else None,
        })
        member.channel_attempts = attempts
        member.save(update_fields=["channel_attempts", "state"])

    if newly_unreachable_ids:
        CampaignMember.objects.filter(id__in=newly_unreachable_ids).update(state="unreachable")

    return {"queued": queued, "unreachable": len(newly_unreachable_ids)}


# -- FR-O5/Edge Cases 13-14: inbound response handling -------------------------

def handle_response_action(member: CampaignMember, intent: str, *,
                            snooze_until: date | None = None,
                            response: InboundResponse | None = None) -> CampaignMember:
    """State machine driven by a classified inbound intent."""
    if intent == "book":
        member.state = "responded"
        member.save(update_fields=["state"])
        emit(
            "outreach.booking_requested", campaign_id=member.campaign_id, member_id=member.id,
            patient_id=member.patient_id, outreach_reason=member.outreach_reason,
        )
    elif intent == "snooze":
        if snooze_until is None:
            raise ValueError("intent='snooze' requires snooze_until")
        member.state = "snoozed"
        member.snooze_until = snooze_until
        member.save(update_fields=["state", "snooze_until"])
    elif intent == "opt_out":
        member.state = "opted_out"
        member.save(update_fields=["state"])
        patient = member.patient
        prefs = dict(patient.communication_preferences or {})
        prefs.update({ch: False for ch in _ALL_CHANNELS})
        patient.communication_preferences = prefs
        patient.save(update_fields=["communication_preferences"])
        _audit(patient, "outreach.opted_out", {"campaign_id": member.campaign_id, "member_id": member.id})
    elif intent in ("question", "unclear"):
        # "question" is meant to route into the normal chat flow (After-Hours
        # agent once it exists; until then a staff task list can just query
        # state="responded" + an unhandled InboundResponse). "unclear" gets
        # the same non-committal treatment -- a human decides, nothing is
        # guessed.
        member.state = "responded"
        member.save(update_fields=["state"])
    else:
        raise ValueError(f"unknown intent: {intent!r}")

    if response is not None:
        response.classified_intent = intent
        response.handled = True
        if snooze_until is not None:
            response.snooze_until = snooze_until
        response.save(update_fields=["classified_intent", "handled", "snooze_until"])

    return member


# -- FR-O7: funnel stats -------------------------------------------------------

def campaign_stats(campaign: Campaign) -> dict:
    members = campaign.members
    identified = members.count()
    sent = members.exclude(state="identified").count()
    delivered = (
        OutboundMessage.objects
        .filter(member__campaign=campaign, notification__status="delivered")
        .values("member_id").distinct().count()
    )
    responded = (
        InboundResponse.objects
        .filter(member__campaign=campaign)
        .values("member_id").distinct().count()
    )
    scheduled = members.filter(state__in=["scheduled", "completed"]).count()
    completed = members.filter(state="completed").count()

    return {
        "identified": identified,
        "sent": sent,
        "delivered": delivered,
        "responded": responded,
        "scheduled": scheduled,
        "completed": completed,
        "conversion_rate": round(scheduled / identified, 4) if identified else 0.0,
    }
