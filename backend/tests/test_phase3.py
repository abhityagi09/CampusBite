"""Stale-order reminders for owners, owner order date filter, order detail extras."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.database.session import get_db
from app.main import app
from app.services import reminder_service
from app.services.notifications import MockNotifier
from tests.conftest import deliver, pay, place_order, set_status



# ------------------------------------------------------------------ stale-order reminders


# ------------------------------------------------------------------ misc


def test_owner_orders_date_filter(client, owner, customer, restaurant):
    oid = place_order(client, customer, restaurant)["id"]
    pay(client, customer, oid)
    today = datetime.now(timezone.utc).date()
    ids = lambda q: [o["id"] for o in client.get(f"/api/v1/orders?{q}", headers=owner).json()]  # noqa: E731
    assert ids(f"created_from={today}") == [oid]
    assert ids(f"created_to={today - timedelta(days=1)}") == []
    assert client.get(f"/api/v1/orders?created_from={today}&created_to={today - timedelta(days=1)}",
                      headers=owner).status_code == 422


def test_order_detail_shows_review_refund_and_mock_paid(client, owner, customer, courier, restaurant):
    oid = deliver(client, owner, customer, courier, restaurant)
    detail = client.get(f"/api/v1/orders/{oid}", headers=customer).json()
    assert detail["payment"]["status"] == "mock_paid"
    assert detail["review"] is None and detail["refund_requests"] == []

    client.post("/api/v1/reviews", json={"order_id": oid, "rating": 4}, headers=customer)
    client.post(f"/api/v1/orders/{oid}/refund-requests", json={"reason": "cold"}, headers=customer)
    detail = client.get(f"/api/v1/orders/{oid}", headers=customer).json()
    assert detail["review"]["rating"] == 4
    assert [r["status"] for r in detail["refund_requests"]] == ["requested"]


def test_customer_cannot_cancel_after_acceptance_or_delivery(client, owner, customer, courier, restaurant):
    oid = place_order(client, customer, restaurant)["id"]
    pay(client, customer, oid)
    set_status(client, owner, oid, "accepted")
    assert client.post(f"/api/v1/orders/{oid}/cancel", headers=customer).status_code == 409
    done = deliver(client, owner, customer, courier, restaurant)
    assert client.post(f"/api/v1/orders/{done}/cancel", headers=customer).status_code == 409
