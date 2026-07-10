"""Triage API (Agent 3, Phase 3) — no AI yet.

The interview is driven by the protocol's question_flow in order; Phase 4
replaces that with adaptive AI questioning behind the same endpoints. The
safety order is already final: red_flag_check runs on every raw patient
input BEFORE anything else, and a hit short-circuits to the emergency
script + escalate() — no more questions, ever (spec emergency shape).
"""

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from core.base_crud_views import BaseCRUDAPIView
from core.sessions import SessionTokenAPIView
from triage import services
from triage.models import ClinicalProtocol, EscalationAlert, TriageAssessment
from triage.serializers import (
    ClinicalProtocolSerializer,
    EscalationAlertSerializer,
    TriageAssessmentSerializer,
)


# Generic CRUD (dev/admin convenience), same pattern as the other agents.
class ClinicalProtocolCRUDAPIView(BaseCRUDAPIView):
    model = ClinicalProtocol
    serializer_class = ClinicalProtocolSerializer


class TriageAssessmentCRUDAPIView(BaseCRUDAPIView):
    model = TriageAssessment
    serializer_class = TriageAssessmentSerializer


class EscalationAlertCRUDAPIView(BaseCRUDAPIView):
    model = EscalationAlert
    serializer_class = EscalationAlertSerializer

# Spec: the emergency response never asks follow-ups.
EMERGENCY_MESSAGE = (
    "Based on what you've described, please call 911 or go to the nearest "
    "emergency department now. Our on-call clinician has been alerted."
)

EXPLANATION_FOR = {
    "ed_now": EMERGENCY_MESSAGE,
    "same_day": "Please book an appointment for today — your symptoms should "
                "be seen by a clinician within the day.",
    "24_48h": "You should be seen within the next 24–48 hours. Please book "
              "an appointment.",
    "routine": "A routine appointment is appropriate. Book at a time that "
               "suits you.",
    "self_care": "Your symptoms can likely be managed at home for now. If "
                 "they worsen or don't improve, start a new assessment or "
                 "contact the clinic.",
}


def _coerce(answer: str):
    """Scripted answers arrive as text; rules need numbers and booleans."""
    text = str(answer).strip()
    lowered = text.lower()
    if lowered in ("yes", "true", "y"):
        return True
    if lowered in ("no", "false", "n"):
        return False
    try:
        return int(text)
    except ValueError:
        try:
            return float(text)
        except ValueError:
            return text


def _emergency_payload():
    return {
        "complete": True,
        "acuity": "emergency",
        "message": EMERGENCY_MESSAGE,
        "ui_hints": {"emergency": True},
    }


def _completion_payload(assessment):
    return {
        "complete": True,
        "acuity": assessment.acuity,
        "disposition": assessment.disposition,
        "explanation": EXPLANATION_FOR[assessment.disposition],
        "ui_hints": {
            "emergency": assessment.acuity == "emergency",
            "offer_booking": assessment.disposition in ("same_day", "24_48h", "routine"),
        },
    }


class StartAssessmentAPIView(SessionTokenAPIView):
    """POST /api/triage/assessments/ — {symptoms_text} -> {id, first_question}
    or the emergency payload. Requires a verified patient (spec auth column)."""

    def post(self, request):
        patient, error = self.verified_patient_or_error()
        if error:
            return error
        symptoms_text = (request.data.get("symptoms_text") or "").strip()
        if not symptoms_text:
            return Response({"error": "symptoms_text is required"},
                            status=status.HTTP_400_BAD_REQUEST)

        protocol = services.select_protocol(symptoms_text)

        # Layer 1 gate: the deterministic screen runs before anything else.
        if services.red_flag_check(symptoms_text):
            assessment = TriageAssessment.objects.create(
                patient=patient, conversation=self.conversation,
                clinical_protocol=protocol,  # may be None — escalate anyway
                reported_symptoms={"text": symptoms_text, "answers": []},
                acuity="emergency", disposition="ed_now", summary_text="",
            )
            services.escalate(assessment)
            return Response({"id": assessment.id, **_emergency_payload()},
                            status=status.HTTP_201_CREATED)

        if protocol is None:
            return Response(
                {"error": "could not match your symptoms to an assessment "
                          "protocol; please describe them differently or "
                          "contact the clinic"},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        assessment = TriageAssessment.objects.create(
            patient=patient, conversation=self.conversation,
            clinical_protocol=protocol,
            reported_symptoms={"text": symptoms_text, "answers": []},
            acuity="minimal", disposition="self_care", summary_text="",
        )
        return Response(
            {"id": assessment.id, "protocol": protocol.name,
             "first_question": protocol.question_flow[0]["ask"]},
            status=status.HTTP_201_CREATED,
        )


class TriageAssessmentAPIView(SessionTokenAPIView):
    """Base with a lookup scoped to the session's own conversation."""

    def assessment_or_error(self, assessment_id):
        try:
            assessment = TriageAssessment.objects.get(
                id=assessment_id, conversation=self.conversation
            )
        except TriageAssessment.DoesNotExist:
            return None, Response({"error": "assessment not found"},
                                  status=status.HTTP_404_NOT_FOUND)
        return assessment, None


class SubmitAnswerAPIView(TriageAssessmentAPIView):
    """POST /api/triage/assessments/{id}/answer/ — {answer} ->
    {next_question} | completion payload | emergency payload."""

    def post(self, request, assessment_id):
        assessment, error = self.assessment_or_error(assessment_id)
        if error:
            return error
        if assessment.status != "pending":
            return Response({"error": "assessment is no longer accepting answers"},
                            status=status.HTTP_400_BAD_REQUEST)
        answer = (str(request.data.get("answer") or "")).strip()
        if not answer:
            return Response({"error": "answer is required"},
                            status=status.HTTP_400_BAD_REQUEST)

        # Layer 1 gate on every answer: emergencies surface mid-interview too.
        if services.red_flag_check(answer):
            services.escalate(assessment)
            return Response(_emergency_payload())

        flow = assessment.clinical_protocol.question_flow
        answers = assessment.reported_symptoms.get("answers", [])
        question = flow[len(answers)]

        assessment.findings[question["capture"]] = _coerce(answer)
        answers.append(answer)
        assessment.reported_symptoms["answers"] = answers

        if len(answers) < len(flow):
            assessment.save(update_fields=["findings", "reported_symptoms"])
            return Response({"next_question": flow[len(answers)]["ask"]})

        # Interview finished: rules decide, then route downstream.
        assessment.status = "completed"
        assessment.finished_at = timezone.now()
        assessment.save(update_fields=["findings", "reported_symptoms", "status",
                                       "finished_at"])
        services.assign_acuity(assessment)
        if assessment.acuity == "emergency":
            services.escalate(assessment)
            return Response(_emergency_payload())
        services.route_disposition(assessment)
        return Response(_completion_payload(assessment))


class AssessmentDetailAPIView(TriageAssessmentAPIView):
    """GET /api/triage/assessments/{id}/ — current assessment state."""

    def get(self, request, assessment_id):
        assessment, error = self.assessment_or_error(assessment_id)
        if error:
            return error
        answered = len(assessment.reported_symptoms.get("answers", []))
        total = len(assessment.clinical_protocol.question_flow) if assessment.clinical_protocol else 0
        finished = assessment.status in ("completed", "escalated")
        return Response({
            "id": assessment.id,
            "status": assessment.status,
            "protocol": assessment.clinical_protocol.name if assessment.clinical_protocol else None,
            "questions_answered": answered,
            "questions_total": total,
            "findings": assessment.findings,
            "acuity": assessment.acuity if finished else None,
            "disposition": assessment.disposition if finished else None,
        })


class EscalationListAPIView(APIView):
    """GET /api/staff/triage/escalations/?status=open — alerts for staff."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        alerts = EscalationAlert.objects.select_related("patient").order_by("-id")
        status_filter = request.query_params.get("status")
        if status_filter:
            alerts = alerts.filter(status=status_filter)
        return Response([{
            "id": a.id,
            "patient_id": a.patient_id,
            "patient_name": f"{a.patient.first_name} {a.patient.last_name}",
            "assessment_id": a.assessment_id,
            "category": a.category,
            "priority": a.priority,
            "summary": a.summary,
            "status": a.status,
            "acknowledged_at": a.acknowledged_at,
        } for a in alerts])


class TriageAnalyticsAPIView(APIView):
    """GET /api/staff/triage/analytics/ — FR-T10 aggregates (staff only)."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        from django.db.models import Avg, Count, F

        assessments = TriageAssessment.objects.all()
        total = assessments.count()
        finished = assessments.exclude(finished_at=None)

        acuity_distribution = {
            row["acuity"]: row["n"]
            for row in assessments.exclude(status="pending")
                                  .values("acuity").annotate(n=Count("id"))
        }
        escalated = assessments.filter(status="escalated").count()
        avg_time = finished.exclude(created_at=None).aggregate(
            avg=Avg(F("finished_at") - F("created_at")))["avg"]

        # Same-day conversion: patients told to be seen today who then got
        # an appointment booked (proxy until appointments link to triage).
        from scheduling.models import Appointment
        same_day = assessments.filter(disposition="same_day",
                                      status__in=("completed", "escalated"))
        same_day_patients = set(same_day.values_list("patient_id", flat=True))
        converted = (Appointment.objects
                     .filter(patient_id__in=same_day_patients)
                     .exclude(status="cancelled")
                     .values_list("patient_id", flat=True).distinct().count()
                     if same_day_patients else 0)

        def rate(part, whole):
            return round(part / whole, 3) if whole else None

        return Response({
            "assessments": {"total": total,
                            "completed": assessments.filter(status="completed").count(),
                            "pending": assessments.filter(status="pending").count()},
            "acuity_distribution": acuity_distribution,
            "escalations": {"total": escalated,
                            "rate": rate(escalated, total)},
            "avg_triage_seconds": round(avg_time.total_seconds(), 1) if avg_time else None,
            "same_day": {"dispositions": same_day.count(),
                         "converted_to_booking": converted,
                         "conversion_rate": rate(converted, len(same_day_patients))},
        })


class EscalationAckAPIView(APIView):
    """POST /api/staff/triage/escalations/{id}/ack/ -> {status: acknowledged}."""

    permission_classes = [IsAdminUser]

    def post(self, request, alert_id):
        try:
            alert = EscalationAlert.objects.get(id=alert_id)
        except EscalationAlert.DoesNotExist:
            return Response({"error": "alert not found"},
                            status=status.HTTP_404_NOT_FOUND)
        if alert.status == "open":
            alert.status = "acknowledged"
            alert.acknowledged_at = timezone.now()
            alert.save(update_fields=["status", "acknowledged_at"])
        return Response({"status": alert.status})
