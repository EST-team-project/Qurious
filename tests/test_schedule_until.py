"""TC-SU · 예약 끝 날짜(`install --until` · 목표 기능 ① 할 일 ①-28 · 2026-10-26).

문제 — 작업 스케줄러 등록은 `schtasks /Create /XML ... /F` 로 통째로 바꾼다. 손으로 넣은 끝 날짜(`EndBoundary` 11-12 23:59:59)는
`install` 을 다시 돌리면 사라진다(여러 PC 동시 켜짐 조사 Q3 ⑴). 지키는 것:
1. 끝 날짜를 안 적으면 XML 은 예전과 **글자까지 같다**(끝 날짜 줄만 없다) · 적으면 시작 날짜 바로 뒤에 `EndBoundary` 한 줄만 더해진다
2. 예약 셋(러너 · 작업자 · 복구 시험)이 같은 규칙을 쓴다
3. `--until` 을 안 쓰고 다시 설치해도 **지금 등록된 끝 날짜를 잇는다** · `none` 이면 지운다 · 이미 지난 옛 날짜는 잇지 않는다
4. 잘못된 날짜(꼴 · 과거)는 등록하지 않고 2(작업 스케줄러를 부르지 않는다)
"""
from __future__ import annotations

import datetime
import re
import subprocess
from pathlib import Path

import pytest

from scripts import collect_worker as cw
from scripts import daily_update as du
from scripts import weekly_rehearsal as wr

TODAY = datetime.date(2026, 10, 26)
END = datetime.date(2026, 11, 12)
END_LINE = "<EndBoundary>2026-11-12T23:59:59</EndBoundary>"

# 세 예약의 XML 을 같은 모양으로 만든다(날짜 인자만 다르게)
MAKERS = {
    "daily": lambda until=None: du.task_xml("12:30", True, python_w="pythonw", root=Path("C:/q"), today=TODAY, until=until),
    "worker": lambda until=None: cw.task_xml(True, python_w="pythonw", root=Path("C:/q"), today=TODAY, until=until),
    "weekly": lambda until=None: wr.task_xml(python_w="pythonw", root=Path("C:/q"), today=TODAY, until=until),
}


@pytest.mark.parametrize("name", MAKERS)
def test_xml_without_until_is_unchanged_and_with_until_adds_one_line(name):
    """TC-SU-01 · 끝 날짜를 안 주면 끝 날짜 줄이 없고, 주면 그 한 줄만 시작 날짜 바로 뒤에 더해진다(다른 설정은 그대로)."""
    plain, bounded = MAKERS[name](), MAKERS[name](END)
    assert "EndBoundary" not in plain
    assert bounded.count("<EndBoundary>") == 1 and END_LINE in bounded
    assert bounded.replace(f"      {END_LINE}\n", "") == plain, "끝 날짜 줄 말고 다른 곳이 바뀌었다"
    # 작업 스케줄러 XML 차례 — StartBoundary 다음 EndBoundary 다음 Enabled(반복은 그 앞 · 일정 종류는 그 뒤)
    assert bounded.index("<StartBoundary>") < bounded.index("<EndBoundary>") < bounded.index("<Enabled>true</Enabled>")
    for keep in ("<StartWhenAvailable>true</StartWhenAvailable>", "<WakeToRun>false</WakeToRun>", "<MultipleInstancesPolicy>IgnoreNew"):
        assert keep in bounded


@pytest.mark.parametrize("text,ok", [
    (None, True), ("none", True), ("NONE", True), ("2026-11-12", True), ("2026-10-26", True),
    ("2026-10-25", False), ("26-11-12", False), ("20261112", False), ("2026-13-01", False), ("", False), ("내일", False),
])
def test_until_error(text, ok):
    """TC-SU-02 · 끝 날짜 검사 — YYYY-MM-DD(오늘 이후) 또는 none · 안 적음. 꼴이 틀리거나 이미 지난 날짜는 까닭을 돌려준다."""
    assert (du.until_error(text, today=TODAY) is None) is ok


def _fake_schtasks(registered: str | None):
    """schtasks 가짜 — /Query /XML 은 `registered` 를 돌려주고(None 이면 등록 없음), /Create 의 XML 파일은 읽어 둔다."""
    seen: dict = {"create": None, "calls": []}

    def run(*args: str):
        seen["calls"].append(args)
        if args[0] == "/Query":
            return subprocess.CompletedProcess(args, 0 if registered is not None else 1, registered or "", "" if registered is not None else "없음")
        if args[0] == "/Create":
            seen["create"] = Path(args[args.index("/XML") + 1]).read_text(encoding="utf-16")
            return subprocess.CompletedProcess(args, 0, "", "")
        raise AssertionError(f"뜻밖의 schtasks 호출: {args}")

    return run, seen


REGISTERED = f"<Task><Triggers><CalendarTrigger><StartBoundary>2026-10-25T12:30:00</StartBoundary>{END_LINE}</CalendarTrigger></Triggers></Task>"


def test_resolve_until_keeps_registered_end_date_unless_told_otherwise(monkeypatch):
    """TC-SU-03 · 안 적으면 지금 등록된 끝 날짜를 잇는다 · 새 날짜는 덮어쓴다 · none 은 지운다 · 지난 옛 날짜는 잇지 않고 알린다 · 등록이 없으면 없음."""
    run, _ = _fake_schtasks(REGISTERED)
    monkeypatch.setattr(du, "_schtasks", run)
    assert du.resolve_until(None, "T", today=TODAY)[0] == END
    assert du.resolve_until("2026-12-31", "T", today=TODAY)[0] == datetime.date(2026, 12, 31)
    assert du.resolve_until("none", "T", today=TODAY)[0] is None
    expired, note = du.resolve_until(None, "T", today=datetime.date(2026, 11, 13))
    assert expired is None and "지났" in note
    monkeypatch.setattr(du, "_schtasks", _fake_schtasks(None)[0])
    assert du.resolve_until(None, "T", today=TODAY) == (None, "")


def _install(name: str, monkeypatch, run, **kw) -> int:
    monkeypatch.setattr(du, "_schtasks", run)
    monkeypatch.setattr(du.os, "name", "nt")
    if name == "daily":
        return du.install("12:30", True, **kw)
    if name == "worker":
        monkeypatch.setattr(cw.os, "name", "nt")
        return cw.install(True, **kw)
    monkeypatch.setattr(wr.os, "name", "nt")
    monkeypatch.setattr(wr, "write_state", lambda **k: None)     # 진짜 상태 파일을 쓰지 않는다
    return wr.install(**kw)


@pytest.mark.parametrize("name", MAKERS)
def test_reinstall_without_until_keeps_the_registered_end_date(name, monkeypatch, capsys):
    """TC-SU-04 · 핵심 — `install` 을 다시 돌려도(--until 없이) 손으로 넣은 11-12 가 사라지지 않는다 · 끝 날짜를 출력으로 알린다."""
    run, seen = _fake_schtasks(REGISTERED)
    assert _install(name, monkeypatch, run) == 0
    assert END_LINE in seen["create"]
    assert "2026-11-12" in capsys.readouterr().out


@pytest.mark.parametrize("name", MAKERS)
def test_install_with_until_sets_it_and_none_clears_it(name, monkeypatch):
    """TC-SU-05 · `--until 날짜` 는 그 날 23:59:59 로 · `--until none` 은 끝 날짜 없이(다시 켜기 때 새로 정한다)."""
    run, seen = _fake_schtasks(REGISTERED)
    assert _install(name, monkeypatch, run, until=datetime.date.today().replace(year=2099).isoformat()) == 0
    assert "<EndBoundary>2099-" in seen["create"] and END_LINE not in seen["create"]
    run, seen = _fake_schtasks(REGISTERED)
    assert _install(name, monkeypatch, run, until="none") == 0
    assert "EndBoundary" not in seen["create"]


@pytest.mark.parametrize("name", MAKERS)
def test_bad_until_registers_nothing(name, monkeypatch, capsys):
    """TC-SU-06 · 꼴이 틀리거나 과거인 끝 날짜는 등록하지 않는다(작업 스케줄러를 부르지 않고 2)."""
    monkeypatch.setattr(du, "_schtasks", lambda *a: pytest.fail("등록하면 안 된다"))
    monkeypatch.setattr(du.os, "name", "nt")
    kw = dict(until="2020-01-01")
    got = {"daily": lambda: du.install("12:30", True, **kw), "worker": lambda: cw.install(True, **kw), "weekly": lambda: wr.install(**kw)}[name]()
    assert got == 2
    assert re.search(r"끝 날짜", capsys.readouterr().out)


def test_cli_accepts_until_for_all_three(monkeypatch):
    """TC-SU-07 · 세 명령줄이 `--until` 을 받아 install 에 넘긴다(말단 연결 — 이름만 틀려도 여기서 깨진다)."""
    got: dict = {}
    monkeypatch.setattr(du, "install", lambda t, upload=True, until=None: got.setdefault("daily", until) or 0)
    monkeypatch.setattr(cw, "install", lambda upload=True, until=None: got.setdefault("worker", until) or 0)
    monkeypatch.setattr(wr, "install", lambda until=None: got.setdefault("weekly", until) or 0)
    du.main(["install", "--until", "2026-11-12"])
    cw.main(["install", "--until", "2026-11-12"])
    wr.main(["install", "--until", "2026-11-12"])
    assert got == {"daily": "2026-11-12", "worker": "2026-11-12", "weekly": "2026-11-12"}
