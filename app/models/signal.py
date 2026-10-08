"""T2 다중 주기 신호 기록 — 거래일마다 종목당 한 줄 (목표 기능 ② 설계서 6절 <표 12> · `P01-②-3`).

쓰는 곳: `scripts/signals_daily.py`(배치) → `app.services.mtf_signals.write_snapshots`.
읽는 곳: 의견 변환(`P01-④-2`) · 설명(`P01-①-5`) · 화면.

기본키에 지표 정의 판(`definition`)이 들어 있다 — 정의가 바뀌면 지난 날짜를 새 판으로 다시 계산해 **새 줄로 더하고 옛 판
줄은 그대로 둔다**(지난 판으로 낸 신호 · 의견을 다시 볼 수 있게). 같은 판 · 같은 날을 다시 계산하면 그 줄을 바꾼다.
의견 칸(`opinion` · `opinion_rule`)은 `P01-④-2` 가 더한다.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SignalSnapshot(Base):
    __tablename__ = "signal_snapshots"

    as_of: Mapped[date] = mapped_column(Date, primary_key=True, comment="기준 거래일(그날 종가까지의 봉)")
    symbol: Mapped[str] = mapped_column(String(16), primary_key=True, comment="종목 단축코드")
    definition: Mapped[str] = mapped_column(String(32), primary_key=True, comment="지표 정의 판(ta_utils.DEFINITION)")

    signal: Mapped[str] = mapped_column(String(8), nullable=False, comment="매수 · 매도 · 관망")
    strength: Mapped[str | None] = mapped_column(String(8), comment="보통 · 강 (관망은 없음)")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, comment="0 ~ 1 — 방향 일치도 ½ + 점수 크기 ½ (확률 아님)")
    composite: Mapped[float] = mapped_column(Float, nullable=False, comment="주기 가중 점수 −6 ~ +6")
    agreement: Mapped[float] = mapped_column(Float, nullable=False, comment="종합 방향과 같은 주기의 가중치 비율 0 ~ 1")

    timeframes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list,
                                             comment="주기별 점수 · RSI · 근거 · 쓴 마지막 봉 · 주봉 partial")
    pattern_bias: Mapped[str | None] = mapped_column(String(16), comment="일봉 패턴 요약 bullish · bearish · neutral")
    patterns: Mapped[list | None] = mapped_column(JSONB, comment="일봉 패턴 · 돌파 목록")
    reasons: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, comment="규칙 근거 문장(설명 층 1 의 입력)")
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="계산 시각")

    __table_args__ = (
        Index("ix_signal_snapshots_symbol_as_of", "symbol", "as_of"),
        {"comment": "T2 다중 주기 신호 — 거래일 · 종목 · 지표 정의 판마다 한 줄 (목표 기능 ② 설계서 6절)"},
    )
