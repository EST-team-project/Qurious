"""사용자 전략의 가상 실행용 선택 사본."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0040_local_strategy"
down_revision = ("0039_paper_fill_notice", "0037_paper_snapshot_price_audits")
branch_labels = depends_on = None


def upgrade():
    op.add_column("broker_settings", sa.Column("quant_local_strategy", postgresql.JSONB(), nullable=True))


def downgrade():
    op.drop_column("broker_settings", "quant_local_strategy")
