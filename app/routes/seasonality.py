"""계절성 분석 API — /api/seasonality (화면 키 `quant-seasonal` · 금융 필수 지식 › 계절성 · 2026-10-14)

- GET /api/seasonality : 시장 지수(코스피 1995 ~ · 코스닥 2003 ~ — 한국은행 ECOS 가격 지수) 또는 종목(2020 ~ — 수집 시세로
  만든 총수익 · 가격 지수)의 달 수익률 해마다 표 · 달 · 요일 통계(홀름 보정) · 산타 랠리 창 · 연말 두 달 · 쉬운 문장 · 출처

옛 화면은 강사님 `/api/ml/seasonality`(일간 수익률의 달별 평균)를 불렀다 — 그 길은 강사님 코드라 그대로 두고 화면만 이 API 로
옮긴다. 계산 · 문장 · 기준값은 `app/services/seasonality.py` 한 곳. 로그인한 사람만 · 할 일(명령)은 관리자 답에만.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query

from app.lib.session import get_current_user
from app.services import seasonality

router = APIRouter(prefix="/api/seasonality", tags=["seasonality"])


@router.get("", summary="계절성 — 달 · 요일 · 연말 창의 과거 수익률(시장 지수 · 종목)")
async def seasonality_route(
    target: str = Query("KOSPI", max_length=12, description="KOSPI · KOSDAQ 또는 종목 단축코드 6자리(005930 · 005930.KS)"),
    basis: str = Query("tr", max_length=2, description="tr(총수익 — 배당 재투자 · 세전) · pr(가격) — 시장 지수는 가격뿐"),
    user=Depends(get_current_user),
):
    admin = "admin" in user.get("roles", [])
    try:
        return await asyncio.to_thread(seasonality.read_seasonality, target, basis, admin)
    except seasonality.SeasonalityError as e:
        # 수집 · 설정 문제(5xx)의 할 일(명령)은 관리자에게만 — 일반 사용자는 글만 본다
        raise HTTPException(status_code=e.status, detail=e.detail(admin)) from None
