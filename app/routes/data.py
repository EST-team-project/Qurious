"""데이터 상태 · 규격 자료 API — /api/data (목표 기능 ① W4 · 설계서 5.2.2 · 7절)

- GET /api/data/status : 일일 갱신(12:30 러너) 결과 · 표별 기준일과 늦음 판정 · 거래일 달력 · HF 태그
- GET /api/data/ohlcv  : 한 종목 · 한 주기 · 한 기간의 OHLCV(`ohlcv-v1` — HF krx-ohlcv 와 같은 줄 모양)

로그인한 사람만 — 수집 자료의 양 · 상태와 PC 의 작업 기록이라(설계서 7절 「수집 자료는 로그인 뒤」).
`GET /api/system/sync-status`(외부 시세 캐시의 신선도)와는 다른 것을 본다 — 화면의 「데이터 기준일」 은 이쪽이다.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query

from app.lib.session import get_current_user
from app.services import data_ohlcv, data_status

router = APIRouter(prefix="/api/data", tags=["data"])


@router.get("/status", summary="데이터 상태")
async def status(_user=Depends(get_current_user)):
    # 표 세기 · 파일 읽기는 1초 안팎이지만 이벤트 루프를 막지 않게 스레드에서 돈다.
    return await asyncio.to_thread(data_status.get_status)


@router.get("/ohlcv", summary="OHLCV 규격 자료(ohlcv-v1)")
async def ohlcv(
    symbol: str = Query(..., max_length=80,
                        description="주식 · ETF 단축코드 6자리(005930 · 0000D0) 또는 지수 「시리즈:이름」(KOSPI:코스피 200)"),
    timeframe: str = Query("1d", description="1d · 1w · 60m · 5m"),
    from_: str | None = Query(None, alias="from", description="YYYY-MM-DD — 비우면 주기마다 정한 만큼 앞(1d 1년 · 1w 3년 · 60m 30일 · 5m 7일)"),
    to: str | None = Query(None, description="YYYY-MM-DD — 비우면 오늘(KST)"),
    basis: str | None = Query(None, description="수정 방식 — 주식 adj_base(기본) · raw / ETF · 지수 raw / 분봉 adj_split"),
    limit: int = Query(data_ohlcv.DEFAULT_LIMIT, ge=1, le=data_ohlcv.MAX_LIMIT,
                       description="줄이 이보다 많으면 자르지 않고 422 로 알린다"),
    _user=Depends(get_current_user),
):
    try:
        return await asyncio.to_thread(data_ohlcv.read_ohlcv, symbol, timeframe, from_, to, basis, limit)
    except data_ohlcv.OhlcvError as e:
        # 고칠 수 있는 잘못은 상태 · 할 일과 함께(없는 지수면 비슷한 이름 후보까지)
        raise HTTPException(status_code=e.status, detail=e.detail()) from None
