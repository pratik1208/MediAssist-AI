"""Refill API (Agent 4, Phase 3) — spec API table, no AI yet.

Patient endpoints ride the shared session token (core.sessions) and require
a verified identity (FR-M2). Physician endpoints are one call = one click
(FR-M6): the deciding doctor defaults to the prescription's prescriber until
a staff-user -> Doctor link exists; pass doctor_id to override.
"""

from rest_framework import status
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from core.base_crud_views import BaseCRUDAPIView
from core.models import Doctor
from core.sessions import SessionTokenAPIView
from refills import services
from refills.models import Pharmacy, Prescription, RefillRequest
from refills.serializers import (
    PharmacySerializer,
    PrescriptionSerializer,
    RefillRequestSerializer,
)


# Generic CRUD (dev/admin convenience), same pattern as the other agents.
class PharmacyCRUDAPIView(BaseCRUDAPIView):
    model = Pharmacy
    serializer_class = PharmacySerializer


class PrescriptionCRUDAPIView(BaseCRUDAPIView):
    model = Prescription
    serializer_class = PrescriptionSerializer


class RefillRequestCRUDAPIView(BaseCRUDAPIView):
    model = RefillRequest
    serializer_class = RefillRequestSerializer


# -- patient endpoints --------------------------------------------------------

class PatientPrescriptionsAPIView(SessionTokenAPIView):
    """GET /api/refills/prescriptions/ — the patient's active prescriptions."""

    def get(self, request):
        patient, error = self.verified_patient_or_error()
        if error:
            return error
        prescriptions = Prescription.objects.filter(patient=patient, status="active")
        return Response([{
            "id": rx.id,
            "medication": f"{rx.medication_name} {rx.dose}",
            "quantity": rx.quantity,
            "refills_remaining": max(rx.refills_allowed - rx.refills_used, 0),
            "controlled_substance": rx.is_controlled_substance,
        } for rx in prescriptions])


class CreateRefillRequestAPIView(SessionTokenAPIView):
    """POST /api/refills/requests/ — {prescription_id, pharmacy_id?} ->
    201 {id, status} or 409 {code: "paused", reason} (spec API table)."""

    def _resolve_pharmacy(self, request_data, patient):
        pharmacy_id = request_data.get("pharmacy_id")
        if pharmacy_id:
            return Pharmacy.objects.filter(id=pharmacy_id).first()
        # Fall back to the patient's preferred pharmacy by name (the Patient
        # field predates the Pharmacy model and is free text).
        preferred = (patient.preferred_pharmacy or "").strip()
        if preferred:
            match = Pharmacy.objects.filter(name__icontains=preferred).first()
            if match:
                return match
        return None

    def post(self, request):
        patient, error = self.verified_patient_or_error()
        if error:
            return error
        try:
            prescription = Prescription.objects.get(
                id=request.data.get("prescription_id"), patient=patient,
            )
        except (Prescription.DoesNotExist, ValueError, TypeError):
            return Response({"error": "prescription not found"},
                            status=status.HTTP_404_NOT_FOUND)
        pharmacy = self._resolve_pharmacy(request.data, patient)
        if pharmacy is None:
            return Response(
                {"error": "pharmacy_id is required (no preferred pharmacy on file)"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        refill_request = RefillRequest.objects.create(
            prescription=prescription, patient=patient, pharmacy=pharmacy,
        )
        result = services.run_eligibility_check(refill_request)
        refill_request.refresh_from_db()

        if refill_request.status == "paused":
            return Response(
                {"id": refill_request.id, "code": "paused",
                 "reason": refill_request.pause_reason},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(
            {"id": refill_request.id, "status": refill_request.status,
             "is_renewal": result.needs_new_prescription},
            status=status.HTTP_201_CREATED,
        )


class RefillRequestStatusAPIView(SessionTokenAPIView):
    """GET /api/refills/requests/{id}/ — status for the session's patient."""

    def get(self, request, request_id):
        patient, error = self.verified_patient_or_error()
        if error:
            return error
        try:
            refill_request = RefillRequest.objects.get(id=request_id, patient=patient)
        except RefillRequest.DoesNotExist:
            return Response({"error": "refill request not found"},
                            status=status.HTTP_404_NOT_FOUND)
        body = {
            "id": refill_request.id,
            "medication": refill_request.prescription.medication_name,
            "status": refill_request.status,
            "status_display": refill_request.get_status_display(),
        }
        if refill_request.pause_reason:
            body["pause_reason"] = refill_request.pause_reason
        return Response(body)


# -- physician endpoints (FR-M6: one call = one click) -------------------------

class PhysicianRefillAPIView(APIView):
    permission_classes = [IsAdminUser]

    def request_or_error(self, request_id):
        try:
            return RefillRequest.objects.get(id=request_id), None
        except RefillRequest.DoesNotExist:
            return None, Response({"error": "refill request not found"},
                                  status=status.HTTP_404_NOT_FOUND)

    def deciding_doctor(self, request, refill_request):
        doctor_id = request.data.get("doctor_id")
        if doctor_id:
            return Doctor.objects.filter(id=doctor_id).first()
        return refill_request.prescription.prescriber

    def must_be_pending(self, refill_request):
        if refill_request.status != "pending_approval":
            return Response(
                {"error": f"request is {refill_request.status}, not pending_approval"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return None


class RefillQueueAPIView(APIView):
    """GET /api/staff/refills/queue/ — pending approvals with summaries."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        queue = (RefillRequest.objects.filter(status="pending_approval")
                 .select_related("patient", "prescription", "pharmacy")
                 .order_by("created_at"))
        return Response([{
            "id": r.id,
            "patient": f"{r.patient.first_name[0]}. {r.patient.last_name}",
            "medication": f"{r.prescription.medication_name} {r.prescription.dose}",
            "requested_at": r.created_at,
            "summary_text": r.summary_text,
            "renewal_summary": r.renewal_summary,
            "controlled_substance": r.prescription.is_controlled_substance,
            "actions": ["approve", "reject", "request_visit"],
        } for r in queue])


class ApproveRefillAPIView(PhysicianRefillAPIView):
    """POST /api/staff/refills/{id}/approve/ — one click (FR-M6/M7/M8)."""

    def post(self, request, request_id):
        refill_request, error = self.request_or_error(request_id)
        if error:
            return error
        error = self.must_be_pending(refill_request)
        if error:
            return error
        services.approve(refill_request, self.deciding_doctor(request, refill_request))
        refill_request.refresh_from_db()
        return Response({"status": refill_request.status})


class RejectRefillAPIView(PhysicianRefillAPIView):
    """POST /api/staff/refills/{id}/reject/ — {reason} required."""

    def post(self, request, request_id):
        refill_request, error = self.request_or_error(request_id)
        if error:
            return error
        error = self.must_be_pending(refill_request)
        if error:
            return error
        reason = (request.data.get("reason") or "").strip()
        if not reason:
            return Response({"error": "reason is required"},
                            status=status.HTTP_400_BAD_REQUEST)
        services.reject(refill_request, self.deciding_doctor(request, refill_request), reason)
        return Response({"status": "rejected"})


class RequestVisitAPIView(PhysicianRefillAPIView):
    """POST /api/staff/refills/{id}/request-visit/ — visit before refill."""

    def post(self, request, request_id):
        refill_request, error = self.request_or_error(request_id)
        if error:
            return error
        error = self.must_be_pending(refill_request)
        if error:
            return error
        services.request_visit(refill_request, self.deciding_doctor(request, refill_request))
        return Response({"status": "visit_required"})
