"""Add append-only Paper ↔ KIS reconciliation snapshots.

Revision ID: 0044_paper_kis_reconciliations
Revises: 0043_regime_targets
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0044_paper_kis_reconciliations"
down_revision = "0043_regime_targets"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "paper_kis_reconciliations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("intent_id", sa.String(64),
                  sa.ForeignKey("order_intents.intent_id"), nullable=False),
        sa.Column("user_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("users.id"), nullable=False),
        sa.Column("account_ref", sa.String(64), nullable=False),
        sa.Column("journal_version_id", sa.Integer(),
                  sa.ForeignKey("paper_journal_versions.id"), nullable=True),
        sa.Column("journal_version_no", sa.Integer(), nullable=True),
        sa.Column("decision_date", sa.Date(), nullable=False),
        sa.Column("execution_date", sa.Date(), nullable=True),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("client_order_id", sa.String(64), nullable=True),
        sa.Column("broker_order_no", sa.String(20), nullable=True),
        sa.Column("kis_order_status", sa.String(24), nullable=True),
        sa.Column("kis_order_quantity", sa.Integer(), nullable=True),
        sa.Column("kis_filled_quantity", sa.Integer(), nullable=True),
        sa.Column("kis_remaining_quantity", sa.Integer(), nullable=True),
        sa.Column("kis_cancelled_quantity", sa.Integer(), nullable=True),
        sa.Column("kis_unfilled_quantity", sa.Integer(), nullable=True),
        sa.Column("kis_order_price", sa.Float(), nullable=True),
        sa.Column("kis_avg_fill_price", sa.Float(), nullable=True),
        sa.Column("quantity_evidence_complete", sa.Boolean(), nullable=True),
        sa.Column("paper_decision_action", sa.String(20), nullable=True),
        sa.Column("paper_order_quantity", sa.Integer(), nullable=True),
        sa.Column("paper_fill_quantity", sa.Integer(), nullable=True),
        sa.Column("paper_fill_status", sa.String(20), nullable=True),
        sa.Column("paper_fill_date", sa.Date(), nullable=True),
        sa.Column("paper_fill_price", sa.Float(), nullable=True),
        sa.Column("signal_aligned", sa.Boolean(), nullable=True),
        sa.Column("quantity_delta", sa.Integer(), nullable=True),
        sa.Column("shadow_kis_adverse_bps", sa.Float(), nullable=True),
        sa.Column("kis_order_adverse_bps", sa.Float(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detail", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("snapshot_hash", name="uq_paper_kis_reconciliations_snapshot"),
        comment="그림자 일지와 KIS 모의 전략 시험 주문의 대사 스냅샷 — 상태 변화만 추가",
    )
    op.create_index("ix_paper_kis_recon_decision_date",
                    "paper_kis_reconciliations", ["decision_date"])
    op.create_index("ix_paper_kis_recon_intent_observed",
                    "paper_kis_reconciliations", ["intent_id", "observed_at"])


def downgrade():
    op.drop_index("ix_paper_kis_recon_intent_observed", table_name="paper_kis_reconciliations")
    op.drop_index("ix_paper_kis_recon_decision_date", table_name="paper_kis_reconciliations")
    op.drop_table("paper_kis_reconciliations")
