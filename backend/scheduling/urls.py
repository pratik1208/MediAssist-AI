from django.urls import path
from scheduling.views import ChatAPIView

from scheduling.views import (
    AppointmentCRUDAPIView,
    ConversationCRUDAPIView,
    DoctorCRUDAPIView,
    MessageCRUDAPIView,
    PatientCRUDAPIView,
    WaitlistCRUDAPIView,
)

urlpatterns = [
    path("chat", ChatAPIView.as_view()),
    path("patients", PatientCRUDAPIView.as_view()),
    path("patients/<int:id>", PatientCRUDAPIView.as_view()),
    path("doctors", DoctorCRUDAPIView.as_view()),
    path("doctors/<int:id>", DoctorCRUDAPIView.as_view()),
    path("appointments", AppointmentCRUDAPIView.as_view()),
    path("appointments/<int:id>", AppointmentCRUDAPIView.as_view()),
    path("waitlists", WaitlistCRUDAPIView.as_view()),
    path("waitlists/<int:id>", WaitlistCRUDAPIView.as_view()),
    path("conversations", ConversationCRUDAPIView.as_view()),
    path("conversations/<int:id>", ConversationCRUDAPIView.as_view()),
    path("messages", MessageCRUDAPIView.as_view()),
    path("messages/<int:id>", MessageCRUDAPIView.as_view()),
]
