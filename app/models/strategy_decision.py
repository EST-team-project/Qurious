"""카드 판단과 외부 주문을 잇는 영속 기록. PENDING도 재전송하지 않는다."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin


class StrategyDecision(Base, CreatedAtMixin):
    __tablename__ = "strategy_decisions"

    decision_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    account_ref: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_id: Mapped[str] = mapped_column(String(100), nullable=False)
    strategy_version: Mapped[int] = mapped_column(nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    bar_end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    action: Mapped[str] = mapped_column(String(4), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    client_order_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("live_orders.client_order_id"), nullable=True)
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False)
