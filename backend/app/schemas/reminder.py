from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.enums import OrderStatus, ReminderType


class OwnerReminderRead(BaseModel):
    id: UUID
    order_id: UUID
    restaurant_id: UUID | None
    restaurant_name: str
    reminder_type: ReminderType
    status_snapshot: str | None  # status the order was idle in
    status_updated_at_snapshot: datetime | None  # since when
    created_at: datetime  # when the reminder was created
    read_at: datetime | None
    is_read: bool
    overdue_minutes_at_reminder: int | None
    current_order_status: OrderStatus
    still_waiting: bool  # order is still in that same status period


class UnreadCount(BaseModel):
    unread: int
