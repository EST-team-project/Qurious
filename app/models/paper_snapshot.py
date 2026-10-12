"""모의계좌 일별 자산 스냅샷 — QFRS 성과 지표 계산의 입력 데이터."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPkMixin, CreatedAtMixin


class PaperAccountSnapshot(Base, UUIDPkMixin, CreatedAtMixin):
    """
    매일(또는 최초 조회 시점부터) 모의계좌 총자산을 1행씩 기록.

    - daily_return = (오늘 total_equity / 어제 total_equity) - 1
    - A1: 리셋 경계에서는 daily_return = 0 (epoch 가 직전 스냅샷과 다르면 경계)
    - QFRS 지표(MDD, Sharpe, DSR) 계산의 유일한 입력원
    """
    __tablename__ = "paper_account_snapshots"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    snap_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    cash: Mapped[float] = mapped_column(Float, default=0.0)
    position_value: Mapped[float] = mapped_column(Float, default=0.0)
    total_equity: Mapped[float] = mapped_column(Float, nullable=False)

    daily_return: Mapped[float] = mapped_column(Float, default=0.0)

    position_count: Mapped[int] = mapped_column(default=0)
    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )

    stock_value: Mapped[float] = mapped_column(Float, default=0.0)
    crypto_value: Mapped[float] = mapped_column(Float, default=0.0)
    alt_value: Mapped[float] = mapped_column(Float, default=0.0)

    # A1 — 이 스냅샷이 속한 회차. PaperAccount.epoch 와 짝.
    epoch: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )

    __table_args__ = (
        Index("ix_paper_snap_user_date", "user_id", "snap_date", unique=True),
    )