"""일반 실행 정책의 진입 연결 및 보유 회차별 손절 기준."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0038_risk_stops"
down_revision = "0037_snapshot_evidence"
branch_labels = depends_on = None


def upgrade():
    op.add_column("portfolio", sa.Column("risk_entry_intent_id", sa.String(64), nullable=True))
    op.create_table("execution_risk_stops",
        sa.Column("position_key", sa.String(64), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("basis", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index("ix_execution_risk_stops_user_id", "execution_risk_stops", ["user_id"])


def downgrade():
    op.drop_table("execution_risk_stops")
    op.drop_column("portfolio", "risk_entry_intent_id")
