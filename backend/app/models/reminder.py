import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.enums import ReminderType, enum_column
from app.models.mixins import UTCDateTime, UUIDPrimaryKeyMixin, utcnow


class ReminderLog(UUIDPrimaryKeyMixin, Base):
    """One row per reminder sent.

    ``event_key`` is the idempotency key, UNIQUE in the database, so concurrent workers can
    never record the same reminder twice:
      * customer reminders:      "<order_id>:<type>"                      (once per order)
      * owner ORDER_STALE:       "<order_id>:order_stale:<status>:<status_updated_at>"
                                 (once per status period; a new period may remind again)
    """

    __tablename__ = "reminder_logs"
    __table_args__ = (
        UniqueConstraint("event_key", name="uq_reminder_logs_event_key"),
        Index("ix_reminder_logs_restaurant_id_sent_at", "restaurant_id", "sent_at"),
        Index("ix_reminder_logs_order_id", "order_id"),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    restaurant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("restaurants.id"))
    reminder_type: Mapped[ReminderType] = mapped_column(
        enum_column(ReminderType, 30, "reminder_type")
    )
    event_key: Mapped[str] = mapped_column(String(200))
    status_snapshot: Mapped[str | None] = mapped_column(String(30))
    status_updated_at_snapshot: Mapped[datetime | None] = mapped_column(UTCDateTime())
    sent_at: Mapped[datetime] = mapped_column(  # = reminder creation time
        UTCDateTime(), default=utcnow, server_default=func.now()
    )
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    order: Mapped["Order"] = relationship(back_populates="reminder_logs")
