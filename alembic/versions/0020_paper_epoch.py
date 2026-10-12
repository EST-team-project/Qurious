"""paper epoch — A1 리셋 경계 가짜 수익률 방지

Revision ID: 0020_paper_epoch
Revises: 0019
Create Date: 2026-10-12
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0020_paper_epoch"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "paper_accounts",
        sa.Column("epoch", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "paper_account_snapshots",
        sa.Column("epoch", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("paper_account_snapshots", "epoch")
    op.drop_column("paper_accounts", "epoch")