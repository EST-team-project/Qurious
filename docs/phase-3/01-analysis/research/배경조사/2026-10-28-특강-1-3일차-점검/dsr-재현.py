"""DSR 재현 — 알파가 없는 수익률에서 `deflated_sharpe_ratio` 가 얼마나 자주 0.95 를 넘는가.

돌리기(저장소 루트에서):  python docs/phase-3/01-analysis/research/배경조사/2026-10-28-특강-1-3일차-점검/dsr-재현.py
읽기만 한다 — 앱 · DB 를 건드리지 않고 `app/services/evaluation_risk.py` 한 파일만 불러온다(numpy · scipy 필요).

비교하는 두 가지:
  코드   : `calculate_all_metrics` 가 내는 `Deflated Sharpe Ratio` (연율 샤프를 식에 넣는다)
  일 단위: 같은 단순 식을 일(관측 주기) 단위 샤프로 쓴 값 — Bailey · López de Prado 의 표준오차 식이 요구하는 단위
주의: 「일 단위」 쪽도 정식 DSR(시도들의 샤프 분산을 쓰는 식)이 아니라 코드와 같은 단순 식이다.
      두 값의 차이는 「단위」 하나만 바꾼 효과이고, 정식 식과의 차이는 이 스크립트가 재지 않는다.
"""
from __future__ import annotations

import importlib.util
import os

import numpy as np
from scipy.stats import kurtosis, norm, skew

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), *([".."] * 6)))
spec = importlib.util.spec_from_file_location(
    "evaluation_risk", os.path.join(ROOT, "app", "services", "evaluation_risk.py")
)
er = importlib.util.module_from_spec(spec)
spec.loader.exec_module(er)

N_TRIALS = 50        # 코드의 기본값(`calculate_all_metrics(n_trials=50)`)
DAILY_SIGMA = 0.01   # 일 변동성 1% 가정
REPEAT = 300


def dsr_daily_unit(returns: np.ndarray, n_trials: int) -> float:
    """코드와 같은 단순 식 — 단 샤프를 일 단위로 둔다."""
    r = np.asarray(returns, float)
    t = len(r)
    sr = r.mean() / r.std(ddof=1)
    g3, g4 = skew(r), kurtosis(r, fisher=False)
    sd = np.sqrt((1 - g3 * sr + (g4 - 1) / 4 * sr**2) / (t - 1))
    emax = norm.ppf(1 - 1 / n_trials) * sd if n_trials > 1 else 0.0
    return float(norm.cdf((sr - emax) / sd))


def main() -> None:
    rng = np.random.default_rng(0)
    print(f"일 변동성 {DAILY_SIGMA:.0%} · 시도 횟수 N={N_TRIALS} · 반복 {REPEAT}회 · 무위험 0")
    print("DSR >= 0.95 를 넘은 비율(알파 없음 = 평균 0 이면 0 에 가까워야 한다)")
    for label, mu in (("알파 없음(평균 0)", 0.0), ("약한 알파(일 0.03%)", 0.0003), ("강한 알파(일 0.1%)", 0.001)):
        for t in (60, 250):
            code, ref = [], []
            for _ in range(REPEAT):
                r = rng.normal(mu, DAILY_SIGMA, t)
                m = er.calculate_all_metrics(r, risk_free_rate=0.0, n_trials=N_TRIALS)
                code.append(m["Deflated Sharpe Ratio"])
                ref.append(dsr_daily_unit(r, N_TRIALS))
            pc = float(np.nanmean(np.array(code) >= 0.95))
            pr = float(np.mean(np.array(ref) >= 0.95))
            print(f"  {label:14s} T={t:3d} | 코드 {pc:6.1%} / 일 단위 {pr:6.1%}"
                  f" (평균 DSR {np.nanmean(code):.2f} / {np.mean(ref):.2f})")


if __name__ == "__main__":
    main()
