"""받을 범위 시험 (TC-FP) — 「자료 직접 받기」 의 받은 것 · 받을 것 · 휴장 · 아직 공개 전(데이터 수집 화면 설계 2 · 2026-10-08).

지키는 것 — 수집기의 실제 스키마(`collector.db.connect`)로 만든 작은 DB 로 돈다(네트워크 없음).
1. 단위는 수집기가 실제로 받는 단위 — 시세 · 공시 · 정책뉴스는 날, 재무는 해(결정 ② · 2026-10-08)
2. 시세: 거래일이 아니면 휴장, 다음 거래일 13시 전이면 아직 공개 전(받을 것으로 세지 않는다) · 빈 응답 · 실패 · 기록 없음은 받을 것
3. 공시: 그날을 덮는 끝난 창이 **기록에 나온 모든 조합**에 있어야 받은 날 — 일부만이면 「일부」(상수를 베끼지 않는다)
4. 받을 것이 있으면 처음 ~ 끝을 한 번에 받는 명령 · 없으면 명령 없이 「받을 것이 없습니다」
5. 입력 잘못은 422 · 수집 DB 가 없으면 503 · 관리자만
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.lib.session import get_current_user
from app.routes import data as data_routes
from app.services import collector_db
from app.services import fetch_plan as fp
from collector import db as cdb

KST = timezone(timedelta(hours=9))
BEFORE_13 = datetime(2026, 10, 8, 11, 0, tzinfo=KST)    # 10-07 시세는 아직 공개 전(10-08 13시 뒤)
AFTER_13 = datetime(2026, 10, 8, 13, 5, tzinfo=KST)

# 2026-09-28(월) ~ 10-12(월) — 10-03 토 · 10-04 일 · 10-05 대체공휴일 · 10-09 한글날 · 10-10 · 10-11 주말
CLOSED = {"2026-10-03": "개천절", "2026-10-04": "일요일", "2026-10-05": "대체공휴일", "2026-10-09": "한글날",
          "2026-10-10": "토요일", "2026-10-11": "일요일"}


@pytest.fixture
def plan_db(tmp_path, monkeypatch):
    path = tmp_path / "market.sqlite3"
    conn = cdb.connect(path)
    conn.execute("BEGIN")
    d = date(2026, 9, 28)
    while d <= date(2026, 10, 12):
        iso = d.isoformat()
        conn.execute("INSERT INTO market_calendar (cal_date, is_trading_day, reason, basis, updated_at) "
                     "VALUES (?, ?, ?, 'rule', '2026-10-08T12:00:00+09:00')", (iso, 0 if iso in CLOSED else 1, CLOSED.get(iso, "")))
        d += timedelta(days=1)
    ing = [("portal", f"202609{x}", "done") for x in ("28", "29", "30")] + [
        ("portal", "20261001", "done"), ("portal", "20261002", "empty"), ("portal", "20261006", "error"),
        # 공시 — 분기 창(과거분) 두 조합 끝남 · 10월 창은 AY 끝남 · AK 는 매일 수집의 끝나지 않은 창(아래 따로 · 받은 시각이 있다)
        ("dart_list", "20260701-20260930:AY", "done"), ("dart_list", "20260701-20260930:AK", "done"),
        ("dart_list", "20261001-20261007:AY", "done"),
        # 재무 — 2024 다 끝남 · 2025 남은 묶음이 자료 없음뿐(마감 전) · 2026 실패 · 2023 기록 없음 · 2022 한 묶음만 부름
        ("dart_fin", "2024-11011-b00", "done"), ("dart_fin", "2024-11011-b01", "done"),
        ("dart_fin", "2025-11011-b00", "done"), ("dart_fin", "2025-11011-b01", "empty"),
        ("dart_fin", "2026-11011-b00", "error"), ("dart_fin", "2022-11011-b00", "done"),
    ]
    conn.executemany("INSERT INTO ingest_day (source, bas_dt, status, rows, attempts, updated_at, message) "
                     "VALUES (?, ?, ?, 0, 1, '2026-10-08T12:00:00+09:00', '')", ing)
    # 매일 수집의 창(끝 = 받은 날) — 10-05 12:40 에 받았으니 10-01 ~ 10-04 는 받은 날, 10-05 ~ 10-07 은 「일부」
    conn.execute("INSERT INTO ingest_day (source, bas_dt, status, rows, attempts, updated_at, message) "
                 "VALUES ('dart_list', '20261001-20261007:AK', 'partial', 0, 1, '2026-10-05T12:40:00+09:00', '')")
    for t, at in (("window/20260928-20260930", "2026-10-04T12:00:00+09:00"), ("window/20261001-20261003", "2026-10-04T12:00:00+09:00"),
                  # 매일 수집 — 10-07 12:31 에 10-05 ~ 10-07 을 받았다 → 10-05 · 10-06 은 받은 날, 10-07 은 그날 받아 「일부」
                  ("daily/20261005-20261007", "2026-10-07T12:31:00+09:00")):
        conn.execute("INSERT INTO raw_response (source, target, fetched_at, body, sha256, bytes) "
                     "VALUES ('policy_news', ?, ?, x'00', 'h', 1)", (t, at))
    conn.execute("COMMIT")
    conn.close()
    monkeypatch.setenv(collector_db.ENV_DB_PATH, str(path))
    return path


def _states(out: dict) -> dict[str, str]:
    return {x["date"]: x["state"] for x in out["days"]}


def test_price_days_closed_pending_and_todo(plan_db):
    """TC-FP-01 · 시세 — 휴장 · 아직 공개 전 · 받음 · 빈 응답 · 실패 · 기록 없음, 받을 것의 처음 ~ 끝을 한 번에 받는 명령."""
    out = fp.plan("price", "2026-09-28", "2026-10-08", now=BEFORE_13)
    st = _states(out)
    assert [st[f"2026-10-0{i}"] for i in (3, 4, 5)] == ["closed"] * 3
    assert st["2026-10-02"] == "missing" and st["2026-10-06"] == "error"
    assert st["2026-10-07"] == "pending" and st["2026-10-08"] == "pending", "다음 거래일 13시 전은 받을 것이 아니다"
    assert out["counts"] == {"done": 4, "partial": 0, "missing": 1, "error": 1, "closed": 3, "pending": 2}
    assert out["todo"] == 2 and out["todo_range"] == {"from": "2026-10-02", "to": "2026-10-06"}
    assert out["command"] == "python -m collector.backfill backfill --from 20261002 --to 20261006"
    # 13시가 지나면 10-07 은 받을 것이 된다(기록이 없다)
    after = fp.plan("price", "2026-09-28", "2026-10-08", now=AFTER_13)
    assert _states(after)["2026-10-07"] == "missing" and after["todo_range"]["to"] == "2026-10-07"
    assert next(x for x in out["days"] if x["date"] == "2026-10-05")["note"] == "대체공휴일"


def test_disclosure_needs_every_recorded_combo(plan_db):
    """TC-FP-02 · 공시 — 받은 창이 기록에 나온 모든 조합(AY · AK)에 있어야 받은 날 · 창 밖은 빈 날 · 오늘은 아직.
    매일 수집의 끝나지 않은 창(partial)은 받은 날(기록 시각)보다 앞선 날만 받은 날 — 받은 그날 뒤는 「일부」."""
    st = _states(fp.plan("disclosure", "2026-06-29", "2026-10-08", now=BEFORE_13))
    assert st["2026-06-29"] == st["2026-06-30"] == "missing"
    assert st["2026-07-01"] == st["2026-09-30"] == "done"
    assert st["2026-10-01"] == st["2026-10-04"] == "done", "받은 날(10-05)보다 앞선 날은 그날이 끝난 뒤에 받았다"
    assert st["2026-10-05"] == st["2026-10-07"] == "partial"
    assert st["2026-10-08"] == "pending"


def test_policy_news_windows_cover_days(plan_db):
    """TC-FP-03 · 정책뉴스 — 과거분 창(window/) · 매일 수집 창(daily/) 모두 · 받은 날보다 앞선 날은 받음 · 받은 그날은 일부 ·
    덮지 않은 날은 빈 날 · 오늘은 아직(매일 수집은 어제까지)."""
    out = fp.plan("policy_news", "2026-09-28", "2026-10-08", now=BEFORE_13)
    st = _states(out)
    assert all(st[f"2026-09-{x}"] == "done" for x in ("28", "29", "30")) and st["2026-10-03"] == "done"
    assert st["2026-10-04"] == "missing"
    assert st["2026-10-05"] == st["2026-10-06"] == "done" and st["2026-10-07"] == "partial"
    assert st["2026-10-08"] == "pending"
    assert out["command"] == "python -m collector.policy_news backfill --from 20261004 --to 20261007"


def test_financial_years(plan_db):
    """TC-FP-04 · 재무 — 해마다 보고서 × 묶음(기록에 나온 것 전부) · 실패 · 부르지 않은 묶음은 받을 것 ·
    「자료 없음」 만 남은 해는 마감 전이라 아직 공개 전(받을 것이 아니다) · 명령은 해 단위."""
    out = fp.plan("financial", "2022-01-01", "2026-10-08", now=BEFORE_13)
    by = {y["year"]: y for y in out["years"]}
    assert [by[y]["state"] for y in (2022, 2023, 2024, 2025, 2026)] == ["partial", "missing", "done", "pending", "error"]
    assert by[2025]["empty"] == 1 and "마감 전" in by[2025]["note"] and by[2024]["expected"] == 2
    assert out["todo"] == 3 and out["counts"]["pending"] == 1
    assert out["command"] == "python -m collector.financials backfill --from-year 2022 --to-year 2026"
    assert "days" not in out


def test_inputs_and_nothing_to_fetch(plan_db):
    """TC-FP-05 · 입력 — 모르는 종류 · 끝 < 시작 · 400일 초과는 422 · 오늘 뒤는 오늘까지 · 받을 것이 없으면 명령 없음."""
    for args in (("rumor", "2026-10-01", None), ("price", "2026-10-05", "2026-10-01"), ("price", "2025-01-01", "2026-10-08"),
                 ("price", "10/01", None), ("price", None, None)):
        with pytest.raises(fp.FetchPlanError) as e:
            fp.plan(*args, now=BEFORE_13)
        assert e.value.status == 422, args
    out = fp.plan("price", "2026-09-28", "2026-12-31", now=BEFORE_13)
    assert out["to"] == "2026-10-08" and out["clipped_to_today"] is True
    none = fp.plan("price", "2026-09-28", "2026-10-01", now=BEFORE_13)
    assert (none["todo"], none["command"], none["todo_range"]) == (0, None, None)
    assert none["note"].startswith("받을 것이 없습니다")


def test_routes_admin_only_and_errors(plan_db, monkeypatch, tmp_path):
    """TC-FP-06 · 라우트 — 관리자만(일반 사용자 403) · 잘못은 422 그대로 · 수집 DB 가 없으면 503 · 출처 표에 종류 넷 + 언론사 기사."""
    app = FastAPI()
    app.include_router(data_routes.router)
    c = TestClient(app)
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "roles": ["user"]}
    assert c.get("/api/data/fetch-plan", params={"kind": "price", "from": "2026-10-01"}).status_code == 403
    assert c.get("/api/data/fetch-sources").status_code == 403
    app.dependency_overrides[get_current_user] = lambda: {"id": "a1", "roles": ["admin"]}
    src = c.get("/api/data/fetch-sources").json()
    assert [k["kind"] for k in src["kinds"]] == ["price", "disclosure", "policy_news", "financial"]
    assert src["extra"][0]["label"] == "언론사 기사" and "본문 받지 않음" in src["extra"][0]["terms"]
    r = c.get("/api/data/fetch-plan", params={"kind": "price", "from": "2026-10-05", "to": "2026-10-01"})
    assert r.status_code == 422 and "앞이다" in r.json()["detail"]
    ok = c.get("/api/data/fetch-plan", params={"kind": "price", "from": "2026-09-28", "to": "2026-10-02"})
    assert ok.status_code == 200 and ok.json()["unit"] == "day"
    monkeypatch.setenv(collector_db.ENV_DB_PATH, str(tmp_path / "없음.sqlite3"))
    r = c.get("/api/data/fetch-plan", params={"kind": "price", "from": "2026-10-01"})
    assert r.status_code == 503


def test_price_received_before_publish_time_is_done(plan_db):
    """TC-FP-07 · 받은 기록이 공개 시각보다 먼저 — 출처가 약속(다음 영업일 13시)보다 일찍 내줘 이미 받은 날은 13시 전이어도 받은 날이다
    (2026-10-08 12:30 회차가 10-07 시세를 받았다). 받지 않은 날만 「아직 공개 전」."""
    import sqlite3
    conn = sqlite3.connect(plan_db)
    conn.execute("INSERT INTO ingest_day (source, bas_dt, status, rows, attempts, updated_at, message) "
                 "VALUES ('portal', '20261007', 'done', 2800, 1, '2026-10-08T12:30:05+09:00', '')")
    conn.commit()
    conn.close()
    st = _states(fp.plan("price", "2026-10-06", "2026-10-08", now=BEFORE_13))
    assert st["2026-10-07"] == "done" and st["2026-10-08"] == "pending" and st["2026-10-06"] == "error"
