"""Prior authorization API (Agent 6, Phases 3 + 4).

Same staff/patient split as referrals: no doctor-user or specialist-user
login exists in this codebase, so "physician orders a treatment" is a staff
action performed on their behalf (IsAdminUser). Patient endpoints ride the
shared session token (core.sessions) and require a verified identity.
"""

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from core.base_crud_views import BaseCRUDAPIView
from core.models import Doctor, Patient
from core.sessions import SessionTokenAPIView
from priorauth import services
from priorauth.gateway import SimulatedPayerGateway
from priorauth.models import (
    AuthorizationPackage,
    AuthorizationRequest,
    PayerMessage,
    PayerRule,
    TreatmentOrder,
)
from priorauth.serializers import (
    AuthorizationPackageSerializer,
    AuthorizationRequestSerializer,
    PayerMessageSerializer,
    PayerRuleSerializer,
    TreatmentOrderSerializer,
)
from referrals.models import Referral
from triage.models import EscalationAlert


# Generic CRUD (dev/admin convenience), same pattern as the other agents.
class PayerRuleCRUDAPIView(BaseCRUDAPIView):
    model = PayerRule
    serializer_class = PayerRuleSerializer


class TreatmentOrderCRUDAPIView(BaseCRUDAPIView):
    model = TreatmentOrder
    serializer_class = TreatmentOrderSerializer


class AuthorizationRequestCRUDAPIView(BaseCRUDAPIView):
    model = AuthorizationRequest
    serializer_class = AuthorizationRequestSerializer


class AuthorizationPackageCRUDAPIView(BaseCRUDAPIView):
    model = AuthorizationPackage
    serializer_class = AuthorizationPackageSerializer


class PayerMessageCRUDAPIView(BaseCRUDAPIView):
    model = PayerMessage
    serializer_class = PayerMessageSerializer


def _request_summary(auth_request: AuthorizationRequest) -> dict:
    order = auth_request.order
    return {
        "id": auth_request.id,
        "order_id": order.id,
        "patient_id": order.patient_id,
        "order_type": order.order_type,
        "treatment": order.medication or order.cpt_code or order.icd10_code,
        "status": auth_request.status,
        "status_display": auth_request.get_status_display(),
        "denial_reason": auth_request.denial_reason,
        "appeal_suggested": auth_request.appeal_suggested,
        "external_reference": auth_request.external_reference,
        "created_at": auth_request.created_at,
    }


def _request_detail(auth_request: AuthorizationRequest) -> dict:
    body = _request_summary(auth_request)
    body["status_history"] = auth_request.status_history
    package = getattr(auth_request, "package", None)
    body["package"] = {
        "codes": package.codes,
        "evidence": package.evidence,
        "demographics_snapshot": package.demographics_snapshot,
        "reviewer_summary": package.reviewer_summary,
    } if package else None
    body["messages"] = [
        {"direction": m.direction, "content": m.content, "created_at": m.created_at}
        for m in auth_request.messages.order_by("created_at")
    ]
    return body


# -- physician: create treatment order (auto-triggers detection, FR-P1) -----

class CreateTreatmentOrderAPIView(APIView):
    """POST /api/priorauth/orders/ — {patient_id, order_type, doctor_id?,
    cpt_code?, icd10_code?, medication?, referral_id?} -> 201
    {order_id, authorization_required, request_id, status}."""

    permission_classes = [IsAdminUser]
    REQUIRED = ("patient_id", "order_type")

    def post(self, request):
        missing = sorted(f for f in self.REQUIRED if not request.data.get(f))
        if missing:
            return Response({"error": f"missing required fields: {missing}"},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            patient = Patient.objects.get(id=request.data["patient_id"])
        except (Patient.DoesNotExist, ValueError, TypeError):
            return Response({"error": "patient not found"}, status=status.HTTP_404_NOT_FOUND)

        order_type = request.data["order_type"]
        if order_type not in dict(TreatmentOrder.ORDER_TYPE_CHOICES):
            return Response(
                {"error": f"order_type must be one of {sorted(dict(TreatmentOrder.ORDER_TYPE_CHOICES))}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        doctor = None
        if request.data.get("doctor_id"):
            try:
                doctor = Doctor.objects.get(id=request.data["doctor_id"])
            except (Doctor.DoesNotExist, ValueError, TypeError):
                return Response({"error": "doctor not found"}, status=status.HTTP_404_NOT_FOUND)

        referral = None
        if request.data.get("referral_id"):
            try:
                referral = Referral.objects.get(id=request.data["referral_id"])
            except (Referral.DoesNotExist, ValueError, TypeError):
                return Response({"error": "referral not found"}, status=status.HTTP_404_NOT_FOUND)

        order = TreatmentOrder.objects.create(
            patient=patient, ordering_doctor=doctor, order_type=order_type,
            cpt_code=request.data.get("cpt_code") or None,
            icd10_code=request.data.get("icd10_code") or None,
            medication=request.data.get("medication") or None,
            referral=referral,
        )
        auth_request = services.initiate_authorization(order)
        return Response({
            "order_id": order.id,
            "authorization_required": auth_request is not None,
            "request_id": auth_request.id if auth_request else None,
            "status": auth_request.status if auth_request else None,
        }, status=status.HTTP_201_CREATED)


# -- patient: my authorization requests (FR-P7 "visible at any time") -------

class PatientAuthorizationsAPIView(SessionTokenAPIView):
    """GET /api/priorauth/status/ — the session's patient's own requests."""

    def get(self, request):
        patient, error = self.verified_patient_or_error()
        if error:
            return error
        requests = (AuthorizationRequest.objects.filter(order__patient=patient)
                    .select_related("order").order_by("-created_at"))
        return Response([_request_summary(r) for r in requests])


# -- staff / provider: full visibility (FR-P7) -------------------------------

class AuthorizationQueueAPIView(APIView):
    """GET /api/staff/priorauth/ — every authorization request, optionally
    filtered by ?status=. There's no separate doctor login in this codebase
    (same limitation noted throughout), so this is the one "provider view"
    too — any staff account can see any request."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        requests = (AuthorizationRequest.objects.select_related("order", "matched_rule")
                    .order_by("-created_at"))
        status_filter = request.query_params.get("status")
        if status_filter:
            requests = requests.filter(status=status_filter)
        return Response([_request_summary(r) for r in requests])


class AuthorizationDetailAPIView(APIView):
    """GET /api/staff/priorauth/{id}/ — full detail: timeline, package, and
    the payer-message audit trail."""

    permission_classes = [IsAdminUser]

    def get(self, request, request_id):
        try:
            auth_request = AuthorizationRequest.objects.get(id=request_id)
        except AuthorizationRequest.DoesNotExist:
            return Response({"error": "authorization request not found"},
                            status=status.HTTP_404_NOT_FOUND)
        return Response(_request_detail(auth_request))


class ReferralAuthorizationsAPIView(APIView):
    """GET /api/priorauth/for-referral/{referral_id}/ — every authorization
    request tied to treatment orders linked to this referral (Phase 5's "PA
    status column on the referral views"). Staff-gated to match the
    referral detail page that will call it."""

    permission_classes = [IsAdminUser]

    def get(self, request, referral_id):
        requests = (AuthorizationRequest.objects.filter(order__referral_id=referral_id)
                    .select_related("order").order_by("-created_at"))
        return Response([_request_summary(r) for r in requests])


class SuggestAppealAPIView(APIView):
    """POST /api/staff/priorauth/{id}/suggest-appeal/ — an AI recommendation
    + draft argument for a denied request (FR-P7 / Edge Case 9). Suggestion
    only — nothing here submits an appeal or changes the request."""

    permission_classes = [IsAdminUser]

    def post(self, request, request_id):
        try:
            auth_request = AuthorizationRequest.objects.get(id=request_id)
        except AuthorizationRequest.DoesNotExist:
            return Response({"error": "authorization request not found"},
                            status=status.HTTP_404_NOT_FOUND)
        try:
            suggestion = services.suggest_appeal_for(auth_request)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(suggestion)


class SubmitAuthorizationAPIView(APIView):
    """POST /api/staff/priorauth/{id}/submit/ — dispatch the package through
    the payer gateway (FR-P4). The connective step Phase 5's manual E2E
    needs to actually move the pipeline past "ready_for_review" — Phase 2's
    submit() has nowhere else to be called from otherwise."""

    permission_classes = [IsAdminUser]

    def post(self, request, request_id):
        try:
            auth_request = AuthorizationRequest.objects.get(id=request_id)
        except AuthorizationRequest.DoesNotExist:
            return Response({"error": "authorization request not found"},
                            status=status.HTTP_404_NOT_FOUND)
        try:
            services.submit(auth_request)
        except services.IllegalStatusTransition as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"status": auth_request.status,
                         "external_reference": auth_request.external_reference})


class PollAuthorizationStatusAPIView(APIView):
    """POST /api/staff/priorauth/{id}/poll/ — check the payer now (FR-P5),
    on demand, rather than waiting for the poll_payer_status management
    command. Pair with the simulator control endpoint to drive every
    branch (approve/deny/info-request) interactively."""

    permission_classes = [IsAdminUser]

    def post(self, request, request_id):
        try:
            auth_request = AuthorizationRequest.objects.get(id=request_id)
        except AuthorizationRequest.DoesNotExist:
            return Response({"error": "authorization request not found"},
                            status=status.HTTP_404_NOT_FOUND)
        services.poll_status(auth_request)
        return Response(_request_summary(auth_request))


class StagedTasksAPIView(APIView):
    """GET /api/staff/priorauth/tasks/ — priorauth's own staged reviews
    (handle_info_request's staff-staging path, FR-P6 / Edge Case 10).
    Acknowledge through the existing /api/staff/triage/escalations/{id}/ack/
    endpoint — one shared model, one ack action, no need to duplicate it."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        alerts = EscalationAlert.objects.filter(source_agent="priorauth").order_by("-id")
        status_filter = request.query_params.get("status", "open")
        if status_filter != "all":
            alerts = alerts.filter(status=status_filter)
        return Response([{
            "id": a.id,
            "patient_id": a.patient_id,
            "priority": a.priority,
            "summary": a.summary,
            "status": a.status,
            "acknowledged_at": a.acknowledged_at,
        } for a in alerts])


class PriorAuthAnalyticsAPIView(APIView):
    """GET /api/staff/priorauth/analytics/ — Phase 6 aggregates: turnaround
    time per status, approval rate, denial reasons breakdown."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        import datetime as dt
        from collections import defaultdict

        from django.db.models import Count

        requests = AuthorizationRequest.objects.all()
        total = requests.count()
        decided = requests.filter(status__in=["approved", "denied"])
        approved_count = decided.filter(status="approved").count()
        denied_qs = decided.filter(status="denied")
        decided_count = decided.count()

        def rate(part, whole):
            return round(part / whole, 3) if whole else None

        denial_reasons = {
            (row["denial_reason"] or "(no reason given)"): row["n"]
            for row in denied_qs.values("denial_reason").annotate(n=Count("id"))
        }

        # Average time spent in each status before moving on, computed from
        # status_history (a JSONField timeline, not separate DB columns —
        # this has to happen in Python, not an ORM aggregate).
        durations = defaultdict(list)
        for auth_request in requests:
            history = auth_request.status_history or []
            for i in range(len(history) - 1):
                try:
                    start = dt.datetime.fromisoformat(history[i]["at"])
                    end = dt.datetime.fromisoformat(history[i + 1]["at"])
                except (KeyError, ValueError, TypeError):
                    continue
                durations[history[i]["status"]].append((end - start).total_seconds())
        avg_seconds_in_status = {
            status: round(sum(values) / len(values), 1) for status, values in durations.items()
        }

        return Response({
            "requests": {
                "total": total, "decided": decided_count,
                "approved": approved_count, "denied": denied_qs.count(),
            },
            "approval_rate": rate(approved_count, decided_count),
            "denial_reasons": denial_reasons,
            "avg_seconds_in_status": avg_seconds_in_status,
        })


# -- simulator control (dev only) --------------------------------------------

class SimulatorControlAPIView(APIView):
    """POST /api/staff/priorauth/{id}/simulate/ — {status, denial_reason?,
    appeal_suggested?, requested_items?} -> force what the SimulatedPayerGateway
    returns on the NEXT poll_status() call for this request. Dev only — makes
    manual testing of every branch (approve/deny/info-request) trivial
    without waiting on a real payer.
    """

    permission_classes = [IsAdminUser]

    def post(self, request, request_id):
        if not settings.DEBUG:
            return Response({"error": "simulator control is only available in DEBUG"},
                            status=status.HTTP_403_FORBIDDEN)
        try:
            auth_request = AuthorizationRequest.objects.get(id=request_id)
        except AuthorizationRequest.DoesNotExist:
            return Response({"error": "authorization request not found"},
                            status=status.HTTP_404_NOT_FOUND)

        forced_status = request.data.get("status")
        valid = {"submitted", "under_review", "info_requested", "approved", "denied"}
        if forced_status not in valid:
            return Response({"error": f"status must be one of {sorted(valid)}"},
                            status=status.HTTP_400_BAD_REQUEST)

        extra = {k: request.data[k] for k in
                 ("denial_reason", "appeal_suggested", "requested_items") if k in request.data}
        SimulatedPayerGateway.force_response(auth_request.id, forced_status, **extra)
        return Response({"forced": {"status": forced_status, **extra}})
