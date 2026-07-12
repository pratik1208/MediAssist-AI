from django.urls import path

from priorauth.views import (
    AuthorizationDetailAPIView,
    AuthorizationPackageCRUDAPIView,
    AuthorizationQueueAPIView,
    AuthorizationRequestCRUDAPIView,
    CreateTreatmentOrderAPIView,
    PatientAuthorizationsAPIView,
    PayerMessageCRUDAPIView,
    PayerRuleCRUDAPIView,
    PollAuthorizationStatusAPIView,
    PriorAuthAnalyticsAPIView,
    ReferralAuthorizationsAPIView,
    SimulatorControlAPIView,
    StagedTasksAPIView,
    SubmitAuthorizationAPIView,
    SuggestAppealAPIView,
    TreatmentOrderCRUDAPIView,
)

urlpatterns = [
    # physician (staff, auto-triggers detection)
    path("priorauth/orders/", CreateTreatmentOrderAPIView.as_view()),
    # patient (session token)
    path("priorauth/status/", PatientAuthorizationsAPIView.as_view()),
    # cross-agent (staff): PA status for a given referral's linked orders
    path("priorauth/for-referral/<int:referral_id>/", ReferralAuthorizationsAPIView.as_view()),
    # staff / provider view + simulator control (staff)
    path("staff/priorauth/", AuthorizationQueueAPIView.as_view()),
    path("staff/priorauth/tasks/", StagedTasksAPIView.as_view()),
    path("staff/priorauth/analytics/", PriorAuthAnalyticsAPIView.as_view()),
    path("staff/priorauth/<int:request_id>/", AuthorizationDetailAPIView.as_view()),
    path("staff/priorauth/<int:request_id>/submit/", SubmitAuthorizationAPIView.as_view()),
    path("staff/priorauth/<int:request_id>/poll/", PollAuthorizationStatusAPIView.as_view()),
    path("staff/priorauth/<int:request_id>/simulate/", SimulatorControlAPIView.as_view()),
    path("staff/priorauth/<int:request_id>/suggest-appeal/", SuggestAppealAPIView.as_view()),
    # generic CRUD (dev/admin convenience)
    path("payerrule", PayerRuleCRUDAPIView.as_view()),
    path("payerrule/<int:id>", PayerRuleCRUDAPIView.as_view()),
    path("treatmentorder", TreatmentOrderCRUDAPIView.as_view()),
    path("treatmentorder/<int:id>", TreatmentOrderCRUDAPIView.as_view()),
    path("authorizationrequest", AuthorizationRequestCRUDAPIView.as_view()),
    path("authorizationrequest/<int:id>", AuthorizationRequestCRUDAPIView.as_view()),
    path("authorizationpackage", AuthorizationPackageCRUDAPIView.as_view()),
    path("authorizationpackage/<int:id>", AuthorizationPackageCRUDAPIView.as_view()),
    path("payermessage", PayerMessageCRUDAPIView.as_view()),
    path("payermessage/<int:id>", PayerMessageCRUDAPIView.as_view()),
]
