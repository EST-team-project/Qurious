"""TC-OH — OHLCV 공통 규격 ``ohlcv-v1`` · 주봉 · 시간대 · ETF/지수 · 분봉 · 유니버스 · 내보내기.

설계서 8절 TC-OH(「값 규칙 · 주봉 만들기(주 중간 분할) · 분봉 시각(UTC → KST) · 키 중복」)에
2026-10-01 실측으로 더한 것 — 수정 방식 칸(price_basis) · 장 구간(session) · 같은 이름 지수 · KRX 구성종목 파일.

네트워크는 쓰지 않는다(야후 · 포털 응답은 손으로 만든 표 · JSON). 실제 수집 DB 도 열지 않는다.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

import pandas as pd
import pytest

from collector import ohlcv as oh
from collector.db import SCHEMA


def _bar(sym="035720", d="2021-04-16", o=115500, h=120500, l=115500, c=119000, v=13709555, **kw):
    row = {"symbol": sym, "market": "KOSPI", "timeframe": "1d", "trade_date": d, "bar_start": None,
           "open": o, "high": h, "low": l, "close": c, "volume": v, "adjusted": False, "price_basis": "raw",
           "source": "test", "contract": oh.CONTRACT}
    row.update(kw)
    return row


def _df(rows):
    return oh.finalize(pd.DataFrame(rows), source="test")


# ── 1. 값 규칙 ──────────────────────────────────────────────────────────

def test_clean_bars_and_flat_halted_bar_pass():
    """TC-OH-01 · 정상 봉과 거래정지일의 평평한 봉(시가=고가=저가=종가 · 거래량 0)은 위반이 아니다."""
    r = oh.check(_df([_bar(), _bar(d="2021-04-14", o=558000, h=558000, l=558000, c=558000, v=0)]))
    assert r["ok"] and r["problems"] == {}


@pytest.mark.parametrize("change, rule", [
    ({"open": 0}, "price_nonpositive"),
    ({"low": 120000}, "ohlc_order"),                 # 저가가 시가보다 높다
    ({"high": 118000}, "ohlc_order"),                # 고가가 종가보다 낮다
    ({"volume": -5}, "volume_negative"),
    ({"timeframe": "1h"}, "bad_timeframe"),
    ({"market": "NASDAQ"}, "bad_market"),
    ({"price_basis": "adjusted"}, "bad_basis"),
])
def test_each_value_rule_is_caught(change, rule):
    """TC-OH-02 · 값 규칙마다 위반을 정확히 그 규칙 이름으로 잡는다."""
    r = oh.check(_df([_bar(**change)]))
    assert rule in r["problems"] and not r["ok"]


def test_duplicate_key_and_trading_calendar():
    """TC-OH-03 · 같은 키 두 줄 · 거래일 달력 밖 날짜(휴장 금요일 2025-10-03)를 잡는다.
    수정 방식이 다르면 같은 날이라도 다른 계열이라 중복이 아니다."""
    rows = [_bar(), _bar(c=119500, h=121000), _bar(price_basis="adj_base", adjusted=True)]
    assert oh.check(_df(rows))["problems"]["duplicate_key"] == 2
    r = oh.check(_df([_bar(d="2025-10-03")]), calendar=["2025-10-02", "2025-10-10"])
    assert r["problems"] == {"not_trading_day": 1}


def test_missing_required_column_stops_early():
    """TC-OH-04 · 필수 칸이 없으면 다른 검사를 하지 않고 그 칸 이름을 돌려준다."""
    r = oh.check(pd.DataFrame([{"symbol": "005930", "close": 1}]))
    assert r["problems"]["missing_column"] >= 5 and {"column": "open"} in r["examples"]["missing_column"]


def test_intraday_bar_start_rules():
    """TC-OH-05 · 분봉은 봉 시각이 있어야 하고, 시간대가 붙어야 하며, KST 날짜가 거래일과 같아야 한다."""
    good = _bar(timeframe="5m", trade_date="2026-09-30", bar_start="2026-09-30T09:00:00+09:00")
    naive = _bar(timeframe="5m", trade_date="2026-09-30", bar_start="2026-09-30T09:05:00")
    utc_day = _bar(timeframe="5m", trade_date="2026-09-29", bar_start="2026-09-29T23:40:00+00:00")  # KST 09-30 08:40
    missing = _bar(timeframe="60m", trade_date="2026-09-30", bar_start=None)
    r = oh.check(_df([good, naive, utc_day, missing]))
    assert r["problems"] == {"bar_start_missing": 1, "bar_start_naive": 1, "bar_date_mismatch": 1}
    assert r["sessions"] == {"regular": 1, "pre_open": 1}


# ── 2. 시간대 · 장 구간 ─────────────────────────────────────────────────

@pytest.mark.parametrize("utc, kst, session", [
    ("2026-09-30T00:00:00Z", "2026-09-30 09:00", "regular"),
    ("2026-09-30T05:55:00Z", "2026-09-30 14:55", "regular"),
    ("2026-09-30T06:20:00Z", "2026-09-30 15:20", "close_auction"),
    ("2026-09-30T06:30:00Z", "2026-09-30 15:30", "outside"),
    ("2026-09-29T23:40:00Z", "2026-09-30 08:40", "pre_open"),
])
def test_utc_to_kst_and_session(utc, kst, session):
    """TC-OH-06 · UTC → KST(+9) · 장 구간 — 개념 학습 1.3 장 ① 의 표와 같다."""
    k = oh.to_kst(utc)
    assert k.strftime("%Y-%m-%d %H:%M") == kst and oh.session_of(k) == session


def test_naive_time_is_refused():
    """TC-OH-07 · 시간대 표시가 없는 시각은 받지 않는다 — UTC 였던 값에 KST 를 붙이면 9시간 이른 봉이 된다."""
    with pytest.raises(ValueError):
        oh.to_kst(datetime(2026, 9, 30, 0, 0))


# ── 3. 주봉 ─────────────────────────────────────────────────────────────

KAKAO = [  # 원자료 그대로 — 2021-04-12~14 거래정지(시가 · 고가 · 저가 0), 04-15 액면분할 5:1
    ("2021-04-05", 503000, 505000, 500000, 502000, 310400), ("2021-04-06", 506000, 545000, 505000, 544000, 1724958),
    ("2021-04-07", 544000, 544000, 526000, 542000, 820896), ("2021-04-08", 539000, 561000, 534000, 548000, 912514),
    ("2021-04-09", 554000, 561000, 551000, 558000, 788839), ("2021-04-12", 0, 0, 0, 558000, 0),
    ("2021-04-13", 0, 0, 0, 558000, 0), ("2021-04-14", 0, 0, 0, 558000, 0),
    ("2021-04-15", 120500, 132500, 118000, 120500, 17115015), ("2021-04-16", 115500, 120500, 115500, 119000, 13709555),
]
FACTOR = 112000 / 558000


def _kakao(adjusted=False):
    rows = []
    for d, o, h, l, c, v in KAKAO:
        f = FACTOR if (adjusted and d < "2021-04-15") else 1.0
        if o == 0:                                     # 평평한 봉(ohlcv-v1 일봉은 0 을 담지 않는다)
            o = h = l = c
        rows.append(_bar(d=d, o=o * f, h=h * f, l=l * f, c=c * f, v=v,
                         price_basis="adj_base" if adjusted else "raw", adjusted=adjusted))
    return _df(rows)


def test_weekly_uses_traded_days_only_for_range():
    """TC-OH-08 · 정지일의 평평한 봉(558,000)은 그 주의 고가 · 저가 · 시가가 되지 않는다(1.1 장 ③)."""
    w = oh.weekly(_kakao())
    second = w[w["trade_date"] == "2021-04-16"].iloc[0]
    assert (second["open"], second["high"], second["low"], second["close"]) == (120500, 132500, 115500, 119000)
    assert second["volume"] == 17115015 + 13709555 and second["timeframe"] == "1w"


def test_weekly_date_is_last_trading_day_not_friday():
    """TC-OH-09 · 휴장 금요일(2025-10-03)이 낀 주의 주봉 날짜는 목요일 10-02 다 — pandas W-FRI 는 10-03 을 붙인다."""
    days = [("2025-09-29", 83300, 85000, 83200, 84200), ("2025-09-30", 84600, 84900, 83400, 83900),
            ("2025-10-01", 84900, 86200, 84700, 86000), ("2025-10-02", 89300, 90300, 88700, 89000)]
    w = oh.weekly(_df([_bar(sym="005930", d=d, o=o, h=h, l=l, c=c, v=1) for d, o, h, l, c in days]))
    assert w["trade_date"].tolist() == ["2025-10-02"]
    assert (w.iloc[0]["open"], w.iloc[0]["high"], w.iloc[0]["low"], w.iloc[0]["close"]) == (83300, 90300, 83200, 89000)


def test_weekly_from_adjusted_daily_fixes_mid_week_break():
    """TC-OH-10 · 수정 주봉 = 수정 일봉을 묶은 것. 가온전선 2026-06-30(화) 권리락 주 — 원 주봉은 고가 353,500 ·
    주간 −15.7%, 수정 일봉을 묶으면 고가 326,000 · +51.8% (1.2 장 ③)."""
    f = 0.5556851311953352
    rows = [("2026-06-26", 308000, 343500, 283000, 329000), ("2026-06-29", 329500, 353500, 320500, 343000),
            ("2026-06-30", 240000, 244000, 210500, 233500), ("2026-07-01", 262000, 303500, 257000, 300500),
            ("2026-07-02", 273000, 326000, 270000, 280000), ("2026-07-03", 311500, 313500, 261500, 277500)]
    raw = oh.weekly(_df([_bar(sym="000500", d=d, o=o, h=h, l=l, c=c, v=1) for d, o, h, l, c in rows]))
    adj = oh.weekly(_df([_bar(sym="000500", d=d, price_basis="adj_base", adjusted=True,
                              **dict(zip("ohlc", [x * (f if d < "2026-06-30" else 1) for x in (o, h, l, c)])), v=1)
                         for d, o, h, l, c in rows]))
    assert raw.iloc[1]["high"] == 353500 and round(raw.iloc[1]["close"] / raw.iloc[0]["close"] - 1, 3) == -0.157
    assert adj.iloc[1]["high"] == 326000 and round(adj.iloc[1]["low"]) == 178097
    assert round(adj.iloc[1]["close"] / adj.iloc[0]["close"] - 1, 3) == 0.518


def test_weekly_marks_running_week_partial():
    """TC-OH-11 · 기준일이 그 주 금요일 전이면 진행 중인 주로 표시한다(매니페스트 partial_weeks)."""
    w = oh.weekly(_kakao(), as_of="2021-04-15")
    assert w.set_index("trade_date")["partial"].to_dict() == {"2021-04-09": False, "2021-04-16": True}


# ── 4. 분봉 정규화 · 유니버스 · KRX 구성종목 파일 ───────────────────────

def test_yahoo_frame_normalized_to_kst_rows():
    """TC-OH-12 · 야후 표(UTC) → 봉 시작 시각 KST(+09:00) · 거래일 · 장 구간 · 수정 방식 adj_split. 빈 봉은 버린다."""
    from collector.sources import yahoo_intraday as yi
    idx = pd.DatetimeIndex(["2026-09-30 00:00", "2026-09-30 05:55", "2026-09-30 06:00"], tz="UTC")
    fr = pd.DataFrame({"Open": [1.0, 2.0, float("nan")], "High": [1.5, 2.5, None], "Low": [0.5, 1.5, None],
                       "Close": [1.2, 2.2, None], "Volume": [0, 10, None]}, index=idx)
    rows = yi.normalize(fr, "005930", "5m", "2026-10-01T12:25:00+09:00")
    assert [r["bar_start"] for r in rows] == ["2026-09-30T09:00:00+09:00", "2026-09-30T14:55:00+09:00"]
    assert {r["price_basis"] for r in rows} == {"adj_split"} and rows[0]["session"] == "regular"
    with pytest.raises(ValueError):
        yi.normalize(fr.tz_localize(None), "005930", "5m", "x")


def _db(tmp_path):
    conn = sqlite3.connect(tmp_path / "m.sqlite3")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def test_universe_excludes_preferred_spac_and_halted(tmp_path):
    """TC-OH-13 · 시가총액 근사 명단은 우선주(코드 끝자리 ≠ 0) · 스팩 · 그날 정지 종목을 빼고, ETF 는 거래대금 순."""
    from collector.sources import yahoo_intraday as yi
    conn = _db(tmp_path)
    pd_rows = [("005930", "삼성전자", 900, 0), ("005935", "삼성전자우", 800, 0), ("123450", "하나스팩", 700, 0),
               ("111110", "정지주", 600, 1), ("000660", "SK하이닉스", 500, 0)]
    conn.executemany("INSERT INTO price_daily (bas_dt,srtn_cd,itms_nm,mrkt_ctg,clpr,mrkt_tot_amt,halted) "
                     "VALUES ('20260930',?,?,'KOSPI',1,?,?)", [(c, n, m, h) for c, n, m, h in pd_rows])
    conn.executemany("INSERT INTO etf_daily (bas_dt,srtn_cd,itms_nm,clpr,tr_prc,halted) VALUES ('20260930',?,?,1,?,0)",
                     [("069500", "KODEX 200", 50), ("122630", "KODEX 레버리지", 70)])
    u = yi.build_universe(conn, "20260930", {"KOSPI": 10, "KOSDAQ": 10, "ETF": 1})
    assert [(m["market"], m["symbol"]) for m in u] == [("KOSPI", "005930"), ("KOSPI", "000660"), ("ETF", "122630")]
    assert "근사" in u[0]["reason"]


@pytest.mark.parametrize("enc", ["cp949", "utf-8-sig"])
def test_krx_constituent_csv_read_by_column_name(tmp_path, enc):
    """TC-OH-14 · KRX 「지수구성종목」 CSV(사람이 받은 것)는 EUC-KR · UTF-8 어느 쪽이든 「종목코드」 · 「종목명」 칸 이름으로
    읽는다 — 칸 순서가 바뀌어도 · 앞자리 0 이 빠져도."""
    from collector.sources import yahoo_intraday as yi
    p = tmp_path / "kospi200.csv"
    p.write_bytes('"종목명","종가","종목코드"\n"삼성전자","271000","005930"\n"SK하이닉스","1","660"\n'.encode(enc))
    assert yi.read_krx_constituents(p) == [{"symbol": "005930", "itms_nm": "삼성전자"},
                                           {"symbol": "000660", "itms_nm": "SK하이닉스"}]
    bad = tmp_path / "bad.csv"
    bad.write_bytes("a,b\n1,2\n".encode(enc))
    with pytest.raises(ValueError):
        yi.read_krx_constituents(bad)


# ── 5. 포털 ETF · 지수 ──────────────────────────────────────────────────

def test_index_key_keeps_same_name_in_two_series(tmp_path):
    """TC-OH-15 · 지수시세는 같은 이름(「IT 서비스」)이 KOSPI · KOSDAQ 시리즈에 따로 있다 — 둘 다 남는다.
    ETF 는 NAV · 기초지수 칸을 그대로 담는다."""
    from collector.sources import portal_products as pp
    conn = _db(tmp_path)
    pp._upsert_index(conn, [{"basDt": "20260929", "idxCsf": "KOSPI시리즈", "idxNm": "IT 서비스", "clpr": "1.5"},
                            {"basDt": "20260929", "idxCsf": "KOSDAQ시리즈", "idxNm": "IT 서비스", "clpr": "663.33"}], "sha")
    assert conn.execute("SELECT COUNT(*) FROM index_daily").fetchone()[0] == 2
    pp._upsert_etf(conn, [{"basDt": "20260929", "srtnCd": "0000D0", "itmsNm": "TIGER 엔비디아", "clpr": "8620",
                           "nav": "8645.58", "mkp": "8670", "trqu": "17479", "bssIdxIdxNm": "KEDI 지수"}], "sha")
    r = conn.execute("SELECT srtn_cd, nav, bss_idx_nm, halted FROM etf_daily").fetchone()
    assert tuple(r) == ("0000D0", 8645.58, "KEDI 지수", 0)


def test_portal_product_day_is_one_transaction(tmp_path, monkeypatch):
    """TC-OH-16 · 하루치 받기 = 원문 · 정규화 · 수집 상태(source=portal_etf)를 한 번에. 실패도 상태로 남는다."""
    from collector.ratelimit import RateLimiter
    from collector.sources import portal_products as pp
    conn = sqlite3.connect(tmp_path / "m.sqlite3", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    body = json.dumps({"response": {"header": {"resultCode": "00"}, "body": {"totalCount": 1, "items": {"item": [
        {"basDt": "20260930", "srtnCd": "069500", "itmsNm": "KODEX 200", "clpr": "109545", "vs": "-1", "mkp": "110000",
         "hipr": "111000", "lopr": "109000", "trqu": "20648747"}]}}}}).encode()

    class Resp:
        status_code, content, headers = 200, body, {"X-RateLimit-Remaining": "9000"}

    monkeypatch.setattr(pp.config, "portal_key", lambda: "k")
    monkeypatch.setattr(pp.requests, "get", lambda *a, **k: Resp())
    res = pp.fetch_day(conn, RateLimiter(0), "etf", "20260930")
    assert (res.status, res.rows) == ("done", 1)
    assert conn.execute("SELECT status FROM ingest_day WHERE source='portal_etf'").fetchone()[0] == "done"
    assert conn.execute("SELECT COUNT(*) FROM raw_response WHERE target='etf/20260930'").fetchone()[0] == 1
    assert pp.pending(conn, "etf", ["20260930", "20261002"]) == ["20261002"]


# ── 6. 내보내기 ─────────────────────────────────────────────────────────

def test_export_writes_contract_files_that_pass_check(tmp_path, monkeypatch):
    """TC-OH-17 · 작은 수집 DB → 내보내기 → 파케이마다 ohlcv-v1 칸 · 값 규칙 위반 0 · 매니페스트 행 수가 파일 합과 같다.
    거래정지일(시가 0)은 평평한 봉으로 나간다."""
    from collector import ohlcv_export as ox
    conn = _db(tmp_path)
    for d, o, h, l, c, v in KAKAO:
        conn.execute("INSERT INTO price_daily (bas_dt,srtn_cd,mrkt_ctg,clpr,mkp,hipr,lopr,trqu,tr_prc,halted) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?)", (d.replace("-", ""), "035720", "KOSPI", c, o, h, l, v, c * v, int(o == 0)))
        f = FACTOR if d < "2021-04-15" else 1.0
        conn.execute("INSERT INTO price_adjusted VALUES (?,?,?,?,?,?,?)",
                     (d.replace("-", ""), "035720", c * f, (o * f) or None, (h * f) or None, (l * f) or None, f))
    conn.commit()
    monkeypatch.setattr(ox.db, "connect", lambda: conn)
    man = ox.export(["1d", "1w"], tmp_path / "out")
    assert man["rows"]["1d"] == 2 * len(KAKAO) and man["rows"]["1w"] == 4
    assert all(not v for v in man["checks"].values())
    total = 0
    for f in man["files"]:
        t = pd.read_parquet(tmp_path / "out" / f["path"])
        assert list(t.columns) == list(oh.COLUMNS) and set(t["contract"]) == {oh.CONTRACT}
        total += len(t)
    assert total == man["rows"]["1d"] + man["rows"]["1w"]
    day = pd.read_parquet(tmp_path / "out" / "ohlcv/timeframe=1d/basis=raw/market=KOSPI/year=2021/part-0.parquet")
    halted = day[day["trade_date"] == "2021-04-13"].iloc[0]
    assert (halted["open"], halted["low"], halted["volume"]) == (558000, 558000, 0)


def test_weekly_range_includes_last_close_on_no_trade_friday():
    """TC-OH-18 · 금요일에 거래가 없던 ETF 는 그날 종가가 기준가(NAV 를 따라감)라 월~목 범위 밖일 수 있다 —
    주봉의 고가 · 저가를 그 종가까지 넓혀 값 규칙을 지킨다(2020-01-02 ~ 2026-09-30 ETF 주봉 1,683개 · 137930 2020-04-10 주)."""
    days = [("2020-04-06", 11125, 11125, 11125, 11125, 0), ("2020-04-07", 11285, 11330, 11210, 11210, 603),
            ("2020-04-08", 11245, 11245, 11245, 11245, 3), ("2020-04-09", 11245, 11325, 11245, 11325, 62),
            ("2020-04-10", 11395, 11395, 11395, 11395, 0)]
    w = oh.weekly(_df([_bar(sym="137930", market="ETF", d=d, o=o, h=h, l=l, c=c, v=v) for d, o, h, l, c, v in days]))
    r = w.iloc[0]
    assert (r["open"], r["high"], r["low"], r["close"]) == (11285, 11395, 11210, 11395)
    assert oh.check(oh.finalize(w.drop(columns=["partial"]), source="test"))["problems"] == {}
