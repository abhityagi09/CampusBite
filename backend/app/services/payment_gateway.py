"""Deterministic dummy payment gateway. No real money, no network.

* The outcome is configured on the SERVER (settings or the constructor in tests), never
  taken from the request, so a client cannot claim a payment succeeded.
* The same (order, amount, method) always produces the same result and the same
  server-generated reference, which makes tests and retries reproducible.

It has no side effects, so calling it inside the checkout database transaction is safe:
if that transaction rolls back, nothing was "charged". A real gateway would need
authorize-then-capture (or reconciliation) instead, because it cannot be rolled back.
"""

import hashlib
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from app.core.config import settings
from app.core.exceptions import BadGatewayError
from app.models import PaymentMethod


class ChargeOutcome(StrEnum):
    SUCCESS = "success"
    DECLINE = "decline"
    ERROR = "error"


@dataclass(frozen=True)
class ChargeResult:
    approved: bool
    reference: str | None
    failure_reason: str | None = None


@dataclass
class DummyPaymentGateway:
    outcome: ChargeOutcome = ChargeOutcome.SUCCESS
    outcomes_by_method: dict[PaymentMethod, ChargeOutcome] = field(default_factory=dict)

    def charge(self, *, order_id: UUID, amount: Decimal, method: PaymentMethod) -> ChargeResult:
        if amount <= 0:
            raise ValueError("Charge amount must be positive")
        outcome = self.outcomes_by_method.get(method, self.outcome)
        if outcome == ChargeOutcome.ERROR:
            raise BadGatewayError()
        if outcome == ChargeOutcome.DECLINE:
            return ChargeResult(
                approved=False, reference=None, failure_reason="Payment declined (simulated)"
            )
        return ChargeResult(approved=True, reference=self.reference_for(order_id, amount, method))

    @staticmethod
    def reference_for(order_id: UUID, amount: Decimal, method: PaymentMethod) -> str:
        digest = hashlib.sha256(f"{order_id}|{amount:.2f}|{method.value}".encode()).hexdigest()
        return f"SIM-{digest[:20].upper()}"


def _parse_method_outcomes(raw: str) -> dict[PaymentMethod, ChargeOutcome]:
    result: dict[PaymentMethod, ChargeOutcome] = {}
    for pair in filter(None, (p.strip() for p in raw.split(","))):
        method, _, outcome = pair.partition("=")
        result[PaymentMethod(method.strip())] = ChargeOutcome(outcome.strip())
    return result


def get_payment_gateway() -> DummyPaymentGateway:
    """FastAPI dependency. Tests override it with a gateway configured per test."""
    return DummyPaymentGateway(
        outcome=ChargeOutcome(settings.PAYMENT_SIMULATOR_OUTCOME),
        outcomes_by_method=_parse_method_outcomes(settings.PAYMENT_SIMULATOR_METHOD_OUTCOMES),
    )
