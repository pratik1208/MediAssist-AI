"""check_stalled_referrals — FR-F9, run manually for now.

Flags every referral incomplete past the threshold (default 14 days),
moves it to status "stalled", and raises a care-coordinator escalation
alert for each one. A scheduled job (Railway/Render cron or
django-crontab) replaces this manual invocation in Phase 7.
"""

from django.core.management.base import BaseCommand

from referrals import services


class Command(BaseCommand):
    help = "Flag referrals incomplete past the stalled threshold and alert care coordinators."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days", type=int, default=services.STALLED_THRESHOLD_DAYS,
            help=f"Threshold in days (default: {services.STALLED_THRESHOLD_DAYS}).",
        )

    def handle(self, *args, **options):
        flagged = services.check_stalled_referrals(threshold_days=options["days"])
        if not flagged:
            self.stdout.write("no stalled referrals found")
            return
        for referral in flagged:
            self.stdout.write(
                f"stalled: referral #{referral.id} — {referral.patient.first_name} "
                f"{referral.patient.last_name} ({referral.specialty_needed})"
            )
        self.stdout.write(self.style.SUCCESS(f"{len(flagged)} referral(s) flagged as stalled"))
