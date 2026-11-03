"""평균-분산 최적화 — 분산투자 · 효율적 투자선 · 제약 · 입력에 대한 민감도 (합성 데이터).

실행    python mean_variance.py      (numpy 와 scipy 만 · 외부 접속 없음)
자료    세 자산(A · B · C)의 변동성 · 기대수익 · 상관을 손으로 정한 값이다. 실제 자산이 아니다.
        앱의 app/services/allocation_models.py 와 같은 목적함수(0.5·δ·wᵀΣw − wᵀμ)와
        제약(합 1 · 공매도 없음)을 SciPy SLSQP 로 푼다. 앱은 여기에 1%~95% 한도를 더한다.

함수
    pair_vol(v1, v2, rho, w1)      두 자산 포트폴리오의 변동성
    best(mu, delta, cap)           효용 0.5·δ·wᵀΣw − wᵀμ 를 최소화하는 비중 (합 1 · 공매도 없음 · 한 자산 최대 cap)
    min_variance_closed()          합 1 제약만 둔 최소분산 닫힌 식 Σ⁻¹ι / (ιᵀΣ⁻¹ι)
    frontier(targets, cap=1.0)     목표 기대수익마다 변동성이 가장 작은 비중 (효율적 투자선의 점들 · cap 은 한 자산 최대 비중)

그림 만드는 코드(tools/learn_figs/mean-variance-optimization.py)도 이 파일의 함수를 그대로 불러 쓴다.
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import minimize

NAMES = ("A", "B", "C")
VOL = np.array([0.08, 0.18, 0.25])          # 합성 입력: 연 변동성
MU = np.array([0.03, 0.07, 0.09])           # 합성 입력: 연 기대수익
CORR = np.array([[1, .2, .1], [.2, 1, .6], [.1, .6, 1]])
COV = np.outer(VOL, VOL) * CORR


def pair_vol(v1: float, v2: float, rho: float, w1: float = 0.5) -> float:
    """두 자산 포트폴리오의 변동성 = √(w1²v1² + w2²v2² + 2·w1·w2·ρ·v1·v2)."""
    w2 = 1 - w1
    return float(np.sqrt(w1 ** 2 * v1 ** 2 + w2 ** 2 * v2 ** 2 + 2 * w1 * w2 * rho * v1 * v2))


def best(mu=MU, delta: float = 3.0, cap: float = 1.0, cov=COV) -> np.ndarray:
    n = len(mu)
    res = minimize(lambda w: 0.5 * delta * w @ cov @ w - w @ mu, np.ones(n) / n, method="SLSQP",
                   bounds=[(0, cap)] * n, constraints={"type": "eq", "fun": lambda w: w.sum() - 1},
                   options={"ftol": 1e-12, "maxiter": 500})
    return res.x


def min_variance_closed(cov=COV) -> np.ndarray:
    x = np.linalg.solve(cov, np.ones(len(cov)))
    return x / x.sum()


def min_variance_slsqp(cov=COV, cap: float = 1.0) -> np.ndarray:
    n = len(cov)
    res = minimize(lambda w: w @ cov @ w, np.ones(n) / n, method="SLSQP", bounds=[(0, cap)] * n,
                   constraints={"type": "eq", "fun": lambda w: w.sum() - 1}, options={"ftol": 1e-14, "maxiter": 500})
    return res.x


def frontier(targets, cov=COV, mu=MU, cap: float = 1.0):
    """각 목표 기대수익에서 변동성이 가장 작은 비중(공매도 없음 · 합 1 · 한 자산 최대 cap)."""
    n = len(mu)
    out = []
    for t in targets:
        res = minimize(lambda w: w @ cov @ w, np.ones(n) / n, method="SLSQP", bounds=[(0, cap)] * n,
                       constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1},
                                    {"type": "eq", "fun": lambda w, t=t: w @ mu - t}],
                       options={"ftol": 1e-14, "maxiter": 500})
        out.append((float(t), res.x, float(np.sqrt(res.x @ cov @ res.x))))
    return out


def stats(w, mu=MU, cov=COV):
    return float(w @ mu), float(np.sqrt(w @ cov @ w))


def fmt(w) -> str:
    return "[" + " ".join(f"{x * 100:5.1f}" for x in w) + "]"


def main() -> None:
    print("① 분산투자 — 변동성 20% 두 자산을 반반 (합성)")
    for rho in (1.0, 0.5, 0.0, -0.5):
        print(f"  상관 {rho:+.1f} → 포트폴리오 변동성 {pair_vol(0.20, 0.20, rho) * 100:5.2f}%")

    print("② 합 1 · 공매도 없음 최소분산: 닫힌 식과 SLSQP (합성 세 자산)")
    wc, ws = min_variance_closed(), min_variance_slsqp()
    r, v = stats(wc)
    print(f"  닫힌 식 {fmt(wc)}%  SLSQP {fmt(ws)}%  → 변동성 {v * 100:.2f}% · 기대수익 {r * 100:.2f}%")

    print("③ 효율적 투자선의 점들 (목표 기대수익 → 변동성이 가장 작은 비중 A·B·C %)")
    lo, hi = stats(wc)[0], MU.max()
    for t, w, vol in frontier(np.linspace(lo, hi - 1e-4, 6)):
        print(f"  기대수익 {t * 100:4.2f}%  비중 {fmt(w)}  변동성 {vol * 100:5.2f}%")
    third = np.ones(3) / 3
    r3, v3 = stats(third)
    print(f"  비교: 똑같이 1/3 씩 → 기대수익 {r3 * 100:.2f}% 변동성 {v3 * 100:.2f}% · 같은 기대수익의 투자선 변동성 {frontier([r3])[0][2] * 100:.2f}%")

    print("④ 효용 최대화(δ=3) — 기대수익을 조금 바꾸면 비중이 얼마나 움직이나")
    base = best()
    print(f"  기대수익 {np.round(MU * 100, 1)}  → 비중 {fmt(base)}%")
    for label, d in (("B 기대수익 +1%p", [0, .01, 0]), ("B 기대수익 -1%p", [0, -.01, 0]),
                     ("C 기대수익 +1%p", [0, 0, .01]), ("B +2%p · C -2%p", [0, .02, -.02])):
        w = best(MU + np.array(d))
        print(f"  {label:<15} → 비중 {fmt(w)}%  바뀐 합계 {np.abs(w - base).sum() * 100:5.1f}%p")

    print("⑤ 합 1 제약을 빼고 푼 (δΣ)⁻¹μ 와, 억지로 합을 1 로 나눈 값")
    free = np.linalg.solve(3.0 * COV, MU)
    print(f"  제약 없는 해 {fmt(free)}%  합 {free.sum() * 100:.1f}%")
    print(f"  합으로 나눔   {fmt(free / free.sum())}%  ← 합 1 제약을 문제 안에 넣은 해 {fmt(base)}% 와 다르다")

    print("⑥ 한 자산 최대 비중을 걸면 (같은 입력 · 최소분산을 더 몰리는 상관에서)")
    cov2 = np.outer(VOL, VOL) * np.array([[1, .5, .5], [.5, 1, .5], [.5, .5, 1]])
    for cap in (1.0, 0.6, 0.4):
        w = min_variance_slsqp(cov2, cap)
        print(f"  최대 {cap * 100:3.0f}% → 비중 {fmt(w)}%  변동성 {np.sqrt(w @ cov2 @ w) * 100:5.2f}%")


if __name__ == "__main__":
    main()
