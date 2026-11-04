"""모의투자와 실거래의 체결 차이 — 호가 잔량을 쓸어 가는 시장가, 증권사 모의의 상한가 체결 규칙, 시간가중수익률 (합성 데이터).

실행    python paper_vs_real.py      (표준 라이브러리만 · 외부 접속 없음)
자료    ① 손으로 정한 매도 호가창(합성 · 실제 시세 아님) ② 한국투자증권 모의투자 대회규정에 실린 계산 예
        (2026-11-03 열람) ③ 손으로 정한 두 구간 수익률
        호가창은 계산이 어떻게 움직이는지 보이려고 만든 숫자다. 투자 권유가 아니다.

함수
    sweep_book(asks, qty, limit)   매수 주문 하나가 매도 호가를 낮은 가격부터 소진하며 체결되는 결과
    slippage_bp(avg, ref)          평균 체결가가 기준 가격보다 얼마나 불리한가(bp, 1bp = 0.01%)
    kis_limit_fill(...)            증권사 모의의 상한가 매수 · 하한가 매도 체결 수량 규칙(단주 미만은 버림)
    time_weighted_return(...)      외부 입출금의 영향을 없애려고 구간 수익률을 곱해 이은 수익률
"""
from __future__ import annotations

# (가격, 잔량) 매도 호가 5단계 — 가장 낮은 가격이 최우선 매도호가. 합성 데이터.
ASKS = [(10_000, 300), (10_010, 500), (10_020, 800), (10_050, 2_000), (10_100, 5_000)]


def sweep_book(asks, qty: int, limit: float | None = None) -> dict:
    """매수 주문 qty 주를 낮은 가격 호가부터 소진한다. limit 가 있으면 그 가격을 넘는 호가는 쓰지 않는다(지정가)."""
    filled, cost, levels = 0, 0, 0
    for price, size in asks:
        if filled >= qty or (limit is not None and price > limit):
            break
        take = min(size, qty - filled)
        filled += take
        cost += price * take
        levels += 1
    return {"체결": filled, "미체결": qty - filled, "평균가": cost / filled if filled else None, "호가 단계": levels}


def slippage_bp(avg: float, ref: float) -> float:
    """기준 가격 대비 평균 체결가의 불리한 정도(bp)."""
    return (avg / ref - 1) * 10_000


def kis_limit_fill(actual_volume: int, total_remaining: int, order_qty: int) -> int:
    """{(실제체결량 ÷ 총호가잔량) × 주문수량} × 0.1, 단주 미만은 버림. 정수만 써서 계산한다."""
    return (actual_volume * order_qty) // (total_remaining * 10)


def time_weighted_return(sub_returns) -> float:
    """구간 수익률을 곱해 이은 수익률. 구간 사이의 입금 · 출금은 각 구간 수익률에 들어가지 않는다."""
    total = 1.0
    for r in sub_returns:
        total *= 1 + r
    return total - 1


def main() -> None:
    ref = ASKS[0][0]
    depth = sum(size for _, size in ASKS)
    print(f"① 합성 매도 호가창에서 시장가 매수 (최우선 매도호가 {ref:,}원 · 5단계 잔량 합계 {depth:,}주)")
    for price, size in ASKS:
        print(f"  {price:>7,}원  잔량 {size:>5,}주")
    for qty in (100, 300, 1_000, 5_000, 10_000):
        r = sweep_book(ASKS, qty)
        extra = (r["평균가"] - ref) * r["체결"]
        tail = f"  미체결 {r['미체결']:,}주" if r["미체결"] else ""
        print(f"  {qty:>6,}주  평균 {r['평균가']:>9,.2f}원  {slippage_bp(r['평균가'], ref):+5.1f}bp  추가 지불 {extra:>9,.0f}원{tail}")

    r = sweep_book(ASKS, 5_000, limit=10_020)
    print(f"  5,000주를 10,020원 지정가로: 체결 {r['체결']:,}주 · 평균 {r['평균가']:,.2f}원 · 미체결 {r['미체결']:,}주")

    print("② 증권사 모의의 상한가 매수 체결 수량 = {(실제체결량 ÷ 총호가잔량) × 주문수량} × 0.1, 단주 미만 버림")
    for actual, order in ((3_000, 3_000), (30_000, 3_000), (3_000, 100)):
        print(f"  총호가잔량 500,000주 · 실제 체결량 {actual:>6,}주 · 주문 {order:>5,}주  →  모의 체결 {kis_limit_fill(actual, 500_000, order)}주")

    print("③ 시간가중수익률 (손으로 정한 숫자): 100 에서 시작 → +10% → 100 입금 → -10%")
    value = 100 * 1.10          # 첫 구간이 끝난 가치 110
    value = (value + 100) * 0.90   # 100 을 넣고 둘째 구간 -10% → 189
    invested = 100 + 100
    print(f"  최종 {value:,.0f} · 넣은 돈 {invested:,} → 단순 수익률 {(value - invested) / invested * 100:+.1f}%")
    print(f"  시간가중수익률 {time_weighted_return([0.10, -0.10]) * 100:+.1f}%")


if __name__ == "__main__":
    main()
