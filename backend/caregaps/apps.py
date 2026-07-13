from django.apps import AppConfig


class CaregapsConfig(AppConfig):
    name = 'caregaps'

    def ready(self):
        # Register event subscribers on startup (SPEC_Core §4.2), same
        # pattern as scheduling/referrals: imports live inside ready().
        from core.events import subscribe

        @subscribe("outreach.member_booked")
        def _plan_moves_forward_on_booking(patient_id, appointment_id=None, **_):
            """A patient replied "book" to outreach and Agent 1 scheduled the
            visit (FR-G6). Their care plan advances sent/accepted ->
            in_progress and its gaps move outreach -> scheduled. Patient-
            level on purpose: whichever campaign carried the reply, the
            clinical state is the same."""
            from caregaps.models import CareGap, CarePlan

            plans = CarePlan.objects.filter(
                patient_id=patient_id, status__in=("sent", "accepted"))
            for plan in plans:
                plan.gaps.filter(status="outreach").update(status="scheduled")
                plan.status = "in_progress"
                plan.save(update_fields=["status"])
            # gaps in outreach outside any plan (defensive) advance too
            CareGap.objects.filter(
                patient_id=patient_id, status="outreach").update(status="scheduled")

        @subscribe("appointment.completed")
        def _completion_detection(patient_id, **_):
            """FR-G8: the visit happened. Scheduled gaps advance to
            "completed" (done, pending evidence); then a rescan closes
            anything whose ClinicalEvent evidence has already landed."""
            from caregaps.models import CareGap
            from caregaps.services import scan_patient
            from core.models import Patient

            CareGap.objects.filter(
                patient_id=patient_id, status="scheduled").update(status="completed")
            patient = Patient.objects.filter(id=patient_id).first()
            if patient is not None:
                scan_patient(patient)
