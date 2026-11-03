"""백테스트를 믿어도 될까 — 난수 전략 N개 중 최고 샤프, 표본 안 1등의 표본 밖 성과, 하루 미루기, 비용 (합성 데이터).

실행    python backtest_trust.py      (numpy 와 표준 라이브러리만 · 외부 접속 없음)
자료    평균 0 · 일 표준편차 1% 의 정규분포 난수로 만든 「전략」 수익률. 실제 시세가 아니다.
        실력이 전혀 없는 전략 묶음에서도 고르기만 하면 높은 샤프가 나온다는 것을 보이려는 실험이다.

함수
    annual_sharpe(r)                    일간 수익률 → 연환산 샤프(무위험 0 · 표준편차 ddof=1 · ×√252)
    best_sharpe_by_trials(ns, ...)      전략 N개 중 최고 샤프의 반복 평균
    expected_max_sharpe(n, days)        Bailey · López de Prado(2014)의 기대 최댓값 식(연환산)
    in_sample_vs_out(...)               표본 안 1등을 다음 구간에 그대로 쓰면
    first_repetition(...)               그 실험의 첫 반복 하나(그림 2 의 왼쪽)
    lookahead_demo(...)                 같은 날 신호를 같은 날 수익에 쓰면 vs 하루 미루면
    round_trip_cost(slippage_bps)       코스피 한 번 사고파는 비용(2026-11-03 비용 모델)

그림 만드는 코드(tools/learn_figs/can-you-trust-a-backtest.py)도 이 파일의 함수를 그대로 불러 쓴다.
"""
from __future__ import annotations

from statistics import NormalDist

import numpy as np

DAYS_3Y = 756                      # 3년 = 252 × 3 거래일
EULER_GAMMA = 0.5772156649015329   # 오일러–마스케로니 상수

# 비용 상수(편도 비율) — 2026-11-03 앱의 비용 모델과 같은 값 · 코스피 · 온라인 계좌
FEE_ONLINE_KRX = 0.000140527
FEE_CLEARING = 0.000036396
SELL_TAX_KOSPI_2026 = 0.0005 + 0.0015     # 증권거래세 + 농어촌특별세, 매도에만


def annual_sharpe(r) -> np.ndarray:
    """마지막 축이 시간. 무위험 0 · 표준편차는 ddof=1 · ×√252."""
    r = np.asarray(r, dtype=float)
    return r.mean(-1) / r.std(-1, ddof=1) * np.sqrt(252)


def best_sharpe_by_trials(ns=(1, 10, 100, 1000), reps: int = 200, days: int = DAYS_3Y, seed: int = 42) -> dict:
    """난수 전략 N개를 만들어 가장 높은 샤프를 reps 번 구해 평균낸다. 난수 상태는 한 줄기로 이어진다."""
    rng = np.random.default_rng(seed)
    out = {}
    for n in ns:
        out[n] = float(np.mean([annual_sharpe(rng.normal(0, 0.01, (n, days))).max() for _ in range(reps)]))
    return out


def expected_max_sharpe(n: int, days: int = DAYS_3Y) -> float:
    """시도 N번의 기대 최대 샤프(연환산). 시도들의 샤프 표준편차는 난수 전략에서 1/√days(일 단위)에 가깝다.

    E[max] ≈ σ · ((1 − γ)·Z⁻¹[1 − 1/N] + γ·Z⁻¹[1 − 1/(N·e)])   (Z⁻¹ 는 표준정규의 역누적분포)
    """
    if n < 2:
        return 0.0
    z = NormalDist().inv_cdf
    sigma = np.sqrt(252 / days)              # 연환산 샤프의 표준편차
    return float(sigma * ((1 - EULER_GAMMA) * z(1 - 1 / n) + EULER_GAMMA * z(1 - 1 / (n * np.e))))


def in_sample_vs_out(n_strategies: int = 100, reps: int = 300, days: int = DAYS_3Y, seed: int = 42):
    """앞 구간에서 샤프가 가장 높은 전략을 골라 바로 다음 같은 길이의 구간에서 재 본다. (평균 표본 안, 평균 표본 밖, 표본 밖 표준오차)"""
    rng = np.random.default_rng(seed)
    ins, outs = [], []
    for _ in range(reps):
        r = rng.normal(0, 0.01, (n_strategies, 2 * days))
        s_in = annual_sharpe(r[:, :days])
        k = int(s_in.argmax())
        ins.append(s_in[k])
        outs.append(float(annual_sharpe(r[k, days:])))
    return float(np.mean(ins)), float(np.mean(outs)), float(np.std(outs, ddof=1) / np.sqrt(reps))


def first_repetition(n_strategies: int = 100, days: int = DAYS_3Y, seed: int = 42):
    """in_sample_vs_out 의 첫 반복 하나를 고르지 않고 그대로: (표본 안 샤프, 표본 밖 샤프, 6년 누적 가치 곡선)."""
    r = np.random.default_rng(seed).normal(0, 0.01, (n_strategies, 2 * days))
    s_in = annual_sharpe(r[:, :days])
    k = int(s_in.argmax())
    cum = np.concatenate([[1.0], np.cumprod(1 + r[k])])
    return float(s_in[k]), float(annual_sharpe(r[k, days:])), cum


def lookahead_demo(days: int = DAYS_3Y, reps: int = 200, seed: int = 7):
    """신호 = 「그날 수익률이 양수였나」. 그날 종가를 보고서야 아는 신호다.
    같은 날에 쓰면 오른 날만 잡고(미래 참조), 하루 미루면 아무 힘이 없다. 평균 상승분이 없는 난수 3년을 reps 번 만들어 샤프를 평균낸다."""
    rng = np.random.default_rng(seed)
    same, nxt = [], []
    for _ in range(reps):
        r = rng.normal(0.0, 0.01, days)
        signal = (r > 0).astype(float)
        same.append(float(annual_sharpe(signal * r)))
        nxt.append(float(annual_sharpe(np.concatenate([[0.0], signal[:-1]]) * r)))
    return float(np.mean(same)), float(np.mean(nxt)), float(np.std(nxt, ddof=1) / np.sqrt(reps))


def round_trip_cost(slippage_bps: float = 10.0) -> float:
    """코스피 한 번 사서 파는 비용 비율(편도 매수 + 편도 매도)."""
    buy = FEE_ONLINE_KRX + FEE_CLEARING + slippage_bps / 10_000
    return buy + (buy + SELL_TAX_KOSPI_2026)


def main() -> None:
    print("① 난수 전략 N개 중 최고 연환산 샤프 (합성 데이터 · 평균 0 · 일 표준편차 1% · 3년 756일 · 200번 평균 · 시드 42)")
    best = best_sharpe_by_trials()
    for n, v in best.items():
        print(f"  N={n:<5} 시뮬레이션 {v:+.2f}   기대 최댓값 식 {expected_max_sharpe(n):+.2f}")

    ins, outs, se = in_sample_vs_out()
    print("② 100개 중 앞 3년 1등을 다음 3년에 (합성 데이터 · 300번 평균 · 시드 42)")
    print(f"  앞 3년(표본 안) 평균 샤프 {ins:+.2f}  →  다음 3년(표본 밖) 평균 샤프 {outs:+.2f}  (표준오차 {se:.2f})")
    f_in, f_out, _ = first_repetition()
    print(f"  첫 반복 하나만 보면  표본 안 {f_in:+.2f}  →  표본 밖 {f_out:+.2f}")

    same, nxt, se = lookahead_demo()
    print("③ 그날 수익률 부호를 신호로 (합성 데이터 · 평균 0 · 일 표준편차 1% · 3년 756일 · 200번 평균 · 시드 7)")
    print(f"  같은 날에 씀  평균 연환산 샤프 {same:.1f}")
    print(f"  하루 미룸     평균 연환산 샤프 {nxt:+.2f}  (표준오차 {se:.2f})")

    cost0, cost10 = round_trip_cost(0), round_trip_cost(10)
    print("④ 한 번 사고파는 비용 (코스피 · 2026-11-03 비용 모델 · 슬리피지는 가정)")
    print(f"  슬리피지 0bp  {cost0 * 100:.4f}%    슬리피지 10bp(편도)  {cost10 * 100:.4f}%")
    print("⑤ 비용을 빼면 순위가 바뀌나 (손으로 정한 가정 숫자 · 단순 합 · 슬리피지 10bp)")
    for name, trips, gain in (("잦은 거래", 80, 0.5), ("드문 거래", 8, 1.5)):
        gross = trips * gain
        cost = trips * cost10 * 100
        print(f"  {name}  연 {trips:>2}회 × 회당 +{gain}%  총수익 {gross:.1f}%  비용 {cost:.1f}%  비용 뒤 {gross - cost:+.1f}%")


if __name__ == "__main__":
    main()
