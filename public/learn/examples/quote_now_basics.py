"""「현재가」는 언제 값인가 — 시각으로 거래 구간을 가르고, 값의 나이를 재고, 출처 · 시각을 화면 글로 만드는 예제.

실행    python quote_now_basics.py        (표준 라이브러리만 · 네트워크 없음)
자료    모두 합성 — 날짜 · 시각 · 출처 이름은 손으로 정한 값이다. 구간 시각은 한국거래소(KRX) 규정 화면을 2026-11-03 에 열람한 값이고,
        호가 접수 시작 시각은 자료마다 다르다(08:20 · 08:30). 장전 시간외 종가(08:30~08:40, 전일 종가)는 다루지 않는다.
        휴장일은 예시로 2026-10-09 만 넣었다(실제 휴장일 표가 아니다). Qurious 실제 코드(app/services/quote_now.py)를 줄여 옮긴 것이다.
흐름    ① 시각 → 지금이 어느 구간인가(체결이 있는 구간 / 예상체결가만 나오는 구간 / 거래 없음)
        ② 「요일 + 시각」 만 보는 판정과 「휴장일까지 보는」 판정이 갈리는 날
        ③ 값의 나이 = 조회(화면을 연) 시각 − 체결 시각
        ④ 출처 · 시각을 화면 글 한 줄로
"""
from __future__ import annotations

import datetime as dt

HOLIDAYS = {dt.date(2026, 10, 9)}                      # 예시용 — 한글날


def session_of(now: dt.datetime) -> str:
    """KRX 구간 이름. 체결이 없는 단일가 구간에는 예상체결가만 나온다."""
    if now.weekday() >= 5 or now.date() in HOLIDAYS:
        return "휴장"
    t = now.time()
    if dt.time(8, 30) <= t < dt.time(9, 0):
        return "시가 단일가(예상체결가만)"
    if dt.time(9, 0) <= t < dt.time(15, 20):
        return "정규장 접속매매"
    if dt.time(15, 20) <= t < dt.time(15, 30):
        return "종가 단일가(예상체결가만)"
    if dt.time(15, 40) <= t < dt.time(16, 0):
        return "시간외 종가"
    if dt.time(16, 0) <= t < dt.time(20, 0):
        return "애프터마켓 접속매매"
    return "거래 없음"


def state_time_only(now: dt.datetime) -> str:
    """요일 + 시각(09:00~15:30)만 보는 단순 판정 — 공휴일과 15:30 이후 거래를 놓친다."""
    return "open" if now.weekday() < 5 and dt.time(9, 0) <= now.time() < dt.time(15, 30) else "closed"


def state_with_calendar(now: dt.datetime) -> str:
    return "open" if state_time_only(now) == "open" and now.date() not in HOLIDAYS else "closed"


def age_minutes(traded_at: dt.datetime, viewed_at: dt.datetime) -> int:
    return int((viewed_at - traded_at).total_seconds() // 60)


def quote_label(source: str, traded_at: dt.datetime | None, queried_at: dt.datetime) -> str:
    if source == "kis_user":
        return f"증권사 조회 · {queried_at:%H:%M:%S}"
    if source == "delayed" and traded_at:
        return f"지연 시세(약 20분) · {traded_at:%H:%M} 체결"
    if source == "collector" and traded_at:
        return f"{traded_at.month}월 {traded_at.day}일 종가"
    return "받지 못했습니다"


def main() -> None:
    D = dt.datetime
    print("① 시각 → 구간")
    for s in ["2026-10-08 08:45", "2026-10-08 10:00", "2026-10-08 15:25", "2026-10-08 15:35", "2026-10-08 15:50",
              "2026-10-08 17:00", "2026-10-08 20:00", "2026-10-09 10:00", "2026-10-10 10:00"]:
        print(f"   {s} → {session_of(D.fromisoformat(s))}")
    print("② 요일 + 시각만 / 달력까지")
    for s in ["2026-10-08 10:00", "2026-10-09 10:00", "2026-10-10 10:00", "2026-10-08 15:35", "2026-10-08 17:00"]:
        n = D.fromisoformat(s)
        print(f"   {s} → {state_time_only(n)} / {state_with_calendar(n)}")
    traded, viewed = D(2026, 10, 8, 10, 10), D(2026, 10, 8, 10, 30)
    print("③ 값의 나이:", age_minutes(traded, viewed), "분 (체결 10:10, 조회 10:30)")
    print("④ 화면 글")
    print("  ", quote_label("kis_user", None, D(2026, 10, 8, 10, 30)))
    print("  ", quote_label("delayed", traded, viewed))
    print("  ", quote_label("collector", D(2026, 10, 30), viewed))


if __name__ == "__main__":
    main()
