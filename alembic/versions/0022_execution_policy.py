"""선택형 위험 수량·취소 확정 매도 재주문 이력."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0022_execution_policy"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("broker_settings", sa.Column("quant_execution_policy", JSONB(), nullable=False, server_default="{}"))
    op.add_column("live_orders", sa.Column("retry_of", UUID(as_uuid=True), nullable=True))
    op.add_column("live_orders", sa.Column("retry_number", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("live_orders", sa.Column("retry_started_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key("fk_live_retry_parent", "live_orders", "live_orders", ["retry_of"], ["id"])
    op.create_unique_constraint("uq_live_orders_retry_of", "live_orders", ["retry_of"])


def downgrade():
    op.drop_constraint("uq_live_orders_retry_of", "live_orders", type_="unique")
    op.drop_constraint("fk_live_retry_parent", "live_orders", type_="foreignkey")
    for name in ("retry_started_at", "retry_number", "retry_of"):
        op.drop_column("live_orders", name)
    op.drop_column("broker_settings", "quant_execution_policy")
