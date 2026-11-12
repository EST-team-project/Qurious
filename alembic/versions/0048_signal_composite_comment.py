"""signal_snapshots.composite 칸 설명을 실제 범위(−5 ~ +5)로 바로잡는다 (#617).

Revision ID: 0048_signal_composite_comment
Revises: 0047_paper_cashflow_order_epoch
Create Date: 2026-11-12

칸 설명(comment)만 바꾼다 — 자료 · 형은 그대로다.
"""
from alembic import op
import sqlalchemy as sa


revision = "0048_signal_composite_comment"
down_revision = "0047_paper_cashflow_order_epoch"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("signal_snapshots", "composite", existing_type=sa.Float(), existing_nullable=False,
                    comment="주기 가중 점수 −5 ~ +5", existing_comment="주기 가중 점수 −6 ~ +6")


def downgrade() -> None:
    op.alter_column("signal_snapshots", "composite", existing_type=sa.Float(), existing_nullable=False,
                    comment="주기 가중 점수 −6 ~ +6", existing_comment="주기 가중 점수 −5 ~ +5")
