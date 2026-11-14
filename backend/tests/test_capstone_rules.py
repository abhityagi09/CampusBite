"""Capstone lifecycle (READY -> ASSIGNED, DELIVERED -> REFUNDED) and API middleware."""

import logging

from tests.conftest import deliver, pay, place_order, set_status


def _ready(client, owner, customer, restaurant):
    oid = place_order(client, customer, restaurant)["id"]
    pay(client, customer, oid)
    for s in ("accepted", "preparing", "ready"):
        assert set_status(client, owner, oid, s).status_code == 200
    return oid


def test_assignment_moves_ready_to_assigned_with_audit(client, owner, customer, courier, restaurant):
    oid = _ready(client, owner, customer, restaurant)
    cid = client.get("/api/v1/auth/me", headers=courier).json()["id"]
    resp = client.post(f"/api/v1/orders/{oid}/assign-delivery", json={"delivery_partner_id": cid}, headers=owner)
    body = resp.json()
    assert body["status"] == "assigned" and body["delivery_partner_id"] == cid
    assert [e["status"] for e in body["events"]][-2:] == ["ready", "assigned"]
    assert "assigned" in body["status_timestamps"]
    # courier: assigned -> out_for_delivery -> delivered; nothing can be skipped
    assert set_status(client, courier, oid, "delivered").status_code == 409
    assert set_status(client, courier, oid, "out_for_delivery").json()["status"] == "out_for_delivery"
    assert set_status(client, courier, oid, "delivered").json()["status"] == "delivered"
    assert client.get("/api/v1/deliveries/me?status=delivered", headers=courier).json()["total"] == 1


def test_assignment_only_from_ready(client, owner, customer, courier, restaurant):
    cid = client.get("/api/v1/auth/me", headers=courier).json()["id"]
    oid = place_order(client, customer, restaurant)["id"]
    pay(client, customer, oid)
    url = f"/api/v1/orders/{oid}/assign-delivery"
    for s in ("accepted", "preparing"):
        set_status(client, owner, oid, s)
        assert client.post(url, json={"delivery_partner_id": cid}, headers=owner).status_code == 409
    done = deliver(client, owner, customer, courier, restaurant)
    assert client.post(f"/api/v1/orders/{done}/assign-delivery", json={"delivery_partner_id": cid},
                       headers=owner).status_code == 409


def test_refund_approval_moves_order_to_refunded(client, owner, customer, courier, restaurant):
    oid = deliver(client, owner, customer, courier, restaurant)
    assert set_status(client, owner, oid, "refunded").status_code == 409  # never directly
    rid = client.post(f"/api/v1/orders/{oid}/refund-requests", json={"reason": "cold"}, headers=customer).json()["id"]
    client.post(f"/api/v1/refund-requests/{rid}/decision", json={"decision": "approve"}, headers=owner)
    order = client.get(f"/api/v1/orders/{oid}", headers=customer).json()
    assert order["status"] == "refunded" and order["payment"]["status"] == "refunded"
    assert order["events"][-1]["status"] == "refunded"
    assert client.post(f"/api/v1/orders/{oid}/cancel", headers=customer).status_code == 409
    # a refunded order was still delivered: the customer may review it
    assert client.post("/api/v1/reviews", json={"order_id": oid, "rating": 3}, headers=customer).status_code == 201


def test_rejected_refund_keeps_order_delivered(client, owner, customer, courier, restaurant):
    oid = deliver(client, owner, customer, courier, restaurant)
    rid = client.post(f"/api/v1/orders/{oid}/refund-requests", json={"reason": "late"}, headers=customer).json()["id"]
    assert client.post(f"/api/v1/refund-requests/{rid}/decision", json={"decision": "reject"},
                       headers=owner).json()["status"] == "rejected"
    order = client.get(f"/api/v1/orders/{oid}", headers=customer).json()
    assert order["status"] == "delivered" and order["payment"]["status"] == "mock_paid"


def test_request_logging_and_timing_middleware(client, caplog):
    with caplog.at_level(logging.INFO, logger="campusbite.access"):
        resp = client.get("/api/v1/restaurants?q=secret-query")
    assert resp.status_code == 200
    assert float(resp.headers["x-process-time-ms"]) >= 0
    line = next(r.getMessage() for r in caplog.records if r.name == "campusbite.access")
    assert line.startswith("GET /api/v1/restaurants -> 200 (") and line.endswith(" ms)")
    assert "secret-query" not in caplog.text  # query strings are never logged


def test_cors_exposes_headers_the_frontend_reads(client):
    resp = client.get("/health", headers={"Origin": "http://localhost:5173"})
    exposed = resp.headers["access-control-expose-headers"].lower()
    for h in ("retry-after", "idempotent-replayed", "x-process-time-ms"):
        assert h in exposed
