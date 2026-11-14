"""UUID primary keys, ledger / refund / reminder tables, constraints (data-preserving)

What this migration does
------------------------
* Everything runs inside ONE PostgreSQL transaction. If any step fails, nothing changes.
* The existing tables are NOT dropped. They are renamed to ``legacy_<name>`` (together with
  their constraints and indexes) and kept after the upgrade.
* New tables with UUID primary keys are created and filled from the legacy tables.
  ``legacy_id_map(table_name, old_id, new_id)`` records every integer -> UUID translation.
* ``payment_ledger`` is back-filled from ``payments`` (paid -> completed charge,
  failed -> failed charge, refunded -> completed charge + completed refund, pending -> none).
* A preflight stops the migration with a readable message if existing data would violate a
  new constraint (duplicate e-mails ignoring case, non-positive prices, ...). Nothing is
  changed in that case.
* Row counts and money totals are verified before the transaction commits.

Dropping the legacy_* tables is deliberately NOT done here (see the README).

Downgrade: drops the new tables and restores the legacy tables under their old names.
Anything created after the upgrade (new users, orders, ledger rows...) is lost, because the
legacy tables never saw it. Take a pg_dump before upgrading AND before downgrading.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Order matters: parents first.
TABLES = [
    "users",
    "restaurants",
    "menu_items",
    "orders",
    "order_items",
    "order_status_events",
    "payments",
    "reviews",
]
NEW_ONLY_TABLES = ["payment_ledger", "refund_requests", "reminder_logs"]

ROLES = ("customer", "owner", "delivery_partner")
ORDER_STATUSES = (
    "pending_payment", "placed", "accepted", "preparing", "ready_for_pickup",
    "out_for_delivery", "delivered", "cancelled", "rejected",
)
PAYMENT_METHODS = ("card", "upi", "wallet")
PAYMENT_STATUSES = ("pending", "paid", "failed", "refunded")
TRANSACTION_TYPES = ("charge", "refund")
LEDGER_STATUSES = ("pending", "completed", "failed")
REFUND_STATUSES = ("requested", "approved", "rejected", "processed")
REMINDER_TYPES = ("payment_pending", "order_ready", "review_request")


def _in(column: str, values: Sequence[str]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def _ts(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def _id() -> sa.Column:
    return sa.Column("id", sa.Uuid(), nullable=False)


# --------------------------------------------------------------------------- preflight


def _preflight(bind) -> None:
    """Collect every problem first, then raise once, so one run shows the whole list."""
    problems: list[str] = []

    def check(title: str, sql: str) -> None:
        rows = bind.execute(sa.text(sql)).fetchall()
        if rows:
            shown = "; ".join(str(tuple(r)) for r in rows[:10])
            more = f" (+{len(rows) - 10} more)" if len(rows) > 10 else ""
            problems.append(f"- {title}: {shown}{more}")

    check("e-mails that collide when lower-cased (id, email)",
          "SELECT u.id, u.email FROM users u WHERE lower(u.email) IN "
          "(SELECT lower(email) FROM users GROUP BY lower(email) HAVING count(*) > 1)")
    check("users with an unknown role (id, role)",
          f"SELECT id, role FROM users WHERE NOT ({_in('role', ROLES)})")
    check("menu items with price <= 0 (id, price)",
          "SELECT id, price FROM menu_items WHERE price <= 0")
    check("orders with an unknown status (id, status)",
          f"SELECT id, status FROM orders WHERE NOT ({_in('status', ORDER_STATUSES)})")
    check("orders with a negative total (id, total_amount)",
          "SELECT id, total_amount FROM orders WHERE total_amount < 0")
    check("order items with quantity <= 0 (id, quantity)",
          "SELECT id, quantity FROM order_items WHERE quantity <= 0")
    check("order items with a negative unit_price (id, unit_price)",
          "SELECT id, unit_price FROM order_items WHERE unit_price < 0")
    check("the same menu item twice in one order (order_id, menu_item_id)",
          "SELECT order_id, menu_item_id FROM order_items WHERE menu_item_id IS NOT NULL "
          "GROUP BY order_id, menu_item_id HAVING count(*) > 1")
    check("status events with an unknown status (id, status)",
          f"SELECT id, status FROM order_status_events WHERE NOT ({_in('status', ORDER_STATUSES)})")
    check("payments with an unknown method (id, method)",
          f"SELECT id, method FROM payments WHERE NOT ({_in('method', PAYMENT_METHODS)})")
    check("payments with an unknown status (id, status)",
          f"SELECT id, status FROM payments WHERE NOT ({_in('status', PAYMENT_STATUSES)})")
    check("payments with a negative amount (id, amount)",
          "SELECT id, amount FROM payments WHERE amount < 0")
    check("paid/failed/refunded payments with amount = 0 (id, amount); the ledger needs amount > 0",
          "SELECT id, amount FROM payments WHERE amount = 0 AND status IN ('paid', 'failed', 'refunded')")
    check("reviews whose customer/restaurant differ from the order's (review id, order id)",
          "SELECT r.id, r.order_id FROM reviews r JOIN orders o ON o.id = r.order_id "
          "WHERE r.customer_id <> o.customer_id OR r.restaurant_id <> o.restaurant_id")

    if problems:
        raise RuntimeError(
            "Migration 0002 was NOT applied because existing data would violate the new "
            "constraints. Nothing was changed. Fix these rows and run it again:\n"
            + "\n".join(problems)
        )


# --------------------------------------------------------------------------- rename helpers

_RENAME_TO_LEGACY = """
DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT conrelid::regclass::text AS tbl, conname
    FROM pg_constraint
    WHERE conrelid IN (SELECT oid FROM pg_class
                       WHERE relname IN ({tables}) AND relnamespace = current_schema()::regnamespace)
      AND contype IN ('p', 'u', 'f', 'c')
  LOOP
    EXECUTE format('ALTER TABLE %s RENAME CONSTRAINT %I TO %I', r.tbl, r.conname, 'legacy_' || r.conname);
  END LOOP;
  FOR r IN
    SELECT indexname FROM pg_indexes
    WHERE schemaname = current_schema() AND tablename IN ({tables})
      AND indexname NOT LIKE 'legacy\\_%'
  LOOP
    EXECUTE format('ALTER INDEX %I RENAME TO %I', r.indexname, 'legacy_' || r.indexname);
  END LOOP;
END $$;
"""

_RENAME_FROM_LEGACY = """
DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT conrelid::regclass::text AS tbl, conname
    FROM pg_constraint
    WHERE conrelid IN (SELECT oid FROM pg_class
                       WHERE relname IN ({tables}) AND relnamespace = current_schema()::regnamespace)
      AND contype IN ('p', 'u', 'f', 'c') AND conname LIKE 'legacy\\_%'
  LOOP
    EXECUTE format('ALTER TABLE %s RENAME CONSTRAINT %I TO %I', r.tbl, r.conname, substr(r.conname, 8));
  END LOOP;
  FOR r IN
    SELECT indexname FROM pg_indexes
    WHERE schemaname = current_schema() AND tablename IN ({tables}) AND indexname LIKE 'legacy\\_%'
  LOOP
    EXECUTE format('ALTER INDEX %I RENAME TO %I', r.indexname, substr(r.indexname, 8));
  END LOOP;
END $$;
"""


def _tables_sql(names: Sequence[str]) -> str:
    return ", ".join(f"'{n}'" for n in names)


# --------------------------------------------------------------------------- upgrade


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("Migration 0002 converts existing data and is written for PostgreSQL only.")

    # Freeze the old tables for the duration of the transaction: no writes can slip in
    # between the preflight, the copy and the verification.
    for t in TABLES:
        op.execute(f"LOCK TABLE {t} IN ACCESS EXCLUSIVE MODE")

    _preflight(bind)

    # ---- 1. move the old tables out of the way (data untouched) ------------------------
    for t in TABLES:
        op.execute(f"ALTER TABLE {t} RENAME TO legacy_{t}")
    op.execute(_RENAME_TO_LEGACY.format(tables=_tables_sql([f"legacy_{t}" for t in TABLES])))

    # ---- 2. id translation table + UUIDv7 helper ---------------------------------------
    op.create_table(
        "legacy_id_map",
        sa.Column("table_name", sa.String(64), nullable=False),
        sa.Column("old_id", sa.Integer(), nullable=False),
        sa.Column("new_id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("table_name", "old_id", name="pk_legacy_id_map"),
        sa.UniqueConstraint("new_id", name="uq_legacy_id_map_new_id"),
    )
    # UUIDv7 layout: 48-bit ms timestamp | version 7 | 12-bit counter | variant | 60 random bits.
    # The timestamp comes from the row's created_at, so sorting by id keeps creation order.
    op.execute("""
        CREATE FUNCTION cb_uuid7(ts timestamptz, seq bigint) RETURNS uuid
        LANGUAGE sql VOLATILE AS $$
          SELECT (
            lpad(to_hex(floor(extract(epoch FROM ts) * 1000)::bigint), 12, '0')
            || '7' || lpad(to_hex((seq % 4096)::int), 3, '0')
            || '8' || substr(md5(random()::text || clock_timestamp()::text || seq::text), 1, 15)
          )::uuid
        $$
    """)
    inspector = sa.inspect(op.get_bind())
    for t in TABLES:
        # Some legacy tables (e.g. order_items) have no created_at column.
        cols = {c["name"] for c in inspector.get_columns(f"legacy_{t}")}
        ts = "created_at" if "created_at" in cols else "now()"
        op.execute(f"""
            INSERT INTO legacy_id_map (table_name, old_id, new_id)
            SELECT '{t}', id, cb_uuid7({ts}, row_number() OVER (ORDER BY id))
            FROM legacy_{t}
        """)

    # ---- 3. new tables -----------------------------------------------------------------
    _create_new_tables()

    # ---- 4. copy data ------------------------------------------------------------------
    _copy_data()

    # ---- 5. verify, then clean up the helper -------------------------------------------
    _verify(bind)
    op.execute("DROP FUNCTION cb_uuid7(timestamptz, bigint)")


def _create_new_tables() -> None:
    op.create_table(
        "users",
        _id(),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint(_in("role", ROLES), name=op.f("ck_users_user_role")),
        sa.CheckConstraint("email = lower(email)", name=op.f("ck_users_email_lowercase")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(op.f("ix_users_role"), "users", ["role"], unique=False)

    op.create_table(
        "restaurants",
        _id(),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("cuisine", sa.String(60), nullable=True),
        sa.Column("location", sa.String(200), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_open", sa.Boolean(), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name=op.f("fk_restaurants_owner_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_restaurants")),
    )
    op.create_index(op.f("ix_restaurants_cuisine"), "restaurants", ["cuisine"], unique=False)
    op.create_index(op.f("ix_restaurants_name"), "restaurants", ["name"], unique=False)
    op.create_index(op.f("ix_restaurants_owner_id"), "restaurants", ["owner_id"], unique=False)

    op.create_table(
        "menu_items",
        _id(),
        sa.Column("restaurant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(60), nullable=True),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("is_available", sa.Boolean(), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint("price > 0", name=op.f("ck_menu_items_price_positive")),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"],
                                name=op.f("fk_menu_items_restaurant_id_restaurants"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_menu_items")),
    )
    op.create_index(op.f("ix_menu_items_restaurant_id"), "menu_items", ["restaurant_id"], unique=False)

    op.create_table(
        "orders",
        _id(),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("restaurant_id", sa.Uuid(), nullable=False),
        sa.Column("delivery_partner_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("total_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("delivery_address", sa.String(255), nullable=False),
        sa.Column("notes", sa.String(500), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint("total_amount >= 0", name=op.f("ck_orders_total_non_negative")),
        sa.CheckConstraint(_in("status", ORDER_STATUSES), name=op.f("ck_orders_order_status")),
        sa.ForeignKeyConstraint(["customer_id"], ["users.id"], name=op.f("fk_orders_customer_id_users")),
        sa.ForeignKeyConstraint(["delivery_partner_id"], ["users.id"],
                                name=op.f("fk_orders_delivery_partner_id_users")),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"],
                                name=op.f("fk_orders_restaurant_id_restaurants")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orders")),
        sa.UniqueConstraint("id", "customer_id", name="uq_orders_id_customer_id"),
        sa.UniqueConstraint("id", "customer_id", "restaurant_id", name="uq_orders_id_customer_id_restaurant_id"),
    )
    op.create_index(op.f("ix_orders_delivery_partner_id"), "orders", ["delivery_partner_id"], unique=False)
    op.create_index(op.f("ix_orders_status"), "orders", ["status"], unique=False)
    op.create_index("ix_orders_restaurant_id_status", "orders", ["restaurant_id", "status"], unique=False)
    op.create_index("ix_orders_customer_id_created_at", "orders", ["customer_id", "created_at"], unique=False)

    op.create_table(
        "order_items",
        _id(),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("menu_item_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("subtotal", sa.Numeric(10, 2), sa.Computed("quantity * unit_price", persisted=True), nullable=False),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_order_items_quantity_positive")),
        sa.CheckConstraint("unit_price >= 0", name=op.f("ck_order_items_unit_price_non_negative")),
        sa.ForeignKeyConstraint(["menu_item_id"], ["menu_items.id"],
                                name=op.f("fk_order_items_menu_item_id_menu_items"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"],
                                name=op.f("fk_order_items_order_id_orders"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_items")),
        sa.UniqueConstraint("order_id", "menu_item_id", name="uq_order_items_order_id_menu_item_id"),
    )
    op.create_index(op.f("ix_order_items_order_id"), "order_items", ["order_id"], unique=False)

    op.create_table(
        "order_status_events",
        _id(),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        _ts("created_at"),
        sa.CheckConstraint(_in("status", ORDER_STATUSES), name=op.f("ck_order_status_events_order_status")),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], name=op.f("fk_order_status_events_actor_id_users")),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"],
                                name=op.f("fk_order_status_events_order_id_orders"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_status_events")),
    )
    op.create_index(op.f("ix_order_status_events_order_id"), "order_status_events", ["order_id"], unique=False)

    op.create_table(
        "payments",
        _id(),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("method", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("transaction_ref", sa.String(40), nullable=True),
        sa.Column("failure_reason", sa.String(200), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint("amount >= 0", name=op.f("ck_payments_amount_non_negative")),
        sa.CheckConstraint(_in("method", PAYMENT_METHODS), name=op.f("ck_payments_payment_method")),
        sa.CheckConstraint(_in("status", PAYMENT_STATUSES), name=op.f("ck_payments_payment_status")),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"],
                                name=op.f("fk_payments_order_id_orders"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payments")),
        sa.UniqueConstraint("order_id", name=op.f("uq_payments_order_id")),
        sa.UniqueConstraint("transaction_ref", name=op.f("uq_payments_transaction_ref")),
    )

    op.create_table(
        "reviews",
        _id(),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("restaurant_id", sa.Uuid(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        _ts("created_at"),
        sa.CheckConstraint("rating >= 1 AND rating <= 5", name=op.f("ck_reviews_rating_range")),
        sa.ForeignKeyConstraint(
            ["order_id", "customer_id", "restaurant_id"],
            ["orders.id", "orders.customer_id", "orders.restaurant_id"],
            name="fk_reviews_order_id_customer_id_restaurant_id_orders",
        ),
        sa.ForeignKeyConstraint(["customer_id"], ["users.id"], name=op.f("fk_reviews_customer_id_users")),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"], name=op.f("fk_reviews_restaurant_id_restaurants")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reviews")),
        sa.UniqueConstraint("order_id", name=op.f("uq_reviews_order_id")),
    )
    op.create_index(op.f("ix_reviews_customer_id"), "reviews", ["customer_id"], unique=False)
    op.create_index(op.f("ix_reviews_restaurant_id"), "reviews", ["restaurant_id"], unique=False)

    op.create_table(
        "payment_ledger",
        _id(),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("transaction_type", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reference", sa.String(64), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint("amount > 0", name=op.f("ck_payment_ledger_amount_positive")),
        sa.CheckConstraint(_in("transaction_type", TRANSACTION_TYPES), name=op.f("ck_payment_ledger_transaction_type")),
        sa.CheckConstraint(_in("status", LEDGER_STATUSES), name=op.f("ck_payment_ledger_ledger_status")),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], name=op.f("fk_payment_ledger_order_id_orders")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_ledger")),
    )
    op.create_index("ix_payment_ledger_order_id_created_at", "payment_ledger", ["order_id", "created_at"], unique=False)
    op.create_index("uq_payment_ledger_reference", "payment_ledger", ["reference"], unique=True,
                    postgresql_where=sa.text("reference IS NOT NULL"))

    op.create_table(
        "refund_requests",
        _id(),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint("length(trim(reason)) > 0", name=op.f("ck_refund_requests_reason_not_blank")),
        sa.CheckConstraint(_in("status", REFUND_STATUSES), name=op.f("ck_refund_requests_refund_status")),
        sa.ForeignKeyConstraint(
            ["order_id", "customer_id"], ["orders.id", "orders.customer_id"],
            name="fk_refund_requests_order_id_customer_id_orders",
        ),
        sa.ForeignKeyConstraint(["customer_id"], ["users.id"], name=op.f("fk_refund_requests_customer_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refund_requests")),
    )
    op.create_index("ix_refund_requests_order_id", "refund_requests", ["order_id"], unique=False)
    op.create_index(op.f("ix_refund_requests_customer_id"), "refund_requests", ["customer_id"], unique=False)
    op.create_index("uq_refund_requests_open_order", "refund_requests", ["order_id"], unique=True,
                    postgresql_where=sa.text("status IN ('requested', 'approved')"))

    op.create_table(
        "reminder_logs",
        _id(),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("reminder_type", sa.String(30), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(_in("reminder_type", REMINDER_TYPES), name=op.f("ck_reminder_logs_reminder_type")),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"],
                                name=op.f("fk_reminder_logs_order_id_orders"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reminder_logs")),
        sa.UniqueConstraint("order_id", "reminder_type", name="uq_reminder_logs_order_id_reminder_type"),
    )


def _map(alias: str, table: str, column: str) -> str:
    """JOIN fragment translating legacy integer ``column`` of the legacy row into a UUID."""
    return (f"JOIN legacy_id_map {alias} ON {alias}.table_name = '{table}' "
            f"AND {alias}.old_id = {column}")


def _copy_data() -> None:
    op.execute(f"""
        INSERT INTO users (id, name, email, phone, password_hash, role, is_active, created_at, updated_at)
        SELECT m.new_id, u.full_name, lower(u.email), u.phone, u.hashed_password, u.role,
               u.is_active, u.created_at, u.created_at
        FROM legacy_users u {_map('m', 'users', 'u.id')}
    """)
    op.execute(f"""
        INSERT INTO restaurants (id, owner_id, name, description, cuisine, location,
                                 is_active, is_open, created_at, updated_at)
        SELECT m.new_id, mo.new_id, r.name, r.description, r.cuisine, r.location,
               TRUE, r.is_open, r.created_at, r.created_at
        FROM legacy_restaurants r
        {_map('m', 'restaurants', 'r.id')}
        {_map('mo', 'users', 'r.owner_id')}
    """)
    op.execute(f"""
        INSERT INTO menu_items (id, restaurant_id, name, description, category, price,
                                is_available, created_at, updated_at)
        SELECT m.new_id, mr.new_id, i.name, i.description, i.category, i.price,
               i.is_available, i.created_at, i.created_at
        FROM legacy_menu_items i
        {_map('m', 'menu_items', 'i.id')}
        {_map('mr', 'restaurants', 'i.restaurant_id')}
    """)
    op.execute(f"""
        INSERT INTO orders (id, customer_id, restaurant_id, delivery_partner_id, status, total_amount,
                            delivery_address, notes, created_at, updated_at)
        SELECT m.new_id, mc.new_id, mr.new_id, md.new_id, o.status, o.total_amount,
               o.delivery_address, o.notes, o.created_at, o.updated_at
        FROM legacy_orders o
        {_map('m', 'orders', 'o.id')}
        {_map('mc', 'users', 'o.customer_id')}
        {_map('mr', 'restaurants', 'o.restaurant_id')}
        LEFT JOIN legacy_id_map md ON md.table_name = 'users' AND md.old_id = o.delivery_partner_id
    """)
    op.execute(f"""
        INSERT INTO order_items (id, order_id, menu_item_id, name, quantity, unit_price)
        SELECT m.new_id, mo.new_id, mi.new_id, i.name, i.quantity, i.unit_price
        FROM legacy_order_items i
        {_map('m', 'order_items', 'i.id')}
        {_map('mo', 'orders', 'i.order_id')}
        LEFT JOIN legacy_id_map mi ON mi.table_name = 'menu_items' AND mi.old_id = i.menu_item_id
    """)
    op.execute(f"""
        INSERT INTO order_status_events (id, order_id, status, actor_id, created_at)
        SELECT m.new_id, mo.new_id, e.status, ma.new_id, e.created_at
        FROM legacy_order_status_events e
        {_map('m', 'order_status_events', 'e.id')}
        {_map('mo', 'orders', 'e.order_id')}
        LEFT JOIN legacy_id_map ma ON ma.table_name = 'users' AND ma.old_id = e.actor_id
    """)
    op.execute(f"""
        INSERT INTO payments (id, order_id, amount, method, status, transaction_ref,
                              failure_reason, created_at, updated_at)
        SELECT m.new_id, mo.new_id, p.amount, p.method, p.status, p.transaction_ref,
               p.failure_reason, p.created_at, p.updated_at
        FROM legacy_payments p
        {_map('m', 'payments', 'p.id')}
        {_map('mo', 'orders', 'p.order_id')}
    """)
    op.execute(f"""
        INSERT INTO reviews (id, order_id, customer_id, restaurant_id, rating, comment, created_at)
        SELECT m.new_id, mo.new_id, mc.new_id, mr.new_id, r.rating, r.comment, r.created_at
        FROM legacy_reviews r
        {_map('m', 'reviews', 'r.id')}
        {_map('mo', 'orders', 'r.order_id')}
        {_map('mc', 'users', 'r.customer_id')}
        {_map('mr', 'restaurants', 'r.restaurant_id')}
    """)

    # ---- ledger back-fill from payments ------------------------------------------------
    # paid / refunded -> completed charge (keeps the gateway reference)
    op.execute(f"""
        INSERT INTO payment_ledger (id, order_id, amount, transaction_type, status, reference,
                                    created_at, updated_at)
        SELECT cb_uuid7(p.created_at, row_number() OVER (ORDER BY p.id)), mo.new_id, p.amount,
               'charge', 'completed', p.transaction_ref, p.created_at, p.created_at
        FROM legacy_payments p {_map('mo', 'orders', 'p.order_id')}
        WHERE p.status IN ('paid', 'refunded')
    """)
    # failed -> failed charge (no reference)
    op.execute(f"""
        INSERT INTO payment_ledger (id, order_id, amount, transaction_type, status, reference,
                                    created_at, updated_at)
        SELECT cb_uuid7(p.created_at, row_number() OVER (ORDER BY p.id)), mo.new_id, p.amount,
               'charge', 'failed', NULL, p.created_at, p.created_at
        FROM legacy_payments p {_map('mo', 'orders', 'p.order_id')}
        WHERE p.status = 'failed'
    """)
    # refunded -> additionally a completed refund, timestamped at the payment's last update
    op.execute(f"""
        INSERT INTO payment_ledger (id, order_id, amount, transaction_type, status, reference,
                                    created_at, updated_at)
        SELECT cb_uuid7(p.updated_at, row_number() OVER (ORDER BY p.id)), mo.new_id, p.amount,
               'refund', 'completed',
               'RFND-' || upper(substr(md5(random()::text || p.id::text), 1, 16)),
               p.updated_at, p.updated_at
        FROM legacy_payments p {_map('mo', 'orders', 'p.order_id')}
        WHERE p.status = 'refunded'
    """)


def _verify(bind) -> None:
    errors: list[str] = []
    for t in TABLES:
        old = bind.execute(sa.text(f"SELECT count(*) FROM legacy_{t}")).scalar_one()
        new = bind.execute(sa.text(f"SELECT count(*) FROM {t}")).scalar_one()
        if old != new:
            errors.append(f"{t}: {old} legacy rows but {new} copied rows")

    def pair(title: str, old_sql: str, new_sql: str) -> None:
        a = bind.execute(sa.text(old_sql)).scalar_one()
        b = bind.execute(sa.text(new_sql)).scalar_one()
        if a != b:
            errors.append(f"{title}: legacy={a} new={b}")

    pair("sum(orders.total_amount)",
         "SELECT coalesce(sum(total_amount), 0) FROM legacy_orders",
         "SELECT coalesce(sum(total_amount), 0) FROM orders")
    pair("sum(order line totals)",
         "SELECT coalesce(sum(quantity * unit_price), 0) FROM legacy_order_items",
         "SELECT coalesce(sum(subtotal), 0) FROM order_items")
    pair("sum(payments.amount)",
         "SELECT coalesce(sum(amount), 0) FROM legacy_payments",
         "SELECT coalesce(sum(amount), 0) FROM payments")
    pair("ledger rows back-filled from payments",
         "SELECT count(*) FILTER (WHERE status IN ('paid','failed')) "
         "+ 2 * count(*) FILTER (WHERE status = 'refunded') FROM legacy_payments",
         "SELECT count(*) FROM payment_ledger")
    pair("order_items still linked to a menu item",
         "SELECT count(menu_item_id) FROM legacy_order_items",
         "SELECT count(menu_item_id) FROM order_items")
    if errors:
        raise RuntimeError("Migration 0002 verification failed, rolling back:\n- " + "\n- ".join(errors))


# --------------------------------------------------------------------------- downgrade


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("Migration 0002 is written for PostgreSQL only.")
    for t in TABLES:
        if not bind.execute(sa.text("SELECT to_regclass(:n)"), {"n": f"legacy_{t}"}).scalar():
            raise RuntimeError(f"Cannot downgrade: legacy_{t} no longer exists.")

    for t in ["reminder_logs", "refund_requests", "payment_ledger", *reversed(TABLES)]:
        op.drop_table(t)

    op.execute(_RENAME_FROM_LEGACY.format(tables=_tables_sql([f"legacy_{t}" for t in TABLES])))
    for t in TABLES:
        op.execute(f"ALTER TABLE legacy_{t} RENAME TO {t}")
    op.drop_table("legacy_id_map")
