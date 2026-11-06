"""Add tracking fields to Paper ↔ KIS reconciliation snapshots.

Revision ID: 0045_paper_kis_reconciliation_tracking
Revises: 0044_paper_kis_reconciliations
"""
from alembic import op
import sqlalchemy as sa

revision = "0045_paper_kis_track"
down_revision = "0044_paper_kis_reconciliations"
branch_labels = depends_on = None


def upgrade():
    op.add_column(
        "paper_kis_reconciliations",
        sa.Column("tracked_order_status", sa.String(24), nullable=True),
    )
    op.add_column(
        "paper_kis_reconciliations",
        sa.Column("tracked_order_quantity", sa.Integer(), nullable=True),
    )
    op.add_column(
        "paper_kis_reconciliations",
        sa.Column("tracked_filled_quantity", sa.Integer(), nullable=True),
    )
    op.add_column(
        "paper_kis_reconciliations",
        sa.Column("submitted_order_price", sa.Float(), nullable=True),
    )
    op.alter_column(
        "paper_kis_reconciliations",
        "decision_date",
        existing_type=sa.Date(),
        existing_nullable=False,
        nullable=True,
    )


def downgrade():
    op.alter_column(
        "paper_kis_reconciliations",
        "decision_date",
        existing_type=sa.Date(),
        existing_nullable=True,
        nullable=False,
    )
    op.drop_column("paper_kis_reconciliations", "submitted_order_price")
    op.drop_column("paper_kis_reconciliations", "tracked_filled_quantity")
    op.drop_column("paper_kis_reconciliations", "tracked_order_quantity")
    op.drop_column("paper_kis_reconciliations", "tracked_order_status")
