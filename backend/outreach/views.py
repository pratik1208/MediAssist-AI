"""Outreach campaign API (Agent 7, Phase 3).

Staff endpoints (IsAdminUser, same staff-account convention as the other
agents — no separate coordinator login exists): create campaign, preview a
cohort BEFORE launching, launch, pause, per-campaign funnel stats.

The inbound webhook is deliberately unauthenticated (AllowAny): a real
SMS/email provider posts replies with its own signature scheme, not a staff
session — in dev it's the "simple POST you curl manually" the build steps
ask for. It only ever records an InboundResponse (and, until Phase 4's AI
classifier lands, applies an explicitly-supplied intent); it can't read
anything back out.
"""

import datetime

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from core.base_crud_views import BaseCRUDAPIView
from outreach import services
from outreach.models import Campaign, CampaignMember, InboundResponse, OutboundMessage
from outreach.serializers import (
    CampaignMemberSerializer,
    CampaignSerializer,
    InboundResponseSerializer,
    OutboundMessageSerializer,
)

_VALID_CHANNELS = {"sms", "email", "voice", "whatsapp"}


# Generic CRUD (dev/admin convenience), same pattern as the other agents.
class CampaignCRUDAPIView(BaseCRUDAPIView):
    model = Campaign
    serializer_class = CampaignSerializer


class CampaignMemberCRUDAPIView(BaseCRUDAPIView):
    model = CampaignMember
    serializer_class = CampaignMemberSerializer


class OutboundMessageCRUDAPIView(BaseCRUDAPIView):
    model = OutboundMessage
    serializer_class = OutboundMessageSerializer


class InboundResponseCRUDAPIView(BaseCRUDAPIView):
    model = InboundResponse
    serializer_class = InboundResponseSerializer

# validates the outreach campaign's communication plan and returns an error message if the structure, channels, or wait times are invalid; otherwise it returns None
def _validate_channel_plan(plan) -> str | None:
    """Return an error string, or None if the plan is valid."""
    if not isinstance(plan, list) or not plan:
        return "channel_plan must be a non-empty list"
    for step in plan:
        if not isinstance(step, dict) or "channel" not in step:
            return 'each channel_plan step must be an object like {"channel": "sms", "wait_days": 3}'
        if step["channel"] not in _VALID_CHANNELS:
            return f"channel must be one of {sorted(_VALID_CHANNELS)}"
        if not isinstance(step.get("wait_days", 0), int) or step.get("wait_days", 0) < 0:
            return "wait_days must be a non-negative integer"
    return None

# Campaign: An outreach program that contacts a group of patients for a specific healthcare goal.
def _campaign_summary(campaign: Campaign) -> dict:
    """In your Outreach Agent, a Campaign is an outreach program created by the clinic to contact a group of patients for a specific clinical goal."""

    return {
        "id": campaign.id,
        "name": campaign.name,
        "clinical_goal": campaign.clinical_goal,
        "cohort_criteria": campaign.cohort_criteria,
        "channel_plan": campaign.channel_plan,
        "status": campaign.status,
        "launched_at": campaign.launched_at,
        "created_at": campaign.created_at,
        "member_count": campaign.members.count(),
    }


# -- staff: create + list campaigns -------------------------------------------

class CampaignListCreateAPIView(APIView):
    """GET /api/staff/outreach/ — all campaigns (optionally ?status=).
    POST — create a draft campaign: {name, clinical_goal, cohort_criteria,
    channel_plan}. Criteria are validated up front (an unsupported key is a
    400 here, not a surprise at launch time)."""

    permission_classes = [IsAdminUser]
    REQUIRED = ("name", "clinical_goal", "cohort_criteria", "channel_plan")

    def get(self, request):
        campaigns = Campaign.objects.order_by("-created_at")
        status_filter = request.query_params.get("status")
        if status_filter:
            campaigns = campaigns.filter(status=status_filter)
        return Response([_campaign_summary(c) for c in campaigns])

    def post(self, request):
        missing = sorted(f for f in self.REQUIRED if not request.data.get(f))
        if missing:
            return Response({"error": f"missing required fields: {missing}"},
                            status=status.HTTP_400_BAD_REQUEST)

        criteria = request.data["cohort_criteria"]
        if not isinstance(criteria, dict):
            return Response({"error": "cohort_criteria must be an object"},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            services.build_cohort(criteria)
        except services.UnsupportedCriteriaError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        plan_error = _validate_channel_plan(request.data["channel_plan"])
        if plan_error:
            return Response({"error": plan_error}, status=status.HTTP_400_BAD_REQUEST)

        campaign = Campaign.objects.create(
            name=request.data["name"],
            clinical_goal=request.data["clinical_goal"],
            cohort_criteria=criteria,
            channel_plan=request.data["channel_plan"],
            schedule=request.data.get("schedule") or {},
        )
        return Response(_campaign_summary(campaign), status=status.HTTP_201_CREATED)


# -- staff: preview a cohort before launching (FR-O1/O2) ----------------------

class PreviewCohortAPIView(APIView):
    """POST /api/staff/outreach/preview-cohort/ — {cohort_criteria} ->
    {count, sample}. Stateless on purpose: the criteria-builder UI can
    preview while composing, before any campaign row exists."""

    permission_classes = [IsAdminUser]
    SAMPLE_SIZE = 10

    def post(self, request):
        criteria = request.data.get("cohort_criteria")
        if not isinstance(criteria, dict):
            return Response({"error": "cohort_criteria must be an object"},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            cohort = services.build_cohort(criteria)
        except services.UnsupportedCriteriaError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            "count": cohort.count(),
            "sample": [{
                "id": p.id,
                "name": f"{p.first_name} {p.last_name}".strip(),
                "dob": p.dob,
                "contact_number": p.contact_number,
                "preferred_language": p.preferred_language,
            } for p in cohort.order_by("id")[:self.SAMPLE_SIZE]],
        })


# -- staff: campaign detail / launch / pause / stats / members -----------------

class CampaignDetailAPIView(APIView):
    """GET /api/staff/outreach/{id}/ — summary + live funnel stats."""

    permission_classes = [IsAdminUser]

    def get(self, request, campaign_id):
        try:
            campaign = Campaign.objects.get(id=campaign_id)
        except Campaign.DoesNotExist:
            return Response({"error": "campaign not found"}, status=status.HTTP_404_NOT_FOUND)
        body = _campaign_summary(campaign)
        body["stats"] = services.campaign_stats(campaign)
        return Response(body)


class LaunchCampaignAPIView(APIView):
    """POST /api/staff/outreach/{id}/launch/ — draft -> running: enroll the
    cohort and dispatch the first wave immediately (wave 0 is normally
    wait_days=0). Also resumes a paused campaign (paused -> running) without
    re-enrolling — a resume shouldn't quietly pull in patients who newly
    match the criteria."""

    permission_classes = [IsAdminUser]

    def post(self, request, campaign_id):
        try:
            campaign = Campaign.objects.get(id=campaign_id)
        except Campaign.DoesNotExist:
            return Response({"error": "campaign not found"}, status=status.HTTP_404_NOT_FOUND)

        if campaign.status == "paused":
            campaign.status = "running"
            campaign.save(update_fields=["status"])
            return Response({"status": "running", "resumed": True})

        if campaign.status != "draft":
            return Response({"error": f"cannot launch a campaign in status {campaign.status!r}"},
                            status=status.HTTP_400_BAD_REQUEST)

        campaign.status = "running"
        campaign.launched_at = timezone.now()
        campaign.save(update_fields=["status", "launched_at"])
        enrollment = services.enroll_cohort(campaign)
        wave = services.dispatch_wave(campaign)
        return Response({"status": "running", "enrolled": enrollment["enrolled"],
                         "first_wave": wave})


class PauseCampaignAPIView(APIView):
    """POST /api/staff/outreach/{id}/pause/ — running -> paused. A paused
    campaign is skipped by wave dispatch (and by the Phase 6 scheduled job);
    relaunch to resume."""

    permission_classes = [IsAdminUser]

    def post(self, request, campaign_id):
        try:
            campaign = Campaign.objects.get(id=campaign_id)
        except Campaign.DoesNotExist:
            return Response({"error": "campaign not found"}, status=status.HTTP_404_NOT_FOUND)
        if campaign.status != "running":
            return Response({"error": f"cannot pause a campaign in status {campaign.status!r}"},
                            status=status.HTTP_400_BAD_REQUEST)
        campaign.status = "paused"
        campaign.save(update_fields=["status"])
        return Response({"status": "paused"})


class CampaignStatsAPIView(APIView):
    """GET /api/staff/outreach/{id}/stats/ — the FR-O7 funnel by itself
    (the analytics dashboard polls this without re-fetching the campaign)."""

    permission_classes = [IsAdminUser]

    def get(self, request, campaign_id):
        try:
            campaign = Campaign.objects.get(id=campaign_id)
        except Campaign.DoesNotExist:
            return Response({"error": "campaign not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(services.campaign_stats(campaign))


class DispatchWaveAPIView(APIView):
    """POST /api/staff/outreach/{id}/dispatch-wave/ — manually run the
    escalation pass for one campaign. Connective tissue: Phase 6 turns wave
    dispatch into a daily scheduled job, but until then (and for the Phase 5
    manual E2E) staff need a button that moves non-responders to their next
    channel."""

    permission_classes = [IsAdminUser]

    def post(self, request, campaign_id):
        try:
            campaign = Campaign.objects.get(id=campaign_id)
        except Campaign.DoesNotExist:
            return Response({"error": "campaign not found"}, status=status.HTTP_404_NOT_FOUND)
        if campaign.status != "running":
            return Response({"error": f"cannot dispatch waves for a campaign in status {campaign.status!r}"},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response(services.dispatch_wave(campaign))


class CampaignMembersAPIView(APIView):
    """GET /api/staff/outreach/{id}/members/ — the outreach list (FR-O3):
    name, contact, reason, language, channel attempts, assigned physician.
    Optionally ?state= for funnel drill-down."""

    permission_classes = [IsAdminUser]

    def get(self, request, campaign_id):
        try:
            campaign = Campaign.objects.get(id=campaign_id)
        except Campaign.DoesNotExist:
            return Response({"error": "campaign not found"}, status=status.HTTP_404_NOT_FOUND)
        members = campaign.members.select_related("patient", "assigned_physician").order_by("id")
        state_filter = request.query_params.get("state")
        if state_filter:
            members = members.filter(state=state_filter)
        return Response([{
            "id": m.id,
            "patient_id": m.patient_id,
            "patient_name": f"{m.patient.first_name} {m.patient.last_name}".strip(),
            "contact_number": m.patient.contact_number,
            "email": m.patient.email,
            "preferred_language": m.patient.preferred_language,
            "state": m.state,
            "snooze_until": m.snooze_until,
            "channel_attempts": m.channel_attempts,
            "outreach_reason": m.outreach_reason,
            "assigned_physician": m.assigned_physician.name if m.assigned_physician else None,
        } for m in members])


# -- inbound webhook (FR-O5 replies land here) ---------------------------------

class InboundWebhookAPIView(APIView):
    """POST /api/outreach/webhook/ — where SMS/email replies land.

    Body: {"from": "<phone number>", "text": "..."} the way a provider
    would post it, or {"member_id": N, "text": "..."} for precise dev
    testing. A phone number resolves to that patient's most recently
    contacted active membership.

    Always records an InboundResponse. By default the text is run through
    the Phase 4 AI classifier (services.classify_and_handle_response) --
    an explicit "intent" (+ optional "snooze_until") in the body bypasses
    the classifier entirely, which dev/testing use for deterministic
    control over exactly which branch runs.
    """

    permission_classes = [AllowAny]
    authentication_classes = []  # provider posts carry no session/JWT
    ACTIVE_STATES = ("identified", "contacted", "responded", "snoozed")

    def post(self, request):
        text = (request.data.get("text") or "").strip()
        if not text:
            return Response({"error": "text is required"}, status=status.HTTP_400_BAD_REQUEST)

        member = self._resolve_member(request.data)
        if member is None:
            return Response({"error": "no active campaign membership found for this sender"},
                            status=status.HTTP_404_NOT_FOUND)

        response = InboundResponse.objects.create(member=member, raw_text=text)

        intent = request.data.get("intent")
        if intent:
            snooze_until = None
            if request.data.get("snooze_until"):
                try:
                    snooze_until = datetime.date.fromisoformat(request.data["snooze_until"])
                except ValueError:
                    return Response({"error": "snooze_until must be YYYY-MM-DD"},
                                    status=status.HTTP_400_BAD_REQUEST)
            try:
                services.handle_response_action(member, intent, snooze_until=snooze_until,
                                                response=response)
            except ValueError as exc:
                return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        else:
            services.classify_and_handle_response(member, text, response=response)

        member.refresh_from_db()
        return Response({
            "response_id": response.id,
            "member_id": member.id,
            "campaign_id": member.campaign_id,
            "handled": response.handled,
            "member_state": member.state,
        }, status=status.HTTP_201_CREATED)

    def _resolve_member(self, data) -> CampaignMember | None:
        if data.get("member_id"):
            return CampaignMember.objects.filter(id=data["member_id"]).first()
        sender = (data.get("from") or "").strip()
        if not sender:
            return None
        return (
            CampaignMember.objects
            .filter(patient__contact_number=sender, state__in=self.ACTIVE_STATES,
                    campaign__status="running")
            .order_by("-id")
            .first()
        )
