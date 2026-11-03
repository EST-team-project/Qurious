"""손절 · 익절 · 포지션 크기 — 손절 폭과 터치 확률, 위험 % 수량, 켈리 비율, 손절 유무 비교 (합성 데이터).

실행    python position_sizing.py      (numpy 만 · 외부 접속 없음)
자료    ① 합성 일간 수익률(난수 · 시드 42) ② 손으로 정한 계좌 · 가격 숫자 ③ 동전 던지기 모형(켈리)
        실제 시세가 아니라 계산이 어떻게 움직이는지 보이려고 만든 숫자다. 투자 권유가 아니다.

함수
    stop_touch_probability(...)   손절 폭마다 N일 안에 종가가 그 폭에 닿는 비율
    per_share_loss(...)           1주를 사서 손절가에 팔 때의 예상 손실(비용 · 슬리피지 포함 선택)
    quantity_limits(...)          위험 예산 · 현금 · 1회 예산 · 종목 비중 네 상한으로 구한 수량
    kelly_fraction(p, b)          켈리 비율 f* = (b·p − q) ÷ b
    log_growth(f, p, b)           한 번 걸 때의 평균 로그 성장률
    kelly_simulation(...)         같은 동전 던지기를 비율 f 마다 되풀이한 평균 로그 성장률과 고점 대비 낙폭의 중앙값
    stop_rule_compare(...)        같은 가격 경로에 손절 규칙이 있을 때와 없을 때

비용 상수는 2026-11-03 기준 Qurious 비용 모델과 같은 값이다(코스피 · 온라인 계좌 · 매도세 합계 0.20%).
세율과 수수료는 바뀔 수 있으니 실제로 쓸 때는 공식 안내를 확인한다.
"""
from __future__ import annotations

import math

import numpy as np

# ── 비용 상수 (편도 비율) ─────────────────────────────────────────────
FEE_ONLINE_KRX = 0.000140527      # 위탁수수료(온라인 계좌)
FEE_CLEARING = 0.000036396        # 유관기관 제비용(매수 · 매도 양쪽)
SELL_TAX_KOSPI_2026 = 0.0005 + 0.0015   # 증권거래세 0.05% + 농어촌특별세 0.15% (매도에만)


def stop_touch_probability(stop_pcts, sigma: float = 0.02, days: int = 20, n_paths: int = 10_000, seed: int = 42) -> dict:
    """일 수익률이 평균 0 · 표준편차 sigma 인 가격 경로 n_paths 개에서, 진입 뒤 days 일 안에
    **종가**가 진입가보다 stop_pct % 이상 낮아진 적이 있는 경로의 비율(같은 경로에 모든 폭을 적용)."""
    rng = np.random.default_rng(seed)
    path = np.cumprod(1 + rng.normal(0.0, sigma, (n_paths, days)), axis=1)
    lowest = path.min(axis=1)
    return {float(x): float((lowest <= 1 - x / 100).mean()) for x in stop_pcts}


def per_share_loss(entry: float, stop: float, slippage_bps: float | None = None) -> float:
    """1주를 entry 에 사서 stop 에 팔 때 잃는 돈. slippage_bps 가 None 이면 비용 없는 단순 식(entry − stop),
    숫자를 주면 매수 쪽은 비용만큼 더 내고 매도 쪽은 비용만큼 덜 받는 식(편도 슬리피지 bp)."""
    if slippage_bps is None:
        return entry - stop
    buy = FEE_ONLINE_KRX + FEE_CLEARING + slippage_bps / 10_000
    sell = buy + SELL_TAX_KOSPI_2026
    return entry * (1 + buy) - stop * (1 - sell)


def quantity_limits(equity: float, cash: float, budget: float, risk_pct: float, entry: float, stop: float,
                    position_cap_pct: float = 30.0, held_value: float = 0.0, slippage_bps: float | None = None) -> dict:
    """네 상한 중 가장 작은 쪽이 수량. 위험 예산 = 평가 자산 × 위험%, 나머지는 현금 · 1회 예산 · 종목 비중."""
    buy = 0.0 if slippage_bps is None else FEE_ONLINE_KRX + FEE_CLEARING + slippage_bps / 10_000
    limits = {
        "위험": equity * risk_pct / 100 / per_share_loss(entry, stop, slippage_bps),
        "현금": cash / (entry * (1 + buy)),
        "예산": budget / (entry * (1 + buy)),
        "비중": max(0.0, equity * position_cap_pct / 100 - held_value) / entry,
    }
    floors = {k: int(math.floor(v)) for k, v in limits.items()}
    qty = max(0, min(floors.values()))
    return {"수량": qty, "상한": floors, "막은 상한": [k for k, v in floors.items() if v == qty]}


def kelly_fraction(p: float, b: float = 1.0) -> float:
    """켈리 비율 f* = (b·p − q) ÷ b. p 는 이길 확률, b 는 걸린 돈에 대한 순이익 배수(동액 베팅이면 1)."""
    return (b * p - (1 - p)) / b


def log_growth(f: float, p: float) -> float:
    """동액 베팅(b = 1)에서 자본의 비율 f 를 걸 때 한 번당 평균 로그 성장률 g(f) = p·ln(1+f) + q·ln(1−f)."""
    return p * math.log(1 + f) + (1 - p) * math.log(1 - f)


def kelly_simulation(p: float = 0.53, fractions=(0.03, 0.06, 0.12), n_bets: int = 1000, reps: int = 2000, seed: int = 42) -> list[dict]:
    """같은 동전 던지기 결과(reps × n_bets)를 모든 비율에 쓰고, 비율마다 평균 로그 성장률과
    고점 대비 최대 낙폭(0~1)의 중앙값을 돌려준다."""
    rng = np.random.default_rng(seed)
    win = rng.random((reps, n_bets)) < p
    rows = []
    for f in fractions:
        factor = np.where(win, 1 + f, 1 - f)
        wealth = np.cumprod(factor, axis=1)
        peak = np.maximum.accumulate(np.concatenate([np.ones((reps, 1)), wealth], axis=1), axis=1)[:, 1:]
        mdd = (1 - wealth / peak).max(axis=1)
        rows.append({"f": f, "성장률": float(np.log(factor).mean()), "MDD 중앙값": float(np.median(mdd))})
    return rows


def stop_rule_compare(drift: float, stop_pct: float = 10.0, sigma: float = 0.02, days: int = 60,
                      n_paths: int = 20_000, seed: int = 42) -> dict:
    """같은 가격 경로에서 (가) 끝까지 보유 (나) 종가가 진입가 대비 -stop_pct % 이하가 된 날 그 종가에 팔고 현금(수익 0)으로 둠."""
    rng = np.random.default_rng(seed)
    path = np.cumprod(1 + rng.normal(drift, sigma, (n_paths, days)), axis=1)
    hold = path[:, -1] - 1
    hit = path <= 1 - stop_pct / 100
    stopped = hit.any(axis=1)
    first = hit.argmax(axis=1)
    exit_value = np.where(stopped, path[np.arange(n_paths), first], path[:, -1]) - 1
    return {"손절 발동 비율": float(stopped.mean()),
            "보유": {"평균": float(hold.mean()), "하위 5%": float(np.percentile(hold, 5))},
            "손절": {"평균": float(exit_value.mean()), "하위 5%": float(np.percentile(exit_value, 5))}}


def exit_cost_example(take_profit_pct: float, stop_loss_pct: float, slippage_bps: float = 0.0) -> dict:
    """익절 · 손절을 한 번씩 체결했다고 보고 비용 뒤 비율로 바꾼다(코스피 · 같은 매입금액)."""
    buy = FEE_ONLINE_KRX + FEE_CLEARING + slippage_bps / 10_000
    sell = buy + SELL_TAX_KOSPI_2026
    win = ((1 + take_profit_pct / 100) * (1 - sell) / (1 + buy) - 1) * 100
    loss = -((1 - stop_loss_pct / 100) * (1 - sell) / (1 + buy) - 1) * 100
    return {"익절": win, "손절": -loss, "손익비": win / loss, "본전 승률": loss / (win + loss) * 100}


def main() -> None:
    # ① 손절 폭과 터치 확률 ────────────────────────────────────────────
    print("① 20일 안에 종가가 손절 폭에 닿을 확률 (합성 데이터 · 평균 0 · 일 표준편차 2% · 경로 10,000개 · 시드 42)")
    for x, prob in stop_touch_probability((1, 2, 4, 6, 8)).items():
        print(f"  진입가 대비 -{x:.0f}% 손절  {prob * 100:5.1f}%")

    # ② 익절 · 손절 비율의 비용 뒤 손익비 ─────────────────────────────
    print("② 익절 +1.5% · 손절 -1.0% 를 비용 뒤 비율로 (코스피 · 2026-11-03 비용 모델 · 슬리피지는 가정)")
    for slip in (0, 10):
        x = exit_cost_example(1.5, 1.0, slip)
        print(f"  슬리피지 {slip:>2}bp  익절 {x['익절']:+.4f}%  손절 {x['손절']:+.4f}%  "
              f"손익비 {x['손익비']:.4f}  본전 승률 {x['본전 승률']:.4f}%")

    # ③ 위험 % 로 수량 구하기 ─────────────────────────────────────────
    equity, entry, stop = 10_000_000, 50_000, 48_000
    print(f"③ 위험 1% 수량 (자산 {equity:,}원 · 진입 {entry:,}원 · 손절 {stop:,}원 · 위험 예산 {equity // 100:,}원)")
    print(f"  비용 없는 식  {equity // 100:,} ÷ {entry - stop:,} = {equity // 100 // (entry - stop)}주")
    for slip in (0, 10):
        loss = per_share_loss(entry, stop, slip)
        q = quantity_limits(equity, equity, 3_000_000, 1, entry, stop, slippage_bps=slip)
        print(f"  슬리피지 {slip:>2}bp  1주 예상 손실 {loss:,.1f}원  위험 상한 {q['상한']['위험']}주  최종 {q['수량']}주")

    # ④ 같은 위험, 다른 손절 폭 ──────────────────────────────────────
    print("④ 같은 위험(자산의 1%)이라도 손절 폭이 넓을수록 수량이 줄어든다 (진입 50,000원 · 비용 전 · 비중 상한 30%)")
    for dist in (1_000, 2_000, 4_000, 8_000):
        by_risk = equity // 100 // dist
        q = quantity_limits(equity, equity, equity, 1, entry, entry - dist)
        print(f"  손절 폭 {dist:>5,}원({dist / entry * 100:4.1f}%)  위험 기준 {by_risk:>3}주  투입 {by_risk * entry:>9,}원  비중 상한 적용 {q['수량']:>3}주")

    # ⑤ 네 상한 중 어느 것이 막나 ─────────────────────────────────────
    print("⑤ 손절 폭이 좁아 위험 기준 수량이 커지면 다른 상한이 먼저 막는다 (슬리피지 10bp · 1회 예산 3,000,000원)")
    for dist in (2_000, 500):
        q = quantity_limits(equity, equity, 3_000_000, 1, entry, entry - dist, slippage_bps=10)
        lim = " ".join(f"{k} {v}" for k, v in q["상한"].items())
        print(f"  손절 폭 {dist:>5,}원  상한 [{lim}]  → {q['수량']}주 (막은 상한: {', '.join(q['막은 상한'])})")

    # ⑥ 켈리 ─────────────────────────────────────────────────────────
    p = 0.53
    fstar = kelly_fraction(p)
    print(f"⑥ 켈리 (이길 확률 {p} · 동액 베팅)  f* = {fstar:.2f}")
    print("  이론 평균 로그 성장률 g(f)  " + "  ".join(
        f"{label} {log_growth(m * fstar, p):+.5f}" for label, m in (("0.5배", 0.5), ("1배", 1.0), ("2배", 2.0))))
    print(f"  절반 켈리 ÷ 풀 켈리 = {log_growth(0.5 * fstar, p) / log_growth(fstar, p):.2f}")
    print("  동전 1,000번 × 2,000번 반복 (합성 데이터 · 시드 42, 같은 던지기를 세 비율에 모두 씀)")
    for row, label in zip(kelly_simulation(p, [m * fstar for m in (0.5, 1.0, 2.0)]), ("0.5배", "1배  ", "2배  ")):
        print(f"  {label} f={row['f']:.2f}  평균 로그 성장률 {row['성장률']:+.5f}  고점 대비 최대 낙폭 중앙값 {row['MDD 중앙값'] * 100:.1f}%")

    # ⑦ 손절이 있으면 어떻게 달라지나 ─────────────────────────────────
    print("⑦ 손절 -10% 규칙 유무 (합성 데이터 · 60일 · 일 표준편차 2% · 경로 20,000개 · 시드 42 · 손절 뒤는 현금)")
    for drift in (0.0, 0.0005):
        r = stop_rule_compare(drift)
        print(f"  하루 평균 {drift * 100:+.2f}%  손절 발동 {r['손절 발동 비율'] * 100:.1f}%  "
              f"평균 보유 {r['보유']['평균'] * 100:+.2f}% 손절 {r['손절']['평균'] * 100:+.2f}%  "
              f"하위 5% 보유 {r['보유']['하위 5%'] * 100:+.1f}% 손절 {r['손절']['하위 5%'] * 100:+.1f}%")


if __name__ == "__main__":
    main()
