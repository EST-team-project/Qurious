"""스트레스 검증의 기초 — 민감도(한 요인만 흔들기) · 시나리오(여러 요인을 한 이야기로) · 낙폭을 한도와 견주기를 합성 포트폴리오로 보이는 예제.

실행    python stress_test_basics.py        (표준 라이브러리 + numpy · 네트워크 없음)
자료    모두 합성 — 비중 · 충격 크기 · 듀레이션 · 볼록성 · 낙폭 한도는 모두 **예시로 정한 값**이다. 어느 감독기관의 시나리오도 아니고 실제 계좌도 아니다.
주의    스트레스 결과는 확률이 붙은 예측이 아니라 「가정한 조건에서의 손익」이다. 이 앱의 일손실 한도(3%)와는 다른 것이다 — 아래 낙폭 한도는 개념을 보이려는 가상값이다.
흐름    ① 민감도: 채권의 금리 +1%p 한 요인만 흔들었을 때 가격 변화(듀레이션 · 볼록성 근사)
        ② 시나리오: 주식 급락 + 금리 상승 + 대체자산 소폭 상승을 한 이야기로 묶어 자산별 손익 분해
        ③ 낙폭 vs 한도: 합성 수익 경로에 충격일을 넣고 최대낙폭을 가상 한도와 견준다
"""
from __future__ import annotations

import numpy as np


def bond_change(duration: float, convexity: float, dy: float) -> float:
    """채권 가격 변화율 근사: ΔP/P ≈ -D·Δy + ½·C·(Δy)²  (D 수정듀레이션, C 볼록성, Δy 금리 변화 — 1%p = 0.01)."""
    return -duration * dy + 0.5 * convexity * dy ** 2


def max_drawdown(curve: np.ndarray) -> float:
    """누적 배수 시계열의 최대 낙폭(음수 비율)."""
    peak = np.maximum.accumulate(curve)
    return float((curve / peak - 1).min())


def main() -> None:
    D, C = 5.0, 40.0                                                  # 듀레이션 · 볼록성(합성)
    print("① 민감도 — 채권 가격 변화(듀레이션 5 · 볼록성 40, 합성)")
    for dy in (-0.02, 0.0, 0.01, 0.03):
        print(f"   금리 {dy * 100:+.0f}%p → 가격 {bond_change(D, C, dy) * 100:+.2f}%  (듀레이션만: {(-D * dy + 0.0) * 100:+.2f}%)")

    w = {"국내주식": 0.30, "해외주식": 0.30, "국내채권": 0.30, "대체자산": 0.10}      # 합성 포트폴리오
    shock = {"국내주식": -0.30, "해외주식": -0.25, "국내채권": bond_change(D, C, 0.01), "대체자산": 0.05}
    pnl = {k: w[k] * shock[k] for k in w}
    print("② 시나리오 — 주식 급락 + 금리 +1%p + 대체자산 +5% (합성)")
    print("   시나리오 · 충격 · 손익(%p)")
    for k in w:
        print(f"   {k:<6} 비중 {w[k] * 100:>4.0f}%  충격 {shock[k] * 100:>+6.2f}%  손익 {pnl[k] * 100:>+6.2f}%p")
    print(f"   합계 손익 {sum(pnl.values()) * 100:+.2f}%  (가정한 조건에서의 손익이며 일어날 확률이 아니다)")

    rng = np.random.default_rng(21)
    r = rng.normal(0.0004, 0.008, 250)
    r[180] = -0.12                                                    # 충격일 하나를 넣는다
    curve = np.cumprod(1 + r)
    mdd = max_drawdown(curve)
    limit = -0.15                                                     # 가상의 누적 낙폭 한도(예시)
    print("③ 낙폭 vs 한도 (합성 250일 · 충격일 1회 · 가상 한도 -15%)")
    print(f"   최대낙폭 {mdd * 100:.2f}%  → 한도 {limit * 100:.0f}% 에", "닿음" if mdd <= limit else "닿지 않음")


if __name__ == "__main__":
    main()
