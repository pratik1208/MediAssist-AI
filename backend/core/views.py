from core.base_crud_views import BaseCRUDAPIView
from core.models import Message, Patient, Doctor, Conversation
from core.serializers import (
    ConversationSerializer,
    DoctorSerializer,
    MessageSerializer,
    PatientSerializer,
)


class PatientCRUDAPIView(BaseCRUDAPIView):
    model = Patient
    serializer_class = PatientSerializer


class DoctorCRUDAPIView(BaseCRUDAPIView):
    model = Doctor
    serializer_class = DoctorSerializer


class ConversationCRUDAPIView(BaseCRUDAPIView):
    model = Conversation
    serializer_class = ConversationSerializer


class MessageCRUDAPIView(BaseCRUDAPIView):
    model = Message
    serializer_class = MessageSerializer
