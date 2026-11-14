import uuid
from decimal import Decimal

from tests.conftest import pay, place_order


def test_successful_payment_places_order(client, customer, restaurant):
    order = place_order(client, customer, restaurant)
    resp = pay(client, customer, order["id"])
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "paid"
    assert data["transaction_ref"].startswith("SIM-")
    assert Decimal(data["amount"]) == Decimal(order["total_amount"])
    assert client.get(f"/api/v1/orders/{order['id']}", headers=customer).json()["status"] == "placed"


def test_failed_payment_can_be_retried(client, customer, restaurant):
    oid = place_order(client, customer, restaurant)["id"]
    failed = pay(client, customer, oid, simulate_failure=True).json()
    assert failed["status"] == "failed"
    assert failed["transaction_ref"] is None
    assert client.get(f"/api/v1/orders/{oid}", headers=customer).json()["status"] == "pending_payment"

    retry = pay(client, customer, oid)
    assert retry.status_code == 200
    assert retry.json()["status"] == "paid"
    assert retry.json()["id"] == failed["id"]  # same payment row reused


def test_cannot_pay_twice(client, customer, restaurant):
    oid = place_order(client, customer, restaurant)["id"]
    assert pay(client, customer, oid).status_code == 200
    assert pay(client, customer, oid).status_code == 409


def test_payment_access_rules(client, make_user, owner, customer, courier, restaurant):
    oid = place_order(client, customer, restaurant)["id"]
    other_customer = make_user("customer", "c2@example.com")

    assert pay(client, other_customer, oid).status_code == 404
    assert pay(client, owner, oid).status_code == 403
    assert pay(client, courier, oid).status_code == 403
    assert pay(client, customer, str(uuid.uuid4())).status_code == 404

    assert client.get(f"/api/v1/payments/orders/{oid}", headers=customer).status_code == 404  # none yet
    pay(client, customer, oid)
    assert client.get(f"/api/v1/payments/orders/{oid}", headers=customer).status_code == 200
    assert client.get(f"/api/v1/payments/orders/{oid}", headers=owner).status_code == 200
    assert client.get(f"/api/v1/payments/orders/{oid}", headers=other_customer).status_code == 404
    assert client.get(f"/api/v1/payments/orders/{oid}", headers=courier).status_code == 404


def test_ledger_records_failed_then_successful_charge(client, customer, restaurant):
    oid = place_order(client, customer, restaurant)["id"]
    pay(client, customer, oid, simulate_failure=True)
    pay(client, customer, oid)
    entries = client.get(f"/api/v1/payments/orders/{oid}/ledger", headers=customer).json()
    assert [(e["transaction_type"], e["status"]) for e in entries] == [
        ("charge", "failed"),
        ("charge", "completed"),
    ]
    assert entries[0]["reference"] is None
    assert entries[1]["reference"].startswith("SIM-")
