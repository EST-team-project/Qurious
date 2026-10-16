"""Background data sync scheduler.

Runs an asyncio loop that wakes every SYNC_INTERVAL_SEC seconds.
When the internet is reachable it fetches all external data sources
and stores the results in PostgreSQL via data_cache so the app stays
functional when the network goes down.

Start/stop is managed by main.py lifespan.
"""
import asyncio
import logging
import time
from datetime import datetime, timezone

from app.services import collector_db, data_provenance, stock
from app.services.data_cache import cache_set, is_internet_available
from app.services.stock import (
    _yahoo_chart,
    get_market_summary,
    get_quant_indicators,
    QUANT_STOCKS,
    MARKET_INDICES,
)

logger = logging.getLogger(__name__)

SYNC_INTERVAL_SEC = 3600  # 1 hour for live market data
CANDLE_INTERVAL_SEC = 86400  # 24 hours for historical candles

# Keys used across the codebase — keep in sync with routes
KEY_MARKET_INDICES = "market_indices"
KEY_MACRO_INDICATORS = "macro_indicators"
KEY_SECTOR_ETFS = "sector_etfs"
KEY_US_STOCKS = "us_stocks"


# ── Macro symbols (mirrors macro.py) ─────────────────────────────────────────

MACRO_SYMBOLS = [
    {"symbol": "^TNX",     "name": "미 국채 10년 금리",   "unit": "%"},
    {"symbol": "^IRX",     "name": "미 국채 3개월 금리",  "unit": "%"},
    {"symbol": "CL=F",     "name": "WTI 원유",            "unit": "USD/bbl"},
    {"symbol": "GC=F",     "name": "금 선물",             "unit": "USD/oz"},
    {"symbol": "KRW=X",    "name": "USD/KRW 환율",        "unit": "KRW"},
    {"symbol": "DX-Y.NYB", "name": "달러 인덱스(DXY)",    "unit": ""},
    {"symbol": "^VIX",     "name": "VIX 공포지수",        "unit": ""},
    {"symbol": "^GSPC",    "name": "S&P 500",             "unit": ""},
    {"symbol": "^KS11",    "name": "KOSPI",               "unit": ""},
]

SECTOR_ETFS = [
    {"symbol": "XLK",  "name": "기술",     "sector": "Technology"},
    {"symbol": "XLF",  "name": "금융",     "sector": "Financials"},
    {"symbol": "XLE",  "name": "에너지",   "sector": "Energy"},
    {"symbol": "XLV",  "name": "헬스케어", "sector": "Health Care"},
    {"symbol": "XLI",  "name": "산업재",   "sector": "Industrials"},
    {"symbol": "XLY",  "name": "소비재",   "sector": "Consumer Disc."},
    {"symbol": "XLP",  "name": "필수소비", "sector": "Consumer Staples"},
    {"symbol": "XLB",  "name": "소재",     "sector": "Materials"},
    {"symbol": "XLRE", "name": "리츠",     "sector": "Real Estate"},
    {"symbol": "XLU",  "name": "유틸리티", "sector": "Utilities"},
    {"symbol": "XLC",  "name": "통신",     "sector": "Communication"},
]

# US blue-chip stocks tracked in the US dashboard
US_STOCKS = [
    {"symbol": "AAPL",  "name": "Apple",           "sector": "Technology"},
    {"symbol": "MSFT",  "name": "Microsoft",        "sector": "Technology"},
    {"symbol": "GOOGL", "name": "Alphabet",         "sector": "Technology"},
    {"symbol": "AMZN",  "name": "Amazon",           "sector": "Consumer Disc."},
    {"symbol": "NVDA",  "name": "NVIDIA",           "sector": "Technology"},
    {"symbol": "TSLA",  "name": "Tesla",            "sector": "Consumer Disc."},
    {"symbol": "META",  "name": "Meta",             "sector": "Communication"},
    {"symbol": "BRK-B", "name": "Berkshire Hathaway", "sector": "Financials"},
    {"symbol": "JPM",   "name": "JPMorgan",         "sector": "Financials"},
    {"symbol": "V",     "name": "Visa",             "sector": "Financials"},
]

# ── State ────────────────────────────────────────────────────────────────────

_sync_task: asyncio.Task | None = None
_last_sync: datetime | None = None
_last_sync_ok: bool = False
_syncing: bool = False


def get_sync_status() -> dict:
    return {
        "running": _sync_task is not None and not _sync_task.done(),
        "syncing": _syncing,
        "last_sync": _last_sync.isoformat() if _last_sync else None,
        "last_sync_ok": _last_sync_ok,
    }


# ── Sync helpers ─────────────────────────────────────────────────────────────

async def _yahoo_latest(symbol: str, unit: str) -> dict:
    """최신 시세 한 줄 — 미국주식 대시보드 · 거시경제 지표 · 산업 분석이 함께 쓰는 **한 곳**(라우트 `macro._get_latest` 도
    이 함수를 부른다 · DF-123 · 2026-10-16).

    - **기간 1일**로 받는다. 응답의 `chartPreviousClose` 는 「차트 첫 봉 바로 앞 종가」라 기간이 5일이면 5거래일 전 종가다
      (옛 코드가 그랬다 — 10-16 실측 AAPL −0.28% 가 +0.46% · TSLA −1.29% 가 −3.35%). `get_quote` 의 9-28 고침(TC-A1)과 같은 꼴.
    - 전일 대비는 `stock._change_from_prev` 한 곳 — 모르면 None(0 은 「보합」 이라는 거짓 · 화면은 「—」).
    - 현재가가 없으면 오류 줄이다 — 옛 코드는 전일 종가나 0 을 현재가로 채웠다(말없는 fallback).
    - `as_of` 는 그 값이 생긴 시각(마지막 체결 · KST) — 화면이 「언제 값인지」 말하게(L8).
    """
    data = await _yahoo_chart(symbol, "1d", "1d")
    if not data:
        return {"symbol": symbol, "error": "데이터 없음", "unit": unit}
    meta = data.get("meta", {})
    price = meta.get("regularMarketPrice")
    if price is None:
        return {"symbol": symbol, "error": "현재가 없음", "unit": unit}
    chg, chg_p = stock._change_from_prev(price, meta.get("previousClose") or meta.get("chartPreviousClose"))
    now = time.time()
    reg = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    # 받을 때 그 종목 정규장 안이었나 — 공급자가 준 정규장 시작 · 끝(유닉스 초). 모르면 None(지어내지 않는다).
    # ⚠️ 코스피(^KS11)는 공급자 정규장 끝이 15:00 으로 와(실제 15:30) 15:00 ~ 15:30 에는 「닫힘」 으로 나온다(10-16 실측).
    opened = (reg["start"] <= now < reg["end"]) if isinstance(reg.get("start"), (int, float)) \
        and isinstance(reg.get("end"), (int, float)) else None
    return {
        "symbol":      symbol,
        "price":       price,
        "change":      chg,
        "change_p":    chg_p,
        "unit":        unit,
        "as_of":       data_provenance.quote_time_kst(meta.get("regularMarketTime")),
        "fetched_at":  data_provenance.quote_time_kst(now),
        "market_open": opened,
    }


def sort_by_change(rows: list[dict]) -> list[dict]:
    """등락률 큰 차례 · 모르는 줄(None · 오류)은 맨 뒤 — 산업 분석 라우트와 예약 동기화가 같은 정렬(DF-123).

    옛 정렬(`x.get("change_p", 0)`)은 None 끼리 견주다 500 이 나거나 모르는 줄을 0 자리에 끼웠다.
    """
    known = [r for r in rows if isinstance(r.get("change_p"), (int, float))]
    unknown = [r for r in rows if not isinstance(r.get("change_p"), (int, float))]
    return sorted(known, key=lambda r: r["change_p"], reverse=True) + unknown


async def _sync_market_indices() -> None:
    indices = await get_market_summary()
    await cache_set(KEY_MARKET_INDICES, indices)
    logger.info("[sync] market_indices: %d items", len(indices))


async def _sync_macro_indicators() -> None:
    tasks = [_yahoo_latest(m["symbol"], m["unit"]) for m in MACRO_SYMBOLS]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    enriched = []
    for m, r in zip(MACRO_SYMBOLS, results):
        if isinstance(r, Exception):
            enriched.append({**m, "error": str(r)})
        else:
            enriched.append({**m, **r})
    await cache_set(KEY_MACRO_INDICATORS, enriched)
    logger.info("[sync] macro_indicators: %d items", len(enriched))


async def _sync_sector_etfs() -> None:
    tasks = [_yahoo_latest(s["symbol"], "") for s in SECTOR_ETFS]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    enriched = []
    for s, r in zip(SECTOR_ETFS, results):
        if isinstance(r, Exception):
            enriched.append({**s, "error": str(r)})
        else:
            enriched.append({**s, **r})
    enriched = sort_by_change(enriched)
    await cache_set(KEY_SECTOR_ETFS, enriched)
    logger.info("[sync] sector_etfs: %d items", len(enriched))


async def _sync_us_stocks() -> None:
    tasks = [_yahoo_latest(s["symbol"], "USD") for s in US_STOCKS]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    enriched = []
    for s, r in zip(US_STOCKS, results):
        if isinstance(r, Exception):
            enriched.append({**s, "error": str(r)})
        else:
            enriched.append({**s, **r})
    await cache_set(KEY_US_STOCKS, enriched)
    logger.info("[sync] us_stocks: %d items", len(enriched))


async def _sync_stock_candles() -> None:
    """Warm the candle + indicator cache for the full quant universe (~30 stocks).

    Runs on every sync cycle (hourly). Concurrency is capped so we don't hammer
    Yahoo Finance with 30+ simultaneous requests; get_candles() already caches
    its own result via data_cache, so this just keeps that cache fresh for the
    robo-advisor / auto-trade scans that read from the same universe.
    """
    from app.services.stock import get_candles
    sem = asyncio.Semaphore(6)

    async def _warm_candles(sym: str) -> None:
        async with sem:
            try:
                data = await get_candles(sym, period="2y", interval="1d")
                if data.get("candles"):
                    logger.info("[sync] candles %s: %d bars", sym, len(data["candles"]))
            except Exception as e:
                logger.warning("[sync] candles %s failed: %s", sym, e)

    async def _warm_indicators(sym: str) -> None:
        async with sem:
            try:
                data = await get_quant_indicators(sym, period="2y")
                if not data.get("error"):
                    await cache_set(f"indicators:{sym}:2y", data)
            except Exception as e:
                logger.warning("[sync] indicators %s failed: %s", sym, e)

    # 수집 DB 다리가 받는 종목은 데우지 않는다(DF-17). 일봉은 다리가 파일에서 바로 읽고, 지표 라우트는
    # 그 요청에 캐시를 쓰지 않으므로 여기서 쓴 `indicators:` 키를 아무도 읽지 않는다.
    # DB 가 없는 환경은 옛 경로(외부 차트)라 그대로 데운다.
    symbols = [s["symbol"] for s in QUANT_STOCKS if not collector_db.handles(s["symbol"], "2y", "1d")]
    if len(symbols) < len(QUANT_STOCKS):
        logger.info("[sync] candles: 수집 DB 다리가 받는 %d종목은 데우지 않는다",
                    len(QUANT_STOCKS) - len(symbols))
    await asyncio.gather(*(_warm_candles(s) for s in symbols))
    await asyncio.gather(*(_warm_indicators(s) for s in symbols))


# ── Public sync entrypoint ────────────────────────────────────────────────────

async def sync_all(force: bool = False) -> dict:
    """Run a full sync cycle.  Returns result summary."""
    global _last_sync, _last_sync_ok, _syncing

    if _syncing:
        return {"ok": False, "reason": "already_syncing"}

    online = await is_internet_available()
    if not online and not force:
        logger.info("[sync] offline — skipping")
        return {"ok": False, "reason": "offline"}

    _syncing = True
    errors = []
    try:
        for fn in (
            _sync_market_indices,
            _sync_macro_indicators,
            _sync_sector_etfs,
            _sync_us_stocks,
        ):
            try:
                await fn()
            except Exception as e:
                logger.exception("[sync] %s failed: %s", fn.__name__, e)
                errors.append(f"{fn.__name__}: {e}")

        # Candles are cached separately — run them too but don't block result
        asyncio.create_task(_sync_stock_candles())

        _last_sync = datetime.now(timezone.utc)
        _last_sync_ok = not errors
        return {"ok": True, "errors": errors, "synced_at": _last_sync.isoformat()}
    finally:
        _syncing = False


# ── Background scheduler loop ────────────────────────────────────────────────

async def _scheduler_loop() -> None:
    logger.info("[sync] scheduler started (interval=%ds)", SYNC_INTERVAL_SEC)
    # Immediate first sync at startup
    await asyncio.sleep(5)
    while True:
        try:
            result = await sync_all()
            logger.info("[sync] cycle done: %s", result)
        except Exception:
            logger.exception("[sync] unexpected scheduler error")
        await asyncio.sleep(SYNC_INTERVAL_SEC)


def start_sync_scheduler() -> None:
    global _sync_task
    if _sync_task is None or _sync_task.done():
        _sync_task = asyncio.create_task(_scheduler_loop())
        logger.info("[sync] scheduler task created")


def stop_sync_scheduler() -> None:
    global _sync_task
    if _sync_task and not _sync_task.done():
        _sync_task.cancel()
    _sync_task = None
    logger.info("[sync] scheduler stopped")
