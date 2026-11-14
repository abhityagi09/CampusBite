"""orders.status_updated_at; reminder_logs event keys, snapshots, restaurant, read state

* orders.status_updated_at: when the order entered its CURRENT status. Back-filled from the
  latest matching order_status_events row (falls back to updated_at / created_at).
* reminder_logs: unique (order_id, reminder_type) is replaced by unique event_key, so an owner
  can be reminded again when an order enters a new eligible status period. Existing rows get
  event_key "<order_id>:<type>" (exactly the old uniqueness) and restaurant_id from orders.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-15

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- orders.status_updated_at -------------------------------------------------
    op.add_column("orders", sa.Column("status_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("""
        UPDATE orders o SET status_updated_at = COALESCE(
            (SELECT max(e.created_at) FROM order_status_events e
              WHERE e.order_id = o.id AND e.status = o.status),
            o.updated_at, o.created_at)
    """)
    op.alter_column("orders", "status_updated_at", nullable=False, server_default=sa.text("now()"))
    op.create_index(op.f("ix_orders_status_status_updated_at"), "orders", ["status", "status_updated_at"])

    # ---- reminder_logs ------------------------------------------------------------
    op.add_column("reminder_logs", sa.Column("restaurant_id", sa.Uuid(), nullable=True))
    op.add_column("reminder_logs", sa.Column("event_key", sa.String(200), nullable=True))
    op.add_column("reminder_logs", sa.Column("status_snapshot", sa.String(30), nullable=True))
    op.add_column("reminder_logs", sa.Column("status_updated_at_snapshot", sa.DateTime(timezone=True), nullable=True))
    op.add_column("reminder_logs", sa.Column("read_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("""
        UPDATE reminder_logs r SET event_key = r.order_id::text || ':' || r.reminder_type,
               restaurant_id = (SELECT o.restaurant_id FROM orders o WHERE o.id = r.order_id)
    """)
    op.alter_column("reminder_logs", "event_key", nullable=False)
    op.drop_constraint(op.f("uq_reminder_logs_order_id_reminder_type"), "reminder_logs", type_="unique")
    op.create_unique_constraint(op.f("uq_reminder_logs_event_key"), "reminder_logs", ["event_key"])
    op.create_foreign_key(op.f("fk_reminder_logs_restaurant_id_restaurants"), "reminder_logs",
                          "restaurants", ["restaurant_id"], ["id"])
    op.create_index(op.f("ix_reminder_logs_restaurant_id_sent_at"), "reminder_logs", ["restaurant_id", "sent_at"])
    op.create_index(op.f("ix_reminder_logs_order_id"), "reminder_logs", ["order_id"])


def downgrade() -> None:
    # Several stale reminders per order cannot satisfy the old constraint: keep the oldest.
    op.execute("""
        DELETE FROM reminder_logs r USING reminder_logs k
         WHERE r.order_id = k.order_id AND r.reminder_type = k.reminder_type
           AND (r.sent_at, r.id::text) > (k.sent_at, k.id::text)
    """)
    op.drop_index(op.f("ix_reminder_logs_order_id"), table_name="reminder_logs")
    op.drop_index(op.f("ix_reminder_logs_restaurant_id_sent_at"), table_name="reminder_logs")
    op.drop_constraint(op.f("fk_reminder_logs_restaurant_id_restaurants"), "reminder_logs", type_="foreignkey")
    op.drop_constraint(op.f("uq_reminder_logs_event_key"), "reminder_logs", type_="unique")
    op.create_unique_constraint(op.f("uq_reminder_logs_order_id_reminder_type"), "reminder_logs",
                                ["order_id", "reminder_type"])
    for col in ("read_at", "status_updated_at_snapshot", "status_snapshot", "event_key", "restaurant_id"):
        op.drop_column("reminder_logs", col)
    op.drop_index(op.f("ix_orders_status_status_updated_at"), table_name="orders")
    op.drop_column("orders", "status_updated_at")
