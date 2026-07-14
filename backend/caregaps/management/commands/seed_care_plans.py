"""seed_care_plans — care plans at draft/sent/recycled, for real.

CarePlan has no seed at all today, so the care-plan view is empty on a
fresh clinic even after scan_care_gaps opens real gaps. This bundles real
open gaps into plans for three patients via the actual service functions
(bundle_care_plan, push_plans_to_outreach, recycle_incomplete): one left at
"draft" (Kamala, untouched — for staff to review before sending), one
pushed to "sent" (Lakshmi — enrolls her into caregaps' own always-running
"Care plan follow-up" outreach campaign, FR-G5), one backdated past the
recycle window and recycled (Sunita — her unfinished gaps reset to "open",
ready for the next cycle).

Requires patients (seed_patients), diabetic diagnoses (seed_clinical_events),
and open gaps (scan_care_gaps) to exist; no-ops with a warning otherwise.
Idempotent: the Lakshmi/Sunita sequence only runs once (guarded by their
final states); Kamala's bundle is naturally idempotent (bundle_care_plan
reuses an existing active plan rather than duplicating).
"""

import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from caregaps.models import CarePlan
from caregaps.services import bundle_care_plan, push_plans_to_outreach, recycle_incomplete
from core.models import Patient

LAKSHMI_PHONE = "9820010006"  # -> sent
SUNITA_PHONE = "9820020001"   # -> recycled
KAMALA_PHONE = "9820010001"   # -> draft, untouched


class Command(BaseCommand):
    help = "Seed care plans at draft/sent/recycled via real service calls (idempotent)."

    def handle(self, *args, **options):
        lakshmi = Patient.objects.filter(contact_number=LAKSHMI_PHONE).first()
        sunita = Patient.objects.filter(contact_number=SUNITA_PHONE).first()
        kamala = Patient.objects.filter(contact_number=KAMALA_PHONE).first()
        if not (lakshmi and sunita and kamala):
            self.stdout.write(self.style.WARNING(
                "roster patients missing — run seed_patients first"))
            return

        already_done = (
            CarePlan.objects.filter(
                patient=lakshmi,
                status__in=("sent", "accepted", "in_progress", "completed")).exists()
            and CarePlan.objects.filter(patient=sunita, status="recycled").exists()
        )
        if not already_done:
            bundle_care_plan(lakshmi)
            sunita_plan = bundle_care_plan(sunita)
            push_plans_to_outreach()
            if sunita_plan:
                CarePlan.objects.filter(id=sunita_plan.id).update(
                    created_at=timezone.now() - datetime.timedelta(days=45))
                recycle_incomplete()
            self.stdout.write("bundled Lakshmi -> sent, Sunita -> recycled")
        else:
            self.stdout.write("Lakshmi/Sunita care plans already seeded — skipping")

        # Bundled last (and every run) so a fresh plan is created only after
        # the push above has already happened — otherwise it would go out
        # with the others instead of staying at draft.
        kamala_plan = bundle_care_plan(kamala)
        if kamala_plan is None:
            self.stdout.write(self.style.WARNING(
                "no open gaps for Kamala — run scan_care_gaps first"))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Kamala care plan #{kamala_plan.id} at {kamala_plan.status}"))
