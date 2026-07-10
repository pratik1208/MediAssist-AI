"""e-Prescription transmission gateway (FR-M8).

Same swap-in pattern as registration's eligibility gateway: services code
only ever talks to the interface; dev ships a log-only implementation, and a
real network (Surescripts-class) is a later drop-in via default_gateway().
"""

import logging

log = logging.getLogger("refills")


class ERxGateway:
    """Interface: transmit a prescription to a pharmacy."""

    def transmit(self, prescription, pharmacy) -> str:
        """Send the prescription; return a transmission reference id."""
        raise NotImplementedError


class LogOnlyGateway(ERxGateway):
    """Dev stand-in: logs the transmission and returns a fake reference."""

    def transmit(self, prescription, pharmacy) -> str:
        reference = f"ERX-DEV-{prescription.id}-{pharmacy.id}"
        log.info(
            "[e-Rx] %s %s x%s -> %s (erx id %s), ref %s",
            prescription.medication_name, prescription.dose,
            prescription.quantity, pharmacy.name,
            pharmacy.erx_identifier or "n/a", reference,
        )
        return reference


def default_gateway() -> ERxGateway:
    return LogOnlyGateway()
