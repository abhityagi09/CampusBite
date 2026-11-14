"""Final-phase verification: deterministic AI figures, windowed AI rate limit, extra reminder
eligibility cases, restart survival and scheduler failure recovery. OpenAI is never called."""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import SecretStr
from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError

from app import worker
from app.core.config import settings
from app.database.session import get_db
from app.main import app
from app.models import Order, ReminderLog, ReminderType, User
from app.services import ai_service
from app.services import reminder_service as rs
from app.services.notifications import MockNotifier
from tests.conftest import deliver, pay, place_order, set_status

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)  # a Wednesday; week starts Mon 2026-11-09


@pytest.fixture
def db(client):
    s = next(app.dependency_overrides[get_db]())
    yield s
    s.close()


def _set_created(db, oid, when):
    db.execute(update(Order).where(Order.id == uuid.UUID(oid)).values(created_at=when))
    db.commit()


# ------------------------------------------------------------------ AI: exact figures


def test_ai_context_figures_are_exact(client, db, owner, customer, courier, restaurant):
    a = deliver(client, owner, customer, courier, restaurant)  # 2 Burger + 1 Fries = 13.25, paid
    b = place_order(client, customer, restaurant, items=(("Burger", 1),))["id"]  # 5.50
    pay(client, customer, b)
    client.post(f"/api/v1/orders/{b}/cancel", headers=customer)  # cancelled -> refunded
    c = place_order(client, customer, restaurant, items=(("Fries", 3),))["id"]  # 6.75 paid, placed
    pay(client, customer, c)
    d = place_order(client, customer, restaurant, items=(("Burger", 2),))["id"]  # 11.00 unpaid
    for oid, when in ((a, NOW - timedelta(days=1, hours=3)), (b, NOW - timedelta(hours=4)),
                      (c, NOW - timedelta(days=10)), (d, NOW - timedelta(hours=2))):
        _set_created(db, oid, when)

    me = db.scalar(select(User).where(User.email == "customer@example.com"))
    ctx = ai_service.build_context(db, me, NOW)
    f = ctx["facts"]
    assert f["orders_included"] == 4
    assert f["week_starts_utc"] == "2026-11-09"
    assert f["spent_this_week"] == "13.25"  # only A: B refunded, C last week, D unpaid
    assert f["spent_last_30_days"] == "20.00" and f["spent_total_paid"] == "20.00"  # A + C
    assert f["refunded_total"] == "5.50"
    assert {x["dish"]: x["quantity"] for x in f["most_ordered_dishes"]} == {"Burger": 4, "Fries": 4}  # B excluded
    assert {p["id"] for p in f["pending_orders"]} == {c[-8:], d[-8:]}
    assert f["orders_by_status"] == {"delivered": 1, "cancelled": 1, "placed": 1, "pending_payment": 1}
    assert f["last_five_order_ids"] == [d[-8:], b[-8:], a[-8:], c[-8:]]  # newest first
    first = ctx["orders_newest_first"][0]
    assert first["total"] == "11.00" and first["payment"] == "none"
    assert Decimal(ctx["orders_newest_first"][2]["items"][0]["subtotal"]) == Decimal("11.00")


def test_ai_rate_limit_uses_a_sliding_window(client, owner, customer, courier, restaurant, monkeypatch):
    deliver(client, owner, customer, courier, restaurant)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr("sk-test"))
    monkeypatch.setattr(settings, "AI_RATE_LIMIT_REQUESTS", 2)
    monkeypatch.setattr(settings, "AI_RATE_LIMIT_WINDOW_SECONDS", 3600)
    ai_service._calls.clear()
    clock = [1000.0]
    monkeypatch.setattr(ai_service, "_clock", lambda: clock[0])
    monkeypatch.setattr(ai_service, "complete", lambda messages: "ok")
    ask = lambda: client.post("/api/v1/ai/insights", json={"question": "What did I order?"}, headers=customer)  # noqa: E731

    assert ask().status_code == 200
    clock[0] += 600
    assert ask().status_code == 200
    clock[0] += 600
    limited = ask()
    assert limited.status_code == 429 and limited.json() == {"detail": limited.json()["detail"]}
    assert int(limited.headers["retry-after"]) == 2401  # first call leaves the window in 2400 s
    clock[0] += 2400  # first request has now left the window
    assert ask().status_code == 200


# ------------------------------------------------------------------ reminders


def _stale(db):
    db.expire_all()
    return db.scalars(select(ReminderLog).where(ReminderLog.reminder_type == ReminderType.ORDER_STALE)).all()


def _since(client, headers, oid):
    return datetime.fromisoformat(client.get(f"/api/v1/orders/{oid}", headers=headers).json()["status_updated_at"])


def test_young_orders_and_more_ineligible_states(client, db, owner, customer, courier, restaurant):
    young = place_order(client, customer, restaurant)["id"]
    pay(client, customer, young)
    since = _since(client, customer, young)
    rs.process_reminders(db, MockNotifier(), now=since + timedelta(minutes=14, seconds=59))
    assert _stale(db) == []

    cid = client.get("/api/v1/auth/me", headers=courier).json()["id"]
    assigned = place_order(client, customer, restaurant)["id"]
    pay(client, customer, assigned)
    for s in ("accepted", "preparing", "ready_for_pickup"):
        set_status(client, owner, assigned, s)
    client.post(f"/api/v1/orders/{assigned}/assign-delivery", json={"delivery_partner_id": cid}, headers=owner)
    out = deliver(client, owner, customer, courier, restaurant)
    refunded = deliver(client, owner, customer, courier, restaurant)
    rid = client.post(f"/api/v1/orders/{refunded}/refund-requests", json={"reason": "cold"}, headers=customer).json()["id"]
    client.post(f"/api/v1/refund-requests/{rid}/decision", json={"decision": "approve"}, headers=owner)
    set_status(client, owner, young, "accepted")  # young becomes accepted: new period, also young
    assert client.get(f"/api/v1/orders/{out}", headers=customer).json()["status"] == "delivered"

    # far in the future, only the (accepted, unattended) `young` order is eligible
    rs.process_reminders(db, MockNotifier(), now=datetime.now(timezone.utc) + timedelta(days=2))
    assert [str(l.order_id) for l in _stale(db)] == [young]


def test_reminders_survive_scheduler_restart(client, db, customer, restaurant):
    oid = place_order(client, customer, restaurant)["id"]
    pay(client, customer, oid)
    at = _since(client, customer, oid) + timedelta(minutes=16)
    sessions = lambda: next(app.dependency_overrides[get_db]())  # noqa: E731

    first = worker.run_once(session_factory=sessions, bind=db.get_bind(), now=at)
    assert first.sent >= 1
    # "restart": a brand-new scheduler and brand-new sessions, same database
    worker.build_scheduler(60)
    again = worker.run_once(session_factory=sessions, bind=db.get_bind(), now=at + timedelta(minutes=5))
    assert again.sent == 0
    logs = _stale(db)
    assert len(logs) == 1 and str(logs[0].order_id) == oid


def test_scheduler_database_failure_is_logged_and_recovered(client, db, customer, restaurant, monkeypatch, caplog):
    oid = place_order(client, customer, restaurant)["id"]
    pay(client, customer, oid)
    at = _since(client, customer, oid) + timedelta(minutes=16)

    def broken_session():
        raise OperationalError("SELECT 1", {}, Exception("database is down"))

    real = worker.run_once
    monkeypatch.setattr(worker, "run_once", lambda: real(session_factory=broken_session, bind=db.get_bind(), now=at))
    with caplog.at_level(logging.ERROR, logger="campusbite.worker"):
        worker._job()  # must not raise: the scheduler keeps running
    assert "reminder run failed" in caplog.text and "database is down" in caplog.text
    assert _stale(db) == []

    # next tick, database back: the missed reminder is created
    sessions = lambda: next(app.dependency_overrides[get_db]())  # noqa: E731
    monkeypatch.setattr(worker, "run_once", lambda: real(session_factory=sessions, bind=db.get_bind(), now=at))
    worker._job()
    assert [str(l.order_id) for l in _stale(db)] == [oid]


def test_threshold_is_configurable(client, db, customer, restaurant, monkeypatch):
    oid = place_order(client, customer, restaurant)["id"]
    pay(client, customer, oid)
    since = _since(client, customer, oid)
    monkeypatch.setattr(settings, "ORDER_REMINDER_THRESHOLD_MINUTES", 30)
    rs.process_reminders(db, MockNotifier(), now=since + timedelta(minutes=20))
    assert _stale(db) == []
    rs.process_reminders(db, MockNotifier(), now=since + timedelta(minutes=31))
    assert len(_stale(db)) == 1
