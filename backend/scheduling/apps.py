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
