import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.enums import ReminderType, enum_column
from app.models.mixins import UTCDateTime, UUIDPrimaryKeyMixin, utcnow


class ReminderLog(UUIDPrimaryKeyMixin, Base):
    """Records that a reminder was sent. UNIQUE(order_id, reminder_type) means each kind of
    reminder is sent at most once per order, even if two workers race."""

    __tablename__ = "reminder_logs"
    __table_args__ = (
        UniqueConstraint(
            "order_id", "reminder_type", name="uq_reminder_logs_order_id_reminder_type"
        ),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    reminder_type: Mapped[ReminderType] = mapped_column(
        enum_column(ReminderType, 30, "reminder_type")
    )
    sent_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, server_default=func.now()
    )

    order: Mapped["Order"] = relationship(back_populates="reminder_logs")
