"""seed_payer_rules — load starter PayerRule rows (Agent 6, Phase 1).

Rules are configurable DATA, not code (matches triage's ClinicalProtocol and
referrals' Specialist philosophy) — detect_authorization_requirement()
(Phase 2) matches a TreatmentOrder against these. A mix of requires_auth
True/False across payers, plans, and order types so that matching logic has
real branching to exercise: some procedures need auth on one payer's plan
but not another's, generic medications never do, imaging/high-cost
procedures usually do. Idempotent — matches on (payer_name, plan,
cpt_pattern, icd10_pattern, medication_pattern), like the other seed
commands match on their own natural key.
"""

from django.core.management.base import BaseCommand

from priorauth.models import PayerRule

RULES = [
    # -- imaging: usually needs auth, especially on tighter plans ------------
    {"payer_name": "BlueShield", "plan": "Premium PPO",
     "cpt_pattern": "7055[1-3]",  # MRI brain w/wo contrast
     "network_requirement": "in_network", "requires_auth": True,
     "submission_channel": "epa",
     "required_documentation": ["diagnosis", "physician_notes", "imaging_reports"]},
    {"payer_name": "BlueShield", "plan": "Basic HMO",
     "cpt_pattern": "7372[1-3]",  # MRI knee w/wo contrast
     "network_requirement": "in_network", "requires_auth": True,
     "submission_channel": "portal",
     "required_documentation": ["diagnosis", "physician_notes", "prior_treatments"]},
    {"payer_name": "Star Health", "plan": None,
     "cpt_pattern": "7417[6-8]",  # CT abdomen w/wo contrast
     "network_requirement": "any", "requires_auth": True,
     "submission_channel": "portal",
     "required_documentation": ["diagnosis", "physician_notes", "labs"]},

    # -- high-cost procedures -------------------------------------------------
    {"payer_name": "Apollo Munich", "plan": None,
     "cpt_pattern": "27447",  # total knee arthroplasty
     "network_requirement": "in_network", "requires_auth": True,
     "submission_channel": "fax",
     "required_documentation": ["diagnosis", "physician_notes", "imaging_reports",
                                "prior_treatments"]},
    {"payer_name": "HDFC Ergo", "plan": None,
     "icd10_pattern": "G47.33",  # obstructive sleep apnea -> CPAP device
     "requires_auth": True, "submission_channel": "portal",
     "required_documentation": ["diagnosis", "physician_notes", "labs"]},

    # -- routine, low-cost care: never needs auth -----------------------------
    {"payer_name": "BlueShield", "plan": None,
     "medication_pattern": "atorvastatin|simvastatin|rosuvastatin",  # generic statins
     "requires_auth": False, "submission_channel": "api",
     "required_documentation": []},
    {"payer_name": "Star Health", "plan": None,
     "medication_pattern": "metformin|amlodipine|lisinopril",  # common generics
     "requires_auth": False, "submission_channel": "api",
     "required_documentation": []},
    {"payer_name": "Apollo Munich", "plan": None,
     "cpt_pattern": "99213|99214",  # routine office visit E/M codes
     "requires_auth": False, "submission_channel": "api",
     "required_documentation": []},
]


class Command(BaseCommand):
    help = "Seed the database with sample payer authorization rules (idempotent)."

    def handle(self, *args, **kwargs):
        for spec in RULES:
            key = {k: spec.get(k) for k in
                   ("payer_name", "plan", "cpt_pattern", "icd10_pattern", "medication_pattern")}
            defaults = {k: v for k, v in spec.items() if k not in key}
            rule, created = PayerRule.objects.update_or_create(defaults=defaults, **key)
            self.stdout.write(
                f"{'created' if created else 'updated'}: {rule.payer_name} "
                f"({rule.plan or 'any plan'}) — requires_auth={rule.requires_auth}"
            )
        self.stdout.write(self.style.SUCCESS(f"seeded {len(RULES)} payer rules"))
