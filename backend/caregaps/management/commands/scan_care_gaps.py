"""scan_care_gaps — FR-G1/G2, the nightly scan as a command.

Same "run now, cron later" pattern as outreach's dispatch_campaign_waves:
gap detection is background work over the whole panel, never something a
request should block on. Runs one full scan_all() pass — open what's owed,
refresh stale dates, close gaps whose satisfying event has appeared. Safe to
run repeatedly (the scanner is idempotent by construction); Phase 7 wires it
to a real scheduler. Pass --recycle to also run the weekly FR-G7 pass that
sends stale care plans back into outreach.
"""

from django.core.management.base import BaseCommand

from caregaps import services


class Command(BaseCommand):
    help = "Scan every patient against the active clinical guidelines (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--recycle", action="store_true",
                            help="Also recycle care plans pending past the window (FR-G7).")

    def handle(self, *args, **options):
        totals = services.scan_all()
        self.stdout.write(
            f"scanned {totals['patients_scanned']} candidate patient(s): "
            f"{totals['opened']} gaps opened, {totals['refreshed']} refreshed, "
            f"{totals['closed']} closed on evidence"
        )
        if options["recycle"]:
            recycled = services.recycle_incomplete()
            self.stdout.write(f"recycled {len(recycled)} stale care plan(s) back into outreach")
        self.stdout.write(self.style.SUCCESS("care gap scan complete"))
