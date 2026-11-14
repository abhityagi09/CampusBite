"""Public reviews endpoint, scoped statistics, and cross-customer privacy."""

import uuid
from decimal import Decimal

from tests.conftest import deliver, pay, place_order


def review(client, headers, oid, rating=5, **extra):
    return client.post("/api/v1/reviews", json={"order_id": oid, "rating": rating, **extra}, headers=headers)


# ------------------------------------------------------------------ reviews


def test_review_rules(client, make_user, owner, customer, courier, restaurant):
    pending = place_order(client, customer, restaurant)["id"]
    assert review(client, customer, pending).status_code == 400  # not delivered
    oid = deliver(client, owner, customer, courier, restaurant)
    for bad in (0, 6, "five"):
        assert review(client, customer, oid, bad).status_code == 422
    assert review(client, make_user("customer", "x@example.com"), oid).status_code == 404
    assert review(client, owner, oid).status_code == 403
    assert review(client, customer, oid, 4, comment="Good").status_code == 201
    assert review(client, customer, oid, 5).status_code == 409  # one per order


def test_public_reviews_hide_private_ids(client, owner, customer, courier, restaurant):
    for rating in (3, 5):
        oid = deliver(client, owner, customer, courier, restaurant)
        review(client, customer, oid, rating)
    page = client.get(f"/api/v1/restaurants/{restaurant}/reviews").json()  # no auth
    assert page["total"] == 2 and [r["rating"] for r in page["items"]] == [5, 3]  # newest first
    for r in page["items"]:
        assert "customer_id" not in r and "order_id" not in r
    legacy = client.get(f"/api/v1/reviews/restaurant/{restaurant}").json()
    assert all("customer_id" not in r and "order_id" not in r for r in legacy)
    assert client.get(f"/api/v1/restaurants/{restaurant}/reviews?limit=1").json()["total"] == 2
    assert client.get(f"/api/v1/restaurants/{uuid.uuid4()}/reviews").status_code == 404


# ------------------------------------------------------------------ statistics


def test_owner_statistics_with_restaurant_performance(client, make_user, owner, customer, courier, restaurant):
    quiet = client.post("/api/v1/restaurants", json={"name": "Zz Quiet"}, headers=owner).json()["id"]
    a = deliver(client, owner, customer, courier, restaurant)  # 13.25
    deliver(client, owner, customer, courier, restaurant, items=(("Fries", 2),))  # 4.50
    review(client, customer, a, 4)
    lost = place_order(client, customer, restaurant)["id"]
    pay(client, customer, lost)
    client.post(f"/api/v1/orders/{lost}/cancel", headers=customer)
    rid = client.post(f"/api/v1/orders/{a}/refund-requests", json={"reason": "cold"}, headers=customer).json()["id"]
    client.post(f"/api/v1/refund-requests/{rid}/decision", json={"decision": "approve"}, headers=owner)

    s = client.get("/api/v1/statistics/owner", headers=owner).json()
    assert s["total_orders"] == 3
    assert s["orders_by_status"] == {"delivered": 1, "refunded": 1, "cancelled": 1}
    assert Decimal(s["revenue"]) == Decimal("17.75")
    assert Decimal(s["refunded"]) == Decimal("13.25")
    assert Decimal(s["net_revenue"]) == Decimal("4.50")
    grill, empty = s["restaurants"]
    assert (grill["name"], grill["total_orders"], grill["delivered_orders"], grill["cancelled_or_rejected"]) == (
        "Campus Grill", 3, 2, 1)
    assert Decimal(grill["revenue"]) == Decimal("17.75")
    assert grill["average_rating"] == 4.0 and grill["review_count"] == 1
    assert empty["restaurant_id"] == quiet and empty["total_orders"] == 0 and Decimal(empty["revenue"]) == 0

    other = make_user("owner", "o2@example.com")
    o2 = client.get("/api/v1/statistics/owner", headers=other).json()
    assert o2["total_orders"] == 0 and o2["restaurants"] == []


def test_customer_statistics_are_own_only(client, make_user, owner, customer, courier, restaurant):
    a = deliver(client, owner, customer, courier, restaurant)
    place_order(client, customer, restaurant)
    other = make_user("customer", "c2@example.com")
    deliver(client, owner, other, courier, restaurant)
    rid = client.post(f"/api/v1/orders/{a}/refund-requests", json={"reason": "cold"}, headers=customer).json()["id"]
    client.post(f"/api/v1/refund-requests/{rid}/decision", json={"decision": "approve"}, headers=owner)

    s = client.get("/api/v1/statistics/customer", headers=customer).json()
    assert s["total_orders"] == 2
    assert s["orders_by_status"] == {"refunded": 1, "pending_payment": 1}
    assert Decimal(s["total_spent"]) == Decimal("13.25")
    assert Decimal(s["total_refunded"]) == Decimal("13.25") and Decimal(s["net_spent"]) == 0
    assert s["top_restaurants"][0]["order_count"] == 2

    o = client.get("/api/v1/statistics/customer", headers=other).json()
    assert o["total_orders"] == 1 and Decimal(o["total_refunded"]) == 0


def test_statistics_endpoints_are_role_scoped(client, owner, customer, courier):
    assert client.get("/api/v1/statistics/owner").status_code == 401
    assert client.get("/api/v1/statistics/customer").status_code == 401
    for who in (customer, courier):
        assert client.get("/api/v1/statistics/owner", headers=who).status_code == 403
    for who in (owner, courier):
        assert client.get("/api/v1/statistics/customer", headers=who).status_code == 403


# ------------------------------------------------------------------ privacy sweep


def test_customer_cannot_read_another_customers_records(client, make_user, owner, customer, courier, restaurant):
    oid = deliver(client, owner, customer, courier, restaurant)
    client.post(f"/api/v1/orders/{oid}/refund-requests", json={"reason": "cold"}, headers=customer)
    spy = make_user("customer", "spy@example.com")

    for path in (f"/orders/{oid}", f"/orders/{oid}/payment", f"/orders/{oid}/tracking",
                 f"/payments/orders/{oid}", f"/payments/orders/{oid}/ledger"):
        assert client.get(f"/api/v1{path}", headers=spy).status_code == 404, path
    assert client.get("/api/v1/orders/me", headers=spy).json()["total"] == 0
    assert client.get("/api/v1/refund-requests/me", headers=spy).json()["total"] == 0
    assert client.get("/api/v1/statistics/customer", headers=spy).json()["total_orders"] == 0
    assert client.post(f"/api/v1/orders/{oid}/refund-requests", json={"reason": "x"}, headers=spy).status_code == 404
    assert review(client, spy, oid).status_code == 404
