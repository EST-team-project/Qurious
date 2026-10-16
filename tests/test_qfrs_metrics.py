"""QFRS 성과 지표 — 순수 계산 시험 (TC-QFRS).

- maximum_drawdown · average_drawdown · calculate_all_metrics
- 코스콤 테스트베드 기준 지표 (MDD · Sharpe · Sortino · Sterling · Calmar · DSR)
- DB 없이 도는 순수 함수 시험 (P01-④-1 · P02-④-2)

관련:
- app/services/evaluation_risk.py
- app/services/performance_service.py (get_robo_metrics · 통합 · DB 필요)
"""
import numpy as np
import pytest

from app.services.evaluation_risk import (
    average_drawdown,
    calculate_all_metrics,
    maximum_drawdown,
)

KEYS = {"MDD", "Sharpe Ratio", "Sortino Ratio", "Sterling Ratio",
        "Calmar Ratio", "Deflated Sharpe Ratio"}


# ── maximum_drawdown ──────────────────────────────────────────────

def test_mdd_empty_returns_nan():
    assert np.isnan(maximum_drawdown(np.array([])))


def test_mdd_all_positive_is_zero():
    returns = np.array([0.01, 0.02, 0.01, 0.03])
    assert maximum_drawdown(returns) == pytest.approx(0.0, abs=1e-9)


def test_mdd_monotone_decline_matches_compounding():
    # 앞에 0(기준점) + -5% × 4번 → 낙폭 = 1 - 0.95^4
    returns = np.array([0.0, -0.05, -0.05, -0.05, -0.05])
    expected = 1 - (0.95 ** 4)
    assert maximum_drawdown(returns) == pytest.approx(expected, abs=1e-6)


def test_mdd_recovery_uses_peak_then_trough():
    # +10% 뒤 -20% (꼭대기 대비 저점) → 낙폭 20%
    returns = np.array([0.10, -0.20, 0.05, 0.05])
    mdd = maximum_drawdown(returns)
    # 누적: 1.10 → 0.88 → 0.924 → 0.9702, 최고 1.10 대비 최저 0.88 → 0.20
    assert mdd == pytest.approx(0.20, abs=1e-6)


# ── average_drawdown ──────────────────────────────────────────────

def test_average_drawdown_all_positive_is_zero():
    returns = np.array([0.01, 0.02, 0.01, 0.03])
    assert average_drawdown(returns) == pytest.approx(0.0, abs=1e-9)


def test_average_drawdown_positive_when_drawdown_exists():
    returns = np.array([0.10, -0.10, 0.05, -0.05])
    avg = average_drawdown(returns)
    assert avg > 0


# ── calculate_all_metrics ─────────────────────────────────────────

def test_all_metrics_has_six_keys():
    rng = np.random.default_rng(42)
    returns = rng.normal(0.0005, 0.01, 252)
    m = calculate_all_metrics(returns)
    assert set(m.keys()) == KEYS


def test_all_metrics_insufficient_returns_all_nan():
    m = calculate_all_metrics(np.array([0.01]))
    for k, v in m.items():
        assert np.isnan(v), f"{k} 이 NaN 이 아님: {v}"


def test_all_metrics_mdd_matches_manual():
    returns = np.array([0.0, -0.05, -0.05, -0.05, -0.05])
    m = calculate_all_metrics(returns)
    assert m["MDD"] == pytest.approx(1 - 0.95 ** 4, abs=1e-6)


def test_sharpe_positive_for_positive_drift():
    rng = np.random.default_rng(7)
    returns = rng.normal(0.002, 0.01, 500)
    m = calculate_all_metrics(returns, risk_free_rate=0.0)
    assert m["Sharpe Ratio"] > 0


def test_sharpe_negative_for_negative_drift():
    rng = np.random.default_rng(7)
    returns = rng.normal(-0.002, 0.01, 500)
    m = calculate_all_metrics(returns, risk_free_rate=0.0)
    assert m["Sharpe Ratio"] < 0


def test_sortino_finite_with_volatility():
    rng = np.random.default_rng(13)
    returns = rng.normal(0.0005, 0.015, 500)
    m = calculate_all_metrics(returns, risk_free_rate=0.0)
    assert np.isfinite(m["Sortino Ratio"])


def test_dsr_present_after_enough_trials():
    rng = np.random.default_rng(11)
    returns = rng.normal(0.001, 0.01, 500)
    m = calculate_all_metrics(returns, n_trials=50)
    dsr = m["Deflated Sharpe Ratio"]
    # DSR 은 확률(0~1) 또는 NaN — 유한하면 범위 확인
    if np.isfinite(dsr):
        assert 0.0 <= dsr <= 1.0


def test_sterling_calmar_present_when_mdd_exists():
    rng = np.random.default_rng(17)
    returns = rng.normal(0.0005, 0.02, 500)
    m = calculate_all_metrics(returns)
    # 두 값이 있기만 하면 됨 (MDD 유무에 따라 finite/NaN)
    assert "Sterling Ratio" in m
    assert "Calmar Ratio" in m


def test_all_metrics_is_deterministic():
    """같은 입력이면 같은 출력 (설명 기준 「정확」)."""
    rng = np.random.default_rng(99)
    returns = rng.normal(0.0007, 0.012, 300)
    m1 = calculate_all_metrics(returns)
    m2 = calculate_all_metrics(returns)
    for k in KEYS:
        assert m1[k] == m2[k]