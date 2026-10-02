"""일일 갱신 러너(`scripts/daily_update.py`) 시험 — 네트워크·DB 없이 돈다.

지키려는 것은 네 가지다.

1. **이번 달은 다시 훑는다** — `recent_months` 가 연말 경계에서도 이번 달·지난달을 준다.
   이것이 틀리면 1월 1일에 12월 배당 공시가 영원히 빠진다.
2. **파생 표가 뒤처져 있으면 새 자료가 없어도 다시 만든다** — 한 번 어긋난 수정주가가
   다음 거래일까지 뒤처진 채 남지 않게.
3. **잠금은 산 프로세스만 존중한다** — 죽은 PID·오래된 잠금은 치운다.
4. **바뀐 파케이가 0개면 올리지 않는다** — 내용 없는 커밋·태그가 매일 쌓이지 않게.
"""
from __future__ import annotations

import datetime
import json

import pytest

from collector.dividend import recent_months
from scripts import daily_update as du
from scripts import hf_dataset


# ── 1. 최근 달 ──────────────────────────────────────────────────────────────
def test_recent_months_crosses_year_boundary():
    assert recent_months(2, datetime.datetime(2027, 1, 3)) == ["202612", "202701"]
    assert recent_months(1, datetime.datetime(2026, 9, 28)) == ["202609"]
    assert recent_months(3, datetime.datetime(2026, 2, 1)) == ["202512", "202601", "202602"]


def test_recent_months_rejects_zero():
    with pytest.raises(ValueError):
        recent_months(0)


# ── 2. 파생 단계 판정 ───────────────────────────────────────────────────────
BASE = {"price_max": "20260922", "price_recent_rows": 50000,
        "adjusted_max": "20260922", "tr_max": "20260922", "benchmark_max": "20260922",
        "dividend": [9188, "20260916000123", 1.0e7]}


def test_nothing_new_skips_derived():
    assert du.needs_derived(BASE, dict(BASE)) is None


def test_new_trading_day_runs_derived():
    after = dict(BASE, price_max="20260925", price_recent_rows=58000)
    assert "시세가 바뀌었다" in du.needs_derived(BASE, after)


def test_dividend_change_alone_runs_derived():
    """시세는 그대로 · 배당만 새로 온 날 — TR 이 건너뛰어지면 안 된다."""
    after = dict(BASE, dividend=[9190, "20260926000456", 1.01e7])
    assert du.needs_derived(BASE, after) == "배당 표가 바뀌었다"


def test_ex_date_change_alone_runs_derived():
    """거래일 달력이 배당락일만 옮긴 날(2026-10-02 · 3행) — 건수 · 접수번호 · 금액은 그대로라도 TR 을 다시 만든다."""
    before = dict(BASE, dividend=[9191, "20261001900087", 5609056.01, 164968436265.0])
    after = dict(BASE, dividend=[9191, "20261001900087", 5609056.01, 164968436265.0 + 1 + 1 + 83])
    assert du.needs_derived(before, after) == "배당 표가 바뀌었다"


def test_calendar_step_runs_before_derived_decision():
    """달력 단계는 배당 뒤 · 파생(수정주가) 앞 — 배당락일을 고친 뒤에 파생 판정을 해야 한다 · 실패해도 뒤를 막지 않는다."""
    names = [s.name for s in du.STEPS]
    assert names.index("dividend") < names.index("calendar") < names.index("adjusted")
    cal = next(s for s in du.STEPS if s.name == "calendar")
    assert (cal.fatal, cal.derived, cal.upload) == (False, False, False)


def test_lagging_derived_tables_run_even_without_new_data():
    """2026-09-28 실측 상태 — 시세 09-22, 파생 표 09-17."""
    stale = dict(BASE, adjusted_max="20260917", tr_max="20260917", benchmark_max="20260917")
    why = du.needs_derived(stale, dict(stale))
    assert why and "뒤처져" in why and "adjusted 20260917" in why


def test_missing_db_builds_from_scratch():
    assert du.needs_derived({}, {}) is not None


# ── 3. 잠금 ────────────────────────────────────────────────────────────────
def test_lock_blocks_while_holder_alive(tmp_path):
    lock = tmp_path / "x.lock"
    now = du.now_kst()
    assert du.acquire_lock(lock, now=now) is None           # 이 프로세스가 잡는다
    assert "다른 실행" in du.acquire_lock(lock, now=now)      # 산 PID → 막힌다
    du.release_lock(lock)
    assert not lock.exists()


def test_lock_from_dead_pid_is_cleared(tmp_path):
    lock = tmp_path / "x.lock"
    lock.write_text(json.dumps({"pid": 0, "started_at": du._iso(du.now_kst())}))
    assert du.acquire_lock(lock) is None
    assert json.loads(lock.read_text())["pid"] > 0


def test_old_lock_is_cleared_even_if_pid_alive(tmp_path):
    lock = tmp_path / "x.lock"
    old = du.now_kst() - datetime.timedelta(hours=du.LOCK_STALE_HOURS + 1)
    import os
    lock.write_text(json.dumps({"pid": os.getpid(), "started_at": du._iso(old)}))
    assert du.acquire_lock(lock) is None


def test_release_does_not_remove_someone_elses_lock(tmp_path):
    lock = tmp_path / "x.lock"
    lock.write_text(json.dumps({"pid": 999999, "started_at": "x"}))
    du.release_lock(lock)
    assert lock.exists()


def test_pid_alive_does_not_kill_self():
    """Windows 의 `os.kill(pid, 0)` 은 프로세스를 죽인다 — 여기까지 오면 안 죽은 것이다."""
    import os
    assert du.pid_alive(os.getpid()) is True
    assert du.pid_alive(0) is False


# ── 4. 작업 스케줄러 정의 ──────────────────────────────────────────────────
def test_task_xml_has_catch_up_and_no_password(tmp_path):
    xml = du.task_xml("12:30", True, python_w=r"C:\py\pythonw.exe", root=tmp_path,
                      today=datetime.date(2026, 9, 28))
    assert "<StartWhenAvailable>true</StartWhenAvailable>" in xml
    assert "<LogonType>InteractiveToken</LogonType>" in xml
    assert "<StartBoundary>2026-09-28T12:30:00</StartBoundary>" in xml
    assert "run --upload</Arguments>" in xml
    assert "&quot;" in xml                                   # 경로 따옴표가 이스케이프됐다


def test_task_xml_without_upload(tmp_path):
    xml = du.task_xml("18:05", False, python_w="pythonw", root=tmp_path)
    assert "run</Arguments>" in xml and "--upload" not in xml


# ── 5. 올릴 것이 있는가 ────────────────────────────────────────────────────
def _man(files, uploaded):
    m = {"tables": {"t": {"files": [{"path": p, "sha256": s} for p, s in files.items()]}}}
    if uploaded is not None:
        m["uploaded"] = {"files": uploaded}
    return m


def test_changed_since_upload():
    files = {"a/year=2026/x.parquet": "new", "a/year=2025/x.parquet": "same"}
    up = {"a/year=2026/x.parquet": "old", "a/year=2025/x.parquet": "same"}
    assert hf_dataset.changed_since_upload(_man(files, up)) == ["a/year=2026/x.parquet"]
    assert hf_dataset.changed_since_upload(_man(files, files)) == []
    assert hf_dataset.changed_since_upload(_man(files, None)) is None
