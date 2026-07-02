from scheduling.base_crud_views import BaseCRUDAPIView
from scheduling.models import (
    Appointment,
    Conversation,
    Doctor,
    Message,
    Patient,
    Waitlist,
)
from scheduling.serializers import (
    AppointmentSerializer,
    ConversationSerializer,
    DoctorSerializer,
    MessageSerializer,
    PatientSerializer,
    WaitlistSerializer,
)


class PatientCRUDAPIView(BaseCRUDAPIView):
    model = Patient
    serializer_class = PatientSerializer


class DoctorCRUDAPIView(BaseCRUDAPIView):
    model = Doctor
    serializer_class = DoctorSerializer


class AppointmentCRUDAPIView(BaseCRUDAPIView):
    model = Appointment
    serializer_class = AppointmentSerializer


class WaitlistCRUDAPIView(BaseCRUDAPIView):
    model = Waitlist
    serializer_class = WaitlistSerializer


class ConversationCRUDAPIView(BaseCRUDAPIView):
    model = Conversation
    serializer_class = ConversationSerializer


class MessageCRUDAPIView(BaseCRUDAPIView):
    model = Message
    serializer_class = MessageSerializer
