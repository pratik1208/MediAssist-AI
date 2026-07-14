"""Outreach API (Phase 3): staff campaign management + the inbound webhook,
including a full lifecycle over HTTP (create -> preview -> launch -> reply
via webhook -> funnel updates)."""

import datetime
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from core.models import Patient, SentNotification
from outreach.models import Campaign, CampaignMember, InboundResponse

STAFF_URL = "/api/staff/outreach/"
WEBHOOK_URL = "/api/outreach/webhook/"

VALID_PLAN = [{"channel": "sms", "wait_days": 0}, {"channel": "email", "wait_days": 3}]


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
def staff_client(client, db):
    staff = get_user_model().objects.create_user("coordinator", password="x", is_staff=True)
    client.force_login(staff)
    return client


def post_json(client, url, data):
    return client.post(url, data, content_type="application/json")


@pytest.fixture
def campaign(db):
    return Campaign.objects.create(
        name="Flu shot 65+", clinical_goal="Get 65+ patients their flu shot",
        cohort_criteria={"age_min": 65}, channel_plan=VALID_PLAN,
    )


class TestCreateCampaign:
    def test_requires_staff_login(self, client, db):
        assert post_json(client, STAFF_URL, {}).status_code == 403

    def test_missing_fields_is_400(self, staff_client):
        response = post_json(staff_client, STAFF_URL, {"name": "x"})
        assert response.status_code == 400
        assert "clinical_goal" in response.json()["error"]

    def test_unsupported_criteria_key_rejected_at_create_time(self, staff_client):
        response = post_json(staff_client, STAFF_URL, {
            "name": "x", "clinical_goal": "y",
            "cohort_criteria": {"vaccination_status": "flu"},
            "channel_plan": VALID_PLAN,
        })
        assert response.status_code == 400
        assert "vaccination_status" in response.json()["error"]

    def test_bad_channel_plan_rejected(self, staff_client):
        response = post_json(staff_client, STAFF_URL, {
            "name": "x", "clinical_goal": "y", "cohort_criteria": {"age_min": 65},
            "channel_plan": [{"channel": "carrier_pigeon"}],
        })
        assert response.status_code == 400

    def test_creates_a_draft(self, staff_client):
        response = post_json(staff_client, STAFF_URL, {
            "name": "Flu shot 65+", "clinical_goal": "flu shots",
            "cohort_criteria": {"age_min": 65}, "channel_plan": VALID_PLAN,
        })
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "draft"
        assert body["member_count"] == 0

    def test_list_campaigns(self, staff_client, campaign):
        response = staff_client.get(STAFF_URL)
        assert response.status_code == 200
        assert [c["id"] for c in response.json()] == [campaign.id]


class TestPreviewCohort:
    def test_count_and_sample(self, staff_client):
        make_patient(dob=age_dob(70))
        make_patient(dob=age_dob(30))
        response = post_json(staff_client, f"{STAFF_URL}preview-cohort/",
                             {"cohort_criteria": {"age_min": 65}})
        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 1
        assert len(body["sample"]) == 1
        assert body["sample"][0]["name"] == "Test Patient"

    def test_unsupported_key_is_400(self, staff_client):
        response = post_json(staff_client, f"{STAFF_URL}preview-cohort/",
                             {"cohort_criteria": {"hba1c_gt": 8}})
        assert response.status_code == 400


class TestLaunchPause:
    def test_launch_enrolls_and_dispatches_first_wave(self, staff_client, campaign):
        make_patient(dob=age_dob(70))
        response = post_json(staff_client, f"{STAFF_URL}{campaign.id}/launch/", {})
        assert response.status_code == 200
        body = response.json()
        assert body == {"status": "running", "enrolled": 1, "first_wave": {"queued": 1, "unreachable": 0}}
        campaign.refresh_from_db()
        assert campaign.status == "running"
        assert campaign.launched_at is not None
        member = campaign.members.get()
        assert member.state == "contacted"
        assert SentNotification.objects.filter(patient=member.patient).exists()

    def test_cannot_launch_twice(self, staff_client, campaign):
        post_json(staff_client, f"{STAFF_URL}{campaign.id}/launch/", {})
        response = post_json(staff_client, f"{STAFF_URL}{campaign.id}/launch/", {})
        assert response.status_code == 400

    def test_pause_and_resume(self, staff_client, campaign):
        post_json(staff_client, f"{STAFF_URL}{campaign.id}/launch/", {})
        response = post_json(staff_client, f"{STAFF_URL}{campaign.id}/pause/", {})
        assert response.status_code == 200
        campaign.refresh_from_db()
        assert campaign.status == "paused"

        # dispatch-wave refuses while paused
        response = post_json(staff_client, f"{STAFF_URL}{campaign.id}/dispatch-wave/", {})
        assert response.status_code == 400

        # relaunching resumes without re-enrolling
        response = post_json(staff_client, f"{STAFF_URL}{campaign.id}/launch/", {})
        assert response.json() == {"status": "running", "resumed": True}

    def test_pause_requires_running(self, staff_client, campaign):
        response = post_json(staff_client, f"{STAFF_URL}{campaign.id}/pause/", {})
        assert response.status_code == 400

    def test_launch_missing_campaign_is_404(self, staff_client):
        assert post_json(staff_client, f"{STAFF_URL}999999/launch/", {}).status_code == 404


class TestDetailStatsMembers:
    def test_detail_includes_stats(self, staff_client, campaign):
        make_patient(dob=age_dob(70))
        post_json(staff_client, f"{STAFF_URL}{campaign.id}/launch/", {})
        response = staff_client.get(f"{STAFF_URL}{campaign.id}/")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "running"
        assert body["stats"]["identified"] == 1
        assert body["stats"]["sent"] == 1

    def test_stats_endpoint(self, staff_client, campaign):
        response = staff_client.get(f"{STAFF_URL}{campaign.id}/stats/")
        assert response.status_code == 200
        assert response.json()["identified"] == 0

    def test_members_list_with_state_filter(self, staff_client, campaign):
        make_patient(dob=age_dob(70))
        post_json(staff_client, f"{STAFF_URL}{campaign.id}/launch/", {})
        response = staff_client.get(f"{STAFF_URL}{campaign.id}/members/")
        assert response.status_code == 200
        members = response.json()
        assert len(members) == 1
        assert members[0]["state"] == "contacted"
        assert members[0]["channel_attempts"][0]["channel"] == "sms"

        response = staff_client.get(f"{STAFF_URL}{campaign.id}/members/?state=identified")
        assert response.json() == []


class TestInboundWebhook:
    @pytest.fixture
    def contacted_member(self, campaign):
        patient = make_patient(contact_number="9111111111")
        campaign.status = "running"
        campaign.save(update_fields=["status"])
        return CampaignMember.objects.create(
            campaign=campaign, patient=patient, state="contacted",
            outreach_reason="flu shot",
        )

    def test_no_auth_required_and_records_response(self, client, contacted_member):
        with patch("outreach.ai.classify_response",
                  return_value={"intent": "question", "snooze_until": None,
                                "question_text": "what is this about?"}):
            response = post_json(client, WEBHOOK_URL,
                                 {"from": "9111111111", "text": "what is this about?"})
        assert response.status_code == 201
        body = response.json()
        assert body["member_id"] == contacted_member.id
        assert body["handled"] is True
        stored = InboundResponse.objects.get(id=body["response_id"])
        assert stored.raw_text == "what is this about?"
        assert stored.classified_intent == "question"

    def test_member_id_resolution(self, client, contacted_member):
        with patch("outreach.ai.classify_response",
                  return_value={"intent": "unclear", "snooze_until": None, "question_text": None}):
            response = post_json(client, WEBHOOK_URL,
                                 {"member_id": contacted_member.id, "text": "yes ok"})
        assert response.status_code == 201

    def test_unknown_sender_falls_through_to_frontdesk(self, client, db):
        """Phase 6: a sender with no campaign match at all is no longer a
        dead end — it's handed to the Agent 9 front door instead of 404ing."""
        from frontdesk.models import PatientSession
        response = post_json(client, WEBHOOK_URL, {"from": "0000000000", "text": "hi"})
        assert response.status_code == 200
        body = response.json()
        session = PatientSession.objects.get(id=body["session_id"])
        assert session.channel == "sms"
        assert session.channel_identifier == "0000000000"
        # no campaign involvement — this never touched InboundResponse
        assert InboundResponse.objects.count() == 0

    def test_empty_text_is_400(self, client, contacted_member):
        response = post_json(client, WEBHOOK_URL, {"from": "9111111111", "text": "  "})
        assert response.status_code == 400

    def test_explicit_opt_out_intent_is_applied(self, client, contacted_member):
        response = post_json(client, WEBHOOK_URL, {
            "from": "9111111111", "text": "STOP", "intent": "opt_out",
        })
        assert response.status_code == 201
        assert response.json()["member_state"] == "opted_out"
        contacted_member.patient.refresh_from_db()
        prefs = contacted_member.patient.communication_preferences
        assert prefs["sms"] is False and prefs["email"] is False

    def test_explicit_snooze_intent_with_date(self, client, contacted_member):
        until = (timezone.localdate() + datetime.timedelta(days=30)).isoformat()
        response = post_json(client, WEBHOOK_URL, {
            "from": "9111111111", "text": "not until next month",
            "intent": "snooze", "snooze_until": until,
        })
        assert response.status_code == 201
        assert response.json()["member_state"] == "snoozed"

    def test_bad_snooze_date_is_400(self, client, contacted_member):
        response = post_json(client, WEBHOOK_URL, {
            "from": "9111111111", "text": "later", "intent": "snooze",
            "snooze_until": "next month sometime",
        })
        assert response.status_code == 400

    def test_paused_campaign_members_fall_through_to_frontdesk(self, client, contacted_member):
        """A paused campaign isn't expecting replies, but a patient texting
        anyway still gets a front door rather than a 404 into the void."""
        contacted_member.campaign.status = "paused"
        contacted_member.campaign.save(update_fields=["status"])
        response = post_json(client, WEBHOOK_URL, {"from": "9111111111", "text": "hi"})
        assert response.status_code == 200
        assert InboundResponse.objects.count() == 0  # not treated as a campaign reply


class TestFullLifecycleOverHTTP:
    def test_create_preview_launch_reply_funnel(self, staff_client, client):
        make_patient(first_name="Meena", contact_number="9222222222", dob=age_dob(68))
        make_patient(first_name="Young", contact_number="9333333333", dob=age_dob(25))

        created = post_json(staff_client, STAFF_URL, {
            "name": "Flu shot 65+", "clinical_goal": "annual flu shot",
            "cohort_criteria": {"age_min": 65}, "channel_plan": VALID_PLAN,
        }).json()

        preview = post_json(staff_client, f"{STAFF_URL}preview-cohort/",
                            {"cohort_criteria": {"age_min": 65}}).json()
        assert preview["count"] == 1

        launch = post_json(staff_client, f"{STAFF_URL}{created['id']}/launch/", {}).json()
        assert launch["enrolled"] == 1
        assert launch["first_wave"]["queued"] == 1

        reply = post_json(client, WEBHOOK_URL, {
            "from": "9222222222", "text": "yes please book me", "intent": "book",
        }).json()
        assert reply["member_state"] == "responded"

        stats = staff_client.get(f"{STAFF_URL}{created['id']}/stats/").json()
        assert stats["identified"] == 1
        assert stats["sent"] == 1
        assert stats["responded"] == 1


class TestValidationBranches:
    def test_create_non_object_criteria_is_400(self, staff_client):
        response = post_json(staff_client, STAFF_URL, {
            "name": "x", "clinical_goal": "y",
            "cohort_criteria": ["not", "an", "object"], "channel_plan": VALID_PLAN,
        })
        assert response.status_code == 400
        assert "object" in response.json()["error"]

    def test_channel_plan_must_be_non_empty_list(self, staff_client):
        response = post_json(staff_client, STAFF_URL, {
            "name": "x", "clinical_goal": "y", "cohort_criteria": {"age_min": 65},
            "channel_plan": "sms",
        })
        assert response.status_code == 400
        assert "non-empty list" in response.json()["error"]

    def test_channel_plan_step_missing_channel_key(self, staff_client):
        response = post_json(staff_client, STAFF_URL, {
            "name": "x", "clinical_goal": "y", "cohort_criteria": {"age_min": 65},
            "channel_plan": [{"wait_days": 3}],
        })
        assert response.status_code == 400

    def test_channel_plan_negative_wait_days(self, staff_client):
        response = post_json(staff_client, STAFF_URL, {
            "name": "x", "clinical_goal": "y", "cohort_criteria": {"age_min": 65},
            "channel_plan": [{"channel": "sms", "wait_days": -3}],
        })
        assert response.status_code == 400
        assert "wait_days" in response.json()["error"]

    def test_preview_non_object_criteria_is_400(self, staff_client):
        response = post_json(staff_client, f"{STAFF_URL}preview-cohort/",
                             {"cohort_criteria": "age_min=65"})
        assert response.status_code == 400

    def test_list_status_filter(self, staff_client, campaign):
        # campaign fixture is a draft
        running = Campaign.objects.create(
            name="Live one", clinical_goal="x", cohort_criteria={},
            channel_plan=VALID_PLAN, status="running",
        )
        response = staff_client.get(f"{STAFF_URL}?status=running")
        assert [c["id"] for c in response.json()] == [running.id]


class TestNotFoundBranches:
    @pytest.mark.parametrize("path_suffix, method", [
        ("999999/", "get"),
        ("999999/stats/", "get"),
        ("999999/members/", "get"),
        ("999999/pause/", "post"),
        ("999999/dispatch-wave/", "post"),
    ])
    def test_missing_campaign_is_404(self, staff_client, path_suffix, method):
        url = f"{STAFF_URL}{path_suffix}"
        response = (staff_client.get(url) if method == "get"
                    else post_json(staff_client, url, {}))
        assert response.status_code == 404


class TestDispatchWaveEndpoint:
    def test_running_campaign_dispatch_returns_counts(self, staff_client, campaign):
        make_patient(dob=age_dob(70))
        post_json(staff_client, f"{STAFF_URL}{campaign.id}/launch/", {})
        # already dispatched wave 0 at launch; a second immediate call is due
        # for nothing yet, but the endpoint still returns the counts shape.
        response = post_json(staff_client, f"{STAFF_URL}{campaign.id}/dispatch-wave/", {})
        assert response.status_code == 200
        assert set(response.json()) == {"queued", "unreachable"}


class TestWebhookErrorBranches:
    @pytest.fixture
    def contacted_member(self, campaign):
        patient = make_patient(contact_number="9444444444")
        campaign.status = "running"
        campaign.save(update_fields=["status"])
        return CampaignMember.objects.create(
            campaign=campaign, patient=patient, state="contacted", outreach_reason="flu shot",
        )

    def test_explicit_intent_that_raises_is_400(self, client, contacted_member):
        # explicit snooze intent with no snooze_until -> handle_response_action
        # raises ValueError -> 400 (never reaches the AI classifier).
        response = post_json(client, WEBHOOK_URL, {
            "from": "9444444444", "text": "later", "intent": "snooze",
        })
        assert response.status_code == 400

    def test_no_sender_and_no_member_id_is_404(self, client, contacted_member):
        response = post_json(client, WEBHOOK_URL, {"text": "hello?"})
        assert response.status_code == 404
