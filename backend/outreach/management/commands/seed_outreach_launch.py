"""seed_outreach_launch — launch one demo campaign with real replies.

seed_campaigns leaves all three demo campaigns in draft on purpose, so a
human can open one, preview the cohort, and launch it themselves. But that
also means CampaignMember is empty on a fresh clinic — the outreach
send/tracking view has nothing to show without launching at least one.

This launches exactly "Flu shot 65+" the same way the real launch endpoint
does (enroll_cohort + dispatch_wave — real CampaignMember and
OutboundMessage rows), then simulates a few realistic replies via
handle_response_action so the funnel shows real variety: one "book" (a
real auto-booked appointment, firing outreach.member_booked), one
"snooze", one "opt_out", the rest left at "contacted" for a tester to
reply to manually. The other two draft campaigns are left untouched, so the
preview -> launch flow is still manually testable from a clean state.

Requires patients and a running/matching cohort to exist; no-ops with a
warning otherwise. Idempotent: no-ops the launch if the campaign isn't in
draft, and each reply is only applied while the member is still at its
pre-reply state.
"""

import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from outreach import services
from outreach.models import Campaign, CampaignMember

CAMPAIGN_NAME = "Flu shot 65+"

# (phone, intent, extra kwargs) -- applied only while the member is still
# "contacted" (i.e. hasn't already been replied to by a prior run).
REPLIES = [
    ("9820010001", "book", {}),                                            # Kamala
    ("9820010002", "snooze", {"snooze_until": timezone.localdate()
                              + datetime.timedelta(days=30)}),              # Ramesh
    ("9820010003", "opt_out", {}),                                         # Gurpreet
]


class Command(BaseCommand):
    help = "Launch one demo outreach campaign with simulated replies (idempotent)."

    def handle(self, *args, **options):
        campaign = Campaign.objects.filter(name=CAMPAIGN_NAME).first()
        if campaign is None:
            self.stdout.write(self.style.WARNING(
                f"campaign {CAMPAIGN_NAME!r} not found — run seed_campaigns first"))
            return

        if campaign.status == "draft":
            campaign.status = "running"
            campaign.launched_at = timezone.now()
            campaign.save(update_fields=["status", "launched_at"])
            enrollment = services.enroll_cohort(campaign)
            wave = services.dispatch_wave(campaign)
            self.stdout.write(
                f"launched {CAMPAIGN_NAME!r}: enrolled {enrollment['enrolled']}, "
                f"wave {wave}")
        else:
            self.stdout.write(f"{CAMPAIGN_NAME!r} already {campaign.status} — skipping launch")

        applied = 0
        for phone, intent, kwargs in REPLIES:
            member = CampaignMember.objects.filter(
                campaign=campaign, patient__contact_number=phone).first()
            if member is None or member.state != "contacted":
                continue
            services.handle_response_action(member, intent, **kwargs)
            applied += 1

        self.stdout.write(self.style.SUCCESS(f"applied {applied} new simulated replies"))
