"""Database-level guarantees: these must hold even if application code is wrong.

Runs on in-memory SQLite with foreign keys switched on (or on PostgreSQL when
TEST_DATABASE_URL is set). CHECK constraints are exercised with raw SQL because the ORM
enum type already rejects unknown values before they reach the database.
"""

import os
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.models import (
    LedgerStatus,
    MenuItem,
    Order,
    OrderItem,
    PaymentLedger,
    RefundRequest,
    RefundStatus,
    ReminderLog,
    ReminderType,
    Restaurant,
    Review,
    TransactionType,
    User,
    UserRole,
)
from app.models.mixins import uuid7


@pytest.fixture
def db():
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        engine = create_engine(url)
        Base.metadata.drop_all(engine)
    else:
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):  # SQLite ignores foreign keys unless asked
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    if url:
        Base.metadata.drop_all(engine)
    engine.dispose()


def _user(db, email, role=UserRole.CUSTOMER):
    u = User(name=email, email=email, password_hash="x", role=role)
    db.add(u)
    db.flush()
    return u


@pytest.fixture
def world(db):
    owner = _user(db, "o@x.com", UserRole.OWNER)
    cust = _user(db, "c@x.com")
    other = _user(db, "c2@x.com")
    rest = Restaurant(owner_id=owner.id, name="R")
    rest2 = Restaurant(owner_id=owner.id, name="R2")
    db.add_all([rest, rest2])
    db.flush()
    item = MenuItem(restaurant_id=rest.id, name="Burger", price=Decimal("5.50"))
    order = Order(
        customer_id=cust.id, restaurant_id=rest.id, total_amount=Decimal("11.00"),
        delivery_address="Hostel",
    )
    db.add_all([item, order])
    db.commit()
    return dict(owner=owner, cust=cust, other=other, rest=rest, rest2=rest2, item=item, order=order)


def _fails(db, obj_or_sql):
    with pytest.raises(IntegrityError):
        if isinstance(obj_or_sql, str):
            db.execute(text(obj_or_sql))
        else:
            db.add(obj_or_sql)
        db.flush()
    db.rollback()


def test_uuid_keys_and_timestamps(world):
    o = world["order"]
    assert isinstance(o.id, uuid.UUID) and o.id.version == 7
    assert o.created_at.tzinfo is not None and o.updated_at.tzinfo is not None


def test_uuid7_is_unique_and_monotonic():
    ids = [uuid7() for _ in range(20000)]
    assert len(set(ids)) == len(ids)
    assert ids == sorted(ids)
    assert all(i.version == 7 and i.variant == uuid.RFC_4122 for i in ids[:100])


def test_money_round_trips_as_decimal(db, world):
    db.expire_all()
    assert world["item"].price == Decimal("5.50")
    assert isinstance(world["order"].total_amount, Decimal)


def test_one_review_per_order(db, world):
    w = world
    db.add(Review(order_id=w["order"].id, customer_id=w["cust"].id, restaurant_id=w["rest"].id, rating=5))
    db.commit()
    _fails(db, Review(order_id=w["order"].id, customer_id=w["cust"].id, restaurant_id=w["rest"].id, rating=4))


def test_review_must_match_the_orders_customer_and_restaurant(db, world):
    w = world
    _fails(db, Review(order_id=w["order"].id, customer_id=w["other"].id, restaurant_id=w["rest"].id, rating=5))
    _fails(db, Review(order_id=w["order"].id, customer_id=w["cust"].id, restaurant_id=w["rest2"].id, rating=5))


def test_review_rating_range(db, world):
    w = world
    for rating in (0, 6):
        _fails(db, Review(order_id=w["order"].id, customer_id=w["cust"].id,
                          restaurant_id=w["rest"].id, rating=rating))


def test_one_reminder_per_type_per_order(db, world):
    oid = world["order"].id
    db.add(ReminderLog(order_id=oid, reminder_type=ReminderType.ORDER_READY))
    db.commit()
    _fails(db, ReminderLog(order_id=oid, reminder_type=ReminderType.ORDER_READY))
    db.add(ReminderLog(order_id=oid, reminder_type=ReminderType.REVIEW_REQUEST))  # other type is fine
    db.commit()


def test_only_one_open_refund_request_per_order(db, world):
    w = world

    def req(status=RefundStatus.REQUESTED):
        return RefundRequest(order_id=w["order"].id, customer_id=w["cust"].id, reason="cold food", status=status)

    first = req()
    db.add(first)
    db.commit()
    _fails(db, req())  # a second open one
    first.status = RefundStatus.REJECTED
    db.commit()
    db.add(req())  # allowed again once the first is closed
    db.commit()


def test_refund_request_customer_must_own_order_and_reason_not_blank(db, world):
    w = world
    _fails(db, RefundRequest(order_id=w["order"].id, customer_id=w["other"].id, reason="x"))
    _fails(db, RefundRequest(order_id=w["order"].id, customer_id=w["cust"].id, reason="   "))


def test_ledger_amount_positive_and_reference_unique_when_present(db, world):
    oid = world["order"].id

    def entry(amount, ref):
        return PaymentLedger(order_id=oid, amount=Decimal(amount), reference=ref,
                             transaction_type=TransactionType.CHARGE, status=LedgerStatus.COMPLETED)

    _fails(db, entry("0", "A"))
    _fails(db, entry("-1.00", "A"))
    db.add_all([entry("5.00", None), entry("5.00", None)])  # NULL references never collide
    db.commit()
    db.add(entry("5.00", "REF-1"))
    db.commit()
    _fails(db, entry("5.00", "REF-1"))


def test_ledger_rows_survive_no_order_deletion(db, world):
    """Financial history blocks deleting its order (no ON DELETE CASCADE)."""
    oid = world["order"].id
    db.add(PaymentLedger(order_id=oid, amount=Decimal("1.00"),
                         transaction_type=TransactionType.CHARGE, status=LedgerStatus.COMPLETED))
    db.commit()
    _fails(db, f"DELETE FROM orders WHERE id = '{oid.hex}'" if db.bind.dialect.name == "sqlite"
           else f"DELETE FROM orders WHERE id = '{oid}'")


def test_order_item_quantity_positive_unique_line_and_computed_subtotal(db, world):
    w = world
    ok = OrderItem(order_id=w["order"].id, menu_item_id=w["item"].id, name="Burger",
                   quantity=3, unit_price=Decimal("5.50"))
    db.add(ok)
    db.commit()
    db.refresh(ok)
    assert ok.subtotal == Decimal("16.50")  # computed by the database
    _fails(db, OrderItem(order_id=w["order"].id, menu_item_id=w["item"].id, name="Burger",
                         quantity=1, unit_price=Decimal("5.50")))  # same item twice in an order
    _fails(db, OrderItem(order_id=w["order"].id, menu_item_id=None, name="X",
                         quantity=0, unit_price=Decimal("1.00")))


def test_menu_price_and_order_total_checks(db, world):
    w = world
    _fails(db, MenuItem(restaurant_id=w["rest"].id, name="Free", price=Decimal("0")))
    _fails(db, Order(customer_id=w["cust"].id, restaurant_id=w["rest"].id,
                     total_amount=Decimal("-1"), delivery_address="x"))


def test_email_must_be_lowercase_and_unique(db, world):
    _fails(db, User(name="n", email="Mixed@X.com", password_hash="x", role=UserRole.CUSTOMER))
    _fails(db, User(name="n", email="c@x.com", password_hash="x", role=UserRole.CUSTOMER))


def test_enum_columns_reject_unknown_values_in_the_database(db, world):
    oid = world["order"].id
    key = oid.hex if db.bind.dialect.name == "sqlite" else str(oid)
    _fails(db, f"UPDATE orders SET status = 'teleported' WHERE id = '{key}'")
    _fails(db, f"UPDATE users SET role = 'admin'")
    _fails(db, f"INSERT INTO reminder_logs (id, order_id, reminder_type, sent_at) "
               f"VALUES ('{uuid.uuid4().hex if db.bind.dialect.name == 'sqlite' else uuid.uuid4()}', '{key}', 'smoke_signal', CURRENT_TIMESTAMP)")
