"""TC-WR · 주 1회 복구 시험(2차-3 · 2026-10-18) — 예약 · 막는 때 · 잠금 · 차례 · 기록, 그리고 「마지막 성공 리허설 n일 전」.

지키는 것
1. 예약은 매주 일요일 15:00 · 꺼져 있었으면 켜진 뒤(StartWhenAvailable) · 네트워크 없이도 · 한 번에 하나(IgnoreNew)
2. 12:30 회차 앞뒤(회차 − 한 바퀴 한도 ~ 회차 + 60분)에는 시작하지 않고 75 · 다른 실행이 잠금을 쥐면 75 — 둘 다 바퀴 기록에 까닭
3. 세 단계를 차례대로(깊은 대조 → 복원 리허설 → 판정 기록) · 앞이 실패해도 뒤는 돈다 · 끝에 잠금을 놓고 WAL 보조 파일을 다시 남긴다
4. 예약 칸은 등록(install)만 쓴다 — 손으로 돈 바퀴가 「예약 있음」 으로 보이지 않게
5. 도구는 마지막 **성공** 리허설을 따로 남기고 판정 기록의 rehearsal 칸에 싣는다 · 그 기록이 없던 때는 last_restore 가 성공일 때만
6. 앱은 그 칸으로만 센다 — 모름 · 없음 · 최근 · 오래됨 · 실패 · 두 곳에 적힌 값(날 수 · 파일 이름 · 명령)이 같다
"""
from __future__ import annotations

import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services import backup_status as bs
from app.services import data_status as ds
from scripts import daily_update as du
from scripts import hf_dataset
from scripts import weekly_rehearsal as wr

KST = timezone(timedelta(hours=9))
SUN = datetime(2026, 10, 18, 15, 0, tzinfo=KST)      # 일요일 예약 시각
NS = "{http://schemas.microsoft.com/windows/2004/02/mit/task}"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
  """상태 · 잠금 · 로그를 임시 폴더로 — 시험이 진짜 상태 폴더 · 러너 잠금을 건드리지 않게. WAL 다시 걸기는 센다."""
  monkeypatch.setattr(wr, "STATE_PATH", tmp_path / "state" / "weekly_rehearsal.json")
  monkeypatch.setattr(wr, "LOG_DIR", tmp_path / "logs")
  monkeypatch.setattr(du, "LOCK_PATH", tmp_path / "state" / "daily_update.lock")
  rearm = []
  monkeypatch.setattr(du, "rearm_wal", lambda *a, **k: rearm.append(1) or True)
  return {"tmp": tmp_path, "rearm": rearm}


def _state() -> dict:
  return json.loads(wr.STATE_PATH.read_text(encoding="utf-8"))


def test_예약은_매주_일요일_15시_꺼져_있었으면_켜진_뒤():
  xml = wr.task_xml(python_w="pythonw.exe", root=Path("C:/q"), today=date(2026, 10, 14))   # 수요일
  root = ET.fromstring(re.sub(r"^<\?xml[^>]*\?>\s*", "", xml))                             # UTF-16 선언은 문자열 파서가 받지 않는다
  trig = root.find(f"{NS}Triggers/{NS}CalendarTrigger")
  assert trig.find(f"{NS}StartBoundary").text == "2026-10-18T15:00:00"                     # 다음 일요일
  assert trig.find(f"{NS}ScheduleByWeek/{NS}DaysOfWeek/{NS}Sunday") is not None
  assert trig.find(f"{NS}ScheduleByWeek/{NS}WeeksInterval").text == "1"
  st = root.find(f"{NS}Settings")
  assert st.find(f"{NS}StartWhenAvailable").text == "true"
  assert st.find(f"{NS}RunOnlyIfNetworkAvailable").text == "false"
  assert st.find(f"{NS}MultipleInstancesPolicy").text == "IgnoreNew"
  assert root.find(f"{NS}Actions/{NS}Exec/{NS}Arguments").text.endswith('weekly_rehearsal.py" run')
  # 일요일 당일에 등록하면 그날 15:00 부터
  assert "2026-10-18T15:00:00" in wr.task_xml(python_w="p", root=Path("C:/q"), today=date(2026, 10, 18))


@pytest.mark.parametrize("hm, blocked", [((11, 29), False), ((11, 30), True), ((12, 30), True), ((13, 30), True), ((13, 31), False)])
def test_12시30분_회차_앞뒤에는_시작하지_않는다(hm, blocked):
  now = SUN.replace(hour=hm[0], minute=hm[1])
  why = wr.blocked(now)
  assert bool(why) is blocked
  if why:
    assert "11:30 ~ 13:30" in why and du.DEFAULT_TIME in why


def test_막는_때_다른_실행이면_75_와_까닭을_남기고_단계를_돌리지_않는다(sandbox):
  def no_child(*a):
    pytest.fail("막힌 바퀴가 단계를 돌렸다")

  assert wr.run(now=SUN.replace(hour=12), child=no_child) == du.EX_TEMPFAIL
  assert _state()["result"] == "skipped" and "회차와 겹친다" in _state()["why"]
  # 다른 실행이 잠금을 쥠(이 프로세스 PID · 방금 시작)
  du.LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
  du.LOCK_PATH.write_text(json.dumps({"pid": os.getpid(), "started_at": du._iso(SUN)}), encoding="utf-8")
  assert wr.run(now=SUN, child=no_child) == du.EX_TEMPFAIL
  assert _state()["result"] == "skipped" and "다른 실행이 돌고 있다" in _state()["why"]
  assert du.LOCK_PATH.exists(), "남의 잠금을 지우면 안 된다"
  assert sandbox["rearm"] == []


def test_세_단계를_차례대로_앞이_실패해도_뒤는_돌고_잠금을_놓는다(sandbox):
  calls = []

  def child(args, log, timeout_s):
    calls.append(list(args))
    assert timeout_s >= 60
    return 1 if args[0] == "verify" else 0

  assert wr.run(now=SUN, child=child) == 1
  assert calls == [["verify", "--deep"], ["restore"], ["status", "--write"]]
  st = _state()
  assert st["result"] == "failed" and st["why"] == "깊은 대조 종료코드 1"
  assert [s["key"] for s in st["steps"]] == ["deep_verify", "restore", "status"] and st["steps"][1]["rc"] == 0
  assert not du.LOCK_PATH.exists(), "끝나면 잠금을 놓는다"
  assert sandbox["rearm"] == [1], "수집 DB 를 읽었으니 WAL 보조 파일을 다시 남긴다"
  assert "schedule" not in st, "손으로 돈 바퀴는 예약 칸을 쓰지 않는다"

  assert wr.run(now=SUN, child=lambda a, l, t: 0) == 0
  assert _state()["result"] == "ok" and _state()["why"] == ""


def test_예약_칸은_등록만_쓰고_바퀴_기록은_남는다(sandbox, monkeypatch):
  import subprocess

  wr.run(now=SUN, child=lambda a, l, t: 0)
  monkeypatch.setattr(du, "_schtasks", lambda *a: subprocess.CompletedProcess(a, 0, "", ""))
  monkeypatch.setattr(wr.os, "name", "nt")
  assert wr.install() == 0
  st = _state()
  assert st["schedule"] == "매주 일요일 15:00" and st["result"] == "ok" and st["steps"]
  assert wr.uninstall() == 0 and _state()["schedule"] is None and _state()["result"] == "ok"


def _logs(tmp: Path, monkeypatch, *, last=None, ok=None, verify=None):
  meta = tmp / "meta"
  for name, path in (("RESTORE_LOG_PATH", meta / "last_restore.json"), ("RESTORE_OK_PATH", tmp / "state" / "hf_restore_last_ok.json"),
                     ("VERIFY_LOG_PATH", meta / "last_verify.json")):
    monkeypatch.setattr(hf_dataset, name, path)
  for path, rec in ((meta / "last_restore.json", last), (tmp / "state" / "hf_restore_last_ok.json", ok), (meta / "last_verify.json", verify)):
    if rec is not None:
      hf_dataset._write_json_atomic(path, rec)


def test_도구는_마지막_성공을_따로_두고_옛_기록은_성공일_때만_쓴다(tmp_path, monkeypatch):
  _logs(tmp_path, monkeypatch, last={"at": "2026-10-08T15:13:43+09:00", "ok": True, "seconds": 495.4, "rehearsal": True})
  rec = hf_dataset.rehearsal_record()
  assert rec["last_ok"]["at"] == "2026-10-08T15:13:43+09:00" and rec["deep_last"] is None     # 이 판 전 리허설 — 옛 기록으로
  _logs(tmp_path, monkeypatch, last={"at": "2026-10-18T15:20:00+09:00", "ok": False})
  assert hf_dataset.rehearsal_record()["last_ok"] is None, "실패한 옛 기록을 성공으로 쓰지 않는다"
  _logs(tmp_path, monkeypatch, ok={"at": "2026-10-11T15:12:00+09:00", "seconds": 480.0, "rows": 9, "rehearsal": True},
        verify={"at": "2026-10-18T15:05:00+09:00", "deep": True, "fails": 0, "checks": 120})
  rec = hf_dataset.rehearsal_record()
  assert rec["last_ok"]["at"] == "2026-10-11T15:12:00+09:00" and rec["last"]["ok"] is False
  assert rec["deep_last"] == {"at": "2026-10-18T15:05:00+09:00", "fails": 0, "checks": 120, "manifest_generated_at": None}


def _snap(last=None, last_ok=None):
  return {"rehearsal": {"last": last, "last_ok": last_ok, "deep_last": None}}


@pytest.mark.parametrize("snap, state, label", [
  (None, "unknown", "리허설 기록을 아직 읽지 못했습니다(다음 회차가 판정 기록을 쓰면 생깁니다)"),
  ({"conditions": []}, "unknown", "리허설 기록을 아직 읽지 못했습니다(다음 회차가 판정 기록을 쓰면 생깁니다)"),  # 옛 도구가 쓴 판정 기록 — 「없음」 이 아니다
  (_snap(), "never", "아직 성공한 복원 리허설이 없습니다"),
  (_snap({"at": "2026-10-18T15:20:00+09:00", "ok": True}, {"at": "2026-10-18T15:20:00+09:00"}), "ok", "마지막 성공 오늘(10-18)"),
  (_snap(None, {"at": "2026-10-15T23:50:00+09:00"}), "ok", "마지막 성공 3일 전(10-15)"),
  (_snap(None, {"at": "2026-10-10T15:00:00+09:00"}), "ok", "마지막 성공 8일 전(10-10)"),
  (_snap(None, {"at": "2026-10-08T15:13:43+09:00"}), "stale", "마지막 성공 10일 전(10-08) · 주 1회보다 오래됨"),
  (_snap({"at": "2026-10-18T15:20:00+09:00", "ok": False}, {"at": "2026-10-11T15:00:00+09:00"}), "failed",
   "마지막 리허설 실패(10-18) · 마지막 성공 7일 전(10-11)"),
])
def test_앱은_판정_기록의_리허설_칸으로만_센다(snap, state, label):
  v = ds.rehearsal_view(snap, None, SUN.replace(hour=18))
  assert v["state"] == state and v["label"] == label
  assert v["state_label"] == ds.REHEARSAL_STATE[state]
  assert (v["command"] is None) is (state == "ok")
  assert v["schedule_label"] == "주간 예약 없음(손으로 돌림)"
  w = ds.rehearsal_view(snap, {"schedule": "매주 일요일 15:00", "result": "ok", "finished_at": "x", "why": ""}, SUN)
  assert w["schedule_label"] == "매주 일요일 15:00 자동"


def test_적재_백업_응답에도_같은_글이_실린다(tmp_path, monkeypatch):
  from app.services import collector_db

  cdir = tmp_path / "collector"
  (cdir / "state").mkdir(parents=True)
  (cdir / "market.sqlite3").write_bytes(b"")
  monkeypatch.setenv(collector_db.ENV_DB_PATH, str(cdir / "market.sqlite3"))
  out = bs.read(SUN)                                                                       # 판정 기록 없음 — 그래도 줄은 「모름」 으로
  assert out["available"] is False and out["rehearsal"]["state"] == "unknown"
  (cdir / "state" / ds.BACKUP_STATUS_FILE).write_text(json.dumps(
    {"schema": 1, "conditions": [], **_snap(None, {"at": "2026-10-15T15:00:00+09:00"})}), encoding="utf-8")
  (cdir / "state" / ds.WEEKLY_REHEARSAL_FILE).write_text(json.dumps({"schedule": "매주 일요일 15:00"}), encoding="utf-8")
  out = bs.read(SUN)
  assert out["rehearsal"]["label"] == "마지막 성공 3일 전(10-15)" and out["rehearsal"]["schedule_label"] == "매주 일요일 15:00 자동"
  # 관제 응답도 같은 함수로 같은 칸을 싣는다(판정 verdict 에는 섞지 않는다)
  src = (ROOT / "app" / "services" / "data_status.py").read_text(encoding="utf-8")
  assert re.search(r'^\s+"rehearsal": rehearsal_view\(_read_json\(sdir / BACKUP_STATUS_FILE\)', src, re.M)


def test_두_곳에_적힌_값이_같다():
  assert wr.STALE_AFTER_DAYS == ds.REHEARSAL_STALE_DAYS
  assert wr.STATE_PATH.name == ds.WEEKLY_REHEARSAL_FILE
  assert hf_dataset.STATUS_SNAPSHOT_PATH.name == ds.BACKUP_STATUS_FILE == bs.STATUS_FILE
  assert ds.REHEARSAL_COMMAND == bs.COMMANDS["restore"]
  assert wr.TIMEOUT_MIN * 60 >= 495 * 2, "한 바퀴 한도가 10-08 리허설(495초)의 두 배는 된다"
