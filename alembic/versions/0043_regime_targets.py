"""사용자가 켠 국면 목표 갱신과 변경 근거."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0043_regime_targets"
down_revision = "0042_merge_cancel_audits"
branch_labels = depends_on = None


def upgrade():
    for name in ("regime_config", "regime_state"):
        op.add_column("rebalance_plans", sa.Column(name, pg.JSONB(), nullable=False,
                                                  server_default=sa.text("'{}'::jsonb")))
    op.create_table(
        "rebalance_target_changes",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_id", pg.UUID(as_uuid=True), sa.ForeignKey("rebalance_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("policy_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("data_as_of", sa.Date(), nullable=False),
        sa.Column("before_targets", pg.JSONB(), nullable=False),
        sa.Column("after_targets", pg.JSONB(), nullable=False),
        sa.Column("evidence", pg.JSONB(), nullable=False),
    )
    op.create_index("uq_rebalance_target_change_day", "rebalance_target_changes",
                    ["plan_id", "policy_id", "data_as_of"], unique=True)
    op.create_index("ix_rebalance_target_changes_user_created", "rebalance_target_changes",
                    ["user_id", "created_at"])


def downgrade():
    op.drop_table("rebalance_target_changes")
    op.drop_column("rebalance_plans", "regime_state")
    op.drop_column("rebalance_plans", "regime_config")
