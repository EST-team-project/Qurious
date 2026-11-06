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
    """TC-HUB-03 · 이름은 주식 시세 마지막 줄 → 없으면 ETF 시세 → 둘 다 없으면 empty · 수집 DB 가 없으면 error(빈칸으로 숨기지 않음).
    신호 기록 대상은 분봉 유니버스 + 마지막 거래일의 KOSPI · KOSDAQ · ETF(#487 · `mtf_signals.record_scope`) — KONEX 는 밖."""
    _fake_db(tmp_path, monkeypatch, stocks=[("20261015", "055550", "신한지주", "KOSPI"), ("20261015", "123456", "코넥스", "KONEX")],
             etfs=[("20261014", "069500", "옛이름"), ("20261015", "069500", "KODEX 200")])
    monkeypatch.setattr(mtf_signals, "universe", lambda **kw: ["055550"])
    s = H.identity("055550")
    assert s["status"] == H.OK and s["data"] == {"name": "신한지주", "market": "KOSPI", "kind": "stock", "signal_universe": True}
    e = H.identity("069500")
    assert e["status"] == H.OK and e["data"]["name"] == "KODEX 200" and e["data"]["kind"] == "etf"
    assert e["data"]["signal_universe"] is True
    assert H.identity("123456")["data"]["signal_universe"] is False
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
                "reasons": [{"key": "rsi_high", "timeframe": "1d", "label": "일봉", "text": "RSI 가 …", "points": -2, "extra": 1,
                             "observed": "RSI 74.2", "contribution": -1.23456, "rule": "내부 칸"}] * 4,
                "counter_reasons": [{"timeframe": "1w", "label": "주봉", "text": "MACD …", "points": 1}]}
    monkeypatch.setattr(signal_explain, "load_snapshot", load)
    monkeypatch.setattr(signal_explain, "explain", explain)
    monkeypatch.setattr(signal_explain, "side_counts", lambda s: {"buy": 1, "neutral": 2, "sell": 3, "components": []})
    s = asyncio.run(H.signal(object(), "055550", True))
    assert s["status"] == H.OK and s["as_of"] == "2026-10-16" and s["notice"] == "투자 권유가 아닙니다."
    # 근거는 자르지 않고 전부 낸다(사용자 11-02 「전부 보이게」 · 신호 순위 입구 통일) — 4개 · 반대 1개가 그대로
    assert s["data"]["summary"] == "일 기준으로 …" and len(s["data"]["reasons"]) == 4 and len(s["data"]["counter_reasons"]) == 1
    # 근거 개수는 순위 표와 같은 셈(side_counts) — 신호 칸이 모달에서 「근거 n개 (매수 쪽 · 중립 · 매도 쪽)」 를 보인다
    assert s["data"]["counts"] == {"buy": 1, "neutral": 2, "sell": 3} and "counts_note" not in s["data"]
    # key = 규칙 이름(화면의 쉬운 풀이 열쇠 · TC-SDR-10) · observed · contribution = `explain` 이 이미 만든 값(본 값 · 종합 점수 몫 · 2026-11-02 S192)
    assert set(s["data"]["reasons"][0]) == {"key", "timeframe", "label", "text", "points", "observed", "contribution"}
    assert s["data"]["reasons"][0]["key"] == "rsi_high"
    assert s["data"]["reasons"][0]["observed"] == "RSI 74.2" and s["data"]["reasons"][0]["contribution"] == -1.23      # 몫은 소수 둘째 자리 · 새 셈 없음
    # 옛 줄(값을 저장하지 않던 T2 · explain 이 observed 를 못 준 줄)은 칸은 있되 None — 화면이 줄을 만들지 않는다
    assert s["data"]["counter_reasons"][0]["observed"] is None and s["data"]["counter_reasons"][0]["contribution"] is None
    none_out = asyncio.run(H.signal(object(), "000660", False))
    assert none_out["status"] == H.EMPTY and none_out["reason"] == H.SIGNAL_NOT_UNIVERSE
    assert asyncio.run(H.signal(object(), "000660", None))["reason"] == H.SIGNAL_NONE
    assert asyncio.run(H.signal(object(), "000660", True))["reason"] == H.SIGNAL_NONE


def test_signal_section_counts_unreadable_keeps_reasons(monkeypatch):
    """TC-HUB-07b · 낯선 근거 문장 때문에 개수를 못 세면 개수만 비우고(0개로 두지 않음) 까닭을 남기며 근거 · 요약은 그대로 낸다 —
    순위 표(signal_rank)와 같은 갈래."""
    snap = {"symbol": "055550"}

    async def load(db, symbol, on=None):
        return snap

    def explain(s):
        return {"as_of": "2026-10-16", "signal": "관망", "strength": None, "confidence": 0.3, "definition": "d1", "summary": "요약",
                "confidence_text": "c", "disclaimer": "고지", "reasons": [{"key": "k", "timeframe": "1d", "label": "일봉", "text": "t", "points": 1}],
                "counter_reasons": []}

    def boom(s):
        raise signal_explain.UnknownReason("낯선 근거 문장")
    monkeypatch.setattr(signal_explain, "load_snapshot", load)
    monkeypatch.setattr(signal_explain, "explain", explain)
    monkeypatch.setattr(signal_explain, "side_counts", boom)
    s = asyncio.run(H.signal(object(), "055550", True))
    assert s["status"] == H.OK and s["data"]["counts"] is None and s["data"]["counts_note"] == H.SIGNAL_RANK_UNREADABLE
    assert s["data"]["summary"] == "요약" and len(s["data"]["reasons"]) == 1


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
    칸 이름은 달력 응답 그대로 · 섹터는 업종코드 → KSIC 제11차 이름(S181 — 앞 판은 「준비 중」 이었다 · 표에 없으면 비었다고 말하고 지어내지 않는다).
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
    # 섹터(S181 · 할 일 ②-10) — 업종코드 → KSIC 제11차 중분류 · 대분류 이름 + 같은 업종 수집 상장사 수. 10차 이름은 섞이지 않는다.
    c = sqlite3.connect(p)
    for rev, level, code, name, parent in (("11", "대분류", "K", "금융 및 보험업", ""), ("11", "중분류", "64", "금융업", "K"),
                                           ("10", "중분류", "64", "옛 차수 이름", "K")):
        c.execute("INSERT INTO ksic_code (revision, level, code, name, parent_code, section, loaded_at) VALUES (?, ?, ?, ?, ?, '', 'x')",
                  (rev, level, code, name, parent))
    for corp, stock, induty in (("c1", "055550", "64992"), ("c2", "105560", "64121"), ("c3", "", "64121"), ("c4", "005930", "26110")):
        c.execute("INSERT INTO dart_company (corp_code, fields_sha256, stock_code, induty_code, first_seen_at, last_seen_at) "
                  "VALUES (?, 'f', ?, ?, 'x', '2026-10-15 12:40:00')", (corp, stock, induty))
    c.commit()
    c.close()
    sec = H.sector("055550")
    assert sec["status"] == H.OK and sec["as_of"] == "2026-10-15" and sec["source"] == H.SECTOR_SOURCE
    assert sec["data"] == {"induty_code": "64992", "division_code": "64", "division_name": "금융업", "section_code": "K",
                           "section_name": "금융 및 보험업", "peer_count": 2}   # 종목코드 없는 법인(c3)은 같은 업종 수에 안 든다
    nof = H.sector("005930")      # 업종코드 앞 두 자리(26)가 KSIC 표에 없다 → 비었다고 말한다(지어내지 않는다)
    assert nof["status"] == H.EMPTY and nof["data"] is None and "26" in nof["reason"]
    none = H.sector("000660")     # 기업개황에 이 종목이 없다
    assert none["status"] == H.EMPTY and "업종코드를 찾지 못" in none["reason"]


# ── 묶음 ────────────────────────────────────────────────────────────────────────────────

def _stub_sections(monkeypatch, *, financials_error=None, signal_error=None):
    monkeypatch.setattr(H, "identity", lambda sym: H.section("identity", H.OK, data={
        "name": "신한지주", "market": "KOSPI", "kind": "stock", "signal_universe": True}))
    monkeypatch.setattr(H, "price", lambda sym, today: H.section("price", H.OK, as_of="2026-10-16"))

    async def sig(db, sym, uni, on=None, today=None):
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
    monkeypatch.setattr(H, "sector", lambda sym: H.section("sector", H.OK))


def test_bundle_shape_and_isolation(monkeypatch):
    """TC-HUB-11 · 묶음 — 칸 차례 · 칸 하나가 터져도 나머지는 돌려줌 · 일반 사용자에겐 예외 글 없음 · 맨 위에 결론 칸 없음."""
    _stub_sections(monkeypatch, financials_error=RuntimeError("no such table: financial_statement"),
                   signal_error=ConnectionRefusedError("앱 DB 127.0.0.1:15432"))
    out = asyncio.run(H.bundle(object(), "055550.KS", today=TODAY))
    assert set(out) == {"version", "symbol", "name", "market", "generated_at", "order", "sections", "links", "notice", "note"}
    assert out["version"] == H.VERSION and out["symbol"] == "055550" and out["name"] == "신한지주"
    assert out["order"] == list(H.SECTIONS) and list(out["sections"]) == list(H.SECTIONS)
    assert out["sections"]["financials"]["status"] == H.ERROR and out["sections"]["signal"]["status"] == H.ERROR
    assert out["sections"]["price"]["status"] == H.OK and out["sections"]["sector"]["status"] == H.OK
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
    async def load_day(db, on=None, symbols=None, limit=None):
        if seen is not None:
            seen.append((on, symbols))
        head = max((r["as_of"] for r in rows), default=None)             # 집계는 진짜 load_day 처럼 자르기 전 전체 줄로(#487)
        stamps = [r["computed_at"] for r in rows if r["as_of"] == head and r.get("computed_at")]
        return {"on": on, "definition": "def-test", "rows": list(rows)[:limit], "missing": list(missing),
                "total": len(rows), "as_of_max": head, "computed_at_max": max(stamps, default=None),
                "older_count": sum(r["as_of"] != head for r in rows)}
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


def test_price_section_says_when_last_close_is_not_in_yet(monkeypatch):
    """TC-HUB-25 · 마지막 종가가 마지막으로 끝난 거래일보다 오래됐으면 가격 칸 `pending_note` 가 「반영 전」 을 말한다(2026-11-01 · 글은
    quote_now 한 곳) — 최신이면 빈 글 · 줄이 없으면 이 칸 자체가 empty."""
    from datetime import datetime  # noqa: PLC0415

    from app.services import quote_now  # noqa: PLC0415

    monkeypatch.setattr(quote_now, "_now", lambda: datetime(2026, 10, 19, 10, 0, tzinfo=quote_now.KST))   # 월요일 낮

    def rows(last):
        return lambda *a, **k: {"rows": [{"trade_date": "2026-10-15", "close": 50_000}, {"trade_date": last, "close": 49_000}]}
    monkeypatch.setattr(data_ohlcv, "read_ohlcv", rows("2026-10-16"))
    assert H.price("055550", TODAY)["data"]["pending_note"] == ""
    monkeypatch.setattr(data_ohlcv, "read_ohlcv", rows("2026-10-15"))
    assert H.price("055550", TODAY)["data"]["pending_note"] == "10월 16일 종가는 반영 전"


# ── 신호 순위 머리줄 · 분봉 없음 표시(할 일 ②-33 · Figma 「신호 순위」 07 쪽 ①) ─────────────────────────

def _kst(y, m, d, hh, mm):
    from datetime import datetime, timedelta, timezone
    return datetime(y, m, d, hh, mm, tzinfo=timezone(timedelta(hours=9)))


def test_signal_freshness_badges_by_time(monkeypatch):
    """TC-HUB-60 · 기준일이 「있어야 할 날」 보다 앞서면 확인 필요 · 장중이면 안내 · 그 밖은 최신 — 월요일 오전 · 장 마감 직후에 거짓 경고가 없다."""
    from datetime import date, datetime, timezone
    at = datetime(2026, 11, 2, 3, 59, tzinfo=timezone.utc)            # 11-02 12:59 KST
    fri, mon = date(2026, 10, 30), date(2026, 11, 2)
    f = H.signal_freshness(fri, at, 0, now=_kst(2026, 11, 2, 12, 59))                   # 월요일 낮 장중 — 금요일 종가가 막 들어오는 때
    assert (f["badge"], f["state"]) == ("안내", "session") and f["computed_at"] == "2026-11-02 12:59" and f["as_of"] == "2026-10-30"
    assert f["basis"] == H.SIGNAL_BASIS and "장중에는 지난 거래일 종가 기준" in f["message"]
    assert H.signal_freshness(fri, at, 0, now=_kst(2026, 11, 2, 17, 0))["badge"] == "최신"       # 장 마감 뒤 — 월요일 종가는 화요일 낮에야 들어온다
    assert H.signal_freshness(fri, at, 0, now=_kst(2026, 11, 7, 10, 0))["state"] == "stale"       # 토요일 — 11-06 종가는 월요일 낮에야 · 기대는 11-05 인데 10-30 은 앞선다
    stale = H.signal_freshness(fri, at, 0, now=_kst(2026, 11, 3, 14, 0))                    # 화요일 14:00 인데 아직 10-30
    assert (stale["badge"], stale["state"]) == ("확인 필요", "stale") and stale["message"] == "지난 거래일(11-02) 신호는 아직 계산 전입니다"
    assert H.signal_freshness(mon, at, 0, now=_kst(2026, 11, 3, 14, 0))["badge"] != "확인 필요"
    assert H.signal_freshness(fri, at, 0, now=_kst(2026, 11, 3, 10, 0))["state"] != "stale"        # 화요일 오전 — 월요일 종가는 아직 기대하지 않는다
    # 날짜를 고른 요청은 최신 여부를 판정하지 않는다 · 기록이 없으면 확인 필요 · 앞 날짜 줄은 따로 알린다
    picked = H.signal_freshness(fri, at, 0, picked=True, now=_kst(2026, 11, 3, 14, 0))
    assert (picked["badge"], picked["state"]) == ("안내", "picked") and "고른 날짜(10-30)" in picked["message"]
    none = H.signal_freshness(None, None, 0, now=_kst(2026, 11, 3, 14, 0))
    assert (none["badge"], none["state"], none["as_of"], none["computed_at"]) == ("확인 필요", "unknown", None, None)
    assert H.signal_freshness(fri, at, 12, now=_kst(2026, 11, 2, 17, 0))["older_note"].startswith("12줄은 그 앞 날짜")


def test_signal_rank_carries_freshness_and_no_intraday(monkeypatch):
    """TC-HUB-61 · 응답에 기록 줄들의 가장 늦은 기준일 · 계산 시각 · 머리줄 글 · 줄마다 「분봉 없이 계산」(기록의 60분 주기 오류에서 읽음)."""
    from datetime import date, datetime, timezone
    rows = _day_rows(3)
    for i, r in enumerate(rows):
        r["as_of"] = date(2026, 10, 30) if i < 2 else date(2026, 10, 29)
        r["computed_at"] = datetime(2026, 11, 2, 3, 59 - i, tzinfo=timezone.utc)
        if i == 1:                                                      # 이 줄만 60분 주기가 비었다(분봉 없음) — 나머지 칸은 그대로 둔다
            r["timeframes"] = [{**t, "error": "시세 없음"} if t.get("timeframe") == "60m" else t for t in r["timeframes"]]
            for t in r["timeframes"]:
                if t.get("timeframe") == "60m":
                    t.pop("score", None)
    _stub_day(monkeypatch, rows)
    out = asyncio.run(H.signal_rank(object()))
    fr = out["freshness"]
    assert out["as_of"] == "2026-10-30" == fr["as_of"] and fr["computed_at"] == "2026-11-02 12:59"       # 그날 줄 가운데 가장 늦은 계산 시각
    assert fr["older_rows"] == 1 and "1줄은 그 앞 날짜" in fr["older_note"]
    assert [r["no_intraday"] for r in out["rows"]] == [False, True, False]
    # 날짜를 고르면(on) 최신 여부를 판정하지 않는다
    picked = asyncio.run(H.signal_rank(object(), on=date(2026, 10, 30)))
    assert picked["freshness"]["state"] == "picked"
    # 기록이 없으면 확인 필요
    _stub_day(monkeypatch, [])
    assert asyncio.run(H.signal_rank(object()))["freshness"]["state"] == "unknown"


def test_not_universe_message_no_longer_claims_401():
    """TC-HUB-62 · 신호 기록 대상이 전체로 넓어져 「401종목」 문구는 틀린 말이다."""
    assert "401" not in H.SIGNAL_NOT_UNIVERSE and "KOSPI" in H.SIGNAL_NOT_UNIVERSE and "ETF" in H.SIGNAL_NOT_UNIVERSE


def test_attach_names_puts_a_name_on_every_rank_row(tmp_path, monkeypatch):
    """TC-HUB-63 · 신호 순위 줄마다 종목 이름을 한 번에 붙인다(순위 새 화면 · 2026-11-02) — 주식 이름표 → 없으면 ETF 이름표 ·
    `.KS` 꼬리 코드도 · 못 찾으면 빈 글. 이름은 꾸밈이라 수집 DB 를 못 읽어도 줄 · 순서는 그대로다."""
    _fake_db(tmp_path, monkeypatch, stocks=[("20261030", "005930", "삼성전자", "KOSPI")], etfs=[("20261030", "069500", "KODEX 200")])
    resp = {"rows": [{"symbol": "005930.KS"}, {"symbol": "069500"}, {"symbol": "999999"}], "count": 3}
    out = H.attach_names(resp)
    assert out is resp                                                    # 같은 응답에 칸만 더한다
    assert [r["name"] for r in out["rows"]] == ["삼성전자", "KODEX 200", ""]
    # 2026-11-06: 시장(`market`)도 같이 붙는다 — 새로고침의 「지금 가격」 이 .KS · .KQ 꼬리를 붙이는 근거. 못 찾으면 빈 글(짐작 금지)
    assert [r["market"] for r in out["rows"]] == ["KOSPI", "ETF", ""]
    assert out["count"] == 3
    # 수집 DB 가 없으면 이름 · 시장만 빈 글
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(tmp_path / "없음.sqlite3"))
    assert H.attach_names({"rows": [{"symbol": "005930"}]})["rows"] == [{"symbol": "005930", "name": "", "market": ""}]
    assert H.attach_names({"rows": []}) == {"rows": []}


# ── 신호 칸 기록 시점 · 날짜 고르기(S195 · 2026-11-03 · 날짜별 근거 안 A) ─────────────────────────────

def _kst_at(y, m, d, hh, mm):
    from datetime import datetime, timedelta, timezone
    return datetime(y, m, d, hh, mm, tzinfo=timezone(timedelta(hours=9)))


def test_record_kind_boundaries():
    """TC-HUB-64 · 기준일 다음 거래일 안(KST)에 계산했으면 정기 · 그 뒤면 늦게 계산 — 정시 / 다음날 이후 / 주말 / 공휴일 / 계산 시각 없음."""
    fri = date(2026, 10, 30)
    regular = H.record_kind(fri, _kst_at(2026, 11, 2, 12, 59))                       # 금요일 신호를 월요일 낮에 — 정상 12:30 회차
    assert (regular["record_kind"], regular["lag_days"], regular["expected_on"]) == ("regular", 0, "2026-11-02")
    assert regular["computed_at"] == "2026-11-02 12:59" and regular["record_label"] == "정기 기록" and regular["record_tip"] == ""
    assert regular["record_note"] == "10-30 종가 기준입니다. 다음 거래일(11-02) 12:59 에 계산해 기록했습니다."
    assert H.record_kind(fri, _kst_at(2026, 11, 2, 23, 59))["record_kind"] == "regular"          # 그 날(KST) 끝까지는 정기
    late = H.record_kind(fri, _kst_at(2026, 11, 3, 0, 1))                                     # 자정을 넘기면 늦게
    assert (late["record_kind"], late["lag_days"], late["record_label"]) == ("late", 1, "늦게 계산") and late["record_tip"]
    assert "11-03 00:01 에 늦게 계산한 값" in late["record_note"] and "그날 이 화면에서 실제로 보였던 값은 아닐 수 있습니다" in late["record_note"]
    assert H.record_kind(fri, _kst_at(2026, 11, 5, 9, 20))["lag_days"] == 3                    # 정기 기록일(11-02)보다 3일 뒤
    # 주말을 건너뜀 — 금요일 기준일의 정기 기록일은 토 · 일이 아니라 월요일, 토요일에 계산됐어도(앞서 계산) 정기
    assert H.record_kind(fri, _kst_at(2026, 10, 31, 10, 0))["record_kind"] == "regular"
    assert "10-31 10:00 에 계산해 기록했습니다" in H.record_kind(fri, _kst_at(2026, 10, 31, 10, 0))["record_note"]
    # 공휴일 건너뜀 — 10-08(목) 다음 거래일은 10-09(한글날 휴장) · 주말을 지난 10-12(월)
    assert H.record_kind(date(2026, 10, 8), _kst_at(2026, 10, 12, 20, 0))["record_kind"] == "regular"
    assert H.record_kind(date(2026, 10, 8), _kst_at(2026, 10, 13, 9, 0))["record_kind"] == "late"
    # UTC 값도 한국 시각으로 읽는다 — 11-02 15:30 UTC = 11-03 00:30 KST
    from datetime import datetime, timezone
    assert H.record_kind(fri, datetime(2026, 11, 2, 15, 30, tzinfo=timezone.utc))["record_kind"] == "late"
    assert H.record_kind(fri, datetime(2026, 11, 2, 3, 59))["computed_at"] == "2026-11-02 12:59"   # 시각대가 빠진 값은 UTC
    # 옛 기록(계산 시각 없음) — 지어내지 않고 모름
    unknown = H.record_kind(fri, None)
    assert (unknown["record_kind"], unknown["lag_days"], unknown["computed_at"], unknown["expected_on"]) == ("unknown", None, None, None)
    assert "알 수 없습니다" in unknown["record_note"]


def test_record_texts_avoid_forbidden_words():
    """TC-HUB-65 · 기록 시점 글은 설명 기준 5.4.1 의 쓰지 않는 말(확률 · 추천 · 보장 …)을 쓰지 않고 「소급」 을 단정하지 않는다."""
    fri = date(2026, 10, 30)
    texts = [H.RECORD_TIP, *H.RECORD_LABELS.values()]
    for at in (_kst_at(2026, 11, 2, 12, 59), _kst_at(2026, 10, 31, 9, 0), _kst_at(2026, 11, 9, 9, 20), None):
        r = H.record_kind(fri, at)
        texts += [r["record_note"], r["record_tip"], r["record_label"]]
    assert not [w for w in signal_explain.FORBIDDEN if any(w in t for t in texts)]
    assert "소급" not in " ".join(texts) and "믿지" not in " ".join(texts)


def test_trading_day_steps_skip_weekends_and_holidays():
    """TC-HUB-66 · 앞/다음 거래일은 주말 · 휴장일(한글날 10-09)을 건너뛴다."""
    assert H.next_trading_day(date(2026, 10, 30)) == date(2026, 11, 2) and H.prev_trading_day(date(2026, 11, 2)) == date(2026, 10, 30)
    assert H.next_trading_day(date(2026, 10, 8)) == date(2026, 10, 12) and H.prev_trading_day(date(2026, 10, 12)) == date(2026, 10, 8)
    assert H.next_trading_day(date(2026, 10, 2)) == date(2026, 10, 6)          # 10-05 대체공휴일 · 주말
    pick = H.signal_pick(date(2026, 10, 12), date(2026, 10, 11), date(2026, 11, 2), date(2026, 11, 3))
    assert (pick["prev_day"], pick["next_day"], pick["requested_on"], pick["picked"], pick["max_on"]) == \
           ("2026-10-08", "2026-10-13", "2026-10-11", True, "2026-11-03")
    # 가장 최근 기록을 넘으면 다음은 비고, 날짜를 고르지 않은 최신 보기도 다음이 없다
    assert H.signal_pick(date(2026, 11, 2), date(2026, 11, 2), date(2026, 11, 2), date(2026, 11, 3))["next_day"] is None
    assert H.signal_pick(date(2026, 11, 2), None, date(2026, 11, 2), date(2026, 11, 3))["next_day"] is None


def _stub_snapshots(monkeypatch, by_day, computed=None):
    """날짜별 기록 합성 — load_snapshot 이 on 이전(포함) 가장 최근 줄을 돌려주는 규칙 그대로. 호출한 on 들을 모아 돌려준다."""
    calls = []

    async def load(db, symbol, on=None):
        calls.append(on)
        days = sorted(d for d in by_day if on is None or d <= on)
        if not days:
            return None
        return {"symbol": symbol, "as_of": days[-1], "computed_at": (computed or {}).get(days[-1])}

    def explain(s):
        return {"as_of": s["as_of"].isoformat(), "signal": "매수", "strength": "보통", "confidence": 0.6, "definition": "d1",
                "summary": "요약", "confidence_text": "c", "disclaimer": "고지", "reasons": [], "counter_reasons": []}
    monkeypatch.setattr(signal_explain, "load_snapshot", load)
    monkeypatch.setattr(signal_explain, "explain", explain)
    monkeypatch.setattr(signal_explain, "side_counts", lambda s: {"buy": 0, "neutral": 0, "sell": 0, "components": []})
    return calls


def test_signal_section_carries_record_time_and_picked_day(monkeypatch):
    """TC-HUB-67 · 신호 칸에 계산 시각 · 정기/늦게 계산 · 지금 보이는 날의 앞/다음 거래일이 실리고, 날짜를 고르면(signal_on) 그날 줄이 나오고
    그날 줄이 없어 앞 날짜가 나오면 fell_back + 안내 글 · 고르기 자료(requested_on · max_on · latest_as_of)가 있다."""
    d29, d30, d02 = date(2026, 10, 29), date(2026, 10, 30), date(2026, 11, 2)
    calls = _stub_snapshots(monkeypatch, {d29: 1, d30: 1, d02: 1},
                            {d29: _kst_at(2026, 10, 30, 12, 59), d30: _kst_at(2026, 11, 5, 9, 20), d02: _kst_at(2026, 11, 3, 12, 59)})
    today = date(2026, 11, 3)
    latest = asyncio.run(H.signal(object(), "055550", True, today=today))["data"]
    assert calls == [None] and latest["record_kind"] == "regular" and latest["computed_at"] == "2026-11-03 12:59"
    assert (latest["picked"], latest["requested_on"], latest["fell_back"], latest["next_day"], latest["prev_day"]) == (False, None, False, None, "2026-10-30")
    assert latest["max_on"] == "2026-11-03" and latest["latest_as_of"] == "2026-11-02" and "fell_back_note" not in latest
    # 고른 날 줄이 있다 — 늦게 계산된 줄(10-30 줄은 11-05 에 계산됨)
    sec = asyncio.run(H.signal(object(), "055550", True, on=d30, today=today))
    d = sec["data"]
    assert sec["as_of"] == "2026-10-30" and d["record_kind"] == "late" and d["lag_days"] == 3 and d["computed_at"] == "2026-11-05 09:20"
    assert (d["picked"], d["requested_on"], d["fell_back"]) == (True, "2026-10-30", False)
    assert (d["prev_day"], d["next_day"], d["latest_as_of"]) == ("2026-10-29", "2026-11-02", "2026-11-02")      # 다음 거래일은 주말을 건너뜀
    # 고른 날 줄이 없어(주말) 앞 날짜가 나옴 — 숨기지 않고 알린다
    fb = asyncio.run(H.signal(object(), "055550", True, on=date(2026, 11, 1), today=today))
    assert fb["as_of"] == "2026-10-30" and fb["data"]["fell_back"] is True and fb["data"]["requested_on"] == "2026-11-01"
    assert fb["data"]["fell_back_note"] == "11-01 은 신호 기록이 없어 그 앞 가장 가까운 날(10-30)의 기록을 보여 드립니다."
    # 오늘을 고르면(아직 오늘 기록 없음) 가장 최근 줄 · 다음 거래일 없음
    td = asyncio.run(H.signal(object(), "055550", True, on=today, today=today))
    assert td["as_of"] == "2026-11-02" and td["data"]["fell_back"] is True and td["data"]["next_day"] is None
    # 계산 시각이 없는 옛 줄 — 모름 (지어내지 않는다)
    _stub_snapshots(monkeypatch, {d30: 1})
    old = asyncio.run(H.signal(object(), "055550", True, today=today))["data"]
    assert (old["record_kind"], old["computed_at"], old["lag_days"]) == ("unknown", None, None)


def test_signal_section_before_first_record_keeps_the_picker(monkeypatch):
    """TC-HUB-68 · 고른 날 이전에 기록이 하나도 없으면 빈 칸 + 날짜를 다시 고를 자료(requested_on · next_day) — 막다른 길이 아니다.
    기록이 아예 없으면 평소 안내(자료 없음)."""
    _stub_snapshots(monkeypatch, {date(2026, 10, 30): 1, date(2026, 11, 2): 1})
    today = date(2026, 11, 3)
    sec = asyncio.run(H.signal(object(), "055550", True, on=date(2026, 10, 20), today=today))
    assert sec["status"] == H.EMPTY and "10-20" in sec["reason"] and "신호 기록이 없습니다" in sec["reason"]
    d = sec["data"]
    assert (d["requested_on"], d["picked"], d["prev_day"], d["latest_as_of"], d["max_on"]) == ("2026-10-20", True, None, "2026-11-02", "2026-11-03")
    assert d["next_day"] == "2026-10-21"
    _stub_snapshots(monkeypatch, {})
    none = asyncio.run(H.signal(object(), "000660", False, on=date(2026, 10, 20), today=today))
    assert none["status"] == H.EMPTY and none["reason"] == H.SIGNAL_NOT_UNIVERSE and none["data"] is None


def test_bundle_passes_signal_on_and_rejects_future(monkeypatch):
    """TC-HUB-69 · 묶음이 signal_on 을 신호 칸에 넘기고, 오늘보다 뒤 날짜는 422(조용히 최신으로 바꾸지 않음) · VERSION 은 4 이상."""
    _stub_sections(monkeypatch)
    seen = []

    async def sig(db, sym, uni, on=None, today=None):
        seen.append((on, today))
        return H.section("signal", H.OK, as_of="2026-10-16")
    monkeypatch.setattr(H, "signal", sig)
    asyncio.run(H.bundle(object(), "055550", sections="signal", today=TODAY, signal_on=date(2026, 10, 15)))
    assert seen == [(date(2026, 10, 15), TODAY)]
    asyncio.run(H.bundle(object(), "055550", sections="signal", today=TODAY, signal_on=TODAY))      # 오늘은 된다
    with pytest.raises(H.HubError) as e:
        asyncio.run(H.bundle(object(), "055550", sections="signal", today=TODAY, signal_on=date(2026, 10, 18)))
    assert e.value.status == 422 and e.value.code == "bad_signal_on"
    assert H.VERSION >= 4


def test_hub_endpoint_signal_on(client, monkeypatch):
    """TC-HUB-70 · GET /api/stock-hub?signal_on= — 날짜는 신호 칸에 넘어가고 · 형식 오류 · 미래 날짜는 422 · 비우면 None."""
    seen = []

    async def sig(db, sym, uni, on=None, today=None):
        seen.append(on)
        return H.section("signal", H.OK, as_of="2026-10-16")
    monkeypatch.setattr(H, "signal", sig)
    assert client.get("/api/stock-hub?symbol=055550&sections=signal").status_code == 200 and seen[-1] is None
    assert client.get("/api/stock-hub?symbol=055550&sections=signal&signal_on=2026-10-15").status_code == 200 and seen[-1] == date(2026, 10, 15)
    assert client.get("/api/stock-hub?symbol=055550&sections=signal&signal_on=2026-13-40").status_code == 422
    assert client.get("/api/stock-hub?symbol=055550&sections=signal&signal_on=가나다").status_code == 422
    future = client.get("/api/stock-hub?symbol=055550&sections=signal&signal_on=2099-01-01")
    assert future.status_code == 422 and future.json()["detail"]["code"] == "bad_signal_on"


def test_signal_rank_filters_reach_load_day_before_limit(client, monkeypatch):
    """TC-HUB-71 · 신호 순위 필터(2026-11-05) — `signal`(매수 · 매도 · 관망)과 `market`(KOSPI · KOSDAQ · ETF)이 limit 전에 걸리도록
    읽는 쪽(`load_day`)에 그대로 가고, 잘못된 낱말은 422 · 시장을 못 읽으면 말없이 전체를 보이지 않고 503 · 필터가 없으면 읽는 쪽에
    새 인자를 넘기지 않는다(옛 호출과 같다) · 응답에 `matched` 와 `filter` 가 있다."""
    from app.lib.session import get_current_user  # noqa: PLC0415

    got = []

    async def load_day(db, on=None, symbols=None, limit=None, **extra):
        got.append((limit, dict(extra)))
        rows = _day_rows(3)
        return {"on": on, "definition": "def-test", "rows": rows[:limit], "missing": [], "total": 3, "as_of_max": rows[0]["as_of"],
                "computed_at_max": None, "older_count": 0, "matched": 2 if extra else None}

    monkeypatch.setattr(H.signal_explain, "load_day", load_day)
    monkeypatch.setattr(H, "market_codes", lambda m: frozenset({"005930", "000660"}) if m != "ETF" else None)

    plain = client.get("/api/stock-hub/signal-rank?limit=2").json()
    assert got[-1] == (2, {}) and plain["matched"] is None and plain["filter"] == {"signal": None, "market": None}

    r = client.get("/api/stock-hub/signal-rank", params={"signal": "매수", "market": "KOSPI", "limit": 2})
    body = r.json()
    assert r.status_code == 200 and got[-1] == (2, {"signal": "매수", "only_codes": frozenset({"005930", "000660"})})
    assert body["matched"] == 2 and body["filter"] == {"signal": "매수", "market": "KOSPI"}

    only_signal = client.get("/api/stock-hub/signal-rank", params={"signal": "관망"})
    assert only_signal.status_code == 200 and got[-1][1] == {"signal": "관망"}

    for q in ({"signal": "BUY"}, {"signal": "강력매수"}, {"market": "코스피"}, {"market": "KONEX"}):
        bad = client.get("/api/stock-hub/signal-rank", params=q)
        assert bad.status_code == 422 and bad.json()["detail"]["code"] in ("bad_signal", "bad_market"), q

    unreadable = client.get("/api/stock-hub/signal-rank", params={"market": "ETF"})
    assert unreadable.status_code == 503 and unreadable.json()["detail"]["code"] == "market_unavailable"
    del client.app_ref.dependency_overrides[get_current_user]
