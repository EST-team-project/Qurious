"""TC-PG — 상품 안내의 ETF 목록(app/services/product_etfs.py · app/routes/products.py) · 2026-10-12

무엇을 지키나
- 수집 DB(`etf_daily`)의 마지막 거래일 ETF 를 **하나도 숨기지 않는다** — 묶음 개수를 모두 더하면 그날 전체 수와 같다
  (사용자 2026-10-12 「위험하거나 목록이 길어진다고 보여 주지 않는 것은 옳지 않다」).
- 정렬은 순자산총액 큰 순이 기본이고, 정렬 기준을 응답에 글로 싣는다 — 「추천」 순위가 아니다.
- 지표는 우리 자료로 잰다: 괴리율(종가 ÷ NAV) · 20일 평균 거래대금 · 1년 수익률(거래소 기준가로 이음 — 분배락으로
  낮춘 기준가를 되돌린 근사) · 가격만 본 1년 수익률 · 1년 변동성. 이력이 짧거나 전일 대비 칸이 비면 빈칸(None)이지
  다른 값으로 메우지 않는다(말없는 fallback 금지). 1년 최대 낙폭도 같은 기준가 이음 값으로 잰다.
- 레버리지 · 인버스는 자산군 탭이 아니라 맨 위 칸 하나(`derivatives`)에 모은다 — 자산군 칸 수 + 파생형 칸 수 = 전체.
  묶음은 배수 · 단일종목으로 나누고, 「실제로 사려면」 요건은 상수표 한 곳(`etp_requirements`)에서만 만든다.
- 수집 DB 는 읽기 전용(`mode=ro`)으로만 연다 — 앱이 읽기 전용으로 붙인 파일이다.
- 새 거래일이 들어오면 기준일이 바로 바뀐다(옛 계산을 붙들지 않는다).
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.lib.session import get_current_user
from app.routes import products as pr
from app.services import etp_requirements as etp
from app.services import product_etfs as pe
from collector.db import SCHEMA  # 수집기의 실제 스키마 — 고정물이 실제와 같은 모양이게

LAST = date(2026, 10, 7)


def _weekdays(n: int, end: date) -> list[date]:
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


# (코드, 이름, 기초지수, 순자산, 거래대금, 이력 일수, 종가 시작 → 끝, NAV 비율)
ETFS = [
    ("069500", "KODEX 200", "코스피 200", 25_000_000_000_000, 2_000_000_000_000, 300, 80_000, 108_550, 1.0),
    ("102110", "TIGER 200", "코스피 200", 18_000_000_000_000, 500_000_000_000, 300, 80_000, 108_000, 1.0),
    ("360750", "TIGER 미국S&P500", "S&P 500", 21_000_000_000_000, 600_000_000_000, 300, 20_000, 26_025, 1.0005),
    ("122630", "KODEX 레버리지", "코스피 200", 3_000_000_000_000, 900_000_000_000, 300, 20_000, 35_000, 1.0),
    ("488770", "KODEX 머니마켓액티브", "KAP MMF 지수(TR)", 10_000_000_000_000, 100_000_000_000, 300, 100_000, 103_000, 1.0),
    ("411060", "ACE KRX금현물", "KRX 금현물지수", 3_700_000_000_000, 200_000_000_000, 300, 15_000, 21_000, 1.0),
    ("273130", "KODEX 종합채권(AA-이상)액티브", "KAP 한국종합채권지수", 3_500_000_000_000, 50_000_000_000, 300, 110_000, 112_000, 1.0),
    ("091160", "KODEX 반도체", "KRX 반도체", 1_000_000_000_000, 80_000_000_000, 300, 40_000, 60_000, 1.0),
    ("0099A0", "NEW 새상장반도체", "KRX 반도체", 50_000_000_000, 10_000_000_000, 30, 10_000, 10_500, 1.0),
    ("999990", "가상 ETF", "알 수 없는 지수", 1_000_000_000, 1_000_000, 300, 10_000, 10_000, 1.0),
    ("459580", "KODEX CD금리액티브(합성)", "KAP 양도성예금증서(CD)금리지수(총수익지수)", 7_000_000_000_000, 30_000_000_000,
     300, 1_000_000, 1_000_000, 1.0),
    ("777770", "옛 자료 채권 ETF", "KAP 국고채 지수", 2_000_000_000, 1_000_000, 300, 10_000, 12_000, 1.0),
    ("091170", "KODEX 자동차", "KRX 자동차", 500_000_000_000, 20_000_000_000, 300, 10_000, 11_000, 1.0),
    ("114800", "KODEX 인버스", "코스피 200 선물지수", 1_500_000_000_000, 300_000_000_000, 300, 5_000, 4_000, 1.0),
    ("252670", "KODEX 200선물인버스2X", "코스피 200 선물지수", 2_000_000_000_000, 700_000_000_000, 300, 3_000, 1_800, 1.0),
    ("0080G0", "KODEX 삼성전자단일종목레버리지", "KRX 삼성전자 지수", 900_000_000_000, 400_000_000_000, 90,
     10_000, 14_000, 1.0),
    ("261240", "KODEX 미국달러선물레버리지", "미국달러선물지수", 100_000_000_000, 5_000_000_000, 300, 12_000, 13_000, 1.0),
]
HALTED_CODE = "999990"  # 마지막 날 거래 정지 — 그래도 목록에 남는다
DIST_CODE = "459580"    # 매달 분배락 — 가격은 그대로, 기준가만 2,000원 낮춘다(실측 꼴 · 2026-10-12)
DIST_EVERY = 21         # 21 거래일마다
DIST_AMT = 2_000
NO_VS_CODE = "777770"   # 전일 대비 칸이 빈 옛 자료 — 분배 포함 수익률은 빈칸이어야 한다
MDD_CODE = "091170"     # 1년 창 안에서 12,000 → 9,000 으로 내렸다가 11,000 — 최대 낙폭 −25%
# 파생형 — (묶음, 배수, 단일종목, 요건 키)
DERIV = {
    "122630": ("index_plus2", 2, False, "leveraged_2x"),
    "114800": ("index_minus1", -1, False, "inverse_1x"),
    "252670": ("index_minus2", -2, False, "leveraged_2x"),
    "0080G0": ("single_stock", 2, True, "single_stock"),
    "261240": ("other_assets", 2, False, "leveraged_2x"),   # 통화 선물 2배 — 주식 밖 자산
}


def _close(p0: int, p1: int, i: int, n: int) -> int:
    return round(p0 + (p1 - p0) * i / (n - 1)) if n > 1 else p1


def _price(code: str, p0: int, p1: int, i: int, n: int) -> int:
    if code == MDD_CODE:                       # 0 → 100: 오름 · 100 → 200: 내림 · 200 → 299: 다시 오름
        if i <= 100:
            return round(10_000 + 2_000 * i / 100)
        if i <= 200:
            return round(12_000 - 3_000 * (i - 100) / 100)
        return round(9_000 + 2_000 * (i - 200) / (n - 1 - 200))
    return _close(p0, p1, i, n)


def _make_db(path: Path, last: date = LAST) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    days_all = _weekdays(300, last)
    for code, name, idx, aum, trp, ndays, p0, p1, navr in ETFS:
        days = days_all[-ndays:]
        n = len(days)
        prev = None
        for i, d in enumerate(days):
            close = _price(code, p0, p1, i, n)
            # 전일 대비 = 종가 − 기준가. 기준가는 보통 전일 종가이고, 분배락일에는 분배금만큼 낮다(거래소 규칙)
            base = close if prev is None else prev
            if code == DIST_CODE and i > 0 and i % DIST_EVERY == 0:
                base = prev - DIST_AMT
            vs = None if code == NO_VS_CODE else close - base
            halted = 1 if (code == HALTED_CODE and d == last) else 0
            conn.execute(
                "INSERT INTO etf_daily(bas_dt, srtn_cd, itms_nm, clpr, vs, nav, mkp, hipr, lopr, trqu, tr_prc, "
                "bss_idx_nm, npt_tot_amt, halted) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (d.strftime("%Y%m%d"), code, name, close, vs, close / navr, 0 if halted else close, close, close,
                 1000, trp, idx, aum, halted),
            )
            prev = close
    conn.commit()
    conn.close()


@pytest.fixture
def db(tmp_path, monkeypatch):
    p = tmp_path / "market.sqlite3"
    _make_db(p)
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(p))
    pe.clear_cache()
    yield p
    pe.clear_cache()


def _all_items(ov: dict) -> list[dict]:
    out = [it for c in ov["classes"] for g in c["groups"] for it in g["items"]]
    return out + [it for g in ov["derivatives"]["groups"] for it in g["items"]]


def test_overview_hides_nothing(db):
    ov = pe.overview(per_group=50)
    assert ov["status"] == "ok"
    assert ov["as_of"] == "2026-10-07"
    assert ov["total"] == len(ETFS)
    n_class, n_deriv = sum(c["count"] for c in ov["classes"]), ov["derivatives"]["count"]
    assert n_class + n_deriv == len(ETFS)                                      # 자산군 칸 + 파생형 칸 = 전체
    assert sum(g["count"] for c in ov["classes"] for g in c["groups"]) == n_class
    assert sum(g["count"] for g in ov["derivatives"]["groups"]) == n_deriv
    assert sum(c["derivatives_count"] for c in ov["classes"]) == n_deriv      # 어느 자산군에서 왔는지도 빠짐없이
    assert n_deriv == len(DERIV)
    items = _all_items(ov)
    assert len(items) == len({it["code"] for it in items}) == len(ETFS)        # 한 번씩만 — 두 칸에 겹치지 않는다
    codes = {it["code"] for it in items}
    assert HALTED_CODE in codes            # 거래 정지도 숨기지 않는다
    assert "122630" in codes               # 레버리지도 숨기지 않는다


def test_overview_counts_full_even_when_items_cut(db):
    ov = pe.overview(per_group=1)
    dom = next(c for c in ov["classes"] if c["key"] == "국내주식")
    market = next(g for g in dom["groups"] if g["key"] == "market")
    assert market["count"] == 2 and len(market["items"]) == 1      # 개수는 전체 · 항목은 잘림
    assert market["items"][0]["code"] == "069500"                   # 순자산 큰 순


def test_overview_order_and_labels(db):
    ov = pe.overview(per_group=3)
    assert [c["key"] for c in ov["classes"]] == ["국내주식", "해외주식", "국내채권", "대체자산", "현금", "그 밖"]
    assert ov["sort"]["key"] == "aum" and "순자산" in ov["sort"]["label"]
    assert all(g["key"] != "leveraged_inverse" for c in ov["classes"] for g in c["groups"])   # 파생형은 맨 위 칸으로
    dom = ov["classes"][0]
    assert [g["key"] for g in dom["groups"]] == ["market", "sector_theme", "strategy"]          # 거래소 유형 순서
    dv = ov["derivatives"]
    assert dv["label"] == "레버리지 · 인버스"
    assert [g["key"] for g in dv["groups"]] == ["index_plus2", "index_minus1", "index_minus2", "single_stock",
                                                "other_assets"]
    plus2 = dv["groups"][0]
    assert plus2["items"][0]["code"] == "122630"
    assert "leverage" in plus2["items"][0]["flags"]
    assert ov["flag_notes"]["leverage"]
    unc = next(g for g in ov["classes"][-1]["groups"] if g["key"] == "unclassified")
    assert unc["count"] == 1


def test_derivative_fields(db):
    items = {it["code"]: it for it in pe.list_etfs(limit=200)["items"]}
    for code, (grp, mult, single, req) in DERIV.items():
        it = items[code]
        got = (it["derivative_group"], it["multiple"], it["single_stock"], it["requirement"])
        assert got == (grp, mult, single, req), (code, got)
    k200 = items["069500"]
    assert (k200["derivative_group"], k200["multiple"], k200["single_stock"], k200["requirement"]) == (None, 1, False,
                                                                                                    None)


def test_derivatives_count_by_class(db):
    ov = pe.overview(per_group=50)
    by = {c["key"]: c for c in ov["classes"]}
    assert by["국내주식"]["derivatives_count"] == 4          # 122630 · 114800 · 252670 · 0080G0
    assert by["그 밖"]["derivatives_count"] == 1             # 261240 달러 선물 2배
    assert by["해외주식"]["derivatives_count"] == 0
    assert pe.list_etfs(group="index_minus2")["total"] == 1
    assert pe.list_etfs(group="other_assets")["items"][0]["code"] == "261240"
    # 자산군으로만 거르면 파생형도 함께 나온다(거르기는 기초 자산 기준) — 자산군 칸 + 그 자산군의 파생형
    dom = by["국내주식"]
    assert pe.list_etfs(asset_class="국내주식", limit=200)["total"] == dom["count"] + dom["derivatives_count"]


def test_requirements_come_from_one_table(db):
    ov = pe.overview()
    req = ov["requirements"]
    assert req["as_of"] == etp.AS_OF
    assert set(req["items"]) == {"leveraged_2x", "inverse_1x", "single_stock"}
    lv, inv, ss = (req["items"][k] for k in ("leveraged_2x", "inverse_1x", "single_stock"))
    assert (lv["education_hours"], lv["deposit_krw"], lv["deposit_cash_only"]) == (1, 10_000_000, False)
    assert (ss["education_hours"], ss["deposit_krw"], ss["deposit_cash_only"]) == (2, 30_000_000, True)
    assert inv["education_hours"] is None and inv["deposit_krw"] is None      # 교육 · 예탁금 대상 아님
    for r in req["items"].values():
        assert r["sources"] and all(s["url"].startswith("https://") for s in r["sources"]), r["label"]
        assert r["certainty"] and r["since"]
    groups = {g["key"]: g for g in ov["derivatives"]["groups"]}
    assert groups["index_plus2"]["requirement"] == "leveraged_2x"
    assert groups["index_minus1"]["requirement"] == "inverse_1x"
    assert groups["index_minus2"]["requirement"] == "leveraged_2x"
    assert groups["single_stock"]["requirement"] == "single_stock"
    assert groups["other_assets"]["requirement"] is None                       # 종목마다 다름 — 줄의 칸을 본다


def test_derivative_notes_follow_the_table(db, monkeypatch):
    before = " ".join(pe.overview()["derivatives"]["notes"])
    assert "3,000만 원" in before and "1,000만 원" in before and etp.AS_OF in before
    monkeypatch.setitem(etp.REQUIREMENTS["single_stock"], "deposit_krw", 50_000_000)
    after = " ".join(pe.overview()["derivatives"]["notes"])
    assert "5,000만 원" in after and "3,000만 원" not in after                 # 숫자는 표 한 곳에서만 온다


def test_mdd_1y(db):
    items = {it["code"]: it for it in pe.list_etfs(limit=200)["items"]}
    assert items[MDD_CODE]["mdd_1y_pct"] == pytest.approx(-25.0, abs=1e-6)
    assert items["069500"]["mdd_1y_pct"] == pytest.approx(0.0, abs=1e-12)     # 오르기만 했다
    assert items[DIST_CODE]["mdd_1y_pct"] == pytest.approx(0.0, abs=1e-12)    # 기준가 이음은 분배만큼 오르기만 했다
    assert items["0099A0"]["mdd_1y_pct"] is None                              # 1년 이력이 없으면 빈칸
    assert items[NO_VS_CODE]["mdd_1y_pct"] is None                            # 기준가로 못 이으면 빈칸(가격으로 메우지 않음)
    assert all(x["mdd_1y_pct"] is None or x["mdd_1y_pct"] <= 0 for x in items.values())


def test_risk_numbers_say_not_official_grade(db):
    notes = " ".join(pe.overview()["notes"])
    assert "최대 낙폭" in notes and "공식 투자위험등급이 아닙니다" in notes


def test_metrics(db):
    items = {it["code"]: it for it in pe.list_etfs(limit=200)["items"]}
    k200 = items["069500"]
    assert k200["close"] == 108_550
    assert k200["history_from"] is None                                # 창(400일)보다 오래전부터 있었다
    assert k200["premium_pct"] == pytest.approx(0.0, abs=1e-9)
    assert k200["trade_value_20d"] == 2_000_000_000_000
    assert k200["return_1y_pct"] is not None and k200["return_1y_pct"] > 0
    assert k200["vol_1y_pct"] is not None and k200["vol_1y_pct"] > 0
    spx = items["360750"]
    assert spx["premium_pct"] == pytest.approx(0.05, abs=1e-3)       # 종가 ÷ NAV − 1
    new = items["0099A0"]
    assert new["return_1y_pct"] is None                                # 1년 이력이 없으면 빈칸
    assert new["history_from"] == _weekdays(30, LAST)[0].isoformat()
    assert items[HALTED_CODE]["halted"] is True


def _start_index() -> int:
    days = _weekdays(300, LAST)
    return days.index(next(d for d in days if d >= LAST - timedelta(days=365)))


def test_return_uses_price_a_year_ago(db):
    it = next(x for x in pe.list_etfs(limit=200)["items"] if x["code"] == "069500")
    p_start = _close(80_000, 108_550, _start_index(), 300)
    assert it["price_return_1y_pct"] == pytest.approx((108_550 / p_start - 1) * 100, rel=1e-6)
    # 분배가 없으면 기준가로 이어도 가격 수익률과 같다
    assert it["return_1y_pct"] == pytest.approx(it["price_return_1y_pct"], rel=1e-9)
    assert it["return_basis"] == "base_price_chain"


def test_distribution_is_added_back(db):
    it = next(x for x in pe.list_etfs(limit=200)["items"] if x["code"] == DIST_CODE)
    i0 = _start_index()
    k = sum(1 for i in range(i0 + 1, 300) if i % DIST_EVERY == 0)        # 1년 창 안의 분배락 수
    assert k >= 11
    assert it["price_return_1y_pct"] == pytest.approx(0.0, abs=1e-9)     # 가격은 그대로
    expected = ((1_000_000 / (1_000_000 - DIST_AMT)) ** k - 1) * 100
    assert it["return_1y_pct"] == pytest.approx(expected, rel=1e-9)       # 기준가를 되돌리면 분배만큼 오른다
    assert it["return_1y_pct"] > 2.0


def test_missing_vs_is_blank_not_price(db):
    it = next(x for x in pe.list_etfs(limit=200)["items"] if x["code"] == NO_VS_CODE)
    assert it["price_return_1y_pct"] is not None and it["price_return_1y_pct"] > 0
    assert it["return_1y_pct"] is None              # 가격 수익률로 메우지 않는다
    assert it["vol_1y_pct"] is None


def test_list_filter_sort_page(db):
    r = pe.list_etfs(asset_class="국내주식", group="market", sort="trade_value", limit=1, offset=1)
    assert r["total"] == 2 and len(r["items"]) == 1
    assert r["items"][0]["code"] == "102110"                           # 거래대금 2위
    q = pe.list_etfs(q="반도체", limit=50)
    assert {x["code"] for x in q["items"]} == {"091160", "0099A0"}
    with pytest.raises(ValueError):
        pe.list_etfs(sort="best")
    with pytest.raises(ValueError):
        pe.list_etfs(asset_class="코인")


def test_blank_values_sort_last_both_ways(db):
    # 1년 수익률이 없는 것(새 상장 · 전일 대비 빈 자료)은 오름 · 내림 어느 쪽이든 늘 뒤에 — 숨기지도 앞세우지도 않는다
    for order in ("desc", "asc"):
        items = pe.list_etfs(sort="return_1y", order=order, limit=200)["items"]
        blanks = [i for i, x in enumerate(items) if x["return_1y_pct"] is None]
        assert blanks and blanks == list(range(len(items) - len(blanks), len(items))), (order, blanks)
        vals = [x["return_1y_pct"] for x in items if x["return_1y_pct"] is not None]
        assert vals == sorted(vals, reverse=(order == "desc"))


def test_no_banned_words_in_our_text(db):
    ov = pe.overview(per_group=3)
    ours = [ov["sort"]["label"], *ov["notes"], *ov["flag_notes"].values(), ov["source"]["name"]]
    ours += [c["label"] for c in ov["classes"]] + [g["label"] for c in ov["classes"] for g in c["groups"]]
    ours += [ov["derivatives"]["label"], *ov["derivatives"]["notes"], *[g["label"] for g in ov["derivatives"]["groups"]]]
    for r in ov["requirements"]["items"].values():
        ours += [r["label"], r["applies_to"], r["education_note"], r["deposit_note"], *r["other"]]
    for text in ours:
        for w in ("추천", "최적", "유망", "베스트"):
            assert w not in text, (w, text)


def test_opens_read_only(db, monkeypatch):
    seen = []
    real = sqlite3.connect

    def spy(target, *a, **k):
        seen.append(str(target))
        return real(target, *a, **k)

    monkeypatch.setattr(pe.sqlite3, "connect", spy)
    pe.overview()
    assert seen and all("mode=ro" in s for s in seen)


def test_new_trading_day_changes_as_of(db):
    assert pe.overview()["as_of"] == "2026-10-07"
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO etf_daily(bas_dt, srtn_cd, itms_nm, clpr, nav, mkp, tr_prc, bss_idx_nm, npt_tot_amt) "
                 "VALUES ('20261008','069500','KODEX 200',109000,109000,109000,1,'코스피 200',1)")
    conn.commit()
    conn.close()
    assert pe.overview()["as_of"] == "2026-10-08"


def test_no_db_is_explicit(tmp_path, monkeypatch):
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(tmp_path / "없음.sqlite3"))
    pe.clear_cache()
    ov = pe.overview()
    assert ov["status"] == "no_data" and ov["classes"] == [] and ov["total"] == 0


# ── 라우트 ──────────────────────────────────────────────────────────────

@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(pr.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "email": "t@t", "roles": []}
    return TestClient(app)


def test_route_overview_and_list(client):
    r = client.get("/api/products/etfs/overview?per_group=2")
    assert r.status_code == 200 and r.json()["total"] == len(ETFS)
    r = client.get("/api/products/etfs?asset_class=국내주식&group=market&sort=aum&limit=5")
    assert r.status_code == 200 and r.json()["total"] == 2
    r = client.get("/api/products/etfs?group=single_stock")
    assert r.status_code == 200 and [x["code"] for x in r.json()["items"]] == ["0080G0"]


def test_route_rejects_bad_params(client):
    assert client.get("/api/products/etfs?sort=best").status_code == 422
    assert client.get("/api/products/etfs?asset_class=코인").status_code == 422
    assert client.get("/api/products/etfs?group=best").status_code == 422
    assert client.get("/api/products/etfs?limit=1000").status_code == 422
    assert client.get("/api/products/etfs/overview?per_group=99").status_code == 422


def test_route_needs_login(db):
    app = FastAPI()
    app.include_router(pr.router)
    c = TestClient(app)
    for url in ("/api/products/etfs/overview", "/api/products/etfs", "/api/products/savings?kind=deposit"):
        assert c.get(url).status_code == 401, url
