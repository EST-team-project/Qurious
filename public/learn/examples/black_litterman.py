"""블랙–리터만 — 기준 비중에서 거꾸로 푼 수익률 + 투자자 뷰 → 사후 수익 → 비중 (합성 데이터).

실행    python black_litterman.py      (numpy 와 scipy 만 · 외부 접속 없음)
자료    네 가상 자산(국내주식 · 해외주식 · 국내채권 · 대체자산)의 변동성 · 상관 · 기준 비중을 손으로 정한 값이다. 실제 시장 자료가 아니다.
        앱의 app/services/allocation_models.py 의 black_litterman 과 같은 식을 옮겼다.
            Π = δ·Σ·w0                              (δ = 3 고정 · w0 = 기준 비중 · 시장 비중이 아니다)
            Ω = τ · pΣpᵀ · (1 − c) / c              (뷰 하나의 불확실성 · c = 신뢰도 · τ = 0.05)
            μ̄ = Π + τΣPᵀ(τPΣPᵀ + Ω)⁻¹(Q − PΠ)       (사후 수익)
            비중 = 0.5·δ·wᵀΣw − wᵀμ̄ 를 최소화 (합 1 · 공매도 없음 · 앱은 비중 1%~95%)

함수
    posterior(c, q, tau)        뷰 하나(국내주식이 해외주식보다 연 q 더)를 넣은 사후 수익
    textbook_posterior(c, ...)  He–Litterman 부록의 꼴로 계산한 같은 사후 수익(두 식이 같은 값인지 확인용)
    weights(mu, lo, hi)         효용을 최대로 하는 비중 (lo~hi = 앱 한도, None 이면 한도 없이 푼 닫힌 식)

그림 만드는 코드(tools/learn_figs/black-litterman.py)도 이 파일의 함수를 그대로 불러 쓴다.
"""
from __future__ import annotations

import unicodedata

import numpy as np
from scipy.optimize import minimize

NAMES = ("국내주식", "해외주식", "국내채권", "대체자산")
VOL = np.array([0.18, 0.16, 0.05, 0.14])
CORR = np.array([[1, .7, .1, .2], [.7, 1, .0, .2], [.1, .0, 1, .1], [.2, .2, .1, 1]])
COV = np.outer(VOL, VOL) * CORR
BASE = np.array([30, 25, 30, 10]) / 95.0          # 기준 비중(현금 5% 를 뺀 네 자산군) — 시가총액 비중이 아니다
DELTA, TAU = 3.0, 0.05
P = np.array([[1.0, -1.0, 0.0, 0.0]])           # 상대 뷰: 국내주식 − 해외주식 (행 합 0)
Q = 0.03                                         # 국내주식이 해외주식보다 연 3%p 더


def pad(text: str, width: int) -> str:
    cols = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)
    return text + " " * max(0, width - cols)


def prior(w0=BASE, cov=COV, delta=DELTA) -> np.ndarray:
    return delta * cov @ w0


def posterior(c: float, q: float = Q, tau: float = TAU, w0=BASE, cov=COV, delta=DELTA, p=P) -> np.ndarray:
    pi = prior(w0, cov, delta)
    s = float(p[0] @ cov @ p[0])
    omega = np.array([tau * s * (1 - c) / c]) if c < 1 else np.array([0.0])      # c = 1 은 확신 100%(Ω = 0)
    tc = tau * cov
    return pi + tc @ p.T @ np.linalg.solve(p @ tc @ p.T + np.diag(omega), np.array([q]) - p @ pi)


def textbook_posterior(c: float, q: float = Q, tau: float = TAU, w0=BASE, cov=COV, delta=DELTA, p=P) -> np.ndarray:
    """He–Litterman 부록의 꼴 [(τΣ)⁻¹ + PᵀΩ⁻¹P]⁻¹[(τΣ)⁻¹Π + PᵀΩ⁻¹Q] — 위 posterior() 와 같은 값이어야 한다."""
    pi = prior(w0, cov, delta)
    omega = np.array([[tau * float(p[0] @ cov @ p[0]) * (1 - c) / c]])
    inv_ts = np.linalg.inv(tau * cov)
    inv_om = np.linalg.inv(omega)
    return np.linalg.solve(inv_ts + p.T @ inv_om @ p, inv_ts @ pi + p.T @ inv_om @ np.array([q]))


def weights(mu, lo=0.01, hi=0.95, cov=COV, delta=DELTA) -> np.ndarray:
    """lo 가 None 이면 한도 · 합 1 제약 없이 푼 닫힌 식 (δΣ)⁻¹μ̄. 상대 뷰 하나는 합이 0 이라 합이 그대로 1 이다."""
    if lo is None:
        return np.linalg.solve(delta * cov, mu)
    res = minimize(lambda w: 0.5 * delta * w @ cov @ w - w @ mu, np.ones(len(mu)) / len(mu), method="SLSQP",
                   bounds=[(lo, hi)] * len(mu), constraints={"type": "eq", "fun": lambda w: w.sum() - 1},
                   options={"maxiter": 1000, "ftol": 1e-12})
    return res.x


def pct(w, digits: int = 1) -> str:
    return "[" + " ".join(f"{x * 100:{digits + 4}.{digits}f}" for x in w) + "]"


def main() -> None:
    pi = prior()
    print("① 기준 비중 w0 에서 거꾸로 푼 수익률 Π = 3·Σ·w0 (합성 · 연 초과수익 %)")
    print(f"  기준 비중 {pct(BASE)}%  →  Π {pct(pi, 2)}%   (국내주식 − 해외주식 = {(pi[0] - pi[1]) * 100:.3f}%p)")
    print(f"  뷰 없음 → 최적 비중 {pct(weights(pi))}%  (= w0 로 돌아옴: {np.allclose(weights(pi), BASE, atol=1e-6)})")

    print("② 뷰: 국내주식이 해외주식보다 연 3%p 더 — 신뢰도 c 에 따라 사후 상대수익은 사전에서 3%p 쪽으로 c 만큼 간다")
    base = (pi[0] - pi[1]) * 100
    for c in (0.25, 0.5, 0.9):
        post = posterior(c)
        rel = (post[0] - post[1]) * 100
        print(f"  c={c:<4} 사후 상대수익 {rel:.3f}%p   사전 + c·(3 − 사전) = {base + c * (3 - base):.3f}%p")

    print("  c=0.5 에서 네 자산군의 기대수익 (연 초과수익 %) — 뷰에 나오지 않는 자산의 기대수익도 움직인다")
    post = posterior(0.5)
    for name, before, after in zip(NAMES, pi, post):
        print(f"  {pad(name, 10)}사전 {before * 100:5.2f} → 사후 {after * 100:5.2f}  ({(after - before) * 100:+.2f}%p)")
    print("③ 같은 뷰를 넣은 최적 비중 (국내주식 · 해외주식 · 국내채권 · 대체자산 %)")
    w100 = weights(posterior(1.0), None)
    print(f"  {pad('뷰 없음(기준 비중)', 24)}{pct(BASE)}")
    for c in (0.25, 0.5, 0.9):
        post = posterior(c)
        free, capped = weights(post, None), weights(post)
        print(f"  c={c:<4} 한도 없음 {pct(free)}   앱 한도 1~95% {pct(capped)}")
    print(f"  {pad('c=1.0 한도 없음', 24)}{pct(w100)}   ← 확신 100%(Ω=0) 일 때 한도 없는 비중")
    for c in (0.25, 0.5, 0.9):
        move, full = weights(posterior(c), None) - BASE, w100 - BASE
        print(f"  c={c:<4} (한도 없음 이동) / (확신 100% 이동) = {np.round(move[:2] / full[:2], 3)}")

    print("④ τ 를 바꿔도 사후 수익은 같다 (c=0.5 · Ω 가 τ 에 비례해 약분된다)")
    for tau in (0.005, 0.05, 0.5):
        print(f"  τ={tau:<5} 사후 수익 {pct(posterior(0.5, tau=tau), 2)}%")

    print("⑤ 신뢰도 99% 와 0%")
    print(f"  c=0.99 사후 상대수익 {(posterior(0.99)[0] - posterior(0.99)[1]) * 100:.3f}%p (뷰 3%p 에 거의 닿음)")
    print("  c=0 이면 뷰를 쓰지 않는다 → 사후 수익 = Π, 비중 = 기준 비중")

    print("⑥ 교과서 꼴과 같은 값인지, 뷰 하나 · 한도 없음일 때 비중 이동의 닫힌 식")
    for c in (0.25, 0.5, 0.9):
        print(f"  c={c:<4} [(τΣ)⁻¹ + PᵀΩ⁻¹P]⁻¹[(τΣ)⁻¹Π + PᵀΩ⁻¹Q] 와 같은 값: {np.allclose(textbook_posterior(c), posterior(c), atol=1e-12)}")
    s = float(P[0] @ COV @ P[0])
    lam = (Q - float(P[0] @ pi)) / (DELTA * s)
    print(f"  pΣpᵀ = {s:.5f} (상대 포지션의 분산) · 100% 확신 때 국내주식 +{lam * 100:.1f}%p · 해외주식 −{lam * 100:.1f}%p")
    for c in (0.25, 0.5, 0.9):
        print(f"  c={c:<4} 닫힌 식 c·(Q − pΠ)/(δ·pΣpᵀ) = {c * lam * 100:5.2f}%p   푼 값 {(weights(posterior(c), None) - BASE)[0] * 100:5.2f}%p")


if __name__ == "__main__":
    main()
