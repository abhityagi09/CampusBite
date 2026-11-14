from decimal import Decimal

from sqlalchemy import case, desc, func, select
from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenError
from app.models import (
    LedgerStatus,
    Order,
    OrderItem,
    OrderStatus,
    PaymentLedger,
    Restaurant,
    Review,
    TransactionType,
    User,
    UserRole,
)
from app.schemas.statistics import (
    CustomerRestaurantSummary,
    CustomerStats,
    RestaurantPerformance,
    DeliveryStats,
    OwnerStats,
    TopItem,
)


# Refunded orders were delivered too: revenue is gross, refunds are reported separately.
DELIVERED_LIKE = (OrderStatus.DELIVERED, OrderStatus.REFUNDED)


def _dec(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def _by_status(db: Session, *conditions) -> dict[str, int]:
    rows = db.execute(
        select(Order.status, func.count(Order.id)).where(*conditions).group_by(Order.status)
    ).all()
    return {status.value: count for status, count in rows}


_DELIVERED_AMOUNT = case((Order.status.in_(DELIVERED_LIKE), Order.total_amount), else_=0)


def _refunds_on_delivered(db: Session, *conditions):
    return db.scalar(
        select(func.sum(PaymentLedger.amount))
        .join(Order, Order.id == PaymentLedger.order_id)
        .where(
            *conditions,
            Order.status.in_(DELIVERED_LIKE),
            PaymentLedger.transaction_type == TransactionType.REFUND,
            PaymentLedger.status == LedgerStatus.COMPLETED,
        )
    )


def customer_stats(db: Session, user: User) -> CustomerStats:
    by_status = _by_status(db, Order.customer_id == user.id)
    spent = db.scalar(
        select(func.sum(Order.total_amount)).where(
            Order.customer_id == user.id, Order.status.in_(DELIVERED_LIKE)
        )
    )
    refunded = _refunds_on_delivered(db, Order.customer_id == user.id)
    count = func.count(Order.id)
    top = db.execute(
        select(Restaurant.id, Restaurant.name, count, func.sum(_DELIVERED_AMOUNT))
        .join(Order, Order.restaurant_id == Restaurant.id)
        .where(Order.customer_id == user.id)
        .group_by(Restaurant.id, Restaurant.name)
        .order_by(desc(count), Restaurant.name)
        .limit(5)
    ).all()
    return CustomerStats(
        total_orders=sum(by_status.values()),
        orders_by_status=by_status,
        total_spent=_dec(spent),
        total_refunded=_dec(refunded),
        net_spent=_dec(spent) - _dec(refunded),
        top_restaurants=[
            CustomerRestaurantSummary(restaurant_id=r, name=n, order_count=c, spent=_dec(s))
            for r, n, c, s in top
        ],
    )


def owner_stats(db: Session, user: User) -> OwnerStats:
    restaurant_ids = select(Restaurant.id).where(Restaurant.owner_id == user.id)
    restaurant_count = db.scalar(
        select(func.count(Restaurant.id)).where(Restaurant.owner_id == user.id)
    )
    in_mine = Order.restaurant_id.in_(restaurant_ids)

    by_status = _by_status(db, in_mine)
    revenue = db.scalar(
        select(func.sum(Order.total_amount)).where(in_mine, Order.status.in_(DELIVERED_LIKE))
    )
    avg_rating, review_count = db.execute(
        select(func.avg(Review.rating), func.count(Review.id)).where(
            Review.restaurant_id.in_(restaurant_ids)
        )
    ).one()

    quantity = func.sum(OrderItem.quantity)
    top_rows = db.execute(
        select(OrderItem.name, quantity)
        .join(Order, Order.id == OrderItem.order_id)
        .where(in_mine, Order.status.in_(DELIVERED_LIKE))
        .group_by(OrderItem.name)
        .order_by(desc(quantity), OrderItem.name)
        .limit(5)
    ).all()

    refunded = _refunds_on_delivered(db, in_mine)
    return OwnerStats(
        restaurant_count=restaurant_count or 0,
        total_orders=sum(by_status.values()),
        orders_by_status=by_status,
        revenue=_dec(revenue),
        refunded=_dec(refunded),
        net_revenue=_dec(revenue) - _dec(refunded),
        restaurants=restaurant_performance(db, user),
        average_rating=round(float(avg_rating), 2) if avg_rating is not None else None,
        review_count=review_count or 0,
        top_items=[TopItem(name=n, quantity=int(q)) for n, q in top_rows],
    )


def restaurant_performance(db: Session, user: User) -> list[RestaurantPerformance]:
    from app.services.restaurant_service import _ratings

    rows = db.execute(
        select(
            Restaurant.id,
            Restaurant.name,
            Restaurant.is_active,
            func.count(Order.id),
            func.count(case((Order.status.in_(DELIVERED_LIKE), 1))),
            func.count(
                case((Order.status.in_([OrderStatus.CANCELLED, OrderStatus.REJECTED]), 1))
            ),
            func.sum(_DELIVERED_AMOUNT),
        )
        .outerjoin(Order, Order.restaurant_id == Restaurant.id)
        .where(Restaurant.owner_id == user.id)
        .group_by(Restaurant.id, Restaurant.name, Restaurant.is_active)
        .order_by(Restaurant.name, Restaurant.id)
    ).all()
    ratings = _ratings(db, [r[0] for r in rows])
    return [
        RestaurantPerformance(
            restaurant_id=rid,
            name=name,
            is_active=active,
            total_orders=total,
            delivered_orders=delivered,
            cancelled_or_rejected=lost,
            revenue=_dec(revenue),
            average_rating=ratings.get(rid, (None, 0))[0],
            review_count=ratings.get(rid, (None, 0))[1],
        )
        for rid, name, active, total, delivered, lost, revenue in rows
    ]


def delivery_stats(db: Session, user: User) -> DeliveryStats:
    mine = Order.delivery_partner_id == user.id
    completed = db.scalar(
        select(func.count(Order.id)).where(mine, Order.status.in_(DELIVERED_LIKE))
    )
    active = db.scalar(
        select(func.count(Order.id)).where(
            mine,
            Order.status.in_([OrderStatus.ASSIGNED, OrderStatus.OUT_FOR_DELIVERY]),
        )
    )
    available = db.scalar(
        select(func.count(Order.id)).where(
            Order.status == OrderStatus.READY,
            Order.delivery_partner_id.is_(None),
        )
    )
    return DeliveryStats(
        completed_deliveries=completed or 0,
        active_deliveries=active or 0,
        available_orders=available or 0,
    )


def statistics_for(db: Session, user: User):
    if user.role == UserRole.CUSTOMER:
        return customer_stats(db, user)
    if user.role == UserRole.OWNER:
        return owner_stats(db, user)
    if user.role == UserRole.DELIVERY_PARTNER:
        return delivery_stats(db, user)
    raise ForbiddenError()
