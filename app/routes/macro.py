"""거시경제 지표 · 산업 분석 · 재무 분석 API."""
from fastapi import APIRouter, Depends, Query
from app.lib.session import get_current_user
from app.services.stock import get_candles, _yahoo_chart
from app.services.data_cache import cache_get, cache_set
from app.services.sync_scheduler import (
    KEY_MACRO_INDICATORS, KEY_SECTOR_ETFS, KEY_US_STOCKS,
    MACRO_SYMBOLS, SECTOR_ETFS, US_STOCKS,
)
from app.services import data_provenance, sync_scheduler

router = APIRouter(prefix="/api/macro")


async def _get_latest(symbol: str, unit: str) -> dict:
    """최신 시세 한 줄 — 예약 동기화와 **같은 함수**(아래 return 줄 · DF-123 · 2026-10-16).

    옛 판은 같은 꼴을 여기 따로 두고 기간 5일로 받아 「전일 대비」 가 5거래일 전 종가 대비였다(동기화 쪽도 같았다).
    별칭으로 묶지 않고 모듈 이름으로 부른다 — 그쪽을 고치거나 시험이 갈아 끼우면 이 라우트도 따라간다.
    """
    return await sync_scheduler._yahoo_latest(symbol, unit)


@router.get("/indicators")
async def macro_indicators(_user=Depends(get_current_user)):
    """거시경제 지표 현황 (금리·물가·유가·환율·주가지수). PostgreSQL cache-first."""
    import asyncio
    cached = await cache_get(KEY_MACRO_INDICATORS, max_age_hours=2)
    if cached is not None:
        return {"indicators": cached, "from_cache": True,
                "note": data_provenance.quote_note(cached, from_cache=True)}   # 지연 · 시각 · 저장본(L8 · DF-123)

    tasks = [_get_latest(m["symbol"], m["unit"]) for m in MACRO_SYMBOLS]
    results = await asyncio.gather(*tasks)
    enriched = [{**m, **r} for m, r in zip(MACRO_SYMBOLS, results)]
    await cache_set(KEY_MACRO_INDICATORS, enriched)
    return {"indicators": enriched, "from_cache": False,
            "note": data_provenance.quote_note(enriched, from_cache=False)}


@router.get("/industry")
async def macro_industry(_user=Depends(get_current_user)):
    """미국 섹터 ETF 기반 산업 분석. PostgreSQL cache-first."""
    import asyncio
    cached = await cache_get(KEY_SECTOR_ETFS, max_age_hours=2)
    if cached is not None:
        return {"sectors": cached, "from_cache": True,
                "note": data_provenance.quote_note(cached, from_cache=True)}

    tasks = [_get_latest(s["symbol"], "") for s in SECTOR_ETFS]
    results = await asyncio.gather(*tasks)
    enriched = [{**s, **r} for s, r in zip(SECTOR_ETFS, results)]
    enriched = sync_scheduler.sort_by_change(enriched)   # 모르는 줄은 맨 뒤(동기화와 같은 정렬 · DF-123)
    await cache_set(KEY_SECTOR_ETFS, enriched)
    return {"sectors": enriched, "from_cache": False,
            "note": data_provenance.quote_note(enriched, from_cache=False)}


@router.get("/us-stocks")
async def macro_us_stocks(_user=Depends(get_current_user)):
    """미국 주요 종목 시세. PostgreSQL cache-first."""
    import asyncio
    cached = await cache_get(KEY_US_STOCKS, max_age_hours=2)
    if cached is not None:
        return {"stocks": cached, "from_cache": True,
                "note": data_provenance.quote_note(cached, from_cache=True)}

    tasks = [_get_latest(s["symbol"], "USD") for s in US_STOCKS]
    results = await asyncio.gather(*tasks)
    enriched = [{**s, **r} for s, r in zip(US_STOCKS, results)]
    await cache_set(KEY_US_STOCKS, enriched)
    return {"stocks": enriched, "from_cache": False,
            "note": data_provenance.quote_note(enriched, from_cache=False)}


@router.get("/fundamental")
async def macro_fundamental(
    symbol: str = Query("005930.KS"),
    _user=Depends(get_current_user),
):
    """
    재무제표 기반 밸류에이션 지표 (DCF/EVA/FCF 개념 설명 포함).

    실제 재무 데이터는 Yahoo Finance summary 메타에서 추출.
    """
    data = await _yahoo_chart(symbol, "1d", "1d")
    if not data:
        return {"symbol": symbol, "error": "데이터 없음"}

    meta = data.get("meta", {})
    price = meta.get("regularMarketPrice", 0)

    # Yahoo Finance는 상세 재무제표를 v8/chart API에서 직접 제공하지 않으므로
    # 실무에서는 yfinance .info 또는 별도 재무 API를 사용합니다.
    # 여기서는 개념 설명 + 목업 지표를 반환합니다.
    dcf_mock = round(price * 1.15, 2)  # 내재가치 (단순 성장률 15% 가정)
    fcf_yield = round(100 / max(price, 1) * 1000, 2)  # 모의 FCF 수익률

    return {
        "symbol": symbol,
        "price":  price,
        "valuation": {
            "DCF_intrinsic_value": dcf_mock,
            "FCF_yield_pct":       fcf_yield,
            "concept": {
                "DCF":  "미래 현금흐름을 현재가치로 할인 (Discounted Cash Flow)",
                "EVA":  "경제적 부가가치 = NOPAT - 자본비용 (Economic Value Added)",
                "FCF":  "잉여현금흐름 = 영업현금흐름 - 설비투자 (Free Cash Flow)",
            },
        },
        "note": "실제 재무제표 연동은 DART API 또는 yfinance .info를 활용하세요.",
    }
