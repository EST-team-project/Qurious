"""TC-HUB — 종목 허브 자료 묶음 · 질문 속 종목 찾기 (app/services/stock_hub.py · /api/stock-hub · 2026-10-17 결정 D95).

지키는 것
  - 칸마다 상태(ok · empty · error · pending) · 기준일 · 출처 · 그 화면 — 칸 하나가 실패해도 묶음은 돌려준다(말없이 비우지 않음)
  - 판단을 섞지 않는다 — 묶음 맨 위에 칸을 합친 결론 칸이 없다
  - 일반 사용자 답에는 예외 글 · 할 일(hint)이 없다(관리자만)
  - 새 계산 없음 — 칸마다 이미 있는 함수를 모듈 이름으로 부른다(갈아 끼우면 따라온다)
  - 질문 속 종목은 이름이 그대로 든 것만 · 짧은 이름은 낱말 경계 · 흔한 낱말 제외 · 겹치면 긴 이름
  - 신호 기록 순위(`signal_rank`)는 허브 `signal` 칸과 같은 값 · 줄마다 기준일 · 낯선 근거 문장 한 줄이 나머지를 막지 않는다(TC-HUB-21 ~ 24)
  - 이 PC 의 실제 수집 DB 를 열지 않는다(autouse 고정물 — S96 · S119)
"""
from __future__ import annotations

import asyncio
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services import company_health, data_ohlcv, data_search, market_calendar, mtf_signals, signal_explain
from app.services import stock_hub as H

TODAY = date(2026, 10, 17)


@pytest.fixture(autouse=True)
def _no_real_collector_db(tmp_path, monkeypatch):
    """이 PC 의 수집 DB(앱이 읽기 전용으로 붙인 WAL DB)를 열지 않게 없는 경로를 준다 · 저장본도 비운다."""
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(tmp_path / "수집DB-없음.sqlite3"))
    monkeypatch.setattr(H, "_NAMES", {"at": 0.0, "names": {}})
    monkeypatch.setattr(H, "_UNIVERSE", {"at": 0.0, "codes": frozenset()})


def _fake_db(tmp_path, monkeypatch, stocks=(), etfs=()):
    """수집기 스키마 그대로의 임시 수집 DB — 주식 (날, 코드, 이름, 시장) · ETF (날, 코드, 이름)."""
    from collector import db as cdb
    p = tmp_path / "m.sqlite3"
    c = cdb.connect(p)
    for d, code, nm, mk in stocks:
        c.execute("INSERT INTO price_daily (bas_dt, srtn_cd, isin_cd, itms_nm, mrkt_ctg, clpr, vs, flt_rt, mkp, hipr, lopr, "
                  "trqu, tr_prc, lstg_st_cnt, mrkt_tot_amt) VALUES (?, ?, '', ?, ?, 1, 0, 0, 1, 1, 1, 0, 0, 0, 0)",
                  (d, code, nm, mk))
    for d, code, nm in etfs:
        c.execute("INSERT INTO etf_daily (bas_dt, srtn_cd, isin_cd, itms_nm, clpr) VALUES (?, ?, '', ?, 1)", (d, code, nm))
    c.commit()
    c.close()
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(p))
    return p


# ── 요청 읽기 ──────────────────────────────────────────────────────────────────────────

def test_normalize_symbol():
    """TC-HUB-01 · 6자리 · .KS/.KQ 꼬리 · 소문자 영문 섞인 ETF 코드를 받고, 그 밖은 422."""
    assert H.normalize("005930") == "005930" and H.normalize(" 005930.ks ") == "005930"
    assert H.normalize("035720.KQ") == "035720" and H.normalize("0000d0") == "0000D0"
    for bad in ("12345", "삼성전자", "", "0059300"):
        with pytest.raises(H.HubError) as e:
            H.normalize(bad)
        assert e.value.status == 422 and e.value.code == "bad_symbol"


def test_wanted_sections():
    """TC-HUB-02 · 칸 고르기 — 비우면 전부 · 종목 칸은 늘 · 차례는 정한 차례 · 모르는 칸은 422."""
    assert H.wanted(None) == H.SECTIONS and H.wanted("") == H.SECTIONS
    assert H.wanted("signal, price") == ("identity", "price", "signal")
    with pytest.raises(H.HubError) as e:
        H.wanted("price,verdict")
    assert e.value.status == 422 and "verdict" in e.value.message


# ── 칸 ──────────────────────────────────────────────────────────────────────────────────

def test_identity_reads_stock_then_etf_then_empty(tmp_path, monkeypatch):
    """TC-HUB-03 · 이름은 주식 시세 마지막 줄 → 없으면 ETF 시세 → 둘 다 없으면 empty · 수집 DB 가 없으면 error(빈칸으로 숨기지 않음)."""
    _fake_db(tmp_path, monkeypatch, stocks=[("20261015", "055550", "신한지주", "KOSPI")],
             etfs=[("20261014", "069500", "옛이름"), ("20261015", "069500", "KODEX 200")])
    monkeypatch.setattr(mtf_signals, "universe", lambda **kw: ["055550"])
    s = H.identity("055550")
    assert s["status"] == H.OK and s["data"] == {"name": "신한지주", "market": "KOSPI", "kind": "stock", "signal_universe": True}
    e = H.identity("069500")
    assert e["status"] == H.OK and e["data"]["name"] == "KODEX 200" and e["data"]["kind"] == "etf"
    assert e["data"]["signal_universe"] is False
    assert H.identity("999999")["status"] == H.EMPTY
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(tmp_path / "없음.sqlite3"))
    gone = H.identity("055550")
    assert gone["status"] == H.ERROR and gone["data"]["signal_universe"] is None


def test_identity_universe_unknown_is_none(tmp_path, monkeypatch):
    """TC-HUB-04 · 신호 기록 대상인지 못 읽으면 None(「아님」 으로 읽지 않는다) — 신호 칸 까닭이 달라진다."""
    _fake_db(tmp_path, monkeypatch, stocks=[("20261015", "055550", "신한지주", "KOSPI")])

    def boom(**kw):
        raise OSError("db")
    monkeypatch.setattr(mtf_signals, "universe", boom)
    assert H.identity("055550")["data"]["signal_universe"] is None


def test_name_queries_use_indexes(tmp_path, monkeypatch):
    """TC-HUB-05 · 이름 질의 둘은 색인을 탄다(질의 계획 · 수집 DB 주식 288만 줄 · ETF 119만 줄)."""
    import sqlite3
    p = _fake_db(tmp_path, monkeypatch, stocks=[("20261015", "055550", "신한지주", "KOSPI")])
    c = sqlite3.connect(p)
    try:
        etf_plan = " ".join(r[-1] for r in c.execute("EXPLAIN QUERY PLAN " + H.ETF_NAME_SQL, ("069500",)))
        names_plan = " ".join(r[-1] for r in c.execute("EXPLAIN QUERY PLAN " + H.NAMES_SQL))
    finally:
        c.close()
    assert "USING" in etf_plan and "ix_etf_srtn" in etf_plan
    assert "SCAN price_daily" not in names_plan.replace("SCAN price_daily USING", "") and "USING" in names_plan


def test_price_section(monkeypatch):
    """TC-HUB-06 · 마지막 종가 · 앞 거래일 대비(수정주가 · 마지막 두 봉 — 기간 첫 봉과 견주지 않음 · DF-123 꼴) · 기준일 = 마지막 봉 ·
    실시간이 아니라고 말함 · 줄 없으면 empty."""
    calls = []

    def fake(symbol, timeframe, start, end, basis, limit, *, today=None, path=None):
        calls.append((symbol, timeframe, start, today))
        return {"rows": [{"trade_date": "2026-10-14", "close": 40_000}, {"trade_date": "2026-10-15", "close": 50_000},
                         {"trade_date": "2026-10-16", "close": 49_000}],
                "basis": "adj_base", "market": "KOSPI"}
    monkeypatch.setattr(data_ohlcv, "read_ohlcv", fake)
    s = H.price("055550", TODAY)
    assert s["status"] == H.OK and s["as_of"] == "2026-10-16" and s["view"] == "trading-chart"
    assert s["data"]["close"] == 49_000 and s["data"]["prev_close"] == 50_000 and s["data"]["change_pct"] == -2.0
    assert "실시간" in s["note"] and calls == [("055550", "1d", "2026-09-27", TODAY)]
    monkeypatch.setattr(data_ohlcv, "read_ohlcv", lambda *a, **k: {"rows": [{"trade_date": "2026-10-16", "close": 1}]})
    assert H.price("055550", TODAY)["data"]["change_pct"] is None
    monkeypatch.setattr(data_ohlcv, "read_ohlcv", lambda *a, **k: {"rows": []})
    assert H.price("055550", TODAY)["status"] == H.EMPTY


def test_signal_section(monkeypatch):
    """TC-HUB-07 · 다중 주기 신호 — 기록이 있으면 설명 서비스의 글 그대로(문장 · 신뢰도 풀이 · 고지) · 없으면 까닭이 대상 여부에 따라."""
    snap = {"symbol": "055550"}
    seen = []

    async def load(db, symbol, on=None):
        seen.append(symbol)
        return snap if symbol == "055550" else None

    def explain(s):
        assert s is snap
        return {"as_of": "2026-10-16", "signal": "매도", "strength": "보통", "confidence": 0.62, "definition": "d1",
                "summary": "일 기준으로 …", "confidence_text": "주기 셋 가운데 둘이 …", "disclaimer": "투자 권유가 아닙니다.",
                "reasons": [{"timeframe": "1d", "label": "일봉", "text": "RSI 가 …", "points": -2, "extra": 1}] * 4,
                "counter_reasons": [{"timeframe": "1w", "label": "주봉", "text": "MACD …", "points": 1}]}
    monkeypatch.setattr(signal_explain, "load_snapshot", load)
    monkeypatch.setattr(signal_explain, "explain", explain)
    s = asyncio.run(H.signal(object(), "055550", True))
    assert s["status"] == H.OK and s["as_of"] == "2026-10-16" and s["notice"] == "투자 권유가 아닙니다."
    assert s["data"]["summary"] == "일 기준으로 …" and len(s["data"]["reasons"]) == 3
    assert set(s["data"]["reasons"][0]) == {"timeframe", "label", "text", "points"}
    none_out = asyncio.run(H.signal(object(), "000660", False))
    assert none_out["status"] == H.EMPTY and none_out["reason"] == H.SIGNAL_NOT_UNIVERSE
    assert asyncio.run(H.signal(object(), "000660", None))["reason"] == H.SIGNAL_NONE
    assert asyncio.run(H.signal(object(), "000660", True))["reason"] == H.SIGNAL_NONE


def test_financials_section(monkeypatch):
    """TC-HUB-08 · 재무 건전성 — read_health 를 그대로 줄여 담음(연결 → 별도 글 · 점검 요약 · 출처 · 고지) · 404 는 empty + 그 글."""
    health = {"kind": "general", "kind_note": "", "fs": "OFS", "fs_note": "연결 재무제표가 없는 회사라 별도 재무제표로 봤습니다",
              "latest": {"period_end": "2025-12-31", "report": "사업보고서", "available_from": "2026-03-18"},
              "summary": {"pass": 4, "fail": 1, "unknown": 2, "total": 7},
              "metrics": [{"key": "debt_ratio", "label": "부채비율", "value": 120.0, "unit": "%", "sentence": "…",
                           "formula": "f", "inputs": {}, "points": []}],
              "zscore": {"value": 3.1, "zone_label": "안전 구간", "x": {}, "reason": ""},
              "operating": {"loss_streak": 0}, "source": "전자공시(DART)", "notice": "투자 권유가 아닙니다."}
    monkeypatch.setattr(company_health, "read_health", lambda symbol: health)
    s = H.financials("055550")
    assert s["status"] == H.OK and s["as_of"] == "2026-03-18" and s["view"] == "agent-cb"
    assert s["data"]["fs_note"].startswith("연결") and s["data"]["summary"]["fail"] == 1
    assert set(s["data"]["metrics"][0]) == {"key", "label", "value", "unit", "sentence"}
    assert s["source"] == "전자공시(DART)" and s["notice"] == "투자 권유가 아닙니다."

    def no_fin(symbol):
        raise company_health.HealthError(404, "no_financials", "069500 의 CFS 재무가 없습니다.", "ETF 는 재무가 없다")
    monkeypatch.setattr(company_health, "read_health", no_fin)
    out = H._guard("financials", lambda: H.financials("069500"), False)
    assert out["status"] == H.EMPTY and "재무가 없습니다" in out["reason"] and "hint" not in out


def test_search_sections(monkeypatch):
    """TC-HUB-09 · 공시는 dart 만 · 기사는 kind=news · 제목 · 주소 · 출처 표시만(본문 없음) · 없으면 empty."""
    asked = []

    def fake(q, kind, symbol, topic, term, dtype, from_, to, sort, limit, offset, source, facets):
        asked.append((kind, symbol, sort, limit, source, facets))
        return {"items": [{"title": "주요사항보고서", "published": "2026-10-15T00:00:00", "url": "https://dart/x",
                           "source": source or "gdelt", "summary": "본문 요약 …",
                           "extra": {"attribution": "출처: 정책브리핑"}, "tags": {"topic": ["배당"]}}],
                "total": 12, "index_built_at": "2026-10-16T13:05"}
    monkeypatch.setattr(data_search, "search", fake)
    d = H.disclosures("055550")
    n = H.news("055550")
    assert asked == [(None, "055550", "date", H.DISCLOSURE_LIMIT, "dart", False),
                     ("news", "055550", "date", H.NEWS_LIMIT, None, False)]
    assert d["status"] == H.OK and d["as_of"] == "2026-10-15" and d["data"]["total"] == 12
    assert set(d["data"]["items"][0]) == {"title", "published", "url", "source", "source_label", "attribution", "topics"}
    assert "summary" not in n["data"]["items"][0] and n["data"]["items"][0]["attribution"] == "출처: 정책브리핑"
    monkeypatch.setattr(data_search, "search", lambda *a: {"items": [], "total": 0})
    assert H.disclosures("055550")["status"] == H.EMPTY and H.news("055550")["status"] == H.EMPTY


def test_schedule_and_sector(tmp_path, monkeypatch):
    """TC-HUB-10 · 일정은 진짜 달력 함수로(수집기 스키마 임시 DB) — 오늘부터 60일 · 그 종목만 · 시장 전체 일정 · 지난 일정 · 60일 뒤는 빠짐 ·
    칸 이름은 달력 응답 그대로 · 섹터는 「준비 중」(pending — 분류 기준 결정 전에는 지어내지 않는다).
    (첫 판은 손으로 만든 대역이 달력 응답과 다른 칸 이름을 써서 우연히 통과했다 — 2026-10-17 실제 앱 확인에서 찾음)"""
    p = _fake_db(tmp_path, monkeypatch)
    import sqlite3
    c = sqlite3.connect(p)
    c.execute("INSERT INTO market_calendar (cal_date, is_trading_day, basis, updated_at) VALUES ('2026-10-16', 1, 'observed', 'x')")
    rows = [("e1", "earnings", "2026-11-12", "055550", "신한지주 실적 발표", "scheduled"),
            ("e2", "dividend_record", "2026-12-31", "055550", "신한지주 배당 기준일", "computed"),   # 60일 뒤 — 빠짐
            ("e3", "market_closure", "2026-12-31", "", "연말 휴장일", "computed"),                  # 시장 전체 — 빠짐
            ("e4", "earnings", "2026-10-02", "055550", "지난 실적", "confirmed"),                    # 지난 일정 — 빠짐
            ("e5", "earnings", "2026-11-13", "005930", "다른 종목", "scheduled")]
    for eid, kind, d, sym, title, conf in rows:
        c.execute("INSERT INTO market_event (event_id, kind, event_date, symbol, title, confidence, source, updated_at) "
                  "VALUES (?, ?, ?, ?, ?, ?, 'dart', 'x')", (eid, kind, d, sym, title, conf))
    c.commit()
    c.close()
    s = H.schedule("055550", TODAY)
    assert s["status"] == H.OK and [e["title"] for e in s["data"]["events"]] == ["신한지주 실적 발표"]
    assert s["data"]["events"][0] == {"date": "2026-11-12", "weekday": "목", "time": "", "kind": "earnings",
                                      "kind_label": market_calendar.EVENT_KINDS["earnings"], "title": "신한지주 실적 발표",
                                      "confidence": "scheduled", "confidence_label": market_calendar.CONFIDENCE["scheduled"]}
    assert H.schedule("000660", TODAY)["status"] == H.EMPTY
    sec = H.sector()
    assert sec["status"] == H.PENDING and sec["data"] is None and sec["reason"] == H.SECTOR_PENDING


# ── 묶음 ────────────────────────────────────────────────────────────────────────────────

def _stub_sections(monkeypatch, *, financials_error=None, signal_error=None):
    monkeypatch.setattr(H, "identity", lambda sym: H.section("identity", H.OK, data={
        "name": "신한지주", "market": "KOSPI", "kind": "stock", "signal_universe": True}))
    monkeypatch.setattr(H, "price", lambda sym, today: H.section("price", H.OK, as_of="2026-10-16"))

    async def sig(db, sym, uni):
        if signal_error:
            raise signal_error
        return H.section("signal", H.OK, as_of="2026-10-16")
    monkeypatch.setattr(H, "signal", sig)

    def fin(sym):
        if financials_error:
            raise financials_error
        return H.section("financials", H.OK)
    monkeypatch.setattr(H, "financials", fin)
    for name in ("disclosures", "news"):
        monkeypatch.setattr(H, name, (lambda n: lambda sym: H.section(n, H.EMPTY, reason="없음"))(name))
    monkeypatch.setattr(H, "schedule", lambda sym, today: H.section("schedule", H.OK))


def test_bundle_shape_and_isolation(monkeypatch):
    """TC-HUB-11 · 묶음 — 칸 차례 · 칸 하나가 터져도 나머지는 돌려줌 · 일반 사용자에겐 예외 글 없음 · 맨 위에 결론 칸 없음."""
    _stub_sections(monkeypatch, financials_error=RuntimeError("no such table: financial_statement"),
                   signal_error=ConnectionRefusedError("앱 DB 127.0.0.1:15432"))
    out = asyncio.run(H.bundle(object(), "055550.KS", today=TODAY))
    assert set(out) == {"version", "symbol", "name", "market", "generated_at", "order", "sections", "links", "notice", "note"}
    assert out["version"] == H.VERSION and out["symbol"] == "055550" and out["name"] == "신한지주"
    assert out["order"] == list(H.SECTIONS) and list(out["sections"]) == list(H.SECTIONS)
    assert out["sections"]["financials"]["status"] == H.ERROR and out["sections"]["signal"]["status"] == H.ERROR
    assert out["sections"]["price"]["status"] == H.OK and out["sections"]["sector"]["status"] == H.PENDING
    flat = str(out)
    assert "financial_statement" not in flat and "15432" not in flat and "hint" not in flat
    assert all(s["reason"] == H.GENERIC_ERROR for k, s in out["sections"].items() if s["status"] == H.ERROR)
    assert [x["view"] for x in out["links"]] == [v for v, _ in H.LINKS] and "투자 권유" in out["notice"]


def test_bundle_admin_gets_hint(monkeypatch):
    """TC-HUB-12 · 관리자 답에만 할 일(hint) — 그 칸의 오류 글이 실린다."""
    _stub_sections(monkeypatch, financials_error=RuntimeError("no such table: financial_statement"))
    out = asyncio.run(H.bundle(object(), "055550", admin=True, today=TODAY))
    assert "financial_statement" in out["sections"]["financials"]["hint"]


def test_bundle_sections_param_and_404(monkeypatch):
    """TC-HUB-13 · 고른 칸만 부른다(다른 칸 함수는 부르지 않음) · 모르는 종목은 404(이름표에 없음)."""
    _stub_sections(monkeypatch)
    called = []
    monkeypatch.setattr(H, "news", lambda sym: called.append("news") or H.section("news", H.OK))
    out = asyncio.run(H.bundle(object(), "055550", sections="signal,price", today=TODAY))
    assert out["order"] == ["identity", "price", "signal"] and called == []
    monkeypatch.setattr(H, "identity", lambda sym: H.section("identity", H.EMPTY, reason="못 찾음"))
    with pytest.raises(H.HubError) as e:
        asyncio.run(H.bundle(object(), "999999", today=TODAY))
    assert e.value.status == 404 and "999999" in e.value.message


def test_failed_maps_status():
    """TC-HUB-14 · 오류 → 칸 상태: 404 는 empty(그 글) · 5xx 는 error(일반 글 · 관리자만 글과 할 일)."""
    e404 = data_ohlcv.OhlcvError(404, "종목 없음: 999999")
    assert H._failed("price", e404, False) == H.section("price", H.EMPTY, reason="종목 없음: 999999")
    e503 = data_search.SearchError(503, "no_index", "검색 색인이 아직 없습니다.", "python -m collector.search_index build")
    gen, adm = H._failed("news", e503, False), H._failed("news", e503, True)
    assert gen["status"] == H.ERROR and gen["reason"] == H.GENERIC_ERROR and "hint" not in gen
    assert "collector.search_index" in adm["hint"] and "색인" in adm["hint"]
    cal = market_calendar.CalendarUnavailable("달력 표가 없습니다", 503)
    assert H._failed("schedule", cal, True)["hint"] == "달력 표가 없습니다"


# ── 질문 속 종목 ────────────────────────────────────────────────────────────────────────

NAMES = {
    "신한지주": ("055550", "KOSPI"), "SK하이닉스": ("000660", "KOSPI"), "SK": ("034730", "KOSPI"),
    "삼성전자": ("005930", "KOSPI"), "삼성전자우": ("005935", "KOSPI"), "기아": ("000270", "KOSPI"),
    "대상": ("001680", "KOSPI"), "태양": ("053620", "KOSDAQ"), "LG": ("003550", "KOSPI"), "LG전자": ("066570", "KOSPI"),
    "KT": ("030200", "KOSPI"), "KT&G": ("033780", "KOSPI"), "TP": ("007980", "KOSPI"), "KODEX 200": ("069500", "ETF"),
}


@pytest.mark.parametrize("q, want", [
    ("신한지주 지금 사도 될까요? 우리 앱의 신호와 근거를 같이", ["055550"]),
    ("SK하이닉스와 삼성전자 중 무엇이 나을까", ["000660", "005930"]),     # 「SK하이닉스」 안의 「SK」 는 따로 읽지 않는다
    ("삼성전자우를 살까", ["005935"]),                                    # 긴 이름(우선주)이 이긴다
    ("투자 대상은 뭐가 좋아요", []),                                       # 흔한 낱말 이름
    ("태양광 관련주 알려줘", []),                                          # 두 글자 이름 뒤에 다른 글자 — 낱말 경계 아님
    ("기아는 어때요", ["000270"]),
    ("LG전자 실적", ["066570"]),
    ("LG 그룹 지주사", ["003550"]),
    ("SKT 요금제", []),                                                    # 영문 이름 뒤에 영문 — 경계 아님
    ("SKT 말고 SK 주가는", ["034730"]),                                     # 앞 자리가 경계에 걸려도 뒤 자리는 읽는다
    ("KT&G 배당", ["033780"]),
    ("TP 가 뭐예요", []),                                                  # 흔한 약어
    ("KODEX 200 사도 돼?", ["069500"]),
    ("삼성전자 삼성전자 신한지주 기아", ["005930", "055550"]),             # 같은 종목은 한 번 · 최대 둘 · 나온 차례
])
def test_mentions(q, want):
    """TC-HUB-15 · 질문 속 종목 — 이름이 그대로 든 것만 · 경계 · 흔한 낱말 · 겹치면 긴 이름 · 차례 · 최대 둘."""
    got = H.mentions(q, table=NAMES)
    assert [x["symbol"] for x in got] == want
    for x in got:
        assert q[x["at"]:x["at"] + len(x["matched"])] == x["matched"]


def test_mentions_reads_names_from_collector_db(tmp_path, monkeypatch):
    """TC-HUB-16 · 이름표는 수집 시세의 마지막 날(주식 · ETF) — 옛 이름은 쓰지 않는다 · 수집 DB 가 없으면 빈 목록."""
    _fake_db(tmp_path, monkeypatch, stocks=[("20261014", "055550", "옛신한", "KOSPI"), ("20261015", "055550", "신한지주", "KOSPI")],
             etfs=[("20261015", "069500", "KODEX 200")])
    assert [x["symbol"] for x in H.mentions("신한지주 · KODEX 200")] == ["055550", "069500"]
    assert H.mentions("옛신한") == []
    monkeypatch.setattr(H, "_NAMES", {"at": 0.0, "names": {}})
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(tmp_path / "없음.sqlite3"))
    assert H.mentions("신한지주") == []


def test_mentions_input_capped():
    """TC-HUB-17 · 300자(상담 입력 상한) 뒤의 글은 보지 않는다."""
    assert H.mentions("가" * 300 + "신한지주", table=NAMES) == []


def test_mentions_one_card_per_code():
    """TC-HUB-21 · 이름 둘이 같은 종목(코드)을 가리켜도 한 번 — 이름표에 다른 이름(영문 이름 · 줄임말)을 더해도 카드가 둘로 겹치지 않게."""
    table = {"삼성전자": ("005930", "KOSPI"), "Samsung Electronics": ("005930", "KOSPI"), "신한지주": ("055550", "KOSPI")}
    got = H.mentions("삼성전자 · Samsung Electronics · 신한지주", table=table)
    assert [x["symbol"] for x in got] == ["005930", "055550"] and got[0]["matched"] == "삼성전자"


# ── API ──────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch):
    from app.database.postgres import get_pg_session
    from app.lib.session import get_current_user
    from app.routes import stock_hub as routes

    async def fake_session():
        yield object()

    _stub_sections(monkeypatch)
    monkeypatch.setattr(H, "names", lambda: NAMES)
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_pg_session] = fake_session
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "roles": ["user"]}
    c = TestClient(app)
    c.app_ref = app
    return c


def test_hub_endpoint(client, monkeypatch):
    """TC-HUB-18 · GET /api/stock-hub — 200 · 칸 고르기 · 잘못된 코드 · 칸 이름은 422 · 모르는 종목 404 · 칸이 실패하면 일반 사용자 답엔
    예외 글 · 할 일(hint)이 없고 관리자 답엔 있다(라우트가 로그인한 사람의 역할로 가른다)."""
    from app.lib.session import get_current_user
    r = client.get("/api/stock-hub?symbol=055550.KS&sections=price")
    assert r.status_code == 200 and r.json()["order"] == ["identity", "price"]
    assert client.get("/api/stock-hub?symbol=삼성").status_code == 422
    assert client.get("/api/stock-hub?symbol=055550&sections=verdict").status_code == 422
    assert client.get("/api/stock-hub").status_code == 422

    def no_table(sym):
        raise RuntimeError("no such table: financial_statement")
    monkeypatch.setattr(H, "financials", no_table)
    plain = client.get("/api/stock-hub?symbol=055550&sections=financials").json()
    assert plain["sections"]["financials"]["status"] == H.ERROR and "hint" not in str(plain) and "financial_statement" not in str(plain)
    client.app_ref.dependency_overrides[get_current_user] = lambda: {"id": "a1", "roles": ["admin"]}
    admin = client.get("/api/stock-hub?symbol=055550&sections=financials").json()
    assert "financial_statement" in admin["sections"]["financials"]["hint"]
    monkeypatch.setattr(H, "identity", lambda sym: H.section("identity", H.EMPTY, reason="못 찾음"))
    gone = client.get("/api/stock-hub?symbol=999999")
    assert gone.status_code == 404 and gone.json()["detail"]["code"] == "no_symbol"


def test_mentions_endpoint(client):
    """TC-HUB-19 · GET /api/stock-hub/mentions — 읽은 글(matched)을 돌려줌 · 300자 넘으면 422."""
    r = client.get("/api/stock-hub/mentions", params={"q": "신한지주 사도 될까요"})
    assert r.status_code == 200 and r.json()["items"][0]["matched"] == "신한지주" and "rule" in r.json()
    assert client.get("/api/stock-hub/mentions", params={"q": "가" * 301}).status_code == 422


def test_endpoints_require_login(client):
    """TC-HUB-20 · 두 길 모두 로그인한 사람만(401)."""
    from app.lib.session import get_current_user
    del client.app_ref.dependency_overrides[get_current_user]
    assert client.get("/api/stock-hub?symbol=055550").status_code == 401
    assert client.get("/api/stock-hub/mentions?q=x").status_code == 401


# ── 신호 기록 순위(#197 · 할 일 ②-19) ─────────────────────────────────────────

def _day_rows(n=6):
    """합성 기록 n 종목 — 종목마다 다른 봉에서 낸 T2 한 줄(`signal_at`) · 읽는 쪽 순서(종합 점수 → 신뢰도 → 종목코드)로 놓음."""
    from tests.test_signal_explain import _snapshots
    snaps = [_snapshots(seeds=[s], step=90)[0] for s in range(1, n + 1)]
    rows = [{**s, "symbol": f"T{i:05d}"} for i, s in enumerate(snaps)]
    rows.sort(key=lambda r: (-r["composite"], -r["confidence"], r["symbol"]))
    return rows


def _stub_day(monkeypatch, rows, missing=(), seen=None):
    async def load_day(db, on=None, symbols=None):
        if seen is not None:
            seen.append((on, symbols))
        return {"on": on, "definition": "def-test", "rows": list(rows), "missing": list(missing)}
    monkeypatch.setattr(signal_explain, "load_day", load_day)


def test_signal_rank_rows(monkeypatch):
    """TC-HUB-21 · 순위는 읽은 순서 그대로 · 줄마다 기준일 · 근거 개수 = 근거 표의 부호 수 · 자르면 total 이 남는다 · components 는 요청할 때만."""
    rows = _day_rows(6)
    miss = [{"symbol": "T99999", "reason": signal_explain.NOT_UNIVERSE}, {"symbol": "T88888", "reason": signal_explain.NONE}]
    _stub_day(monkeypatch, rows, miss)
    out = asyncio.run(H.signal_rank(object(), symbols=["T99999", "T88888"], limit=4))
    assert out["total"] == 6 and out["count"] == 4 and out["limit"] == 4 and out["definition"] == "def-test"
    assert [r["symbol"] for r in out["rows"]] == [r["symbol"] for r in rows[:4]]
    assert [r["rank"] for r in out["rows"]] == [1, 2, 3, 4]
    for got, snap in zip(out["rows"], rows):
        c = signal_explain.side_counts(snap)
        assert got["counts"] == {k: c[k] for k in ("buy", "neutral", "sell")} and "components" not in got
        assert got["as_of"] == str(snap["as_of"]) and got["signal"] == snap["signal"]
        assert got["composite"] == round(float(snap["composite"]), 4) and got["confidence"] == round(float(snap["confidence"]), 4)
    assert out["missing"] == [{"symbol": "T99999", "reason": "not_universe", "message": H.SIGNAL_NOT_UNIVERSE},
                              {"symbol": "T88888", "reason": "none", "message": H.SIGNAL_NONE}]
    assert out["notice"] == signal_explain.DISCLAIMER and out["source"] == H.SIGNAL_SOURCE and out["note"] == H.SIGNAL_RANK_NOTE
    full = asyncio.run(H.signal_rank(object(), components=True))
    assert full["count"] == 6 and full["rows"][0]["components"] == signal_explain.side_counts(rows[0])["components"]


def test_signal_rank_matches_hub_signal_section(monkeypatch):
    """TC-HUB-22 · 같은 종목은 허브 `signal` 칸과 같은 값 — 신호 · 기준일 · 신뢰도(같은 기록 · 같은 반올림)."""
    rows = _day_rows(4)
    by_symbol = {r["symbol"]: r for r in rows}
    _stub_day(monkeypatch, rows)

    async def load(db, symbol, on=None):
        return by_symbol.get(symbol)
    monkeypatch.setattr(signal_explain, "load_snapshot", load)
    out = asyncio.run(H.signal_rank(object()))
    assert out["count"] == 4
    for row in out["rows"]:
        hub = asyncio.run(H.signal(object(), row["symbol"], True))
        assert hub["status"] == H.OK
        assert (hub["as_of"], hub["data"]["signal"], hub["data"]["strength"], hub["data"]["confidence"]) == \
               (row["as_of"], row["signal"], row["strength"], row["confidence"])


def test_signal_rank_one_unknown_reason_does_not_block_the_rest(monkeypatch):
    """TC-HUB-23 · 낯선 근거 문장이 든 줄은 counts 만 비고(안내 글) 점수 · 순서 · 나머지 줄은 그대로 · unreadable 이 센다."""
    rows = _day_rows(5)
    bad = {**rows[1], "timeframes": [{**t, "reasons": list(t.get("reasons", [])) + ["RSI 다이버전스"]} if "score" in t else t
                                     for t in rows[1]["timeframes"]]}
    with pytest.raises(signal_explain.UnknownReason):
        signal_explain.side_counts(bad)
    _stub_day(monkeypatch, [rows[0], bad, *rows[2:]])
    out = asyncio.run(H.signal_rank(object()))
    assert out["count"] == 5 and out["unreadable"] == 1
    assert [r["symbol"] for r in out["rows"]] == [r["symbol"] for r in rows]
    assert out["rows"][1]["counts"] is None and out["rows"][1]["counts_note"] == H.SIGNAL_RANK_UNREADABLE
    assert out["rows"][1]["composite"] == round(float(bad["composite"]), 4) and out["rows"][1]["signal"] == bad["signal"]
    assert all(r["counts"] is not None and "counts_note" not in r for i, r in enumerate(out["rows"]) if i != 1)


def test_signal_rank_endpoint(client, monkeypatch):
    """TC-HUB-24 · GET /api/stock-hub/signal-rank — 200 · 기준일 · 종목(.KS 꼬리 떼기) · 줄 수가 읽는 쪽에 그대로 가고,
    잘못된 종목 · 빈 목록 · 100개 초과 · 줄 수 0 · 잘못된 날짜는 422 · 로그인한 사람만(401)."""
    from app.lib.session import get_current_user
    seen = []
    _stub_day(monkeypatch, _day_rows(3), seen=seen)
    r = client.get("/api/stock-hub/signal-rank?limit=2")
    assert r.status_code == 200 and r.json()["count"] == 2 and r.json()["total"] == 3 and seen[-1] == (None, None)
    ok = client.get("/api/stock-hub/signal-rank", params={"on": "2026-10-16", "symbols": "005930.KS, 000660 ,0000d0"})
    assert ok.status_code == 200 and seen[-1] == (date(2026, 10, 16), ["005930", "000660", "0000D0"])
    for q in ({"symbols": "삼성전자"}, {"symbols": " , "}, {"symbols": ""}, {"symbols": ",".join(["005930"] * 101)},
              {"limit": 0}, {"limit": 501}, {"on": "2026-13-01"}):
        assert client.get("/api/stock-hub/signal-rank", params=q).status_code == 422, q
    assert client.get("/api/stock-hub/signal-rank", params={"symbols": ",".join(["005930"] * 100)}).status_code == 200
    del client.app_ref.dependency_overrides[get_current_user]
    assert client.get("/api/stock-hub/signal-rank").status_code == 401
