"""DF-08 다리 시험 — 국내 주식 일봉을 수집 DB 에서 읽는가 (옛 `#61` P1-1).

무엇이 틀렸었나 —
수집기가 2020-01-02 부터 전 종목 일봉 446만 행을 모았는데, 차트 · 지표 · 백테스트 · ML 이 부르는
`stock.get_candles` 는 그 DB 를 한 번도 읽지 않고 외부 차트 API 를 불렀다(ERD v1.0 §1).
팀이 약관 근거로 배제한 출처라, 그 위에서 낸 숫자는 우리 성과로 내기 어렵다.

여기서 지키는 것 —
1. **골든 픽스처**: 카카오 5:1 분할(2021-04-15) 전후 12봉이 정답지와 한 자리도 다르지 않다.
   정답지는 수정주가 표가 아니라 **원래 값 × 계수**로 따로 만들었다(픽스처 파일 `_기대값을_만든_방법`).
2. 수정주가로 낸 하루 수익률이 **거래소가 준 등락률**(`flt_rt`)과 같다 — 분할 날도.
   어댑터 밖의 숫자로 어댑터를 재는 시험이다.
3. 쓸 수 없으면 **None** — 예외를 올리지 않고 옛 경로로 넘긴다(지수 · 환율 · 해외 · ETF · 일봉 아님).
4. `get_candles` 는 국내 주식 일봉이면 **외부 차트를 부르지 않는다** ← 옛 코드에서 실패하는 시험.

네트워크는 쓰지 않는다. 마지막 통합 시험만 실제 수집 DB 를 읽고, 파일이 없으면 건너뛴다.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services import collector_db, stock
from collector.db import SCHEMA  # 수집기의 실제 스키마 — 픽스처 DB 가 실제와 같은 모양이게

FIXTURE = Path(__file__).parent / "fixtures" / "collector_golden_035720.json"
GOLDEN = json.loads(FIXTURE.read_text(encoding="utf-8"))
REQ = GOLDEN["요청"]
TODAY = date.fromisoformat(REQ["today"])
REAL_DB = Path(__file__).resolve().parents[1] / "data" / "collector" / "market.sqlite3"


@pytest.fixture
def golden_db(tmp_path, monkeypatch) -> Path:
    """골든 픽스처 행으로 수집 DB 를 만들고, 어댑터가 그 파일을 보게 한다."""
    p = tmp_path / "market.sqlite3"
    conn = sqlite3.connect(p)
    conn.executescript(SCHEMA)
    for table in ("price_daily", "price_adjusted"):
        rows = GOLDEN[table]
        cols = list(rows[0])
        conn.executemany(
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
            [tuple(r[c] for c in cols) for r in rows],
        )
    conn.commit()
    conn.close()
    monkeypatch.setenv(collector_db.ENV_DB_PATH, str(p))
    return p


def _read(symbol=REQ["symbol"], period=REQ["period"], interval=REQ["interval"], today=TODAY):
    return collector_db.read_daily_candles(symbol, period, interval, today=today)


def _daily(srtn_cd: str = "035720") -> dict[str, dict]:
    return {r["bas_dt"]: r for r in GOLDEN["price_daily"] if r["srtn_cd"] == srtn_cd}


def _bas_dt(candle: dict) -> str:
    return datetime.fromtimestamp(candle["time"], tz=timezone.utc).strftime("%Y%m%d")


# ── 1. 골든 픽스처 ───────────────────────────────────────────────────────
def test_golden_candles_match_exactly(golden_db):
    out = _read()
    assert out is not None
    assert out["candles"] == GOLDEN["기대_candles"]
    assert out["as_of"] == GOLDEN["기대_as_of"]
    assert out["source"] == "collector"
    # 옛 경로와 같은 머리 칸 — get_candles 를 부르는 14곳(2026-09-28 실측)이 이 모양에 기대고 있다.
    assert {k: out[k] for k in ("symbol", "interval", "period")} == {
        "symbol": REQ["symbol"], "interval": REQ["interval"], "period": REQ["period"],
    }


def test_split_day_is_continuous_not_a_crash(golden_db):
    """분할 전날 558,000 → 분할 날 120,500 은 −78% 가 아니라 +7.59% 다."""
    by_day = {_bas_dt(c): c for c in _read()["candles"]}
    assert by_day["20210409"]["close"] == 112_000.0      # 558,000 × 0.2007(= 112,000 / 558,000)
    assert by_day["20210415"]["close"] == 120_500.0      # 분할 뒤 첫날 — 계수 1
    ret = by_day["20210415"]["close"] / by_day["20210414"]["close"] - 1
    assert ret == pytest.approx(0.0759, abs=0.0001)


# ── 2. 어댑터 밖의 숫자로 재기 ───────────────────────────────────────────
def test_adjusted_returns_equal_exchange_change_rate(golden_db):
    """수정 종가의 하루 수익률 = 거래소 등락률(flt_rt, 소수 둘째 자리). 분할 날 · 정지 날 포함."""
    candles = _read()["candles"]
    daily = _daily()
    for prev, cur in zip(candles, candles[1:]):
        ret_pct = (cur["close"] / prev["close"] - 1) * 100
        assert abs(ret_pct - daily[_bas_dt(cur)]["flt_rt"]) <= 0.006, _bas_dt(cur)


def test_no_trade_day_is_flat_with_zero_volume(golden_db):
    by_day = {_bas_dt(c): c for c in _read()["candles"]}
    for d in ("20210412", "20210413", "20210414"):   # 분할 거래정지 3일
        c = by_day[d]
        assert c["open"] == c["high"] == c["low"] == c["close"] == 112_000.0, d
        assert c["volume"] == 0, d


def test_volume_is_rescaled_to_post_split_shares(golden_db):
    by_day = {_bas_dt(c): c for c in _read()["candles"]}
    # 원래 788,839주 ÷ 0.2007 ≈ 3,930,109주 — 분할 뒤 주식 수 기준
    assert by_day["20210409"]["volume"] == 3_930_109
    assert by_day["20210415"]["volume"] == 17_115_015   # 계수 1 — 원래 값 그대로


def test_time_is_midnight_utc_which_is_market_open_kst(golden_db):
    by_day = {_bas_dt(c): c for c in _read()["candles"]}
    t = by_day["20210415"]["time"]
    assert t == 1_618_444_800
    assert datetime.fromtimestamp(t, tz=timezone(timedelta(hours=9))).hour == 9


# ── 3. 범위 · 거름 ──────────────────────────────────────────────────────
def test_period_window_cuts_older_rows(golden_db):
    assert len(_read(period="1mo")["candles"]) == 12            # 03-20 이후 — 03-02 는 잘린다
    assert len(_read(period="3mo")["candles"]) == 13            # 01-20 이후 — 03-02 가 들어온다
    assert len(_read(period="max")["candles"]) == 13


def test_other_symbols_do_not_leak(golden_db):
    out = _read(symbol="000660.KS")
    assert [_bas_dt(c) for c in out["candles"]] == ["20210415"]
    assert _read(symbol="035720.KQ")["candles"] == _read()["candles"]   # 시장 표기는 보지 않는다


@pytest.mark.parametrize("symbol,period,interval", [
    ("^KS11", "1y", "1d"),        # 지수 — 이 DB 에 없다
    ("KRW=X", "1y", "1d"),        # 환율
    ("AAPL", "1y", "1d"),         # 해외
    ("005930", "1y", "1d"),       # 시장 표기 없음 — 옛 경로의 기호 규칙이 아니다
    ("035720.KS", "1y", "1wk"),   # 주봉 — 일봉만 다룬다
    ("035720.KS", "5m", "1d"),    # 모르는 기간
    ("035720.KS", "", "1d"),
    ("999999.KS", "max", "1d"),   # DB 에 없는 종목(ETF 도 여기 해당)
])
def test_not_applicable_returns_none(golden_db, symbol, period, interval):
    assert _read(symbol=symbol, period=period, interval=interval) is None


def test_missing_or_broken_db_returns_none_without_raising(tmp_path, monkeypatch):
    monkeypatch.setenv(collector_db.ENV_DB_PATH, str(tmp_path / "없음.sqlite3"))
    assert _read() is None
    broken = tmp_path / "broken.sqlite3"
    broken.write_bytes(b"not a sqlite file" * 100)
    monkeypatch.setenv(collector_db.ENV_DB_PATH, str(broken))
    assert _read() is None


def test_reading_does_not_change_the_db(golden_db):
    before = hashlib.sha256(golden_db.read_bytes()).hexdigest()
    _read(period="max")
    assert hashlib.sha256(golden_db.read_bytes()).hexdigest() == before


# ── 4. 계약 — get_candles 가 다리를 건너는가 ─────────────────────────────
def _stub_old_path(monkeypatch) -> dict:
    """옛 경로(외부 차트 · 캐시)를 대역으로 바꾸고, 불린 기록을 돌려준다."""
    calls: dict[str, list] = {"chart": [], "cache_get": [], "cache_set": []}

    async def fake_chart(symbol, interval, range_):
        calls["chart"].append((symbol, interval, range_))
        return None

    async def fake_cache_get(key, max_age_hours=24):
        calls["cache_get"].append(key)
        return None

    async def fake_cache_set(key, value):
        calls["cache_set"].append(key)

    monkeypatch.setattr(stock, "_yahoo_chart", fake_chart)
    monkeypatch.setattr(stock, "cache_get", fake_cache_get)
    monkeypatch.setattr(stock, "cache_set", fake_cache_set)
    return calls


def test_get_candles_reads_collector_db_for_krx_daily(golden_db, monkeypatch):
    """옛 코드에서는 실패한다 — 외부 차트를 불러 빈 캔들을 돌려줬다."""
    calls = _stub_old_path(monkeypatch)
    out = asyncio.run(stock.get_candles("035720.KS", period="max", interval="1d"))
    assert out.get("source") == "collector"
    assert len(out["candles"]) == 13
    assert calls["chart"] == []          # 외부 차트를 부르지 않는다
    assert calls["cache_get"] == []      # 파일 읽기가 캐시 조회보다 싸다 · 12:30 갱신이 바로 보인다


def test_get_candles_falls_back_for_index(golden_db, monkeypatch):
    calls = _stub_old_path(monkeypatch)
    out = asyncio.run(stock.get_candles("^KS11", period="1y", interval="1d"))
    assert calls["chart"] == [("^KS11", "1d", "1y")]
    assert out == {"symbol": "^KS11", "candles": []}      # 옛 경로의 '없음' 모양 그대로


def test_indicators_carry_as_of(monkeypatch):
    """지표 화면의 '현재가'는 마지막 봉 종가다 — 기준일이 함께 가야 오늘 값으로 오해하지 않는다."""
    base = datetime(2026, 8, 3, tzinfo=timezone.utc)
    candles = [{"time": int((base + timedelta(days=i)).timestamp()), "open": 100 + i, "high": 101 + i,
                "low": 99 + i, "close": 100 + i, "volume": 1000} for i in range(30)]

    async def fake_get_candles(symbol, period="1y", interval="1d"):
        return {"symbol": symbol, "interval": interval, "period": period, "candles": candles,
                "source": "collector", "as_of": "2026-09-01"}

    monkeypatch.setattr(stock, "get_candles", fake_get_candles)
    out = asyncio.run(stock.get_quant_indicators("035720.KS", period="2y"))
    assert out["as_of"] == "2026-09-01"
    assert out["source"] == "collector"


# ── 5. 통합 — 실제 수집 DB ───────────────────────────────────────────────
@pytest.mark.skipif(not REAL_DB.is_file(), reason="수집 DB 가 없다(데이터 파트 밖의 환경)")
def test_real_db_universe_is_served_and_consistent():
    """스크리닝 유니버스 31종목 전부가 수집 DB 에서 나오고, 전 기간 수익률이 거래소 등락률과 맞는다.

    ⚠️ 등락률 대조의 사각지대 — 등락률(`flt_rt`)도 수정주가도 **같은 포털 값**(`vs`)에서 나온다.
    포털이 기준가를 조정하지 않은 사건(장기 거래정지 뒤 감자 · 병합)은 둘이 **함께 틀려서** 대조를
    통과한다. 2026-09-28 실측으로 전 종목에 2곳 — 052670 제일바이오(2026-02-09, 1,500:1 · DF-01) ·
    086460 큐러블(2025-08-07, 20:1). 그래서 **주식 수가 1/5 아래로 줄었는데 조정 이벤트가 없는 날**을
    따로 본다. 유니버스에 그런 날이 생기면 여기서 멈춘다.
    """
    conn = sqlite3.connect(f"{REAL_DB.resolve().as_uri()}?mode=ro", uri=True)
    try:
        codes = [s["symbol"][:6] for s in stock.QUANT_STOCKS]
        collapsed = conn.execute(f"""
            WITH s AS (SELECT srtn_cd, bas_dt, lstg_st_cnt AS n,
                              LAG(lstg_st_cnt) OVER (PARTITION BY srtn_cd ORDER BY bas_dt) AS pn
                         FROM price_daily WHERE srtn_cd IN ({', '.join('?' * len(codes))}))
            SELECT s.srtn_cd, s.bas_dt FROM s LEFT JOIN corporate_action AS ca USING (srtn_cd, bas_dt)
             WHERE s.pn > 0 AND s.n > 0 AND s.n * 5 < s.pn AND ca.srtn_cd IS NULL""", codes).fetchall()
        assert collapsed == [], f"조정이 빠진 감자·병합 후보(DF-01 유형): {collapsed}"

        for s in stock.QUANT_STOCKS:
            out = collector_db.read_daily_candles(s["symbol"], "max", "1d", path=REAL_DB)
            assert out is not None and len(out["candles"]) > 200, s["symbol"]
            code = s["symbol"][:6]
            rows = dict(conn.execute(
                "SELECT bas_dt, flt_rt FROM price_daily WHERE srtn_cd = ?", (code,)).fetchall())
            last = conn.execute(
                "SELECT clpr FROM price_daily WHERE srtn_cd = ? AND bas_dt = ?",
                (code, out["as_of"].replace("-", ""))).fetchone()
            # 가장 최근 날은 계수 1 — 마지막 봉은 원래 종가와 같다.
            assert out["candles"][-1]["close"] == float(last[0]), s["symbol"]
            c = out["candles"]
            for prev, cur in zip(c, c[1:]):
                ret_pct = (cur["close"] / prev["close"] - 1) * 100
                assert abs(ret_pct - rows[_bas_dt(cur)]) <= 0.006, (s["symbol"], _bas_dt(cur))
    finally:
        conn.close()
