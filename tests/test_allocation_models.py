"""자산군 모델의 수학적 성질·시점·실패 처리를 독립 기대값과 대조한다."""
from decimal import Decimal
from types import SimpleNamespace

import numpy as np
import pytest

from app.services import allocation_models as models
from app.services.asset_allocation import asset_allocation, rebalance_draft
from tests.test_portfolio_allocation_constraints import candles


def inputs():
    return [{"symbol": name, "candles": candles(i + 8, count=181, volatility=.005 + i * .003)}
            for i, name in enumerate(models.ASSET_PROXIES)]


def calculate(model, **kwargs):
    return models.calculate_allocation(model, inputs(), asset_allocation("moderate", 3),
                                       as_of="2025-06-30", **kwargs)


def test_risk_parity_matches_analytic_diagonal_solution():
    vol = np.array([.2, .3, .4, .1])
    cov = np.diag(vol ** 2)
    weights = models.solve_weights(cov, risk_parity=True)
    assert weights == pytest.approx((1 / vol) / (1 / vol).sum(), abs=1e-6)
    assert models.risk_shares(weights, cov) == pytest.approx([.25] * 4, abs=1e-6)


def test_minimum_variance_matches_analytic_diagonal_solution():
    variance = np.array([.04, .09, .16, .01])
    cov = np.diag(variance)
    weights = models.solve_weights(cov)
    assert weights == pytest.approx((1 / variance) / (1 / variance).sum(), abs=1e-5)
    equal = np.ones(4) / 4
    assert weights @ cov @ weights < equal @ cov @ equal


def test_minimum_variance_honors_binding_cap():
    weights = models.solve_weights(np.diag([.000001, 1, 1, 1]))
    assert weights[0] == pytest.approx(.95)
    assert sum(weights) == pytest.approx(1)


def test_black_litterman_relative_view_and_confidence_have_correct_direction():
    labels = list(models.ASSET_PROXIES)
    cov = np.eye(4) * .04
    baseline = np.ones(4) / 4
    changes = []
    for confidence in (0, 30, 90):
        view = dict(asset=labels[0], relative_to=labels[1], outperformance_pct=5, confidence_pct=confidence)
        weights, prior, posterior = models.black_litterman(cov, baseline, [view], labels)
        changes.append(weights[0] - weights[1])
        # 선형 Gaussian 업데이트의 독립 스칼라 해: 사전 상대수익 0, 신뢰도 c → c * 5%.
        assert posterior[0] - posterior[1] == pytest.approx(confidence / 100 * .05)
        assert posterior[2:] == pytest.approx(prior[2:])
    assert changes[0] == 0 < changes[1] < changes[2]


@pytest.mark.parametrize("model", list(models.MODELS))
@pytest.mark.parametrize("profile", ["conservative", "moderate", "aggressive"])
def test_model_output_reproducible_and_exact_total(model, profile):
    base = asset_allocation(profile, 3)
    result = models.calculate_allocation(model, inputs(), base, as_of="2025-06-30")
    assert result == models.calculate_allocation(model, inputs(), base, as_of="2025-06-30")
    assert sum(Decimal(str(w)) for w in result["allocations"].values()) == Decimal(100)
    assert all(0 <= w <= 100 for w in result["allocations"].values())
    assert sum(result["risk_contribution_pct"].values()) == pytest.approx(100, abs=.002)
    assert result["observations"] == 180
    if model != "regime":
        assert result["allocations"]["현금"] == base["현금"]
        invested = 100 - base["현금"]
        assert all(.01 <= result["allocations"][a] / invested <= .95 for a in models.ASSET_PROXIES)
    if model == "black_litterman":
        assert result["allocations"] == base
        assert result["benchmark_source"] == "risk_profile"


def test_custom_benchmark_no_views_and_zero_confidence_preserve_baseline():
    baseline = dict(국내주식=25, 해외주식=30, 국내채권=20, 대체자산=15, 현금=10)
    zero = dict(asset="국내주식", relative_to="해외주식", outperformance_pct=50, confidence_pct=0)
    for views in ([], [zero]):
        result = calculate("black_litterman", benchmark=baseline, views=views)
        assert result["allocations"] == baseline
        assert result["benchmark_source"] == "user"


@pytest.mark.parametrize("trend", ["up", "down"])
@pytest.mark.parametrize("vol", ["high", "low"])
def test_regime_four_states_and_target_changes(trend, vol):
    import pandas as pd
    r = np.full(180, .004 if trend == "up" else -.004)
    r[-20:] += np.tile([-.03, .03] if vol == "high" else [-.001, .001], 10)
    data = inputs()
    prices = 100 * np.cumprod(np.r_[1., 1 + r])
    for candle, price in zip(data[0]["candles"], prices):
        candle["close"] = float(price)
    state = models.detect_regime(pd.DataFrame({"국내주식": r}))
    assert state["key"] == f"{trend}_{vol}"
    base = asset_allocation("moderate", 3)
    result = models.calculate_allocation("regime", data, base, as_of="2025-06-30")
    old_equity = base["국내주식"] + base["해외주식"]
    new_equity = result["allocations"]["국내주식"] + result["allocations"]["해외주식"]
    assert new_equity == pytest.approx(old_equity * state["equity_multiplier"], abs=.1)
    if trend == "down" or vol == "high":
        assert result["allocations"]["현금"] > base["현금"]


@pytest.mark.parametrize("model", list(models.MODELS))
def test_future_price_changes_cannot_change_past_allocation(model):
    data = inputs()
    base = asset_allocation("moderate", 3)
    before = models.calculate_allocation(model, data, base, as_of="2025-05-20")
    for item in data:
        for candle in item["candles"][150:]:
            candle["close"] *= 100
    assert models.calculate_allocation(model, data, base, as_of="2025-05-20") == before


@pytest.mark.parametrize("defect", ["missing", "stale", "duplicate", "nonfinite", "negative", "short", "unaligned"])
def test_bad_proxy_data_rejected(defect):
    data = inputs()
    candles_ = data[0]["candles"]
    if defect == "missing":
        data[0]["candles"] = []
    elif defect == "stale":
        candles_.pop()
    elif defect == "duplicate":
        candles_.append(candles_[-1])
    elif defect == "nonfinite":
        candles_[10]["close"] = float("nan")
    elif defect == "negative":
        candles_[10]["close"] = -1
    elif defect == "short":
        for item in data:
            item["candles"] = item["candles"][-60:]
    else:
        data[0]["candles"] = candles(3, count=181, offset=121)
    with pytest.raises(ValueError):
        models.calculate_allocation("risk_parity", data, asset_allocation("moderate", 3), as_of="2025-06-30")


def test_missing_day_does_not_mix_one_and_two_day_returns():
    data = inputs()
    del data[0]["candles"][10]
    ret = models.common_returns(data, as_of="2025-06-30")
    assert len(ret) == 178  # 해당 날짜와 그 다음 수익률 모두 제외


def test_solver_failure_is_reported_without_fallback_weights(monkeypatch):
    monkeypatch.setattr(models, "minimize", lambda *a, **k: SimpleNamespace(success=False, x=np.ones(4) / 4))
    with pytest.raises(ValueError, match="수렴"):
        calculate("risk_parity")


@pytest.mark.parametrize("views", [
    [dict(asset="국내주식", relative_to="국내주식", outperformance_pct=3, confidence_pct=50)],
    [dict(asset="국내주식", relative_to="해외주식", outperformance_pct=3, confidence_pct=100)],
    [dict(asset="국내주식", relative_to="해외주식", outperformance_pct=3, confidence_pct=50)] * 2,
])
def test_invalid_views_rejected(views):
    with pytest.raises(ValueError):
        calculate("black_litterman", views=views)


def test_allocation_is_preserved_in_existing_rebalance_handoff():
    result = calculate("regime")
    draft = rebalance_draft({"allocations": result["allocations"],
                             "optimization": {"weights": {"005930.KS": 60, "000660.KS": 40}},
                             "stock_picks": []})
    assert sum(t["weight_pct"] for t in draft["targets"]) == pytest.approx(result["allocations"]["국내주식"])
    assert draft["cash_weight_pct"] + draft["domestic_weight_pct"] == 100
