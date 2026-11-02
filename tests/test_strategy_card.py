"""TC-CRD — 전략 카드 판 2 (인디케이터 전략 설계서 4.3 · #314 2026-10-27).

카드는 백테스트 · Pine 생성기 · 자동매매가 같은 명세를 읽는 자리라(`P02-①-2`), 칸 이름 · 값이 읽는 쪽 코드의
이름 · 범위와 같은지, 판 2 가 판 1 과 같은 매수 · 매도 판단을 내는지, 판단이 뒤 봉에 기대지 않는지를 본다.
판 2 카드를 백테스트 엔진과 자동매매 판 2 실행기(오준영 님 `strategy_v2` · 가상 다시 돌리기)에 같이 넣어 사고파는 날이
같은지, 종가 판정 · 자료 부족 · 시가 갭 같은 예외에서 두 쪽이 같은 쪽으로 움직이는지도 본다(2026-11-02).
주문 · LEAN 은 부르지 않는다. 판 1 파일은 그림자 일지 지문이라(#333) 읽기만 한다.
"""
import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import get_args

import pandas as pd
import pytest

from app.services.auto_trade import apply_strategy_spec_to_signal, evaluate_spec_rules
from app.services.collector_db import read_daily_candles
from app.services.execution_policy import ExecutionPolicy
from app.services.investment_research import backtest_strategy
from app.services import strategy_v2
from app.services.quant_pipeline import backtest, backtest_custom_indicator, preprocess
from app.services.strategy_v2_replay import replay
from app.services.ta_utils import sma
from app.services.trading_cost import KrxCostModel
from tests.conftest import make_candles

CARDS = Path(__file__).resolve().parents[1] / "docs/phase-3/02-design/system/예시"
V1 = json.loads((CARDS / "strategy-card-ma-cross-v1.json").read_text(encoding="utf-8"))
V2 = json.loads((CARDS / "strategy-card-ma-cross-v2.json").read_text(encoding="utf-8"))
REAL_DB = Path(__file__).resolve().parents[1] / "data" / "collector" / "market.sqlite3"


def _action(card: dict, closes: list[float]) -> str:
    return apply_strategy_spec_to_signal({"action": "관망", "score": 0}, card, indicators={"closes": closes})["action"]


def test_v2_keeps_v1_fields():
    assert (V2["strategy_id"], V2["version"]) == (V1["strategy_id"], 2)
    for key in V1.keys() - {"version", "name", "position_sizing"}:
        assert V2[key] == V1[key], key
    assert V1["position_sizing"].items() <= V2["position_sizing"].items()


def test_v2_names_and_values_match_readers():
    sizing = V2["position_sizing"]
    assert sizing["size_kind"] in get_args(ExecutionPolicy.model_fields["size_kind"].annotation)
    ExecutionPolicy(size_kind=sizing["size_kind"], risk_pct=sizing["risk_pct"])   # 자동매매 수량 설정의 이름 · 범위 그대로
    stops = V2["stops"]
    assert stops["stop_kind"] in ("pct", "atr") and stops["atr_period"] == 14 and stops["atr_mult"] > 0
    assert stops["take_kind"] == "rr" and 1.5 <= stops["take_rr"] <= 3
    assert stops["judge"] in ("close", "next_open", "intrabar") and stops["lock"] == "entry"
    assert V2["reentry"] == "new_signal" and V2["price_basis"] in ("raw", "adj_base")   # 앱 OHLCV 의 가격 기준 이름(data_ohlcv)


def test_v2_fill_timing_is_what_backtest_reads_and_reports():
    df = preprocess(make_candles(120))
    out = backtest(df, pd.Series(0, index=df.index), entry_mode=V2["entry_mode"], exit_mode=V2["exit_mode"])
    assert (out["entry_mode"], out["exit_mode"]) == (V2["entry_mode"], V2["exit_mode"])


def test_v2_judge_is_what_every_backtest_response_reports():
    # 세 백테스트 모두 손절 · 익절을 apply_stops(그날 종가)로 판정한다 — 응답이 카드 판 2 의 `stops.judge` 와 같은 값을 싣는다
    df = preprocess(make_candles(120))
    plain = backtest(df, pd.Series(0, index=df.index), stop_loss_pct=5.0)
    custom = backtest_custom_indicator(make_candles(300), base="rsi_ma", stop_loss_pct=5.0)
    strategy = backtest_strategy(make_candles(400), strategy="ma", stop_loss_pct=5.0)
    assert "error" not in strategy
    assert plain["judge"] == custom["costs"]["judge"] == strategy["judge"] == V2["stops"]["judge"]


def test_warmup_bars_is_where_the_card_starts_judging():
    windows = [V2["entry"]["params"]["long_window"], V2["entry"]["params"]["short_window"], V2["stops"]["atr_period"]]
    assert V2["warmup_bars"] == max(windows)
    closes = [100.0] * V2["warmup_bars"]
    assert evaluate_spec_rules(V2, {"closes": closes[:-1]}) is None
    assert evaluate_spec_rules(V2, {"closes": closes}) is not None


def test_v2_judges_like_v1():
    closes = preprocess(make_candles(300))["close"].astype(float).tolist()
    for k in range(V2["warmup_bars"] - 5, len(closes) + 1):
        assert _action(V2, closes[:k]) == _action(V1, closes[:k]), k


def test_v2_judgment_uses_only_the_last_warmup_bars():
    closes = preprocess(make_candles(300))["close"].astype(float).tolist()
    w = V2["warmup_bars"]
    for k in range(w, len(closes) + 1):
        assert _action(V2, closes[:k]) == _action(V2, closes[k - w:k]), k


@pytest.mark.skipif(not REAL_DB.is_file(), reason="수집 DB 가 없다(CI · 새 clone)")
def test_v2_judges_like_v1_on_005930():
    data = read_daily_candles("005930.KS", period="2y", today=date(2026, 8, 31), path=REAL_DB)
    closes = [float(c["close"]) for c in data["candles"]]
    assert len(closes) > V2["warmup_bars"]
    for k in range(V2["warmup_bars"], len(closes) + 1):
        assert _action(V2, closes[:k]) == _action(V1, closes[:k]), k


@pytest.mark.skipif(not REAL_DB.is_file(), reason="수집 DB 가 없다(CI · 새 clone)")
def test_수정주가는_원래_가격에_그날_계수를_곱한_값이라_ATR_을_원래_단위로_옮길_수_있다():
    # #366 — 판 2 의 ATR 은 수정주가로 재고 주문 · 일지는 원래 가격으로 체결한다. 식의 방향(수정 = 원래 × cum_factor)을
    # 계수가 바뀐 실제 종목에서 못 박는다: 판단 날 ATR(수정) ÷ cum_factor 가 그날 원래 가격 단위의 거리다.
    import sqlite3
    from app.services.price_basis import adjusted_to_raw

    con = sqlite3.connect(f"file:{REAL_DB}?mode=ro", uri=True)
    try:
        code, day = con.execute(
            "SELECT srtn_cd, MAX(bas_dt) FROM price_adjusted WHERE cum_factor < 0.9 GROUP BY srtn_cd ORDER BY srtn_cd LIMIT 1").fetchone()
        rows = con.execute(
            "SELECT a.bas_dt, p.clpr, a.adj_clpr, a.cum_factor FROM price_adjusted a JOIN price_daily p USING (bas_dt, srtn_cd) "
            "WHERE a.srtn_cd = ? AND a.bas_dt <= ? ORDER BY a.bas_dt DESC LIMIT 15", (code, day)).fetchall()
        latest = con.execute("SELECT cum_factor FROM price_adjusted WHERE srtn_cd = ? ORDER BY bas_dt DESC LIMIT 1", (code,)).fetchone()[0]
    finally:
        con.close()
    assert rows and latest == pytest.approx(1.0)                       # 가장 최근 날 계수는 1 — 평소 주문에서는 단위가 같다
    for _, raw, adj, factor in rows:
        assert factor < 0.9 and adj == pytest.approx(raw * factor)      # 계수가 바뀐 앞날들 — 수정 = 원래 × 계수
        atr_adj = 0.05 * adj                                           # 수정 단위의 거리 하나(값은 아무것)
        assert adjusted_to_raw(atr_adj, factor) == pytest.approx(0.05 * raw)


# ── 카드 → 백테스트 엔진 · 자동매매 판 2 실행기 대조 · 예외 (2026-11-02) ─────────────────────────────
# 두 쪽 모두 같은 카드(V2)를 읽는다. 엔진은 수정주가 OHLC 하나로, 자동매매는 원래 가격 + 그날 계수로 판단한다.

def _bars(rows) -> list[dict]:
    """(날짜, 시, 고, 저, 종, 계수, 거래정지) → 자동매매 실행기가 읽는 일봉 꼴(`strategy_v2.load_bars` 와 같은 칸)."""
    out = []
    for d, o, h, l, c, f, halted in rows:
        b = {"date": d, "open": o, "high": h, "low": l, "close": c, "factor": f, "halted": halted}
        b.update({"adjusted_" + k: b[k] * f for k in ("open", "high", "low", "close")})
        out.append(b)
    return out


def _frame(bars: list[dict]) -> pd.DataFrame:
    """엔진 입력 — 수정주가 OHLC(설계서 4.3 판단 가격 = 수정주가)."""
    df = pd.DataFrame([{k: b["adjusted_" + k] for k in ("open", "high", "low", "close")} for b in bars],
                      index=pd.to_datetime([b["date"] for b in bars]), dtype=float)
    return df


def _engine(df: pd.DataFrame) -> dict:
    p, st, ps = V2["entry"]["params"], V2["stops"], V2["position_sizing"]
    sig = (sma(df["close"], p["short_window"]) > sma(df["close"], p["long_window"])).astype(int)
    return backtest(df, sig, cost=KrxCostModel(), entry_mode=V2["entry_mode"], exit_mode=V2["exit_mode"],
                    atr_period=st["atr_period"], atr_mult=st["atr_mult"], take_rr=st["take_rr"],
                    risk_pct=ps["risk_pct"], max_position_pct=ps["max_position_pct"])


def _autotrade(bars: list[dict], monkeypatch) -> dict:
    # 거래일 달력은 넣은 일봉 날짜 그대로(이 시험은 달력이 아니라 판단을 본다)
    days = [b["date"] for b in bars]
    monkeypatch.setattr(strategy_v2.market_calendar, "trading_days", lambda s, e: {"partial": False, "days": [
        {"date": d, "is_trading_day": True} for d in days if s.isoformat() <= d <= e.isoformat()]})
    return replay(V2, bars, start=date.fromisoformat(days[V2["warmup_bars"] - 1]), initial_cash=10_000_000.0,
                  budget=10_000_000.0)


def _engine_trades(df: pd.DataFrame, res: dict) -> list[dict]:
    """엔진 거래 → 사는 판단 날 · 파는 판단 날 · 까닭 · 손절 · 익절선. 체결이 다음 봉 시가라 판단 날은 체결 앞 봉이다."""
    days = [d.date().isoformat() for d in df.index]
    at, close, rr = {d: i for i, d in enumerate(days)}, df["close"].to_numpy(), V2["stops"]["take_rr"]
    out = []
    for t in res["sizing"]["trades"]:
        stop, take = t["entry_price"] - t["stop_distance"], t["entry_price"] + rr * t["stop_distance"]
        row = {"buy": days[at[t["entry_date"][:10]] - 1], "sell": None, "why": None, "stop": stop, "take": take}
        if t["exit_date"]:
            j = at[t["exit_date"][:10]] - 1
            row.update(sell=days[j], why="STOP_CLOSE" if close[j] <= stop else "TAKE_CLOSE" if close[j] >= take else "EXIT_SIGNAL")
        out.append(row)
    return out


@pytest.mark.skipif(not REAL_DB.is_file(), reason="수집 DB 가 없다(CI · 새 clone)")
def test_v2_card_engine_and_autotrade_buy_and_sell_on_the_same_days_on_005930(monkeypatch):
    con = sqlite3.connect(f"file:{REAL_DB}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT p.bas_dt, p.mkp, p.hipr, p.lopr, p.clpr, a.cum_factor, p.halted FROM price_daily p "
            "JOIN price_adjusted a USING (bas_dt, srtn_cd) WHERE p.srtn_cd = '005930' AND p.bas_dt <= '20260831' "
            "ORDER BY p.bas_dt").fetchall()
    finally:
        con.close()
    bars = _bars([(f"{d[:4]}-{d[4:6]}-{d[6:]}", o, h, l, c, f, bool(x)) for d, o, h, l, c, f, x in rows])
    # 005930 은 이 기간 계수가 늘 1 · 거래정지 없음 — 조정 사건으로 갈리는 일 없이 판단만 맞댄다
    assert all(b["factor"] == 1 and not b["halted"] for b in bars)
    df = _frame(bars)
    eng = _engine_trades(df, _engine(df))
    auto = _autotrade(bars, monkeypatch)
    assert auto["status"] == "ok"
    buys = [f for f in auto["fills"] if f["side"] == "BUY"]
    sells = [f for f in auto["fills"] if f["side"] == "SELL"]
    assert len(eng) >= 10 and len(buys) == len(eng)

    rr, close = V2["stops"]["take_rr"], {b["date"]: b["close"] for b in bars}
    for e, b in zip(eng, buys):
        s = next((x for x in sells if x["signal_date"] > b["signal_date"]), None)
        assert b["signal_date"] == e["buy"]                              # 사는 판단 날은 늘 같다
        if s and (s["signal_date"], s["reason"]) == (e["sell"], e["why"]):
            continue
        # 갈린 곳은 손절 · 익절선을 잡은 가격 하나로만 설명된다 — 엔진은 그날 시가, 자동매매는 슬리피지를 더한 체결가.
        # 먼저 판 쪽의 그날 종가가 두 선 사이에 있어야 한다. 이 뒤로는 보유가 갈려 더 맞대지 않는다.
        a_stop, a_take = b["price"] - b["distance_raw"], b["price"] + rr * b["distance_raw"]
        c = close[min(d for d in (e["sell"], s and s["signal_date"]) if d)]
        assert min(e["stop"], a_stop) < c <= max(e["stop"], a_stop) or min(e["take"], a_take) <= c < max(e["take"], a_take)
        break


def _rising(n: int, start: str = "2025-03-03") -> list[tuple]:
    """매일 0.5 씩 오르는 일봉(고가 · 저가 ±1) — 단기 평균이 장기 평균 위라 준비 봉이 차면 바로 산다."""
    days = pd.bdate_range(start, periods=n)
    return [(d.date().isoformat(), 100 + i * 0.5, 101 + i * 0.5, 99 + i * 0.5, 100 + i * 0.5, 1.0, False) for i, d in enumerate(days)]


def test_close_judging_ignores_a_bar_that_pierces_both_stop_and_take_intraday(monkeypatch):
    # 판정은 종가(`stops.judge` = close) — 장중 저가가 손절선 아래 · 고가가 익절선 위여도 종가가 그 사이면 둘 다 그대로 들고 간다.
    # 그래서 판 2 에서는 「같은 봉에서 손절과 익절이 함께 걸리는」 일이 생기지 않는다(엔진은 그때 손절 먼저 · apply_stops).
    rows = _rising(70)
    d, o, h, l, c, f, x = rows[64]
    rows[64] = (d, o, c + 60, c - 60, c, f, x)
    bars = _bars(rows)
    res = _engine(_frame(bars))
    assert len(res["sizing"]["trades"]) == 1 and res["sizing"]["trades"][0]["exit_date"] is None
    assert (res["stop_loss_exits"], res["take_profit_exits"]) == (0, 0)
    auto = _autotrade(bars, monkeypatch)
    assert [f["side"] for f in auto["fills"]] == ["BUY"]


def test_short_data_is_refused_with_a_reason_on_both_sides():
    # 준비 봉이 모자라면 둘 다 판단하지 않고 까닭을 낸다 — 손절 거리 없이 사거나 빈 값으로 판단하지 않는다
    bars = _bars(_rising(V2["warmup_bars"] - 1))
    with pytest.raises(ValueError, match="60"):
        strategy_v2.judgment(V2, bars)
    df = _frame(bars)
    with pytest.raises(ValueError, match="ATR"):
        backtest(df, pd.Series(1, index=df.index), atr_period=14, atr_mult=V2["stops"]["atr_mult"], take_rr=2.0,
                 entry_mode="open", exit_mode="open", risk_pct=1.0)


def test_a_gap_up_open_never_buys_more_than_the_cash():
    # 수량은 판단 날 종가로 낸다(설계서 4.3 · #314 10-27 — 판단 시점까지의 자료만 · 갭에 따른 초과는 받아들임).
    # 다음 날 시가가 판단 종가의 10배로 뛰어도 산 금액 + 비용은 가진 현금을 넘지 않는다 — 한 종목 크기 합은 100% 안이다.
    rows = _rising(70)
    for i in range(V2["warmup_bars"], 70):
        d, *_ = rows[i]
        p = 2000 + i
        rows[i] = (d, p, p + 1, p - 1, p, 1.0, False)
    res = _engine(_frame(_bars(rows)))
    t = res["sizing"]["trades"][0]
    assert t["entry_price"] >= 10 * t["decision_price"]
    assert 0 < t["weight_pct"] <= 100.0
    assert t["quantity"] * t["entry_price"] < 10_000_000.0
