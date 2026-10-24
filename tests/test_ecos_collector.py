"""ECOS 시장금리 받기 시험 (TC-ECS) — `collector/ecos.py` (④-2 재무 · 신용 위험 · 2026-10-13).

여기서 지키는 것 —
1. 응답 읽기 — TIME(YYYYMMDD) → YYYY-MM-DD · 값은 수(빈칸은 None) · 「자료 없음」(INFO-200)은 0줄 · 다른 결과 코드는 예외(할 일 글).
2. 쌓기 — 같은 값은 그대로 · 바뀐 값은 값과 updated_at 만(처음 받은 시각은 그대로).
3. 받기 — 처음엔 계열마다 ECOS 첫 날부터 · 그다음엔 마지막 날 앞 14일부터 · 쪽 넘기기 · 원문은 raw_response(ecos).
4. **없는 항목 코드도 INFO-200 으로 온다** — 거래일이 들어 있을 긴 창이 비면 실패(짧은 창은 그대로 0줄).
5. **인증키가 새지 않는다** — 키는 주소 경로에 들어간다. 연결 오류 글 · 명령 출력 · 원문 이름에 키가 없다.
6. 키가 없으면 78(설정 결함)로 끝나고 부르지 않는다.
7. **월 주기**(소비자물가 · 2026-10-24 G1) — TIME(YYYYMM) → YYYY-MM(가짜 날 없음) · 매일 받기는 마지막 달 앞 3달부터 ·
   3달 넘는 창이 비면 실패 · 상태 줄에 「월」 · 원 출처.

네트워크 · 실제 수집 DB 를 쓰지 않는다. 응답 꼴은 2026-10-13 공식 샘플 키(sample)로 받은 실제 응답의 칸 이름을 따른다.
"""
from __future__ import annotations

import json
import re
from datetime import date

import pytest
import requests

from collector import config, db, ecos as E

#: 가짜 키 — 한 덩어리로 쓰면 비밀값 검사에 걸린다(실행할 때 이어 붙인다).
KEY = "ecosTEST" + "0123456789" + "ABCDEF"


def _search(rows, total=None, stat=None) -> bytes:
    """StatisticSearch 응답 — rows = [(item, TIME, 값)] · STAT_CODE 는 부른 통계표(실제 ECOS 와 같게)."""
    names = {it: (lab, "연%") for _k, it, lab, _f in E.SERIES}
    names.update({it: (lab, "1980.01.04=100") for _k, it, lab, _f in E.INDEX_SERIES})
    names.update({it: (lab, "연%") for _k, it, lab, _f in E.BASE_RATE_SERIES})
    names.update({it: (lab, "원") for _k, it, lab, _f in E.FX_SERIES})
    names.update({it: (lab, "2020=100") for _k, it, lab, _f in E.CPI_SERIES})
    stat = stat or E.STAT
    stat_names = {E.STAT: "1.3.2.1. 시장금리(일별)", E.INDEX_STAT: "1.5.1.1. 주식시장(일)",
                  E.BASE_RATE_STAT: "1.3.1. 한국은행 기준금리 및 여수신금리", E.FX_STAT: "3.1.1.1. 주요국 통화의 대원화환율",
                  E.CPI_STAT: "4.2.1. 소비자물가지수"}
    body = {"StatisticSearch": {"list_total_count": len(rows) if total is None else total, "row": [
        {"STAT_CODE": stat, "STAT_NAME": stat_names.get(stat, "?"),
         "ITEM_CODE1": it, "ITEM_NAME1": names.get(it, ("?",))[0],
         "ITEM_CODE2": None, "ITEM_NAME2": None, "UNIT_NAME": names.get(it, ("?", "연%"))[1], "WGT": None, "TIME": t,
         "DATA_VALUE": v}
        for it, t, v in rows]}}
    return json.dumps(body, ensure_ascii=False).encode("utf-8")


def _result(code, msg) -> bytes:
    return json.dumps({"RESULT": {"CODE": code, "MESSAGE": msg}}, ensure_ascii=False).encode("utf-8")


class _Resp:
    def __init__(self, body: bytes, status: int = 200):
        self.content, self.status_code = body, status


class _Session:
    """주소를 읽어 응답을 고르는 가짜 — 부른 주소를 모두 남긴다."""

    def __init__(self, respond):
        self.calls, self.respond = [], respond

    def get(self, url, timeout=None):
        self.calls.append(url)
        m = re.search(r"/StatisticSearch/([^/]+)/json/kr/(\d+)/(\d+)/(\w+)/(\w)/(\d+)/(\d+)/(\w+)$", url)
        assert m, url
        key, start, end, stat, cycle, bgn, fin, item = m.groups()
        return self.respond(dict(key=key, start=int(start), end=int(end), stat=stat, cycle=cycle, bgn=bgn, fin=fin,
                                 item=item))


class _NoWait:
    def wait(self):
        pass


@pytest.fixture()
def conn(tmp_path):
    c = db.connect(tmp_path / "m.sqlite3")
    E.ensure_table(c)
    yield c
    c.close()


def test_parse_rows_dates_values_and_blank_value():
    """TC-ECS-01 · TIME → YYYY-MM-DD · 값은 수 · 빈칸은 None · 전체 줄 수 · 항목 이름 · 단위."""
    total, rows = E.parse(_search([("010200000", "20261012", "3.921"), ("010200000", "20261008", "")], total=7))
    assert total == 7 and len(rows) == 2
    assert rows[0] == {"stat_code": "817Y002", "item_code": "010200000", "cycle": "D", "date": "2026-10-12",
                       "value": 3.921, "unit": "연%", "item_name": "국고채(3년)"}
    assert rows[1]["value"] is None and rows[1]["date"] == "2026-10-08"
    with pytest.raises(E.EcosError, match="숫자가 아니다"):
        E.parse(_search([("010200000", "20261012", "-")]))
    with pytest.raises(E.EcosError, match="일별"):
        E.parse(_search([("010200000", "202610", "3.9")]))


def test_parse_info200_is_empty_and_other_codes_raise_with_hint():
    """TC-ECS-02 · INFO-200 은 0줄 · INFO-100(키) · ERROR-101(날짜) 은 코드와 할 일 글을 단 예외 · JSON 이 아니면 예외."""
    assert E.parse(_result("INFO-200", "해당하는 데이터가 없습니다.")) == (0, [])
    with pytest.raises(E.EcosError) as ei:
        E.parse(_result("INFO-100", "인증키가 유효하지 않습니다."))
    assert ei.value.code == "INFO-100" and "ECOS_API_KEY" in str(ei.value) and "2년" in str(ei.value)
    with pytest.raises(E.EcosError) as ei:
        E.parse(_result("ERROR-101", "주기와 다른 형식의 날짜 형식입니다."))
    assert ei.value.code == "ERROR-101"
    with pytest.raises(E.EcosError, match="JSON"):
        E.parse(b"<html>gateway</html>")


def test_upsert_same_changed_keeps_first_fetch_time(conn):
    """TC-ECS-03 · 같은 값 그대로 · 바뀐 값은 값 · updated_at 만 · 처음 받은 시각은 그대로."""
    _, rows = E.parse(_search([("010300000", "20261012", "4.602"), ("010300000", "20261008", "4.651")]))
    assert E.upsert(conn, rows, at="2026-10-13T10:00:00+09:00") == {"new": 2, "changed": 0, "same": 0}
    assert E.upsert(conn, rows, at="2026-10-13T11:00:00+09:00") == {"new": 0, "changed": 0, "same": 2}
    _, fixed = E.parse(_search([("010300000", "20261012", "4.610")]))
    assert E.upsert(conn, fixed, at="2026-10-14T12:30:00+09:00") == {"new": 0, "changed": 1, "same": 0}
    r = conn.execute("SELECT value, fetched_at, updated_at FROM ecos_series WHERE date='2026-10-12'").fetchone()
    assert (r[0], r[1], r[2]) == (4.61, "2026-10-13T10:00:00+09:00", "2026-10-14T12:30:00+09:00")


def _good(req):
    """창 안의 거래일(주말 빼고) 마다 값 — 항목 코드로 값 높이를 다르게. 월 주기(M)는 달마다 값."""
    from datetime import datetime, timedelta

    base = {"010200000": 3.9, "010300000": 4.6, "010320000": 10.4, "010502000": 3.24, "010503000": 3.6,
            "010210000": 4.1, "0001000": 2600.0, "0089000": 850.0, "0101000": 2.5, "0000001": 1390.0,
            "0": 117.0}[req["item"]]
    if req["cycle"] == "M":
        y, m = int(req["bgn"][:4]), int(req["bgn"][4:])
        months = []
        while y * 100 + m <= int(req["fin"]):
            months.append(f"{y:04d}{m:02d}")
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        rows = [(req["item"], t, f"{base:.2f}") for t in months]
        page = rows[req["start"] - 1:req["end"]]
        return _Resp(_search(page, total=len(rows), stat=req["stat"]))
    d0 = datetime.strptime(req["bgn"], "%Y%m%d").date()
    d1 = datetime.strptime(req["fin"], "%Y%m%d").date()
    days = []
    d = d0
    while d <= d1:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    rows = [(req["item"], x.strftime("%Y%m%d"), f"{base:.3f}") for x in days]
    page = rows[req["start"] - 1:req["end"]]
    return _Resp(_search(page, total=len(rows), stat=req["stat"]))


def test_collect_first_run_from_series_start_then_overlap(conn):
    """TC-ECS-04 · 처음엔 계열마다 ECOS 첫 날부터 · 다음엔 마지막 날 앞 14일부터 · 원문은 raw_response(ecos) · 이름에 키 없음."""
    s = _Session(_good)
    today = date(2026, 10, 13)
    r = E.collect(conn, today, key=KEY, since=date(2026, 9, 1), session=s, limiter=_NoWait())
    # 시장금리 여섯(국고채 10년 2026-10-24) + 주가지수 둘(2026-10-14) + G1 셋(기준금리 · 환율 · 물가 2026-10-24)
    n_series = sum(len(series) for _st, _cy, series in E.GROUPS)
    assert len(s.calls) == n_series == 11 and all(f"/{KEY}/" in u for u in s.calls)
    assert {x["from"] for k, x in r.items() if k != "cpi_total"} == {"20260901"} and r["cpi_total"]["from"] == "202609"
    # 매일 — 마지막 날(10-13 화) 앞 14일부터 · 월은 마지막 달(2026-10) 앞 3달부터
    s2 = _Session(_good)
    E.collect(conn, today, key=KEY, session=s2, limiter=_NoWait())
    assert {u.split("/")[-3] for u in s2.calls if "/M/" not in u} == {"20260929"}
    assert [u.split("/")[-3] for u in s2.calls if "/M/" in u] == ["202607"]
    # 처음(표가 빈 계열)이면 ECOS 첫 날부터 — 국고채 3년은 1998-11-13
    conn.execute("DELETE FROM ecos_series WHERE item_code='010200000'")
    s3 = _Session(_good)
    E.collect(conn, today, key=KEY, session=s3, limiter=_NoWait())
    first = [u for u in s3.calls if u.endswith("/010200000")][0]
    assert first.split("/")[-3] == "19981113"
    targets = [t for (t,) in conn.execute("SELECT target FROM raw_response WHERE source='ecos'")]
    assert targets and all(KEY not in t for t in targets)
    assert conn.execute("SELECT COUNT(DISTINCT item_code) FROM ecos_series").fetchone()[0] == n_series


def test_paging_when_total_exceeds_page(conn, monkeypatch):
    """TC-ECS-05 · 전체 줄 수가 한 쪽보다 많으면 다음 쪽을 부른다(시작 · 끝 번호)."""
    monkeypatch.setattr(E, "PAGE", 3)
    s = _Session(_good)
    out = E.fetch_range(conn, _NoWait(), KEY, "010200000", "20261001", "20261012", session=s)
    # 10-01 ~ 10-12 평일 8일 → 3 + 3 + 2
    assert out["calls"] == 3 and out["rows"] == 8
    assert [u.split("/")[8:10] for u in s.calls] == [["1", "3"], ["4", "6"], ["7", "9"]]


def test_empty_long_window_fails_short_window_is_fine(conn):
    """TC-ECS-06 · 없는 항목 코드도 INFO-200 — 거래일이 들어 있을 10일 넘는 창이 비면 실패 · 주말 같은 짧은 창은 0줄 그대로."""
    empty = _Session(lambda req: _Resp(_result("INFO-200", "해당하는 데이터가 없습니다.")))
    with pytest.raises(E.EcosError, match="비워 보냈다"):
        E.fetch_range(conn, _NoWait(), KEY, "999999999", "20260929", "20261013", session=empty)
    out = E.fetch_range(conn, _NoWait(), KEY, "010200000", "20261010", "20261011", session=empty)
    assert out["rows"] == 0 and out["calls"] == 1


def test_http_error_and_connection_error_never_show_the_key(conn):
    """TC-ECS-07 · 연결 오류 글(주소가 든 예외)에 키가 없다 · HTTP 오류는 상태 번호만."""
    def boom(req):
        raise requests.ConnectionError(f"HTTPSConnectionPool(host='ecos.bok.or.kr', port=443): Max retries exceeded "
                                       f"with url: /api/StatisticSearch/{req['key']}/json/kr/1/10000/817Y002/D/x/y/z")
    with pytest.raises(E.EcosError) as ei:
        E.fetch_range(conn, _NoWait(), KEY, "010200000", "20261001", "20261012", session=_Session(boom))
    assert KEY not in str(ei.value) and "***" in str(ei.value)
    assert ei.value.__cause__ is None and ei.value.__suppress_context__  # 원래 예외(키가 든 글)를 잇지 않는다
    with pytest.raises(E.EcosError, match="HTTP 503"):
        E.fetch_range(conn, _NoWait(), KEY, "010200000", "20261001", "20261012",
                      session=_Session(lambda req: _Resp(b"", 503)))


def test_main_output_has_no_key_and_runs_with_db_option(tmp_path, monkeypatch, capsys):
    """TC-ECS-08 · 명령 출력 · 오류 줄에 키가 없다 — 성공 길과 연결 실패 길 둘 다."""
    monkeypatch.setattr(config, "require", lambda k, what: KEY)
    monkeypatch.setattr(E, "RateLimiter", lambda *a, **k: _NoWait())
    monkeypatch.setattr(E, "_session", lambda: _Session(_good))
    dbp = tmp_path / "x.sqlite3"
    assert E.main(["backfill", "--from", "20261001", "--db", str(dbp)]) == 0
    out = capsys.readouterr().out
    assert "ECOS treasury_3y" in out and KEY not in out

    def boom(req):
        raise requests.ConnectionError(f"url: /api/StatisticSearch/{req['key']}/json")
    monkeypatch.setattr(E, "_session", lambda: _Session(boom))
    assert E.main(["daily", "--db", str(dbp)]) == 1
    out = capsys.readouterr().out
    assert "🔴" in out and KEY not in out
    assert E.main(["status", "--db", str(dbp)]) == 0
    assert "국고채(3년)" in capsys.readouterr().out


def test_missing_key_is_config_defect_78_and_no_call(tmp_path, monkeypatch, capsys):
    """TC-ECS-09 · 키가 없으면 78(설정 결함 — 숨기지 않는다) · 할 일 글 · 부르지 않는다 · 상태 보기는 키 없이 된다."""
    def missing(k, what):
        raise config.MissingKey(f"{k} 가 없다 — {what}")
    monkeypatch.setattr(config, "require", missing)
    monkeypatch.setattr(E, "_session", lambda: pytest.fail("키가 없는데 부르려 했다"))
    assert E.main(["daily", "--db", str(tmp_path / "y.sqlite3")]) == E.EX_CONFIG == 78
    assert "ECOS_API_KEY" in capsys.readouterr().out
    assert E.main(["status", "--db", str(tmp_path / "y.sqlite3")]) == 0


def test_attribution_series_and_terms_are_written_down():
    """TC-ECS-10 · 출처 표시(약관 제7조②) · 항목 다섯(코드 · 첫 날) · 약관 조항이 머리말에 원문 근거로 있다."""
    assert "ECOS" in E.ATTRIBUTION and "한국은행" in E.ATTRIBUTION
    assert [s[1] for s in E.SERIES] == ["010200000", "010300000", "010320000", "010502000", "010503000", "010210000"]
    assert all(re.fullmatch(r"\d{8}", s[3]) for s in E.SERIES)
    doc = E.__doc__ or ""
    for clause in ("제5조①", "제6조②5", "제7조②", "2020-11-05 시행"):     # 시행일은 원문 끝 부칙(2026-10-13 받은 원문)
        assert clause in doc


def test_index_series_from_stock_market_table(conn):
    """TC-ECS-12 · 주가지수 둘(통계표 802Y001 — 2026-10-14 실측 코드 · 첫 날) · 그 통계표로 부르고 그 코드로 쌓는다 ·
    처음엔 ECOS 첫 날(코스피 1995-01-03 · 코스닥 2003-01-02)부터 · 시장금리 줄은 섞이지 않는다 · 상태 줄에 이름."""
    assert E.INDEX_STAT == "802Y001" and E.GROUPS[:2] == ((E.STAT, "D", E.SERIES), (E.INDEX_STAT, "D", E.INDEX_SERIES))
    assert [(k, c, f) for k, c, _n, f in E.INDEX_SERIES] == [("kospi", "0001000", "19950103"), ("kosdaq", "0089000", "20030102")]
    s = _Session(_good)
    today = date(2026, 10, 13)
    E.collect(conn, today, key=KEY, since=date(2026, 9, 1), session=s, limiter=_NoWait())
    idx_calls = [u for u in s.calls if u.endswith("/0001000") or u.endswith("/0089000")]
    assert len(idx_calls) == 2 and all("/802Y001/D/" in u for u in idx_calls)
    rate_items = {it for _k, it, _n, _f in E.SERIES}
    assert all("/817Y002/D/" in u for u in s.calls if u.rsplit("/", 1)[1] in rate_items)
    by_stat = dict(conn.execute("SELECT stat_code, COUNT(DISTINCT item_code) FROM ecos_series GROUP BY stat_code").fetchall())
    assert by_stat == {"817Y002": 6, "802Y001": 2, "722Y001": 1, "731Y001": 1, "901Y009": 1}
    # 처음(지수 줄이 없음)이면 ECOS 첫 날부터 — 다른 계열은 마지막 날 앞 14일부터
    conn.execute("DELETE FROM ecos_series WHERE stat_code='802Y001'")
    s2 = _Session(_good)
    E.collect(conn, today, key=KEY, session=s2, limiter=_NoWait())
    firsts = {u.rsplit("/", 1)[1]: u.split("/")[-3] for u in s2.calls}
    assert firsts["0001000"] == "19950103" and firsts["0089000"] == "20030102" and firsts["010200000"] == "20260929"
    # 지수 줄이 생긴 뒤의 매일 받기는 그 통계표의 마지막 날 앞 14일부터 — 통계표 코드를 잘못 보면 날마다 1995 부터 다시 받는다
    s3 = _Session(_good)
    E.collect(conn, today, key=KEY, session=s3, limiter=_NoWait())
    again = {u.rsplit("/", 1)[1]: u.split("/")[-3] for u in s3.calls}
    assert again["0001000"] == "20260929" and again["0089000"] == "20260929"
    targets = [t for (t,) in conn.execute("SELECT target FROM raw_response WHERE source='ecos' AND target LIKE '802Y001/%'")]
    assert targets and all(KEY not in t for t in targets)
    lines = "\n".join(E.status_lines(conn))
    assert "KOSPI지수" in lines and "KOSDAQ지수" in lines and "국고채(3년)" in lines
    # 줄 수도 그 통계표에서 센다 — 시장금리 코드로 세면 지수 줄이 0 으로 보인다(깨 보기 E5)
    kospi = next(ln for ln in lines.splitlines() if "KOSPI지수" in ln)
    assert re.search(r"\s([1-9][\d,]*)줄", kospi), kospi


def test_table_in_db_schema_and_wired_everywhere(tmp_path):
    """TC-ECS-11 · 표 정의는 collector/db.py 한 곳(연결할 때마다 만든다) · 러너 ecos 단계(받기 · 멈추지 않음 · 하루 받기) ·
    백업 대상(필수) · 관제 표 · 자료 안내가 이 표를 잇는다 — 어느 한 곳만 빠지면 백업 대조가 「모르는 표」 로 멈추거나(DB 에는
    있는데 백업 대상에 없음) 관제 · 안내가 숫자를 못 잇는다."""
    import sqlite3

    from app.services import data_guide as dg
    from app.services import data_status as ds
    from collector import db as cdb
    from scripts import daily_update as du
    from scripts import hf_dataset

    assert E.ECOS_SERIES_DDL is cdb.ECOS_SERIES_DDL and cdb.ECOS_SERIES_DDL in cdb.SCHEMA
    c = cdb.connect(tmp_path / "m.sqlite3")
    try:
        cols = [r[1] for r in c.execute("PRAGMA table_info(ecos_series)")]
    finally:
        c.close()
    assert cols == ["stat_code", "item_code", "cycle", "date", "value", "unit", "item_name", "fetched_at", "updated_at", "raw_sha256"]
    step = next(s for s in du.STEPS if s.name == "ecos")
    assert step.args == ["-m", "collector.ecos", "daily", "--quiet"] and not step.fatal and step.group == "받기" and step.label
    names = [s.name for s in du.STEPS]
    assert names.index("ecos") < names.index("export"), "백업 내보내기보다 먼저"
    spec = hf_dataset.TABLES["ecos_series"]
    assert spec["date_col"] == "date" and spec["optional"] is False and "ecos_series" not in hf_dataset.EXCLUDED
    assert [k for k, t, *_ in ds.TABLES if t == "ecos_series"] == ["ecos_series"]
    item = next(it for it in dg.load_guide()["items"] if "ecos_series" in it["dev"]["tables"])
    assert item["key"] == "market-rates" and "agent-cb" in str(item)


def test_monthly_cycle_parse_window_and_empty_rule(conn):
    """TC-ECS-13 · 월 주기(소비자물가 · 2026-10-24) — TIME YYYYMM → YYYY-MM(가짜 날을 붙이지 않는다) · 13월 같은 꼴은 예외 ·
    처음엔 ECOS 첫 달(1965-01)부터 · 다음엔 마지막 달 앞 3달부터 · 3달 넘는 창이 비면 실패 · 2달 창은 0줄 그대로 ·
    상태 줄에 「월」 과 원 출처 · 일 계열의 마지막 날 읽기(last_date)에 월 줄이 섞이지 않는다."""
    _, rows = E.parse(_search([("0", "202609", "117.32")], stat=E.CPI_STAT), cycle="M", stat=E.CPI_STAT)
    assert rows == [{"stat_code": "901Y009", "item_code": "0", "cycle": "M", "date": "2026-09", "value": 117.32,
                     "unit": "2020=100", "item_name": "소비자물가지수 총지수"}]
    with pytest.raises(E.EcosError, match="월별"):
        E.parse(_search([("0", "202613", "1")], stat=E.CPI_STAT), cycle="M", stat=E.CPI_STAT)
    with pytest.raises(E.EcosError, match="월별"):
        E.parse(_search([("0", "20260901", "1")], stat=E.CPI_STAT), cycle="M", stat=E.CPI_STAT)
    s = _Session(_good)
    E.collect(conn, date(2026, 10, 24), key=KEY, session=s, limiter=_NoWait())
    cpi = [u for u in s.calls if "/901Y009/" in u]
    assert len(cpi) == 1 and "/901Y009/M/196501/202610/0" in cpi[0]
    lo, hi, n = conn.execute("SELECT MIN(date), MAX(date), COUNT(*) FROM ecos_series WHERE stat_code='901Y009'").fetchone()
    assert (lo, hi, n) == ("1965-01", "2026-10", (2026 - 1965) * 12 + 10)
    s2 = _Session(_good)
    E.collect(conn, date(2026, 10, 24), key=KEY, session=s2, limiter=_NoWait())
    assert [u.split("/")[-3] for u in s2.calls if "/901Y009/" in u] == ["202607"]
    empty = _Session(lambda req: _Resp(_result("INFO-200", "해당하는 데이터가 없습니다.")))
    with pytest.raises(E.EcosError, match="3달"):
        E.fetch_range(conn, _NoWait(), KEY, "0", "202607", "202609", session=empty, stat=E.CPI_STAT, cycle="M")
    out = E.fetch_range(conn, _NoWait(), KEY, "0", "202609", "202610", session=empty, stat=E.CPI_STAT, cycle="M")
    assert out["rows"] == 0 and out["calls"] == 1
    lines = "\n".join(E.status_lines(conn))
    cpi_line = next(ln for ln in lines.splitlines() if "소비자물가" in ln)
    assert "· 월" in cpi_line and "국가데이터처" in cpi_line and "1965-01 ~ 2026-10" in cpi_line
    fx_line = next(ln for ln in lines.splitlines() if "원/미국달러" in ln)
    assert "서울외국환중개" in fx_line
    # 일 계열의 마지막 날은 월 줄을 보지 않는다(같은 표 · 다른 주기가 섞이면 date.fromisoformat 이 「2026-10」 에서 죽는다)
    assert E.last_date(conn, "0", E.CPI_STAT) is None and E.last_time(conn, "0", E.CPI_STAT, "M") == "2026-10"


def test_g1_series_codes_first_points_and_origin_are_pinned():
    """TC-ECS-14 · G1 셋 · 국고채 10년의 코드 · 주기 · 첫 시점(2026-10-22 일회 수집 · 2026-10-24 StatisticItemList 실측) ·
    원 출처(환율 = 서울외국환중개 — 영리목적 복제 · 배포 금지 약관) · 이용 조건 셋이 머리말에 · 모르는 주기는 예외."""
    got = {(st, cy, it, first) for st, cy, series in E.GROUPS for _k, it, _n, first in series}
    for want in (("722Y001", "D", "0101000", "19990506"), ("731Y001", "D", "0000001", "19640504"),
                 ("901Y009", "M", "0", "196501"), ("817Y002", "D", "010210000", "20001218")):
        assert want in got, want
    assert all(re.fullmatch(r"\d{8}" if cy == "D" else r"\d{6}", first)
               for _st, cy, series in E.GROUPS for _k, _it, _n, first in series)
    assert len({k for _st, _cy, series in E.GROUPS for k, *_ in series}) == 11, "열쇠는 계열마다 하나(명령 출력 · 러너 로그)"
    assert E.ORIGIN[E.FX_STAT] == "서울외국환중개" and E.ORIGIN[E.CPI_STAT] == "국가데이터처"
    assert all(st in E.ORIGIN for st, _cy, _s in E.GROUPS)
    doc = E.__doc__ or ""
    for phrase in ("서울외국환중개 약관", "KOSIS", "출처를 명시하는 한 상업적"):
        assert phrase in doc
    with pytest.raises(E.EcosError, match="주기"):
        E._iso_time("2026Q3", "Q")
