# from rest_framework.response import Response
from django.core.serializers.json import DjangoJSONEncoder
from django.http import StreamingHttpResponse
from rest_framework.views import APIView
import json
from scheduling.ai.handler import handle_patient_message
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


class ChatAPIView(APIView):

    def post(self, request):
        conversation = request.data.get("conversation", [])

        result = handle_patient_message(conversation)

        def event_stream():
            yield f"data: {json.dumps(result, cls=DjangoJSONEncoder)}\n\n"

        return StreamingHttpResponse(
            event_stream(),
            content_type="text/event-stream",
        )
