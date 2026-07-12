"""seed_appointments — appointment history for the curated patient roster.

Gives the outreach cohort engine real data to query: `completed` visits (some
recent, some 12-18 months old) drive months_since_last_visit_gte, and
`no_show` rows drive missed_appointments_gte. It reads the roster + per-patient
tags straight from core's seed_patients so the two stay in lockstep.

Requires patients (seed_patients) and doctors (seed_doctors) to already exist;
no-ops with a warning otherwise. seed_all runs them in the right order.

Idempotent across ANY run date: start_times are anchored to "today", so a
rerun on a later day would otherwise pile up a second set of history. To stay
clean, the command first deletes its OWN previously-seeded rows (identified by
the `reason="Seed history"` marker, scoped to roster patients) and then
recreates them — never touching real appointments.
"""

SEED_MARKER = "Seed history"

import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.management.commands.seed_patients import PATIENTS
from core.models import Doctor, Patient
from scheduling.models import Appointment

# tag -> (status, whole-days-ago). Two no_show rows share a bucket but get
# distinct slots via the per-bucket counter below.
BUCKETS = {
    "recent": ("completed", 60),
    "overdue": ("completed", 420),
    "no_show_x1": ("no_show", 30),
    "no_show_x2": ("no_show", 45),
    "upcoming": ("booked", -10),  # negative -> future
    # "never" intentionally produces no appointment.
}


class Command(BaseCommand):
    help = "Seed completed / no_show / upcoming appointment history (idempotent)."

    def handle(self, *args, **options):
        doctors = list(Doctor.objects.filter(is_active=True).order_by("id"))
        if not doctors:
            self.stdout.write(self.style.WARNING(
                "no doctors found — run seed_doctors first; skipping"))
            return

        # Clear our own previously-seeded rows so reruns (esp. on a later date)
        # replace history rather than duplicating it. Real appointments have a
        # different reason and are untouched.
        roster_phones = [e["phone"] for e in PATIENTS]
        Appointment.objects.filter(
            reason=SEED_MARKER, patient__contact_number__in=roster_phones,
        ).delete()

        today = timezone.localdate()
        counters: dict[datetime.date, int] = {}

        def next_slot(days_ago: int):
            """A unique (doctor, aware start_time) for a given day bucket:
            rotate doctors, step 20 min once every doctor has one at that time."""
            day = today - datetime.timedelta(days=days_ago)
            n = counters.get(day, 0)
            counters[day] = n + 1
            doctor = doctors[n % len(doctors)]
            start_naive = datetime.datetime.combine(day, datetime.time(9, 0)) \
                + datetime.timedelta(minutes=(n // len(doctors)) * 20)
            start = timezone.make_aware(start_naive)
            return doctor, start, start + datetime.timedelta(minutes=20)

        created = skipped = 0
        for entry in PATIENTS:
            patient = Patient.objects.filter(contact_number=entry["phone"]).first()
            if patient is None:
                skipped += 1
                continue
            for tag in entry.get("tags", []):
                if tag not in BUCKETS:
                    continue
                status, days_ago = BUCKETS[tag]
                # "no_show_x2" means TWO missed visits.
                for _ in range(2 if tag == "no_show_x2" else 1):
                    doctor, start, end = next_slot(days_ago)
                    _, was_created = Appointment.objects.get_or_create(
                        doctor=doctor, start_time=start,
                        defaults={
                            "patient": patient, "end_time": end,
                            "reason": SEED_MARKER, "urgency": "routine",
                            "status": status, "source": "scheduling",
                        },
                    )
                    created += was_created

        if skipped:
            self.stdout.write(self.style.WARNING(
                f"{skipped} roster patients missing — run seed_patients first"))
        self.stdout.write(self.style.SUCCESS(
            f"seeded appointment history ({created} new rows)"))
