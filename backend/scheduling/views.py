# from rest_framework.response import Response
from django.core.serializers.json import DjangoJSONEncoder
from django.http import StreamingHttpResponse
from rest_framework.views import APIView
import json
from scheduling.ai.handler import handle_patient_message
from core.base_crud_views import BaseCRUDAPIView
from core.events import emit
from scheduling.models import (
    Appointment,
    Waitlist,
)

from scheduling.serializers import (
    AppointmentSerializer,
    WaitlistSerializer,
)


class AppointmentCRUDAPIView(BaseCRUDAPIView):
    model = Appointment
    serializer_class = AppointmentSerializer

    def post(self, request, id=None):
        """Booking + the Agent 8 scheduling-surface hook (PRD secondary
        journey): every successful booking response carries the patient's
        open care gaps, so the calling flow can offer "you're also due
        for..." right in the conversation. A caregaps problem must never
        break booking, hence the broad guard."""
        response = super().post(request, id)
        if response.status_code == 201:
            try:
                from caregaps.services import open_gaps_for
                from core.models import Patient
                patient = Patient.objects.filter(id=response.data.get("patient")).first()
                if patient is not None:
                    response.data["care_gap_offers"] = open_gaps_for(patient)
            except Exception:
                pass
        return response

    def patch(self, request, id=None):
        """A PATCH that flips status to "completed" is how staff mark a
        visit done today, so it fires the same appointment.completed event
        as scheduling.services.complete_appointment — Agent 8's completion
        detection hangs off it (FR-G8)."""
        was_completed = bool(
            id and Appointment.objects.filter(id=id, status="completed").exists()
        )
        response = super().patch(request, id)
        if (response.status_code == 200 and not was_completed
                and response.data.get("status") == "completed"):
            appointment = Appointment.objects.get(id=id)
            emit(
                "appointment.completed",
                appointment_id=appointment.id,
                patient_id=appointment.patient_id,
                doctor_name=appointment.doctor.name,
                source=appointment.source,
            )
        return response


class WaitlistCRUDAPIView(BaseCRUDAPIView):
    model = Waitlist
    serializer_class = WaitlistSerializer


class ChatAPIView(APIView):

    def post(self, request):
        conversation = request.data.get("conversation", [])

        results = handle_patient_message(conversation)

        def event_stream():
            # One SSE event per entry — a slot search streams one "slots"
            # event per doctor, and the UI renders each as its own card.
            for result in results:
                yield f"data: {json.dumps(result, cls=DjangoJSONEncoder)}\n\n"

        return StreamingHttpResponse(
            event_stream(),
            content_type="text/event-stream",
        )
