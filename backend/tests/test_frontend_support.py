"""Small endpoints added for the frontend."""

from datetime import datetime, timedelta, timezone

from tests.conftest import place_order


def test_delivery_partner_directory_is_owner_only(client, make_user, owner, customer, courier):
    make_user("delivery_partner", "zed@example.com")
    resp = client.get("/api/v1/users/delivery-partners", headers=owner)
    assert resp.status_code == 200
    assert [set(p) for p in resp.json()] == [{"id", "name"}] * 2  # no e-mail / phone
    for who in (customer, courier):
        assert client.get("/api/v1/users/delivery-partners", headers=who).status_code == 403
    assert client.get("/api/v1/users/delivery-partners").status_code == 401


def test_my_orders_date_filter(client, customer, restaurant):
    place_order(client, customer, restaurant)
    today = datetime.now(timezone.utc).date()  # the filter works in UTC days
    url = "/api/v1/orders/me"
    for q, total in [(f"created_from={today - timedelta(days=1)}", 1),
                     (f"created_to={today - timedelta(days=1)}", 0),
                     (f"created_from={today + timedelta(days=1)}", 0),
                     (f"created_from={today - timedelta(days=1)}&created_to={today + timedelta(days=1)}", 1)]:
        assert client.get(f"{url}?{q}", headers=customer).json()["total"] == total, q
    assert client.get(f"{url}?created_from={today}&created_to={today - timedelta(days=1)}", headers=customer).status_code == 422
    assert client.get(f"{url}?created_from=not-a-date", headers=customer).status_code == 422
