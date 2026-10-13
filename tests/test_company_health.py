"""상장사 재무 건전성 시험 (TC-FH) — `app/services/company_health.py` (API-RISK-01 · ④-2 · 2026-10-13).

여기서 지키는 것 —
1. 비율 — 유동비율 · 부채비율 · 자기자본비율 · 자본잠식률(부분 · 완전) · 넣은 숫자와 기준 기간.
2. Altman Z'' — 계수 6.56 · 3.26 · 6.72 · 1.05 · 경계 1.10 · 2.60(경계 값은 가운데) · 사업보고서로만 · 해마다.
3. 견줄 수 없으면 값 대신 까닭 — 금융회사(유동 · 비유동 구분 없음 + 금융업 계정) · 구분 없는 재무제표 · 자본 0 이하.
4. 숨기지 않는다 — 이자보상배율 · 영업현금흐름은 자료가 없어도 점검 · `unavailable` 에 까닭과 함께(D67).
5. 판 고르기는 `data_financials` 한 곳(SSoT) — 기준일 · strict 를 그대로 넘기고, 연결이 없을 때만 별도로 바꾸며 그 사실을 글로.
6. 문장 — 값이 있는 비율마다 문장 · 「재는 법」 · 반대로 읽을 경우 · 권유 낱말 없음 · 정정된 기간 표시.
7. 라우트 — 로그인 · 상태 번호 그대로 · 수집 · 설정 문제(5xx)의 명령 힌트는 관리자에게만.

수집 DB 를 쓰지 않는다 — 재무는 가짜 `read_financials` 가 주고, 회사 이름 읽기는 없는 경로를 본다(S96 · 아래 autouse).
"""
from __future__ import annotations

import json

import pytest

from app.services import company_health as H
from app.services import data_financials as F

BANNED = ("추천", "최적", "유망", "베스트", "안전한", "매수", "매도", "사세요", "파세요", "유리합니다", "확실", "보장")

GOOD = {"current_assets": 200, "current_liabilities": 100, "noncurrent_liabilities": 50, "assets": 500,
        "liabilities": 150, "capital_stock": 50, "retained_earnings": 250, "equity": 350, "revenue": 800,
        "operating_income": 40}


@pytest.fixture(autouse=True)
def _no_real_collector_db(tmp_path, monkeypatch):
    """회사 이름 읽기(name_of)가 이 PC 의 실제 수집 DB 를 열지 않게 — 없는 경로를 준다(S96 · 앱이 읽기 전용으로 붙인 WAL DB).
    이름이 필요한 시험(TC-FH-15)은 저마다 임시 DB 를 다시 준다."""
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(tmp_path / "수집DB-없음.sqlite3"))


def _p(end, rc="11011", acc=None, restated=False, extra=()):
    acc = dict(GOOD if acc is None else acc)
    accounts = [{"statement": sj, "name": names[0], "amount": acc[k], "cumulative": None, "previous": None}
                for k, sj, names in H.ACCOUNTS if acc.get(k) is not None]
    accounts += [{"statement": "BS", "name": n, "amount": 1, "cumulative": None, "previous": None} for n in extra]
    return {"bsns_year": end[:4], "reprt_code": rc, "report": F.REPORT_NAMES[rc], "period_end": end,
            "rcept_no": "20260101000001", "url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260101000001",
            "known_at": "2026-03-10", "first_known_at": "2026-03-10", "available_from": "2026-03-11",
            "available_from_approx": False, "amended": False, "revision": None, "restated": restated,
            "values_revised_after_as_of": False, "versions": 1, "currency": "KRW", "key": {}, "accounts": accounts}


def _fake(monkeypatch, periods_by_fs, calls=None):
    def read(symbol, as_of, pit, fs, periods):
        if calls is not None:
            calls.append((symbol, as_of, pit, fs, periods))
        ps = periods_by_fs.get(fs)
        if ps is None:
            raise F.FinancialsError(404, "no_financials", f"{symbol} 의 {fs} 재무가 없습니다.", "힌트")
        ps = sorted(ps, key=lambda p: (p["period_end"], p["bsns_year"], p["reprt_code"]), reverse=True)
        return {"symbol": symbol, "corp_code": "00126380", "fs": fs, "pit": pit, "as_of": as_of, "periods": ps}
    monkeypatch.setattr(H.F, "read_financials", read)


def _m(out, key):
    return next(m for m in out["metrics"] if m["key"] == key)


def _texts(out) -> str:
    return json.dumps(out, ensure_ascii=False)


def test_ratios_inputs_and_basis(monkeypatch):
    """TC-FH-01 · 유동비율 200 · 부채비율 42.9 · 자기자본비율 70 · 자본잠식 0 — 넣은 숫자 · 기준 기간(가장 최근 판)."""
    _fake(monkeypatch, {"CFS": [_p("2025-12-31"), _p("2026-06-30", "11012")]})
    out = H.read_health("005930")
    assert out["kind"] == "general" and out["fs"] == "CFS" and out["fs_note"] is None and out["market"] == "KR"
    assert _m(out, "current_ratio")["value"] == 200.0
    assert _m(out, "debt_ratio")["value"] == 42.9
    assert _m(out, "equity_ratio")["value"] == 70.0
    assert _m(out, "impairment")["value"] == 0.0 and "없습니다" in _m(out, "impairment")["sentence"]
    assert out["latest"]["period_end"] == "2026-06-30" and out["latest"]["report"] == "반기보고서"
    assert _m(out, "current_ratio")["inputs"] == {"유동자산": 200, "유동부채": 100}


def test_zscore_formula_zones_and_annual_only(monkeypatch):
    """TC-FH-02 · Z'' = 6.56 X1 + 3.26 X2 + 6.72 X3 + 1.05 X4 · 경계 값 2.60 · 1.10 은 가운데 · 반기는 쓰지 않는다."""
    z, x, why = H.z_score(GOOD)
    assert why == "" and x == {"x1": 0.2, "x2": 0.5, "x3": 0.08, "x4": 350 / 150}
    assert z == pytest.approx(6.56 * 0.2 + 3.26 * 0.5 + 6.72 * 0.08 + 1.05 * 350 / 150)
    assert [H.zone_of(v) for v in (2.6001, 2.60, 1.10, 1.0999)] == ["high", "middle", "middle", "low"]
    half = dict(GOOD, operating_income=-400)        # 반기 숫자로 쓰면 낮은 구간이 될 값
    _fake(monkeypatch, {"CFS": [_p("2025-12-31"), _p("2026-06-30", "11012", half)]})
    out = H.read_health("005930")
    assert out["zscore"]["zone"] == "high" and out["zscore"]["basis"]["report"] == "사업보고서"
    assert [h["bsns_year"] for h in out["zscore"]["history"]] == ["2025"]
    assert "3.25" not in out["zscore"]["formula"]


def test_impairment_partial_full_and_debt_ratio_reason(monkeypatch):
    """TC-FH-03 · 자본총계 < 자본금 → 자본잠식률 · 0 이하 → 완전자본잠식 100 · 부채비율은 값 대신 까닭."""
    part = dict(GOOD, equity=30, capital_stock=50, liabilities=470)
    _fake(monkeypatch, {"CFS": [_p("2025-12-31", acc=part)]})
    out = H.read_health("000001")
    assert _m(out, "impairment")["value"] == 40.0
    assert next(c for c in out["checks"] if c["key"] == "no_impairment")["status"] == "fail"
    full = dict(GOOD, equity=-10, capital_stock=50, liabilities=510)
    _fake(monkeypatch, {"CFS": [_p("2025-12-31", acc=full)]})
    out = H.read_health("000001")
    assert _m(out, "impairment")["value"] == 100.0 and "완전자본잠식" in _m(out, "impairment")["sentence"]
    dr = _m(out, "debt_ratio")
    assert dr["value"] is None and "완전자본잠식" in dr["reason"] and dr["sentence"] == dr["reason"]


def test_financial_company_shows_reasons_not_numbers(monkeypatch):
    """TC-FH-04 · 유동 · 비유동이 없고 예수부채가 있으면 금융회사 — 유동비율 · 부채비율 · Z'' 는 값 대신 까닭 · 점검은 모름."""
    bank = {k: v for k, v in GOOD.items() if k not in ("current_assets", "current_liabilities", "noncurrent_liabilities")}
    _fake(monkeypatch, {"CFS": [_p("2025-12-31", acc=bank, extra=("예수부채",))]})
    out = H.read_health("105560")
    assert out["kind"] == "financial" and "금융회사" in out["kind_note"]
    for key in ("current_ratio", "debt_ratio"):
        assert _m(out, key)["value"] is None and "금융회사" in _m(out, key)["reason"]
    assert out["zscore"]["value"] is None and "금융회사" in out["zscore"]["reason"]
    assert _m(out, "equity_ratio")["value"] == 70.0         # 자기자본비율 · 자본잠식은 그대로 보인다
    st = {c["key"]: c["status"] for c in out["checks"]}
    assert st["short_term"] == st["long_term"] == st["debt_trend"] == "unknown"


def test_no_split_statement_is_not_called_financial(monkeypatch):
    """TC-FH-05 · 구분이 없고 금융업 계정도 없으면 「구분 없는 재무제표」 — 금융회사라 부르지 않는다."""
    odd = {k: v for k, v in GOOD.items() if k not in ("current_assets", "current_liabilities")}
    _fake(monkeypatch, {"CFS": [_p("2025-12-31", acc=odd)]})
    out = H.read_health("000002")
    assert out["kind"] == "no_split"
    assert "구분이 없는" in _m(out, "current_ratio")["reason"] and "금융회사" not in _m(out, "current_ratio")["reason"]
    assert _m(out, "debt_ratio")["value"] == 42.9


def test_operating_loss_streak_and_debt_trend(monkeypatch):
    """TC-FH-06 · 영업손실이 이어진 해 · 가장 최근 해 적자면 점검 실패 · 부채비율 추세는 실제로 견준 해를 글로."""
    years = []
    for y, oi, liab in ((2020, 50, 100), (2021, 30, 120), (2022, -10, 150), (2023, -20, 180), (2024, -5, 200)):
        years.append(_p(f"{y}-12-31", acc=dict(GOOD, operating_income=oi, liabilities=liab)))
    _fake(monkeypatch, {"CFS": years})
    out = H.read_health("000003")
    assert out["operating"]["loss_streak"] == 3
    op = next(c for c in out["checks"] if c["key"] == "operating_profit")
    assert op["status"] == "fail" and "3년 이어 영업손실" in op["reason"]
    tr = next(c for c in out["checks"] if c["key"] == "debt_trend")
    assert tr["status"] == "fail" and tr["reason"].startswith("2020년") and "2024년" in tr["reason"]
    assert [o["bsns_year"] for o in out["operating"]["history"]] == ["2020", "2021", "2022", "2023", "2024"]


def test_unavailable_items_are_listed_not_hidden(monkeypatch):
    """TC-FH-07 · 이자보상배율 · 영업현금흐름은 자료가 없어도 점검(모름) · unavailable 에 까닭과 함께 · 요약 셈."""
    _fake(monkeypatch, {"CFS": [_p("2025-12-31")]})
    out = H.read_health("005930")
    assert [u["key"] for u in out["unavailable"]] == ["interest_coverage", "ocf_to_debt"]
    assert all("없습니다" in u["reason"] for u in out["unavailable"])
    st = {c["key"]: c["status"] for c in out["checks"]}
    assert st["interest_coverage"] == st["ocf_coverage"] == "unknown"
    s = out["summary"]
    assert s["total"] == len(out["checks"]) == 7 and s["pass"] + s["fail"] + s["unknown"] == 7 and s["unknown"] >= 2


def test_cfs_to_ofs_fallback_is_written_and_errors_pass_through(monkeypatch):
    """TC-FH-08 · 연결이 없으면 별도로 · 그 사실을 fs_note 로 · 둘 다 없으면 404 그대로 · 다른 오류(422)는 바꾸지 않는다."""
    _fake(monkeypatch, {"OFS": [_p("2025-12-31")]})
    out = H.read_health("000004")
    assert out["fs"] == "OFS" and "별도" in out["fs_note"]
    _fake(monkeypatch, {})
    with pytest.raises(H.HealthError) as ei:
        H.read_health("000005")
    assert ei.value.status == 404 and ei.value.code == "no_financials"

    def bad(*a, **k):
        raise F.FinancialsError(422, "bad_symbol", "symbol 은 단축코드 6자리입니다")
    monkeypatch.setattr(H.F, "read_financials", bad)
    with pytest.raises(H.HealthError) as ei:
        H.read_health("12")
    assert ei.value.status == 422 and ei.value.code == "bad_symbol"


def test_as_of_and_strict_go_to_the_one_reader(monkeypatch):
    """TC-FH-09 · 기준일 · strict · 기간 상한을 판 고르기 한 곳에 그대로 넘긴다(여기서 판을 다시 고르지 않는다)."""
    calls = []
    _fake(monkeypatch, {"CFS": [_p("2024-12-31")]}, calls)
    H.read_health("005930", as_of="2025-03-01")
    assert calls == [("005930", "2025-03-01", "strict", "CFS", F.MAX_PERIODS)]


def test_sentences_points_and_no_advice_words(monkeypatch):
    """TC-FH-10 · 값이 있는 비율마다 문장 · 「재는 법」 · 반대로 읽을 경우 · 권유 낱말 없음 · 고지 · 출처."""
    _fake(monkeypatch, {"CFS": [_p("2025-12-31"), _p("2024-12-31", acc=dict(GOOD, liabilities=200))]})
    out = H.read_health("005930")
    for m in out["metrics"]:
        if m["value"] is not None:
            assert m["sentence"] and any(p.startswith("재는 법") for p in m["points"])
    assert any("늘 좋지는 않습니다" in p for p in _m(out, "current_ratio")["points"])
    assert any("늘 좋지는 않습니다" in p for p in _m(out, "debt_ratio")["points"])
    assert "앞날을 맞히는 값이 아닙니다" in " ".join(out["zscore"]["points"])
    text = _texts(out)
    assert not [w for w in BANNED if w in text]
    assert "투자 권유가 아닙니다" in out["notice"] and "DART" in out["source"]


def test_restated_period_is_marked(monkeypatch):
    """TC-FH-11 · 정정된 기간이면 문장 줄에 「정정」 · 처음 보고값이 없다는 사실(D66 표시만)."""
    _fake(monkeypatch, {"CFS": [_p("2025-12-31", restated=True)]})
    out = H.read_health("005930")
    assert out["latest"]["restated"] is True
    assert any("정정" in p and "처음 보고된 값은 남아 있지 않습니다" in p for p in _m(out, "current_ratio")["points"])


def test_history_is_ascending_for_charts(monkeypatch):
    """TC-FH-12 · 그림용 이력은 날짜 오름차순 · 분기 · 반기 · 사업보고서를 모두(비율) · Z'' 는 사업보고서만."""
    ps = [_p("2025-03-31", "11013"), _p("2024-12-31"), _p("2025-06-30", "11012"), _p("2025-12-31")]
    _fake(monkeypatch, {"CFS": ps})
    out = H.read_health("005930")
    h = _m(out, "current_ratio")["history"]
    assert [x["period_end"] for x in h] == ["2024-12-31", "2025-03-31", "2025-06-30", "2025-12-31"]
    assert [x["bsns_year"] for x in out["zscore"]["history"]] == ["2024", "2025"]


# ── 라우트 ──────────────────────────────────────────────────────────────────
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.lib.session import get_current_user  # noqa: E402
from app.routes import risk as rr  # noqa: E402


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(rr.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "email": "t@t", "roles": []}
    return TestClient(app)


def test_route_company_ok_errors_and_bounds(client, monkeypatch):
    """TC-FH-13 · 200(점검 · 비율) · 재무 없음 404(코드 그대로) · 단축코드 7자리 422 · fs 4자 422."""
    _fake(monkeypatch, {"CFS": [_p("2025-12-31")]})
    r = client.get("/api/risk/company?symbol=005930")
    assert r.status_code == 200 and r.json()["summary"]["total"] == 7
    _fake(monkeypatch, {})
    r = client.get("/api/risk/company?symbol=000009")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "no_financials"
    assert client.get("/api/risk/company?symbol=0059300").status_code == 422
    assert client.get("/api/risk/company?symbol=005930&fs=CFSX").status_code == 422


def test_route_company_needs_login():
    """TC-FH-14 · 로그인하지 않으면 401."""
    app = FastAPI()
    app.include_router(rr.router)
    assert TestClient(app).get("/api/risk/company?symbol=005930").status_code == 401


def test_name_from_price_table_uses_index(tmp_path, monkeypatch):
    """TC-FH-15 · 이름 · 시장은 시세 표 마지막 줄(색인 ix_price_srtn) · 수집 DB 가 없거나 그 종목이 없으면 빈칸(응답은 그대로)."""
    import sqlite3

    from collector import db as cdb
    p = tmp_path / "m.sqlite3"
    c = cdb.connect(p)
    for d, nm in (("20261007", "옛이름"), ("20261008", "삼성전자")):
        c.execute("INSERT INTO price_daily (bas_dt, srtn_cd, isin_cd, itms_nm, mrkt_ctg, clpr, vs, flt_rt, mkp, hipr, lopr, "
                  "trqu, tr_prc, lstg_st_cnt, mrkt_tot_amt) VALUES (?, '005930', '', ?, 'KOSPI', 1, 0, 0, 1, 1, 1, "
                  "0, 0, 0, 0)", (d, nm))
    plan = " ".join(r[-1] for r in c.execute("EXPLAIN QUERY PLAN " + H.NAME_SQL, ("005930",)))
    c.close()
    assert "USING" in plan and "ix_price_srtn" in plan
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(p))
    assert H.name_of("005930") == ("삼성전자", "KOSPI") and H.name_of("999999") == ("", "")
    _fake(monkeypatch, {"CFS": [_p("2025-12-31")]})
    out = H.read_health("005930")
    assert out["name"] == "삼성전자" and out["exchange"] == "KOSPI"
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(tmp_path / "없음.sqlite3"))
    assert H.read_health("005930")["name"] == ""


def test_check_reasons_use_readable_money(monkeypatch):
    """TC-FH-16 · 점검 까닭의 돈은 조원 · 억원 꼴(날숫자 379,711,982,000,000 을 쓰지 않는다 — 2026-10-13 화면 확인)."""
    assert H.won(379_711_982_000_000) == "379.7조원" and H.won(-43_000_000_000) == "-430억원" and H.won(5_000) == "5,000원"
    big = {k: v * 10 ** 12 for k, v in GOOD.items()}
    _fake(monkeypatch, {"CFS": [_p("2025-12-31", acc=big)]})
    out = H.read_health("005930")
    reasons = " ".join(c["reason"] for c in out["checks"])
    assert "조원" in reasons and not __import__("re").search(r"\d{1,3}(,\d{3}){3,}", reasons)


def test_route_hint_commands_only_for_admin(monkeypatch):
    """TC-FH-17 · 수집 · 설정 문제(5xx)의 힌트(명령)는 관리자에게만 · 다시 묻는 법(4xx 힌트)은 누구에게나."""
    def no_db(*a, **k):
        raise F.FinancialsError(503, "no_db", "수집 DB 가 없습니다.", "python -m collector.financials backfill 을 먼저 돌린다")
    monkeypatch.setattr(H.F, "read_financials", no_db)

    def call(roles):
        app = FastAPI()
        app.include_router(rr.router)
        app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "email": "t@t", "roles": roles}
        return TestClient(app).get("/api/risk/company?symbol=005930")
    user, admin = call([]), call(["admin"])
    assert user.status_code == admin.status_code == 503
    assert "hint" not in user.json()["detail"] and "python" not in user.text
    assert admin.json()["detail"]["hint"].startswith("python -m collector.financials")
    _fake(monkeypatch, {})
    assert "hint" in call([]).json()["detail"]          # 404 의 힌트(다른 fs 로 · 아직 받지 않음)는 누구에게나
