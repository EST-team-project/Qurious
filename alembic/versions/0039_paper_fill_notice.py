"""PAPER 체결 알림의 재시작 복구용 대기 표시."""
from alembic import op
import sqlalchemy as sa

revision = "0039_paper_fill_notice"
down_revision = "0038_risk_stops"
branch_labels = depends_on = None


def upgrade():
    op.add_column("orders", sa.Column("fill_notice_pending", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column("orders", "fill_notice_pending")
