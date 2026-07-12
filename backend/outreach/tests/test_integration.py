"""Outreach Phase 6: cross-agent integration (FR-O6 auto-booking through
Agent 1, NFR-8 opt-out propagation) and PRD Edge Cases 13/14/15."""

import datetime

import pytest
from django.core.management import call_command
from django.utils import timezone

from core.models import Doctor, Patient, SentNotification
from core.notifications import notify
from outreach.models import Campaign, CampaignMember, InboundResponse
from outreach.services import (
    campaign_stats,
    classify_and_handle_response,
    dispatch_wave,
    enroll_cohort,
    handle_response_action,
)
from scheduling.models import Appointment

ALL_WEEK = {d: [["08:00", "18:00"]] for d in ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]}


def age_dob(age: int) -> datetime.date:
    today = timezone.localdate()
    return today.replace(year=today.year - age)


def make_patient(**overrides):
    defaults = dict(
        first_name="Test", last_name="Patient", contact_number="9000000000",
        email="test.patient@example.com", dob=age_dob(70),
        registration_status="complete",
    )
    defaults.update(overrides)
    return Patient.objects.create(**defaults)


@pytest.fixture
def bookable_doctor(db):
    return Doctor.objects.create(
        name="Dr. Asha Mehta", specialty="General Medicine",
        working_hours=ALL_WEEK, avg_consult_minutes=20, buffer_minutes=0, is_active=True,
    )


@pytest.fixture
def campaign(db):
    return Campaign.objects.create(
        name="Flu shot 65+", clinical_goal="come in for your annual flu shot",
        cohort_criteria={"age_min": 65},
        channel_plan=[
            {"channel": "sms", "wait_days": 0},
            {"channel": "email", "wait_days": 3},
            {"channel": "voice", "wait_days": 7},
        ],
    )


def make_member(campaign, patient, **overrides):
    defaults = dict(campaign=campaign, patient=patient, state="contacted", outreach_reason="flu shot")
    defaults.update(overrides)
    return CampaignMember.objects.create(**defaults)


# -- FR-O6: booking handoff creates a real appointment via Agent 1 -------------

class TestAutoBooking:
    def test_book_reply_creates_real_appointment_and_advances_to_scheduled(
        self, campaign, bookable_doctor
    ):
        member = make_member(campaign, make_patient())
        handle_response_action(member, "book")

        member.refresh_from_db()
        assert member.state == "scheduled"
        appt = Appointment.objects.get(patient=member.patient)
        assert appt.doctor_id == bookable_doctor.id
        assert appt.source == "outreach"
        assert appt.status == "booked"
        # Agent 1's own appointment.booked subscriber sends the confirmation SMS.
        assert SentNotification.objects.filter(
            patient=member.patient, rendered_content__icontains="confirmed",
        ).exists()

    def test_prefers_the_members_assigned_physician(self, campaign, bookable_doctor):
        other = Doctor.objects.create(
            name="Dr. Preferred", specialty="General Medicine",
            working_hours=ALL_WEEK, is_active=True,
        )
        member = make_member(campaign, make_patient(), assigned_physician=other)
        handle_response_action(member, "book")
        appt = Appointment.objects.get(patient=member.patient)
        assert appt.doctor_id == other.id

    def test_no_doctor_falls_back_to_responded_plus_event(self, campaign):
        # No Doctor rows exist -> can't auto-book -> offer fallback.
        received = []
        from core.events import subscribe

        @subscribe("outreach.booking_requested")
        def _capture(**payload):
            received.append(payload)

        member = make_member(campaign, make_patient())
        handle_response_action(member, "book")
        member.refresh_from_db()
        assert member.state == "responded"
        assert not Appointment.objects.filter(patient=member.patient).exists()
        assert received and received[0]["member_id"] == member.id

    def test_no_available_slot_falls_back_to_responded(self, campaign):
        # An active doctor with NO working hours yields no slots.
        Doctor.objects.create(name="Dr. Busy", specialty="General Medicine",
                              working_hours={}, is_active=True)
        member = make_member(campaign, make_patient())
        handle_response_action(member, "book")
        member.refresh_from_db()
        assert member.state == "responded"
        assert not Appointment.objects.filter(patient=member.patient).exists()

    def test_scheduled_member_counts_in_the_funnel(self, campaign, bookable_doctor):
        member = make_member(campaign, make_patient())
        handle_response_action(member, "book")
        stats = campaign_stats(campaign)
        assert stats["scheduled"] == 1
        assert stats["conversion_rate"] == 1.0

    def test_booking_exception_is_swallowed_and_falls_back(self, campaign, bookable_doctor):
        # A slot exists, but the booking call itself blows up — response
        # handling must not crash; the member falls back to responded.
        from unittest.mock import patch

        member = make_member(campaign, make_patient())
        with patch("scheduling.services.book_appointment", side_effect=RuntimeError("db hiccup")):
            handle_response_action(member, "book")
        member.refresh_from_db()
        assert member.state == "responded"
        assert not Appointment.objects.filter(patient=member.patient).exists()


# -- NFR-8 (cross-module): opt-out propagates everywhere -----------------------

class TestOptOutPropagation:
    def test_opt_out_blocks_scheduling_reminders_and_future_campaigns(self, campaign):
        patient = make_patient()
        member = make_member(campaign, patient)
        handle_response_action(member, "opt_out")

        patient.refresh_from_db()

        # 1) Scheduling (and every other module) goes through core.notify(),
        #    which now returns None for this patient -> no message escapes.
        assert notify(patient, "appointment_booked",
                      {"name": patient.first_name, "doctor": "X", "start": "Y"}) is None
        assert not SentNotification.objects.filter(patient=patient).exists()

        # 2) A brand-new campaign targeting the same cohort excludes them.
        other = Campaign.objects.create(
            name="Mammogram 65+", clinical_goal="x",
            cohort_criteria={"age_min": 65}, channel_plan=[{"channel": "sms", "wait_days": 0}],
        )
        assert enroll_cohort(other)["enrolled"] == 0


# -- PRD Edge Case 13: patient opts out ---------------------------------------

class TestEdgeCase13OptOut:
    def test_opt_out_recorded_and_prefs_updated_across_channels(self, campaign):
        member = make_member(campaign, make_patient())
        response = InboundResponse.objects.create(member=member, raw_text="STOP")
        # goes through the deterministic hard-stop path, no AI needed
        intent = classify_and_handle_response(member, "STOP", response=response)
        assert intent == "opt_out"
        member.refresh_from_db()
        member.patient.refresh_from_db()
        assert member.state == "opted_out"
        prefs = member.patient.communication_preferences
        assert all(prefs[ch] is False for ch in ("sms", "email", "voice", "whatsapp"))
        response.refresh_from_db()
        assert response.handled and response.classified_intent == "opt_out"


# -- PRD Edge Case 14: patient defers ("remind me next month") -----------------

class TestEdgeCase14Snooze:
    def test_snooze_pauses_until_the_requested_date(self, campaign, bookable_doctor):
        member = make_member(campaign, make_patient())
        until = timezone.localdate() + datetime.timedelta(days=30)
        handle_response_action(member, "snooze", snooze_until=until)
        member.refresh_from_db()
        assert member.state == "snoozed"
        assert member.snooze_until == until

        # Wave dispatch skips them while snoozed...
        assert dispatch_wave(campaign)["queued"] == 0

        # ...and resumes once the snooze date has passed.
        member.snooze_until = timezone.localdate() - datetime.timedelta(days=1)
        member.state = "identified"
        member.save(update_fields=["snooze_until", "state"])
        assert dispatch_wave(campaign)["queued"] == 1


# -- PRD Edge Case 15: non-responder escalates SMS -> email -> voice -----------

class TestEdgeCase15Escalation:
    def test_non_responder_escalates_through_the_channel_plan(self, campaign):
        make_member(campaign, make_patient(), state="identified", channel_attempts=[])
        member = campaign.members.get()

        # wave 0: sms (wait_days 0)
        dispatch_wave(campaign)
        member.refresh_from_db()
        assert [a["channel"] for a in member.channel_attempts] == ["sms"]

        # backdate so the 3-day email wait has elapsed -> wave 1: email
        member.channel_attempts[0]["at"] = (timezone.now() - datetime.timedelta(days=4)).isoformat()
        member.save(update_fields=["channel_attempts"])
        dispatch_wave(campaign)
        member.refresh_from_db()
        assert [a["channel"] for a in member.channel_attempts] == ["sms", "email"]

        # backdate again past the 7-day voice wait -> wave 2: voice (AI voice agent)
        member.channel_attempts[1]["at"] = (timezone.now() - datetime.timedelta(days=8)).isoformat()
        member.save(update_fields=["channel_attempts"])
        dispatch_wave(campaign)
        member.refresh_from_db()
        assert [a["channel"] for a in member.channel_attempts] == ["sms", "email", "voice"]


# -- the daily scheduled job ---------------------------------------------------

class TestDispatchWavesCommand:
    def test_dispatches_running_campaigns_only(self, campaign, capsys):
        make_member(campaign, make_patient(contact_number="9111111111"),
                    state="identified", channel_attempts=[])
        paused = Campaign.objects.create(
            name="Paused one", clinical_goal="x", cohort_criteria={},
            channel_plan=[{"channel": "sms", "wait_days": 0}], status="paused",
        )
        make_member(paused, make_patient(contact_number="9222222222"),
                    state="identified", channel_attempts=[])

        campaign.status = "running"
        campaign.save(update_fields=["status"])
        call_command("dispatch_campaign_waves")

        # the running campaign's member got contacted; the paused one did not
        assert campaign.members.get().state == "contacted"
        assert paused.members.get().state == "identified"

    def test_no_running_campaigns_is_a_clean_noop(self, db, capsys):
        call_command("dispatch_campaign_waves")
        assert "no running campaigns" in capsys.readouterr().out
