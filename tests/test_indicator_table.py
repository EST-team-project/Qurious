"""지표 비교 표 시험 (TC-IT) — `GET /api/data/indicators/table` · `app/services/data_indicator_table.py` ·
`public/js/company-compare-table.js` · 지표 비교 화면 (D11 · 2026-11-04).

강사님 lumina-invest 의 「전체 종목 표 + 시장 · 업종 필터 + 30종목 쪽 + 열 정렬」을 우리 수집 대상 상장사로 옮겼다(새 라이브러리 없이 일반 표).
여기서 지키는 것 —
서버 (가짜 수집 DB — 개발 DB 를 읽지 않는다)
 1. 응답 꼴 — 칸 정의(식 포함) · 필터 목록(몇 곳) · 줄마다 기준 한 줄 · 출처 · 한계 글 · 투자 권유 낱말 없음.
 2. 모든 줄의 값이 지표 대시보드(`read_indicators`)의 값과 같다 — 같은 서비스를 모아 쓰므로 어긋날 수 없다는 것을 전부 견줘 고정한다.
 3. 정렬 — 오름 · 내림 · 값 없는 줄은 어느 쪽이든 맨 뒤 · 같은 값은 코드 오름차순 · 문자 칸(이름 · 시장 · 업종).
 4. 쪽 — 30개씩 · 마지막 쪽 · 끝을 넘으면 마지막 쪽 · 쪽을 넘겨도 줄이 겹치거나 빠지지 않는다 · 크기 바꾸기.
 5. 필터 — 시장 · 업종(분류 못 찾음 포함) · 이름 · 코드 검색 · 겹쳐 쓰기 · 결과 없음.
 6. 값 없음 — null + 까닭(적자 · 자본잠식 · 자료 없음) · 별도재무제표 · 근사 · 상태(완료 · 일부 값 없음 · 자료 없음).
 7. 잘못된 입력 422 · 수집 DB 없음 503(명령 힌트는 관리자만) · 표 모양이 달라도(시장 · 업종 칸 없음) 죽지 않는다.
 8. 라우트 — 실제 FastAPI 라우터로 질의 인자 · JSON · 오류 모양.
 9. 저장 — 두 번째 요청은 종목을 다시 훑지 않는다 · 비우면 다시 · 새 종가 날짜가 들어오면 다시.
화면 (node 로 순수 함수를 그대로 돌린다 — 파이썬으로 다시 쓰면 고친 곳을 시험하지 못한다)
10. 질의 문자열 · 정렬 바꾸기 · 쪽 글 · 값 글(자릿수 · 근사 · 줄표) · 줄 · 머리 · 필터 목록.
11. 마크업 · 연결 — 지표 비교 view 안의 칸 · 링크 · 기존 칩 비교 유지 · 좁은 화면 규칙 · 금지 낱말.
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import sqlite3
import subprocess
from collections import Counter
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.lib.session import get_current_user
from app.routes import data as D
from app.services import company_indicators as CI
from app.services import data_indicator_table as T

ROOT = Path(__file__).resolve().parents[1]
BANNED = ("추천", "최적", "유망", "베스트", "안전한", "매수", "매도", "사세요", "파세요", "유리합니다", "확실", "보장", "저평가", "우수", "양호")
NI, EQ, EPS = CI.ACC_NI, CI.ACC_EQ, CI.ACC_EPS[0]

# 종목 구성 — 평범한 65곳(000001~000065) + 특별한 6곳. 합 71곳 → 30 · 30 · 11 로 세 쪽.
PLAIN = 65
SPECIAL = {
    "900001": ("적자회사", "Y", "26299"),
    "900002": ("잠식회사", "K", "47111"),
    "900003": ("자료없음", "K", "64110"),
    "900004": ("별도회사", "Y", "26299"),
    "900005": ("분류없음", "", ""),
    "900006": ("우선주회사", "Y", "47111"),
}
TOTAL = PLAIN + len(SPECIAL)


def _world(tmp_path, monkeypatch, *, ddl_extra=True, with_ksic=True, price_date="20261029"):
    """가짜 수집 DB — 평범한 65곳 + 특별한 6곳. 평범한 곳 i 의 EPS = 10·i(종가 1500 → PER = 150 ÷ i)라 일부는 반올림하면 값이 같다(동률 시험)."""
    path = tmp_path / "수집DB.sqlite3"
    c = sqlite3.connect(path)
    c.executescript("""
        CREATE TABLE price_daily(bas_dt TEXT, srtn_cd TEXT, itms_nm TEXT, clpr REAL, lstg_st_cnt REAL, mrkt_tot_amt REAL);
        CREATE TABLE financial_statement_full(stock_code TEXT, bsns_year TEXT, reprt_code TEXT, fs_div TEXT, sj_div TEXT, ord INT,
            account_id TEXT, account_nm TEXT, rcept_no TEXT, thstrm_amount REAL, known_at TEXT, first_known_at TEXT);
        CREATE TABLE financial_statement(stock_code TEXT, bsns_year TEXT, reprt_code TEXT, fs_div TEXT, sj_div TEXT, ord INT,
            account_nm TEXT, rcept_no TEXT, scope TEXT, thstrm_amount REAL);
        CREATE TABLE dividend(srtn_cd TEXT, record_dt TEXT, dps REAL, div_type TEXT, needs_review INT);
    """)
    if ddl_extra:
        c.execute("CREATE TABLE dart_company(stock_code TEXT, stock_name TEXT, corp_code TEXT, last_seen_at TEXT, corp_cls TEXT, induty_code TEXT)")
    else:
        c.execute("CREATE TABLE dart_company(stock_code TEXT, stock_name TEXT, corp_code TEXT, last_seen_at TEXT)")
    if with_ksic:
        c.execute("CREATE TABLE ksic_code(revision TEXT, level TEXT, code TEXT, name TEXT, parent_code TEXT)")
        c.executemany("INSERT INTO ksic_code VALUES('11',?,?,?,?)",
                      [("중분류", "26", "전자 부품 제조업", "C"), ("중분류", "47", "소매업", "G"), ("중분류", "64", "금융업", "K"),
                       ("대분류", "C", "제조업", ""), ("대분류", "G", "도소매업", ""), ("대분류", "K", "금융 및 보험업", "")])

    def company(code, name, cls, induty):
        if ddl_extra:
            c.execute("INSERT INTO dart_company VALUES(?,?,?,?,?,?)", (code, name, "c" + code, "2026-10-29", cls, induty))
        else:
            c.execute("INSERT INTO dart_company VALUES(?,?,?,?)", (code, name, "c" + code, "2026-10-29"))

    def money(code, name, *, close=1500, mcap=300_000, eps=100.0, ni=1_000, eq=10_000, fs="CFS", owner=True, revenue=5_000, op=500):
        c.execute("INSERT INTO price_daily VALUES(?,?,?,?,200,?)", (price_date, code, name, close, mcap))
        rc = "2026031" + code
        items = [(NI, ni), (EQ, eq)] if owner else [(CI.ACC_NI_TOTAL, ni), (CI.ACC_EQ_TOTAL, eq)]
        if eps is not None:
            items.append((EPS, eps))
        for i, (acc, v) in enumerate(items):
            c.execute("INSERT INTO financial_statement_full VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                      (code, "2025", "11011", fs, "IS", i, acc, acc, rc, v, "20260310", "20260310"))
        for nm, v in (("매출액", revenue), ("영업이익", op)):
            if v is not None:
                c.execute("INSERT INTO financial_statement VALUES(?,?,?,?,?,?,?,?,?,?)", (code, "2025", "11011", fs, "IS", 1, nm, rc, "major", v))

    for i in range(1, PLAIN + 1):
        code = f"{i:06d}"
        name = f"가짜{i:02d}"
        company(code, name, "Y" if i % 2 else "K", ("26110", "47111", "64110")[i % 3])
        money(code, name, eps=10.0 * i, ni=100 * i, eq=1_000 * (i + 5), mcap=2_000 * i + 7_000, op=50 + i)
        if i % 4 == 0:
            c.execute("INSERT INTO dividend VALUES(?,?,?,'현금배당',0)", (code, "20260630", 15.0))
    company("900001", "적자회사", "Y", "26299")
    money("900001", "적자회사", eps=-50.0, ni=-500)
    company("900002", "잠식회사", "K", "47111")
    money("900002", "잠식회사", eq=-100)
    company("900003", "자료없음", "K", "64110")                                  # 종가도 재무도 없는 수집 대상
    company("900004", "별도회사", "Y", "26299")
    money("900004", "별도회사", fs="OFS", owner=False)
    company("900005", "분류없음", "", "")
    money("900005", "분류없음", revenue=None, op=None)                            # 영업이익률 항목이 없는 회사
    company("900006", "우선주회사", "Y", "47111")
    money("900006", "우선주회사")
    c.execute("INSERT INTO price_daily VALUES(?,?,?,900,50,45000)", (price_date, "900066", "우선주회사우"))
    c.commit()
    c.close()
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(path))
    return path


@pytest.fixture(autouse=True)
def _fresh_cache():
    T.clear_cache()
    yield
    T.clear_cache()


@pytest.fixture
def world(tmp_path, monkeypatch):
    return _world(tmp_path, monkeypatch)


def _all(**kw):
    """필터 없이 모든 줄을 쪽 100 으로 두 번에 받는다(최대 쪽 크기)."""
    out, page = [], 1
    while True:
        d = T.read_table(size=100, page=page, **kw)
        out += d["rows"]
        if page >= d["pages"]:
            return out
        page += 1


# ── 서버 ────────────────────────────────────────────────────────────────

def test_response_shape(world):
    """TC-IT-01 · 칸 정의(식) · 필터 목록(몇 곳) · 줄마다 기준 한 줄 · 출처 · 한계 · 투자 권유 낱말 없음."""
    d = T.read_table()
    assert d["available"] is True and d["universe"] == TOTAL and d["total"] == TOTAL and d["as_of"] == "2026-10-29"
    assert (d["page"], d["pages"], d["size"], d["start"], d["end"]) == (1, 3, 30, 1, 30) and len(d["rows"]) == 30
    assert [c["key"] for c in d["columns"]] == ["per", "pbr", "roe", "eps", "operating_margin", "dividend_yield"]
    assert all(c["label"] and c["unit"] and c["formula"] and isinstance(c["digits"], int) for c in d["columns"])
    assert d["sort"] == "name" and d["order"] == "asc" and d["sort_keys"][:4] == ["name", "code", "market", "sector"]
    assert d["filters"]["markets"] == [{"code": "KOSPI", "name": "코스피", "n": 33 + 3}, {"code": "KOSDAQ", "name": "코스닥", "n": 32 + 2}]
    secs = {s["code"]: s for s in d["filters"]["sectors"]}
    assert set(secs) == {"26", "47", "64", "none"} and secs["none"]["name"] == "분류 못 찾음" and sum(s["n"] for s in secs.values()) == TOTAL
    assert [s["code"] for s in d["filters"]["sectors"]][-1] == "none"          # 분류 못 찾음은 목록 끝
    r = d["rows"][0]
    assert r["basis"] == "2025 사업보고서(연결) · 공시 접수 2026-03-10 · 종가 2026-10-29" and r["trade_date"] == "2026-10-29"
    assert set(r["metrics"]) == set(T.METRIC_KEYS) and r["status"] == {"code": "ok", "text": "완료", "missing": 0}
    assert d["source"] == CI.SOURCE and "투자 권유가 아닙니다" in d["notice"] and len(d["limits"]) >= 3
    text = json.dumps(d, ensure_ascii=False)
    assert not [w for w in BANNED if w in text]


def test_rows_equal_company_indicators_for_every_company(world):
    """TC-IT-02 · 표의 모든 줄이 `read_indicators`(지표 대시보드) 와 같은 값 · 같은 까닭 · 같은 근사 표시 — 식 글도 같다."""
    rows = {r["code"]: r for r in _all()}
    assert len(rows) == TOTAL
    sample = CI.read_indicators("000001")
    assert {c["key"]: c["formula"] for c in T.COLUMNS} == {m["key"]: m["formula"] for m in sample["metrics"]}
    for code, row in rows.items():
        try:
            ind = CI.read_indicators(code)
        except CI.IndicatorsError as e:
            assert e.status == 404 and row["status"]["code"] == "none" and all(m["value"] is None and m["reason"] == e.message for m in row["metrics"].values())
            continue
        by = {m["key"]: m for m in ind["metrics"]}
        for key in T.METRIC_KEYS:
            mine, theirs = row["metrics"][key], by.get(key)
            if theirs is None:
                assert mine["value"] is None and mine["reason"]
                continue
            assert mine["value"] == theirs["value"], (code, key)
            assert bool(mine.get("approx")) == bool(theirs.get("approx")), (code, key)
            assert mine.get("reason") == theirs.get("reason"), (code, key)
        assert row["name"] == ind["name"] and row["close"] == ind["price"]["close"] and row["trade_date"] == ind["price"]["trade_date"]
        assert row["report"] == {"bsns_year": ind["report"]["bsns_year"], "fs": ind["report"]["fs"], "known_at": ind["report"]["known_at"]}


def test_sort_numeric_missing_last_and_ties(world):
    """TC-IT-03a · 숫자 칸 정렬 — 오름 · 내림 · 값 없는 줄은 어느 쪽이든 맨 뒤 · 같은 값은 코드 오름차순."""
    for order in ("asc", "desc"):
        rows = _all(sort="per", order=order)
        vals = [r["metrics"]["per"]["value"] for r in rows]
        have = [v for v in vals if v is not None]
        assert have == sorted(have, reverse=(order == "desc"))
        assert vals[len(have):] == [None] * (TOTAL - len(have))                   # 값 없는 줄이 끝에 몰려 있다
        assert TOTAL - len(have) == 2                                              # 적자회사 · 자료없음
        # 같은 값(반올림 PER) 끼리는 코드 오름차순
        for a, b in zip(rows, rows[1:]):
            if a["metrics"]["per"]["value"] is not None and a["metrics"]["per"]["value"] == b["metrics"]["per"]["value"]:
                assert a["code"] < b["code"]
    assert any(a["metrics"]["per"]["value"] == b["metrics"]["per"]["value"] for a, b in zip(rows, rows[1:]) if a["metrics"]["per"]["value"] is not None)
    zero = _all(sort="dividend_yield", order="desc")                               # 0.0 은 값이 있는 것(배당 없음) — 없는 값이 아니다
    assert next(r for r in zero if r["code"] == "000001")["metrics"]["dividend_yield"]["value"] == 0.0
    assert zero[0]["metrics"]["dividend_yield"]["value"] > 0


def test_sort_text_columns(world):
    """TC-IT-03b · 이름 · 코드 · 시장 · 업종 정렬 — 시장이 없는 줄은 끝."""
    names = [r["name"] for r in _all(sort="name", order="desc")]
    assert names == sorted(names, key=str.casefold, reverse=True)
    codes = [r["code"] for r in _all(sort="code")]
    assert codes == sorted(codes)
    sector = _all(sort="sector")
    assert [r["sector"]["name"] for r in sector] == sorted(r["sector"]["name"] for r in sector)
    market = _all(sort="market", order="desc")
    assert [r["market"] for r in market[:5]] == ["KOSPI"] * 5 and market[-1]["market"] is None and market[-1]["code"] == "900005"


def test_paging_boundaries(world):
    """TC-IT-04 · 30개씩 세 쪽(30 · 30 · 11) · 끝을 넘으면 마지막 쪽 · 쪽을 넘겨도 줄이 겹치거나 빠지지 않는다 · 크기 바꾸기."""
    seen = []
    for p, (lo, hi, n) in enumerate([(1, 30, 30), (31, 60, 30), (61, 71, 11)], start=1):
        d = T.read_table(sort="pbr", order="desc", page=p)
        assert (d["page"], d["pages"], d["start"], d["end"], len(d["rows"])) == (p, 3, lo, hi, n)
        seen += [r["code"] for r in d["rows"]]
    assert len(seen) == TOTAL and len(set(seen)) == TOTAL                          # 겹침 · 빠짐 없음(동률이 있어도)
    assert seen == [r["code"] for r in _all(sort="pbr", order="desc")]             # 쪽 크기를 바꿔도 같은 순서
    far = T.read_table(page=99)
    assert far["page"] == 3 and far["start"] == 61 and far["end"] == 71
    ten = T.read_table(size=10, page=8)
    assert (ten["pages"], ten["start"], ten["end"], len(ten["rows"])) == (8, 71, 71, 1)
    exact = T.read_table(sector="26", size=10)                                     # 26 업종 23곳 → 세 쪽(10 · 10 · 3)
    assert exact["total"] == sum(1 for r in _all() if r["sector"]["code"] == "26") and exact["pages"] == -(-exact["total"] // 10)


def test_filters(world):
    """TC-IT-05 · 시장 · 업종(분류 못 찾음 포함) · 이름 · 코드 검색 · 겹쳐 쓰기 · 결과 없음 · 목록의 곳 수는 필터와 무관."""
    kospi = _all(market="KOSPI")
    assert len(kospi) == 36 and {r["market"] for r in kospi} == {"KOSPI"}
    assert len(_all(market="kosdaq")) == 34                                        # 대소문자 무시
    s26 = _all(sector="26")
    assert s26 and {r["sector"]["code"] for r in s26} == {"26"} and all(r["sector"]["name"] == "전자 부품 제조업" for r in s26)
    none = _all(sector="none")
    assert [r["code"] for r in none] == ["900005"] and none[0]["market"] is None and none[0]["sector"]["name"] == "분류 못 찾음"
    assert [r["code"] for r in _all(q="우선주")] == ["900006"]
    assert [r["code"] for r in _all(q="000007")] == ["000007"]
    assert {r["code"] for r in _all(q="가짜0")} == {f"{i:06d}" for i in range(1, 10)}
    both = _all(market="KOSPI", sector="47")
    assert both and all(r["market"] == "KOSPI" and r["sector"]["code"] == "47" for r in both)
    d = T.read_table(market="KOSPI", sector="64", q="없는이름")
    assert (d["total"], d["rows"], d["start"], d["end"], d["page"], d["pages"]) == (0, [], 0, 0, 1, 1)
    assert d["universe"] == TOTAL and d["filters"]["markets"][0]["n"] == 36            # 필터를 걸어도 목록은 전체 기준


def test_reasons_status_and_notes(world):
    """TC-IT-06 · 값 없음 = null + 까닭 · 별도재무제표 · 근사 · 상태 셋."""
    rows = {r["code"]: r for r in _all()}
    loss = rows["900001"]
    assert loss["metrics"]["per"] == {"value": None, "reason": "적자라 계산하지 않음"} and loss["status"] == {"code": "partial", "text": "일부 값 없음", "missing": 1}
    assert "PER — 적자라 계산하지 않음" in loss["notes"]
    imp = rows["900002"]
    assert imp["metrics"]["pbr"]["value"] is None and "자본잠식" in imp["metrics"]["roe"]["reason"] and imp["status"]["missing"] == 2
    nodata = rows["900003"]
    assert nodata["status"] == {"code": "none", "text": "자료 없음", "missing": 6} and nodata["close"] is None and nodata["report"] is None
    assert all(m["value"] is None and "자료가 없습니다" in m["reason"] for m in nodata["metrics"].values())
    assert nodata["basis"] == "재무 자료 없음 · 종가 없음" and len(nodata["notes"]) == 6
    sep = rows["900004"]
    assert sep["report"]["fs"] == "OFS" and sep["basis"].startswith("2025 사업보고서(별도)") and T.FS_NOTE in sep["notes"]
    fin = rows["900005"]
    assert fin["metrics"]["operating_margin"]["value"] is None and fin["market"] is None and fin["status"]["code"] == "partial"
    pref = rows["900006"]
    assert pref["metrics"]["pbr"]["approx"] is True and pref["status"]["code"] == "ok" and any(n.startswith("PBR 근사") for n in pref["notes"])
    assert Counter(r["status"]["code"] for r in rows.values()) == {"ok": TOTAL - 4, "partial": 3, "none": 1}


def test_validation_errors(world):
    """TC-IT-07a · 잘못된 입력은 422 와 코드."""
    bad = [({"sort": "close"}, "bad_sort"), ({"order": "up"}, "bad_order"), ({"market": "NASDAQ"}, "bad_market"), ({"sector": "2"}, "bad_sector"),
           ({"sector": "abc"}, "bad_sector"), ({"q": "가" * 41}, "bad_q"), ({"page": 0}, "bad_page"), ({"size": 9}, "bad_size"), ({"size": 101}, "bad_size")]
    for kw, code in bad:
        with pytest.raises(CI.IndicatorsError) as e:
            T.read_table(**kw)
        assert e.value.status == 422 and e.value.code == code, kw
    assert T.read_table(size=10)["size"] == 10 and T.read_table(size=100)["size"] == 100          # 경계는 받는다


def test_no_db_and_odd_shapes(tmp_path, monkeypatch):
    """TC-IT-07b · 수집 DB 없음 503 · 종가 표 없음 503 · 시장 · 업종 칸이 없는 표 모양에서도 죽지 않는다(필터는 빈 목록)."""
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(tmp_path / "없음.sqlite3"))
    with pytest.raises(CI.IndicatorsError) as e1:
        T.read_table()
    assert e1.value.status == 503 and e1.value.code == "no_db"
    empty = tmp_path / "빈DB.sqlite3"
    sqlite3.connect(empty).close()
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(empty))
    with pytest.raises(CI.IndicatorsError) as e2:
        T.read_table()
    assert e2.value.status == 503 and e2.value.code == "no_data"
    sub = tmp_path / "sub"
    sub.mkdir()
    _world(sub, monkeypatch, ddl_extra=False, with_ksic=False)
    T.clear_cache()
    d = T.read_table(size=100)
    assert d["total"] == TOTAL and d["filters"]["markets"] == [] and {r["sector"]["code"] for r in d["rows"]} == {"none"} and all(r["market"] is None for r in d["rows"])
    assert d["rows"][0]["metrics"]["per"]["value"] is not None                    # 지표 자체는 그대로 계산된다


def test_sqlite_failure_becomes_503(world, monkeypatch):
    """TC-IT-07c · 만드는 도중 수집 DB 를 못 읽으면 500 이 아니라 503(다시 시도하라는 글) — 실패한 결과는 저장하지 않는다."""
    def boom(_code):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(CI, "read_indicators", boom)
    with pytest.raises(CI.IndicatorsError) as e:
        T.read_table()
    assert e.value.status == 503 and e.value.code == "read_failed" and T._CACHE["val"] is None


def _client(roles=()):
    app = FastAPI()
    app.include_router(D.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "roles": list(roles)}
    return TestClient(app)


def test_route_query_parameters_and_errors(world):
    """TC-IT-08 · 라우터 — 질의 인자가 서비스까지 가고 · 잘못된 입력은 {code, message} · 서비스 오류의 힌트는 관리자에게만."""
    c = _client()
    r = c.get("/api/data/indicators/table", params={"market": "KOSDAQ", "sort": "pbr", "order": "desc", "page": 2, "size": 10, "q": "가짜"})
    assert r.status_code == 200
    d = r.json()
    assert (d["market"], d["sort"], d["order"], d["page"], d["size"], d["q"]) == ("KOSDAQ", "pbr", "desc", 2, 10, "가짜")
    assert d["start"] == 11 and d["end"] == 20 and all(x["market"] == "KOSDAQ" for x in d["rows"])
    vals = [x["metrics"]["pbr"]["value"] for x in d["rows"]]
    assert vals == sorted(vals, reverse=True)
    default = c.get("/api/data/indicators/table").json()
    assert (default["sort"], default["order"], default["size"], default["page"]) == ("name", "asc", 30, 1)
    bad = c.get("/api/data/indicators/table", params={"sort": "nope"})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "bad_sort"
    assert c.get("/api/data/indicators/table", params={"page": "x"}).status_code == 422             # 숫자 아님 — FastAPI 검증
    # 기존 길이 이 길과 겹치지 않는다
    assert c.get("/api/data/indicators", params={"symbol": "000001"}).status_code == 200
    assert c.get("/api/data/indicators/universe").json()["count"] == TOTAL


def test_route_no_db_hint_admin_only(tmp_path, monkeypatch):
    """TC-IT-08b · 수집 DB 없음 503 — 할 일(명령)은 관리자 응답에만."""
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(tmp_path / "없음.sqlite3"))
    user = _client().get("/api/data/indicators/table")
    admin = _client(("admin",)).get("/api/data/indicators/table")
    assert user.status_code == 503 and "hint" not in user.json()["detail"]
    assert admin.status_code == 503 and "hint" in admin.json()["detail"]


def test_route_requires_login(world):
    """TC-IT-08c · 로그인 없이는 부를 수 없다 — 지표 대시보드 길과 같은 의존."""
    app = FastAPI()
    app.include_router(D.router)
    r = TestClient(app).get("/api/data/indicators/table")
    assert r.status_code in (401, 403)


def test_cache_reuse_clear_and_new_price_date(world, monkeypatch):
    """TC-IT-09 · 두 번째 요청은 종목을 다시 훑지 않는다 · 비우면 다시 · 새 종가 날짜가 들어오면 다시 · 요청이 달라도(정렬 · 필터) 훑지 않는다."""
    calls = []
    real = CI.read_indicators
    monkeypatch.setattr(CI, "read_indicators", lambda code, *a, **k: (calls.append(code), real(code, *a, **k))[1])
    T.read_table()
    assert len(calls) == TOTAL
    T.read_table(sort="roe", order="desc", market="KOSPI", page=2)
    T.read_table(q="가짜")
    assert len(calls) == TOTAL
    T.clear_cache()
    T.read_table()
    assert len(calls) == 2 * TOTAL
    c = sqlite3.connect(world)
    c.execute("INSERT INTO price_daily VALUES('20261030','000001','가짜01',1500,200,300000)")
    c.commit()
    c.close()
    d = T.read_table()
    assert len(calls) == 3 * TOTAL and d["as_of"] == "2026-10-30"


def test_service_source_hygiene():
    """TC-IT-12 · 서비스 파일에 외부 재무 요약 낱말 · 투자 권유 낱말이 없다."""
    src = (ROOT / "app" / "services" / "data_indicator_table.py").read_text(encoding="utf-8")
    assert "yfinance" not in src.lower() and "yahoo" not in src.lower()
    assert not [w for w in BANNED if w in src]


# ── 화면 (node) ─────────────────────────────────────────────────────────

CT = ROOT / "public" / "js" / "company-compare-table.js"
APP = (ROOT / "public" / "app.html").read_text(encoding="utf-8")
ESC = ('const esc = s => String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")'
       '.replace(/"/g,"&quot;").replace(/\'/g,"&#39;");')


def _node(tmp_path: Path, body: str, data: dict | None = None) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node 가 없어 화면 함수를 돌릴 수 없다")
    script = tmp_path / "run.mjs"
    script.write_text(f'import * as ct from "{CT.resolve().as_uri()}";\n{ESC}\n'
                      f"const DATA = {json.dumps(data, ensure_ascii=False)};\nconst out = {{}};\n(async () => {{\n{body}\n"
                      "process.stdout.write(JSON.stringify(out));\n})();\n", encoding="utf-8")
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_state_query_and_sort_toggle(tmp_path):
    """TC-IT-10a · 질의 문자열(빈 필터는 안 보냄) · 열 머리 누르기 — 같은 열이면 오름 ↔ 내림, 다른 열이면 오름차순 + 첫 쪽."""
    out = _node(tmp_path, """
      const d = ct.ctDefaultState();
      out.def = ct.ctQueryString(d);
      out.full = ct.ctQueryString({...d, q: "삼성 전자", market: "KOSPI", sector: "26", sort: "per", order: "desc", page: 3});
      const a = ct.ctNextSort({...d, page: 4}, "name");          // 같은 열: 오름 → 내림
      const b = ct.ctNextSort(a, "name");                        // 다시: 내림 → 오름
      const c = ct.ctNextSort({...d, sort: "per", order: "desc", page: 5}, "pbr");   // 다른 열: 오름 + 첫 쪽
      out.seq = [[a.sort, a.order, a.page], [b.sort, b.order, b.page], [c.sort, c.order, c.page]];
      out.size = ct.CT_PAGE_SIZE;
    """)
    assert out["def"] == "sort=name&order=asc&page=1&size=30"
    assert out["full"] == "q=%EC%82%BC%EC%84%B1+%EC%A0%84%EC%9E%90&market=KOSPI&sector=26&sort=per&order=desc&page=3&size=30"
    assert out["seq"] == [["name", "desc", 1], ["name", "asc", 1], ["pbr", "asc", 1]]
    assert out["size"] == 30


def test_texts_range_value_and_dash(tmp_path):
    """TC-IT-10b · 「1~30 / 351종목」 · 값 글(자릿수 · 쉼표 · 근사) · 없으면 N/A 가 아니라 줄표."""
    out = _node(tmp_path, """
      const col = (digits) => ({key: "x", digits});
      out.range = [ct.ctRangeText({total: 351, universe: 351, start: 1, end: 30}), ct.ctRangeText({total: 12, universe: 351, start: 1, end: 12}),
                   ct.ctRangeText({total: 0, universe: 351, start: 0, end: 0}), ct.ctRangeText(null)];
      out.val = [ct.ctValueText(col(1), {value: 15}), ct.ctValueText(col(1), {value: 1234.56}), ct.ctValueText(col(0), {value: 11303}),
                 ct.ctValueText(col(2), {value: 0}), ct.ctValueText(col(2), {value: 1.8, approx: true}), ct.ctValueText(col(1), {value: null, reason: "적자라 계산하지 않음"}),
                 ct.ctValueText(col(1), undefined), ct.ctValueText(col(1), {value: NaN})];
      out.pick = ct.ctPickText(5, 8);
      out.opts = ct.ctFilterOptions([{code: "26", name: "전자 <부품>", n: 21}], "전체 업종", esc, "26");
    """)
    assert out["range"] == ["1~30 / 351종목", "1~12 / 12종목 (수집 대상 351종목 중)", "0종목", "0종목"]
    assert out["val"] == ["15.0", "1,234.6", "11,303", "0.00", "1.80 (근사)", "—", "—", "—"]
    assert out["pick"] == "비교에 담은 종목 5/8"
    assert out["opts"] == '<option value="">전체 업종</option><option value="26" selected>전자 &lt;부품&gt; (21)</option>'


def test_table_html_from_real_server_response(tmp_path, world):
    """TC-IT-10c · 서버가 준 한 쪽을 그대로 그린다 — 줄 수 · 값 글은 서버 값의 자릿수만 바꾼 것 · 줄표 수 = null 수 · 기준 줄 · 상태 글과 까닭이 보인다 · 이스케이프."""
    data = T.read_table(sort="per", order="desc", page=3)           # 마지막 쪽 11줄 — 값 없는 줄(적자 · 자료 없음)이 끝에 온다
    data["rows"][0]["name"] = '<img src=x onerror="alert(1)">'
    out = _node(tmp_path, """
      const st = {...ct.ctDefaultState(), sort: "per", order: "desc", page: 3};
      const html = ct.ctTableHtml(DATA, st, esc, new Set([DATA.rows[1].code]));
      out.html = html;
      out.rows = (html.match(/data-ct-row=/g) || []).length;
      out.heads = (html.match(/<th scope="col"/g) || []).length;
      out.dash = (html.match(/data-ct-metric="[a-z_]+">—</g) || []).length;
      out.pressed = (html.match(/aria-pressed="true"/g) || []).length;
      out.empty = ct.ctTableHtml({...DATA, rows: []}, st, esc, new Set());
      out.foot = ct.ctFootHtml(DATA, esc);
    """, data)
    html = out["html"]
    assert out["rows"] == 11 and out["heads"] == 12 and out["pressed"] == 1
    nulls = sum(1 for r in data["rows"] for m in r["metrics"].values() if m["value"] is None)
    assert nulls >= 6 and out["dash"] == nulls
    assert "<img" not in html and "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in html            # 이름은 이스케이프
    assert 'aria-sort="descending"' in html and html.count('aria-sort="none"') == 9 and "▼" in html
    assert 'data-ct-sort="per"' in html and 'data-ct-sort="dividend_yield"' in html and 'data-ct-sort="sector"' in html
    assert "N/A" not in html and "undefined" not in html and "null" not in html and "NaN" not in html
    assert "적자라 계산하지 않음" in html and "자료 없음" in html and "재무 자료 없음 · 종가 없음" in html          # 까닭이 글로 보인다(호버가 아니라)
    first_valued = next(r for r in data["rows"] if r["metrics"]["per"]["value"] is not None)
    assert f'data-ct-metric="per">{first_valued["metrics"]["per"]["value"]:.1f}<' in html.replace(",", "")
    assert "조건에 맞는 종목이 없습니다" in out["empty"] and 'colspan="12"' in out["empty"]
    assert "종가 최신일 2026-10-29" in out["foot"] and "PER = 종가 ÷ 보고된 기본주당이익" in out["foot"] and "투자 권유가 아닙니다" in out["foot"]
    assert not [w for w in BANNED if w in html + out["foot"]]


# ctMount 를 돌릴 가짜 칸 모음 — id 로 찾는 칸 · 이벤트 등록 · 요청 기록(응답은 시험이 정한다)
FAKE_JS = """
      const els = {};
      for (const id of ["ct-table","ct-foot","ct-msg","ct-q","ct-market","ct-sector","ct-prev","ct-next","ct-page","ct-range","ct-picked","ct-goto","co-compare-chips"]) {
        els[id] = {id, innerHTML: "", textContent: "", value: "", disabled: false, style: {}, attrs: {}, listeners: {}, options: {length: 1}, scrolled: 0,
          addEventListener(t, f) { (this.listeners[t] ||= []).push(f); }, setAttribute(k, v) { this.attrs[k] = v; }, removeAttribute(k) { delete this.attrs[k]; },
          querySelectorAll() { return []; }, scrollIntoView() { this.scrolled++; } };
      }
      globalThis.document = { getElementById: id => els[id] || null };
      const fire = (id, type, ev = {}) => (els[id].listeners[type] || []).forEach(f => f(ev));
      const tgt = (sel, dataset) => ({ target: { closest: s => (s === sel ? { dataset } : null) } });
      const sleep = ms => new Promise(r => setTimeout(r, ms));
      const calls = [], picks = [];
      const page = (over = {}) => ({ ...DATA, ...over });
      const mk = (fetchPage, extra = {}) => ct.ctMount({ fetchPage, esc, max: 8, isPicked: c => c === "000001", pickedCount: () => 1,
        onPick: (c, n) => { picks.push([c, n]); return extra.note || ""; } });
"""


def test_mount_requests_and_events(tmp_path, world):
    """TC-IT-10d · 연결 — 처음 한 번만 받고 · 열 머리 → 정렬 요청 · 필터 → 첫 쪽 · 다음 쪽 · 검색은 늦춰 한 번 · 담기 → onPick · 나란히 비교로 이동."""
    data = T.read_table()
    out = _node(tmp_path, FAKE_JS + """
      const api = async url => { calls.push(url); return page(); };
      const m = mk(api);
      m.ensureLoaded(); m.ensureLoaded(); await sleep(30);
      out.first = [calls.length, calls[0], els["ct-range"].textContent, els["ct-page"].textContent, els["ct-prev"].disabled, els["ct-next"].disabled,
                   els["ct-picked"].textContent, els["ct-market"].innerHTML.includes("코스피 (36)"), els["ct-sector"].innerHTML.includes("분류 못 찾음 (1)"),
                   els["ct-foot"].innerHTML.includes("출처"), els["ct-msg"].textContent];
      m.ensureLoaded(); await sleep(10); out.again = calls.length;                       // 이미 받았으면 다시 받지 않는다
      fire("ct-table", "click", tgt("[data-ct-sort]", {ctSort: "per"})); await sleep(20);
      fire("ct-table", "click", tgt("[data-ct-sort]", {ctSort: "per"})); await sleep(20);
      els["ct-market"].value = "KOSDAQ"; fire("ct-market", "change"); await sleep(20);
      els["ct-sector"].value = "26"; fire("ct-sector", "change"); await sleep(20);
      fire("ct-next", "click"); await sleep(20);
      els["ct-q"].value = " 가짜0 "; fire("ct-q", "input"); fire("ct-q", "input"); await sleep(ct.CT_DEBOUNCE_MS + 120);
      fire("ct-table", "click", tgt("[data-ct-pick]", {ctPick: "000007", ctName: "가짜07"}));
      fire("ct-goto", "click");
      out.urls = calls.slice(1);
      out.picks = picks; out.scrolled = els["co-compare-chips"].scrolled;
    """, data)
    assert out["first"][:2] == [1, "sort=name&order=asc&page=1&size=30"]
    assert out["first"][2:7] == ["1~30 / 71종목", "1 / 3쪽", True, False, "비교에 담은 종목 1/8"]
    assert out["first"][7:] == [True, True, True, ""] and out["again"] == 1
    assert out["urls"] == [
        "sort=per&order=asc&page=1&size=30",
        "sort=per&order=desc&page=1&size=30",
        "market=KOSDAQ&sort=per&order=desc&page=1&size=30",
        "market=KOSDAQ&sector=26&sort=per&order=desc&page=1&size=30",
        "market=KOSDAQ&sector=26&sort=per&order=desc&page=2&size=30",       # 서버가 page=1 로 답한 상태에서 다음 → 2
        "q=%EA%B0%80%EC%A7%9C0&market=KOSDAQ&sector=26&sort=per&order=desc&page=1&size=30",   # 두 번 쳐도 한 번만 · 첫 쪽
    ]
    assert out["picks"] == [["000007", "가짜07"]] and out["scrolled"] == 1


def test_mount_stale_response_error_and_pick_note(tmp_path, world):
    """TC-IT-10e · 늦게 온 옛 응답은 버린다 · 서버가 쪽을 맞춰 주면 그 쪽을 따른다 · 실패하면 글로 · 담지 못한 까닭은 표 위 글로."""
    data = T.read_table()
    out = _node(tmp_path, FAKE_JS + """
      const waits = [];
      const api = url => { calls.push(url); return new Promise((res, rej) => waits.push({url, res, rej})); };
      const m = mk(api, {note: "최대 8개까지 나란히 볼 수 있습니다."});
      m.ensureLoaded();
      waits[0].res(page({page: 1})); await sleep(10);
      fire("ct-table", "click", tgt("[data-ct-sort]", {ctSort: "pbr"}));           // 느린 요청
      fire("ct-table", "click", tgt("[data-ct-sort]", {ctSort: "roe"}));           // 빠른 요청(나중에 보낸 것)
      waits[2].res(page({sort: "roe", rows: DATA.rows.slice(0, 2)})); await sleep(10);
      waits[1].res(page({sort: "pbr", rows: DATA.rows.slice(2, 3)})); await sleep(10);       // 옛 응답 — 버려진다
      out.rowsAfterStale = (els["ct-table"].innerHTML.match(/data-ct-row=/g) || []).length;
      fire("ct-table", "click", tgt("[data-ct-pick]", {ctPick: "000009", ctName: "가짜09"}));
      out.note = els["ct-msg"].textContent;
      // 서버가 끝을 넘은 쪽을 마지막 쪽(3)으로 맞춘 경우 — 이어서 이전을 누르면 2 쪽을 요청한다
      fire("ct-next", "click");
      waits[3].res(page({page: 3, pages: 3, start: 61, end: 71})); await sleep(10);
      fire("ct-prev", "click");
      out.prevUrl = waits[4].url;
      waits[4].res(page({page: 2})); await sleep(10);
      // 실패
      fire("ct-table", "click", tgt("[data-ct-sort]", {ctSort: "name"}));
      const w = waits[waits.length - 1]; w.rej(new Error("지표 비교 표 자료를 아직 받지 못했습니다.")); await sleep(10);
      out.err = [els["ct-msg"].textContent, els["ct-msg"].style.color];
    """, data)
    assert out["rowsAfterStale"] == 2
    assert out["note"] == "최대 8개까지 나란히 볼 수 있습니다."
    assert out["prevUrl"].endswith("page=2&size=30")
    assert out["err"] == ["지표 비교 표 자료를 아직 받지 못했습니다.", "var(--red)"]


def test_failed_first_load_retries_on_next_open(tmp_path, world):
    """TC-IT-10f · 처음 받기가 실패하면 다음에 화면을 열 때(ensureLoaded) 다시 받는다 — 실패한 채 굳지 않는다."""
    data = T.read_table()
    out = _node(tmp_path, FAKE_JS + """
      let n = 0;
      const api = async url => { calls.push(url); if (++n === 1) throw new Error("실패"); return page(); };
      const m = mk(api);
      m.ensureLoaded(); await sleep(20);
      out.afterFail = [calls.length, els["ct-msg"].textContent, els["ct-table"].innerHTML];
      m.ensureLoaded(); await sleep(20);
      out.afterRetry = [calls.length, (els["ct-table"].innerHTML.match(/data-ct-row=/g) || []).length, els["ct-msg"].textContent];
    """, data)
    assert out["afterFail"] == [1, "실패", ""] and out["afterRetry"] == [2, 30, ""]


def test_markup_wiring_and_hygiene():
    """TC-IT-11 · 지표 비교 view 안의 칸 · 링크 · 기존 칩 비교 유지 · AG Grid 없음 · 판단 낱말 없음 · 좁은 화면 규칙 · 라우트 등록."""
    app = (ROOT / "public" / "app.html").read_text(encoding="utf-8")
    view = re.search(r'data-view="company-compare">(.*?)data-view=', app, flags=re.S).group(1)
    for i in ("ct-q", "ct-market", "ct-sector", "ct-prev", "ct-next", "ct-page", "ct-range", "ct-picked", "ct-goto", "ct-msg", "ct-table", "ct-foot"):
        assert f'id="{i}"' in view, i
    for i in ("co-compare-chips", "co-compare-form", "co-compare-add", "co-compare-msg", "co-compare-table"):       # 기존 칩 비교는 그대로
        assert f'id="{i}"' in view, i
    assert view.index('id="co-compare-chips"') < view.index('id="ct-table"')                                          # 담은 종목 비교가 위
    assert 'href="/css/company-compare-table.css"' in app and app.count('id="ct-table"') == 1
    assert not re.search(r"ag-?grid", view + CT.read_text(encoding="utf-8"), re.I)
    assert not [w for w in BANNED if w in view]
    js = CT.read_text(encoding="utf-8")
    assert 'from "/js/common.js"' not in js and "yahoo" not in js.lower() and "N/A" not in js and not [w for w in BANNED if w in js]
    assert not re.search(r"(?<![A-Za-z])(?:api|fetch)\(", js)           # 요청은 company.js 가 넘겨 주는 fetchPage 로만(요청 주소는 company.js 가 적는다 — 스캐너가 화면에 잇는다)
    company = (ROOT / "public" / "js" / "company.js").read_text(encoding="utf-8")
    assert 'import { ctMount } from "/js/company-compare-table.js"' in company and "mountCompareTable();" in company
    assert "api(`/api/data/indicators/table?${qs}`)" in company
    assert "compareTable.syncPicks()" in company and "cvCompareLoad" in company and "/api/data/indicators/universe" in company
    css = (ROOT / "public" / "css" / "company-compare-table.css").read_text(encoding="utf-8")
    assert re.search(r"\.ct-scroll\s*\{[^}]*overflow-x:\s*auto", css) and "100vw" not in css and "var(--text-mute)" in css
    assert re.search(r"\.ct-table\s+\.ct-name\s*\{[^}]*position:\s*sticky", css)
    assert "@media (max-width: 640px)" in css
    assert '"/indicators/table"' in (ROOT / "app" / "routes" / "data.py").read_text(encoding="utf-8")
