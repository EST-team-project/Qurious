"""수정주가 단계의 단계 안 시간 (TC-AJT · `P01-①-4` · DF-104).

왜 — 매일 낮 수집의 수정주가 단계(`python -m collector.preprocess`)가 평소 570 ~ 790초인데 회차를 건너뛴 뒤
1,787초(10-11)까지 길어져 한도(30분)에 13초 앞이었다. 한도는 45분으로 올렸지만 까닭(읽기 · 계산 · 쓰기 · 커밋 ·
쓰기 앞 기록 파일 WAL 크기)은 재지 않았다 — 고치기 전에 단계 안 시간을 나눠 로그에 남긴다.

여기서 지키는 것 —
1. `rebuild(..., timings=)` 가 여섯 부분(종목 목록 · 쓰기 잠금 · 읽기 · 계산 · 쓰기 · 커밋)의 초를 채운다 · 결과(줄 · 이벤트)는 그대로.
2. `timings` 를 주지 않으면 예전과 같다(러너 밖에서 부르는 곳).
3. `main()` 이 요약 뒤에 한 줄(「⏱ 단계 안 시간 — …」 · 끝에 CPU 시간 — 걸린 시간과 견주면 기다린 시간이 보인다)을 찍고,
   로그 표 도구가 그 줄을 읽을 수 있다.
4. WAL 크기는 연결이 가리키는 파일에서 읽는다 — 메모리 DB 는 「없음」(진짜 수집 DB 를 보지 않는다).
"""
from __future__ import annotations

import re
import sqlite3
import sys

from collector import preprocess
from collector.db import SCHEMA

ROWS = {
    "000001": [("20230101", 1000, 0), ("20230102", 1010, 10), ("20230103", 1005, -5)],
    "000002": [("20230101", 500, 0), ("20230102", 505, 5)],
}
PARTS = ("list", "begin", "read", "compute", "write", "commit")


def _memdb() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    for code, rows in ROWS.items():
        conn.executemany(
            "INSERT INTO price_daily (bas_dt, srtn_cd, itms_nm, clpr, vs, mkp, hipr, lopr, halted, lstg_st_cnt) "
            "VALUES (?,?,?,?,?,?,?,?,0,1000000)",
            [(d, code, "시험", c, v, c, c, c) for d, c, v in rows])
    return conn


def test_rebuild_fills_six_parts_and_keeps_the_result():
    plain = preprocess.rebuild(_memdb())
    t: dict = {}
    timed = preprocess.rebuild(_memdb(), timings=t)
    assert timed == plain                                   # 재는 것이 결과를 바꾸지 않는다
    assert set(t) == set(PARTS)
    assert all(isinstance(v, float) and v >= 0 for v in t.values())


def test_rebuild_without_timings_is_unchanged():
    t = preprocess.rebuild(_memdb())
    assert t["codes"] == 2 and t["rows"] == 5 and t["events"] == 0


def test_main_prints_one_parsable_line(monkeypatch, capsys):
    conn = _memdb()
    monkeypatch.setattr(preprocess.db, "connect", lambda *a, **k: conn)
    monkeypatch.setattr(sys, "argv", ["collector.preprocess"])
    assert preprocess.main() == 0
    lines = [l for l in capsys.readouterr().out.splitlines() if "⏱ 단계 안 시간" in l]
    assert len(lines) == 1, lines
    parsed = preprocess.parse_timing_line(lines[0])
    assert set(parsed) == {"종목 목록", "잠금", "읽기", "계산", "쓰기", "커밋", "폐지 목록", "CPU 시간"}
    assert all(v >= 0 for k, v in parsed.items() if k != "WAL")
    assert "WAL 없음" in lines[0]                            # 메모리 DB — 파일이 없다


def test_wal_bytes_reads_the_connected_file_only(tmp_path):
    mem = sqlite3.connect(":memory:")
    assert preprocess.wal_bytes(mem) is None
    path = tmp_path / "t.sqlite3"
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE x (a)")
    conn.execute("INSERT INTO x VALUES (1)")
    size = preprocess.wal_bytes(conn)
    assert isinstance(size, int) and size > 0
    conn.close()


def test_timing_line_round_trips():
    line = preprocess.timing_line({"list": 0.4, "read": 120.25, "compute": 80.0, "write": 300.5,
                                   "commit": 20.0, "delisted": 3.0}, 12 * 2**20, 1850 * 2**20)
    assert re.match(r"^\s*⏱ 단계 안 시간 — ", line)
    p = preprocess.parse_timing_line(line)
    assert p["읽기"] == 120.2 or p["읽기"] == 120.3          # 소수 한 자리
    assert p["쓰기"] == 300.5 and p["커밋"] == 20.0
    assert "WAL 12 MB → 1,850 MB" in line
