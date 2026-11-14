from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import LedgerStatus, PaymentMethod, PaymentStatus, TransactionType


class PaymentCreate(BaseModel):
    method: PaymentMethod
    # Lets the frontend / tests exercise the failure path of the simulated gateway.
    simulate_failure: bool = False


class PaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_id: UUID
    amount: Decimal
    method: PaymentMethod
    status: PaymentStatus
    transaction_ref: str | None
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime


class PaymentLedgerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_id: UUID
    amount: Decimal
    transaction_type: TransactionType
    status: LedgerStatus
    reference: str | None
    created_at: datetime
    updated_at: datetime
