"""카드 판단별 주문 선점과 결과 기록."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0027_strategy_decisions"
down_revision = "0026_paper_journal"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("strategy_decisions",
        sa.Column("decision_key", sa.String(64), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("account_ref", sa.String(64), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("strategy_id", sa.String(100), nullable=False),
        sa.Column("strategy_version", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("bar_end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("action", sa.String(4), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("client_order_id", sa.String(64), sa.ForeignKey("live_orders.client_order_id"), nullable=True),
        sa.Column("detail", pg.JSONB(), nullable=False),
    )
    op.create_index("ix_strategy_decisions_user_id", "strategy_decisions", ["user_id"])
    op.create_index("ix_strategy_decisions_account_ref", "strategy_decisions", ["account_ref"])


def downgrade():
    op.drop_table("strategy_decisions")
