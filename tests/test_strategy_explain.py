"""성과 검증의 규칙 설명 (TC-RX · `P01-①-5`).

기본 전략 백테스트 응답의 `explanation` 은 그 전략의 매수 · 매도 규칙을 마지막 두 봉 값과 함께 보인다
(강사님 원본 2026-10-08 `0ca06dc` 의 `explain_strategy` · 시험을 우리 비용 모델 위에 받음 · #153 B2).
SHAP(다른 모델의 근거)은 이 응답에 붙이지 않는다. custom 은 설명을 비운다.
같은 화면(`indicator-backtest`)의 「비교에 추가」 단추 속성도 여기서 지킨다(#174).
"""
import asyncio
import re
from pathlib import Path

import pandas as pd
import pytest

from app.routes import stocks
from app.services import signal_explain as se
from app.services import trading_cost as tcost
from app.services.investment_research import _position, backtest_strategy, explain_strategy
from tests.conftest import make_candles

STRATEGIES = ["rsi", "ma", "bollinger", "composite"]
ROW = dict(close=100, ma5=100, ma20=100, rsi=50, macd=1, macd_signal=1, bb_lower=90, bb_upper=110)


def _two_bars(changes: dict) -> pd.DataFrame:
    return pd.DataFrame([ROW, ROW | changes], index=pd.date_range("2026-01-01", periods=2))


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_explanation_matches_backtest_signal(strategy):
    """설명의 판단 = 응답의 `latest_signal` · 기준일 = 마지막 봉 (설명이 백테스트와 어긋나지 않음)."""
    r = backtest_strategy(make_candles(400), strategy=strategy)
    xai = r["explanation"]
    assert xai["kind"] == "strategy_rules" and xai["strategy"] == strategy
    assert xai["action"] == r["latest_signal"]
    assert xai["as_of"][:10] == r["times"][-1][:10]
    assert xai["buy_conditions"] and xai["sell_conditions"]
    assert all(type(c["matched"]) is bool and c["observed"] for c in xai["buy_conditions"] + xai["sell_conditions"])


@pytest.mark.parametrize("cost", [tcost.NoCostModel(), tcost.build("real", market="KOSPI")])
def test_explanation_does_not_depend_on_cost(cost):
    """규칙 설명은 신호만 본다 — 우리 비용 모델(real · none)을 넘겨도 같은 설명."""
    candles = make_candles(400)
    base = backtest_strategy(candles, strategy="composite")["explanation"]
    assert backtest_strategy(candles, strategy="composite", cost=cost)["explanation"] == base


@pytest.mark.parametrize("strategy,changes,expected", [
    ("rsi", {"rsi": 29}, "BUY"), ("rsi", {"rsi": 30}, "HOLD"),
    ("ma", {"ma5": 101}, "BUY"), ("ma", {"ma5": 100}, "HOLD"),
    ("bollinger", {"close": 89}, "BUY"), ("bollinger", {"close": 90}, "HOLD"),
    ("composite", {"ma5": 101, "rsi": 51, "macd": 2}, "BUY"),
    ("composite", {"ma5": 101, "rsi": 50, "macd": 2}, "HOLD"),
])
def test_buy_boundaries(strategy, changes, expected):
    """경계값 — 부등호가 `_position` 과 같다(30 · 50 은 매수 아님)."""
    df = _two_bars(changes)
    xai = explain_strategy(df, strategy, _position(df, strategy))
    assert xai["action"] == expected
    assert all(c["matched"] for c in xai["buy_conditions"]) == (expected == "BUY")


@pytest.mark.parametrize("strategy,changes", [
    ("rsi", {"rsi": 71}), ("ma", {"ma5": 99}), ("bollinger", {"close": 111}),
    ("composite", {"ma5": 99}), ("composite", {"rsi": 76}),
])
def test_sell_conditions_from_held(strategy, changes):
    """보유 중 매도 조건 하나라도 충족 → 매도 전환."""
    df = _two_bars(changes)
    xai = explain_strategy(df, strategy, pd.Series([1.0, 0.0], index=df.index))
    assert xai["action"] == "SELL" and xai["position"] == "현금 대기"
    assert any(c["matched"] for c in xai["sell_conditions"])


def test_wording_has_no_forbidden_words():
    """화면에 나가는 낱말 — #169 신호 설명과 같은 금지어를 쓰지 않는다."""
    texts = []
    for s in STRATEGIES:
        x = backtest_strategy(make_candles(400), strategy=s)["explanation"]
        texts += [x["scope"], x["position"], x["buy_logic"], x["sell_logic"]]
        texts += [c[k] for c in x["buy_conditions"] + x["sell_conditions"] for k in ("label", "rule")]
    assert not [t for t in texts if any(w in t for w in se.FORBIDDEN)]


def _call_route(monkeypatch, strategy):
    async def fake_candles(symbol, period, interval):
        return {"candles": make_candles(400)}

    async def no_cache(*a, **k):
        raise AssertionError("성과 검증 응답은 SHAP 캐시를 읽지 않는다")

    monkeypatch.setattr(stocks, "get_candles", fake_candles)
    monkeypatch.setattr(stocks, "cache_get", no_cache)
    return asyncio.run(stocks.quant_pipeline_indicator_backtest(
        symbol="005930.KS", period="10y", base="rsi_ma", short=5, mid=20, rsi=14, buy_th=35.0,
        strategy=strategy, cost_bps=None, cost_model=None, slippage_bps=None, market=None,
        stop_loss_pct=None, take_profit_pct=None, _user=None,
    ))


def test_route_returns_rule_explanation_not_shap(monkeypatch):
    r = _call_route(monkeypatch, "rsi")
    assert r["explanation"]["kind"] == "strategy_rules"
    assert r["cost"]["model"] == "krx_real"  # 비용 인자 없는 요청 = real (우리 기본 · #134)


def test_route_custom_has_no_explanation(monkeypatch):
    assert _call_route(monkeypatch, "custom")["explanation"] is None


def test_compare_button_onclick_closes_after_paren():
    """「비교에 추가」 단추 — `onclick='compareTrayAdd(…)'` 의 작은따옴표가 `)` 뒤에서 닫힌다(#174).

    앞에서 닫히면 속성 값이 `compareTrayAdd({…}` 에서 끊겨 누를 때 문법 오류가 난다(강사님 `3a135b1` 과 같은 고침).
    """
    js = (Path(__file__).resolve().parents[1] / "public" / "js" / "indicator.js").read_text(encoding="utf-8")
    buttons = re.findall(r"onclick='compareTrayAdd\(.*?</button>", js, flags=re.S)
    assert buttons, "성과 검증의 「비교에 추가」 단추를 찾지 못했다"
    for b in buttons:
        assert b.endswith("})'>⚖️ 비교에 추가</button>"), b[-60:]
