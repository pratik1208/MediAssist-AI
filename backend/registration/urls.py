from django.urls import path

from registration.views import (
    CompleteRegistrationAPIView,
    InsurancePolicyCRUDAPIView,
    IntakeSummaryCRUDAPIView,
    RegistrationAnalyticsAPIView,
    RegistrationChatAPIView,
    RegistrationStatusAPIView,
    RequestOtpAPIView,
    StartRegistrationAPIView,
    SubmitDemographicsAPIView,
    SubmitInsuranceAPIView,
    UploadDocumentAPIView,
    UploadedDocumentCRUDAPIView,
    VerifyOtpAPIView,
)

urlpatterns = [
    path("registration/start", StartRegistrationAPIView.as_view()),
    path("registration/chat", RegistrationChatAPIView.as_view()),
    path("staff/registration/analytics", RegistrationAnalyticsAPIView.as_view()),
    path("registration/demographics", SubmitDemographicsAPIView.as_view()),
    path("registration/otp/request", RequestOtpAPIView.as_view()),
    path("registration/otp/verify", VerifyOtpAPIView.as_view()),
    path("registration/documents", UploadDocumentAPIView.as_view()),
    path("registration/insurance", SubmitInsuranceAPIView.as_view()),
    path("registration/status", RegistrationStatusAPIView.as_view()),
    path("registration/complete", CompleteRegistrationAPIView.as_view()),
    path("insurancepolicy", InsurancePolicyCRUDAPIView.as_view()),
    path("insurancepolicy/<int:id>", InsurancePolicyCRUDAPIView.as_view()),
    path("intakesummary", IntakeSummaryCRUDAPIView.as_view()),
    path("intakesummary/<int:id>", IntakeSummaryCRUDAPIView.as_view()),
    path("uploadeddocument", UploadedDocumentCRUDAPIView.as_view()),
    path("uploadeddocument/<int:id>", UploadedDocumentCRUDAPIView.as_view()),
]
