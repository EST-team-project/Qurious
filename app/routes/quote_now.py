"""지금 값(quote_now) — 「현재가」 칸이 부르는 길 하나 (2026-10-19 · 사용자 「투자 인디케이터 210,000 · 실제 217,000」).

    GET /api/quote/now?symbol=005930.KS     지금 값 · 출처 · 시각 · 한 줄 글

로그인한 사람만 — 그 사람의 KIS 키가 있으면 증권사 조회 값을 쓰기 때문이다(실시간 시세는 자기 키 · 자기 화면까지 —
코스콤 정보이용정책 · KIS 약관 제5조 ③). 인증은 모의투자 길과 같다(세션 쿠키 또는 Bearer JWT).
값을 찾는 차례와 글은 app/services/quote_now.py 한 곳에 있다. 실시간 값은 저장하지 않는다(10초 메모리 저장본만).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.postgres import get_pg_session
from app.lib.jwt_auth import get_current_user_any
from app.services import quote_now as qn

router = APIRouter(prefix="/api/quote", tags=["현재가"])


@router.get("/now", summary="지금 값 · 출처 · 시각(내 증권사 키 → 지연 시세 → 지난 종가)")
async def now(symbol: str = Query(..., min_length=1, max_length=20, pattern=r"^[0-9A-Za-z.\-]+$"),
              user: dict = Depends(get_current_user_any),
              db: AsyncSession = Depends(get_pg_session)) -> dict:
    try:
        uid = uuid.UUID(str(user["id"]))
    except (KeyError, ValueError):
        raise HTTPException(400, "유효하지 않은 사용자 ID입니다.") from None
    return await qn.quote_now(symbol, db=db, user_id=uid)
