"""모의투자 그림자 일지 — 판단 기준일 · 체결 · 크기 · 판 지문 · 봉인 · 한 행 하루 · 원장 추가만 (TC-PJ · 할 일 ①-26).

설계 `docs/phase-3/02-design/system/모의투자-그림자일지-설계.md`. 수집 DB 는 수집기 스키마(`collector.db.SCHEMA`)로 만든 합성
자료다(실제 봉인 구간 자료를 읽지 않는다 — 설계 4.3 ⚠️). 판 등록 · 회차 시험은 일회용 시험 DB(`QURIOUS_TEST_DATABASE_URL`)가
있을 때만 돈다(`scripts/personal/test.ps1`).
"""
import asyncio
import inspect
import json
import os
import sqlite3
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from app.services import paper_journal as pj

KST = pj.KST
CARD = "005930.KS"


# ── 합성 수집 DB ─────────────────────────────────────────────────────────

def _universe() -> list[dict]:
    from app.services.stock import QUANT_STOCKS
    return QUANT_STOCKS


def _make_db(path, days, *, seed=7, calendar=None):
    """수집기 스키마로 일봉 두 표(원주가 · 수정주가 · 계수 1)를 채운다 — 31종목(카드 종목 005930 포함). 한 트랜잭션으로."""
    from collector import db

    conn = sqlite3.connect(path)
    conn.executescript(db.SCHEMA)
    rng = np.random.default_rng(seed)
    daily, adjusted = [], []
    for i, s in enumerate(_universe()):
        code = s["symbol"][:6]
        # 카드 종목(005930 · 첫 줄)은 꾸준히 오르는 쪽 — 카드 규칙(SMA20 > SMA60)이 매수 신호를 내 체결 사슬을 시험할 수 있게
        mu, sd = (0.002, 0.006) if code == "005930" else (0.0003 * ((i % 5) - 2), 0.015)
        close = 50_000 * (1 + i / 10) * np.cumprod(1 + rng.normal(mu, sd, len(days)))
        prev = close[0] if len(days) else 0
        for d, c in zip(days, close):
            c = int(round(c))
            o = int(round(prev * (1 + rng.normal(0, 0.004))))
            h, low = max(o, c) + 50, min(o, c) - 50
            ymd = d.strftime("%Y%m%d")
            daily.append((ymd, code, s["name"], c, o, h, low))
            adjusted.append((ymd, code, float(c), float(o), float(h), float(low)))
            prev = c
    conn.executemany("INSERT INTO price_daily (bas_dt, srtn_cd, itms_nm, mrkt_ctg, clpr, mkp, hipr, lopr, trqu, halted) "
                     "VALUES (?, ?, ?, 'KOSPI', ?, ?, ?, ?, 1000, 0)", daily)
    conn.executemany("INSERT INTO price_adjusted (bas_dt, srtn_cd, adj_clpr, adj_mkp, adj_hipr, adj_lopr, cum_factor) "
                     "VALUES (?, ?, ?, ?, ?, ?, 1.0)", adjusted)
    conn.executemany("INSERT INTO market_calendar (cal_date, is_trading_day, reason, basis, note, updated_at) "
                     "VALUES (?, ?, '', 'rule', '', '2026-10-24')",
                     [(d.isoformat(), int(t)) for d, t in (calendar or {}).items()])
    conn.commit()
    conn.close()


DAYS = [d.date() for d in pd.bdate_range("2025-08-01", "2026-09-30")]


@pytest.fixture(scope="module")
def _base_db(tmp_path_factory):
    path = tmp_path_factory.mktemp("pj") / "market.sqlite3"
    _make_db(path, DAYS)
    return path


@pytest.fixture
def cdb(_base_db, tmp_path, monkeypatch):
    """시험마다 바탕 DB 의 사본 — 고쳐 보는 시험이 다른 시험에 새지 않게."""
    import shutil

    path = tmp_path / "market.sqlite3"
    shutil.copy(_base_db, path)
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(path))
    return path


def _set(path, symbol, d, **cols):
    conn = sqlite3.connect(path, isolation_level=None)
    sets = ", ".join(f"{k} = ?" for k in cols)
    conn.execute(f"UPDATE price_daily SET {sets} WHERE bas_dt = ? AND srtn_cd = ?",
                 (*cols.values(), d.strftime("%Y%m%d"), symbol[:6]))
    conn.close()


def _run(coro):
    return asyncio.run(coro)


# ── TC-PJ-01 · 02 판단은 그날까지 · 수집 DB 만 ─────────────────────────────

def test_pj01_decision_ignores_bars_after_the_day(cdb):
    """행 D 의 판단은 D 뒤 봉을 세 배로 바꿔도 같다 — 두 규칙 모두(미래 참조 없음)."""
    d = date(2026, 9, 15)
    specs = [pj.rule_spec(pj.RULE_CARD), pj.rule_spec(pj.RULE_DEFAULT)]
    before = [_run(pj.decide(s, d)) for s in specs]
    conn = sqlite3.connect(cdb, isolation_level=None)
    conn.execute("UPDATE price_adjusted SET adj_clpr = adj_clpr * 3 WHERE bas_dt > ?", (d.strftime("%Y%m%d"),))
    conn.execute("UPDATE price_daily SET clpr = clpr * 3 WHERE bas_dt > ?", (d.strftime("%Y%m%d"),))
    conn.close()
    after = [_run(pj.decide(s, d)) for s in specs]
    assert before == after
    assert all(x["as_of"] == d.isoformat() for dec, _ in before for x in dec)


def test_pj02_no_other_source_and_get_candles_is_restored(cdb, monkeypatch):
    """그날 수집 DB 봉이 없는 종목은 「자료 없음」 — 앱의 일봉 함수가 다른 출처로 넘어가지 않고, 끝나면 원래 함수로 돌아온다."""
    from app.services import stock

    orig = stock.get_candles
    called = []

    async def boom(*a, **k):                      # 일지가 원래 함수를 부르면(= 다른 출처로 샐 수 있으면) 실패
        called.append(a)
        raise AssertionError("일지 안에서 앱의 원래 일봉 함수를 불렀다")

    monkeypatch.setattr(stock, "get_candles", boom)
    d = date(2026, 9, 15)
    conn = sqlite3.connect(cdb, isolation_level=None)
    conn.execute("DELETE FROM price_adjusted WHERE bas_dt = ? AND srtn_cd = '005930'", (d.strftime("%Y%m%d"),))
    conn.close()
    dec, _ = _run(pj.decide(pj.rule_spec(pj.RULE_CARD), d))
    assert dec[0]["missing"] is True and dec[0]["action"] is None
    assert stock.get_candles is boom and not called            # 바꿔 끼운 것을 원래대로(여기서는 boom) 돌려놓았다
    monkeypatch.setattr(stock, "get_candles", orig)


# ── TC-PJ-03 카드 규칙 = 앱 함수 · 카드 종목만 ─────────────────────────────

def test_pj03_card_rule_is_the_app_function_on_card_symbol_only(cdb):
    from app.services import auto_trade, collector_db, stock

    d = date(2026, 9, 15)
    spec = pj.rule_spec(pj.RULE_CARD)
    dec, ranking = _run(pj.decide(spec, d))
    assert [x["symbol"] for x in dec] == [CARD] and ranking == []      # AI 상위 3 과 상관없이 카드에 적힌 종목만
    candles = collector_db.read_daily_candles(CARD, "2y", today=d)
    closes = [c["close"] for c in candles["candles"]]
    sma = lambda n: sum(closes[-n:]) / n                                 # noqa: E731
    want = "매도" if sma(20) < sma(60) else "매수" if sma(20) > sma(60) else "관망"
    assert dec[0]["action"] == want and dec[0]["rule_based"] is True
    ind = _run(pj._indicators([CARD], d))[CARD]
    assert dec[0]["action"] == auto_trade.apply_strategy_spec_to_signal(ind["signal"], spec["card"], None, ind)["action"]
    assert spec["decision"]["card_sha256"] == pj._card()[1] and spec["sizing"]["max_position_pct"] == 30.0
    assert stock.get_quant_indicators.__name__ == "get_quant_indicators"


def test_pj03b_default_rule_ranks_like_auto_trade(cdb):
    """기본 규칙은 31종목 점수 내림차순 상위 3 — 같은 점수는 유니버스 차례(자동매매 `ranked.sort(reverse=True)` 와 같음)."""
    d = date(2026, 9, 15)
    spec = pj.rule_spec(pj.RULE_DEFAULT)
    dec, ranking = _run(pj.decide(spec, d))
    assert len(ranking) == 31 and [x["symbol"] for x in dec] == [r["symbol"] for r in ranking[:3]]
    scores = [r["score"] for r in ranking]
    assert scores == sorted(scores, reverse=True)
    order = [s["symbol"] for s in _universe()]
    for a, b in zip(ranking, ranking[1:]):
        if a["score"] == b["score"]:
            assert order.index(a["symbol"]) < order.index(b["symbol"])


# ── TC-PJ-04 · 05 크기 · 체결 · 비용 ──────────────────────────────────────

def _spec(**sizing):
    s = pj.rule_spec(pj.RULE_CARD)
    s["sizing"].update(sizing)
    return s


def test_pj05_buy_size_budget_cap_and_sell_half():
    from app.services import risk_guard

    spec, d = _spec(), date(2026, 9, 15)
    book = pj.Book(cash=10_000_000.0, positions={}, equity=10_000_000.0)
    prices = {CARD: {"close": 70_000.0, "open": 70_500.0}}
    dec = [{"symbol": CARD, "name": "삼성전자", "action": "매수"}]
    orders, skipped = pj.plan_orders(spec, dec, book, prices, d)
    assert orders[0]["qty"] == int(1_000_000 / 70_000) and orders[0]["decision_price"] == 70_000.0 and not skipped
    # 30% 상한 — 이미 2,900,000 원어치(41주)면 1주만 더(3,000,000 까지)
    book.positions[CARD] = {"qty": 41, "avg_price": 70_000.0, "name": "삼성전자"}
    orders, _ = pj.plan_orders(spec, dec, book, prices, d)
    want, _ = risk_guard.cap_buy_quantity(14, 70_000.0, 41 * 70_000.0, 10_000_000.0, 30.0)
    assert orders[0]["qty"] == want == 1
    book.positions[CARD]["qty"] = 43
    orders, skipped = pj.plan_orders(spec, dec, book, prices, d)
    assert orders == [] and "한도" in skipped[0]["reason"]
    # 매도 = 보유의 절반(내림 · 최소 1) · 보유 없으면 주문 없음
    sell = [{"symbol": CARD, "name": "삼성전자", "action": "강력 매도"}]
    assert pj.plan_orders(spec, sell, book, prices, d)[0][0]["qty"] == 21
    book.positions[CARD]["qty"] = 1
    assert pj.plan_orders(spec, sell, book, prices, d)[0][0]["qty"] == 1
    book.positions.clear()
    assert pj.plan_orders(spec, sell, book, prices, d) == ([], [])
    # 예산보다 비싼 종목은 1주(자동매매 `max(1, int(예산 ÷ 가격))` 와 같음)
    assert pj.plan_orders(spec, dec, book, {CARD: {"close": 1_500_000.0}}, d)[0][0]["qty"] == 1


def test_pj04_fill_next_open_slippage_costs_halt_and_cash():
    from app.services import trading_cost

    d = date(2026, 9, 16)
    book = pj.Book(cash=10_000_000.0, positions={}, equity=10_000_000.0)
    orders = [{"symbol": CARD, "name": "삼성전자", "side": "buy", "qty": 14, "decision_date": "2026-09-15",
               "decision_price": 70_000.0}]
    f = pj.fill_orders(orders, {CARD: {"open": 71_000.0, "close": 72_000.0}}, book, d, 10.0)[0]
    px = 71_000.0 * 1.001
    oc = trading_cost.order_costs(side="buy", price=px, quantity=14, when=d, market="KOSPI", is_etf=False)
    assert f["status"] == "filled" and f["fill_price"] == round(px, 4) and f["cost"] == oc.as_dict()
    assert book.cash == round(10_000_000.0 - oc.net_amount, 2) and book.positions[CARD]["qty"] == 14
    # 매도는 시가 × (1 − 10bp) · 매도세가 붙는다
    sell = [{"symbol": CARD, "name": "삼성전자", "side": "sell", "qty": 7}]
    f = pj.fill_orders(sell, {CARD: {"open": 72_000.0}}, book, d, 10.0)[0]
    assert f["fill_price"] == round(72_000.0 * 0.999, 4) and f["cost"]["tax_transfer"] > 0 and book.positions[CARD]["qty"] == 7
    # 거래정지 · 시가 0 은 미체결(넘기지 않음)
    assert pj.fill_orders(sell, {CARD: {"open": 0.0}}, book, d, 10.0)[0]["status"] == "unfilled"
    assert pj.fill_orders(sell, {CARD: {"open": 72_000.0, "halted": True}}, book, d, 10.0)[0]["status"] == "unfilled"
    # 현금 부족 → 비용까지 살 수 있는 수량으로 · 0 이면 미체결
    poor = pj.Book(cash=150_000.0, positions={}, equity=150_000.0)
    f = pj.fill_orders(orders, {CARD: {"open": 71_000.0}}, poor, d, 10.0)[0]
    assert f["status"] == "partial" and f["qty_filled"] == 2 and poor.cash >= 0
    assert pj.fill_orders(orders, {CARD: {"open": 71_000.0}}, pj.Book(cash=1_000.0), d, 10.0)[0]["reason"] == "현금 부족"
    # 보유 없는 매도는 미체결
    assert pj.fill_orders(sell, {CARD: {"open": 72_000.0}}, pj.Book(cash=0.0), d, 10.0)[0]["reason"] == "보유 없음"


# ── TC-PJ-06 판 지문 ──────────────────────────────────────────────────────

def test_pj06_fingerprint_ignores_comments_but_sees_code_and_data(monkeypatch):
    src_a = "def f(x):\n    \"\"\"문서\"\"\"\n    # 주석\n    return x + 1\n"
    src_b = "def f(x):\n\n    return x+1   # 다른 주석\n"
    src_c = "def f(x):\n    return x + 2\n"
    ns: dict = {}
    digests = []
    for i, src in enumerate((src_a, src_b, src_c)):
        monkeypatch.setattr(inspect, "getsource", lambda _fn, s=src: s)
        digests.append(pj.code_digest(lambda: None))
    assert digests[0] == digests[1] != digests[2]
    a = pj.fingerprint_parts(pj.RULE_CARD)
    spec = pj.rule_spec(pj.RULE_CARD)
    spec["sizing"]["sell_ratio"] = 1.0
    b = pj.fingerprint_parts(pj.RULE_CARD, spec)
    assert pj.changed_parts(a, b) == ["spec"] and pj.fingerprint_of(a) != pj.fingerprint_of(b)
    assert "auto_trade.apply_strategy_spec_to_signal" in a and "auto_trade.apply_strategy_spec_to_signal" not in \
        pj.fingerprint_parts(pj.RULE_DEFAULT)
    assert set(pj.watch_parts()) == {"auto_trade._run_quant_cycle", "auto_trade._execute_virtual_trade",
                                     "auto_trade.apply_strategy_spec_to_symbols", "stock.get_candles"}


def test_pj06b_fingerprint_follows_app_function_change(monkeypatch):
    """앱의 판단 함수가 바뀌면 그 조각 이름이 바뀐 조각으로 나온다 — 주담당이 고친 것을 기계가 알아챈다."""
    from app.services import stock

    before = pj.fingerprint_parts(pj.RULE_DEFAULT)

    def _generate_signal(closes, rsi, ma5, ma20, ma60, bb_upper, bb_lower):   # 식이 다른 판
        return {"action": "관망", "color": "gray", "score": 0, "reasons": []}

    monkeypatch.setattr(stock, "_generate_signal", _generate_signal)
    after = pj.fingerprint_parts(pj.RULE_DEFAULT)
    assert pj.changed_parts(before, after) == ["stock._generate_signal"]


# ── TC-PJ-07 봉인 시작일 ─────────────────────────────────────────────────

def test_pj07_seal_start(tmp_path, monkeypatch):
    cal = {date(2026, 10, 24): False, date(2026, 10, 25): False, date(2026, 10, 26): True, date(2026, 10, 27): True,
           date(2026, 10, 9): False, date(2026, 10, 8): True, date(2026, 10, 12): True}
    path = tmp_path / "cal.sqlite3"
    _make_db(path, [], calendar=cal)
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(path))
    at = lambda *x: datetime(*x, tzinfo=KST)                         # noqa: E731
    assert pj.seal_start_for(at(2026, 10, 24, 12, 30)) == date(2026, 10, 26)        # 토요일 → 월요일
    assert pj.seal_start_for(at(2026, 10, 26, 15, 29)) == date(2026, 10, 26)        # 거래일 마감 전 → 그날
    assert pj.seal_start_for(at(2026, 10, 26, 15, 30)) == date(2026, 10, 27)        # 마감 뒤 → 다음 거래일
    assert pj.seal_start_for(at(2026, 10, 8, 16, 0)) == date(2026, 10, 12)          # 휴장일(10-09 한글날)을 건너뜀
    assert pj.prev_trading_day(date(2026, 10, 26)) == date(2026, 10, 23)


# ── TC-PJ-08 한 행 하루 · 등급 · 재계산 ─────────────────────────────────────

def test_pj08_rows_chain_grade_and_recomputed(cdb):
    spec = pj.rule_spec(pj.RULE_CARD)
    version = {"spec": spec, "seal_start": date(2026, 9, 16), "watch_parts": pj.watch_parts()}
    days = [date(2026, 9, 14), date(2026, 9, 15), date(2026, 9, 16), date(2026, 9, 17)]
    now = datetime(2026, 9, 18, 13, 30, tzinfo=KST)
    prev, rows = None, []
    for d in days:
        r = _run(pj.compute_day(version, prev, d, now=now, commit="c", fingerprint="f", watch_now=version["watch_parts"]))
        rows.append(r)
        prev = r
    assert [r["grade"] for r in rows] == ["post_hoc", "post_hoc", "forward", "forward"]
    # 09-16 행은 예정(다음 거래일 09-17)보다 늦게(09-18) 계산 → 재계산 · 09-17 행은 예정일(09-18)과 같은 날 → 아님
    assert [r["recomputed"] for r in rows] == [False, False, True, False]
    for a, b in zip(rows, rows[1:]):                                    # 앞 행 주문 = 다음 행 체결
        assert [(o["symbol"], o["side"], o["qty"]) for o in a["orders"]] == \
            [(f["symbol"], f["side"], f["qty_ordered"]) for f in b["fills"]]
        assert all(f["decision_date"] == a["trade_date"] for f in b["fills"])
    assert all(r["decisions"] for r in rows) and rows[0]["fills"] == []    # 첫 행은 체결 없음 · 날마다 판단(관망 포함)
    assert sum(len(r["fills"]) for r in rows) >= 2, "사슬을 재려면 체결이 있어야 한다(합성 자료가 매수 신호를 낸다)"
    for r in rows[1:]:                                                   # 체결가 = 그날 원주가 시가 × (1 + 10bp)
        for f in r["fills"]:
            if f["side"] == "buy" and f["status"] != "unfilled":
                o = pj.raw_prices([f["symbol"]], date.fromisoformat(r["trade_date"]))[f["symbol"]]["open"]
                assert f["open"] == o and f["fill_price"] == round(o * 1.001, 4)
    again = _run(pj.compute_day(version, rows[1], days[2], now=now, commit="c", fingerprint="f",
                                watch_now=version["watch_parts"]))
    assert {k: v for k, v in again.items() if k != "computed_at"} == {k: v for k, v in rows[2].items() if k != "computed_at"}


def test_pj10_daily_loss_limit_is_flag_only(cdb):
    """하루 −3% 를 넘으면 표시만 — 주문은 이어 간다(10-24 결정 6)."""
    spec = pj.rule_spec(pj.RULE_CARD)
    version = {"spec": spec, "seal_start": date(2026, 9, 1), "watch_parts": pj.watch_parts()}
    d = date(2026, 9, 16)
    prev = {"trade_date": "2026-09-15", "cash": 0.0, "equity": 10_000_000.0, "orders": [],
            "positions": {CARD: {"qty": 200, "avg_price": 50_000.0, "name": "삼성전자"}}}
    _set(cdb, CARD, d, clpr=40_000, mkp=40_000)                          # 평가 8,000,000 → −20%
    r = _run(pj.compute_day(version, prev, d, now=datetime(2026, 9, 17, 13, 30, tzinfo=KST), commit="c",
                            fingerprint="f", watch_now=version["watch_parts"]))
    assert r["day_return"] < -0.03 and any("일손실 한도" in f for f in r["flags"]) and r["decisions"]


def test_pj11_watch_part_change_is_flagged_not_versioned(cdb):
    spec = pj.rule_spec(pj.RULE_CARD)
    version = {"spec": spec, "seal_start": date(2026, 9, 1), "watch_parts": {**pj.watch_parts(), "stock.get_candles": "0" * 12}}
    r = _run(pj.compute_day(version, None, date(2026, 9, 15), now=datetime(2026, 9, 16, 13, 30, tzinfo=KST),
                            commit="c", fingerprint="f", watch_now=pj.watch_parts()))
    assert any("참고 지문 바뀜 — stock.get_candles" in f for f in r["flags"])


# ── TC-PJ-09 원장 추가만 ─────────────────────────────────────────────────

def test_pj09_ledger_append_only(tmp_path):
    from scripts import paper_journal as cli

    v = {"id": 1, "rule_id": pj.RULE_CARD, "version_no": 1, "registered_at": datetime(2026, 10, 24, 13, 0, tzinfo=KST),
         "spec": {"a": 1}}
    day = {"trade_date": "2026-09-15", "fills": [], "decisions": [{"symbol": CARD, "action": "매수"}], "ranking": [],
           "orders": [], "skipped": [], "positions": {}, "flags": [], "cash": 1.0, "equity": 1.0, "day_return": 0.0}
    m1 = pj.write_export(pj.export_rows([v], [(v, day)], []), tmp_path / "a")
    m2 = pj.write_export(pj.export_rows([v], [(v, day)], []), tmp_path / "b")
    assert {k: x["content_sha256"] for k, x in m1["files"].items()} == {k: x["content_sha256"] for k, x in m2["files"].items()}
    assert m1["counts"] == {"version": 1, "day": 1, "note": 0}
    t = pd.read_parquet(tmp_path / "a" / "rows" / pj.RULE_CARD / "v1" / "2026-09-15.parquet")
    assert json.loads(t["decisions"][0])[0]["action"] == "매수" and t["rule_id"][0] == pj.RULE_CARD
    # 다음 날 행이 더해지면 새 파일 하나만 올리고, 지난 파일이 바뀌거나 없어지면 멈춘다
    day2 = {**day, "trade_date": "2026-09-16"}
    m3 = pj.write_export(pj.export_rows([v], [(v, day), (v, day2)], []), tmp_path / "c")
    new, bad = cli.plan_upload(m3, m1)
    assert new == ["rows/card_ma_cross_20_60/v1/2026-09-16.parquet"] and bad == []
    m4 = pj.write_export(pj.export_rows([v], [(v, {**day, "equity": 2.0})], []), tmp_path / "d")
    assert cli.plan_upload(m4, m1)[1] == ["rows/card_ma_cross_20_60/v1/2026-09-15.parquet — 내용이 바뀌었다"]
    assert "— 없어졌다" in cli.plan_upload({"files": {}}, m1)[1][0]


def test_pj12_service_has_no_update_or_delete():
    """세 표는 추가만 — 서비스에 고치기 · 지우기 문이 없다(INSERT · ON CONFLICT DO NOTHING 만). 구문 나무로 본다
    (사전의 `.update(` 는 SQL 이 아니다): SQLAlchemy `update` · `delete` 를 들여오거나 부르지 않고 · 세션 `.delete(` 가 없고 ·
    SQL 글자에 UPDATE · DELETE 가 없다."""
    import ast
    import re

    tree = ast.parse(inspect.getsource(pj))
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("sqlalchemy"):
            bad += [a.name for a in node.names if a.name in ("update", "delete")]
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name) and f.id in ("update", "delete"):
                bad.append(f.id)
            if isinstance(f, ast.Attribute) and f.attr in ("delete", "merge"):
                bad.append(f.attr)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and re.search(r"\b(UPDATE|DELETE)\s+(FROM\s+)?\w", node.value):
            bad.append(node.value[:40])
    assert bad == []
    assert "on_conflict_do_nothing" in inspect.getsource(pj)


# ── TC-PJ-13 러너 단계 ───────────────────────────────────────────────────

def test_pj13_runner_steps():
    from scripts import daily_update as du

    names = [s.name for s in du.STEPS]
    assert names.index("signals") + 1 == names.index("journal") and names.index("journal") + 1 == names.index("manifest")
    j = next(s for s in du.STEPS if s.name == "journal")
    # 여러 PC(2026-10-25) — 계산 앞에 HF 원장을 이 PC 앱 DB 로 받는다(``--pull`` · 받지 못하면 4 · 그날 계산 안 함)
    assert j.args == ["scripts/paper_journal.py", "daily", "--quiet", "--pull"] and j.app_db and not j.fatal and j.catch_up
    assert pj.EXIT_VERSION_CHANGED in j.warn_codes and not j.fill_args
    u = next(s for s in du.STEPS if s.name == "journal_upload")
    assert names.index("ohlcv_upload") + 1 == names.index("journal_upload")
    assert u.args == ["scripts/paper_journal.py", "upload", "--yes", "--quiet"] and u.upload and u.sharing
    assert not u.app_db and not u.fatal


# ── TC-PJ-14 판 등록 · 회차 (일회용 시험 DB) ───────────────────────────────

DB_URL = os.environ.get("QURIOUS_TEST_DATABASE_URL", "")


def _db(coro_fn):
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.models.paper_journal import PaperJournalDay, PaperJournalNote, PaperJournalVersion

    url = make_url(DB_URL)
    assert "test" in DB_URL and url.database != "fin_ai" and url.port != 15432, "일회용 시험 DB만 사용"
    tables = [PaperJournalVersion.__table__, PaperJournalDay.__table__, PaperJournalNote.__table__]

    async def go():
        engine = create_async_engine(DB_URL, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                for t in reversed(tables):
                    await conn.run_sync(lambda c, t=t: t.drop(c, checkfirst=True))
                for t in tables:
                    await conn.run_sync(lambda c, t=t: t.create(c))
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                return await coro_fn(session)
        finally:
            async with engine.begin() as conn:
                for t in reversed(tables):
                    await conn.run_sync(lambda c, t=t: t.drop(c, checkfirst=True))
            await engine.dispose()

    return asyncio.run(go())


@pytest.mark.skipif(not DB_URL, reason="일회용 시험 DB 없음 — scripts/personal/test.ps1 로 돈다")
def test_pj14_register_daily_idempotent_and_auto_version(cdb, monkeypatch):
    from sqlalchemy import func, select

    from app.models.paper_journal import PaperJournalDay, PaperJournalNote, PaperJournalVersion

    reg_at = datetime(2026, 9, 10, 10, 0, tzinfo=KST)                   # 목요일 장중 → 봉인 시작 09-10
    run_at = datetime(2026, 9, 18, 13, 30, tzinfo=KST)

    async def scenario(session):
        v1 = await pj.register(session, pj.RULE_CARD, now=reg_at, commit="test")
        await session.commit()
        assert (v1.version_no, v1.attempt_no, v1.seal_start, v1.post_hoc_from, v1.post_hoc_to) == \
            (1, 1, date(2026, 9, 10), date(2026, 9, 1), date(2026, 9, 9))
        with pytest.raises(ValueError):
            await pj.register(session, pj.RULE_CARD, now=reg_at)               # 판 1 은 한 번만(사람)
        s1 = await pj.run_daily(session, now=run_at, until=date(2026, 9, 17))
        n1 = await session.scalar(select(func.count()).select_from(PaperJournalDay))
        s2 = await pj.run_daily(session, now=run_at, until=date(2026, 9, 17))   # 같은 회차를 다시 — 줄이 늘지 않는다
        n2 = await session.scalar(select(func.count()).select_from(PaperJournalDay))
        grades = (await session.execute(select(PaperJournalDay.trade_date, PaperJournalDay.grade)
                                        .order_by(PaperJournalDay.trade_date))).all()
        # 규칙 코드가 바뀐 회차 — 기계가 판 2 를 등록하고 옛 판은 늘리지 않는다
        real = pj.fingerprint_parts
        monkeypatch.setattr(pj, "fingerprint_parts",
                            lambda rule_id, spec=None: {**real(rule_id, spec), "stock._generate_signal": "f" * 64})
        s3 = await pj.run_daily(session, now=datetime(2026, 9, 21, 13, 30, tzinfo=KST), until=date(2026, 9, 18))
        vers = (await session.execute(select(PaperJournalVersion).order_by(PaperJournalVersion.id))).scalars().all()
        n3 = await session.scalar(select(func.count()).select_from(PaperJournalDay).where(PaperJournalDay.version_id == v1.id))
        kinds = (await session.execute(select(PaperJournalNote.kind).order_by(PaperJournalNote.id))).scalars().all()
        return s1, s2, n1, n2, grades, s3, vers, n3, kinds

    s1, s2, n1, n2, grades, s3, vers, n3, kinds = _db(scenario)
    assert s1["rules"][pj.RULE_DEFAULT] == {"state": "unregistered"}
    assert s1["rules"][pj.RULE_CARD]["days"][0] == "2026-09-01" and n1 == n2 == 13 and s2["rows"] == 0
    assert all(g == ("post_hoc" if d < date(2026, 9, 10) else "forward") for d, g in grades)
    assert s3["changed"] == [{"rule_id": pj.RULE_CARD, "from_version": 1, "parts": ["stock._generate_signal"]}]
    assert [(v.version_no, v.registered_by, v.attempt_no) for v in vers] == [(1, "manual", 1), (2, "auto_fingerprint", 2)]
    assert vers[1].supersedes_id == vers[0].id and vers[1].change_parts == ["stock._generate_signal"]
    assert vers[1].post_hoc_from is None and vers[1].seal_start == date(2026, 9, 21)
    assert n3 == 13, "옛 판의 남은 날(09-18)은 계산하지 않는다"
    assert kinds == ["opening", "ops"]

# ── TC-PJ-17 · 18 원장 받기(여러 PC · 2026-10-25) ───────────────────────────────────────────

def test_pj17_ledger_round_trip_keeps_every_content_fingerprint(tmp_path):
    """TC-PJ-17 · 원장 파일 → 앱 DB 줄로 되돌린 값으로 다시 내보내면 모든 파일의 내용 지문이 원장과 같다(판 · 메모 번호 · 시각 · 날짜 ·
    묶음 칸 JSON · 실수) — 받아 넣은 PC 의 다음 올리기가 「추가만 위반」 으로 멈추지 않는 근거(DB 없이 도는 쪽)."""
    import types

    from scripts import paper_journal as cli

    v = {"id": 7, "rule_id": pj.RULE_CARD, "version_no": 1, "attempt_no": 1,
         "registered_at": datetime(2026, 10, 24, 13, 0, 5, tzinfo=KST), "registered_by": "manual",
         "seal_start": date(2026, 10, 26), "post_hoc_from": date(2026, 9, 1), "post_hoc_to": date(2026, 10, 23),
         "fingerprint": "f" * 64, "fingerprint_parts": {"stock._generate_signal": "a" * 12}, "watch_parts": {"auto": "b" * 12},
         "spec": {"symbols": [CARD], "slippage_bps": 10.0, "nested": {"x": [1, 2.5, None]}}, "code_commit": "abc", "python": "3.12.14",
         "supersedes_id": None, "change_parts": []}
    day = {"trade_date": "2026-09-15", "grade": "post_hoc", "status": "ok", "computed_at": "2026-10-24T13:01:02+09:00",
           "recomputed": False, "data_as_of": "2026-09-15", "code_commit": "abc", "fingerprint": "f" * 64,
           "fills": [{"symbol": CARD, "qty": 1, "price": 71234.5}], "decisions": [{"symbol": CARD, "action": "매수"}],
           "ranking": [], "orders": [], "skipped": [{"why": "비중 30% 상한"}], "cash": 9_928_765.5,
           "positions": {CARD: {"qty": 1, "avg": 71234.5}}, "equity": 9_999_999.25, "day_return": -0.000123456789, "flags": []}
    note = {"id": 3, "version_id": 7, "trade_date": date(2026, 10, 24), "kind": "opening", "author": "journal",
            "written_at": datetime(2026, 10, 24, 13, 0, 6, tzinfo=KST), "text": "사후 봉인 시험 구간을 열었다"}
    man = pj.write_export(pj.export_rows([v], [(v, day)], [note]), tmp_path / "ledger")
    back_v, back_d, back_n = [], [], []
    for rel in man["files"]:
        rec = cli._ledger_record(tmp_path / "ledger" / rel)
        if rel.startswith("versions/"):
            back_v.append(types.SimpleNamespace(**cli._version_row(rec)))
        elif rel.startswith("notes/"):
            back_n.append(cli._note_row(rec))
        else:
            back_d.append(types.SimpleNamespace(**cli._day_row(rec)))
    vd = pj.version_dict(back_v[0])
    again = pj.export_rows([vd], [(vd, pj.day_dict(d)) for d in back_d], back_n)
    assert set(again) == set(man["files"])
    for rel, meta in man["files"].items():
        assert pj.content_sha(again[rel]["record"]) == meta["content_sha256"], rel


@pytest.mark.skipif(not DB_URL, reason="일회용 시험 DB 없음 — scripts/personal/test.ps1 로 돈다")
def test_pj18_pull_imports_the_ledger_into_an_empty_app_db(cdb, tmp_path):
    """TC-PJ-18 · 판이 없는 PC(앱 DB 비었음)가 원장을 받으면 판 · 행 · 메모가 같은 번호로 들어가고 다시 내보낸 지문이 원장과 같다 ·
    다음 자동 번호는 그 뒤 · 두 번 받으면 0 · 같은 경로에 다른 내용이면 아무것도 쓰지 않고 멈춘다(conflict)."""
    from sqlalchemy import func, select

    from app.models.paper_journal import PaperJournalDay, PaperJournalNote, PaperJournalVersion
    from scripts import paper_journal as cli

    reg_at = datetime(2026, 9, 10, 10, 0, tzinfo=KST)
    run_at = datetime(2026, 9, 18, 13, 30, tzinfo=KST)
    ledger = tmp_path / "ledger"

    async def make_ledger(session):                              # 앞 PC — 등록 · 회차 · 내보내기(원장)
        await pj.register(session, pj.RULE_CARD, now=reg_at, commit="test")
        await session.commit()
        await pj.run_daily(session, now=run_at, until=date(2026, 9, 17))
        versions, days, notes = await pj.load_all(session)
        return pj.write_export(pj.export_rows(versions, days, notes), ledger)

    man = _db(make_ledger)

    async def pull_into_empty(session):                          # 이 PC — 일지 표가 빈 앱 DB
        first = await cli._pull(session, man, ledger)
        n_days = await session.scalar(select(func.count()).select_from(PaperJournalDay))
        vers = (await session.execute(select(PaperJournalVersion))).scalars().all()
        again = await cli._pull(session, man, ledger)
        note = await pj.add_note(session, kind="ops", text="받은 뒤 첫 메모", now=run_at)
        await session.commit()
        max_imported = max(int(rel.split("/")[1].split(".")[0]) for rel in man["files"] if rel.startswith("notes/"))
        return first, n_days, [(v.id, v.version_no, v.fingerprint) for v in vers], again, note.id, max_imported

    first, n_days, vers, again, note_id, max_imported = _db(pull_into_empty)
    assert first["state"] == "imported" and first["versions"] == 1 and first["rows"] == man["counts"]["day"] == n_days
    assert vers[0][0] == json.loads((ledger / f"versions/{pj.RULE_CARD}-v1.json").read_text(encoding="utf-8"))["id"]
    assert again == {"state": "same", "imported": 0}
    assert note_id > max_imported, "원장 번호를 넣은 뒤 자동 번호가 그 뒤로 간다(setval)"

    async def clash(session):                                    # 이 PC 에 같은 판 경로 · 다른 내용(따로 등록한 판)
        await pj.register(session, pj.RULE_CARD, now=datetime(2026, 9, 11, 10, 0, tzinfo=KST), commit="other")
        await session.commit()
        out = await cli._pull(session, man, ledger)
        n = await session.scalar(select(func.count()).select_from(PaperJournalDay))
        notes_n = await session.scalar(select(func.count()).select_from(PaperJournalNote))
        return out, n, notes_n

    out, n, notes_n = _db(clash)
    assert out["state"] == "conflict" and f"versions/{pj.RULE_CARD}-v1.json" in out["paths"] and n == 0


def test_pj19_pull_accepts_other_pyarrow_bytes_but_not_other_content(tmp_path):
    """TC-PJ-19 · 원장 받기는 바이트 지문이 아니라 내용 지문으로 같은 파일인지 본다 — pyarrow 판이 달라 같은 내용이 다른 바이트로
    쓰인 파일은 받아들이고(2026-10-28 · 원장 68 / 76 이 그랬다), 내용이 바뀌었거나 없는 파일은 거부한다."""
    import shutil
    import types

    import pyarrow.parquet as pq

    from scripts import paper_journal as cli

    day = {"trade_date": "2026-09-15", "grade": "post_hoc", "status": "ok", "computed_at": "2026-10-24T13:01:02+09:00",
           "recomputed": False, "data_as_of": "2026-09-15", "code_commit": "abc", "fingerprint": "f" * 64,
           "fills": [{"symbol": CARD, "qty": 1, "price": 71234.5}], "decisions": [], "ranking": [], "orders": [], "skipped": [],
           "cash": 9_928_765.5, "positions": {}, "equity": 9_999_999.25, "day_return": 0.0, "flags": []}
    v = {"id": 7, "rule_id": pj.RULE_CARD, "version_no": 1, "attempt_no": 1,
         "registered_at": datetime(2026, 10, 24, 13, 0, 5, tzinfo=KST), "registered_by": "manual",
         "seal_start": date(2026, 10, 26), "post_hoc_from": date(2026, 9, 1), "post_hoc_to": date(2026, 10, 23),
         "fingerprint": "f" * 64, "fingerprint_parts": {}, "watch_parts": {}, "spec": {"symbols": [CARD]}, "code_commit": "abc",
         "python": "3.12.14", "supersedes_id": None, "change_parts": []}
    src = tmp_path / "remote"
    man = pj.write_export(pj.export_rows([v], [(v, day)], []), src)
    (src / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    parquet = sorted(r for r in man["files"] if r.endswith(".parquet"))[0]

    class FakeApi:
        def __init__(self, folder):
            self.folder = folder

        def repo_info(self, repo, repo_type=None, timeout=None):
            return types.SimpleNamespace(sha="a" * 40)

        def snapshot_download(self, repo, repo_type=None, revision=None, local_dir=None):
            shutil.copytree(self.folder, local_dir, dirs_exist_ok=True)

    # 1) 바이트까지 같다
    head, got, root = cli._ledger_download(FakeApi(src))
    assert head == "a" * 40 and set(got["files"]) == set(man["files"])
    # 2) 같은 내용을 다른 바이트로 썼다(다른 pyarrow 판을 흉내 — 압축만 바꾼다) → 받아들인다
    other = tmp_path / "other"
    shutil.copytree(src, other)
    pq.write_table(pq.read_table(other / parquet), other / parquet, compression="gzip")
    assert (other / parquet).read_bytes() != (src / parquet).read_bytes()
    cli._ledger_download(FakeApi(other))
    # 3) 내용이 바뀌었다 → 거부
    bad = tmp_path / "bad"
    shutil.copytree(src, bad)
    tbl = pq.read_table(bad / parquet)
    pq.write_table(tbl.set_column(tbl.schema.get_field_index("cash"), "cash", tbl["cash"].cast("float64").to_pandas().add(1).pipe(
        lambda s: __import__("pyarrow").array(s))), bad / parquet)
    with pytest.raises(ValueError, match="지문 목록과 다르다"):
        cli._ledger_download(FakeApi(bad))
    # 4) 파일이 없다 → 거부
    gone = tmp_path / "gone"
    shutil.copytree(src, gone)
    (gone / parquet).unlink()
    with pytest.raises(ValueError, match="지문 목록과 다르다"):
        cli._ledger_download(FakeApi(gone))

def test_pj20_upload_manifest_keeps_remote_bytes_fingerprint_for_existing_files(): # 이슈 #377
    import scripts.paper_journal as cli

    remote = {"schema": 1, "files": {"rows/a.parquet": {"kind": "day", "bytes": 100, "sha256": "R" * 64, "content_sha256": "c1"}}}
    local = {"schema": 1, "counts": {"day": 2}, "files": {
        "rows/a.parquet": {"kind": "day", "bytes": 110, "sha256": "L" * 64, "content_sha256": "c1"},   # 같은 내용 · 다른 pyarrow 바이트
        "rows/b.parquet": {"kind": "day", "bytes": 50, "sha256": "N" * 64, "content_sha256": "c2"}}}      # 새 파일
    assert cli.plan_upload(local, remote) == (["rows/b.parquet"], [])
    merged = cli.keep_remote_meta(local, remote)
    assert merged["files"]["rows/a.parquet"] == remote["files"]["rows/a.parquet"]      # 원격에 있던 파일 = 원격 지문
    assert merged["files"]["rows/b.parquet"] == local["files"]["rows/b.parquet"]       # 새 파일 = 올리는 로컬 바이트 지문
    assert merged["counts"] == {"day": 2} and local["files"]["rows/a.parquet"]["sha256"] == "L" * 64   # 원본은 바꾸지 않는다
    assert cli.keep_remote_meta(local, {})["files"] == local["files"]                  # 첫 올리기 = 그대로
