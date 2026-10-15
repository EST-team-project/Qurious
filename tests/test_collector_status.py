"""종목 · 날짜별 수집 상태 시험 (TC-SDS) — `app/services/collector_status.py` (#124 계약 · 2026-10-15).

여기서 지키는 것 —
1. 사실만 — kind(본 적 있는 표) · collected(그날 출처별 수집 기록 상태 그대로) · row · halted · volume_zero · notes.
   판정(기다림 · 미체결 종료)은 하지 않는다(응답 칸에 판정이 없다).
2. 모르면 None + 까닭 — 기록 없는 날 · 거래량 칸 빔 · 어느 표에도 없는 종목(두 출처 모두 싣기).
3. 맞대기 — 같은 임시 수집 DB 에서 리밸런싱 판정(`rebalance_prices.read_prices(field="open")`)과 이 함수의 사실로 다시 낸 결론이
   경우마다 같다(주담당 코드는 고치지 않고 어긋남만 본다).
4. 수집 DB 는 읽기 전용 한 트랜잭션 · 없거나 못 읽으면 예외(종목별 「모름」 을 꾸미지 않음) · 꼴이 틀린 기호 · 날짜는 DB 를 열기 전에 멈춤.

실제 수집 DB 는 열지 않는다 — 임시 SQLite 를 COLLECTOR_DB_PATH 로 가리키고, 그 밖의 시험은 없는 경로(autouse).
"""
from __future__ import annotations

import sqlite3
from datetime import date

import pytest

from app.services import collector_db
from app.services import collector_status as cs
from app.services import rebalance_prices as rp

DAY = date(2026, 10, 13)
D = DAY.strftime("%Y%m%d")


@pytest.fixture(autouse=True)
def _no_real_db(tmp_path, monkeypatch):
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(tmp_path / "없는-수집DB.sqlite3"))


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """임시 수집 DB — 수집기 표 정의(SSoT) 그대로 · 경우마다 종목 한 줄씩."""
    from collector import db as CDB

    p = tmp_path / "market.sqlite3"
    c = sqlite3.connect(p)
    c.executescript(CDB.SCHEMA)
    c.commit()
    c.close()
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(p))
    return p


def put(p, table, code, day=D, *, mkp=10_000, clpr=10_100, trqu=1000, halted=0):
    c = sqlite3.connect(p)
    c.execute(f"INSERT INTO {table} (bas_dt, srtn_cd, itms_nm, clpr, mkp, hipr, lopr, trqu, halted) VALUES (?,?,?,?,?,?,?,?,?)",
              (day, code, code, clpr, mkp, clpr, mkp, trqu, halted))
    c.commit()
    c.close()


def mark(p, source, status, day=D):
    c = sqlite3.connect(p)
    c.execute("INSERT INTO ingest_day (source, bas_dt, status, rows, attempts, updated_at) VALUES (?,?,?,?,1,'2026-10-14T12:31:00+09:00')",
              (source, day, status, 1 if status == "done" else 0))
    c.commit()
    c.close()


# ── TC-SDS-01 kind · collected 열쇠 ───────────────────────────────

def test_sds01_kind_by_tables_seen_and_sources_carried(db):
    put(db, "price_daily", "005930", day="20261001")                     # 다른 날 행만 있어도 「본 적 있음」
    put(db, "etf_daily", "069500", day="20261001")
    put(db, "price_daily", "111111", day="20261001")
    put(db, "etf_daily", "111111", day="20261001")
    out = cs.symbol_day_status(["005930", "069500", "111111", "222222"], DAY)
    assert out["005930"]["kind"] == "stock" and set(out["005930"]["collected"]) == {"portal"}
    assert out["069500"]["kind"] == "etf" and set(out["069500"]["collected"]) == {"portal_etf"}
    assert out["111111"]["kind"] == "mixed" and set(out["111111"]["collected"]) == {"portal", "portal_etf"}
    assert out["222222"]["kind"] == "unknown" and set(out["222222"]["collected"]) == {"portal", "portal_etf"}
    assert any("어디에도 없는" in n for n in out["222222"]["notes"])


# ── TC-SDS-02 수집 기록 상태는 그대로 · 기록 없음은 None + 까닭 ───────

def test_sds02_collected_status_passthrough_and_none_with_reason(db):
    put(db, "price_daily", "005930", day="20261001")
    for status in ("done", "empty", "holiday", "error"):
        c = sqlite3.connect(db)
        c.execute("DELETE FROM ingest_day")
        c.commit()
        c.close()
        mark(db, "portal", status)
        st = cs.symbol_day_status(["005930"], DAY)["005930"]
        assert st["collected"] == {"portal": status}
        assert not any("기록 없음" in n for n in st["notes"])
    c = sqlite3.connect(db)
    c.execute("DELETE FROM ingest_day")
    c.commit()
    c.close()
    st = cs.symbol_day_status(["005930"], DAY)["005930"]
    assert st["collected"] == {"portal": None} and any("기록 없음" in n for n in st["notes"])
    mark(db, "portal", "weird")
    st = cs.symbol_day_status(["005930"], DAY)["005930"]
    assert st["collected"] == {"portal": "weird"} and any("모르는 상태" in n for n in st["notes"])


# ── TC-SDS-03 행 · 거래정지 · 거래량 ─────────────────────────────

def test_sds03_row_halted_volume_facts(db):
    put(db, "price_daily", "000001")
    put(db, "price_daily", "000002", halted=1)
    put(db, "price_daily", "000003", trqu=0, mkp=0)
    put(db, "price_daily", "000004", trqu=None)
    put(db, "price_daily", "000005", day="20261001")                     # 그날 행 없음
    put(db, "etf_daily", "0000D0", trqu=0)                                # ETF 는 영문이 섞인 코드
    out = cs.symbol_day_status(["000001", "000002", "000003", "000004", "000005", "0000D0"], "2026-10-13")
    assert (out["000001"]["row"], out["000001"]["halted"], out["000001"]["volume_zero"]) == (True, False, False)
    assert out["000002"]["halted"] is True
    assert out["000003"]["volume_zero"] is True
    assert out["000004"]["volume_zero"] is None and any("거래량" in n for n in out["000004"]["notes"])
    assert (out["000005"]["row"], out["000005"]["halted"], out["000005"]["volume_zero"]) == (False, None, None)
    assert out["0000D0"]["kind"] == "etf" and out["0000D0"]["volume_zero"] is True


def test_sds03b_reply_has_facts_only_no_decision(db):
    put(db, "price_daily", "005930")
    st = cs.symbol_day_status(["005930"], DAY)["005930"]
    assert set(st) == {"symbol", "day", "kind", "collected", "row", "halted", "volume_zero", "notes"}
    assert st["symbol"] == "005930" and st["day"] == "2026-10-13"


# ── TC-SDS-04 기호 · 날짜 꼴 · DB 없음 · 못 읽음 ────────────────────

def test_sds04_inputs_and_unavailable(db, tmp_path, monkeypatch):
    put(db, "price_daily", "005930")
    out = cs.symbol_day_status(["005930.KS", "005930", "005930.KS"], "20261013")
    assert list(out) == ["005930.KS", "005930"]                          # 넣은 기호를 열쇠로 · 같은 기호는 한 번
    assert out["005930.KS"]["symbol"] == out["005930"]["symbol"] == "005930"
    for bad in ("5930", "AAPL", "005930.XX", ""):
        with pytest.raises(ValueError):
            cs.symbol_day_status([bad], DAY)
    for bad_day in ("2026/10/13", "어제", "202610"):
        with pytest.raises(ValueError):
            cs.symbol_day_status(["005930"], bad_day)
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(tmp_path / "없음.sqlite3"))
    with pytest.raises(cs.CollectorStatusUnavailable):
        cs.symbol_day_status(["005930"], DAY)
    with pytest.raises(ValueError):                                      # 꼴이 틀리면 DB 를 보기 전에 멈춘다
        cs.symbol_day_status(["zzz"], DAY)
    broken = tmp_path / "broken.sqlite3"
    broken.write_bytes(b"not a sqlite database at all")
    with pytest.raises(cs.CollectorStatusUnavailable):
        cs.symbol_day_status(["005930"], DAY, path=broken)


def test_sds05_read_only_single_connection(db, monkeypatch):
    put(db, "price_daily", "005930")
    put(db, "etf_daily", "069500")
    seen, real, recs = [], sqlite3.connect, []

    class Rec:                                                           # 연결이 받은 SQL 첫 낱말을 차례대로 적는다
        def __init__(self, conn):
            self.conn, self.sql = conn, []

        def execute(self, sql, *a):
            self.sql.append(sql.split()[0].upper())
            return self.conn.execute(sql, *a)

        def close(self):
            self.conn.close()

    def spy(target, *a, **k):
        seen.append(str(target))
        recs.append(Rec(real(target, *a, **k)))
        return recs[-1]

    monkeypatch.setattr(cs.sqlite3, "connect", spy)
    cs.symbol_day_status(["005930", "069500", "123456"], DAY)
    assert len(seen) == 1 and "mode=ro" in seen[0]                       # 종목이 여럿이어도 한 번 · 읽기 전용
    sql = recs[0].sql                                                    # 첫 질의 전에 BEGIN 한 번 — 모든 종목이 같은 순간의 DB(깨 보기 D2)
    assert sql[0] == "BEGIN" and sql.count("BEGIN") == 1 and len(sql) > 6 and set(sql[1:]) == {"SELECT"}


# ── TC-SDS-06 맞대기 — 리밸런싱 판정과 같은 결론 ─────────────────

def _decide(st: dict) -> str:
    """리밸런싱 예약 체결 규칙을 이 함수의 사실로 다시 쓴 것 — 시험 안에만 둔다(앱의 판정은 `rebalance_prices` 한 곳)."""
    complete = all(v == "done" for v in st["collected"].values())
    if not st["row"] or st["halted"] or st["volume_zero"] is True:
        return "not_tradable" if complete else "wait"
    if st["volume_zero"] is None:
        return "wait"
    return "tradable"


def _read_prices_outcome(sym: str) -> str:
    try:
        rp.read_prices([sym], DAY, field="open")
        return "tradable"
    except rp.OpenNotTradable:
        return "not_tradable"
    except rp.PriceUnavailable:
        return "wait"


CASES = [
    # (이름, 준비, 기대 결론)
    ("행 있음 · 정상", lambda p: (put(p, "price_daily", "100001"), mark(p, "portal", "done")), "100001", "tradable"),
    ("행 없음 · 수집 끝", lambda p: (put(p, "price_daily", "100002", day="20261001"), mark(p, "portal", "done")), "100002", "not_tradable"),
    ("행 없음 · 기록 없음", lambda p: put(p, "price_daily", "100003", day="20261001"), "100003", "wait"),
    ("행 없음 · 0행 응답", lambda p: (put(p, "price_daily", "100004", day="20261001"), mark(p, "portal", "empty")), "100004", "wait"),
    ("행 없음 · 수집 실패", lambda p: (put(p, "price_daily", "100005", day="20261001"), mark(p, "portal", "error")), "100005", "wait"),
    ("거래정지 · 수집 끝", lambda p: (put(p, "price_daily", "100006", halted=1), mark(p, "portal", "done")), "100006", "not_tradable"),
    ("거래량 0 · 수집 끝", lambda p: (put(p, "price_daily", "100007", trqu=0), mark(p, "portal", "done")), "100007", "not_tradable"),
    ("거래량 0 · 기록 없음", lambda p: put(p, "price_daily", "100008", trqu=0), "100008", "wait"),
    ("거래량 칸 빔 · 수집 끝", lambda p: (put(p, "price_daily", "100009", trqu=None), mark(p, "portal", "done")), "100009", "wait"),
    ("모르는 종목 · 두 출처 끝", lambda p: (mark(p, "portal", "done"), mark(p, "portal_etf", "done")), "100010", "not_tradable"),
    ("모르는 종목 · 한 출처만", lambda p: mark(p, "portal", "done"), "100011", "wait"),
    ("ETF 행 없음 · ETF 수집 끝", lambda p: (put(p, "etf_daily", "200001", day="20261001"), mark(p, "portal_etf", "done")), "200001", "not_tradable"),
    ("ETF 행 없음 · 주식만 끝", lambda p: (put(p, "etf_daily", "200002", day="20261001"), mark(p, "portal", "done")), "200002", "wait"),
    ("ETF 정상", lambda p: (put(p, "etf_daily", "200003"), mark(p, "portal_etf", "done")), "200003", "tradable"),
]


@pytest.mark.parametrize("name,setup,sym,want", CASES, ids=[c[0] for c in CASES])
def test_sds06_same_conclusion_as_rebalance_prices(db, name, setup, sym, want):
    setup(db)
    st = cs.symbol_day_status([sym], DAY)[sym]
    assert _read_prices_outcome(sym) == want, name                     # 주담당 판정(지금 코드)
    assert _decide(st) == want, (name, st)                              # 이 함수의 사실로 낸 결론이 같다
    assert collector_db.db_path() == db
