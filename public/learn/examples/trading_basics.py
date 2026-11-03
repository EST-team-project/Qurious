"""주식의 기본 — 호가단위 · 상한가 하한가 · 결제일(T+2)을 직접 계산해 보는 예제.

실행    python trading_basics.py      (표준 라이브러리만 · 외부 접속 없음)
자료    한국거래소 KRX 규정/제도 「매매거래제도일반」의 호가가격단위 · 가격제한폭 · 결제 설명과
        코스닥시장 가격제한폭 산출 예(기준가 9,940원) — 2026-11-03 열람. 바뀔 수 있으니 공식 안내를 확인한다.
주의    휴장일 목록은 이 예제의 계산을 위해 손으로 넣은 가정이다(연말 12-31 휴장 규칙과 성탄절 · 신정만 넣었다).
        실제 휴장일은 거래소 공지를 따른다.

함수
    tick_size(price)               주권의 호가가격단위
    price_limit(base, pct)         하루 가격제한폭(원) — 기준가 × 비율을 기준가 가격대의 호가단위 미만에서 자른다
    settle_date(trade_day, ...)    체결일 → 결제일 (기본 T+2, 휴장일을 건너뛴다)
"""
from __future__ import annotations

from datetime import date, timedelta

# 주권 호가가격단위 — (가격 미만, 단위). 마지막 줄은 50만 원 이상.
TICKS = ((2_000, 1), (5_000, 5), (20_000, 10), (50_000, 50), (200_000, 100), (500_000, 500), (float("inf"), 1_000))

# 손으로 넣은 휴장일 가정 — 연말 12-31 은 휴장이다(거래소 규정). 토 · 일은 따로 거른다.
HOLIDAYS = {
    date(2025, 12, 25), date(2025, 12, 31), date(2026, 1, 1),
    date(2026, 12, 25), date(2026, 12, 31),
}
WEEKDAY = "월화수목금토일"


def tick_size(price: int) -> int:
    for upper, tick in TICKS:
        if price < upper:
            return tick
    raise ValueError(price)


def on_tick(price: int) -> bool:
    return price % tick_size(price) == 0


def price_limit(base: int, pct: int = 30) -> tuple[int, int, int]:
    """(한도, 상한가, 하한가). pct 는 정수 퍼센트(유가증권 · 코스닥 30, 코넥스 15).

    한도 = 기준가 × pct% 를 기준가가 속한 가격대의 호가단위 미만에서 자른다.
    상한가 = 기준가 + 한도, 하한가 = 기준가 − 한도.
    기준가 근처에서 호가단위가 바뀌는 경우의 세부 절사 규칙은 다루지 않는다(아래 출력 ③ 참고).
    """
    tick = tick_size(base)
    limit = base * pct // 100 // tick * tick          # 정수 계산 — 부동소수점 오차가 끼지 않게
    return limit, base + limit, base - limit


def is_trading_day(d: date, holidays: set[date] = HOLIDAYS) -> bool:
    return d.weekday() < 5 and d not in holidays


def add_trading_days(d: date, n: int, holidays: set[date] = HOLIDAYS) -> date:
    while n > 0:
        d += timedelta(days=1)
        if is_trading_day(d, holidays):
            n -= 1
    return d


def settle_date(trade_day: date, holidays: set[date] = HOLIDAYS, lag: int = 2) -> date:
    """체결일 + lag 거래일. 지금 제도는 lag=2(T+2), 거래일 달력으로 센다."""
    return add_trading_days(trade_day, lag, holidays)


def fmt(d: date) -> str:
    return f"{d.isoformat()}({WEEKDAY[d.weekday()]})"


def main() -> None:
    print("① 상한가 · 하한가: 코스닥 규정의 예(기준가 9,940원, 호가단위 10원)")
    limit, up, low = price_limit(9_940)
    print(f"  한도 9,940 × 30% = {9_940 * 30 // 100:,} → 호가단위 10원 미만 자름 → {limit:,}")
    print(f"  상한가 {up:,}  하한가 {low:,}")
    print("  코넥스(±15%)로 계산하면", " / ".join(f"{x:,}" for x in price_limit(9_940, 15)))

    print("② 호가단위 ÷ 가격: 구간 경계 바로 아래와 위")
    for p in (1_999, 2_000, 4_995, 5_000, 19_990, 20_000, 49_950, 50_000, 199_900, 200_000, 499_500, 500_000):
        t = tick_size(p)
        print(f"  {p:>8,}원  단위 {t:>5,}원  {t / p * 100:.3f}%")

    print("③ 구간 경계에 걸친 기준가 19,990원")
    limit, up, low = price_limit(19_990)
    print(f"  한도 {limit:,}  상한가 후보 {up:,} (호가단위에 맞나: {on_tick(up)})  하한가 후보 {low:,} ({on_tick(low)})")
    print("  → 이런 기준가는 규정에서 상 · 하한가의 절사 방식을 따로 확인해야 한다")

    print("④ 체결일 → 결제일(T+2): 연말 휴장 · 신정을 건너뛴다")
    for d in (date(2025, 12, 24), date(2025, 12, 26), date(2025, 12, 29), date(2025, 12, 30)):
        print(f"  체결 {fmt(d)} → 결제 {fmt(settle_date(d))}")
    d = date(2025, 12, 29)
    print(f"  T+1 가정(아직 시행 전 · 초안 로드맵)이면 체결 {fmt(d)} → 결제 {fmt(settle_date(d, lag=1))}")


if __name__ == "__main__":
    main()
