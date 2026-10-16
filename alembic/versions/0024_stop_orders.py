"""orders — 스탑 주문 칸 (B5 · #160)

Revision ID: 0024_stop_orders
Revises: 0023_signal_opinion
Create Date: 2026-10-16
"""
from alembic import op
import sqlalchemy as sa


revision = "0024_stop_orders"
down_revision = "0023_signal_opinion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("order_kind", sa.String(10), nullable=False, server_default="market"))
    op.add_column("orders", sa.Column("stop_price", sa.Float(), nullable=True))
    op.add_column("orders", sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "triggered_at")
    op.drop_column("orders", "stop_price")
    op.drop_column("orders", "order_kind")