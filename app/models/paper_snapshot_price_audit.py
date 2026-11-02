"""모의계좌 스냅샷에 실제 사용된 가격의 출처·시점 감사 기록."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPkMixin, CreatedAtMixin


class PaperSnapshotPriceAudit(Base, UUIDPkMixin, CreatedAtMixin):
    __tablename__ = "paper_snapshot_price_audits"

    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("paper_account_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    asset_type: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    price_role: Mapped[str] = mapped_column(String(16), nullable=False)
    used_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cache_hit: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    cache_age_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    fallback_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fallback_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    fallback_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    __table_args__ = (
        Index("ix_paper_snapshot_price_audits_snapshot", "snapshot_id"),
    )
