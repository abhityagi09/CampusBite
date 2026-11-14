import os

# Must be set before the app is imported. By default tests use a throwaway in-memory
# SQLite database and never touch your real data. To run them against a disposable
# PostgreSQL database instead, set TEST_DATABASE_URL (it is wiped after every test).
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
if TEST_DATABASE_URL and "test" not in TEST_DATABASE_URL.rsplit("/", 1)[-1].lower():
    # The fixtures drop every table in this database. Refuse to touch a real one.
    raise RuntimeError(
        "TEST_DATABASE_URL must point at a throwaway database whose name contains "
        "'test' (e.g. campusbite_test). Tests wipe it."
    )
os.environ["DATABASE_URL"] = TEST_DATABASE_URL or "sqlite://"
os.environ["SECRET_KEY"] = "test-secret-key-that-is-long-enough-for-hs256-0123456789"
os.environ["BCRYPT_ROUNDS"] = "4"  # fast hashing in tests only
STAFF_KEY = "test-staff-registration-key"
os.environ["STAFF_REGISTRATION_KEY"] = STAFF_KEY
os.environ["REMINDER_SCHEDULER_ENABLED"] = "false"  # the worker never runs inside tests
os.environ["OPENAI_API_KEY"] = ""  # AI tests configure it explicitly

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.database.base import Base  # noqa: E402
from app.database.session import get_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def client():
    if TEST_DATABASE_URL:
        engine = create_engine(TEST_DATABASE_URL)
        Base.metadata.drop_all(engine)
    else:
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
    Base.metadata.create_all(engine)  # tests only; the app itself never does this
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    if TEST_DATABASE_URL:
        Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def make_user(client):
    """Register + log in a user; returns Authorization headers."""

    def _make(role: str, email: str | None = None) -> dict[str, str]:
        email = email or f"{role}@example.com"
        resp = client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": "password123",
                "name": f"Test {role}",
                "role": role,
            },
            # owner / delivery_partner sign-up needs the staff key; customers don't
            headers={"X-Registration-Key": STAFF_KEY} if role != "customer" else {},
        )
        assert resp.status_code == 201, resp.text
        login = client.post(
            "/api/v1/auth/login/json", json={"email": email, "password": "password123"}
        )
        assert login.status_code == 200, login.text
        return {"Authorization": f"Bearer {login.json()['access_token']}"}

    return _make


@pytest.fixture
def owner(make_user):
    return make_user("owner")


@pytest.fixture
def customer(make_user):
    return make_user("customer")


@pytest.fixture
def courier(make_user):
    return make_user("delivery_partner")


class RestaurantId(str):
    """The restaurant's UUID (usable anywhere a string is) plus ``.menu``: name -> item UUID."""

    menu: dict[str, str]


@pytest.fixture
def restaurant(client, owner):
    """A restaurant with two menu items: Burger 5.50 and Fries 2.25 (ids in ``.menu``)."""
    resp = client.post(
        "/api/v1/restaurants",
        json={"name": "Campus Grill", "cuisine": "American", "location": "Block A"},
        headers=owner,
    )
    assert resp.status_code == 201, resp.text
    rid = RestaurantId(resp.json()["id"])
    rid.menu = {}
    for name, price in (("Burger", "5.50"), ("Fries", "2.25")):
        r = client.post(
            f"/api/v1/restaurants/{rid}/menu",
            json={"name": name, "price": price},
            headers=owner,
        )
        assert r.status_code == 201, r.text
        rid.menu[name] = r.json()["id"]
    return rid


def place_order(client, headers, restaurant_id, items=(("Burger", 2), ("Fries", 1))):
    """``items``: (menu item name or UUID, quantity) pairs."""
    menu = getattr(restaurant_id, "menu", {})
    resp = client.post(
        "/api/v1/orders",
        json={
            "restaurant_id": restaurant_id,
            "items": [{"menu_item_id": menu.get(i, i), "quantity": q} for i, q in items],
            "delivery_address": "Hostel 3, Room 204",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def pay(client, headers, order_id, **extra):
    return client.post(
        f"/api/v1/payments/orders/{order_id}/pay",
        json={"method": "upi", **extra},
        headers=headers,
    )


def set_status(client, headers, order_id, status):
    return client.patch(
        f"/api/v1/orders/{order_id}/status", json={"status": status}, headers=headers
    )


def deliver(client, owner, customer, courier, restaurant, items=(("Burger", 2), ("Fries", 1))):
    """Place, pay and run an order all the way to 'delivered'. Returns the order id."""
    oid = place_order(client, customer, restaurant, items)["id"]
    assert pay(client, customer, oid).status_code == 200
    courier_id = client.get("/api/v1/auth/me", headers=courier).json()["id"]
    for s in ("accepted", "preparing", "ready"):
        assert set_status(client, owner, oid, s).status_code == 200
    r = client.post(f"/api/v1/orders/{oid}/assign-delivery",
                    json={"delivery_partner_id": courier_id}, headers=owner)
    assert r.status_code == 200, r.text
    for s in ("out_for_delivery", "delivered"):
        assert set_status(client, courier, oid, s).status_code == 200
    return oid
