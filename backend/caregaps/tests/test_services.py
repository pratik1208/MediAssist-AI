"""Phase 2 service tests: the scanner truth table per timing model, the
no-duplicate rule, prioritization, bundling, close-on-evidence, the recycle
loop, and the build_cohort clinical-key extension the guidelines rely on."""

import datetime

import pytest
from django.core.management import call_command
from django.utils import timezone

from caregaps import services
from caregaps.models import CareGap, CarePlan, ClinicalEvent, ClinicalGuideline
from core.models import AuditEvent, Patient
from outreach.services import UnsupportedCriteriaError, build_cohort

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()


def make_patient(first="Asha", last="Rao", phone="9000000001", age=70, **extra):
    dob = datetime.date(TODAY.year - age, 1, 15)
    return Patient.objects.create(
        first_name=first, last_name=last, contact_number=phone, dob=dob,
        registration_status="complete", **extra,
    )


def make_event(patient, code, days_ago, event_type="lab", value=None):
    occurred = timezone.now() - datetime.timedelta(days=days_ago)
    return ClinicalEvent.objects.create(
        patient=patient, event_type=event_type, code=code,
        value=value or {}, occurred_at=occurred,
    )


def make_guideline(name="HbA1c", criteria=None, item_type="test", code="4548-4",
                   frequency_days=182, risk_tier="high", **extra):
    return ClinicalGuideline.objects.create(
        name=name, population_criteria=criteria or {}, care_item_type=item_type,
        care_item_code=code, frequency_days=frequency_days, risk_tier=risk_tier, **extra,
    )


# -- build_cohort extension (the shared criteria schema gains clinical keys) ----

class TestClinicalCriteriaKeys:
    def test_has_diagnosis_code_matches_only_diagnosed(self):
        diabetic = make_patient(phone="9000000001")
        healthy = make_patient(first="Ravi", phone="9000000002")
        make_event(diabetic, "E11", days_ago=400, event_type="diagnosis")

        result = set(build_cohort({"has_diagnosis_code": "E11"}).values_list("id", flat=True))
        assert result == {diabetic.id}
        assert healthy.id not in result

    def test_has_diagnosis_code_ignores_non_diagnosis_events(self):
        patient = make_patient()
        make_event(patient, "E11", days_ago=10, event_type="lab")  # right code, wrong type
        assert build_cohort({"has_diagnosis_code": "E11"}).count() == 0

    def test_has_event_code_matches_any_event_type(self):
        discharged = make_patient(phone="9000000003")
        make_event(discharged, "99238", days_ago=5, event_type="procedure")
        result = set(build_cohort({"has_event_code": "99238"}).values_list("id", flat=True))
        assert result == {discharged.id}

    def test_many_matching_events_still_one_row(self):
        patient = make_patient()
        for days in (10, 20, 30):
            make_event(patient, "E11", days_ago=days, event_type="diagnosis")
        assert build_cohort({"has_diagnosis_code": "E11"}).count() == 1

    def test_unsupported_key_still_raises(self):
        with pytest.raises(UnsupportedCriteriaError):
            build_cohort({"hba1c_gt": 8})


# -- scanner truth table: periodic guidelines -----------------------------------

class TestScanPatientPeriodic:
    def test_out_of_population_no_gap(self):
        young = make_patient(age=30)
        make_guideline(name="Flu 65+", criteria={"age_min": 65}, item_type="vaccination",
                       code="140", frequency_days=365)
        result = services.scan_patient(young)
        assert result == {"opened": 0, "refreshed": 0, "closed": 0}
        assert CareGap.objects.count() == 0

    def test_never_done_opens_gap_due_today(self):
        senior = make_patient(age=70)
        guideline = make_guideline(name="Flu 65+", criteria={"age_min": 65},
                                   item_type="vaccination", code="140", frequency_days=365)
        result = services.scan_patient(senior)
        assert result["opened"] == 1
        gap = CareGap.objects.get(patient=senior, guideline=guideline)
        assert gap.status == "open"
        assert gap.due_since == TODAY

    def test_done_recently_no_gap(self):
        senior = make_patient(age=70)
        make_guideline(criteria={"age_min": 65}, code="140",
                       item_type="vaccination", frequency_days=365)
        make_event(senior, "140", days_ago=100, event_type="vaccination")
        assert services.scan_patient(senior)["opened"] == 0
        assert CareGap.objects.count() == 0

    def test_boundary_day_still_satisfied(self):
        """'Every 182 days' means the event aged exactly 182 days still
        counts; day 183 is the first overdue day."""
        patient = make_patient(age=70)
        make_guideline(criteria={"age_min": 65}, code="4548-4", frequency_days=182)
        make_event(patient, "4548-4", days_ago=182)
        assert services.scan_patient(patient)["opened"] == 0

    def test_one_day_past_boundary_opens_gap_with_correct_due_since(self):
        patient = make_patient(age=70)
        guideline = make_guideline(criteria={"age_min": 65}, code="4548-4", frequency_days=182)
        make_event(patient, "4548-4", days_ago=183)
        assert services.scan_patient(patient)["opened"] == 1
        gap = CareGap.objects.get()
        # overdue since (event date + frequency) = yesterday
        assert gap.due_since == TODAY - datetime.timedelta(days=1)
        assert gap.guideline == guideline

    def test_inactive_guideline_is_skipped(self):
        patient = make_patient(age=70)
        make_guideline(criteria={"age_min": 65}, code="4548-4", is_active=False)
        assert services.scan_patient(patient)["opened"] == 0

    def test_rescan_never_duplicates(self):
        patient = make_patient(age=70)
        make_guideline(criteria={"age_min": 65}, code="4548-4")
        services.scan_patient(patient)
        result = services.scan_patient(patient)
        assert result == {"opened": 0, "refreshed": 0, "closed": 0}
        assert CareGap.objects.count() == 1

    def test_rescan_refreshes_due_since_on_newer_stale_event(self):
        patient = make_patient(age=70)
        make_guideline(criteria={"age_min": 65}, code="4548-4", frequency_days=182)
        make_event(patient, "4548-4", days_ago=400)
        services.scan_patient(patient)
        old_due = CareGap.objects.get().due_since

        make_event(patient, "4548-4", days_ago=200)  # newer but still too old
        result = services.scan_patient(patient)
        assert result["refreshed"] == 1
        assert CareGap.objects.get().due_since == TODAY - datetime.timedelta(days=200 - 182)
        assert CareGap.objects.get().due_since != old_due

    def test_never_done_due_since_does_not_slide_on_rescan(self):
        """A never-done gap ages from its detection date. If rescans
        re-anchored due_since to 'today', these gaps would look 0 days
        overdue forever and never rise in the priority list."""
        patient = make_patient(age=70)
        make_guideline(criteria={"age_min": 65}, code="4548-4")
        services.scan_patient(patient)
        gap = CareGap.objects.get()
        # simulate the gap having been detected 10 days ago
        detected = TODAY - datetime.timedelta(days=10)
        CareGap.objects.filter(id=gap.id).update(due_since=detected)

        result = services.scan_patient(patient)
        assert result["refreshed"] == 0
        gap.refresh_from_db()
        assert gap.due_since == detected

    def test_rescan_closes_gap_when_evidence_appears(self):
        patient = make_patient(age=70)
        make_guideline(criteria={"age_min": 65}, code="4548-4", frequency_days=182)
        services.scan_patient(patient)
        gap = CareGap.objects.get()
        assert gap.status == "open"

        evidence = make_event(patient, "4548-4", days_ago=1, value={"hba1c": 6.9})
        result = services.scan_patient(patient)
        assert result["closed"] == 1
        gap.refresh_from_db()
        assert gap.status == "closed"
        assert gap.closing_event == evidence
        assert gap.closed_at is not None

    def test_left_population_keeps_live_gap(self):
        """Silently discarding a detected gap is a clinical call — the
        scanner leaves gaps of patients who left the population."""
        patient = make_patient(age=70)
        guideline = make_guideline(criteria={"age_min": 65}, code="4548-4")
        services.scan_patient(patient)
        guideline.population_criteria = {"age_min": 90}
        guideline.save()
        services.scan_patient(patient)
        assert CareGap.objects.get().status == "open"


# -- scanner truth table: anchored follow-up ------------------------------------

class TestScanPatientFollowup:
    def _guideline(self):
        return make_guideline(
            name="Post-discharge follow-up", criteria={"has_event_code": "99238"},
            item_type="followup", code="99495", frequency_days=14, risk_tier="high",
        )

    def test_within_window_not_due_yet(self):
        patient = make_patient()
        self._guideline()
        make_event(patient, "99238", days_ago=5, event_type="procedure")
        assert services.scan_patient(patient)["opened"] == 0

    def test_past_window_without_followup_opens_gap(self):
        patient = make_patient()
        self._guideline()
        make_event(patient, "99238", days_ago=20, event_type="procedure")
        assert services.scan_patient(patient)["opened"] == 1
        gap = CareGap.objects.get()
        assert gap.due_since == TODAY - datetime.timedelta(days=20 - 14)

    def test_followup_after_discharge_satisfies(self):
        patient = make_patient()
        self._guideline()
        make_event(patient, "99238", days_ago=20, event_type="procedure")
        make_event(patient, "99495", days_ago=10, event_type="visit")
        assert services.scan_patient(patient)["opened"] == 0
        assert CareGap.objects.count() == 0

    def test_followup_from_previous_discharge_does_not_satisfy_new_one(self):
        patient = make_patient()
        self._guideline()
        make_event(patient, "99238", days_ago=100, event_type="procedure")  # old discharge
        make_event(patient, "99495", days_ago=95, event_type="visit")       # its follow-up
        make_event(patient, "99238", days_ago=30, event_type="procedure")   # NEW discharge
        assert services.scan_patient(patient)["opened"] == 1

    def test_new_followup_closes_open_gap(self):
        patient = make_patient()
        self._guideline()
        make_event(patient, "99238", days_ago=20, event_type="procedure")
        services.scan_patient(patient)
        assert CareGap.objects.get().status == "open"

        evidence = make_event(patient, "99495", days_ago=0, event_type="visit")
        assert services.scan_patient(patient)["closed"] == 1
        gap = CareGap.objects.get()
        assert gap.status == "closed"
        assert gap.closing_event == evidence


# -- scan_all --------------------------------------------------------------------

class TestScanAll:
    def test_scans_across_patients_and_is_idempotent(self):
        overdue_senior = make_patient(phone="9000000011", age=70)
        current_senior = make_patient(first="Ravi", phone="9000000012", age=68)
        young = make_patient(first="Nita", phone="9000000013", age=30)
        make_guideline(name="Flu 65+", criteria={"age_min": 65}, item_type="vaccination",
                       code="140", frequency_days=365, risk_tier="medium")
        make_event(current_senior, "140", days_ago=30, event_type="vaccination")

        totals = services.scan_all()
        assert totals["opened"] == 1
        assert CareGap.objects.filter(patient=overdue_senior).count() == 1
        assert CareGap.objects.filter(patient=current_senior).count() == 0
        assert CareGap.objects.filter(patient=young).count() == 0

        # second pass: nothing new, nothing duplicated
        totals = services.scan_all()
        assert totals["opened"] == 0
        assert CareGap.objects.count() == 1

    def test_satisfied_patients_are_not_candidates(self):
        """The set-based prefilter: a patient with a recent event and no
        live gap is never even evaluated."""
        current = make_patient(age=70)
        make_guideline(criteria={"age_min": 65}, code="140",
                       item_type="vaccination", frequency_days=365)
        make_event(current, "140", days_ago=10, event_type="vaccination")
        assert services.scan_all()["patients_scanned"] == 0

    def test_management_command_runs(self, capsys):
        make_patient(age=70)
        make_guideline(criteria={"age_min": 65}, code="140",
                       item_type="vaccination", frequency_days=365)
        call_command("scan_care_gaps", "--recycle")
        out = capsys.readouterr().out
        assert "1 gaps opened" in out
        assert "recycled 0" in out
        assert "care gap scan complete" in out


# -- prioritize ------------------------------------------------------------------

class TestPrioritize:
    def test_orders_by_risk_tier_then_overdue_duration(self):
        p1, p2, p3, p4 = [make_patient(phone=f"900000002{i}", age=70) for i in range(4)]
        high = make_guideline(name="high rule", criteria={}, code="A", risk_tier="high")
        medium = make_guideline(name="medium rule", criteria={}, code="B", risk_tier="medium")
        low = make_guideline(name="low rule", criteria={}, code="C", risk_tier="low")

        recent_high = CareGap.objects.create(
            patient=p1, guideline=high, due_since=TODAY - datetime.timedelta(days=5))
        old_high = CareGap.objects.create(
            patient=p2, guideline=high, due_since=TODAY - datetime.timedelta(days=90))
        old_low = CareGap.objects.create(
            patient=p3, guideline=low, due_since=TODAY - datetime.timedelta(days=400))
        old_medium = CareGap.objects.create(
            patient=p4, guideline=medium, due_since=TODAY - datetime.timedelta(days=200))

        assert list(services.prioritize()) == [old_high, recent_high, old_medium, old_low]

    def test_only_requested_statuses(self):
        patient = make_patient(age=70)
        guideline = make_guideline(criteria={}, code="A")
        gap = CareGap.objects.create(patient=patient, guideline=guideline, due_since=TODAY)
        gap.status = "outreach"
        gap.save()
        assert list(services.prioritize()) == []
        assert list(services.prioritize(statuses=("open", "outreach"))) == [gap]


# -- bundling --------------------------------------------------------------------

class TestBundleCarePlan:
    def test_no_open_gaps_returns_none(self):
        assert services.bundle_care_plan(make_patient()) is None

    def test_bundles_and_marks_shareable_vs_separate(self):
        patient = make_patient(age=70)
        lab = make_guideline(name="HbA1c", criteria={}, item_type="test", code="4548-4")
        vaccine = make_guideline(name="Flu vaccine", criteria={}, item_type="vaccination", code="140")
        screening = make_guideline(name="Mammogram", criteria={}, item_type="screening", code="77067")
        gaps = [CareGap.objects.create(patient=patient, guideline=g, due_since=TODAY)
                for g in (lab, vaccine, screening)]

        plan = services.bundle_care_plan(patient)
        assert plan.status == "draft"
        assert set(plan.gaps.all()) == set(gaps)
        assert "single visit: HbA1c, Flu vaccine." in plan.plan_text
        assert "own appointment: Mammogram." in plan.plan_text

        breakdown = services.bundle_breakdown(plan.gaps.select_related("guideline"))
        assert {g.guideline.name for g in breakdown["shared_visit"]} == {"HbA1c", "Flu vaccine"}
        assert {g.guideline.name for g in breakdown["separate"]} == {"Mammogram"}

    def test_reuses_active_plan_and_adds_new_gaps(self):
        patient = make_patient(age=70)
        first = make_guideline(name="HbA1c", criteria={}, item_type="test", code="4548-4")
        CareGap.objects.create(patient=patient, guideline=first, due_since=TODAY)
        plan = services.bundle_care_plan(patient)

        second = make_guideline(name="Flu vaccine", criteria={}, item_type="vaccination", code="140")
        CareGap.objects.create(patient=patient, guideline=second, due_since=TODAY)
        again = services.bundle_care_plan(patient)

        assert again.id == plan.id
        assert CarePlan.objects.count() == 1
        assert again.gaps.count() == 2

    def test_completed_plan_is_not_reused(self):
        patient = make_patient(age=70)
        guideline = make_guideline(criteria={}, code="4548-4")
        gap = CareGap.objects.create(patient=patient, guideline=guideline, due_since=TODAY)
        plan = services.bundle_care_plan(patient)
        services.close_gap(gap)
        plan.refresh_from_db()
        assert plan.status == "completed"

        # a NEW cycle opens a fresh gap -> a fresh plan
        CareGap.objects.create(patient=patient, guideline=guideline, due_since=TODAY)
        new_plan = services.bundle_care_plan(patient)
        assert new_plan.id != plan.id


# -- close on evidence -----------------------------------------------------------

class TestCloseGap:
    def test_close_sets_evidence_and_audits(self):
        patient = make_patient(age=70)
        guideline = make_guideline(criteria={}, code="4548-4")
        gap = CareGap.objects.create(patient=patient, guideline=guideline, due_since=TODAY)
        evidence = make_event(patient, "4548-4", days_ago=0, value={"hba1c": 6.5})

        services.close_gap(gap, evidence)
        gap.refresh_from_db()
        assert gap.status == "closed"
        assert gap.closing_event == evidence
        assert gap.closed_at is not None
        audit = AuditEvent.objects.get(action="caregaps.gap_closed")
        assert audit.payload["closing_event_id"] == evidence.id

    def test_plan_completes_only_when_all_gaps_closed(self):
        patient = make_patient(age=70)
        g1 = make_guideline(name="A", criteria={}, code="A")
        g2 = make_guideline(name="B", criteria={}, code="B")
        gap1 = CareGap.objects.create(patient=patient, guideline=g1, due_since=TODAY)
        gap2 = CareGap.objects.create(patient=patient, guideline=g2, due_since=TODAY)
        plan = services.bundle_care_plan(patient)

        services.close_gap(gap1)
        plan.refresh_from_db()
        assert plan.status == "draft"  # one gap still live

        services.close_gap(gap2)
        plan.refresh_from_db()
        assert plan.status == "completed"


# -- recycle loop (Edge Case 17) --------------------------------------------------

class TestRecycleIncomplete:
    def _stale_plan(self, patient, gap, status="sent", days_old=45):
        plan = services.bundle_care_plan(patient)
        plan.status = status
        plan.save()
        CarePlan.objects.filter(id=plan.id).update(
            created_at=timezone.now() - datetime.timedelta(days=days_old))
        return plan

    def test_stale_plan_with_live_gaps_recycles_and_reopens(self):
        patient = make_patient(age=70)
        guideline = make_guideline(criteria={}, code="4548-4")
        gap = CareGap.objects.create(patient=patient, guideline=guideline, due_since=TODAY)
        plan = self._stale_plan(patient, gap)
        # the gap then entered the outreach workflow before the plan went stale
        gap.status = "outreach"
        gap.save()

        recycled = services.recycle_incomplete()
        assert [p.id for p in recycled] == [plan.id]
        plan.refresh_from_db()
        gap.refresh_from_db()
        assert plan.status == "recycled"
        assert gap.status == "open"
        assert AuditEvent.objects.filter(action="caregaps.plan_recycled").exists()

    def test_recent_plan_untouched(self):
        patient = make_patient(age=70)
        guideline = make_guideline(criteria={}, code="4548-4")
        CareGap.objects.create(patient=patient, guideline=guideline, due_since=TODAY)
        plan = services.bundle_care_plan(patient)
        plan.status = "sent"
        plan.save()

        assert services.recycle_incomplete() == []
        plan.refresh_from_db()
        assert plan.status == "sent"

    def test_stale_plan_with_all_gaps_closed_completes_instead(self):
        patient = make_patient(age=70)
        guideline = make_guideline(criteria={}, code="4548-4")
        gap = CareGap.objects.create(patient=patient, guideline=guideline, due_since=TODAY)
        plan = self._stale_plan(patient, gap)
        services.close_gap(gap)
        plan.refresh_from_db()
        if plan.status == "completed":
            # close_gap already completed it; force back to a pending state
            # aged past the window to exercise recycle's own completion path.
            CarePlan.objects.filter(id=plan.id).update(status="sent")

        assert services.recycle_incomplete() == []
        plan.refresh_from_db()
        assert plan.status == "completed"

    def test_draft_plans_are_not_recycled(self):
        patient = make_patient(age=70)
        guideline = make_guideline(criteria={}, code="4548-4")
        CareGap.objects.create(patient=patient, guideline=guideline, due_since=TODAY)
        plan = services.bundle_care_plan(patient)  # stays draft
        CarePlan.objects.filter(id=plan.id).update(
            created_at=timezone.now() - datetime.timedelta(days=100))
        assert services.recycle_incomplete() == []
