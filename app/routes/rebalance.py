"""리밸런싱 API — /api/rebalance

플랜(목표 비중·트리거 설정) · 현재 비중/이탈률 스냅샷 · 주문 제안/실행 · 입출금/배당 이벤트 · 실행 이력
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.postgres import get_pg_session
from app.lib.jwt_auth import get_current_user_any
from app.services import rebalance as rb, rebalance_settlement as settlement
from app.services.audit import audit

router = APIRouter(prefix="/api/rebalance", tags=["rebalance"])


def _uid(user: dict) -> uuid.UUID:
    try:
        return uuid.UUID(str(user["id"]))
    except Exception:
        raise HTTPException(400, "유효하지 않은 사용자 ID입니다.")


class TargetBody(BaseModel):
    symbol: str
    name: str = ""
    weight_pct: float = Field(..., ge=0, le=100, allow_inf_nan=False)


class PlanBody(BaseModel):
    name: str | None = None
    is_active: bool | None = None
    targets: list[TargetBody] | None = None
    time_period: str | None = Field(None, description="none | monthly | quarterly | yearly")
    drift_enabled: bool | None = None
    drift_threshold_pct: float | None = Field(None, ge=0.5, le=50, multiple_of=0.5, allow_inf_nan=False)
    drift_check_mode: Literal["always", "scheduled"] | None = None
    exclude_unplanned: bool | None = None
    cashflow_enabled: bool | None = None
    cashflow_min_amount: float | None = Field(None, ge=0, allow_inf_nan=False)
    auto_execute: bool | None = None
    min_order_amount: float | None = Field(None, ge=0, allow_inf_nan=False)


class CashflowBody(BaseModel):
    kind: str = Field(..., description="DEPOSIT | WITHDRAW | DIVIDEND")
    amount: float = Field(..., gt=0, allow_inf_nan=False)
    symbol: str = ""
    memo: str = ""


class ExecuteBody(BaseModel):
    run_id: str | None = Field(None, description="제안(proposed) 이력을 승인해 실행할 때")
    note: str = ""


@router.get("/plan")
async def get_plan(user=Depends(get_current_user_any), db: AsyncSession = Depends(get_pg_session)):
    plan = await rb.get_plan(db, _uid(user))
    await rb.refresh_time_schedule(plan)
    await db.commit()
    await db.refresh(plan)
    return rb.plan_to_dict(plan)


@router.put("/plan")
async def update_plan(body: PlanBody, user=Depends(get_current_user_any), db: AsyncSession = Depends(get_pg_session)):
    plan = await rb.get_plan(db, _uid(user))
    data = body.model_dump(exclude_none=True)
    try:
        if "targets" in data:
            data["targets"] = await rb.resolve_targets(data["targets"])
        rb.apply_plan_update(plan, data)
        await rb.refresh_time_schedule(plan)
        await settlement.cancel_inactive(db, _uid(user), plan)
    except (rb.RebalanceError, ValueError) as exc:
        await db.rollback()
        raise HTTPException(400, str(exc))
    await db.commit()
    await db.refresh(plan)  # onupdate(updated_at) 서버 생성값 재로딩 (async lazy-load 방지)
    await audit(user["id"], user.get("client_id", ""), "rebalance.plan.update", {"fields": list(data.keys())})
    return rb.plan_to_dict(plan)


@router.get("/status")
async def status(user=Depends(get_current_user_any), db: AsyncSession = Depends(get_pg_session)):
    """현재 비중·목표 비중·이탈률 + 트리거 상태."""
    uid = _uid(user)
    plan = await rb.get_plan(db, uid)
    timing = await rb.refresh_time_schedule(plan)
    valuation_error = None
    try:
        snap = await rb.snapshot(db, uid, plan)
    except rb.RebalanceError as exc:
        snap, valuation_error = None, str(exc)
    await db.commit()
    await db.refresh(plan)
    time_due = timing["time_due"]
    automatic_check = rb.daily.view(plan, await asyncio.to_thread(rb.daily.readiness))
    return {"plan": rb.plan_to_dict(plan), "snapshot": snap,
            "automatic_check": automatic_check, "valuation_error": valuation_error,
            "triggers": {"time_due": time_due,
                         "drift_due": bool(snap and snap["drift_exceeded"]) and (plan.drift_check_mode != "scheduled" or time_due),
                         "cashflow_due": bool(snap and plan.cashflow_enabled and snap["cashflow_due"])}}


@router.post("/preview")
async def preview(user=Depends(get_current_user_any), db: AsyncSession = Depends(get_pg_session)):
    """갱신 완료된 전 거래일 종가 기준 예상 주문(체결 시 수량 재계산)."""
    uid = _uid(user)
    plan = await rb.get_plan(db, uid)
    try:
        result = await rb.propose(db, uid, plan)
    except rb.RebalanceError as exc:
        raise HTTPException(400, str(exc))
    await db.commit()
    return result


@router.post("/execute")
async def execute(body: ExecuteBody, user=Depends(get_current_user_any), db: AsyncSession = Depends(get_pg_session)):
    """수동 리밸런싱(MANUAL) 또는 제안 승인의 다음 거래일 시가 예약."""
    uid = _uid(user)
    try:
        if body.run_id:
            run = await rb.execute_proposal(db, uid, uuid.UUID(body.run_id))
        else:
            plan = await rb.get_plan(db, uid)
            run = await rb.execute(db, uid, plan, "MANUAL", None, body.note or "사용자 수동 실행")
    except (rb.RebalanceError, ValueError) as exc:
        await db.rollback()
        raise HTTPException(400, str(exc))
    await db.commit()
    await db.refresh(run)
    await audit(user["id"], user.get("client_id", ""), "rebalance.execute",
                {"trigger": run.trigger, "orders": len(run.orders), "status": run.status})
    return rb.run_to_dict(run)


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: uuid.UUID, user=Depends(get_current_user_any),
                     db: AsyncSession = Depends(get_pg_session)):
    try:
        run = await settlement.cancel_reservation(db, _uid(user), run_id)
        if run is None:
            raise HTTPException(404, '예약을 찾을 수 없습니다.')
    except rb.RebalanceError as exc:
        await db.rollback()
        raise HTTPException(409, str(exc))
    await db.commit()
    await db.refresh(run)
    await audit(user['id'], user.get('client_id', ''), 'rebalance.cancel', {'run_id': str(run.id)})
    return rb.run_to_dict(run)


@router.post("/check")
async def check(user=Depends(get_current_user_any), db: AsyncSession = Depends(get_pg_session)):
    """시간·이탈률 트리거를 지금 점검(스케줄러와 동일 로직)."""
    uid = _uid(user)
    plan = await rb.get_plan(db, uid)
    try:
        result = await rb.check_daily(db, uid, plan)
        if not result["checked"]:
            result = {**result, "already_processed": result["reason"] == "already_checked",
                      "message": rb.daily.view(plan, await asyncio.to_thread(rb.daily.readiness))["message"]}
            if result["reason"] == "settlement_waiting":
                result.update(status="scheduled", message="기존 예약의 시가 체결을 기다립니다.")
    except rb.RebalanceError as exc:
        await db.rollback()
        raise HTTPException(409, str(exc))
    await db.commit()
    return result


@router.post("/cashflow")
async def cashflow(body: CashflowBody, user=Depends(get_current_user_any), db: AsyncSession = Depends(get_pg_session)):
    """현금 즉시 반영 → 다음 일별 점검 회차에서 리밸런싱 판단."""
    uid = _uid(user)
    try:
        result = await rb.record_cashflow(db, uid, body.kind, body.amount, body.symbol, body.memo)
    except rb.RebalanceError as exc:
        await db.rollback()
        raise HTTPException(400, str(exc))
    await db.commit()
    await audit(user["id"], user.get("client_id", ""), "rebalance.cashflow",
                {"kind": body.kind.upper(), "amount": body.amount, "symbol": body.symbol})
    return result


@router.get("/cashflows")
async def cashflows(limit: int = Query(50, ge=1, le=200), user=Depends(get_current_user_any),
                    db: AsyncSession = Depends(get_pg_session)):
    return {"events": await rb.list_cashflows(db, _uid(user), limit)}


@router.get("/runs")
async def runs(limit: int = Query(30, ge=1, le=200), user=Depends(get_current_user_any),
               db: AsyncSession = Depends(get_pg_session)):
    return {"runs": await rb.list_runs(db, _uid(user), limit)}
