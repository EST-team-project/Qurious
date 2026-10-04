"""공시 목록 수집 시험 (TC-DC) — `collector/disclosure.py` (목표 기능 ① W7 · 설계서 5.1.5).

여기서 지키는 것 —
1. 보고서 이름을 칸으로 나눈다 — 머리 [기재정정] · 꼬리 설명(긴 공백 뒤) · 정기보고서 기간 (YYYY.MM).
2. 같은 접수번호를 다시 받으면 처음 받은 시각은 그대로 · 비고(rm)와 마지막 받은 시각만 바뀐다 · 유형은 빈칸으로 덮이지 않는다.
3. 쪽을 끝까지 넘기고, 같은 응답 원문은 두 번 쌓지 않는다(매일 같은 사흘을 다시 받는다).
4. 끝난 (창 · 유형 · 시장)은 다시 받지 않고, 오늘이 든 창은 「끝남」 으로 남기지 않는다. 한도에 닿으면 깔끔히 멈춘다.
5. 보존 원문으로 다시 정규화할 때 네트워크를 타지 않는다.

네트워크 · 실제 수집 DB 를 쓰지 않는다 — DART 호출을 가짜 응답으로 바꾼다.
"""
from __future__ import annotations

import json
from datetime import datetime

import pytest

from collector import db
from collector import disclosure as D
from collector.sources import dart


class FakeResp:
    def __init__(self, doc: dict, status: int = 200):
        self.content = json.dumps(doc, ensure_ascii=False).encode("utf-8")
        self.status_code = status
        self.headers = {}


def item(rcept_no: str, report_nm: str, *, stock="005930", corp="00126380", name="삼성전자", cls="Y", rm=""):
    return {"corp_code": corp, "corp_name": name, "stock_code": stock, "corp_cls": cls, "report_nm": report_nm,
            "rcept_no": rcept_no, "flr_nm": name, "rcept_dt": rcept_no[:8], "rm": rm}


def page(items, page_no=1, total_page=1):
    return {"status": "000", "message": "정상", "page_no": page_no, "page_count": 100,
            "total_count": len(items) * total_page, "total_page": total_page, "list": items}


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    path = tmp_path / "market.sqlite3"
    real = db.connect
    monkeypatch.setattr(db, "connect", lambda p=None: real(path))
    c = real(path)
    yield c
    c.close()


def test_split_report_name():
    """TC-DC-01 · 머리 [..] 여럿 · 긴 공백 뒤 꼬리 설명 · 정기보고서 기간을 가른다(공백을 접기 전에 나눈다)."""
    a = D.split_report_nm("[기재정정]주주총회소집결의              (임시주주총회)")
    assert (a.title, a.revision, a.period, a.report_nm) == ("주주총회소집결의", "기재정정", "",
                                                            "[기재정정]주주총회소집결의 (임시주주총회)")
    b = D.split_report_nm("[기재정정][첨부추가]분기보고서 (2026.03)")
    assert (b.title, b.revision, b.period) == ("분기보고서", "기재정정·첨부추가", "2026.03")
    c = D.split_report_nm("주요사항보고서(유상증자결정)")
    assert (c.title, c.revision, c.period) == ("주요사항보고서(유상증자결정)", "", "")
    d = D.split_report_nm("투자판단관련주요경영사항(임상시험결과)        (제2상 임상시험결과보고서(CSR) 수령)")
    assert d.title == "투자판단관련주요경영사항(임상시험결과)"


def test_refetch_keeps_first_fetch_time_and_type(conn):
    """TC-DC-02 · 다시 받으면 fetched_at 은 그대로 · rm · updated_at 은 새 값 · 빈 유형은 있던 유형을 덮지 않는다."""
    r1 = D.normalize_item(item("20260930000001", "사업보고서 (2025.12)"), "A", fetched_at="2026-10-01T12:30:00+09:00")
    D.upsert_rows(conn, [r1])
    r2 = D.normalize_item(item("20260930000001", "사업보고서 (2025.12)", rm="정"), "", fetched_at="2026-10-04T12:30:00+09:00")
    D.upsert_rows(conn, [r2])
    row = conn.execute("SELECT * FROM disclosure WHERE rcept_no='20260930000001'").fetchone()
    assert (row["fetched_at"], row["updated_at"], row["rm"], row["pblntf_ty"], row["period"]) == (
        "2026-10-01T12:30:00+09:00", "2026-10-04T12:30:00+09:00", "정", "A", "2025.12")


def test_paging_and_raw_dedupe(conn, monkeypatch):
    """TC-DC-03 · 쪽을 끝까지 넘기고, 같은 응답을 다시 받아도 원문은 한 벌 · 줄도 한 벌."""
    pages = {1: page([item("20261002000001", "현금ㆍ현물배당결정")], 1, 2),
             2: page([item("20261002000002", "자기주식취득결정")], 2, 2)}
    calls = []

    def fake_get(limiter, url, params, session=None):
        calls.append(params["page_no"])
        limiter.calls += 1
        return FakeResp(pages[params["page_no"]])

    monkeypatch.setattr(dart, "_get", fake_get)
    # 받은 시각을 부를 때마다 1초씩 — 같은 초면 원문 표의 기본 키(받은 시각)가 같아 중복이 저절로 덮인다
    tick = iter(range(100))
    monkeypatch.setattr(D.raw_store, "now_kst_iso", lambda: f"2026-10-04T19:00:{next(tick):02d}+09:00")
    lim, t = D._limiter(), D.Tally()
    lim.min_interval = 0
    n = D.fetch_combo(conn, lim, None, pblntf_ty="I", corp_cls="Y", bgn="20261002", end="20261002", tally=t)
    assert (n, calls, t.new) == (2, [1, 2], 2)
    n2 = D.fetch_combo(conn, lim, None, pblntf_ty="I", corp_cls="Y", bgn="20261002", end="20261002", tally=D.Tally())
    assert n2 == 2
    assert conn.execute("SELECT COUNT(*) FROM disclosure").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM raw_response WHERE target LIKE 'list/%'").fetchone()[0] == 2


def test_resume_skips_done_and_open_window_is_partial(conn, monkeypatch):
    """TC-DC-04 · 끝난 조합은 다시 부르지 않는다 · 오늘이 든 창은 partial 로 남아 다음 실행이 다시 받는다."""
    seen = []

    def fake_get(limiter, url, params, session=None):
        seen.append((params["pblntf_ty"], params["corp_cls"], params["bgn_de"]))
        limiter.calls += 1
        return FakeResp({"status": "013", "message": "조회된 데이타가 없습니다."})

    monkeypatch.setattr(dart, "_get", fake_get)
    monkeypatch.setattr(D, "_limiter", lambda: _fast())
    today = datetime.now().strftime("%Y%m%d")
    D.run(bgn="20260101", end=today, types=["A"], markets=["Y"], resume=True, max_calls=None, quiet=True)
    first = len(seen)
    marks = dict(conn.execute("SELECT bas_dt, status FROM ingest_day WHERE source='dart_list'").fetchall())
    assert marks[D.combo_key("20260101", "20260331", "A", "Y")] == "done"
    assert any(k.endswith(today + ":AY") and v == "partial" for k, v in marks.items())
    D.run(bgn="20260101", end=today, types=["A"], markets=["Y"], resume=True, max_calls=None, quiet=True)
    # 두 번째 실행은 끝나지 않은 창(오늘이 든 분기) 하나만 다시 부른다
    assert len(seen) - first == 1


def _fast():
    """간격 0 — 가짜 응답이라 기다릴 까닭이 없다."""
    from collector.ratelimit import RateLimiter
    return RateLimiter(0, name="DART")


def test_quota_stop_is_clean(conn, monkeypatch):
    """TC-DC-05 · 이번 실행 호출 상한에 닿으면 예외 없이 멈추고 stopped 를 남긴다 — 멈춘 조합은 끝남으로 남지 않는다."""
    def fake_get(limiter, url, params, session=None):
        limiter.calls += 1
        return FakeResp(page([item(f"2026010{params['page_no']}000001", "사업보고서 (2025.12)")],
                             params["page_no"], 5))

    monkeypatch.setattr(dart, "_get", fake_get)
    monkeypatch.setattr(D, "_limiter", _fast)
    t = D.run(bgn="20260101", end="20260331", types=["A"], markets=["Y"], resume=True, max_calls=3, quiet=True)
    assert t.stopped and t.calls == 3
    assert conn.execute("SELECT COUNT(*) FROM ingest_day WHERE source='dart_list' AND status='done'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM disclosure").fetchone()[0] == 3     # 받은 쪽까지는 남는다


def test_reparse_uses_no_network(conn, monkeypatch):
    """TC-DC-06 · 보존 원문으로 다시 정규화 — 네트워크를 부르면 실패한다."""
    def fake_get(limiter, url, params, session=None):
        limiter.calls += 1
        return FakeResp(page([item("20261002000009", "[기재정정]사업보고서 (2025.12)")]))

    monkeypatch.setattr(dart, "_get", fake_get)
    D.fetch_combo(conn, _fast(), None, pblntf_ty="A", corp_cls="Y", bgn="20261002", end="20261002", tally=D.Tally())
    conn.execute("DELETE FROM disclosure")

    def boom(*a, **k):
        raise AssertionError("재정규화가 네트워크를 불렀다")

    monkeypatch.setattr(dart, "_get", boom)
    assert D.run_reparse(quiet=True) == 1
    row = conn.execute("SELECT pblntf_ty, revision, period FROM disclosure").fetchone()
    assert tuple(row) == ("A", "기재정정", "2025.12")


def test_quarter_windows_stay_within_three_months():
    """TC-DC-07 · 창은 달력 분기로 자르고 3개월을 넘지 않는다(DART 는 3개월을 넘으면 status=100 · #33 실측)."""
    w = D.quarter_windows("20200101", "20261004")
    assert w[0] == ("20200101", "20200331") and w[-1] == ("20261001", "20261004") and len(w) == 28
    for a, b in w:
        da, db_ = datetime.strptime(a, "%Y%m%d"), datetime.strptime(b, "%Y%m%d")
        assert (db_ - da).days < 92
