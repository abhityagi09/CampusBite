"""The ONLY place that decides which order status changes are allowed, and by whom.

    pending_payment --system(pay)--> placed --owner--> accepted --owner--> preparing
    preparing --owner--> ready --owner assigns a courier--> assigned
    assigned --assigned courier--> out_for_delivery --assigned courier--> delivered
    delivered --approved refund request--> refunded

    customer may cancel  : pending_payment, placed               (nothing accepted yet)
    owner may reject     : placed, accepted                      (before preparation)
    cancelled / rejected / refunded are terminal; delivered can only become refunded.

Anything not listed (skips, reversals, repeats, leaving a terminal state) is refused.
"""

from enum import StrEnum

from sqlalchemy import update
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from app.core.exceptions import ConflictError, ForbiddenError
from app.models import Order, OrderStatus
from app.models.mixins import utcnow

S = OrderStatus


class Actor(StrEnum):
    SYSTEM = "system"  # payment confirmation
    CUSTOMER = "customer"  # the order's customer
    OWNER = "owner"  # owner of the order's restaurant
    COURIER = "courier"  # the delivery partner assigned to the order


TRANSITIONS: dict[OrderStatus, dict[OrderStatus, frozenset[Actor]]] = {
    S.PENDING_PAYMENT: {
        S.PLACED: frozenset({Actor.SYSTEM}),
        S.CANCELLED: frozenset({Actor.CUSTOMER}),
    },
    S.PLACED: {
        S.ACCEPTED: frozenset({Actor.OWNER}),
        S.REJECTED: frozenset({Actor.OWNER}),
        S.CANCELLED: frozenset({Actor.CUSTOMER}),
    },
    S.ACCEPTED: {
        S.PREPARING: frozenset({Actor.OWNER}),
        S.REJECTED: frozenset({Actor.OWNER}),
    },
    S.PREPARING: {S.READY: frozenset({Actor.OWNER})},
    S.READY: {S.ASSIGNED: frozenset({Actor.OWNER})},  # only via POST /orders/{id}/assign-delivery
    S.ASSIGNED: {S.OUT_FOR_DELIVERY: frozenset({Actor.COURIER})},
    S.OUT_FOR_DELIVERY: {S.DELIVERED: frozenset({Actor.COURIER})},
    S.DELIVERED: {S.REFUNDED: frozenset({Actor.SYSTEM})},  # only via an approved refund request
}
TERMINAL = frozenset({S.REFUNDED, S.CANCELLED, S.REJECTED})
# Assignment needs a READY order; an ASSIGNED one may be re-assigned until pickup.
ASSIGNABLE = frozenset({S.READY, S.ASSIGNED})
# Reached only through dedicated endpoints, never through PATCH /orders/{id}/status.
NOT_VIA_STATUS_ENDPOINT = frozenset({S.ASSIGNED, S.REFUNDED})


def check_transition(current: OrderStatus, new: OrderStatus, actor: Actor) -> None:
    """409 if the move is never allowed from ``current``; 403 if it is, but not for ``actor``."""
    allowed_actors = TRANSITIONS.get(current, {}).get(new)
    if allowed_actors is None:
        raise ConflictError(f"Cannot move order from '{current.value}' to '{new.value}'")
    if actor not in allowed_actors:
        raise ForbiddenError(f"You cannot move this order to '{new.value}'")


def compare_and_set(db: Session, order: Order, expected: OrderStatus, **values) -> None:
    """Write ``values`` only if the row still has status ``expected`` (and, for a
    ``delivery_partner_id`` change, the partner we read). Complements SELECT ... FOR UPDATE:
    even without row locks (e.g. SQLite) a stale writer changes nothing and gets 409."""
    stmt = update(Order).where(Order.id == order.id, Order.status == expected)
    if "delivery_partner_id" in values:
        current = order.delivery_partner_id
        stmt = stmt.where(
            Order.delivery_partner_id.is_(None)
            if current is None
            else Order.delivery_partner_id == current
        )
    result = db.execute(
        stmt.values(**values, updated_at=utcnow()).execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        raise ConflictError("The order was changed by someone else. Reload and try again.")
    for key, value in values.items():
        set_committed_value(order, key, value)
