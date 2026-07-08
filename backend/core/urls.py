from django.urls import path

from core.views import (
    ConversationCRUDAPIView,
    DoctorCRUDAPIView,
    MessageCRUDAPIView,
    PatientCRUDAPIView,
)

urlpatterns = [
    path("patients", PatientCRUDAPIView.as_view()),
    path("patients/<int:id>", PatientCRUDAPIView.as_view()),
    path("doctors", DoctorCRUDAPIView.as_view()),
    path("doctors/<int:id>", DoctorCRUDAPIView.as_view()),
    path("conversations", ConversationCRUDAPIView.as_view()),
    path("conversations/<int:id>", ConversationCRUDAPIView.as_view()),
    path("messages", MessageCRUDAPIView.as_view()),
    path("messages/<int:id>", MessageCRUDAPIView.as_view()),
]
