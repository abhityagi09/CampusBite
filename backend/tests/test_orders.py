import uuid
from decimal import Decimal

from tests.conftest import pay, place_order, set_status


def test_total_is_computed_from_server_prices(client, customer, restaurant):
    order = place_order(client, customer, restaurant, items=(("Burger", 2), ("Fries", 1), ("Burger", 1)))
    # duplicate lines are merged: 3 x 5.50 + 1 x 2.25
    assert Decimal(order["total_amount"]) == Decimal("18.75")
    assert order["status"] == "pending_payment"
    assert len(order["items"]) == 2
    assert order["events"][0]["status"] == "pending_payment"


def test_create_order_validation(client, owner, customer, courier, restaurant):
    burger, fries = restaurant.menu["Burger"], restaurant.menu["Fries"]

    def post(headers, **kw):
        body = {
            "restaurant_id": restaurant,
            "items": [{"menu_item_id": burger, "quantity": 1}],
            "delivery_address": "Hostel 3",
        }
        body.update(kw)
        return client.post("/api/v1/orders", json=body, headers=headers)

    assert post(owner).status_code == 403
    assert post(courier).status_code == 403
    assert post(customer, items=[]).status_code == 422
    assert post(customer, items=[{"menu_item_id": burger, "quantity": 0}]).status_code == 422
    assert post(customer, items=[{"menu_item_id": str(uuid.uuid4()), "quantity": 1}]).status_code == 400
    assert post(customer, items=[{"menu_item_id": "99", "quantity": 1}]).status_code == 422  # not a UUID
    assert post(customer, restaurant_id=str(uuid.uuid4())).status_code == 404
    assert post(customer, restaurant_id="999").status_code == 422

    client.patch(f"/api/v1/restaurants/{restaurant}/menu/{burger}", json={"is_available": False}, headers=owner)
    assert post(customer).status_code == 400  # unavailable item

    client.patch(f"/api/v1/restaurants/{restaurant}", json={"is_open": False}, headers=owner)
    assert post(customer, items=[{"menu_item_id": fries, "quantity": 1}]).status_code == 400  # closed


def test_item_from_another_restaurant_rejected(client, make_user, customer, restaurant):
    other = make_user("owner", "other@example.com")
    r2 = client.post("/api/v1/restaurants", json={"name": "Other"}, headers=other).json()["id"]
    client.post(
        f"/api/v1/restaurants/{r2}/menu", json={"name": "Pizza", "price": "9.00"}, headers=other
    )
    foreign_item = client.get(f"/api/v1/restaurants/{r2}/menu").json()["items"][0]["id"]
    resp = client.post(
        "/api/v1/orders",
        json={
            "restaurant_id": restaurant,
            "items": [{"menu_item_id": foreign_item, "quantity": 1}],
            "delivery_address": "Hostel 3",
        },
        headers=customer,
    )
    assert resp.status_code == 400


def test_full_happy_path_lifecycle(client, owner, customer, courier, restaurant):
    oid = place_order(client, customer, restaurant)["id"]
    assert pay(client, customer, oid).json()["status"] == "mock_paid"

    assert set_status(client, owner, oid, "accepted").json()["status"] == "accepted"
    assert set_status(client, owner, oid, "preparing").status_code == 200
    assert set_status(client, owner, oid, "ready").status_code == 200
    assert client.get(f"/api/v1/orders/{oid}", headers=courier).status_code == 404  # not assigned yet
    cid = client.get("/api/v1/auth/me", headers=courier).json()["id"]
    assert client.post(f"/api/v1/orders/{oid}/assign-delivery", json={"delivery_partner_id": cid},
                       headers=owner).json()["status"] == "assigned"

    assert set_status(client, courier, oid, "out_for_delivery").status_code == 200
    done = set_status(client, courier, oid, "delivered")
    assert done.json()["status"] == "delivered"

    track = client.get(f"/api/v1/orders/{oid}/tracking", headers=customer).json()
    assert [e["status"] for e in track] == [
        "pending_payment",
        "placed",
        "accepted",
        "preparing",
        "ready",
        "assigned",
        "out_for_delivery",
        "delivered",
    ]


def test_invalid_transitions_and_wrong_actor(client, owner, customer, courier, restaurant):
    oid = place_order(client, customer, restaurant)["id"]
    # not paid yet: owner cannot accept
    assert set_status(client, owner, oid, "accepted").status_code == 409
    pay(client, customer, oid)
    # cannot skip steps
    assert set_status(client, owner, oid, "ready").status_code == 409
    assert set_status(client, owner, oid, "delivered").status_code == 409
    # customers cannot drive the lifecycle; courier cannot touch an unassigned order
    assert set_status(client, customer, oid, "accepted").status_code == 403
    assert set_status(client, courier, oid, "out_for_delivery").status_code == 403
    # courier cannot claim an order that isn't ready
    assert client.post(f"/api/v1/orders/{oid}/claim", headers=courier).status_code in (404, 409)


def test_ownership_isolation(client, make_user, owner, customer, restaurant):
    oid = place_order(client, customer, restaurant)["id"]
    other_customer = make_user("customer", "c2@example.com")
    other_owner = make_user("owner", "o2@example.com")

    assert client.get(f"/api/v1/orders/{oid}", headers=other_customer).status_code == 404
    assert client.get(f"/api/v1/orders/{oid}", headers=other_owner).status_code == 404
    assert client.get(f"/api/v1/orders/{oid}", headers=owner).status_code == 200
    assert client.post(f"/api/v1/orders/{oid}/cancel", headers=other_customer).status_code == 404
    pay(client, customer, oid)
    assert set_status(client, other_owner, oid, "accepted").status_code == 404

    assert client.get("/api/v1/orders", headers=other_customer).json() == []
    assert len(client.get("/api/v1/orders", headers=customer).json()) == 1
    assert len(client.get("/api/v1/orders", headers=owner).json()) == 1
    assert client.get("/api/v1/orders", headers=other_owner).json() == []


def test_customer_cancel_rules_and_refund(client, owner, customer, restaurant):
    unpaid = place_order(client, customer, restaurant)["id"]
    assert client.post(f"/api/v1/orders/{unpaid}/cancel", headers=customer).json()["status"] == "cancelled"
    # cancelled orders cannot be paid
    assert pay(client, customer, unpaid).status_code == 409

    paid = place_order(client, customer, restaurant)["id"]
    pay(client, customer, paid)
    cancelled = client.post(f"/api/v1/orders/{paid}/cancel", headers=customer).json()
    assert cancelled["status"] == "cancelled"
    assert cancelled["payment"]["status"] == "refunded"

    accepted = place_order(client, customer, restaurant)["id"]
    pay(client, customer, accepted)
    set_status(client, owner, accepted, "accepted")
    set_status(client, owner, accepted, "preparing")
    # once preparation has started the customer can no longer cancel
    assert client.post(f"/api/v1/orders/{accepted}/cancel", headers=customer).status_code == 409


def test_owner_reject_refunds(client, owner, customer, restaurant):
    oid = place_order(client, customer, restaurant)["id"]
    pay(client, customer, oid)
    rejected = set_status(client, owner, oid, "rejected").json()
    assert rejected["status"] == "rejected"
    assert rejected["payment"]["status"] == "refunded"
    assert set_status(client, owner, oid, "accepted").status_code == 409


def test_couriers_cannot_self_assign(client, make_user, owner, customer, courier, restaurant):
    other_courier = make_user("delivery_partner", "courier2@example.com")
    oid = place_order(client, customer, restaurant)["id"]
    pay(client, customer, oid)
    for s in ("accepted", "preparing", "ready"):
        set_status(client, owner, oid, s)

    assert client.post(f"/api/v1/orders/{oid}/claim", headers=courier).status_code in (404, 405)  # removed
    assert client.get("/api/v1/orders/available", headers=courier).status_code in (404, 422)  # removed
    assert set_status(client, owner, oid, "assigned").status_code == 409  # only via assign-delivery
    cid = client.get("/api/v1/auth/me", headers=courier).json()["id"]
    client.post(f"/api/v1/orders/{oid}/assign-delivery", json={"delivery_partner_id": cid}, headers=owner)
    # the other courier can't move it, nor see it
    assert set_status(client, other_courier, oid, "out_for_delivery").status_code == 403
    assert client.get(f"/api/v1/orders/{oid}", headers=other_courier).status_code == 404
    # assigned courier sees it in their list
    assert len(client.get("/api/v1/orders", headers=courier).json()) == 1


def test_status_filter(client, customer, restaurant):
    a = place_order(client, customer, restaurant)["id"]
    place_order(client, customer, restaurant)
    pay(client, customer, a)
    placed = client.get("/api/v1/orders?status=placed", headers=customer).json()
    assert [o["id"] for o in placed] == [a]


def test_order_items_expose_subtotal_and_ledger_tracks_refund(client, owner, customer, restaurant):
    order = place_order(client, customer, restaurant)
    burger = next(i for i in order["items"] if i["name"] == "Burger")
    assert Decimal(burger["subtotal"]) == Decimal("11.00")
    assert "line_total" not in burger
    oid = order["id"]
    pay(client, customer, oid)
    client.post(f"/api/v1/orders/{oid}/cancel", headers=customer)
    ledger = client.get(f"/api/v1/payments/orders/{oid}/ledger", headers=customer)
    assert ledger.status_code == 200
    kinds = [(e["transaction_type"], e["status"]) for e in ledger.json()]
    assert kinds == [("charge", "completed"), ("refund", "completed")]
