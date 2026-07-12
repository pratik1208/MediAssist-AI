"""seed_campaigns — demo outreach campaigns (Agent 7).

Three DRAFT campaigns, each showcasing a different build_cohort criterion, so
the campaign manager UI has something to preview/launch immediately. Left in
`draft` on purpose: the demo flow is for a human to open one, preview the
cohort, launch it, and simulate a reply through the frontend.

Idempotent: keyed on campaign name.
"""

from django.core.management.base import BaseCommand

from outreach.models import Campaign

# sms first (immediate), escalate to email after 3 days, voice after 7.
CHANNEL_PLAN = [
    {"channel": "sms", "wait_days": 0},
    {"channel": "email", "wait_days": 3},
    {"channel": "voice", "wait_days": 7},
]

CAMPAIGNS = [
    {"name": "Flu shot 65+",
     "clinical_goal": "come in for your annual flu shot",
     "cohort_criteria": {"age_min": 65}},
    {"name": "Overdue annual check-up",
     "clinical_goal": "it's been over a year since your last visit — let's schedule a check-up",
     "cohort_criteria": {"months_since_last_visit_gte": 12}},
    {"name": "Missed-appointment follow-up",
     "clinical_goal": "we noticed you missed some appointments — let's get you rescheduled",
     "cohort_criteria": {"missed_appointments_gte": 2}},
]


class Command(BaseCommand):
    help = "Seed demo draft outreach campaigns (idempotent)."

    def handle(self, *args, **options):
        created = 0
        for spec in CAMPAIGNS:
            # status="draft" only on first creation — re-seeding must NOT reset
            # a campaign a user has already launched back to draft. Content
            # fields are refreshed either way.
            campaign, was_created = Campaign.objects.get_or_create(
                name=spec["name"],
                defaults={
                    "clinical_goal": spec["clinical_goal"],
                    "cohort_criteria": spec["cohort_criteria"],
                    "channel_plan": CHANNEL_PLAN,
                    "status": "draft",
                },
            )
            if not was_created:
                campaign.clinical_goal = spec["clinical_goal"]
                campaign.cohort_criteria = spec["cohort_criteria"]
                campaign.channel_plan = CHANNEL_PLAN
                campaign.save(update_fields=["clinical_goal", "cohort_criteria", "channel_plan"])
            created += was_created
            self.stdout.write(f"{'created' if was_created else 'updated'}: {spec['name']}")
        self.stdout.write(self.style.SUCCESS(
            f"seeded {len(CAMPAIGNS)} demo campaigns ({created} new)"))
