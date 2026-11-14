from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response

from app.dependencies import CurrentUser, CustomerUser, DbSession, DeliveryUser, OwnerUser
from app.dependencies.query import PageParams
from app.models import OrderStatus
from app.schemas.order import (
    AssignDelivery,
    OrderCreate,
    OrderDetail,
    OrderRead,
    OrderStatusUpdate,
    StatusEventRead,
)
from app.schemas.common import Page
from app.schemas.payment import PaymentRead
from app.services import order_service as svc
from app.services import payment_service as payment_svc
from app.services.payment_gateway import DummyPaymentGateway, get_payment_gateway

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post(
    "",
    response_model=OrderDetail,
    status_code=201,
    responses={
        200: {"description": "Replay: this Idempotency-Key was already used with the same body"},
        402: {"description": "Payment declined; nothing was saved"},
        409: {"description": "expected_total differs from the server-computed total"},
        422: {"description": "Invalid cart, or Idempotency-Key reused with a different body"},
        502: {"description": "Payment provider failed; nothing was saved"},
    },
)
def create_order(
    data: OrderCreate,
    db: DbSession,
    customer: CustomerUser,
    response: Response,
    gateway: Annotated[DummyPaymentGateway, Depends(get_payment_gateway)],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            min_length=8,
            max_length=64,
            pattern=r"^[A-Za-z0-9_\-:.]+$",
            description="Unique per checkout attempt (e.g. a UUID). Required with payment_method.",
        ),
    ] = None,
):
    """Check out the cart. Only menu item ids, quantities and the restaurant are taken
    from the client; prices and totals come from the database.

    * With ``payment_method``: order + payment are created in one transaction and the
      order is ``placed``. Needs an Idempotency-Key header.
    * Without it: the order waits in ``pending_payment``; pay via
      POST /payments/orders/{id}/pay.
    """
    result = svc.checkout(db, customer, data, idempotency_key, gateway)
    if result.replayed:
        response.status_code = 200
        response.headers["Idempotent-Replayed"] = "true"
    return result.order


@router.get("/me", response_model=Page[OrderRead])
def my_orders(
    db: DbSession,
    customer: CustomerUser,
    page: PageParams,
    status_filter: OrderStatus | None = Query(None, alias="status"),
    created_from: date | None = Query(None, description="Inclusive, YYYY-MM-DD (UTC)"),
    created_to: date | None = Query(None, description="Inclusive, YYYY-MM-DD (UTC)"),
):
    """The signed-in customer's orders, newest first."""
    return svc.list_my_orders(db, customer, status_filter, page, created_from, created_to)


@router.get("", response_model=list[OrderRead])
def list_orders(
    db: DbSession,
    user: CurrentUser,
    status_filter: OrderStatus | None = Query(None, alias="status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    created_from: date | None = Query(None, description="Inclusive, YYYY-MM-DD (UTC)"),
    created_to: date | None = Query(None, description="Inclusive, YYYY-MM-DD (UTC)"),
):
    """Customers: own orders. Owners: orders for their restaurants.
    Delivery partners: orders assigned to them."""
    return svc.list_orders(db, user, status_filter, limit, offset, created_from, created_to)


# Must be declared before "/{order_id}"
@router.get("/available", response_model=list[OrderRead])
def available_orders(
    db: DbSession,
    partner: DeliveryUser,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """Ready-for-pickup orders that no courier has claimed yet."""
    return svc.list_available_orders(db, limit, offset)


@router.get("/{order_id}", response_model=OrderDetail)
def get_order(order_id: UUID, db: DbSession, user: CurrentUser):
    return svc.get_order_for_user(db, order_id, user)


@router.get("/{order_id}/payment", response_model=PaymentRead)
def get_order_payment(order_id: UUID, db: DbSession, user: CurrentUser):
    """Payment of an order (its customer or the restaurant owner)."""
    return payment_svc.get_payment(db, user, order_id)


@router.get("/{order_id}/tracking", response_model=list[StatusEventRead])
def track_order(order_id: UUID, db: DbSession, user: CurrentUser):
    return svc.get_order_for_user(db, order_id, user).events


@router.patch("/{order_id}/status", response_model=OrderDetail)
def update_status(
    order_id: UUID, data: OrderStatusUpdate, db: DbSession, user: CurrentUser
):
    """Owner: accepted / rejected / preparing / ready_for_pickup.
    Assigned delivery partner: out_for_delivery / delivered."""
    return svc.update_status(db, user, order_id, data.status)


@router.post("/{order_id}/cancel", response_model=OrderDetail)
def cancel_order(order_id: UUID, db: DbSession, customer: CustomerUser):
    return svc.cancel_order(db, customer, order_id)


@router.post("/{order_id}/assign-delivery", response_model=OrderDetail)
def assign_delivery(order_id: UUID, data: AssignDelivery, db: DbSession, owner: OwnerUser):
    """Restaurant owner assigns an active delivery partner (accepted .. ready_for_pickup)."""
    return svc.assign_delivery(db, owner, order_id, data.delivery_partner_id)


@router.post("/{order_id}/claim", response_model=OrderDetail)
def claim_order(order_id: UUID, db: DbSession, partner: DeliveryUser):
    return svc.claim_order(db, partner, order_id)
