def _register(client, **overrides):
    body = {
        "email": "A@Example.com",
        "password": "password123",
        "name": "Asha",
        "role": "customer",
    }
    body.update(overrides)
    return client.post("/api/v1/auth/register", json=body)


def test_register_normalizes_email_and_hides_password(client):
    resp = _register(client)
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "a@example.com"
    assert data["role"] == "customer"
    assert "password" not in data and "password_hash" not in data


def test_duplicate_email_conflict(client):
    assert _register(client).status_code == 201
    assert _register(client, email="a@example.com").status_code == 409


def test_register_rejects_bad_input(client):
    assert _register(client, password="short").status_code == 422
    assert _register(client, role="admin").status_code == 422
    assert _register(client, email="not-an-email").status_code == 422


def test_login_success_and_failure(client):
    _register(client)
    ok = client.post(
        "/api/v1/auth/login/json", json={"email": "a@example.com", "password": "password123"}
    )
    assert ok.status_code == 200
    assert ok.json()["token_type"] == "bearer"
    bad = client.post(
        "/api/v1/auth/login/json", json={"email": "a@example.com", "password": "wrongpass1"}
    )
    assert bad.status_code == 401
    unknown = client.post(
        "/api/v1/auth/login/json", json={"email": "x@example.com", "password": "password123"}
    )
    assert unknown.status_code == 401


def test_oauth2_form_login_for_swagger(client):
    _register(client)
    resp = client.post(
        "/api/v1/auth/login",
        data={"username": "a@example.com", "password": "password123"},
    )
    assert resp.status_code == 200
    assert resp.json()["access_token"]


def test_me_requires_valid_token(client, customer):
    assert client.get("/api/v1/auth/me").status_code == 401
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage"}).status_code
        == 401
    )
    me = client.get("/api/v1/auth/me", headers=customer)
    assert me.status_code == 200
    assert me.json()["role"] == "customer"


def test_update_profile_and_change_password(client, customer):
    resp = client.patch("/api/v1/auth/me", json={"name": "New Name"}, headers=customer)
    assert resp.json()["name"] == "New Name"

    wrong = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "nope-nope", "new_password": "newpassword1"},
        headers=customer,
    )
    assert wrong.status_code == 400

    ok = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "password123", "new_password": "newpassword1"},
        headers=customer,
    )
    assert ok.status_code == 204
    relogin = client.post(
        "/api/v1/auth/login/json",
        json={"email": "customer@example.com", "password": "newpassword1"},
    )
    assert relogin.status_code == 200


def test_register_still_accepts_legacy_full_name_field(client):
    resp = _register(client, name=None)  # overrides name with None...
    assert resp.status_code == 422
    body = {"email": "legacy@example.com", "password": "password123",
            "full_name": "Legacy Client", "role": "customer"}
    resp = client.post("/api/v1/auth/register", json=body)
    assert resp.status_code == 201
    assert resp.json()["name"] == "Legacy Client"


def test_user_ids_are_uuids(client, customer):
    import uuid

    me = client.get("/api/v1/auth/me", headers=customer).json()
    assert uuid.UUID(me["id"]).version == 7
    assert me["created_at"] and me["updated_at"]
