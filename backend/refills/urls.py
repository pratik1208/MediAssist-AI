from django.urls import path

from refills.views import (
    ApproveRefillAPIView,
    CreateRefillRequestAPIView,
    PatientPrescriptionsAPIView,
    PharmacyCRUDAPIView,
    PrescriptionCRUDAPIView,
    RefillQueueAPIView,
    RefillRequestCRUDAPIView,
    RefillRequestStatusAPIView,
    RejectRefillAPIView,
    RequestVisitAPIView,
)

urlpatterns = [
    # patient (session token)
    path("refills/prescriptions/", PatientPrescriptionsAPIView.as_view()),
    path("refills/requests/", CreateRefillRequestAPIView.as_view()),
    path("refills/requests/<int:request_id>/", RefillRequestStatusAPIView.as_view()),
    # physician (staff)
    path("staff/refills/queue/", RefillQueueAPIView.as_view()),
    path("staff/refills/<int:request_id>/approve/", ApproveRefillAPIView.as_view()),
    path("staff/refills/<int:request_id>/reject/", RejectRefillAPIView.as_view()),
    path("staff/refills/<int:request_id>/request-visit/", RequestVisitAPIView.as_view()),
    # generic CRUD (dev/admin convenience)
    path("pharmacy", PharmacyCRUDAPIView.as_view()),
    path("pharmacy/<int:id>", PharmacyCRUDAPIView.as_view()),
    path("prescription", PrescriptionCRUDAPIView.as_view()),
    path("prescription/<int:id>", PrescriptionCRUDAPIView.as_view()),
    path("refillrequest", RefillRequestCRUDAPIView.as_view()),
    path("refillrequest/<int:id>", RefillRequestCRUDAPIView.as_view()),
]
