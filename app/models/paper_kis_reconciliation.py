"""그림자 일지 ↔ KIS 모의 체결 대사 스냅샷 — 기존 원장은 수정하지 않고 상태 변화만 추가한다."""
from datetime import date, datetime
import uuid
from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin


class PaperKisReconciliation(Base, CreatedAtMixin):
    __tablename__ = "paper_kis_reconciliations"
    __table_args__ = (
        UniqueConstraint("snapshot_hash", name="uq_paper_kis_reconciliations_snapshot"),
        Index("ix_paper_kis_recon_decision_date", "decision_date"),
        Index("ix_paper_kis_recon_intent_observed", "intent_id", "observed_at"),
        {"comment": "그림자 일지와 KIS 모의 전략 시험 주문의 대사 스냅샷 — 상태 변화만 추가"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    intent_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("order_intents.intent_id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    account_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    journal_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("paper_journal_versions.id")
    )
    journal_version_no: Mapped[int | None] = mapped_column(Integer)
    decision_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    execution_date: Mapped[date | None] = mapped_column(Date)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)

    client_order_id: Mapped[str | None] = mapped_column(String(64))
    broker_order_no: Mapped[str | None] = mapped_column(String(20))
    tracked_order_status: Mapped[str | None] = mapped_column(String(24))
    tracked_order_quantity: Mapped[int | None] = mapped_column(Integer)
    tracked_filled_quantity: Mapped[int | None] = mapped_column(Integer)
    submitted_order_price: Mapped[float | None] = mapped_column(Float)
    kis_order_status: Mapped[str | None] = mapped_column(String(24))
    kis_order_quantity: Mapped[int | None] = mapped_column(Integer)
    kis_filled_quantity: Mapped[int | None] = mapped_column(Integer)
    kis_remaining_quantity: Mapped[int | None] = mapped_column(Integer)
    kis_cancelled_quantity: Mapped[int | None] = mapped_column(Integer)
    kis_unfilled_quantity: Mapped[int | None] = mapped_column(Integer)
    kis_order_price: Mapped[float | None] = mapped_column(Float)
    kis_avg_fill_price: Mapped[float | None] = mapped_column(Float)
    quantity_evidence_complete: Mapped[bool | None] = mapped_column(nullable=True)

    paper_decision_action: Mapped[str | None] = mapped_column(String(20))
    paper_order_quantity: Mapped[int | None] = mapped_column(Integer)
    paper_fill_quantity: Mapped[int | None] = mapped_column(Integer)
    paper_fill_status: Mapped[str | None] = mapped_column(String(20))
    paper_fill_date: Mapped[date | None] = mapped_column(Date)
    paper_fill_price: Mapped[float | None] = mapped_column(Float)

    signal_aligned: Mapped[bool | None] = mapped_column(nullable=True)
    quantity_delta: Mapped[int | None] = mapped_column(Integer)
    shadow_kis_adverse_bps: Mapped[float | None] = mapped_column(Float)
    kis_order_adverse_bps: Mapped[float | None] = mapped_column(Float)

    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
