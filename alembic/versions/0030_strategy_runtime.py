"""판 2 포지션·재진입 상태와 사건 중복 키."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0030_strategy_runtime"
down_revision = "0029_webhook_dedupe"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("strategy_runtimes",
        sa.Column("runtime_id", sa.String(64), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("account_ref", sa.String(64), nullable=False),
        sa.Column("book", sa.String(20), nullable=False),
        sa.Column("strategy_id", sa.String(100), nullable=False),
        sa.Column("strategy_version", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("spec_hash", sa.String(64), nullable=False),
        sa.Column("state", postgresql.JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_strategy_runtimes_user_id", "strategy_runtimes", ["user_id"])
    op.create_index("ix_strategy_runtimes_account_ref", "strategy_runtimes", ["account_ref"])
    op.create_table("strategy_runtime_events",
        sa.Column("runtime_id", sa.String(64), sa.ForeignKey("strategy_runtimes.runtime_id"), primary_key=True),
        sa.Column("event_key", sa.String(160), primary_key=True),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))


def downgrade():
    op.drop_table("strategy_runtime_events")
    op.drop_index("ix_strategy_runtimes_account_ref", table_name="strategy_runtimes")
    op.drop_index("ix_strategy_runtimes_user_id", table_name="strategy_runtimes")
    op.drop_table("strategy_runtimes")
