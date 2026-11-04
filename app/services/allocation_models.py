"""재현 가능한 자산군 배분. 계산만 수행하며 주문이나 실행 설정을 변경하지 않는다.

RP: w_i (Σw)_i / (w'Σw)의 균등화(상하한 안에서 최소 오차).
BL: Π=δΣw0, μ=Π+τΣP'(τPΣP'+Ω)^-1(Q-PΠ).
기준 포트폴리오는 사용자가 지정하거나 기존 성향 배분을 사용한다. 시가총액
가중 시장 포트폴리오로 오인하지 않도록 기준 출처와 입력을 결과에 보관한다.
"""
from __future__ import annotations

import hashlib
import numpy as np
import pandas as pd
from scipy.optimize import minimize

ASSET_PROXIES = {
    "국내주식": {"symbol": "069500.KS", "name": "KODEX 200"},
    "해외주식": {"symbol": "360750.KS", "name": "TIGER 미국S&P500"},
    "국내채권": {"symbol": "114260.KS", "name": "KODEX 국고채3년"},
    "대체자산": {"symbol": "132030.KS", "name": "KODEX 골드선물(H)"},
}
MODELS = {
    "risk_parity": "리스크 패리티",
    "minimum_variance": "최소분산",
    "black_litterman": "Black–Litterman",
    "regime": "시장 국면별 배분",
}
LOWER, UPPER = .01, .95  # 현금 제외 자산군 비중의 제약


def percent_weights(weights, labels, *, total=1000, lower_units=0, upper_units=None):
    """0.1% 단위 최대 나머지법. 표시·저장·인수 비중의 합계를 보존한다."""
    exact = np.asarray(weights, dtype=float) * total
    upper_units = total if upper_units is None else upper_units
    if len(labels) * lower_units > total or len(labels) * upper_units < total:
        raise ValueError("표시 단위에서 배분 상하한을 지킬 수 없습니다.")
    units = np.clip(np.floor(exact + 1e-9).astype(int), lower_units, upper_units)
    rest = total - int(units.sum())
    if abs(rest) > len(labels):
        raise ValueError("배분 합계가 올바르지 않습니다.")
    while rest:
        direction = 1 if rest > 0 else -1
        candidates = [i for i in range(len(labels)) if
                      (units[i] < upper_units if direction == 1 else units[i] > lower_units)]
        i = min(candidates, key=lambda i: (-direction * (exact[i] - units[i]), labels[i]))
        units[i] += direction
        rest -= direction
    return {label: int(n) / 10 for label, n in zip(labels, units)}


def bounded_weights(values, labels, *, lower, upper):
    """양수 점수를 비례 조정하되 마지막 정규화 뒤에도 상하한을 보존한다."""
    values = np.asarray(values, dtype=float)
    n = len(values)
    if not np.all(np.isfinite(values)) or not n * lower <= 1 <= n * upper:
        raise ValueError("배분 상하한 또는 입력값을 확인하세요.")
    scores = np.clip(values, max(lower, 1e-12), upper)
    lo, hi = 0., 1 / float(scores.min())
    for _ in range(80):
        mid = (lo + hi) / 2
        if np.clip(scores * mid, lower, upper).sum() < 1:
            lo = mid
        else:
            hi = mid
    weights = np.clip(scores * ((lo + hi) / 2), lower, upper)
    return np.array(list(percent_weights(weights, labels).values())) / 100


def common_returns(stock_data, *, as_of, minimum=60):
    """수익률의 시작·끝 날짜가 같은 표본만 사용한다. 결측을 채우지 않는다."""
    cutoff = pd.Timestamp(as_of).date()
    closes = []
    labels = set()
    for item in stock_data:
        symbol = item["symbol"]
        if symbol in labels:
            raise ValueError("배분 종목이 중복되었습니다.")
        labels.add(symbol)
        frame = pd.DataFrame(item["candles"])
        if not {"time", "close"} <= set(frame.columns):
            raise ValueError(f"{symbol}: 자산군 시세가 없습니다.")
        dates = pd.to_datetime(frame["time"], unit="s", utc=True).dt.tz_convert("Asia/Seoul").dt.normalize()
        prices = pd.to_numeric(frame["close"], errors="coerce")
        s = pd.Series(prices.to_numpy(), index=dates, name=symbol).sort_index()
        s = s[s.index.date <= cutoff]
        if s.index.has_duplicates or not np.isfinite(s).all() or (s <= 0).any():
            raise ValueError(f"{symbol}: 중복 날짜 또는 잘못된 시세가 있습니다.")
        closes.append(s)
    if len(closes) < 2 or any(s.empty for s in closes):
        raise ValueError("자산군 시세가 부족합니다.")
    if len({s.index[-1] for s in closes}) != 1:
        raise ValueError("자산군별 마지막 시세 날짜가 다릅니다. 자료 갱신 후 다시 계산하세요.")
    # 먼저 날짜를 맞춘 뒤 결측 날짜에 걸친 다일 수익률도 제거한다.
    prices = pd.concat(closes, axis=1, sort=True)
    ret = prices.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan).dropna().tail(756)
    if len(ret) < minimum:
        raise ValueError(f"자산군 공통 수익률 {minimum}거래일 이상이 필요합니다.")
    return ret


def risk_shares(weights, cov):
    variance = float(weights @ cov @ weights)
    if not np.isfinite(variance) or variance <= 0:
        raise ValueError("위험 기여도를 계산할 수 없습니다.")
    return weights * (cov @ weights) / variance


def solve_weights(cov, *, returns=None, risk_parity=False, risk_aversion=3.):
    n = len(cov)
    if risk_parity:
        objective = lambda w: float(np.sum((risk_shares(w, cov) - 1 / n) ** 2))
    else:
        mu = np.zeros(n) if returns is None else np.asarray(returns)
        objective = lambda w: float(100 * (.5 * risk_aversion * (w @ cov @ w) - w @ mu))
    initial = 1 / np.sqrt(np.diag(cov)) if risk_parity else np.ones(n)
    initial /= initial.sum()
    solved = minimize(objective, initial, method="SLSQP", bounds=[(LOWER, UPPER)] * n,
                      constraints={"type": "eq", "fun": lambda w: w.sum() - 1},
                      options={"maxiter": 1000, "ftol": 1e-12})
    w = solved.x
    if (not solved.success or not np.isfinite(w).all() or abs(w.sum() - 1) > 1e-7
            or np.any(w < LOWER - 1e-7) or np.any(w > UPPER + 1e-7)):
        raise ValueError("배분 계산이 수렴하지 않았습니다. 기존 저장 결과를 유지합니다.")
    return w


def black_litterman(cov, baseline, views, labels, *, risk_aversion=3., tau=.05):
    """연 초과수익 상대 뷰. 무관심(0% 신뢰도)은 뷰를 적용하지 않는다."""
    prior = risk_aversion * cov @ baseline
    rows, expectations, uncertainty = [], [], []
    pairs = set()
    for view in views:
        a, b = view["asset"], view["relative_to"]
        confidence, excess = float(view["confidence_pct"]) / 100, float(view["outperformance_pct"]) / 100
        if a not in labels or b not in labels or a == b:
            raise ValueError("서로 다른 두 자산군의 전망을 선택하세요.")
        pair = frozenset((a, b))
        if pair in pairs:
            raise ValueError("같은 자산군 쌍의 전망은 한 번만 입력하세요.")
        pairs.add(pair)
        if not np.isfinite([confidence, excess]).all() or not 0 <= confidence < 1 or not -.5 <= excess <= .5:
            raise ValueError("전망은 연 -50~50%p, 신뢰도는 0~99%로 입력하세요.")
        if confidence == 0:
            continue
        p = np.zeros(len(labels))
        p[labels.index(a)], p[labels.index(b)] = 1, -1
        rows.append(p)
        expectations.append(excess)
        uncertainty.append(float(tau * (p @ cov @ p) * (1 - confidence) / confidence))
    if not rows:
        return baseline.copy(), prior, prior
    p, q = np.asarray(rows), np.asarray(expectations)
    tau_cov = tau * cov
    posterior = prior + tau_cov @ p.T @ np.linalg.solve(p @ tau_cov @ p.T + np.diag(uncertainty), q - p @ prior)
    weights = solve_weights(cov, returns=posterior, risk_aversion=risk_aversion)
    return weights, prior, posterior


def detect_regime(returns):
    """국내주식 대용 ETF의 추세120일 × 연변동성20일(20% 경계), 그날까지."""
    r = returns["국내주식"]
    if len(r) < 120:
        raise ValueError("시장 국면 판정에는 공통 수익률 120거래일 이상이 필요합니다.")
    index = (1 + r).cumprod()
    ratio = float(index.iloc[-1] / index.tail(120).mean())
    vol = float(r.tail(20).std(ddof=1) * np.sqrt(252))
    trend, volatility = ("up" if ratio >= 1 else "down"), ("high" if vol >= .20 else "low")
    key = f"{trend}_{volatility}"
    return {"key": key, "trend": trend, "volatility": volatility,
            "trend_ratio": round(ratio, 6), "annual_volatility_pct": round(vol * 100, 3),
            "equity_multiplier": {"up_low": 1.1, "up_high": .85, "down_low": .75, "down_high": .5}[key],
            "rule": "국내주식 ETF 종가/120일 평균 ≥ 1이면 상승, 20일 연변동성 ≥ 20%이면 고변동"}


def calculate_allocation(model, stock_data, baseline, *, as_of, views=None, benchmark=None):
    """신규 모델은 네 자산군 대용 ETF, 현금은 성향별 유보 비중을 사용한다."""
    if model not in MODELS:
        raise ValueError("지원하지 않는 배분 모델입니다.")
    labels = list(ASSET_PROXIES)
    base = dict(baseline if benchmark is None else benchmark)
    if set(base) != set(labels + ["현금"]):
        raise ValueError("기준 비중에는 네 자산군과 현금이 모두 필요합니다.")
    values = np.array([base[k] for k in labels + ["현금"]], dtype=float)
    if not np.isfinite(values).all() or (values < 0).any() or abs(values.sum() - 100) > 1e-7 or base["현금"] >= 100:
        raise ValueError("기준 비중은 음수 없이 합계 100%여야 합니다.")
    if not np.allclose(values * 10, np.round(values * 10), rtol=0, atol=1e-8):
        raise ValueError("기준 비중은 0.1% 단위로 입력하세요.")
    invested = 1 - float(base["현금"]) / 100
    reference = values[:-1] / (invested * 100)
    if (reference < LOWER).any() or (reference > UPPER).any():
        raise ValueError("현금 제외 기준 비중은 자산군별 1~95%여야 합니다.")
    try:
        ret = common_returns(stock_data, as_of=as_of, minimum=120 if model == "regime" else 60)
        if set(ret.columns) != set(labels):
            raise ValueError("네 자산군 시세가 모두 필요합니다.")
        ret = ret[labels]
        input_hash = hashlib.sha256(ret.to_json(date_format="iso", double_precision=15).encode()).hexdigest()
        cov = ret.cov().to_numpy() * 252 + np.eye(len(labels)) * 1e-6
        mu = .5 * np.clip(ret.mean().to_numpy() * 252, -.30, .30) + .5 * .07
        details = {}
        if model == "risk_parity":
            weights = solve_weights(cov, risk_parity=True)
        elif model == "minimum_variance":
            weights = solve_weights(cov, risk_aversion=1.)
        elif model == "black_litterman":
            weights, prior, posterior = black_litterman(cov, reference, views or [], labels)
            mu = posterior + .025  # 초과수익을 총수익으로 바꿀 때 현금과 같은 무위험수익 가정
            details = {"prior_excess_return_pct": dict(zip(labels, (prior * 100).tolist())),
                       "posterior_excess_return_pct": dict(zip(labels, (posterior * 100).tolist())),
                       "views": views or [], "tau": .05, "risk_aversion": 3.,
                       "benchmark_source": "user" if benchmark is not None else "risk_profile",
                       "benchmark_note": "사용자 기준 균형 비중입니다. 시가총액 가중 시장 비중은 아닙니다."}
        else:
            regime = detect_regime(ret)
            target = values / 100
            old_equities = target[0] + target[1]
            desired = old_equities * regime["equity_multiplier"]
            shift = min(desired - old_equities, target[2] + target[4])
            if shift > 0:
                funding = target[2] + target[4]
                target[2] -= shift * target[2] / funding
                target[4] -= shift * target[4] / funding
            else:
                target[2] -= shift * .7
                target[4] -= shift * .3
            target[:2] *= (old_equities + shift) / old_equities
            invested = 1 - target[4]
            weights = target[:-1] / invested
            details = {"regime": regime}
        total = int(round(invested * 1000))
        bounds = {} if model == "regime" else {"lower_units": int(np.ceil(LOWER * total)),
                                              "upper_units": int(np.floor(UPPER * total))}
        allocation = percent_weights(weights, labels, total=total, **bounds)
        allocation["현금"] = (1000 - total) / 10
        # 표시된 비중으로 성과·위험을 다시 계산한다.
        actual = np.array([allocation[k] for k in labels]) / 100
        shares = risk_shares(actual, cov)
        return {"allocations": allocation, "model": model, "name": MODELS[model],
                "as_of": ret.index[-1].date().isoformat(), "observations": len(ret),
                "input_sha256": input_hash,
                "reference_allocations": base, "proxies": ASSET_PROXIES,
                "risk_contribution_pct": dict(zip(labels, np.round(shares * 100, 3).tolist())),
                "risk_parity_max_deviation_pct": round(float(np.max(np.abs(shares - .25))) * 100, 3) if model == "risk_parity" else None,
                "expected_return_pct": round(float(actual @ mu + allocation["현금"] / 100 * .025) * 100, 3),
                "expected_volatility_pct": round(float(np.sqrt(actual @ cov @ actual)) * 100, 3),
                "constraints": {"long_only": True, "invested_asset_min_pct": LOWER * 100,
                                "invested_asset_max_pct": UPPER * 100} if model != "regime" else {"long_only": True},
                "method": "국내 상장 ETF 종가 수익률 대용치 · 배당·기업행동·비용·세금 미조정 · 현금 연 2.5% 가정",
                **details}
    except (np.linalg.LinAlgError, FloatingPointError) as exc:
        raise ValueError("자산군 배분 계산에 실패했습니다. 시세와 전망을 확인하세요.") from exc
