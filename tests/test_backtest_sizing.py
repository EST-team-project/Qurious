"""TC-BSZ — 백테스트 위험 % 수량(quant_pipeline.size_positions · 전략 카드 판 2 · #161 A2 · #314) · 2026-10-30

1. 수량 = 오준영 님 `risk_quantity` 결과 — 위험 1% ÷ 비용 포함 1주 손실 · 판단 날 종가로 계산. (TC-BSZ-01)
2. 종목 비중 상한(30%)이 위험 수량보다 작으면 상한이 수량을 정한다. (TC-BSZ-02)
3. 평가액 = 현금 + 주 수 × 종가 — 거래 손익(비용 뗀 뒤) 합 = 마지막 평가액 − 시작 자금 · 수익률도 같다. (TC-BSZ-03)
4. 판단 시점까지의 자료만 — 진입 날의 시가 · 종가를 바꿔도 수량이 같다(현금이 모자라지 않을 때). (TC-BSZ-04)
5. `risk_pct` 를 안 주면 결과가 예전과 같고 `sizing` 칸이 없다 · 손절 거리가 없으면 오류. (TC-BSZ-05)
6. 판 2 카드(ATR 14 × 2 · 손익비 2 · 다음 시가 · 국내 실제 요율)로 돌면 보유 · 손절 · 익절 · 매매 횟수는 전액 진입과 같고,
   거래마다 예상 손실이 위험 예산을 넘지 않는다. (TC-BSZ-06)
7. 비용 모델에서 뽑은 날짜별 매수율 · 매도율이 `trading_cost.cost_rate` 와 같다. (TC-BSZ-07)
8. `sizing` 칸은 넘파이 수 없이 JSON 으로 그대로 나간다. (TC-BSZ-08)
"""
from __future__ import annotations

import pandas as pd
import pytest

from app.services import quant_pipeline as qp
from app.services import trading_cost
from app.services.execution_policy import risk_quantity
from app.services.quant_pipeline import backtest, feature_engineer, preprocess
from tests.conftest import make_candles

CAP = 10_000_000.0


def _frame(closes, opens=None):
    idx = pd.date_range("2026-03-02", periods=len(closes), freq="B")
    c = pd.Series(closes, index=idx, dtype=float)
    o = pd.Series(opens if opens is not None else closes, index=idx, dtype=float)
    return pd.DataFrame({"open": o, "high": c * 1.01, "low": c * 0.99, "close": c})


def _sig(n, on, off):
    s = pd.Series(0, index=pd.date_range("2026-03-02", periods=n, freq="B"))
    s.iloc[on:off] = 1
    return s


def test_quantity_is_risk_quantity_at_decision_close():
    df = _frame([10_000, 10_000, 10_200, 10_400, 10_100, 10_300, 10_500, 10_600])
    res = backtest(df, _sig(8, 1, 6), stop_loss_pct=5, risk_pct=1.0)
    t = res["sizing"]["trades"][0]
    # 신호 1일 → 보유 2일차부터 · 판단은 2일차 전날(신호 날) 종가 10,000
    want = risk_quantity(equity=CAP, cash=CAP, price=10_000, stop_price=9_500, budget=CAP, existing_value=0,
                         position_cap_pct=30.0, risk_pct=1.0, slippage_bps=0, when=df.index[1], market="KOSPI")
    assert t["quantity"] == want["quantity"] > 0
    assert t["decision_price"] == 10_000 and t["stop_distance"] == pytest.approx(500)
    assert t["estimated_loss"] <= CAP * 0.01


def test_position_cap_limits_quantity():
    df = _frame([10_000] * 3 + [10_100] * 5)
    res = backtest(df, _sig(8, 1, 6), stop_loss_pct=0.5, risk_pct=1.0)   # 위험 수량 ≈ 1,800주 > 상한 300주
    t = res["sizing"]["trades"][0]
    assert t["quantity"] == 300
    assert t["weight_pct"] <= 30.0


def test_equity_matches_trade_pnl():
    df = feature_engineer(preprocess(make_candles(260)))
    sig = pd.Series(0, index=df.index)
    sig.iloc[20:60] = 1
    sig.iloc[100:150] = 1
    cost = trading_cost.KrxCostModel()
    res = backtest(df, sig, cost=cost, entry_mode="open", exit_mode="open", stop_loss_pct=4, risk_pct=1.0)
    s = res["sizing"]
    assert len(s["trades"]) == 2
    assert sum(t["pnl"] for t in s["trades"]) == pytest.approx(s["final_equity"] - CAP, abs=0.05)
    assert res["total_return_pct"] == pytest.approx((s["final_equity"] / CAP - 1) * 100, abs=0.01)
    assert res["cost_pct"] > 0 and res["gross_return_pct"] > res["total_return_pct"]


def test_entry_day_prices_do_not_change_quantity():
    base = [10_000, 10_000, 10_200, 10_400, 10_100, 10_300, 10_500, 10_600]
    a = backtest(_frame(base), _sig(8, 1, 6), stop_loss_pct=5, risk_pct=1.0, entry_mode="open", exit_mode="open")
    moved = list(base)
    moved[2] = 9_000                                     # 진입 날(보유 2일차) 종가
    opens = list(base)
    opens[2] = 10_300                                    # 진입 날 시가(체결가)
    b = backtest(_frame(moved, opens), _sig(8, 1, 6), stop_loss_pct=5, risk_pct=1.0, entry_mode="open", exit_mode="open")
    assert a["sizing"]["trades"][0]["quantity"] == b["sizing"]["trades"][0]["quantity"]
    assert b["sizing"]["trades"][0]["entry_price"] == 10_300


def test_without_risk_pct_result_is_unchanged():
    df = feature_engineer(preprocess(make_candles(260)))
    sig = pd.Series(0, index=df.index)
    sig.iloc[20:60] = 1
    old = backtest(df, sig, cost=trading_cost.KrxCostModel(), entry_mode="open", exit_mode="open", stop_loss_pct=4)
    assert "sizing" not in old
    assert old["total_return_pct"] == backtest(df, sig, cost=trading_cost.KrxCostModel(), entry_mode="open",
                                               exit_mode="open", stop_loss_pct=4, risk_pct=None)["total_return_pct"]
    with pytest.raises(ValueError, match="손절 거리"):
        backtest(df, sig, risk_pct=1.0)


def test_card_v2_keeps_exits_and_caps_risk():
    df = feature_engineer(preprocess(make_candles(400)))
    sig = (df["close"].rolling(20).mean() > df["close"].rolling(60).mean()).astype(int)
    kw = dict(cost=trading_cost.KrxCostModel(), entry_mode="open", exit_mode="open",
              atr_period=14, atr_mult=2.0, take_rr=2.0)
    full = backtest(df, sig, **kw)
    sized = backtest(df, sig, risk_pct=1.0, **kw)
    for k in ("trade_count", "stop_loss_exits", "take_profit_exits"):
        assert sized[k] == full[k]
    trades = sized["sizing"]["trades"]
    assert trades and all(t["estimated_loss"] <= t["risk_budget"] + 1e-6 for t in trades)
    assert all(0 < t["weight_pct"] <= 30.0 for t in trades)
    # 전액이 아니라 일부만 들어가므로 수익 · 손실 폭이 전액 진입보다 작다
    assert abs(sized["total_return_pct"]) < abs(full["total_return_pct"])


def test_side_rates_match_cost_rate():
    idx = pd.to_datetime(["2023-03-02", "2024-03-04", "2025-03-04", "2026-03-03", "2026-03-04"])
    cost = trading_cost.KrxCostModel()
    buy, sell = qp._side_rates(cost, idx)
    for i, d in enumerate(idx):
        assert buy[i] == pytest.approx(trading_cost.cost_rate("buy", d, cost.slippage_bps))
        if i:
            assert sell[i] == pytest.approx(trading_cost.cost_rate("sell", d, cost.slippage_bps))


def test_sizing_result_is_plain_json():
    import json
    df = feature_engineer(preprocess(make_candles(260)))
    sig = pd.Series(0, index=df.index)
    sig.iloc[20:60] = 1
    res = backtest(df, sig, cost=trading_cost.KrxCostModel(), entry_mode="open", exit_mode="open", stop_loss_pct=4, risk_pct=1.0)
    json.dumps(res["sizing"])                            # 넘파이 수가 섞이면 API 응답 · 결과 파일에서 깨진다
