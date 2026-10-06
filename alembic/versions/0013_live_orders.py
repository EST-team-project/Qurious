"""live_orders(게이트웨이 경유 KIS 실주문 추적) + broker_settings.quant_strategy_id/version(domain-rag-lab 전략 선택)

Revision ID: 0013
Revises: 17e868117893
Create Date: 2026-10-02

강사님 기초 코드 9478811 의 0009_live_orders 를 그대로 옮기고 번호만 바꿨다(2026-10-03 반영).
우리 0009 는 이미 formula_indicators(09-30 반영 때 우리 0003_trading_cost 가 끼어 한 칸씩 밀렸다)이고,
이미 적용된 DB 를 깨지 않으려고 강사님 것을 그때의 머리(17e868117893 · #96 합치기 판) 뒤에 둔다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: Union[str, None] = "17e868117893"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "live_orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("client_order_id", sa.String(64), nullable=False),
        sa.Column("environment", sa.String(10), nullable=False, server_default="paper"),
        sa.Column("broker", sa.String(20), nullable=False, server_default="kis"),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("name", sa.String(100), nullable=False, server_default=""),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("order_type", sa.String(6), nullable=False, server_default="LIMIT"),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("price", sa.Float, nullable=False, server_default="0"),
        sa.Column("order_no", sa.String(20), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("filled_quantity", sa.Integer, nullable=False, server_default="0"),
        sa.Column("avg_filled_price", sa.Float, nullable=False, server_default="0"),
        sa.Column("message", sa.String(300), nullable=False, server_default=""),
        sa.Column("raw", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("client_order_id", name="uq_live_orders_client_order_id"),
    )
    op.create_index("ix_live_orders_user_status", "live_orders", ["user_id", "status"])
    op.add_column("broker_settings", sa.Column("quant_strategy_id", sa.String(40), nullable=False, server_default=""))
    op.add_column("broker_settings", sa.Column("quant_strategy_version", sa.Integer, nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("broker_settings", "quant_strategy_version")
    op.drop_column("broker_settings", "quant_strategy_id")
    op.drop_index("ix_live_orders_user_status", table_name="live_orders")
    op.drop_table("live_orders")
