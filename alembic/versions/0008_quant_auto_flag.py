"""broker_settings.quant_auto_enabled — 자동매매 활성 플래그 (Celery Beat 10분 주기 실행용)

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-29
강사님 원본 번호 0007 -> Qurious 0008 (우리 0003_trading_cost 뒤로 옮김 · 2026-09-30)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("broker_settings", sa.Column("quant_auto_enabled", sa.Boolean, nullable=False, server_default=sa.text("false")))


def downgrade() -> None:
    op.drop_column("broker_settings", "quant_auto_enabled")
