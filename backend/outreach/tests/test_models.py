"""Human-readable __str__ / admin display helpers — cheap to verify, and
they show up in the admin (a real staff surface until the dashboard)."""

import datetime

import pytest

from core.models import Doctor, Patient, SentNotification
from outreach.admin import CampaignAdmin
from outreach.models import Campaign, CampaignMember, InboundResponse, OutboundMessage


@pytest.fixture
def patient(db):
    return Patient.objects.create(
        first_name="Rahul", last_name="Sharma", contact_number="9876543210",
        email="r@example.com", dob=datetime.date(1955, 5, 17), registration_status="complete",
    )


@pytest.fixture
def campaign(db):
    return Campaign.objects.create(
        name="Flu shot 65+", clinical_goal="flu shots",
        cohort_criteria={"age_min": 65}, channel_plan=[{"channel": "sms", "wait_days": 0}],
    )


def test_campaign_str(campaign):
    assert str(campaign) == "Flu shot 65+ (draft)"


def test_campaign_member_str(campaign, patient):
    member = CampaignMember.objects.create(campaign=campaign, patient=patient, outreach_reason="flu")
    assert "Rahul Sharma" in str(member)
    assert "Flu shot 65+" in str(member)
    assert "identified" in str(member)


def test_outbound_and_inbound_str(campaign, patient):
    member = CampaignMember.objects.create(campaign=campaign, patient=patient, outreach_reason="flu")
    note = SentNotification.objects.create(
        patient=patient, channel="sms", recipient="9876543210",
        rendered_content="hi", status="sent",
    )
    outbound = OutboundMessage.objects.create(member=member, notification=note, wave_number=0)
    assert f"member #{member.id}" in str(outbound)

    inbound = InboundResponse.objects.create(member=member, raw_text="yes")
    assert "unclassified" in str(inbound)
    inbound.classified_intent = "book"
    assert "book" in str(inbound)


def test_admin_member_count(campaign, patient):
    CampaignMember.objects.create(campaign=campaign, patient=patient, outreach_reason="flu")
    admin = CampaignAdmin(Campaign, None)
    assert admin.member_count(campaign) == 1
