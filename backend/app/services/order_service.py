import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.permissions import ensure_role
from app.core.exceptions import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    PaymentRequiredError,
    UnprocessableError,
)
from app.models import (
    MenuItem,
    Order,
    OrderItem,
    OrderStatus,
    OrderStatusEvent,
    LedgerStatus,
    Payment,
    PaymentLedger,
    PaymentMethod,
    PaymentStatus,
    Restaurant,
    TransactionType,
    User,
    UserRole,
)
from app.models.mixins import utcnow, uuid7
from app.schemas.common import Page
from app.schemas.order import OrderCreate, OrderRead
from app.services import order_lifecycle as lifecycle
from app.services.order_lifecycle import Actor
from app.services.payment_gateway import DummyPaymentGateway
from app.services.restaurant_service import Pagination

# ---- lifecycle rules -------------------------------------------------------
# Allowed transitions and who may make them live in app/services/order_lifecycle.py.

REFUND_ON = {OrderStatus.CANCELLED, OrderStatus.REJECTED}

_LOAD = (
    selectinload(Order.items),
    selectinload(Order.events),
    selectinload(Order.payment),
    selectinload(Order.restaurant),
    selectinload(Order.review),
    selectinload(Order.refund_requests),
)


def load_order(db: Session, order_id: UUID, lock: bool = False) -> Order | None:
    stmt = select(Order).options(*_LOAD).where(Order.id == order_id)
    if lock:
        stmt = stmt.with_for_update()
    return db.scalar(stmt)


def reload_order(db: Session, order_id: UUID) -> Order:
    db.expire_all()
    order = load_order(db, order_id)
    assert order is not None
    return order


def can_view(order: Order, user: User) -> bool:
    if user.role == UserRole.CUSTOMER:
        return order.customer_id == user.id
    if user.role == UserRole.OWNER:
        return order.restaurant.owner_id == user.id
    if user.role == UserRole.DELIVERY_PARTNER:
        unclaimed_ready = (
            order.status == OrderStatus.READY_FOR_PICKUP
            and order.delivery_partner_id is None
        )
        return order.delivery_partner_id == user.id or unclaimed_ready
    return False


def get_order_for_user(db: Session, order_id: UUID, user: User) -> Order:
    order = load_order(db, order_id)
    # 404 (not 403) so users cannot discover other people's order ids
    if order is None or not can_view(order, user):
        raise NotFoundError("Order not found")
    return order


def apply_status(order: Order, new_status: OrderStatus, actor: User) -> None:
    """Change status, record history, and refund a paid order if it ended unfulfilled.
    The caller commits."""
    if order.status != new_status:  # (a compare-and-set caller already wrote both)
        order.status = new_status
        order.status_updated_at = utcnow()
    order.events.append(OrderStatusEvent(status=new_status, actor_id=actor.id))
    if (
        new_status in REFUND_ON
        and order.payment is not None
        and order.payment.status == PaymentStatus.PAID
    ):
        order.payment.status = PaymentStatus.REFUNDED
        # Append-only money history: the refund is recorded, never edited in place.
        order.ledger_entries.append(
            PaymentLedger(
                amount=order.payment.amount,
                transaction_type=TransactionType.REFUND,
                status=LedgerStatus.COMPLETED,
                reference=f"RFND-{uuid.uuid4().hex[:16].upper()}",
            )
        )


# ---- customer --------------------------------------------------------------


@dataclass(frozen=True)
class CheckoutResult:
    order: Order
    replayed: bool  # True: the order from an earlier request with the same Idempotency-Key


def _fingerprint(data: OrderCreate) -> str:
    canonical = json.dumps(data.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _find_by_idempotency_key(db: Session, customer: User, key: str) -> Order | None:
    return db.scalar(
        select(Order).where(Order.customer_id == customer.id, Order.idempotency_key == key)
    )


def _replay(db: Session, existing: Order, fingerprint: str) -> CheckoutResult:
    if existing.request_fingerprint != fingerprint:
        raise UnprocessableError(
            "This Idempotency-Key was already used for a different order. "
            "Use a new key for a new checkout."
        )
    return CheckoutResult(order=reload_order(db, existing.id), replayed=True)


def _charge(
    order: Order, customer: User, method: PaymentMethod, gateway: DummyPaymentGateway
) -> None:
    """Charge through the gateway and attach payment + ledger entry to the order.
    Raises on decline / gateway error; the caller then rolls everything back."""
    result = gateway.charge(order_id=order.id, amount=order.total_amount, method=method)
    if not result.approved:
        raise PaymentRequiredError(result.failure_reason)
    order.payment = Payment(
        amount=order.total_amount,
        method=method,
        status=PaymentStatus.PAID,  # decided by the server from the gateway result only
        transaction_ref=result.reference,
    )
    order.ledger_entries.append(
        PaymentLedger(
            amount=order.total_amount,
            transaction_type=TransactionType.CHARGE,
            status=LedgerStatus.COMPLETED,
            reference=result.reference,
        )
    )
    apply_status(order, OrderStatus.PLACED, customer)


def checkout(
    db: Session,
    customer: User,
    data: OrderCreate,
    idempotency_key: str | None = None,
    gateway: DummyPaymentGateway | None = None,
) -> CheckoutResult:
    """Create an order from a cart, and pay for it if ``data.payment_method`` is set.

    Order, items, status events, payment and ledger entry are written in ONE transaction;
    any failure (including a declined payment) rolls all of it back.

    Idempotency: repeating a request with the same key and body returns the original order
    (``replayed=True``) without charging again; the same key with a different body is 422.
    Declined / failed attempts save nothing, so their key may be retried.
    """
    ensure_role(customer, UserRole.CUSTOMER)
    if data.payment_method is not None:
        if not idempotency_key:
            raise BadRequestError("An Idempotency-Key header is required to check out")
        if gateway is None:
            raise RuntimeError("checkout with payment needs a payment gateway")

    fingerprint = _fingerprint(data)
    if idempotency_key:
        existing = _find_by_idempotency_key(db, customer, idempotency_key)
        if existing is not None:
            return _replay(db, existing, fingerprint)

    try:
        order = _build_order(db, customer, data)
        order.id = uuid7()  # assigned now: the payment reference is derived from it
        order.idempotency_key = idempotency_key
        order.request_fingerprint = fingerprint if idempotency_key else None
        if data.payment_method is not None:
            assert gateway is not None
            _charge(order, customer, data.payment_method, gateway)
        db.add(order)
        db.commit()
    except IntegrityError:
        db.rollback()
        # Lost a race with a concurrent request using the same key: return its order.
        if idempotency_key:
            existing = _find_by_idempotency_key(db, customer, idempotency_key)
            if existing is not None:
                return _replay(db, existing, fingerprint)
        raise
    except BaseException:
        db.rollback()
        raise
    return CheckoutResult(order=reload_order(db, order.id), replayed=False)


def create_order(db: Session, customer: User, data: OrderCreate) -> Order:
    """Place an order without an idempotency key (kept for existing callers)."""
    return checkout(db, customer, data).order


def _date_range(stmt, created_from: date | None, created_to: date | None):
    """Inclusive calendar days (UTC) on Order.created_at."""
    if created_from and created_to and created_from > created_to:
        raise UnprocessableError("created_from cannot be after created_to")
    if created_from is not None:
        stmt = stmt.where(Order.created_at >= datetime.combine(created_from, time.min, tzinfo=timezone.utc))
    if created_to is not None:
        end = datetime.combine(created_to + timedelta(days=1), time.min, tzinfo=timezone.utc)
        stmt = stmt.where(Order.created_at < end)
    return stmt


def list_my_orders(
    db: Session,
    customer: User,
    status: OrderStatus | None,
    page: Pagination,
    created_from: date | None = None,
    created_to: date | None = None,
) -> Page[OrderRead]:
    """``created_from`` / ``created_to`` are inclusive calendar days (UTC)."""
    ensure_role(customer, UserRole.CUSTOMER)
    if created_from and created_to and created_from > created_to:
        raise UnprocessableError("created_from cannot be after created_to")
    stmt = (
        select(Order)
        .options(selectinload(Order.items))
        .where(Order.customer_id == customer.id)
        .order_by(Order.created_at.desc(), Order.id.desc())
    )
    if status is not None:
        stmt = stmt.where(Order.status == status)
    stmt = _date_range(stmt, created_from, created_to)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    orders = db.scalars(stmt.limit(page.limit).offset(page.offset)).all()
    return Page(
        items=[OrderRead.model_validate(o) for o in orders],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


def _build_order(db: Session, customer: User, data: OrderCreate) -> Order:
    """Validate the cart against the database and price it from database prices.
    Adds nothing to the session."""
    restaurant = db.get(Restaurant, data.restaurant_id)
    if restaurant is None:
        raise NotFoundError("Restaurant not found")
    if not restaurant.is_active:
        raise NotFoundError("Restaurant not found")
    if not restaurant.is_open:
        raise BadRequestError("This restaurant is currently closed")

    quantities: dict[UUID, int] = {}
    for line in data.items:
        quantities[line.menu_item_id] = quantities.get(line.menu_item_id, 0) + line.quantity
    if any(q > 50 for q in quantities.values()):
        raise BadRequestError("Maximum quantity per item is 50")

    menu_items = {
        m.id: m
        for m in db.scalars(
            select(MenuItem).where(
                MenuItem.id.in_(quantities), MenuItem.restaurant_id == restaurant.id
            )
        )
    }
    missing = set(quantities) - set(menu_items)
    if missing:
        raise BadRequestError(
            f"Menu items not found at this restaurant: {sorted(str(m) for m in missing)}"
        )
    unavailable = [m.name for m in menu_items.values() if not m.is_available]
    if unavailable:
        raise BadRequestError(f"Currently unavailable: {', '.join(unavailable)}")

    order = Order(
        customer_id=customer.id,
        restaurant_id=restaurant.id,
        status=OrderStatus.PENDING_PAYMENT,
        delivery_address=data.delivery_address,
        notes=data.notes,
        total_amount=Decimal("0.00"),
    )
    total = Decimal("0.00")
    for menu_item_id, quantity in quantities.items():
        menu_item = menu_items[menu_item_id]
        order.items.append(
            OrderItem(
                menu_item_id=menu_item.id,
                name=menu_item.name,
                unit_price=menu_item.price,  # price always comes from the server
                quantity=quantity,  # subtotal is generated by the database
            )
        )
        total += menu_item.price * quantity
    order.total_amount = total.quantize(Decimal("0.01"))

    # The client's total is never used for charging, only compared, so a stale or
    # tampered cart can't be charged an amount the customer didn't see.
    if data.expected_total is not None and data.expected_total != order.total_amount:
        raise ConflictError(
            f"Cart total is out of date: expected {data.expected_total}, "
            f"current total is {order.total_amount}. Nothing was charged."
        )
    order.events.append(
        OrderStatusEvent(status=OrderStatus.PENDING_PAYMENT, actor_id=customer.id)
    )
    return order


def _transition(db: Session, order: Order, user: User, new: OrderStatus, actor: Actor) -> Order:
    """Validate against the central table, write with compare-and-set, then record the
    audit event (and refund if needed) in the same transaction."""
    current = order.status
    lifecycle.check_transition(current, new, actor)
    lifecycle.compare_and_set(db, order, current, status=new, status_updated_at=utcnow())
    apply_status(order, new, user)  # status already set: adds event + refund only
    db.commit()
    return reload_order(db, order.id)


def cancel_order(db: Session, customer: User, order_id: UUID) -> Order:
    ensure_role(customer, UserRole.CUSTOMER)
    order = load_order(db, order_id, lock=True)
    if order is None or order.customer_id != customer.id:
        raise NotFoundError("Order not found")
    if OrderStatus.CANCELLED not in lifecycle.TRANSITIONS.get(order.status, {}):
        raise ConflictError(
            f"An order that is '{order.status.value}' can no longer be cancelled"
        )
    return _transition(db, order, customer, OrderStatus.CANCELLED, Actor.CUSTOMER)


# ---- owner / delivery partner ---------------------------------------------


def update_status(
    db: Session, actor: User, order_id: UUID, new_status: OrderStatus
) -> Order:
    order = load_order(db, order_id, lock=True)
    if order is None:
        raise NotFoundError("Order not found")

    if actor.role == UserRole.OWNER:
        if order.restaurant.owner_id != actor.id:
            raise NotFoundError("Order not found")
        kind = Actor.OWNER
    elif actor.role == UserRole.DELIVERY_PARTNER:
        if order.delivery_partner_id != actor.id:
            raise ForbiddenError("This order is not assigned to you")
        kind = Actor.COURIER
    else:
        raise ForbiddenError("Customers can only cancel their own orders")
    return _transition(db, order, actor, new_status, kind)


def assign_delivery(db: Session, owner: User, order_id: UUID, partner_id: UUID) -> Order:
    """Owner assigns (or, before pickup, reassigns) an active delivery partner."""
    ensure_role(owner, UserRole.OWNER)
    order = load_order(db, order_id, lock=True)
    if order is None or order.restaurant.owner_id != owner.id:
        raise NotFoundError("Order not found")
    if order.status not in lifecycle.ASSIGNABLE:
        raise ConflictError(
            f"A delivery partner cannot be assigned while the order is '{order.status.value}'"
        )
    partner = db.get(User, partner_id)
    if partner is None or partner.role != UserRole.DELIVERY_PARTNER or not partner.is_active:
        raise UnprocessableError("Not an active delivery partner")
    if order.delivery_partner_id == partner.id:
        return reload_order(db, order.id)  # idempotent
    lifecycle.compare_and_set(db, order, order.status, delivery_partner_id=partner.id)
    db.commit()
    return reload_order(db, order.id)


def list_my_deliveries(
    db: Session, partner: User, status: OrderStatus | None, page: Pagination
) -> Page[OrderRead]:
    ensure_role(partner, UserRole.DELIVERY_PARTNER)
    stmt = (
        select(Order)
        .options(selectinload(Order.items))
        .where(Order.delivery_partner_id == partner.id)
        .order_by(Order.created_at.desc(), Order.id.desc())
    )
    if status is not None:
        stmt = stmt.where(Order.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    orders = db.scalars(stmt.limit(page.limit).offset(page.offset)).all()
    return Page(
        items=[OrderRead.model_validate(o) for o in orders],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


def claim_order(db: Session, partner: User, order_id: UUID) -> Order:
    ensure_role(partner, UserRole.DELIVERY_PARTNER)
    # Row lock: if two couriers claim at once, the second sees the first one's claim.
    order = load_order(db, order_id, lock=True)
    if order is None or not can_view(order, partner):
        if order is not None and order.delivery_partner_id is not None:
            raise ConflictError("This order has already been claimed")
        raise NotFoundError("Order not found")
    if order.status != OrderStatus.READY_FOR_PICKUP:
        raise ConflictError("Order is not ready for pickup")
    order.delivery_partner_id = partner.id
    db.commit()
    return reload_order(db, order_id)


# ---- listings --------------------------------------------------------------


def list_orders(
    db: Session,
    user: User,
    status: OrderStatus | None,
    limit: int,
    offset: int,
    created_from: date | None = None,
    created_to: date | None = None,
) -> list[Order]:
    stmt = (
        select(Order)
        .options(selectinload(Order.items))
        .order_by(Order.created_at.desc(), Order.id.desc())
    )
    if user.role == UserRole.CUSTOMER:
        stmt = stmt.where(Order.customer_id == user.id)
    elif user.role == UserRole.OWNER:
        stmt = stmt.where(
            Order.restaurant_id.in_(
                select(Restaurant.id).where(Restaurant.owner_id == user.id)
            )
        )
    else:
        stmt = stmt.where(Order.delivery_partner_id == user.id)
    if status is not None:
        stmt = stmt.where(Order.status == status)
    stmt = _date_range(stmt, created_from, created_to)
    return list(db.scalars(stmt.limit(limit).offset(offset)).all())


def list_available_orders(db: Session, limit: int, offset: int) -> list[Order]:
    stmt = (
        select(Order)
        .options(selectinload(Order.items))
        .where(
            Order.status == OrderStatus.READY_FOR_PICKUP,
            Order.delivery_partner_id.is_(None),
        )
        .order_by(Order.updated_at, Order.id)
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(stmt).all())
