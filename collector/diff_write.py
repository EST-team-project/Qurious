"""바뀐 행만 쓰기 — 한 범위(종목 하나 등)를 새로 계산한 행과 같게 만들되, 같은 행은 건드리지 않는다 (할 일 P4 · 2026-10-31).

왜 — 파생 표(수정주가 · 총수익)는 종목마다 「지우고 전부 다시 넣기」 로 다시 만들었다. 10-31 회차의 수정주가 단계는 423초 가운데
**쓰기가 311초(74%)** 였고 계산은 7.6초였다. 하루에 늘어나는 것은 종목마다 한 행인데 450만 행을 매일 다시 쓴 것이다.
계산 결과가 같은 행은 그대로 두고 **다른 행만** 넣으면 표의 내용은 전부 다시 쓴 것과 같고(시험이 맞댄다) 쓰는 양은 수천 행으로 준다.

약속
  · 끝난 뒤 범위 안의 행 집합은 ``new_rows`` 와 정확히 같다(전부 다시 쓴 것과 같은 내용). 행의 물리적 순서(rowid)만 다를 수 있는데,
    내보내기는 키 순서로 정렬해 내보내고 읽는 쪽은 ``ORDER BY`` 를 쓰므로 결과가 같다.
  · 값 비교는 **정확히 같을 때만** 같은 행이다(실수도 그대로 ``==``). 같은 코드가 같은 입력으로 만든 값은 비트까지 같으니 안 바뀐 행은
    건드리지 않고, 계산 규칙이 바뀌면 그 행들이 모두 다르다고 나와 알아서 고쳐진다.
  · 트랜잭션은 부르는 쪽이 연다(이 함수는 ``BEGIN`` · ``COMMIT`` 을 하지 않는다).
"""
from __future__ import annotations

import sqlite3
from typing import Dict, Iterable, Sequence, Tuple


def sync_rows(conn: sqlite3.Connection, table: str, cols: Sequence[str], key_n: int, where: str, args: Tuple,
              new_rows: Iterable[Sequence]) -> Dict[str, int]:
    """``where`` 범위의 ``table`` 행을 ``new_rows`` 와 같게 만든다 — 같은 행은 그대로 · 새 행은 넣고 · 달라진 행은 고치고 · 없어진 행은 지운다.

    ``cols`` 는 ``new_rows`` 의 칸 차례이고 앞의 ``key_n`` 칸이 행 열쇠다(표의 기본키). 돌려주는 값은 ``{"new", "changed", "gone", "same"}``.
    """
    cols = list(cols)
    names = ", ".join(cols)
    old: Dict[Tuple, Tuple] = {}
    for r in conn.execute(f"SELECT {names} FROM {table} WHERE {where}", args):
        t = tuple(r)
        old[t[:key_n]] = t
    new: Dict[Tuple, Tuple] = {}
    n_in = 0
    for r in new_rows:
        t = tuple(r)
        n_in += 1
        new[t[:key_n]] = t
    if len(new) != n_in:
        raise ValueError(f"{table}: 새 행에 열쇠가 겹친 줄이 있다({n_in - len(new)}개)")

    gone = [k for k in old if k not in new]
    add = [t for k, t in new.items() if k not in old]
    chg = [t for k, t in new.items() if k in old and old[k] != t]

    key_cols, val_cols = cols[:key_n], cols[key_n:]
    where_key = " AND ".join(f"{c}=?" for c in key_cols)
    if gone:
        conn.executemany(f"DELETE FROM {table} WHERE {where_key}", gone)
    if chg and val_cols:
        conn.executemany(f"UPDATE {table} SET {', '.join(f'{c}=?' for c in val_cols)} WHERE {where_key}",
                         [t[key_n:] + t[:key_n] for t in chg])
    if add:
        conn.executemany(f"INSERT INTO {table} ({names}) VALUES ({', '.join('?' * len(cols))})", add)
    return {"new": len(add), "changed": len(chg), "gone": len(gone), "same": len(new) - len(add) - len(chg)}


def add_stats(total: Dict[str, int], part: Dict[str, int]) -> None:
    """종목마다 나온 숫자를 합친다."""
    for k, v in part.items():
        total[k] = total.get(k, 0) + v


def stats_line(label: str, s: Dict[str, int]) -> str:
    """로그 한 줄 — 「  수정주가 바뀐 행: 새 2,872 · 고침 0 · 지움 0 · 같아서 안 건드림 4,532,453」."""
    return (f"  {label} 바뀐 행: 새 {s.get('new', 0):,} · 고침 {s.get('changed', 0):,} · 지움 {s.get('gone', 0):,} · "
            f"같아서 안 건드림 {s.get('same', 0):,}")
