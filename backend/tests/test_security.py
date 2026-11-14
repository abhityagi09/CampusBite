"""JWT authentication and role-based authorization."""

import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.core.exceptions import ForbiddenError
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.database.session import get_db
from app.main import app
from app.models import User, UserRole
from app.services import order_service, restaurant_service
from tests.conftest import STAFF_KEY

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
LOGIN_JSON = "/api/v1/auth/login/json"
ME = "/api/v1/auth/me"


def _body(**kw):
    body = {"email": "new@example.com", "password": "password123", "name": "New", "role": "customer"}
    body.update(kw)
    return body


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _my_id(client, headers) -> str:
    return client.get(ME, headers=headers).json()["id"]


def _forge(claims: dict, key: str | None = None, algorithm: str | None = None) -> str:
    base = {
        "sub": str(uuid.uuid4()),
        "type": "access",
        "iss": settings.JWT_ISSUER,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    base.update(claims)
    base = {k: v for k, v in base.items() if v is not None}
    return jwt.encode(base, key or settings.SECRET_KEY, algorithm=algorithm or settings.JWT_ALGORITHM)


# ------------------------------------------------------------------ registration


def test_register_returns_user_without_password_material(client):
    resp = client.post(REGISTER, json=_body(email="Mixed@Example.com"))
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "mixed@example.com"
    assert data["role"] == "customer"
    assert uuid.UUID(data["id"])
    assert not {"password", "password_hash", "hashed_password"} & data.keys()
    assert "$2" not in resp.text  # no bcrypt hash anywhere in the body


def test_password_is_stored_as_bcrypt_hash():
    h = hash_password("password123")
    assert h.startswith("$2") and h != "password123"
    assert verify_password("password123", h)
    assert not verify_password("password124", h)
    assert not verify_password("password123", "not-a-hash")


@pytest.mark.parametrize(
    "overrides",
    [
        {"email": "nope"},
        {"password": "short1"},  # < 8 chars
        {"password": "alllettersnodigit"},
        {"password": "12345678901"},  # no letter
        {"password": "a1" * 40},  # > 72 bytes
        {"role": "admin"},
        {"name": ""},
        {"is_active": True},  # unknown fields are rejected, not ignored
    ],
)
def test_register_validation(client, overrides):
    assert client.post(REGISTER, json=_body(**overrides)).status_code == 422


def test_duplicate_email_is_a_conflict_ignoring_case(client):
    assert client.post(REGISTER, json=_body()).status_code == 201
    assert client.post(REGISTER, json=_body(email="NEW@example.com")).status_code == 409


@pytest.mark.parametrize("role", ["owner", "delivery_partner"])
def test_privileged_roles_cannot_self_register(client, monkeypatch, role):
    # no key header at all
    assert client.post(REGISTER, json=_body(role=role)).status_code == 403
    # wrong key
    bad = client.post(REGISTER, json=_body(role=role), headers={"X-Registration-Key": "wrong"})
    assert bad.status_code == 403
    # correct key
    ok = client.post(REGISTER, json=_body(role=role), headers={"X-Registration-Key": STAFF_KEY})
    assert ok.status_code == 201 and ok.json()["role"] == role


def test_privileged_registration_is_off_when_no_key_is_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "STAFF_REGISTRATION_KEY", None)
    resp = client.post(
        REGISTER, json=_body(role="owner"), headers={"X-Registration-Key": STAFF_KEY}
    )
    assert resp.status_code == 403
    assert client.post(REGISTER, json=_body(email="c@example.com")).status_code == 201  # customers fine


def test_customer_registration_ignores_a_staff_key(client):
    resp = client.post(REGISTER, json=_body(), headers={"X-Registration-Key": "anything"})
    assert resp.status_code == 201 and resp.json()["role"] == "customer"


# ------------------------------------------------------------------ login


def test_login_form_and_json_issue_a_verifiable_token(client, customer):
    form = client.post(LOGIN, data={"username": "customer@example.com", "password": "password123"})
    assert form.status_code == 200
    body = form.json()
    assert body["token_type"] == "bearer"
    claims = decode_access_token(body["access_token"])
    assert claims["type"] == "access" and claims["iss"] == settings.JWT_ISSUER
    assert claims["sub"] == body["user"]["id"]
    assert "password_hash" not in body["user"]

    js = client.post(LOGIN_JSON, json={"email": "CUSTOMER@example.com", "password": "password123"})
    assert js.status_code == 200
    assert js.json()["access_token"] != body["access_token"]  # unique jti per token


def test_token_lifetime_follows_configuration(monkeypatch):
    monkeypatch.setattr(settings, "ACCESS_TOKEN_EXPIRE_MINUTES", 7)
    claims = decode_access_token(create_access_token(uuid.uuid4()))
    assert claims["exp"] - claims["iat"] == 7 * 60


def test_invalid_credentials_are_indistinguishable(client, customer):
    wrong_pw = client.post(LOGIN_JSON, json={"email": "customer@example.com", "password": "wrongpass1"})
    unknown = client.post(LOGIN_JSON, json={"email": "ghost@example.com", "password": "password123"})
    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.json() == unknown.json()
    assert wrong_pw.headers["www-authenticate"] == "Bearer"
    assert client.post(LOGIN, data={"username": "customer@example.com", "password": ""}).status_code in (401, 422)


def test_disabled_account_cannot_log_in_or_use_existing_token(client, customer):
    token = client.post(LOGIN_JSON, json={"email": "customer@example.com", "password": "password123"}).json()["access_token"]
    db = next(app.dependency_overrides[get_db]())
    user = db.query(User).filter_by(email="customer@example.com").one()
    user.is_active = False
    db.commit()
    db.close()  # don't leave a pooled connection checked out (matters on PostgreSQL)
    assert client.post(LOGIN_JSON, json={"email": "customer@example.com", "password": "password123"}).status_code == 401
    assert client.get(ME, headers=_bearer(token)).status_code == 401  # already-issued token dies too


# ------------------------------------------------------------------ token verification (401)


def test_me_returns_current_user(client, customer):
    resp = client.get(ME, headers=customer)
    assert resp.status_code == 200
    assert resp.json()["email"] == "customer@example.com"
    assert "password_hash" not in resp.json()


def test_missing_or_malformed_authorization_is_401(client):
    assert client.get(ME).status_code == 401
    assert client.get(ME).headers["www-authenticate"] == "Bearer"
    assert client.get(ME, headers={"Authorization": "Bearer garbage"}).status_code == 401
    assert client.get(ME, headers={"Authorization": "Basic abc"}).status_code == 401
    assert client.get(ME, headers={"Authorization": "Bearer"}).status_code == 401


def test_expired_token_is_401(client, customer):
    uid = _my_id(client, customer)
    expired = create_access_token(uid, expires_minutes=-10)
    resp = client.get(ME, headers=_bearer(expired))
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Token has expired"
    assert resp.headers["www-authenticate"] == "Bearer"


def test_tampered_or_foreign_signature_is_401(client, customer):
    uid = _my_id(client, customer)
    good = create_access_token(uid)
    head, payload, sig = good.split(".")
    assert client.get(ME, headers=_bearer(f"{head}.{payload}.{sig[:-2]}AA")).status_code == 401
    other_key = _forge({"sub": uid}, key="a-different-secret-key-0123456789abcdef-xyz")
    assert client.get(ME, headers=_bearer(other_key)).status_code == 401


def test_unsigned_alg_none_token_is_rejected(client, customer):
    uid = _my_id(client, customer)
    unsigned = jwt.encode(
        {"sub": uid, "type": "access", "iss": settings.JWT_ISSUER,
         "iat": datetime.now(timezone.utc), "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        key=None, algorithm="none",
    )
    assert client.get(ME, headers=_bearer(unsigned)).status_code == 401


def test_wrong_token_type_issuer_or_missing_claims_are_401(client, customer):
    uid = _my_id(client, customer)
    assert client.get(ME, headers=_bearer(_forge({"sub": uid}))).status_code == 200  # control
    for bad in (
        _forge({"sub": uid, "type": "refresh"}),
        _forge({"sub": uid, "type": None}),
        _forge({"sub": uid, "iss": "someone-else"}),
        _forge({"sub": uid, "iss": None}),
        _forge({"sub": None}),
        _forge({"sub": uid, "exp": None}),
        _forge({"sub": uid, "iat": None}),
        _forge({"sub": "not-a-uuid"}),
        _forge({"sub": str(uuid.uuid4())}),  # signed correctly but no such user
        _forge({"sub": 12345}),
    ):
        assert client.get(ME, headers=_bearer(bad)).status_code == 401, bad


def test_extra_claims_cannot_override_reserved_ones():
    token = create_access_token(
        uuid.uuid4(), extra_claims={"type": "refresh", "sub": "x", "iss": "evil", "role": "owner"}
    )
    claims = decode_access_token(token)
    assert claims["type"] == "access" and claims["iss"] == settings.JWT_ISSUER
    assert claims["sub"] != "x"


def test_role_comes_from_the_database_not_the_token(client, customer):
    uid = _my_id(client, customer)
    forged_role = _forge({"sub": uid, "role": "owner"})  # valid signature, lying claim
    assert client.get(ME, headers=_bearer(forged_role)).json()["role"] == "customer"
    resp = client.post("/api/v1/restaurants", json={"name": "Sneaky"}, headers=_bearer(forged_role))
    assert resp.status_code == 403


# ------------------------------------------------------------------ authorization (403)


def test_role_gates_return_403_for_valid_users_and_401_for_anonymous(client, owner, customer, courier, restaurant):
    burger = restaurant.menu["Burger"]
    order_body = {"restaurant_id": restaurant, "items": [{"menu_item_id": burger, "quantity": 1}],
                  "delivery_address": "Hostel"}
    assert client.post("/api/v1/restaurants", json={"name": "X"}, headers=customer).status_code == 403
    assert client.post("/api/v1/restaurants", json={"name": "X"}, headers=courier).status_code == 403
    assert client.post("/api/v1/restaurants", json={"name": "X"}).status_code == 401
    for who in (owner, courier):
        assert client.post("/api/v1/orders", json=order_body, headers=who).status_code == 403
    assert client.post("/api/v1/orders", json=order_body).status_code == 401
    oid = client.post("/api/v1/orders", json=order_body, headers=customer).json()["id"]
    assert client.post(f"/api/v1/payments/orders/{oid}/pay", json={"method": "upi"}, headers=courier).status_code == 403
    assert client.post(f"/api/v1/orders/{oid}/claim", headers=customer).status_code == 403
    assert client.post(f"/api/v1/orders/{oid}/claim", headers=owner).status_code == 403


def test_restaurant_ownership_is_enforced_for_every_write(client, make_user, restaurant):
    intruder = make_user("owner", "intruder@example.com")
    item = restaurant.menu["Burger"]
    base = f"/api/v1/restaurants/{restaurant}"
    assert client.patch(base, json={"name": "Mine now"}, headers=intruder).status_code == 403
    assert client.post(f"{base}/menu", json={"name": "Z", "price": "1.00"}, headers=intruder).status_code == 403
    assert client.patch(f"{base}/menu/{item}", json={"price": "0.01"}, headers=intruder).status_code == 403
    assert client.delete(f"{base}/menu/{item}", headers=intruder).status_code == 403


def test_order_access_is_enforced_in_the_service_layer(client, make_user, owner, customer, courier, restaurant):
    from tests.conftest import place_order

    oid = place_order(client, customer, restaurant)["id"]
    strangers = [make_user("customer", "s1@example.com"), make_user("owner", "s2@example.com"),
                 make_user("delivery_partner", "s3@example.com")]
    for who in strangers:
        assert client.get(f"/api/v1/orders/{oid}", headers=who).status_code == 404
        assert client.get(f"/api/v1/orders/{oid}/tracking", headers=who).status_code == 404
        # Another customer gets 404 (existence not revealed). Owners / couriers are refused
        # by role (403) before any lookup, which reveals nothing about the order either.
        expected = 404 if who is strangers[0] else 403
        assert client.post(f"/api/v1/orders/{oid}/cancel", headers=who).status_code == expected
    assert client.get(f"/api/v1/orders/{oid}", headers=customer).status_code == 200
    assert client.get(f"/api/v1/orders/{oid}", headers=owner).status_code == 200


def test_services_enforce_roles_even_when_called_without_a_route():
    """Defence in depth: the service layer refuses the wrong role itself."""
    customer = User(id=uuid.uuid4(), name="c", email="c@x.com", password_hash="x", role=UserRole.CUSTOMER)
    owner = User(id=uuid.uuid4(), name="o", email="o@x.com", password_hash="x", role=UserRole.OWNER)
    with pytest.raises(ForbiddenError):
        restaurant_service.create_restaurant(None, customer, None)  # db/data never reached
    with pytest.raises(ForbiddenError):
        order_service.create_order(None, owner, None)
    with pytest.raises(ForbiddenError):
        order_service.claim_order(None, customer, uuid.uuid4())


# ------------------------------------------------------------------ Swagger / OpenAPI


def test_openapi_declares_the_oauth2_password_flow(client):
    spec = client.get("/openapi.json").json()
    schemes = spec["components"]["securitySchemes"]
    flow = next(iter(schemes.values()))["flows"]["password"]
    assert flow["tokenUrl"] == "/api/v1/auth/login"
    register_params = spec["paths"]["/api/v1/auth/register"]["post"]["parameters"]
    assert any(p["name"].lower() == "x-registration-key" for p in register_params)
