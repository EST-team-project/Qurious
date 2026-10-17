"""미국주식 예약 주문 · 미국 정규장 상태 (모의투자 · 2026-10-17 · L10 설계 C).

규칙은 `app/services/us_reserve.py` 한 곳 — 이 파일은 사용자 · DB 를 붙이고 오류를 HTTP 로 바꾸기만 한다.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.postgres import get_pg_session
from app.lib.jwt_auth import get_current_user_any
from app.services import paper_trading, us_reserve
from app.services.audit import audit

router = APIRouter(prefix="/api/paper", tags=["paper"])


class ReserveBody(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20)
    quantity: int = Field(..., ge=1, le=100_000)


def _uid(user: dict) -> uuid.UUID:
    try:
        return uuid.UUID(str(user["id"]))
    except (KeyError, ValueError):
        raise HTTPException(400, "유효하지 않은 사용자입니다.") from None


@router.get("/stocks/us-market", summary="미국 정규장 상태 — 열림 · 닫힘 · 다음 정규장(KST)")
async def us_market():
    return us_reserve.market_state()


@router.get("/stocks/reservations", summary="미국주식 예약 주문 목록 — 정규장이 이미 열린 예약은 그 시가로 먼저 체결")
async def reservations(user=Depends(get_current_user_any), db: AsyncSession = Depends(get_pg_session)):
    uid = _uid(user)
    fired = await us_reserve.fill_due(db, uid)
    await db.commit()
    return {"market": us_reserve.market_state(), "fired": fired,
            "reservations": await us_reserve.list_reservations(db, uid), "note": us_reserve.NOTE}


@router.post("/stocks/reservations", status_code=201, summary="미국주식 매수 예약(장이 닫힌 때만) — 다음 정규장 시작가로 체결")
async def reserve(body: ReserveBody, user=Depends(get_current_user_any), db: AsyncSession = Depends(get_pg_session)):
    try:
        result = await us_reserve.place(db, _uid(user), body.symbol.strip(), body.quantity)
    except us_reserve.MarketOpenError as exc:
        raise HTTPException(409, str(exc)) from None
    except paper_trading.PaperTradeError as exc:          # ReserveError 도 여기로(같은 갈래)
        await db.rollback()
        raise HTTPException(400, str(exc)) from None
    await db.commit()
    await audit(user["id"], user.get("client_id", ""), "paper.stock.reserve",
                {"symbol": result["symbol"], "quantity": body.quantity, "order_id": result["order_id"]})
    return result


@router.delete("/stocks/reservations/{order_id}", summary="대기 중인 미국주식 예약 취소")
async def cancel_reservation(order_id: str, user=Depends(get_current_user_any), db: AsyncSession = Depends(get_pg_session)):
    try:
        result = await us_reserve.cancel(db, _uid(user), order_id)
    except paper_trading.PaperTradeError as exc:
        raise HTTPException(404, str(exc)) from None
    await db.commit()
    await audit(user["id"], user.get("client_id", ""), "paper.stock.reserve.cancel", {"order_id": result["order_id"]})
    return result
