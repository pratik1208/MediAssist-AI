from django.apps import AppConfig


class ReferralsConfig(AppConfig):
    name = 'referrals'

    def ready(self):
        # Register event subscribers on startup (SPEC_Core §4.2).
        from core.events import subscribe

        @subscribe("triage.disposition")
        def _draft_referral_from_triage_handoff(patient_id, assessment_id=None,
                                                route_to=None, **_):
            """Phase 6 handoff: triage.route_disposition() already emits
            route_to="referrals" whenever findings.route_hint == "specialist"
            (see triage/services.py ROUTE_FOR_HINT) — react by auto-creating
            a draft referral so the patient never repeats their story. A
            physician still must confirm it (accept_referral) before it can
            proceed to a specialist.
            """
            if route_to != "referrals":
                return
            from core.models import Patient
            from referrals import services
            from triage.models import TriageAssessment

            patient = Patient.objects.filter(id=patient_id).first()
            assessment = TriageAssessment.objects.filter(id=assessment_id).first()
            if patient is None or assessment is None:
                return
            services.create_draft_referral_from_triage(patient, assessment)
