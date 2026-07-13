"""Care gap API (Agent 8, Phase 3).

Staff endpoints (IsAdminUser, same staff-account convention as the other
agents): the risk-prioritized gap worklist, per-patient gap panel, care plan
bundling + detail, a manual scan trigger (the "run now, cron later" button —
Phase 7 gives the nightly job to a real scheduler), and the FR-G9 quality
metrics the population-health dashboard reads.

"Per-provider" in the metrics means the patient's most recent completed
appointment's doctor — the closest thing to a panel assignment this codebase
has (Patient carries no assigned-physician field). Patients who have never
completed a visit roll up under "unassigned".
"""

from django.db.models import OuterRef, Subquery
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from caregaps import services
from caregaps.models import CareGap, CarePlan, ClinicalEvent, ClinicalGuideline
from caregaps.serializers import (
    CareGapSerializer,
    CarePlanSerializer,
    ClinicalEventSerializer,
    ClinicalGuidelineSerializer,
)
from core.base_crud_views import BaseCRUDAPIView
from core.models import Patient
from scheduling.models import Appointment

_GAP_STATUSES = {choice for choice, _ in CareGap.STATUS_CHOICES}


# Generic CRUD (dev/admin convenience), same pattern as the other agents.
class ClinicalGuidelineCRUDAPIView(BaseCRUDAPIView):
    model = ClinicalGuideline
    serializer_class = ClinicalGuidelineSerializer


class ClinicalEventCRUDAPIView(BaseCRUDAPIView):
    model = ClinicalEvent
    serializer_class = ClinicalEventSerializer


class CareGapCRUDAPIView(BaseCRUDAPIView):
    model = CareGap
    serializer_class = CareGapSerializer


class CarePlanCRUDAPIView(BaseCRUDAPIView):
    model = CarePlan
    serializer_class = CarePlanSerializer


def _gap_summary(gap: CareGap, today=None) -> dict:
    today = today or timezone.localdate()
    return {
        "id": gap.id,
        "patient_id": gap.patient_id,
        "patient_name": f"{gap.patient.first_name} {gap.patient.last_name}".strip(),
        "contact_number": gap.patient.contact_number,
        "guideline_id": gap.guideline_id,
        "guideline_name": gap.guideline.name,
        "care_item_type": gap.guideline.care_item_type,
        "risk_tier": gap.guideline.risk_tier,
        "status": gap.status,
        "due_since": gap.due_since,
        "days_overdue": (today - gap.due_since).days,
        "detected_at": gap.detected_at,
        "closed_at": gap.closed_at,
    }


def _plan_detail(plan: CarePlan) -> dict:
    gaps = list(plan.gaps.select_related("patient", "guideline").order_by("id"))
    breakdown = services.bundle_breakdown(g for g in gaps if g.status != "closed")
    return {
        "id": plan.id,
        "patient_id": plan.patient_id,
        "patient_name": f"{plan.patient.first_name} {plan.patient.last_name}".strip(),
        "status": plan.status,
        "plan_text": plan.plan_text,
        "created_at": plan.created_at,
        "gaps": [_gap_summary(g) for g in gaps],
        "shared_visit_gap_ids": [g.id for g in breakdown["shared_visit"]],
        "separate_gap_ids": [g.id for g in breakdown["separate"]],
    }


# -- staff: the risk-prioritized worklist (FR-G3) -------------------------------

class GapWorklistAPIView(APIView):
    """GET /api/staff/caregaps/ — every gap in priority order (risk tier,
    then most overdue first): the staff work-the-list surface and the
    dashboard's patient list. ?status= narrows (default "open");
    ?guideline= narrows to one rule."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        status_filter = request.query_params.get("status", "open")
        if status_filter not in _GAP_STATUSES:
            return Response({"error": f"status must be one of {sorted(_GAP_STATUSES)}"},
                            status=status.HTTP_400_BAD_REQUEST)
        gaps = services.prioritize(statuses=(status_filter,))
        guideline_id = request.query_params.get("guideline")
        if guideline_id:
            gaps = gaps.filter(guideline_id=guideline_id)
        today = timezone.localdate()
        return Response([_gap_summary(g, today) for g in gaps])


# -- staff: per-patient gap panel ------------------------------------------------

class PatientGapsAPIView(APIView):
    """GET /api/staff/caregaps/patients/{id}/ — one patient's gaps (live
    first, prioritized) and care plans. This is also the surface the
    scheduling flow reads in Phase 6 ("also due for a cholesterol
    screening")."""

    permission_classes = [IsAdminUser]

    def get(self, request, patient_id):
        try:
            patient = Patient.objects.get(id=patient_id)
        except Patient.DoesNotExist:
            return Response({"error": "patient not found"}, status=status.HTTP_404_NOT_FOUND)
        today = timezone.localdate()
        live = services.prioritize(statuses=services.LIVE_GAP_STATUSES).filter(patient=patient)
        closed = (CareGap.objects.filter(patient=patient, status="closed")
                  .select_related("patient", "guideline").order_by("-closed_at"))
        return Response({
            "patient_id": patient.id,
            "patient_name": f"{patient.first_name} {patient.last_name}".strip(),
            "open_gaps": [_gap_summary(g, today) for g in live],
            "closed_gaps": [_gap_summary(g, today) for g in closed],
            "care_plans": [_plan_detail(p) for p in
                           patient.care_plans.order_by("-created_at")],
        })


# -- staff: bundle + plan detail (FR-G4) ----------------------------------------

class BundleCarePlanAPIView(APIView):
    """POST /api/staff/caregaps/patients/{id}/bundle/ — build (or refresh)
    the patient's care plan from their open gaps. Connective tissue: the
    build step only names "care plan detail", but bundling needs a trigger
    before Phase 6 automates it, and the Phase 5 UI needs this button."""

    permission_classes = [IsAdminUser]

    def post(self, request, patient_id):
        try:
            patient = Patient.objects.get(id=patient_id)
        except Patient.DoesNotExist:
            return Response({"error": "patient not found"}, status=status.HTTP_404_NOT_FOUND)
        plan = services.bundle_care_plan(patient)
        if plan is None:
            return Response({"error": "no open gaps to bundle"},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response(_plan_detail(plan), status=status.HTTP_201_CREATED)


class CarePlanDetailAPIView(APIView):
    """GET /api/staff/caregaps/plans/{id}/ — the plan, its gaps, and the
    shared-visit vs. separate-appointment split."""

    permission_classes = [IsAdminUser]

    def get(self, request, plan_id):
        try:
            plan = CarePlan.objects.get(id=plan_id)
        except CarePlan.DoesNotExist:
            return Response({"error": "care plan not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(_plan_detail(plan))


# -- staff: manual scan trigger --------------------------------------------------

class TriggerScanAPIView(APIView):
    """POST /api/staff/caregaps/scan/ — run the scanner now. Body
    {"patient_id": N} scans one patient (the per-chart refresh button);
    an empty body runs the full panel scan (dev convenience — nightly this
    is the scan_care_gaps command, not a request)."""

    permission_classes = [IsAdminUser]

    def post(self, request):
        patient_id = request.data.get("patient_id")
        if patient_id:
            try:
                patient = Patient.objects.get(id=patient_id)
            except Patient.DoesNotExist:
                return Response({"error": "patient not found"}, status=status.HTTP_404_NOT_FOUND)
            return Response({"scope": f"patient {patient.id}", **services.scan_patient(patient)})
        return Response({"scope": "all", **services.scan_all()})


# -- staff: FR-G9 quality metrics -------------------------------------------------

class QualityMetricsAPIView(APIView):
    """GET /api/staff/caregaps/metrics/ — what the population-health
    dashboard plots: open gaps by guideline, overall closure rate, the care
    plan funnel (response + completion rates), and the per-provider
    breakdown."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        # gaps by guideline
        by_guideline = []
        for guideline in ClinicalGuideline.objects.order_by("name"):
            live = guideline.gaps.exclude(status="closed").count()
            closed = guideline.gaps.filter(status="closed").count()
            by_guideline.append({
                "guideline_id": guideline.id,
                "guideline_name": guideline.name,
                "risk_tier": guideline.risk_tier,
                "is_active": guideline.is_active,
                "open_gaps": live,
                "closed_gaps": closed,
            })

        total = CareGap.objects.count()
        closed = CareGap.objects.filter(status="closed").count()

        # care plan funnel: response = the patient engaged with a sent plan;
        # completion = every item in the plan actually happened.
        plan_counts = {choice: 0 for choice, _ in CarePlan.STATUS_CHOICES}
        for row in CarePlan.objects.values("status"):
            plan_counts[row["status"]] += 1
        ever_sent = sum(plan_counts[s] for s in
                        ("sent", "accepted", "in_progress", "completed", "recycled"))
        responded = sum(plan_counts[s] for s in ("accepted", "in_progress", "completed"))

        # per-provider: the doctor of the patient's most recent completed visit.
        provider_of_patient = Subquery(
            Appointment.objects
            .filter(patient=OuterRef("patient_id"), status="completed")
            .order_by("-start_time")
            .values("doctor__name")[:1]
        )
        per_provider: dict[str, dict] = {}
        for row in CareGap.objects.annotate(_provider=provider_of_patient).values("_provider", "status"):
            bucket = per_provider.setdefault(
                row["_provider"] or "unassigned", {"open_gaps": 0, "closed_gaps": 0})
            bucket["closed_gaps" if row["status"] == "closed" else "open_gaps"] += 1
        provider_rows = [
            {"provider": name, **counts,
             "closure_rate": round(counts["closed_gaps"] /
                                   (counts["open_gaps"] + counts["closed_gaps"]), 3)}
            for name, counts in sorted(per_provider.items())
        ]

        return Response({
            "gaps": {
                "total": total,
                "open": total - closed,
                "closed": closed,
                "closure_rate": round(closed / total, 3) if total else 0.0,
                "by_guideline": by_guideline,
            },
            "care_plans": {
                "by_status": plan_counts,
                "response_rate": round(responded / ever_sent, 3) if ever_sent else 0.0,
                "completion_rate": round(plan_counts["completed"] / ever_sent, 3) if ever_sent else 0.0,
            },
            "per_provider": provider_rows,
        })
