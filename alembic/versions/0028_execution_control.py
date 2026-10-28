"""주문 귀속·영속 위험/실행 기록·알림 사건 선점. 과거 보유를 자동 편입하지 않는다."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0028_execution_control"
down_revision = "0027_strategy_decisions"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("orders", sa.Column("execution_intent_id", sa.String(64)))
    op.create_unique_constraint("uq_orders_execution_intent_id", "orders", ["execution_intent_id"])
    for name, typ, default in [("account_ref", sa.String(64), ""), ("strategy_id", sa.String(100), ""),
                               ("strategy_version", sa.Integer(), "0")]:
        op.add_column("live_orders", sa.Column(name, typ, nullable=False, server_default=default))
    op.create_index("ix_live_orders_account_ref", "live_orders", ["account_ref"])
    op.create_table("order_intents",
        sa.Column("intent_id", sa.String(64), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        *[sa.Column(n, sa.String(size), nullable=False) for n, size in
          [("account_ref",64),("book",20),("strategy_id",100),("symbol",20),("side",4),
           ("source",30),("input_hash",64),("status",20)]],
        sa.Column("strategy_version", sa.Integer(), nullable=False),
        sa.Column("result", pg.JSONB(), nullable=False))
    for name in ("user_id", "account_ref"):
        op.create_index("ix_order_intents_" + name, "order_intents", [name])
    op.create_table("execution_runs",
        sa.Column("run_id", sa.String(64), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("detail", pg.JSONB(), nullable=False))
    op.create_index("ix_execution_runs_user_id", "execution_runs", ["user_id"])
    op.create_table("execution_risk_days",
        sa.Column("account_ref", sa.String(64), primary_key=True),
        sa.Column("day", sa.Date(), primary_key=True), sa.Column("equity", sa.Float(), nullable=False))
    op.create_table("broker_position_baselines",
        sa.Column("account_ref", sa.String(64), primary_key=True),
        sa.Column("symbol", sa.String(20), primary_key=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.add_column("notification_log", sa.Column("kind", sa.String(40)))
    op.add_column("notification_log", sa.Column("ref", sa.String(64)))
    op.add_column("notification_log", sa.Column("delivery_status", sa.String(20), nullable=False, server_default="legacy"))
    op.create_unique_constraint("uq_notification_event", "notification_log", ["user_id", "kind", "ref"])


def downgrade():
    op.drop_constraint("uq_orders_execution_intent_id", "orders", type_="unique")
    op.drop_column("orders", "execution_intent_id")
    op.drop_constraint("uq_notification_event", "notification_log", type_="unique")
    for name in ("delivery_status", "ref", "kind"):
        op.drop_column("notification_log", name)
    for name in ("broker_position_baselines", "execution_risk_days", "execution_runs", "order_intents"):
        op.drop_table(name)
    op.drop_index("ix_live_orders_account_ref", table_name="live_orders")
    for name in ("strategy_version", "strategy_id", "account_ref"):
        op.drop_column("live_orders", name)
