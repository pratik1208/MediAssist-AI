from django.urls import path

from triage.views import (
    AssessmentDetailAPIView,
    ClinicalProtocolCRUDAPIView,
    EscalationAckAPIView,
    EscalationAlertCRUDAPIView,
    EscalationListAPIView,
    StartAssessmentAPIView,
    SubmitAnswerAPIView,
    TriageAnalyticsAPIView,
    TriageAssessmentCRUDAPIView,
)

urlpatterns = [
    path("triage/assessments/", StartAssessmentAPIView.as_view()),
    path("triage/assessments/<int:assessment_id>/", AssessmentDetailAPIView.as_view()),
    path("triage/assessments/<int:assessment_id>/answer/", SubmitAnswerAPIView.as_view()),
    path("staff/triage/analytics/", TriageAnalyticsAPIView.as_view()),
    path("staff/triage/escalations/", EscalationListAPIView.as_view()),
    path("staff/triage/escalations/<int:alert_id>/ack/", EscalationAckAPIView.as_view()),
    # generic CRUD (dev/admin convenience)
    path("clinicalprotocol", ClinicalProtocolCRUDAPIView.as_view()),
    path("clinicalprotocol/<int:id>", ClinicalProtocolCRUDAPIView.as_view()),
    path("triageassessment", TriageAssessmentCRUDAPIView.as_view()),
    path("triageassessment/<int:id>", TriageAssessmentCRUDAPIView.as_view()),
    path("escalationalert", EscalationAlertCRUDAPIView.as_view()),
    path("escalationalert/<int:id>", EscalationAlertCRUDAPIView.as_view()),
]
