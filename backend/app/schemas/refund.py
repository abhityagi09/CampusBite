from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import RefundStatus


class RefundRequestCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    order_id: UUID
    reason: str = Field(min_length=1, max_length=2000)


class RefundRequestBody(BaseModel):
    """POST /orders/{id}/refund-requests: the order comes from the URL."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    reason: str = Field(min_length=1, max_length=2000)


class RefundDecision(BaseModel):
    """Restaurant owner's decision. 'approve' refunds the full payment immediately."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]


class RefundRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_id: UUID
    customer_id: UUID
    reason: str
    status: RefundStatus
    created_at: datetime
    updated_at: datetime
