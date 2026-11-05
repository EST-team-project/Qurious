"""거시경제 지표 · 산업 분석 · 재무 분석 API."""
from fastapi import APIRouter, Depends, Query
from app.lib.session import get_current_user
from app.services.stock import get_candles, _yahoo_chart
from app.services.data_cache import cache_get, cache_set
from app.services.sync_scheduler import (
    KEY_MACRO_INDICATORS, KEY_SECTOR_ETFS, KEY_US_STOCKS,
    MACRO_SYMBOLS, SECTOR_ETFS, US_STOCKS,
)
# macro_industry 는 아래 /industry 라우트 함수 이름과 같아 별칭으로 가져온다(같은 이름이면 모듈이 함수에 가려진다)
from app.services import data_provenance, macro_ecos, sync_scheduler
from app.services import macro_industry as industry_kr_service

router = APIRouter(prefix="/api/macro")

#: 저장본(data_cache)을 그대로 보이는 평소 한도 — 예약 동기화가 채운 값은 최대 2시간 된 것이다.
CACHE_MAX_AGE_HOURS = 2
#: 새로고침(`?refresh=true`) 요청도 이 안에 받은 저장본은 그대로 돌려준다 — 단추를 연타해도 야후를 연달아 두드리지 않는다(2026-11-05).
REFRESH_MIN_AGE_SECONDS = 60


def _max_age_hours(refresh: bool) -> float:
    """저장본을 믿는 한도(시간) — 평소 2시간 · 새로고침이면 60초(그보다 오래된 저장본은 버리고 다시 받는다)."""
    return REFRESH_MIN_AGE_SECONDS / 3600 if refresh else CACHE_MAX_AGE_HOURS


def _refresh_meta(refresh: bool, from_cache: bool, failed: bool = False) -> dict:
    """응답에 붙는 새로고침 안내 — 화면이 「방금 받은 값이라 그대로입니다 · 다시 받지 못했습니다」 를 말할 수 있게(요청이 없으면 빈 사전)."""
    if not refresh:
        return {}
    meta = {"requested": True, "reused_cache": from_cache, "min_age_seconds": REFRESH_MIN_AGE_SECONDS}
    if failed:
        meta["failed"] = True
    return {"refresh": meta}


def _has_prices(rows: list[dict]) -> bool:
    """받은 줄 가운데 값이 하나라도 있나 — 전부 비면 외부 시세가 막힌 것이다."""
    return any(isinstance(r, dict) and r.get("price") is not None for r in rows)


async def _keep_old_when_refresh_failed(refresh: bool, key: str, enriched: list[dict], field: str) -> dict | None:
    """새로고침으로 받았는데 값이 전부 비었으면 저장본을 덮어쓰지 않고 이전 저장본(최대 2시간)을 돌려준다 — 외부 시세가 막힌 순간
    누군가 새로고침을 눌렀다고 모든 사용자의 화면이 두 시간 동안 빈 값이 되면 안 된다. 이전 저장본도 없으면 None(평소처럼 그대로 낸다)."""
    if not refresh or _has_prices(enriched):
        return None
    kept = await cache_get(key, max_age_hours=CACHE_MAX_AGE_HOURS)
    if kept is None:
        return None
    return {field: kept, "from_cache": True, "note": data_provenance.quote_note(kept, from_cache=True),
            **_refresh_meta(refresh, True, failed=True)}


async def _get_latest(symbol: str, unit: str) -> dict:
    """최신 시세 한 줄 — 예약 동기화와 **같은 함수**(아래 return 줄 · DF-123 · 2026-10-16).

    옛 판은 같은 꼴을 여기 따로 두고 기간 5일로 받아 「전일 대비」 가 5거래일 전 종가 대비였다(동기화 쪽도 같았다).
    별칭으로 묶지 않고 모듈 이름으로 부른다 — 그쪽을 고치거나 시험이 갈아 끼우면 이 라우트도 따라간다.
    """
    return await sync_scheduler._yahoo_latest(symbol, unit)


@router.get("/ecos", summary="거시경제 현황 — 한국은행 ECOS(기준금리 · 시장금리 · 주가지수 · 환율 · 물가)")
async def macro_ecos_latest(user=Depends(get_current_user)):
    """수집 DB 의 한국은행 통계를 값 · 기준일 · 직전 값 · 출처와 함께(읽기만). 거시 화면(할 일 ①-10)이 부른다.

    야후 시세로 그리던 옛 /indicators 와 달리 한국 거시이고, 값마다 기준일이 있다. 자료가 없으면 available=false + 까닭
    (일반 사용자 답에는 표 이름 · 명령이 없고 관리자 답에만 admin_hint).
    """
    import asyncio
    admin = "admin" in user.get("roles", [])
    return await asyncio.to_thread(macro_ecos.read_ecos, admin)


@router.get("/indicators")
async def macro_indicators(_user=Depends(get_current_user), refresh: bool = False):
    """거시경제 지표 현황 (금리·물가·유가·환율·주가지수). PostgreSQL cache-first — `?refresh=true` 면 60초 넘은 저장본은 버리고 다시 받는다."""
    import asyncio
    cached = await cache_get(KEY_MACRO_INDICATORS, max_age_hours=_max_age_hours(refresh))
    if cached is not None:
        return {"indicators": cached, "from_cache": True,
                "note": data_provenance.quote_note(cached, from_cache=True),
                **_refresh_meta(refresh, True)}   # 지연 · 시각 · 저장본(L8 · DF-123)

    tasks = [_get_latest(m["symbol"], m["unit"]) for m in MACRO_SYMBOLS]
    results = await asyncio.gather(*tasks)
    enriched = [{**m, **r} for m, r in zip(MACRO_SYMBOLS, results)]
    kept = await _keep_old_when_refresh_failed(refresh, KEY_MACRO_INDICATORS, enriched, "indicators")
    if kept is not None:
        return kept
    await cache_set(KEY_MACRO_INDICATORS, enriched)
    return {"indicators": enriched, "from_cache": False,
            "note": data_provenance.quote_note(enriched, from_cache=False),
            **_refresh_meta(refresh, False)}


@router.get("/industry-kr", summary="국내 산업별 하루 등락 — KSIC 중분류 · DART 업종코드 · 일봉")
async def macro_industry_kr(user=Depends(get_current_user)):
    """수집 DB 의 업종코드(DART) · 업종 이름 표(KSIC) · 일봉 등락률로 업종별 등락 중앙값 · 오른 종목 수 · 종목 수(읽기만).

    산업 화면(할 일 ①-10)이 부른다. 미국 섹터 ETF 를 그리던 옛 /industry 와 달리 한국 종목이다 — 수집 대상 몇 곳만의 값이라
    응답에 곳 수와 「업종 전체 지수가 아니다」 라는 말을 싣는다. 자료가 없으면 available=false + 까닭(관리자에게만 admin_hint).
    """
    import asyncio
    admin = "admin" in user.get("roles", [])
    return await asyncio.to_thread(industry_kr_service.read_industry, admin)


@router.get("/industry")
async def macro_industry(_user=Depends(get_current_user), refresh: bool = False):
    """미국 섹터 ETF 기반 산업 분석. PostgreSQL cache-first — `?refresh=true` 면 60초 넘은 저장본은 버리고 다시 받는다."""
    import asyncio
    cached = await cache_get(KEY_SECTOR_ETFS, max_age_hours=_max_age_hours(refresh))
    if cached is not None:
        return {"sectors": cached, "from_cache": True,
                "note": data_provenance.quote_note(cached, from_cache=True),
                **_refresh_meta(refresh, True)}

    tasks = [_get_latest(s["symbol"], "") for s in SECTOR_ETFS]
    results = await asyncio.gather(*tasks)
    enriched = [{**s, **r} for s, r in zip(SECTOR_ETFS, results)]
    enriched = sync_scheduler.sort_by_change(enriched)   # 모르는 줄은 맨 뒤(동기화와 같은 정렬 · DF-123)
    kept = await _keep_old_when_refresh_failed(refresh, KEY_SECTOR_ETFS, enriched, "sectors")
    if kept is not None:
        return kept
    await cache_set(KEY_SECTOR_ETFS, enriched)
    return {"sectors": enriched, "from_cache": False,
            "note": data_provenance.quote_note(enriched, from_cache=False),
            **_refresh_meta(refresh, False)}


@router.get("/us-stocks")
async def macro_us_stocks(_user=Depends(get_current_user), refresh: bool = False):
    """미국 주요 종목 시세. PostgreSQL cache-first — `?refresh=true` 면 60초 넘은 저장본은 버리고 다시 받는다."""
    import asyncio
    cached = await cache_get(KEY_US_STOCKS, max_age_hours=_max_age_hours(refresh))
    if cached is not None:
        return {"stocks": cached, "from_cache": True,
                "note": data_provenance.quote_note(cached, from_cache=True),
                **_refresh_meta(refresh, True)}

    tasks = [_get_latest(s["symbol"], "USD") for s in US_STOCKS]
    results = await asyncio.gather(*tasks)
    enriched = [{**s, **r} for s, r in zip(US_STOCKS, results)]
    kept = await _keep_old_when_refresh_failed(refresh, KEY_US_STOCKS, enriched, "stocks")
    if kept is not None:
        return kept
    await cache_set(KEY_US_STOCKS, enriched)
    return {"stocks": enriched, "from_cache": False,
            "note": data_provenance.quote_note(enriched, from_cache=False),
            **_refresh_meta(refresh, False)}


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

    # 2026-10-29 ①-10 — 예전에는 여기서 DCF = 가격 × 1.15 · FCF 수익률 = 100 ÷ 가격 × 1000 으로 **지어낸 값**을 돌려줬다(「목업」).
    # 근거 없는 숫자라 내지 않는다: 두 칸은 null + 까닭. 재무제표 화면은 이제 이 길을 부르지 않고
    # /api/data/financials · /api/risk/company (DART 주요계정, 값마다 출처 · 기준일) 를 읽는다 — public/js/fundview.js.
    return {
        "symbol": symbol,
        "price":  price,
        "valuation": {
            "DCF_intrinsic_value": None,
            "FCF_yield_pct":       None,
            "reason": "계산하지 않습니다 — 잉여현금흐름에는 영업현금흐름과 설비투자가 필요한데 지금 읽는 DART 주요계정에는 없습니다.",
            "concept": {
                "DCF":  "미래 현금흐름을 현재가치로 할인 (Discounted Cash Flow)",
                "EVA":  "경제적 부가가치 = NOPAT - 자본비용 (Economic Value Added)",
                "FCF":  "잉여현금흐름 = 영업현금흐름 - 설비투자 (Free Cash Flow)",
            },
        },
        "note": "재무제표 숫자는 /api/data/financials · /api/risk/company(DART 주요계정)에서 읽습니다. 이 길은 개념 설명만 줍니다.",
    }
