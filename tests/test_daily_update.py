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
import sqlite3

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


def test_schedule_and_sector_law_steps():
    """주총 · 배당 지급 일정은 재무 뒤 · 달력 앞(달력이 그 표로 일정을 만든다) · 섹터 법령 매주 대조는 맨 끝의 올리기 단계 —
    둘 다 실패해도 뒤를 막지 않고, 섹터 법령은 --upload 실행에서만 · 공유 스위치를 켜서 돈다(2026-10-05)."""
    names = [s.name for s in du.STEPS]
    assert names.index("financial") < names.index("schedule") < names.index("calendar")
    sch = next(s for s in du.STEPS if s.name == "schedule")
    assert (sch.fatal, sch.derived, sch.upload) == (False, False, False)
    sec = next(s for s in du.STEPS if s.name == "sector_laws")
    assert names[-1] == "sector_laws" and (sec.fatal, sec.upload, sec.sharing) == (False, True, True)
    assert "weekly" in sec.args and "--yes" in sec.args


def test_news_step_before_search_index():
    """정책뉴스는 이름표 · 색인(search) 앞 — 그날 받은 기사가 같은 회차의 색인에 들어간다 · 실패해도 뒤를 막지 않고
    올리기 · 공유 스위치와 무관하다(2026-10-05)."""
    names = [s.name for s in du.STEPS]
    assert names.index("schedule") < names.index("news") < names.index("search")
    news = next(s for s in du.STEPS if s.name == "news")
    assert (news.fatal, news.derived, news.upload, news.sharing) == (False, False, False, False)
    assert news.args[:3] == ["-m", "collector.policy_news", "daily"]


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


# ── 6. 단계 이름표 · 회차 기록 · 한 단계만 다시(2026-10-07 · 결정 ④) ─────────────────────
def test_every_step_has_label_group_desc_in_group_order():
    """모든 단계에 화면 이름표 · 묶음 · 하는 일이 있다 — 앱은 이것을 기록에서만 읽으니 빠지면 영어 이름이 보인다.
    묶음은 ``GROUPS`` 차례대로 이어져 있다(화면이 러너 차례로 줄을 놓고 묶음이 바뀔 때 머리를 단다)."""
    keys = [g["key"] for g in du.GROUPS]
    labels = [s.label for s in du.STEPS]
    assert all(s.label and s.group and s.desc for s in du.STEPS), [s.name for s in du.STEPS if not (s.label and s.group and s.desc)]
    assert len(set(labels)) == len(labels), "이름표가 겹친다"
    assert all(s.group in keys for s in du.STEPS)
    seen = [g for i, g in enumerate(s.group for s in du.STEPS) if i == 0 or du.STEPS[i - 1].group != g]
    assert seen == [k for k in keys if k in seen], f"묶음이 끊겼거나 차례가 다르다: {seen}"
    cat = du.step_catalog()
    assert [s["name"] for s in cat["steps"]] == [s.name for s in du.STEPS] and cat["groups"] == du.GROUPS


@pytest.fixture
def fake_runner(tmp_path, monkeypatch):
    """임시 폴더에서 도는 러너 — 단계 둘(성공 · 멈추지 않는 실패), 잠금 · 기록 · 로그 · 목록 · 용량 파일 모두 임시 경로."""
    import functools
    lock = tmp_path / "state" / "daily_update.lock"
    for name, rel in (("LOG_DIR", "logs"), ("LAST_PATH", "state/daily_update_last.json"),
                      ("HISTORY_PATH", "state/daily_update_history.jsonl"),
                      ("CATALOG_PATH", "state/daily_update_steps.json"), ("DISK_PATH", "state/pc_disk.json"),
                      ("PROGRESS_PATH", "state/daily_update_progress.json")):
        monkeypatch.setattr(du, name, tmp_path / rel)
    monkeypatch.setattr(du, "acquire_lock", functools.partial(du.acquire_lock, lock))
    monkeypatch.setattr(du, "release_lock", functools.partial(du.release_lock, lock))
    monkeypatch.setattr(du, "snapshot", lambda *a, **k: {})
    monkeypatch.setattr(du, "ROOT", tmp_path)                 # 로그 경로를 저장소 기준 상대 경로로 적는다 — 임시 폴더를 뿌리로
    db = tmp_path / "market.sqlite3"
    db.write_bytes(b"x" * 1000)
    monkeypatch.setattr(du.config, "DB_PATH", db)
    steps = [du.Step("alpha", ["-c", "pass"], 1, label="가 단계", group="받기", desc="첫 일"),
             du.Step("beta", ["-c", "import sys; sys.exit(3)"], 1, fatal=False, label="나 단계", group="계산", desc="둘째 일")]
    monkeypatch.setattr(du, "STEPS", steps)
    (tmp_path / "state").mkdir()
    return tmp_path


def test_run_writes_labels_step_history_catalog_and_disk(fake_runner):
    """회차 기록의 단계 줄에 이름표 · 묶음 · 하는 일 · 멈춤 여부가 함께 남고, 이력 줄에 단계별 결과 · 단계 목록 · 이 PC 용량 파일이 생긴다."""
    t = fake_runner
    assert du.run_all() == 3
    last = json.loads((t / "state/daily_update_last.json").read_text(encoding="utf-8"))
    assert [(s["name"], s["label"], s["group"], s["fatal"], s["rc"]) for s in last["steps"]] == [
        ("alpha", "가 단계", "받기", True, 0), ("beta", "나 단계", "계산", False, 3)]
    hist = [json.loads(x) for x in (t / "state/daily_update_history.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(s["name"], s["rc"]) for s in hist[-1]["steps"]] == [("alpha", 0), ("beta", 3)]
    assert "label" not in hist[-1]["steps"][0], "이력 줄은 짧게 — 이름표는 단계 목록 파일에 있다"
    cat = json.loads((t / "state/daily_update_steps.json").read_text(encoding="utf-8"))
    assert [s["label"] for s in cat["steps"]] == ["가 단계", "나 단계"]
    disk = json.loads((t / "state/pc_disk.json").read_text(encoding="utf-8"))
    assert disk["collector_db_bytes"] == 1000 and disk["free_bytes"] > 0 and disk["total_bytes"] >= disk["free_bytes"]
    assert not (t / "state/daily_update.lock").exists(), "잠금을 풀었다"


def test_progress_names_the_running_step_and_is_cleared(fake_runner, monkeypatch):
    """도는 중의 지금 단계 — 단계를 시작할 때 진행 파일에 몇 번째 · 모두 몇 · 이름 · 이름표를 잠금과 같은 시작 시각으로 적고,
    회차가 끝나면 지운다 · 한 단계 다시도 같다(수집 일정 화면 「수집 중 — n번째 단계」 · 2026-10-08).
    시계는 부를 때마다 1초씩 간다 — 잠금이 시작 시각을 따로 재면(같은 초에 들어 우연히 통과하던 꼴) 여기서 어긋난다."""
    t = fake_runner
    base = datetime.datetime(2026, 10, 8, 15, 0, tzinfo=du.KST)
    ticks = iter(range(10_000))
    monkeypatch.setattr(du, "now_kst", lambda: base + datetime.timedelta(seconds=next(ticks)))
    prog, lock = t / "state" / "daily_update_progress.json", t / "state" / "daily_update.lock"
    # 단계 안에서 진행 파일 · 잠금을 읽어 맞으면 0, 아니면 9(회차 기록에 남는다)
    check = ("import json,sys; p=json.load(open(r'{p}',encoding='utf-8')); l=json.load(open(r'{l}',encoding='utf-8')); "
             "s=p['step']; sys.exit(0 if (s['index'], s['total'], s['name'], s['label']) == ({i}, 2, '{n}', '{lb}') "
             "and p['started_at'] == l['started_at'] else 9)")
    du.STEPS[0] = du.Step("alpha", ["-c", check.format(p=prog, l=lock, i=1, n="alpha", lb="가 단계")], 1,
                          label="가 단계", group="받기", desc="첫 일")
    du.STEPS[1] = du.Step("beta", ["-c", check.format(p=prog, l=lock, i=2, n="beta", lb="나 단계")], 1, fatal=False,
                          label="나 단계", group="계산", desc="둘째 일")
    assert du.run_all() == 0, "단계 안에서 본 진행 파일이 그 단계 · 잠금과 같은 시작 시각이어야 한다"
    assert not prog.exists(), "회차가 끝나면 진행 파일을 지운다"
    assert du.run_one("beta", now=datetime.datetime(2026, 10, 8, 16, 0, tzinfo=du.KST)) == 0 and not prog.exists()


def test_rerun_one_step_blocks_and_patches_only_that_row(fake_runner):
    """한 단계만 다시 — 고를 수 없는 단계 · 올리기 단계는 2, 12:30 회차와 겹치는 때 · 다른 실행이 돌 때는 3 으로 막고,
    돌리면 마지막 회차의 그 줄만 새 결과로 바꾸고 이력에 「다시 돌림」 한 줄을 남긴다."""
    t = fake_runner
    du.run_all()
    noon = datetime.datetime(2026, 10, 7, 12, 45, tzinfo=du.KST)   # 시험 단계 한도 1분 → 12:29 ~ 13:30 이 막힘
    later = datetime.datetime(2026, 10, 7, 15, 0, tzinfo=du.KST)
    hist = t / "state/daily_update_history.jsonl"
    n0 = len(hist.read_text(encoding="utf-8").splitlines())
    assert du.run_one("없는단계", now=later) == 2
    assert du.run_one("alpha", now=noon) == 3, "12:30 회차와 겹친다(돌았다면 alpha 는 0 이다)"
    assert len(hist.read_text(encoding="utf-8").splitlines()) == n0, "막힌 실행은 이력을 남기지 않는다"
    du.STEPS.append(du.Step("up", ["-c", "pass"], 1, upload=True, label="올림", group="백업", desc="올린다"))
    assert du.run_one("up", now=later) == 2, "올리기 단계는 --upload 와 함께만"
    (t / "state/daily_update.lock").write_text(json.dumps({"pid": __import__("os").getpid(),
                                                           "started_at": later.isoformat()}), encoding="utf-8")
    assert du.run_one("beta", now=later) == 3, "다른 실행이 돌고 있다"
    (t / "state/daily_update.lock").unlink()

    du.STEPS[1] = du.Step("beta", ["-c", "pass"], 1, fatal=False, label="나 단계", group="계산", desc="둘째 일")
    before = json.loads((t / "state/daily_update_last.json").read_text(encoding="utf-8"))
    assert du.run_one("beta", now=later) == 0
    last = json.loads((t / "state/daily_update_last.json").read_text(encoding="utf-8"))
    assert last["steps"][0] == before["steps"][0], "다른 단계 줄은 그대로"
    assert (last["steps"][1]["rc"], last["steps"][1]["note"]) == (0, "다시 돌림") and last["steps"][1]["rerun_at"]
    assert last["ok"] is True and last["started_at"] == before["started_at"] and last["reruns"][-1]["name"] == "beta"
    h = json.loads((t / "state/daily_update_history.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert (h["only"], h["ok"], [s["name"] for s in h["steps"]]) == ("beta", True, ["beta"])
    assert not (t / "state/daily_update.lock").exists()


def test_rerun_window_follows_step_timeout():
    """막는 때는 「회차 시작 − 그 단계 시간 한도」 ~ 「회차 시작 + 60분」 — 긴 단계일수록 일찍부터 막는다."""
    s10 = du.Step("s", [], 10)
    s60 = du.Step("l", [], 60)
    at = lambda h, m: datetime.datetime(2026, 10, 7, h, m, tzinfo=du.KST)  # noqa: E731
    assert du.rerun_blocked(s10, at(12, 19)) is None and du.rerun_blocked(s10, at(12, 20))
    assert du.rerun_blocked(s60, at(11, 30)) and du.rerun_blocked(s60, at(11, 29)) is None
    assert du.rerun_blocked(s10, at(13, 30)) and du.rerun_blocked(s10, at(13, 31)) is None


def test_rerun_leaves_wal_side_files_for_the_app(fake_runner, monkeypatch):
    """한 단계 다시 뒤에도 수집 DB 의 WAL 보조 파일(-wal · -shm)이 남는다 — 앱(도커)은 data/ 를 읽기 전용으로 붙여, 이것이
    없으면 수집 DB 를 열지 못한다(2026-10-07 `run --only manifest` 뒤 데이터 API 8개가 「unable to open database file」).
    쓰기 연결이 마지막으로 닫히면 SQLite 가 둘을 지우므로, 러너가 단계 뒤에 읽기 전용으로 한 번 열어 다시 만든다."""
    t = fake_runner
    db = t / "wal.sqlite3"
    c = sqlite3.connect(db)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("CREATE TABLE x (a INTEGER)")
    c.commit()
    c.close()
    side = (db.with_name(db.name + "-wal"), db.with_name(db.name + "-shm"))
    assert not any(p.exists() for p in side), "시험의 전제 — 쓰기 연결이 마지막으로 닫히면 보조 파일이 지워진다"
    monkeypatch.setattr(du.config, "DB_PATH", db)
    code = f"import sqlite3; c = sqlite3.connect({str(db)!r}); c.execute('INSERT INTO x VALUES (1)'); c.commit(); c.close()"
    du.STEPS.append(du.Step("write", ["-c", code], 1, fatal=False, label="쓰기", group="받기", desc="수집 DB 에 쓴다"))
    later = datetime.datetime(2026, 10, 7, 15, 0, tzinfo=du.KST)
    assert du.run_one("write", now=later) == 0
    assert all(p.exists() for p in side), "단계가 쓰기 연결로 끝나도 보조 파일이 남아야 앱이 읽는다"
    assert du.rearm_wal(t / "없는.sqlite3") is False
