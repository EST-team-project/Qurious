"""플랜별 자동 정기 점검 완료일. 주문 없는 날도 중복 판정하지 않는다."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("rebalance_plans", sa.Column("last_auto_check_date", sa.Date(), nullable=True))
    op.add_column("rebalance_plans", sa.Column("last_auto_check_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("rebalance_plans", sa.Column("last_auto_check_result", postgresql.JSONB(), nullable=False,
                                              server_default=sa.text("'{}'::jsonb")))


def downgrade():
    op.drop_column("rebalance_plans", "last_auto_check_result")
    op.drop_column("rebalance_plans", "last_auto_check_at")
    op.drop_column("rebalance_plans", "last_auto_check_date")
