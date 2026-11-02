"""스냅샷 가격 근거와 수익률 유효성. 과거 근거는 추정으로 채우지 않는다."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0037_snapshot_evidence"
down_revision = "0036_notif_discord_url"
branch_labels = depends_on = None


def upgrade():
    op.add_column("paper_account_snapshots", sa.Column("price_metadata", JSONB, nullable=False, server_default="[]"))
    op.add_column("paper_account_snapshots", sa.Column("return_valid", sa.Boolean(), nullable=False, server_default="false"))


def downgrade():
    op.drop_column("paper_account_snapshots", "return_valid")
    op.drop_column("paper_account_snapshots", "price_metadata")
