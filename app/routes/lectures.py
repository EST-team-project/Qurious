"""금융 강의 API — /api/lectures (「금융 필수 지식」 › 강의실 · 주제 화면)

강의 본문(public/lectures/days/*.html)의 그림이 부르는 시세 주소다. 통합본의 `/market/*` 일곱 주소를
같은 모양으로 옮겼고, 계산은 app/services/lecture_market.py 가 한다(수집 DB 먼저 · 야후는 화면 표시만 · 저장 없음).

- GET  /api/lectures/market/kospi-history               : 코스피 일봉 종가 (최대 370일)
- GET  /api/lectures/market/rate-market-history         : 코스피 + 국고채 10년 ETF (최대 760일)
- GET  /api/lectures/market/kospi200-history            : 코스피 200 현물 지수 (최대 270일)
- GET  /api/lectures/market/central-bank-event-history  : 정책금리 결정일 전후의 대표 지수
- GET  /api/lectures/market/intraday                    : 오늘의 1분봉 (30초 캐시)
- GET  /api/lectures/market/period-return               : 고른 기간의 종가 대 종가 수익률
- POST /api/lectures/market/period-return/extend        : 더 앞선 이력 요청 — 저장하지 않고 가장 이른 날짜만 답한다
- GET  /api/lectures/historic-bond-image                : 3일차 본문의 국채 사료 그림(e뮤지엄 공개 사료를 대신 받아 건넨다)

로그인 없이 읽는다 — 강의 본문과 같이 누구에게나 같은 공개 시세이고 사용자 데이터가 없다(통합본도 같았다).
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.services import lecture_market as lm

router = APIRouter(prefix="/api/lectures", tags=["lectures"])


async def _run(coro):
    """계산부의 오류를 HTTP 오류로 — 강의 그림은 상태 번호와 `detail` 문구를 읽는다."""
    try:
        return await coro
    except lm.MarketDataError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.get("/market/kospi-history", summary="코스피 일봉 종가")
async def kospi_history(
    start: date = Query(description="조회 시작일(YYYY-MM-DD)"),
    end: date = Query(description="조회 종료일(YYYY-MM-DD, 미포함)"),
):
    return await _run(lm.kospi_history(start, end))


@router.get("/market/rate-market-history", summary="코스피와 국고채 10년 ETF")
async def rate_market_history(
    start: date = Query(description="조회 시작일(YYYY-MM-DD)"),
    end: date = Query(description="조회 종료일(YYYY-MM-DD, 미포함)"),
):
    return await _run(lm.rate_market_history(start, end))


@router.get("/market/kospi200-history", summary="코스피 200 현물 지수")
async def kospi200_history(
    start: date = Query(description="조회 시작일(YYYY-MM-DD)"),
    end: date = Query(description="조회 종료일(YYYY-MM-DD, 미포함)"),
):
    return await _run(lm.kospi200_history(start, end))


@router.get("/market/central-bank-event-history", summary="정책금리 결정일 전후의 대표 지수")
async def central_bank_event_history(
    bank: str = Query(pattern=r"^(fed|ecb|boj|bok)$", description="fed · ecb · boj · bok"),
    meeting_date: date = Query(description="정책금리 결정일(YYYY-MM-DD)"),
    window: int = Query(default=5, ge=3, le=10, description="결정일 앞뒤로 볼 거래일 수"),
):
    return await _run(lm.central_bank_event_history(bank, meeting_date, window))


@router.get("/market/intraday", summary="오늘의 1분봉")
async def intraday(
    ticker: str = Query(pattern=r"^\d{6}$", description="종목 단축코드 6자리"),
    market: str = Query(pattern=r"^(KOSPI|KOSDAQ)$"),
):
    return await lm.intraday(ticker, market)


@router.get("/market/period-return", summary="고른 기간의 수익률")
async def period_return(
    ticker: str = Query(pattern=r"^[0-9A-Z]{6}$", description="종목 · ETF 단축코드"),
    start: date = Query(description="조회 시작일(YYYY-MM-DD)"),
    end: date = Query(description="조회 종료일(YYYY-MM-DD)"),
):
    try:
        return lm.period_return(ticker, start, end)
    except lm.MarketDataError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.post("/market/period-return/extend", summary="더 앞선 이력 요청 (저장하지 않음)")
async def extend_period_history(
    ticker: str = Query(pattern=r"^[0-9A-Z]{6}$"),
    start: date = Query(description="더 앞선 시작일(YYYY-MM-DD)"),
):
    return lm.extend_period_history(ticker, start)


@router.get("/historic-bond-image", summary="국채 사료 그림 (e뮤지엄)")
async def historic_bond_image():
    content, media = await _run(lm.historic_bond_image())
    return Response(content=content, media_type=media, headers={"Cache-Control": "public, max-age=86400"})
