"""Outreach Phase 2 business logic tests (no AI yet)."""

import datetime

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from core.events import subscribe
from core.models import Doctor, Patient, SentNotification
from outreach.models import Campaign, CampaignMember, InboundResponse, OutboundMessage
from outreach.services import (
    UnsupportedCriteriaError,
    build_cohort,
    campaign_stats,
    dispatch_wave,
    enroll_cohort,
    handle_response_action,
)
from scheduling.models import Appointment


def make_patient(**overrides):
    defaults = dict(
        first_name="Test", last_name="Patient", contact_number="9000000000",
        email="test.patient@example.com",
        dob=datetime.date(1990, 1, 1), registration_status="complete",
    )
    defaults.update(overrides)
    return Patient.objects.create(**defaults)


@pytest.fixture
def campaign(db):
    return Campaign.objects.create(
        name="Flu shot 65+", clinical_goal="Get 65+ patients their flu shot",
        cohort_criteria={"age_min": 65},
        channel_plan=[{"channel": "sms", "wait_days": 0}, {"channel": "email", "wait_days": 3}],
    )


@pytest.fixture
def doctor(db):
    return Doctor.objects.create(name="Dr. Asha Mehta", specialty="General Medicine")


def age_dob(age: int) -> datetime.date:
    today = timezone.localdate()
    return today.replace(year=today.year - age)


class TestBuildCohort:
    def test_age_min_and_max(self, db):
        young = make_patient(dob=age_dob(30))
        senior = make_patient(dob=age_dob(70))
        borderline = make_patient(dob=age_dob(65))

        result = set(build_cohort({"age_min": 65}).values_list("id", flat=True))
        assert result == {senior.id, borderline.id}

        result = set(build_cohort({"age_max": 64}).values_list("id", flat=True))
        assert result == {young.id}

    def test_months_since_last_visit_gte_includes_never_visited(self, db, doctor):
        never_visited = make_patient()
        recently_visited = make_patient()
        Appointment.objects.create(
            doctor=doctor, patient=recently_visited,
            start_time=timezone.now() - datetime.timedelta(days=5),
            end_time=timezone.now() - datetime.timedelta(days=5, hours=-1),
            reason="checkup", urgency="routine", status="completed",
        )
        overdue = make_patient()
        Appointment.objects.create(
            doctor=doctor, patient=overdue,
            start_time=timezone.now() - datetime.timedelta(days=400),
            end_time=timezone.now() - datetime.timedelta(days=400, hours=-1),
            reason="checkup", urgency="routine", status="completed",
        )

        result = set(build_cohort({"months_since_last_visit_gte": 6}).values_list("id", flat=True))
        assert never_visited.id in result
        assert overdue.id in result
        assert recently_visited.id not in result

    def test_missed_appointments_gte(self, db, doctor):
        chronic_no_show = make_patient()
        for _ in range(2):
            Appointment.objects.create(
                doctor=doctor, patient=chronic_no_show,
                start_time=timezone.now() + datetime.timedelta(days=1),
                end_time=timezone.now() + datetime.timedelta(days=1, hours=1),
                reason="checkup", urgency="routine", status="no_show",
            )
        reliable = make_patient()

        result = set(build_cohort({"missed_appointments_gte": 2}).values_list("id", flat=True))
        assert result == {chronic_no_show.id}
        assert reliable.id not in result

    def test_unsupported_key_raises(self, db):
        with pytest.raises(UnsupportedCriteriaError):
            build_cohort({"vaccination_status": "flu_2025"})

    def test_empty_criteria_matches_everyone(self, db):
        make_patient()
        make_patient()
        assert build_cohort({}).count() == 2

    def test_preferred_language_in(self, db):
        hindi = make_patient(preferred_language="hi")
        make_patient(preferred_language="en")
        marathi = make_patient(preferred_language="mr")
        result = set(build_cohort({"preferred_language_in": ["hi", "mr"]}).values_list("id", flat=True))
        assert result == {hindi.id, marathi.id}

    def test_exclude_patient_ids(self, db):
        keep = make_patient()
        drop = make_patient()
        result = set(build_cohort({"exclude_patient_ids": [drop.id]}).values_list("id", flat=True))
        assert result == {keep.id}

    def test_age_cutoff_is_leap_day_safe(self, db, monkeypatch):
        # The age math anchors on *today*. When today is Feb 29 and the cutoff
        # year isn't a leap year, the naive today.replace(year=...) would
        # raise — build_cohort must fall back to Feb 28, not crash.
        import outreach.services as svc
        monkeypatch.setattr(svc.timezone, "localdate", lambda: datetime.date(2024, 2, 29))
        make_patient(dob=datetime.date(1950, 1, 1))  # comfortably older than 10
        # 2024 - 10 = 2014 (not a leap year) -> exercises the Feb-28 fallback.
        assert build_cohort({"age_min": 10}).count() == 1

    def test_one_query_regardless_of_cohort_size(self, db, doctor):
        for i in range(200):
            make_patient(dob=age_dob(70), contact_number=f"90000{i:05d}")

        with CaptureQueriesContext(connection) as ctx:
            list(build_cohort({"age_min": 65, "missed_appointments_gte": 1}))
        assert len(ctx.captured_queries) == 1, ctx.captured_queries


class TestEnrollCohort:
    def test_bulk_enrolls_matching_patients(self, campaign, doctor):
        make_patient(dob=age_dob(70))
        make_patient(dob=age_dob(70))
        make_patient(dob=age_dob(30))  # doesn't match age_min=65

        result = enroll_cohort(campaign)
        assert result == {"enrolled": 2, "already_enrolled": 0}
        assert campaign.members.count() == 2
        for member in campaign.members.all():
            assert member.outreach_reason == campaign.clinical_goal
            assert member.state == "identified"

    def test_excludes_fully_opted_out_patients(self, campaign):
        make_patient(dob=age_dob(70))
        make_patient(
            dob=age_dob(70),
            communication_preferences={"sms": False, "email": False, "voice": False, "whatsapp": False},
        )
        # Partial opt-out (not every channel) is still reachable and enrolled.
        make_patient(dob=age_dob(70), communication_preferences={"sms": False, "email": True})

        result = enroll_cohort(campaign)
        assert result["enrolled"] == 2

    def test_second_call_does_not_duplicate(self, campaign):
        make_patient(dob=age_dob(70))
        enroll_cohort(campaign)
        result = enroll_cohort(campaign)
        assert result == {"enrolled": 0, "already_enrolled": 1}
        assert campaign.members.count() == 1

    def test_assigned_physician_applied_uniformly(self, campaign, doctor):
        make_patient(dob=age_dob(70))
        enroll_cohort(campaign, assigned_physician=doctor)
        member = campaign.members.get()
        assert member.assigned_physician_id == doctor.id


class TestDispatchWave:
    def test_wave_zero_sent_immediately(self, campaign):
        patient = make_patient(dob=age_dob(70))
        enroll_cohort(campaign)
        result = dispatch_wave(campaign)

        assert result["queued"] == 1
        member = campaign.members.get()
        assert member.state == "contacted"
        assert len(member.channel_attempts) == 1
        assert member.channel_attempts[0]["channel"] == "sms"
        assert OutboundMessage.objects.filter(member=member, wave_number=0).exists()
        note = SentNotification.objects.get(patient=patient)
        assert campaign.clinical_goal in note.rendered_content

    def test_second_channel_waits_for_wait_days(self, campaign):
        make_patient(dob=age_dob(70))
        enroll_cohort(campaign)
        dispatch_wave(campaign)  # wave 0 (sms, wait_days=0) sent

        # Immediately re-dispatching should NOT send wave 1 (email, wait_days=3) yet.
        result = dispatch_wave(campaign)
        assert result["queued"] == 0
        member = campaign.members.get()
        assert len(member.channel_attempts) == 1

    def test_escalates_to_next_channel_after_wait_elapses(self, campaign):
        make_patient(dob=age_dob(70))
        enroll_cohort(campaign)
        dispatch_wave(campaign)
        member = campaign.members.get()
        # Simulate wave 0 having happened 4 days ago (past the 3-day wait).
        member.channel_attempts[0]["at"] = (timezone.now() - datetime.timedelta(days=4)).isoformat()
        member.save(update_fields=["channel_attempts"])

        result = dispatch_wave(campaign)
        assert result["queued"] == 1
        member.refresh_from_db()
        assert len(member.channel_attempts) == 2
        assert member.channel_attempts[1]["channel"] == "email"

    def test_snoozed_member_is_skipped_until_snooze_expires(self, campaign):
        make_patient(dob=age_dob(70))
        enroll_cohort(campaign)
        member = campaign.members.get()
        member.state = "snoozed"
        member.snooze_until = timezone.localdate() + datetime.timedelta(days=10)
        member.save(update_fields=["state", "snooze_until"])

        assert dispatch_wave(campaign)["queued"] == 0

        member.snooze_until = timezone.localdate() - datetime.timedelta(days=1)
        member.state = "identified"
        member.save(update_fields=["state", "snooze_until"])
        assert dispatch_wave(campaign)["queued"] == 1

    def test_channel_opt_out_advances_wave_without_sending(self, campaign):
        make_patient(
            dob=age_dob(70),
            communication_preferences={"sms": False},  # only sms opted out
        )
        enroll_cohort(campaign)
        result = dispatch_wave(campaign)

        assert result["queued"] == 0
        member = campaign.members.get()
        assert member.state == "identified"  # nothing was actually sent
        assert len(member.channel_attempts) == 1
        assert member.channel_attempts[0]["message_id"] is None

    def test_exhausting_the_plan_marks_unreachable(self, campaign):
        make_patient(dob=age_dob(70))
        enroll_cohort(campaign)
        member = campaign.members.get()

        dispatch_wave(campaign)  # wave 0 (sms) sent
        member.refresh_from_db()
        member.channel_attempts[0]["at"] = (timezone.now() - datetime.timedelta(days=4)).isoformat()
        member.save(update_fields=["channel_attempts"])

        dispatch_wave(campaign)  # wave 1 (email) sent -- plan now exhausted
        member.refresh_from_db()
        assert len(member.channel_attempts) == 2

        result = dispatch_wave(campaign)  # nothing left to send
        assert result["queued"] == 0
        assert result["unreachable"] == 1
        member.refresh_from_db()
        assert member.state == "unreachable"

    def test_no_channel_plan_is_a_no_op(self, db):
        empty_plan_campaign = Campaign.objects.create(
            name="No plan", clinical_goal="x", cohort_criteria={}, channel_plan=[],
        )
        assert dispatch_wave(empty_plan_campaign) == {"queued": 0, "unreachable": 0}


class TestHandleResponseAction:
    @pytest.fixture
    def member(self, campaign):
        patient = make_patient(dob=age_dob(70))
        return CampaignMember.objects.create(campaign=campaign, patient=patient, outreach_reason="flu shot")

    def test_book_sets_responded_and_emits_event(self, member):
        received = []

        @subscribe("outreach.booking_requested")
        def _capture(**payload):
            received.append(payload)

        handle_response_action(member, "book")
        member.refresh_from_db()
        assert member.state == "responded"
        assert received and received[0]["member_id"] == member.id

    def test_snooze_requires_date(self, member):
        with pytest.raises(ValueError):
            handle_response_action(member, "snooze")

    def test_snooze_sets_state_and_date(self, member):
        until = timezone.localdate() + datetime.timedelta(days=30)
        handle_response_action(member, "snooze", snooze_until=until)
        member.refresh_from_db()
        assert member.state == "snoozed"
        assert member.snooze_until == until

    def test_opt_out_updates_patient_preferences_for_every_channel(self, member):
        handle_response_action(member, "opt_out")
        member.refresh_from_db()
        member.patient.refresh_from_db()
        assert member.state == "opted_out"
        prefs = member.patient.communication_preferences
        assert all(prefs[ch] is False for ch in ("sms", "email", "voice", "whatsapp"))

    def test_opt_out_excludes_from_future_campaign_enrollment(self, member, campaign):
        handle_response_action(member, "opt_out")
        other_campaign = Campaign.objects.create(
            name="Another campaign", clinical_goal="x", cohort_criteria={"age_min": 65}, channel_plan=[],
        )
        result = enroll_cohort(other_campaign)
        assert result["enrolled"] == 0

    def test_question_and_unclear_mark_responded_without_side_effects(self, member):
        handle_response_action(member, "question")
        member.refresh_from_db()
        assert member.state == "responded"

    def test_unknown_intent_raises(self, member):
        with pytest.raises(ValueError):
            handle_response_action(member, "not_a_real_intent")

    def test_marks_inbound_response_handled(self, member):
        response = InboundResponse.objects.create(member=member, raw_text="stop texting me")
        handle_response_action(member, "opt_out", response=response)
        response.refresh_from_db()
        assert response.handled is True
        assert response.classified_intent == "opt_out"


class TestCampaignStats:
    def test_funnel_math(self, campaign):
        patients = [make_patient(dob=age_dob(70)) for _ in range(5)]
        members = [
            CampaignMember.objects.create(campaign=campaign, patient=p, outreach_reason="flu shot")
            for p in patients
        ]
        # member 0: still just identified
        # members 1-4: contacted
        for m in members[1:]:
            m.state = "contacted"
            m.save(update_fields=["state"])
        # members 2-4 responded
        for m in members[2:]:
            InboundResponse.objects.create(member=m, raw_text="ok", classified_intent="book", handled=True)
        # members 3-4 scheduled
        for m in members[3:]:
            m.state = "scheduled"
            m.save(update_fields=["state"])
        # member 4 completed
        members[4].state = "completed"
        members[4].save(update_fields=["state"])

        stats = campaign_stats(campaign)
        assert stats["identified"] == 5
        assert stats["sent"] == 4
        assert stats["responded"] == 3
        assert stats["scheduled"] == 2
        assert stats["completed"] == 1
        assert stats["conversion_rate"] == round(2 / 5, 4)

    def test_zero_members_does_not_divide_by_zero(self, campaign):
        stats = campaign_stats(campaign)
        assert stats["identified"] == 0
        assert stats["conversion_rate"] == 0.0
        assert stats["by_channel"] == {}

    def test_by_channel_breakdown_counts_sent_messages(self, campaign):
        make_patient(dob=age_dob(70))
        make_patient(dob=age_dob(70))
        enroll_cohort(campaign)
        dispatch_wave(campaign)  # channel_plan wave 0 is sms for both members
        stats = campaign_stats(campaign)
        # SentNotification records the channel as "SMS" (its own casing).
        assert sum(stats["by_channel"].values()) == 2
