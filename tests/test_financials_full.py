"""전체 재무제표 시험 (TC-FF) — `collector/financials_full.py` (할 일 ①-05 G3 · 2026-10-24 · 사용자 결정 「새 공시 + 분기마다 대조」).

여기서 지키는 것 —
1. 줄 읽기 — 계정 ID 가 없으면 버림 · 금액은 정수 · 이름 공백 접음 · 구분(CFS · OFS)은 부른 값 · 종목코드는 우리 매핑 · 알 수 있었던 날은 접수번호.
2. **같은 판을 다시 받아도 줄을 고치지 않는다** — 처음 받은 값이 「그날 알 수 있었던 값」.
3. 새 정기보고서 — 응답 접수번호가 공시와 같아야 끝 · 옛 판이면 기다림(다섯 번이면 값 없음) · 같은 보고서 정정본이 먼저 오면 밀림 ·
   다른 기간의 더 새 판은 밀림이 아니다 · 351곳 밖 회사는 묻지 않는다 · 연결이 없으면 별도.
4. 분기 대조 — 같음(원문 안 남김) · 조용한 고침(우리 줄 그대로 · 원문 남김) · 없던 판(더함) · 사라짐 · 둘 다 없음 · 하루 50곳 ·
   끝낸 회사는 그 분기에 다시 안 봄 · 다음 분기엔 다시.
5. 멈춤 — 상한 · 020 은 그 자리에서(받은 것은 남음) · 지난 해 채우기는 회차 시간(12:20 ~ 13:20) · 회차 잠금에 시작하지 않는다.
6. 옮겨 담기 — 일회 수집 원문(값 있음 · 없음)을 네트워크 없이 · 받은 시각 = 파일 시각 · 다시 돌려도 같은 줄.
7. 연결 — 표 정의 한 곳 · 러너 단계(차례 · 상한 · 경고 종료코드) · 백업 대상 · 관제 줄 · 자료 안내.
8. 처음 보는 회사의 연결 → 별도 떠보기(지난 해 채우기) · 사용자가 정한 몫 값(TC-FF-14 · 15 — 깨 보기 M8 · M5 뒤 더함).

네트워크 · 실제 수집 DB 를 쓰지 않는다(가짜 세션 · 임시 DB). 응답 꼴은 2026-10-22 일회 수집 원문의 칸 이름을 따른다.
"""
from __future__ import annotations

import gzip
import json
import os
from datetime import date, datetime

import pytest

from collector import config, db
from collector import financials_full as F
from collector.sources import dart

CORP_A, STOCK_A = "00126380", "005930"     # 유니버스 안
CORP_B, STOCK_B = "00164779", "000660"     # 유니버스 안
CORP_X = "00999999"                         # 유니버스 밖
CORP_MAP = {STOCK_A: [CORP_A, "삼성전자"], STOCK_B: [CORP_B, "SK하이닉스"], "999999": [CORP_X, "밖"]}


def _line(rcept, corp, year, reprt, sj="BS", ord_="1", acc="ifrs-full_CurrentAssets", nm="유동자산", amt="1,000", detail="-"):
    return {"rcept_no": rcept, "reprt_code": reprt, "bsns_year": str(year), "corp_code": corp, "sj_div": sj, "sj_nm": "재무상태표",
            "account_id": acc, "account_nm": nm, "account_detail": detail, "thstrm_nm": "제 57 기", "thstrm_amount": amt,
            "frmtrm_nm": "제 56 기", "frmtrm_amount": "900", "bfefrmtrm_nm": "", "bfefrmtrm_amount": "", "ord": ord_,
            "currency": "KRW"}


def _body(lines=None, status="000") -> bytes:
    d = {"status": status, "message": "정상" if status == "000" else "조회된 데이타가 없습니다."}
    if lines:
        d["list"] = lines
    return json.dumps(d, ensure_ascii=False).encode("utf-8")


class _Resp:
    def __init__(self, body: bytes, status: int = 200):
        self.content, self.status_code, self.headers = body, status, {}


class _Session:
    """(corp, year, reprt, fs) → 응답 — 표에 없으면 013. 부른 열쇠를 모두 남긴다."""

    def __init__(self, table=None):
        self.table, self.calls = dict(table or {}), []

    def get(self, url, params=None, timeout=None):
        k = (params["corp_code"], params["bsns_year"], params["reprt_code"], params["fs_div"])
        self.calls.append(k)
        v = self.table.get(k)
        if v is None:
            return _Resp(_body(status="013"))
        if isinstance(v, bytes):
            return _Resp(v)
        return _Resp(_body(v))


class _NoWait:
    calls = 0

    def wait(self):
        pass

    def observe(self, headers):
        pass


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "dart_key", lambda: "dartTEST" + "0" * 32)
    monkeypatch.delenv(dart.LEDGER_ENV, raising=False)
    c = db.connect(tmp_path / "m.sqlite3")
    c.execute("INSERT INTO intraday_universe (version, symbol, itms_nm, market, reason) VALUES "
              "('u2-20260930', ?, '', 'KOSPI', ''), ('u2-20260930', ?, '', 'KOSPI', ''), ('u2-20260930', '069500', '', 'ETF', ''), "
              "('u1-20260930', '999999', '', 'KOSPI', '')", (STOCK_A, STOCK_B))
    yield c
    c.close()


def _disc(conn, rcept, corp, title, period, rcept_dt=None):
    conn.execute("INSERT INTO disclosure (rcept_no, rcept_dt, corp_code, corp_name, report_nm, title, period, fetched_at, "
                 "updated_at) VALUES (?,?,?,'회사',?,?,?,'t','t')", (rcept, rcept_dt or rcept[:8], corp, title, title, period))


def _daily(conn, s, today=date(2026, 11, 17), **kw):
    kw.setdefault("check_per_day", 0)
    kw.setdefault("new_corp_calls", 0)
    return F.run_daily(conn, today=today, session=s, limiter=_NoWait(), corp_map=CORP_MAP, **kw)


def test_normalize_amounts_names_fs_and_dates():
    """TC-FF-01 · 줄 읽기 — 금액 정수(쉼표 · 「-」 · 빈칸) · 이름 공백 접음 · 구분은 부른 값 · 종목코드는 우리 매핑 · 계정 ID 없으면 버림."""
    it = _line("20261114000123", CORP_A, 2026, "11014", nm="유동  자산", amt="12,069,316")
    it["frmtrm_q_amount"] = "-"
    r = F.normalize(it, fs_div="CFS", stock_code=STOCK_A, fetched_at="2026-11-17T12:31:00+09:00", raw_sha256="ab")
    assert (r["fs_div"], r["stock_code"], r["account_nm"], r["thstrm_amount"], r["frmtrm_q_amount"], r["known_at"]) == \
        ("CFS", STOCK_A, "유동 자산", 12069316, None, "20261114")
    assert set(F.COLS) == set(r) and r["ord"] == 1 and r["first_known_at"] == ""
    bad = dict(it, account_id="")
    assert F.normalize(bad, fs_div="CFS", stock_code="", fetched_at="", raw_sha256="") is None


def test_same_version_again_keeps_first_values(conn):
    """TC-FF-02 · 같은 판(접수번호)을 다시 받아도 줄을 고치지 않는다 — 기본 키는 계정 ID · 상세까지(자본변동표 줄이 겹치지 않게)."""
    rows = [F.normalize(_line("20260515000001", CORP_A, 2026, "11013", amt="100"), fs_div="CFS", stock_code=STOCK_A,
                        fetched_at="a", raw_sha256="x"),
            F.normalize(_line("20260515000001", CORP_A, 2026, "11013", sj="SCE", acc="ifrs-full_Equity", nm="기초자본",
                              detail="이익잉여금 [member]", amt="5"), fs_div="CFS", stock_code=STOCK_A, fetched_at="a",
                        raw_sha256="x"),
            F.normalize(_line("20260515000001", CORP_A, 2026, "11013", sj="SCE", acc="ifrs-full_Equity", nm="기초자본",
                              detail="자본금 [member]", amt="7"), fs_div="CFS", stock_code=STOCK_A, fetched_at="a",
                        raw_sha256="x")]
    assert F.insert_rows(conn, rows) == 3
    again = [dict(rows[0], thstrm_amount=999, fetched_at="b")]
    assert F.insert_rows(conn, again) == 0
    assert tuple(conn.execute("SELECT thstrm_amount, fetched_at FROM financial_statement_full WHERE sj_div='BS'").fetchone()) == (100, "a")


def test_new_filing_done_lag_missing_and_outside_universe(conn):
    """TC-FF-03 · 새 정기보고서 — 응답 접수번호 = 공시면 끝 · 옛 판(반영 늦음)이면 기다림 · 다섯 번이면 값 없음 · 351곳 밖은 묻지 않는다."""
    _disc(conn, "20261114000500", CORP_A, "분기보고서", "2026.09")
    _disc(conn, "20261114000600", CORP_B, "분기보고서", "2026.09")
    _disc(conn, "20261114000700", CORP_X, "분기보고서", "2026.09")
    s = _Session({(CORP_A, "2026", "11014", "CFS"): [_line("20261114000500", CORP_A, 2026, "11014")],
                  (CORP_B, "2026", "11014", "CFS"): [_line("20260814000100", CORP_B, 2026, "11014")]})   # B 는 옛 판
    t = _daily(conn, s)
    assert (t.filings_done, t.filings_pending) == (1, 1) and all(k[0] != CORP_X for k in s.calls)
    st = dict(conn.execute("SELECT bas_dt, status FROM ingest_day WHERE source='dart_full_rcept'").fetchall())
    assert st == {"20261114000500": "done", "20261114000600": "pending"}
    # 끝낸 공시는 다시 묻지 않는다 · 기다림은 다섯 번째에 「값 없음」
    for _ in range(4):
        s2 = _Session(s.table)
        _daily(conn, s2)
        assert all(k[0] == CORP_B for k in s2.calls)
    assert tuple(conn.execute("SELECT status, attempts FROM ingest_day WHERE bas_dt='20261114000600'").fetchone()) == ("missing", 5)
    s3 = _Session(s.table)
    _daily(conn, s3)
    assert s3.calls == [], "값 없음 · 끝낸 공시는 더 묻지 않는다"


def test_superseded_only_by_correction_of_same_report(conn):
    """TC-FF-04 · 밀림 — 같은 회사 · 같은 보고서 이름 · 같은 기간의 더 늦은 접수번호(정정본)가 먼저 오면 원본 공시는 끝(옛 판 값은 다시
    오지 않는다). 더 늦은 접수번호라도 공시 목록에 그 보고서의 정정본으로 없으면 밀림이 아니다(다른 기간의 판 · 결산월이 다른 회사)."""
    _disc(conn, "20261114000500", CORP_A, "분기보고서", "2026.09")
    _disc(conn, "20261120000900", CORP_A, "분기보고서", "2026.09")         # 같은 보고서의 정정본
    _disc(conn, "20261114000600", CORP_B, "분기보고서", "2026.09")
    s = _Session({(CORP_A, "2026", "11014", "CFS"): [_line("20261120000900", CORP_A, 2026, "11014")],
                  (CORP_B, "2026", "11014", "CFS"): [_line("20261201000001", CORP_B, 2026, "11014")]})
    _daily(conn, s, today=date(2026, 11, 21))
    st = dict(conn.execute("SELECT bas_dt, status FROM ingest_day WHERE source='dart_full_rcept'").fetchall())
    assert st["20261114000500"] == "superseded" and st["20261120000900"] == "done" and st["20261114000600"] == "pending"


def test_ofs_when_no_consolidated(conn):
    """TC-FF-05 · 처음 보는 회사는 연결 먼저 · 연결이 없으면(013) 별도 — 별도 줄로 쌓이고 다음엔 별도 먼저 묻는다."""
    _disc(conn, "20261114000500", CORP_A, "분기보고서", "2026.09")
    s = _Session({(CORP_A, "2026", "11014", "OFS"): [_line("20261114000500", CORP_A, 2026, "11014")]})
    _daily(conn, s)
    assert s.calls[:2] == [(CORP_A, "2026", "11014", "CFS"), (CORP_A, "2026", "11014", "OFS")]
    assert [tuple(r) for r in conn.execute("SELECT DISTINCT fs_div FROM financial_statement_full")] == [("OFS",)]
    assert F.corp_fs(conn, CORP_A) == "OFS"


def _seed_version(conn, corp, stock, y, rp, rcept, amt="100", fs="CFS"):
    rows = [F.normalize(_line(rcept, corp, y, rp, amt=amt), fs_div=fs, stock_code=stock, fetched_at="t0", raw_sha256="s0")]
    F.insert_rows(conn, rows)


def test_quarterly_check_results(conn):
    """TC-FF-06 · 분기 대조 — 같음(원문 안 남김) · 조용한 고침(우리 줄은 그대로 · 원문 남김 · 다른 줄 수) · 없던 판(더함) · 사라짐 ·
    둘 다 없음. 결과는 대조 표에 기간마다 한 줄 · 회사는 끝으로 적힌다."""
    today = date(2026, 10, 25)
    _seed_version(conn, CORP_A, STOCK_A, 2025, "11011", "20260310000001")                  # 같음
    _seed_version(conn, CORP_A, STOCK_A, 2025, "11012", "20250814000001", amt="100")       # 조용한 고침
    _seed_version(conn, CORP_A, STOCK_A, 2025, "11013", "20250515000001")                  # 없던 판(정정)
    _seed_version(conn, CORP_A, STOCK_A, 2025, "11014", "20251114000001")                  # 사라짐
    s = _Session({(CORP_A, "2025", "11011", "CFS"): [_line("20260310000001", CORP_A, 2025, "11011", amt="100")],
                  (CORP_A, "2025", "11012", "CFS"): [_line("20250814000001", CORP_A, 2025, "11012", amt="120")],
                  (CORP_A, "2025", "11013", "CFS"): [_line("20260601000009", CORP_A, 2025, "11013")]})
    t = F.Tally()
    caller = F.Caller(conn, t, max_calls=None, session=s, limiter=_NoWait())
    F.check_corp(conn, caller, CORP_A, STOCK_A, "2026Q4", today, t)
    res = {(y, rp): (r, n) for y, rp, r, n in conn.execute(
        "SELECT bsns_year, reprt_code, result, changed_rows FROM financial_full_check WHERE quarter='2026Q4'")}
    assert res[("2025", "11011")] == ("same", 0)
    assert res[("2025", "11012")] == ("silent_change", 1)
    assert res[("2025", "11013")] == ("new_version", 0)
    assert res[("2025", "11014")] == ("gone", 0)
    assert res[("2026", "11013")] == ("no_data", 0) and res[("2026", "11012")] == ("no_data", 0)
    assert ("2026", "11014") not in res, "아직 마감 전(11-14) 보고서는 묻지 않는다"
    # 조용한 고침 — 우리 줄은 처음 받은 값 · 원문은 남김 / 같음 — 원문을 또 남기지 않는다
    assert conn.execute("SELECT thstrm_amount FROM financial_statement_full WHERE reprt_code='11012'").fetchone()[0] == 100
    targets = [r[0] for r in conn.execute("SELECT target FROM raw_response WHERE source='dart'")]
    assert any(x.endswith("2025-11012-CFS") for x in targets) and not any(x.endswith("2025-11011-CFS") for x in targets)
    assert conn.execute("SELECT COUNT(DISTINCT rcept_no) FROM financial_statement_full WHERE reprt_code='11013'").fetchone()[0] == 2
    assert conn.execute("SELECT status FROM ingest_day WHERE source='dart_full_check' AND bas_dt=?",
                        (f"2026Q4:{CORP_A}",)).fetchone()[0] == "done"


def test_quarterly_check_50_per_day_once_per_quarter(conn, monkeypatch):
    """TC-FF-07 · 하루 상한(회사 수) · 끝낸 회사는 그 분기에 다시 보지 않는다 · 다음 분기엔 다시."""
    def checked(q):
        return {r[0] for r in conn.execute("SELECT DISTINCT corp_code FROM financial_full_check WHERE quarter=?", (q,))}

    s = _Session()
    t = _daily(conn, s, today=date(2026, 10, 25), check_per_day=1)
    assert t.check_corps == 1 and t.quarter == "2026Q4" and len(checked("2026Q4")) == 1
    first = checked("2026Q4")
    s2 = _Session()
    _daily(conn, s2, today=date(2026, 10, 26), check_per_day=1)
    assert {k[0] for k in s2.calls} and not ({k[0] for k in s2.calls} & first), "끝낸 회사는 그 분기에 다시 안 본다"
    assert checked("2026Q4") == {CORP_A, CORP_B}
    s3 = _Session()
    t3 = _daily(conn, s3, today=date(2026, 10, 27), check_per_day=1)
    assert t3.check_corps == 0 and s3.calls == [], "두 곳 다 끝 — 그 분기는 더 없다"
    s4 = _Session()
    t4 = _daily(conn, s4, today=date(2027, 1, 2), check_per_day=5)
    assert t4.quarter == "2027Q1" and t4.check_corps == 2


def test_stops_at_cap_and_quota_keep_what_was_got(conn):
    """TC-FF-08 · 상한에 닿으면 그 자리에서 멈춤(받은 것은 남음 · 종료 까닭) · 020 도 멈춤(재시도하지 않는다)."""
    _disc(conn, "20261114000500", CORP_A, "분기보고서", "2026.09")
    _disc(conn, "20261114000600", CORP_B, "분기보고서", "2026.09")
    s = _Session({(CORP_A, "2026", "11014", "CFS"): [_line("20261114000500", CORP_A, 2026, "11014")],
                  (CORP_B, "2026", "11014", "CFS"): [_line("20261114000600", CORP_B, 2026, "11014")]})
    t = _daily(conn, s, max_calls=1)
    assert "상한" in t.stopped and t.calls == 1 and t.filings_done == 1
    s2 = _Session({(CORP_B, "2026", "11014", "CFS"): _body(status="020")})
    t2 = _daily(conn, s2)
    assert "020" in t2.stopped and len(s2.calls) == 1


def test_backfill_round_guard_and_lock(conn, monkeypatch):
    """TC-FF-09 · 지난 해 채우기 — 12:20 ~ 13:20 에는 「회차 시간」 으로 멈추고, 그 밖엔 회차 잠금을 본다 · 막히면 한 번도 부르지 않는다."""
    assert "회차 시간" in F.round_busy(datetime(2026, 10, 26, 12, 25))
    assert "회차 시간" in F.round_busy(datetime(2026, 10, 26, 13, 19))
    from scripts import daily_update as du
    monkeypatch.setattr(du, "lock_holder", lambda *_a, **_k: "다른 실행이 돌고 있다 (PID 1)")
    assert "정기 회차" in F.round_busy(datetime(2026, 10, 26, 15, 0))
    monkeypatch.setattr(du, "lock_holder", lambda *_a, **_k: None)
    assert F.round_busy(datetime(2026, 10, 26, 13, 20)) is None
    s = _Session()
    t = F.run_backfill(conn, years=(2015, 2016), max_calls=100, session=s, limiter=_NoWait(), corp_map=CORP_MAP,
                       guard=lambda: "회차 시간(12:20 ~ 13:20)이라 멈춤", today=date(2026, 10, 26))
    assert "회차 시간" in t.stopped and s.calls == []


def test_backfill_fills_periods_skips_asked_and_uses_known_fs(conn):
    """TC-FF-10 · 지난 해 채우기 — 회사 구분은 우리 표에서(별도 회사는 별도로) · 처음 회사는 사업보고서로 떠 봄(연결 → 별도) ·
    물은 조합은 다시 묻지 않는다 · 늦은 해 · 늦은 보고서부터."""
    _seed_version(conn, CORP_A, STOCK_A, 2025, "11011", "20260310000001", fs="OFS")
    s = _Session({(CORP_B, "2025", "11011", "CFS"): [_line("20260310000002", CORP_B, 2025, "11011")]})
    t = F.run_backfill(conn, years=(2019, 2020), max_calls=500, session=s, limiter=_NoWait(), corp_map=CORP_MAP,
                       guard=None, today=date(2026, 10, 26))
    a = [k for k in s.calls if k[0] == CORP_A]
    assert a and all(k[3] == "OFS" for k in a) and a[0][1:3] == ("2020", "11011")
    b = [k for k in s.calls if k[0] == CORP_B]
    assert b[0] == (CORP_B, "2025", "11011", "CFS") and all(k[3] in ("CFS", "OFS") for k in b)
    assert len(a) == 8 and t.calls == len(s.calls)
    s2 = _Session(s.table)
    F.run_backfill(conn, years=(2019, 2020), max_calls=500, session=s2, limiter=_NoWait(), corp_map=CORP_MAP, guard=None,
                   today=date(2026, 10, 26))
    assert s2.calls == [], "물은 조합(값 없음 포함)은 다시 묻지 않는다"


def test_periods_respect_filing_deadlines():
    """TC-FF-11 · 마감 — 3분기는 11-14 부터 · 사업보고서는 다음 해 3-31 부터 · 늦은 해 · 늦은 보고서부터."""
    assert not F.due(2026, "11014", date(2026, 11, 13)) and F.due(2026, "11014", date(2026, 11, 14))
    assert not F.due(2026, "11011", date(2026, 12, 31)) and F.due(2026, "11011", date(2027, 3, 31))
    assert F.periods(2025, 2026, date(2026, 10, 25)) == [(2026, "11012"), (2026, "11013"), (2025, "11011"), (2025, "11014"),
                                                         (2025, "11012"), (2025, "11013")]


def test_seed_imports_raw_files_offline_and_is_idempotent(conn, tmp_path):
    """TC-FF-12 · 옮겨 담기 — 값 있음은 원문 · 줄 · 부른 기록(done) · 값 없음은 부른 기록(empty)만 · 받은 시각은 파일 시각 · 다시 돌려도 같다 ·
    처음 공개일을 공시 목록에서 잇는다."""
    raw = tmp_path / "raw_fs"
    (raw / CORP_A).mkdir(parents=True)
    f1 = raw / CORP_A / "2025_11011_CFS.json.gz"
    f1.write_bytes(gzip.compress(_body([_line("20260310000001", CORP_A, 2025, "11011")]), mtime=0))
    f2 = raw / CORP_A / "2025_11014_CFS.json.gz"
    f2.write_bytes(gzip.compress(_body(status="013"), mtime=0))
    os.utime(f1, (1792641457, 1792641457))
    _disc(conn, "20260305000001", CORP_A, "사업보고서", "2025.12")              # 원본 공시(정정 전)
    out = F.seed(conn, raw, corp_map=CORP_MAP)
    assert (out["files"], out["with_data"], out["empty"], out["rows"]) == (2, 1, 1, 1)
    r = conn.execute("SELECT fetched_at, stock_code, first_known_at, known_at FROM financial_statement_full").fetchone()
    assert r[0].startswith("2026-10-22T12:57") and r[1] == STOCK_A and (r[2], r[3]) == ("20260305", "20260310")
    st = dict(conn.execute("SELECT bas_dt, status FROM ingest_day WHERE source='dart_full_bf'").fetchall())
    assert st == {f"{CORP_A}:2025:11011:CFS": "done", f"{CORP_A}:2025:11014:CFS": "empty"}
    n_raw = conn.execute("SELECT COUNT(*) FROM raw_response WHERE source='dart'").fetchone()[0]
    assert n_raw == 1
    out2 = F.seed(conn, raw, corp_map=CORP_MAP)
    assert out2["rows"] == 0 and conn.execute("SELECT COUNT(*) FROM raw_response WHERE source='dart'").fetchone()[0] == n_raw


def test_wired_table_runner_backup_status_guide(tmp_path):
    """TC-FF-13 · 연결 — 표 정의는 collector/db.py 한 곳 · 러너 단계(재무 뒤 · 일정 앞 · 받기 · 멈추지 않음 · 상한 = 몫 표 · 3 은 경고) ·
    백업 대상(연도 = 접수일) · 대조 표도 백업 · 관제 줄(새 행 없는 날이 정상 — 단계 결과로 판정) · 자료 안내 한 자료."""
    from app.services import data_guide as dg
    from app.services import data_status as ds
    from scripts import daily_update as du
    from scripts import hf_dataset

    c = db.connect(tmp_path / "w.sqlite3")
    try:
        assert F.COLS == tuple(r[1] for r in c.execute("PRAGMA table_info(financial_statement_full)"))
    finally:
        c.close()
    names = [s.name for s in du.STEPS]
    assert names.index("financial") + 1 == names.index("financial_full") < names.index("schedule")
    step = du.STEPS[names.index("financial_full")]
    assert step.args[:4] == ["-m", "collector.financials_full", "daily", "--quiet"] and not step.fatal and step.group == "받기"
    assert step.args[step.args.index("--max-calls") + 1] == str(du.DART_CAPS["financial_full"]) and step.warn_codes == (3,)
    spec = hf_dataset.TABLES["financial_statement_full"]
    assert spec["partition"] == "year" and spec["date_col"] == "known_at" and not spec["optional"]
    assert "financial_full_check" in hf_dataset.TABLES
    assert ds.FRESHNESS["financial_statement_full"] == ("step_checked", "financial_full")
    assert [k for k, t, *_ in ds.TABLES if t == "financial_statement_full"] == ["financial_statement_full"]
    item = next(it for it in dg.load_guide()["items"] if it["key"] == "fin-full")
    assert item["dev"]["tables"] == ["financial_statement_full", "financial_full_check"]


def test_backfill_first_company_without_consolidated_probes_separate(conn):
    """TC-FF-14 · 지난 해 채우기 — 처음 보는 회사(우리 표에 구분이 없음)가 연결이 없으면(013) 별도로 떠 보고, 그 뒤 기간도 별도로
    묻는다(깨 보기 M8 이 TC-FF-10 을 지나갔다 — TC-FF-10 의 처음 회사는 연결이 있었다 · 2026-10-24)."""
    s = _Session({(CORP_B, "2025", "11011", "OFS"): [_line("20260310000002", CORP_B, 2025, "11011")]})
    F.run_backfill(conn, years=(2019, 2020), max_calls=500, session=s, limiter=_NoWait(), corp_map=CORP_MAP, guard=None,
                   today=date(2026, 10, 26))
    b = [k for k in s.calls if k[0] == CORP_B]
    assert b[:2] == [(CORP_B, "2025", "11011", "CFS"), (CORP_B, "2025", "11011", "OFS")], b[:3]
    assert F.corp_fs(conn, CORP_B) == "OFS"
    assert len(b) > 2 and all(k[3] == "OFS" for k in b[2:]), "떠 본 뒤 기간은 별도로만"


def test_shares_are_the_decided_values():
    """TC-FF-15 · 사용자가 정한 값(2026-10-24 · 결정 대장 v1.10 부록 C) — 분기 대조 하루 50곳(약 300 ~ 400회 · 7일 안에 351곳 한 바퀴) ·
    새로 든 회사 하루 300회 · 지난 해 채우기 0.6초 간격 · 12:20 ~ 13:20 막기 · 매일 단계의 기본값이 그 상수다(깨 보기 M5 — 다른 시험은
    값을 늘 넘겨 기본값을 보지 않았다)."""
    import inspect

    assert F.CHECK_CORPS_PER_DAY == 50 and F.NEW_CORP_MAX_CALLS == 300 and F.BACKFILL_SLEEP == 0.6
    assert F.ROUND_GUARD == ((12, 20), (13, 20)) and F.MAX_ATTEMPTS == 5
    sig = inspect.signature(F.run_daily).parameters
    assert sig["check_per_day"].default == F.CHECK_CORPS_PER_DAY and sig["new_corp_calls"].default == F.NEW_CORP_MAX_CALLS
    assert inspect.signature(F.run_backfill).parameters["sleep"].default == F.BACKFILL_SLEEP

