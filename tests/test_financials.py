"""재무 주요계정 수집 시험 (TC-FS) — `collector/financials.py` (목표 기능 ① W7 · 설계서 5.1.5).

무엇이 문제인가 — DART 재무 API 는 가장 최근 정정본의 값과 접수번호만 준다(2026-10-04 실측 · GS건설 2023 사업보고서는
2024-03-21 첫 제출 → 정정 셋 → 지금 부르면 2026-06-30 정정본). 그래서 이 표는 정정본마다 한 벌을 쌓고 날짜를 둘 둔다.

여기서 지키는 것 —
1. 금액 · 기간 끝날 · 접수일(접수번호 앞 8자리)을 바르게 읽는다(「-」 · 빈칸은 값 없음).
2. 같은 판을 다시 받으면 한 벌 그대로 · 정정본(새 접수번호)은 옛 판 옆에 새 판으로 쌓인다.
3. 처음 공개일(first_known_at) = 같은 회사 · 기간 · 보고서 이름의 공시 가운데 가장 이른 접수일(정정 · 첨부추가 포함)이고,
   값의 접수일(known_at)보다 늦을 수 없다.
4. 공시 목록의 (보고서 이름 · 기간)으로 물을 (사업연도 · 보고서 코드)를 고른다 — 12월 결산을 먼저, 다른 결산월은 뒤 후보.
5. 일일 받기는 아직 값이 없는 정기보고서 접수번호만 묻고, 후보를 차례로 바꿔 묻고, 끝내 못 받은 것은 시도 수를 남겨
   다섯 번이면 「값 없음」 으로 접는다.

네트워크 · 실제 수집 DB 를 쓰지 않는다.
"""
from __future__ import annotations

import json

import pytest

from collector import db
from collector import financials as F
from collector.ratelimit import RateLimiter
from collector.sources import dart


class FakeResp:
    def __init__(self, doc: dict):
        self.content = json.dumps(doc, ensure_ascii=False).encode("utf-8")
        self.status_code = 200
        self.headers = {}


def acct(rcept_no, account_nm, amount, *, corp="00126380", stock="005930", year="2023", rc="11011", fs="CFS",
         sj="IS", ord_=1, dt="2023.01.01 ~ 2023.12.31"):
    return {"rcept_no": rcept_no, "reprt_code": rc, "bsns_year": year, "corp_code": corp, "stock_code": stock,
            "fs_div": fs, "fs_nm": "연결재무제표", "sj_div": sj, "sj_nm": "손익계산서", "account_nm": account_nm,
            "thstrm_nm": "제 55 기", "thstrm_dt": dt, "thstrm_amount": amount, "frmtrm_amount": "1,000",
            "ord": str(ord_), "currency": "KRW"}


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    path = tmp_path / "market.sqlite3"
    real = db.connect
    monkeypatch.setattr(db, "connect", lambda p=None: real(path))
    monkeypatch.setattr(F, "_limiter", lambda: RateLimiter(0, name="DART"))
    c = real(path)
    yield c
    c.close()


def test_parse_amount_period_and_known_at():
    """TC-FS-01 · 「12,069,316,661,153」 · 「-1,234」 · 「-」 · 빈칸 · 기간 끝날 · 접수번호 앞 8자리."""
    assert F.parse_amount("12,069,316,661,153") == 12069316661153
    assert F.parse_amount("-1,234") == -1234
    assert F.parse_amount("-") is None and F.parse_amount("") is None and F.parse_amount(None) is None
    assert F.period_end("2025.12.31 현재") == "2025-12-31"
    assert F.period_end("2025.01.01 ~ 2025.12.31") == "2025-12-31"
    assert F.known_at_of("20260630000500") == "20260630" and F.known_at_of("") == ""


def test_same_version_once_correction_is_new_version(conn):
    """TC-FS-02 · 같은 판은 한 벌 · 정정본은 새 판으로 옆에 쌓인다(옛 판을 지우지 않는다)."""
    orig = [F.normalize_row(acct("20240321001895", "매출액", "13,436,000"), fetched_at="2024-03-22T12:30:00+09:00")]
    F.upsert_rows(conn, orig)
    F.upsert_rows(conn, orig)
    assert conn.execute("SELECT COUNT(*) FROM financial_statement").fetchone()[0] == 1
    fixed = [F.normalize_row(acct("20260630000500", "매출액", "13,400,000"), fetched_at="2026-07-01T12:30:00+09:00")]
    F.upsert_rows(conn, fixed)
    rows = conn.execute("SELECT rcept_no, known_at, thstrm_amount FROM financial_statement ORDER BY rcept_no").fetchall()
    assert [tuple(r) for r in rows] == [("20240321001895", "20240321", 13436000), ("20260630000500", "20260630", 13400000)]


def _disc(conn, rcept_no, report_nm, corp="00126380"):
    from collector import disclosure as D
    D.upsert_rows(conn, [D.normalize_item({"corp_code": corp, "corp_name": "가", "stock_code": "005930", "corp_cls": "Y",
                                            "report_nm": report_nm, "rcept_no": rcept_no, "rcept_dt": rcept_no[:8]},
                                           "A", fetched_at="2026-10-04T19:00:00+09:00")])


def test_first_known_is_earliest_filing_of_that_period(conn):
    """TC-FS-03 · 처음 공개일 = 그 기간 보고서 가운데 가장 이른 접수일 — 다른 기간 · 다른 보고서는 섞이지 않는다."""
    F.upsert_rows(conn, [F.normalize_row(acct("20260630000500", "매출액", "1"), fetched_at="x")])
    _disc(conn, "20240321001895", "사업보고서 (2023.12)")
    _disc(conn, "20240328001696", "[기재정정]사업보고서 (2023.12)")
    _disc(conn, "20260630000500", "[기재정정]사업보고서 (2023.12)")
    _disc(conn, "20230320000001", "사업보고서 (2022.12)")                 # 다른 기간
    _disc(conn, "20231114000001", "분기보고서 (2023.09)")                 # 다른 보고서
    assert F.link_first_known(conn) == 1
    assert conn.execute("SELECT first_known_at FROM financial_statement").fetchone()[0] == "20240321"
    assert F.link_first_known(conn) == 0                                  # 바뀐 것이 없으면 고치지 않는다


def test_first_known_never_after_known_at(conn):
    """TC-FS-04 · 공시 목록이 덜 받혀 원본이 값의 판보다 늦게 나오면 값의 접수일로 둔다(미래 날짜로 거르지 않게)."""
    F.upsert_rows(conn, [F.normalize_row(acct("20240321001895", "매출액", "1"), fetched_at="x")])
    _disc(conn, "20240401000001", "[첨부추가]사업보고서 (2023.12)")
    F.link_first_known(conn)
    assert conn.execute("SELECT first_known_at FROM financial_statement").fetchone()[0] == "20240321"


def test_guess_reports_december_first():
    """TC-FS-05 · 12월 결산 후보가 먼저 — 3월 분기보고서는 1분기, 9월은 3분기 · 다른 결산월은 뒤 후보."""
    assert F.guess_reports("사업보고서", "2025.12")[0] == ("2025", "11011")
    assert F.guess_reports("반기보고서", "2026.06")[0] == ("2026", "11012")
    assert F.guess_reports("분기보고서", "2026.03")[0] == ("2026", "11013")
    assert F.guess_reports("분기보고서", "2026.09")[0] == ("2026", "11014")
    six = F.guess_reports("분기보고서", "2025.12")            # 6월 결산 회사의 2분기 같은 꼴
    assert {c for _, c in six} == {"11013", "11014"} and ("2024", "11013") in six
    assert F.guess_reports("주주총회소집결의", "") == []


def test_daily_asks_until_receipt_matches_then_folds_missing(conn, monkeypatch):
    """TC-FS-06 · 일일 받기 — 응답의 접수번호가 공시와 같으면 끝 · 다르면 다음 후보 · 끝내 없으면 시도를 세고 다섯 번이면 접는다."""
    _disc(conn, "20261002000100", "사업보고서 (2026.06)", corp="00999999")     # 6월 결산 — 두 번째 후보(2025)에서 맞는다
    _disc(conn, "20261002000200", "분기보고서 (2026.03)", corp="00888888")     # 끝내 값이 안 온다
    asked = []

    def fake_get(limiter, url, params, session=None):
        limiter.calls += 1
        asked.append((params["corp_code"], params["bsns_year"], params["reprt_code"]))
        if params["bsns_year"] == "2025" and params["reprt_code"] == "11011" and "00999999" in params["corp_code"]:
            return FakeResp({"status": "000", "list": [acct("20261002000100", "매출액", "5", corp="00999999",
                                                            stock="111111", year="2025", dt="2025.07.01 ~ 2026.06.30")]})
        return FakeResp({"status": "013", "message": "조회된 데이타가 없습니다."})

    monkeypatch.setattr(dart, "_get", fake_get)
    F.run_daily(days=3650, quiet=True)
    assert ("00999999", "2026", "11011") in asked and ("00999999", "2025", "11011") in asked
    assert conn.execute("SELECT COUNT(*) FROM financial_statement WHERE rcept_no='20261002000100'").fetchone()[0] == 1
    st = conn.execute("SELECT status, attempts FROM ingest_day WHERE source='dart_fin_rcept' AND bas_dt='20261002000200'").fetchone()
    assert tuple(st) == ("pending", 1)
    for _ in range(F.MAX_ATTEMPTS - 1):
        F.run_daily(days=3650, quiet=True)
    st = conn.execute("SELECT status FROM ingest_day WHERE source='dart_fin_rcept' AND bas_dt='20261002000200'").fetchone()
    assert st[0] == "missing"
    before = len(asked)
    F.run_daily(days=3650, quiet=True)
    assert len(asked) == before                                       # 접은 것 · 받은 것은 다시 묻지 않는다
