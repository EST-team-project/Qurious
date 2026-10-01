# app/services/evaluation_risk.py
"""
QFRS (Quantitative Finance Research) 기반 성과·리스크 지표.

참고 논문:
- Bailey & Lopez de Prado (2014) — Deflated Sharpe Ratio
- Khushi (2026) — 본 프로젝트 성과 검증 방법론

⚠️ 알파스택 원본(HF 의존성)에서 이식. 입력은 numpy array만 받음.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
from scipy.stats import kurtosis, norm, skew


# ═══════════════════════════════════════════════════════════
# 1. Maximum Drawdown
# ═══════════════════════════════════════════════════════════
def maximum_drawdown(returns: np.ndarray) -> float:
    """MDD — 최대 낙폭 (양수 반환)."""
    returns = np.asarray(returns, dtype=float)
    if len(returns) == 0:
        return float("nan")
    cumulative = np.cumprod(1 + returns)
    running_max = np.maximum.accumulate(cumulative)
    drawdown = cumulative / running_max - 1
    return float(abs(np.min(drawdown)))


def average_drawdown(returns: np.ndarray) -> float:
    """평균 낙폭 (양수)."""
    returns = np.asarray(returns, dtype=float)
    cumulative = np.cumprod(1 + returns)
    running_max = np.maximum.accumulate(cumulative)
    drawdown = cumulative / running_max - 1
    return float(abs(np.mean(drawdown)))


def _get_drawdown_periods(returns: np.ndarray) -> List[float]:
    """각 하락 구간(Drawdown Episode)의 최대 깊이 리스트."""
    returns = np.asarray(returns, dtype=float)
    cumulative = np.cumprod(1 + returns)
    running_max = np.maximum.accumulate(cumulative)
    drawdown_series = cumulative / running_max - 1

    periods = []
    i = 0
    while i < len(drawdown_series):
        if drawdown_series[i] < 0:
            max_dd = drawdown_series[i]
            while i < len(drawdown_series) and drawdown_series[i] < 0:
                if drawdown_series[i] < max_dd:
                    max_dd = drawdown_series[i]
                i += 1
            periods.append(abs(max_dd))
        else:
            i += 1
    return periods


# ═══════════════════════════════════════════════════════════
# 2. Sharpe / Sortino
# ═══════════════════════════════════════════════════════════
def sharpe_ratio(
    returns: np.ndarray,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
) -> float:
    """연환산 샤프 비율."""
    returns = np.asarray(returns, dtype=float)
    if len(returns) < 2:
        return float("nan")

    rf_period = (1 + risk_free_rate) ** (1 / periods_per_year) - 1
    excess = returns - rf_period
    std = np.std(excess, ddof=1)
    if std == 0:
        return float("nan")
    return float((np.mean(excess) / std) * np.sqrt(periods_per_year))


def sortino_ratio(
    returns: np.ndarray,
    target_return: float = 0.0,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
) -> float:
    """연환산 소티노 비율 (하방 변동성만 사용)."""
    returns = np.asarray(returns, dtype=float)
    if len(returns) < 2:
        return float("nan")

    rf_period = (1 + risk_free_rate) ** (1 / periods_per_year) - 1
    excess = returns - rf_period
    downside = np.minimum(excess - target_return, 0)
    downside_dev = np.sqrt(np.mean(downside**2))
    if downside_dev == 0:
        return float("nan")

    ann_excess = np.mean(excess) * periods_per_year
    ann_downside = downside_dev * np.sqrt(periods_per_year)
    return float(ann_excess / ann_downside)


# ═══════════════════════════════════════════════════════════
# 3. Sterling / Calmar
# ═══════════════════════════════════════════════════════════
def sterling_ratio(
    returns: np.ndarray,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
    top_k: Optional[int] = 3,
) -> float:
    """스털링 비율 — 상위 K개 MDD 평균 대비 초과수익."""
    returns = np.asarray(returns, dtype=float)
    if len(returns) < 2:
        return float("nan")

    n = len(returns)
    ann_return = np.prod(1 + returns) ** (periods_per_year / n) - 1
    excess = ann_return - risk_free_rate

    if top_k is not None and top_k > 0:
        periods = _get_drawdown_periods(returns)
        if not periods:
            return float("nan")
        sorted_periods = sorted(periods, reverse=True)
        avg_mdd = float(np.mean(sorted_periods[:top_k]))
    else:
        avg_mdd = average_drawdown(returns)

    if avg_mdd == 0:
        return float("nan")
    return float(excess / avg_mdd)


def calmar_ratio(
    returns: np.ndarray,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
) -> float:
    """칼마 비율 — 단일 최대 MDD 대비 초과수익."""
    returns = np.asarray(returns, dtype=float)
    if len(returns) < 2:
        return float("nan")

    n = len(returns)
    ann_return = np.prod(1 + returns) ** (periods_per_year / n) - 1
    excess = ann_return - risk_free_rate

    mdd = maximum_drawdown(returns)
    if mdd == 0:
        return float("nan")
    return float(excess / mdd)


# ═══════════════════════════════════════════════════════════
# 4. Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014)
# ═══════════════════════════════════════════════════════════
def deflated_sharpe_ratio(
    sharpe: float,
    n_observations: int,
    skewness: float,
    kurtosis_value: float,
    n_trials: int = 1,
    expected_max_sharpe: float = 0.0,
) -> float:
    """
    DSR — 우연이 아닐 확률 (0~1).

    ⚠️ kurtosis_value는 Fisher=False 기준 (정규분포=3).
    """
    if n_observations <= 1:
        return float("nan")

    # Sharpe의 표준오차
    denom = n_observations - 1
    numer = 1 - skewness * sharpe + ((kurtosis_value - 1) / 4) * sharpe**2
    if numer < 0:
        return float("nan")
    sharpe_std = float(np.sqrt(numer / denom))

    if sharpe_std == 0:
        return float("nan")

    # 기대 최대 Sharpe
    if n_trials > 1:
        expected_max_sharpe = float(norm.ppf(1 - 1 / n_trials) * sharpe_std)

    dsr = float(norm.cdf((sharpe - expected_max_sharpe) / sharpe_std))
    return dsr


# ═══════════════════════════════════════════════════════════
# 5. 통합 계산 (Wrapper)
# ═══════════════════════════════════════════════════════════
def calculate_all_metrics(
    returns: np.ndarray,
    risk_free_rate: float = 0.02,
    target_return: float = 0.0,
    periods_per_year: int = 252,
    n_trials: int = 50,
    sterling_top_k: int = 3,
) -> Dict[str, float]:
    """
    모든 QFRS 지표를 한 번에 계산.

    Returns
    -------
    dict
        MDD, Sharpe Ratio, Sortino Ratio, Sterling Ratio,
        Calmar Ratio, Deflated Sharpe Ratio
    """
    returns = np.asarray(returns, dtype=float)

    if len(returns) < 2:
        return {
            "MDD": float("nan"),
            "Sharpe Ratio": float("nan"),
            "Sortino Ratio": float("nan"),
            "Sterling Ratio": float("nan"),
            "Calmar Ratio": float("nan"),
            "Deflated Sharpe Ratio": float("nan"),
        }

    sharpe = sharpe_ratio(returns, risk_free_rate, periods_per_year)

    # DSR용 왜도/첨도
    if len(returns) >= 4:
        skewness = float(skew(returns))
        kurt = float(kurtosis(returns, fisher=False))
    else:
        skewness, kurt = 0.0, 3.0

    dsr = deflated_sharpe_ratio(
        sharpe=sharpe,
        n_observations=len(returns),
        skewness=skewness,
        kurtosis_value=kurt,
        n_trials=n_trials,
    )

    return {
        "MDD": maximum_drawdown(returns),
        "Sharpe Ratio": sharpe,
        "Sortino Ratio": sortino_ratio(
            returns, target_return, risk_free_rate, periods_per_year
        ),
        "Sterling Ratio": sterling_ratio(
            returns, risk_free_rate, periods_per_year, top_k=sterling_top_k
        ),
        "Calmar Ratio": calmar_ratio(returns, risk_free_rate, periods_per_year),
        "Deflated Sharpe Ratio": dsr,
    }