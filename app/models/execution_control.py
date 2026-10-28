"""주문 의도·실행 회차·위험 기준을 프로세스 밖에 보존한다."""
import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin


class OrderIntent(Base, CreatedAtMixin):
    __tablename__ = "order_intents"

    intent_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    account_ref: Mapped[str] = mapped_column(String(64), index=True)
    book: Mapped[str] = mapped_column(String(20))
    strategy_id: Mapped[str] = mapped_column(String(100))
    strategy_version: Mapped[int] = mapped_column(Integer)
    symbol: Mapped[str] = mapped_column(String(20))
    side: Mapped[str] = mapped_column(String(4))
    source: Mapped[str] = mapped_column(String(30))
    input_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20))
    result: Mapped[dict] = mapped_column(JSONB, default=dict)


class ExecutionRun(Base, CreatedAtMixin):
    __tablename__ = "execution_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)


class RiskDay(Base):
    __tablename__ = "execution_risk_days"

    account_ref: Mapped[str] = mapped_column(String(64), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    equity: Mapped[float] = mapped_column(Float)


class BrokerPositionBaseline(Base, CreatedAtMixin):
    """새 추적을 시작할 때 있던 보유는 수동/귀속 불명으로 보존한다."""
    __tablename__ = "broker_position_baselines"

    account_ref: Mapped[str] = mapped_column(String(64), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    quantity: Mapped[int] = mapped_column(Integer)
