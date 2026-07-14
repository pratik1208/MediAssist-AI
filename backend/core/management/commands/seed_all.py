"""seed_all — one-command clinic bootstrap.

Runs every seed in dependency order (doctors + patients before the rows that
reference them, payer rules before anything that matches against them). Every
underlying seed is idempotent, so this is safe to re-run.

Two layers: REFERENCE data (patients, doctors, appointments, insurance,
prescriptions, specialists, payer rules, protocols, campaigns, guidelines,
knowledge base) establishes the roster; WORKFLOW-STATE data (clinical
events, care gaps/plans, triage assessments, referrals, prior-auth
requests, refill requests, an outreach launch, staff tasks) drives real
records through every meaningful status via each app's own service layer,
so every staff queue has something real to click into on a fresh clinic
instead of sitting empty.

    ./venv/bin/python manage.py seed_all
"""

from django.core.management import call_command
from django.core.management.base import BaseCommand

# In dependency order.
SEEDS = [
    # -- reference data --------------------------------------------------------
    "seed_doctors",         # core.Doctor
    "seed_patients",        # core.Patient (roster)
    "seed_appointments",    # scheduling.Appointment history (needs doctors + patients)
    "seed_insurance",       # registration.InsurancePolicy/IntakeSummary (needs patients)
    "seed_prescriptions",   # refills.Pharmacy/Prescription (needs patients + doctors)
    "seed_specialists",     # referrals.Specialist
    "seed_payer_rules",     # priorauth.PayerRule
    "seed_protocols",       # triage.ClinicalProtocol
    "seed_campaigns",       # outreach.Campaign demo drafts
    "seed_guidelines",      # caregaps.ClinicalGuideline
    # -- workflow-state data ----------------------------------------------------
    "seed_clinical_events", # caregaps.ClinicalEvent — diabetic cohort (needs patients)
    "scan_care_gaps",       # caregaps.CareGap — real detection (needs guidelines + events)
    "seed_care_plans",      # caregaps.CarePlan at draft/sent/recycled (needs open gaps)
    "seed_knowledge",       # frontdesk.KnowledgeArticle (FAQ corpus)
    "seed_assessments",     # triage.TriageAssessment + EscalationAlert (needs patients + protocols;
                             # also fans out into referrals/priorauth via triage.disposition)
    "seed_referral_pipeline",   # referrals.Referral across every lifecycle stage
    "seed_priorauth_pipeline",  # priorauth.TreatmentOrder/AuthorizationRequest across every status
    "seed_refill_pipeline",     # refills.RefillRequest across every status
    "seed_outreach_launch",     # outreach.CampaignMember — launches one demo campaign with replies
    "seed_staff_tasks",         # frontdesk.StaffTask across every category/status
]


class Command(BaseCommand):
    help = "Seed the whole clinic (all seed commands, in dependency order)."

    def handle(self, *args, **options):
        for name in SEEDS:
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n=== {name} ==="))
            call_command(name)
        self.stdout.write(self.style.SUCCESS("\nseed_all complete — clinic bootstrapped."))
