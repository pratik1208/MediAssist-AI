"""Insurance eligibility checking (FR-R8).

The PRD doesn't name a real payer/clearinghouse API (see its Assumptions),
so this module defines the interface every gateway must follow, plus a
stub used in dev and tests. When a real provider is chosen in Phase 7,
it becomes one more subclass of PayerEligibilityGateway — nothing in
services.py has to change.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class EligibilityResult:
    # status values mirror InsurancePolicy.eligibility_status choices
    status: str  # "eligible" | "ineligible" | "unknown"
    reason: str = ""
    raw: dict = field(default_factory=dict)  # untouched payer response, for audit

# Abstract Base Class
class PayerEligibilityGateway(ABC):
    """What every eligibility backend (stub or real) must implement."""

    @abstractmethod
    def check(self, *, provider_name: str, policy_number: str, member_id: str | None) -> EligibilityResult:
        ...


class StubGateway(PayerEligibilityGateway):
    """Answers from a hardcoded fixture table instead of a network call.

    Any policy number listed in FIXTURES gets that verdict; anything else
    is treated as eligible so dev conversations flow smoothly. Use the
    INACTIVE-* numbers to exercise the "inactive insurance" edge case
    (PRD Edge Case 3).
    """

    FIXTURES = {
        "BS-448291": "eligible",       # the spec's example policy
        "INACTIVE-001": "ineligible",
        "EXPIRED-2024": "ineligible",
        "UNKNOWN-PAYER": "unknown",
    }

    def check(self, *, provider_name, policy_number, member_id=None) -> EligibilityResult:
        if not policy_number:
            return EligibilityResult("unknown", reason="no policy number provided")
        status = self.FIXTURES.get(policy_number, "eligible")
        return EligibilityResult(
            status,
            reason=f"stub fixture verdict for {policy_number}",
            raw={"provider": provider_name, "policy_number": policy_number, "member_id": member_id},
        )


def default_gateway() -> PayerEligibilityGateway:
    """The gateway used when none is injected. Swap here in Phase 7."""
    return StubGateway()
