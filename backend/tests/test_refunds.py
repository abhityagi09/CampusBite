import uuid
from decimal import Decimal

import pytest

from app.core.exceptions import ConflictError
from app.database.session import get_db
from app.main import app
from app.models import RefundRequest, User
from app.services import order_service, refund_service
from tests.conftest import deliver, pay, place_order, set_status

REASON = {"reason": "Fries were missing"}


def req(client, headers, oid, body=REASON):
    return client.post(f"/api/v1/orders/{oid}/refund-requests", json=body, headers=headers)


def decide(client, headers, rid, decision):
    return client.post(f"/api/v1/refund-requests/{rid}/decision", json={"decision": decision}, headers=headers)


def ledger(client, customer, oid):
    return client.get(f"/api/v1/payments/orders/{oid}/ledger", headers=customer).json()


@pytest.fixture
def delivered(client, owner, customer, courier, restaurant):
    return deliver(client, owner, customer, courier, restaurant)  # 13.25


def test_request_and_approve_refund_creates_reversal(client, owner, customer, delivered):
    r = req(client, customer, delivered)
    assert r.status_code == 201 and r.json()["status"] == "requested"
    rid = r.json()["id"]

    mine = client.get("/api/v1/refund-requests/me", headers=customer).json()
    assert mine["total"] == 1 and mine["items"][0]["id"] == rid
    incoming = client.get("/api/v1/refund-requests/incoming?status=requested", headers=owner).json()
    assert [i["id"] for i in incoming["items"]] == [rid]

    done = decide(client, owner, rid, "approve")
    assert done.status_code == 200 and done.json()["status"] == "processed"

    payment = client.get(f"/api/v1/orders/{delivered}/payment", headers=customer).json()
    assert payment["status"] == "refunded"
    entries = ledger(client, customer, delivered)
    assert [(e["transaction_type"], e["status"]) for e in entries] == [
        ("charge", "completed"), ("refund", "completed")]
    assert Decimal(entries[1]["amount"]) == Decimal(entries[0]["amount"]) == Decimal("13.25")
    assert entries[1]["reference"] == refund_service.refund_reference(uuid.UUID(rid))


def test_reject_then_new_request_allowed(client, owner, customer, delivered):
    rid = req(client, customer, delivered).json()["id"]
    assert decide(client, owner, rid, "reject").json()["status"] == "rejected"
    assert client.get(f"/api/v1/orders/{delivered}/payment", headers=customer).json()["status"] == "paid"
    assert len(ledger(client, customer, delivered)) == 1  # no reversal
    assert req(client, customer, delivered).status_code == 201


def test_duplicate_requests_and_refunds_prevented(client, owner, customer, delivered):
    rid = req(client, customer, delivered).json()["id"]
    assert req(client, customer, delivered).status_code == 409  # one open request
    assert decide(client, owner, rid, "approve").status_code == 200
    assert decide(client, owner, rid, "approve").status_code == 409  # decided once
    assert decide(client, owner, rid, "reject").status_code == 409
    assert req(client, customer, delivered).status_code == 409  # already refunded
    assert [e["transaction_type"] for e in ledger(client, customer, delivered)].count("refund") == 1


def test_only_delivered_paid_orders_are_eligible(client, owner, customer, restaurant):
    unpaid = place_order(client, customer, restaurant)["id"]
    assert req(client, customer, unpaid).status_code == 409
    paid = place_order(client, customer, restaurant)["id"]
    pay(client, customer, paid)
    set_status(client, owner, paid, "accepted")
    assert req(client, customer, paid).status_code == 409  # not delivered yet
    client.post(f"/api/v1/orders/{paid}/cancel", headers=customer)  # auto-refunded
    assert req(client, customer, paid).status_code == 409
    assert req(client, customer, uuid.uuid4()).status_code == 404


@pytest.mark.parametrize("body", [{"reason": ""}, {"reason": "   "}, {}, {"reason": "x", "amount": "1.00"}])
def test_refund_request_validation(client, customer, delivered, body):
    assert req(client, customer, delivered, body).status_code == 422


def test_refund_authorization(client, make_user, owner, customer, courier, delivered):
    stranger = make_user("customer", "stranger@example.com")
    other_owner = make_user("owner", "o2@example.com")
    assert req(client, stranger, delivered).status_code == 404  # can't touch others' orders
    assert req(client, owner, delivered).status_code == 403
    assert req(client, courier, delivered).status_code == 403
    assert req(client, {}, delivered).status_code == 401

    rid = req(client, customer, delivered).json()["id"]
    assert client.get("/api/v1/refund-requests/me", headers=stranger).json()["total"] == 0
    assert client.get("/api/v1/refund-requests/incoming", headers=other_owner).json()["total"] == 0
    assert client.get("/api/v1/refund-requests/me", headers=owner).status_code == 403
    assert client.get("/api/v1/refund-requests/incoming", headers=customer).status_code == 403
    assert decide(client, other_owner, rid, "approve").status_code == 404
    assert decide(client, customer, rid, "approve").status_code == 403
    assert decide(client, courier, rid, "approve").status_code == 403
    assert decide(client, owner, uuid.uuid4(), "approve").status_code == 404
    assert client.post(f"/api/v1/refund-requests/{rid}/decision", json={"decision": "processed"},
                       headers=owner).status_code == 422


def test_failure_during_approval_rolls_back_everything(client, owner, customer, delivered, monkeypatch):
    rid = req(client, customer, delivered).json()["id"]
    charge_ref = ledger(client, customer, delivered)[0]["reference"]
    # Reversal entry reuses the charge's reference -> unique violation at COMMIT, after the
    # request and payment were already updated in the transaction.
    monkeypatch.setattr(refund_service, "refund_reference", lambda _id: charge_ref)
    assert decide(client, owner, rid, "approve").status_code == 500

    assert client.get("/api/v1/refund-requests/me", headers=customer).json()["items"][0]["status"] == "requested"
    assert client.get(f"/api/v1/orders/{delivered}/payment", headers=customer).json()["status"] == "paid"
    assert len(ledger(client, customer, delivered)) == 1

    monkeypatch.undo()
    assert decide(client, owner, rid, "approve").json()["status"] == "processed"


def test_concurrent_approvals_refund_once(client, owner, customer, delivered):
    rid = req(client, customer, delivered).json()["id"]
    db_a = next(app.dependency_overrides[get_db]())
    db_a.get(RefundRequest, uuid.UUID(rid))  # A has read 'requested' and 'paid'
    order_service.load_order(db_a, uuid.UUID(delivered))
    owner_user = db_a.query(User).filter_by(email="owner@example.com").one()

    assert decide(client, owner, rid, "approve").status_code == 200  # B wins
    with pytest.raises(ConflictError):
        refund_service.decide_refund(db_a, owner_user, uuid.UUID(rid), "approve")
    db_a.close()
    assert [e["transaction_type"] for e in ledger(client, customer, delivered)].count("refund") == 1
