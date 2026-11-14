from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

from app.core.config import Settings
from app.database import session as session_module
from app.database.session import get_db
from app.main import app


def _settings(monkeypatch, **values) -> Settings:
    for name in ("DATABASE_URL", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"):
        monkeypatch.delenv(name, raising=False)
    return Settings(_env_file=None, **values)


def test_url_is_built_from_parts_and_escapes_password(monkeypatch):
    s = _settings(
        monkeypatch,
        POSTGRES_USER="campus",
        POSTGRES_PASSWORD="p@ss/w:rd#1",
        POSTGRES_DB="campusbite",
        POSTGRES_HOST="db",
        POSTGRES_PORT=5432,
    )
    url = s.sqlalchemy_url
    assert url.drivername == "postgresql+psycopg"
    assert (url.host, url.port, url.database) == ("db", 5432, "campusbite")
    assert url.password == "p@ss/w:rd#1"  # survives escaping
    assert "p@ss" not in s.safe_database_url  # never logged
    assert "***" in s.safe_database_url


def test_host_defaults_to_localhost_for_local_runs(monkeypatch):
    s = _settings(monkeypatch, POSTGRES_USER="u", POSTGRES_PASSWORD="p", POSTGRES_DB="d")
    assert s.sqlalchemy_url.host == "localhost"


def test_missing_credentials_fail_fast(monkeypatch):
    s = _settings(monkeypatch)
    with pytest.raises(RuntimeError, match="POSTGRES_PASSWORD"):
        _ = s.sqlalchemy_url


def test_database_url_override_and_scheme_normalised(monkeypatch):
    s = _settings(monkeypatch, DATABASE_URL="postgres://u:p@cloud:6543/prod")
    assert s.sqlalchemy_url.drivername == "postgresql+psycopg"
    assert s.sqlalchemy_url.host == "cloud"


def test_empty_database_url_is_ignored(monkeypatch):
    # docker-compose sets DATABASE_URL="" so the POSTGRES_* values win
    s = _settings(
        monkeypatch,
        DATABASE_URL="",
        POSTGRES_USER="u",
        POSTGRES_PASSWORD="p",
        POSTGRES_DB="d",
        POSTGRES_HOST="db",
    )
    assert s.sqlalchemy_url.host == "db"


def test_production_requires_real_secret_key(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(ValueError):
        _settings(monkeypatch, ENVIRONMENT="production")
    ok = _settings(monkeypatch, ENVIRONMENT="production", SECRET_KEY="x" * 40)
    assert ok.ENVIRONMENT == "production"


def test_empty_secret_key_is_rejected_in_production(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(ValueError):
        _settings(monkeypatch, ENVIRONMENT="production", SECRET_KEY="")


def test_get_db_rolls_back_on_error_and_always_closes(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(session_module, "SessionLocal", lambda: fake)

    gen = session_module.get_db()
    assert next(gen) is fake
    with pytest.raises(ValueError):
        gen.throw(ValueError("boom"))
    fake.rollback.assert_called_once()
    fake.close.assert_called_once()

    fake.reset_mock()
    gen = session_module.get_db()
    next(gen)
    gen.close()  # normal finish
    fake.rollback.assert_not_called()
    fake.close.assert_called_once()


def test_unreachable_database_gives_503_on_health(monkeypatch):
    dead = create_engine(
        "postgresql+psycopg://u:p@127.0.0.1:1/x", connect_args={"connect_timeout": 1}
    )
    monkeypatch.setattr("app.main.engine", dead)
    with TestClient(app) as client:
        resp = client.get("/health/db")
    assert resp.status_code == 503
    assert resp.json()["database"] == "unreachable"
    assert resp.headers["retry-after"] == "5"


def test_database_error_inside_endpoint_gives_503_not_500():
    class BrokenSession:
        def scalar(self, *args, **kwargs):
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

        def close(self):
            pass

        def rollback(self):
            pass

    def broken_db():
        yield BrokenSession()

    app.dependency_overrides[get_db] = broken_db
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/auth/login/json",
                json={"email": "a@example.com", "password": "password123"},
            )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 503
    assert "temporarily unavailable" in resp.json()["detail"]
    assert "connection refused" not in resp.text  # internals are not leaked


def test_health_db_ok_when_database_up(client):
    assert client.get("/health/db").json() == {"status": "ok", "database": "connected"}
