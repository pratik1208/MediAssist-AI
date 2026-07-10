from django.apps import AppConfig


class TriageConfig(AppConfig):
    name = 'triage'

    def ready(self):
        # Register event subscribers on startup (SPEC_Core §4.2).
        from core.events import subscribe

        @subscribe("registration.completed")
        def _start_assessment_from_intake(patient_id, **_):
            """PRD primary journey: symptoms reported during registration
            pre-load a triage assessment — the patient never repeats them.

            Red-flag symptoms escalate immediately; otherwise a pending
            assessment (protocol already selected, symptoms recorded) waits
            for the patient's first triage answer.
            """
            from core.models import Conversation, Patient
            from registration.models import IntakeSummary
            from triage import services
            from triage.models import TriageAssessment

            patient = Patient.objects.filter(id=patient_id).first()
            if patient is None:
                return
            intake = IntakeSummary.objects.filter(patient=patient).order_by("-id").first()
            symptoms = (intake.clinical_profile if intake else {}).get("symptoms") or []
            if not symptoms:
                return  # nothing reported; nothing to hand off
            if TriageAssessment.objects.filter(patient=patient,
                                               status="pending").exists():
                return  # an open assessment already exists

            conversation = (Conversation.objects.filter(patient=patient)
                            .order_by("-id").first())
            if conversation is None:
                return

            symptoms_text = ", ".join(symptoms)
            assessment = TriageAssessment.objects.create(
                patient=patient,
                conversation=conversation,
                clinical_protocol=services.select_protocol(symptoms_text),
                reported_symptoms={"text": symptoms_text, "answers": [],
                                   "source": "registration_intake"},
                acuity="minimal", disposition="self_care", summary_text="",
            )
            # Same safety order as everywhere else: deterministic screen first.
            if services.red_flag_check(symptoms_text):
                services.escalate(assessment)
