"""기술적 스크리닝 — 정배열 · 52주 신고가를 합성 가격으로 직접 계산하고, 정의를 바꾸면 통과 종목 수가 달라지는 것을 보이는 예제.

실행    python technical_screening.py        (numpy 만 · 네트워크 없음)
자료    모두 합성 — 가격은 시드가 고정된 난수 걸음으로 만든 가상 값이다(실제 종목이 아니고, 정배열이 오른다는 뜻도 아니다).
        「정배열」의 기간 조합(5/20/60 또는 5/20/60/120)은 규정이 아니라 관행이다.
흐름    ① 이동평균을 구하고 정배열 일수를 센다(봉이 모자란 앞부분은 판정할 수 없다)
        ② 52주 신고가 — 252봉이 다 있을 때만 판정하는 방식과, 65봉부터 있는 만큼의 창으로 판정하는 방식이 다르다
        ③ 합성 종목 10개에 정의 네 가지를 적용하면 통과 수가 달라진다(정의 선택이 결과를 바꾼다)
"""
from __future__ import annotations

import numpy as np


def sma(c: np.ndarray, n: int) -> np.ndarray:
    """단순 이동평균 — 처음 n-1 봉은 계산할 수 없어 nan."""
    out = np.full(len(c), np.nan)
    cs = np.cumsum(np.insert(c, 0, 0.0))
    out[n - 1:] = (cs[n:] - cs[:-n]) / n
    return out


def rolling_max(c: np.ndarray, n: int, min_periods: int) -> np.ndarray:
    out = np.full(len(c), np.nan)
    for i in range(len(c)):
        if i + 1 >= min_periods:
            out[i] = c[max(0, i - n + 1): i + 1].max()
    return out


def path(seed: int, days: int = 300, mu: float = 0.0008, sd: float = 0.012) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return 100 * np.cumprod(1 + rng.normal(mu, sd, days))


def aligned(c: np.ndarray, periods: tuple[int, ...]) -> np.ndarray:
    """정배열 = 짧은 선이 긴 선보다 위(선 개수는 관행). 가장 긴 선이 비어 있는 날은 nan 이라 False."""
    ma = [sma(c, k) for k in periods]
    ok = np.ones(len(c), dtype=bool)
    for a, b in zip(ma[:-1], ma[1:]):
        ok &= a > b
    return ok


def main() -> None:
    c = path(3)
    al4 = aligned(c, (5, 20, 60, 120))
    n_eval = int((~np.isnan(sma(c, 120))).sum())
    print("① 정배열(5>20>60>120) 일수:", int(al4.sum()), "/ 평가 가능", n_eval)

    full = rolling_max(c, 252, min_periods=252)
    short = rolling_max(c, 252, min_periods=65)
    hit_full = int(np.sum(c >= full))                              # nan 과의 비교는 False
    hit_short = int(np.sum(c >= short))
    print("② 52주 신고가 — 252봉이 다 있을 때만:", hit_full, "| 65봉부터 있는 만큼의 창:", hit_short)
    print("   마지막 종가 ÷ 최근 252봉 최고가:", round(float(c[-1] / c[-252:].max()), 3))

    print("③ 합성 10종목에 정의를 달리 적용한 오늘(마지막 날) 통과 수")
    res = {"정배열 3선(5>20>60)": 0, "정배열 4선(5>20>60>120)": 0, "52주 신고가 도달": 0, "52주 신고가 95% 근접": 0}
    for seed in range(100, 110):
        p = path(seed)
        res["정배열 3선(5>20>60)"] += bool(aligned(p, (5, 20, 60))[-1])
        res["정배열 4선(5>20>60>120)"] += bool(aligned(p, (5, 20, 60, 120))[-1])
        hi = p[-252:].max()
        res["52주 신고가 도달"] += bool(p[-1] >= hi)
        res["52주 신고가 95% 근접"] += bool(p[-1] >= 0.95 * hi)
    for k, v in res.items():
        print(f"   {k:<22}: {v} / 10")


if __name__ == "__main__":
    main()
