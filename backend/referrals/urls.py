from django.urls import path

from referrals.views import (
    AcceptReferralAPIView,
    BookReferralVisitAPIView,
    ConfirmReferralAPIView,
    ConsultationReportCRUDAPIView,
    CreateReferralAPIView,
    MarkVisitCompletedAPIView,
    PatientReferralsAPIView,
    ReferralCRUDAPIView,
    ReferralPackageCRUDAPIView,
    ReferralQueueAPIView,
    ReferralTimelineAPIView,
    ResumeReferralAPIView,
    SpecialistCandidatesAPIView,
    SpecialistCRUDAPIView,
    UploadConsultationReportAPIView,
)

urlpatterns = [
    # physician (staff, one-click create)
    path("referrals/", CreateReferralAPIView.as_view()),
    # patient (session token)
    path("referrals/status/", PatientReferralsAPIView.as_view()),
    path("referrals/<int:referral_id>/confirm/", ConfirmReferralAPIView.as_view()),
    # care coordinator + specialist-side (simulated) (staff)
    path("staff/referrals/", ReferralQueueAPIView.as_view()),
    path("staff/referrals/<int:referral_id>/", ReferralTimelineAPIView.as_view()),
    path("staff/referrals/<int:referral_id>/candidates/", SpecialistCandidatesAPIView.as_view()),
    path("staff/referrals/<int:referral_id>/accept/", AcceptReferralAPIView.as_view()),
    path("staff/referrals/<int:referral_id>/resume/", ResumeReferralAPIView.as_view()),
    path("staff/referrals/<int:referral_id>/book/", BookReferralVisitAPIView.as_view()),
    path("staff/referrals/<int:referral_id>/visit-completed/", MarkVisitCompletedAPIView.as_view()),
    path("staff/referrals/<int:referral_id>/report/", UploadConsultationReportAPIView.as_view()),
    # generic CRUD (dev/admin convenience)
    path("specialist", SpecialistCRUDAPIView.as_view()),
    path("specialist/<int:id>", SpecialistCRUDAPIView.as_view()),
    path("referral", ReferralCRUDAPIView.as_view()),
    path("referral/<int:id>", ReferralCRUDAPIView.as_view()),
    path("referralpackage", ReferralPackageCRUDAPIView.as_view()),
    path("referralpackage/<int:id>", ReferralPackageCRUDAPIView.as_view()),
    path("consultationreport", ConsultationReportCRUDAPIView.as_view()),
    path("consultationreport/<int:id>", ConsultationReportCRUDAPIView.as_view()),
]
