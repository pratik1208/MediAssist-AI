"""push_care_plans — FR-G5, the outreach leg of the care-gap pipeline.

Bundles every patient with open gaps into a care plan, then pushes all
draft plans into the dedicated Agent 7 campaign ("Care plan follow-up") and
dispatches the first wave. Same "run now, cron later" pattern as
scan_care_gaps; the intended nightly order (Phase 7) is:

    manage.py scan_care_gaps --recycle   # detect + recycle stale plans
    manage.py push_care_plans            # bundle + send

Safe to run repeatedly: already-sent plans aren't re-sent, opted-out
patients are never enrolled, and wave escalation is date-driven.
"""

from django.core.management.base import BaseCommand

from caregaps import services


class Command(BaseCommand):
    help = "Bundle open gaps into care plans and push them into the outreach campaign."

    def handle(self, *args, **options):
        bundled = services.bundle_all()
        self.stdout.write(f"bundled care plans for {bundled} patient(s)")
        result = services.push_plans_to_outreach()
        if result.get("paused"):
            self.stdout.write(self.style.WARNING(
                "care-gap campaign is paused — plans left in draft"))
            return
        self.stdout.write(
            f"pushed {result['sent']} plan(s) into campaign "
            f"#{result['campaign_id']} ({result['skipped_opted_out']} opted out); "
            f"wave: {result['wave']['queued']} queued, "
            f"{result['wave']['unreachable']} unreachable"
        )
        self.stdout.write(self.style.SUCCESS("care plan outreach push complete"))
