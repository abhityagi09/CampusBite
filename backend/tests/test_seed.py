"""The development seed: fictional data in every lifecycle state, idempotent."""

from sqlalchemy import func, select

from app.database.session import get_db
from app.main import app
from app.models import Order, PaymentStatus, RefundRequest, RefundStatus, Review, User
from app.seed import DEMO_ORDERS, seed


def test_seed_creates_demo_data_once(client):
    db = next(app.dependency_overrides[get_db]())
    try:
        first = seed(db)
        assert first["users"] == 7 and first["restaurants"] == 3 and first["demo_orders"] == len(DEMO_ORDERS)
        statuses = dict(db.execute(select(Order.status, func.count()).group_by(Order.status)).all())
        assert {s.value: n for s, n in statuses.items()} == {
            "placed": 1, "accepted": 1, "preparing": 1, "ready": 1, "assigned": 1, "out_for_delivery": 1,
            "delivered": 3, "refunded": 1, "cancelled": 1,
        }
        assert db.scalar(select(func.count()).select_from(Review)) == 1
        refunds = {r.status for r in db.scalars(select(RefundRequest))}
        assert refunds == {RefundStatus.REQUESTED, RefundStatus.PROCESSED}
        refunded = db.scalar(select(Order).where(Order.status == "refunded"))
        assert refunded.payment.status == PaymentStatus.REFUNDED

        again = seed(db)  # idempotent
        assert again == {"users": 0, "restaurants": 0, "menu_items": 0, "demo_orders": 0}
        assert db.scalar(select(func.count()).select_from(Order)) == len(DEMO_ORDERS)
        assert db.scalar(select(func.count()).select_from(User)) == 7
    finally:
        db.close()


def test_seeded_accounts_can_log_in(client):
    db = next(app.dependency_overrides[get_db]())
    try:
        seed(db)
    finally:
        db.close()
    for email in ("asha@example.com", "grill.owner@example.com", "dev.courier@example.com"):
        resp = client.post("/api/v1/auth/login/json", json={"email": email, "password": "Campus123"})
        assert resp.status_code == 200, email
