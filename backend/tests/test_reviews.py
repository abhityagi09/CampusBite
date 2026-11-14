import uuid

from tests.conftest import pay, place_order, set_status


def _deliver(client, owner, customer, courier, restaurant):
    oid = place_order(client, customer, restaurant)["id"]
    pay(client, customer, oid)
    for s in ("accepted", "preparing", "ready_for_pickup"):
        set_status(client, owner, oid, s)
    client.post(f"/api/v1/orders/{oid}/claim", headers=courier)
    for s in ("out_for_delivery", "delivered"):
        set_status(client, courier, oid, s)
    return oid


def test_review_requires_delivered_order(client, customer, restaurant):
    oid = place_order(client, customer, restaurant)["id"]
    resp = client.post("/api/v1/reviews", json={"order_id": oid, "rating": 5}, headers=customer)
    assert resp.status_code == 400


def test_review_flow_and_rating_average(client, make_user, owner, customer, courier, restaurant):
    oid = _deliver(client, owner, customer, courier, restaurant)

    assert client.post("/api/v1/reviews", json={"order_id": oid, "rating": 6}, headers=customer).status_code == 422
    other = make_user("customer", "c2@example.com")
    assert client.post("/api/v1/reviews", json={"order_id": oid, "rating": 5}, headers=other).status_code == 404
    assert client.post("/api/v1/reviews", json={"order_id": oid, "rating": 5}, headers=owner).status_code == 403

    ok = client.post(
        "/api/v1/reviews",
        json={"order_id": oid, "rating": 4, "comment": "Tasty"},
        headers=customer,
    )
    assert ok.status_code == 201
    assert client.post("/api/v1/reviews", json={"order_id": oid, "rating": 5}, headers=customer).status_code == 409

    oid2 = _deliver(client, owner, other, courier, restaurant)
    client.post("/api/v1/reviews", json={"order_id": oid2, "rating": 5}, headers=other)

    detail = client.get(f"/api/v1/restaurants/{restaurant}").json()
    assert detail["average_rating"] == 4.5
    assert detail["review_count"] == 2
    listed = client.get(f"/api/v1/reviews/restaurant/{restaurant}").json()
    assert len(listed) == 2
    assert client.get(f"/api/v1/reviews/restaurant/{uuid.uuid4()}").status_code == 404


def test_delete_own_review_only(client, make_user, owner, customer, courier, restaurant):
    oid = _deliver(client, owner, customer, courier, restaurant)
    rid = client.post("/api/v1/reviews", json={"order_id": oid, "rating": 3}, headers=customer).json()["id"]
    other = make_user("customer", "c2@example.com")
    assert client.delete(f"/api/v1/reviews/{rid}", headers=other).status_code == 404
    assert client.delete(f"/api/v1/reviews/{rid}", headers=customer).status_code == 204
    assert client.get(f"/api/v1/restaurants/{restaurant}").json()["review_count"] == 0
