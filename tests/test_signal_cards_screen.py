"""TC-SCD — 퀀트 대시보드 「규칙 신호」 카드 (public/js/quant.js `signalCardHtml` · 할 일 ②-21 · ②-22 · 2026-10-30)

화면만 고친다 — 서버 응답 · 판정(`_generate_signal` · 일지 판 지문)은 그대로다. 서버가 이미 주는 `signal.reasons` · `as_of` · `data_note` 를 보인다.
1. 카드가 「근거 n개」 · 근거 목록 · 출처 한 줄 · 「종가」 를 보이고, 기준일이 전 거래일보다 앞이면 경고한다(전 거래일을 모르면 경고하지 않는다). (TC-SCD-01)
2. 근거 없음 · 응답 실패(null)도 깨지지 않고, 글은 HTML 로 이스케이프된다. (TC-SCD-02)
3. 제목 · 도움말 낱말이 「규칙 신호」 로 맞고 「AI 매매 시그널」 이 남지 않으며, 제목의 종목 수는 실제 그리는 수다. (TC-SCD-03)
node 가 없으면 1 · 2 는 건너뛴다(구조 시험 3 은 항상 돈다).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
QUANT = (ROOT / "public" / "js" / "quant.js").read_text(encoding="utf-8")
NODE = shutil.which("node")


def _extract(name_start: str, end_marker: str) -> str:
    i = QUANT.index(name_start)
    return QUANT[i:QUANT.index(end_marker, i)]


def _run_cards(cases: list[dict]) -> list[str]:
    """quant.js 의 카드 함수만 잘라 node 로 돌린다(`/js/common.js` 같은 브라우저 경로 import 는 쓰지 않는다)."""
    display = _extract("function _displayAction", "async function loadMarketCards")
    card = _extract("export function signalCardHtml", "async function qdCardsHtml").replace("export function", "function")
    js = textwrap.dedent("""
        const escHtml = s => String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
        const fmt = n => n == null ? "-" : Number(n).toLocaleString("en-US");
    """) + display + card + textwrap.dedent("""
        const cases = JSON.parse(process.argv[1]);
        console.log(JSON.stringify(cases.map(c => signalCardHtml(c.s, c.r, c.prev))));
    """)
    out = subprocess.run([NODE, "-e", js, json.dumps(cases, ensure_ascii=False)], capture_output=True, text=True, timeout=60, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


STOCK = {"name": "삼성전자", "symbol": "005930.KS"}


def _resp(as_of="2026-10-29", reasons=("RSI 중립 (55.0)", "단기 이평 > 중기 이평 (매수 우위)"), note="금융위원회 주식시세정보 · 2026-10-29 종가"):
    return {"signal": {"action": "매수", "reasons": list(reasons), "score": 1}, "current_price": 217000, "current_rsi": 55.04,
            "as_of": as_of, "data_note": note}


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_card_shows_reasons_note_close_and_flags_stale_data():
    """TC-SCD-01 · 근거 n개 · 근거 목록 · 출처 한 줄 · 종가 · 기준일이 전 거래일보다 앞이면 경고 · 전 거래일을 모르면 경고 안 함."""
    fresh, stale, unknown = _run_cards([
        {"s": STOCK, "r": _resp("2026-10-29"), "prev": "2026-10-29"},
        {"s": STOCK, "r": _resp("2026-10-28"), "prev": "2026-10-29"},
        {"s": STOCK, "r": _resp("2026-10-28"), "prev": ""},
    ])
    assert "근거 2개" in fresh and "RSI 중립 (55.0)" in fresh and "단기 이평 &gt; 중기 이평" in fresh and "금융위원회 주식시세정보" in fresh
    assert ">종가<" in fresh and "217,000" in fresh and "10-29 기준" in fresh and "최신 아님" not in fresh
    assert "매수" in fresh and "RSI: 55.0" in fresh
    assert 'data-hub-open="005930"' in fresh and 'data-hub-name="삼성전자"' in fresh
    assert "10-28 기준 · ⚠ 최신 아님" in stale and "var(--red)" in stale
    assert "최신 아님" not in unknown and "10-28 기준" in unknown, "전 거래일을 모르면 경고를 못 낸다(거짓 경고 금지)"


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_card_survives_missing_data_and_escapes_text():
    """TC-SCD-02 · 응답 실패(null) · 근거 없음도 깨지지 않고, 글은 이스케이프된다(`<script>` 가 그대로 안 나간다)."""
    failed, empty, evil = _run_cards([
        {"s": STOCK, "r": None, "prev": "2026-10-29"},
        {"s": STOCK, "r": {"signal": {"action": "관망", "reasons": []}, "current_price": 1000, "as_of": "2026-10-29"}, "prev": "2026-10-29"},
        {"s": {"name": "<b>x</b>", "symbol": "A&B"}, "r": _resp(reasons=("<script>alert(1)</script>",), note="<img src=x>"), "prev": "2026-10-29"},
    ])
    assert "근거 없음" in failed and "RSI: -" in failed and "기준" not in failed
    assert "근거 없음" in empty and "관망" in empty
    assert "<script>" not in evil and "&lt;script&gt;" in evil and "<img src=x>" not in evil and "&lt;b&gt;x" in evil and "A&amp;B" in evil
    assert 'data-hub-open=' not in evil


def test_labels_follow_the_decision_and_title_counts_what_it_draws():
    """TC-SCD-03 · 제목 · 도움말이 「규칙 신호」(결정 10-27 · 「AI 판단」 안 씀) · 「대표 5종목」 이 아니라 실제 그리는 수 · 서버 판정 코드는 그대로."""
    html = (ROOT / "public" / "app.html").read_text(encoding="utf-8")
    assert 'id="signal-cards-title"' in html and "규칙 신호" in html and "AI 매매 시그널" not in html and "대표 5종목" not in html.split('id="signal-cards-title"')[1][:200]
    core = (ROOT / "public" / "js" / "core.js").read_text(encoding="utf-8")
    m = re.search(r'signal:\s*\{ title: "([^"]+)"', core)
    assert m and m.group(1) == "규칙 신호"
    assert "stocks.length" in QUANT and "signal-cards-title" in QUANT, "제목의 종목 수는 실제 그리는 수"
    assert "관찰 목록 ${stocks.length}종목" in QUANT and "자동매매 대상 ${stocks.length}" not in QUANT
    assert "previous_trading_day" in QUANT, "전 거래일은 서버(/api/data/status)가 알려 준 값"
    stock = (ROOT / "app" / "services" / "stock.py").read_text(encoding="utf-8")
    assert 'return {"action": action, "color": color, "score": score, "reasons": signals}' in stock, "서버 판정 응답은 그대로(일지 판 지문)"


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_card_names_its_rule_and_drops_signal_colors():
    """TC-SCD-04 · 카드는 자기 신호를 「일봉 단독 규칙」 이라 부르고 「기록된 신호 · 근거 →」 로 모달을 연다 · 오름 빨강 · 내림 파랑 관행과
    부딪히지 않게 카드 색(초록 · 빨강 테두리)을 빼고 글자 칩만 쓴다(2026-11-03 안 A2 · A5)."""
    (card,) = _run_cards([{"s": STOCK, "r": {**_resp(), "signal": {"action": "강력 매도", "reasons": ["데드크로스 (강력 매도)"], "score": -3}}, "prev": "2026-10-29"}])
    assert "일봉 단독 규칙" in card and "기록된 신호 · 근거 →" in card and 'class="qd-chip"' in card and "매도 · 강" in card
    assert "emerald" not in card and "border-red" not in card and "bg-red" not in card and "text-slate-400" not in card


def test_dashboard_is_wired_for_cards_table_strip_and_chart_row():
    """TC-SCD-05 · 퀀트 대시보드 구조(안 A + B) — 카드는 처음 10장 + 「더 보기」(펼칠 때 나머지 요청) · 관찰 목록 표는 신호 순위 API 한 번 ·
    선택 종목 신호 띠(기록된 신호 + 일봉 단독 규칙) · 차트 줄 줄바꿈 · 고르면 차트가 다시 그려진다."""
    html = (ROOT / "public" / "app.html").read_text(encoding="utf-8")
    block = html[html.index('data-view="quant-dashboard"'):html.index('data-view="quant-auto"')]
    for needle in ('id="quant-chart-row" class="flex flex-wrap', 'id="quant-strip"', 'id="quant-watch"', 'id="signal-cards-panel"',
                   'id="signal-cards-more"', 'id="quant-find-host"', "기록된 신호(60분 · 일 · 주)", "일봉 단독 규칙"):
        assert needle in block, needle
    assert "QD_CARD_FIRST = 10" in QUANT and "slice(0, QD_CARD_FIRST)" in QUANT and "slice(QD_CARD_FIRST)" in QUANT, "카드는 처음 10장 · 나머지는 펼칠 때"
    assert 'setAttribute("aria-expanded"' in QUANT and "신호 순위에서 전체 종목 보기" in QUANT
    assert "/api/stock-hub/signal-rank?symbols=${codes.join" in QUANT, "표는 신호 순위 API 한 번"
    assert "data-qd-pick" in QUANT and "data-hub-open" in QUANT
    assert 'addEventListener("change"' in QUANT and "qdSelectSymbol" in QUANT, "종목을 고르면 차트가 다시 그려진다"
    company = (ROOT / "public" / "js" / "company.js").read_text(encoding="utf-8")
    assert 'getElementById("quant-symbol").dispatchEvent(new Event("change"))' in company
    for name in ("mountQuantHubButton", 'id = "quant-hub-open"', "export function signalCardHtml"):
        assert name in QUANT, name   # 다른 시험(TC-RKS-14 · paper_flow.js)이 읽는 이름


def _run_rows(cases: list[dict]) -> list:
    """quant.js 의 `quantRows`(와 날짜 읽기 · 겹침 정리)만 잘라 node 로 돌린다."""
    fn = _extract("function qdDay", "/** 공용 차트를 이 화면의 칸에 붙인다").replace("export function", "function")
    js = fn + "\nconst cases = JSON.parse(process.argv[1]);\nconsole.log(JSON.stringify(cases.map(c => quantRows(c))));\n"
    out = subprocess.run([NODE, "-e", js, json.dumps(cases)], capture_output=True, text=True, timeout=60, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_quant_rows_hand_the_indicator_closes_to_the_shared_chart():
    """TC-SCD-06 · 공용 차트 합치기(2026-11-03 S195) — 지표 응답의 종가는 날짜(KST) 줄로 바뀌어 해외 종목과 수집 일봉을 못 받은 국내 종목의 대신 줄이 된다.
    값이 빈 날은 빼고 · 같은 날짜가 겹치면 나중 것 하나 · 시간순 · 시가 · 고가 · 저가를 지어내지 않는다(종가 선으로 보인다). 옛 「종가가 지표와 달라 봉을 버리는」 갈래는 봉과 선이 같은 일봉에서 나와 없어졌다."""
    import datetime as dt

    def kst_midnight(y, m, d):
        return int(dt.datetime(y, m, d, tzinfo=dt.timezone(dt.timedelta(hours=9))).timestamp())
    t = [kst_midnight(2026, 10, 28), kst_midnight(2026, 10, 29), kst_midnight(2026, 10, 29) + 3600, kst_midnight(2026, 10, 30), kst_midnight(2026, 10, 31)]
    rows, empty, partial = _run_rows([
        {"times": t, "closes": [100, 101, 102, None, 104]},
        {"times": [], "closes": []},
        {"times": t[:2], "closes": [100]},
    ])
    assert [r["trade_date"] for r in rows] == ["2026-10-28", "2026-10-29", "2026-10-31"], "KIS 식 KST 자정 시각도 같은 거래일 · 값이 빈 날은 뺀다 · 겹친 날짜는 하나"
    assert [r["close"] for r in rows] == [100, 102, 104] and all(set(r) == {"time", "trade_date", "close"} for r in rows), "나중 값이 남고 시가 · 고가 · 저가는 없다"
    assert empty == [] and [r["trade_date"] for r in partial] == ["2026-10-28"]


def test_quant_chart_uses_the_shared_daily_chart_part_with_credit_and_no_apex():
    """TC-SCD-07 · 퀀트 대시보드 차트는 공용 일봉 차트 부품(`stockchart.js` — 벤더 사본 Lightweight Charts · 로고 · 크레딧 줄 유지 · 새 CDN 없음)을 쓴다 —
    칸 높이를 미리 정하고 다음 프레임에 그리며 창 크기를 따른다(그 약속은 부품에 있고, 이 화면은 크레딧 줄 · 외부 링크 · 경합 가드를 지닌다)."""
    chart_js = (ROOT / "public" / "js" / "stockchart.js").read_text(encoding="utf-8")
    assert "new ApexCharts" not in QUANT and "quantChartInstance" not in QUANT and "qdLoadLwc" not in QUANT and "QD_LWC_SRC" not in QUANT, "이 화면에 자기 차트 코드가 남지 않는다"
    assert 'import { scCode, mountDailyChart } from "/js/stockchart.js";' in QUANT
    assert 'mountDailyChart(document, document.getElementById("quant-chart-container"), view, { api })' in QUANT
    assert "attributionLogo: true" in chart_js and "lockVisibleTimeRangeOnResize: true" in chart_js and "autoSize: true" in chart_js
    assert "requestAnimationFrame" in chart_js and "CandlestickSeries" in chart_js and "HistogramSeries" in chart_js
    assert 'rel="noopener noreferrer">tradingview.com</a>' in QUANT and "TradingView Lightweight Charts™" in QUANT
    for src in (QUANT, chart_js):
        assert not re.search(r"https?://[^\"' ]*(cdn|unpkg|jsdelivr)[^\"' ]*lightweight", src, re.I)
    html = (ROOT / "public" / "app.html").read_text(encoding="utf-8")
    assert "lightweight-charts" not in html, "미리 싣지 않는다 — 차트를 그릴 때만 불러온다"
    block = html[html.index('data-view="quant-dashboard"'):html.index('data-view="quant-auto"')]
    assert 'id="quant-chart-container" class="qd-chart"' in block
    css = (ROOT / "public" / "css" / "signalrankview.css").read_text(encoding="utf-8")
    assert ".qd-chart { height: 380px" in css


def test_external_chart_link_and_labels_follow_trademark_rule():
    """TC-SCD-08 · 퀀트 대시보드 차트 줄의 「외부 차트에서 열기」(숫자 6자리 국내 코드만 · 새 탭) + 출처 줄 · 메뉴 라벨에 상표를 쓰지 않는다(NOTICE.md) · 웹훅 안내는 「기록 · 대조」(실제 주문 아님)."""
    html = (ROOT / "public" / "app.html").read_text(encoding="utf-8")
    block = html[html.index('data-view="quant-dashboard"'):html.index('data-view="quant-auto"')]
    assert 'id="quant-ext-chart"' in block and 'target="_blank" rel="noopener noreferrer"' in block and "외부 차트에서 열기 ↗" in block
    assert "외부 차트 링크는 TradingView 로 연결됩니다 · 로그인 · 지연 시세는 그쪽 정책을 따릅니다." in block
    assert "hubExtChartUrl(symbol)" in QUANT and "qdChartLink(symbol)" in QUANT
    core = (ROOT / "public" / "js" / "core.js").read_text(encoding="utf-8")
    assert 'key: "indicator-tradingview"' in core, "화면 키는 바꾸지 않는다"
    m = re.search(r'key: "indicator-tradingview"[^}]*label: "([^"]+)"', core)
    assert m and "TradingView" not in m.group(1) and "외부 차트 알림 연동" in m.group(1)
    howto = re.search(r'"indicator-tradingview": \{ summary: "([^"]+)"', core)
    assert howto and "실제 주문을 내는 기능이 아닙니다" in howto.group(1) and "장부에 기록" in howto.group(1)


# ── 동작 시험(2026-11-03 검수 반영) — 위의 구조 시험은 글자만 보므로, 순수 함수와 경합은 node 로 실제로 돌려 본다 ─────────────────────────


def _node(js: str):
    """JS 를 표준입력으로 넘겨 돌리고 마지막 줄 JSON 을 돌려준다(긴 소스도 명령줄 길이 한도에 안 걸린다)."""
    out = subprocess.run([NODE, "-"], input=js, capture_output=True, text=True, timeout=60, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def _epoch(y, m, d, hh=0, mm=0, tz="utc"):
    from datetime import datetime, timedelta, timezone
    zone = timezone.utc if tz == "utc" else timezone(timedelta(hours=9))
    return int(datetime(y, m, d, hh, mm, tzinfo=zone).timestamp())


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_day_reads_every_source_as_the_same_kst_trading_day():
    """TC-SCD-09 · qdDay — 수집 DB(00:00 UTC) · KIS(`_ts_of` 00:00 KST = 전날 15:00 UTC) · 야후 미국(14:30 UTC)이 모두 같은 거래일 글이 된다(UTC 로 읽으면 KIS 가 하루 앞선다).
    같은 날짜가 겹치면 나중 값만 남고 시간순이다(가격 축 글은 공용 부품 `scPrice` 의 몫 — tests/test_stockchart.py)."""
    fn = _extract("function qdDay", "export function quantRows").replace("export function", "function")
    days = [_epoch(2026, 10, 30), _epoch(2026, 10, 30, tz="kst"), _epoch(2026, 10, 30, 14, 30), _epoch(2026, 10, 30, 9, 0, tz="kst")]
    js = fn + """
    const t = JSON.parse(process.argv[1]);
    console.log(JSON.stringify({
      days: t.map(qdDay),
      prev: qdDay(t[1] - 1),
      dedupe: qdDedupe([{ time: "2026-10-30", v: 1 }, { time: "2026-10-28", v: 2 }, { time: "2026-10-30", v: 3 }]),
    }));
    """
    out = subprocess.run([NODE, "-e", js, json.dumps(days)], capture_output=True, text=True, timeout=60, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert got["days"] == ["2026-10-30"] * 4, "수집 DB · KIS · 야후 미국 · 장 시작이 모두 같은 거래일"
    assert got["prev"] == "2026-10-29", "KST 자정 1초 전은 전 거래일"
    assert got["dedupe"] == [{"time": "2026-10-28", "v": 2}, {"time": "2026-10-30", "v": 3}], "겹친 날짜는 나중 값 · 시간순"


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_watch_table_escapes_text_and_skips_request_without_codes():
    """TC-SCD-11 · 표 HTML 은 종목명 · 서버 문구 · 속성을 이스케이프한다(스크립트가 그대로 안 나간다) · 읽을 국내 코드가 없으면 신호 순위 요청을 보내지 않는다."""
    table = _extract("const qdCodeOf", "function qdMarkSelected")
    run = _extract("async function qdWatchRun", "// ── 선택 종목 신호 띠")
    # qdWatchRun 은 모듈 전역(qdWatchList · qdWatchSeq …)을 쓰므로, 한 범위에 같은 이름으로 놓고 돌린다
    js2 = textwrap.dedent("""
        const escHtml = s => String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
        const renderFreshness = () => "";
        const rowView = (r, nameOf) => ({ name: nameOf(r.symbol) || "", signal: r.signal, strength: "", noIntraday: false, countsText: "근거", countsNote: "", asOf: "10-30" });
        const els = {};
        const elOf = id => els[id] || (els[id] = { textContent: "", innerHTML: "" });
        globalThis.document = { getElementById: elOf };
        const calls = [];
        const api = async url => { calls.push(url); return { rows: [], missing: [] }; };
        const drawerFailText = e => "실패 " + e.message;
        const qdMarkSelected = () => {};
        let qdWatchLast = null;
        const qdWatchRepaint = () => {};
        let stocks = [{ symbol: "AAPL" }];
        const qdWatchList = async () => ({ stocks });
        const qdRankByCode = new Map();
        let qdWatchSeq = 0;
    """) + table + run + textwrap.dedent("""
        (async () => {
          const evil = '"><img src=x onerror=alert(1)>';
          const html = qdWatchHtml(
            { rows: [{ symbol: "005930", signal: "<script>1</script>" }], missing: [{ symbol: "000660", message: "<b>없음</b>" }], notice: "<i>안내</i>" },
            [{ symbol: "005930.KS", name: evil }, { symbol: "000660.KS", name: "SK하이닉스" }]);
          await qdWatchRun();
          const noCodes = { calls: calls.length, text: elOf("quant-watch").textContent };
          stocks = [{ symbol: "005930.KS" }, { symbol: "AAPL" }];
          await qdWatchRun();
          console.log(JSON.stringify({ html, noCodes, calls }));
        })();
    """)
    got = _node(js2)
    html = got["html"]
    assert "<script>" not in html and "<img" not in html and "<b>없음" not in html and "<i>안내" not in html
    assert "&lt;script&gt;" in html and "&lt;img src=x" in html and "&quot;&gt;" in html and "&lt;b&gt;없음" in html
    assert got["noCodes"]["calls"] == 0 and "국내 종목" in got["noCodes"]["text"], "코드가 없으면 요청하지 않고 까닭을 보인다"
    assert got["calls"] == ["/api/stock-hub/signal-rank?symbols=005930"], "국내 코드만 한 번에"


_WATCH_HARNESS = """
const escHtml = s => String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
const renderFreshness = () => "";
const rowView = (r, nameOf) => ({ name: (nameOf && nameOf(r.symbol)) || r.symbol, signal: r.signal, strength: "", noIntraday: false, countsText: "근거", countsNote: "", asOf: "11-03" });
const els = {};
const elOf = id => els[id] || (els[id] = { textContent: "", innerHTML: "", dataset: {} });
globalThis.document = { getElementById: elOf, querySelectorAll: () => [] };
const qdMarkSelected = () => {};
const loads = [];
let loadWatchTable = async () => { loads.push(1); };
const SAMPLE = { resp: { rows: [{ symbol: "000001", signal: "매수 쪽" }, { symbol: "000002", signal: "관망" }, { symbol: "000003", signal: "매도 쪽" }, { symbol: "000004", signal: "매수" }],
                         missing: [{ symbol: "000005", message: "기록 없음" }], notice: "n" },
                 stocks: [1, 2, 3, 4, 5].map(i => ({ symbol: "00000" + i + ".KS", name: "종목" + i })) };
"""


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_watch_table_signal_filter_and_refresh_button():
    """TC-SCD-20 · 관찰 목록 표(퀀트 대시보드 「기록된 신호」)에 신호 필터(전체 · 매수 · 매도 · 관망)와 새로고침 단추가 보인다(2026-11-05 사용자 스크린샷 —
    필터 · 새로고침이 카드 패널에만 있고 이 표에는 없었다) · 신호를 고르면 이미 받은 응답을 브라우저에서 걸러 맞는 줄만 보이고 개수 글이 바뀐다 ·
    걸 때는 「기록 없음」 줄이 안 보인다 · 맞는 게 없으면 한 줄 안내 · 모르는 낱말은 무시 · 풀면 모두 돌아온다."""
    table = _extract("const qdCodeOf", "function qdMarkSelected")
    bucket = _extract("function qdBucket", "/** 관찰 목록 종목의 시장")
    helpers = _extract("let qdWatchSignal", "let qdWatchBusy")
    js = _WATCH_HARNESS + bucket + table + helpers + textwrap.dedent("""
        (async () => {
          qdWatchLast = SAMPLE;
          const out = {};
          qdWatchRepaint();
          const all = elOf("quant-watch").innerHTML;
          out.all = { rows: (all.match(/data-qd-pick=/g) || []).length, chips: (all.match(/data-qd-wfilter/g) || []).length, refresh: all.includes("data-qd-wrefresh"), count: elOf("quant-watch-count").textContent };
          qdWatchSetSignal("매수");
          const buy = elOf("quant-watch").innerHTML;
          out.buy = { rows: (buy.match(/data-qd-pick=/g) || []).length, missing: buy.includes("기록 없음"), count: elOf("quant-watch-count").textContent, note: buy.includes("조건 매수 — 기록된 4종목 중 2종목"), pressed: buy.includes('data-value="매수" aria-pressed="true"') };
          qdWatchSetSignal("관망");
          out.watch = (elOf("quant-watch").innerHTML.match(/data-qd-pick=/g) || []).length;
          qdWatchLast = { resp: { rows: [{ symbol: "000001", signal: "매수 쪽" }], missing: [] }, stocks: SAMPLE.stocks };
          qdWatchSetSignal("매도");
          out.none = elOf("quant-watch").innerHTML.includes("이 조건에 맞는 종목이 없습니다");
          qdWatchSetSignal("BUY"); out.bad = qdWatchSignal;
          qdWatchSetSignal(""); out.reset = (elOf("quant-watch").innerHTML.match(/data-qd-pick=/g) || []).length;
          console.log(JSON.stringify(out));
        })();
    """)
    got = _node(js)
    assert got["all"] == {"rows": 5, "chips": 4, "refresh": True, "count": "5종목 중 4종목 기록"}, got
    assert got["buy"] == {"rows": 2, "missing": False, "count": "5종목 중 2종목 일치", "note": True, "pressed": True}, got
    assert got["watch"] == 1 and got["none"] and got["bad"] == "매도" and got["reset"] == 1, got


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_watch_table_refresh_rereads_keeps_filter_and_says_so():
    """TC-SCD-21 · 새로고침 — 서버에서 기록을 다시 읽고(loadWatchTable 한 번) 걸어 둔 신호 필터는 그대로이며 「다시 읽었습니다 · 새로 계산하지 않습니다」 를 알린다 ·
    다시 읽기가 실패해 표가 없으면 안내를 붙이지 않는다."""
    table = _extract("const qdCodeOf", "function qdMarkSelected")
    bucket = _extract("function qdBucket", "/** 관찰 목록 종목의 시장")
    helpers = _extract("let qdWatchSignal", "let qdWatchBusy")
    js = _WATCH_HARNESS + bucket + table + helpers + textwrap.dedent("""
        (async () => {
          qdWatchLast = SAMPLE; qdWatchSetSignal("매수");
          loadWatchTable = async () => { loads.push(1); qdWatchLast = SAMPLE; };
          await qdWatchRefresh();
          const html = elOf("quant-watch").innerHTML;
          const ok = { loads: loads.length, filter: qdWatchSignal, note: html.includes("기록을 다시 읽었습니다") && html.includes("새로 계산하지 않고"), rows: (html.match(/data-qd-pick=/g) || []).length };
          qdWatchLast = null; qdWatchNote = "";
          loadWatchTable = async () => { loads.push(1); };
          await qdWatchRefresh();
          console.log(JSON.stringify({ ok, failedNote: qdWatchNote }));
        })();
    """)
    got = _node(js)
    assert got["ok"] == {"loads": 1, "filter": "매수", "note": True, "rows": 2}, got
    assert got["failedNote"] == "", "다시 읽기가 실패했으면 안내를 붙이지 않는다"


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_more_bar_keeps_the_same_button_so_keyboard_focus_survives():
    """TC-SCD-12 · qdMoreBar — 토글해도 단추 요소가 그대로이고(초점 유지) 글 · aria-expanded 만 바뀐다 · 나머지가 없으면 단추만 빠지고 순위 링크는 하나."""
    fn = _extract("function qdMoreBar", "async function qdToggleCards")
    js = textwrap.dedent("""
        const QD_CARD_FIRST = 10;
        let qdStocks = Array.from({ length: 15 }, (_, i) => ({ symbol: String(i) }));
        let qdCardFilter = { signal: "", market: "" }, qdCardsDrawn = 10;
        const mk = tag => ({ tag, id: "", type: "", className: "", attrs: {}, children: [], parent: null, textContent: "",
          setAttribute(k, v) { this.attrs[k] = String(v); }, getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
          removeAttribute(k) { delete this.attrs[k]; },
          prepend(c) { c.parent = this; this.children.unshift(c); }, append(c) { c.parent = this; this.children.push(c); },
          remove() { if (this.parent) this.parent.children = this.parent.children.filter(x => x !== this); this.parent = null; } });
        const root = mk("body"), host = mk("div"); host.id = "signal-cards-more"; host.parent = root; root.children = [host];
        const find = (n, id) => (n.id === id ? n : n.children.map(c => find(c, id)).find(Boolean) || null);
        globalThis.document = { getElementById: id => find(root, id), createElement: mk };
    """) + fn + textwrap.dedent("""
        qdMoreBar(false);
        const first = find(root, "signal-cards-toggle");
        const a = { text: first.textContent, exp: first.getAttribute("aria-expanded") };
        first.setAttribute("aria-disabled", "true");
        qdMoreBar(true);
        const second = find(root, "signal-cards-toggle");
        const b = { same: first === second, text: second.textContent, exp: second.getAttribute("aria-expanded"), disabled: second.getAttribute("aria-disabled") };
        qdStocks = qdStocks.slice(0, 5);
        qdMoreBar(false);
        console.log(JSON.stringify({ a, b, btnGone: find(root, "signal-cards-toggle") === null, kids: host.children.map(c => c.id) }));
    """)
    got = _node(js)
    assert got["a"] == {"text": "나머지 5종목 보기", "exp": "false"}
    assert got["b"] == {"same": True, "text": "나머지 접기", "exp": "true", "disabled": None}, "같은 단추 · 받는 중 표시는 풀린다"
    assert got["btnGone"] and got["kids"] == ["signal-cards-rank"], "나머지가 없으면 단추만 빠지고 링크는 하나"


_CHART_HARNESS = r"""
const T = (y, m, d, extra = 0) => Date.UTC(y, m - 1, d) / 1000 - 9 * 3600 + extra;      // KIS 식 — 그날 00:00 KST
const mk = tag => ({                                                                      // textContent 를 쓰면 innerHTML 이 비는 실제 DOM 동작을 흉내 낸다
  tag, id: "", value: "", _t: "", _h: "", hidden: false, attrs: {}, style: {}, className: "", children: [], parentNode: null,
  setAttribute(k, v) { this.attrs[k] = v; }, getAttribute(k) { return this.attrs[k] ?? null; },
  insertBefore(c, ref) { c.parentNode = this; this.children.splice(this.children.indexOf(ref), 0, c); return c; },
  get textContent() { return this._t; }, set textContent(v) { this._t = String(v); this._h = ""; },
  get innerHTML() { return this._h; }, set innerHTML(v) { this._h = String(v); this._t = ""; },
});
const els = {}, wrap = mk("div");
const elOf = id => els[id] || wrap.children.find(c => c.id === id) || (els[id] = Object.assign(mk("div"), { id }));
for (const id of ["quant-chart-container", "quant-chart-note"]) { const e = elOf(id); e.parentNode = wrap; wrap.children.push(e); }
globalThis.document = { documentElement: {}, getElementById: elOf, createElement: mk };
const escHtml = s => String(s ?? "");
const qdStrip = { symbol: "" }, qdStripPaint = () => {}, qdMarkSelected = () => {}, qdStripLoad = () => {};
const scCode = s => (/^\d{6}\./.test(s) ? s.slice(0, 6) : "");
const hubExtChartUrl = s => (scCode(s) ? "https://example.invalid/" + scCode(s) : "");
const sleep = ms => new Promise(r => setTimeout(r, ms));
// 공용 차트 부품의 가짜 — 어떤 인자로 그리라고 했는지 · 걷었는지만 본다
const mount = { made: 0, calls: [], destroys: 0, results: {}, gates: {}, throwFor: "" };
const mountDailyChart = (doc, box, note, opts) => {
  mount.made += 1; mount.box = box; mount.note = note; mount.opts = opts;
  return {
    async draw(o) {
      mount.calls.push({ symbol: o.symbol, period: o.period, rows: o.rows ? o.rows.map(r => r.trade_date) : null });
      if (mount.gates[o.symbol]) await mount.gates[o.symbol];
      if (mount.throwFor === o.symbol) throw new Error("그리기 실패");
      const r = mount.results[o.symbol];
      return Array.isArray(r) ? r[mount.calls.filter(c => c.symbol === o.symbol).length - 1] : (r ?? true);
    },
    destroy() { mount.destroys += 1; },
  };
};
const delays = {}, replies = {};
const indFor = (sym, times) => ({ symbol: sym, times, closes: times.map((_, i) => i + 1), data_note: "note-" + sym });
const api = async url => {
  const sym = decodeURIComponent(/symbol=([^&]+)/.exec(url)[1]);
  await sleep(delays[sym] || 0);
  return replies[sym] || indFor(sym, [T(2026, 10, 28), T(2026, 10, 29), T(2026, 10, 30)]);
};
const pick = sym => { elOf("quant-symbol").value = sym; return loadQuantChart(); };
const snap = () => ({ made: mount.made, calls: mount.calls.map(c => c.symbol), destroys: mount.destroys, text: elOf("quant-chart-container").textContent, credit: elOf("quant-chart-note").innerHTML + elOf("quant-chart-note").textContent });
const reset = () => { Object.assign(mount, { calls: [], destroys: 0, throwFor: "", results: {}, gates: {} }); elOf("quant-chart-note").textContent = ""; };
"""


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_chart_ignores_late_responses_cleans_up_and_hands_the_right_rows():
    """TC-SCD-13 · loadQuantChart 실동작(공용 부품은 가짜) — ① 먼저 보낸 느린 응답이 나중에 와도 마지막 요청만 그리게 한다 ② 그리는 사이 다른 종목이 오면 먼저 것의 크레딧 줄을 쓰지 않는다
    ③ 부품이 던지면 차트를 걷고 오류 글을 보인다 ④ 오류 응답이면 이전 차트를 걷고 크레딧 줄을 비운다 ⑤ 국내 코드는 줄을 넘기지 않고(부품이 수집 일봉을 받는다), 해외 종목은 지표 응답의 종가 줄(KST 날짜)을 넘긴다
    ⑥ 국내인데 부품이 못 그리면 지표 응답의 줄로 한 번 더 그린다 ⑦ 부품은 한 번만 만들고 크레딧 줄 앞에 풀이 글 줄을 끼운다."""
    fn = _extract("let qdChartSeq", 'document.getElementById("quant-chart-load").addEventListener("click"').replace("export function", "function")
    js = _CHART_HARNESS + fn + textwrap.dedent("""
        (async () => {
          const out = {};
          // ① 느린 응답이 나중에 도착
          delays["005930.KS"] = 40; delays["000660.KS"] = 1;
          await Promise.all([pick("005930.KS"), pick("000660.KS")]); await sleep(60);
          out.late = snap(); out.hostMade = mount.made;
          out.viewFirst = wrap.children.map(c => c.id);
          // ② 그리는 사이 다른 종목
          reset(); delays["005930.KS"] = 0; delays["000660.KS"] = 0;
          let release; mount.gates["005930.KS"] = new Promise(r => { release = r; });
          const p1 = pick("005930.KS"); await sleep(10);
          const p2 = pick("000660.KS"); await sleep(10);
          release(); await Promise.all([p1, p2]);
          out.mid = snap();
          // ③ 부품이 던진다
          reset(); mount.throwFor = "005930.KS";
          await pick("005930.KS"); out.throws = snap();
          // ④ 오류 응답
          reset(); replies["000660.KS"] = { symbol: "000660.KS", error: "데이터 부족" };
          await pick("005930.KS"); await pick("000660.KS"); out.error = snap(); delete replies["000660.KS"];
          // ⑤ 넘기는 줄
          reset(); replies.AAPL = indFor("AAPL", [T(2026, 10, 28), T(2026, 10, 29), T(2026, 10, 29, 3600), T(2026, 10, 30)]);
          await pick("005930.KS"); await pick("AAPL");
          out.args = mount.calls;
          // ⑥ 국내인데 못 그림 -> 대신 줄
          reset(); mount.results["000660.KS"] = [false, true];
          await pick("000660.KS"); out.fallback = { calls: mount.calls, credit: snap().credit };
          console.log(JSON.stringify(out));
        })();
    """)
    got = _node(js)
    assert got["late"]["calls"] == ["000660.KS"] and got["late"]["credit"].startswith("note-000660.KS"), "늦은 응답은 그리게 하지 않는다"
    assert got["hostMade"] == 1 and got["viewFirst"].index("quant-chart-view-note") < got["viewFirst"].index("quant-chart-note"), "부품은 한 번만 만들고 풀이 글 줄은 크레딧 줄 앞에"
    assert got["mid"]["calls"] == ["005930.KS", "000660.KS"] and got["mid"]["credit"].startswith("note-000660.KS") and "note-005930" not in got["mid"]["credit"], "그리는 사이 바뀌면 먼저 것의 크레딧 줄은 쓰지 않는다"
    assert got["throws"]["text"].startswith("차트 오류") and got["throws"]["destroys"] >= 2, "부품이 던져도 차트를 걷고 오류 글을 보인다"
    assert got["error"]["text"] == "데이터 부족" and got["error"]["credit"] == "" and got["error"]["destroys"] >= 3, "오류 응답이면 이전 차트를 걷고 「최근 0거래일」 안내를 붙이지 않는다"
    kr, us = got["args"]
    assert kr["rows"] is None and kr["period"] == "6m", "국내 코드는 줄을 넘기지 않는다(부품이 수집 일봉을 받는다)"
    assert us["rows"] == ["2026-10-28", "2026-10-29", "2026-10-30"], "해외 종목은 KST 날짜의 종가 줄 · 겹친 날짜는 하나 · 시간순"
    fb = got["fallback"]
    assert [c["rows"] is None for c in fb["calls"]] == [True, False] and fb["calls"][1]["rows"] == ["2026-10-28", "2026-10-29", "2026-10-30"], "국내인데 못 그리면 지표 응답의 줄로 한 번 더"


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_card_carries_signal_bucket_and_market_for_the_filter():
    """TC-SCD-14 · 카드 필터(2026-11-05) — 카드 뿌리에 신호 낱말(`data-qd-signal`: 강력 매수 · 매수 → 매수 / 강력 매도 · 매도 → 매도 / 그 밖 → 관망 /
    신호 없음 → 빈 글)과 시장(`data-qd-market`: .KS → KOSPI · .KQ → KOSDAQ · 그 밖 → 빈 글)이 달린다. 카드의 다른 글은 그대로다."""
    def resp(action):
        return {"signal": {"action": action, "reasons": [], "score": 0}, "current_price": 1, "current_rsi": 50, "as_of": "2026-10-29"}

    html = _run_cards([
        {"s": {"name": "가", "symbol": "005930.KS"}, "r": resp("강력 매수"), "prev": ""},
        {"s": {"name": "나", "symbol": "247540.KQ"}, "r": resp("매도"), "prev": ""},
        {"s": {"name": "다", "symbol": "AAPL"}, "r": resp("관망"), "prev": ""},
        {"s": {"name": "라", "symbol": "000660.KS"}, "r": None, "prev": ""},
        {"s": {"name": "마", "symbol": "035420.ks"}, "r": resp("강력 매도"), "prev": ""},
    ])
    want = [("매수", "KOSPI"), ("매도", "KOSDAQ"), ("관망", ""), ("", "KOSPI"), ("매도", "KOSPI")]
    for h, (sig, mkt) in zip(html, want):
        assert f'data-qd-signal="{sig}" data-qd-market="{mkt}"' in h, (sig, mkt, h[:200])
    assert "일봉 단독 규칙" in html[0] and "qd-chip" in html[0]          # 카드의 나머지는 그대로


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_card_filter_hides_by_signal_and_market_and_reports_counts():
    """TC-SCD-15 · qdSetCardFilter — 신호 · 시장을 겹쳐 걸면 맞는 카드만 보이고(`hidden`) 개수 글이 「n종목 중 m개 일치」 로 바뀐다 ·
    맞는 게 없으면 「이 조건에 맞는 종목이 없습니다」 한 줄 · 풀면(전체) 모두 다시 보이고 빈 줄이 사라진다 · 모르는 낱말은 무시한다."""
    fn = _extract("function qdCardsCount", "/** 「나머지 n종목 보기」") + _extract("const QD_FILTER_SIGNALS", "async function qdToggleCards")
    js = textwrap.dedent("""
        const QD_CARD_FIRST = 10;
        let qdStocks = Array.from({ length: 6 }, (_, i) => ({ symbol: String(i) }));
        let qdCardsDrawn = 6, qdFilterShown = 0;
        let qdCardFilter = { signal: "", market: "" };
        const escHtml = s => String(s ?? "");
        const qdMarketOf = () => "";
        const spec = [["매수", "KOSPI"], ["매수", "KOSDAQ"], ["매도", "KOSPI"], ["관망", "KOSDAQ"], ["매수", "KOSPI"], ["", "KOSPI"]];
        const cards = spec.map(([s, m]) => ({ hidden: false, dataset: { qdSignal: s, qdMarket: m } }));
        const state = { empty: false, note: "", count: "" };
        const grid = { querySelector: sel => (sel === "[data-qd-filter-empty]" && state.empty ? { remove() { state.empty = false; } } : null),
          querySelectorAll: () => cards, insertAdjacentHTML: (_, h) => { if (h.includes("data-qd-filter-empty")) state.empty = true; } };
        const note = { set textContent(v) { state.note = v; }, get textContent() { return state.note; } };
        const count = { set textContent(v) { state.count = v; } };
        const bar = { innerHTML: "" };
        globalThis.document = { getElementById: id => ({ "signal-cards": grid, "signal-cards-filter-note": note, "signal-cards-count": count, "signal-cards-filter": bar })[id] || null };
        const qdMoreBar = () => {}, qdCardsHtml = async () => "";
    """) + fn + textwrap.dedent("""
        const shown = () => cards.filter(c => !c.hidden).length;
        (async () => {
          const out = {};
          await qdSetCardFilter("signal", "매수");
          out.buy = { shown: shown(), count: state.count, note: state.note };
          await qdSetCardFilter("market", "KOSPI");
          out.buyKospi = { shown: shown(), count: state.count, note: state.note, bar: bar.innerHTML.includes('aria-pressed="true"') };
          await qdSetCardFilter("signal", "관망");
          out.none = { shown: shown(), empty: state.empty, count: state.count };
          await qdSetCardFilter("signal", "");
          await qdSetCardFilter("market", "");
          out.reset = { shown: shown(), empty: state.empty, count: state.count, note: state.note };
          await qdSetCardFilter("signal", "BUY"); await qdSetCardFilter("market", "코스피"); await qdSetCardFilter("color", "x");
          out.bad = { shown: shown(), signal: qdCardFilter.signal, market: qdCardFilter.market };
          console.log(JSON.stringify(out));
        })();
    """)
    got = _node(js)
    assert got["buy"]["shown"] == 3 and got["buy"]["count"] == "6종목 중 3개 일치" and got["buy"]["note"].startswith("조건 매수 — 관찰 목록 6종목 중 3개")
    assert got["buyKospi"]["shown"] == 2 and got["buyKospi"]["count"] == "6종목 중 2개 일치" and got["buyKospi"]["bar"]
    assert got["none"] == {"shown": 0, "empty": True, "count": "6종목 중 0개 일치"}
    assert got["reset"] == {"shown": 6, "empty": False, "count": "6종목 중 6개 표시", "note": ""}
    assert got["bad"] == {"shown": 6, "signal": "", "market": ""}


def test_card_filter_is_wired_without_touching_app_html():
    """TC-SCD-16 · 필터 줄은 quant.js 가 카드 칸 앞에 한 번 만든다(app.html 은 그대로) · 카드를 받을 때마다 중복으로 만들지 않는다 ·
    필터가 걸려 있으면 카드를 새로 받은 뒤에도 다시 건다."""
    html = (ROOT / "public" / "app.html").read_text(encoding="utf-8")
    assert "signal-cards-filter" not in html and "qd-fchip" not in html
    assert 'document.getElementById("signal-cards-filter")) return' in QUANT          # 한 번만 만든다
    assert "qdMountCardFilter();" in QUANT and "await qdLoadExtraCards(); } catch { /* 위와 같다 */ } qdApplyCardFilter();" in QUANT


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_card_filter_loads_the_rest_once_and_unfolds_them():
    """TC-SCD-17 · 필터를 거는 순간 11번째부터의 카드를 한 번만 받아 붙이고(두 번째 필터 변경은 다시 받지 않는다) 접어 둔 나머지도 펼친 채로 거른다 ·
    받기에 실패해도 필터는 걸리고 「처음 10종목만 거른 결과」 라고 말한다."""
    fn = _extract("function qdCardsCount", "/** 「나머지 n종목 보기」") + _extract("const QD_FILTER_SIGNALS", "async function qdToggleCards")
    js = textwrap.dedent("""
        const QD_CARD_FIRST = 2;
        let qdStocks = Array.from({ length: 5 }, (_, i) => ({ symbol: String(i) }));
        let qdCardsDrawn = 2, qdFilterShown = 0;
        let qdCardFilter = { signal: "", market: "" };
        const escHtml = s => String(s ?? "");
        const qdMarketOf = () => "";
        const mkCard = (s, m) => ({ hidden: false, dataset: { qdSignal: s, qdMarket: m } });
        const first = [mkCard("매수", "KOSPI"), mkCard("매도", "KOSPI")];
        const rest = [mkCard("매수", "KOSDAQ"), mkCard("매수", "KOSPI"), mkCard("관망", "KOSPI")];
        const state = { extra: null, fetches: 0, moreBar: [], note: "", fail: false };
        const grid = {
          querySelector: sel => (sel === "[data-qd-extra]" ? state.extra : null),
          querySelectorAll: () => (state.extra ? first.concat(rest) : first),
          appendChild: el => { state.extra = el; }, insertAdjacentHTML: () => {},
        };
        const note = { set textContent(v) { state.note = v; } };
        globalThis.document = {
          getElementById: id => ({ "signal-cards": grid, "signal-cards-filter-note": note, "signal-cards-count": { set textContent(v) {} }, "signal-cards-toggle": null, "signal-cards-filter": { innerHTML: "" } })[id] || null,
          createElement: () => ({ attrs: {}, style: {}, hidden: true, setAttribute(k, v) { this.attrs[k] = v; }, set innerHTML(v) { this._h = v; } }),
        };
        const qdMoreBar = ok => state.moreBar.push(ok);
        const qdCardsHtml = async () => { state.fetches += 1; if (state.fail) throw new Error("x"); return ""; };
    """) + fn + textwrap.dedent("""
        (async () => {
          const out = {};
          await qdSetCardFilter("signal", "매수");
          out.a = { fetches: state.fetches, drawn: qdCardsDrawn, shown: qdFilterShown, extraOpen: state.extra && state.extra.hidden === false && state.extra.style.display === "contents", moreBar: state.moreBar.slice() };
          await qdSetCardFilter("market", "KOSPI");
          out.b = { fetches: state.fetches, shown: qdFilterShown, note: state.note };
          // 받기 실패 — 새 상태에서
          state.extra = null; state.fetches = 0; state.fail = true; qdCardsDrawn = 2; qdCardFilter = { signal: "", market: "" };
          let err = "";
          try { await qdSetCardFilter("signal", "매수"); } catch (e) { err = String(e.message); }
          out.c = { err, shown: qdFilterShown, note: state.note };
          console.log(JSON.stringify(out));
        })();
    """)
    got = _node(js)
    assert got["a"]["fetches"] == 1 and got["a"]["drawn"] == 5 and got["a"]["shown"] == 3 and got["a"]["extraOpen"]
    assert got["b"] == {"fetches": 1, "shown": 2, "note": "조건 매수 · KOSPI — 관찰 목록 5종목 중 2개"}
    assert got["c"]["err"] == "" and got["c"]["shown"] == 1 and "나머지 종목을 받지 못해 처음 2종목만" in got["c"]["note"], got["c"]


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_more_bar_hides_fold_button_while_filter_is_on():
    """TC-SCD-18 · 필터를 건 동안은 「나머지 접기」 단추를 숨긴다(접으면 「n개 일치」 글과 보이는 카드가 어긋난다 · 신장환 님 #556 확인 11-05) ·
    필터를 풀면 되살아나고 · 나머지를 못 받은 채(일부만 그림)라면 다시 받을 수 있게 숨기지 않는다."""
    fn = _extract("function qdMoreBar", "async function qdToggleCards")
    js = textwrap.dedent("""
        const QD_CARD_FIRST = 10;
        let qdStocks = Array.from({ length: 15 }, (_, i) => ({ symbol: String(i) }));
        let qdCardFilter = { signal: "", market: "" }, qdCardsDrawn = 10;
        const mk = tag => ({ tag, id: "", type: "", className: "", attrs: {}, children: [], parent: null, textContent: "", hidden: false,
          setAttribute(k, v) { this.attrs[k] = String(v); }, getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
          removeAttribute(k) { delete this.attrs[k]; },
          prepend(c) { c.parent = this; this.children.unshift(c); }, append(c) { c.parent = this; this.children.push(c); },
          remove() { if (this.parent) this.parent.children = this.parent.children.filter(x => x !== this); this.parent = null; } });
        const root = mk("body"), host = mk("div"); host.id = "signal-cards-more"; host.parent = root; root.children = [host];
        const find = (n, id) => (n.id === id ? n : n.children.map(c => find(c, id)).find(Boolean) || null);
        globalThis.document = { getElementById: id => find(root, id), createElement: mk };
    """) + fn + textwrap.dedent("""
        const out = {};
        qdMoreBar(false); out.off = find(root, "signal-cards-toggle").hidden;                                  // 필터 없음 → 보인다
        qdCardFilter = { signal: "매수", market: "" }; qdCardsDrawn = 15; qdMoreBar(true); out.on = find(root, "signal-cards-toggle").hidden;   // 필터 + 전부 그림 → 숨김
        qdCardsDrawn = 10; qdMoreBar(false); out.partial = find(root, "signal-cards-toggle").hidden;           // 필터 + 일부만 → 다시 받게 보임
        qdCardFilter = { signal: "", market: "" }; qdCardsDrawn = 15; qdMoreBar(true); out.cleared = find(root, "signal-cards-toggle").hidden;   // 풀면 되살아남
        console.log(JSON.stringify(out));
    """)
    got = _node(js)
    assert got == {"off": False, "on": True, "partial": False, "cleared": False}, got


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_market_chips_only_when_the_watch_list_has_more_than_one_market():
    """TC-SCD-19 · 관찰 목록이 전부 .KS 면 항상 0개인 「KOSDAQ」 칩을 만들지 않고 시장 줄 자체를 감춘다(신장환 님 #556 확인) ·
    시장이 둘 이상이면 있는 시장만 칩으로 · 이미 걸린 시장은 목록에 없어도 줄을 남겨 풀 수 있다."""
    fn = _extract("const QD_FILTER_SIGNALS", "function qdMountCardFilter")
    js = textwrap.dedent("""
        const escHtml = s => String(s ?? "");
        const qdMarketOf = s => (String(s).endsWith(".KQ") ? "KOSDAQ" : String(s).endsWith(".KS") ? "KOSPI" : "");
        let qdStocks = [{ symbol: "005930.KS" }, { symbol: "000660.KS" }];
        let qdCardFilter = { signal: "", market: "" };
    """) + fn + textwrap.dedent("""
        const chips = h => (h.match(/data-qd-filter="market" data-value="([^"]*)"/g) || []).map(x => x.split('data-value="')[1].replace('"', ""));
        const out = {};
        out.onlyKs = { row: qdFilterBarHtml().includes("시장"), kosdaq: qdFilterBarHtml().includes("KOSDAQ") };
        qdStocks = [{ symbol: "005930.KS" }, { symbol: "247540.KQ" }];
        out.both = chips(qdFilterBarHtml());
        qdStocks = [{ symbol: "005930.KS" }]; qdCardFilter = { signal: "", market: "KOSDAQ" };
        out.stuck = chips(qdFilterBarHtml());
        console.log(JSON.stringify(out));
    """)
    got = _node(js)
    assert got["onlyKs"] == {"row": False, "kosdaq": False}, got
    assert got["both"] == ["", "KOSPI", "KOSDAQ"], got
    assert got["stuck"] == ["", "KOSPI", "KOSDAQ"], got          # 목록엔 KOSPI 만 있어도 걸린 KOSDAQ 칩은 남아 풀 수 있다
