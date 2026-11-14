"""Idle-order (ORDER_STALE) reminders: status periods, idempotency, worker, owner APIs."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.database.session import get_db
from app.main import app
from app.models import ReminderLog, ReminderType
from app.services import reminder_service as rs
from app.services.notifications import MockNotifier
from app.worker import build_scheduler, run_once
from tests.conftest import deliver, pay, place_order, set_status

R = "/api/v1/owner/reminders"
LATER = timedelta(minutes=16)


@pytest.fixture
def db(client):
    s = next(app.dependency_overrides[get_db]())
    yield s
    s.close()


def now():
    return datetime.now(timezone.utc)


def stale_logs(db):
    db.expire_all()
    return db.scalars(select(ReminderLog).where(ReminderLog.reminder_type == ReminderType.ORDER_STALE)
                      .order_by(ReminderLog.sent_at)).all()


def run(db, at):
    return rs.process_reminders(db, MockNotifier(), now=at)


def paid_order(client, customer, restaurant):
    oid = place_order(client, customer, restaurant)["id"]
    pay(client, customer, oid)
    return oid


def order(client, headers, oid):
    return client.get(f"/api/v1/orders/{oid}", headers=headers).json()


# ------------------------------------------------------------------ status_updated_at


def test_status_updated_at_tracks_status_changes_only(client, owner, customer, courier, restaurant):
    oid = place_order(client, customer, restaurant)["id"]
    created = order(client, customer, oid)
    assert created["status_updated_at"] is not None
    assert created["status_updated_at"].endswith(("Z", "+00:00"))  # timezone-aware UTC

    pay(client, customer, oid)
    placed = order(client, customer, oid)["status_updated_at"]
    assert placed > created["status_updated_at"]
    for s in ("accepted", "preparing", "ready_for_pickup"):
        set_status(client, owner, oid, s)
    ready = order(client, customer, oid)["status_updated_at"]
    assert ready > placed

    cid = client.get("/api/v1/auth/me", headers=courier).json()["id"]
    client.post(f"/api/v1/orders/{oid}/assign-delivery", json={"delivery_partner_id": cid}, headers=owner)
    after = order(client, customer, oid)
    assert after["delivery_partner_id"] == cid and after["status_updated_at"] == ready  # unrelated change


# ------------------------------------------------------------------ generation rules


def test_one_reminder_per_idle_placed_and_accepted_order(client, db, owner, customer, restaurant):
    placed_id = paid_order(client, customer, restaurant)
    accepted_id = paid_order(client, customer, restaurant)
    set_status(client, owner, accepted_id, "accepted")

    assert run(db, now()).sent == 0  # not idle yet
    run(db, now() + LATER)
    logs = stale_logs(db)
    assert {(str(l.order_id), l.status_snapshot) for l in logs} == {(placed_id, "placed"), (accepted_id, "accepted")}
    rid = uuid.UUID(restaurant)
    for log in logs:
        assert log.restaurant_id == rid and log.status_updated_at_snapshot is not None
        assert log.sent_at.tzinfo is not None

    for _ in range(3):  # repeated scheduler runs
        assert run(db, now() + LATER).sent == 0
    assert len(stale_logs(db)) == 2


def test_exactly_15_minutes_is_not_more_than_15(client, db, customer, restaurant):
    oid = paid_order(client, customer, restaurant)
    since = datetime.fromisoformat(order(client, customer, oid)["status_updated_at"])
    run(db, since + timedelta(minutes=15))
    assert stale_logs(db) == []
    run(db, since + timedelta(minutes=15, seconds=1))
    assert len(stale_logs(db)) == 1


def test_new_eligible_status_period_reminds_again(client, db, owner, customer, restaurant):
    oid = paid_order(client, customer, restaurant)
    run(db, now() + LATER)  # idle while placed
    set_status(client, owner, oid, "accepted")  # new status period starts now
    run(db, now() + LATER + timedelta(minutes=1))
    logs = stale_logs(db)
    assert [l.status_snapshot for l in logs] == ["placed", "accepted"]
    assert logs[0].event_key != logs[1].event_key
    run(db, now() + timedelta(hours=2))
    assert len(stale_logs(db)) == 2  # still one per period


def test_ineligible_orders_never_get_stale_reminders(client, db, owner, customer, courier, restaurant):
    place_order(client, customer, restaurant)  # pending_payment
    for path in (["accepted", "preparing"], ["accepted", "preparing", "ready_for_pickup"], ["rejected"]):
        oid = paid_order(client, customer, restaurant)
        for s in path:
            set_status(client, owner, oid, s)
    cancelled = paid_order(client, customer, restaurant)
    client.post(f"/api/v1/orders/{cancelled}/cancel", headers=customer)
    deliver(client, owner, customer, courier, restaurant)
    run(db, now() + timedelta(days=1))
    assert stale_logs(db) == []


def test_concurrent_runs_record_one_reminder(client, db, customer, restaurant):
    paid_order(client, customer, restaurant)
    at = now() + LATER
    worker_a = rs.due_reminders(db, at)  # both workers computed the same to-do list
    worker_b = rs.due_reminders(db, at)
    stale = [r for r in worker_a if r.kind == ReminderType.ORDER_STALE]
    assert rs.send_reminder(db, MockNotifier(), stale[0]) == "sent"
    other = [r for r in worker_b if r.kind == ReminderType.ORDER_STALE][0]
    assert rs.send_reminder(db, MockNotifier(), other) == "duplicate"  # UNIQUE event_key
    assert len(stale_logs(db)) == 1


# ------------------------------------------------------------------ worker


def test_worker_run_once_and_scheduler_config(client, db, customer, restaurant):
    result = run_once(session_factory=lambda: next(app.dependency_overrides[get_db]()), bind=db.get_bind())
    assert result is not None and result.failed == 0
    sched = build_scheduler(60)
    job = sched.get_job("order-reminders")
    assert job.trigger.interval == timedelta(seconds=60)
    assert sched._job_defaults["max_instances"] == 1 and sched._job_defaults["coalesce"] is True
    assert job.next_run_time is not None  # runs immediately on start (catch-up after restart)


# ------------------------------------------------------------------ owner API


def test_owner_reminder_api(client, db, make_user, owner, customer, restaurant):
    a = paid_order(client, customer, restaurant)
    b = paid_order(client, customer, restaurant)
    run(db, now() + LATER)

    page = client.get(R, headers=owner).json()
    assert page["total"] == 2 and {i["order_id"] for i in page["items"]} == {a, b}
    assert page["items"][0]["created_at"] >= page["items"][1]["created_at"]  # newest first
    item = page["items"][0]
    assert item["restaurant_name"] == "Campus Grill" and item["status_snapshot"] == "placed"
    assert item["is_read"] is False and item["still_waiting"] is True
    # wall-clock creation time vs. the simulated "16 minutes later" run: only presence is checkable
    assert item["overdue_minutes_at_reminder"] is not None and item["status_updated_at_snapshot"]
    assert client.get(f"{R}/unread-count", headers=owner).json() == {"unread": 2}

    marked = client.patch(f"{R}/{item['id']}/read", headers=owner)
    assert marked.status_code == 200 and marked.json()["is_read"] is True
    again = client.patch(f"{R}/{item['id']}/read", headers=owner).json()
    assert again["read_at"] == marked.json()["read_at"]  # idempotent
    assert client.get(f"{R}/unread-count", headers=owner).json() == {"unread": 1}
    assert client.get(f"{R}?unread_only=true", headers=owner).json()["total"] == 1
    assert len(client.get(f"{R}?limit=1", headers=owner).json()["items"]) == 1

    set_status(client, owner, a, "accepted")
    states = {i["order_id"]: i for i in client.get(R, headers=owner).json()["items"]}
    assert states[a]["still_waiting"] is False and states[a]["current_order_status"] == "accepted"

    other = make_user("owner", "o2@example.com")
    assert client.get(R, headers=other).json()["total"] == 0
    assert client.get(f"{R}/unread-count", headers=other).json() == {"unread": 0}
    assert client.patch(f"{R}/{item['id']}/read", headers=other).status_code == 404
    assert client.patch(f"{R}/{uuid.uuid4()}/read", headers=owner).status_code == 404
    for path in (R, f"{R}/unread-count"):
        assert client.get(path, headers=customer).status_code == 403
        assert client.get(path).status_code == 401
    assert client.patch(f"{R}/{item['id']}/read", headers=customer).status_code == 403
