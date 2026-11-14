"""Cart checkout: POST /orders with payment, GET /orders/me, GET /orders/{id}/payment.

Cart used throughout: 2 x Burger (5.50) + 1 x Fries (2.25) = 13.25.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.exceptions import BadGatewayError
from app.database.session import get_db
from app.main import app
from app.models import Order, OrderItem, OrderStatusEvent, Payment, PaymentLedger, PaymentMethod
from app.services.payment_gateway import (
    ChargeOutcome,
    ChargeResult,
    DummyPaymentGateway,
    get_payment_gateway,
)

ORDERS = "/api/v1/orders"
TOTAL = Decimal("13.25")


def cart(restaurant, items=(("Burger", 2), ("Fries", 1)), **extra):
    body = {
        "restaurant_id": str(restaurant),
        "items": [{"menu_item_id": restaurant.menu.get(n, n), "quantity": q} for n, q in items],
        "delivery_address": "Hostel 3, Room 204",
        "payment_method": "upi",
    }
    body.update(extra)
    return body


def key():
    return {"Idempotency-Key": str(uuid.uuid4())}


def use_gateway(gateway):
    app.dependency_overrides[get_payment_gateway] = lambda: gateway


def row_counts():
    """Rows in every table a checkout writes to, read straight from the test database."""
    db = next(app.dependency_overrides[get_db]())
    try:
        return {
            m.__tablename__: db.scalar(select(func.count()).select_from(m))
            for m in (Order, OrderItem, OrderStatusEvent, Payment, PaymentLedger)
        }
    finally:
        db.close()


EMPTY = {"orders": 0, "order_items": 0, "order_status_events": 0, "payments": 0, "payment_ledger": 0}


@pytest.fixture(autouse=True)
def default_gateway():
    use_gateway(DummyPaymentGateway())


# ===================================================================== success


def test_successful_checkout_creates_paid_order_atomically(client, customer, restaurant):
    resp = client.post(ORDERS, json=cart(restaurant), headers={**customer, **key()})
    assert resp.status_code == 201, resp.text
    order = resp.json()

    assert order["status"] == "placed"
    assert Decimal(order["total_amount"]) == TOTAL
    lines = {i["name"]: i for i in order["items"]}
    assert Decimal(lines["Burger"]["unit_price"]) == Decimal("5.50")  # snapshot
    assert lines["Burger"]["quantity"] == 2 and Decimal(lines["Burger"]["subtotal"]) == Decimal("11.00")
    assert [e["status"] for e in order["events"]] == ["pending_payment", "placed"]

    payment = order["payment"]
    assert payment["status"] == "paid" and payment["method"] == "upi"
    assert Decimal(payment["amount"]) == TOTAL
    assert payment["transaction_ref"].startswith("SIM-")

    ledger = client.get(f"/api/v1/payments/orders/{order['id']}/ledger", headers=customer).json()
    assert len(ledger) == 1
    assert ledger[0]["transaction_type"] == "charge" and ledger[0]["status"] == "completed"
    assert ledger[0]["reference"] == payment["transaction_ref"]
    assert Decimal(ledger[0]["amount"]) == TOTAL

    assert row_counts() == {"orders": 1, "order_items": 2, "order_status_events": 2,
                            "payments": 1, "payment_ledger": 1}


def test_payment_reference_is_server_generated_and_deterministic(client, customer, restaurant):
    order = client.post(ORDERS, json=cart(restaurant), headers={**customer, **key()}).json()
    expected = DummyPaymentGateway.reference_for(uuid.UUID(order["id"]), TOTAL, PaymentMethod.UPI)
    assert order["payment"]["transaction_ref"] == expected


def test_duplicate_lines_are_merged_and_priced_from_db(client, customer, restaurant):
    body = cart(restaurant, items=(("Burger", 1), ("Burger", 1), ("Fries", 1)))
    order = client.post(ORDERS, json=body, headers={**customer, **key()}).json()
    assert [(i["name"], i["quantity"]) for i in order["items"]] == [("Burger", 2), ("Fries", 1)]
    assert Decimal(order["total_amount"]) == TOTAL


def test_order_without_payment_method_keeps_existing_pay_later_flow(client, customer, restaurant):
    body = cart(restaurant)
    del body["payment_method"]
    resp = client.post(ORDERS, json=body, headers=customer)  # no key needed
    assert resp.status_code == 201
    assert resp.json()["status"] == "pending_payment" and resp.json()["payment"] is None
    assert client.get(f"{ORDERS}/{resp.json()['id']}/payment", headers=customer).status_code == 404


def test_prices_changed_later_do_not_affect_placed_order(client, owner, customer, restaurant):
    order = client.post(ORDERS, json=cart(restaurant), headers={**customer, **key()}).json()
    client.patch(f"/api/v1/restaurants/{restaurant}/menu/{restaurant.menu['Burger']}",
                 json={"price": "99.00", "name": "Mega Burger"}, headers=owner)
    again = client.get(f"{ORDERS}/{order['id']}", headers=customer).json()
    assert Decimal(again["total_amount"]) == TOTAL
    burger = next(i for i in again["items"] if i["menu_item_id"] == restaurant.menu["Burger"])
    assert burger["name"] == "Burger" and Decimal(burger["unit_price"]) == Decimal("5.50")


# ===================================================================== auth


def test_checkout_requires_customer(client, owner, courier, restaurant):
    assert client.post(ORDERS, json=cart(restaurant), headers=key()).status_code == 401
    for headers in (owner, courier):
        assert client.post(ORDERS, json=cart(restaurant), headers={**headers, **key()}).status_code == 403
    assert row_counts() == EMPTY


# ===================================================================== unavailable / invalid


def test_unavailable_item_rejects_whole_cart(client, owner, customer, restaurant):
    client.post(f"/api/v1/restaurants/{restaurant}/menu/{restaurant.menu['Fries']}/disable", headers=owner)
    resp = client.post(ORDERS, json=cart(restaurant), headers={**customer, **key()})
    assert resp.status_code == 400 and "Fries" in resp.json()["detail"]
    assert row_counts() == EMPTY


def test_deleted_or_unknown_item_rejected(client, customer, restaurant):
    resp = client.post(ORDERS, json=cart(restaurant, items=((str(uuid.uuid4()), 1),)),
                       headers={**customer, **key()})
    assert resp.status_code == 400
    assert row_counts() == EMPTY


def test_items_must_all_belong_to_the_selected_restaurant(client, make_user, customer, restaurant):
    other = make_user("owner", "other@example.com")
    r2 = client.post("/api/v1/restaurants", json={"name": "Other"}, headers=other).json()["id"]
    pizza = client.post(f"/api/v1/restaurants/{r2}/menu", json={"name": "Pizza", "price": "9.00"},
                        headers=other).json()["id"]
    body = cart(restaurant, items=(("Burger", 1), (pizza, 1)))
    assert client.post(ORDERS, json=body, headers={**customer, **key()}).status_code == 400
    assert row_counts() == EMPTY


def test_inactive_or_closed_restaurant_rejected(client, owner, customer, restaurant):
    client.patch(f"/api/v1/restaurants/{restaurant}", json={"is_open": False}, headers=owner)
    assert client.post(ORDERS, json=cart(restaurant), headers={**customer, **key()}).status_code == 400
    client.patch(f"/api/v1/restaurants/{restaurant}", json={"is_active": False}, headers=owner)
    assert client.post(ORDERS, json=cart(restaurant), headers={**customer, **key()}).status_code == 404
    body = cart(restaurant)
    body["restaurant_id"] = str(uuid.uuid4())
    assert client.post(ORDERS, json=body, headers={**customer, **key()}).status_code == 404
    assert row_counts() == EMPTY


@pytest.mark.parametrize("quantity", [0, -1, 51, 2.5, "2", True, None])
def test_invalid_quantities_rejected(client, customer, restaurant, quantity):
    body = cart(restaurant)
    body["items"][0]["quantity"] = quantity
    assert client.post(ORDERS, json=body, headers={**customer, **key()}).status_code == 422
    assert row_counts() == EMPTY


def test_combined_quantity_over_limit_rejected(client, customer, restaurant):
    body = cart(restaurant, items=(("Burger", 30), ("Burger", 30)))
    assert client.post(ORDERS, json=body, headers={**customer, **key()}).status_code == 400
    assert row_counts() == EMPTY


@pytest.mark.parametrize("mutate", [
    lambda b: b.update(items=[]),
    lambda b: b.pop("restaurant_id"),
    lambda b: b.update(delivery_address=""),
    lambda b: b.update(payment_method="bitcoin"),
    lambda b: b["items"][0].update(menu_item_id="not-a-uuid"),
])
def test_invalid_cart_shapes_rejected(client, customer, restaurant, mutate):
    body = cart(restaurant)
    mutate(body)
    assert client.post(ORDERS, json=body, headers={**customer, **key()}).status_code == 422
    assert row_counts() == EMPTY


# ===================================================================== tampering


@pytest.mark.parametrize("tamper", [
    lambda b: b.update(total_amount="0.01"),
    lambda b: b["items"][0].update(unit_price="0.01"),
    lambda b: b["items"][0].update(price="0.01"),
    lambda b: b.update(status="placed"),
    lambda b: b.update(payment_status="paid"),
    lambda b: b.update(transaction_ref="SIM-FAKE"),
])
def test_client_supplied_prices_and_payment_state_are_rejected(client, customer, restaurant, tamper):
    body = cart(restaurant)
    tamper(body)
    resp = client.post(ORDERS, json=body, headers={**customer, **key()})
    assert resp.status_code == 422
    assert row_counts() == EMPTY


def test_tampered_expected_total_is_refused_and_nothing_is_charged(client, customer, restaurant):
    resp = client.post(ORDERS, json=cart(restaurant, expected_total="1.00"), headers={**customer, **key()})
    assert resp.status_code == 409
    assert "13.25" in resp.json()["detail"]
    assert row_counts() == EMPTY


def test_matching_expected_total_is_accepted(client, customer, restaurant):
    resp = client.post(ORDERS, json=cart(restaurant, expected_total="13.25"), headers={**customer, **key()})
    assert resp.status_code == 201
    assert Decimal(resp.json()["payment"]["amount"]) == TOTAL


def test_stale_cart_after_price_change_is_refused(client, owner, customer, restaurant):
    client.patch(f"/api/v1/restaurants/{restaurant}/menu/{restaurant.menu['Fries']}",
                 json={"price": "3.00"}, headers=owner)
    resp = client.post(ORDERS, json=cart(restaurant, expected_total="13.25"), headers={**customer, **key()})
    assert resp.status_code == 409 and "14.00" in resp.json()["detail"]
    assert row_counts() == EMPTY


# ===================================================================== idempotency


def test_duplicate_request_returns_same_order_without_charging_twice(client, customer, restaurant):
    headers = {**customer, **key()}
    first = client.post(ORDERS, json=cart(restaurant), headers=headers)
    second = client.post(ORDERS, json=cart(restaurant), headers=headers)

    assert first.status_code == 201 and "Idempotent-Replayed" not in first.headers
    assert second.status_code == 200 and second.headers["Idempotent-Replayed"] == "true"
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["payment"]["transaction_ref"] == first.json()["payment"]["transaction_ref"]
    assert row_counts()["orders"] == 1 and row_counts()["payment_ledger"] == 1


def test_same_key_with_different_cart_is_rejected(client, customer, restaurant):
    headers = {**customer, **key()}
    assert client.post(ORDERS, json=cart(restaurant), headers=headers).status_code == 201
    resp = client.post(ORDERS, json=cart(restaurant, items=(("Fries", 5),)), headers=headers)
    assert resp.status_code == 422 and "Idempotency-Key" in resp.json()["detail"]
    assert row_counts()["orders"] == 1


def test_new_key_creates_new_order(client, customer, restaurant):
    client.post(ORDERS, json=cart(restaurant), headers={**customer, **key()})
    client.post(ORDERS, json=cart(restaurant), headers={**customer, **key()})
    assert row_counts()["orders"] == 2 and row_counts()["payment_ledger"] == 2


def test_keys_are_scoped_per_customer(client, make_user, customer, restaurant):
    other = make_user("customer", "other-customer@example.com")
    k = key()
    a = client.post(ORDERS, json=cart(restaurant), headers={**customer, **k})
    b = client.post(ORDERS, json=cart(restaurant), headers={**other, **k})
    assert a.status_code == b.status_code == 201
    assert a.json()["id"] != b.json()["id"]
    # and nobody can fetch someone else's order by guessing their key
    assert b.json()["customer_id"] != a.json()["customer_id"]


@pytest.mark.parametrize("bad_key", [None, "short", "x" * 65, "has space key", "bad/slash-key"])
def test_checkout_requires_a_valid_idempotency_key(client, customer, restaurant, bad_key):
    headers = dict(customer)
    if bad_key is not None:
        headers["Idempotency-Key"] = bad_key
    assert client.post(ORDERS, json=cart(restaurant), headers=headers).status_code in (400, 422)
    assert row_counts() == EMPTY


def test_declined_attempt_saves_nothing_so_its_key_can_be_retried(client, customer, restaurant):
    headers = {**customer, **key()}
    use_gateway(DummyPaymentGateway(outcome=ChargeOutcome.DECLINE))
    declined = client.post(ORDERS, json=cart(restaurant), headers=headers)
    assert declined.status_code == 402 and "declined" in declined.json()["detail"].lower()
    assert row_counts() == EMPTY

    use_gateway(DummyPaymentGateway())
    retry = client.post(ORDERS, json=cart(restaurant), headers=headers)
    assert retry.status_code == 201 and retry.json()["status"] == "placed"


# ===================================================================== rollback


def test_gateway_error_rolls_back_everything(client, customer, restaurant):
    use_gateway(DummyPaymentGateway(outcome=ChargeOutcome.ERROR))
    resp = client.post(ORDERS, json=cart(restaurant), headers={**customer, **key()})
    assert resp.status_code == 502
    assert row_counts() == EMPTY


def test_per_method_outcomes(client, customer, restaurant):
    use_gateway(DummyPaymentGateway(outcomes_by_method={PaymentMethod.WALLET: ChargeOutcome.DECLINE}))
    assert client.post(ORDERS, json=cart(restaurant, payment_method="wallet"),
                       headers={**customer, **key()}).status_code == 402
    assert client.post(ORDERS, json=cart(restaurant, payment_method="card"),
                       headers={**customer, **key()}).status_code == 201


class _FixedReferenceGateway(DummyPaymentGateway):
    """Approves every charge with the SAME reference, so the second checkout violates the
    unique ledger/payment reference constraint at COMMIT time, after the order, items,
    events and payment were already added to the session."""

    def charge(self, *, order_id, amount, method):
        return ChargeResult(approved=True, reference="SIM-COLLIDING-REFERENCE")


def test_database_failure_at_commit_rolls_back_whole_checkout(client, customer, restaurant):
    use_gateway(_FixedReferenceGateway())
    assert client.post(ORDERS, json=cart(restaurant), headers={**customer, **key()}).status_code == 201
    before = row_counts()

    resp = client.post(ORDERS, json=cart(restaurant), headers={**customer, **key()})
    assert resp.status_code == 500
    assert row_counts() == before  # no orphan order, items, events or payment

    # the session/connection is healthy afterwards
    use_gateway(DummyPaymentGateway())
    assert client.post(ORDERS, json=cart(restaurant), headers={**customer, **key()}).status_code == 201


class _ExplodingGateway(DummyPaymentGateway):
    def charge(self, *, order_id, amount, method):
        raise RuntimeError("gateway crashed mid-charge")


def test_unexpected_exception_rolls_back_whole_checkout(client, customer, restaurant):
    use_gateway(_ExplodingGateway())
    with pytest.raises(RuntimeError):  # TestClient re-raises unhandled server errors
        client.post(ORDERS, json=cart(restaurant), headers={**customer, **key()})
    assert row_counts() == EMPTY


def test_configured_outcome_comes_from_server_settings(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "PAYMENT_SIMULATOR_OUTCOME", "decline")
    monkeypatch.setattr(settings, "PAYMENT_SIMULATOR_METHOD_OUTCOMES", "card=error")
    gw = get_payment_gateway()
    oid = uuid.uuid4()
    assert gw.charge(order_id=oid, amount=TOTAL, method=PaymentMethod.UPI).approved is False
    with pytest.raises(BadGatewayError):
        gw.charge(order_id=oid, amount=TOTAL, method=PaymentMethod.CARD)


def test_dummy_gateway_is_deterministic():
    gw = DummyPaymentGateway()
    oid = uuid.uuid4()
    a = gw.charge(order_id=oid, amount=TOTAL, method=PaymentMethod.UPI)
    b = gw.charge(order_id=oid, amount=TOTAL, method=PaymentMethod.UPI)
    c = gw.charge(order_id=uuid.uuid4(), amount=TOTAL, method=PaymentMethod.UPI)
    assert a == b and a.approved and a.reference != c.reference
    with pytest.raises(ValueError):
        gw.charge(order_id=oid, amount=Decimal("0"), method=PaymentMethod.UPI)


# ===================================================================== reads


def test_my_orders_lists_only_own_orders_paginated(client, make_user, customer, courier, restaurant):
    other = make_user("customer", "other-customer@example.com")
    ids = [client.post(ORDERS, json=cart(restaurant), headers={**customer, **key()}).json()["id"]
           for _ in range(3)]
    client.post(ORDERS, json=cart(restaurant), headers={**other, **key()})

    page = client.get(f"{ORDERS}/me", headers=customer).json()
    assert page["total"] == 3
    assert [o["id"] for o in page["items"]] == ids[::-1]  # newest first
    p2 = client.get(f"{ORDERS}/me?limit=2&offset=2", headers=customer).json()
    assert [o["id"] for o in p2["items"]] == [ids[0]]
    assert client.get(f"{ORDERS}/me?status=placed", headers=customer).json()["total"] == 3
    assert client.get(f"{ORDERS}/me?status=delivered", headers=customer).json()["total"] == 0

    assert client.get(f"{ORDERS}/me").status_code == 401
    assert client.get(f"{ORDERS}/me", headers=courier).status_code == 403


def test_get_order_and_payment_visibility(client, owner, make_user, customer, courier, restaurant):
    order = client.post(ORDERS, json=cart(restaurant), headers={**customer, **key()}).json()
    oid = order["id"]
    stranger = make_user("customer", "stranger@example.com")
    other_owner = make_user("owner", "other-owner@example.com")

    assert client.get(f"{ORDERS}/{oid}", headers=customer).json()["id"] == oid
    payment = client.get(f"{ORDERS}/{oid}/payment", headers=customer)
    assert payment.status_code == 200
    assert payment.json() == order["payment"]
    assert client.get(f"{ORDERS}/{oid}/payment", headers=owner).status_code == 200

    for who in (stranger, other_owner, courier):
        assert client.get(f"{ORDERS}/{oid}", headers=who).status_code == 404
        assert client.get(f"{ORDERS}/{oid}/payment", headers=who).status_code == 404
    assert client.get(f"{ORDERS}/{oid}/payment").status_code == 401
    assert client.get(f"{ORDERS}/{uuid.uuid4()}/payment", headers=customer).status_code == 404
