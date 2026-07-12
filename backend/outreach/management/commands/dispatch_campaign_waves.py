"""dispatch_campaign_waves — FR-O4/Edge Case 15, the daily scheduled job.

Wave dispatch must NOT be request-triggered (Phase 6): a 5,000-patient
escalation pass is background work, not something a staff click should block
on. This command runs one dispatch pass over every RUNNING campaign —
paused/draft/completed campaigns are skipped — moving each due non-responder
to their next channel. Safe to run repeatedly; dispatch_wave only sends
messages that are actually due, so running it daily is the intended cadence
(a real scheduler/cron calls this; Phase 7 wires that up).
"""

from django.core.management.base import BaseCommand

from outreach import services
from outreach.models import Campaign


class Command(BaseCommand):
    help = "Dispatch the next outreach wave for every running campaign."

    def handle(self, *args, **options):
        running = Campaign.objects.filter(status="running")
        if not running:
            self.stdout.write("no running campaigns")
            return
        total_queued = 0
        total_unreachable = 0
        for campaign in running:
            result = services.dispatch_wave(campaign)
            total_queued += result["queued"]
            total_unreachable += result["unreachable"]
            self.stdout.write(
                f"campaign #{campaign.id} {campaign.name!r}: "
                f"queued {result['queued']}, unreachable {result['unreachable']}"
            )
        self.stdout.write(self.style.SUCCESS(
            f"dispatched across {running.count()} campaign(s): "
            f"{total_queued} queued, {total_unreachable} newly unreachable"
        ))
