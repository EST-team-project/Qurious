"""add completeness and origin to paper account snapshots"""

from alembic import op
import sqlalchemy as sa


revision = "0033_paper_snapshot_completeness"
down_revision = "0032_user_consents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "paper_account_snapshots",
        sa.Column(
            "completeness",
            sa.String(length=16),
            nullable=False,
            server_default="unknown",
        ),
    )
    op.add_column(
        "paper_account_snapshots",
        sa.Column(
            "origin",
            sa.String(length=16),
            nullable=False,
            server_default="unknown",
        ),
    )


def downgrade() -> None:
    op.drop_column("paper_account_snapshots", "origin")
    op.drop_column("paper_account_snapshots", "completeness")