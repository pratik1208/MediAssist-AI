from django.apps import AppConfig


class SchedulingConfig(AppConfig):
    name = "scheduling"

    def ready(self):
        # Register event subscribers on startup (SPEC_Core §4.2).
        # Imports are inside ready() to avoid touching models/apps too early.
        from core.events import subscribe
        from core.models import Patient
        from core.notifications import notify

        @subscribe("appointment.booked")
        def _send_booking_confirmation(patient_id, doctor_name=None, start=None, **_):
            """Send the patient a confirmation when an appointment is booked."""
            patient = Patient.objects.filter(id=patient_id).first()
            if patient:
                notify(
                    patient,
                    "appointment_booked",
                    {"name": patient.first_name, "doctor": doctor_name, "start": start},
                )

        @subscribe("registration.completed")
        def _offer_booking_after_registration(patient_id, **_):
            """Registration finished -> invite the patient to book (PRD journey 4-5)."""
            patient = Patient.objects.filter(id=patient_id).first()
            if patient:
                notify(patient, "registration_complete", {"name": patient.first_name})

        @subscribe("appointment.cancelled")
        def _send_cancellation_notice(patient_id, start=None, **_):
            """Let the patient know when their appointment is cancelled."""
            patient = Patient.objects.filter(id=patient_id).first()
            if patient:
                notify(
                    patient,
                    "appointment_cancelled",
                    {"name": patient.first_name, "start": start},
                )

        @subscribe("triage.disposition")
        def _offer_booking_after_triage(patient_id, route_to=None,
                                        disposition=None, **_):
            """Triage routed the patient here -> invite booking with the
            right urgency (FR-T7 meets FR-S2/S3)."""
            if route_to != "scheduling":
                return
            patient = Patient.objects.filter(id=patient_id).first()
            if patient:
                notify(patient, "triage_booking_offer", {
                    "name": patient.first_name,
                    "urgency": {"same_day": "today",
                                "24_48h": "within the next 24-48 hours",
                                "routine": "at a convenient time"}.get(disposition, "soon"),
                })

        @subscribe("refill.visit_required")
        def _offer_booking_for_refill_visit(patient_id, medication=None, **_):
            """The physician wants a visit before refilling -> offer booking
            (FR-M6 -> Agent 1)."""
            patient = Patient.objects.filter(id=patient_id).first()
            if patient:
                notify(patient, "refill_visit_booking_offer", {
                    "name": patient.first_name,
                    "medication": medication or "your medication",
                })

        @subscribe("priorauth.approved")
        def _offer_booking_after_priorauth_approval(patient_id, treatment=None, **_):
            """Insurance approved the treatment -> invite booking (FR-P7
            "hand off to Scheduling"). Same offer-not-auto-book pattern as
            the other two handoffs above: priorauth doesn't know which
            doctor/slot fits an arbitrary approved treatment, so inviting
            the patient into the existing booking chat is the consistent,
            correct handoff — not a silently auto-created appointment."""
            patient = Patient.objects.filter(id=patient_id).first()
            if patient:
                notify(patient, "priorauth_booking_offer", {
                    "name": patient.first_name,
                    "treatment": treatment or "your approved treatment",
                })
