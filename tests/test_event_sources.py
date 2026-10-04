"""금융 일정 더하기 시험 (TC-EV) — `collector/event_sources.py` (목표 기능 ① W7 · 설계서 5.2.4 <표 15>).

여기서 지키는 것 —
1. 한국은행 「통화정책방향 결정회의 일정」 한 해를 읽는다 — 아직 발표 전인 해는 빈 목록(있던 행을 지우지 않는다).
2. 연준 「Meeting calendars」 를 해마다 읽고 회의 둘째 날을 쓴다 · 경제전망(*) 표시 · 달을 넘는 회의(「Apr/May 30-1」).
3. 정기보고서 법정 기한 — 사업 90일 · 분기 · 반기 45일 · 말일이 토요일 · 일요일 · 공휴일이면 다음 날(민법 제161조).
4. 실적 일정 — 잠정실적 · 손익구조 변동 공시의 접수일 · 정정 공시는 새 발표로 세지 않는다 · 같은 종목 같은 날은 하나.
5. 공식 일정은 7일 안이면 다시 받지 않고, 한 출처가 실패해도 다른 출처는 넣는다.
6. 일정 API 는 `kind` 를 비우면 화면이 그리는 네 종류만, 새 종류는 이름이나 all 로.

네트워크 · 실제 수집 DB 를 쓰지 않는다.
"""
from __future__ import annotations

from datetime import date

import pytest

from collector import db, disclosure as D, event_sources as E

BOK_PAGE = """<html><div class="h-group">
	<h3>2026년</h3><select name="pYear"><option value="2027">2027년</option></select></div>
<table><tr><td>01월 15일(목)</td><td>결정문</td></tr><tr><td>04월 10일(금)</td></tr><tr><td>11월 26일(목)</td></tr></table></html>"""

BOK_EMPTY = """<html><div class="h-group"><h3>2027년</h3></div><table><tr><td>자료가 없습니다</td></tr></table></html>"""

FOMC_PAGE = """<html><h4>2026 FOMC Meetings</h4>
<div>January</div><div>27-28</div><div>Statement:</div>
<div>March</div><div>17-18*</div>
<div>Apr/May</div><div>30-1</div>
<p>(Released February 18, 2026)</p>
<h4>2027 FOMC Meetings</h4>
<div>January</div><div>26-27</div>
<div>December</div><div>7-8*</div>
<p>* Meeting associated with a Summary of Economic Projections.</p></html>"""


def test_parse_bok_year_and_unpublished_year():
    """TC-EV-01 · 한 해의 회의일 셋 · 아직 발표 전인 해는 빈 목록."""
    year, days = E.parse_bok(BOK_PAGE)
    assert year == 2026 and days == [date(2026, 1, 15), date(2026, 4, 10), date(2026, 11, 26)]
    assert E.parse_bok(BOK_EMPTY) == (2027, [])


def test_parse_fomc_second_day_sep_and_cross_month():
    """TC-EV-02 · 회의 둘째 날 · 경제전망 표시 · 달을 넘는 회의는 둘째 날의 달로."""
    got = E.parse_fomc(FOMC_PAGE)
    assert got == [(date(2026, 1, 28), False), (date(2026, 3, 18), True), (date(2026, 5, 1), False),
                   (date(2027, 1, 27), False), (date(2027, 12, 8), True)]


def test_report_deadlines_move_past_weekend_and_holiday():
    """TC-EV-03 · 2026 3분기보고서 기한 11-14 는 토요일 → 11-16 · 공휴일이 끼면 그다음 날."""
    ev = {e[6]: e for e in E.report_deadlines([2026], [], "x")}
    assert ev["3분기보고서 제출 기한(12월 결산)"][2] == "2026-11-16"
    assert "민법 제161조" in ev["3분기보고서 제출 기한(12월 결산)"][7]
    assert ev["사업보고서 제출 기한(12월 결산)"][2] == "2026-03-31"           # 2025-12-31 + 90일 = 3-31(화)
    assert ev["반기보고서 제출 기한(12월 결산)"][2] == "2026-08-14"
    moved = {e[6]: e for e in E.report_deadlines([2026], [date(2026, 8, 14)], "x")}
    assert moved["반기보고서 제출 기한(12월 결산)"][2] == "2026-08-17"        # 금요일이 공휴일이면 월요일로
    assert E.legal_deadline(date(2026, 5, 15), []) == date(2026, 5, 15)


@pytest.fixture()
def conn(tmp_path):
    c = db.connect(tmp_path / "m.sqlite3")
    yield c
    c.close()


def _disc(conn, rcept_no, report_nm, code="114090", name="GKL"):
    D.upsert_rows(conn, [D.normalize_item({"corp_code": "00000001", "corp_name": name, "stock_code": code,
                                            "corp_cls": "Y", "report_nm": report_nm, "rcept_no": rcept_no,
                                            "rcept_dt": rcept_no[:8]}, "I", fetched_at="2026-10-04T19:00:00+09:00")])


def test_earnings_events_skip_corrections_and_dedupe(conn):
    """TC-EV-04 · 잠정실적 · 손익구조 변동은 그날의 실적 일정 · 정정은 빼고 · 같은 종목 같은 날은 하나."""
    _disc(conn, "20261002000001", "영업(잠정)실적(공정공시)")
    _disc(conn, "20261002000002", "연결재무제표기준영업(잠정)실적(공정공시)")          # 같은 날 · 같은 종목
    _disc(conn, "20261010000003", "[기재정정]영업(잠정)실적(공정공시)")                 # 정정 — 새 발표 아님
    _disc(conn, "20260226000004", "매출액또는손익구조30%(대규모법인은15%)이상변동", code="034230", name="파라다이스")
    _disc(conn, "20261002000005", "현금ㆍ현물배당결정")                                  # 실적 아님
    ev = E.earnings_events(conn, "x")
    assert sorted((e[2], e[5]) for e in ev) == [("2026-02-26", "034230"), ("2026-10-02", "114090")]
    assert all(e[1] == "earnings" and e[8] == "confirmed" and e[9] == "dart" for e in ev)


def test_refresh_skips_within_seven_days_and_survives_one_failure(conn):
    """TC-EV-05 · 한 출처가 실패해도 다른 출처는 넣고 · 7일 안이면 다시 받지 않는다 · 빈 해는 있던 행을 지우지 않는다."""
    calls = []

    def fake(url):
        calls.append(url)
        if "federalreserve" in url:
            raise OSError("연결 실패")
        return BOK_PAGE if "pYear=2026" in url else BOK_EMPTY

    out = E.refresh_policy_meetings(conn, date(2026, 10, 4), force=True, fetch=fake)
    assert out["bok"] == 3 and out["fomc"] == 0 and out["errors"] == 1
    n = len(calls)
    assert E.refresh_policy_meetings(conn, date(2026, 10, 4), fetch=fake) == {"skipped": 1}
    assert len(calls) == n
    ev = E.policy_events(conn, date(2026, 10, 4), "x")
    assert [(e[2], e[8]) for e in ev] == [("2026-01-15", "confirmed"), ("2026-04-10", "confirmed"),
                                          ("2026-11-26", "scheduled")]


def test_calendar_api_default_kinds_and_all(tmp_path, monkeypatch):
    """TC-EV-06 · 일정 API — kind 를 비우면 화면이 그리는 네 종류만 · all 이나 이름으로 새 종류."""
    from app.services import collector_db, market_calendar as mc
    from collector import market_calendar as cal
    path = tmp_path / "collector" / "market.sqlite3"
    path.parent.mkdir()
    c = db.connect(path)
    c.execute("INSERT INTO holiday_kasi VALUES ('2026-10-09', '한글날', 'Y', '01', 1, 'x')")
    for y in range(2020, 2028):
        c.execute("INSERT OR IGNORE INTO holiday_kasi VALUES (?, '신정', 'Y', '01', 1, 'x')", (f"{y}-01-01",))
    _disc(c, "20261002000001", "영업(잠정)실적(공정공시)")
    cal.build(c, fetch=False, today=date(2026, 10, 4), quiet=True)
    c.close()
    monkeypatch.setenv(collector_db.ENV_DB_PATH, str(path))
    plain = mc.events(date(2026, 10, 1), date(2026, 11, 30))
    assert {e["kind"] for e in plain["events"]} <= set(mc.DEFAULT_KINDS)
    every = mc.events(date(2026, 10, 1), date(2026, 11, 30), "all")
    kinds = {e["kind"] for e in every["events"]}
    assert {"earnings", "report_deadline"} <= kinds
    named = mc.events(date(2026, 10, 1), date(2026, 11, 30), "earnings")
    assert [e["title"] for e in named["events"]] == ["GKL 잠정실적 발표"]
