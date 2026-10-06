"""OHLCV 규격 자료 API 시험 (TC-OA) — `GET /api/data/ohlcv` · 목표 기능 ① W4 · 설계서 7절 · 결함 DF-43.

무엇을 지키나 —
앱 이미지에는 `collector` 패키지가 들어가지 않아(collector_db 머리말) API 는 수집기 내보내기와 **같은 규칙을 따로** 갖고
있다. 둘이 어긋나면 HF `krx-ohlcv` 파일과 API 가 같은 날 다른 값을 준다. 그래서 같은 작은 DB 를 두고 줄마다 대조한다.

1. 칸 · 지수 접두사가 수집기 규격과 같다.
2. 주식 일봉(원 가격 · 수정 가격) · ETF · 지수 · 분봉이 수집기 내보내기 함수와 줄마다 같다 — 거래정지일(시가 0) ·
   액면분할(카카오 2021-04-15 · 5:1) · 같은 이름 지수(KOSPI · KOSDAQ 「IT 서비스」) 포함.
3. 주봉이 `collector.ohlcv.weekly` 와 같다 — 거래 없는 금요일(137930 2020-04-10 주) · 진행 중인 주(partial).
4. 분봉의 시장 = 그 종목이 든 가장 최근 유니버스 판(DF-43 — 최신 판에 없는 코스닥 종목이 KOSPI 로 나갔다).
5. 받은 시각 = 그날 원문을 마지막으로 받은 시각(같은 날 두 번 받으면 뒤의 것 — 정규화 줄이 쓰는 것).
6. 고칠 수 있는 잘못은 상태와 할 일로(422 · 404 · 503) · 로그인 없이는 401.
마지막 시험만 실제 수집 DB 를 읽고, 없으면 건너뛴다.
"""
from __future__ import annotations

import math
import sqlite3
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.lib.session import get_current_user
from app.routes import data as data_routes
from app.services import collector_db, data_ohlcv as oa
from collector import db
from collector import ohlcv as oh
from collector import ohlcv_export as ox

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 10, 2)
ALL = {"start": "2019-01-01", "end": "2027-12-31", "today": TODAY}

KAKAO = [  # tests/test_ohlcv.py 와 같은 원자료 — 2021-04-12~14 거래정지(시가 · 고가 · 저가 0), 04-15 액면분할 5:1
    ("20210405", 503000, 505000, 500000, 502000, 310400), ("20210406", 506000, 545000, 505000, 544000, 1724958),
    ("20210407", 544000, 544000, 526000, 542000, 820896), ("20210408", 539000, 561000, 534000, 548000, 912514),
    ("20210409", 554000, 561000, 551000, 558000, 788839), ("20210412", 0, 0, 0, 558000, 0),
    ("20210413", 0, 0, 0, 558000, 0), ("20210414", 0, 0, 0, 558000, 0),
    ("20210415", 120500, 132500, 118000, 120500, 17115015), ("20210416", 115500, 120500, 115500, 119000, 13709555),
]
FACTOR = 112000 / 558000
ETF_WEEK = [  # 137930 2020-04-06 주 — 금요일 거래 없음 · 종가가 월~목 범위 밖(TC-OH-18)
    ("20200406", 11125, 11125, 11125, 11125, 0), ("20200407", 11285, 11330, 11210, 11210, 603),
    ("20200408", 11245, 11245, 11245, 11245, 3), ("20200409", 11245, 11325, 11245, 11325, 62),
    ("20200410", 0, 0, 0, 11395, 0),
]


@pytest.fixture
def market(tmp_path, monkeypatch):
    """수집기 SCHEMA 로 만든 작은 수집 DB — 주식 · ETF · 지수 · 분봉 · 유니버스 두 판 · 원문 기록."""
    path = tmp_path / "collector" / "market.sqlite3"
    path.parent.mkdir()
    conn = db.connect(path)
    raw = []
    for d, o, h, l, c, v in KAKAO:
        sha = f"p-{d}"
        if d == "20210409":                          # 같은 날을 두 번 받았다 — 정규화 줄은 뒤의 것을 쓴다
            raw.append(("portal", f"price/{d}", "2026-09-19T11:00:00+09:00", f"{sha}-old"))
            sha = f"{sha}-new"
            raw.append(("portal", f"price/{d}", "2026-09-20T09:00:00+09:00", sha))
        else:
            raw.append(("portal", f"price/{d}", "2026-09-19T11:00:00+09:00", sha))
        conn.execute("INSERT INTO price_daily (bas_dt, srtn_cd, mrkt_ctg, clpr, mkp, hipr, lopr, trqu, tr_prc, halted, "
                     "raw_sha256) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (d, "035720", "KOSPI", c, o, h, l, v, c * v, int(o == 0), sha))
        f = FACTOR if d < "20210415" else 1.0
        conn.execute("INSERT INTO price_adjusted VALUES (?,?,?,?,?,?,?)",
                     (d, "035720", c * f, (o * f) or None, (h * f) or None, (l * f) or None, f))
    for d, o, h, l, c, v in ETF_WEEK:
        raw.append(("portal", f"etf/{d}", "2026-10-01T12:52:17+09:00", f"e-{d}"))
        conn.execute("INSERT INTO etf_daily (bas_dt, srtn_cd, itms_nm, clpr, mkp, hipr, lopr, trqu, tr_prc, raw_sha256) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?)", (d, "137930", "시험 ETF", c, o, h, l, v, c * v, f"e-{d}"))
    for d, series, name, c in (("20260929", "KOSPI시리즈", "IT 서비스", 1121.5), ("20260929", "KOSDAQ시리즈", "IT 서비스", 880.25),
                               ("20260930", "KOSPI시리즈", "IT 서비스", 1130.75), ("20260930", "KOSDAQ시리즈", "IT 서비스", 875.0),
                               ("20260930", "KOSPI시리즈", "코스피 200", 1104.5)):
        raw.append(("portal", f"index/{d}", "2026-10-01T12:52:20+09:00", f"i-{d}"))
        conn.execute("INSERT INTO index_daily (bas_dt, idx_csf, idx_nm, clpr, mkp, hipr, lopr, trqu, tr_prc, raw_sha256) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?)", (d, series, name, c, c - 1, c + 2, c - 3, 1000, 2000, f"i-{d}"))
    conn.executemany("INSERT OR IGNORE INTO raw_response (source, target, fetched_at, body, sha256, bytes) "
                     "VALUES (?,?,?,x'00',?,1)", raw)
    conn.executemany("INSERT INTO intraday_universe (version, symbol, itms_nm, market, reason, rank) VALUES (?,?,?,?,?,?)",
                     [("u1-20260929", "005930", "삼성전자", "KOSPI", "KOSPI 시가총액 1위", 1),
                      ("u1-20260929", "440110", "코스닥 종목", "KOSDAQ", "KOSDAQ 시가총액 50위", 50),
                      ("u2-20260930", "005930", "삼성전자", "KOSPI", "코스피 200", 1)])
    bars = []
    for sym in ("005930", "440110"):
        for hh in (9, 10, 11):
            bars.append((sym, "60m", f"2026-10-01T{hh:02d}:00:00+09:00", "2026-10-01", 100 + hh, 101 + hh, 99 + hh, 100.5 + hh,
                         10 * hh, "regular", "yahoo", "adj_split", "2026-10-01T16:10:00+09:00"))
        bars.append((sym, "60m", "2026-10-02T09:00:00+09:00", "2026-10-02", 120, 121, 119, 120.5, 30,
                     "regular", "yahoo", "adj_split", "2026-10-02T12:55:03+09:00"))   # 장 중에 받은 날
    conn.executemany("INSERT INTO price_intraday VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", bars)
    conn.commit()
    conn.close()
    monkeypatch.setenv(collector_db.ENV_DB_PATH, str(path))
    return path


def _norm(v):
    if v is None:
        return None
    if hasattr(v, "item"):                          # numpy 값 → 파이썬 값
        v = v.item()
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, bool) or isinstance(v, str):
        return v
    if isinstance(v, (int, float)):
        return round(float(v), 6)
    return v


def _rows(df) -> list[dict]:
    return [{c: _norm(r.get(c)) for c in oh.COLUMNS} for r in df.to_dict("records")]


def _export(fn, path: Path, **filt) -> pd.DataFrame:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        df = oh.finalize(fn(conn), source=filt.pop("source", "portal"))
    finally:
        conn.close()
    for k, v in filt.items():
        df = df[df[k] == v]
    return df.sort_values(["trade_date", "bar_start"], na_position="first").reset_index(drop=True)


def test_columns_and_index_prefix_match_collector():
    """TC-OA-01 · 칸 · 차례 · 주기 · 지수 접두사가 수집기 규격(`collector/ohlcv.py` · `ohlcv_export.py`)과 같다."""
    assert oa.COLUMNS == tuple(oh.COLUMNS) and oa.CONTRACT == oh.CONTRACT
    assert set(oa.TIMEFRAMES) <= set(oh.TIMEFRAMES) and set(oa.INTRADAY) <= set(oh.INTRADAY)
    assert oa.INDEX_PREFIX == ox.INDEX_PREFIX
    assert {b for v in oa.BASES.values() for b in v} <= set(oh.PRICE_BASES)


@pytest.mark.parametrize("basis", ["raw", "adj_base"])
def test_stock_daily_matches_export(market, basis):
    """TC-OA-02 · 주식 일봉이 내보내기와 줄마다 같다 — 거래정지 사흘은 평평한 봉 · 분할 앞은 계수 · 거래량 ÷ 계수 · 받은 시각."""
    got = oa.read_ohlcv("035720", basis=basis, **ALL)
    want = _export(ox.stock_daily, market, symbol="035720", price_basis=basis)
    assert got["count"] == len(KAKAO) and got["market"] == "KOSPI" and got["basis"] == basis
    assert [{c: _norm(r[c]) for c in oh.COLUMNS} for r in got["rows"]] == _rows(want)
    halted = next(r for r in got["rows"] if r["trade_date"] == "2021-04-13")
    assert halted["open"] == halted["high"] == halted["low"] == halted["close"] and halted["volume"] == 0
    assert next(r for r in got["rows"] if r["trade_date"] == "2021-04-09")["fetched_at"] == "2026-09-20T09:00:00+09:00"


def test_weekly_matches_collector_weekly_and_partial(market):
    """TC-OA-03 · 주봉이 `collector.ohlcv.weekly` 와 같다(분할 주 · 거래 없는 금요일) · `to` 가 주 중간이면 그 주는 진행 중."""
    for sym, basis, fn in (("035720", "adj_base", ox.stock_daily), ("035720", "raw", ox.stock_daily),
                           ("137930", "raw", ox.etf_daily)):
        daily = _export(fn, market, symbol=sym, price_basis=basis)
        last = daily["trade_date"].max()
        want = oh.weekly(daily, as_of=last)
        got = oa.read_ohlcv(sym, "1w", basis=basis, **ALL)
        assert [{c: _norm(r[c]) for c in oh.COLUMNS} for r in got["rows"]] == _rows(oh.finalize(want.drop(columns=["partial"]),
                                                                                              source="portal")), (sym, basis)
        assert got["partial"] == bool(want["partial"].iloc[-1])
    etf = oa.read_ohlcv("137930", "1w", **ALL)["rows"][0]
    assert (etf["open"], etf["high"], etf["low"], etf["close"]) == (11285, 11395, 11210, 11395)
    cut = oa.read_ohlcv("035720", "1w", start="2021-04-12", end="2021-04-14", today=TODAY)   # 수요일에서 자름
    assert cut["partial"] is True and cut["rows"][-1]["trade_date"] == "2021-04-14"
    assert oa.read_ohlcv("035720", "1w", start="2021-04-05", end="2021-04-09", today=TODAY)["partial"] is False


def test_etf_and_same_name_indexes_match_export(market):
    """TC-OA-04 · ETF · 지수 일봉이 내보내기와 같다 — 같은 이름 「IT 서비스」 는 시리즈마다 따로 · 없는 지수는 404 와 후보(띄어쓰기 무시)."""
    assert [{c: _norm(r[c]) for c in oh.COLUMNS} for r in oa.read_ohlcv("137930", **ALL)["rows"]] == \
        _rows(_export(ox.etf_daily, market, symbol="137930"))
    for sym in ("KOSPI:IT 서비스", "KOSDAQ:IT 서비스", "KOSPI:코스피 200"):
        got = oa.read_ohlcv(sym, **ALL)
        assert got["market"] == "INDEX" and got["rows"], sym
        assert [{c: _norm(r[c]) for c in oh.COLUMNS} for r in got["rows"]] == _rows(_export(ox.index_daily, market, symbol=sym))
    assert oa.read_ohlcv("KOSPI:IT 서비스", **ALL)["rows"][-1]["close"] == 1130.75
    assert oa.read_ohlcv("KOSDAQ:IT 서비스", **ALL)["rows"][-1]["close"] == 875.0
    with pytest.raises(oa.OhlcvError) as e:
        oa.read_ohlcv("KRX:IT 서비스", **ALL)
    assert e.value.status == 404 and set(e.value.extra["candidates"]) == {"KOSPI:IT 서비스", "KOSDAQ:IT 서비스"}
    with pytest.raises(oa.OhlcvError) as e:
        oa.read_ohlcv("KOSPI:코스피200", **ALL)
    assert e.value.extra["candidates"][0] == "KOSPI:코스피 200"


def test_intraday_market_from_latest_version_holding_symbol(market):
    """TC-OA-05 · 분봉의 시장 = 그 종목이 든 가장 최근 유니버스 판(DF-43). 내보내기도 같다 — 옛 내보내기는 최신 판(u2)에 없는
    코스닥 종목을 KOSPI 로 채웠다. 장 중에 받은 마지막 날은 덜 찼다고 알린다."""
    got = oa.read_ohlcv("440110", "60m", **ALL)
    assert got["market"] == "KOSDAQ" and {r["market"] for r in got["rows"]} == {"KOSDAQ"}
    want = _export(lambda c: ox.intraday(c, "60m"), market, symbol="440110", source="yahoo")
    assert set(want["market"]) == {"KOSDAQ"}, "DF-43 — 내보내기가 최신 판에 없는 코스닥 종목을 KOSPI 로 채운다"
    assert [{c: _norm(r[c]) for c in oh.COLUMNS} for r in got["rows"]] == _rows(want)
    assert got["incomplete_day"] == "2026-10-02" and "12:55" in got["incomplete_note"]
    done = oa.read_ohlcv("005930", "60m", start="2026-10-01", end="2026-10-01", today=TODAY)
    assert "incomplete_day" not in done and done["count"] == 3


@pytest.mark.parametrize("kw, status, word", [
    ({"symbol": "035720", "timeframe": "1m"}, 422, "1분봉"),
    ({"symbol": "035720", "timeframe": "1h"}, 422, "주기"),
    ({"symbol": "삼성전자"}, 422, "기호 모양"),
    ({"symbol": "NASDAQ:애플"}, 422, "시리즈"),
    ({"symbol": "999999"}, 404, "없다"),
    ({"symbol": "137930", "basis": "adj_base"}, 422, "raw"),
    ({"symbol": "035720", "start": "2021-04-16", "end": "2021-04-05"}, 422, "뒤다"),
    ({"symbol": "035720", "start": "2021-13-01"}, 422, "없는 날짜"),
    ({"symbol": "035720", "start": "2021/04/05"}, 422, "YYYY-MM-DD"),
    ({"symbol": "035720", "start": "2019-01-01", "end": "2027-12-31", "limit": 5}, 422, "limit"),
    ({"symbol": "KOSPI:코스피 200", "timeframe": "60m"}, 422, "지수 분봉"),
    ({"symbol": "000660", "timeframe": "5m"}, 404, "유니버스"),
])
def test_errors_say_what_to_do(market, kw, status, word):
    """TC-OA-06 · 고칠 수 있는 잘못은 상태와 할 일로 — 1분봉 · 모르는 주기 · 기호 모양 · 시리즈 · 없는 종목 · 없는 수정 방식 ·
    날짜 차례 · 날짜 모양 · 줄 수 상한 · 지수 분봉 · 유니버스 밖 분봉."""
    args = {"today": TODAY, **kw}
    with pytest.raises(oa.OhlcvError) as e:
        oa.read_ohlcv(args.pop("symbol"), **args)
    assert e.value.status == status and word in e.value.message


def test_no_db_is_503(tmp_path, monkeypatch):
    """TC-OA-07 · 수집 DB 가 없으면 503 과 어디서 찾았는지."""
    monkeypatch.setenv(collector_db.ENV_DB_PATH, str(tmp_path / "없음.sqlite3"))
    with pytest.raises(oa.OhlcvError) as e:
        oa.read_ohlcv("005930", today=TODAY)
    assert e.value.status == 503 and "COLLECTOR_DB_PATH" in e.value.extra["hint"]


def test_api_requires_login_and_returns_detail(market):
    """TC-OA-08 · 로그인 없이는 401 · 로그인하면 200 과 ohlcv-v1 줄 · 잘못은 상태와 `detail.message`(지수면 후보까지)."""
    app = FastAPI()
    app.include_router(data_routes.router)
    c = TestClient(app)
    assert c.get("/api/data/ohlcv", params={"symbol": "035720"}).status_code == 401
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "name": "시험", "email": "t@example.com"}
    j = c.get("/api/data/ohlcv", params={"symbol": "035720", "from": "2021-04-05", "to": "2021-04-16"}).json()
    assert j["contract"] == "ohlcv-v1" and j["count"] == 10 and j["columns"] == list(oh.COLUMNS)
    assert j["rows"][0]["trade_date"] == "2021-04-05" and j["source"] == "collector" and j["as_of"] == "2021-04-16"
    r = c.get("/api/data/ohlcv", params={"symbol": "KRX:IT 서비스"})
    assert r.status_code == 404 and r.json()["detail"]["candidates"]
    assert c.get("/api/data/ohlcv", params={"symbol": "035720", "limit": 0}).status_code == 422


def test_real_db_matches_tables():
    """TC-OA-09 · (실제 수집 DB) 삼성전자 마지막 일봉 = 주식 표 · 코스피 200 마지막 날 = 지수 표 · u2 에서 빠진 코스닥 종목의 분봉 시장 = KOSDAQ."""
    path = collector_db.db_path()
    if path is None:
        pytest.skip("수집 DB 가 없다")
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        last = conn.execute("SELECT bas_dt, clpr FROM price_daily WHERE srtn_cd='005930' ORDER BY bas_dt DESC LIMIT 1").fetchone()
        idx = conn.execute("SELECT bas_dt, clpr FROM index_daily WHERE idx_csf='KOSPI시리즈' AND idx_nm='코스피 200' "
                           "ORDER BY bas_dt DESC LIMIT 1").fetchone()
        gone = conn.execute("SELECT symbol FROM intraday_universe WHERE market='KOSDAQ' AND symbol NOT IN "
                            "(SELECT symbol FROM intraday_universe WHERE version=(SELECT MAX(version) FROM intraday_universe)) "
                            "AND symbol IN (SELECT symbol FROM price_intraday WHERE timeframe='60m') LIMIT 1").fetchone()
    finally:
        conn.close()
    got = oa.read_ohlcv("005930", basis="raw")
    assert (got["rows"][-1]["trade_date"].replace("-", ""), got["rows"][-1]["close"]) == (last[0], float(last[1]))
    assert oa.read_ohlcv("KOSPI:코스피 200")["rows"][-1]["close"] == idx[1]
    if gone:
        assert oa.read_ohlcv(gone[0], "60m")["market"] == "KOSDAQ"
