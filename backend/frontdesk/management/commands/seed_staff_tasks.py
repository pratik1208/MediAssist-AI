"""seed_staff_tasks — the "human needed" queue, populated for real.

StaffTask has no seed at all today, so the front-desk staff queue is empty
on a fresh clinic. This creates one task per category (the four mandatory
ones plus unanswered_question and manual_review) spanning every status
(open, claimed, resolved), so a tester can see and act on every combination
without having to trigger each one through the live chat first.

Requires no other seed data (StaffTask.session/patient are both nullable) —
runs standalone. Idempotent: keyed on a marker prefix in `summary`, which no
other code path ever rewrites (claim/resolve only touch status/claimed_by/
resolved_at).
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from frontdesk.models import StaffTask

MARKER = "[seed_staff_tasks]"

# category -> (priority, status, claimed_by)
CASES = [
    ("mental_health", "critical", "open", ""),
    ("stroke", "critical", "claimed", "dr_patel"),
    ("insurance_dispute", "high", "resolved", "front_desk_1"),
    ("controlled_substance", "high", "open", ""),
    ("unanswered_question", "normal", "open", ""),
    ("manual_review", "normal", "claimed", "front_desk_2"),
]

SUMMARIES = {
    "mental_health": "Caller described feeling hopeless and unsafe — needs immediate follow-up.",
    "stroke": "Caller reported sudden one-sided weakness and slurred speech.",
    "insurance_dispute": "Patient disputes a co-pay charge from their last visit.",
    "controlled_substance": "Early refill request for a controlled substance.",
    "unanswered_question": "No knowledge-base answer for: 'do you offer home nursing visits?'",
    "manual_review": "Unclassifiable request forwarded from the front-desk chat.",
}


class Command(BaseCommand):
    help = "Seed the front-desk staff task queue across every category and status (idempotent)."

    def handle(self, *args, **options):
        created = 0
        for category, priority, status, claimed_by in CASES:
            summary = f"{MARKER} {SUMMARIES[category]}"
            if StaffTask.objects.filter(category=category, summary=summary).exists():
                continue
            StaffTask.objects.create(
                category=category, priority=priority, status=status,
                claimed_by=claimed_by, summary=summary,
                resolved_at=timezone.now() if status == "resolved" else None,
            )
            created += 1

        self.stdout.write(self.style.SUCCESS(f"seeded {created} new staff tasks"))
