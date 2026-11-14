import uuid

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.enums import RefundStatus, enum_column
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class RefundRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "refund_requests"
    __table_args__ = (
        CheckConstraint("length(trim(reason)) > 0", name="reason_not_blank"),
        # The requester must be the order's own customer.
        ForeignKeyConstraint(
            ["order_id", "customer_id"],
            ["orders.id", "orders.customer_id"],
            name="fk_refund_requests_order_id_customer_id_orders",
        ),
        Index("ix_refund_requests_order_id", "order_id"),
        # At most one OPEN request per order. Once a request is rejected or processed a
        # new one may be filed.
        Index(
            "uq_refund_requests_open_order",
            "order_id",
            unique=True,
            postgresql_where=text("status IN ('requested', 'approved')"),
            sqlite_where=text("status IN ('requested', 'approved')"),
        ),
    )

    order_id: Mapped[uuid.UUID] = mapped_column()
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[RefundStatus] = mapped_column(
        enum_column(RefundStatus, 20, "refund_status"), default=RefundStatus.REQUESTED
    )

    order: Mapped["Order"] = relationship(
        back_populates="refund_requests", overlaps="customer"
    )
    customer: Mapped["User"] = relationship(
        back_populates="refund_requests", overlaps="order"
    )
