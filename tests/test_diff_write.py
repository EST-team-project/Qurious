"""TC-DW — 바뀐 행만 쓰기 (collector/diff_write.py · 수정주가 · 총수익 · 할 일 P4 · 2026-10-31 · 강사님 피드백 「속도」)

왜 — 10-31 회차의 수정주가 단계는 423초 가운데 쓰기가 311초(74%)였고 계산은 7.6초였다. 하루에 늘어나는 것은 종목마다 한 행인데
450만 행을 매일 지우고 다시 넣었다. 계산 결과가 같은 행은 건드리지 않고 다른 행만 쓰면 표의 내용은 전부 다시 쓴 것과 같아야 한다 —
**그 「같다」 를 여기서 여러 상황으로 맞댄다.**

지키는 것
1. `sync_rows` 의 뜻 — 같은 행은 그대로 · 새 행은 넣고 · 달라진 행은 고치고 · 없어진 행은 지운다 · 범위 밖은 건드리지 않는다. (TC-DW-01 ~ 03)
2. `rebuild(diff=True)` 와 `rebuild(diff=False)`(예전 방식)가 **같은 표 내용**을 만든다 — 첫 계산 · 하루 늘어남 · 분할로 옛 행이 모두 바뀜 ·
   옛 시세 정정 · 시세 행 사라짐. (TC-DW-04)
3. 같은 입력으로 다시 돌리면 쓰는 행이 0 이다(멱등) — 쓰기를 줄였다는 증거. (TC-DW-05)
4. `total_return.build` 도 같다 — 배당 추가로 그 날 뒤 행이 모두 바뀌는 경우 포함. (TC-DW-06)
5. 로그 줄과 `--full` · `delisted_count` · 모르는 인자는 여전히 막힘. (TC-DW-07 ~ 08)
"""
from __future__ import annotations

import sqlite3
import sys

import pytest

from collector import db, preprocess, total_return
from collector.db import SCHEMA
from collector.diff_write import add_stats, stats_line, sync_rows

DAYS = ["20230102", "20230103", "20230104", "20230105", "20230106", "20230109", "20230110", "20230111", "20230112", "20230113"]


def _mem() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _price(conn, code, rows):
    """rows = (일자, 종가, 전일대비, 주식수)."""
    conn.executemany(
        "INSERT INTO price_daily (bas_dt, srtn_cd, itms_nm, clpr, vs, mkp, hipr, lopr, halted, lstg_st_cnt) "
        "VALUES (?,?,?,?,?,?,?,?,0,?)", [(d, code, "시험", c, v, c, c, c, n) for d, c, v, n in rows])


def _base() -> sqlite3.Connection:
    """종목 셋 — A(평범) · B(중간에 반토막 분할) · C(짧은 종목)."""
    conn = _mem()
    _price(conn, "000001", [(d, 1000 + 10 * i, 10 if i else 0, 1000) for i, d in enumerate(DAYS)])
    b = []
    for i, d in enumerate(DAYS):
        if i < 5:
            b.append((d, 2000 + 5 * i, 5 if i else 0, 100))
        elif i == 5:
            b.append((d, 1010, 0, 200))                         # 분할: 종가 반토막 · vs 0 · 주식수 2배 → 계수 0.5
        else:
            b.append((d, 1010 + 5 * (i - 5), 5, 200))
    _price(conn, "000002", b)
    _price(conn, "000003", [(d, 300 + i, 1 if i else 0, 50) for i, d in enumerate(DAYS[:4])])
    return conn


def _copy(src: sqlite3.Connection, factory=sqlite3.Connection) -> sqlite3.Connection:
    """같은 내용의 복사본 — 쓰던 트랜잭션이 열려 있으면 backup 이 끝나지 않으므로 먼저 확정한다."""
    if src.in_transaction:
        src.commit()
    dst = sqlite3.connect(":memory:", isolation_level=None, factory=factory)
    dst.row_factory = sqlite3.Row
    src.backup(dst)
    return dst


def _snap(conn, *tables):
    return {t: [tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2")] for t in tables}


# ── 1. sync_rows ────────────────────────────────────────────────────────────
def _t(conn):
    conn.execute("CREATE TABLE t (g TEXT, k INTEGER, a REAL, b TEXT, PRIMARY KEY (g, k))")
    conn.executemany("INSERT INTO t VALUES (?,?,?,?)", [("x", 1, 1.5, "a"), ("x", 2, 2.5, "b"), ("x", 3, 3.5, None), ("y", 1, 9.0, "z")])


def test_sync_rows_inserts_updates_deletes_and_leaves_same_rows_alone():
    """TC-DW-01 · 새 행은 넣고 · 달라진 행은 고치고 · 없어진 행은 지우고 · 같은 행은 그대로 — 범위(g='x') 밖은 건드리지 않는다."""
    conn = _mem()
    _t(conn)
    before_rowid = {r["k"]: r["rowid"] for r in conn.execute("SELECT rowid, k FROM t WHERE g='x'")}
    new = [("x", 1, 1.5, "a"),                  # 같음
           ("x", 2, 2.5, "CHANGED"),            # 고침
           ("x", 4, 4.5, "n")]                  # 새로 (x,3 은 빠졌다 → 지움)
    s = sync_rows(conn, "t", ("g", "k", "a", "b"), 2, "g=?", ("x",), new)
    assert s == {"new": 1, "changed": 1, "gone": 1, "same": 1}
    assert [tuple(r) for r in conn.execute("SELECT * FROM t ORDER BY g, k")] == [
        ("x", 1, 1.5, "a"), ("x", 2, 2.5, "CHANGED"), ("x", 4, 4.5, "n"), ("y", 1, 9.0, "z")]
    after = {r["k"]: r["rowid"] for r in conn.execute("SELECT rowid, k FROM t WHERE g='x'")}
    assert after[1] == before_rowid[1] and after[2] == before_rowid[2], "같은 행 · 고친 행은 그 자리에서 — 지우고 다시 넣지 않았다"


def test_sync_rows_second_run_is_all_same_and_rejects_duplicate_keys():
    """TC-DW-02 · 같은 입력으로 다시 부르면 모두 같음 · 열쇠가 겹친 새 행은 거부(기본키 위반과 같은 뜻)."""
    conn = _mem()
    _t(conn)
    rows = [("x", 1, 1.5, "a"), ("x", 2, 2.5, "b"), ("x", 3, 3.5, None)]
    assert sync_rows(conn, "t", ("g", "k", "a", "b"), 2, "g=?", ("x",), rows) == {"new": 0, "changed": 0, "gone": 0, "same": 3}
    with pytest.raises(ValueError, match="겹친"):
        sync_rows(conn, "t", ("g", "k", "a", "b"), 2, "g=?", ("x",), rows + [("x", 1, 0.0, "dup")])
    assert sync_rows(conn, "t", ("g", "k", "a", "b"), 2, "g=?", ("none",), []) == {"new": 0, "changed": 0, "gone": 0, "same": 0}


def test_stats_helpers():
    """TC-DW-03 · 종목마다 나온 숫자를 합치고 로그 한 줄로 보인다."""
    tot: dict = {}
    add_stats(tot, {"new": 2, "changed": 1, "gone": 0, "same": 10})
    add_stats(tot, {"new": 3, "changed": 0, "gone": 1, "same": 5})
    assert tot == {"new": 5, "changed": 1, "gone": 1, "same": 15}
    line = stats_line("수정주가", tot)
    assert "새 5" in line and "고침 1" in line and "지움 1" in line and "같아서 안 건드림 15" in line
    assert "단계 안 시간" not in line, "시간 줄(로그 표 도구가 읽음)과 섞이지 않는다"


# ── 2. 수정주가 — 바뀐 행만 쓴 결과 = 전부 다시 쓴 결과 ───────────────────────
def _both(base: sqlite3.Connection, mutate):
    """같은 시작 상태 둘에 같은 변경을 하고 각자 다른 방식으로 다시 계산한다. (diff 연결, full 연결, diff 통계)"""
    a, b = _copy(base), _copy(base)
    for c in (a, b):
        mutate(c)
    st: dict = {}
    ta = preprocess.rebuild(a, diff=True, stats=st)
    tb = preprocess.rebuild(b, diff=False)
    assert ta == tb, "집계(종목 · 행 · 이벤트)도 같다"
    return a, b, st


def test_diff_rebuild_gives_the_same_tables_as_full_rewrite_in_every_situation():
    """TC-DW-04 · 첫 계산 · 하루 늘어남 · 분할로 옛 행이 모두 바뀜 · 옛 시세 정정 · 시세 행 사라짐 — 표 내용이 전부 다시 쓴 것과 같다."""
    base = _base()
    preprocess.rebuild(base, diff=False)                                       # 어제까지 만들어 둔 상태
    tables = ("price_adjusted", "corporate_action")

    # (가) 첫 계산 — 빈 표에서
    a0, b0, st0 = _both(_base(), lambda c: None)
    assert _snap(a0, *tables) == _snap(b0, *tables) and st0["price_adjusted"]["new"] == 10 + 10 + 4

    # (나) 하루 늘어남 — 새 행만 들어가고 옛 행은 그대로(변경 0)
    def add_day(c):
        _price(c, "000001", [("20230116", 1100, 10, 1000)])
        _price(c, "000002", [("20230116", 1060, 30, 200)])                     # 직전 종가 1030 → 1060 (전일대비 +30 — 이어지는 가격)

    a, b, st = _both(base, add_day)
    assert _snap(a, *tables) == _snap(b, *tables)
    assert st["price_adjusted"] == {"new": 2, "changed": 0, "gone": 0, "same": 24}, "하루 늘었을 뿐이면 새 행 둘 · 나머지는 건드리지 않는다"

    # (다) 새 날에 분할 — 그 종목의 옛 행이 모두 바뀌고(누적 계수) 이벤트가 생긴다 · 다른 종목은 그대로
    def split_today(c):
        _price(c, "000001", [("20230116", 560, 0, 2000)])                      # 종가 반토막 · 주식수 2배

    a, b, st = _both(base, split_today)
    assert _snap(a, *tables) == _snap(b, *tables)
    assert st["price_adjusted"]["changed"] >= 9 and st["price_adjusted"]["new"] == 1
    assert st["corporate_action"]["new"] == 1
    assert [tuple(r)[:2] for r in a.execute("SELECT bas_dt, srtn_cd FROM corporate_action WHERE srtn_cd='000001'")] == [("20230116", "000001")]

    # (라) 옛 시세 정정 — 한 날의 종가가 고쳐져 그 날(과 이어진 계수)이 바뀐다
    a, b, st = _both(base, lambda c: c.execute("UPDATE price_daily SET clpr=1234, vs=234 WHERE srtn_cd='000001' AND bas_dt='20230104'"))
    assert _snap(a, *tables) == _snap(b, *tables) and st["price_adjusted"]["changed"] >= 1

    # (마) 시세 행이 사라짐(그 날 수정주가 행도 사라져야 한다) · 종목 전체가 사라지면 그 종목은 건드리지 않는다(옛 방식과 같다)
    a, b, st = _both(base, lambda c: c.execute("DELETE FROM price_daily WHERE srtn_cd='000003' AND bas_dt='20230105'"))
    assert _snap(a, *tables) == _snap(b, *tables) and st["price_adjusted"]["gone"] == 1


def test_second_run_writes_nothing():
    """TC-DW-05 · 같은 입력으로 다시 돌리면 쓰는 행이 0 — 쓰기를 줄였다는 증거(멱등)."""
    conn = _base()
    st1: dict = {}
    preprocess.rebuild(conn, stats=st1)
    assert st1["price_adjusted"]["new"] == 24
    st2: dict = {}
    preprocess.rebuild(conn, stats=st2)
    for t in ("price_adjusted", "corporate_action"):
        assert st2[t]["new"] == st2[t]["changed"] == st2[t]["gone"] == 0
    assert st2["price_adjusted"]["same"] == 24 and st2["corporate_action"]["same"] == 1
    assert preprocess.rebuild(_copy(conn), diff=False) == preprocess.rebuild(conn)


# ── 3. 총수익 ───────────────────────────────────────────────────────────────
def test_total_return_diff_equals_full_rewrite_including_a_new_dividend():
    """TC-DW-06 · 총수익도 같다 — 하루 늘어남 · 배당 하나 추가(그 날 뒤 행이 모두 바뀜)."""
    base = _base()
    preprocess.rebuild(base)
    total_return.build(base, diff=False)
    tables = ("price_total_return",)

    def run(mutate):
        a, b = _copy(base), _copy(base)
        for c in (a, b):
            mutate(c)
            preprocess.rebuild(c)                                              # 수정주가는 같은 방식으로 맞춘다
        st: dict = {}
        ta = total_return.build(a, diff=True, stats=st)
        tb = total_return.build(b, diff=False)
        assert ta == tb and _snap(a, *tables) == _snap(b, *tables)
        return st

    def add_day(c):
        _price(c, "000001", [("20230116", 1100, 10, 1000)])

    st = run(add_day)
    assert st == {"new": 1, "changed": 0, "gone": 0, "same": 10 + 10 + 4}, st

    def add_dividend(c):
        c.execute("INSERT INTO dividend (srtn_cd, record_dt, rcept_no, ex_div_dt, dps, yield_pct) VALUES "
                  "('000001', '20230105', 'R1', '20230106', 20.0, 2.0)")

    st = run(add_dividend)
    assert st["changed"] >= 4 and st["new"] == 0, "배당락일 뒤의 총수익 지수는 모두 바뀐다"


# ── 4. 로그 · --full · 개수 ─────────────────────────────────────────────────
class _KeepOpen(sqlite3.Connection):
    def close(self):
        pass


def _main(monkeypatch, conn, *argv):
    monkeypatch.setattr(db, "connect", lambda *a, **k: conn)
    monkeypatch.setattr(sys, "argv", ["collector.preprocess", *argv])
    return preprocess.main()


def test_main_prints_stats_lines_and_full_flag_rewrites(monkeypatch, capsys):
    """TC-DW-07 · 인자 없이 부르면 바뀐 행 줄이 붙고(시간 줄은 그대로 하나) `--full` 이면 예전 방식 — 표 내용은 같다."""
    c1 = sqlite3.connect(":memory:", factory=_KeepOpen, isolation_level=None)       # main() 이 끝에 close() 를 불러도 닫히지 않는 연결
    c1.row_factory = sqlite3.Row
    c1.executescript(SCHEMA)
    _price(c1, "000001", [(d, 1000 + i, 1 if i else 0, 100) for i, d in enumerate(DAYS[:5])])
    c2 = _copy(c1, factory=_KeepOpen)
    assert _main(monkeypatch, c1) == 0
    out = capsys.readouterr().out
    assert "수정주가 바뀐 행: 새 5 · 고침 0 · 지움 0 · 같아서 안 건드림 0" in out and "조정 이벤트 바뀐 행:" in out
    assert len([ln for ln in out.splitlines() if "⏱ 단계 안 시간" in ln]) == 1
    assert "종목 1 · 행 5 · 조정 이벤트 0" in out
    assert _main(monkeypatch, c2, "--full") == 0
    out2 = capsys.readouterr().out
    assert "--full" in out2 and "바뀐 행:" not in out2 and "종목 1 · 행 5 · 조정 이벤트 0" in out2
    assert _snap(c1, "price_adjusted") == _snap(c2, "price_adjusted")


def test_delisted_count_equals_the_list_length():
    """TC-DW-08 · 개수만 세는 빠른 길이 목록 길이와 같다 — 최근 기준일에 없는 종목 수."""
    conn = _base()
    assert preprocess.delisted_count(conn) == len(preprocess.delisted(conn)) == 1     # 000003 은 일찍 끝났다
    assert preprocess.delisted_count(conn, as_of="20230103") == len(preprocess.delisted(conn, as_of="20230103")) == 0
    assert preprocess.delisted_count(_mem()) == 0
