"""Checkout idempotency keys on orders

Adds two nullable columns (existing orders keep NULL) and a unique constraint on
(customer_id, idempotency_key). Metadata-only on PostgreSQL: no table rewrite.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("idempotency_key", sa.String(length=64), nullable=True))
    op.add_column("orders", sa.Column("request_fingerprint", sa.String(length=64), nullable=True))
    op.create_unique_constraint(
        "uq_orders_customer_id_idempotency_key", "orders", ["customer_id", "idempotency_key"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_orders_customer_id_idempotency_key", "orders", type_="unique")
    op.drop_column("orders", "request_fingerprint")
    op.drop_column("orders", "idempotency_key")
