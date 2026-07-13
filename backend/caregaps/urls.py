from django.urls import path

from caregaps.views import (
    BundleCarePlanAPIView,
    CareGapCRUDAPIView,
    CarePlanCRUDAPIView,
    CarePlanDetailAPIView,
    ClinicalEventCRUDAPIView,
    ClinicalGuidelineCRUDAPIView,
    GapWorklistAPIView,
    PatientGapsAPIView,
    PushOutreachAPIView,
    QualityMetricsAPIView,
    TriggerScanAPIView,
)

urlpatterns = [
    # staff care-gap surfaces
    path("staff/caregaps/", GapWorklistAPIView.as_view()),
    path("staff/caregaps/scan/", TriggerScanAPIView.as_view()),
    path("staff/caregaps/push-outreach/", PushOutreachAPIView.as_view()),
    path("staff/caregaps/metrics/", QualityMetricsAPIView.as_view()),
    path("staff/caregaps/patients/<int:patient_id>/", PatientGapsAPIView.as_view()),
    path("staff/caregaps/patients/<int:patient_id>/bundle/", BundleCarePlanAPIView.as_view()),
    path("staff/caregaps/plans/<int:plan_id>/", CarePlanDetailAPIView.as_view()),
    # generic CRUD (dev/admin convenience)
    path("clinicalguideline", ClinicalGuidelineCRUDAPIView.as_view()),
    path("clinicalguideline/<int:id>", ClinicalGuidelineCRUDAPIView.as_view()),
    path("clinicalevent", ClinicalEventCRUDAPIView.as_view()),
    path("clinicalevent/<int:id>", ClinicalEventCRUDAPIView.as_view()),
    path("caregap", CareGapCRUDAPIView.as_view()),
    path("caregap/<int:id>", CareGapCRUDAPIView.as_view()),
    path("careplan", CarePlanCRUDAPIView.as_view()),
    path("careplan/<int:id>", CarePlanCRUDAPIView.as_view()),
]
