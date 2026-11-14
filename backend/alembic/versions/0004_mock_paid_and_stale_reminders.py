"""payments: 'paid' -> 'mock_paid'; reminder type 'order_stale'

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-15

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_PAY = ("pending", "paid", "failed", "refunded")
NEW_PAY = ("pending", "mock_paid", "failed", "refunded")
OLD_REM = ("payment_pending", "order_ready", "review_request")
NEW_REM = OLD_REM + ("order_stale",)


def _in(col, values):
    return f"{col} IN ({', '.join(repr(v) for v in values)})"


def _swap(table, name, col, values):
    op.drop_constraint(op.f(name), table, type_="check")
    op.create_check_constraint(op.f(name), table, _in(col, values))


def upgrade() -> None:
    op.drop_constraint(op.f("ck_payments_payment_status"), "payments", type_="check")
    op.execute("UPDATE payments SET status = 'mock_paid' WHERE status = 'paid'")
    op.create_check_constraint(op.f("ck_payments_payment_status"), "payments", _in("status", NEW_PAY))
    _swap("reminder_logs", "ck_reminder_logs_reminder_type", "reminder_type", NEW_REM)


def downgrade() -> None:
    op.execute("DELETE FROM reminder_logs WHERE reminder_type = 'order_stale'")
    _swap("reminder_logs", "ck_reminder_logs_reminder_type", "reminder_type", OLD_REM)
    op.drop_constraint(op.f("ck_payments_payment_status"), "payments", type_="check")
    op.execute("UPDATE payments SET status = 'paid' WHERE status = 'mock_paid'")
    op.create_check_constraint(op.f("ck_payments_payment_status"), "payments", _in("status", OLD_PAY))
