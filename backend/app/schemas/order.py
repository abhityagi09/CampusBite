from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.models.enums import OrderStatus, PaymentMethod
from app.schemas.payment import PaymentRead


class OrderItemCreate(BaseModel):
    """A cart line: only WHAT and HOW MANY. The price always comes from the database;
    unknown fields such as ``price`` / ``unit_price`` are rejected (422)."""

    model_config = ConfigDict(extra="forbid")

    menu_item_id: UUID
    # strict: 2.5, "2" and true are rejected instead of being coerced.
    quantity: int = Field(ge=1, le=50, strict=True)


class OrderCreate(BaseModel):
    """Checkout request built from the client-side cart.

    The client never sends prices or totals it expects to be charged (``total_amount``
    etc. are rejected). ``expected_total`` is optional and only ever COMPARED: if the
    server-computed total differs (prices changed, or the cart was tampered with) the
    checkout is refused with 409 and nothing is saved or charged.

    With ``payment_method`` the order is paid in the same transaction (checkout; requires
    an Idempotency-Key header). Without it the order waits in pending_payment and is paid
    via POST /payments/orders/{id}/pay.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    restaurant_id: UUID
    items: list[OrderItemCreate] = Field(min_length=1, max_length=50)
    delivery_address: str = Field(min_length=5, max_length=255)
    notes: str | None = Field(default=None, max_length=500)
    payment_method: PaymentMethod | None = None
    expected_total: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)


class OrderStatusUpdate(BaseModel):
    status: OrderStatus


class OrderItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    menu_item_id: UUID | None
    name: str
    unit_price: Decimal
    quantity: int
    subtotal: Decimal


class StatusEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: OrderStatus
    actor_id: UUID | None
    created_at: datetime


class OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    customer_id: UUID
    restaurant_id: UUID
    delivery_partner_id: UUID | None
    status: OrderStatus
    total_amount: Decimal
    delivery_address: str
    notes: str | None
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemRead]


class OrderDetail(OrderRead):
    events: list[StatusEventRead]  # audit history: every status, who set it, when
    payment: PaymentRead | None

    @computed_field
    @property
    def status_timestamps(self) -> dict[OrderStatus, datetime]:
        """When the order entered each status it has been in."""
        return {e.status: e.created_at for e in self.events}


class AssignDelivery(BaseModel):
    delivery_partner_id: UUID
