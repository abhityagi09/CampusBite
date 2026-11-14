"""Order lifecycle: transitions, permissions, cancellation, assignment, concurrency."""

import uuid

import pytest
from sqlalchemy import select

from app.core.exceptions import ConflictError
from app.database.session import get_db
from app.main import app
from app.models import OrderStatus, User
from app.services import order_service
from app.services.order_lifecycle import TRANSITIONS, Actor
from tests.conftest import pay, place_order, set_status

O = "/api/v1/orders"


def placed(client, customer, restaurant):
    oid = place_order(client, customer, restaurant)["id"]
    assert pay(client, customer, oid).json()["status"] == "mock_paid"
    return oid


def advance(client, owner, oid, *statuses):
    for s in statuses:
        r = set_status(client, owner, oid, s)
        assert r.status_code == 200, (s, r.text)


def user_id(client, headers):
    return client.get("/api/v1/auth/me", headers=headers).json()["id"]


def assign(client, owner, oid, partner_id):
    return client.post(f"{O}/{oid}/assign-delivery", json={"delivery_partner_id": partner_id}, headers=owner)


def session():
    return next(app.dependency_overrides[get_db]())


# ------------------------------------------------------------------ happy path


def test_full_lifecycle_with_audit_and_timestamps(client, owner, customer, courier, restaurant):
    oid = placed(client, customer, restaurant)
    advance(client, owner, oid, "accepted", "preparing", "ready")
    assert assign(client, owner, oid, user_id(client, courier)).status_code == 200
    advance(client, courier, oid, "out_for_delivery", "delivered")

    order = client.get(f"{O}/{oid}", headers=customer).json()
    expected = ["pending_payment", "placed", "accepted", "preparing",
                "ready", "assigned", "out_for_delivery", "delivered"]
    assert [e["status"] for e in order["events"]] == expected
    assert all(e["actor_id"] for e in order["events"])
    stamps = order["status_timestamps"]
    assert list(stamps) == expected
    assert sorted(stamps.values()) == list(stamps.values())  # chronological


# ------------------------------------------------------------------ invalid moves


@pytest.mark.parametrize("target", ["preparing", "ready", "out_for_delivery", "delivered"])
def test_skipping_statuses_is_refused(client, owner, customer, restaurant, target):
    oid = placed(client, customer, restaurant)
    assert set_status(client, owner, oid, target).status_code in (403, 409)
    assert client.get(f"{O}/{oid}", headers=customer).json()["status"] == "placed"


def test_reversed_and_repeated_transitions_are_refused(client, owner, customer, restaurant):
    oid = placed(client, customer, restaurant)
    advance(client, owner, oid, "accepted", "preparing")
    for target in ("accepted", "placed", "preparing", "pending_payment"):
        assert set_status(client, owner, oid, target).status_code == 409
    events = client.get(f"{O}/{oid}", headers=customer).json()["events"]
    assert [e["status"] for e in events].count("preparing") == 1


@pytest.mark.parametrize("terminal", ["rejected", "cancelled"])
def test_terminal_states_are_final(client, owner, customer, restaurant, terminal):
    oid = placed(client, customer, restaurant)
    if terminal == "rejected":
        advance(client, owner, oid, "rejected")
    else:
        assert client.post(f"{O}/{oid}/cancel", headers=customer).status_code == 200
    for target in ("accepted", "preparing", "rejected", "cancelled"):
        assert set_status(client, owner, oid, target).status_code == 409
    assert client.post(f"{O}/{oid}/cancel", headers=customer).status_code == 409


def test_transition_table_has_no_way_out_of_terminal_states():
    for s in (OrderStatus.REFUNDED, OrderStatus.CANCELLED, OrderStatus.REJECTED):
        assert s not in TRANSITIONS
    # delivered can only become refunded, and only by the system (approved refund request)
    assert TRANSITIONS[OrderStatus.DELIVERED] == {OrderStatus.REFUNDED: frozenset({Actor.SYSTEM})}
    for targets in TRANSITIONS.values():  # nothing ever goes back to the start
        assert OrderStatus.PENDING_PAYMENT not in targets


# ------------------------------------------------------------------ authorization


def test_unauthorized_status_updates(client, make_user, owner, customer, courier, restaurant):
    oid = placed(client, customer, restaurant)
    other_owner = make_user("owner", "other-owner@example.com")
    assert set_status(client, other_owner, oid, "accepted").status_code == 404
    assert set_status(client, customer, oid, "accepted").status_code == 403
    assert set_status(client, courier, oid, "accepted").status_code == 403  # not assigned
    assert set_status(client, {}, oid, "accepted").status_code == 401

    advance(client, owner, oid, "accepted", "preparing", "ready")
    # owner cannot do the courier's steps, unassigned courier cannot either
    assert set_status(client, owner, oid, "out_for_delivery").status_code == 409  # must be assigned first
    assert set_status(client, courier, oid, "out_for_delivery").status_code == 403  # not this courier's

    other_courier = make_user("delivery_partner", "c2@example.com")
    assign(client, owner, oid, user_id(client, other_courier))
    assert set_status(client, courier, oid, "out_for_delivery").status_code == 403
    advance(client, other_courier, oid, "out_for_delivery")
    # assigned courier cannot do the owner's steps
    assert client.get(f"{O}/{oid}", headers=customer).json()["status"] == "out_for_delivery"
    assert set_status(client, owner, oid, "delivered").status_code == 403


# ------------------------------------------------------------------ cancel / reject


@pytest.mark.parametrize("before", [[]])
def test_customer_can_cancel_before_preparation(client, owner, customer, restaurant, before):
    oid = placed(client, customer, restaurant)
    advance(client, owner, oid, *before)
    resp = client.post(f"{O}/{oid}/cancel", headers=customer)
    assert resp.status_code == 200 and resp.json()["status"] == "cancelled"
    assert resp.json()["payment"]["status"] == "refunded"


@pytest.mark.parametrize("path", [["accepted"], ["accepted", "preparing"], ["accepted", "preparing", "ready"]])
def test_customer_cannot_cancel_once_preparation_started(client, owner, customer, restaurant, path):
    oid = placed(client, customer, restaurant)
    advance(client, owner, oid, *path)
    assert client.post(f"{O}/{oid}/cancel", headers=customer).status_code == 409


def test_cancel_permissions(client, make_user, owner, courier, customer, restaurant):
    oid = placed(client, customer, restaurant)
    stranger = make_user("customer", "stranger@example.com")
    assert client.post(f"{O}/{oid}/cancel", headers=stranger).status_code == 404
    assert client.post(f"{O}/{oid}/cancel", headers=owner).status_code == 403
    assert client.post(f"{O}/{oid}/cancel", headers=courier).status_code == 403
    assert set_status(client, owner, oid, "cancelled").status_code == 403  # owners reject


@pytest.mark.parametrize("path,ok", [([], True), (["accepted"], True), (["accepted", "preparing"], False)])
def test_owner_reject_only_before_preparation(client, owner, customer, restaurant, path, ok):
    oid = placed(client, customer, restaurant)
    advance(client, owner, oid, *path)
    assert set_status(client, owner, oid, "rejected").status_code == (200 if ok else 409)


# ------------------------------------------------------------------ assignment


def test_assign_delivery_rules(client, make_user, owner, customer, courier, restaurant):
    oid = placed(client, customer, restaurant)
    cid = user_id(client, courier)
    assert assign(client, owner, oid, cid).status_code == 409  # placed
    advance(client, owner, oid, "accepted")
    assert assign(client, owner, oid, cid).status_code == 409  # accepted, not ready
    advance(client, owner, oid, "preparing")
    assert assign(client, owner, oid, cid).status_code == 409  # still cooking
    advance(client, owner, oid, "ready")

    assert assign(client, make_user("owner", "o2@example.com"), oid, cid).status_code == 404
    assert assign(client, customer, oid, cid).status_code == 403
    assert assign(client, courier, oid, cid).status_code == 403
    assert assign(client, owner, oid, user_id(client, customer)).status_code == 422  # not a courier
    assert assign(client, owner, oid, "00000000-0000-7000-8000-000000000000").status_code == 422

    inactive = make_user("delivery_partner", "inactive@example.com")
    inactive_id = user_id(client, inactive)
    db = session()
    db.get(User, uuid.UUID(inactive_id)).is_active = False
    db.commit()
    db.close()
    assert assign(client, owner, oid, inactive_id).status_code == 422

    resp = assign(client, owner, oid, cid)
    assert resp.status_code == 200 and resp.json()["delivery_partner_id"] == cid
    assert assign(client, owner, oid, cid).status_code == 200  # idempotent

    other = make_user("delivery_partner", "c2@example.com")
    assert assign(client, owner, oid, user_id(client, other)).status_code == 200  # reassign
    advance(client, other, oid, "out_for_delivery")
    assert assign(client, owner, oid, cid).status_code == 409  # after pickup


def test_deliveries_me(client, make_user, owner, customer, courier, restaurant):
    mine = [placed(client, customer, restaurant) for _ in range(2)]
    not_mine = placed(client, customer, restaurant)
    cid = user_id(client, courier)
    for oid in mine:
        advance(client, owner, oid, "accepted", "preparing", "ready")
        assign(client, owner, oid, cid)
    advance(client, owner, not_mine, "accepted")

    page = client.get("/api/v1/deliveries/me", headers=courier).json()
    assert page["total"] == 2 and {o["id"] for o in page["items"]} == set(mine)
    assert client.get("/api/v1/deliveries/me?status=delivered", headers=courier).json()["total"] == 0
    assert client.get("/api/v1/deliveries/me?limit=1", headers=courier).json()["total"] == 2
    assert client.get("/api/v1/deliveries/me", headers=customer).status_code == 403
    assert client.get("/api/v1/deliveries/me", headers=owner).status_code == 403
    assert client.get("/api/v1/deliveries/me").status_code == 401


# ------------------------------------------------------------------ concurrency


def _load(db, oid):
    return order_service.load_order(db, uuid.UUID(oid))


def test_stale_writer_loses_and_changes_nothing(client, owner, customer, restaurant):
    """Two owners' tabs: A reads 'placed', B accepts, then A (still holding 'placed')
    tries to reject. The compare-and-set write sees the status moved and refuses."""
    oid = placed(client, customer, restaurant)
    db_a = session()
    stale = _load(db_a, oid)
    owner_user = db_a.scalar(select(User).where(User.email == "owner@example.com"))
    assert stale.status == OrderStatus.PLACED

    advance(client, owner, oid, "accepted")  # B wins

    with pytest.raises(ConflictError):
        order_service._transition(db_a, stale, owner_user, OrderStatus.REJECTED, Actor.OWNER)
    db_a.close()

    order = client.get(f"{O}/{oid}", headers=customer).json()
    assert order["status"] == "accepted"
    assert "rejected" not in [e["status"] for e in order["events"]]
    assert order["payment"]["status"] == "mock_paid"  # no refund from the losing write


def test_customer_cancel_racing_owner_preparation(client, owner, customer, restaurant):
    oid = placed(client, customer, restaurant)
    db_a = session()
    stale = _load(db_a, oid)  # customer's view: placed, still cancellable
    cust = db_a.scalar(select(User).where(User.email == "customer@example.com"))

    advance(client, owner, oid, "accepted")  # owner accepts first

    with pytest.raises(ConflictError):
        order_service._transition(db_a, stale, cust, OrderStatus.CANCELLED, Actor.CUSTOMER)
    db_a.close()
    assert client.get(f"{O}/{oid}", headers=customer).json()["status"] == "accepted"


def test_stale_assignment_is_refused(client, make_user, owner, customer, courier, restaurant):
    from app.services import order_lifecycle

    oid = placed(client, customer, restaurant)
    advance(client, owner, oid, "accepted", "preparing", "ready")
    db_a = session()
    stale = _load(db_a, oid)  # sees no courier yet
    other = make_user("delivery_partner", "c2@example.com")
    assign(client, owner, oid, user_id(client, other))  # someone else assigns first

    with pytest.raises(ConflictError):
        order_lifecycle.compare_and_set(db_a, stale, stale.status,
                                        delivery_partner_id=uuid.UUID(user_id(client, courier)))
    db_a.close()
    order = client.get(f"{O}/{oid}", headers=customer).json()
    assert order["delivery_partner_id"] == user_id(client, other)
