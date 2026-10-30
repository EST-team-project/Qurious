"""모의계좌 일별 자산 스냅샷 — QFRS 성과 지표 계산의 입력 데이터."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPkMixin, CreatedAtMixin


class PaperAccountSnapshot(Base, UUIDPkMixin, CreatedAtMixin):
    """
    모의계좌 자산 스냅샷.

    completeness:
        complete   - 실제 시세를 사용한 완전한 스냅샷
        incomplete - 일부 자산의 실제 시세를 확보하지 못한 스냅샷
        unknown    - 과거 데이터 또는 출처를 확인할 수 없는 스냅샷

    origin:
        daily      - 일일 계좌 스냅샷
        backtest   - 백테스트 생성 데이터
        simulation - 시뮬레이션 생성 데이터
        unknown    - 출처를 확인할 수 없는 데이터
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

    epoch: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )

    completeness: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unknown", server_default="unknown"
    )
    origin: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unknown", server_default="unknown"
    )

    __table_args__ = (
        Index("ix_paper_snap_user_date", "user_id", "snap_date", unique=True),
    )