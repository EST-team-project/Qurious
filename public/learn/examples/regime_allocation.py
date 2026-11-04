"""시장 국면(추세 × 변동성)으로 주식 비중을 조절하는 규칙 — 판정 · 자금 이동 · 「미래 값이 과거 판정을 못 바꾼다」를 보이는 예제.

실행    python regime_allocation.py        (numpy 만 · 네트워크 없음)
자료    모두 합성 — 수익률은 시드 7 의 난수로 만든 가상 값이고 기준 비중도 손으로 정한 값이다(실제 시세 · 실제 계좌가 아니다).
        국면 규칙(120일 평균 · 20일 연변동성 20% · 배수 1.1 / 0.85 / 0.75 / 0.5 · 줄일 때 채권 70% 현금 30%)은 Qurious 앱의 명시적 규칙을
        줄여 옮긴 것이다. 이 값은 연구가 정해 준 것이 아니라 프로젝트가 정한 값이다.
흐름    ① 같은 합성 수익률에서 시간이 흘러 국면이 바뀐다(200일째 → 240일째)
        ② 200일 뒤의 값을 모두 바꿔도 200일째까지의 판정은 같다 = 그날까지의 데이터만 쓴다
        ③ 주식 비중을 줄일 때 채권 · 현금으로 어떻게 옮겨 가는가
"""
from __future__ import annotations

import numpy as np

MULT = {"up_low": 1.1, "up_high": 0.85, "down_low": 0.75, "down_high": 0.5}


def regime(r: np.ndarray) -> dict:
    """r: 일간 수익률 배열. 추세비 = 지수 마지막 ÷ 최근 120개 평균 · 변동성 = 최근 20일 표준편차(ddof=1) × √252."""
    if len(r) < 120:
        raise ValueError("국면 판정에는 120거래일 이상이 필요합니다.")
    index = np.cumprod(1 + r)
    ratio = float(index[-1] / index[-120:].mean())
    vol = float(r[-20:].std(ddof=1) * np.sqrt(252))
    key = ("up" if ratio >= 1 else "down") + "_" + ("high" if vol >= 0.20 else "low")
    return {"key": key, "trend_ratio": round(ratio, 4), "vol_pct": round(vol * 100, 1), "mult": MULT[key]}


def shift_weights(base: dict[str, float], mult: float) -> dict[str, float]:
    """주식(국내 + 해외) 비중을 mult 배로 바꾼다. 늘릴 때는 채권 · 현금에서 비례해 가져오고, 줄일 때는 채권 70% · 현금 30% 로 보낸다. 대체자산은 그대로."""
    t = {k: v / 100 for k, v in base.items()}
    eq = t["국내주식"] + t["해외주식"]
    shift = eq * mult - eq                                    # 줄이면 음수
    if shift > 0:
        shift = min(shift, t["국내채권"] + t["현금"])
        pool = t["국내채권"] + t["현금"]
        t["국내채권"] -= shift * t["국내채권"] / pool
        t["현금"] -= shift * t["현금"] / pool
    else:
        t["국내채권"] -= shift * 0.7
        t["현금"] -= shift * 0.3
    scale = (eq + shift) / eq
    t["국내주식"] *= scale
    t["해외주식"] *= scale
    return {k: round(v * 100, 1) for k, v in t.items()}


def main() -> None:
    rng = np.random.default_rng(7)
    r = np.r_[rng.normal(0.0006, 0.007, 200), rng.normal(-0.002, 0.022, 40)]
    print("① 시간이 흘러 국면이 바뀐다 (합성 수익률)")
    print("   200일째까지:", regime(r[:200]))
    print("   240일째까지:", regime(r))
    r2 = r.copy()
    r2[200:] = 0.05                                           # 미래 값을 모두 바꿔도
    same = regime(r[:200]) == regime(r2[:200])
    print("② 200일 뒤 값을 5% 로 바꿔도 200일째 판정이 같은가:", same)

    base = {"국내주식": 30, "해외주식": 30, "국내채권": 25, "대체자산": 10, "현금": 5}   # 합성 기준 비중(%)
    print("③ 자금 이동 (합성 기준 비중, %)")
    print("   기준      :", base)
    print("   ×0.5(하락·고변동):", shift_weights(base, 0.5))
    print("   ×1.1(상승·저변동):", shift_weights(base, 1.1))


if __name__ == "__main__":
    main()
