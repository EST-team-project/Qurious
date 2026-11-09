"""리밸런싱 엔진 모델.

모의투자 계좌(PaperAccount 현금 + Portfolio 주식 포지션)를 대상으로
  1) 시간 기반      : 월·분기·연 주기가 도래하면 실행
  2) 이탈률 기반    : 현재 비중이 목표 비중에서 허용 이탈률(%p) 이상 벗어나면 실행
  3) 현금흐름 기반  : 입금·출금·배당금이 발생하면 현금을 즉시 반영하고 다음 일별 점검에서 판단
세 가지 트리거로 목표 비중(RebalancePlan.targets)에 맞춰 매수·매도 주문을 산출·체결한다.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UpdatedAtMixin, UUIDPkMixin

TIME_PERIODS = ("none", "monthly", "quarterly", "yearly")
CASHFLOW_KINDS = ("DEPOSIT", "WITHDRAW", "DIVIDEND")
TRIGGERS = ("TIME", "DRIFT", "CASHFLOW", "MANUAL")


class RebalancePlan(Base, UUIDPkMixin, CreatedAtMixin, UpdatedAtMixin):
    """유저당 1행. 목표 비중과 3가지 트리거 설정."""

    __tablename__ = "rebalance_plans"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(60), nullable=False, default="내 리밸런싱 플랜")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # [{"symbol": "005930.KS", "name": "삼성전자", "weight_pct": 30.0}, ...]  합계 <= 100, 잔여분은 현금 비중
    targets: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # 1) 시간 기반
    time_period: Mapped[str] = mapped_column(String(10), nullable=False, default="none")
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 2) 이탈률 기반 (목표 비중 대비 절대 이탈 %p)
    drift_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    drift_threshold_pct: Mapped[float] = mapped_column(Float, nullable=False, default=5.0)
    drift_check_mode: Mapped[str] = mapped_column(String(12), nullable=False, default="always")
    exclude_unplanned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # 3) 현금흐름 기반 (입출금·배당 발생 시)
    cashflow_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    cashflow_min_amount: Mapped[float] = mapped_column(Float, nullable=False, default=100_000)

    # 트리거 충족 시 자동 체결(true) / 제안만 생성(false)
    auto_execute: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 1주 미만·이 금액 미만의 주문은 생략 (잦은 소액 매매 방지)
    min_order_amount: Mapped[float] = mapped_column(Float, nullable=False, default=10_000)

    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_auto_check_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_auto_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_auto_check_result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict,
                                                       server_default=text("'{}'::jsonb"))
    # 사용자가 가져온 국면 배분의 기준·종목 구성을 고정한다. 빈 설정은 미사용.
    regime_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict,
                                               server_default=text("'{}'::jsonb"))
    regime_state: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict,
                                              server_default=text("'{}'::jsonb"))


class RebalanceTargetChange(Base, UUIDPkMixin, CreatedAtMixin):
    """국면에 따른 목표 변경 근거. 플랜·변경 이력·후속 제안을 한 트랜잭션에 저장."""

    __tablename__ = "rebalance_target_changes"
    __table_args__ = (
        Index("uq_rebalance_target_change_day", "plan_id", "policy_id", "data_as_of", unique=True),
        Index("ix_rebalance_target_changes_user_created", "user_id", "created_at"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("rebalance_plans.id", ondelete="CASCADE"), nullable=False)
    policy_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    data_as_of: Mapped[date] = mapped_column(Date, nullable=False)
    before_targets: Mapped[list] = mapped_column(JSONB, nullable=False)
    after_targets: Mapped[list] = mapped_column(JSONB, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False)


class CashflowEvent(Base, UUIDPkMixin, CreatedAtMixin):
    """모의계좌 입금·출금·배당 이벤트."""

    __tablename__ = "cashflow_events"
    __table_args__ = (
        Index("ix_cashflow_events_user_created", "user_id", "created_at"),
        Index("ix_cashflow_events_user_epoch_created", "user_id", "epoch", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    # 이벤트가 실제 반영된 PAPER 계좌 회차. 기존 이벤트는 회차를 추정할 수 없어 NULL.
    epoch: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # DEPOSIT | WITHDRAW | DIVIDEND
    amount: Mapped[float] = mapped_column(Float, nullable=False)   # 항상 양수, 방향은 kind로 구분
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, default="")  # 배당 종목
    memo: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    cash_after: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    rebalance_run_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    remaining_budget: Mapped[float] = mapped_column(Float, nullable=False, default=0)


class RebalanceRun(Base, UUIDPkMixin, CreatedAtMixin):
    """리밸런싱 실행(또는 제안) 이력."""

    __tablename__ = "rebalance_runs"
    __table_args__ = (
        Index("ix_rebalance_runs_user_created", "user_id", "created_at"),
        Index("uq_rebalance_plan_day", "plan_id", "decision_date", unique=True,
              postgresql_where=text("trigger <> 'MANUAL'")),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    plan_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    trigger: Mapped[str] = mapped_column(String(10), nullable=False)          # TIME | DRIFT | CASHFLOW | MANUAL
    triggers: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    plan_kind: Mapped[str] = mapped_column(String(12), nullable=False, default="full")
    decision_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    context: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="proposed")  # proposed | scheduled | executed | partial | skipped | failed | cancelled
    total_asset: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    max_drift_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    before_weights: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    target_weights: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    after_weights: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # [{"symbol","name","side","quantity","price","amount","status","error"}]
    orders: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    note: Mapped[str] = mapped_column(String(300), nullable=False, default="")
