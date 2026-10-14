"""signal_snapshots — 의견 칸 (P01-④-2)

Revision ID: 0023_signal_opinion
Revises: 0022_execution_policy
Create Date: 2026-10-14
"""
from alembic import op
import sqlalchemy as sa


revision = "0023_signal_opinion"
down_revision = "0022_execution_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "signal_snapshots",
        sa.Column("opinion", sa.String(8), nullable=True, comment="매수 · 매도 · 보유"),
    )
    op.add_column(
        "signal_snapshots",
        sa.Column("opinion_rule", sa.String(32), nullable=True, comment="어떤 규칙으로 정해졌나"),
    )


def downgrade() -> None:
    op.drop_column("signal_snapshots", "opinion_rule")
    op.drop_column("signal_snapshots", "opinion")
