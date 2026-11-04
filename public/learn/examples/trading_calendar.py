"""거래일 달력 위에 일정 얹기 — 다음 거래일 · 둘째 목요일 만기 · 연말 휴장 · 배당락일 · 미국 발표의 한국 시각을 규칙으로 계산하는 예제.

실행    python trading_calendar.py        (표준 라이브러리만 · 네트워크 없음 · 시간대 데이터베이스도 쓰지 않는다)
자료    휴장일 표는 한국거래소(KRX) 「증시일정 > 휴장일」 화면을 2026-11-03 에 열람해 옮긴 평일 휴장일이다.
        실제 거래소 공지가 나오면 그쪽이 맞다 — 공식 표가 정본이고 이 파일은 학습용 사본이다.
        2026-12-29 같은 배당락일은 규칙으로 계산한 값이며 거래소 공지가 아니다.
흐름    ① 다음 거래일   ② 선물 · 옵션 월물의 최종거래일(두 번째 목요일, 휴장이면 앞 거래일)
        ③ 연말 휴장일   ④ 배당락일(기준일 이하 마지막 거래일의 한 거래일 전, 결제 T+2 가정)   ⑤ 미국 발표의 한국 시각
"""
from __future__ import annotations

import datetime as dt

D = dt.date

#: KRX 휴장일(평일만) — 2026-11-03 열람. 토 · 일은 따로 거른다.
HOLIDAYS = {
    # 2026
    D(2026, 1, 1), D(2026, 2, 16), D(2026, 2, 17), D(2026, 2, 18), D(2026, 3, 2), D(2026, 5, 1), D(2026, 5, 5),
    D(2026, 5, 25), D(2026, 6, 3), D(2026, 7, 17), D(2026, 8, 17), D(2026, 9, 24), D(2026, 9, 25), D(2026, 10, 5),
    D(2026, 10, 9), D(2026, 12, 25), D(2026, 12, 31),
    # 2027
    D(2027, 1, 1), D(2027, 2, 8), D(2027, 2, 9), D(2027, 3, 1), D(2027, 5, 3), D(2027, 5, 5), D(2027, 5, 13),
    D(2027, 7, 19), D(2027, 8, 16), D(2027, 9, 14), D(2027, 9, 15), D(2027, 9, 16), D(2027, 10, 4), D(2027, 10, 11),
    D(2027, 12, 27), D(2027, 12, 31),
}
# 2024 · 2025 의 연말 휴장일(실제) — 배당락일 검산용
HOLIDAYS |= {D(2024, 12, 31), D(2025, 12, 31)}


def is_trading(d: dt.date) -> bool:
    return d.weekday() < 5 and d not in HOLIDAYS


def prev_trading(d: dt.date, include_self: bool = True) -> dt.date:
    cur = d if include_self else d - dt.timedelta(days=1)
    while not is_trading(cur):
        cur -= dt.timedelta(days=1)
    return cur


def next_trading(d: dt.date) -> dt.date:
    cur = d + dt.timedelta(days=1)
    while not is_trading(cur):
        cur += dt.timedelta(days=1)
    return cur


def second_thursday(y: int, m: int) -> dt.date:
    first = D(y, m, 1)
    first_thu = first + dt.timedelta(days=(3 - first.weekday()) % 7)      # 목요일 = 3
    return first_thu + dt.timedelta(days=7)


def expiry(y: int, m: int) -> dt.date:
    """월물 최종거래일 — 두 번째 목요일, 휴장이면 앞 거래일로 당긴다."""
    return prev_trading(second_thursday(y, m))


def ex_div(record_date: dt.date) -> dt.date:
    """배당락일 = 기준일 이하 마지막 거래일의 한 거래일 전(결제 T+2 전제)."""
    return prev_trading(prev_trading(record_date), include_self=False)


def year_end_closure(y: int) -> dt.date:
    """연말 휴장일 — 12월 31일이 토 · 일이면 앞 평일. 이 예제는 휴장일 표에 있는 해만 맞춘다."""
    d = D(y, 12, 31)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


KST = dt.timezone(dt.timedelta(hours=9))


def us_to_kst(naive_local: dt.datetime, utc_offset_hours: int) -> dt.datetime:
    """미국 현지 시각 → 한국 시각. utc_offset_hours 는 그때의 미국 동부 UTC 오프셋(서머타임 EDT=-4, 표준 EST=-5)."""
    aware = naive_local.replace(tzinfo=dt.timezone(dt.timedelta(hours=utc_offset_hours)))
    return aware.astimezone(KST)


def main() -> None:
    print("① 2026-12-24 의 다음 거래일:", next_trading(D(2026, 12, 24)), "| 2026-12-30 의 다음 거래일:", next_trading(D(2026, 12, 30)))
    print("② 월물 최종거래일 (두 번째 목요일, 휴장이면 앞 거래일)")
    for y, m in [(2026, 11), (2026, 12), (2027, 5)]:
        st = second_thursday(y, m)
        ex = expiry(y, m)
        note = "  ← 둘째 목요일이 휴장이라 앞당김" if ex != st else ""
        print(f"   {y}-{m:02d}: 둘째 목요일 {st} → 최종거래일 {ex}{note}")
    print("③ 연말 휴장일:", {y: str(year_end_closure(y)) for y in (2024, 2025, 2026, 2027)})
    print("④ 12월 말 기준일 → 배당락일(계산)")
    for y in (2024, 2025, 2026):
        rec = D(y, 12, 31)
        print(f"   기준일 {rec} → 배당락일 {ex_div(rec)}")
    fomc = us_to_kst(dt.datetime(2026, 10, 28, 14, 0), -4)
    jobs = us_to_kst(dt.datetime(2026, 11, 6, 8, 30), -5)
    print("⑤ 미국 발표의 한국 시각")
    print("   FOMC 2026-10-28 14:00(EDT) →", fomc.strftime("%Y-%m-%d %H:%M KST"))
    print("   고용상황 2026-11-06 08:30(EST) →", jobs.strftime("%Y-%m-%d %H:%M KST"))


if __name__ == "__main__":
    main()
