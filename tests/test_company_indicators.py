"""기업 지표 시험 (TC-CIN) — `app/services/company_indicators.py` · `GET /api/data/indicators` (할 일 ①-16 · 2026-10-30).

여기서 지키는 것 —
1. 계산 — PER = 종가 ÷ 보고된 기본주당이익(시가총액 ÷ 순이익이 아니다) · PBR = 시가총액 ÷ 지배지분 자본 · ROE = 지배주주 순이익 ÷ 지배지분 자본.
2. 우선주가 상장된 회사의 PBR 은 `approx` 와 한계 글을 단다.
3. 견줄 수 없으면 값 대신 까닭 — 적자(PER) · 자본잠식(PBR · ROE) · 지배 몫 계정 없음(총액과 섞지 않음) · 금융회사(영업이익률).
4. 비지배지분이 없는 회사는 당기순이익 · 자본총계를 그대로 쓰고 그 사실을 글로.
5. 연결이 없으면 별도로 바꾸고 `fs_note` 에 적는다.
6. 배당 — 종가 날짜 앞 12개월 안 기준일의 현금배당 합 · 미래 기준일 · 검토 필요 줄은 뺀다.
7. 시점 고정 — `as_of` 보다 늦게 접수된 판은 쓰지 않는다(`data_financials.choose_version` 한 곳).
8. 숫자마다 식 · 기준 · 문장 · 권유 낱말 없음 · 야후를 읽지 않는다.
9. 라우트 — 잘못된 종목 422 · 자료 없음 404 · 정상 200 · 수집 DB 없음 503(명령 힌트는 관리자에게만).
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.routes import data as D
from app.services import company_indicators as CI

BANNED = ("추천", "최적", "유망", "베스트", "안전한", "매수", "매도", "사세요", "파세요", "유리합니다", "확실", "보장")
ROOT = Path(__file__).resolve().parents[1]

NI, EQ, EPS = CI.ACC_NI, CI.ACC_EQ, CI.ACC_EPS[0]


def _db(tmp_path, monkeypatch, *, fs="CFS", ni=1_000, eq=10_000, eps=100.0, with_owner=True, with_nci=False, price=1_500,
        mcap=300_000, preferred=False, revenue=5_000, op=500, dividends=(), known="20260310", year="2025", extra_year=None):
    """가짜 수집 DB 한 개 — 종목 000001(「가짜전자」) 한 곳."""
    path = tmp_path / "수집DB.sqlite3"
    c = sqlite3.connect(path)
    c.executescript("""
        CREATE TABLE price_daily(bas_dt TEXT, srtn_cd TEXT, itms_nm TEXT, clpr REAL, lstg_st_cnt REAL, mrkt_tot_amt REAL);
        CREATE TABLE financial_statement_full(stock_code TEXT, bsns_year TEXT, reprt_code TEXT, fs_div TEXT, sj_div TEXT, ord INT,
            account_id TEXT, account_nm TEXT, rcept_no TEXT, thstrm_amount REAL, known_at TEXT, first_known_at TEXT);
        CREATE TABLE financial_statement(stock_code TEXT, bsns_year TEXT, reprt_code TEXT, fs_div TEXT, sj_div TEXT, ord INT,
            account_nm TEXT, rcept_no TEXT, scope TEXT, thstrm_amount REAL);
        CREATE TABLE dividend(srtn_cd TEXT, record_dt TEXT, dps REAL, div_type TEXT, needs_review INT);
        CREATE TABLE dart_company(stock_code TEXT, stock_name TEXT, corp_code TEXT, last_seen_at TEXT);
    """)
    c.execute("INSERT INTO dart_company VALUES('000001','가짜전자','c1','2026-10-29')")
    c.execute("INSERT INTO price_daily VALUES('20261029','000001','가짜전자',?,200,?)", (price, mcap))
    if preferred:
        c.execute("INSERT INTO price_daily VALUES('20261029','000005','가짜전자우',900,50,45000)")

    def put(y, rc, kn, items):
        for i, (acc, nm, v) in enumerate(items):
            c.execute("INSERT INTO financial_statement_full VALUES('000001',?,?,?,?,?,?,?,?,?,?,?)",
                      (y, "11011", fs, "IS", i, acc, nm, rc, v, kn, kn))

    items = []
    if with_owner:
        items += [(NI, "지배기업 소유주지분", ni), (EQ, "지배기업 소유주지분", eq)]
    else:
        items += [(CI.ACC_NI_TOTAL, "당기순이익", ni), (CI.ACC_EQ_TOTAL, "자본총계", eq)]
    if with_nci:
        items += [(CI.ACC_NCI[0], "비지배지분", 1)]
    if eps is not None:
        items += [(EPS, "기본주당이익", eps)]
    put(year, "20260310000001", known, items)
    if extra_year:
        put(extra_year[0], "20250310000001", extra_year[1], [(NI, "지배", 7), (EQ, "지배", 70), (EPS, "기본주당이익", 70.0)])
    for nm, v in (("매출액", revenue), ("영업이익", op)):
        if v is not None:
            c.execute("INSERT INTO financial_statement VALUES('000001',?,?,?,?,?,?,?,?,?)", (year, "11011", fs, "IS", 1, nm, "20260310000001", "major", v))
    for rec, dps, review in dividends:
        c.execute("INSERT INTO dividend VALUES('000001',?,?,'현금배당',?)", (rec, dps, review))
    c.commit()
    c.close()
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(path))
    return path


def _m(out, key):
    return next(m for m in out["metrics"] if m["key"] == key)


def test_ratios_and_basis(tmp_path, monkeypatch):
    """TC-CIN-01 · PER = 종가 ÷ 보고 EPS(15.0) · PBR = 시가총액 ÷ 지배지분 자본(30.0) · ROE = 순이익 ÷ 자본(10.0) · 기준 글."""
    _db(tmp_path, monkeypatch)
    out = CI.read_indicators("000001")
    assert out["name"] == "가짜전자" and out["price"]["close"] == 1500 and out["price"]["trade_date"] == "2026-10-29"
    assert _m(out, "per")["value"] == 15.0 and _m(out, "pbr")["value"] == 30.0 and _m(out, "roe")["value"] == 10.0
    assert _m(out, "eps")["value"] == 100.0 and _m(out, "operating_margin")["value"] == 10.0
    per = _m(out, "per")
    assert "종가" in per["formula"] and "기본주당이익" in per["formula"] and "2025 사업보고서" in per["basis"] and "2026-03-10" in per["basis"]
    assert out["report"]["fs"] == "CFS" and out["fs_note"] == "연결재무제표 기준" and out["report"]["url"].endswith("20260310000001")
    assert not _m(out, "pbr").get("approx")


def test_per_uses_reported_eps_not_market_cap(tmp_path, monkeypatch):
    """TC-CIN-02 · 시가총액 ÷ 순이익(300 ÷ 1 = 300)이 아니라 종가 ÷ 보고 EPS — 우선주 몫이 든 순이익으로 나눠 어긋나는 것을 막는다."""
    _db(tmp_path, monkeypatch, ni=1_000, eps=100.0, mcap=300_000, price=1_500)
    per = _m(CI.read_indicators("000001"), "per")["value"]
    assert per == 15.0 and per != round(300_000 / 1_000, 1)


def test_preferred_shares_mark_pbr_approx(tmp_path, monkeypatch):
    """TC-CIN-03 · 같은 날 「가짜전자우」 가 상장돼 있으면 PBR 에 approx · 한계 글."""
    _db(tmp_path, monkeypatch, preferred=True)
    pbr = _m(CI.read_indicators("000001"), "pbr")
    assert pbr["value"] == 30.0 and pbr["approx"] is True and "우선주" in pbr["sentence"]


def test_loss_blocks_per(tmp_path, monkeypatch):
    """TC-CIN-04 · 보고 EPS 가 음수면 PER 값 없음 + 「적자라 계산하지 않음」 · 나머지는 그대로."""
    _db(tmp_path, monkeypatch, eps=-50.0, ni=-500)
    out = CI.read_indicators("000001")
    per = _m(out, "per")
    assert per["value"] is None and per["reason"] == "적자라 계산하지 않음"
    assert _m(out, "roe")["value"] == -5.0 and _m(out, "pbr")["value"] == 30.0


def test_missing_eps_gives_reason(tmp_path, monkeypatch):
    """TC-CIN-05 · 보고 EPS 가 없으면 PER 도 EPS 도 줄표 + 까닭(지어내지 않는다)."""
    _db(tmp_path, monkeypatch, eps=None)
    out = CI.read_indicators("000001")
    assert _m(out, "eps")["value"] is None and _m(out, "eps")["reason"]
    assert _m(out, "per")["value"] is None and "기본주당이익" in _m(out, "per")["reason"]


def test_capital_impairment(tmp_path, monkeypatch):
    """TC-CIN-06 · 지배지분 자본이 0 이하면 PBR · ROE 값 없음 + 「자본잠식」."""
    _db(tmp_path, monkeypatch, eq=-100)
    out = CI.read_indicators("000001")
    assert _m(out, "pbr")["value"] is None and "자본잠식" in _m(out, "pbr")["reason"]
    assert _m(out, "roe")["value"] is None and "자본잠식" in _m(out, "roe")["reason"]


def test_total_not_mixed_with_owner_share(tmp_path, monkeypatch):
    """TC-CIN-07 · 연결인데 지배 몫 계정이 없고 비지배지분 계정이 있으면 총액을 쓰지 않는다 — ROE · PBR 줄표."""
    _db(tmp_path, monkeypatch, with_owner=False, with_nci=True)
    out = CI.read_indicators("000001")
    assert _m(out, "roe")["value"] is None and _m(out, "pbr")["value"] is None


def test_total_used_when_no_minority(tmp_path, monkeypatch):
    """TC-CIN-08 · 비지배지분이 없는 회사는 당기순이익 · 자본총계를 그대로 쓰고 그 사실을 글로."""
    _db(tmp_path, monkeypatch, with_owner=False, with_nci=False)
    out = CI.read_indicators("000001")
    roe = _m(out, "roe")
    assert roe["value"] == 10.0 and "비지배지분이 없는 회사" in roe["basis"]


def test_separate_statement_fallback(tmp_path, monkeypatch):
    """TC-CIN-09 · 연결이 없고 별도만 있으면 별도 값으로 계산하고 fs_note 에 적는다(별도는 총액 계정)."""
    _db(tmp_path, monkeypatch, fs="OFS", with_owner=False)
    out = CI.read_indicators("000001")
    assert out["report"]["fs"] == "OFS" and "별도재무제표" in out["fs_note"] and _m(out, "roe")["value"] == 10.0


def test_financial_company_no_operating_margin(tmp_path, monkeypatch):
    """TC-CIN-10 · 매출액 · 영업이익 항목이 없는 회사(금융)는 영업이익률 줄표 + 까닭 · 다른 지표는 그대로."""
    _db(tmp_path, monkeypatch, revenue=None, op=None)
    out = CI.read_indicators("000001")
    om = _m(out, "operating_margin")
    assert om["value"] is None and om["reason"] and _m(out, "per")["value"] == 15.0


def test_dividend_window(tmp_path, monkeypatch):
    """TC-CIN-11 · 12개월 안 기준일의 합만(100 + 50) · 1년 전 · 미래 기준일 · 검토 필요 줄은 뺀다 → 150 ÷ 1500 = 10%."""
    _db(tmp_path, monkeypatch, dividends=[("20260630", 100.0, 0), ("20251231", 50.0, 0), ("20251001", 999.0, 1),
                                          ("20250101", 777.0, 0), ("20261130", 888.0, 0)])
    dy = _m(CI.read_indicators("000001"), "dividend_yield")
    assert dy["value"] == 10.0 and "실제 지급과 다를 수 있음" in dy["basis"]


def test_point_in_time(tmp_path, monkeypatch):
    """TC-CIN-12 · as_of 가 접수일(2026-03-10) 이하면 그 판을 쓰지 않고 앞 해(2024)가 있으면 그 해 값을 쓴다 — 미래 값이 섞이지 않는다."""
    _db(tmp_path, monkeypatch, extra_year=("2024", "20250310"))
    early = CI.read_indicators("000001", as_of="2026-03-10")
    assert early["report"]["bsns_year"] == "2024" and _m(early, "eps")["value"] == 70.0
    late = CI.read_indicators("000001", as_of="2026-03-11")
    assert late["report"]["bsns_year"] == "2025" and _m(late, "eps")["value"] == 100.0


def test_wording_no_advice_no_yahoo(tmp_path, monkeypatch):
    """TC-CIN-13 · 모든 문장에 권유 낱말이 없고 서비스가 야후를 읽지 않는다 · 지표마다 식 · 기준이 있다."""
    _db(tmp_path, monkeypatch, dividends=[("20260630", 100.0, 0)])
    out = CI.read_indicators("000001")
    text = json.dumps(out, ensure_ascii=False)
    assert not [w for w in BANNED if w in text]
    assert "투자 권유가 아닙니다" in out["notice"]
    assert all(m["formula"] and m["basis"] and m["sentence"] for m in out["metrics"])
    src = (ROOT / "app" / "services" / "company_indicators.py").read_text(encoding="utf-8").lower()
    assert "yfinance" not in src and "yahoo" not in src      # 머리 글의 「야후」 는 옛 화면 설명(한글)이라 걸리지 않는다


def _call(symbol, roles=()):
    return asyncio.run(D.indicators(symbol=symbol, as_of=None, pit="strict", user={"roles": list(roles)}))


def test_route_status_codes(tmp_path, monkeypatch):
    """TC-CIN-14 · 라우트 — 정상 200 값 · 잘못된 종목 422 · 자료 없음 404."""
    _db(tmp_path, monkeypatch)
    assert _m(_call("000001"), "per")["value"] == 15.0
    with pytest.raises(HTTPException) as e1:
        _call("12345")
    assert e1.value.status_code == 422 and e1.value.detail["code"] == "bad_symbol"
    with pytest.raises(HTTPException) as e2:
        _call("999999")
    assert e2.value.status_code == 404 and "hint" not in e2.value.detail


def test_universe_lists_collected_companies(tmp_path, monkeypatch):
    """TC-CIN-16 · 지표를 볼 수 있는 종목 = 수집 대상 상장사(코드 · 이름) — 지표 비교의 종목 추가가 이 안에서만 고른다."""
    _db(tmp_path, monkeypatch)
    u = asyncio.run(D.indicators_universe(user={"roles": []}))
    assert u["count"] == 1 and u["companies"] == [{"code": "000001", "name": "가짜전자"}] and "수집 대상" in u["note"]


def test_sector_medians(tmp_path, monkeypatch):
    """TC-CIN-17 · 업종(KSIC 중분류)별 PER · PBR 중앙값 — 같은 규칙 · 흑자만 센 곳 수 · 적은 업종 표시 · 업종 코드 없는 곳은 「분류 못 찾음」."""
    path = _db(tmp_path, monkeypatch)
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE ksic_code(revision TEXT, level TEXT, code TEXT, name TEXT, parent_code TEXT)")
    c.executemany("INSERT INTO ksic_code VALUES('11',?,?,?,?)", [("중분류", "26", "전자 부품 제조업", "C"), ("대분류", "C", "제조업", "")])
    c.execute("UPDATE dart_company SET stock_code='000001'")
    c.execute("ALTER TABLE dart_company ADD COLUMN induty_code TEXT")
    c.execute("UPDATE dart_company SET induty_code='26110'")
    # 둘째 · 셋째 종목: 같은 업종 · EPS 50(PER 30) / 적자 · 업종 코드 없는 넷째
    for code, nm, eps, eq, mcap, ind in (("000002", "둘째", 50.0, 20_000, 400_000, "26299"), ("000003", "셋째", -10.0, 10_000, 100_000, "26299"), ("000004", "넷째", 10.0, 1_000, 5_000, None)):
        c.execute("INSERT INTO dart_company(stock_code, stock_name, corp_code, last_seen_at, induty_code) VALUES(?,?,?,?,?)", (code, nm, "c" + code, "2026-10-29", ind))
        c.execute("INSERT INTO price_daily VALUES('20261029',?,?,?,200,?)", (code, nm, 1_500, mcap))
        for i, (acc, v) in enumerate(((EPS, eps), (EQ, eq))):
            c.execute("INSERT INTO financial_statement_full VALUES(?,'2025','11011','CFS','IS',?,?,'x','2026XX',?,'20260310','20260310')", (code, i, acc, v))
    c.commit()
    c.close()
    out = asyncio.run(D.indicators_sectors(user={"roles": []}))
    g = {x["code"]: x for x in out["groups"]}
    assert out["universe"] == 4 and out["as_of"] == "2026-10-29" and "업종 전체 지수가 아니고" in out["notice"]
    e = g["26"]                                                                              # 전자 부품: 가짜전자(PER 15 · PBR 30) · 둘째(PER 30 · PBR 20) · 셋째(적자 · PBR 10)
    assert e["n"] == 3 and e["thin"] is False and e["name"] == "전자 부품 제조업" and e["section"]["name"] == "제조업"
    assert e["per"] == {"median": 22.5, "n": 2} and e["pbr"] == {"median": 20.0, "n": 3}   # 적자는 PER 에서 빠지고 곳 수가 준다
    assert g[""]["name"] == "분류 못 찾음" and g[""]["n"] == 1 and g[""]["thin"] is True
    assert [x["name"] for x in e["top"]][:1] == ["둘째"]                                      # 시가총액 큰 순


def test_route_no_db_hint_admin_only(tmp_path, monkeypatch):
    """TC-CIN-15 · 수집 DB 없음 503 — 할 일(명령)은 관리자 응답에만."""
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(tmp_path / "없음.sqlite3"))
    with pytest.raises(HTTPException) as user:
        _call("000001")
    with pytest.raises(HTTPException) as admin:
        _call("000001", roles=("admin",))
    assert user.value.status_code == 503 and "hint" not in user.value.detail
    assert "hint" in admin.value.detail
