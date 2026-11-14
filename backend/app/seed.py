"""Sample data for local development.

    python -m app.seed            (inside the backend container:  docker compose exec backend python -m app.seed)

Creates fictional users, restaurants, menus and demo orders in every lifecycle state
(placed/accepted orders already idle for 20 minutes for the reminder demo, a delivered order to
review/refund, a pending refund request, a refunded and a cancelled order).

Idempotent: users are matched by e-mail, restaurants by (owner, name) and demo orders by their
idempotency key, so running it again adds nothing. Refuses to run when ENVIRONMENT=production.
Every account's password is SEED_PASSWORD below (development only).
"""

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.database.session import SessionLocal
from app.models import MenuItem, Order, Restaurant, User, UserRole
from app.models.mixins import utcnow

SEED_PASSWORD = "Campus123"

USERS = [
    ("Asha Customer", "asha@example.com", UserRole.CUSTOMER),
    ("Ben Customer", "ben@example.com", UserRole.CUSTOMER),
    ("Chen Customer", "chen@example.com", UserRole.CUSTOMER),
    ("Grill Owner", "grill.owner@example.com", UserRole.OWNER),
    ("Dosa Owner", "dosa.owner@example.com", UserRole.OWNER),
    ("Dev Courier", "dev.courier@example.com", UserRole.DELIVERY_PARTNER),
    ("Eva Courier", "eva.courier@example.com", UserRole.DELIVERY_PARTNER),
]

RESTAURANTS = [
    ("grill.owner@example.com", "Campus Grill", "American", "Block A, Ground floor", [
        ("Classic Burger", "Mains", "5.50"), ("Veggie Burger", "Mains", "5.00"),
        ("Fries", "Sides", "2.25"), ("Cola", "Drinks", "1.50"),
    ]),
    ("grill.owner@example.com", "Late Night Bites", "Snacks", "Hostel 2 Lobby", [
        ("Cheese Toastie", "Snacks", "3.00"), ("Instant Noodles", "Snacks", "2.50"),
        ("Cold Coffee", "Drinks", "2.00"),
    ]),
    ("dosa.owner@example.com", "Dosa Corner", "South Indian", "Library Lane", [
        ("Masala Dosa", "Mains", "4.00"), ("Idli (3 pcs)", "Mains", "3.00"),
        ("Filter Coffee", "Drinks", "1.20"), ("Vada", "Sides", "1.50"),
    ]),
]


def seed(db: Session) -> dict[str, int]:
    created = {"users": 0, "restaurants": 0, "menu_items": 0}
    users: dict[str, User] = {}
    password_hash = hash_password(SEED_PASSWORD)
    for name, email, role in USERS:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(name=name, email=email, role=role, password_hash=password_hash)
            db.add(user)
            created["users"] += 1
        users[email] = user
    db.flush()

    for owner_email, name, cuisine, location, items in RESTAURANTS:
        owner = users[owner_email]
        restaurant = db.scalar(
            select(Restaurant).where(Restaurant.owner_id == owner.id, Restaurant.name == name)
        )
        if restaurant is None:
            restaurant = Restaurant(owner_id=owner.id, name=name, cuisine=cuisine, location=location)
            db.add(restaurant)
            db.flush()
            created["restaurants"] += 1
            for item_name, category, price in items:
                db.add(MenuItem(restaurant_id=restaurant.id, name=item_name,
                                category=category, price=Decimal(price)))
                created["menu_items"] += 1
    db.commit()
    created["demo_orders"] = seed_demo_orders(db)
    return created


# ---- demo orders ---------------------------------------------------------------------
# Each demo order is created through the REAL services (checkout, lifecycle, refunds), so
# the data obeys every business rule. The idempotency key makes re-runs create nothing.
DEMO_CUSTOMER, DEMO_OWNER, DEMO_COURIER = "asha@example.com", "grill.owner@example.com", "dev.courier@example.com"
DEMO_RESTAURANT = "Campus Grill"
STALE = timedelta(minutes=20)  # older than the 15-minute reminder threshold
# key -> (target state, items as (dish, qty))
DEMO_ORDERS = [
    ("demo-placed-stale", "placed_stale", [("Classic Burger", 1), ("Cola", 1)]),
    ("demo-accepted-stale", "accepted_stale", [("Veggie Burger", 2)]),
    ("demo-preparing", "preparing", [("Fries", 2)]),
    ("demo-ready", "ready", [("Classic Burger", 2)]),
    ("demo-assigned", "assigned", [("Veggie Burger", 1), ("Fries", 1)]),
    ("demo-out-for-delivery", "out_for_delivery", [("Classic Burger", 1)]),
    ("demo-delivered", "delivered", [("Classic Burger", 2), ("Fries", 1)]),  # review / refund it live
    ("demo-reviewed", "reviewed", [("Veggie Burger", 1), ("Cola", 2)]),
    ("demo-refund-pending", "refund_pending", [("Fries", 3)]),              # owner approves/rejects live
    ("demo-refunded", "refunded", [("Classic Burger", 1), ("Cola", 1)]),
    ("demo-cancelled", "cancelled", [("Cola", 1)]),
]
PATHS = {
    "accepted_stale": ["accepted"], "preparing": ["accepted", "preparing"],
    "ready": ["accepted", "preparing", "ready"],
}
DELIVERY_STATES = {"assigned", "out_for_delivery", "delivered", "reviewed", "refund_pending", "refunded"}


def seed_demo_orders(db: Session) -> int:
    from app.models import OrderStatus
    from app.schemas.order import OrderCreate, OrderItemCreate
    from app.schemas.review import ReviewCreate
    from app.services import order_service, refund_service, review_service
    from app.services.payment_gateway import DummyPaymentGateway

    user = lambda e: db.scalar(select(User).where(User.email == e))  # noqa: E731
    customer, owner, courier = user(DEMO_CUSTOMER), user(DEMO_OWNER), user(DEMO_COURIER)
    restaurant = db.scalar(select(Restaurant).where(Restaurant.owner_id == owner.id,
                                                    Restaurant.name == DEMO_RESTAURANT))
    if restaurant is None or not restaurant.is_open:
        return 0
    menu = {m.name: m for m in db.scalars(select(MenuItem).where(MenuItem.restaurant_id == restaurant.id))}
    created = 0
    for key, state, items in DEMO_ORDERS:
        if any(not menu.get(dish) or not menu[dish].is_available for dish, _ in items):
            continue  # an owner changed the sample menu; skip rather than fail
        body = OrderCreate(
            restaurant_id=restaurant.id, delivery_address="Hostel 3, Room 204 (demo)", notes=f"[demo] {state}",
            payment_method="upi", items=[OrderItemCreate(menu_item_id=menu[d].id, quantity=q) for d, q in items],
        )
        result = order_service.checkout(db, customer, body, idempotency_key=key, gateway=DummyPaymentGateway())
        if result.replayed:
            continue  # already seeded: never touch it again
        created += 1
        oid = result.order.id
        if state == "cancelled":
            order_service.cancel_order(db, customer, oid)
            continue
        for status in PATHS.get(state, ["accepted", "preparing", "ready"] if state in DELIVERY_STATES else []):
            order_service.update_status(db, owner, oid, OrderStatus(status))
        if state in DELIVERY_STATES:
            order_service.assign_delivery(db, owner, oid, courier.id)
            if state != "assigned":
                order_service.update_status(db, courier, oid, OrderStatus.OUT_FOR_DELIVERY)
            if state not in ("assigned", "out_for_delivery"):
                order_service.update_status(db, courier, oid, OrderStatus.DELIVERED)
        if state == "reviewed":
            review_service.create_review(db, customer, ReviewCreate(order_id=oid, rating=5, comment="Hot and fast. (demo)"))
        if state in ("refund_pending", "refunded"):
            req = refund_service.request_refund(db, customer, oid, "Fries were cold. (demo)")
            if state == "refunded":
                refund_service.decide_refund(db, owner, req.id, "approve")
        if state.endswith("_stale"):  # make the reminder worker pick these up on its next tick
            db.execute(update(Order).where(Order.id == oid).values(status_updated_at=utcnow() - STALE))
            db.commit()
    return created


def main() -> None:
    if settings.ENVIRONMENT.lower() == "production":
        raise SystemExit("Refusing to seed a production database.")
    with SessionLocal() as db:
        created = seed(db)
    print(f"Seeded: {created}. All accounts use the password {SEED_PASSWORD!r}.")


if __name__ == "__main__":
    main()
