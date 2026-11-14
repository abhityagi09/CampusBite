"""Run the real Alembic migrations against a real PostgreSQL database.

Skipped unless TEST_DATABASE_URL is set (see conftest.py), because the default test
suite uses in-memory SQLite. This is the test that proves `alembic upgrade head` works on
PostgreSQL and that the migration matches the models exactly (no drift).
"""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="set TEST_DATABASE_URL to a disposable PostgreSQL database to run",
)

BACKEND_DIR = Path(__file__).resolve().parents[1]
BASE_TABLES = {
    "users",
    "restaurants",
    "menu_items",
    "orders",
    "order_items",
    "order_status_events",
    "payments",
    "reviews",
}
NEW_TABLES = {"payment_ledger", "refund_requests", "reminder_logs"}
# Migration 0002 keeps the old integer-key tables as legacy_* until a later cleanup.
LEGACY_TABLES = {f"legacy_{t}" for t in BASE_TABLES} | {"legacy_id_map"}
EXPECTED_TABLES = BASE_TABLES | NEW_TABLES | LEGACY_TABLES


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


@pytest.fixture
def empty_database():
    from app.database.session import engine

    def wipe():
        with engine.begin() as conn:
            conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))

    wipe()
    yield engine
    wipe()


def _tables(engine) -> set[str]:
    return set(inspect(engine).get_table_names()) - {"alembic_version"}


def test_upgrade_head_creates_schema_matching_models(empty_database):
    cfg = _alembic_config()
    command.upgrade(cfg, "head")
    assert _tables(empty_database) == EXPECTED_TABLES
    # Raises if the models differ from what the migrations built (missing migration).
    command.check(cfg)


def test_upgrade_is_idempotent_and_downgrade_is_clean(empty_database):
    cfg = _alembic_config()
    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")  # already at head: must be a no-op
    command.downgrade(cfg, "base")
    assert _tables(empty_database) == set()  # 0002 restores legacy tables, 0001 then drops them
    command.upgrade(cfg, "head")  # and it can be re-applied
    assert _tables(empty_database) == EXPECTED_TABLES


def _seed_legacy(conn):
    """Integer-key data as the old (revision 0001) application would have written it."""
    conn.execute(text("""
        INSERT INTO users (id, email, full_name, hashed_password, role, is_active) VALUES
          (1, 'Owner@Example.com', 'Olive Owner', 'h1', 'owner', true),
          (2, 'cust@example.com', 'Cass Customer', 'h2', 'customer', true),
          (3, 'rider@example.com', 'Ray Rider', 'h3', 'delivery_partner', true);
        INSERT INTO restaurants (id, owner_id, name, is_open) VALUES (1, 1, 'Grill', true);
        INSERT INTO menu_items (id, restaurant_id, name, price, is_available) VALUES
          (1, 1, 'Burger', 5.50, true), (2, 1, 'Fries', 2.25, true);
        INSERT INTO orders (id, customer_id, restaurant_id, delivery_partner_id, status,
                            total_amount, delivery_address) VALUES
          (1, 2, 1, 3, 'delivered', 13.25, 'Hostel'),
          (2, 2, 1, NULL, 'cancelled', 5.50, 'Hostel'),
          (3, 2, 1, NULL, 'pending_payment', 2.25, 'Hostel'),
          (4, 2, 1, NULL, 'placed', 2.25, 'Hostel');
        INSERT INTO order_items (id, order_id, menu_item_id, name, unit_price, quantity) VALUES
          (1, 1, 1, 'Burger', 5.50, 2), (2, 1, 2, 'Fries', 2.25, 1),
          (3, 2, 1, 'Burger', 5.50, 1), (4, 3, 2, 'Fries', 2.25, 1), (5, 4, 2, 'Fries', 2.25, 1);
        INSERT INTO order_status_events (id, order_id, status, actor_id) VALUES
          (1, 1, 'pending_payment', 2), (2, 1, 'delivered', 3);
        INSERT INTO payments (id, order_id, amount, method, status, transaction_ref) VALUES
          (1, 1, 13.25, 'upi', 'paid', 'SIM-AAA'),
          (2, 2, 5.50, 'card', 'refunded', 'SIM-BBB'),
          (3, 3, 2.25, 'upi', 'pending', NULL),
          (4, 4, 2.25, 'upi', 'failed', NULL);
        INSERT INTO reviews (id, order_id, customer_id, restaurant_id, rating, comment)
          VALUES (1, 1, 2, 1, 5, 'Great');
    """))


def test_upgrade_preserves_existing_data(empty_database):
    cfg = _alembic_config()
    command.upgrade(cfg, "0001")
    with empty_database.begin() as conn:
        _seed_legacy(conn)

    command.upgrade(cfg, "head")

    with empty_database.connect() as conn:
        def one(sql):
            return conn.execute(text(sql)).scalar_one()

        assert one("SELECT count(*) FROM users") == 3
        assert one("SELECT email FROM users WHERE name = 'Olive Owner'") == "owner@example.com"
        assert one("SELECT count(*) FROM orders") == 4
        assert one("SELECT sum(total_amount) FROM orders") == one("SELECT sum(total_amount) FROM legacy_orders")
        assert one("SELECT sum(subtotal) FROM order_items") == 13.25 + 5.50 + 2.25 + 2.25
        # relationships survived the key conversion
        assert one(
            "SELECT count(*) FROM orders o JOIN users c ON c.id = o.customer_id "
            "JOIN restaurants r ON r.id = o.restaurant_id JOIN users d ON d.id = o.delivery_partner_id "
            "WHERE c.name = 'Cass Customer' AND r.name = 'Grill' AND d.name = 'Ray Rider'"
        ) == 1
        assert one("SELECT count(*) FROM reviews rv JOIN orders o ON o.id = rv.order_id WHERE rv.rating = 5") == 1
        # ledger back-fill: paid -> 1, refunded -> 2, failed -> 1, pending -> 0
        assert one("SELECT count(*) FROM payment_ledger") == 4
        assert one("SELECT count(*) FROM payment_ledger WHERE transaction_type = 'refund'") == 1
        assert one("SELECT count(*) FROM payment_ledger WHERE status = 'failed' AND reference IS NULL") == 1
        # the untouched originals are still there
        assert one("SELECT count(*) FROM legacy_users") == 3
        assert one("SELECT count(*) FROM legacy_id_map") == 3 + 1 + 2 + 4 + 5 + 2 + 4 + 1
        # new ids are real UUIDv7
        assert one("SELECT count(*) FROM users WHERE substr(id::text, 15, 1) = '7'") == 3

    command.check(cfg)  # models and migrated schema agree, legacy_* ignored


def test_preflight_blocks_and_changes_nothing_when_data_would_violate_constraints(empty_database):
    cfg = _alembic_config()
    command.upgrade(cfg, "0001")
    with empty_database.begin() as conn:
        conn.execute(text("""
            INSERT INTO users (id, email, full_name, hashed_password, role, is_active) VALUES
              (1, 'dup@example.com', 'A', 'h', 'customer', true),
              (2, 'DUP@example.com', 'B', 'h', 'customer', true);
        """))
    with pytest.raises(RuntimeError, match="NOT applied"):
        command.upgrade(cfg, "head")
    assert _tables(empty_database) == BASE_TABLES  # untouched, still at 0001
    with empty_database.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM users")).scalar_one() == 2
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0001"


def test_downgrade_restores_original_tables_and_names(empty_database):
    cfg = _alembic_config()
    command.upgrade(cfg, "0001")
    with empty_database.begin() as conn:
        _seed_legacy(conn)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0001")
    assert _tables(empty_database) == BASE_TABLES
    with empty_database.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM users")).scalar_one() == 3
        names = {r[0] for r in conn.execute(text(
            "SELECT conname FROM pg_constraint WHERE conrelid = 'users'::regclass"))}
        assert "pk_users" in names and not any(n.startswith("legacy_") for n in names)
    command.upgrade(cfg, "head")  # and forward again
