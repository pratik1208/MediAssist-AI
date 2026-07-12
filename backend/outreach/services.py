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

# How far ahead to look for an auto-booked slot when a member replies "book"
# (FR-O6). Outreach is proactive/routine, so a couple of weeks is plenty.
_AUTOBOOK_WINDOW_DAYS = 14
_AUTOBOOK_DEFAULT_SPECIALTY = "General Medicine"

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

        # render_message() returns fully-rendered, already-personalized text;
        # passing it as notify()'s "template" works because render_template()
        # falls back to using an unrecognized string as-is when there's no
        # matching key in _TEMPLATES, and .format() is a no-op on a string
        # with no {placeholders} left in it.
        rendered = render_message(member, campaign.clinical_goal)
        note = notify(member.patient, rendered, {}, channel=step["channel"])
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


# -- FR-O4 (Phase 4): AI-personalized message body, cached per (language, goal) --

_MESSAGE_BODY_CACHE: dict[tuple[str, str], str] = {}


def render_message(member: CampaignMember, template_goal: str) -> str:
    """The per-patient message text: an AI-written body for this member's
    language + the campaign's clinical goal, with "Hi {name}," prepended.

    Cached per (language, template_goal) — personalization beyond the name
    is deliberately light, so a 5,000-patient wave makes at most a handful
    of AI calls (one per language actually present in the cohort), never
    one per patient (NFR-9). An AI outage never blocks a wave: it falls
    back to the plain, non-AI Phase 2 wording instead of leaving the
    member unmessaged.
    """
    patient = member.patient
    language = patient.preferred_language
    cache_key = (language, template_goal)
    body = _MESSAGE_BODY_CACHE.get(cache_key)
    if body is None:
        try:
            from outreach.ai import render_outreach_message_body  # local: keeps AI optional
            body = render_outreach_message_body(template_goal, language)["body"]
        except Exception:
            log.warning("[OUTREACH RENDER] AI message generation failed for goal=%r "
                       "lang=%r — using fallback wording", template_goal, language)
            body = f"{template_goal}. Reply to let us know, or call the clinic to book. Reply STOP to opt out."
        _MESSAGE_BODY_CACHE[cache_key] = body
    return f"Hi {patient.first_name}, {body}"


# -- FR-O6: auto-book the resulting appointment via Agent 1 --------------------

def _resolve_booking_doctor(member: CampaignMember) -> Doctor | None:
    """Which doctor an auto-booked outreach appointment goes to: the member's
    assigned physician if there is one, else an active general-medicine
    doctor, else any active doctor. None if the clinic has no active
    doctors at all (then we can't auto-book and fall back to an offer)."""
    if member.assigned_physician and member.assigned_physician.is_active:
        return member.assigned_physician
    gm = Doctor.objects.filter(specialty=_AUTOBOOK_DEFAULT_SPECIALTY, is_active=True).first()
    return gm or Doctor.objects.filter(is_active=True).first()


def book_member_appointment(member: CampaignMember):
    """FR-O6: schedule the appointment a "book" reply asked for, automatically,
    through Agent 1's shared booking door (same direct reuse referrals makes
    of scheduling.services). Returns the Appointment, or None if we couldn't
    auto-book (no doctor, or no open slot in the window) so the caller can
    fall back to a staff/patient offer instead. Never raises on a booking
    problem — a scheduling hiccup must not break response handling."""
    from scheduling.services import book_appointment, find_available_slots

    try:
        doctor = _resolve_booking_doctor(member)
        if doctor is None:
            return None
        # find_available_slots works in naive local wall-clock time (it builds
        # candidates with datetime.combine and compares against
        # timezone.localtime().replace(tzinfo=None)) — the same convention
        # referrals._parse_datetime documents. Pass the window the same way.
        now = timezone.localtime().replace(tzinfo=None)
        slots = find_available_slots(doctor, now, now + timedelta(days=_AUTOBOOK_WINDOW_DAYS))
        if not slots:
            return None
        start, end = slots[0]
        return book_appointment(
            doctor=doctor, patient=member.patient, start=start, end=end,
            reason=f"Outreach: {member.outreach_reason}", urgency="routine",
            source="outreach",
        )
    except Exception:
        log.warning("[OUTREACH BOOK] auto-book failed for member %s — falling back to offer",
                    member.id)
        return None


# -- FR-O5/Edge Cases 13-14: inbound response handling -------------------------

def handle_response_action(member: CampaignMember, intent: str, *,
                            snooze_until: date | None = None,
                            response: InboundResponse | None = None) -> CampaignMember:
    """State machine driven by a classified inbound intent."""
    if intent == "book":
        # FR-O6: try to schedule automatically. Success -> scheduled; if no
        # doctor/slot is available, fall back to "responded" + an event so
        # staff (or the patient, once After-Hours exists) can complete it.
        appointment = book_member_appointment(member)
        if appointment is not None:
            member.state = "scheduled"
            member.save(update_fields=["state"])
            _audit(member.patient, "outreach.appointment_booked", {
                "campaign_id": member.campaign_id, "member_id": member.id,
                "appointment_id": appointment.id,
            })
        else:
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


# -- FR-O5 (Phase 4): classify a raw reply, then run the state machine --------

# Standard US carrier/SMS-compliance opt-out keywords (TCPA/CTIA short-code
# rules): these must always work, model or no model, so they're checked
# BEFORE ever calling the AI -- opt-out compliance can't depend on an LLM
# being reachable. Deliberately an exact match on the whole normalized
# message, not a substring: "please don't stop asking, I'll book eventually"
# must NOT trip this, so more natural phrasings are left to the classifier.
_HARD_STOP_KEYWORDS = frozenset({"stop", "stopall", "unsubscribe", "cancel", "end", "quit"})


def _looks_like_hard_stop(text: str) -> bool:
    return text.strip().strip(".!?").lower() in _HARD_STOP_KEYWORDS


def classify_and_handle_response(member: CampaignMember, text: str,
                                  response: InboundResponse | None = None) -> str:
    """Turn a raw inbound reply into a classified intent and run the state
    machine. The failure mode to guard hardest against (per the build
    step) is misclassifying an opt-out as anything else, so this checks
    the deterministic keyword list first; only genuinely ambiguous text
    reaches the AI classifier. Any AI failure, or a claimed 'snooze' with
    no date the model could actually resolve, falls back to 'unclear' --
    the one intent with zero side effects -- rather than guessing.
    """
    if _looks_like_hard_stop(text):
        intent, snooze_until = "opt_out", None
    else:
        today = timezone.localdate().isoformat()
        try:
            from outreach.ai import classify_response as ai_classify_response  # local: keeps AI optional
            result = ai_classify_response(text, today)
            intent = result.get("intent") or "unclear"
            snooze_until = None
            if intent == "snooze":
                raw_date = result.get("snooze_until")
                try:
                    snooze_until = date.fromisoformat(raw_date) if raw_date else None
                except ValueError:
                    snooze_until = None
                if snooze_until is None:
                    intent = "unclear"  # claimed snooze but no resolvable date -- don't guess
        except Exception:
            log.warning("[OUTREACH CLASSIFY] AI classification failed — treating as unclear")
            intent, snooze_until = "unclear", None

    handle_response_action(member, intent, snooze_until=snooze_until, response=response)
    return intent


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

    # Per-channel breakdown for the analytics dashboard: how many messages
    # actually went out on each channel. One grouped aggregate, not a
    # per-member loop — the notification carries the channel (SentNotification
    # uses "SMS"/"email"/"whatsapp"), so this survives at cohort scale (NFR-9).
    by_channel = {
        row["notification__channel"]: row["n"]
        for row in (
            OutboundMessage.objects
            .filter(member__campaign=campaign)
            .values("notification__channel")
            .annotate(n=Count("id"))
        )
    }

    return {
        "identified": identified,
        "sent": sent,
        "delivered": delivered,
        "responded": responded,
        "scheduled": scheduled,
        "completed": completed,
        "conversion_rate": round(scheduled / identified, 4) if identified else 0.0,
        "by_channel": by_channel,
    }
