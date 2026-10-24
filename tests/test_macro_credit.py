"""거시 신용(신용 스프레드) 시험 (TC-MC) — `app/services/macro_credit.py` (API-RISK-02 · ④-2 · 2026-10-13).

여기서 지키는 것 —
1. 항목 코드 표는 수집기(`collector/ecos.py` SERIES)와 같다 — 앱 이미지에 collector/ 가 없어 두 곳에 있다(SSoT 를 시험으로).
2. 스프레드는 **같은 날** 둘 다 있는 날만 · bp(×100) · 위치 = 같거나 낮은 날의 몫.
3. 응답 — 최근 값 · 보이는 기간만큼의 이력 · 10년 통계 · 한 달 변화 · 문장 · 출처 표시(약관 제7조②).
4. 자료가 없으면 「아직 받지 못함」 — 일반 사용자에겐 표 이름 · 명령이 없고 관리자에게만 할 일.
5. 수집 DB 는 읽기 전용(mode=ro)으로만 연다.

실제 수집 DB 를 쓰지 않는다 — 임시 SQLite 를 COLLECTOR_DB_PATH 로 가리킨다.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta

import pytest

from app.services import macro_credit as M
from collector import ecos as E


@pytest.fixture()
def dbfile(tmp_path, monkeypatch):
    p = tmp_path / "market.sqlite3"
    c = sqlite3.connect(p)
    c.executescript(E.ECOS_SERIES_DDL)
    c.close()
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(p))
    return p


def _fill(p, rows):
    c = sqlite3.connect(p)
    c.executemany("INSERT INTO ecos_series (stat_code, item_code, cycle, date, value, unit, item_name, fetched_at, "
                  "updated_at) VALUES ('817Y002', ?, 'D', ?, ?, '연%', '', 't', 't')", rows)
    c.commit()
    c.close()


def _weekdays(end: date, n: int):
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


def test_item_codes_match_the_collector():
    """TC-MC-01 · 앱의 항목 표 = 수집기의 항목 표(열쇠 · 코드 · 이름) · 표 코드 · 출처 표시."""
    assert [(k, c, n) for k, c, n in M.ITEMS] == [(k, c, n) for k, c, n, _f in E.SERIES]
    assert M.STAT == E.STAT and M.ATTRIBUTION == E.ATTRIBUTION


def test_spread_same_day_only_bp_and_rank():
    """TC-MC-02 · 둘 다 있는 날만 · bp · 위치는 같거나 낮은 날의 몫."""
    a = {"2026-10-07": 4.644, "2026-10-08": 4.651, "2026-10-12": 4.602}
    b = {"2026-10-07": 3.961, "2026-10-12": 3.921, "2026-10-13": 3.9}
    assert M.spread_series(a, b) == [("2026-10-07", 68.3), ("2026-10-12", 68.1)]
    assert M.pct_rank([10, 20, 30, 40], 20) == 50.0 and M.pct_rank([10, 20, 30, 40], 5) == 0.0
    assert M.pct_rank([10, 20, 30, 40], 40) == 100.0


def test_read_macro_latest_history_stats_change_and_attribution(dbfile):
    """TC-MC-03 · 마지막 날 · 보이는 기간(3년) 이력 · 10년 통계 · 20거래일 변화 · 문장 · 출처."""
    today = date(2026, 10, 13)
    days = _weekdays(date(2026, 10, 12), 2700)          # 10년 넘게
    rows = []
    for i, d in enumerate(days):
        ds = d.isoformat()
        rows += [("010200000", ds, 3.0), ("010300000", ds, 3.0 + 0.5 + (i % 100) / 1000),
                 ("010320000", ds, 9.0), ("010502000", ds, 3.2), ("010503000", ds, 3.5),
                 ("010210000", ds, 3.4)]
    _fill(dbfile, rows)
    out = M.read_macro(years=3, today=today)
    assert out["available"] and out["as_of"] == "2026-10-12" and out["source"] == M.ATTRIBUTION and out["region"] == "KR"
    aa = next(s for s in out["spreads"] if s["key"] == "aa")
    assert aa["latest"]["date"] == "2026-10-12"
    assert aa["history"][0]["date"] >= (today - timedelta(days=366 * 3)).isoformat()
    assert aa["stats"]["from"] <= (today - timedelta(days=366 * 10)).isoformat()
    assert aa["change"]["days"] == 20 and aa["change"]["from"] == days[-21].isoformat()
    assert "아래에서" in aa["sentence"] and M.ATTRIBUTION in aa["points"][-1]
    assert next(s for s in out["spreads"] if s["key"] == "bbb")["latest"]["bp"] == 600.0
    assert next(s for s in out["spreads"] if s["key"] == "cp_cd")["latest"]["bp"] == 30.0
    assert {r["key"] for r in out["rates"]} == {k for k, _c, _n in M.ITEMS}


def test_missing_or_empty_table_and_admin_hint(dbfile, tmp_path, monkeypatch):
    """TC-MC-04 · 비었으면 「아직 받지 못함」 · 일반 사용자 답엔 표 이름 · 명령 없음 · 관리자만 할 일 · 표가 아예 없어도 같다."""
    out = M.read_macro()
    text = json.dumps(out, ensure_ascii=False)
    assert out["available"] is False and "받지 못했습니다" in out["reason"]
    assert "ecos_series" not in text and "python" not in text and "admin_hint" not in out
    assert "python -m collector.ecos" in M.read_macro(admin=True)["admin_hint"]
    bare = tmp_path / "bare.sqlite3"
    sqlite3.connect(bare).close()
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(bare))
    assert M.read_macro()["available"] is False


def test_opens_collector_db_read_only(dbfile, monkeypatch):
    """TC-MC-05 · 수집 DB 는 mode=ro 로만 연다(쓰기 연결이 WAL 보조 파일을 지워 앱을 멈춘 적이 있다 — DF-81)."""
    seen = []
    real = sqlite3.connect

    def spy(*a, **k):
        seen.append(a[0])
        return real(*a, **k)
    monkeypatch.setattr(M.sqlite3, "connect", spy)
    M.read_macro()
    assert seen and all("mode=ro" in s for s in seen)


def test_years_bounds():
    """TC-MC-06 · 보이는 기간은 1 ~ 10년."""
    for bad in (0, 11):
        with pytest.raises(M.MacroError) as ei:
            M.read_macro(years=bad)
        assert ei.value.status == 422


# ── 라우트 ──────────────────────────────────────────────────────────────────
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.lib.session import get_current_user  # noqa: E402
from app.routes import risk as rr  # noqa: E402


def _client(roles):
    app = FastAPI()
    app.include_router(rr.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "email": "t@t", "roles": roles}
    return TestClient(app)


def test_route_macro_admin_split_and_bounds(dbfile):
    """TC-MC-07 · 비었을 때 일반 사용자 답엔 할 일이 없고 관리자 답에만 · 햇수 0 · 11 은 422."""
    r = _client([]).get("/api/risk/macro")
    assert r.status_code == 200 and r.json()["available"] is False and "admin_hint" not in r.json()
    assert "admin_hint" in _client(["admin"]).get("/api/risk/macro").json()
    for bad in (0, 11):
        assert _client([]).get(f"/api/risk/macro?years={bad}").status_code == 422


def test_route_macro_needs_login():
    """TC-MC-08 · 로그인하지 않으면 401."""
    app = FastAPI()
    app.include_router(rr.router)
    assert TestClient(app).get("/api/risk/macro").status_code == 401
