"""DF-16 시험 — ``python -m collector.preprocess`` 가 인자를 본다.

무엇이 틀렸었나 — 2026-09-29 S60, 도움말을 보려고 ``python -m collector.preprocess --help`` 를 줬더니
``main()`` 이 인자를 읽지 않고 곧바로 ``db.connect()`` → 전 종목 수정주가 재계산(쓰기 트랜잭션)을 시작했다.
마침 예약 작업이 같은 일을 하고 있어 잠금을 기다리다 멈췄고, 한 트랜잭션(``BEGIN IMMEDIATE``)이라
중단해도 DB 는 되돌려졌다. 해는 없었지만 **도움말이 쓰기를 시작하면 안 된다.**

여기서 지키는 것 —
1. ``--help`` 는 도움말만 찍고 DB 를 열지 않는다 ← 옛 코드 실패
2. 모르는 인자는 DB 를 열기 전에 멈춘다(종료코드 2) ← 옛 코드 실패
3. 인자 없이 부르면 **예전처럼** 전 종목을 다시 계산한다 — 일일 러너의 ``adjusted`` 단계가 이렇게 부른다
   (``scripts/daily_update.py`` 의 ``STEPS``). 옛 코드에서도 통과해야 맞다 — 고치면서 러너를 깨지 않았다는 증거다.

DB 는 ``collector.db.connect`` 를 바꿔 끼워 막거나 메모리 DB 로 돌린다. 실제 수집 DB 는 열지 않는다 —
옛 코드로 이 파일을 돌려도 마찬가지다(그래서 명령줄 대신 ``main()`` 을 직접 부른다).
"""
from __future__ import annotations

import sqlite3
import sys

import pytest

from collector import db, preprocess
from collector.db import SCHEMA


@pytest.fixture
def no_db(monkeypatch):
    """DB 를 열면 시험이 실패한다. 옛 코드가 실제 수집 DB 를 여는 일도 이것이 막는다."""
    opened = []

    def refuse(*a, **k):
        opened.append(a)
        raise AssertionError("인자를 보기 전에 DB 를 열었다 — 전 종목 재계산이 시작된다")

    monkeypatch.setattr(db, "connect", refuse)
    return opened


class _KeepOpen(sqlite3.Connection):
    """``main()`` 이 끝에 ``close()`` 를 불러도 표를 읽을 수 있게 닫지 않는 연결."""

    def close(self):
        pass


def test_help_prints_usage_without_opening_the_db(no_db, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["collector.preprocess", "--help"])
    with pytest.raises(SystemExit) as e:
        preprocess.main()
    assert e.value.code == 0
    out = " ".join(capsys.readouterr().out.split())     # argparse 가 창 폭에 맞춰 줄을 바꾼다
    assert "usage: python -m collector.preprocess" in out
    assert "다시 계산한다" in out and "daily_update.py status" in out   # 무엇을 하는지 · 돌리기 전에 볼 것
    assert no_db == []


def test_unknown_argument_stops_before_the_db(no_db, monkeypatch, capsys):
    """다른 모듈처럼 ``--codes`` 가 있으리라 짐작하고 준 인자 — 전 종목을 돌리지 말고 멈춘다."""
    monkeypatch.setattr(sys, "argv", ["collector.preprocess", "--codes", "005930"])
    with pytest.raises(SystemExit) as e:
        preprocess.main()
    assert e.value.code == 2
    assert "unrecognized arguments: --codes 005930" in capsys.readouterr().err
    assert no_db == []


def test_no_arguments_still_rebuilds_like_the_daily_runner(monkeypatch, capsys):
    conn = sqlite3.connect(":memory:", factory=_KeepOpen)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.executemany(
        "INSERT INTO price_daily (bas_dt, srtn_cd, itms_nm, clpr, vs, mkp, hipr, lopr, halted, lstg_st_cnt) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        [("20240102", "005930", "테스트", 1000, 0, 1000, 1000, 1000, 0, 100),
         ("20240103", "005930", "테스트", 1010, 10, 1010, 1010, 1010, 0, 100)])
    conn.commit()
    monkeypatch.setattr(db, "connect", lambda *a, **k: conn)
    monkeypatch.setattr(sys, "argv", ["collector.preprocess"])

    assert preprocess.main() == 0
    out = capsys.readouterr().out
    assert "수정주가 다시 계산 중" in out and "종목 1 · 행 2 · 조정 이벤트 0" in out
    assert conn.execute("SELECT COUNT(*) FROM price_adjusted").fetchone()[0] == 2
