from enum import StrEnum

from sqlalchemy import Enum


class UserRole(StrEnum):
    CUSTOMER = "customer"
    OWNER = "owner"
    DELIVERY_PARTNER = "delivery_partner"


class OrderStatus(StrEnum):
    PENDING_PAYMENT = "pending_payment"
    PLACED = "placed"
    ACCEPTED = "accepted"
    PREPARING = "preparing"
    READY_FOR_PICKUP = "ready_for_pickup"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class PaymentMethod(StrEnum):
    CARD = "card"
    UPI = "upi"
    WALLET = "wallet"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    PAID = "mock_paid"  # dummy gateway only: never a real capture
    FAILED = "failed"
    REFUNDED = "refunded"



class TransactionType(StrEnum):
    """Direction of a payment_ledger entry."""

    CHARGE = "charge"
    REFUND = "refund"


class LedgerStatus(StrEnum):
    """Outcome of a payment_ledger entry."""

    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class RefundStatus(StrEnum):
    REQUESTED = "requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    PROCESSED = "processed"


class ReminderType(StrEnum):
    PAYMENT_PENDING = "payment_pending"
    ORDER_READY = "order_ready"
    REVIEW_REQUEST = "review_request"
    ORDER_STALE = "order_stale"  # to the owner: placed/accepted, untouched 15 min


def enum_column(enum_cls: type[StrEnum], length: int, name: str) -> Enum:
    """Store enum *values* as VARCHAR guarded by a named CHECK constraint.

    VARCHAR (not a native PostgreSQL ENUM) keeps migrations simple: adding a value later
    is "drop and recreate one CHECK constraint", not an ALTER TYPE. The CHECK still makes
    the database itself reject unknown values. The naming convention in
    app/database/base.py names it ck_<table>_<name>.
    """
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        length=length,
        create_constraint=True,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )
