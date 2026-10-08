"""데이터 상태 시험 (TC-DST) — `GET /api/data/status` (목표 기능 ① W4 · 설계서 5.2.2 · 8절 표 「TC-DST」).

무엇을 보이나 — 「데이터가 언제 것인가 · 매일 갱신이 돌았나」.
지금까지 화면이 보던 `/api/system/sync-status` 는 외부 시세 **캐시**의 신선도라, 수집 DB 가 며칠째 멈춰도
초록으로 보였다. 이 API 는 러너 기록 파일 · 수집 DB 표 · 거래일 달력 · HF 기록을 읽어 판정한다.

여기서 지키는 것 —
1. 러너 판정 다섯 — 성공 · 실패(멈춘 단계) · 일부 실패(멈추지 않는 단계) · 도는 중(4시간 안 잠금) · 오늘 회차 없음.
2. 표 판정 — 오늘 앞 거래일이 몇 개 비었나(0 최신 · 1 정상 · 2 늦음 · 3+ 멈춤) · 계산 표는 주식 일봉과 같은 날.
   **휴장일은 세지 않는다** — 10-06 에 09-30 까지 있으면 빈 거래일은 10-01 · 10-02 둘이다(10-05 대체공휴일 ·
   주말은 세지 않는다).
3. 달력이 없으면 평일로 어림하고 `approx` 를 켠다(숨기지 않는다).
4. HF 기록 두 데이터셋의 태그 · 올린 시각.
5. 러너의 단계 이름이 상태 API 의 이름표와 어긋나지 않는다(단계를 더하면 이름표도 더해야 한다).
6. 로그인 없이는 401.
7. 표마다 「마지막 날짜」 질의가 큰 표를 색인 없이 처음부터 끝까지 읽지 않는다(DF-80 — 질의 계획으로 본다).

네트워크 · 실제 수집 DB 를 쓰지 않는다.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.lib.session import get_current_user
from app.routes import data as data_routes
from app.services import collector_db, data_status as ds
from collector import db
from collector import market_calendar as mc

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "kasi_holidays_2020_2027.json").read_text(encoding="utf-8"))


def at(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=KST)


def step(name, rc=0, note=""):
    return {"name": name, "rc": rc, "seconds": 1.0, "note": note}


def write_state(state: Path, *, last: dict | None = None, lock: dict | None = None, history: list | None = None):
    state.mkdir(parents=True, exist_ok=True)
    if last is not None:
        (state / "daily_update_last.json").write_text(json.dumps(last, ensure_ascii=False), encoding="utf-8")
    if lock is not None:
        (state / "daily_update.lock").write_text(json.dumps(lock), encoding="utf-8")
    if history is not None:
        (state / "daily_update_history.jsonl").write_text(
            "\n".join(json.dumps(h, ensure_ascii=False) for h in history) + "\n", encoding="utf-8")


def write_catalog(state: Path) -> dict:
    """러너가 회차마다 쓰는 단계 목록을 그대로 만든다 — 러너 코드(``scripts/daily_update.step_catalog``)에서."""
    from scripts import daily_update as du
    cat = du.step_catalog(at("2026-10-02T12:30:01"))
    state.mkdir(parents=True, exist_ok=True)
    (state / ds.CATALOG_FILE).write_text(json.dumps(cat, ensure_ascii=False), encoding="utf-8")
    return cat


def last_run(day: str, steps: list, ok=True, stopped=None) -> dict:
    return {"started_at": f"{day}T12:30:01+09:00", "finished_at": f"{day}T12:51:16+09:00", "ok": ok,
            "upload": True, "stopped": stopped, "derived": "시세가 바뀌었다", "steps": steps,
            "after": {"price_max": day.replace("-", "")}}


# ── 1. 러너 ──────────────────────────────────────────────────────────────
def test_runner_ok_failed_warning(tmp_path):
    """TC-DST-01 · 성공 · 실패(멈춘 단계를 그대로) · 일부 실패(멈추지 않는 단계의 이름표)."""
    st = tmp_path / "state"
    write_catalog(st)                                         # 러너가 회차마다 처음에 쓰는 단계 목록 — 이름표 · 멈춤 여부(결정 ④)
    write_state(st, last=last_run("2026-10-02", [step("price"), step("dividend"), step("calendar")]))
    r = ds.runner_state(st, at("2026-10-02T14:00:00"))
    assert (r["state"], r["ran_today"], r["last"]["minutes"]) == ("ok", True, 21.2)

    write_state(st, last=last_run("2026-10-02", [step("price", 1), step("adjusted", None, "앞 단계 실패로 건너뜀")],
                                  ok=False, stopped="price 종료코드 1"))
    r = ds.runner_state(st, at("2026-10-02T14:00:00"))
    assert r["state"] == "failed" and "price 종료코드 1" in r["detail"]
    assert [s["status"] for s in r["last"]["steps"]] == ["failed", "skipped"]

    write_state(st, last=last_run("2026-10-02", [step("price"), step("calendar", 3), step("ohlcv", 2)], ok=False))
    r = ds.runner_state(st, at("2026-10-02T14:00:00"))
    assert r["state"] == "warning" and r["detail"] == "실패한 단계: 시장 달력 · 일봉"


def test_followup_skip_is_attention_not_failure(tmp_path):
    """TC-DST-16 · 채울 것이 있는 건너뜀(신호 단계 · 앱 DB 꺼짐 — 러너가 돌리기 전에 확인 · 2026-10-08 안 B)은 회차 판정
    「일부 건너뜀」 — 실패 · 경고가 아니다. 단계 줄은 상태 「건너뜀」 그대로 까닭 · 뒤 할 일 · 거래일을 넘긴다(화면이 노랑으로).
    할 일이 없어 건너뛴 줄(새 자료 없음 등)은 회차를 「성공」 에 둔다."""
    st = tmp_path / "state"
    write_catalog(st)
    held = {"name": "signals", "rc": None, "seconds": 0.0, "reason": "app_db_down", "followup": "fill",
            "date": "2026-10-07", "note": "앱 DB 꺼짐 · 127.0.0.1:15432 연결 거부 · 건너뜀"}
    write_state(st, last=last_run("2026-10-08", [step("price"), held]))
    r = ds.runner_state(st, at("2026-10-08T15:00:00"))
    sig = r["last"]["steps"][1]
    assert (sig["status"], sig["reason"], sig["followup"], sig["date"]) == ("skipped", "app_db_down", "fill", "2026-10-07")
    assert (r["state"], r["label"]) == ("attention", "일부 건너뜀") and "신호" in r["detail"]
    assert r["last"]["ok"] is True, "회차 ok 는 러너가 쓴 그대로"
    idle = {"name": "adjusted", "rc": None, "seconds": 0.0, "reason": "no_new_data", "note": "새 자료 없음"}
    write_state(st, last=last_run("2026-10-08", [step("price"), idle]))
    r = ds.runner_state(st, at("2026-10-08T15:00:00"))
    assert r["state"] == "ok" and "followup" not in r["last"]["steps"][1]


def test_attention_run_makes_overall_verdict_check_needed(monkeypatch):
    """TC-DST-17 · 「일부 건너뜀」 회차는 전체 판정을 「확인 필요」 로 올린다(빠진 날을 채울 일이 남았다) — 「멈춤」 은 아니다."""
    monkeypatch.setattr(ds, "collector_dir", lambda: None)
    monkeypatch.setattr(ds, "runner_state", lambda *a, **k: {"state": "attention", "label": "일부 건너뜀", "running": False})
    monkeypatch.setattr(ds, "table_states", lambda *a, **k: ([{"key": "price_daily", "verdict": "ok", "last_date": "2026-10-07"}], {}))
    monkeypatch.setattr(ds, "hf_state", lambda *a, **k: [])
    s = ds.get_status(at("2026-10-08T15:00:00"), use_cache=False)
    assert (s["verdict"], s["verdict_label"]) == ("warning", "확인 필요")


def test_runner_running_lock_and_stale_lock(tmp_path):
    """TC-DST-02 · 4시간 안 잠금 = 도는 중 · 그보다 오래된 잠금은 죽은 잠금이라 무시한다."""
    st = tmp_path / "state"
    write_state(st, last=last_run("2026-10-01", [step("price")]),
                lock={"pid": 1, "started_at": "2026-10-02T12:30:00+09:00"})
    r = ds.runner_state(st, at("2026-10-02T12:40:00"))
    assert (r["state"], r["running"]) == ("running", True)
    r = ds.runner_state(st, at("2026-10-02T17:00:00"))
    assert r["running"] is False and r["state"] == "late", "잠금이 4시간 넘으면 도는 중이 아니다 · 오늘 회차도 없다"


def test_running_step_from_progress_of_the_same_run(tmp_path):
    """TC-DST-14 · 도는 중의 지금 단계 — 러너의 진행 파일을 같은 실행(시작 시각이 잠금과 같음)일 때만 믿는다 ·
    지난 실행이 남긴 진행 파일 · 도는 중이 아닐 때는 싣지 않는다(수집 일정 화면 「수집 중 — n번째 단계」 · 2026-10-08)."""
    st = tmp_path / "state"
    write_state(st, last=last_run("2026-10-01", [step("price")]),
                lock={"pid": 1, "started_at": "2026-10-02T12:30:00+09:00"})
    prog = {"started_at": "2026-10-02T12:30:00+09:00", "step": {"index": 10, "total": 19, "name": "adjusted", "label": "수정주가"}}
    (st / ds.PROGRESS_FILE).write_text(json.dumps(prog, ensure_ascii=False), encoding="utf-8")
    r = ds.runner_state(st, at("2026-10-02T12:50:00"))
    assert r["running_step"] == {"index": 10, "total": 19, "name": "adjusted", "label": "수정주가"}
    prog["started_at"] = "2026-10-01T12:30:00+09:00"            # 어제 실행이 남긴 진행 파일
    (st / ds.PROGRESS_FILE).write_text(json.dumps(prog, ensure_ascii=False), encoding="utf-8")
    assert "running_step" not in ds.runner_state(st, at("2026-10-02T12:50:00"))
    (st / "daily_update.lock").unlink()
    assert "running_step" not in ds.runner_state(st, at("2026-10-02T14:00:00"))


def test_runner_late_only_after_an_hour_and_missing(tmp_path):
    """TC-DST-03 · 오늘 회차가 없으면 13:30 부터 「오늘 회차 없음」 · 그 전엔 어제 성공 그대로 · 기록이 없으면 「기록 없음」."""
    st = tmp_path / "state"
    write_state(st, last=last_run("2026-10-01", [step("price")]),
                history=[{"started_at": "2026-10-01T12:30:01+09:00", "finished_at": "2026-10-01T12:51:16+09:00",
                          "ok": True, "upload": True, "stopped": None, "price_max": "20260930"},
                         {"started_at": "2026-10-01T13:00:00+09:00", "skipped": "다른 실행이 돌고 있다"}])
    assert ds.runner_state(st, at("2026-10-02T12:10:00"))["state"] == "ok"
    late = ds.runner_state(st, at("2026-10-02T13:31:00"))
    assert late["state"] == "late" and late["next_expected"] == "2026-10-03T12:30+09:00"
    assert [h["ok"] for h in late["history"]] == [None, True], "최근이 먼저 · 건너뛴 회차는 ok 대신 skipped"
    assert ds.runner_state(tmp_path / "없음", at("2026-10-02T12:10:00"))["state"] == "missing"


# ── 2. 표 ────────────────────────────────────────────────────────────────
def _days_between(a: date, b: date):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


@pytest.fixture
def market(tmp_path, monkeypatch):
    """거래일 달력 · 시세가 있는 수집 DB — 시세는 2026-09-30 까지(실측과 같은 모양)."""
    path = tmp_path / "collector" / "market.sqlite3"
    path.parent.mkdir()
    conn = db.connect(path)
    rows = [r for v in FIXTURE["years"].values() for r in v]
    conn.executemany("INSERT INTO holiday_kasi (locdate, date_name, is_holiday, date_kind, seq, fetched_at) "
                     "VALUES (?, ?, ?, ?, ?, '2026-10-02T12:00:00+09:00')",
                     [(r["locdate"], r["date_name"], r["is_holiday"], r["date_kind"], r["seq"]) for r in rows])
    hol = mc.public_holidays(conn)
    trading = [d for d in _days_between(date(2026, 9, 1), date(2026, 9, 30)) if mc.rule_reason(d, hol) is None]
    conn.executemany("INSERT INTO price_daily (bas_dt, srtn_cd, clpr) VALUES (?, '005930', 1)",
                     [(d.strftime("%Y%m%d"),) for d in trading])
    conn.executemany("INSERT INTO price_adjusted (bas_dt, srtn_cd, adj_clpr, cum_factor) VALUES (?, '005930', 1, 1)",
                     [(d.strftime("%Y%m%d"),) for d in trading[:-2]])        # 계산 표가 두 거래일 뒤처짐
    mc.build(conn, fetch=False, today=date(2026, 10, 2), quiet=True)
    conn.close()
    monkeypatch.setenv(collector_db.ENV_DB_PATH, str(path))
    ds._cache.clear()
    ds._counts.update(sig=None, rows={}, at=None)
    yield path
    t = ds._count_job["thread"]                     # 뒤에서 세는 스레드가 임시 DB 를 쥔 채 끝나지 않게
    if t is not None:
        t.join(10)


def _states(today: date):
    conn = ds._connect_ro()
    try:
        tables, cal = ds.table_states(conn, today)
    finally:
        conn.close()
    return {t["key"]: t for t in tables}, cal


def test_tables_count_only_trading_days(market):
    """TC-DST-04 · 비어 있는 거래일만 센다 — 10-02 엔 10-01 하루(정상) · 10-06 엔 10-01 · 10-02 둘(늦음, 10-05 휴일은 안 셈)."""
    t, cal = _states(date(2026, 10, 2))
    p = t["price_daily"]
    assert (p["last_date"], p["behind_trading_days"], p["verdict"], p["approx"]) == ("2026-09-30", 1, "ok", False)
    assert cal == {"today_is_trading_day": True, "today_reason": "", "next_trading_day": "2026-10-02",
                   "previous_trading_day": "2026-10-01"}

    t, cal = _states(date(2026, 10, 6))
    assert (t["price_daily"]["behind_dates"], t["price_daily"]["verdict"]) == (["2026-10-01", "2026-10-02"], "late")
    t, _ = _states(date(2026, 10, 8))
    assert t["price_daily"]["verdict"] == "stale", "10-01 · 02 · 06 · 07 — 넷이면 멈춤"
    t, cal = _states(date(2026, 10, 5))
    assert cal["today_is_trading_day"] is False and cal["today_reason"] == "대체공휴일(개천절)"


def test_tables_derived_lag_missing_and_calendar(market):
    """TC-DST-05 · 계산 표가 주식 일봉보다 뒤처지면 늦음 · 없는 표는 없음 · 달력은 끝까지 남은 날로."""
    t, _ = _states(date(2026, 10, 2))
    assert (t["price_adjusted"]["verdict"], t["price_adjusted"]["behind_trading_days"]) == ("late", 2)
    assert t["etf_daily"]["verdict"] == "missing", "표는 있으나 행이 없다"
    assert t["market_calendar"]["verdict"] == "ok" and t["market_calendar"]["last_date"] == "2027-12-31"
    assert t["market_event"]["verdict"] == "info"


def test_news_rows_split_by_source(market):
    """TC-DST-15 · 뉴스 표의 출처 둘을 줄 둘로 — 정책뉴스 줄이 언론사 기사(GDELT)를 세지 않는다(DF-87).

    한 줄로 셀 때는 정책뉴스 줄이 42,303(= 정책뉴스 32,983 + 언론사 기사 9,320)을 보였고, 마지막 날짜도 매일 받는
    언론사 기사 쪽으로 당겨져 정책뉴스가 멈춰도 관제에 보이지 않았다(2026-10-08 실측).
    """
    conn = db.connect(market)
    rows = [("policy:1", "policy_news", "2026-09-30T10:00:00+09:00"), ("policy:2", "policy_news", "2026-10-01T09:00:00+09:00"),
            ("gdelt:a", "gdelt", "2026-10-06T08:00:00+09:00"), ("gdelt:b", "gdelt", "2026-10-07T08:00:00+09:00"),
            ("gdelt:c", "gdelt", "2026-10-07T09:15:00+09:00")]
    conn.executemany("INSERT INTO news_item (news_id, source, title, pub_at, available_at, fetched_at, updated_at) "
                     "VALUES (?, ?, '제목', ?, ?, '2026-10-07T12:30:00+09:00', '2026-10-07T12:30:00+09:00')",
                     [(i, s, p, p) for i, s, p in rows])
    conn.commit()
    counts = {key: conn.execute(count_sql).fetchone()[0]
              for key, _table, *_rest, _last_sql, count_sql in ds.TABLES if key in ("news_item", "news_gdelt")}
    conn.close()
    assert counts == {"news_item": 2, "news_gdelt": 3}
    t, _ = _states(date(2026, 10, 8))
    assert (t["news_item"]["label"], t["news_item"]["last_date"]) == ("정책뉴스", "2026-10-01"), "언론사 기사 날짜로 당겨지지 않는다"
    assert (t["news_gdelt"]["label"], t["news_gdelt"]["last_date"], t["news_gdelt"]["verdict"]) == ("언론사 기사", "2026-10-07", "info")


def test_tables_without_calendar_are_approximate(tmp_path, monkeypatch):
    """TC-DST-06 · 달력이 없는 PC — 평일로 어림하고 `approx` 를 켠다(10-05 휴일도 거래일로 세게 된다)."""
    path = tmp_path / "market.sqlite3"
    conn = db.connect(path)
    conn.execute("INSERT INTO price_daily (bas_dt, srtn_cd, clpr) VALUES ('20260930', '005930', 1)")
    conn.close()
    monkeypatch.setenv(collector_db.ENV_DB_PATH, str(path))
    t, cal = _states(date(2026, 10, 6))
    assert (t["price_daily"]["approx"], t["price_daily"]["behind_trading_days"]) == (True, 3)
    assert cal == {}


# ── 3. HF · 모으기 · API ─────────────────────────────────────────────────
def test_status_gathers_runner_tables_and_hf(market):
    """TC-DST-07 · 러너 · 표 · HF 두 데이터셋을 한 답에 · 가장 나쁜 판정이 전체 판정 · 기준일 = 주식 일봉 마지막 날."""
    cdir = market.parent
    write_state(cdir / "state", last=last_run("2026-10-02", [step("price"), step("calendar")]))
    (cdir.parent / "hf_export" / "meta").mkdir(parents=True)
    (cdir.parent / "hf_export" / "meta" / "manifest.json").write_text(json.dumps(
        {"generated_at": "2026-10-02T12:50:00+09:00", "repo_id": "qurious-quant/krx-daily-market",
         "uploaded": {"at": "2026-10-02T12:51:16+09:00", "tag": "snapshot-2026-10-02",
                      "repo_id": "qurious-quant/krx-daily-market"}}), encoding="utf-8")
    (cdir / "ohlcv_export").mkdir()
    (cdir / "ohlcv_export" / "manifest.json").write_text(json.dumps(
        {"as_of": "2026-10-01", "built_at": "2026-10-02T12:45:00+09:00", "rows": {"1d": 10},
         "uploaded": {"at": "2026-10-02T12:52:00+09:00", "tag": "ohlcv-2026-10-02"}}), encoding="utf-8")
    s = ds.get_status(at("2026-10-02T14:00:00"), use_cache=False)
    assert s["as_of"] == "2026-09-30" and s["runner"]["state"] == "ok"
    assert s["verdict"] == "warning", "계산 표가 늦고 ETF 표가 비어 있다"
    assert [(h["repo"], h["tag"]) for h in s["hf"]] == [("qurious-quant/krx-daily-market", "snapshot-2026-10-02"),
                                                       ("qurious-quant/krx-ohlcv", "ohlcv-2026-10-02")]
    assert s["source"] == "collector" and s["summary"].startswith("주식 시세 기준일 2026-09-30")


def test_runner_step_labels_come_from_runner_records(tmp_path):
    """TC-DST-08 · 앱에는 단계 이름표 사본이 없다 — 이름표 · 묶음 · 하는 일은 러너 기록에서 온다(회차 기록 → 단계 목록 → 이름 그대로).

    2026-10-07 전에는 앱에 손으로 옮긴 사본(19줄)이 있어 단계를 더할 때 두 곳을 고쳐야 했다(결정 ④ · 단계가 늘면 화면이 따라온다).
    """
    from scripts import daily_update as du
    assert not hasattr(ds, "STEPS"), "앱에 단계 이름표 사본이 다시 생겼다 — 러너의 Step(label · group · desc)에만 둔다"
    st = tmp_path / "state"
    cat = write_catalog(st)
    by_name = ds.load_catalog(st)["by_name"]
    assert [s["name"] for s in cat["steps"]] == [s.name for s in du.STEPS]
    for s in du.STEPS:                                         # 러너의 모든 단계가 목록에서 한국어 이름표 · 묶음 · 하는 일을 얻는다
        v = ds._step_view({"name": s.name, "rc": 1}, by_name)
        assert v["label"] == s.label != s.name and v["group"] == s.group and v["desc"] == s.desc
        assert v["status"] == ("failed" if s.fatal else "warning"), f"{s.name}: 멈추는 단계 표시가 러너와 다르다"
    # 그 회차 기록에 적힌 이름표가 단계 목록보다 먼저다 — 단계 이름표를 바꾼 뒤에도 옛 회차는 그때 이름으로
    assert ds._step_view({"name": "price", "label": "옛 이름", "fatal": False, "rc": 2}, by_name)["label"] == "옛 이름"
    assert ds._step_view({"name": "price", "label": "옛 이름", "fatal": False, "rc": 2}, by_name)["status"] == "warning"
    # 기록에도 목록에도 없으면 이름 그대로(옛 기록 · 목록 파일이 없는 PC)
    assert ds._step_view({"name": "brand_new", "rc": 0}, by_name)["label"] == "brand_new"
    assert ds._step_view({"name": "price", "rc": 0}, {})["label"] == "price"


def test_runner_history_steps_disk_and_detail(tmp_path, monkeypatch):
    """TC-DST-11 · 회차 기록 — 새 줄은 단계별 결과(이름표 포함) · 옛 줄은 None · 한 단계 다시 돌린 줄 표시 · 이 PC 용량(GB) ·
    수집 일정 화면 답(단계 목록 · 용량 · 다시 돌리는 명령)."""
    st = tmp_path / "state"
    write_catalog(st)
    write_state(st, last=last_run("2026-10-02", [step("price"), step("news", 3)], ok=False), history=[
        {"started_at": "2026-10-01T12:30:01+09:00", "finished_at": "2026-10-01T12:55:01+09:00", "ok": True, "price_max": "20260930"},
        {"started_at": "2026-10-02T12:30:01+09:00", "finished_at": "2026-10-02T12:51:16+09:00", "ok": False,
         "price_max": "20261001", "steps": [step("price"), step("news", 3)]},
        {"started_at": "2026-10-02T15:00:00+09:00", "finished_at": "2026-10-02T15:00:05+09:00", "only": "news", "ok": True,
         "steps": [step("news")]},
    ])
    (st / ds.DISK_FILE).write_text(json.dumps({"measured_at": "2026-10-02T12:51:16+09:00", "drive": "C:",
                                                "free_bytes": 130_449_000_000, "total_bytes": 1_000_000_000_000,
                                                "collector_db_bytes": 5_028_982_016}), encoding="utf-8")
    r = ds.runner_state(st, at("2026-10-02T16:00:00"))
    newest, mid, old = r["history"]
    assert newest["only"] == "news" and [s["label"] for s in newest["steps"]] == ["정책뉴스"]
    assert [(s["label"], s["group"], s["status"]) for s in mid["steps"]] == [("시세", "받기", "ok"), ("정책뉴스", "받기", "warning")]
    assert old["steps"] is None and old["only"] is None, "단계별 결과가 없는 옛 줄"
    assert [g["key"] for g in r["groups"]] == ["받기", "계산", "백업", "근거 문서"]
    assert ds.pc_disk(st) == {"measured_at": "2026-10-02T12:51:16+09:00", "drive": "C:", "free_gb": 130.4,
                              "total_gb": 1000.0, "collector_db_gb": 5.0}
    assert ds.pc_disk(tmp_path / "없음") is None

    monkeypatch.setattr(ds, "collector_dir", lambda: tmp_path)
    d = ds.runner_detail(at("2026-10-02T16:00:00"))
    assert d["catalog"]["steps"][0] == {"name": "price", "label": "시세", "group": "받기",
                                        "desc": "최근 거래일 시세를 받아 빈 날을 메운다", "fatal": True, "derived": False,
                                        "upload": False, "timeout_min": 30, "fill": ""}
    sig = next(s for s in d["catalog"]["steps"] if s["name"] == "signals")
    assert sig["fill"].startswith("python scripts/signals_daily.py --from"), "빠진 날 채우기 명령이 API 까지 온다(#142)"
    assert d["disk"]["free_gb"] == 130.4 and d["rerun"]["from_screen"] is False and "--only" in d["rerun"]["command"]


def test_runner_api_is_admin_only(tmp_path, monkeypatch):
    """TC-DST-12 · 수집 일정 · 단계 API(`GET /api/data/runner`)는 관리자만 — 로그인 없이 401 · 일반 사용자 403 · 관리자 200."""
    monkeypatch.setattr(ds, "collector_dir", lambda: tmp_path)
    write_catalog(tmp_path / "state")
    app = FastAPI()
    app.include_router(data_routes.router)
    c = TestClient(app)
    assert c.get("/api/data/runner").status_code == 401
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "name": "시험", "email": "t@example.com", "roles": ["user"]}
    assert c.get("/api/data/runner").status_code == 403
    app.dependency_overrides[get_current_user] = lambda: {"id": "a1", "name": "관리", "email": "a@example.com", "roles": ["admin"]}
    j = c.get("/api/data/runner").json()
    assert len(j["catalog"]["steps"]) >= 19 and j["rerun"]["from_screen"] is False


def test_api_requires_login(market):
    """TC-DST-09 · 로그인 없이는 401 · 로그인하면 200 과 판정."""
    app = FastAPI()
    app.include_router(data_routes.router)
    c = TestClient(app)
    assert c.get("/api/data/status").status_code == 401
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "name": "시험", "email": "t@example.com"}
    j = c.get("/api/data/status").json()
    assert j["verdict"] in ("ok", "warning", "error") and {t["key"] for t in j["tables"]} >= {"price_daily", "market_calendar"}


def test_row_counts_in_background_reused_and_recounted(market, monkeypatch):
    """TC-DST-10 · 행 수는 뒤에서 센다 — 처음엔 곧바로 「세는 중」(줄 수 None)으로 답하고, 다 세면 그 값(fresh)을 쓴다.
    파일이 그대로면 다시 세지 않고, 러너가 도는 중이면 지난 값(old)과 그 까닭을, 러너가 끝나면 뒤에서 다시 센다.
    (컨테이너에서 큰 표 다섯의 COUNT(*) 가 첫 호출에 14.8초 · 점검 스크립트에서 21초 걸렸다 — 2026-10-02)"""
    import sqlite3 as _sq
    import threading

    gate = threading.Event()
    real = ds._count_rows
    monkeypatch.setattr(ds, "_count_rows", lambda path, sig: (gate.wait(10), real(path, sig)))
    now = at("2026-10-02T14:00:00")
    s = ds.get_status(now)
    assert s["rows_state"] == "pending" and "세는 중" in s["rows_note"]
    assert all(t["rows"] is None for t in s["tables"] if t["verdict"] != "missing"), "세는 동안 줄 수는 비운다"
    assert {t["key"]: t["last_date"] for t in s["tables"]}["price_daily"] == "2026-09-30", "기준일 · 판정은 그대로"
    gate.set()
    ds._count_job["thread"].join(10)
    s = ds.get_status(now)
    rows = {t["key"]: t["rows"] for t in s["tables"]}
    assert s["rows_state"] == "fresh" and rows["price_daily"] > 0 and "rows_note" not in s

    real_start = ds.start_count
    started = []
    monkeypatch.setattr(ds, "start_count", lambda **k: started.append(1) or True)
    assert ds.get_status(now)["rows_state"] == "fresh" and not started, "파일이 그대로면 다시 세지 않는다"

    w = _sq.connect(market)                                   # 러너가 쓰는 중 — 파일이 바뀐다
    w.execute("INSERT INTO price_daily (bas_dt, srtn_cd, clpr) VALUES ('20261001', '000660', 1)")
    w.commit()
    w.close()
    write_state(market.parent / "state", lock={"pid": 1, "started_at": "2026-10-02T13:55:00+09:00"})
    s = ds.get_status(now)
    assert s["rows_state"] == "old" and "도는 중" in s["rows_note"] and not started, "러너가 쓰는 동안은 다시 세지 않는다"
    assert {t["key"]: t["rows"] for t in s["tables"]}["price_daily"] == rows["price_daily"]

    (market.parent / "state" / "daily_update.lock").unlink()   # 러너가 끝났다 — 다시 센다
    monkeypatch.setattr(ds, "start_count", real_start)
    s = ds.get_status(now)
    assert s["rows_state"] == "old" and "다시 세는 중" in s["rows_note"]
    ds._count_job["thread"].join(10)
    s = ds.get_status(now)
    assert s["rows_state"] == "fresh" and {t["key"]: t["rows"] for t in s["tables"]}["price_daily"] == rows["price_daily"] + 1


def test_last_date_queries_use_indexes(tmp_path):
    """TC-DST-13 · 표마다 「마지막 날짜」 질의가 큰 표를 색인 없이 처음부터 끝까지 읽지 않는다(DF-80).

    재무 표(188만 행)의 `MAX(known_at)` 는 그 칸에 색인이 없어 도커 앱에서 19 ~ 31초 걸렸다 — 30초 응답 캐시가 끊길 때마다
    데이터 상태 API 가 그만큼 멈췄고, 기능 점검(check.ps1 데이터)이 30초 시간 초과로 실패했다(2026-10-07).
    수집기의 실제 표 정의(`collector.db.connect` — 기본 키 · 색인 그대로)로 빈 DB 를 만들고, 질의 계획에서 그 표를 읽는 줄이
    모두 색인 · 기본 키를 쓰는지(`USING`) 본다. 작은 표 둘(배당 · 정책뉴스 — 수천 행)은 글자를 잘라 견주느라 전체를 읽어도 된다.
    """
    conn = db.connect(tmp_path / "plan.sqlite3")
    try:
        small = {"dividend", "news_item"}
        checked = []
        for key, table, *_rest, last_sql, _count_sql in ds.TABLES:
            if table in small or not ds._has_table(conn, table):
                continue
            plan = [r[-1] for r in conn.execute("EXPLAIN QUERY PLAN " + last_sql)]
            reads = [p for p in plan if re.search(rf"\b{table}\b", p)]
            assert reads, (key, plan)
            assert all("USING" in p for p in reads), f"{key}: 색인 없이 표를 훑는다 — {last_sql} → {plan}"
            checked.append(table)
        assert {"price_daily", "price_adjusted", "disclosure", "financial_statement", "price_intraday",
                "market_event"} <= set(checked), checked
    finally:
        conn.close()
