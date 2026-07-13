"""Phase 6 integration: care-gap outreach rides Agent 7 (FR-G5), booking
rides Agent 1 (FR-G6), the scheduling-surface hook, completion detection via
appointment.completed, and PRD Edge Case 17 (the recycle loop re-enters
outreach). AI is blocked by conftest, so wave messages exercise the
deterministic fallback path."""

import datetime

import pytest
from django.utils import timezone

from caregaps import services
from caregaps.models import CareGap, CarePlan, ClinicalEvent, ClinicalGuideline
from core.models import Doctor, Patient, SentNotification
from outreach import services as outreach_services
from outreach.models import Campaign, CampaignMember, OutboundMessage
from scheduling.models import Appointment
from scheduling.services import complete_appointment

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()


@pytest.fixture
def doctor(db):
    hours = {day: [["09:00", "17:00"]] for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}
    return Doctor.objects.create(
        name="Dr. Asha Mehta", specialty="General Medicine", working_hours=hours)


def make_patient(first="Asha", phone="9000000001", age=70, prefs=None):
    return Patient.objects.create(
        first_name=first, last_name="Rao", contact_number=phone,
        dob=datetime.date(TODAY.year - age, 1, 15),
        communication_preferences=prefs or {}, registration_status="complete",
    )


def make_guideline(name="Flu 65+", code="140", item_type="vaccination", risk="medium"):
    return ClinicalGuideline.objects.create(
        name=name, population_criteria={"age_min": 65}, care_item_type=item_type,
        care_item_code=code, frequency_days=365, risk_tier=risk,
    )


def seeded_plan(patient):
    services.scan_patient(patient)
    return services.bundle_care_plan(patient)


class TestHasOpenCarePlanCriteria:
    def test_matches_only_patients_with_live_plans(self):
        planned = make_patient(phone="9000000001")
        unplanned = make_patient(first="Ravi", phone="9000000002")
        make_guideline()
        seeded_plan(planned)

        cohort = outreach_services.build_cohort({"has_open_care_plan": True})
        assert set(cohort.values_list("id", flat=True)) == {planned.id}
        assert unplanned.id not in set(cohort.values_list("id", flat=True))

    def test_completed_plans_do_not_match(self):
        patient = make_patient()
        make_guideline()
        plan = seeded_plan(patient)
        plan.status = "completed"
        plan.save()
        assert outreach_services.build_cohort({"has_open_care_plan": True}).count() == 0


class TestPushPlansToOutreach:
    def test_creates_campaign_enrolls_and_sends_personalized_wave(self):
        patient = make_patient()
        make_guideline(name="Annual flu vaccine")
        plan = seeded_plan(patient)

        result = services.push_plans_to_outreach()

        campaign = Campaign.objects.get(name=services.CAREGAP_CAMPAIGN_NAME)
        assert result["campaign_id"] == campaign.id
        assert result["sent"] == 1
        assert result["wave"]["queued"] == 1
        assert campaign.status == "running"
        assert campaign.cohort_criteria == {"has_open_care_plan": True}

        member = CampaignMember.objects.get(campaign=campaign, patient=patient)
        # per-member goal: the member carries THEIR plan summary
        assert "Annual flu vaccine" in member.outreach_reason
        assert member.state == "contacted"
        # message went out through core.notifications (the one door), with
        # the deterministic fallback body built from the member's own plan
        note = SentNotification.objects.get(patient=patient)
        assert "Annual flu vaccine" in note.rendered_content
        assert note.rendered_content.startswith("Hi Asha")

        plan.refresh_from_db()
        assert plan.status == "sent"
        assert set(plan.gaps.values_list("status", flat=True)) == {"outreach"}

    def test_no_draft_plans_is_a_noop(self):
        result = services.push_plans_to_outreach()
        assert result["sent"] == 0
        assert Campaign.objects.count() == 0

    def test_opted_out_patient_never_enrolled_plan_stays_draft(self):
        opted_out = {"sms": False, "email": False, "voice": False, "whatsapp": False}
        patient = make_patient(prefs=opted_out)
        make_guideline()
        plan = seeded_plan(patient)

        result = services.push_plans_to_outreach()
        assert result["skipped_opted_out"] == 1
        assert result["sent"] == 0
        assert CampaignMember.objects.count() == 0
        plan.refresh_from_db()
        assert plan.status == "draft"

    def test_push_twice_does_not_resend(self):
        patient = make_patient()
        make_guideline()
        seeded_plan(patient)
        services.push_plans_to_outreach()
        again = services.push_plans_to_outreach()
        assert again["sent"] == 0  # plan already sent, no drafts left
        assert OutboundMessage.objects.count() == 1

    def test_paused_campaign_is_honored(self):
        patient = make_patient()
        make_guideline()
        seeded_plan(patient)
        Campaign.objects.create(
            name=services.CAREGAP_CAMPAIGN_NAME, clinical_goal="g",
            cohort_criteria={"has_open_care_plan": True},
            channel_plan=[{"channel": "sms", "wait_days": 0}], status="paused",
        )
        result = services.push_plans_to_outreach()
        assert result.get("paused") is True
        assert result["sent"] == 0
        assert CarePlan.objects.get().status == "draft"


class TestBookingRidesAgentOne:
    def test_book_reply_books_via_agent1_and_advances_plan(self, doctor):
        """FR-G6 end to end: push -> patient replies 'book' -> outreach
        auto-books through scheduling -> the member_booked event moves the
        plan to in_progress and its gaps to scheduled."""
        patient = make_patient()
        make_guideline()
        plan = seeded_plan(patient)
        services.push_plans_to_outreach()
        member = CampaignMember.objects.get(patient=patient)

        outreach_services.handle_response_action(member, "book")

        appointment = Appointment.objects.get(patient=patient, source="outreach")
        assert "Annual flu vaccine" in appointment.reason or "Outreach" in appointment.reason
        member.refresh_from_db()
        assert member.state == "scheduled"
        plan.refresh_from_db()
        assert plan.status == "in_progress"
        assert set(plan.gaps.values_list("status", flat=True)) == {"scheduled"}

    def test_completion_event_advances_and_closes_on_evidence(self, doctor):
        """The last leg: the visit completes -> gaps move to 'completed';
        the vaccination event lands -> the rescan inside the handler closes
        the gap with evidence and the plan completes (FR-G8)."""
        patient = make_patient()
        make_guideline(code="140")
        plan = seeded_plan(patient)
        services.push_plans_to_outreach()
        member = CampaignMember.objects.get(patient=patient)
        outreach_services.handle_response_action(member, "book")
        appointment = Appointment.objects.get(patient=patient, source="outreach")

        # the vaccine was given at the visit; its event is recorded first
        evidence = ClinicalEvent.objects.create(
            patient=patient, event_type="vaccination", code="140",
            occurred_at=timezone.now())
        complete_appointment(appointment)

        appointment.refresh_from_db()
        assert appointment.status == "completed"
        gap = CareGap.objects.get(patient=patient)
        assert gap.status == "closed"
        assert gap.closing_event == evidence
        plan.refresh_from_db()
        assert plan.status == "completed"


class TestSchedulingSurfaceHook:
    def test_open_gaps_for_returns_compact_priority_list(self):
        patient = make_patient()
        make_guideline(name="Flu", code="140", risk="medium")
        make_guideline(name="HbA1c", code="4548-4", item_type="test", risk="high")
        services.scan_patient(patient)

        offers = services.open_gaps_for(patient)
        assert [o["guideline"] for o in offers] == ["HbA1c", "Flu"]  # high first
        assert {"gap_id", "guideline", "care_item_type", "risk_tier",
                "days_overdue"} == set(offers[0])

    def test_booking_response_carries_care_gap_offers(self, client, doctor):
        patient = make_patient()
        make_guideline(name="Flu vaccine", code="140")
        services.scan_patient(patient)

        start = timezone.now() + datetime.timedelta(days=1)
        response = client.post("/api/appointments", {
            "doctor": doctor.id, "patient": patient.id,
            "start_time": start.isoformat(),
            "end_time": (start + datetime.timedelta(minutes=20)).isoformat(),
            "reason": "checkup", "urgency": "routine",
            "status": "booked", "source": "scheduling",
        }, content_type="application/json")
        assert response.status_code == 201
        offers = response.json()["care_gap_offers"]
        assert [o["guideline"] for o in offers] == ["Flu vaccine"]

    def test_completed_patch_via_api_fires_completion_detection(self, client, doctor):
        patient = make_patient()
        make_guideline(code="140")
        services.scan_patient(patient)
        gap = CareGap.objects.get()
        gap.status = "scheduled"
        gap.save()
        start = timezone.now() - datetime.timedelta(days=1)
        appointment = Appointment.objects.create(
            doctor=doctor, patient=patient, start_time=start,
            end_time=start + datetime.timedelta(minutes=20),
            reason="visit", urgency="routine", status="booked", source="scheduling")

        response = client.patch(f"/api/appointments/{appointment.id}",
                                {"status": "completed"}, content_type="application/json")
        assert response.status_code == 200
        gap.refresh_from_db()
        assert gap.status == "completed"  # advanced by the event handler


class TestEdgeCase17RecycleLoop:
    def test_recycled_plan_reenters_outreach_with_fresh_ladder(self, doctor):
        """PRD Edge Case 17: a sent plan nobody acted on for 30+ days is
        recycled; the patient is re-bundled and RE-messaged from the top of
        the escalation ladder — one campaign, one membership, a fresh cycle."""
        patient = make_patient()
        make_guideline()
        seeded_plan(patient)
        services.push_plans_to_outreach()
        member = CampaignMember.objects.get(patient=patient)
        assert member.state == "contacted"
        assert OutboundMessage.objects.count() == 1

        # a month passes with no response
        plan = CarePlan.objects.get()
        CarePlan.objects.filter(id=plan.id).update(
            created_at=timezone.now() - datetime.timedelta(days=45))
        recycled = services.recycle_incomplete()
        assert [p.id for p in recycled] == [plan.id]
        assert CareGap.objects.get().status == "open"

        # the nightly pipeline re-bundles and re-pushes
        assert services.bundle_all() == 1
        result = services.push_plans_to_outreach()
        assert result["sent"] == 1
        member.refresh_from_db()
        assert member.state == "contacted"  # re-enrolled and re-messaged
        assert OutboundMessage.objects.count() == 2  # a genuinely new send
        new_plan = CarePlan.objects.exclude(id=plan.id).get()
        assert new_plan.status == "sent"

    def test_recycle_never_overrides_opt_out(self, doctor):
        patient = make_patient()
        make_guideline()
        seeded_plan(patient)
        services.push_plans_to_outreach()
        member = CampaignMember.objects.get(patient=patient)
        outreach_services.handle_response_action(member, "opt_out")

        plan = CarePlan.objects.get()
        CarePlan.objects.filter(id=plan.id).update(
            created_at=timezone.now() - datetime.timedelta(days=45))
        services.recycle_incomplete()
        services.bundle_all()
        result = services.push_plans_to_outreach()

        assert result["sent"] == 0
        assert result["skipped_opted_out"] == 1
        member.refresh_from_db()
        assert member.state == "opted_out"
        assert OutboundMessage.objects.count() == 1  # nothing new was sent


class TestPushOutreachAPI:
    def test_staff_button(self, client, db):
        from django.contrib.auth import get_user_model
        staff = get_user_model().objects.create_user("q", password="x", is_staff=True)
        client.force_login(staff)
        patient = make_patient()
        make_guideline()
        services.scan_patient(patient)

        response = client.post("/api/staff/caregaps/push-outreach/")
        assert response.status_code == 200
        body = response.json()
        assert body["bundled"] == 1
        assert body["sent"] == 1

    def test_anonymous_rejected(self, client, db):
        assert client.post("/api/staff/caregaps/push-outreach/").status_code in (401, 403)
