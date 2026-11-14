from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ReviewCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    order_id: UUID
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)


class PublicReviewRead(BaseModel):
    """What anyone may see: no customer id and no order id (those are private)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    restaurant_id: UUID
    rating: int
    comment: str | None
    created_at: datetime


class ReviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_id: UUID
    customer_id: UUID
    restaurant_id: UUID
    rating: int
    comment: str | None
    created_at: datetime
