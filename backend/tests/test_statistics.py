from decimal import Decimal

from tests.test_reviews import _deliver
from tests.conftest import pay, place_order


def test_statistics_per_role(client, owner, customer, courier, restaurant):
    oid = _deliver(client, owner, customer, courier, restaurant)  # 2 x 5.50 + 2.25 = 13.25
    client.post("/api/v1/reviews", json={"order_id": oid, "rating": 5}, headers=customer)
    place_order(client, customer, restaurant)  # stays pending_payment
    cancelled = place_order(client, customer, restaurant)["id"]
    pay(client, customer, cancelled)
    client.post(f"/api/v1/orders/{cancelled}/cancel", headers=customer)

    c = client.get("/api/v1/statistics/me", headers=customer).json()
    assert c["role"] == "customer"
    assert c["total_orders"] == 3
    assert c["orders_by_status"] == {"delivered": 1, "pending_payment": 1, "cancelled": 1}
    assert Decimal(c["total_spent"]) == Decimal("13.25")

    o = client.get("/api/v1/statistics/me", headers=owner).json()
    assert o["role"] == "owner"
    assert o["restaurant_count"] == 1
    assert o["total_orders"] == 3
    assert Decimal(o["revenue"]) == Decimal("13.25")
    assert o["average_rating"] == 5.0
    assert o["review_count"] == 1
    assert o["top_items"][0] == {"name": "Burger", "quantity": 2}

    d = client.get("/api/v1/statistics/me", headers=courier).json()
    assert d == {
        "role": "delivery_partner",
        "completed_deliveries": 1,
        "active_deliveries": 0,
        "available_orders": 0,
    }


def test_statistics_requires_auth_and_handles_empty(client, owner):
    assert client.get("/api/v1/statistics/me").status_code == 401
    o = client.get("/api/v1/statistics/me", headers=owner).json()
    assert o["restaurant_count"] == 0
    assert Decimal(o["revenue"]) == 0
    assert o["average_rating"] is None
