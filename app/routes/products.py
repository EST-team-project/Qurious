"""상품 안내 API — /api/products (화면 키 `agent-products` · 결정 ② A · 2026-10-12)

- GET /api/products/etfs/overview : 자산군 → 묶음별 ETF 개수와 순자산 큰 순 몇 개(수집 DB · 마지막 거래일)
- GET /api/products/etfs          : 한 자산군 · 묶음의 ETF 전체 목록(정렬 · 쪽 나눔 · 이름 찾기)
- GET /api/products/etfs/{code}/chart : 한 종목의 상품 상세 창 — 기간 계열 · 칩마다 요약과 쉬운 말 문장(서버가 만든다)
  · 레버리지 · 인버스의 「왜 n배가 아닌가」 세 값 · 머리 숫자는 목록 줄과 같은 값
- GET /api/products/savings       : 예금 · 적금 · 연금저축 — 금융감독원 「금융상품 한눈에」 오픈 API 를 **부를 때마다**
  받아 보여 준다(약관 제9조 — 저장하지 않는다 · 응답의 출처 문구를 화면이 그대로 보인다)

투자 성향 → 자산군 비중은 자산 배분(`/api/ml/robo/allocation` · 오준영 님 몫)이 정본이다. 이 API 는 비중을 계산하지
않고 자산군마다 「공시된 상품 정보」 를 정해진 기준으로 늘어놓는다 — 「추천」 이 아니다(사용자 결정 2026-10-12).
로그인한 사람만(수집 자료는 로그인 뒤 · 설계서 7절). 키가 없을 때 고칠 곳은 관리자에게만 알린다.
"""
from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from app.lib.session import get_current_user
from app.services import fss_products, product_chart, product_etfs

router = APIRouter(prefix="/api/products", tags=["products"])


@router.get("/etfs/overview", summary="상품 안내 — ETF 자산군 · 묶음 한눈에")
async def etf_overview(
    per_group: int = Query(3, ge=1, le=20, description="묶음마다 돌려줄 ETF 수(순자산 큰 순) — 개수 칸은 늘 전체"),
    _user=Depends(get_current_user),
):
    # 1년치 일봉을 한 번 읽어 지표를 재므로(첫 부름 1초 안팎) 이벤트 루프를 막지 않게 스레드에서 돈다
    return await asyncio.to_thread(product_etfs.overview, per_group)


@router.get("/etfs", summary="상품 안내 — ETF 목록")
async def etf_list(
    asset_class: str | None = Query(None, description="국내주식 · 해외주식 · 국내채권 · 대체자산 · 현금 · 그 밖"),
    group: str | None = Query(None, description="자산군 묶음(market · sector_theme · strategy · … — overview 의 group_labels) 또는 "
                                "레버리지 · 인버스 묶음(index_plus2 · index_minus1 · index_minus2 · single_stock · other_assets)"),
    q: str | None = Query(None, max_length=40, description="이름 · 기초지수 이름 · 종목코드"),
    sort: Literal["aum", "trade_value", "return_1y", "vol_1y", "name"] = "aum",
    order: Literal["desc", "asc"] = "desc",
    offset: int = Query(0, ge=0, le=5000),
    limit: int = Query(50, ge=1, le=200),
    _user=Depends(get_current_user),
):
    try:
        return await asyncio.to_thread(product_etfs.list_etfs, asset_class=asset_class, group=group, q=q,
                                       sort=sort, order=order, offset=offset, limit=limit)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.get("/etfs/{code}/chart", summary="상품 안내 — ETF 한 종목의 기간 그림 자료(상품 상세 창)")
async def etf_chart(
    code: str = Path(..., pattern=r"^[0-9A-Z]{6}$", description="종목코드(단축 6자리 — 예 069500 · 0000D0)"),
    period: Literal["1m", "6m", "1y", "3y"] = Query("1y", description="1개월 · 6개월 · 1년 · 3년(기준일부터 거슬러)"),
    _user=Depends(get_current_user),
):
    # 목록 계산(캐시)을 먼저 보고 한 종목만 색인으로 읽는다 — 첫 부름이면 목록 계산 1초 안팎이 함께 든다
    try:
        result = await asyncio.to_thread(product_chart.chart, code, period)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    if result["status"] == "not_found":
        raise HTTPException(404, "그날 상품 목록에 없는 종목입니다")
    return result


@router.get("/savings", summary="상품 안내 — 예금 · 적금 · 연금저축(금융감독원 실시간)")
async def savings(
    kind: Literal["deposit", "saving", "annuity"] = Query(..., description="deposit 정기예금 · saving 적금 · annuity 연금저축"),
    sector: Literal["bank", "savings_bank", "insurance", "investment", "credit_card"] = "bank",
    term: int = Query(12, description="저축 기간(개월) — 1 · 3 · 6 · 12 · 24 · 36"),
    sort: Literal["base", "max", "name"] = "base",
    user=Depends(get_current_user),
):
    try:
        result = await fss_products.search(kind=kind, sector=sector, term=term, sort=sort)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    if result["status"] != "ok" and "admin" in (user.get("roles") or []):
        result["admin_detail"] = fss_products.ADMIN_DETAIL.get(result["status"], "")
    return result
