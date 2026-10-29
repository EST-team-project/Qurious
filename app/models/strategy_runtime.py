"""판 2의 전략별 포지션·재진입 상태와 중복 방지 사건 기록."""
from datetime import datetime
import uuid

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin


class StrategyRuntime(Base):
    __tablename__ = "strategy_runtimes"

    runtime_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    account_ref: Mapped[str] = mapped_column(String(64), index=True)
    book: Mapped[str] = mapped_column(String(20))
    strategy_id: Mapped[str] = mapped_column(String(100))
    strategy_version: Mapped[int] = mapped_column()
    symbol: Mapped[str] = mapped_column(String(20))
    spec_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[dict] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StrategyRuntimeEvent(Base, CreatedAtMixin):
    __tablename__ = "strategy_runtime_events"

    runtime_id: Mapped[str] = mapped_column(String(64), ForeignKey("strategy_runtimes.runtime_id"), primary_key=True)
    event_key: Mapped[str] = mapped_column(String(160), primary_key=True)
    input_hash: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSONB)
