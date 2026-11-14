"""Restaurant and menu APIs: public browsing/search, owner CRUD, validation, access control
and unavailable / soft-disabled menu items."""

import uuid

import pytest

from tests.conftest import place_order

API = "/api/v1/restaurants"


def _create_restaurant(client, headers, **body):
    resp = client.post(API, json={"name": "R", **body}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _add_item(client, headers, rid, **body):
    resp = client.post(f"{API}/{rid}/menu", json={"name": "Item", "price": "1.00", **body}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _names(page):
    return [x["name"] for x in page["items"]]


# ============================================================ public: restaurants


def test_list_restaurants_is_public_and_paginated(client, owner, restaurant):
    _create_restaurant(client, owner, name="Dosa Corner", cuisine="Indian")
    _create_restaurant(client, owner, name="Bagel Bar", cuisine="Bakery")

    page = client.get(API).json()  # no auth header
    assert page["total"] == 3 and page["limit"] == 20 and page["offset"] == 0
    assert _names(page) == ["Bagel Bar", "Campus Grill", "Dosa Corner"]

    p1 = client.get(f"{API}?limit=2").json()
    p2 = client.get(f"{API}?limit=2&offset=2").json()
    assert _names(p1) == ["Bagel Bar", "Campus Grill"] and p1["total"] == 3
    assert _names(p2) == ["Dosa Corner"] and p2["total"] == 3
    assert client.get(f"{API}?offset=10").json() == {"items": [], "total": 3, "limit": 20, "offset": 10}


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1", "limit=abc", "q="])
def test_list_restaurants_rejects_bad_query_params(client, query):
    assert client.get(f"{API}?{query}").status_code == 422


def test_restaurant_filters_and_search(client, owner, restaurant):
    _create_restaurant(
        client, owner, name="Dosa Corner", cuisine="Indian", location="Block B",
        description="Crispy south indian breakfast", is_open=False,
    )
    assert _names(client.get(f"{API}?q=dosa").json()) == ["Dosa Corner"]  # name
    assert _names(client.get(f"{API}?q=AMERICAN").json()) == ["Campus Grill"]  # cuisine
    assert _names(client.get(f"{API}?q=breakfast").json()) == ["Dosa Corner"]  # description
    assert _names(client.get(f"{API}?cuisine=indian").json()) == ["Dosa Corner"]
    assert _names(client.get(f"{API}?location=block a").json()) == ["Campus Grill"]
    assert _names(client.get(f"{API}?open_only=true").json()) == ["Campus Grill"]
    assert client.get(f"{API}?q=dosa&open_only=true").json()["total"] == 0
    # LIKE wildcards in the search text are matched literally
    assert client.get(f"{API}?q=%25").json()["total"] == 0


def test_restaurant_detail_shows_only_available_items(client, owner, restaurant):
    client.post(f"{API}/{restaurant}/menu/{restaurant.menu['Fries']}/disable", headers=owner)
    detail = client.get(f"{API}/{restaurant}").json()
    assert detail["name"] == "Campus Grill"
    assert [m["name"] for m in detail["menu_items"]] == ["Burger"]


def test_missing_or_malformed_restaurant(client):
    assert client.get(f"{API}/{uuid.uuid4()}").status_code == 404
    assert client.get(f"{API}/{uuid.uuid4()}/menu").status_code == 404
    assert client.get(f"{API}/999").status_code == 422  # ids are UUIDs


def test_inactive_restaurant_is_hidden_from_public_but_not_owner(client, owner, restaurant):
    resp = client.patch(f"{API}/{restaurant}", json={"is_active": False}, headers=owner)
    assert resp.status_code == 200 and resp.json()["is_active"] is False

    assert client.get(API).json()["total"] == 0
    assert client.get(f"{API}/{restaurant}").status_code == 404
    assert client.get(f"{API}/{restaurant}/menu").status_code == 404
    assert client.get("/api/v1/menu-items?q=burger").json()["total"] == 0

    mine = client.get(f"{API}/mine", headers=owner).json()
    assert mine["total"] == 1 and mine["items"][0]["is_active"] is False
    # and the owner can bring it back
    assert client.patch(f"{API}/{restaurant}", json={"is_active": True}, headers=owner).status_code == 200
    assert client.get(f"{API}/{restaurant}").status_code == 200


# ============================================================ public: menu


def test_public_menu_lists_available_items_with_filters(client, owner, restaurant):
    _add_item(client, owner, restaurant, name="Cola", price="1.50", category="Drinks")
    _add_item(client, owner, restaurant, name="Shake", price="3.75", category="Drinks", is_available=False)

    menu = client.get(f"{API}/{restaurant}/menu").json()  # no auth
    assert _names(menu) == ["Burger", "Fries", "Cola"] and menu["total"] == 3
    assert _names(client.get(f"{API}/{restaurant}/menu?category=drinks").json()) == ["Cola"]
    assert _names(client.get(f"{API}/{restaurant}/menu?min_price=3&max_price=6").json()) == ["Burger"]
    assert _names(client.get(f"{API}/{restaurant}/menu?q=fri").json()) == ["Fries"]
    page = client.get(f"{API}/{restaurant}/menu?limit=1&offset=1").json()
    assert _names(page) == ["Fries"] and page["total"] == 3


def test_public_menu_never_shows_unavailable_items_even_to_owner(client, owner, restaurant):
    client.patch(f"{API}/{restaurant}/menu/{restaurant.menu['Fries']}", json={"is_available": False}, headers=owner)
    assert _names(client.get(f"{API}/{restaurant}/menu", headers=owner).json()) == ["Burger"]


def test_menu_price_range_validation(client, restaurant):
    assert client.get(f"{API}/{restaurant}/menu?min_price=5&max_price=1").status_code == 422
    assert client.get(f"{API}/{restaurant}/menu?min_price=-1").status_code == 422
    assert client.get("/api/v1/menu-items?min_price=5&max_price=1").status_code == 422


def test_menu_item_search_across_restaurants(client, owner, make_user, restaurant):
    other = make_user("owner", "other@example.com")
    pizza = _create_restaurant(client, other, name="Pizza Place", is_open=False)
    _add_item(client, other, pizza["id"], name="Veggie Burger", price="7.00", category="Mains")
    _add_item(client, other, pizza["id"], name="Secret Burger", price="9.00", is_available=False)
    hidden = _create_restaurant(client, other, name="Hidden")
    _add_item(client, other, hidden["id"], name="Ghost Burger", price="4.00")
    client.patch(f"{API}/{hidden['id']}", json={"is_active": False}, headers=other)

    result = client.get("/api/v1/menu-items?q=burger").json()  # public
    assert _names(result) == ["Burger", "Veggie Burger"]  # sorted by name, no hidden/disabled
    assert result["total"] == 2
    veggie = result["items"][1]
    assert veggie["restaurant_name"] == "Pizza Place" and veggie["restaurant_is_open"] is False
    assert veggie["restaurant_id"] == pizza["id"]

    assert _names(client.get("/api/v1/menu-items?q=burger&open_only=true").json()) == ["Burger"]
    assert _names(client.get(f"/api/v1/menu-items?restaurant_id={pizza['id']}").json()) == ["Veggie Burger"]
    assert _names(client.get("/api/v1/menu-items?category=mains").json()) == ["Veggie Burger"]
    assert _names(client.get("/api/v1/menu-items?max_price=3").json()) == ["Fries"]
    assert client.get("/api/v1/menu-items?limit=1").json()["total"] == 3  # every available item in active restaurants


# ============================================================ owner: restaurants


def test_owner_creates_and_updates_restaurant(client, owner):
    created = _create_restaurant(
        client, owner, name="  Noodle Hut  ", cuisine="Chinese", description="Hand-pulled"
    )
    assert created["name"] == "Noodle Hut"  # whitespace stripped
    assert created["is_active"] is True and created["is_open"] is True
    assert created["average_rating"] is None and created["review_count"] == 0

    rid = created["id"]
    resp = client.patch(f"{API}/{rid}", json={"name": "Noodle House", "is_open": False}, headers=owner)
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Noodle House" and body["is_open"] is False
    assert body["cuisine"] == "Chinese"  # untouched fields are kept

    # explicit null clears an optional field
    cleared = client.patch(f"{API}/{rid}", json={"description": None}, headers=owner).json()
    assert cleared["description"] is None and cleared["name"] == "Noodle House"


def test_owner_lists_own_restaurants_only_with_all_items(client, owner, make_user, restaurant):
    other = make_user("owner", "other@example.com")
    _create_restaurant(client, other, name="Not Mine")
    client.post(f"{API}/{restaurant}/menu/{restaurant.menu['Fries']}/disable", headers=owner)

    mine = client.get(f"{API}/mine", headers=owner).json()
    assert _names(mine) == ["Campus Grill"] and mine["total"] == 1
    assert {m["name"] for m in mine["items"][0]["menu_items"]} == {"Burger", "Fries"}


@pytest.mark.parametrize(
    "body",
    [
        {},  # name missing
        {"name": ""},
        {"name": "   "},  # whitespace only
        {"name": "x" * 121},
        {"name": "X", "cuisine": "c" * 61},
        {"name": "X", "is_open": "maybe"},
    ],
)
def test_create_restaurant_validation(client, owner, body):
    resp = client.post(API, json=body, headers=owner)
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Validation error"


@pytest.mark.parametrize(
    "body", [{"name": None}, {"name": ""}, {"is_open": None}, {"is_active": None}]
)
def test_update_restaurant_validation(client, owner, restaurant, body):
    assert client.patch(f"{API}/{restaurant}", json=body, headers=owner).status_code == 422
    assert client.get(f"{API}/{restaurant}").json()["name"] == "Campus Grill"


def test_update_missing_restaurant_is_404(client, owner):
    assert client.patch(f"{API}/{uuid.uuid4()}", json={"name": "X"}, headers=owner).status_code == 404


# ============================================================ owner: menu items


def test_menu_item_crud(client, owner, restaurant):
    created = _add_item(
        client, owner, restaurant, name="Wrap", price="4.5", category="Mains", description="Chicken"
    )
    assert created["price"] == "4.50" and created["is_available"] is True
    assert created["restaurant_id"] == restaurant
    item = f"{API}/{restaurant}/menu/{created['id']}"

    upd = client.patch(item, json={"price": "4.95", "category": None}, headers=owner)
    assert upd.status_code == 200
    assert upd.json()["price"] == "4.95" and upd.json()["category"] is None
    assert upd.json()["name"] == "Wrap"

    disabled = client.post(f"{item}/disable", headers=owner)
    assert disabled.status_code == 200 and disabled.json()["is_available"] is False
    assert client.post(f"{item}/disable", headers=owner).status_code == 200  # idempotent
    enabled = client.post(f"{item}/enable", headers=owner)
    assert enabled.status_code == 200 and enabled.json()["is_available"] is True

    # never ordered -> really deleted
    assert client.delete(item, headers=owner).status_code == 204
    assert client.patch(item, json={"price": "1.00"}, headers=owner).status_code == 404
    assert client.delete(item, headers=owner).status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"name": "Free", "price": "0"},
        {"name": "Neg", "price": "-1.00"},
        {"name": "Fraction", "price": "1.999"},  # more than 2 decimals
        {"name": "Huge", "price": "100000000.00"},  # exceeds Numeric(10, 2)
        {"name": "NaN", "price": "abc"},
        {"price": "1.00"},  # name missing
        {"name": "", "price": "1.00"},
        {"name": "   ", "price": "1.00"},
        {"name": "No price"},
        {"name": "Desc", "price": "1.00", "description": "d" * 1001},
    ],
)
def test_create_menu_item_validation(client, owner, restaurant, body):
    resp = client.post(f"{API}/{restaurant}/menu", json=body, headers=owner)
    assert resp.status_code == 422, resp.text


@pytest.mark.parametrize(
    "body",
    [{"price": "0"}, {"price": "-5"}, {"price": None}, {"name": None}, {"name": ""}, {"is_available": None}],
)
def test_update_menu_item_validation(client, owner, restaurant, body):
    item = f"{API}/{restaurant}/menu/{restaurant.menu['Burger']}"
    assert client.patch(item, json=body, headers=owner).status_code == 422
    menu = client.get(f"{API}/{restaurant}/menu").json()["items"]
    burger = next(m for m in menu if m["name"] == "Burger")
    assert burger["price"] == "5.50"


def test_menu_item_must_belong_to_the_restaurant_in_the_url(client, owner, restaurant):
    second = _create_restaurant(client, owner, name="Second")
    wrong = f"{API}/{second['id']}/menu/{restaurant.menu['Burger']}"
    assert client.patch(wrong, json={"price": "1.00"}, headers=owner).status_code == 404
    assert client.post(f"{wrong}/disable", headers=owner).status_code == 404
    assert client.delete(wrong, headers=owner).status_code == 404
    assert client.post(f"{API}/{uuid.uuid4()}/menu", json={"name": "X", "price": "1"}, headers=owner).status_code == 404


def test_owner_menu_items_view_includes_disabled_items(client, owner, make_user, restaurant):
    second = _create_restaurant(client, owner, name="Second")
    _add_item(client, owner, second["id"], name="Tea", price="1.00", category="Drinks")
    client.post(f"{API}/{restaurant}/menu/{restaurant.menu['Fries']}/disable", headers=owner)
    other = make_user("owner", "other@example.com")
    foreign = _create_restaurant(client, other, name="Foreign")
    _add_item(client, other, foreign["id"], name="Foreign Item")

    url = f"{API}/mine/menu-items"
    all_items = client.get(url, headers=owner).json()
    assert all_items["total"] == 3
    assert {m["name"] for m in all_items["items"]} == {"Burger", "Fries", "Tea"}

    assert _names(client.get(f"{url}?is_available=false", headers=owner).json()) == ["Fries"]
    assert _names(client.get(f"{url}?restaurant_id={second['id']}", headers=owner).json()) == ["Tea"]
    assert _names(client.get(f"{url}?category=drinks", headers=owner).json()) == ["Tea"]
    page = client.get(f"{url}?limit=2", headers=owner).json()
    assert len(page["items"]) == 2 and page["total"] == 3

    # filtering by someone else's restaurant is refused, not silently empty
    assert client.get(f"{url}?restaurant_id={foreign['id']}", headers=owner).status_code == 403
    assert client.get(f"{url}?restaurant_id={uuid.uuid4()}", headers=owner).status_code == 404


# ============================================================ access control


def test_cross_owner_writes_are_forbidden(client, make_user, restaurant):
    intruder = make_user("owner", "intruder@example.com")
    base = f"{API}/{restaurant}"
    item = f"{base}/menu/{restaurant.menu['Burger']}"

    assert client.patch(base, json={"name": "Hijack"}, headers=intruder).status_code == 403
    assert client.patch(base, json={"is_active": False}, headers=intruder).status_code == 403
    assert client.post(f"{base}/menu", json={"name": "Spam", "price": "1.00"}, headers=intruder).status_code == 403
    assert client.patch(item, json={"price": "0.01"}, headers=intruder).status_code == 403
    assert client.post(f"{item}/disable", headers=intruder).status_code == 403
    assert client.post(f"{item}/enable", headers=intruder).status_code == 403
    assert client.delete(item, headers=intruder).status_code == 403

    # nothing changed
    detail = client.get(base).json()
    assert detail["name"] == "Campus Grill" and detail["is_active"] is True
    assert [(m["name"], m["price"]) for m in detail["menu_items"]] == [("Burger", "5.50"), ("Fries", "2.25")]
    assert client.get(f"{API}/mine", headers=intruder).json()["total"] == 0


@pytest.mark.parametrize("role", ["customer", "delivery_partner", None])
def test_non_owners_cannot_use_owner_endpoints(client, make_user, restaurant, role):
    headers = make_user(role, f"{role}-x@example.com") if role else {}
    expected = 403 if role else 401
    base = f"{API}/{restaurant}"
    item = f"{base}/menu/{restaurant.menu['Burger']}"
    calls = [
        ("post", API, {"name": "X"}),
        ("patch", base, {"name": "X"}),
        ("get", f"{API}/mine", None),
        ("get", f"{API}/mine/menu-items", None),
        ("post", f"{base}/menu", {"name": "X", "price": "1.00"}),
        ("patch", item, {"price": "1.00"}),
        ("post", f"{item}/disable", None),
        ("post", f"{item}/enable", None),
        ("delete", item, None),
    ]
    for method, url, body in calls:
        kwargs = {"headers": headers} | ({"json": body} if body is not None else {})
        resp = getattr(client, method)(url, **kwargs)
        assert resp.status_code == expected, (method, url, resp.status_code)

    assert client.get(base).json()["name"] == "Campus Grill"


def test_customers_and_couriers_can_browse(client, customer, courier, restaurant):
    for headers in (customer, courier):
        assert client.get(API, headers=headers).json()["total"] == 1
        assert client.get(f"{API}/{restaurant}/menu", headers=headers).json()["total"] == 2


# ============================================================ unavailable / soft-disabled items


def test_unavailable_item_cannot_be_ordered(client, owner, customer, restaurant):
    burger = restaurant.menu["Burger"]
    client.post(f"{API}/{restaurant}/menu/{burger}/disable", headers=owner)
    resp = client.post(
        "/api/v1/orders",
        json={
            "restaurant_id": restaurant,
            "items": [{"menu_item_id": burger, "quantity": 1}],
            "delivery_address": "Hostel 3",
        },
        headers=customer,
    )
    assert resp.status_code == 400
    # re-enabling makes it orderable again
    client.post(f"{API}/{restaurant}/menu/{burger}/enable", headers=owner)
    place_order(client, customer, restaurant, items=(("Burger", 1),))


def test_deleting_an_ordered_item_soft_disables_it(client, owner, customer, restaurant):
    order = place_order(client, customer, restaurant, items=(("Burger", 2),))
    burger = restaurant.menu["Burger"]

    assert client.delete(f"{API}/{restaurant}/menu/{burger}", headers=owner).status_code == 204

    # gone for customers ...
    assert _names(client.get(f"{API}/{restaurant}/menu").json()) == ["Fries"]
    assert client.get("/api/v1/menu-items?q=burger").json()["total"] == 0
    # ... but kept (disabled) for the owner and for order history
    owned = client.get(f"{API}/mine/menu-items?is_available=false", headers=owner).json()
    assert [(m["id"], m["name"]) for m in owned["items"]] == [(burger, "Burger")]
    history = client.get(f"/api/v1/orders/{order['id']}", headers=customer).json()
    assert history["items"][0]["menu_item_id"] == burger
    assert history["items"][0]["name"] == "Burger"

    # editing the item never rewrites the historical snapshot
    client.patch(f"{API}/{restaurant}/menu/{burger}", json={"name": "Big Burger", "price": "9.99"}, headers=owner)
    history = client.get(f"/api/v1/orders/{order['id']}", headers=customer).json()
    assert history["items"][0]["name"] == "Burger"
    assert history["items"][0]["unit_price"] == "5.50"


def test_deleting_an_unordered_item_removes_it(client, owner, customer, restaurant):
    place_order(client, customer, restaurant, items=(("Burger", 1),))
    fries = restaurant.menu["Fries"]
    assert client.delete(f"{API}/{restaurant}/menu/{fries}", headers=owner).status_code == 204
    ids = [m["id"] for m in client.get(f"{API}/mine/menu-items", headers=owner).json()["items"]]
    assert fries not in ids and restaurant.menu["Burger"] in ids


def test_service_rules_hold_without_routes(client, owner, restaurant):
    """Defence in depth: services re-check role and ownership themselves."""
    from app.core.exceptions import ForbiddenError
    from app.models import User, UserRole
    from app.services import restaurant_service as svc
    from app.services.restaurant_service import MenuFilters, Pagination

    stranger = User(id=uuid.uuid4(), name="o", email="o@x.com", password_hash="x", role=UserRole.OWNER)
    customer = User(id=uuid.uuid4(), name="c", email="c@x.com", password_hash="x", role=UserRole.CUSTOMER)
    with pytest.raises(ForbiddenError):
        svc.list_owner_menu_items(None, customer, MenuFilters(), Pagination())
    with pytest.raises(ForbiddenError):
        svc.list_owner_restaurants(None, customer, Pagination())

    from app.database.session import get_db
    from app.main import app

    db = next(app.dependency_overrides[get_db]())
    try:
        with pytest.raises(ForbiddenError):
            svc.delete_menu_item(db, stranger, uuid.UUID(restaurant), uuid.UUID(restaurant.menu["Burger"]))
    finally:
        db.close()
