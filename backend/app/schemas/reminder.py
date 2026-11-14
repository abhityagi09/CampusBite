from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import ReminderType


class ReminderLogCreate(BaseModel):
    order_id: UUID
    reminder_type: ReminderType


class ReminderLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_id: UUID
    reminder_type: ReminderType
    sent_at: datetime
