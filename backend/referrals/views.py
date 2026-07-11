"""Referral API (Agent 5, Phases 3 + 4).

Physician/care-coordinator/specialist-office endpoints are staff-only
(IsAdminUser) — there's no separate doctor-user or specialist-user login in
this codebase yet, so "physician creates a referral" / "specialist accepts"
are staff actions performed on their behalf (same simulated-staff pattern
refills and triage already use for their physician endpoints). Patient
endpoints ride the shared session token (core.sessions) and require a
verified identity, like triage and refills.
"""

from datetime import datetime

from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from core.base_crud_views import BaseCRUDAPIView
from core.models import Doctor, Patient
from core.sessions import SessionTokenAPIView
from referrals import services
from referrals.models import ConsultationReport, Referral, ReferralPackage, Specialist
from referrals.serializers import (
    ConsultationReportSerializer,
    ReferralPackageSerializer,
    ReferralSerializer,
    SpecialistSerializer,
)
from registration.models import UploadedDocument


# Generic CRUD (dev/admin convenience), same pattern as the other agents.
class SpecialistCRUDAPIView(BaseCRUDAPIView):
    model = Specialist
    serializer_class = SpecialistSerializer


class ReferralCRUDAPIView(BaseCRUDAPIView):
    model = Referral
    serializer_class = ReferralSerializer


class ReferralPackageCRUDAPIView(BaseCRUDAPIView):
    model = ReferralPackage
    serializer_class = ReferralPackageSerializer


class ConsultationReportCRUDAPIView(BaseCRUDAPIView):
    model = ConsultationReport
    serializer_class = ConsultationReportSerializer


def _parse_datetime(value):
    """Incoming ISO strings -> naive LOCAL datetimes.

    Matches scheduling.services' existing convention exactly (find_available_slots
    builds and compares naive local-wall-clock times via
    timezone.localtime().replace(tzinfo=None)) — an aware input must be
    converted to local time FIRST, not just have its offset chopped off, or
    a client sending UTC would silently book 5.5 hours off (TIME_ZONE is
    Asia/Kolkata).
    """
    parsed = datetime.fromisoformat(value)
    return timezone.localtime(parsed).replace(tzinfo=None) if parsed.tzinfo else parsed


def _referral_summary(referral: Referral) -> dict:
    return {
        "id": referral.id,
        "patient_id": referral.patient_id,
        "specialty_needed": referral.specialty_needed,
        "specialist": referral.specialist.name if referral.specialist else None,
        "referring_doctor": referral.referring_doctor.name if referral.referring_doctor else None,
        "reason": referral.reason,
        "urgency": referral.urgency,
        "status": referral.status,
        "status_display": referral.get_status_display(),
        "stalled": referral.status == "stalled",
        "appointment_id": referral.appointment_id,
        "external_appointment_at": referral.external_appointment_at,
        "created_at": referral.created_at,
    }


# -- physician: create (FR-F1) ------------------------------------------------

class CreateReferralAPIView(APIView):
    """POST /api/referrals/ — {patient_id, doctor_id, specialty, reason,
    urgency} -> 201 {id, status}. One click during consultation (FR-F1)."""

    permission_classes = [IsAdminUser]
    REQUIRED = ("patient_id", "doctor_id", "specialty", "reason", "urgency")

    def post(self, request):
        missing = sorted(f for f in self.REQUIRED if not request.data.get(f))
        if missing:
            return Response({"error": f"missing required fields: {missing}"},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            patient = Patient.objects.get(id=request.data["patient_id"])
        except (Patient.DoesNotExist, ValueError, TypeError):
            return Response({"error": "patient not found"}, status=status.HTTP_404_NOT_FOUND)
        try:
            doctor = Doctor.objects.get(id=request.data["doctor_id"])
        except (Doctor.DoesNotExist, ValueError, TypeError):
            return Response({"error": "doctor not found"}, status=status.HTTP_404_NOT_FOUND)

        referral = services.create_referral(
            doctor, patient, request.data["specialty"],
            request.data["reason"], request.data["urgency"],
        )
        return Response({"id": referral.id, "status": referral.status},
                        status=status.HTTP_201_CREATED)


# -- patient: my referrals + confirming a booked visit ------------------------

class PatientReferralsAPIView(SessionTokenAPIView):
    """GET /api/referrals/status/ — the session's patient's own referrals."""

    def get(self, request):
        patient, error = self.verified_patient_or_error()
        if error:
            return error
        referrals = Referral.objects.filter(patient=patient).order_by("-created_at")
        return Response([_referral_summary(r) for r in referrals])


class ConfirmReferralAPIView(SessionTokenAPIView):
    """POST /api/referrals/{id}/confirm/ — the patient confirms a booked
    specialist visit -> status patient_confirmed."""

    def post(self, request, referral_id):
        patient, error = self.verified_patient_or_error()
        if error:
            return error
        try:
            referral = Referral.objects.get(id=referral_id, patient=patient)
        except Referral.DoesNotExist:
            return Response({"error": "referral not found"}, status=status.HTTP_404_NOT_FOUND)

        try:
            services.advance_status(referral, "patient_confirmed")
        except services.IllegalStatusTransition as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"status": referral.status})


# -- care coordinator: pipeline view (FR-F7, FR-F9) ---------------------------

class ReferralQueueAPIView(APIView):
    """GET /api/staff/referrals/ — every referral with status + stalled flag,
    optionally filtered by ?status=."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        referrals = Referral.objects.select_related(
            "patient", "specialist", "referring_doctor",
        ).order_by("-created_at")
        status_filter = request.query_params.get("status")
        if status_filter:
            referrals = referrals.filter(status=status_filter)
        return Response([_referral_summary(r) for r in referrals])


class ReferralTimelineAPIView(APIView):
    """GET /api/staff/referrals/{id}/ — one referral's full status timeline."""

    permission_classes = [IsAdminUser]

    def get(self, request, referral_id):
        try:
            referral = Referral.objects.get(id=referral_id)
        except Referral.DoesNotExist:
            return Response({"error": "referral not found"}, status=status.HTTP_404_NOT_FOUND)
        body = _referral_summary(referral)
        body["status_history"] = referral.status_history
        return Response(body)


# -- specialist-side (simulated) + booking ------------------------------------

class SpecialistCandidatesAPIView(APIView):
    """GET /api/staff/referrals/{id}/candidates/ — ranked match_specialists()
    results, best first, so a coordinator can pick who to accept with."""

    permission_classes = [IsAdminUser]

    def get(self, request, referral_id):
        try:
            referral = Referral.objects.get(id=referral_id)
        except Referral.DoesNotExist:
            return Response({"error": "referral not found"}, status=status.HTTP_404_NOT_FOUND)
        candidates = services.match_specialists(referral, referral.patient)
        return Response(SpecialistSerializer(candidates, many=True).data)


class AcceptReferralAPIView(APIView):
    """POST /api/staff/referrals/{id}/accept/ — {specialist_id, doctor_id?}
    -> accepted.

    Simulates the specialist's office confirming they'll take the referral
    (FR-F3) — there's no specialist portal yet, so a coordinator enters this
    on their behalf. doctor_id is required the first time for a draft
    referral that came from a triage handoff (no referring_doctor yet) —
    that's the physician-confirmation gate (Phase 6); a referral that
    already has one ignores doctor_id.
    """

    permission_classes = [IsAdminUser]

    def post(self, request, referral_id):
        try:
            referral = Referral.objects.get(id=referral_id)
        except Referral.DoesNotExist:
            return Response({"error": "referral not found"}, status=status.HTTP_404_NOT_FOUND)
        try:
            specialist = Specialist.objects.get(id=request.data.get("specialist_id"))
        except (Specialist.DoesNotExist, ValueError, TypeError):
            return Response({"error": "specialist not found"}, status=status.HTTP_404_NOT_FOUND)

        doctor = None
        doctor_id = request.data.get("doctor_id")
        if doctor_id:
            try:
                doctor = Doctor.objects.get(id=doctor_id)
            except (Doctor.DoesNotExist, ValueError, TypeError):
                return Response({"error": "referring doctor not found"},
                                status=status.HTTP_404_NOT_FOUND)

        try:
            services.accept_referral(referral, specialist, doctor)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except services.IllegalStatusTransition as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"status": referral.status, "specialist": specialist.name})


class BookReferralVisitAPIView(APIView):
    """POST /api/staff/referrals/{id}/book/ — {start, end} (ISO datetimes)
    -> books against the specialist's in-network calendar (FR-F5)."""

    permission_classes = [IsAdminUser]

    def post(self, request, referral_id):
        try:
            referral = Referral.objects.get(id=referral_id)
        except Referral.DoesNotExist:
            return Response({"error": "referral not found"}, status=status.HTTP_404_NOT_FOUND)
        if not request.data.get("start") or not request.data.get("end"):
            return Response({"error": "start and end are required"},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            start = _parse_datetime(request.data["start"])
            end = _parse_datetime(request.data["end"])
        except ValueError:
            return Response({"error": "start/end must be ISO 8601 datetimes"},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            appointment = services.book_specialist_visit(referral, (start, end))
        except (services.IllegalStatusTransition, ValueError) as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"status": referral.status, "appointment_id": appointment.id})


class ResumeReferralAPIView(APIView):
    """POST /api/staff/referrals/{id}/resume/ — move a stalled referral back
    to whatever status it was in before it stalled, so the normal next
    action (book/visit-completed/report) becomes available again."""

    permission_classes = [IsAdminUser]

    def post(self, request, referral_id):
        try:
            referral = Referral.objects.get(id=referral_id)
        except Referral.DoesNotExist:
            return Response({"error": "referral not found"}, status=status.HTTP_404_NOT_FOUND)
        try:
            services.resume_referral(referral)
        except services.IllegalStatusTransition as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"status": referral.status})


class MarkVisitCompletedAPIView(APIView):
    """POST /api/staff/referrals/{id}/visit-completed/ — the specialist's
    office reports the patient was seen -> visit_completed."""

    permission_classes = [IsAdminUser]

    def post(self, request, referral_id):
        try:
            referral = Referral.objects.get(id=referral_id)
        except Referral.DoesNotExist:
            return Response({"error": "referral not found"}, status=status.HTTP_404_NOT_FOUND)
        try:
            services.advance_status(referral, "visit_completed")
        except services.IllegalStatusTransition as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"status": referral.status})


class UploadConsultationReportAPIView(APIView):
    """POST /api/staff/referrals/{id}/report/ — closes the loop (FR-F10),
    two ways:

    1. Structured JSON: {diagnosis, treatment_plan, medications,
       followup_recommendations} — a human enters the specialist's report.
    2. Multipart {file}: reads the report with AI (Phase 4's
       parse_consultation_report) and feeds the extracted fields into the
       same close_loop() call. Extraction failure or an illegible scan
       returns a 422 — the caller should retry the upload or fall back to
       path 1 — it never closes the referral with unreliable content.
    """

    permission_classes = [IsAdminUser]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request, referral_id):
        try:
            referral = Referral.objects.get(id=referral_id)
        except Referral.DoesNotExist:
            return Response({"error": "referral not found"}, status=status.HTTP_404_NOT_FOUND)

        upload = request.FILES.get("file")
        if upload is not None:
            document = UploadedDocument.objects.create(
                patient=referral.patient, document_type="consultation_report", file=upload,
            )
            try:
                report_data = services.parse_consultation_report(document)
            except Exception:
                return Response(
                    {"error": "could not read the uploaded report reliably — "
                              "please re-upload a clearer copy or enter the details manually",
                     "document_id": document.id},
                    status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
        else:
            report_data = {
                "diagnosis": request.data.get("diagnosis", ""),
                "treatment_plan": request.data.get("treatment_plan", ""),
                "medications": request.data.get("medications", []),
                "followup_recommendations": request.data.get("followup_recommendations", []),
            }

        try:
            report = services.close_loop(referral, report_data)
        except services.IllegalStatusTransition as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"status": referral.status, "report_id": report.id})
