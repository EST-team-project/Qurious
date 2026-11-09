"""Track PAPER order/cashflow epochs for cashflow-adjusted performance.

Revision ID: 0047_paper_cashflow_order_epoch
Revises: crypto_order_costs_20261109
Create Date: 2026-11-09

Existing rows intentionally remain NULL: reset history cannot be reconstructed
reliably from the current orders/cashflow tables, so old records must not be
silently assigned to the current PAPER account epoch.
"""
from alembic import op
import sqlalchemy as sa


revision = "0047_paper_cashflow_order_epoch"
down_revision = "crypto_order_costs_20261109"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("epoch", sa.Integer(), nullable=True))
    op.add_column("cashflow_events", sa.Column("epoch", sa.Integer(), nullable=True))
    op.create_index(
        "ix_orders_user_epoch_created",
        "orders",
        ["user_id", "epoch", "created_at"],
    )
    op.create_index(
        "ix_cashflow_events_user_epoch_created",
        "cashflow_events",
        ["user_id", "epoch", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_cashflow_events_user_epoch_created", table_name="cashflow_events")
    op.drop_index("ix_orders_user_epoch_created", table_name="orders")
    op.drop_column("cashflow_events", "epoch")
    op.drop_column("orders", "epoch")
