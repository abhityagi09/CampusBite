import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.database.session import get_db
from app.main import app
from app.models import ReminderLog, ReminderType
from app.models.mixins import utcnow
from app.services import reminder_service
from app.services.notifications import MockNotifier
from tests.conftest import deliver, pay, place_order, set_status

LATER = timedelta(hours=2)  # past every reminder threshold


@pytest.fixture
def db(client):
    session = next(app.dependency_overrides[get_db]())
    yield session
    session.close()


def logs(db):
    db.expire_all()
    return {(r.order_id, r.reminder_type) for r in db.scalars(select(ReminderLog))}


def test_each_reminder_type_is_sent_once_and_logged(client, db, owner, customer, courier, restaurant):
    unpaid = uuid.UUID(place_order(client, customer, restaurant)["id"])
    ready = place_order(client, customer, restaurant)["id"]
    pay(client, customer, ready)
    for s in ("accepted", "preparing", "ready_for_pickup"):
        set_status(client, owner, ready, s)
    ready = uuid.UUID(ready)
    done = uuid.UUID(deliver(client, owner, customer, courier, restaurant))

    notifier = MockNotifier()
    result = reminder_service.process_reminders(db, notifier, now=utcnow() + LATER)
    assert result.sent == 3 and result.failed == 0
    assert {(n.order_id, n.kind) for n in notifier.sent} == logs(db) == {
        (unpaid, ReminderType.PAYMENT_PENDING),
        (ready, ReminderType.ORDER_READY),
        (done, ReminderType.REVIEW_REQUEST),
    }
    customer_id = uuid.UUID(client.get("/api/v1/auth/me", headers=customer).json()["id"])
    assert all(n.user_id == customer_id for n in notifier.sent)

    again = reminder_service.process_reminders(db, notifier, now=utcnow() + LATER)
    assert again.sent == 0 and len(notifier.sent) == 3  # never twice


def test_reminders_respect_time_thresholds_and_reviews(client, db, owner, customer, courier, restaurant):
    place_order(client, customer, restaurant)  # pending payment, just now
    oid = deliver(client, owner, customer, courier, restaurant)
    client.post("/api/v1/reviews", json={"order_id": oid, "rating": 4}, headers=customer)
    result = reminder_service.process_reminders(db, MockNotifier(), now=utcnow())
    assert result.sent == 0  # too early for payment; delivered order already reviewed
    assert reminder_service.process_reminders(db, MockNotifier(), now=utcnow() + LATER).sent == 1


def test_failed_send_is_not_logged_and_is_retried(client, db, customer, restaurant):
    oid = uuid.UUID(place_order(client, customer, restaurant)["id"])
    failing = MockNotifier(fail_for={oid})
    result = reminder_service.process_reminders(db, failing, now=utcnow() + LATER)
    assert result.failed == 1 and result.sent == 0 and logs(db) == set()

    ok = MockNotifier()
    assert reminder_service.process_reminders(db, ok, now=utcnow() + LATER).sent == 1
    assert logs(db) == {(oid, ReminderType.PAYMENT_PENDING)}


def test_unique_event_key_stops_a_racing_worker(client, db, customer, restaurant, monkeypatch):
    """Worker A computed its to-do list, then worker B sent the same reminder first."""
    oid = uuid.UUID(place_order(client, customer, restaurant)["id"])
    stale = reminder_service.due_reminders(db, utcnow() + LATER)
    assert len(stale) == 1

    reminder_service.process_reminders(db, MockNotifier(), now=utcnow() + LATER)  # worker B

    monkeypatch.setattr(reminder_service, "due_reminders", lambda *_a, **_k: stale)
    notifier = MockNotifier()
    result = reminder_service.process_reminders(db, notifier, now=utcnow() + LATER)  # worker A
    assert result.skipped_duplicates == 1 and result.sent == 0 and notifier.sent == []
    assert logs(db) == {(oid, ReminderType.PAYMENT_PENDING)}
