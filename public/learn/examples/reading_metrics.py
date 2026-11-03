"""성과 지표 읽기 — 같은 수익률 · 다른 낙폭, 같은 이름 · 다른 샤프, 승률과 손익비 (합성 데이터).

실행    python reading_metrics.py      (numpy 만 · 외부 접속 없음)
자료    ① 합성 일간 수익률 252개(시드 고정) ② 장에 실린 열흘 수익률 ③ 손으로 정한 승률 · 손익비 숫자
        실제 시세가 아니라 계산이 어떻게 움직이는지 보이려고 만든 숫자다.

함수
    max_drawdown(r)           일간 수익률 → 최대 낙폭(시작 값 1.0 을 고점에 넣는다)
    daily_stats(r)            최종 수익률 · 평균 · 표준편차 · 샤프 · 오른 날 비율 · MDD · 최고점 못 되찾은 기간 한 묶음
    extreme_orders(base, ...) 같은 수익률을 여러 번 섞어 MDD 가 가장 작은 · 가장 큰 순서를 고른다
    sharpe_three_ways(r)      앱에 있는 세 가지 샤프 정의를 같은 수익률에 적용
    exit_cost_example(...)    익절 · 손절을 비용 뒤 비율로 바꿔 손익비 · 본전 승률을 낸다
    required_years(sr)        연환산 샤프가 t 값 2 를 넘기려면 몇 년의 자료가 필요한가

비용 상수는 2026-11-03 기준 앱의 비용 모델과 같은 값이다(코스피 · 온라인 계좌 · 매도세 합계 0.20%).
세율과 수수료는 바뀔 수 있으니 실제로 쓸 때는 공식 안내를 확인한다.
"""
from __future__ import annotations

import numpy as np

# ── 비용 상수 (편도 비율) ─────────────────────────────────────────────
FEE_ONLINE_KRX = 0.000140527      # 위탁수수료(온라인 계좌)
FEE_CLEARING = 0.000036396        # 유관기관 제비용(매수 · 매도 양쪽)
SELL_TAX_KOSPI_2026 = 0.0005 + 0.0015   # 증권거래세 0.05% + 농어촌특별세 0.15% (매도에만)


def max_drawdown(r) -> float:
    """최대 낙폭 — 음수 비율. 시작 값 1.0 도 고점 후보에 넣어, 첫날부터 떨어진 경우도 센다."""
    cum = np.concatenate([[1.0], np.cumprod(1 + np.asarray(r, dtype=float))])
    return float((cum / np.maximum.accumulate(cum) - 1).min())


def longest_underwater(r) -> int:
    """최고점을 되찾지 못한 채 이어진 가장 긴 기간(거래일 수). 시작 값 1.0 도 최고점으로 센다."""
    cum = np.concatenate([[1.0], np.cumprod(1 + np.asarray(r, dtype=float))])
    below = cum < np.maximum.accumulate(cum)
    best = run = 0
    for flag in below:
        run = run + 1 if flag else 0
        best = max(best, run)
    return best


def daily_stats(r) -> dict:
    r = np.asarray(r, dtype=float)
    return {
        "최종 수익률": float(np.prod(1 + r) - 1),
        "일 평균": float(r.mean()),
        "일 표준편차": float(r.std(ddof=1)),
        "샤프(무위험 0)": float(r.mean() / r.std(ddof=1) * np.sqrt(252)),
        "오른 날 비율": float((r > 0).mean()),
        "MDD": max_drawdown(r),
        "최고점 못 되찾은 가장 긴 기간": longest_underwater(r),
    }


def extreme_orders(base, n_shuffles: int = 2000, seed: int = 2026):
    """같은 수익률 묶음을 n 번 섞어 MDD 가 가장 작은 순서 · 가장 큰 순서와 MDD 중앙값을 돌려준다."""
    rng = np.random.default_rng(seed)
    tries = []
    for _ in range(n_shuffles):
        order = rng.permutation(base)
        tries.append((max_drawdown(order), order))
    tries.sort(key=lambda t: t[0])
    mdds = np.array([m for m, _ in tries])
    return tries[-1][1], tries[0][1], float(np.median(mdds))     # (가장 얕은, 가장 깊은, 중앙값)


def sharpe_three_ways(r, rf: float = 0.02, ppy: int = 252) -> dict:
    """앱 안의 세 곳이 쓰는 샤프 정의를 같은 수익률에 적용한다(구현 모양만 옮긴 것)."""
    r = np.asarray(r, dtype=float)
    # ① 백테스트: 무위험 0 · 표준편차 ddof=1 · √252
    a = r.mean() / r.std(ddof=1) * np.sqrt(ppy)
    # ② 모의계좌 지표 묶음: 연 무위험을 하루치로 바꿔 날마다 뺀 뒤 √252
    rf_day = (1 + rf) ** (1 / ppy) - 1
    ex = r - rf_day
    b = ex.mean() / ex.std(ddof=1) * np.sqrt(ppy)
    # ③ 테스트베드 기준: (연 평균 − 연 무위험) ÷ 연 표준편차
    c = (r.mean() * ppy - rf) / (r.std(ddof=1) * np.sqrt(ppy))
    return {"백테스트식(무위험 0)": float(a), "모의계좌식(일 무위험을 날마다 뺌)": float(b), "테스트베드식(연 평균 − 2%)": float(c)}


def exit_cost_example(take_profit_pct: float, stop_loss_pct: float, slippage_bps: float = 0.0) -> dict:
    """익절 · 손절을 한 번씩 체결했다고 보고 비용 뒤 비율로 바꾼다(코스피 · 같은 매입금액)."""
    slip = slippage_bps / 10_000
    buy = FEE_ONLINE_KRX + FEE_CLEARING + slip
    sell = buy + SELL_TAX_KOSPI_2026
    win = ((1 + take_profit_pct / 100) * (1 - sell) / (1 + buy) - 1) * 100
    loss = -((1 - stop_loss_pct / 100) * (1 - sell) / (1 + buy) - 1) * 100
    return {"익절(%)": win, "손절(%)": -loss, "손익비": win / loss, "본전 승률(%)": loss / (win + loss) * 100}


def required_years(annual_sharpe: float, t: float = 2.0) -> float:
    """t = 샤프(한 기간) × √(기간 수) 에서, 연환산 샤프가 t 에 닿는 데 필요한 햇수 = (t ÷ 샤프)² (수익률이 서로 독립이라는 가정)."""
    return (t / annual_sharpe) ** 2


def main() -> None:
    # ① 같은 수익률 252개를 다른 순서로 ─────────────────────────────────
    base = np.random.default_rng(3).normal(0.0008, 0.01, 252)       # 합성: 평균 0.08% · 표준편차 1% · 시드 3
    shallow, deep, median = extreme_orders(base)
    print("① 같은 일간 수익률 252개 — 순서만 다르다 (합성 데이터 · 시드 3 · 2,000번 섞음 · 시드 2026)")
    print("  A = MDD 가 가장 작았던 순서 · B = MDD 가 가장 컸던 순서")
    sa, sb = daily_stats(shallow), daily_stats(deep)
    for key, kind in (("최종 수익률", "pct"), ("일 평균", "pct"), ("일 표준편차", "plain"), ("샤프(무위험 0)", "num"),
                      ("오른 날 비율", "plain"), ("MDD", "pct"), ("최고점 못 되찾은 가장 긴 기간", "days")):
        fmt = {"pct": lambda v: f"{v * 100:+.2f}%", "plain": lambda v: f"{v * 100:.2f}%", "num": lambda v: f"{v:.3f}",
               "days": lambda v: f"{v}거래일"}[kind]
        print(f"  {key}   A {fmt(sa[key])}   B {fmt(sb[key])}")
    print(f"  2,000번 섞은 MDD 중앙값 {median * 100:+.2f}%")

    # ② 샤프 세 가지 ─────────────────────────────────────────────────
    ten = np.array([0.01, 0.02, -0.03, -0.02, 0.015, 0.01, -0.01, 0.02, 0.005, -0.005])
    print("② 같은 열흘 수익률에 샤프 세 정의를 적용 (연 무위험 2%)")
    for name, v in sharpe_three_ways(ten).items():
        print(f"  {name:<30}{v:>8.4f}")

    # ③ 승률 · 손익비 · 기대값 ────────────────────────────────────────
    print("③ 승률이 높아도 기대값이 음수일 수 있다 (거래 한 건 단위 · 비용 전 · 손으로 정한 숫자)")
    for p, w, l in ((0.9, 1.0, 10.0), (0.4, 3.0, 1.5)):
        e = p * w - (1 - p) * l
        print(f"  승률 {p * 100:.0f}% · 평균 이익 +{w}% · 평균 손실 -{l}%  →  기대값 {e:+.2f}%/건")
    for rr in (0.5, 1.0, 1.5, 2.0, 3.0):
        print(f"  손익비 {rr:.1f} → 본전 승률 {100 / (1 + rr):.1f}%")

    # ④ 비용을 넣으면 ──────────────────────────────────────────────
    print("④ 익절 +1.5% · 손절 -1.0% 를 비용 뒤 비율로 (코스피 · 2026-11-03 비용 모델 · 슬리피지는 가정)")
    for slip in (0, 10):
        x = exit_cost_example(1.5, 1.0, slip)
        print(f"  슬리피지 {slip:>2}bp  익절 {x['익절(%)']:+.4f}%  손절 {x['손절(%)']:+.4f}%  "
              f"손익비 {x['손익비']:.4f}  본전 승률 {x['본전 승률(%)']:.4f}%")

    # ⑤ 샤프와 기간 ────────────────────────────────────────────────
    print("⑤ 연환산 샤프가 t 값 2 에 닿으려면 (수익률이 서로 독립이라는 가정)")
    for sr in (0.5, 1.0, 1.5, 2.0):
        print(f"  샤프 {sr:.1f} → {required_years(sr):.1f}년")


if __name__ == "__main__":
    main()
