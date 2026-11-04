"""금융 일정 더하기 시험 (TC-EV) — `collector/event_sources.py` (목표 기능 ① W7 · 설계서 5.2.4 <표 15>).

여기서 지키는 것 —
1. 한국은행 「통화정책방향 결정회의 일정」 한 해를 읽는다 — 아직 발표 전인 해는 빈 목록(있던 행을 지우지 않는다).
2. 연준 「Meeting calendars」 를 해마다 읽고 회의 둘째 날을 쓴다 · 경제전망(*) 표시 · 달을 넘는 회의(「Apr/May 30-1」).
3. 정기보고서 법정 기한 — 사업 90일 · 분기 · 반기 45일 · 말일이 토요일 · 일요일 · 공휴일이면 다음 날(민법 제161조).
4. 실적 일정 — 잠정실적 · 손익구조 변동 공시의 접수일 · 정정 공시는 새 발표로 세지 않는다 · 같은 종목 같은 날은 하나.
5. 공식 일정은 7일 안이면 다시 받지 않고, 한 출처가 실패해도 다른 출처는 넣는다.
6. 일정 API 는 `kind` 를 비우면 화면이 그리는 네 종류만, 새 종류는 이름이나 all 로.
7. (2026-11-03 · ①-23 E) 국가데이터처 보도계획 — 연도는 머리에서만 · 요일 대조 · 행사 · 포상은 뺀다 · 윤년(TC-EV-07).
8. 미국 BLS · BEA 달력 — 미국 날짜 · 동부 시각 그대로(UTC 는 동부로) · 연말 경계(TC-EV-08).
9. 경제지표 받기 — 출처마다 7일 · 한 출처 실패는 삼키고 · 멱등 · 옮겨진 앞날 행 지움 · 빈 응답은 안 지움 · 달력 단계는 안 멈춤(TC-EV-09 · 10).
10. (F-lite) 증권신고서(지분증권) — 청약 기간 · 납입 · 철회 · 호출 수 줄이기 · 하루 한도 멈춤 · 멱등(TC-EV-11 · 12).
11. 주말 날짜는 받은 그대로(옮기지 않는다)(TC-EV-13).

네트워크 · 실제 수집 DB 를 쓰지 않는다(새 받기 함수는 가짜 응답만 받는다).
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


# ── 경제지표 발표 일정(①-23 E · 2026-11-03 S195) — collector/econ_calendar.py ───────────────────────────────
# 픽스처는 실제 페이지 복사가 아니라 **합성 글**이다(2026-11-03 에 받은 응답의 모양만 본떴다).
from collector import econ_calendar as EC, offering as OF  # noqa: E402


def _kostat_page(year_head: str, rows: list) -> str:
    trs = "".join(f'<tr class="tr-notice"><td class="center" >{d}</td><td class="center" >{t}</td><td>{title}</td>'
                  f'<td class="center" >{dept}</td><td class="center" ></td></tr>' for d, t, title, dept in rows)
    return (f"<html><form><h3>{year_head}</h3></form><table><thead><tr><th>보도일자</th><th>보도시간</th><th>보도자료명</th>"
            f"</tr></thead><tbody>{trs}</tbody></table></html>")


KOSTAT_PAGE = _kostat_page("2026년 전체 보도계획", [
    ("11.03.( 화 )", "08:00", "2026년 10월 소비자물가동향", "물가동향과"),
    ("11.03.( 화 )", "08:00", "2026년 10월 소비자물가동향", "물가동향과"),        # 같은 줄 두 번 — 하나로
    ("11.04.( 수 )", "14:00", "국가데이터처, 중국 국가통계청과 양자협력회의 개최", "국제협력담당관"),   # 기준 연도로 시작하지 않음
    ("11.02.( 월 )", "16:30", "2026년도 대규모 통계조사 업무 유공 포상 전수식 개최", "인구총조사과"),  # 행사
    ("11.05.( 화 )", "12:00", "2025년 다문화인구동태 통계", "인구동향과"),           # 요일이 다르다(11-05 는 목) — 버린다
    ("12.31.( 목 )", "12:00", "2026년 11월 산업활동동향", "산업동향과"),             # 연말
    ("01.02.( 금 )", "", "2025 인구주택총조사(표본) 결과", "인구총조사과"),           # 시각 빈칸 · 「2025 」 로 시작
])


def test_parse_kostat_year_weekday_and_non_statistics():
    """TC-EV-07 · 국가데이터처 보도계획 — 연도는 머리에서만 · 요일이 다르면 버림 · 행사 · 기관 보도는 뺌 · 같은 줄은 하나 · 연도 머리가 없으면 아무것도 안 만든다."""
    year, rows, dropped = EC.parse_kostat(KOSTAT_PAGE)
    assert year == 2026
    assert rows == [(date(2026, 1, 2), "", "2025 인구주택총조사(표본) 결과", "인구총조사과"),
                    (date(2026, 11, 3), "08:00", "2026년 10월 소비자물가동향", "물가동향과"),
                    (date(2026, 12, 31), "12:00", "2026년 11월 산업활동동향", "산업동향과")]
    assert any("요일 다름" in d for d in dropped) and any("개최" in d for d in dropped) and len(dropped) == 3
    assert EC.parse_kostat(KOSTAT_PAGE.replace("<h3>2026년 전체 보도계획</h3>", "<h3>보도계획</h3>")) == (None, [], [])
    # 윤년 — 2028-02-29(화)는 있는 날 · 2027-02-29 는 없는 날이라 만들지 않는다(규칙으로 옮기지 않는다)
    leap = EC.parse_kostat(_kostat_page("2028년 2월 보도계획", [("02.29.( 화 )", "08:00", "2028년 1월 고용동향", "고용통계과")]))
    assert leap[1] == [(date(2028, 2, 29), "08:00", "2028년 1월 고용동향", "고용통계과")]
    none = EC.parse_kostat(_kostat_page("2027년 2월 보도계획", [("02.29.( 월 )", "08:00", "2027년 1월 고용동향", "고용통계과")]))
    assert none[1] == [] and "날짜 못 읽음" in none[2][0]


BLS_ICS = (
    "BEGIN:VCALENDAR\r\nX-WR-TIMEZONE:US-Eastern\r\nBEGIN:VTIMEZONE\r\nTZID:US-Eastern\r\nBEGIN:DAYLIGHT\r\n"
    "DTSTART:20070311T020000\r\nEND:DAYLIGHT\r\nEND:VTIMEZONE\r\n"
    "BEGIN:VEVENT\r\nUID:a\r\nDTSTART;TZID=US-Eastern:20261204T083000\r\nSUMMARY:Employment Situation\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nUID:b\r\nDTSTART;TZID=US-Eastern:20261231T100000\r\n"
    "SUMMARY:Metropolitan Area Employment and Unemployment\r\n  (Monthly)\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nUID:c\r\nDTSTART;TZID=US-Eastern:20261204T083000\r\nSUMMARY:Employment Situation\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nUID:d\r\nSUMMARY:No date at all\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")

BEA_ICS = (
    "BEGIN:VCALENDAR\nTZID:America/New_York\n"
    "BEGIN:VEVENT\nSUMMARY:Personal Income and Outlays\\, June 2026\nDTSTART;VALUE=DATE-TIME:20260731T123000Z\nEND:VEVENT\n"
    "BEGIN:VEVENT\nSUMMARY:Gross Domestic Product\\, 3rd Quarter 2026 (Advance Estima\n te)\n"
    "DTSTART;VALUE=DATE-TIME:20261126T133000Z\nEND:VEVENT\n"
    "BEGIN:VEVENT\nSUMMARY:Late evening release\nDTSTART;VALUE=DATE-TIME:20270101T013000Z\nEND:VEVENT\n"
    "BEGIN:VEVENT\nSUMMARY:All day item\nDTSTART;VALUE=DATE:20260229\nEND:VEVENT\n"
    "BEGIN:VEVENT\nSUMMARY:Leap day item\nDTSTART;VALUE=DATE:20280229\nEND:VEVENT\nEND:VCALENDAR\n")


def test_parse_ics_keeps_us_dates_and_eastern_time():
    """TC-EV-08 · 미국 일정 — BLS 는 동부 벽시계 그대로(VTIMEZONE 안 DTSTART 는 무시) · BEA 의 UTC 는 동부로 바꾼다(여름 12:30Z ·
    겨울 13:30Z 모두 08:30) · 01:30Z 는 미국 날짜로 하루 앞(2026-12-31 20:30) — 한국 날짜로 옮기지 않는다 · 접힌 줄 · 날짜 없는 일정 ·
    없는 날짜(2026-02-29)는 버리고 · 같은 일정은 하나."""
    assert EC.parse_ics(BLS_ICS) == [(date(2026, 12, 4), "08:30", "Employment Situation"),
                                     (date(2026, 12, 31), "10:00", "Metropolitan Area Employment and Unemployment (Monthly)")]
    assert EC.parse_ics(BEA_ICS) == [(date(2026, 7, 31), "08:30", "Personal Income and Outlays, June 2026"),
                                     (date(2026, 11, 26), "08:30", "Gross Domestic Product, 3rd Quarter 2026 (Advance Estimate)"),
                                     (date(2026, 12, 31), "20:30", "Late evening release"),
                                     (date(2028, 2, 29), "", "Leap day item")]


def _econ_fake(calls: list, *, fail: str = "", empty: str = "", bls: str = BLS_ICS):
    def fake(url, data=None):
        calls.append(url)
        if fail and fail in url:
            raise OSError("연결 실패")
        if empty and empty in url:
            return "BEGIN:VCALENDAR\nEND:VCALENDAR\n"
        if "mods.go.kr" in url:
            assert data and b"oa_mm=ALL" in data
            return KOSTAT_PAGE
        return bls if "bls.gov" in url else BEA_ICS
    return fake


def test_econ_refresh_per_source_failure_seven_days_and_moves(conn):
    """TC-EV-09 · 경제지표 받기 — 한 출처가 실패해도 나머지는 넣고 · 출처마다 7일 안이면 건너뛰고(실패한 출처는 다음에 다시) ·
    두 번 받아도 늘지 않고(멱등) · 옮겨진 발표의 옛 앞날 행은 지우되 지난 행은 두고 · 빈 응답은 아무것도 지우지 않는다."""
    calls: list = []
    today = date(2026, 11, 3)
    out = EC.refresh_econ_releases(conn, today, force=True, fetch=_econ_fake(calls, fail="bea.gov"), sleep=lambda s: None)
    assert out["kostat"] == 3 and out["bls"] == 2 and out["bea"] == "error" and out["errors"] == 1 and out["dropped"] == 3
    n = len(calls)
    again = EC.refresh_econ_releases(conn, today, fetch=_econ_fake(calls), sleep=lambda s: None)
    assert again["kostat"] == "skipped" and again["bls"] == "skipped" and again["bea"] == 4      # 실패했던 출처만 다시
    assert len(calls) == n + 1
    total = conn.execute("SELECT COUNT(*) FROM econ_release").fetchone()[0]
    EC.refresh_econ_releases(conn, today, force=True, fetch=_econ_fake(calls), sleep=lambda s: None)
    assert conn.execute("SELECT COUNT(*) FROM econ_release").fetchone()[0] == total                 # 멱등
    # BLS 가 12-04 고용상황을 12-11 로 옮겼다 — 옛 앞날 행은 사라지고, 지난 행(BEA 7-31)은 그대로
    moved = BLS_ICS.replace("20261204T083000", "20261211T083000")
    EC.refresh_econ_releases(conn, today, force=True, fetch=_econ_fake(calls, bls=moved), sleep=lambda s: None)
    bls = [r[0] for r in conn.execute("SELECT release_date FROM econ_release WHERE source='bls' ORDER BY 1")]
    assert bls == ["2026-12-11", "2026-12-31"]
    assert conn.execute("SELECT COUNT(*) FROM econ_release WHERE source='bea' AND release_date='2026-07-31'").fetchone()[0] == 1
    before = conn.execute("SELECT COUNT(*) FROM econ_release").fetchone()[0]
    got = EC.refresh_econ_releases(conn, today, force=True, fetch=_econ_fake(calls, empty="bls.gov"), sleep=lambda s: None)
    assert got["bls"] == 0 and conn.execute("SELECT COUNT(*) FROM econ_release").fetchone()[0] == before
    # 달력 일정 — 한국은 시각 칸 · 미국은 시각을 설명에(ET) · 지난 날 확정 · 앞날 예정 · 같은 날 여럿이어도 번호가 겹치지 않는다
    ev = EC.econ_events(conn, today, "x")
    assert len({e[0] for e in ev}) == len(ev)
    kr = next(e for e in ev if e[1] == "econ_kr" and e[2] == "2026-11-03")
    assert kr[3] == "08:00" and kr[8] == "scheduled" and kr[9] == "kostat"
    us = next(e for e in ev if e[1] == "econ_us" and e[2] == "2026-12-11")
    assert us[3] == "" and "미국 동부 시각(ET) 08:30" in us[7] and us[6].startswith("미국 ") and us[8] == "scheduled"
    old = next(e for e in ev if e[2] == "2026-07-31")
    assert old[1] == "econ_us" and old[8] == "confirmed"


def test_calendar_build_survives_econ_failure(tmp_path, monkeypatch):
    """TC-EV-10 · 달력 단계 — 경제지표 받기가 통째로 터져도 달력 · 일정은 만들고(econ_error 로 알림) · 받기는 실제 네트워크를 부르지 않는다."""
    from collector import market_calendar as cal
    c = db.connect(tmp_path / "m.sqlite3")
    for y in range(2020, 2028):
        c.execute("INSERT OR IGNORE INTO holiday_kasi VALUES (?, '신정', 'Y', '01', 1, 'x')", (f"{y}-01-01",))
    monkeypatch.setattr(E, "refresh_policy_meetings", lambda *a, **k: {"skipped": 1})

    def boom(*_a, **_k):
        raise RuntimeError("누리집이 막혔다")
    monkeypatch.setattr(EC, "refresh_econ_releases", boom)
    out = cal.build(c, fetch=True, today=date(2026, 11, 3), fetcher=lambda y: [], quiet=True)
    assert out["econ_error"] == "누리집이 막혔다" and out["events"] > 0
    c.close()


# ── 공모 청약 · 납입(①-23 F-lite) — collector/offering.py · 응답 모양은 2026-11-03 실측 3건을 본뜬 합성 JSON ──────────
def _estk(*items) -> bytes:
    import json
    gen = [{"rcept_no": r, "corp_cls": "K", "corp_code": cc, "corp_name": nm, "sbd": sbd, "pymd": pymd, "sband": "-",
            "asand": "-", "asstd": "-", "exstk": "-", "exprc": "-", "expd": "-", "rpt_rcpn": "x"}
           for r, cc, nm, sbd, pymd, _p, _t in items]
    sec = [{"rcept_no": r, "corp_cls": "K", "corp_code": cc, "corp_name": nm, "stksen": "보통주", "stkcnt": "1,000",
            "fv": "500", "slprc": p, "slta": t, "slmthn": "주주배정후 실권주 일반공모"} for r, cc, nm, _s, _y, p, t in items]
    return json.dumps({"status": "000", "message": "정상", "group": [
        {"title": "일반사항", "list": gen}, {"title": "증권의종류", "list": sec}, {"title": "인수인정보", "list": []}]},
        ensure_ascii=False).encode("utf-8")


def _equity(conn, rcept_no, corp_code, code, name, report_nm="증권신고서(지분증권)"):
    D.upsert_rows(conn, [D.normalize_item({"corp_code": corp_code, "corp_name": name, "stock_code": code, "corp_cls": "K",
                                            "report_nm": report_nm, "rcept_no": rcept_no, "rcept_dt": rcept_no[:8]},
                                           "C", fetched_at="2026-11-03T12:30:00+09:00")])


def test_parse_estk_period_payment_and_amounts():
    """TC-EV-11 · 증권신고서(지분증권) — 청약기일은 기간(시작 · 끝) · 납입기일 하나 · 가액 · 총액은 쉼표 글자 · 날짜가 비면 빈칸(추측 없음) ·
    정상이 아니면(013) 빈 목록."""
    body = _estk(("20261028000411", "01344202", "뷰노", "2026년 12월 18일 ~ 2026년 12월 21일", "2026년 12월 29일",
                  "4,980", "31,374,000,000"),
                 ("20260904000344", "00232007", "상지건설", "-", "", "8,520", "18,744,000,000"))
    got = {o["rcept_no"]: o for o in OF.parse_estk(body)}
    v = got["20261028000411"]
    assert (v["sub_start"], v["sub_end"], v["pay"]) == ("2026-12-18", "2026-12-21", "2026-12-29")
    assert v["securities"][0]["price"] == 4980 and v["securities"][0]["total"] == 31_374_000_000
    s = got["20260904000344"]
    assert (s["sub_start"], s["pay"]) == ("", "")
    assert OF.parse_estk(b'{"status": "013", "message": "x"}') == []
    assert OF.dates_in("2027년 02월 29일 ~ 2028년 02월 29일") == ["2028-02-29"]          # 없는 날은 버린다(윤년만 남음)


def test_offering_fetch_build_withdraw_and_events(conn):
    """TC-EV-12 · 공모 받기 · 읽기 — 최근 신고서를 낸 상장사만 회사마다 한 번 · 오늘 받은 회사는 다시 안 부름 · 한 회사 오류는 세고 넘어감 ·
    하루 한도면 멈춤 · 철회신고서가 뒤에 오면 달력에 올리지 않음 · 날짜 없는 신고서는 일정 없음 · 두 번 읽어도 늘지 않음 ·
    지난 날 확정 · 앞날 예정."""
    from collector import corp_schedule as CS
    today = date(2026, 11, 3)
    _equity(conn, "20261028000411", "01344202", "338220", "뷰노", "[기재정정]증권신고서(지분증권)")
    _equity(conn, "20261023000337", "00625942", "114810", "한솔아이원스")
    _equity(conn, "20261020000001", "00000009", "000009", "철회회사")
    _equity(conn, "20261030000002", "00000009", "000009", "철회회사", "철회신고서")
    _equity(conn, "20261021000003", "00000010", "000010", "오류회사")
    _equity(conn, "20250101000004", "00000011", "000011", "오래된회사")               # 90일 창 밖
    bodies = {
        "01344202": _estk(("20261028000411", "01344202", "뷰노", "2026년 10월 08일 ~ 2026년 10월 09일",
                           "2026년 12월 29일", "4,980", "31,374,000,000")),
        "00625942": _estk(("20261023000337", "00625942", "한솔아이원스", "-", "-", "9,120", "60,000,480,000")),
        "00000009": _estk(("20261020000001", "00000009", "철회회사", "2026년 11월 20일 ~ 2026년 11월 21일",
                           "2026년 11월 28일", "1,000", "1,000,000,000")),
    }
    seen = []

    def call(corp, bgn, end):
        seen.append((corp, bgn, end))
        if corp == "00000010":
            raise ConnectionError("끊김")
        return bodies[corp]

    out = OF.fetch_recent(conn, today, max_calls=10, call=call)
    assert out["todo"] == 4 and out["fetched"] == 3 and out["errors"] == 1 and out["left"] == 0
    assert all(b == "20251103" and e == "20261103" for _c, b, e in seen)                 # 최초접수일 기준 1년
    assert "00000011" not in {c for c, *_ in seen}
    again = OF.fetch_recent(conn, today, max_calls=10, call=call)
    assert again["todo"] == 1 and again["fetched"] == 0                                     # 받은 셋은 오늘 다시 안 부름 · 오류 회사만

    class DartQuotaExceeded(Exception):
        pass

    def quota(corp, bgn, end):
        raise DartQuotaExceeded("020")
    stop = OF.fetch_recent(conn, date(2026, 11, 4), max_calls=10, call=quota)
    assert stop["quota"] is True and stop["calls"] == 1

    CS.build(conn)
    CS.build(conn)                                                                           # 두 번 — 늘지 않는다
    rows = conn.execute("SELECT stock_code, kind, event_date FROM corp_schedule WHERE kind LIKE 'offer_%' "
                        "ORDER BY 1, 2").fetchall()
    assert [tuple(r) for r in rows] == [("114810", "offer_pay", ""), ("114810", "offer_sub", ""),
                                        ("338220", "offer_pay", "2026-12-29"), ("338220", "offer_sub", "2026-10-08")]
    ev = OF.offer_events(conn, today, "x")
    assert [(e[1], e[2], e[5], e[8]) for e in ev] == [("offer_sub", "2026-10-08", "338220", "confirmed"),
                                                      ("offer_pay", "2026-12-29", "338220", "scheduled")]
    assert ev[0][6] == "뷰노 공모 청약" and "청약 2026-10-08 ~ 2026-10-09" in ev[0][7] and "정정될 수 있음" in ev[0][7]
    assert "모집총액 313.7억 원" in ev[1][7]
    # 달력 한 곳(extra_events)이 새 종류 넷을 함께 돌려준다 — 같은 일정 번호는 없다
    allev = E.extra_events(conn, [], [2026], today, "x")
    assert len({e[0] for e in allev}) == len(allev)
    assert {"offer_sub", "offer_pay"} <= {e[1] for e in allev}


def test_weekend_dates_are_kept_as_published(conn):
    """TC-EV-13 · 주말 경계 — 발표 · 청약 날짜가 주말이어도 받은 날짜 그대로 둔다(보고서 기한처럼 민법 제161조로 옮기지 않고 ·
    휴장일처럼 다음 거래일로 밀지 않는다). 미국 금요일 밤 발표(UTC 로는 토요일)는 미국 날짜 금요일로 남는다."""
    from collector import raw_store
    sat = EC.parse_kostat(_kostat_page("2026년 11월 보도계획", [("11.07.( 토 )", "12:00", "2026년 3분기 가계동향조사 결과", "가계수지동향과")]))
    assert sat[1] == [(date(2026, 11, 7), "12:00", "2026년 3분기 가계동향조사 결과", "가계수지동향과")]
    fri = EC.parse_ics("BEGIN:VCALENDAR\nBEGIN:VEVENT\nSUMMARY:Friday night\nDTSTART:20261205T013000Z\nEND:VEVENT\nEND:VCALENDAR\n")
    assert fri == [(date(2026, 12, 4), "20:30", "Friday night")]                          # 한국 날짜(토 12-05)로 넘기지 않는다
    _equity(conn, "20261020000001", "00000012", "000012", "주말회사")
    conn.execute("BEGIN IMMEDIATE")
    raw_store.save(conn, "dart", "estk/00000012", _estk(("20261020000001", "00000012", "주말회사",
                                                          "2026년 11월 07일 ~ 2026년 11월 08일", "2026년 11월 14일",
                                                          "1,000", "1,000,000,000")))
    conn.execute("COMMIT")
    assert OF.build(conn)["offers"] == 1
    ev = {e[1]: e[2] for e in OF.offer_events(conn, date(2026, 11, 3), "x")}
    assert ev == {"offer_sub": "2026-11-07", "offer_pay": "2026-11-14"}                   # 토요일 그대로


def test_offering_fetch_safety_guards(conn):
    """TC-EV-14 · 공모 받기 안전장치(코드 검수 2026-11-03) — ① DART 가 계속 실패하면 연속 3번에서 멈추고 남은 회사는 다음 회차로
    ② 시간 상한을 넘으면 멈춘다 ③ 정정 반영이 늦어 013(데이터 없음)이 오면 있던 좋은 원문(000)을 덮지 않는다(공모 일정이 사라지지 않게)."""
    import json as _json
    from datetime import date as _date

    from collector import offering

    today = _date(2026, 11, 10)            # 실제 오늘(원문 fetched_at)과 같은 날이 되지 않게 — 「오늘 이미 받았다」 건너뛰기에 걸리지 않는다
    for i in range(6):
        _equity(conn, f"20261102{i:06d}", f"0000{i:04d}", f"{100000 + i}", f"회사{i}")

    # ① 연속 실패 — 3번째에서 멈춘다(호출 3번 · 오류 3 · 나머지 left)
    calls = []

    def boom(corp, bgn, end):
        calls.append(corp)
        raise OSError("연결 안 됨")

    out = offering.fetch_recent(conn, today, max_calls=100, call=boom)
    assert len(calls) == 3 and out["errors"] == 3 and out.get("stopped_on_errors") is True and out["left"] == 3

    # ② 시간 상한 — 상한을 0 으로 내리면 첫 회사 전에 멈춘다
    old = offering.MAX_FETCH_SECONDS
    offering.MAX_FETCH_SECONDS = -1
    try:
        out = offering.fetch_recent(conn, today, max_calls=100, call=lambda *a: b"{}")
    finally:
        offering.MAX_FETCH_SECONDS = old
    assert out.get("timed_out") is True and out["fetched"] == 0

    # ③ 013 이 좋은 원문을 덮지 않는다
    good = _json.dumps({"status": "000", "message": "정상", "list": []}).encode()
    none = _json.dumps({"status": "013", "message": "조회된 데이타가 없습니다."}).encode()
    from collector import raw_store

    conn.execute("BEGIN IMMEDIATE")
    raw_store.save(conn, "dart", f"{offering.RAW_PREFIX}/00000000", good, http_status=200, note="이전")
    conn.execute("COMMIT")
    out = offering.fetch_recent(conn, today, max_calls=1, call=lambda *a: none)
    assert out["kept"] == 1 and out["fetched"] == 0
    assert offering._status_of(raw_store.load(conn, "dart", f"{offering.RAW_PREFIX}/00000000")["body"]) == "000"


def test_econ_partial_response_keeps_future_rows(conn):
    """TC-EV-15 · 경제지표 부분 응답 보호(코드 검수) — 앞날 행이 10건 이상 있는데 새 응답의 앞날 행이 절반 아래면(월 한 쪽 · 잘린 달력)
    앞날 일정을 지우지 않고 `partial` 로 세어 다음 회차에 다시 받는다. 정상 응답(비슷한 수)은 그대로 바꾼다."""
    from datetime import date as _date

    from collector import econ_calendar

    today = _date(2026, 11, 3)
    econ_calendar.ensure_schema(conn)
    for i in range(12):
        conn.execute(
            "INSERT INTO econ_release (source, release_date, title, release_time, tz, detail, source_url, fetched_at) "
            "VALUES ('bls', ?, ?, '', 'ET', '', 'u', '2026-10-27T00:00:00')", (f"2026-12-{i + 1:02d}", f"지표{i}"))
    conn.commit()

    def fake_fetch(url, *a, **k):          # 앞날 행이 3건뿐인 잘린 달력
        return ("BEGIN:VCALENDAR\r\n" + "".join(
            f"BEGIN:VEVENT\r\nDTSTART;TZID=US-Eastern:202612{i + 1:02d}T083000\r\nSUMMARY:지표{i}\r\nEND:VEVENT\r\n" for i in range(3))
            + "END:VCALENDAR\r\n")

    out = econ_calendar.refresh_econ_releases(conn, today, force=True, fetch=fake_fetch, sources=("bls",), sleep=lambda s: None)
    assert out["bls"] == "partial" and out["errors"] == 1
    assert conn.execute("SELECT COUNT(*) FROM econ_release WHERE source='bls' AND release_date >= '2026-11-03'").fetchone()[0] == 12
