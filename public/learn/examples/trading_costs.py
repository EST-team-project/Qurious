"""매매 비용 — 수수료 · 유관기관 제비용 · 증권거래세 · 농어촌특별세를 직접 계산해 보는 예제.

실행    python trading_costs.py      (표준 라이브러리만 · 외부 접속 없음)
요율    Qurious 비용 모델(app/services/trading_cost.py)의 값을 그대로 옮겨 적었다.
        · 2026-01-01 이후 거래세율(코스피 0.05% · 코스닥 0.20% · 코넥스 0.10%)과 농어촌특별세 0.15% 는
          증권거래세법 시행령 제5조 · 농어촌특별세법 제5조에서 2026-11-03 에 확인한 값이다.
        · 2019-06-03 거래세는 시행령 개정이유로 확인했고, 2023~2025 는 해설 자료와 맞춰 본 앱의 값이다(2021~2022 는 2차 자료).
        · 수수료(0.0140527%)는 한 증권사 온라인 계좌의 안내값이고, 유관기관 제비용(0.0036396%)은
          거래소 원가로 알려진 값이다. 증권사 · 계좌 종류 · 시기에 따라 다르다.
        · 슬리피지는 측정값이 아니라 가정값이다.
주의    세율은 바뀔 수 있다. 실제 거래의 정산액은 증권사 거래명세서가 정본이다. 세무 · 법률 자문이 아니다.
"""
from __future__ import annotations

from datetime import date, timedelta

FEE = 0.000140527          # 위탁수수료(편도) — 한 증권사 온라인 KRX 예
CLEARING = 0.000036396     # 유관기관 제비용(편도, 매수 · 매도 모두)
RURAL = 0.0015             # 농어촌특별세 — 코스피 매도에만
SLIPPAGE_BPS = 10.0        # 슬리피지 가정(편도 bp) — 가정일 뿐 측정값이 아니다

# 시행일별 증권거래세율 (시행일, 코스피, 코스닥, 코넥스)
SCHEDULE = (
    (date(2019, 6, 3), 0.0010, 0.0025, 0.0010),
    (date(2021, 1, 1), 0.0008, 0.0023, 0.0010),
    (date(2023, 1, 1), 0.0005, 0.0020, 0.0010),
    (date(2024, 1, 1), 0.0003, 0.0018, 0.0010),
    (date(2025, 1, 1), 0.0000, 0.0015, 0.0010),
    (date(2026, 1, 1), 0.0005, 0.0020, 0.0010),
)
COL = {"KOSPI": 1, "KOSDAQ": 2, "KONEX": 3}

# 손으로 넣은 휴장일 가정 — 연말 12-31 휴장 · 성탄절 · 신정
HOLIDAYS = {date(2025, 12, 25), date(2025, 12, 31), date(2026, 1, 1)}


def sell_tax(day: date, market: str) -> tuple[float, float]:
    """(증권거래세율, 농어촌특별세율). 매도에만 붙는다."""
    if day < SCHEDULE[0][0]:
        raise ValueError("2019-06-03 이전은 이 예제가 다루지 않는다")
    rate = [row for row in SCHEDULE if day >= row[0]][-1][COL[market]]
    return rate, (RURAL if market == "KOSPI" else 0.0)


def order_cost(side: str, amount: float, day: date, market: str = "KOSPI") -> dict[str, float]:
    """한 주문의 비용(원). 슬리피지는 넣지 않는다 — 체결가에 이미 들어 있는 것으로 본다."""
    commission, clearing = amount * FEE, amount * CLEARING
    transfer = rural = 0.0
    if side == "sell":
        t, r = sell_tax(day, market)
        transfer, rural = amount * t, amount * r
    total = commission + clearing + transfer + rural
    return {"commission": commission, "clearing": clearing, "transfer": transfer, "rural": rural, "total": total}


def settle_date(trade_day: date, lag: int = 2) -> date:
    d = trade_day
    while lag > 0:
        d += timedelta(days=1)
        if d.weekday() < 5 and d not in HOLIDAYS:
            lag -= 1
    return d


def main() -> None:
    amount = 1_000_000
    print(f"① 거래대금 {amount:,}원: 비용 내역(원) · 슬리피지 제외")
    cases = [("코스피 2025", "KOSPI", date(2025, 6, 2)), ("코스피 2026", "KOSPI", date(2026, 6, 2)),
             ("코스닥 2026", "KOSDAQ", date(2026, 6, 2)), ("코넥스 2026", "KONEX", date(2026, 6, 2))]
    buy = order_cost("buy", amount, date(2026, 6, 2))
    print(f"  매수(어디서나)  수수료 {buy['commission']:.1f}  유관기관 {buy['clearing']:.1f}  합계 {buy['total']:.1f}")
    for label, market, day in cases:
        s = order_cost("sell", amount, day, market)
        rt = (buy["total"] + s["total"]) / amount * 100
        print(f"  매도 {label}  수수료 {s['commission']:.1f}  유관기관 {s['clearing']:.1f}  거래세 {s['transfer']:.1f}"
              f"  농특세 {s['rural']:.1f}  합계 {s['total']:.1f}  왕복 {rt:.4f}%")

    print("② 코스피 매도 세금 합계: 2025 → 2026")
    t25 = sum(sell_tax(date(2025, 6, 2), "KOSPI"))
    t26 = sum(sell_tax(date(2026, 6, 2), "KOSPI"))
    print(f"  2025 {t25 * 100:.2f}%  →  2026 {t26 * 100:.2f}%  (매도 세금 {t26 / t25 - 1:+.0%})")

    print("③ 슬리피지 편도 10bp 를 가정하면: 코스피 2026 왕복")
    base = (order_cost("buy", amount, date(2026, 6, 2))["total"] + order_cost("sell", amount, date(2026, 6, 2))["total"]) / amount
    print(f"  슬리피지 없음 {base * 100:.4f}%  →  있음 {(base + 2 * SLIPPAGE_BPS / 10_000) * 100:.4f}%  (왕복 +{2 * SLIPPAGE_BPS / 100:.2f}%p)")

    print("④ 연말 경계: 2025-12-29(월)에 체결한 코스피 매도 1,000,000원의 세금")
    trade = date(2025, 12, 29)
    settle = settle_date(trade)
    by_trade = sum(sell_tax(trade, "KOSPI")) * amount
    by_settle = sum(sell_tax(settle, "KOSPI")) * amount
    print(f"  체결일 {trade} → 결제일 {settle}")
    print(f"  체결일로 세율을 고르면 {by_trade:,.0f}원  /  결제일로 고르면 {by_settle:,.0f}원  (차이 {by_settle - by_trade:,.0f}원)")

    print("⑤ 한 해에 왕복 N회 하면: 코스피 2026, 순자산 대비 비용(단순 곱)")
    rt_free = base * 100
    rt_slip = (base + 2 * SLIPPAGE_BPS / 10_000) * 100
    for n in (1, 2, 12, 24):
        print(f"  연 {n:>2}회  슬리피지 없음 {n * rt_free:6.3f}%  슬리피지 10bp 가정 {n * rt_slip:6.3f}%")


if __name__ == "__main__":
    main()
