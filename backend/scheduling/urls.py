from django.urls import path

from scheduling.views import (
    AppointmentCRUDAPIView,
    ChatAPIView,
    WaitlistCRUDAPIView,
)

urlpatterns = [
    path("chat", ChatAPIView.as_view()),
    path("appointments", AppointmentCRUDAPIView.as_view()),
    path("appointments/<int:id>", AppointmentCRUDAPIView.as_view()),
    path("waitlists", WaitlistCRUDAPIView.as_view()),
    path("waitlists/<int:id>", WaitlistCRUDAPIView.as_view()),
]
