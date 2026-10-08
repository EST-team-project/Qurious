"""T2 signal_snapshots — 다중 주기 신호를 거래일마다 기록 (목표 기능 ② 설계서 6절 · P01-②-3).

Revision ID: 0017
Revises: 0016

기본키 (as_of · symbol · definition) — 지표 정의 판이 바뀌면 새 줄로 더하고 옛 판 줄은 둔다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0017"
down_revision: Union[str, Sequence[str], None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "signal_snapshots",
        sa.Column("as_of", sa.Date(), nullable=False, comment="기준 거래일(그날 종가까지의 봉)"),
        sa.Column("symbol", sa.String(length=16), nullable=False, comment="종목 단축코드"),
        sa.Column("definition", sa.String(length=32), nullable=False, comment="지표 정의 판(ta_utils.DEFINITION)"),
        sa.Column("signal", sa.String(length=8), nullable=False, comment="매수 · 매도 · 관망"),
        sa.Column("strength", sa.String(length=8), nullable=True, comment="보통 · 강 (관망은 없음)"),
        sa.Column("confidence", sa.Float(), nullable=False, comment="0 ~ 1 — 방향 일치도 ½ + 점수 크기 ½ (확률 아님)"),
        sa.Column("composite", sa.Float(), nullable=False, comment="주기 가중 점수 −6 ~ +6"),
        sa.Column("agreement", sa.Float(), nullable=False, comment="종합 방향과 같은 주기의 가중치 비율 0 ~ 1"),
        sa.Column("timeframes", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  comment="주기별 점수 · RSI · 근거 · 쓴 마지막 봉 · 주봉 partial"),
        sa.Column("pattern_bias", sa.String(length=16), nullable=True, comment="일봉 패턴 요약 bullish · bearish · neutral"),
        sa.Column("patterns", postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment="일봉 패턴 · 돌파 목록"),
        sa.Column("reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  comment="규칙 근거 문장(설명 층 1 의 입력)"),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, comment="계산 시각"),
        sa.PrimaryKeyConstraint("as_of", "symbol", "definition"),
        comment="T2 다중 주기 신호 — 거래일 · 종목 · 지표 정의 판마다 한 줄 (목표 기능 ② 설계서 6절)",
    )
    op.create_index("ix_signal_snapshots_symbol_as_of", "signal_snapshots", ["symbol", "as_of"])


def downgrade() -> None:
    op.drop_index("ix_signal_snapshots_symbol_as_of", table_name="signal_snapshots")
    op.drop_table("signal_snapshots")
