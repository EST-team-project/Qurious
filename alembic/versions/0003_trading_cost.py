"""매매비용 — orders 확장 + order_fills 신설

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-20

왜 칸을 이렇게 나누는가
---------------------
`orders` 에는 값이 열 개뿐이었고, `price` 하나가 주문가인지 체결가인지 구분이 없었다.
비용을 셀 칸도, 부분체결을 받을 자리도 없었다.

FIX 프로토콜이 `CumQty`·`AvgPx`(집계)와 `LastQty`·`LastPx`(개별)를 **둘 다** 두는 것과
같은 구조를 택했다 — 합계는 `orders` 에, 근거는 `order_fills` 에 남긴다. 부분체결이
흔하지 않은 규모에서 매번 조인하는 비용이 크기 때문에 비정규화를 일부러 남긴다.

세목을 쪼갠 이유: 농어촌특별세는 코스피에만 붙고 코스닥은 증권거래세가 그만큼 높아
합계가 같다. 합계 한 칸에 합쳐 두면 나중에 "이 값이 맞나" 를 되짚을 수 없다.

`cost_basis` 가 중요하다 — 같은 수익률이 요율표로 추정한 것인지(estimated) 증권사가
준 실제 금액인지(broker) 구분하지 못하면, 어느 쪽도 검증할 수 없다.

상세 설계와 확실도 표시는 Issue #40.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _uuid_pk():
    return sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()"))


def _created_at():
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


#: orders 에 더하는 칸. 기존 행을 깨지 않으려고 전부 nullable 또는 server_default 다.
#: `price` 는 건드리지 않는다 — 읽는 코드가 여럿이고, 뜻을 바꾸면 조용히 어긋난다.
_ORDER_COLUMNS = (
    ("order_price",      sa.Float,        dict(nullable=True)),
    ("filled_quantity",  sa.Integer,      dict(nullable=False, server_default="0")),
    ("avg_fill_price",   sa.Float,        dict(nullable=True)),
    ("commission",       sa.Float,        dict(nullable=False, server_default="0")),
    ("tax_transfer",     sa.Float,        dict(nullable=False, server_default="0")),
    ("tax_rural",        sa.Float,        dict(nullable=False, server_default="0")),
    ("fee_clearing",     sa.Float,        dict(nullable=False, server_default="0")),
    ("slippage_bps",     sa.Float,        dict(nullable=True)),
    ("net_amount",       sa.Float,        dict(nullable=True)),
    ("broker_order_id",  sa.String(40),   dict(nullable=True)),
    ("filled_at",        sa.DateTime(timezone=True), dict(nullable=True)),
    ("cost_basis",       sa.String(20),   dict(nullable=False, server_default="none")),
)


def upgrade() -> None:
    for name, type_, kwargs in _ORDER_COLUMNS:
        op.add_column("orders", sa.Column(name, type_, **kwargs))

    # 기존 행 이행: 그 시절에는 주문가와 체결가의 구분이 없었으므로 price 를 둘 다로 본다.
    # 비용은 뗀 적이 없으니 cost_basis 는 "none" 으로 남는다(칸 기본값) — 나중에 이 행들의
    # 수익률을 실제 비용 기반 수치와 섞어 보지 않도록 표시가 남아야 한다.
    op.execute("""
        UPDATE orders
           SET order_price     = price,
               avg_fill_price  = price,
               filled_quantity = quantity,
               net_amount      = price * quantity
         WHERE order_price IS NULL
    """)

    op.create_table(
        "order_fills",
        _uuid_pk(),
        sa.Column("order_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("fill_price", sa.Float, nullable=False),
        sa.Column("fill_quantity", sa.Integer, nullable=False),
        sa.Column("fill_at", sa.DateTime(timezone=True), nullable=False),
        # 한 주문이 부분적으로 메이커이고 부분적으로 테이커일 수 있어 체결 행에 둔다
        sa.Column("liquidity_side", sa.String(10), nullable=True),   # maker | taker
        sa.Column("broker_exec_id", sa.String(40), nullable=True),
        sa.Column("commission", sa.Float, nullable=False, server_default="0"),
        sa.Column("tax_transfer", sa.Float, nullable=False, server_default="0"),
        sa.Column("tax_rural", sa.Float, nullable=False, server_default="0"),
        sa.Column("fee_clearing", sa.Float, nullable=False, server_default="0"),
        _created_at(),
        sa.UniqueConstraint("order_id", "seq", name="uq_order_fills_order_seq"),
    )
    op.create_index("ix_order_fills_order", "order_fills", ["order_id"])


def downgrade() -> None:
    op.drop_index("ix_order_fills_order", table_name="order_fills")
    op.drop_table("order_fills")
    for name, _type, _kwargs in reversed(_ORDER_COLUMNS):
        op.drop_column("orders", name)
