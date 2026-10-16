"""응답 숫자의 자료 출처 · 기준일 (TC-DP · `P01-①-2` · #134 후보 A).

왜 — 지표 백테스트 응답(`GET /api/quant/pipeline`)이 어느 자료로 계산했고 마지막 봉이 언제인지 말하지 않아,
#134 검수에서 같은 종목 · 같은 날 숫자가 0.37% 갈린 까닭(외부 시세의 장중 봉으로 보임)을 확인하지 못했다.
`get_candles` 는 이미 `source` · `as_of` 를 돌려주는데 라우트가 버리고 있었다.

여기서 지키는 것 —
1. 출처 · 기준일 · 한 줄 글은 서버 한 곳(`app/services/data_provenance.py`)이 만든다 — 모르면 None(지어내지 않음).
2. 지표 백테스트 응답에 `source` · `data_from` · `data_as_of` · `data_note` 가 실린다(기본 전략 · custom 두 길 모두).
   첫 봉 날짜는 DF-15 D-1(「10년」 백테스트가 실제로는 2020-01-02 부터)을 응답이 스스로 말하게 한다.
   출처 칸 이름은 강사님 판(th06 `2852210` 의 `result["source"]`)과 같게 — 다음 기초 코드 반영 때 같은 뜻 칸이 둘이 되지 않게.
3. 전략 분석 화면(`quant-backtest` · 이동원 몫)은 마지막 봉 종가를 「현재가」 라 부르지 않고 서버 글을 그대로 보인다.
4. 화면 코드에 출처 글을 두지 않는다(SSoT).
"""
from __future__ import annotations

import asyncio
import re
from datetime import date
from pathlib import Path

from app.routes import stocks
from app.services import data_provenance as dp
from app.services import stock
from tests.conftest import make_candles

ROOT = Path(__file__).resolve().parents[1]
JS_DIR = ROOT / "public" / "js"
QUANT_JS = JS_DIR / "quant.js"      # 전략 분석 화면 — 깨 보기가 이 칸을 사본으로 바꿔 끼운다
DAY = 86_400
T_1015 = 1_792_022_400          # 2026-10-15 00:00 UTC(= 09:00 KST) — 수집 DB 봉 시각 꼴
TODAY = date(2026, 10, 16)


def _bars(last_time: int, n: int = 3) -> list[dict]:
    return [{"time": last_time - (n - 1 - i) * DAY, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}
            for i in range(n)]


# ── 1. 서버 한 곳 ───────────────────────────────────────────────────

def test_collector_source_uses_given_as_of_and_label():
    p = dp.candle_provenance({"source": "collector", "as_of": "2026-10-15", "candles": _bars(T_1015)}, today=TODAY)
    assert p == {"source": "collector", "data_from": "2026-10-13", "data_as_of": "2026-10-15",
                 "data_note": "수집 DB 일봉(수정주가) · 2026-10-13 ~ 2026-10-15 종가"}


def test_as_of_is_read_from_last_bar_when_source_gives_none():
    """증권사 · 외부 시세 길은 `as_of` 를 주지 않는다 — 마지막 봉 시각(그날 00:00 UTC)의 날짜."""
    p = dp.candle_provenance({"source": "kis", "candles": _bars(T_1015)}, today=TODAY)
    assert p["data_as_of"] == "2026-10-15"
    assert p["data_note"] == "증권사(KIS) 일봉 · 2026-10-13 ~ 2026-10-15 종가"


def test_other_source_keeps_its_name_without_guessing():
    p = dp.candle_provenance({"source": "somefeed", "candles": _bars(T_1015)}, today=TODAY)
    assert p["source"] == "somefeed"
    assert p["data_note"].startswith("외부 시세 일봉(somefeed) · 2026-10-13 ~ 2026-10-15")


def test_today_bar_from_outside_source_is_flagged_as_maybe_intraday():
    """수집 DB 가 아닌 길의 오늘 봉은 장중 값일 수 있다(#134 의 0.37% 차이) — 글로 알린다."""
    p = dp.candle_provenance({"source": "kis", "candles": _bars(T_1015 + DAY)}, today=TODAY)
    assert p["data_as_of"] == "2026-10-16"
    assert "장중 값일 수 있음" in p["data_note"] and "종가" not in p["data_note"]


def test_collector_today_is_never_flagged():
    """수집 DB 는 다음 날 낮에 받은 확정 값만 있다 — 날짜가 오늘이어도 장중 표시를 붙이지 않는다."""
    p = dp.candle_provenance({"source": "collector", "as_of": "2026-10-16", "candles": _bars(T_1015 + DAY)},
                             today=TODAY)
    assert p["data_note"] == "수집 DB 일봉(수정주가) · 2026-10-14 ~ 2026-10-16 종가"


def test_unknown_source_is_not_invented():
    p = dp.candle_provenance({"candles": _bars(T_1015)}, today=TODAY)
    assert p["source"] is None
    assert p["data_from"] == "2026-10-13" and p["data_as_of"] == "2026-10-15"
    assert p["data_note"] == "자료 출처를 알 수 없습니다 · 2026-10-13 ~ 2026-10-15"


def test_no_candles_gives_no_date():
    p = dp.candle_provenance({"source": "collector", "candles": []}, today=TODAY)
    assert p["data_from"] is None and p["data_as_of"] is None and p["data_note"] == "수집 DB 일봉(수정주가) · 봉 없음"
    assert dp.candle_provenance(None, today=TODAY) == {
        "source": None, "data_from": None, "data_as_of": None, "data_note": "자료 출처를 알 수 없습니다"}


def test_single_bar_has_no_range():
    p = dp.candle_provenance({"source": "collector", "candles": _bars(T_1015, n=1)}, today=TODAY)
    assert p["data_from"] == p["data_as_of"] == "2026-10-15"
    assert p["data_note"] == "수집 DB 일봉(수정주가) · 2026-10-15 종가"


def test_last_bar_date_reads_text_dates_too():
    assert dp.last_bar_date([{"time": "20261015"}]) == "2026-10-15"
    assert dp.last_bar_date([{"time": "2026-10-15 15:30"}]) == "2026-10-15"
    assert dp.last_bar_date([{"time": None}]) is None
    assert dp.last_bar_date([{"time": True}]) is None


# ── 2. 지표 백테스트 응답 ─────────────────────────────────────────────

def _call_pipeline(monkeypatch, strategy, candle_data):
    async def fake_candles(symbol, period, interval):
        return candle_data

    monkeypatch.setattr(stocks, "get_candles", fake_candles)
    return asyncio.run(stocks.quant_pipeline_indicator_backtest(
        symbol="005930.KS", period="10y", base="rsi_ma", short=5, mid=20, rsi=14, buy_th=35.0,
        strategy=strategy, cost_bps=None, cost_model=None, slippage_bps=None, market=None,
        stop_loss_pct=None, take_profit_pct=None, _user=None,
        # 라우트를 직접 부르면 기본값이 Query(...) 객체로 들어간다 — #221 의 새 인자 둘은 값으로 넘긴다
        entry_mode="close", exit_mode="close",
    ))


def test_pipeline_response_carries_source_and_last_bar(monkeypatch):
    candles = make_candles(400)
    data = {"symbol": "005930.KS", "candles": candles, "source": "collector", "as_of": "2026-10-15"}
    for strategy in ("rsi", "custom"):
        r = _call_pipeline(monkeypatch, strategy, data)
        assert r["source"] == "collector", strategy
        assert r["data_from"] == dp.first_bar_date(candles) == "2020-09-13", strategy   # 「10년」 이라도 첫 봉을 말한다
        assert r["data_as_of"] == "2026-10-15", strategy
        assert r["data_note"] == "수집 DB 일봉(수정주가) · 2020-09-13 ~ 2026-10-15 종가", strategy


def test_pipeline_without_source_says_unknown(monkeypatch):
    """출처 칸이 없는 옛 꼴 응답(시험 · 다른 길)도 날짜는 마지막 봉에서 · 출처는 None."""
    candles = make_candles(400)
    r = _call_pipeline(monkeypatch, "ma", {"candles": candles})
    assert r["source"] is None
    assert r["data_as_of"] == dp.last_bar_date(candles)
    assert r["data_note"].startswith("자료 출처를 알 수 없습니다")


# ── 3. 전략 분석 화면(이동원 몫) ──────────────────────────────────────

def test_indicators_response_has_server_note(monkeypatch):
    """전략 분석이 부르는 `/api/stocks/quant/indicators` 에도 서버가 만든 한 줄이 실린다."""
    async def fake_candles(symbol, period="1y", interval="1d", max_age_hours=6):
        return {"candles": make_candles(120), "source": "collector", "as_of": "2026-10-15"}

    monkeypatch.setattr(stock, "get_candles", fake_candles)
    r = asyncio.run(stock.get_quant_indicators("005930.KS", period="10y"))
    assert r["as_of"] == "2026-10-15" and r["source"] == "collector"
    assert r["data_note"] == "수집 DB 일봉(수정주가) · 2020-09-13 ~ 2026-10-15 종가"


def _bt_handler() -> str:
    js = QUANT_JS.read_text(encoding="utf-8")
    m = re.search(r'getElementById\("bt-load"\)\.addEventListener\("click".*?\n\}\);', js, flags=re.S)
    assert m, "전략 분석(bt-load) 처리기를 찾지 못했다"
    return m.group(0)


def test_strategy_screen_does_not_call_last_close_current_price():
    h = _bt_handler()
    assert "현재가" not in h, "마지막 봉 종가를 「현재가」 로 부른다"
    assert "마지막 종가" in h


def test_strategy_screen_shows_server_note_escaped():
    h = _bt_handler()
    assert re.search(r"escHtml\(data\.data_note\)", h), "서버 글(data_note)을 그대로 · 이스케이프해 보이지 않는다"


def test_strategy_screen_backtest_block_shows_server_note_escaped():
    """#224(강민석 님 · 10-16)가 같은 화면에 더한 체결 시점 백테스트 칸도 서버 출처 줄을 그대로 · 이스케이프해 보인다 —
    「10년치」 를 불러도 실제 기간(수집 DB 는 2020-01-02 부터)이 보이게."""
    js = QUANT_JS.read_text(encoding="utf-8")
    m = re.search(r'getElementById\("bt-pipeline-run"\)\.addEventListener\("click".*?\n\}\);', js, flags=re.S)
    assert m, "전략 분석의 체결 시점 백테스트(bt-pipeline-run) 처리기를 찾지 못했다"
    assert re.search(r"escHtml\(d\.data_note\)", m.group(0))


def test_screens_do_not_hardcode_source_labels():
    """출처 글은 서버 한 곳 — 화면 코드가 같은 글을 따로 적으면 두 벌이 된다."""
    hits = []
    for p in [QUANT_JS if q.name == "quant.js" else q for q in sorted(JS_DIR.glob("*.js"))]:
        text = p.read_text(encoding="utf-8")
        for label in list(dp.SOURCE_LABELS.values()) + [dp.UNKNOWN_NOTE, dp.INTRADAY_NOTE]:
            if label in text:
                hits.append(f"{p.name}: {label}")
    assert not hits, hits
