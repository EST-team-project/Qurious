"""「금융 필수 지식」 강의의 시세 그림 — 강의 본문(public/lectures/days)이 부르는 시세 API 의 계산부.

어디서 왔나
-----------
통합본(investment-rag-lab)의 `app/api/routes/market.py` 에서 강의 사이트가 부르는 일곱 주소를 옮겼다.
돌려주는 모양(칸 이름 · 단위 · 오류 문구)은 그대로 둔다 — 강의 본문의 그림 코드가 그 모양을 읽는다.

무엇이 다른가
-------------
1. 국내 지수(코스피 · 코스피 200) · 국고채 10년 ETF(148070) · 종목 · ETF 일봉은 **수집 DB 를 먼저** 읽는다.
   통합본은 같은 값을 야후에서 받았다. 수집 DB 는 공공데이터포털의 공식 시세라 출처가 분명하고 외부 호출이 없다.
   수집 DB 가 없거나(팀원 PC 에 파일이 없을 때) 요청 기간을 덮지 못하면 그때만 야후로 간다.
2. 해외 지수(S&P 500 · EURO STOXX 50 · Nikkei 225)와 오늘의 1분봉은 수집 DB 에 없어 야후에서 받는다.
3. **받은 시세를 저장하지 않는다.** 통합본의 `POST /market/period-return/extend` 는 야후 값을 PostgreSQL 표에
   넣었다. 팀 규칙(야후 · 네이버 시세는 화면에 보여 주기만 하고 적재하지 않는다)에 걸리고, 수집 DB 가
   2020-01-02 부터 모든 거래일을 이미 갖고 있어 필요도 없다 — 그 주소는 「더 앞선 자료가 없다」 고만 답한다.
4. 캐시는 메모리에만 두고 수명은 통합본과 같다(1분봉 30초 · 코스피 이력 30일 · 금리 비교 6시간 · 코스피 200 30분).
"""
from __future__ import annotations

import ast
import asyncio
import logging
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from math import isfinite
from typing import Any

import httpx

from app.services import collector_db

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
YAHOO_CHART = "https://query2.finance.yahoo.com/v8/finance/chart/"
HEADERS = {"User-Agent": "Qurious/1.0 (educational use)"}

# 출처 이름 — 강의 그림이 「출처: …」 로 보여 준다(04일차 코스피 200 그림).
SOURCE_COLLECTOR = "공공데이터포털 (KRX 시세)"
SOURCE_YAHOO = "Yahoo Finance"
SOURCE_NAVER = "Naver Finance"

# 중앙은행 결정일 전후를 볼 그 나라 대표 지수 — 한국은행만 수집 DB 의 코스피로 읽는다
CENTRAL_BANK_BENCHMARKS = {
    "fed": {"symbol": "%5EGSPC", "name": "S&P 500", "timezone": "America/New_York"},
    "ecb": {"symbol": "%5ESTOXX50E", "name": "EURO STOXX 50", "timezone": "Europe/Frankfurt"},
    "boj": {"symbol": "%5EN225", "name": "Nikkei 225", "timezone": "Asia/Tokyo"},
    "bok": {"symbol": "%5EKS11", "name": "KOSPI", "timezone": "Asia/Seoul"},
}


class MarketDataError(Exception):
    """밖에서 시세를 못 받았거나 그릴 만큼 없을 때 — 라우트가 이 상태 번호와 문구로 바꾼다."""

    def __init__(self, detail: str, status_code: int = 502):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


# ── 메모리 캐시 ─────────────────────────────────────────────────────
_CACHES: dict[str, dict[str, tuple[datetime, Any]]] = {}
TTL = {
    "intraday": timedelta(seconds=30),
    "kospi": timedelta(days=30),
    "rate": timedelta(hours=6),
    "kospi200": timedelta(minutes=30),
}


def _cache_get(name: str, key: str) -> Any | None:
    hit = _CACHES.get(name, {}).get(key)
    if hit and datetime.now(timezone.utc) - hit[0] < TTL[name]:
        return hit[1]
    return None


def _cache_put(name: str, key: str, value: Any) -> Any:
    _CACHES.setdefault(name, {})[key] = (datetime.now(timezone.utc), value)
    return value


def clear_caches() -> None:
    """시험이 서로 섞이지 않게 비운다."""
    _CACHES.clear()


# ── 수집 DB (읽기 전용) ─────────────────────────────────────────────
def _connect() -> sqlite3.Connection | None:
    path = collector_db.db_path()
    if path is None:
        return None
    try:
        return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error as e:  # 파일이 잠겨 있거나 깨졌을 때 — 야후로 넘어간다
        logger.warning("수집 DB 를 열지 못했다(%s) — 강의 시세는 야후로 간다", e)
        return None


def _query(sql: str, params: tuple) -> list[tuple] | None:
    conn = _connect()
    if conn is None:
        return None
    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.Error as e:
        logger.warning("수집 DB 를 읽지 못했다(%s)", e)
        return None
    finally:
        conn.close()


def _ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


def _day(bas_dt: str) -> date:
    return datetime.strptime(bas_dt, "%Y%m%d").date()


def _ms(bas_dt: str) -> int:
    """그날 00:00 UTC(= 09:00 KST 장 시작)의 밀리초 — 야후 일봉의 시각과 같은 자리다."""
    return int(datetime.strptime(bas_dt, "%Y%m%d").replace(tzinfo=timezone.utc).timestamp() * 1000)


def _covers(days: list[date], start: date, end: date) -> bool:
    """수집 DB 의 봉이 요청 기간을 덮는가 — 앞뒤로 주말 · 연휴 만큼(7 · 8일)은 비어도 된다.

    덮지 못하면(2020 년 앞의 위기 사례 · 오늘 봉 등) 야후로 넘긴다. 통합본이 야후의 「끝이 모자란 이력」 을
    가린 기준(8일)과 같다.
    """
    if not days:
        return False
    today = datetime.now(KST).date()
    last_needed = min(end, today) - timedelta(days=1)
    return (days[0] - start).days <= 7 and (last_needed - days[-1]).days <= 8


def collector_index(name: str, start: date, end: date, series: str = "KOSPI시리즈") -> list[tuple[str, float]] | None:
    """지수 일봉 [start, end) — (bas_dt, 종가). 수집 DB 가 없거나 기간을 덮지 못하면 None."""
    rows = _query(
        "SELECT bas_dt, clpr FROM index_daily WHERE idx_csf=? AND idx_nm=? AND bas_dt>=? AND bas_dt<? ORDER BY bas_dt",
        (series, name, _ymd(start), _ymd(end)),
    )
    rows = [(d, float(c)) for d, c in (rows or []) if c is not None and isfinite(float(c))]
    return rows if _covers([_day(d) for d, _ in rows], start, end) else None


def collector_etf(code: str, start: date, end: date) -> tuple[str, list[tuple[str, float]]] | None:
    """ETF 일봉 [start, end) — (종목 이름, [(bas_dt, 종가)]). 덮지 못하면 None."""
    rows = _query(
        "SELECT bas_dt, clpr, itms_nm FROM etf_daily WHERE srtn_cd=? AND bas_dt>=? AND bas_dt<? ORDER BY bas_dt",
        (code, _ymd(start), _ymd(end)),
    )
    rows = [r for r in (rows or []) if r[1] is not None]
    if not _covers([_day(r[0]) for r in rows], start, end):
        return None
    return rows[-1][2], [(d, float(c)) for d, c, _ in rows]


# ── 야후 (화면 표시만 · 저장하지 않는다) ─────────────────────────────
async def yahoo_daily(symbol: str, start: date, end: date, tz: timezone = KST, timeout: float = 12.0) -> list[tuple[int, float]]:
    """야후 일봉 [start, end) — (유닉스 초, 종가). 실패하면 httpx · KeyError 등을 그대로 올린다."""
    p1 = int(datetime.combine(start, datetime.min.time(), tzinfo=tz).timestamp())
    p2 = int(datetime.combine(end, datetime.min.time(), tzinfo=tz).timestamp())
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.get(f"{YAHOO_CHART}{symbol}?period1={p1}&period2={p2}&interval=1d", headers=HEADERS)
        resp.raise_for_status()
    result = resp.json()["chart"]["result"][0]
    stamps = result.get("timestamp") or []
    closes = result["indicators"]["quote"][0].get("close") or []
    return [(t, float(c)) for t, c in zip(stamps, closes) if c is not None and isfinite(float(c))]


_YAHOO_ERRORS = (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError)


def _check_range(start: date, end: date, max_days: int) -> None:
    if start >= end or (end - start).days > max_days:
        raise MarketDataError(f"조회 기간은 최대 {max_days}일이며 시작일은 종료일보다 앞서야 합니다.", 400)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── 일곱 주소 ───────────────────────────────────────────────────────
async def kospi_history(start: date, end: date) -> dict[str, Any]:
    """코스피 일봉 종가 — 강의의 위기 사례 그림(01일차 · 03일차)."""
    _check_range(start, end, 370)
    key = f"{start}:{end}"
    if (hit := _cache_get("kospi", key)) is not None:
        return hit
    rows = collector_index("코스피", start, end)
    if rows:
        bars, source = [{"time": _ms(d), "close": c} for d, c in rows], SOURCE_COLLECTOR
    else:
        try:
            bars = [{"time": t * 1000, "close": c} for t, c in await yahoo_daily("%5EKS11", start, end, timeout=10.0)]
        except _YAHOO_ERRORS as exc:
            raise MarketDataError("KOSPI 과거 종가를 불러오지 못했습니다.") from exc
        source = SOURCE_YAHOO
    if not bars:
        raise MarketDataError("표시할 KOSPI 종가 데이터가 없습니다.")
    return _cache_put("kospi", key, {"symbol": "^KS11", "start": start.isoformat(), "end": end.isoformat(),
                                     "bars": bars, "source": source, "updated_at": _now()})


async def rate_market_history(start: date, end: date) -> dict[str, Any]:
    """코스피와 국고채 10년 ETF 를 한 그림에 — 금리와 주식시장의 관계(03일차)."""
    _check_range(start, end, 760)
    key = f"rate:{start}:{end}"
    if (hit := _cache_get("rate", key)) is not None:
        return hit
    kospi_rows = collector_index("코스피", start, end)
    etf = collector_etf("148070", start, end)
    if kospi_rows and etf:
        kospi = [{"time": _ms(d), "close": round(c, 2)} for d, c in kospi_rows]
        bond_name, bond = etf[0], [{"time": _ms(d), "close": round(c, 2)} for d, c in etf[1]]
        source = SOURCE_COLLECTOR
    else:
        try:
            k, b = await asyncio.gather(yahoo_daily("%5EKS11", start, end), yahoo_daily("148070.KS", start, end))
        except _YAHOO_ERRORS as exc:
            raise MarketDataError("비교 차트의 과거 시세를 불러오지 못했습니다.") from exc
        kospi = [{"time": t * 1000, "close": round(c, 2)} for t, c in k]
        bond = [{"time": t * 1000, "close": round(c, 2)} for t, c in b]
        bond_name, source = "국고채10년 ETF (148070)", SOURCE_YAHOO
    if len(kospi) < 21 or len(bond) < 2:
        raise MarketDataError("비교 차트에 필요한 충분한 과거 시세가 없습니다.")
    return _cache_put("rate", key, {
        "start": start.isoformat(), "end": end.isoformat(),
        "kospi": {"symbol": "^KS11", "name": "KOSPI", "bars": kospi},
        "bond_etf": {"symbol": "148070.KS", "name": bond_name, "bars": bond},
        "source": source, "updated_at": _now(),
    })


async def kospi200_history(start: date, end: date) -> dict[str, Any]:
    """코스피 200 현물 지수 — 선물 베이시스 연습(04일차). 선물 가격은 무료로 받을 곳이 없어 이론값을 화면이 계산한다."""
    _check_range(start, end, 270)
    key = f"{start}:{end}"
    if (hit := _cache_get("kospi200", key)) is not None:
        return hit
    warnings: list[str] = []
    rows = collector_index("코스피 200", start, end)
    if rows:
        bars, source = [{"time": _ms(d), "close": c} for d, c in rows], SOURCE_COLLECTOR
    else:
        bars, source = [], SOURCE_YAHOO
        try:
            bars = [{"time": t * 1000, "close": c} for t, c in await yahoo_daily("%5EKS200", start, end, timeout=10.0)]
        except _YAHOO_ERRORS:
            bars = []
        latest = datetime.fromtimestamp(bars[-1]["time"] / 1000, tz=KST).date() if bars else None
        if len(bars) < 2 or latest is None or (end - latest).days > 8:
            # 야후가 ^KS200 을 하루치만 주거나 일찍 끊기는 일이 있다 — 통합본처럼 네이버 지수 이력으로 메운다
            naver = await _naver_kospi200(start, end)
            if len(naver) > len(bars):
                bars, source = naver, SOURCE_NAVER
                warnings.append("기본 데이터 제공처의 이력이 부족해 대체 데이터로 표시했습니다.")
    if not bars:
        raise MarketDataError("표시할 KOSPI 200 지수 데이터가 없습니다.")
    bars.sort(key=lambda b: b["time"])
    if len(bars) < 2:
        warnings.append("조회된 거래일이 1일뿐이어서 추이 차트를 표시할 수 없습니다.")
    latest_date = datetime.fromtimestamp(bars[-1]["time"] / 1000, tz=KST).date().isoformat()
    return _cache_put("kospi200", key, {
        "symbol": "^KS200", "start": start.isoformat(), "end": end.isoformat(), "bars": bars,
        "bar_count": len(bars), "latest_date": latest_date, "source": source, "warnings": warnings, "updated_at": _now(),
    })


async def _naver_kospi200(start: date, end: date) -> list[dict[str, Any]]:
    url = ("https://api.finance.naver.com/siseJson.naver"
           f"?symbol=KPI200&requestType=1&startTime={_ymd(start)}&endTime={_ymd(end - timedelta(days=1))}&timeframe=day")
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=HEADERS)
            resp.raise_for_status()
        resp.encoding = "utf-8"
        rows = ast.literal_eval(resp.text.strip())
    except (httpx.HTTPError, SyntaxError, ValueError, TypeError):
        return []
    out = []
    for row in rows[1:]:
        if not isinstance(row, list) or len(row) < 5:
            continue
        try:
            d = datetime.strptime(str(row[0]), "%Y%m%d").date()
            close = float(row[4])
        except (TypeError, ValueError):
            continue
        if start <= d < end and isfinite(close):
            out.append({"time": int(datetime.combine(d, datetime.min.time(), tzinfo=KST).timestamp() * 1000), "close": close})
    return out


async def central_bank_event_history(bank: str, meeting_date: date, window: int) -> dict[str, Any]:
    """정책금리 결정일 전후의 그 나라 대표 지수 — 회의 전후 수익률 · 변동성은 화면이 계산한다(02일차)."""
    if meeting_date > datetime.now(KST).date():
        raise MarketDataError("과거 회의일만 조회할 수 있습니다.", 400)
    bench = CENTRAL_BANK_BENCHMARKS[bank]
    pad = window * 2 + 5
    start, end = meeting_date - timedelta(days=pad), meeting_date + timedelta(days=pad + 1)
    key = f"central-bank:{bank}:{meeting_date}:{window}"
    if (hit := _cache_get("rate", key)) is not None:
        return hit
    rows = collector_index("코스피", start, end) if bank == "bok" else None
    if rows:
        bars, source = [{"date": _day(d).isoformat(), "close": round(c, 4)} for d, c in rows], SOURCE_COLLECTOR
    else:
        try:
            pairs = await yahoo_daily(bench["symbol"], start, end, tz=timezone.utc)
        except _YAHOO_ERRORS as exc:
            raise MarketDataError("회의 전후 주가지수 시세를 불러오지 못했습니다.") from exc
        bars = [{"date": datetime.fromtimestamp(t, tz=timezone.utc).date().isoformat(), "close": round(c, 4)} for t, c in pairs]
        source = SOURCE_YAHOO
    if len(bars) < window * 2 + 1:
        raise MarketDataError("변동성 계산에 필요한 거래일 시세가 부족합니다.")
    return _cache_put("rate", key, {
        "bank": bank, "meeting_date": meeting_date.isoformat(), "window": window,
        "benchmark": {"symbol": bench["symbol"].replace("%5E", "^"), "name": bench["name"],
                      "timezone": bench["timezone"], "bars": bars},
        "source": source, "updated_at": _now(),
    })


async def intraday(ticker: str, market: str) -> dict[str, Any]:
    """오늘의 1분봉 — 무료로 받을 수 있는 가장 잘게 쪼갠 봉이다(체결 하나하나는 유료 시세 · 증권사 API 가 필요하다)."""
    key = f"{ticker}:{market}"
    if (hit := _cache_get("intraday", key)) is not None:
        return hit
    symbol = f"{ticker}.{'KS' if market == 'KOSPI' else 'KQ'}"
    bars: list[dict[str, Any]] = []
    meta_out: dict[str, Any] = {}
    error: str | None = None
    try:
        async with httpx.AsyncClient(timeout=6.0, follow_redirects=True) as client:
            resp = await client.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1d&interval=1m", headers=HEADERS)
            resp.raise_for_status()
        result = resp.json()["chart"]["result"][0]
        meta = result["meta"]
        quote = result["indicators"]["quote"][0]
        cols = [quote.get(k) or [] for k in ("open", "high", "low", "close", "volume")]
        for i, ts in enumerate(result.get("timestamp") or []):
            o, h, lo, c = (col[i] if i < len(col) else None for col in cols[:4])
            if None in (o, h, lo, c):
                continue
            v = cols[4][i] if i < len(cols[4]) and cols[4][i] is not None else 0
            bars.append({"time": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                         "open": o, "high": h, "low": lo, "close": c, "volume": v})
        meta_out = {
            "price": meta.get("regularMarketPrice"),
            "previous_close": meta.get("chartPreviousClose") or meta.get("previousClose"),
            "currency": meta.get("currency", "KRW"),
            "market_state": meta.get("marketState"),
            "exchange_name": meta.get("exchangeName"),
        }
        if not bars:
            error = "장중이 아니거나 표시할 분봉 데이터가 없습니다."
    except _YAHOO_ERRORS:
        error = "분봉 데이터를 불러오지 못했습니다."
    return _cache_put("intraday", key, {"ticker": ticker, "symbol": symbol, "market": market, "bars": bars,
                                        "meta": meta_out, "updated_at": _now(), "error": error})


def _ticker_rows(ticker: str) -> list[tuple[str, float]] | None:
    """종목이면 수정주가(분할을 폭락으로 읽지 않게), ETF 면 종가 — 전 기간. 없으면 None."""
    rows = _query("SELECT bas_dt, adj_clpr FROM price_adjusted WHERE srtn_cd=? ORDER BY bas_dt", (ticker,))
    if not rows:
        rows = _query("SELECT bas_dt, clpr FROM etf_daily WHERE srtn_cd=? ORDER BY bas_dt", (ticker,))
    if rows is None:
        return None
    return [(d, float(c)) for d, c in rows if c is not None]


def period_return(ticker: str, start: date, end: date) -> dict[str, Any]:
    """사용자가 고른 기간의 종가 대 종가 수익률 — ETF 탐색표의 「기간 수익률」 칸(02일차)."""
    if start >= end:
        raise MarketDataError("시작일은 종료일보다 앞서야 합니다.", 400)
    base = {"ticker": ticker, "start": start.isoformat(), "end": end.isoformat()}
    rows = _ticker_rows(ticker)
    if not rows:
        return {"available": False, "reason": "no_data", **base}
    earliest = _day(rows[0][0])
    # 고른 시작일이 가진 자료보다 한 주 넘게 앞서면 수익률을 내지 않는다. 통합본은 이때 가진 첫날부터 계산해
    # (예: 2019년부터를 골랐는데 2020-01-02 부터의 수익률) 기간과 다른 숫자를 아무 표시 없이 보여 줬다.
    if (earliest - start).days > 7:
        return {"available": False, "reason": "needs_older_history", "earliest_stored_date": earliest.isoformat(), **base}
    inside = [(d, c) for d, c in rows if start <= _day(d) <= end]
    if len(inside) < 2:
        return {"available": False, "reason": "insufficient_bars", "earliest_stored_date": earliest.isoformat(), **base}
    (d0, c0), (d1, c1) = inside[0], inside[-1]
    return {"available": True, "ticker": ticker, "start_date": _day(d0).isoformat(), "end_date": _day(d1).isoformat(),
            "start_close": c0, "end_close": c1, "return_pct": round((c1 / c0 - 1) * 100, 2), "bar_count": len(inside)}


# ── 강의 3일차의 국채 사료 그림 (e뮤지엄) ────────────────────────────
HISTORIC_BOND_DETAIL_URL = "https://www.emuseum.go.kr/detail?relicId=PS0100202500100758500000"
_bond_image: tuple[datetime, bytes, str] | None = None


async def historic_bond_image() -> tuple[bytes, str]:
    """1961년 「대한민국정부 건국국채증서 일백환」 그림 — 국립중앙박물관 e뮤지엄의 공개 사료.

    e뮤지엄은 그림 주소를 상세 페이지를 거친 요청(같은 세션 · Referer)에만 내준다. 브라우저가 바로 부르면
    막히므로 서버가 상세 페이지 → 그림 순서로 받아 그대로 건넨다(통합본과 같은 방식). 바꾸지 않고, 하루 동안
    메모리에만 둔다 — 파일 · DB 에 저장하지 않는다.
    """
    global _bond_image
    now = datetime.now(timezone.utc)
    if _bond_image and now - _bond_image[0] < timedelta(days=1):
        return _bond_image[1], _bond_image[2]
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, headers=HEADERS) as client:
            detail = await client.get(HISTORIC_BOND_DETAIL_URL)
            detail.raise_for_status()
            m = re.search(r'<img src="(?P<path>/IMG/[^"]+)" alt="대한민국정부 건국국채증서 일백환', detail.text)
            if not m:
                raise MarketDataError("국채 사료 그림의 주소를 상세 페이지에서 찾지 못했습니다.")
            image = await client.get(f"https://www.emuseum.go.kr{m.group('path')}", headers={"Referer": HISTORIC_BOND_DETAIL_URL})
            image.raise_for_status()
    except httpx.HTTPError as exc:
        raise MarketDataError("국채 사료 그림을 불러오지 못했습니다.") from exc
    media = image.headers.get("Content-Type", "image/jpeg").split(";")[0]
    _bond_image = (now, image.content, media)
    return image.content, media


def extend_period_history(ticker: str, start: date) -> dict[str, Any]:
    """통합본은 여기서 야후 이력을 받아 표에 넣었다 — 우리는 넣지 않고 수집 DB 의 가장 이른 날짜만 돌려준다.

    화면은 `earliest_date` 가 앞서 받은 날짜와 같으면 「더 앞선 자료 없음」 으로 바꿔 단추를 다시 내지 않는다.
    """
    rows = _ticker_rows(ticker) or []
    earliest = _day(rows[0][0]).isoformat() if rows else None
    return {"ticker": ticker, "market": None, "fetched_bars": 0, "earliest_date": earliest,
            "note": "수집 DB 가 2020-01-02 부터의 거래일을 이미 갖고 있어 더 불러오지 않습니다.", "updated_at": _now()}
