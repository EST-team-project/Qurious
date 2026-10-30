"""백테스트 계좌 및 스냅샷 분리.

Revision ID: 0034_backtest_account_isolation
Revises: 0033_paper_snapshot_completeness
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0034_backtest_account_isolation"
down_revision = "0033_paper_snapshot_completeness"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "backtest_accounts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("initial_cash", sa.Float(), nullable=False, server_default="100000000"),
        sa.Column("cash", sa.Float(), nullable=False, server_default="100000000"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "backtest_snapshots",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("snap_date", sa.Date(), nullable=False),
        sa.Column("cash", sa.Float(), nullable=False),
        sa.Column("position_value", sa.Float(), nullable=False),
        sa.Column("total_equity", sa.Float(), nullable=False),
        sa.Column("daily_return", sa.Float(), nullable=False, server_default="0"),
        sa.Column("position_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stock_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "user_id",
            "snap_date",
            name="uq_backtest_snapshots_user_date",
        ),
    )


def downgrade():
    op.drop_table("backtest_snapshots")
    op.drop_table("backtest_accounts")