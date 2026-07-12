from django.urls import path

from outreach.views import (
    CampaignCRUDAPIView,
    CampaignDetailAPIView,
    CampaignListCreateAPIView,
    CampaignMemberCRUDAPIView,
    CampaignMembersAPIView,
    CampaignStatsAPIView,
    DispatchWaveAPIView,
    InboundResponseCRUDAPIView,
    InboundWebhookAPIView,
    LaunchCampaignAPIView,
    OutboundMessageCRUDAPIView,
    PauseCampaignAPIView,
    PreviewCohortAPIView,
)

urlpatterns = [
    # inbound webhook (unauthenticated — provider replies land here)
    path("outreach/webhook/", InboundWebhookAPIView.as_view()),
    # staff campaign management
    path("staff/outreach/", CampaignListCreateAPIView.as_view()),
    path("staff/outreach/preview-cohort/", PreviewCohortAPIView.as_view()),
    path("staff/outreach/<int:campaign_id>/", CampaignDetailAPIView.as_view()),
    path("staff/outreach/<int:campaign_id>/launch/", LaunchCampaignAPIView.as_view()),
    path("staff/outreach/<int:campaign_id>/pause/", PauseCampaignAPIView.as_view()),
    path("staff/outreach/<int:campaign_id>/stats/", CampaignStatsAPIView.as_view()),
    path("staff/outreach/<int:campaign_id>/dispatch-wave/", DispatchWaveAPIView.as_view()),
    path("staff/outreach/<int:campaign_id>/members/", CampaignMembersAPIView.as_view()),
    # generic CRUD (dev/admin convenience)
    path("campaign", CampaignCRUDAPIView.as_view()),
    path("campaign/<int:id>", CampaignCRUDAPIView.as_view()),
    path("campaignmember", CampaignMemberCRUDAPIView.as_view()),
    path("campaignmember/<int:id>", CampaignMemberCRUDAPIView.as_view()),
    path("outboundmessage", OutboundMessageCRUDAPIView.as_view()),
    path("outboundmessage/<int:id>", OutboundMessageCRUDAPIView.as_view()),
    path("inboundresponse", InboundResponseCRUDAPIView.as_view()),
    path("inboundresponse/<int:id>", InboundResponseCRUDAPIView.as_view()),
]
