"""재무 값을 「그날 알 수 있었던 값」으로 고르기(point-in-time) — 결산일과 공시 접수일의 차이, 정정본이 나왔을 때 날짜별로 보이는 값이 달라지는 것을 보이는 예제.

실행    python pit_financials.py        (표준 라이브러리만 · 네트워크 없음)
자료    모두 합성 — 결산 연도 · 접수일 · EPS(주당순이익) 숫자는 손으로 정한 값이다(실제 종목 · 실제 공시가 아니다).
        선택 규칙(기준일보다 먼저 접수된 판 중 가장 늦게 접수된 것을 쓴다)은 Qurious 앱의 `strict` 규칙을 줄여 옮긴 것이다.
흐름    ① 기준일마다 「그날 보이는」 재무 값을 고른다 — 정정본이 나오면 같은 결산기의 값이 바뀐다
        ② 결산일을 공시일로 착각하면 그날 알 수 없던 값을 쓰게 된다(미래 참조)
        ③ 접수 당일은 쓰지 않고 다음 거래일부터 쓴다
"""
from __future__ import annotations

import datetime as dt

D = dt.date.fromisoformat

# (결산일, 접수일, EPS) — 2023 결산은 3월 20일에 냈다가 4월 10일에 정정, 2024 결산은 2025년 3월 19일에 접수(합성)
FILINGS = [
    (D("2023-12-31"), D("2024-03-20"), 1000),
    (D("2023-12-31"), D("2024-04-10"), 800),
    (D("2024-12-31"), D("2025-03-19"), 1200),
]


def visible(as_of: dt.date) -> tuple[dt.date, int] | None:
    """기준일(as_of)보다 먼저 접수된 판만 본다. 결산기마다 가장 늦게 접수된 판을 고르고, 그중 가장 최근 결산기의 값을 돌려준다."""
    seen: dict[dt.date, tuple[dt.date, int]] = {}
    for period, known, eps in sorted(FILINGS, key=lambda x: x[1]):
        if known < as_of:                                      # 접수 당일은 제외(다음 날부터)
            seen[period] = (known, eps)
    if not seen:
        return None
    last = max(seen)
    return last, seen[last][1]


def leaky(as_of: dt.date) -> tuple[dt.date, int] | None:
    """잘못된 규칙 — 결산일을 알려진 날로 착각한다. 그 날 알 수 없던 값을 쓴다."""
    ok = [f for f in FILINGS if f[0] < as_of]
    if not ok:
        return None
    period = max(p for p, _, _ in ok)
    final = sorted((f for f in ok if f[0] == period), key=lambda x: x[1])[-1]   # 나중에 정정된 값까지 가져온다
    return period, final[2]


def next_weekday(d: dt.date) -> dt.date:
    cur = d + dt.timedelta(days=1)
    while cur.weekday() >= 5:                                  # 휴장일 표가 없어 다음 평일로 어림한다
        cur += dt.timedelta(days=1)
    return cur


def main() -> None:
    dates = ["2024-01-02", "2024-03-15", "2024-03-25", "2024-04-15", "2025-03-18", "2025-03-20"]
    print("① 기준일 → 그날 보이는 값 (strict)  |  ② 결산일을 공시일로 착각한 값")
    for s in dates:
        a = visible(D(s))
        b = leaky(D(s))
        fa = "없음" if a is None else f"{a[0]} 결산 EPS {a[1]}"
        fb = "없음" if b is None else f"{b[0]} 결산 EPS {b[1]}"
        print(f"   {s} → {fa:<24} | {fb}")
    print("③ 접수일의 다음 거래일(주말만 건너뜀):", {str(k): str(next_weekday(k)) for k in (D("2024-03-20"), D("2024-03-22"))})


if __name__ == "__main__":
    main()
