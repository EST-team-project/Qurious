"""개인 KIS 모의 취소 요청의 영속 선점."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0041_broker_cancel"
down_revision = "0040_local_strategy"
branch_labels = depends_on = None


def upgrade():
    op.create_table("broker_cancel_requests",
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("live_orders.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("cancel_order_no", sa.String(20), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))


def downgrade():
    op.drop_table("broker_cancel_requests")
