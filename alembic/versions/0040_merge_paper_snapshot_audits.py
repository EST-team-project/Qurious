"""Merge PAPER snapshot price audits and main migration branches.

Revision ID: 0040_merge_paper_snapshot_audits
Revises: 0039_paper_fill_notice, 0037_paper_snapshot_price_audits
"""

revision = "0040_merge_paper_snapshot_audits"
down_revision = (
    "0039_paper_fill_notice",
    "0037_paper_snapshot_price_audits",
)
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
