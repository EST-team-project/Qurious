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
                      ("PROGRESS_PATH", "state/daily_update_progress.json"),
                      ("FILL_PATH", "state/daily_update_fill.json"),           # 빠진 날 — 진짜 상태 폴더에 쓰지 않게(2026-10-10)
                      ("GUIDE_STATS_PATH", "state/data_guide_stats.json")):    # 자료 안내 숫자 — 같은 까닭(2026-10-11)
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
    # 시계는 월 15:00 부터 부를 때마다 1초 — 정기 회차는 12:30 앞 막는 때(11:00 ~ 12:28 · DF-99)에 돌지 않으므로, 시계를 고정하지
    # 않으면 이 시험들이 그 시간에 돌 때만 실패한다(2026-10-15). 시각을 보는 시험은 저마다 다시 고정한다.
    base = datetime.datetime(2026, 10, 12, 15, 0, tzinfo=du.KST)
    ticks = iter(range(10_000_000))
    monkeypatch.setattr(du, "now_kst", lambda: base + datetime.timedelta(seconds=next(ticks)))
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
    """한 단계만 다시 — 고를 수 없는 단계 · 올리기 단계는 2, 12:30 회차와 겹치는 때 · 다른 실행이 돌 때는 75(EX_TEMPFAIL ·
    「지금은 못 돈다, 나중에 다시」)로 막고, 돌리면 마지막 회차의 그 줄만 새 결과로 바꾸고 이력에 「다시 돌림」 한 줄을 남긴다.
    막힘이 단계가 스스로 내는 3 과 겹치지 않아야 화면 작업자가 「기다림」 과 「경고」 를 가른다(2026-10-10)."""
    t = fake_runner
    du.run_all()
    noon = datetime.datetime(2026, 10, 7, 12, 45, tzinfo=du.KST)   # 시험 단계 한도 1분 → 12:29 ~ 13:30 이 막힘
    later = datetime.datetime(2026, 10, 7, 15, 0, tzinfo=du.KST)
    hist = t / "state/daily_update_history.jsonl"
    n0 = len(hist.read_text(encoding="utf-8").splitlines())
    assert du.run_one("없는단계", now=later) == 2
    assert du.run_one("alpha", now=noon) == du.EX_TEMPFAIL == 75, "12:30 회차와 겹친다(돌았다면 alpha 는 0 이다)"
    assert len(hist.read_text(encoding="utf-8").splitlines()) == n0, "막힌 실행은 이력을 남기지 않는다"
    du.STEPS.append(du.Step("up", ["-c", "pass"], 1, upload=True, label="올림", group="백업", desc="올린다"))
    assert du.run_one("up", now=later) == 2, "올리기 단계는 --upload 와 함께만"
    (t / "state/daily_update.lock").write_text(json.dumps({"pid": __import__("os").getpid(),
                                                           "started_at": later.isoformat()}), encoding="utf-8")
    assert du.run_one("beta", now=later) == du.EX_TEMPFAIL, "다른 실행이 돌고 있다"
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


# ── 7. 한 단계 다시 뒤 시세 기준일(2026-10-08 · DF-85) · 신호 단계(#142) ─────────────────────
def test_rerun_remeasures_as_of_so_readiness_sees_new_price(fake_runner, monkeypatch):
    """DF-85 — 한 단계만 다시 돌린 뒤 회차 기록의 「끝 상태」(`after` · 시세 기준일)를 다시 잰다.

    옛 코드는 단계 줄 · 성공 여부만 바꾸고 `after` 는 회차 때 값 그대로 두었다 — 시세를 다시 받아도 리밸런싱 하루 점검
    준비 판정(팀원 #136 · `rebalance_daily.readiness`)이 회차 기록의 옛 기준일로 「시세 기준일이 다름」 을 냈다.
    이력 줄에도 다시 잰 기준일이 남는다(관제의 회차 목록이 그 줄의 기준일을 보인다)."""
    from app.services import data_status

    t = fake_runner
    state = {"price_max": "20261006", "adjusted_max": "20261006"}
    monkeypatch.setattr(du, "snapshot", lambda *a, **k: dict(state))
    du.run_all()
    last = json.loads((t / "state/daily_update_last.json").read_text(encoding="utf-8"))
    assert last["after"]["price_max"] == "20261006"

    state.update(price_max="20261007")                                # 오후에 시세 단계를 다시 돌려 하루치가 들어왔다
    du.STEPS[1] = du.Step("beta", ["-c", "pass"], 1, fatal=False, label="나 단계", group="계산", desc="둘째 일")
    assert du.run_one("beta", now=datetime.datetime(2026, 10, 8, 15, 0, tzinfo=du.KST)) == 0
    last = json.loads((t / "state/daily_update_last.json").read_text(encoding="utf-8"))
    assert last["after"]["price_max"] == "20261007", "다시 돌린 뒤 기준일을 다시 잰다"
    assert last["after"]["adjusted_max"] == "20261006" and last["before"] is not None, "회차의 시작 상태는 그대로"
    hist = json.loads((t / "state/daily_update_history.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert (hist["only"], hist["price_max"]) == ("beta", "20261007")
    now = datetime.datetime(2026, 10, 8, 15, 1, tzinfo=du.KST)
    assert data_status.runner_state(t / "state", now)["last"]["price_max"] == "2026-10-07", "준비 판정이 읽는 칸"


def test_rerun_keeps_old_as_of_and_says_so_when_measure_fails(fake_runner, monkeypatch):
    """다시 재기가 실패하면(수집 DB 를 못 엶) 옛 기준일을 그대로 두되 말없이 넘어가지 않는다 — 로그에 한 줄 ·
    회차 기록에 `after_error`(언제 · 왜). 화면 · 준비 판정이 「옛 값」 임을 알 수 있게."""
    t = fake_runner
    monkeypatch.setattr(du, "snapshot", lambda *a, **k: {"price_max": "20261006"})
    du.run_all()

    def broken(*a, **k):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(du, "snapshot", broken)
    du.STEPS[1] = du.Step("beta", ["-c", "pass"], 1, fatal=False, label="나 단계", group="계산", desc="둘째 일")
    assert du.run_one("beta", now=datetime.datetime(2026, 10, 8, 15, 0, tzinfo=du.KST)) == 0
    last = json.loads((t / "state/daily_update_last.json").read_text(encoding="utf-8"))
    assert last["after"]["price_max"] == "20261006", "못 재면 옛 값을 지우지 않는다"
    assert "database is locked" in last["after_error"]["why"] and last["after_error"]["at"]
    log = sorted((t / "logs").glob("*-only-beta.log"))[-1].read_text(encoding="utf-8")
    assert "시세 기준일을 다시 재지 못했다" in log


def test_rerun_of_a_new_step_is_inserted_in_catalog_order(fake_runner):
    """회차 뒤에 더한 단계(신호 단계를 처음 붙인 날)를 한 단계만 다시 돌리면 마지막 회차 기록에 그 줄이 없다 — 옛 코드는
    바꿀 줄을 못 찾아 결과를 버렸다(이력에만 남고 수집 일정 화면 표에는 안 보임). 단계 목록 차례 자리에 끼워 넣는다."""
    t = fake_runner
    du.run_all()
    du.STEPS.insert(1, du.Step("gamma", ["-c", "pass"], 1, fatal=False, label="다 단계", group="받기", desc="새 일"))
    assert du.run_one("gamma", now=datetime.datetime(2026, 10, 8, 15, 0, tzinfo=du.KST)) == 0
    last = json.loads((t / "state/daily_update_last.json").read_text(encoding="utf-8"))
    assert [s["name"] for s in last["steps"]] == ["alpha", "gamma", "beta"]
    assert (last["steps"][1]["rc"], last["steps"][1]["label"]) == (0, "다 단계")


def test_host_app_db_address_comes_from_compose_and_matches_dev_ps1():
    """앱 DB 주소 — 컨테이너끼리는 `postgres:5432` 지만 PC 에서 도는 단계는 compose 가 연 포트로 불러야 한다.

    2026-10-08 실측: 러너로 신호 단계를 돌리자 앱 DB 컨테이너가 떠 있는데도 `ConnectionRefusedError` → 종료코드 3.
    앱 설정(`app/config.py`)은 ENV_FILE 이 없으면 `.env.dev` 를 읽고, 컨테이너가 받는 주소는 compose 의 environment 에만 있다.
    정본은 compose(앱의 DATABASE_URL + postgres 포트 짝)이고, 개발 모드 스크립트(`scripts/personal/dev.ps1`)와 같은 값이어야 한다."""
    import re
    from urllib.parse import urlsplit

    env, why = du.host_app_db_env()
    assert why is None, why
    got = urlsplit(env["DATABASE_URL"])
    assert (got.scheme, got.hostname, got.port, got.path) == ("postgresql+asyncpg", "127.0.0.1", 15432, "/fin_ai")
    dev = (du.ROOT / "scripts" / "personal" / "dev.ps1").read_text(encoding="utf-8")
    m = re.search(r"^\s+DATABASE_URL\s+=\s+'([^']+)'", dev, re.M)
    want = urlsplit(m.group(1))
    assert (got.username, got.password, got.port, got.path) == (want.username, want.password, want.port, want.path), \
        "dev.ps1 3단계의 PC 쪽 주소와 같아야 한다(호스트 이름만 127.0.0.1 — DF-63)"


def test_host_app_db_address_says_why_when_compose_lacks_it(tmp_path):
    """compose 에서 주소를 못 만들면 빈 값과 까닭 — 말없이 `.env.dev` 기본 주소로 돌게 두지 않는다(러너가 로그 · 단계 메모에 적는다)."""
    p = tmp_path / "docker-compose.yml"
    p.write_text("services:\n  app:\n    environment:\n    - PORT=8000\n", encoding="utf-8")
    env, why = du.host_app_db_env(p)
    assert env == {} and "DATABASE_URL" in why
    p.write_text("services:\n  app:\n    environment:\n    - DATABASE_URL=postgresql+asyncpg://u:p@postgres:5432/db\n"
                 "  postgres:\n    image: x\n", encoding="utf-8")
    env, why = du.host_app_db_env(p)
    assert env == {} and "5432" in why and "포트" in why
    p.write_text("services:\n  app:\n    environment:\n      DATABASE_URL: postgresql+asyncpg://u:p@postgres:5432/db\n"
                 "  postgres:\n    ports:\n    - \"127.0.0.1:25432:5432/tcp\"\n", encoding="utf-8")
    env, why = du.host_app_db_env(p)
    assert why is None and env["DATABASE_URL"] == "postgresql+asyncpg://u:p@127.0.0.1:25432/db", "사전 꼴 · IP 붙은 포트 짝도 읽는다"
    assert du.host_app_db_env(tmp_path / "없음.yml")[0] == {}


def test_only_app_db_steps_get_the_host_address(fake_runner, monkeypatch):
    """PC 쪽 앱 DB 주소는 앱 DB 를 쓰는 단계(`app_db=True`)에만 넘긴다 — 다른 단계의 환경은 그대로. 로그에는 비밀번호 없이
    호스트:포트/DB 만 남는다. 포트는 시험이 연 빈 포트다 — 개발 DB 포트(15432)를 쓰면 개발 앱이 꺼진 날 러너가 단계를
    「앱 DB 꺼짐」 으로 건너뛰어 이 시험이 실패한다(S105 a2 를 다시 돌리기 전 리허설에서 찾음)."""
    import socket
    t = fake_runner
    monkeypatch.delenv("DATABASE_URL", raising=False)
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen()
    port = srv.getsockname()[1]
    try:
        monkeypatch.setattr(du, "host_app_db_env", _db_env(port))
        dump = "import os,sys; open(sys.argv[1],'w').write(os.environ.get('DATABASE_URL','(없음)'))"
        du.STEPS[0] = du.Step("alpha", ["-c", dump, str(t / "a.txt")], 1, label="가 단계", group="받기", desc="첫 일", app_db=True)
        du.STEPS[1] = du.Step("beta", ["-c", dump, str(t / "b.txt")], 1, fatal=False, label="나 단계", group="계산", desc="둘째 일")
        assert du.run_all() == 0
    finally:
        srv.close()
    assert (t / "a.txt").read_text() == f"postgresql+asyncpg://u:secret@127.0.0.1:{port}/fin_ai"
    assert (t / "b.txt").read_text() == "(없음)"
    log = sorted((t / "logs").glob("daily_update-*.log"))[-1].read_text(encoding="utf-8")
    assert f"127.0.0.1:{port}/fin_ai" in log and "secret" not in log, "주소만 · 비밀번호는 찍지 않는다"


def test_signals_step_after_daily_bars_before_manifest():
    """#142 — 다중 주기 신호 배치(`scripts/signals_daily.py` · 팀원 #140)는 일봉 · 분봉(ohlcv) 뒤 · 목록표(manifest) 앞.
    그날 일봉 · 60분봉이 들어온 다음에 돌아야 하고, 실패해도 백업을 막지 않는다(fatal=False). 파생 판정 · 올리기와 무관하다."""
    names = [s.name for s in du.STEPS]
    # 신호 뒤에는 모의 일지(2026-10-24 · 신호와 같은 계산 묶음) — 그 뒤가 목록표다(TC-PJ-13)
    assert names.index("ohlcv") + 1 == names.index("signals") and names.index("signals") + 1 == names.index("journal")
    assert names.index("journal") + 1 == names.index("manifest")
    sig = next(s for s in du.STEPS if s.name == "signals")
    assert sig.args == ["scripts/signals_daily.py"], "인자 없이 — 수집 DB 의 마지막 거래일 하루"
    assert (sig.fatal, sig.derived, sig.upload, sig.sharing) == (False, False, False, False)
    assert (sig.label, sig.group) == ("신호", "계산") and sig.timeout_min >= 5
    assert sig.app_db is True, "앱 DB(T2)에 쓰는 단계 — PC 쪽 주소를 받아야 한다"
    assert [s.name for s in du.STEPS if s.app_db] == ["signals", "journal"], "앱 DB 를 쓰는 단계는 신호 · 모의 일지 둘뿐이다"


# ── 8. 앱 DB 를 쓰는 단계의 전제 조건(2026-10-08 · 조사서 안 B · 사용자 결정) ─────────────────────
def _closed_port() -> int:
    """지금 아무도 듣지 않는 포트 — 잠깐 묶었다 푼 번호."""
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _db_env(port: int):
    return lambda *a, **k: ({"DATABASE_URL": f"postgresql+asyncpg://u:secret@127.0.0.1:{port}/fin_ai"}, None)


def _last(t) -> dict:
    return json.loads((t / "state/daily_update_last.json").read_text(encoding="utf-8"))


def test_app_db_step_is_skipped_not_run_when_port_closed(fake_runner, monkeypatch):
    """앱 DB 가 꺼진 날 — 러너가 돌리기 **전에** compose 주소로 포트를 확인하고, 닫혀 있으면 단계를 돌리지 않는다.
    단계 줄은 `rc` 없음 · 까닭 `app_db_down` · 뒤 할 일 `fill` · 그 회차가 계산했을 거래일. 회차는 성공 그대로다 —
    리밸런싱 하루 점검(팀원 #136)이 읽는 회차 ok · 시세 · 달력 줄을 신호가 흔들지 않는다(#142 답글 약속)."""
    t = fake_runner
    port = _closed_port()
    monkeypatch.setattr(du, "host_app_db_env", _db_env(port))
    monkeypatch.setattr(du, "snapshot", lambda *a, **k: {"price_max": "20261007"})
    marker = t / "ran.txt"
    du.STEPS[1] = du.Step("beta", ["-c", f"open(r'{marker}', 'w').write('x')"], 1, fatal=False, app_db=True,
                          label="나 단계", group="계산", desc="둘째 일", fill="python x.py --from YYYY-MM-DD --to YYYY-MM-DD")
    assert du.run_all() == 0
    assert not marker.exists(), "포트가 닫혀 있으면 돌리지 않는다(계산을 버리지 않는다)"
    last = _last(t)
    b = last["steps"][1]
    assert (b["rc"], b["reason"], b["followup"], b["date"]) == (None, "app_db_down", "fill", "2026-10-07")
    assert "앱 DB 꺼짐" in b["note"] and f"127.0.0.1:{port}" in b["note"] and "secret" not in b["note"]
    assert last["ok"] is True and last["steps"][0]["rc"] == 0
    hist = json.loads((t / "state/daily_update_history.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert (hist["steps"][1]["reason"], hist["steps"][1]["followup"]) == ("app_db_down", "fill"), "이력 줄에도 남는다"


def test_app_db_step_failing_with_port_open_is_a_warning(fake_runner, monkeypatch):
    """포트가 열려 있는데 단계가 실패하면(오늘 실측처럼 주소 · 계정이 틀린 경우 등) 건너뜀이 아니라 **경고**다 —
    종료코드 3 만 보고 건너뜀으로 바꾸면 설정 결함이 노랑 한 줄 뒤에 숨는다."""
    import socket
    t = fake_runner
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen()
    try:
        monkeypatch.setattr(du, "host_app_db_env", _db_env(srv.getsockname()[1]))
        du.STEPS[1] = du.Step("beta", ["-c", "import sys; sys.exit(3)"], 1, fatal=False, app_db=True,
                              label="나 단계", group="계산", desc="둘째 일")
        assert du.run_all() == 3
    finally:
        srv.close()
    b = _last(t)["steps"][1]
    assert b["rc"] == 3 and "reason" not in b and _last(t)["ok"] is False


def test_app_db_step_without_address_is_not_run_and_warns(fake_runner, monkeypatch):
    """주소를 compose 에서 만들지 못하면 돌리지 않는다 — 앱 설정의 기본 주소(`.env.dev` · 기초 코드의 `lumina@localhost`)로
    돌면 다른 DB 에 말없이 쓸 수 있다. 설정 결함이라 경고(종료코드 78 = EX_CONFIG)로 남긴다."""
    t = fake_runner
    monkeypatch.setattr(du, "host_app_db_env", lambda *a, **k: ({}, "compose 의 앱 서비스에 DATABASE_URL 이 없다"))
    marker = t / "ran.txt"
    du.STEPS[1] = du.Step("beta", ["-c", f"open(r'{marker}', 'w').write('x')"], 1, fatal=False, app_db=True,
                          label="나 단계", group="계산", desc="둘째 일")
    assert du.run_all() == du.EX_CONFIG == 78
    assert not marker.exists()
    b = _last(t)["steps"][1]
    assert (b["rc"], b["reason"]) == (78, "app_db_address_unknown") and "DATABASE_URL" in b["note"]
    assert _last(t)["ok"] is False


def test_rerun_of_app_db_step_with_db_down_is_blocked_and_recorded(fake_runner, monkeypatch):
    """한 단계 다시(`run --only`)도 같다 — 포트가 닫혀 있으면 돌리지 않고 종료코드 3(건너뜀 · 채울 것 — 회차와 겹친 막힘 75 와
    다르다)으로 끝나며, 회차 기록의 그 줄을
    「건너뜀 · 앱 DB 꺼짐」 으로 바꾸고 이력에 한 줄 남긴다(무엇을 시도했는지 보인다)."""
    t = fake_runner
    du.run_all()
    monkeypatch.setattr(du, "host_app_db_env", _db_env(_closed_port()))
    monkeypatch.setattr(du, "snapshot", lambda *a, **k: {"price_max": "20261007"})
    du.STEPS[1] = du.Step("beta", ["-c", "pass"], 1, fatal=False, app_db=True, label="나 단계", group="계산", desc="둘째 일")
    assert du.run_one("beta", now=datetime.datetime(2026, 10, 8, 15, 0, tzinfo=du.KST)) == 3
    b = _last(t)["steps"][1]
    assert (b["rc"], b["reason"], b["followup"]) == (None, "app_db_down", "fill") and b["rerun_at"]
    hist = json.loads((t / "state/daily_update_history.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert hist["only"] == "beta" and hist["steps"][0]["reason"] == "app_db_down"


def test_every_runner_skip_says_why(fake_runner, monkeypatch):
    """할 일이 없어 건너뛴 줄에도 까닭 코드를 적는다 — 업로드 끔 · 새 자료 없음 · 앞 단계 실패 · 올릴 것 없음.
    화면은 까닭 코드로 「채울 것이 있는 건너뜀(노랑)」 과 「할 일 없는 건너뜀(회색)」 을 가른다(조사서 안 B)."""
    t = fake_runner
    same = {"price_max": "20261007", "price_recent_rows": 10, "adjusted_max": "20261007", "tr_max": "20261007",
            "benchmark_max": "20261007", "dividend": [1, "x", 1.0, 0.0]}
    monkeypatch.setattr(du, "snapshot", lambda *a, **k: dict(same))
    monkeypatch.setattr(du, "_pending_upload", lambda: [])
    du.STEPS[:] = [du.Step("d", ["-c", "pass"], 1, derived=True, label="파생", group="계산", desc="d"),
                   du.Step("u", ["-c", "pass"], 1, upload=True, label="올림", group="백업", desc="u")]
    du.run_all(upload=False)
    assert [(s["name"], s.get("reason")) for s in _last(t)["steps"]] == [("d", "no_new_data"), ("u", "upload_off")]
    du.STEPS[:] = [du.Step("upload", ["-c", "pass"], 1, upload=True, label="올리기", group="백업", desc="u")]
    du.run_all(upload=True)
    assert _last(t)["steps"][0]["reason"] == "nothing_to_upload"
    du.STEPS[:] = [du.Step("f", ["-c", "import sys; sys.exit(1)"], 1, label="멈춤", group="받기", desc="f"),
                   du.Step("g", ["-c", "pass"], 1, label="뒤", group="계산", desc="g")]
    du.run_all()
    assert _last(t)["steps"][1]["reason"] == "upstream_failed"
    assert all("followup" not in s for s in _last(t)["steps"]), "할 일 없는 건너뜀에는 뒤 할 일이 없다"


def test_fill_command_lives_in_the_step_and_reaches_the_catalog():
    """빠진 날 채우기 명령(#142 답글 — 앱 DB 가 꺼진 날은 `--from` · `--to` 로 채운다)은 러너 단계 정의 한 곳에 두고
    단계 목록(앱이 읽는 파일)에 그대로 싣는다 — 화면은 그 칸이 있는 단계에만 「빠진 날 채우기」 명령을 보인다."""
    sig = next(s for s in du.STEPS if s.name == "signals")
    assert sig.fill == "python scripts/signals_daily.py --from YYYY-MM-DD --to YYYY-MM-DD"
    cat = {s["name"]: s for s in du.step_catalog()["steps"]}
    assert cat["signals"]["fill"] == sig.fill
    assert all(cat[n]["fill"] == "" for n in cat if n != "signals"), "채우기 명령이 없는 단계는 빈 글"


# ── 7. 화면 수집 요청 — 막는 때 한 곳 · 수동 회차 · 요청 번호(2026-10-10) ─────────────────────
RID = "11111111-2222-3333-4444-555555555555"


def _at(h, m):
    return datetime.datetime(2026, 10, 12, h, m, tzinfo=du.KST)


def test_guard_windows_come_from_one_function():
    """막는 때는 `guard_window` 한 곳에서 — 한 단계 다시 · 수동 전체 수집 · 단계 목록에 싣는 시각(앱은 보이기만 한다)이 같은 셈이다.
    전체 수집 11:00 ~ 13:30(앞 90분 · 뒤 60분) · 단계마다 「12:30 − 그 단계 한도 ~ 13:30」 · 목록의 시각 경계에서 판정이 바뀐다."""
    assert du.full_run_blocked(_at(10, 59)) is None and du.full_run_blocked(_at(13, 31)) is None
    assert "11:00 ~ 13:30" in du.full_run_blocked(_at(11, 0)) and du.full_run_blocked(_at(13, 30))
    g = du.step_catalog(now=_at(9, 0))["guards"]
    assert g["schedule"] == du.DEFAULT_TIME and g["full"] == {"from": "11:00", "to": "13:30"}
    assert set(g["steps"]) == {s.name for s in du.STEPS}
    one = datetime.timedelta(minutes=1)
    for s in du.STEPS:
        w = g["steps"][s.name]
        lo, hi = _at(*map(int, w["from"].split(":"))), _at(*map(int, w["to"].split(":")))
        assert du.rerun_blocked(s, lo) and du.rerun_blocked(s, hi), s.name
        assert du.rerun_blocked(s, lo - one) is None and du.rerun_blocked(s, hi + one) is None, s.name


def test_manual_full_run_waits_instead_of_skipping(fake_runner, monkeypatch):
    """수동 회차(화면 「전체 수집」)는 막는 때 · 다른 실행이 돌 때 75 로 끝나고 「건너뜀」 이력 줄 · 잠금을 남기지 않는다
    (작업자가 요청을 대기로 되돌린다 — 요청 줄이 기록이다). 정기 회차의 겹침은 지금처럼 0 과 「건너뜀」 줄."""
    t = fake_runner
    hist, lock = t / "state/daily_update_history.jsonl", t / "state/daily_update.lock"
    monkeypatch.setattr(du, "now_kst", lambda: _at(11, 30))
    assert du.run_all(manual=True, request_id=RID) == du.EX_TEMPFAIL
    assert not hist.exists() and not (t / "logs").exists() and not lock.exists()
    monkeypatch.setattr(du, "now_kst", lambda: _at(15, 0))
    lock.write_text(json.dumps({"pid": __import__("os").getpid(), "started_at": _at(14, 59).isoformat()}), encoding="utf-8")
    assert du.run_all(manual=True, request_id=RID) == du.EX_TEMPFAIL and not hist.exists()
    assert du.run_all() == 0
    assert "skipped" in json.loads(hist.read_text(encoding="utf-8").splitlines()[-1])
    lock.unlink()


def test_manual_run_records_trigger_request_rc_and_log(fake_runner, monkeypatch):
    """요청 번호 · 수동 표시 · 종료코드 · 로그가 회차 기록과 이력 줄에 남는다 — 작업자가 요청 번호로 결과를 찾는다.
    정기 회차는 「schedule」 이고 요청 번호가 없다 · 한 단계 다시도 이력 줄 · 다시 돌림 줄에 요청 번호를 남긴다."""
    t = fake_runner
    monkeypatch.setattr(du, "now_kst", lambda: _at(15, 0))
    assert du.run_all(manual=True, request_id=RID) == 3              # 가짜 단계 beta 가 3(멈추지 않는 실패)
    last = _last(t)
    h = json.loads((t / "state/daily_update_history.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert (last["trigger"], last["request_id"]) == ("manual", RID)
    assert (h["trigger"], h["request_id"], h["rc"], h["ok"]) == ("manual", RID, 3, False)
    assert h["log"].endswith("-manual.log") and (t / h["log"]).exists()
    monkeypatch.setattr(du, "now_kst", lambda: _at(15, 5))
    du.run_all()
    h2 = json.loads((t / "state/daily_update_history.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert h2["trigger"] == "schedule" and "request_id" not in h2 and h2["rc"] == 3
    assert du.run_one("alpha", now=_at(15, 10), request_id=RID) == 0
    h3 = json.loads((t / "state/daily_update_history.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert (h3["only"], h3["request_id"], h3["rc"], h3["trigger"]) == ("alpha", RID, 0, "manual") and h3["log"]
    assert _last(t)["reruns"][-1]["request_id"] == RID


def test_lock_holder_only_reads(tmp_path):
    """잠금 읽기 — 없으면 None · 살아 있는 실행이면 까닭 · 죽었거나 4시간 넘은 잠금은 쥔 것이 아님(지우지 않는다 — 치우기는 잡는 쪽)."""
    import os
    lock, now = tmp_path / "x.lock", _at(15, 0)
    assert du.lock_holder(lock, now=now) is None
    lock.write_text(json.dumps({"pid": os.getpid(), "started_at": _at(14, 0).isoformat()}), encoding="utf-8")
    assert "다른 실행이 돌고 있다" in du.lock_holder(lock, now=now)
    assert du.lock_holder(lock, now=_at(14, 0) + datetime.timedelta(hours=4, minutes=1)) is None
    lock.write_text(json.dumps({"pid": 0, "started_at": _at(14, 59).isoformat()}), encoding="utf-8")
    assert du.lock_holder(lock, now=now) is None and lock.exists()
    assert du.acquire_lock(lock, now=now) is None and json.loads(lock.read_text(encoding="utf-8"))["pid"] == os.getpid()
    du.release_lock(lock)


def test_cli_request_must_be_a_request_number(monkeypatch):
    """`--request` 는 화면 요청 번호(UUID)만 — 다른 글자는 2 로 멈춘다(돌리기 전에 · 잘못 넣은 값이 기록에 섞이지 않게).
    러너 함수는 부르면 실패하게 바꿔 끼운다 — 검사가 깨져도 시험이 진짜 회차를 돌리지 않게."""
    monkeypatch.setattr(du, "run_all", lambda *a, **k: pytest.fail("검사를 지나 회차를 돌렸다"))
    monkeypatch.setattr(du, "run_one", lambda *a, **k: pytest.fail("검사를 지나 단계를 돌렸다"))
    assert du.main(["run", "--request", "not-a-uuid"]) == 2
    assert du.main(["run", "--only", "price", "--request", "x; del"]) == 2


# ── 9. 실패한 단계의 까닭(DF-101) · 빠진 날 세기 · 빠진 날 채우기(2026-10-10 · 사용자 결정 — 새 요청 종류 fill · 상한 31일) ─────
#: 2026-10-10 16:52 배당 다시 받기의 실제 로그 끝(DART 시스템 점검) — 경로는 이 PC 꼴 그대로
DART_TAIL = (
    "Traceback (most recent call last):\n"
    '  File "<frozen runpy>", line 198, in _run_module_as_main\n'
    '  File "C:\\Users\\kik32\\workspace\\EST-Camp-AI-Quant\\team_project\\Qurious\\collector\\sources\\dart.py", line 269, in _check_status\n'
    "    raise DartError(\n"
    "collector.sources.dart.DartError: DART 가 정상 응답이 아니다 (본문 20261008900398): status=800 "
    "'시스템 점검으로 인한  서비스가 중지 중입니다.'\n"
    "  할 일: status=010/011 이면 DART_API_KEY 를 확인한다(오픈API 이용현황에서\n"
    "         키 상태를 본다). status=800 은 시스템 점검이라 기다리면 된다.\n"
    "대상 2달 (전체 2달 중 2달은 이미 처리됨)\n"
)


def test_failure_line_picks_the_exception_and_drops_paths_and_keys():
    """DF-101 · 실패한 단계의 까닭 한 줄 — 그 단계 로그 구간에서 마지막 예외 줄(모듈 경로는 뗀다)을 고른다. 화면 · 요청 결과에
    그대로 나가므로 PC 경로는 파일 이름만 · 주소는 물음표 뒤를 버리고 · 「키 = 값」 꼴 비밀값 · 계정이 든 주소 · 긴 토큰은 지운다 ·
    겹친 빈칸은 하나로 · 200자를 넘지 않는다. 예외 줄이 없으면 실패 표시 줄(🔴 · 실패 · 오류) · 그것도 없으면 마지막 줄."""
    line = du.failure_line(DART_TAIL)
    assert line == ("DartError: DART 가 정상 응답이 아니다 (본문 20261008900398): status=800 "
                    "'시스템 점검으로 인한 서비스가 중지 중입니다.'")
    noisy = ("Traceback (most recent call last):\n"
             '  File "C:\\Users\\kik32\\Qurious\\collector\\x.py", line 3, in f\n'
             "requests.exceptions.HTTPError: 401 Client Error for url: "
             "https://opendart.fss.or.kr/api/list.json?crtfc_key=0123456789abcdef0123456789abcdef01234567&bgn_de=20261001"
             # 가짜 토큰은 이어 붙여 만든다 — 한 덩어리로 쓰면 커밋 전 비밀값 검사(a 스크립트) · GitHub 비밀값 차단에 걸린다
             " at C:\\Users\\kik32\\workspace\\Qurious\\collector\\sources\\dart.py token=" + "hf_" + "AbCdEfGhIjKlMnOpQrStUvWxYz012345" +
             " password: s3cr3t serviceKey=abc%2Bdef postgresql+asyncpg://u:pw@127.0.0.1:15432/fin_ai "
             "/home/runner/work/qurious/collector/y.py " + "가" * 300 + "\n")
    out = du.failure_line(noisy)
    assert out.startswith("HTTPError: 401 Client Error for url: https://opendart.fss.or.kr/api/list.json ")
    for bad in ("crtfc_key", "0123456789abcdef", "kik32", "hf_AbCd", "s3cr3t", "abc%2Bdef", ":pw@", "C:\\", "\\Users",
                "/home/runner", "requests.exceptions"):
        assert bad not in out, bad
    assert "dart.py" in out and "y.py" in out and "127.0.0.1:15432/fin_ai" in out
    assert len(out) <= du.ERROR_LINE_MAX and out.endswith("…")
    assert du.failure_line("받는 중\n🔴 포털이 503 을 돌려줬다\n정리\n") == "🔴 포털이 503 을 돌려줬다"
    assert du.failure_line("a\nb\n\n") == "b" and du.failure_line("") == ""


def test_run_records_why_a_step_failed(fake_runner, monkeypatch):
    """DF-101 · 회차 · 한 단계 다시 모두 실패한 줄에 까닭 한 줄(`error`)과 로그 파일 이름(`log_name` — 경로 없이)을 남긴다 —
    회차 기록 · 이력 줄(작업자가 요청 결과에 옮긴다). 성공한 줄에는 없다 · 단계가 찍은 키는 기록 어디에도 남지 않는다 ·
    시간 한도를 넘기면 「시간 한도」 로 · 2026-10-10 처럼 결과 줄이 「종료코드 1」 만 남지 않는다."""
    t = fake_runner
    tail = t / "tail.txt"
    tail.write_text("Traceback (most recent call last):\n"
                    '  File "C:\\Users\\kik32\\Qurious\\collector\\sources\\dart.py", line 269, in _check_status\n'
                    "collector.sources.dart.DartError: status=800 점검 — "
                    "https://opendart.fss.or.kr/api/document.xml?crtfc_key=0123456789abcdef0123456789abcdef01234567&rcept_no=1\n",
                    encoding="utf-8")
    du.STEPS[1] = du.Step("beta", ["-c", f"import sys; sys.stderr.write(open(r'{tail}', encoding='utf-8').read()); sys.exit(1)"],
                          1, fatal=False, label="나 단계", group="계산", desc="둘째 일")
    assert du.run_all() == 1
    last = _last(t)
    a, b = last["steps"]
    assert "error" not in a and "log_name" not in a
    assert b["error"] == "DartError: status=800 점검 — https://opendart.fss.or.kr/api/document.xml"
    assert b["log_name"] == (t / last["log"]).name and "/" not in b["log_name"] and "\\" not in b["log_name"]
    assert "0123456789abcdef" not in json.dumps(last, ensure_ascii=False)
    hist = json.loads((t / "state/daily_update_history.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert hist["steps"][1]["error"] == b["error"] and "error" not in hist["steps"][0]
    assert du.run_one("beta", now=datetime.datetime(2026, 10, 8, 15, 0, tzinfo=du.KST)) == 1
    b2 = _last(t)["steps"][1]
    assert (b2["error"], b2["note"]) == (b["error"], "다시 돌림") and b2["log_name"].endswith("-only-beta.log")
    monkeypatch.setattr(du, "_run_step", lambda run, step, **kw: 124)
    assert du.run_one("beta", now=datetime.datetime(2026, 10, 8, 15, 5, tzinfo=du.KST)) == 124
    assert _last(t)["steps"][1]["error"] == "시간 한도 1분을 넘겨 멈춤"


def test_catch_up_step_clears_all_missed_days_on_success(fake_runner, monkeypatch):
    """스스로 따라잡는 단계(`catch_up` · 모의 일지 2026-10-24) — 앱 DB 가 꺼진 회차마다 빠진 날을 모으는 것은 같고, 다시 뜬 회차가
    성공하면(또는 정의한 경고 종료코드면) 남은 날을 **모두** 지운다 — 단계가 마지막 행 뒤의 날을 스스로 다 계산하므로 「채울 날」 이
    성공 줄에 남지 않는다. 보통 단계(아래 시험)는 그날만 지운다."""
    import socket
    t = fake_runner
    asof = {"price_max": "20261002"}
    monkeypatch.setattr(du, "snapshot", lambda *a, **k: dict(asof))
    monkeypatch.setattr(du, "host_app_db_env", _db_env(_closed_port()))
    du.STEPS[1] = du.Step("beta", ["-c", "import sys; sys.exit(10)"], 1, fatal=False, app_db=True, catch_up=True,
                          warn_codes=(10,), label="나 단계", group="계산", desc="둘째 일")
    du.run_all()
    asof["price_max"] = "20261006"
    du.run_all()
    assert json.loads((t / "state/daily_update_fill.json").read_text(encoding="utf-8"))["steps"]["beta"]["days"] == \
        ["2026-10-02", "2026-10-06"]
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen()
    try:                                                          # 앱 DB 가 다시 뜸 — 단계가 경고 종료코드(판 바뀜)로 끝남
        monkeypatch.setattr(du, "host_app_db_env", _db_env(srv.getsockname()[1]))
        du.run_all()
    finally:
        srv.close()
    b = _last(t)["steps"][1]
    assert b["rc"] == 10 and b.get("warn") is True and "followup" not in b and "채울 날" not in (b.get("note") or "")
    state = json.loads((t / "state/daily_update_fill.json").read_text(encoding="utf-8"))
    assert "beta" not in state["steps"], "남은 날을 모두 지웠다"


def test_app_db_down_days_accumulate_and_a_good_run_removes_only_its_day(fake_runner, monkeypatch):
    """빠진 날 세기 — 앱 DB 가 꺼진 회차마다 그 회차가 계산했을 거래일을 러너 상태 파일(`daily_update_fill.json`)에 모으고 단계 줄에
    「채울 날 n · 첫날 · 마지막 날」 을 적는다(이틀 넘게 꺼졌던 때 · 사용자 2026-10-10). 앱 DB 가 다시 뜬 회차는 그날 하루만 계산하므로
    그날만 지우고 남은 날은 성공 줄이어도 「채울 것」 으로 둔다(말없이 사라지지 않게)."""
    import socket
    t = fake_runner
    asof = {"price_max": "20261002"}
    monkeypatch.setattr(du, "snapshot", lambda *a, **k: dict(asof))
    monkeypatch.setattr(du, "host_app_db_env", _db_env(_closed_port()))
    du.STEPS[1] = du.Step("beta", ["-c", "pass"], 1, fatal=False, app_db=True, label="나 단계", group="계산", desc="둘째 일",
                          fill_args=["x.py", "--from", "{from}", "--to", "{to}"])
    du.run_all()
    asof["price_max"] = "20261006"
    du.run_all()
    b = _last(t)["steps"][1]
    assert (b["rc"], b["reason"], b["followup"]) == (None, "app_db_down", "fill")
    assert (b["fill_from"], b["fill_to"], b["fill_days"]) == ("2026-10-02", "2026-10-06", 2)
    state = json.loads((t / "state/daily_update_fill.json").read_text(encoding="utf-8"))
    assert state["steps"]["beta"]["days"] == ["2026-10-02", "2026-10-06"]
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen()
    try:                                                          # 앱 DB 가 다시 뜸 — 같은 거래일(10-06)을 다시 계산
        monkeypatch.setattr(du, "host_app_db_env", _db_env(srv.getsockname()[1]))
        assert du.run_all() == 0
    finally:
        srv.close()
    b = _last(t)["steps"][1]
    assert b["rc"] == 0 and (b["followup"], b["fill_from"], b["fill_to"], b["fill_days"]) == ("fill", "2026-10-02", "2026-10-02", 1)
    assert "채울 날 1" in b["note"] and "reason" not in b
    assert json.loads((t / "state/daily_update_fill.json").read_text(encoding="utf-8"))["steps"]["beta"]["days"] == ["2026-10-02"]
    hist = json.loads((t / "state/daily_update_history.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert hist["steps"][1]["fill_days"] == 1, "이력 줄에도 남는다"


def test_fill_range_rules():
    """빠진 날 채우기의 받는 값 — 채우기 인자가 있는 단계 · 날짜 꼴(YYYY-MM-DD) · 첫날 ≤ 마지막 날 · 마지막 날 ≤ 오늘 · 31일 안
    (사용자 결정 2026-10-10 「31일」 · 양 끝 포함) · 시간 한도는 평일 수만큼 늘고 120분에서 멈춘다 · 막는 때는 그 한도로 센다."""
    sig = next(s for s in du.STEPS if s.name == "signals")
    price = next(s for s in du.STEPS if s.name == "price")
    today = datetime.date(2026, 10, 12)
    assert du.FILL_MAX_DAYS == 31
    assert du.fill_range_error(sig, "2026-10-02", "2026-10-06", today) is None
    assert du.fill_range_error(sig, "2026-09-12", "2026-10-12", today) is None            # 31일
    for a, b, word in (("2026-09-11", "2026-10-12", "31일"), ("2026-10-06", "2026-10-02", "첫날"),
                       ("2026-10-2", "2026-10-06", "날짜"), ("2026-10-02", "2026-10-13", "오늘"), ("", "2026-10-06", "날짜")):
        assert word in (du.fill_range_error(sig, a, b, today) or ""), (a, b)
    assert "채우기" in du.fill_range_error(price, "2026-10-02", "2026-10-06", today)
    assert du.fill_timeout_min(sig, "2026-10-02", "2026-10-06") == sig.timeout_min * 3          # 금 · 월 · 화
    assert du.fill_timeout_min(sig, "2026-09-12", "2026-10-12") == du.FILL_TIMEOUT_CAP_MIN == 120
    at = lambda h, m: datetime.datetime(2026, 10, 12, h, m, tzinfo=du.KST)  # noqa: E731
    assert du.fill_blocked(sig, "2026-10-02", "2026-10-06", at(12, 0)) and du.fill_blocked(sig, "2026-10-02", "2026-10-06", at(13, 31)) is None
    assert du.fill_blocked(sig, "2026-10-02", "2026-10-06", at(11, 59)) is None              # 한도 30분 → 12:00 부터
    cat = du.step_catalog(now=at(9, 0))
    assert cat["fill_max_days"] == 31 and set(cat["guards"]["fill"]) == {s.name for s in du.STEPS if s.fill_args} == {"signals"}
    w = cat["guards"]["fill"]["signals"]
    one = datetime.timedelta(minutes=1)
    lo = at(*map(int, w["from"].split(":")))
    assert du.fill_blocked(sig, "2026-09-12", "2026-10-12", lo) and du.fill_blocked(sig, "2026-09-12", "2026-10-12", lo - one) is None, \
        "단계 목록의 채우기 창은 가장 긴 범위의 창 — 화면이 끄는 때와 러너가 막는 때가 같다"
    assert sig.fill == "python scripts/signals_daily.py --from YYYY-MM-DD --to YYYY-MM-DD", "명령 글은 채우기 인자에서 만든다"


def test_fill_fields_cut_a_long_gap_into_31_day_chunks():
    """빠진 날이 31일을 넘게 쌓이면(한 달 넘게 앱 DB 가 꺼짐) 단계 줄에는 첫날부터 31일 안의 날만 한 묶음으로 적고, 남은 날 수를
    `fill_rest` 로 — 화면 단추가 보내는 범위가 늘 상한 안이다(서버가 422 로 막는 범위를 단추가 만들지 않게). 묶음을 채우면 다음
    묶음이 나온다 · 남은 날이 없으면 빈 칸."""
    days = ["2026-09-01", "2026-09-30", "2026-10-01", "2026-10-02"]
    f = du.fill_fields(days)
    assert (f["followup"], f["fill_from"], f["fill_to"], f["fill_days"], f["fill_rest"]) == (
        "fill", "2026-09-01", "2026-10-01", 3, 1)
    assert du.fill_range_error(next(s for s in du.STEPS if s.name == "signals"), f["fill_from"], f["fill_to"],
                               datetime.date(2026, 10, 12)) is None
    assert "fill_rest" not in du.fill_fields(["2026-10-06", "2026-10-02"]) and du.fill_fields([]) == {}
    assert du.fill_fields(["2026-10-06", "2026-10-02"])["fill_from"] == "2026-10-02", "차례대로"


def test_fill_run_checks_range_window_and_passes_dates(fake_runner):
    """빠진 날 채우기(`run --fill`) — 받는 값이 틀리면 2(돌리지 않음) · 12:30 회차와 겹치는 때는 75 · 돌리면 날짜를 단계 인자에 넣고
    그 범위의 빠진 날만 지운다 · 회차 기록의 그 줄 · 다시 돌림 줄 · 이력 줄(요청 번호 · 범위 · 로그)에 남긴다."""
    t = fake_runner
    out = t / "argv.txt"
    du.STEPS[1] = du.Step("beta", ["-c", "pass"], 1, fatal=False, label="나 단계", group="계산", desc="둘째 일",
                          fill_args=["-c", f"import sys; open(r'{out}', 'w').write(' '.join(sys.argv[1:]))",
                                     "--from", "{from}", "--to", "{to}"])
    du.run_all()
    (t / "state/daily_update_fill.json").write_text(json.dumps(
        {"steps": {"beta": {"days": ["2026-10-02", "2026-10-06", "2026-10-07"]}}}), encoding="utf-8")
    later = datetime.datetime(2026, 10, 8, 15, 0, tzinfo=du.KST)
    noon = datetime.datetime(2026, 10, 8, 12, 45, tzinfo=du.KST)
    hist = t / "state/daily_update_history.jsonl"
    n0 = len(hist.read_text(encoding="utf-8").splitlines())
    assert du.run_fill("alpha", "2026-10-02", "2026-10-06", now=later) == 2
    assert du.run_fill("없음", "2026-10-02", "2026-10-06", now=later) == 2
    for a, b in (("2026-10-06", "2026-10-02"), ("2026-10-2", "2026-10-06"), ("2026-09-01", "2026-10-06"),
                 ("2026-10-02", "2026-10-09")):
        assert du.run_fill("beta", a, b, now=later) == 2, (a, b)
    assert du.run_fill("beta", "2026-10-02", "2026-10-06", now=noon) == du.EX_TEMPFAIL
    assert not out.exists() and len(hist.read_text(encoding="utf-8").splitlines()) == n0, "막힌 · 틀린 실행은 남기지 않는다"
    assert du.run_fill("beta", "2026-10-02", "2026-10-06", now=later, request_id=RID) == 0
    assert out.read_text() == "--from 2026-10-02 --to 2026-10-06"
    assert json.loads((t / "state/daily_update_fill.json").read_text(encoding="utf-8"))["steps"]["beta"]["days"] == ["2026-10-07"]
    b = _last(t)["steps"][1]
    assert b["rc"] == 0 and "빠진 날 채움 2026-10-02 ~ 2026-10-06" in b["note"]
    assert (b["followup"], b["fill_from"], b["fill_to"], b["fill_days"]) == ("fill", "2026-10-07", "2026-10-07", 1)
    h = json.loads(hist.read_text(encoding="utf-8").splitlines()[-1])
    assert (h["only"], h["fill"], h["request_id"], h["rc"], h["trigger"]) == (
        "beta", {"from": "2026-10-02", "to": "2026-10-06"}, RID, 0, "manual")
    assert h["log"].endswith("-fill-beta.log") and (t / h["log"]).exists()
    assert _last(t)["reruns"][-1]["fill"] == {"from": "2026-10-02", "to": "2026-10-06"}
    assert not (t / "state/daily_update.lock").exists()


def test_cli_fill_needs_both_dates_and_nothing_else(monkeypatch):
    """`run --fill <단계> --from --to` — 날짜 둘이 다 있어야 하고 `--only` · `--manual` · `--upload` 와 함께 쓰지 않는다 · 날짜만
    주고 `--fill` 이 없으면 2. 러너 함수는 부르면 실패하게 바꿔 끼운다(검사가 깨져도 진짜 실행을 하지 않게)."""
    for fn in ("run_all", "run_one", "run_fill"):
        monkeypatch.setattr(du, fn, lambda *a, _fn=fn, **k: pytest.fail(f"검사를 지나 {_fn} 을 불렀다"))
    for argv in (["run", "--fill", "signals"], ["run", "--fill", "signals", "--from", "2026-10-02"],
                 ["run", "--fill", "signals", "--only", "news", "--from", "2026-10-02", "--to", "2026-10-06"],
                 ["run", "--fill", "signals", "--manual", "--from", "2026-10-02", "--to", "2026-10-06"],
                 ["run", "--fill", "signals", "--upload", "--from", "2026-10-02", "--to", "2026-10-06"],
                 ["run", "--from", "2026-10-02", "--to", "2026-10-06"],
                 ["run", "--fill", "signals", "--from", "2026-10-02", "--to", "2026-10-06", "--request", "x"]):
        assert du.main(argv) == 2, argv
    calls = []
    monkeypatch.setattr(du, "run_fill", lambda name, a, b, **k: calls.append((name, a, b, k.get("request_id"))) or 0)
    assert du.main(["run", "--fill", "signals", "--from", "2026-10-02", "--to", "2026-10-06", "--request", RID]) == 0
    assert calls == [("signals", "2026-10-02", "2026-10-06", RID)]


def test_upload_step_keeps_the_fill_days_and_the_run_goes_on(fake_runner, monkeypatch):
    """올리기 단계를 지나도 회차가 끝까지 돈다(DF-103 · 2026-10-11) — 빠진 날(`load_fill` 의 사전)과 올릴 파케이 목록
    (`_pending_upload` 의 목록)이 같은 이름 `pending` 을 써서, 올리기가 성공한 직후 `pending.get` 이 목록에서 터졌다(10-11 따라잡기
    회차 17:20 「러너 오류: AttributeError: 'list' object has no attribute 'get'」 — 일봉 올리기 · 섹터 법령을 못 돌고 회차가 실패로
    남았다). 가짜 러너의 단계 이름에 upload 가 없어 시험이 그 길을 지나지 않았다 — 이름이 upload 인 단계를 넣어 지나게 한다.
    빠진 날 상태는 올릴 목록으로 덮이지 않는다."""
    t = fake_runner
    steps = [du.Step("alpha", ["-c", "pass"], 1, label="가 단계", group="받기", desc="첫 일"),
             du.Step("upload", ["-c", "pass"], 1, upload=True, label="올리기", group="백업", desc="바뀐 조각을 올린다"),
             du.Step("after", ["-c", "pass"], 1, fatal=False, upload=True, label="뒤 단계", group="백업", desc="올린 뒤 일")]
    monkeypatch.setattr(du, "STEPS", steps)
    monkeypatch.setattr(du, "_pending_upload", lambda: ["price_daily/year=2026/part-00000.parquet"])
    du._write_json_atomic(t / "state/daily_update_fill.json", {"steps": {"signals": {"days": ["2026-10-06"]}}})
    assert du.run_all(upload=True) == 0
    last = json.loads((t / "state/daily_update_last.json").read_text(encoding="utf-8"))
    assert not last.get("stopped") and last["ok"] is True, last.get("stopped")
    assert [(s["name"], s["rc"]) for s in last["steps"]] == [("alpha", 0), ("upload", 0), ("after", 0)]
    fill = json.loads((t / "state/daily_update_fill.json").read_text(encoding="utf-8"))
    assert fill["steps"] == {"signals": {"days": ["2026-10-06"]}}, "빠진 날 상태가 올릴 목록으로 덮이지 않는다"

# ── 자료 안내 숫자 파일(2026-10-11 · 자료 안내 2단계 · 결정 ④ 「숫자는 러너가 회차마다 쓰는 파일」) ──────────────
def _numbers_db(path):
    """표 하나(주식 일봉 두 줄)만 있는 작은 수집 DB — 나머지 표는 없다(「없음」 이 되어야 한다)."""
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE price_daily (bas_dt TEXT, srtn_cd TEXT, PRIMARY KEY (bas_dt, srtn_cd))")
    conn.executemany("INSERT INTO price_daily VALUES (?, ?)", [("20261006", "005930"), ("20261007", "005930")])
    conn.commit()
    conn.close()


def test_table_numbers_use_the_status_rules_and_read_only(tmp_path, monkeypatch):
    """자료 안내 숫자 — 관제와 같은 표 정의(data_status.TABLES) · 셈법(table_states)으로 표마다 줄 수 · 마지막 날을 센다(SSoT ·
    러너에 사본을 두지 않는다) · 없는 표는 「없음」(줄 수 0 이 아니라 None) · 수집 DB 가 없으면 모두 「없음」 · 읽기 전용으로만
    연다(앱이 읽기 전용으로 붙인 WAL DB 의 보조 파일을 지우지 않게 · DF-81) · 쓴 시각은 KST 초까지."""
    from app.services import data_status as ds
    db = tmp_path / "m.sqlite3"
    _numbers_db(db)
    uris = []
    real = du.sqlite3.connect
    monkeypatch.setattr(du.sqlite3, "connect", lambda database, *a, **k: uris.append(database) or real(database, *a, **k))
    at = datetime.datetime(2026, 10, 11, 16, 58, tzinfo=du.KST)
    out = du.table_numbers(db_path=db, now=at)
    assert uris and all("mode=ro" in u for u in uris), uris
    assert out["schema"] == du.GUIDE_STATS_SCHEMA == 1 and out["written_at"] == "2026-10-11T16:58:00+09:00"
    assert out["seconds"] >= 0 and out["db"] is True
    assert [t["key"] for t in out["tables"]] == [k for k, *_ in ds.TABLES]
    row = {t["key"]: t for t in out["tables"]}
    assert row["price_daily"] == {"key": "price_daily", "rows": 2, "last_date": "2026-10-07", "missing": False}
    assert row["etf_daily"] == {"key": "etf_daily", "rows": None, "last_date": None, "missing": True}
    none = du.table_numbers(db_path=tmp_path / "없음.sqlite3", now=at)
    assert none["db"] is False and all(t["missing"] and t["rows"] is None for t in none["tables"])
    assert len(none["tables"]) == len(ds.TABLES)
    # 관제 밖 자료 여덟(자료 안내 3단계 · 2026-10-15) — 관제 모듈의 정의 한 곳(EXTRA_KEYS · extra_counts)으로 · DB 옆 상태 폴더만 본다
    assert [x["key"] for x in out["extras"]] == list(ds.EXTRA_KEYS)
    ex = {x["key"]: x for x in out["extras"]}
    terms = len(json.loads(ds.GLOSSARY_FILE.read_text(encoding="utf-8"))["terms"])
    assert (ex["glossary"]["rows"], ex["glossary"]["missing"]) == (terms, False)
    assert ex["kb_law"]["missing"] and ex["kb_law"]["rows"] is None, "없는 DB 는 「없음」(0 이 아니다)"
    assert ex["run_history"]["missing"], "이 DB 옆 상태 폴더(임시)만 본다 — 진짜 상태 폴더의 이력을 읽지 않는다"
    assert [x["key"] for x in none["extras"]] == list(ds.EXTRA_KEYS)


def test_run_writes_guide_numbers_at_the_end_and_after_one_step(fake_runner, monkeypatch):
    """회차 끝 · 한 단계 다시 뒤에 자료 안내 숫자 파일을 쓴다(곁 파일 · 단계 수는 그대로 · 회차 시작에는 쓰지 않는다) — 회차 기록보다
    뒤에 써서 앱이 「수집 뒤 못 씀」 을 가를 수 있게 · 누가 썼나(by) 를 남긴다. 못 세면 🟡 한 줄만 남기고 회차 결과 · 종료코드는
    그대로 · 옛 파일을 지우지 않는다(말없이 사라지지 않게)."""
    t = fake_runner
    db = t / "real.sqlite3"
    _numbers_db(db)
    monkeypatch.setattr(du.config, "DB_PATH", db)
    path = t / "state" / "data_guide_stats.json"
    first = du.STEPS[0]
    du.STEPS[0] = du.Step(first.name, ["-c", f"import os,sys; sys.exit(9 if os.path.exists(r'{path}') else 0)"], 1,
                          label=first.label, group=first.group, desc=first.desc)
    assert du.run_all() == 3, "첫 단계가 9 로 끝나면 회차 시작에 숫자 파일을 쓴 것이다"
    du.STEPS[0] = first
    last = json.loads((t / "state/daily_update_last.json").read_text(encoding="utf-8"))
    nums = json.loads(path.read_text(encoding="utf-8"))
    assert nums["by"] == "run" and nums["written_at"] >= last["finished_at"]
    assert {x["key"]: x["rows"] for x in nums["tables"]}["price_daily"] == 2
    assert [s.name for s in du.STEPS] == ["alpha", "beta"], "단계로 더하지 않는다(곁 파일)"
    # 한 단계 다시 — 다시 쓴다(누가 썼나 = only)
    assert du.run_one("beta", now=datetime.datetime(2026, 10, 8, 16, 0, tzinfo=du.KST)) == 3
    assert json.loads(path.read_text(encoding="utf-8"))["by"] == "only"
    # 못 센다 — 🟡 한 줄 · 종료코드 그대로 · 옛 파일 그대로
    before = path.read_bytes()

    def boom(**_k):
        raise sqlite3.DatabaseError("file is not a database")

    monkeypatch.setattr(du, "table_numbers", boom)
    assert du.run_all() == 3
    assert path.read_bytes() == before, "못 센 회차는 옛 파일을 지우거나 덮지 않는다"
    log = sorted((t / "logs").glob("daily_update-*.log"))[-1].read_text(encoding="utf-8")
    assert "🟡 기록 파일을 쓰지 못했다 — data_guide_stats.json: DatabaseError: file is not a database" in log


def test_steps_write_also_writes_guide_numbers(fake_runner, monkeypatch, capsys):
    """`steps --write` 는 단계 목록 · 이 PC 용량 · 자료 안내 숫자를 함께 지금 쓴다(합친 뒤 c 스크립트가 회차를 기다리지 않고 화면을
    채우게) · 누가 썼나 = steps · 하나라도 못 쓰면 1 과 까닭."""
    t = fake_runner
    db = t / "real.sqlite3"
    _numbers_db(db)
    monkeypatch.setattr(du.config, "DB_PATH", db)
    assert du.main(["steps", "--write"]) == 0
    out = capsys.readouterr().out
    assert "data_guide_stats.json" in out
    nums = json.loads((t / "state" / "data_guide_stats.json").read_text(encoding="utf-8"))
    assert nums["by"] == "steps" and (t / "state" / "daily_update_steps.json").exists() and (t / "state" / "pc_disk.json").exists()
    monkeypatch.setattr(du, "table_numbers", lambda **_k: (_ for _ in ()).throw(OSError("디스크 없음")))
    assert du.main(["steps", "--write"]) == 1
    assert "🟡 data_guide_stats.json: OSError: 디스크 없음" in capsys.readouterr().out


# ── 8. 따라잡기 회차 · 시세 경고 · 회차 기록 사본(2026-10-15 · DF-99 · DF-92 · #124 약속 ②) ───────────────
def _marker_step(path, name="alpha", **kw):
    """돌면 파일 하나를 만드는 가짜 단계 — 「돌았나」 를 본다."""
    return du.Step(name, ["-c", f"open({str(path)!r}, 'w').write('x')"], 1, label=kw.pop("label", "가 단계"),
                   group=kw.pop("group", "받기"), desc=kw.pop("desc", "첫 일"), **kw)


def test_catch_up_run_right_before_1230_leaves_one_line_and_does_nothing(fake_runner, monkeypatch):
    """DF-99 (가) · 11:00 ~ 12:28 에 시작한 정기 회차(꺼져 있던 PC 의 따라잡기 — 작업 스케줄러 StartWhenAvailable)는 잠금 · 로그 ·
    회차 기록을 만들지 않고 이력에 「건너뜀」 한 줄(까닭 before_schedule)만 남기고 0. 12:30 회차가 같은 일을 한다(시세 14일 ·
    공시 3일 · 기사 30시간 창) — 돌면 12:30 회차가 잠금에 걸려 통째로 건너뛰고(IgnoreNew) 그날 「12:30 뒤 시작한 회차」 가 없어
    리밸런싱 하루 점검이 하루 내내 기다린다. 12:28 부터는 돈다."""
    t = fake_runner
    marker = t / "ran.txt"
    du.STEPS[0] = _marker_step(marker)
    hist, lock = t / "state/daily_update_history.jsonl", t / "state/daily_update.lock"
    monkeypatch.setattr(du, "now_kst", lambda: _at(11, 10))
    assert du.run_all(upload=True) == 0
    h = json.loads(hist.read_text(encoding="utf-8").splitlines()[-1])
    assert (h["reason"], h["trigger"], h["started_at"]) == ("before_schedule", "schedule", _at(11, 10).isoformat())
    assert "12:30" in h["skipped"]
    assert not marker.exists() and not lock.exists() and not (t / "logs").exists()
    assert not (t / "state/daily_update_last.json").exists(), "마지막 회차 기록은 그대로 — 건너뜀은 이력 한 줄"
    monkeypatch.setattr(du, "now_kst", lambda: _at(12, 28))
    assert du.run_all() == 3 and marker.exists(), "12:28 부터는 돈다(진짜 12:30 회차가 몇 초 일찍 깨어나도 건너뛰지 않게)"


@pytest.mark.parametrize("hm, blocked", [((10, 59), False), ((11, 0), True), ((12, 27), True), ((12, 28), False),
                                         ((12, 30), False), ((13, 0), False), ((15, 0), False)])
def test_catch_up_window_edges(hm, blocked):
    """DF-99 (가) · 막는 때는 [12:30 − 90분, 12:30 − 2분) — 앞쪽은 수동 전체 수집과 같은 값(`MANUAL_FULL_GUARD_BEFORE_MIN` · 같은 시각
    셈 · SSoT) · 뒤쪽 2분은 진짜 12:30 회차를 잘못 건너뛰지 않을 여유(잘못 건너뛰면 그날 수집을 통째로 잃고, 잘못 돌면 지금과 같다)."""
    why = du.catch_up_blocked(_at(*hm))
    assert (why is not None) == blocked, (hm, why)
    if why:
        assert "12:30" in why and "따라잡기" in why


def test_install_refuses_a_time_the_catch_up_rule_would_always_skip(monkeypatch, capsys):
    """DF-99 (가) · 그 막는 때 안의 시각으로 등록하면 정기 회차가 날마다 건너뛴다 — 등록하지 않고 2(작업 스케줄러를 부르지 않는다) ·
    형식이 틀린 시각도 2 · 12:30 · 저녁 시각은 그대로 받는다."""
    monkeypatch.setattr(du, "_schtasks", lambda *a: pytest.fail("등록하면 안 된다"))
    for hm in ("11:00", "11:30", "12:27", "25:00", "1230"):
        assert du.install(hm) == 2, hm
    assert "12:30" in capsys.readouterr().out
    assert du.install_time_error("12:30") is None and du.install_time_error("18:30") is None
    assert du.install_time_error("12:28") is None and du.install_time_error("10:59") is None


def test_warn_code_of_a_stopping_step_is_a_warning_and_the_run_goes_on(fake_runner):
    """DF-92 · 멈추는 단계(시세)라도 단계 정의의 `warn_codes`(69 — 출처가 다 주지 못함 · 받은 날은 저장)는 경고 — 뒤 단계가 돌고
    회차는 「일부 실패」(ok 거짓 · stopped 없음) · 단계 줄 · 이력 줄에 `warn` 을 적는다(앱은 종료코드를 다시 해석하지 않는다).
    다른 종료코드(1 — 예외)는 지금처럼 멈춘다 · 한 단계 다시도 같은 규칙."""
    t = fake_runner
    du.STEPS[0] = du.Step("alpha", ["-c", "import sys; sys.exit(69)"], 1, warn_codes=(69,), label="가 단계", group="받기", desc="첫 일")
    du.STEPS[1] = du.Step("beta", ["-c", "pass"], 1, fatal=False, label="나 단계", group="계산", desc="둘째 일")
    assert du.run_all() == 69
    last = _last(t)
    a, b = last["steps"]
    assert (a["rc"], a.get("warn"), b["rc"], last["stopped"], last["ok"]) == (69, True, 0, None, False)
    h = json.loads((t / "state/daily_update_history.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert h["steps"][0].get("warn") is True and "warn" not in h["steps"][1]
    du.STEPS[0] = du.Step("alpha", ["-c", "import sys; sys.exit(1)"], 1, warn_codes=(69,), label="가 단계", group="받기", desc="첫 일")
    assert du.run_all() == 1
    last = _last(t)
    assert last["stopped"] == "alpha 종료코드 1" and last["steps"][1]["reason"] == "upstream_failed"
    assert "warn" not in last["steps"][0]
    du.STEPS[0] = du.Step("alpha", ["-c", "import sys; sys.exit(69)"], 1, warn_codes=(69,), label="가 단계", group="받기", desc="첫 일")
    assert du.run_one("alpha", now=_at(15, 10)) == 69
    assert _last(t)["steps"][0].get("warn") is True


def test_price_step_warns_on_69_and_still_stops_on_a_crash():
    """DF-92 · 시세 단계는 멈추는 단계 그대로(예외 · 시간 넘김은 뒤를 막는다)이고 69 만 경고다 · 러너의 69 는 시세 명령의 값과 같다."""
    from collector import backfill
    price = next(s for s in du.STEPS if s.name == "price")
    assert price.fatal is True and price.warn_codes == (du.EX_UNAVAILABLE,) == (backfill.EX_UNAVAILABLE,)
    # 경고 종료코드를 둔 단계는 시세(69 — 다 받지 못함)와 모의 일지(10 — 판 바뀜 · 2026-10-24 · TC-PJ-13) 둘이다
    assert [s.name for s in du.STEPS if s.warn_codes] == ["price", "journal"]
    assert next(s for s in du.STEPS if s.name == "journal").warn_codes == (10,)


def _record_steps(t, rec_path, env_name):
    """올리기 앞 · 올리기 · 뒤 단계 — 올리기 자식만 회차 시작 시각을 받고, 그 시각이 사본의 회차와 같아야 0."""
    check = (f"import json,os,sys; r=json.load(open({str(rec_path)!r},encoding='utf-8')); "
             f"ok = os.environ.get({env_name!r}) == r['run']['started_at'] and "
             "[s['name'] for s in r['run']['steps']] == ['alpha','beta','upload']; sys.exit(0 if ok else 9)")
    no_env = f"import os,sys; sys.exit(9 if os.environ.get({env_name!r}) else 0)"
    return [du.Step("alpha", ["-c", no_env], 1, label="가 단계", group="받기", desc="첫 일"),
            du.Step("beta", ["-c", "import sys; sys.exit(3)"], 1, fatal=False, label="나 단계", group="계산", desc="둘째 일"),
            du.Step("upload", ["-c", check], 1, upload=True, sharing=True, label="올리기", group="백업", desc="올린다"),
            du.Step("after", ["-c", no_env], 1, fatal=False, upload=True, label="뒤 단계", group="백업", desc="뒤 일")]


def test_upload_step_gets_a_record_of_this_run(fake_runner, monkeypatch):
    """#124 약속 ② · 올리기 단계 직전에 그 회차가 그때까지 한 일을 HF 내보내기 폴더(`meta/run_record.json` — `meta/*` 라 같은 커밋)에
    쓰고, 올리기 자식에게만 그 회차의 시작 시각을 넘긴다(`QURIOUS_RUN_RECORD` — 공유 스위치와 같은 꼴 · 다른 단계에는 없다).
    사본은 마지막 회차 기록과 같은 칸 + finished_at 빈칸 · 기록한 시각 · 남은 단계, 그리고 앞 회차들의 이력 줄(31일)을 싣는다 ·
    요청 번호는 빼고 글 칸의 이 PC 경로는 파일 이름만."""
    t = fake_runner
    rec_path = t / "hf_export" / "meta" / "run_record.json"
    monkeypatch.setattr(hf_dataset, "RUN_RECORD_PATH", rec_path)
    monkeypatch.setattr(du, "_pending_upload", lambda: ["price_daily/year=2026/x.parquet"])
    du.STEPS[:] = _record_steps(t, rec_path, hf_dataset.ENV_RUN_RECORD)
    old = {"started_at": "2026-10-11T12:30:01+09:00", "finished_at": "2026-10-11T12:40:00+09:00", "ok": False,
           "upload": True, "stopped": "러너 오류 FileNotFoundError: " + "C:" + "\\Users\\someone\\data\\x.json",
           "log": "data/collector/logs/daily_update-20261011-123001.log", "trigger": "manual", "request_id": RID, "rc": 1,
           "steps": [{"name": "alpha", "rc": 1, "seconds": 1.0, "note": "", "error": "x"}]}
    ancient = dict(old, started_at="2026-08-01T12:30:01+09:00", stopped=None)
    (t / "state/daily_update_history.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in (ancient, old)) + "\n", encoding="utf-8")
    assert du.run_all(upload=True, manual=True, request_id=RID) == 3          # beta 의 3(멈추지 않는 실패)
    last = _last(t)
    assert [(s["name"], s["rc"]) for s in last["steps"]] == [("alpha", 0), ("beta", 3), ("upload", 0), ("after", 0)], \
        "올리기 자식만 회차 시각을 받고 · 그 시각이 사본의 회차와 같다(9 면 어긋남)"
    r = json.loads(rec_path.read_text(encoding="utf-8"))
    run = r["run"]
    assert (r["schema"], run["finished_at"], run["started_at"], run["trigger"]) == (1, None, last["started_at"], "manual")
    assert run["recorded_at"] and run["pending_steps"] == ["upload", "after"]
    assert [s["name"] for s in run["steps"]] == ["alpha", "beta", "upload"] and run["steps"][2]["rc"] is None
    assert "request_id" not in run, "요청 번호(앱 DB 요청자와 잇는 열쇠)는 뺀다"
    assert [h["started_at"] for h in r["history"]] == ["2026-10-11T12:30:01+09:00"], "31일 안 줄만"
    assert "request_id" not in r["history"][0] and r["history"][0]["stopped"].endswith("x.json")
    assert "someone" not in json.dumps(r, ensure_ascii=False), "글 칸의 이 PC 경로는 파일 이름만"


def test_no_record_when_nothing_is_uploaded_and_a_failed_write_is_said(fake_runner, monkeypatch):
    """#124 약속 ② · 올릴 것이 없어 올리기를 건너뛴 회차는 사본을 쓰지 않는다 · 사본을 못 쓰면 올리기는 그대로 돌고(백업이 먼저)
    그 단계 줄 메모와 로그에 「회차 기록 사본을 쓰지 못함」 을 남긴다(올리기 쪽은 시각을 받지 않아 옛 사본을 지운다)."""
    t = fake_runner
    rec_path = t / "hf_export" / "meta" / "run_record.json"
    monkeypatch.setattr(hf_dataset, "RUN_RECORD_PATH", rec_path)
    du.STEPS[:] = _record_steps(t, rec_path, hf_dataset.ENV_RUN_RECORD)
    monkeypatch.setattr(du, "_pending_upload", lambda: [])
    du.run_all(upload=True)
    assert not rec_path.exists() and _last(t)["steps"][2]["reason"] == "nothing_to_upload"
    monkeypatch.setattr(du, "_pending_upload", lambda: ["x"])
    monkeypatch.setattr(hf_dataset, "write_run_record", lambda rec: (_ for _ in ()).throw(OSError("디스크 가득")))
    du.STEPS[2] = du.Step("upload", ["-c", f"import os,sys; sys.exit(9 if os.environ.get({hf_dataset.ENV_RUN_RECORD!r}) else 0)"],
                          1, upload=True, sharing=True, label="올리기", group="백업", desc="올린다")
    du.run_all(upload=True)
    up = _last(t)["steps"][2]
    assert up["rc"] == 0 and "회차 기록 사본을 쓰지 못함" in up["note"]
    log = sorted((t / "logs").glob("daily_update-*.log"))[-1].read_text(encoding="utf-8")
    assert "🟡 회차 기록 사본을 쓰지 못했다 — OSError: 디스크 가득" in log


def test_runner_error_on_a_scheduled_run_still_leaves_a_history_line(fake_runner, monkeypatch):
    """러너 오류로 끝난 정기 회차도 이력에 한 줄을 남긴다(자료 안내 3단계 · 2026-10-15) — 화면 요청 회차(`request_id`)일 때만 남겨서
    DF-103 회차(10-11 17:20 따라잡기)가 이력에 없었다(관제 · 수집 일정의 지난 회차 목록에서 빠짐). 이력 줄 = 회차 기록과 같은 칸 ·
    종료코드 1 · 단계별 결과 · 요청 회차여도 한 줄만. 회차 끝처럼 자료 안내 숫자 파일도 다시 쓴다(오류 앞 단계가 자료를 바꿨을 수
    있다 · 못 쓰면 지금처럼 🟡)."""
    t = fake_runner
    db = t / "real.sqlite3"
    _numbers_db(db)
    monkeypatch.setattr(du.config, "DB_PATH", db)

    def boom(run, steps):
        raise RuntimeError("일부러 낸 러너 결함")

    monkeypatch.setattr(du, "prepare_app_db", boom)
    assert du.run_all() == 1
    last = _last(t)
    assert (last["ok"], last["stopped"]) == (False, "러너 오류 RuntimeError: 일부러 낸 러너 결함")
    hist = [json.loads(x) for x in (t / "state/daily_update_history.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(hist) == 1 and (hist[0]["stopped"], hist[0]["rc"], hist[0]["trigger"]) == (last["stopped"], 1, "schedule")
    assert "request_id" not in hist[0] and hist[0]["started_at"] == last["started_at"]
    nums = json.loads((t / "state/data_guide_stats.json").read_text(encoding="utf-8"))
    assert nums["by"] == "run" and {x["key"]: x for x in nums["tables"]}["price_daily"]["rows"] == 2
    assert {x["key"]: x for x in nums["extras"]}["run_history"]["rows"] == 1, "숫자 파일은 이력 줄 뒤에 쓴다"
    log = sorted((t / "logs").glob("daily_update-*.log"))[-1].read_text(encoding="utf-8")
    assert "🔴 러너 오류: RuntimeError: 일부러 낸 러너 결함" in log
    # 요청 회차 — 한 줄만(두 번 쓰지 않는다)
    assert du.run_all(manual=True, request_id=RID) == 1
    hist = [json.loads(x) for x in (t / "state/daily_update_history.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(hist) == 2 and hist[1]["request_id"] == RID and hist[1]["trigger"] == "manual"


def test_app_beat_schedules_no_collector_task():
    """TC-DU · 수집 예약은 이 PC 러너 하나다(D106) — 앱 Celery Beat 예약 목록에 `collector.*` 태스크가 없다.

    예약기가 둘이면 같은 수집 DB 를 서로 다른 잠금으로 쓰게 되고, 앱 컨테이너에는 collector 패키지가
    없어 저녁 예약(18 · 19 · 20시)이 import 에서 실패했다. 태스크 정의는 손으로 부를 수 있게 남긴다.
    """
    from app.celery_app import celery_app
    from app.tasks import collector_tasks

    sched = celery_app.conf.beat_schedule
    assert "quant-auto-trade-cycle" in sched, "예약 목록을 제대로 읽었는지(다른 예약은 그대로)"
    found = sorted(k for k, v in sched.items() if str(v.get("task", "")).startswith("collector."))
    assert found == [], f"앱 Beat 에 수집 예약이 있다: {found}"
    assert collector_tasks.portal_recent_task.name == "collector.portal_recent", "태스크 정의는 남긴다"
