"""배당 기준일 · 배당락일 · 마지막 매수일 — 거래일 달력으로 세는 예제.

실행    python dividend_dates.py      (표준 라이브러리만 · 외부 접속 없음)
규칙    보통거래는 체결 후 3일째(T+2)에 결제되고, 결제된 사람이 기준일의 주주명부에 오른다.
        그래서 기준일이 거래일이면 배당락일은 그 하루 전 거래일, 마지막 배당 매수일은 이틀 전 거래일이다.
        기준일이 휴장일(12-31 등)이면 기준일 이하 마지막 거래일을 L 로 두고 L 에서 센다.
        (한국거래소 「배당락/권리락」 설명, 2026-11-03 열람 · Qurious 수집기의 ex_dividend_date 와 같은 규칙)
주의    휴장일은 이 예제를 위해 손으로 넣은 가정이다. 실제 휴장일은 거래소 공지를 따른다.
        T+1(lag=1)은 2026-11-02 에 보도된 초안 로드맵을 가정한 계산일 뿐, 확정된 제도가 아니다.
"""
from __future__ import annotations

import bisect
from datetime import date, timedelta

HOLIDAYS = {date(2025, 12, 25), date(2025, 12, 31), date(2026, 1, 1),
            date(2026, 12, 25), date(2026, 12, 31), date(2027, 1, 1)}
WEEKDAY = "월화수목금토일"


def calendar(start: date, end: date, holidays: set[date] = HOLIDAYS) -> list[date]:
    """start ~ end 의 거래일(평일 − 휴장일)."""
    out, d = [], start
    while d <= end:
        if d.weekday() < 5 and d not in holidays:
            out.append(d)
        d += timedelta(days=1)
    return out


def dates_for(cal: list[date], record: date, lag: int = 2) -> dict[str, date]:
    """기준일 → L(기준일 이하 마지막 거래일) · 마지막 매수일 · 배당락일 · 마지막 매수분의 결제일."""
    i = bisect.bisect_right(cal, record) - 1          # L 의 위치
    return {
        "L": cal[i],
        "last_buy": cal[i - lag],                      # 이 날 산 주식이 L 에 결제된다
        "ex": cal[i - lag + 1],                        # 이 날부터 사면 이번 배당을 못 받는다
        "settle": cal[i],
    }


def settle_of(cal: list[date], buy_day: date, lag: int = 2) -> date:
    """buy_day(거래일)에 체결된 주식의 결제일 = 거래일 달력에서 lag 칸 뒤."""
    return cal[cal.index(buy_day) + lag]


def fmt(d: date) -> str:
    return f"{d.isoformat()}({WEEKDAY[d.weekday()]})"


def show(cal: list[date], record: date, lag: int = 2) -> None:
    r = dates_for(cal, record, lag)
    print(f"  기준일 {fmt(record)}  L {r['L'].isoformat()}  마지막 매수 {fmt(r['last_buy'])}  배당락 {fmt(r['ex'])}")


def main() -> None:
    cal = calendar(date(2022, 1, 1), date(2027, 1, 31))

    print("① 기준일 → 배당락일 · 마지막 매수일 (T+2, 거래일로 센다)")
    show(cal, date(2026, 12, 31))        # 휴장일 — 12-30 이 L
    show(cal, date(2026, 6, 30))
    print("  · 규정 설명의 6월 결산 예(6/28 마지막 매수 · 6/29 배당락 · 6/30 기준일)와 같은 구조를 2022년 달력으로 확인")
    show(cal, date(2022, 6, 30))

    print("② 달력 날짜로 세면 틀린다: 기준일 2026-06-30 에서 달력 2일 전")
    naive = date(2026, 6, 30) - timedelta(days=2)
    real = dates_for(cal, date(2026, 6, 30))["ex"]
    print(f"  달력 −2일 {fmt(naive)} (거래일 아님)  ↔  배당락일 {fmt(real)}")

    print("③ 기준일 2026-12-31(휴장): 어느 날 산 주식이 명부에 오르나(결제일이 기준일 이하여야 한다)")
    record = date(2026, 12, 31)
    for buy in (date(2026, 12, 28), date(2026, 12, 29), date(2026, 12, 30)):
        st = settle_of(cal, buy)
        print(f"  {fmt(buy)} 매수 → 결제 {fmt(st)}  {'명부에 오름' if st <= record else '이번 배당 못 받음'}")

    print("④ T+1 이 시행된다면(초안 로드맵 가정): 기준일 2026-12-31")
    show(cal, date(2026, 12, 31), lag=1)


if __name__ == "__main__":
    main()
