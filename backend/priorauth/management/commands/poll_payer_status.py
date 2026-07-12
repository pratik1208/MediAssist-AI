"""poll_payer_status — FR-P5, run manually for now.

Polls every authorization request still in flight (not yet approved/
denied) against the payer gateway and reacts to whatever comes back. A
scheduled job (e.g. hourly, per Phase 7) replaces this manual invocation.
"""

from django.core.management.base import BaseCommand

from priorauth import services
from priorauth.models import AuthorizationRequest


class Command(BaseCommand):
    help = "Poll payer status for every in-flight authorization request."

    def handle(self, *args, **options):
        in_flight = AuthorizationRequest.objects.exclude(status__in=["approved", "denied"])
        if not in_flight:
            self.stdout.write("no authorization requests in flight")
            return
        for auth_request in in_flight:
            before = auth_request.status
            services.poll_status(auth_request)
            auth_request.refresh_from_db()
            self.stdout.write(
                f"request #{auth_request.id}: {before} -> {auth_request.status}"
            )
        self.stdout.write(self.style.SUCCESS(f"polled {in_flight.count()} request(s)"))
