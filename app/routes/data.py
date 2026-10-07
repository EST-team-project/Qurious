"""데이터 상태 · 규격 자료 API — /api/data (목표 기능 ① W4 · 설계서 5.2.2 · 7절)

- GET /api/data/status : 일일 갱신(12:30 러너) 결과 · 표별 기준일과 늦음 판정 · 거래일 달력 · HF 태그
- GET /api/data/ohlcv  : 한 종목 · 한 주기 · 한 기간의 OHLCV(`ohlcv-v1` — HF krx-ohlcv 와 같은 줄 모양)
- GET /api/data/search : 공시 · 뉴스 검색(낱말 · 이름표 · 공시 요약의 핵심 숫자) — W7 · 2026-10-04
- GET /api/data/financials : 재무 주요계정 — 기준일에 알 수 있었던 판만(pit) — W7 · 2026-10-04

로그인한 사람만 — 수집 자료의 양 · 상태와 PC 의 작업 기록이라(설계서 7절 「수집 자료는 로그인 뒤」).
`GET /api/system/sync-status`(외부 시세 캐시의 신선도)와는 다른 것을 본다 — 화면의 「데이터 기준일」 은 이쪽이다.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.lib.session import get_current_user
from app.services import data_financials, data_ohlcv, data_search, data_status, url_guard

router = APIRouter(prefix="/api/data", tags=["data"])


@router.get("/status", summary="데이터 상태")
async def status(_user=Depends(get_current_user)):
    # 표 세기 · 파일 읽기는 1초 안팎이지만 이벤트 루프를 막지 않게 스레드에서 돈다.
    return await asyncio.to_thread(data_status.get_status)


def _require_admin(user=Depends(get_current_user)):
    if "admin" not in user.get("roles", []):
        raise HTTPException(403, "관리자 권한이 필요합니다.")
    return user


@router.get("/runner", summary="수집 일정 · 단계(관리자)")
async def runner(_user=Depends(_require_admin)):
    # 단계 이름표 · 묶음 · 하는 일은 러너가 쓴 기록에서 읽는다 — 앱에 사본을 두지 않는다(결정 ④).
    return await asyncio.to_thread(data_status.runner_detail)


@router.get("/url-rules", summary="주소 검사 규칙 — 허용 목록 · 막음(관리자)")
async def url_rules(_user=Depends(_require_admin)):
    return url_guard.rules()


class UrlCheckBody(BaseModel):
    url: str = Field(..., max_length=2000)


@router.post("/url-check", summary="주소 검사 — 형식 · 내부망 · 허용 목록 · robots(관리자)")
async def url_check(body: UrlCheckBody, _user=Depends(_require_admin)):
    # 막혀도 200 — 화면이 까닭을 그대로 보인다(실제로 받는 길은 url_guard.ensure_allowed 가 400 으로 막는다).
    return await asyncio.to_thread(url_guard.check, body.url)


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


@router.get("/search", summary="수집 자료 검색(공시 · 뉴스)")
async def search(
    q: str = Query("", max_length=data_search.MAX_Q, description="검색어 — 띄어쓴 낱말마다 이어진 글로 찾는다(모두 맞아야 함)"),
    kind: str | None = Query(None, description="disclosure(공시) · news(뉴스) — 비우면 둘 다"),
    symbol: str | None = Query(None, max_length=6, description="종목 단축코드 6자리 — 종목 이름표로 거른다"),
    topic: str | None = Query(None, max_length=20, description="주제 이름표 — 실적 · 배당 · 증자 · 자기주식 · 합병·분할 …"),
    term: str | None = Query(None, max_length=80, description="용어 이름표 — 용어사전 id"),
    dtype: str | None = Query(None, max_length=1, description="공시 유형 A~J(A 정기 · B 주요사항 · I 거래소 …)"),
    from_: str | None = Query(None, alias="from", description="YYYY-MM-DD"),
    to: str | None = Query(None, description="YYYY-MM-DD"),
    sort: str = Query("date", description="date(최신순) · relevance(낱말 점수)"),
    limit: int = Query(data_search.DEFAULT_LIMIT, ge=1, le=data_search.MAX_LIMIT),
    offset: int = Query(0, ge=0, le=data_search.MAX_OFFSET),
    source: str | None = Query(None, max_length=20, description="dart(공시) · policy_news(정책뉴스) · gdelt(언론사 기사) — 비우면 전부"),
    facets: bool = Query(False, description="참이면 같은 조건에서 출처마다 몇 건인지 함께(종류 · 출처 거름은 빼고 센다)"),
    _user=Depends(get_current_user),
):
    try:
        return await asyncio.to_thread(data_search.search, q, kind, symbol, topic, term, dtype, from_, to,
                                       sort, limit, offset, source, facets)
    except data_search.SearchError as e:
        raise HTTPException(status_code=e.status, detail=e.detail()) from None


@router.get("/financials", summary="재무제표 주요계정(기준일에 알 수 있었던 판)")
async def financials(
    symbol: str = Query(..., max_length=6, description="종목 단축코드 6자리"),
    as_of: str | None = Query(None, description="YYYY-MM-DD — 이날 전날까지 접수된 판만(비우면 가장 최근 판)"),
    pit: str = Query("strict", description="strict(값의 접수일로 거름) · first(그 기간 원본 접수일로 거름 · 정정 표시)"),
    fs: str = Query("CFS", description="CFS(연결) · OFS(별도)"),
    periods: int = Query(data_financials.DEFAULT_PERIODS, ge=1, le=data_financials.MAX_PERIODS,
                         description="최근 몇 개 기간(분기 · 반기 · 사업보고서 각각 한 기간)"),
    _user=Depends(get_current_user),
):
    try:
        return await asyncio.to_thread(data_financials.read_financials, symbol, as_of, pit, fs, periods)
    except data_financials.FinancialsError as e:
        raise HTTPException(status_code=e.status, detail=e.detail()) from None
