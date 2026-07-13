"""seed_all — one-command clinic bootstrap.

Runs every seed in dependency order (doctors + patients before the rows that
reference them, payer rules before anything that matches against them). Every
underlying seed is idempotent, so this is safe to re-run.

    ./venv/bin/python manage.py seed_all
"""

from django.core.management import call_command
from django.core.management.base import BaseCommand

# In dependency order.
SEEDS = [
    "seed_doctors",       # core.Doctor
    "seed_patients",      # core.Patient (roster)
    "seed_appointments",  # scheduling.Appointment history (needs doctors + patients)
    "seed_insurance",     # registration.InsurancePolicy/IntakeSummary (needs patients)
    "seed_prescriptions", # refills.Pharmacy/Prescription (needs patients + doctors)
    "seed_specialists",   # referrals.Specialist
    "seed_payer_rules",   # priorauth.PayerRule
    "seed_protocols",     # triage.ClinicalProtocol
    "seed_campaigns",     # outreach.Campaign demo drafts
    "seed_guidelines",    # caregaps.ClinicalGuideline
    "seed_knowledge",     # frontdesk.KnowledgeArticle (FAQ corpus)
]


class Command(BaseCommand):
    help = "Seed the whole clinic (all seed commands, in dependency order)."

    def handle(self, *args, **options):
        for name in SEEDS:
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n=== {name} ==="))
            call_command(name)
        self.stdout.write(self.style.SUCCESS("\nseed_all complete — clinic bootstrapped."))
