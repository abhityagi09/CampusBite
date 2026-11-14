import uuid
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.enums import LedgerStatus, TransactionType, enum_column
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class PaymentLedger(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append-only money history: every charge attempt and every refund is one row.

    Amounts are always positive; transaction_type says which direction the money moved.
    """

    __tablename__ = "payment_ledger"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        Index("ix_payment_ledger_order_id_created_at", "order_id", "created_at"),
        # A gateway reference identifies exactly one ledger entry; rows without one
        # (e.g. declined attempts) are not constrained.
        Index(
            "uq_payment_ledger_reference",
            "reference",
            unique=True,
            postgresql_where=text("reference IS NOT NULL"),
            sqlite_where=text("reference IS NOT NULL"),
        ),
    )

    # No ON DELETE: financial history must never disappear because an order was touched.
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    transaction_type: Mapped[TransactionType] = mapped_column(
        enum_column(TransactionType, 20, "transaction_type")
    )
    status: Mapped[LedgerStatus] = mapped_column(
        enum_column(LedgerStatus, 20, "ledger_status"), default=LedgerStatus.PENDING
    )
    reference: Mapped[str | None] = mapped_column(String(64))

    order: Mapped["Order"] = relationship(back_populates="ledger_entries")
