"""패턴 화면 응답 — 패턴 통계 묶음 · 가격 수준 · 다중 주기 신호의 기록/그 자리 계산 (TC-PV · `P01-②-2` · `②-3` · `①-5`).

목표 기능 ② 설계서 <표 13> `API-STK-34` · `API-STK-35` · W4. 수집 DB · 앱 DB 없이 합성 봉으로 돈다.
"""
import asyncio
import json
import re
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from app.routes import stocks
from app.services import mtf_signals as ms
from app.services import pattern_stats as ps
from app.services import pattern_view as pv
from app.services import signal_explain as se
from app.services import ta_utils as ta
from app.services.patterns import pattern_summary, timeframe_score
from app.services.quant_pipeline import preprocess
from tests.conftest import make_candles
from tests.test_mtf_signals import _bars


@pytest.fixture(autouse=True)
def _fresh_cache():
    # 시험이 바꿔 끼운 함수가 아니라 원래 함수의 저장값을 지운다
    cached = (pv._symbol_stats, pv._benchmark)
    for f in cached:
        f.cache_clear()
    yield
    for f in cached:
        f.cache_clear()


# ── 패턴 통계 ─────────────────────────────────────────────────────────────

def test_summary_is_the_scan_result():
    """앱에 담은 전 종목 통계 = 스캔 결과 — 11종 · 봉인 구간 전 끝날 · 사건 수 합 = meta."""
    s = pv.load_summary()
    assert [p["key"] for p in s["patterns"]] == list(ps.STAT_PATTERNS)
    assert s["meta"]["end"] < ps.SEAL_START and s["meta"]["definition"] == ta.DEFINITION
    assert sum(p["events"] for p in s["patterns"]) == s["meta"]["events"]


def test_stats_block_puts_all_and_symbol_side_by_side(monkeypatch):
    one = {"baseline_mean_5d": 0.001, "baseline_up_ratio": 0.5, "baseline_days": 10,
           "patterns": {"doji": {"events": 3, "mean_ret_5d": 0.01, "up_ratio": 2 / 3, "mean_excess_5d": None}}}
    monkeypatch.setattr(pv, "symbol_stats", lambda symbol: one)
    b = pv.stats_block("005930.KS")
    s = pv.load_summary()
    assert len(b["patterns"]) == 11 and b["end"] == s["meta"]["end"]
    for row, p in zip(b["patterns"], s["patterns"]):
        assert row["all"]["events"] == p["events"] and row["all"]["mean_ret_5d"] == p["mean_ret_5d"]
        # 그 종목 자료는 있는데 사건이 없던 패턴은 0 — 「자료 없음」(None)과 가른다
        assert row["symbol"] == one["patterns"].get(p["key"], {"events": 0})
    assert b["baseline"]["symbol"] == {"mean_ret_5d": 0.001, "up_ratio": 0.5}


def test_stats_block_without_symbol_data(monkeypatch):
    """수집 DB 에 없는 종목(해외 등) — 전 종목 줄만, 그 종목 칸은 비움."""
    monkeypatch.setattr(pv, "symbol_stats", lambda symbol: None)
    b = pv.stats_block("AAPL")
    assert all(r["symbol"] is None for r in b["patterns"]) and b["baseline"]["symbol"] is None


def test_symbol_stats_same_rule_as_scan_and_reads_before_seal(monkeypatch):
    """그 종목 통계 = `event_study` 를 같은 끝날로 · 수집 DB 는 끝날까지만 읽는다(봉인 구간 안 읽음)."""
    candles = make_candles(500)
    seen = {}

    def fake_read(symbol, period, *, today=None, **_):
        seen.update(symbol=symbol, period=period, today=today)
        return {"candles": candles}

    monkeypatch.setattr(pv.collector_db, "read_daily_candles", fake_read)
    monkeypatch.setattr(pv, "_benchmark", lambda end: None)
    got = pv.symbol_stats("005930.KS")
    end = pv.load_summary()["meta"]["end"]
    assert seen == {"symbol": "005930.KS", "period": "max", "today": date.fromisoformat(end)}
    ev, base = ps.event_study(preprocess(candles), None, end=end)
    assert got["baseline_days"] == base["baseline_days"]
    assert {k: v["events"] for k, v in got["patterns"].items()} == ev.groupby("key").size().to_dict()
    for key, g in ev.groupby("key"):
        assert got["patterns"][key]["mean_ret_5d"] == pytest.approx(g["forward_ret_5d"].mean())


def test_symbol_stats_none_when_no_data(monkeypatch):
    monkeypatch.setattr(pv.collector_db, "read_daily_candles", lambda *a, **k: None)
    assert pv.symbol_stats("AAPL") is None


def test_symbol_stats_failure_is_not_cached(monkeypatch):
    """수집 DB 를 잠깐 못 읽은 결과(없음 · 오류)는 저장하지 않는다 — 다음 요청이 다시 읽는다."""
    calls = []

    def flaky(symbol, period, *, today=None, **_):
        calls.append(1)
        if len(calls) == 1:
            return None
        if len(calls) == 2:
            raise RuntimeError("database is locked")
        return {"candles": make_candles(500)}

    monkeypatch.setattr(pv.collector_db, "read_daily_candles", flaky)
    monkeypatch.setattr(pv, "_benchmark", lambda end: None)
    assert pv.symbol_stats("005930.KS") is None          # 없음
    assert pv.symbol_stats("005930.KS") is None          # 오류 — 응답은 막지 않는다
    assert pv.symbol_stats("005930.KS") is not None      # 세 번째에 읽힘
    assert pv.symbol_stats("005930.ks ") is not None and len(calls) == 3   # 이름을 맞춰 저장값을 씀


# ── 가격 수준 ─────────────────────────────────────────────────────────────

def test_price_levels_atr_and_nearest():
    candles = make_candles(300)
    sr = pattern_summary(candles)["support_resistance"]
    lv = pv.price_levels(candles, sr)
    df = preprocess(candles)
    want = ta.atr(df["high"], df["low"], df["close"], 14).iloc[-1]
    assert lv["atr14"] == round(float(want), 2)
    assert lv["atr_pct"] == round(float(want) / float(df["close"].iloc[-1]) * 100, 2)
    assert lv["support"] == sr["nearest_support"] and lv["resistance"] == sr["nearest_resistance"]


def test_levels_text_one_line_for_summary():
    """설명 요약에 붙일 한 줄 — 가장 가까운 지지 · 저항 · ATR 변동 폭(#161 A5) · 없는 값은 뺀다."""
    s = {"price": 240000.0, "distance_pct": -7.69}
    r = {"price": 262000.0, "distance_pct": 0.77}
    assert pv.levels_text(s, r, 18569.95, 7.14) == (
        "가장 가까운 지지 240,000(-7.7%) · 저항 262,000(+0.8%) · 하루 평균 변동 폭(ATR 14일) 18,570(7.1%)")
    assert pv.levels_text(None, r, None, None) == "저항 262,000(+0.8%)"
    # 해외 종목처럼 값이 작으면 소수 둘째 자리까지(정수로 자르면 ATR 7.03 이 7 로 보인다)
    assert pv.levels_text({"price": 335.4, "distance_pct": -1.83}, None, 7.03, 2.04) == (
        "가장 가까운 지지 335.40(-1.8%) · 하루 평균 변동 폭(ATR 14일) 7.03(2.0%)")
    lv = pv.price_levels(make_candles(300), pattern_summary(make_candles(300))["support_resistance"])
    assert lv["text"] == pv.levels_text(lv["support"], lv["resistance"], lv["atr14"], lv["atr_pct"])


# ── 다중 주기 신호 ────────────────────────────────────────────────────────

@pytest.mark.parametrize("signal,strength,text,action", [
    ("매수", "강", "매수 · 강", "강력 매수"), ("매수", "보통", "매수", "매수"),
    ("매도", "강", "매도 · 강", "강력 매도"), ("관망", None, "관망", "관망"),
])
def test_label_and_kept_action(signal, strength, text, action):
    """화면 낱말은 강할 때만 「매수 · 강」(보통은 「매수」 그대로) · 자동매매가 읽는 `action` 은 옛 낱말 그대로(#161 A7 · #153)."""
    assert pv.label(signal, strength) == text and pv._action(signal, strength) == action


def test_from_record_same_numbers_and_explanation():
    """T2 한 줄 → 화면 칸(신뢰도 · 방향 일치도는 T2 와 같은 0 ~ 1 · 설계서 <표 13>) · 설명 = `/api/explain` 과 같은 함수."""
    b = _bars(seed=11)
    day = b.daily[-1]["trade_date"]
    snap = ms.signal_at(b, day)
    r = pv.from_record(snap)
    assert r["source"] == "record" and r["as_of"] == day and r["signal"] == snap["signal"]
    assert r["confidence"] == round(snap["confidence"], 4) and 0 <= r["confidence"] <= 1
    assert r["agreement"] == round(snap["agreement"], 4) and r["composite"] == round(snap["composite"], 2)
    assert r["explanation"] == se.explain(snap)
    assert [t["label"] for t in r["timeframes"]] == [t["label"] for t in snap["timeframes"]]


def test_from_live_combines_like_record():
    """그 자리 계산도 기록과 같은 식(`mtf_signals.combine`) · 같은 설명 · 주봉 이름은 1w."""
    b = _bars(seed=12)
    daily = ms._candles(b.daily[-250:])
    live = {"timeframes": [
        {"label": "분봉(60분)", "interval": "60m", "range": "1mo", "weight": 0.2, "error": "시세 없음"},
        {"label": "일봉", "interval": "1d", "range": "1y", "weight": 0.5, **timeframe_score(daily)},
        {"label": "주봉", "interval": "1wk", "range": "5y", "weight": 0.3, **timeframe_score(daily)},
    ], "pattern": pattern_summary(daily)}
    r = pv.from_live("005930.KS", live)
    want = ms.combine([dict(t) for t in live["timeframes"]])
    assert r["source"] == "live" and r["signal"] == want["signal"] and r["strength"] == want["strength"]
    assert r["confidence"] == round(want["confidence"], 4)
    assert r["explanation"]["symbol"] == "005930" and r["explanation"]["summary"]
    assert {e["timeframe"] for e in r["explanation"]["evidence"]} <= {"1d", "1w"}


def test_from_live_as_of_is_last_daily_bar_and_keeps_breakouts():
    """그 자리 계산의 기준일 = 마지막 일봉 날(오늘이 아님) · 돌파 사건도 「그날 패턴」 에 든다(기록과 같다)."""
    b = _bars(seed=14)
    daily = ms._candles(b.daily[-250:])
    pat = pattern_summary(daily)
    pat["breakouts"] = [{"key": "high_52w", "name": "52주 신고가", "direction": "bullish"}]
    live = {"timeframes": [{"label": "일봉", "interval": "1d", "range": "1y", "weight": 0.5, **timeframe_score(daily)}],
            "pattern": pat, "disclaimer": "분봉은 최근 1개월 60분봉, 주봉은 5년 데이터를 사용합니다."}
    r = pv.from_live("005930.KS", live)
    assert r["as_of"] == pat["as_of"] == b.daily[-1]["trade_date"]
    assert any("52주 신고가" in n for n in r["explanation"]["notes"])
    assert r["disclaimer"].startswith(se.DISCLAIMER) and "주봉은 5년" in r["disclaimer"]


def test_wording_has_no_forbidden_words():
    texts = [pv.LEVEL_NOTE, pv.levels_text({"price": 1, "distance_pct": -1}, {"price": 2, "distance_pct": 1}, 1.0, 1.0)]
    texts += [pv.label(s, k) for s in ("매수", "매도") for k in ("강", "보통")]
    assert not [t for t in texts if any(w in t for w in se.FORBIDDEN)]


# ── 라우트 ────────────────────────────────────────────────────────────────

def test_mtf_route_uses_record_whenever_it_exists_else_live(monkeypatch):
    """기록(T2)이 있으면 날짜와 상관없이 그 기록(`as_of` 로 날짜를 보임) · 없으면 그 자리 계산(#153 B4)."""
    b = _bars(seed=13)
    snap = ms.signal_at(b, b.daily[-1]["trade_date"])
    live_calls = []

    async def fake_live(symbol):
        live_calls.append(symbol)
        return {"timeframes": [{"label": "일봉", "interval": "1d", "weight": 0.5, "error": "시세 없음"}], "pattern": None}

    found = {"row": snap}

    async def load(db, symbol, on=None):
        return found["row"]

    monkeypatch.setattr(se, "load_snapshot", load)
    monkeypatch.setattr("app.services.patterns.multi_timeframe_signal", fake_live)
    r = asyncio.run(stocks.stock_mtf_signal(symbol="TEST01", db=None, _user=None))
    assert r["source"] == "record" and r["as_of"] == snap["as_of"].isoformat() and not live_calls
    old = dict(snap, as_of=date(2025, 1, 2))           # 오래된 기록이어도 기록을 쓴다
    found["row"] = old
    r = asyncio.run(stocks.stock_mtf_signal(symbol="TEST01", db=None, _user=None))
    assert r["source"] == "record" and r["as_of"] == "2025-01-02" and not live_calls
    found["row"] = None
    r = asyncio.run(stocks.stock_mtf_signal(symbol="TEST01", db=None, _user=None))
    assert r["source"] == "live" and live_calls == ["TEST01"] and r["label"] == "관망"


def test_mtf_route_survives_missing_t2(monkeypatch):
    """앱 DB 에 T2 가 없거나 닿지 않아도 그 자리 계산으로 돈다."""
    async def broken(db, symbol, on=None):
        raise RuntimeError("relation signal_snapshots does not exist")

    async def fake_live(symbol):
        return {"timeframes": [], "pattern": None}

    monkeypatch.setattr(se, "load_snapshot", broken)
    monkeypatch.setattr("app.services.patterns.multi_timeframe_signal", fake_live)
    r = asyncio.run(stocks.stock_mtf_signal(symbol="TEST01", db=None, _user=None))
    assert r["source"] == "live" and r["signal"] == "관망"


def test_patterns_route_survives_stats_error(monkeypatch):
    """종목 통계가 오류여도 패턴 응답은 나간다 — 그 종목 칸만 빈다."""
    async def fake_candles(symbol, period, interval):
        return {"candles": make_candles(300)}

    def boom(symbol):
        raise RuntimeError("bad data")

    monkeypatch.setattr(stocks, "get_candles", fake_candles)
    monkeypatch.setattr(pv, "_symbol_stats", boom)
    r = asyncio.run(stocks.stock_patterns(symbol="005930.KS", period="1y", _user=None))
    assert all(p["symbol"] is None for p in r["stats"]["patterns"])


def test_patterns_route_adds_stats_and_levels(monkeypatch):
    candles = make_candles(300)

    async def fake_candles(symbol, period, interval):
        return {"candles": candles}

    monkeypatch.setattr(stocks, "get_candles", fake_candles)
    monkeypatch.setattr(pv, "symbol_stats", lambda symbol: None)
    r = asyncio.run(stocks.stock_patterns(symbol="005930.KS", period="1y", _user=None))
    assert r["candles"] == candles and len(r["stats"]["patterns"]) == 11
    assert r["levels"]["atr14"] is not None and r["levels"]["as_of"] == r["as_of"]
    json.dumps(r)   # 응답이 JSON 으로 나간다


# ── 화면(robo-patterns) ───────────────────────────────────────────────────

_PUB = Path(__file__).resolve().parents[1] / "public"


def _pattern_js() -> str:
    js = (_PUB / "js" / "robo.js").read_text(encoding="utf-8")
    start = js.index("// ── 로보 어드바이저: 차트 패턴")
    return js[start:js.index("// ── 로보 어드바이저: 모의 투자 의사결정", start)]


def test_screen_loads_chart_lib_like_product_chart():
    """차트 라이브러리는 상품 상세 창(#171)과 같은 저장소 안 파일을 그릴 때만 불러온다 — 바깥 주소 · 미리 싣기 없음."""
    js = _pattern_js()
    src = re.search(r'const PT_LWC_SRC = "([^"]+)"', js).group(1)
    product = re.search(r'const LWC_SRC = "([^"]+)"', (_PUB / "js" / "productchart.js").read_text(encoding="utf-8")).group(1)
    assert src == product and (_PUB / src.lstrip("/")).is_file()
    assert not re.search(r"https?://[^\"' ]*lightweight", js, re.I)
    assert "lightweight-charts" not in (_PUB / "app.html").read_text(encoding="utf-8")


def test_screen_has_no_auto_refresh():
    """30초 자동 갱신은 받지 않았다(#153 B4) — 종가 기준 기록과 화면이 다른 날을 말하지 않게."""
    js = _pattern_js()
    assert "setInterval" not in js and "schedulePatternRefresh" not in js and "max_age_hours" not in js


def test_screen_shows_label_not_action():
    """신호 배지는 「매수 · 강」(label) · 자동매매가 읽는 action(「강력 매수」)은 화면에 쓰지 않는다(#161 A7)."""
    js = _pattern_js()
    assert "escHtml(mtf.label)" in js and "mtf.action" not in js
    assert "ptPct(mtf.confidence)" in js          # 신뢰도는 0 ~ 1 → %


def test_screen_markers_without_text_and_small_sample_note():
    """차트 표식은 화살표만(가까운 날 이름끼리 포개져서) · 이름은 마우스를 올린 날의 시세 줄에 · 이 종목 칸은 사건이 적다는 안내를 함께."""
    js = _pattern_js()
    markers = js[js.index("function patternMarkersData"):js.index("function updatePatternOverlays")]
    assert "text:" not in markers
    assert "patternNamesByTime(pat, candles)" in js and "` · 패턴: ${names.join(\" · \")}`" in js
    assert "이 종목 칸은 사건이 수십 건뿐이라" in js


def test_screen_evidence_table_with_contribution_bars():
    """신호 칸에 근거 표(주기 · 근거 · 관측값 · 규칙 · 기여도) + 기여도 막대(설계서 5.5) — 설명의 `evidence` 를 그리기만 한다.
    막대는 앱에 이미 있는 ApexCharts · 다시 분석하면 지난 막대를 지움 · 화면이 읽는 칸은 응답에 있고 기여도 합 = 종합 점수."""
    js = _pattern_js()
    table = js[js.index("function renderEvidenceTable"):js.index("function renderEvidenceChart")]
    chart = js[js.index("function renderEvidenceChart"):js.index("function renderPatternStats")]
    assert all(h in table for h in ("<th>주기</th>", "<th>근거</th>", "<th>관측값</th>", "<th>규칙</th>", "기여도</th>"))
    assert "renderEvidenceTable(ex, mtf.composite)" in js and "renderEvidenceChart(mtfResult.value.explanation)" in js
    assert "new ApexCharts(" in chart and "horizontal: true" in chart and "<script" not in chart
    assert "ptEvidenceChart?.destroy()" in js[js.index("function clearPatternResults"):]
    assert "apexcharts@3.49.2/" in (_PUB / "app.html").read_text(encoding="utf-8")
    used = set(re.findall(r"\br\.(\w+)", table + chart))
    r = pv.from_record(ms.signal_at(b := _bars(seed=11), b.daily[-1]["trade_date"]))
    rows = r["explanation"]["evidence"]
    assert rows and all(used <= set(row) for row in rows)
    assert sum(row["contribution"] for row in rows) == pytest.approx(r["explanation"]["composite"], abs=1e-4)
    assert not [w for w in se.FORBIDDEN if w in table + chart]


# ── 입력 꼴 · 판단 출처(#213 · 차트 패턴 6자리 코드) ──────────────────────────

def _market_db(tmp_path):
    import sqlite3
    path = tmp_path / "market.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE price_daily (bas_dt TEXT, srtn_cd TEXT, mrkt_ctg TEXT)")
    conn.executemany("INSERT INTO price_daily VALUES (?, ?, ?)",
                     [("20260831", "055550", "KOSPI"), ("20260831", "247540", "KOSDAQ")])
    conn.commit()
    conn.close()
    return path


def test_resolve_symbol_six_digits_lowercase_and_market(tmp_path, monkeypatch):
    """6자리 · 소문자 입력도 수집 DB 다리 · T2 · 장부가 쓰는 대문자 `.KS` · `.KQ` 로 — 시장은 수집 DB 에서."""
    path = _market_db(tmp_path)
    monkeypatch.setattr(pv.collector_db, "db_path", lambda: path)
    assert pv.resolve_symbol("055550") == "055550.KS"
    assert pv.resolve_symbol(" 247540 ") == "247540.KQ"
    assert pv.resolve_symbol("055550.ks") == "055550.KS"
    assert pv.resolve_symbol("069500") == "069500.KS"      # 주식 표에 없는 코드(ETF 등)는 코스피로
    assert pv.resolve_symbol("aapl") == "AAPL"
    monkeypatch.setattr(pv.collector_db, "db_path", lambda: None)
    assert pv.resolve_symbol("247540") == "247540.KS"      # 수집 DB 가 없으면 코스피로


def test_patterns_and_mtf_routes_resolve_input(monkeypatch):
    """패턴 · 다중 주기 라우트가 맞춘 종목으로 시세 · T2 를 읽고 그 이름을 돌려준다(6자리 → 「종목 데이터 없음」 이 아님)."""
    monkeypatch.setattr(pv.collector_db, "db_path", lambda: None)
    seen = []

    async def fake_candles(symbol, period, interval):
        seen.append(symbol)
        return {"candles": make_candles(300)}

    monkeypatch.setattr(stocks, "get_candles", fake_candles)
    monkeypatch.setattr(pv, "symbol_stats", lambda symbol: None)
    r = asyncio.run(stocks.stock_patterns(symbol="055550", period="1y", _user=None))
    assert seen == ["055550.KS"] and r["symbol"] == "055550.KS"

    loaded = []

    async def load(db, symbol, on=None):
        loaded.append(symbol)
        b = _bars(seed=13)
        return ms.signal_at(b, b.daily[-1]["trade_date"])

    monkeypatch.setattr(se, "load_snapshot", load)
    monkeypatch.setattr(stocks, "_uid", lambda raw: None)    # 로그인 없음 — 장부 조회를 건너뜀
    r = asyncio.run(stocks.stock_mtf_signal(symbol="055550.ks", db=None, user={"id": ""}))
    assert loaded == ["055550.KS"] and r["symbol"] == "055550.KS" and r["source"] == "record"


def test_screening_rows_carry_last_daily_bar_date(monkeypatch):
    """스크리닝 줄마다 기준일(마지막 일봉 날) — 화면이 「무엇으로 · 언제 시세로 냈나」 를 보인다."""
    candles = make_candles(300)

    async def fake_candles(symbol, period, interval):
        return {"candles": candles}

    async def fake_quote(symbol):
        return {"price": 1.0, "change_pct": 0.0}

    async def no_cache(key, max_age_hours=None):
        return None

    monkeypatch.setattr(stocks, "get_candles", fake_candles)
    monkeypatch.setattr(stocks, "get_quote", fake_quote)
    monkeypatch.setattr(stocks, "cache_get", no_cache)
    r = asyncio.run(stocks.stock_signals(signal="all", model="lightgbm", min_confidence=0, symbols="005930.KS"))
    assert r["signals"] and r["signals"][0]["as_of"] == pv.candle_day(candles) == preprocess(candles).index[-1].strftime("%Y-%m-%d")


def test_screens_say_how_each_judgment_is_made():
    """스크리닝 · XAI · 다중 주기 · 캔들 패턴이 「무엇으로 냈나」 를 말하고, 규칙 합산을 학습 모델 · AI 로 부르지 않는다(#213)."""
    html = (_PUB / "app.html").read_text(encoding="utf-8")
    js = (_PUB / "js" / "robo.js").read_text(encoding="utf-8")
    for old in ("LightGBM (앙상블)", "ML 파이프라인", "AI 패턴 인식", "<th>AI 신호</th>"):
        assert old not in html and old not in js, old
    assert "규칙 앙상블 (추세 · MACD · RSI)" in html and 'placeholder="005930 또는 005930.KS"' in html
    assert "SCREEN_BASIS[model]" in js and "renderScreenTable(signals, model)" in js            # 스크리닝 판단 한 줄
    assert "판단 = 학습 모델(LightGBM" in js                                                   # XAI 판단 한 줄
    pattern = _pattern_js()
    assert "규칙: 일 · 주 · 60분마다" in pattern and "캔들 모양 규칙 · 일봉 최근 5봉" in pattern   # 다중 주기 · 캔들 패턴
    assert "/api/stocks/quant/indicators?symbol=${encodeURIComponent(resolved)}&period=2y" in pattern  # 자동매매가 읽는 판단
    assert "${renderAutoRule(auto, mtf)}" in pattern and "판단이 다릅니다" in pattern          # 신호 칸에 실제로 그림
    assert "openPatternFor('${escHtml(s.symbol)}')" in js and "openPatternFor('${escHtml(r.symbol)}')" in js
    assert 'navigate("robo-patterns")' in js
