"""Care gap API (Phase 3): staff worklist / patient panel / bundling / scan
trigger / FR-G9 metrics, plus auth gating and the generic CRUD routes."""

import datetime

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from caregaps import services
from caregaps.models import CareGap, CarePlan, ClinicalEvent, ClinicalGuideline
from core.models import Doctor, Patient
from scheduling.models import Appointment

pytestmark = pytest.mark.django_db

BASE = "/api/staff/caregaps/"
TODAY = timezone.localdate()


@pytest.fixture
def staff_client(client, db):
    staff = get_user_model().objects.create_user("quality", password="x", is_staff=True)
    client.force_login(staff)
    return client


def post_json(client, url, data):
    return client.post(url, data, content_type="application/json")


def make_patient(first="Asha", phone="9000000001", age=70):
    return Patient.objects.create(
        first_name=first, last_name="Rao", contact_number=phone,
        dob=datetime.date(TODAY.year - age, 1, 15), registration_status="complete",
    )


def make_guideline(name="Flu 65+", criteria=None, item_type="vaccination", code="140",
                   frequency_days=365, risk_tier="medium"):
    return ClinicalGuideline.objects.create(
        name=name, population_criteria=criteria if criteria is not None else {"age_min": 65},
        care_item_type=item_type, care_item_code=code,
        frequency_days=frequency_days, risk_tier=risk_tier,
    )


class TestAuth:
    @pytest.mark.parametrize("url,method", [
        (BASE, "get"),
        (f"{BASE}scan/", "post"),
        (f"{BASE}metrics/", "get"),
        (f"{BASE}patients/1/", "get"),
        (f"{BASE}patients/1/bundle/", "post"),
        (f"{BASE}plans/1/", "get"),
    ])
    def test_staff_endpoints_reject_anonymous(self, client, db, url, method):
        response = getattr(client, method)(url)
        assert response.status_code in (401, 403)


class TestGapWorklist:
    def test_prioritized_order_and_fields(self, staff_client):
        p1 = make_patient(phone="9000000001")
        p2 = make_patient(first="Ravi", phone="9000000002")
        high = make_guideline(name="HbA1c", criteria={}, item_type="test",
                              code="4548-4", risk_tier="high")
        medium = make_guideline(name="Flu", criteria={}, code="140", risk_tier="medium")
        CareGap.objects.create(patient=p1, guideline=medium,
                               due_since=TODAY - datetime.timedelta(days=400))
        CareGap.objects.create(patient=p2, guideline=high,
                               due_since=TODAY - datetime.timedelta(days=10))

        body = staff_client.get(BASE).json()
        assert [row["risk_tier"] for row in body] == ["high", "medium"]
        first = body[0]
        assert first["patient_name"] == "Ravi Rao"
        assert first["guideline_name"] == "HbA1c"
        assert first["days_overdue"] == 10
        assert first["status"] == "open"

    def test_status_and_guideline_filters(self, staff_client):
        patient = make_patient()
        g1 = make_guideline(name="A", criteria={}, code="A")
        g2 = make_guideline(name="B", criteria={}, code="B")
        gap = CareGap.objects.create(patient=patient, guideline=g1, due_since=TODAY)
        gap.status = "scheduled"
        gap.save()
        CareGap.objects.create(patient=patient, guideline=g2, due_since=TODAY)

        assert len(staff_client.get(BASE).json()) == 1  # default: open only
        scheduled = staff_client.get(f"{BASE}?status=scheduled").json()
        assert [row["id"] for row in scheduled] == [gap.id]
        assert staff_client.get(f"{BASE}?guideline={g2.id}").json()[0]["guideline_id"] == g2.id

    def test_bad_status_is_400(self, staff_client):
        response = staff_client.get(f"{BASE}?status=bogus")
        assert response.status_code == 400
        assert "status must be one of" in response.json()["error"]


class TestPatientGaps:
    def test_404_unknown_patient(self, staff_client):
        assert staff_client.get(f"{BASE}patients/99999/").status_code == 404

    def test_panel_shows_live_closed_and_plans(self, staff_client):
        patient = make_patient()
        guideline = make_guideline(criteria={})
        gap = CareGap.objects.create(patient=patient, guideline=guideline, due_since=TODAY)
        plan = services.bundle_care_plan(patient)
        evidence = ClinicalEvent.objects.create(
            patient=patient, event_type="vaccination", code="140", occurred_at=timezone.now())
        services.close_gap(gap, evidence)

        body = staff_client.get(f"{BASE}patients/{patient.id}/").json()
        assert body["patient_name"] == "Asha Rao"
        assert body["open_gaps"] == []
        assert len(body["closed_gaps"]) == 1
        assert body["closed_gaps"][0]["status"] == "closed"
        assert len(body["care_plans"]) == 1
        assert body["care_plans"][0]["id"] == plan.id
        assert body["care_plans"][0]["status"] == "completed"


class TestBundleAndPlanDetail:
    def test_bundle_404_unknown_patient(self, staff_client):
        assert post_json(staff_client, f"{BASE}patients/99999/bundle/", {}).status_code == 404

    def test_bundle_400_when_nothing_open(self, staff_client):
        patient = make_patient()
        response = post_json(staff_client, f"{BASE}patients/{patient.id}/bundle/", {})
        assert response.status_code == 400
        assert "no open gaps" in response.json()["error"]

    def test_bundle_creates_plan_with_breakdown(self, staff_client):
        patient = make_patient()
        lab = make_guideline(name="HbA1c", criteria={}, item_type="test", code="4548-4")
        screening = make_guideline(name="Mammogram", criteria={},
                                   item_type="screening", code="77067")
        lab_gap = CareGap.objects.create(patient=patient, guideline=lab, due_since=TODAY)
        scr_gap = CareGap.objects.create(patient=patient, guideline=screening, due_since=TODAY)

        response = post_json(staff_client, f"{BASE}patients/{patient.id}/bundle/", {})
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "draft"
        assert {g["id"] for g in body["gaps"]} == {lab_gap.id, scr_gap.id}
        assert body["shared_visit_gap_ids"] == [lab_gap.id]
        assert body["separate_gap_ids"] == [scr_gap.id]
        assert "single visit" in body["plan_text"]

    def test_plan_detail_and_404(self, staff_client):
        assert staff_client.get(f"{BASE}plans/99999/").status_code == 404
        patient = make_patient()
        guideline = make_guideline(criteria={})
        CareGap.objects.create(patient=patient, guideline=guideline, due_since=TODAY)
        plan = services.bundle_care_plan(patient)
        body = staff_client.get(f"{BASE}plans/{plan.id}/").json()
        assert body["id"] == plan.id
        assert len(body["gaps"]) == 1


class TestTriggerScan:
    def test_scan_one_patient(self, staff_client):
        patient = make_patient()
        make_guideline()
        response = post_json(staff_client, f"{BASE}scan/", {"patient_id": patient.id})
        assert response.status_code == 200
        body = response.json()
        assert body["scope"] == f"patient {patient.id}"
        assert body["opened"] == 1
        assert CareGap.objects.filter(patient=patient).count() == 1

    def test_scan_unknown_patient_404(self, staff_client):
        assert post_json(staff_client, f"{BASE}scan/", {"patient_id": 99999}).status_code == 404

    def test_scan_all(self, staff_client):
        make_patient(phone="9000000001")
        make_patient(first="Ravi", phone="9000000002")
        make_guideline()
        body = post_json(staff_client, f"{BASE}scan/", {}).json()
        assert body["scope"] == "all"
        assert body["opened"] == 2


class TestQualityMetrics:
    def test_empty_db_metrics(self, staff_client):
        body = staff_client.get(f"{BASE}metrics/").json()
        assert body["gaps"]["total"] == 0
        assert body["gaps"]["closure_rate"] == 0.0
        assert body["care_plans"]["response_rate"] == 0.0
        assert body["per_provider"] == []

    def test_full_metrics_shape(self, staff_client):
        doctor = Doctor.objects.create(name="Dr. Mehta", specialty="General Medicine",
                                       working_hours={"mon": [["09:00", "17:00"]]})
        assigned = make_patient(phone="9000000001")
        unassigned = make_patient(first="Ravi", phone="9000000002")
        start = timezone.now() - datetime.timedelta(days=30)
        Appointment.objects.create(
            doctor=doctor, patient=assigned, start_time=start,
            end_time=start + datetime.timedelta(minutes=20),
            reason="checkup", urgency="routine", status="completed", source="scheduling",
        )
        guideline = make_guideline(criteria={})
        closed_gap = CareGap.objects.create(patient=assigned, guideline=guideline, due_since=TODAY)
        plan = services.bundle_care_plan(assigned)
        plan.status = "sent"
        plan.save()
        services.close_gap(closed_gap)  # sent plan whose gaps all closed -> completed
        CareGap.objects.create(patient=unassigned, guideline=guideline, due_since=TODAY)

        body = staff_client.get(f"{BASE}metrics/").json()
        assert body["gaps"]["total"] == 2
        assert body["gaps"]["open"] == 1
        assert body["gaps"]["closed"] == 1
        assert body["gaps"]["closure_rate"] == 0.5
        row = body["gaps"]["by_guideline"][0]
        assert row["open_gaps"] == 1 and row["closed_gaps"] == 1

        assert body["care_plans"]["by_status"]["completed"] == 1
        assert body["care_plans"]["response_rate"] == 1.0
        assert body["care_plans"]["completion_rate"] == 1.0

        providers = {r["provider"]: r for r in body["per_provider"]}
        assert providers["Dr. Mehta"]["closed_gaps"] == 1
        assert providers["Dr. Mehta"]["closure_rate"] == 1.0
        assert providers["unassigned"]["open_gaps"] == 1


class TestGenericCRUD:
    def test_crud_roundtrip(self, client, db):
        patient = make_patient()
        response = post_json(client, "/api/clinicalevent", {
            "patient": patient.id, "event_type": "lab", "code": "4548-4",
            "value": {"hba1c": 7.1}, "occurred_at": timezone.now().isoformat(),
        })
        assert response.status_code == 201
        event_id = response.json()["id"]

        assert client.get("/api/clinicalevent").json()[0]["id"] == event_id
        patched = client.patch(f"/api/clinicalevent/{event_id}",
                               {"code": "4548-9"}, content_type="application/json")
        assert patched.status_code == 200
        assert patched.json()["code"] == "4548-9"
        assert client.delete(f"/api/clinicalevent/{event_id}").status_code == 204

    def test_guideline_list(self, client, db):
        make_guideline()
        assert len(client.get("/api/clinicalguideline").json()) == 1
