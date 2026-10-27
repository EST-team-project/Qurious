"""자동 정기 점검 준비 상태. 데이터 상태 API와 같은 자료를 읽되 추정은 허용하지 않는다."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, time, timezone

from app.services import data_status, market_calendar, rebalance_schedule, hf_snapshot

KST = rebalance_schedule.KST


def _timestamp(value):
    try:
        result = datetime.fromisoformat(value)
        return result.astimezone(KST) if result.tzinfo else None
    except (TypeError, ValueError):
        return None


def _required_steps_ok(steps: list[dict]) -> bool:
    # 전체 회차 ok는 관제용이다. 필수 단계의 명시적 성공만 사용한다.
    # 중복 기록이나 JSON false를 종료코드 0으로 오인하지 않는다.
    for name in ("price", "calendar"):
        matches = [step for step in steps if step.get("name") == name]
        if len(matches) != 1:
            return False
        rc = matches[0].get("rc")
        if type(rc) is not int or rc != 0:
            return False
    return True


def readiness(now: datetime | None = None) -> dict:
    """회차의 필수 자료 준비 여부. 종목별 종가·시가는 각 판단/정산에서 검증한다."""
    now = (now or datetime.now(timezone.utc)).astimezone(KST)
    result = dict(ready=False, state="waiting", message="데이터 갱신 완료 대기",
                  decision_date=now.date().isoformat(), data_as_of=None, update_finished_at=None,
                  data_ready_at=None, source_commit=None)

    def wait(state, message):
        return {**result, "state": state, "message": message}

    if now.time() < time(12, 30):
        return wait("before_update", "12:30 데이터 갱신 이후 자동 점검합니다.")
    try:
        status = data_status.get_status(now, use_cache=False)
        cal = status.get("calendar") or {}
        today = rebalance_schedule.days(now.date(), now.date())[0]
        if not today["is_trading_day"]:
            return wait("closed", "오늘은 휴장일입니다. 다음 거래일에 자동 점검합니다.")
        folder = data_status.collector_dir()
        # The status page treats locks older than four hours as stale. A trading
        # decision must not infer completion from that timeout alone.
        if folder and (folder / "state" / "daily_update.lock").exists():
            return wait("updating", "데이터 갱신 진행 상태를 확인 중입니다. 완료 후 자동 점검합니다.")
        previous = date.fromisoformat(cal.get("previous_trading_day", ""))
        rows = rebalance_schedule.days(previous, now.date())
        if previous >= now.date() or not rows[0]["is_trading_day"] or any(r["is_trading_day"] for r in rows[1:-1]):
            return wait("calendar_unavailable", "전 거래일을 확인할 수 없어 자동 점검을 기다립니다.")
        runner = status.get("runner") or {}
        if runner.get("running"):
            return wait("updating", "데이터 갱신 중입니다. 완료 후 자동 점검합니다.")
        last = runner.get("last") or {}
        started, finished = _timestamp(last.get("started_at")), _timestamp(last.get("finished_at"))
        prepared = finished
        if folder and (folder / "provenance.json").exists():
            # HF 사본은 전체 회차 종료가 아니라, 동일 커밋의 검증된 자료 준비를 확인한다.
            # 검증 표지가 잘못됐으면 과거 완료 기록으로 우회하지 않는다.
            import json
            receipt = json.loads((folder / "provenance.json").read_text(encoding="utf-8"))
            if "proof_version" in receipt:
                proof = hf_snapshot.read_ready_proof(folder, now=now)
                if proof["started_at"] != last.get("started_at"):
                    return wait("data_unavailable", "동기화 자료와 실행 기록의 회차가 달라 자동 점검을 기다립니다.")
                prepared = _timestamp(proof["data_ready_at"])
                result.update(data_ready_at=proof["data_ready_at"], source_commit=proof["snapshot_commit"])
        if not started or not prepared or started.date() != now.date() or started.time() < time(12, 30) or not started <= prepared <= now:
            return wait("waiting", "오늘 12:30 이후 데이터 갱신 완료 기록을 기다립니다.")
        result["update_finished_at"] = finished.isoformat() if finished else None
        if last.get("stopped") or not _required_steps_ok(last.get("steps") or []):
            return wait("update_failed", "데이터 갱신이 중단됐거나 시세·달력 단계의 성공을 확인하지 못했습니다. 다시 확인합니다.")
        result["data_as_of"] = status.get("as_of")
        if status.get("as_of") != previous.isoformat() or last.get("price_max") != previous.isoformat():
            return wait("stale_data", "시세 기준일이 전 거래일과 달라 자동 점검을 기다립니다.")
        message = "동기화 자료 검증 완료 · 자동 점검 준비됨" if result["data_ready_at"] else "데이터 갱신 완료 · 자동 점검 준비됨"
        return {**result, "ready": True, "state": "ready", "message": message}
    except (market_calendar.CalendarUnavailable, sqlite3.Error, OSError, ValueError, TypeError, KeyError):
        return wait("data_unavailable", "거래일 달력 또는 갱신 상태를 확인할 수 없어 자동 점검을 기다립니다.")


def view(plan, state: dict) -> dict:
    """화면용: 완료한 날에는 이후 갱신 상태가 바뀌어도 완료 사실을 유지한다."""
    out = {**state, "last_checked_at": plan.last_auto_check_at.isoformat() if plan.last_auto_check_at else None,
           "last_result": plan.last_auto_check_result or {}}
    if not plan.is_active or not plan.targets:
        out.update(ready=False, state="inactive", message="플랜을 활성화하고 목표 비중을 저장하면 자동 점검합니다.")
    elif plan.last_auto_check_date and plan.last_auto_check_date.isoformat() == state["decision_date"]:
        out.update(ready=False, state="checked", message="오늘 자동 점검을 완료했습니다.")
    return out
