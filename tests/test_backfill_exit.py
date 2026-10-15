"""시세 수집 종료코드 시험 (TC-BF) — `python -m collector.backfill recent` 가 결과를 종료코드로 알린다(DF-92 · 2026-10-15).

고치기 전에는 받다가 멈춰도(포털 하루 한도 소진 · 하루치가 나뉘어 옴) · 실패한 날이 있어도 늘 0 이었다. 일일 러너에는
「✅ 시세」 로 보였고, 관제도 그날은 「정상」 이라(DF-91) 놓친 날이 다음 날 0시에야 「늦음」 으로 보였다.

지키는 것 —
1. 빈 날(아직 안 올라옴 · 휴장)만이면 0 — 12:30 회차의 전 거래일은 출처가 약속(다음 영업일 13:00)보다 일찍 주지 않으면 이렇다.
2. 실패한 날이 있거나(통신 · 응답 오류) 멈췄으면(한도 소진 · 하루치가 나뉘어 옴) 69(EX_UNAVAILABLE) — 받은 날은 저장했고
   실패한 날은 수집 기록에 「error」 로 남아 다음 회차가 그날만 다시 받는다.
3. 69 는 러너 · PC 작업자가 쓰는 종료코드(2 · 3 · 75 · 78 · 124)와 겹치지 않는다 — 75 를 쓰면 회차 종료코드가 75 가 되어 작업자가
   화면 수집 요청을 다시 대기로 돌린다.
4. 멈춘 까닭은 마지막 줄에 한 번 — 러너가 실패한 단계의 까닭 한 줄로 잡는다(DF-101 · `failure_line`).

네트워크 · 실제 수집 DB 를 쓰지 않는다 — DB 는 임시 파일, 포털 받기는 가짜.
"""
from __future__ import annotations

import functools
from datetime import date

import pytest

from collector import backfill, config, db
from collector.ratelimit import BudgetExhausted
from collector.sources import portal

DAYS = (date(2026, 10, 5), date(2026, 10, 9))        # 월 ~ 금 — 평일 다섯


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """임시 수집 DB — 이 PC 의 진짜 수집 DB 를 열지 않는다(`db.connect()` 의 기본 경로를 임시 파일로)."""
    path = tmp_path / "market.sqlite3"
    monkeypatch.setattr(config, "DB_PATH", path)
    monkeypatch.setattr(config, "PORTAL_SLEEP", 0.0)
    db.connect(path).close()
    return path


def fake_fetch(monkeypatch, plan):
    """평일마다 차례로 결과를 낸다 — done · empty · error · budget(한도 소진) · split(하루치가 나뉘어 옴)."""
    it = iter(plan)
    seen = []

    def fetch(conn, limiter, bas_dt, *, session=None):
        what = next(it)
        seen.append(bas_dt)
        if what == "budget":
            raise BudgetExhausted("포털 하루 한도를 다 썼다 — 남은 유량 0")
        if what == "split":
            raise portal.PortalError(f"하루치가 한 번에 안 들어온다: totalCount=9,999 > numOfRows=5,000 ({bas_dt})\n  할 일: …")
        return portal.DayResult(bas_dt, what, 3 if what == "done" else 0, message="HTTP 500" if what == "error" else "")

    monkeypatch.setattr(portal, "fetch_day", fetch)
    return seen


def test_only_empty_days_end_with_zero(temp_db, monkeypatch, capsys):
    """TC-BF-01 · 받은 날 · 빈 날(아직 안 올라옴)만이면 0 — 평소 회차가 이렇다."""
    fake_fetch(monkeypatch, ["done", "done", "done", "done", "empty"])
    t = backfill.run(*DAYS, quiet=True)
    assert (t["done"], t["empty"], t["error"], t["stopped"]) == (4, 1, 0, "")
    assert backfill.exit_code(t) == 0
    assert "다 받지 못했다" not in capsys.readouterr().out


def test_failed_day_ends_with_69_and_is_kept_for_the_next_run(temp_db, monkeypatch, capsys):
    """TC-BF-02 · 실패한 날이 하나라도 있으면 69 — 받은 날은 저장하고, 실패한 날은 수집 기록에 error 로 남아 다음 회차가 그날만 다시 받는다."""
    fake_fetch(monkeypatch, ["done", "error", "done", "empty", "done"])
    t = backfill.run(*DAYS, quiet=True)
    assert (t["done"], t["error"], t["stopped"]) == (3, 1, "")
    assert backfill.exit_code(t) == backfill.EX_UNAVAILABLE == 69
    conn = db.connect(temp_db)
    try:
        st = {r["bas_dt"]: r["status"] for r in conn.execute("SELECT bas_dt, status FROM ingest_day WHERE source='portal'")}
        assert st.get("20261006") == "error"
        assert backfill.pick_targets(conn, ["20261006"], today=date(2026, 10, 9)) == ["20261006"], "다음 회차가 그날을 다시 받는다"
    finally:
        conn.close()
    out = capsys.readouterr().out.strip().splitlines()
    assert out[-1].startswith("🟡 다 받지 못했다") and "실패 1일" in out[-1], "까닭은 마지막 줄 — 러너가 그 줄을 단계 까닭으로 잡는다"


@pytest.mark.parametrize("stop, why", [("budget", "한도"), ("split", "하루치가 한 번에 안 들어온다")])
def test_stopped_run_ends_with_69_and_says_why_once(temp_db, monkeypatch, capsys, stop, why):
    """TC-BF-03 · 받다가 멈추면(한도 소진 · 설계 전제 깨짐) 69 · 남은 날은 부르지 않는다 · 멈춘 까닭의 첫 줄을 마지막 줄에."""
    seen = fake_fetch(monkeypatch, ["done", stop, "done", "done", "done"])
    t = backfill.run(*DAYS, quiet=True)
    assert len(seen) == 2, "멈춘 뒤의 날은 부르지 않는다"
    assert t["done"] == 1 and why in t["stopped"]
    assert backfill.exit_code(t) == 69
    last = capsys.readouterr().out.strip().splitlines()[-1]
    assert last.startswith("🟡 다 받지 못했다") and why in last and "할 일" not in last, "까닭은 첫 줄만"


def test_cli_returns_the_exit_code(monkeypatch):
    """TC-BF-04 · 명령 줄(`recent` · `backfill`)이 그 결과를 종료코드로 돌려준다 — 고치기 전에는 늘 0 이었다(DF-92)."""
    bad = {"done": 3, "empty": 0, "error": 1, "rows": 9, "skipped": 0, "stopped": ""}
    good = dict(bad, error=0)
    monkeypatch.setattr(backfill, "run_recent", lambda **k: bad)
    assert backfill.main(["recent", "--quiet"]) == 69
    monkeypatch.setattr(backfill, "run_recent", lambda **k: good)
    assert backfill.main(["recent", "--quiet"]) == 0
    monkeypatch.setattr(backfill, "run", lambda *a, **k: dict(good, stopped="한도"))
    assert backfill.main(["backfill", "--from", "20261005", "--to", "20261009"]) == 69


def test_69_does_not_collide_with_runner_and_worker_codes():
    """TC-BF-05 · 69 는 러너 · 작업자의 종료코드 약속(0 끝 · 2 인자 · 3 앱 DB 꺼짐 · 75 지금은 못 돈다 · 78 설정 결함 · 124 시간 넘김)과
    겹치지 않고, 러너가 시세 단계에서 경고로 세는 값과 같다(값이 두 곳 — 이 시험이 맞춘다)."""
    from scripts import daily_update as du
    assert backfill.EX_UNAVAILABLE not in {0, 1, 2, 3, du.EX_TEMPFAIL, du.EX_CONFIG, 124}
    price = next(s for s in du.STEPS if s.name == "price")
    assert price.warn_codes == (backfill.EX_UNAVAILABLE,) == (du.EX_UNAVAILABLE,)


def test_tally_keeps_working_for_the_app_task(temp_db, monkeypatch):
    """TC-BF-06 · 앱의 수집 작업(`collector_tasks.portal_recent_task`)이 읽는 칸(done · empty · error · rows)은 그대로 숫자다."""
    fake_fetch(monkeypatch, ["empty"] * 5)
    t = backfill.run(*DAYS, quiet=True)
    assert all(isinstance(t[k], int) for k in ("done", "empty", "error", "rows", "skipped"))
    assert isinstance(t["stopped"], str)
