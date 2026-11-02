"""모의계좌 스냅샷 가격 출처·시점 감사 테이블 추가.

Revision ID: 0037_paper_snapshot_price_audits
Revises: 0036_notif_discord_url
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0037_paper_snapshot_price_audits"
down_revision = "0036_notif_discord_url"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "paper_snapshot_price_audits",
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_type", sa.String(length=16), nullable=False),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("price_role", sa.String(length=16), nullable=False),
        sa.Column("used_price", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cache_hit", sa.Boolean(), nullable=True),
        sa.Column("cache_age_sec", sa.Float(), nullable=True),
        sa.Column("fallback_used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("fallback_reason", sa.String(length=128), nullable=True),
        sa.Column("fallback_price", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["snapshot_id"], ["paper_account_snapshots.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_paper_snapshot_price_audits_snapshot",
        "paper_snapshot_price_audits",
        ["snapshot_id"],
    )


def downgrade():
    op.drop_index(
        "ix_paper_snapshot_price_audits_snapshot",
        table_name="paper_snapshot_price_audits",
    )
    op.drop_table("paper_snapshot_price_audits")
