"""백테스트 전용 계좌 및 일별 스냅샷."""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Date, Float, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UpdatedAtMixin, UUIDPkMixin


class BacktestAccount(Base, UUIDPkMixin, CreatedAtMixin, UpdatedAtMixin):
    """PAPER 계좌와 완전히 분리된 백테스트 현금 계좌."""

    __tablename__ = "backtest_accounts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    initial_cash: Mapped[float] = mapped_column(
        Float, nullable=False, default=100_000_000
    )
    cash: Mapped[float] = mapped_column(
        Float, nullable=False, default=100_000_000
    )


class BacktestSnapshot(Base, UUIDPkMixin, CreatedAtMixin):
    """백테스트 전용 일별 평가 기록."""

    __tablename__ = "backtest_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "snap_date",
            name="uq_backtest_snapshots_user_date",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    snap_date: Mapped[date] = mapped_column(Date, nullable=False)
    cash: Mapped[float] = mapped_column(Float, nullable=False)
    position_value: Mapped[float] = mapped_column(Float, nullable=False)
    total_equity: Mapped[float] = mapped_column(Float, nullable=False)
    daily_return: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    position_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stock_value: Mapped[float] = mapped_column(Float, nullable=False, default=0)