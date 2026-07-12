from django.apps import AppConfig


class PriorauthConfig(AppConfig):
    name = 'priorauth'

    def ready(self):
        # Register event subscribers on startup (SPEC_Core §4.2).
        from core.events import subscribe

        @subscribe("priorauth.needed")
        def _detect_from_referral_acceptance(referral_id, patient_id, specialty_needed=None,
                                             specialist_id=None, **_):
            """Phase 6 handoff: referrals.services.accept_referral() emits
            this the moment a referral is accepted (ORCHESTRATION §3) —
            react by opening a treatment order for the specialist visit and
            running detection (FR-P1) immediately, rather than waiting for
            someone to remember to check.

            Honest limitation: a referral carries no CPT/ICD-10 code (only
            a specialty and a free-text reason), so detect_authorization_
            requirement() will usually report "not required" here until the
            specialist's office names an actual procedure — this still puts
            a linked, re-checkable order in the system the moment the
            referral is accepted, which is the real point of the handoff.
            """
            from core.models import Patient
            from priorauth import services
            from priorauth.models import TreatmentOrder
            from referrals.models import Referral

            patient = Patient.objects.filter(id=patient_id).first()
            referral = Referral.objects.filter(id=referral_id).first()
            if patient is None or referral is None:
                return
            order = TreatmentOrder.objects.create(
                patient=patient, ordering_doctor=referral.referring_doctor,
                order_type="procedure", referral=referral,
            )
            services.initiate_authorization(order)

        @subscribe("triage.disposition")
        def _detect_from_triage_disposition(patient_id, assessment_id=None,
                                            route_to=None, **_):
            """FR-T7: "Prior Authorization (diagnostics requiring approval)"
            is one of triage's five named downstream routes
            (triage/services.py ROUTE_FOR_HINT["diagnostics"]) — ordering a
            treatment during triage disposition also triggers detection
            directly, the same way a specialist hint hands off to
            referrals. Same honest limitation as above: no real procedure
            code is known from a triage assessment alone.
            """
            if route_to != "priorauth":
                return
            from core.models import Patient
            from priorauth import services
            from priorauth.models import TreatmentOrder
            from triage.models import TriageAssessment

            patient = Patient.objects.filter(id=patient_id).first()
            assessment = TriageAssessment.objects.filter(id=assessment_id).first()
            if patient is None or assessment is None:
                return
            order = TreatmentOrder.objects.create(patient=patient, order_type="imaging")
            services.initiate_authorization(order)
