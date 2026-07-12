"""Payer submission/status gateway (FR-P4).

Same swap-in pattern as registration's eligibility gateway and refills'
e-Rx gateway: services code only ever talks to the interface. The PRD
names no real payer API, so Phase 2 ships exactly one implementation —
SimulatedPayerGateway — and every test in this agent runs against it. A
real ePA network / payer API / fax service is a Phase 7 drop-in behind
this same interface; nothing in services.py would need to change.
"""

from abc import ABC, abstractmethod


class PayerGateway(ABC):
    """What every payer backend (simulated or real) must implement."""

    @abstractmethod
    def submit(self, auth_request, package) -> str:
        """Submit the package; return the payer's external case reference."""

    @abstractmethod
    def check_status(self, auth_request) -> dict:
        """Poll the payer. Either {"status": ...} — a "denied" status also
        carries denial_reason/appeal_suggested, an "info_requested" status
        also carries requested_items (evidence category names) — OR, for a
        channel that only ever hands back unstructured text (fax/portal),
        {"raw_text": "..."}; services.poll_status() runs that through
        priorauth.ai.interpret_payer_message() (Phase 4) to get the same
        structured shape."""


class SimulatedPayerGateway(PayerGateway):
    """Dev/test stand-in for every real channel (api/epa/portal/fax).

    Behavior is fixture-driven, not random, so every branch (approve, deny,
    info-request) is directly testable and demo-able: force_response() sets
    what the NEXT check_status() call returns for a given request. An
    unscripted request defaults to "approved" so a demo run isn't blocked
    on setup. State is in-process memory only (like core.notifications'
    ConsoleProvider) — it resets on restart, which is fine for a dev stub.
    """

    _forced: dict[int, dict] = {}

    @classmethod
    def force_response(cls, auth_request_id: int, status: str, **extra) -> None:
        cls._forced[auth_request_id] = {"status": status, **extra}

    @classmethod
    def force_raw_message(cls, auth_request_id: int, text: str) -> None:
        """Simulate a real payer channel handing back unstructured text
        (fax/portal copy) instead of neat JSON — services.poll_status()
        routes this through priorauth.ai.interpret_payer_message() (Phase 4)
        rather than reading a "status" key directly."""
        cls._forced[auth_request_id] = {"raw_text": text}

    @classmethod
    def clear_forced(cls, auth_request_id: int | None = None) -> None:
        if auth_request_id is None:
            cls._forced.clear()
        else:
            cls._forced.pop(auth_request_id, None)

    def submit(self, auth_request, package) -> str:
        return f"SIM-{auth_request.id:06d}"

    def check_status(self, auth_request) -> dict:
        return dict(self._forced.get(auth_request.id, {"status": "approved"}))


def default_gateway() -> PayerGateway:
    """The gateway used when none is injected. Swap here in Phase 7."""
    return SimulatedPayerGateway()
