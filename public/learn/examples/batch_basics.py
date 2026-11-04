"""정기 배치의 뼈대 — 겹침 막기(잠금) · 다시 돌려도 같은 결과(멱등) · 놓친 날 따라잡기 · 죽은 쥔 이어받기를 보이는 예제.

실행    python batch_basics.py        (표준 라이브러리만 · 네트워크 없음 · 임시 폴더만 쓴다)
자료    모두 합성 — 날짜 · 종목 · 가격은 손으로 정한 값이고, 실제 러너의 상태 표 · 임대 파일이 아니라 구조를 줄여 옮긴 것이다
흐름    ① 잠금 파일을 O_EXCL 로 만들면 둘 중 하나만 성공한다
        ② 같은 날을 두 번 적재해도 행이 늘지 않는다(기본키 + upsert + 한 트랜잭션)
        ③ 최근 N일의 「빈 날」을 계산해 채운다 — 놓친 날은 배치 스스로 메운다
        ④ 회차의 「자리(slot)」 날짜 — 12:28 부터 그날, 그 앞은 전날
        ⑤ 쥔의 소식이 90분 넘게 없으면 이어받는다
주의    Windows 에서는 os.kill(pid, 0) 으로 생존 확인을 하지 않는다(임의 sig 가 프로세스를 종료시킨다) — 이 예제는 쓰지 않는다
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import tempfile
from pathlib import Path


# ── ① 잠금 ─────────────────────────────────────────────────────────────────────────────
def acquire(lock: Path) -> bool:
    """이미 있으면 실패(EEXIST) — 둘이 동시에 만들어도 한쪽만 성공한다."""
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w") as f:
        json.dump({"pid": os.getpid()}, f)
    return True


# ── ② 멱등 적재 ────────────────────────────────────────────────────────────────────────
def open_db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE price(dt TEXT, code TEXT, close INT, PRIMARY KEY(dt, code))")
    con.execute("CREATE TABLE ingest(dt TEXT PRIMARY KEY, status TEXT)")
    return con


def run_day(con: sqlite3.Connection, day: str, rows: list[tuple]) -> str:
    if con.execute("SELECT 1 FROM ingest WHERE dt=? AND status='done'", (day,)).fetchone():
        return "건너뜀(이미 done)"
    with con:                                           # 적재와 상태를 한 트랜잭션으로 — 「상태만 done」이 안 생기게
        con.executemany("INSERT OR REPLACE INTO price VALUES (?,?,?)", rows)
        con.execute("INSERT OR REPLACE INTO ingest VALUES (?, 'done')", (day,))
    return f"적재 {len(rows)}행"


# ── ③ 따라잡기: 최근 N일의 빈 날 ─────────────────────────────────────────────────────────
def missing_days(today: dt.date, done: set[str], holidays: set[str], window: int = 14) -> list[str]:
    """오늘을 찍는 대신 최근 window 일을 되돌아보며 done · 휴장이 아닌 날만 고른다(주말은 제외)."""
    out = []
    for back in range(1, window + 1):
        d = today - dt.timedelta(days=back)
        key = d.isoformat()
        if d.weekday() >= 5 or key in holidays or key in done:
            continue
        out.append(key)
    return sorted(out)


# ── ④ 자리(slot) ────────────────────────────────────────────────────────────────────────
SLOT_FROM = dt.time(12, 28)


def slot_of(now: dt.datetime) -> str:
    return (now.date() if now.time() >= SLOT_FROM else now.date() - dt.timedelta(days=1)).isoformat()


# ── ⑤ 죽은 쥔 이어받기 ──────────────────────────────────────────────────────────────────
def can_take(renewed_at: dt.datetime, now: dt.datetime, expire_min: int = 90) -> bool:
    return now - renewed_at > dt.timedelta(minutes=expire_min)


def main() -> None:
    with tempfile.TemporaryDirectory() as t:
        lock = Path(t) / "job.lock"
        print("① 첫 번째:", acquire(lock), "| 두 번째:", acquire(lock))

    con = open_db()
    rows = [("2026-11-02", "111111", 100), ("2026-11-02", "222222", 200)]
    print("② ", run_day(con, "2026-11-02", rows), "|", run_day(con, "2026-11-02", rows),
          "| 행 수", con.execute("SELECT COUNT(*) FROM price").fetchone()[0])

    today = dt.date(2026, 11, 4)                                    # 수요일. 11-02 만 받아 둔 상태(합성)
    done = {"2026-11-02"}
    print("③ 빈 날(최근 7일 창):", missing_days(today, done, holidays=set(), window=7))

    done_slots = {"2026-11-02"}
    for s in ("2026-11-03 09:00", "2026-11-03 12:30", "2026-11-03 18:54", "2026-11-04 08:00"):
        now = dt.datetime.fromisoformat(s)
        slot = slot_of(now)
        print(f"④ {s} -> 자리 {slot} ->", "건너뜀(끝남)" if slot in done_slots else "돈다")

    base = dt.datetime(2026, 11, 3, 12, 30)
    print("⑤ 60분 무소식:", can_take(base, base + dt.timedelta(minutes=60)),
          "| 91분 무소식:", can_take(base, base + dt.timedelta(minutes=91)))


if __name__ == "__main__":
    main()
