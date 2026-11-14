"""Order statuses: ready_for_pickup -> ready; new assigned and refunded

* 'ready_for_pickup' becomes 'ready' (orders and order_status_events).
* Ready orders that already have a courier become 'assigned'.
* Delivered orders whose payment was refunded become 'refunded'.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-15

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BASE = ("pending_payment", "placed", "accepted", "preparing")
TAIL = ("out_for_delivery", "delivered", "cancelled", "rejected")
OLD = BASE + ("ready_for_pickup",) + TAIL
NEW = BASE + ("ready", "assigned") + TAIL + ("refunded",)
CHECKS = (("orders", "ck_orders_order_status"), ("order_status_events", "ck_order_status_events_order_status"))


def _in(values):
    return "status IN (" + ", ".join(repr(v) for v in values) + ")"


def _swap(values):
    for table, name in CHECKS:
        op.create_check_constraint(op.f(name), table, _in(values))


def _drop():
    for table, name in CHECKS:
        op.drop_constraint(op.f(name), table, type_="check")


def upgrade() -> None:
    _drop()
    for table in ("orders", "order_status_events"):
        op.execute(f"UPDATE {table} SET status = 'ready' WHERE status = 'ready_for_pickup'")
    op.execute("UPDATE orders SET status = 'assigned' WHERE status = 'ready' AND delivery_partner_id IS NOT NULL")
    op.execute("""
        UPDATE orders o SET status = 'refunded'
          FROM payments p WHERE p.order_id = o.id AND o.status = 'delivered' AND p.status = 'refunded'
    """)
    _swap(NEW)


def downgrade() -> None:
    _drop()
    op.execute("UPDATE orders SET status = 'delivered' WHERE status = 'refunded'")
    op.execute("DELETE FROM order_status_events WHERE status IN ('assigned', 'refunded')")
    op.execute("UPDATE orders SET status = 'ready' WHERE status = 'assigned'")
    for table in ("orders", "order_status_events"):
        op.execute(f"UPDATE {table} SET status = 'ready_for_pickup' WHERE status = 'ready'")
    _swap(OLD)
