"""거래일 달력 · 금융 일정 시험 (TC-CA) — 목표 기능 ① W4 · 설계서 5.2.4 · 8절 표 「TC-CA」.

무엇이 틀렸었나 —
거래일 달력이 「시세가 쌓인 날」 뿐이라 내일이 없었다. 그래서 아직 시세가 없는 기준일의 배당락일을
달력 끝에서 세었다(2026-10-02 실측 3행 — 블랙야크아이앤씨 기준일 10-13 → 09-29, 기준일 09-30 두 행 → 09-28).
배당락일은 TR 이 배당을 더하는 날이라 TR 도 함께 틀렸다.

여기서 지키는 것 —
1. 규칙 — 주말 · 공휴일(특일 정보) · 근로자의 날 · 연말 휴장일(주말이면 앞 평일: 2022-12-30 · 2023-12-29).
2. 지난날은 시세를 따르고, 규칙과 어긋난 날 · 시세가 아직 없는 날을 가려 적는다.
3. 달력 끝 = 특일 정보가 2020 년부터 이어서 있는 마지막 해 — 공휴일을 모르는 해는 만들지 않는다.
4. 파생 만기 = 두 번째 목요일, 휴장이면 앞당김(2025-10 은 한글날 · 추석 연휴로 10-02).
5. 특일 정보 받기 — 응답 꼴 셋 · 오류 메시지에 키가 새지 않는다 · 0건인 해는 옛 행을 지우지 않는다.
6. 배당락일 다시 계산 — 위 3행이 바로잡히고, 달력 끝 뒤 기준일은 비워 두고 표시한다(지우지 않는다).
7. API — 로그인 없이 읽고, 달력 밖은 partial 로 알리고, 달력이 없으면 503 과 할 일.

네트워크는 쓰지 않는다(특일 정보는 픽스처 · 가짜 opener). 마지막 시험만 실제 수집 DB 를 읽고, 없으면 건너뛴다.
"""
from __future__ import annotations

import io
import json
import sqlite3
import urllib.error
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes import calendar as calendar_routes
from app.services import collector_db
from collector import config, db
from collector import market_calendar as mc

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "kasi_holidays_2020_2027.json").read_text(encoding="utf-8"))
HOLIDAY_ROWS = {int(y): rows for y, rows in FIXTURE["years"].items()}
REAL_DB = ROOT / "data" / "collector" / "market.sqlite3"
TODAY = date(2026, 10, 2)
LAST_PRICE = date(2026, 9, 30)


def holidays() -> dict[date, str]:
    return {date.fromisoformat(r["locdate"]): r["date_name"]
            for rows in HOLIDAY_ROWS.values() for r in rows if r["is_holiday"] == "Y"}


def rule_trading_days(start: date, end: date) -> list[date]:
    hol = holidays()
    out, d = [], start
    while d <= end:
        if mc.rule_reason(d, hol) is None:
            out.append(d)
        d += timedelta(days=1)
    return out


def fake_fetch(year: int) -> list[dict]:
    return [dict(r) for r in HOLIDAY_ROWS.get(year, [])]


def make_db(path: Path, *, observed_until: date = LAST_PRICE, dividends: list[tuple] = ()) -> sqlite3.Connection:
    """수집기의 실제 스키마로 픽스처 DB — 시세는 날짜만(종목 하나), 배당은 넘겨준 행."""
    conn = db.connect(path)
    days = rule_trading_days(date(2020, 1, 2), observed_until)
    conn.execute("BEGIN")
    conn.executemany("INSERT INTO price_daily (bas_dt, srtn_cd, clpr) VALUES (?, '005930', 1)",
                     [(d.strftime("%Y%m%d"),) for d in days])
    conn.executemany(
        "INSERT INTO dividend (srtn_cd, record_dt, rcept_no, itms_nm, div_kind, dps, ex_div_dt, note) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", list(dividends))
    conn.execute("COMMIT")
    return conn


# 2026-10-02 실측 세 행 + 정상 한 행
DIVIDENDS = [
    ("478560", "20261013", "20260928000001", "블랙야크아이앤씨", "중간배당", 100.0, "20260929", ""),
    ("069960", "20260930", "20261001000002", "가", "분기배당", 500.0, "20260928", ""),
    ("213500", "20260930", "20261001000003", "나", "분기배당", 250.0, "20260928", ""),
    ("017960", "20260930", "20261001800104", "한국카본", "분기배당", 100.0, "20260929", ""),
]


# ── 1. 규칙 ──────────────────────────────────────────────────────────────
def test_rule_reason_weekend_holiday_labor_day_year_end():
    """TC-CA-01 · 주말 · 공휴일 이름(토요일 개천절은 「개천절」) · 근로자의 날 · 평일은 None."""
    hol = holidays()
    assert mc.rule_reason(date(2026, 10, 3), hol) == "개천절", "공휴일 이름이 요일보다 먼저"
    assert mc.rule_reason(date(2026, 10, 4), hol) == "일요일"
    assert mc.rule_reason(date(2026, 10, 5), hol) == "대체공휴일(개천절)"
    assert mc.rule_reason(date(2025, 5, 1), hol) == "근로자의 날", "2025 년까지 특일 정보에 없던 5-1"
    assert mc.rule_reason(date(2026, 5, 1), hol) == "노동절", "2026 년부터는 특일 정보의 공휴일"
    assert mc.rule_reason(date(2026, 10, 2), hol) is None


def test_year_end_closure_moves_to_last_weekday():
    """TC-CA-02 · 연말 휴장일 — 12-31 이 평일이면 그날, 주말이면 앞 평일(시세로 확인한 2022-12-30 · 2023-12-29)."""
    hol = holidays()
    assert mc.year_end_closure(2021, hol) == date(2021, 12, 31)
    assert mc.year_end_closure(2022, hol) == date(2022, 12, 30)
    assert mc.year_end_closure(2023, hol) == date(2023, 12, 29)
    assert mc.year_end_closure(2026, hol) == date(2026, 12, 31)
    # 12-31 이 공휴일인 가상의 해 — 그 앞 평일로
    assert mc.year_end_closure(2026, {**hol, date(2026, 12, 31): "임시공휴일"}) == date(2026, 12, 30)


def test_calendar_end_needs_contiguous_years():
    """TC-CA-03 · 달력 끝은 2020 년부터 이어서 공휴일이 있는 마지막 해의 12-31 — 빈 해에서 멈춘다."""
    assert mc.calendar_end(range(2020, 2028)) == date(2027, 12, 31)
    assert mc.calendar_end([2020, 2021, 2023]) == date(2021, 12, 31), "2022 가 비면 2021 에서 멈춘다"
    assert mc.calendar_end([2021, 2022]) is None, "2020 이 없으면 만들지 않는다"


def test_build_days_follows_prices_and_flags_mismatches():
    """TC-CA-04 · 시세 구간은 시세를 따르고, 어긋남 둘과 「아직 없음」 을 가려 적는다 · 그 뒤는 규칙."""
    hol = holidays()
    observed = rule_trading_days(date(2020, 1, 2), LAST_PRICE)
    observed.remove(date(2026, 9, 15))                       # 규칙은 거래일 · 포털 holiday 확정 → 까닭 모름 휴장
    observed.remove(date(2026, 9, 29))                       # 규칙은 거래일 · 포털 empty → 아직 못 받은 거래일
    observed = sorted(observed + [date(2026, 9, 25)])        # 규칙은 휴장(추석)인데 시세가 있다 → 시세를 따른다
    states = {"20260915": "holiday", "20260929": "empty"}
    days, st = mc.build_days(hol, date(2027, 12, 31), observed, states)
    by = {x.cal_date: x for x in days}

    assert len(days) == (date(2027, 12, 31) - date(2020, 1, 1)).days + 1
    assert (by[date(2026, 9, 25)].is_trading_day, by[date(2026, 9, 25)].basis) == (1, "observed")
    assert "규칙은 휴장(추석)" in by[date(2026, 9, 25)].note
    assert (by[date(2026, 9, 15)].is_trading_day, by[date(2026, 9, 15)].reason) == (0, "휴장(까닭 모름)")
    assert (by[date(2026, 9, 29)].is_trading_day, by[date(2026, 9, 29)].basis) == (1, "rule")
    assert "아직 없다" in by[date(2026, 9, 29)].note
    assert (st["rule_closed_but_traded"], st["rule_open_but_closed"], st["missing_price"]) == (1, 1, 1)
    # 시세 뒤는 규칙 — 10-01 거래일(예정) · 10-05 대체공휴일 · 10-09 한글날
    assert (by[date(2026, 10, 1)].is_trading_day, by[date(2026, 10, 1)].basis) == (1, "rule")
    assert (by[date(2026, 10, 5)].is_trading_day, by[date(2026, 10, 5)].reason) == (0, "대체공휴일(개천절)")
    assert by[date(2026, 12, 31)].reason == "연말 휴장일"


# ── 2. 파생 만기 ──────────────────────────────────────────────────────────
def test_expiry_second_thursday_moves_earlier_on_holiday():
    """TC-CA-05 · 두 번째 목요일 — 2025-10-09(한글날)과 그 앞 추석 연휴를 건너 10-02 · 달을 넘으면 None."""
    trading = rule_trading_days(date(2025, 1, 1), date(2027, 12, 31))
    assert mc.second_thursday(2026, 10) == date(2026, 10, 8)
    assert mc.expiry_day(2026, 10, trading) == date(2026, 10, 8)
    assert mc.expiry_day(2025, 10, trading) == date(2025, 10, 2)
    assert mc.expiry_day(2026, 12, trading) == date(2026, 12, 10)
    assert mc.expiry_day(2026, 10, [date(2026, 9, 30), date(2026, 10, 20)]) is None, "앞달로 넘어가면 만기로 치지 않는다"


# ── 3. 특일 정보 받기 ────────────────────────────────────────────────────
class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _opener(payload, seen: list):
    def op(url, timeout=20):
        seen.append(url)
        if isinstance(payload, Exception):
            raise payload
        return _Resp(payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8"))
    return op


def _body(items, code="00"):
    return {"response": {"header": {"resultCode": code, "resultMsg": "NORMAL SERVICE."},
                         "body": {"items": items, "totalCount": 0}}}


def test_fetch_kasi_parses_three_shapes_and_hides_key(monkeypatch):
    """TC-CA-06 · 목록 · 한 건(객체) · 0건(빈 문자열) 을 같은 꼴로 · 오류 셋은 KasiError 이고 메시지에 키가 없다."""
    monkeypatch.setattr(config, "portal_key", lambda: "SECRET+KEY/=")
    one = {"dateKind": "01", "dateName": "한글날", "isHoliday": "Y", "locdate": 20261009, "seq": 1}
    seen: list = []
    rows = mc.fetch_kasi_year(2026, opener=_opener(_body({"item": [one, {**one, "locdate": 20261005,
                                                                         "dateName": "대체공휴일(개천절)"}]}), seen))
    assert [r["locdate"] for r in rows] == ["2026-10-09", "2026-10-05"]
    assert "serviceKey=SECRET%2BKEY%2F%3D" in seen[0] and "solYear=2026" in seen[0] and "_type=json" in seen[0]
    assert mc.fetch_kasi_year(2026, opener=_opener(_body({"item": one}), []))[0]["date_name"] == "한글날"
    assert mc.fetch_kasi_year(2028, opener=_opener(_body(""), [])) == []

    errors = [
        _body({}, code="30"),
        b"<OpenAPI_ServiceResponse><cmmMsgHeader>SERVICE KEY IS NOT REGISTERED</cmmMsgHeader></OpenAPI_ServiceResponse>",
        urllib.error.HTTPError("https://x/?serviceKey=SECRET+KEY/=", 403, "Forbidden", None, None),
    ]
    for payload in errors:
        with pytest.raises(mc.KasiError) as e:
            mc.fetch_kasi_year(2026, opener=_opener(payload, []))
        assert "SECRET" not in str(e.value) and "serviceKey" not in str(e.value)


def test_refresh_keeps_year_when_response_is_empty(tmp_path):
    """TC-CA-07 · 받은 해는 통째로 바꾸고, 0건이 온 해(발표 전 · 장애)는 어제 받은 행을 지우지 않는다."""
    conn = db.connect(tmp_path / "m.sqlite3")
    mc.refresh_holidays(conn, [2026, 2027], fetch=fake_fetch, sleep=0)
    n2027 = conn.execute("SELECT COUNT(*) FROM holiday_kasi WHERE locdate LIKE '2027%'").fetchone()[0]
    assert n2027 == len(HOLIDAY_ROWS[2027])
    got = mc.refresh_holidays(conn, [2026, 2027], fetch=lambda y: fake_fetch(y)[:3] if y == 2026 else [], sleep=0)
    assert got == {2026: 3, 2027: 0}
    assert conn.execute("SELECT COUNT(*) FROM holiday_kasi WHERE locdate LIKE '2026%'").fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(*) FROM holiday_kasi WHERE locdate LIKE '2027%'").fetchone()[0] == n2027
    assert mc.years_to_fetch(conn, TODAY) == list(range(2020, 2026)) + [2026, 2027], "지난해는 없는 해만"


# ── 4. 배당락일 다시 계산 ─────────────────────────────────────────────────
def test_rederive_fixes_the_three_rows_and_holds_beyond_calendar(tmp_path):
    """TC-CA-08 · 실측 3행이 바로잡히고(10-12 · 09-29 · 09-29), 달력 끝 뒤 기준일은 비우고 표시 → 달력이 늘면 채우고 표시를 지운다."""
    conn = make_db(tmp_path / "m.sqlite3", dividends=DIVIDENDS + [
        ("000001", "20280315", "20280301000009", "다", "결산배당", 50.0, "20260929", "본문 메모")])
    cal = [d.strftime("%Y%m%d") for d in rule_trading_days(date(2020, 1, 1), date(2027, 12, 31))]
    changes = {(c, r): (o, n) for c, r, o, n in mc.rederive_ex_dates(conn, cal)}
    assert changes[("478560", "20261013")] == ("20260929", "20261012")
    assert changes[("069960", "20260930")] == ("20260928", "20260929")
    assert changes[("213500", "20260930")] == ("20260928", "20260929")
    assert ("017960", "20260930") not in changes, "맞던 행은 그대로"
    ex, note = conn.execute("SELECT ex_div_dt, note FROM dividend WHERE srtn_cd='000001'").fetchone()
    assert ex == "" and note.startswith("본문 메모 / " + mc.EX_HOLD), "달력 끝(2027) 뒤 기준일은 지우지 않고 보류"
    assert mc.rederive_ex_dates(conn, cal) == [], "두 번째는 바뀔 것이 없다"

    longer = cal + [d.strftime("%Y%m%d") for d in rule_trading_days(date(2028, 1, 1), date(2028, 12, 31))]
    mc.rederive_ex_dates(conn, longer)
    ex, note = conn.execute("SELECT ex_div_dt, note FROM dividend WHERE srtn_cd='000001'").fetchone()
    assert ex == "20280314" and note == "본문 메모", "달력이 늘면 채우고 보류 표시만 지운다"


# ── 5. 일정 · 끝까지 ─────────────────────────────────────────────────────
def test_build_end_to_end_events_and_idempotent(tmp_path):
    """TC-CA-09 · build 한 번에 공휴일 → 달력 → 배당락일 → 일정 · 두 번 돌려도 같다 · 받기가 실패해도 어제 공휴일로 만든다."""
    conn = make_db(tmp_path / "m.sqlite3", dividends=DIVIDENDS)
    res = mc.build(conn, today=TODAY, fetcher=fake_fetch, quiet=True)
    assert res["end"] == "2027-12-31" and res["fetch_error"] == ""
    assert res["stats"]["rule_closed_but_traded"] == res["stats"]["rule_open_but_closed"] == 0
    assert len(res["ex_changes"]) == 3

    ev = {r[0]: r for r in conn.execute("SELECT event_id, kind, event_date, title, detail, confidence, source "
                                        "FROM market_event")}
    assert "market_closure:2026-10-03" not in ev, "주말 공휴일은 일정에 싣지 않는다"
    assert ev["market_closure:2026-10-05"][5:] == ("scheduled", "kasi")
    assert ev["market_closure:2025-12-31"][5:] == ("confirmed", "krx_rule")
    assert ev["deriv_expiry:2025-10-02"][3] == "코스피200 옵션 만기" and "앞당김" in ev["deriv_expiry:2025-10-02"][4]
    assert ev["deriv_expiry:2026-12-10"][3] == "코스피200 선물 · 옵션 동시 만기"
    assert ev["dividend_ex:2026-10-13:478560"][2] == "2026-10-12"
    assert ev["dividend_record:2026-10-13:478560"][5] == "confirmed"

    counts = [conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("market_calendar", "market_event")]
    mc.build(conn, today=TODAY, fetcher=fake_fetch, quiet=True)
    assert counts == [conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("market_calendar", "market_event")]

    def broken(year):
        raise mc.KasiError(f"{year}년 특일 정보 연결 실패(URLError)")
    res = mc.build(conn, today=TODAY, fetcher=broken, quiet=True)
    assert res["fetch_error"] and res["end"] == "2027-12-31"

    empty = db.connect(tmp_path / "empty.sqlite3")
    with pytest.raises(mc.CalendarError):
        mc.build(empty, fetch=False, today=TODAY, quiet=True)


# ── 6. API ───────────────────────────────────────────────────────────────
@pytest.fixture
def api(tmp_path, monkeypatch):
    path = tmp_path / "market.sqlite3"
    conn = make_db(path, dividends=DIVIDENDS)
    mc.build(conn, today=TODAY, fetcher=fake_fetch, quiet=True)
    conn.close()
    monkeypatch.setenv(collector_db.ENV_DB_PATH, str(path))
    app = FastAPI()
    app.include_router(calendar_routes.router)
    return TestClient(app)


def test_api_trading_days_and_events_without_login(api):
    """TC-CA-10 · 로그인 없이 — 10월 첫 열흘의 거래일 · 휴장 까닭 · 근거, 만기 · 배당 일정, 출처 · 기준일."""
    r = api.get("/api/calendar/trading-days", params={"from": "2026-10-01", "to": "2026-10-10"})
    assert r.status_code == 200
    j = r.json()
    by = {d["date"]: d for d in j["days"]}
    assert j["trading_days"] == 5 and j["source"] == "collector" and j["as_of"], "1 · 2 · 6 · 7 · 8일"
    assert by["2026-10-05"]["reason"] == "대체공휴일(개천절)" and by["2026-10-05"]["basis"] == "rule"
    assert by["2026-10-09"]["weekday"] == "금" and not by["2026-10-09"]["is_trading_day"]
    assert "partial" not in j

    e = api.get("/api/calendar/events", params={"from": "2026-10-01", "to": "2026-10-31",
                                                "kind": "deriv_expiry,dividend_ex"}).json()
    assert [(x["date"], x["kind"]) for x in e["events"]] == [("2026-10-08", "deriv_expiry"), ("2026-10-12", "dividend_ex")]
    assert e["events"][1]["symbol"] == "478560" and e["events"][1]["confidence_label"] == "규칙으로 계산"


def test_api_partial_bad_kind_and_missing_calendar(api, tmp_path, monkeypatch):
    """TC-CA-11 · 달력 밖은 partial 로 알리고 · 모르는 종류는 422 · 달력이 없으면 503 과 할 일."""
    j = api.get("/api/calendar/trading-days", params={"from": "2027-12-20", "to": "2028-01-10"}).json()
    assert j["partial"] is True and "2027-12-31 뒤는 아직 없다" in j["partial_reason"]
    assert api.get("/api/calendar/events", params={"kind": "ipo"}).status_code == 422           # 실적(earnings)은 2026-10-04 부터 있는 종류
    assert api.get("/api/calendar/trading-days", params={"from": "2026-10-10", "to": "2026-10-01"}).status_code == 422

    bare = tmp_path / "bare.sqlite3"
    sqlite3.connect(bare).executescript("CREATE TABLE price_daily (bas_dt TEXT);")
    monkeypatch.setenv(collector_db.ENV_DB_PATH, str(bare))
    r = api.get("/api/calendar/trading-days")
    assert r.status_code == 503 and "collector.market_calendar build" in r.json()["detail"]


# ── 7. 실제 수집 DB ──────────────────────────────────────────────────────
def _real_calendar():
    if not REAL_DB.is_file():
        return None
    conn = sqlite3.connect(f"{REAL_DB.resolve().as_uri()}?mode=ro", uri=True)
    has = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='market_calendar'").fetchone()[0]
    if not has or not conn.execute("SELECT 1 FROM market_calendar LIMIT 1").fetchone():
        conn.close()
        return None
    return conn


def test_real_db_rules_match_prices_and_ex_dates_follow_calendar():
    """TC-CA-12 · (실제 DB) 규칙과 시세가 어긋난 날 0 · 저장된 배당락일이 지금 달력으로 센 값과 모두 같다."""
    conn = _real_calendar()
    if conn is None:
        pytest.skip("실제 수집 DB 나 거래일 달력이 없다 — python -m collector.market_calendar build")
    from collector.sources import dart
    try:
        odd = conn.execute("SELECT cal_date, note FROM market_calendar WHERE note LIKE '규칙은%'").fetchall()
        assert odd == [], f"규칙과 시세가 어긋난 날: {odd[:5]}"
        cal = [r[0].replace("-", "") for r in conn.execute(
            "SELECT cal_date FROM market_calendar WHERE is_trading_day = 1 ORDER BY cal_date")]
        diff = [(c, r, ex) for c, r, ex in conn.execute("SELECT srtn_cd, record_dt, ex_div_dt FROM dividend")
                if (dart.ex_dividend_date(cal, r) or "") != (ex or "")]
        assert diff == [], f"달력과 다른 배당락일: {diff[:5]}"
    finally:
        conn.close()
