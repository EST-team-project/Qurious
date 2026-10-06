"""한 달 달력 요약 · 그날 목록 시험 (TC-CN) — `app/services/market_calendar.py` · `GET /api/calendar/events/summary` · `events` 의
쪽 넘기기(목표 기능 ① W7 · 일정 2판 결정 안 B · DF-66).

여기서 지키는 것 —
1. 한 달 요약은 날짜 × 종류 개수 + 시장 전체 일정(휴장 · 만기 · 금통위 · FOMC · 보고서 기한)의 이름만 싣는다 — 종목 일정은
   개수만. 일정이 없는 날은 싣지 않는다 · 종류를 비우면 열 종류 모두.
2. 종목 일정이 한 날 수천 건이어도 요약의 크기는 날짜 수 × 종류 수로 그대로다(3월 주총 몰림 · DF-66).
3. 그날 목록 — 쪽 넘기기(offset · limit · total · truncated) · 회사 이름 찾기(글자 그대로 · 「%」 도 글자) · 내 종목을 맨 위에.
4. 지금 화면이 받는 기본(종류 넷 · 칸 이름)은 그대로다.

수집기의 실제 스키마로 픽스처 DB 를 만들고(일정 행은 직접 넣는다), 네트워크 · 실제 수집 DB 를 쓰지 않는다.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes import calendar as calendar_routes
from app.services import collector_db
from app.services import market_calendar as M
from collector import db

AT = "2026-10-05T14:00:00+09:00"


def _ev(eid, kind, d, title, symbol="", t=""):
    return (eid, kind, d, t, "KRX" if not symbol else "", symbol, title, "", "confirmed", "test", "", AT)


def make_db(path, extra=()):
    conn = db.connect(path)
    conn.execute("BEGIN")
    conn.executemany("INSERT INTO market_calendar (cal_date, is_trading_day, reason, basis, note, updated_at) "
                     "VALUES (?, ?, ?, 'observed', '', ?)",
                     [(f"2026-03-{d:02d}", 0 if d in (1, 2, 7, 8) else 1, "", AT) for d in range(1, 32)])
    rows = [
        _ev("closure:2026-03-02", "market_closure", "2026-03-02", "휴장 — 대체공휴일(삼일절)"),
        _ev("expiry:2026-03-12", "deriv_expiry", "2026-03-12", "코스피200 선물 · 옵션 동시 만기"),
        _ev("fomc:2026-03-18", "fomc", "2026-03-18", "미국 FOMC 회의 결과 발표(연방기금금리)"),
        _ev("earn:1", "earnings", "2026-03-03", "가나 잠정실적 발표", "000001"),
        _ev("earn:2", "earnings", "2026-03-03", "다라 잠정실적 발표", "000002"),
        _ev("agm:1", "agm", "2026-03-26", "KB금융 정기주주총회", "105560", "10:00"),
        _ev("agm:2", "agm", "2026-03-26", "동화약품 정기주주총회", "000020"),
        _ev("agm:3", "agm", "2026-03-26", "하이트진로 정기주주총회", "000080"),
        _ev("agm:4", "agm", "2026-03-26", "하이트진로홀딩스 정기주주총회", "000140"),
        _ev("agm:5", "agm", "2026-03-26", "DL 정기주주총회", "000210"),
        _ev("ex:1", "dividend_ex", "2026-03-26", "백퍼센트% 배당락일", "000300"),
        _ev("ex:2", "dividend_ex", "2026-03-26", "삼성전자 배당락일", "005930"),
        _ev("agm:6", "agm", "2026-03-31", "삼성전자 정기주주총회", "005930"),
        _ev("rec:1", "dividend_record", "2026-03-31", "삼성전자 배당 기준일", "005930"),
    ] + list(extra)
    conn.executemany("INSERT INTO market_event (event_id, kind, event_date, event_time, market, symbol, title, detail, "
                     "confidence, source, source_ref, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.execute("COMMIT")
    conn.close()


@pytest.fixture
def market(tmp_path, monkeypatch):
    path = tmp_path / "market.sqlite3"
    make_db(path)
    monkeypatch.setenv(collector_db.ENV_DB_PATH, str(path))
    return path


def test_summary_counts_by_day_and_kind_with_market_names(market):
    """TC-CN-01 · 날짜 × 종류 개수 · 시장 전체 일정은 이름까지 · 종목 일정은 개수만 · 빈 날은 없음 · 종류를 비우면 열 모두."""
    j = M.events_summary(date(2026, 3, 1), date(2026, 3, 31))
    assert j["kind"] == list(M.EVENT_KINDS) and set(j["market_kinds"]) <= set(M.MARKET_KINDS)
    by = {d["date"]: d for d in j["days"]}
    assert sorted(by) == ["2026-03-02", "2026-03-03", "2026-03-12", "2026-03-18", "2026-03-26", "2026-03-31"]
    assert by["2026-03-26"]["counts"] == {"agm": 5, "dividend_ex": 2} and by["2026-03-26"]["total"] == 7
    assert by["2026-03-26"]["market_events"] == []                       # 종목 일정은 이름 없이 개수만
    assert [(m["kind"], m["title"]) for m in by["2026-03-18"]["market_events"]] == [("fomc", "미국 FOMC 회의 결과 발표(연방기금금리)")]
    assert by["2026-03-18"]["weekday"] == "수" and j["totals"]["agm"] == 6 and j["total"] == 14
    only = M.events_summary(date(2026, 3, 1), date(2026, 3, 31), "agm")
    assert only["market_kinds"] == [] and [d["date"] for d in only["days"]] == ["2026-03-26", "2026-03-31"]


def test_summary_size_does_not_grow_with_events_and_range_cap(tmp_path, monkeypatch):
    """TC-CN-02 · 한 날 3,000건이 몰려도 요약은 날짜 · 종류 수만큼 · 400일 넘는 구간은 422(DF-66)."""
    path = tmp_path / "busy.sqlite3"
    make_db(path, extra=[_ev(f"agm:x{i}", "agm", "2026-03-27", f"회사{i} 정기주주총회", f"{i:06d}") for i in range(3000)])
    monkeypatch.setenv(collector_db.ENV_DB_PATH, str(path))
    j = M.events_summary(date(2026, 3, 1), date(2026, 3, 31))
    day = next(d for d in j["days"] if d["date"] == "2026-03-27")
    assert day["counts"] == {"agm": 3000} and day["market_events"] == [] and len(j["days"]) == 7
    assert j["total"] == 3014
    with pytest.raises(M.CalendarUnavailable) as e:
        M.events_summary(date(2026, 1, 1), date(2027, 3, 1))
    assert e.value.status_code == 422


def test_day_list_paging_search_and_mine_first(market):
    """TC-CN-03 · 그날 목록 — 쪽 넘기기 · 회사 이름 찾기(「%」 도 글자 그대로) · 내 종목 맨 위 · 틀린 종목 코드는 422."""
    d = date(2026, 3, 26)
    p1 = M.events(d, d, "agm,dividend_ex", limit=3, offset=0)
    p3 = M.events(d, d, "agm,dividend_ex", limit=3, offset=6)
    assert (p1["total"], len(p1["events"]), p1["truncated"]) == (7, 3, True)
    assert (len(p3["events"]), p3["truncated"], p3["offset"]) == (1, False, 6)
    hits = M.events(d, d, "agm", q="하이트")
    assert [e["title"] for e in hits["events"]] == ["하이트진로 정기주주총회", "하이트진로홀딩스 정기주주총회"]
    assert [e["title"] for e in M.events(d, d, "dividend_ex", q="%")["events"]] == ["백퍼센트% 배당락일"]
    mine = M.events(d, d, "agm,dividend_ex", first="005930,105560", limit=3)
    assert [e["symbol"] for e in mine["events"][:2]] == ["105560", "005930"]   # 내 종목끼리는 날짜 · 종류 · 종목 차례
    assert all(e["mine"] for e in mine["events"][:2]) and not mine["events"][2]["mine"]
    with pytest.raises(M.CalendarUnavailable) as e:
        M.events(d, d, "agm", first="5930")
    assert e.value.status_code == 422


def test_default_events_unchanged_and_api_routes(market):
    """TC-CN-04 · 기본(종류 넷 · 칸 이름)은 그대로 · 요약 API 는 로그인 없이 · 모르는 종류는 422."""
    j = M.events(date(2026, 3, 1), date(2026, 3, 31))
    assert {e["kind"] for e in j["events"]} == {"market_closure", "deriv_expiry", "dividend_ex", "dividend_record"}
    assert {"from", "to", "kind", "symbol", "events", "total", "truncated", "calendar", "source", "as_of"} <= set(j)
    app = FastAPI()
    app.include_router(calendar_routes.router)
    c = TestClient(app)
    r = c.get("/api/calendar/events/summary", params={"from": "2026-03-01", "to": "2026-03-31"})
    assert r.status_code == 200 and r.json()["totals"]["agm"] == 6
    assert c.get("/api/calendar/events/summary", params={"kind": "ipo"}).status_code == 422
    r = c.get("/api/calendar/events", params={"from": "2026-03-26", "to": "2026-03-26", "kind": "agm", "limit": 2,
                                              "offset": 2, "first": "005930"})
    assert r.status_code == 200 and r.json()["offset"] == 2 and len(r.json()["events"]) == 2
