"""TC-SCH — 종목 일봉 차트 칸(public/js/stockchart.js) · 모의주문 시세 조회 차트 · 스탑가 안내 · 2026-11-02 S187

결정(Figma 「Qurious · 종목 허브」 07 쪽 안 C · 안 D · 사용자 11-02 「시세 조회했을 때 차트가 나오면 더 좋을 것 같고 스탑 칸에 삼성전자를 쳐도 되게」):
서랍 · 크게 보기 모달 · 모의주문 시세 조회가 같은 차트 부품을 쓴다. 데이터는 새로 만들지 않고 종목 허브가 쓰는 수집 일봉 한 길이다.

지키는 것 —
1. 순수 함수(DOM 없음 — Node): 6자리 코드 · 일봉 주소 · 기간 점 · 요약 글 · 스탑가 점선 문구. (TC-SCH-01)
2. 스탑 안전장치: 방향 안내 · 이미 닿은 스탑 판정이 서버 `check_stop_orders` 의 발동 조건과 같다 · 빠른 단추 값. (TC-SCH-02)
3. 연결: 모의주문 화면에 차트 칸 둘 · 스탑가 칸을 현재가로 채우지 않음 · 서랍 입구 단추 · 야후 참조를 늘리지 않음. (TC-SCH-03)
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PUB = ROOT / "public"
SC = PUB / "js" / "stockchart.js"


def _run(tmp_path: Path, body: str):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node 가 없어 화면 함수를 돌릴 수 없다")
    script = tmp_path / "sc.mjs"
    script.write_text(f'import * as sc from "{SC.resolve().as_uri()}";\nconst out = {{}};\n{body}\nprocess.stdout.write(JSON.stringify(out));\n', encoding="utf-8")
    run = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def test_chart_pure_functions(tmp_path):
    """TC-SCH-01 · 코드 · 주소 · 기간 점 · 요약 글."""
    out = _run(tmp_path, """
out.codes = ["005930", "005930.KS", "035720.kq", "0000D0", "AAPL", "삼성전자", "", null].map(sc.scCode);
out.path = [sc.scPath("005930.KS"), sc.scPath("AAPL")];
const rows = [];
for (let i = 0; i < 400; i += 1) { const d = new Date(Date.UTC(2025, 9, 1) + i * 86400000).toISOString().slice(0, 10); rows.push({ trade_date: d, close: 100 + i }); }
rows.push({ trade_date: "2026-11-06", close: null });
out.p1m = sc.scPoints(rows, "1m").length; out.p3m = sc.scPoints(rows, "3m").length; out.p1y = sc.scPoints(rows, "1y").length; out.pdef = sc.scPoints(rows).length;
out.last = sc.scPoints(rows, "1m").slice(-1)[0];
out.empty = sc.scPoints(null, "3m");
const pts = [{ time: "2026-10-29", value: 232000 }, { time: "2026-10-30", value: 221500 }];
out.sum = sc.scSummary(pts); out.sumStop = sc.scSummary(pts, 210400); out.sumNone = sc.scSummary([]);
out.periods = sc.SC_PERIODS.map(p => p[0]);
""")
    assert out["codes"] == ["005930", "005930", "035720", "0000D0", "", "", "", ""]
    assert out["path"] == ["/api/data/ohlcv?symbol=005930", ""]
    assert out["p1m"] < out["p3m"] < out["p1y"] and out["pdef"] == out["p3m"]
    assert out["last"]["value"] == 100 + 399                               # 종가가 없는 줄(null)은 뺀다
    assert out["empty"] == []
    assert "최고 232,000원 · 최저 221,500원 · 마지막 종가 221,500원(2026-10-30)" in out["sum"] and "실시간 차트가 아닙니다" in out["sum"]
    assert "스탑가" not in out["sum"] and "검은 점선은 입력한 스탑가 210,400원" in out["sumStop"]
    assert "일봉 자료가 없습니다" in out["sumNone"]
    assert out["periods"] == ["1m", "3m", "1y"]


def test_stop_direction_and_fire_now_match_the_server_rule(tmp_path):
    """TC-SCH-02 · 현재가와 견준 안내 · 등록 즉시 발동 판정(서버와 같은 조건) · 빠른 단추."""
    out = _run(tmp_path, """
out.dir = [sc.scDirection(221500, 210400), sc.scDirection(221500, 230000), sc.scDirection(221500, 221500), sc.scDirection(null, 1), sc.scDirection(221500, 0)];
const f = (s, c, p) => sc.scWouldFireNow(s, c, p);
out.fire = [f("SELL", 221500, 221500), f("SELL", 221500, 230000), f("SELL", 221500, 210400), f("BUY", 221500, 221500), f("BUY", 221500, 210400), f("BUY", 221500, 230000), f("sell", 221500, 230000), f("SELL", null, 1), f("HOLD", 1, 1)];
out.quick = sc.scQuickStops(221500); out.quickNone = [sc.scQuickStops(0), sc.scQuickStops(null)];
""")
    d = out["dir"]
    assert "5.0% 낮습니다" in d[0] and "매도 스탑(손절)" in d[0] and "서버 기준 시세보다 높아야 등록" in d[0]
    assert "3.8% 높습니다" in d[1] and "매수 스탑으로 쓰는 값" in d[1]
    assert "현재가와 같습니다" in d[2] and d[3] == "" and d[4] == ""
    assert out["fire"] == [True, True, False, True, True, False, True, False, False]   # 매도: 현재가 ≤ 스탑가 · 매수: 현재가 ≥ 스탑가
    assert [q["label"] for q in out["quick"]] == ["−3%", "−5%", "−10%"] and [q["value"] for q in out["quick"]] == [214855, 210425, 199350]
    assert out["quickNone"] == [[], []]
    # 서버 발동 조건과 같은 식이어야 한다 — 서버를 바꾸면 이 시험이 알려 준다
    server = (ROOT / "app" / "services" / "paper_trading.py").read_text(encoding="utf-8")
    assert 'order.order_type == "sell" and current <= float(order.stop_price)' in server
    assert 'order.order_type == "buy" and current >= float(order.stop_price)' in server


def test_paper_screen_has_charts_and_no_auto_filled_stop_price():
    """TC-SCH-03 · 차트 칸 둘 · 스탑가를 현재가로 채우지 않음 · 서랍 입구 · 새 서버 길 · 야후 참조 없음."""
    app = (PUB / "app.html").read_text(encoding="utf-8")
    paper = (PUB / "js" / "paper.js").read_text(encoding="utf-8")
    sc = SC.read_text(encoding="utf-8")
    for el in ("ps-chart", "ps-chart-note", "ps-chart-periods", "ps-hub-open", "ps-stop-chart", "ps-stop-chart-note", "ps-stop-hint", "ps-stop-quick"):
        assert f'id="{el}"' in app, el
    assert 'data-hub-open=""' in app                                                # 서랍 입구 — 시세 조회 뒤 코드가 채워진다
    assert "Math.round(q.price)" not in paper and '$("ps-stop-price").value = Math' not in paper   # 현재가 자동 채움 없음
    assert 'from "/js/stockchart.js"' in paper and "scWouldFireNow(side" in paper and "psStopHint()" in paper
    assert "/api/data/ohlcv" in sc and "yahoo" not in sc.lower() and "/api/stocks/" not in sc   # 수집 일봉 한 길 · 야후 참조를 늘리지 않는다(TC-YH)
    assert re.search(r'"/js/vendor/lightweight-charts/lightweight-charts-5\.2\.1\.min\.js"', sc)


# ── 2026-11-03 S195 · 공용 일봉 차트 업그레이드 — 캔들 · 거래량 · 이동평균 · 볼린저 · RSI · MACD · 신호 · 일정 표식 ─────────────────────────────


def _closes(n: int = 320) -> list[float]:
    """서버 지표와 맞대어 볼 종가 — 무작위 걸음 + 앞쪽의 계속 오르는 구간."""
    import random
    rnd = random.Random(7)
    v, out = 50000.0, []
    for _ in range(n):
        v = max(1000.0, v + rnd.gauss(0, 900))
        out.append(round(v, 2))
    for i in range(20):                      # 앞 스무 날은 계속 오른다 — 손실이 0 이라 RSI 가 100 이 되는 서버 규칙의 가장자리
        out[i] = 50000.0 + i * 10
    return out


def test_chart_indicators_match_the_server_definition(tmp_path):
    """TC-SCH-04 · 화면에서 계산한 이동평균 · 볼린저(모집단 σ) · RSI(Wilder) · MACD 가 서버 `ta_utils`(tv-2026)와 같은 종가에서 같은 값이다.
    선을 서버의 지표 길(`indicator-strategy/chart` — 상대강도 기준선 때문에 서버가 야후를 다시 부른다)이 아니라 화면에서 계산해도
    「정의 한 벌」 이 어긋나지 않는다는 근거 — 서버 정의를 바꾸면 이 시험이 알려 준다."""
    import math
    import pandas as pd
    from app.services import ta_utils
    closes = _closes()
    out = _run(tmp_path, f"""
const c = {json.dumps(closes)};
const b = sc.scBollinger(c);
const m = sc.scMacd(c);
out.sma20 = sc.scSma(c, 20); out.sma60 = sc.scSma(c, 60);
out.bbU = b.upper; out.bbM = b.mid; out.bbL = b.lower;
out.rsi = sc.scRsi(c);
out.macd = m.macd; out.sig = m.signal; out.hist = m.hist;
""")
    s = pd.Series(closes, dtype=float)
    up, mid, lo = ta_utils.bollinger(s, 20, 2.0)
    macd, sig, hist = ta_utils.macd(s)
    want = {"sma20": ta_utils.sma(s, 20), "sma60": ta_utils.sma(s, 60), "bbU": up, "bbM": mid, "bbL": lo,
            "rsi": ta_utils.rsi(s, 14), "macd": macd, "sig": sig, "hist": hist}
    for key, series in want.items():
        got = out[key]
        assert len(got) == len(series), key
        for i, (g, w) in enumerate(zip(got, series.tolist())):
            if w is None or (isinstance(w, float) and math.isnan(w)):
                assert g is None, f"{key}[{i}] 서버는 비었는데 화면은 {g}"
            else:
                assert g is not None and abs(g - w) <= 1e-6 * max(1.0, abs(w)), f"{key}[{i}] 화면 {g} ≠ 서버 {w}"
    assert 100.0 in [v for v in out["rsi"] if v is not None], "계속 오르는 구간에서 RSI 가 100 이 되는 서버 규칙(손실 0)까지 같다"


def test_chart_bars_legend_markers_and_paths(tmp_path):
    """TC-SCH-05 · 순수 함수 — 봉 정리 · 기간 시작 · 값 줄 · 신호 표식(기준일 봉에만) · 일정 표식(봉이 있는 날만) · 요청 주소(야후 길 없음)."""
    out = _run(tmp_path, """
const rows = [
  { trade_date: "2026-10-28", open: 100, high: 110, low: 95, close: 105, volume: 1000 },
  { trade_date: "2026-10-29", open: 105, high: 112, low: 100, close: 110, volume: 2000 },
  { trade_date: "2026-10-29", open: 106, high: 113, low: 101, close: 111, volume: 2500 },
  { trade_date: "2026-10-30", close: 108 },
  { trade_date: "2026-10-31", close: null },
  { close: 1 },
];
const bars = sc.scBars(rows);
out.days = bars.map(b => b.time); out.dup = bars[1].close; out.hasOhlc = sc.scHasOhlc(bars); out.hasOhlcOk = sc.scHasOhlc(bars.slice(0, 2));
out.volNull = bars[2].volume; out.empty = [sc.scBars(null), sc.scHasOhlc([])];
const long = []; for (let i = 0; i < 400; i += 1) long.push({ time: new Date(Date.UTC(2025, 9, 1) + i * 86400000).toISOString().slice(0, 10), close: i });
out.start = ["1m", "3m", "1y"].map(p => long.length - sc.scStart(long, p));
out.legend = [sc.scLegendText(bars[1], bars[0], ["실적 발표(확정)"]), sc.scLegendText(bars[2], bars[1]), sc.scLegendText(null)];
const shown = bars.slice(0, 3);
out.sig = [sc.scSignalMark({ asOf: "2026-10-29", side: "매수" }, shown), sc.scSignalMark({ asOf: "2026-10-29", side: "매도" }, shown),
  sc.scSignalMark({ asOf: "2026-10-29", side: "관망" }, shown), sc.scSignalMark({ asOf: "2026-11-02", side: "매수" }, shown), sc.scSignalMark(null, shown), sc.scSignalMark({ asOf: "x", side: "매수" }, shown)];
out.sigNote = sc.scSignalNote(out.sig[0], "2026-10-29");
out.miss = [sc.scSignalMissNote({ asOf: "2026-11-04", side: "매수" }, shown), sc.scSignalMissNote({ asOf: "2020-01-02", side: "매수" }, shown),
  sc.scSignalMissNote({ asOf: "2026-10-29", side: "매수" }, [shown[0], shown[2]]), sc.scSignalMissNote({ asOf: "x" }, shown), sc.scSignalMissNote(null, shown)];
out.fits = [sc.scSignalFits({ asOf: "2026-10-29" }, "005930"), sc.scSignalFits({ symbol: "005930", asOf: "x" }, "005930.KS"), sc.scSignalFits({ symbol: "005930" }, "000660"),
  sc.scSignalFits({ symbol: "AAPL" }, "aapl"), sc.scSignalFits({ symbol: "AAPL" }, "TSLA"), sc.scSignalFits(null, "005930")];
out.stopFit = [sc.scStopFit(95, 90, 110, 100), sc.scStopFit(85, 90, 110, 100), sc.scStopFit(130, 90, 110, 100), sc.scStopFit(131, 90, 110, 100), sc.scStopFit(60, 90, 110, 100),
  sc.scStopFit(null, 90, 110, 100), sc.scStopFit(0, 90, 110, 100), sc.scStopFit(95, NaN, 110, 100)];
out.labels = [sc.scPeriodLabel("1m"), sc.scPeriodLabel("6m"), sc.scPeriodLabel("2y"), sc.scPeriodLabel(""), sc.scAriaLabel("005930.KS", "3m", [{ time: "2026-10-30", value: 221500 }]),
  sc.scAriaLabel("AAPL", "1y", [{ time: "2026-10-30", value: 344.63 }]), sc.scAriaLabel("005930", "3m", [])];
const pp = [{ time: "2026-10-29", value: 100 }, { time: "2026-10-30", value: 110 }];
out.basis = [sc.scSummary(pp, null, "adj_base"), sc.scSummary(pp, null, "raw"), sc.scSummary(pp, null), sc.scSummary(pp, 95, "raw")];
const evs = [
  { kind: "earnings", date: "2026-10-29", kind_label: "실적 발표", confidence_label: "확정" },
  { kind: "dividend_ex", date: "2026-10-31", kind_label: "배당락일", confidence_label: "예정" },
  { kind: "agm", date: "2026-11-20", kind_label: "주주총회", confidence_label: "예정" },
  { kind: "agm", date: "2026-10-27", kind_label: "주주총회" },
  { kind: "econ_us", date: "2026-10-29" }, null];
out.evLate = [sc.scEventMarks(evs, shown, "2026-11-02"), sc.scEventMarks(evs, shown, "2026-10-31"), sc.scEventMarks(evs, shown, "2026-11-20")];
const ev = sc.scEventMarks([
  { kind: "earnings", date: "2026-10-29", kind_label: "실적 발표", confidence_label: "확정" },
  { kind: "dividend_ex", date: "2026-10-31", kind_label: "배당락일", confidence_label: "예정" },
  { kind: "agm", date: "2026-11-20", kind_label: "주주총회", confidence_label: "예정" },
  { kind: "agm", date: "2026-10-27", kind_label: "주주총회" },
  { kind: "econ_us", date: "2026-10-29" }, null], shown, "2026-10-30");
out.ev = ev;
out.list = sc.scMarkerList(out.sig[0], ev.marks);
out.byDay = [...sc.scMarksByDay(out.sig[0], ev.marks, { asOf: "2026-10-29" }).entries()];
out.byDayNoDate = [...sc.scMarksByDay(out.sig[0], [], {}).entries()];
out.keys = [sc.scTimeKey("2026-10-29"), sc.scTimeKey({ year: 2026, month: 3, day: 5 }), sc.scTimeKey(null), sc.scTimeKey(1700000000)];
out.paths = [sc.scPathWarm("005930.KS", "2026-11-03"), sc.scPathWarm("AAPL", "2026-11-03"), sc.scEventsPath("0000D0", "2025-06-01", "2027-01-31"), sc.scEventsPath("삼성전자", "a", "b")];
out.today = [sc.scToday(Date.UTC(2026, 10, 3, 15, 30)), sc.scToday(Date.UTC(2026, 10, 3, 14, 59))];
out.price = [sc.scPrice(500.4, true), sc.scPrice(500.4, false), sc.scPrice(12345.6, false), sc.scPrice(-0.5, false)];
out.plain = [sc.scSummaryPlain([{ time: "2026-10-29", value: 340.97 }, { time: "2026-10-30", value: 344.63 }]), sc.scSummaryPlain([])];
out.legendUs = sc.scLegendText({ time: "2026-10-30", open: 340.1, high: 345, low: 339.5, close: 344.63, volume: 1500 }, { close: 340.97 }, null, false);
""")
    assert out["days"] == ["2026-10-28", "2026-10-29", "2026-10-30"] and out["dup"] == 111, "종가 없는 줄은 빼고 같은 날짜는 나중 줄"
    assert out["hasOhlc"] is False and out["hasOhlcOk"] is True and out["volNull"] is None and out["empty"] == [[], False]
    assert out["start"][0] < out["start"][1] < out["start"][2] and out["start"][2] <= 367
    assert out["legend"][0] == "2026-10-29 · 시 106 · 고 113 · 저 101 · 종 111 (+5.71%) · 거래량 2,500 — 실적 발표(확정)"
    assert "시 " not in out["legend"][1] and out["legend"][1].startswith("2026-10-30 · 종 108 (−2.70%)") and out["legend"][2] == ""
    buy, sell, hold, outside, none, bad = out["sig"]
    # 신호 표식은 매수 · 매도 · 관망 모두 같은 중립 점이다 — 화살표는 그 봉 마감에 신호가 난 것처럼 읽혀(룩어헤드) 쓰지 않는다. 어느 쪽인지는 값 줄 · 풀이 글이 말한다
    assert buy["time"] == "2026-10-29" and buy["position"] == "belowBar" and buy["words"] == "매수 쪽" and sell["words"] == "매도 쪽" and hold["words"] == "관망"
    assert {m["shape"] for m in (buy, sell, hold)} == {"circle"} and {m["glyph"] for m in (buy, sell, hold)} == {"●"} and {m["text"] for m in (buy, sell, hold)} == {"신호 기록"}
    assert not any(a in json.dumps(out["sig"], ensure_ascii=False) for a in ("arrowUp", "arrowDown", "▲", "▼")), "화살표 · 삼각형이 남지 않았다"
    assert outside is None and none is None and bad is None, "기준일 봉이 보이는 기간에 없으면 찍지 않는다(가까운 봉으로 옮겨 찍지 않는다)"
    assert "10-29 종가까지의 규칙 점수가 매수 쪽이었다는 기록" in out["sigNote"] and "다음 거래일 낮에 기록" in out["sigNote"] and "재지 않습니다" in out["sigNote"]
    assert "여러 주기(60분 · 일 · 주)를 합친 기록" in out["sigNote"] and "●" in out["sigNote"] and "분봉이 없는 종목은 일 · 주" in out["sigNote"]
    m_after, m_before, m_gap, m_bad, m_none = out["miss"]
    assert "(11-04)이 일봉의 마지막 봉(10-30)보다 뒤라 아직 그 날의 일봉이 들어오지 않아" in m_after, "기준일이 마지막 봉보다 뒤면 「기간에 없어」 가 아니라 맞는 까닭"
    assert "기준일 봉이 지금 보이는 기간에 없어" in m_before and "기간에 없어" not in m_after
    assert "(10-29)에는 일봉이 없어(휴장일이거나 수집되지 않은 날)" in m_gap and "읽지 못해" in m_bad and m_none == ""
    assert out["fits"] == [True, True, False, True, False, False], "종목을 밝힌 신호는 같은 종목 칸에만(005930 = 005930.KS) · 밝히지 않은 신호는 그대로"
    assert out["stopFit"] == ["in", "extend", "extend", "far", "far", "none", "none", "none"], "스탑가: 범위 안 · 가까우면 넓힘(30% 이내) · 멀면 넓히지 않음"
    assert out["labels"] == ["1개월", "6개월", "2년", "", "005930.KS 3개월 일봉 차트 — 마지막 종가 221,500원(2026-10-30)", "AAPL 1년 일봉 차트 — 마지막 종가 344.63(2026-10-30)", ""]
    adj, raw_, unknown, raw_stop = out["basis"]
    assert "우리 수집 일봉(수정주가) 종가이며" in adj and "수정하지 않은 종가이며" in raw_ and "수정주가" not in raw_ and "수정주가" not in unknown and "우리 수집 일봉 종가이며" in unknown, "ETF · 지수는 수정주가라고 하지 않는다"
    assert "검은 점선은 입력한 스탑가 95원" in raw_stop
    late, sat, upcoming_all = out["evLate"]
    assert [u["time"] for u in late["upcoming"]] == ["2026-11-20"] and late["noBar"] == 1, "오늘(11-02) 기준 — 10-31 은 지난 날인데 봉이 없으니 예정이 아니다(일봉이 늦는 월요일 오전)"
    assert [u["time"] for u in sat["upcoming"]] == ["2026-10-31", "2026-11-20"] and sat["noBar"] == 0, "오늘이 10-31 이면 그날은 아직 예정"
    assert [u["time"] for u in upcoming_all["upcoming"]] == ["2026-11-20"] and upcoming_all["noBar"] == 1, "오늘 이후(포함)만 예정"
    assert [m["time"] for m in out["ev"]["marks"]] == ["2026-10-29"] and [u["time"] for u in out["ev"]["upcoming"]] == ["2026-10-31", "2026-11-20"], "봉 없는 지난 날의 일정은 찍지 않고 마지막 봉 뒤 일정은 따로 · 알 수 없는 종류는 뺀다"
    assert [m["time"] for m in out["list"]] == ["2026-10-29", "2026-10-29"] and {m["text"] for m in out["list"]} == {"신호 기록", "실적"}
    assert out["byDay"] == [["2026-10-29", ["기록된 신호 매수 쪽 (10-29 기준 · 여러 주기(60분 · 일 · 주)를 합친 기록)", "실적 발표(확정)"]]]
    assert out["byDayNoDate"] == [["2026-10-29", ["기록된 신호 매수 쪽 (여러 주기(60분 · 일 · 주)를 합친 기록)"]]]
    assert out["keys"] == ["2026-10-29", "2026-03-05", "", ""]
    assert out["paths"][0].startswith("/api/data/ohlcv?symbol=005930&from=2025-06-") and out["paths"][1] == ""
    assert out["paths"][2] == "/api/calendar/events?symbol=0000D0&kind=earnings,dividend_ex,agm&from=2025-06-01&to=2027-01-31&limit=300" and out["paths"][3] == ""
    assert out["today"] == ["2026-11-04", "2026-11-03"], "한국 날짜(KST)로 읽는다"
    assert out["price"] == ["500", "500.40", "12,346", "-0.50"], "가격 글 — 국내 코드는 정수 · 그 밖은 1000 미만이면 소수 둘"
    assert out["plain"][0] == "최고 344.63 · 최저 340.97 · 마지막 종가 344.63(2026-10-30) — 일봉 종가이며 실시간 차트가 아닙니다." and out["plain"][1] == "일봉 자료가 없습니다.", "통화를 모르는 종목은 원 · 수정주가를 말하지 않는다"
    assert out["legendUs"] == "2026-10-30 · 시 340.10 · 고 345.00 · 저 339.50 · 종 344.63 (+1.07%) · 거래량 1,500"


_FAKE_DOM = """
class El {
  constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.style = {}; this.attrs = {}; this.listeners = {}; this.parentNode = null; this.hidden = false; this.textContent = ""; this.className = ""; this.clientHeight = 150; this.classes = new Set(); this.classList = { add: c => this.classes.add(c) }; }
  get isConnected() { return this.parentNode !== null; }
  appendChild(c) { if (c.parentNode) c.remove(); c.parentNode = this; this.children.push(c); return c; }
  insertBefore(c, ref) { c.parentNode = this; this.children.splice(this.children.indexOf(ref), 0, c); return c; }
  replaceChildren() { this.children.forEach(c => { c.parentNode = null; }); this.children = []; }
  remove() { if (this.parentNode) { this.parentNode.children = this.parentNode.children.filter(x => x !== this); this.parentNode = null; } }
  addEventListener(t, f) { this.listeners[t] = f; }
  setAttribute(k, v) { this.attrs[k] = v; }
  removeAttribute(k) { delete this.attrs[k]; }
}
const log = { charts: [], markers: [], calls: [] };
const lib = {
  CandlestickSeries: "candle", LineSeries: "line", HistogramSeries: "hist",
  createChart(el, opts) {
    const c = { el, opts, series: [], removed: false };
    c.addSeries = (kind, o, pane = 0) => {
      const s = { kind, o: { ...o }, pane, data: [], lines: [] };
      s.setData = d => { if (log.throwOnSetData) throw new Error("setData 실패"); s.data = d; }; s.applyOptions = x => Object.assign(s.o, x); s.createPriceLine = l => { s.lines.push(l); return l; }; s.removePriceLine = l => { s.lines = s.lines.filter(x => x !== l); };
      s.priceScale = () => ({ applyOptions() {} });
      c.series.push(s); return s;
    };
    c.priceScale = () => ({ applyOptions() {} }); c.timeScale = () => ({ fitContent() {} });
    c.subscribeCrosshairMove = f => { c.cross = f; }; c.panes = () => [{ setStretchFactor() {} }];
    c.remove = () => { c.removed = true; };
    log.charts.push(c); return c;
  },
  createSeriesMarkers(series, markers) { log.markers.push({ series, markers }); },
};
const doc = { defaultView: { LightweightCharts: lib, requestAnimationFrame: f => setTimeout(f, 0), getComputedStyle: () => ({ getPropertyValue: () => "" }) },
  createElement: t => new El(t), documentElement: {}, head: new El("head") };
const sleep = ms => new Promise(r => setTimeout(r, ms));
function mkRows(n, withOhlc = true, start = 100000) {
  const rows = []; let d = Date.UTC(2026, 4, 1), v = start;
  while (rows.length < n) {
    const day = new Date(d); d += 86400000;
    if (day.getUTCDay() === 0 || day.getUTCDay() === 6) continue;
    v += (rows.length % 7 - 3) * 300;
    const r = { trade_date: day.toISOString().slice(0, 10), close: v, volume: 1000 + rows.length };
    if (withOhlc) Object.assign(r, { open: v - 200, high: v + 500, low: v - 600 });
    rows.push(r);
  }
  return rows;
}
const rowsA = mkRows(150);
const lastDay = rowsA[rowsA.length - 1].trade_date;
const delays = {}; let calendarFail = false, ohlcFail = false; const ohlcFor = {};
const api = async url => {
  log.calls.push(url);
  const code = /symbol=([0-9A-Z]{6})/.exec(url)[1];
  await sleep(delays[code] || 0);
  if (ohlcFail && url.startsWith("/api/data/")) throw new Error("500");
  if (url.startsWith("/api/calendar/")) {
    if (calendarFail) throw new Error("503");
    return { events: [{ kind: "earnings", date: lastDay, kind_label: "실적 발표", confidence_label: "확정" }, { kind: "dividend_ex", date: "2027-01-02", kind_label: "배당락일", confidence_label: "예정" }] };
  }
  return { rows: ohlcFor[code] || rowsA, basis: "adj_base" };
};
function fresh() {
  const wrap = new El("div"), box = new El("div"), note = new El("p");
  wrap.appendChild(box); wrap.appendChild(note); box.style.height = "200px";
  log.charts = []; log.markers = []; log.calls = [];
  return { wrap, box, note, c: sc.mountDailyChart(doc, box, note, { api }) };
}
"""


def test_mounted_chart_draws_candles_toggles_and_drops_late_answers(tmp_path):
    """TC-SCH-06 · mountDailyChart 실동작(가짜 DOM · 가짜 라이브러리) — 캔들 + 거래량 + 선 · 칩 줄은 box 의 형제 · 기록 한 점 + 일정이 한 번의 표식 호출 · 스탑가 점선 ·
    선 켜고 끄기는 다시 그리지 않고 하위 창은 다시 그린다 · 기간을 바꿔도 다시 받지 않는다 · 늦은 응답은 버린다 · destroy 가 차트와 칩 줄을 걷는다 · 시가가 없으면 종가 선."""
    out = _run(tmp_path, _FAKE_DOM + """
await (async () => {
  // ① 기본 그림
  let t = fresh(); t.c.setSignal({ asOf: lastDay, side: "매수" });
  await t.c.draw({ symbol: "005930.KS", period: "3m", stop: 99000 });
  const ch = log.charts[0];
  const legendOf = () => t.wrap.children.find(c => c.className === "pc-dc-legend").textContent;
  out.basic = {
    charts: log.charts.length, kinds: ch.series.map(s => s.kind + ":" + s.pane), visible: ch.series.map(s => s.o.visible),
    stop: ch.series[0].lines.map(l => [l.price, l.lineStyle, l.title]), markers: log.markers.length, markerTexts: log.markers.map(m => m.markers.map(x => x.text)),
    markerSeriesIsMain: !!log.markers[0] && log.markers[0].series === ch.series[0],
    barBefore: t.wrap.children[0].className, chips: t.wrap.children[0].children.map(b => b.dataset.pcDc + ":" + b.attrs["aria-pressed"]), wrapOrder: t.wrap.children.map(c => c.className || c.tag), boxChildren: t.box.children.map(c => c.className),
    calls: log.calls.map(u => u.split("?")[0]), paths: log.calls, note: t.note.textContent, boxClass: [...t.box.classes], height: t.box.style.height,
    legend: legendOf(), autoSize: ch.opts.autoSize, lock: ch.opts.timeScale.lockVisibleTimeRangeOnResize, candleColors: [ch.series[0].o.upColor, ch.series[0].o.downColor],
  };
  ch.cross({ time: rowsA[100].trade_date }); out.hover = legendOf();
  ch.cross({}); out.hoverOut = legendOf();
  // ② 기간 바꾸기 — 다시 받지 않고 새로 그린다
  await t.c.draw({ symbol: "005930.KS", period: "1y", stop: 99000 });
  out.period = { calls: log.calls.length, charts: log.charts.length, firstRemoved: log.charts[0].removed };
  // ③ 선 켜고 끄기 — 다시 그리지 않는다
  const bar = t.wrap.children[0];
  const clickChip = k => bar.children.find(b => b.dataset.pcDc === k).listeners.click();
  const cur = () => log.charts[log.charts.length - 1];
  clickChip("ma60"); clickChip("bb"); clickChip("ma20");
  out.toggle = { charts: log.charts.length, visible: cur().series.slice(2).map(s => s.o.visible), pressed: bar.children.map(b => b.attrs["aria-pressed"]) };
  // ④ 하위 창 — 다시 그리고 칸이 커진다
  clickChip("rsi"); await sleep(20); clickChip("macd"); await sleep(20);
  const c4 = cur();
  out.panes = { charts: log.charts.length, panes: c4.series.map(s => s.pane), height: t.box.style.height, prevRemoved: log.charts.slice(0, -1).every(c => c.removed), rsiLines: c4.series.filter(s => s.lines.length === 2).length };
  // ⑤ destroy
  t.c.destroy();
  out.destroy = { removed: cur().removed, bar: t.wrap.children.length, box: t.box.children.length };
  // ⑥ 늦은 응답 — 종목마다 다른 줄을 준다(같은 줄이면 옛 종목 응답이 덮어써도 눈치채지 못한다)
  t = fresh(); delays["000660"] = 40; delays["035720"] = 1; ohlcFor["000660"] = mkRows(150, true, 50000); ohlcFor["035720"] = mkRows(150, true, 30000);
  const p1 = t.c.draw({ symbol: "000660.KS", period: "3m" }); const p2 = t.c.draw({ symbol: "035720.KS", period: "3m" });
  const rets = await Promise.all([p1, p2]); await sleep(60);
  const candle = log.charts.map(c => c.series.find(s => s.kind === "candle").data);
  out.late = { charts: log.charts.length, note: t.note.textContent.slice(0, 2), rets, lastClose: candle.map(d => d[d.length - 1].close),
    want: ohlcFor["035720"][ohlcFor["035720"].length - 1].close, other: ohlcFor["000660"][ohlcFor["000660"].length - 1].close, calls: log.calls.filter(u => u.startsWith("/api/data/")).length };
  // ⑦ 시가가 없으면 종가 선 · 일정을 못 받아도 그린다
  t = fresh(); ohlcFor["005380"] = mkRows(80, false); calendarFail = true;
  await t.c.draw({ symbol: "005380", period: "3m" });
  out.line = { kinds: log.charts[0].series.map(s => s.kind).slice(0, 2), note: t.note.textContent, markers: log.markers.length };
  // ⑧ 외국 종목 · 기록 날짜가 기간 밖
  t = fresh(); await t.c.draw({ symbol: "AAPL" }); out.foreign = { note: t.note.textContent, charts: log.charts.length, calls: log.calls.length };
  calendarFail = false; t = fresh(); t.c.setSignal({ asOf: "2020-01-02", side: "매도" });
  await t.c.draw({ symbol: "005930.KS", period: "1m" }); out.sigOut = t.note.textContent;
})();
""")
    b = out["basic"]
    assert b["charts"] == 1 and b["kinds"] == ["candle:0", "hist:0", "line:0", "line:0", "line:0", "line:0"], "캔들 · 거래량 · 20일 · 60일 · 볼린저 둘 (하위 창은 꺼짐)"
    assert b["visible"][1:] == [True, True, False, False, False] and b["candleColors"] == ["#dc2626", "#2563eb"], "처음에는 거래량 · 20일선만 · 오름 빨강 내림 파랑"
    assert b["stop"] == [[99000, 2, "스탑가"]], "스탑가 점선(계약)이 캔들 위에도 그대로"
    assert b["markers"] == 1 and b["markerTexts"] == [["신호 기록", "실적"]] and b["markerSeriesIsMain"], "신호 한 점과 일정이 한 번의 표식 호출(두 번 걸면 앞 것이 덮인다)"
    assert b["barBefore"] == "pc-dc-bar" and b["chips"] == ["vol:true", "ma20:true", "ma60:false", "bb:false", "rsi:false", "macd:false"], "칩 줄은 box 앞 형제(다시 그릴 때 안 지워짐)"
    assert b["wrapOrder"] == ["pc-dc-bar", "pc-dc-legend", "div", "p"] and b["boxChildren"] == [] and "pc-dc-box" in b["boxClass"] and b["height"] == "200px", "칩 줄 · 값 줄은 box 앞 형제(차트에 겹치지 않고 다시 그려도 남는다)"
    assert b["calls"] == ["/api/data/ohlcv", "/api/calendar/events"] and "&from=" in b["paths"][0] and not any("/api/stocks/" in u or "yahoo" in u for u in b["paths"])
    assert "검은 점선은 입력한 스탑가 99,000원" in b["note"] and "표시용 값" in b["note"] and "다음 거래일 낮에 기록" in b["note"] and "네모 표시" in b["note"]
    assert b["autoSize"] is True and b["lock"] is True
    assert "거래량" in b["legend"] and "실적 발표(확정)" in b["legend"] and "기록된 신호 매수 쪽" in b["legend"], "처음에는 마지막 봉의 값 · 그날의 기록과 일정"
    assert out["hover"].startswith(f"{_hover_day()} · 시 ") and "고 " in out["hover"] and "저 " in out["hover"] and "종 " in out["hover"] and "거래량" in out["hover"]
    assert out["hoverOut"] == b["legend"], "크로스헤어가 빠지면 마지막 봉으로 돌아온다"
    assert out["period"] == {"calls": 2, "charts": 2, "firstRemoved": True}, "기간을 바꿔도 다시 받지 않고 이전 차트는 걷는다"
    assert out["toggle"]["charts"] == 2 and out["toggle"]["visible"] == [False, True, True, True], "선을 켜고 끄는 것은 다시 그리지 않는다(20일선 끔 · 60일선 · 볼린저 켬)"
    assert out["toggle"]["pressed"] == ["true", "false", "true", "true", "false", "false"], "눌림 표시가 따라간다"
    p = out["panes"]
    assert p["charts"] == 4 and p["panes"].count(1) >= 1 and p["panes"].count(2) >= 1 and p["height"] == "384px" and p["prevRemoved"] and p["rsiLines"] == 1, "RSI(30 · 70 점선) · MACD 하위 창을 켜면 다시 그리고 칸이 92px 씩 커진다"
    assert out["destroy"] == {"removed": True, "bar": 2, "box": 0}, "destroy 는 차트를 걷고 칩 줄 · 값 줄을 떼며(형제는 box · 글 칸 둘만 남는다) box 를 비운다"
    late = out["late"]
    assert late["charts"] == 1 and late["note"] == "최고", "먼저 보낸 느린 응답은 그리지 않는다"
    assert late["lastClose"] == [late["want"]] and late["want"] != late["other"], "남은 차트는 나중에 요청한 종목의 줄이다(옛 종목 응답이 덮어쓰지 않았다)"
    assert late["rets"] == [False, True] and late["calls"] == 2, "밀린 draw 는 false · 마지막 요청은 true"
    assert out["line"]["kinds"] == ["line", "hist"] and "종가 선으로 보입니다" in out["line"]["note"] and "일정 표시는 받지 못해" in out["line"]["note"]
    assert out["foreign"] == {"note": "이 종목은 수집 일봉이 없어 차트를 그리지 못합니다(국내 6자리 코드만).", "charts": 0, "calls": 0}
    assert "기준일 봉이 지금 보이는 기간에 없어" in out["sigOut"]


def _hover_day() -> str:
    """가짜 일봉 줄(2026-05-01 부터 평일 150개)의 101번째 날짜 — 시험 안의 mkRows 와 같은 규칙."""
    from datetime import date, timedelta
    d, n = date(2026, 5, 1), 0
    while True:
        if d.weekday() < 5:
            if n == 100:
                return d.isoformat()
            n += 1
        d += timedelta(days=1)


def test_chart_wiring_names_css_and_words():
    """TC-SCH-07 · 연결 — 서랍은 마지막 기록 한 점만 넘긴다(신호 칸 글은 안 건드림) · 새 CSS 는 pc-dc- 로만 · 상품 차트의 pc- 와 겹치지 않음 · 화면 글에 금지어가 없다 · 계약 이름이 남는다."""
    from app.services import signal_explain
    sc = SC.read_text(encoding="utf-8")
    drawer = (PUB / "js" / "stockdrawer.js").read_text(encoding="utf-8")
    css = (PUB / "css" / "pricechart.css").read_text(encoding="utf-8")
    app = (PUB / "app.html").read_text(encoding="utf-8")
    assert "export function sdChartSignal(hub)" in drawer and "c.setSignal?.(sdChartSignal(hub))" in drawer and "startChart(h, hub.symbol, undefined, hub)" in drawer
    assert '<link rel="stylesheet" href="/css/pricechart.css"' in app
    classes = set(re.findall(r"\.(pc-[a-z-]+)", css))
    assert classes == {"pc-dc-box", "pc-dc-bar", "pc-dc-chip", "pc-dc-legend", "pc-dc-sw"}
    assert "min-height: 24px" in css and "min-height: 4.2em" in css, "칩 터치 대상 24px · 좁은 화면 값 줄은 석 줄 높이"
    other_css = "".join(p.read_text(encoding="utf-8") for p in (PUB / "css").glob("*.css") if p.name != "pricechart.css")
    other_js = "".join(p.read_text(encoding="utf-8") for p in (PUB / "js").glob("*.js") if p.name != "stockchart.js")
    for c in classes:
        assert f".{c}" not in other_css and c not in other_js, f"{c} 가 다른 파일과 겹친다"
    for name in ("export function mountDailyChart", "export const SC_PERIODS", "export const SC_DEFAULT_PERIOD", "export function scDirection", "export function scQuickStops", "export function scWouldFireNow", "export function scCode"):
        assert name in sc, name
    assert "return { draw, destroy, setSignal }" in sc
    code = re.sub(r"/\*.*?\*/", "", sc, flags=re.S)
    code = "\n".join(re.sub(r"\s//.*$", "", line) for line in code.splitlines())
    for word in signal_explain.FORBIDDEN:
        assert word not in code, f"화면 글에 금지어 「{word}」"
    assert "/api/stocks/" not in sc and "/api/indicator-strategy" not in sc and "yahoo" not in sc.lower(), "지표는 서버 지표 길(야후 기준선을 부른다)이 아니라 화면 계산"


def test_mounted_chart_waits_a_frame_safely_and_cleans_up_when_drawing_fails(tmp_path):
    """TC-SCH-08 · 옛 퀀트 차트에서 검수가 지적한 두 가지가 공용 부품에서도 지켜진다 — ① 첫 그림이 다음 프레임을 기다리는 사이 다른 종목을 그리라고 하면 먼저 것은 차트를 만들지 않는다
    ② 그리는 중 라이브러리가 던지면 반쯤 그려진 차트를 걷고(새지 않게) 오류 글을 남기며 호스트에 알린다."""
    out = _run(tmp_path, _FAKE_DOM + """
const rafQ = [];
const doc2 = { ...doc, defaultView: { ...doc.defaultView, requestAnimationFrame: f => rafQ.push(f) } };     // 프레임을 손으로 흘려 보내 경합 순서를 정한다
const settle = async ps => { let done = false; Promise.all(ps).then(() => { done = true; }); while (!done) { await sleep(2); while (rafQ.length) rafQ.shift()(); } };
await (async () => {
  // ① 프레임 대기 중에 다른 종목
  let t = fresh(); const c2 = sc.mountDailyChart(doc2, t.box, t.note, { api });
  ohlcFor["000660"] = mkRows(40);
  const p1 = c2.draw({ symbol: "005930.KS", period: "3m" });
  while (!rafQ.length) await sleep(1);
  const p2 = c2.draw({ symbol: "000660.KS", period: "3m" });
  await settle([p1, p2]);
  const candle = log.charts.map(c => c.series.find(s => s.kind === "candle").data.length);
  out.mid = { charts: log.charts.length, candleBars: candle, note: t.note.textContent.slice(0, 2) };
  // ② setData 예외
  t = fresh(); log.throwOnSetData = true; let reported = 0;
  const c3 = sc.mountDailyChart(doc, t.box, t.note, { api, onError: () => { reported += 1; } });
  await c3.draw({ symbol: "005930.KS", period: "3m" });
  out.throws = { charts: log.charts.length, removed: log.charts.map(c => c.removed), note: t.note.textContent, box: t.box.children.length, reported };
  log.throwOnSetData = false;
  // 던진 뒤에도 다시 그릴 수 있다
  await c3.draw({ symbol: "005930.KS", period: "1y" });
  out.after = { charts: log.charts.length, lastRemoved: log.charts[log.charts.length - 1].removed };
})();
""")
    assert out["mid"]["charts"] == 1 and out["mid"]["candleBars"][0] <= 40 and out["mid"]["note"] == "최고", "프레임 대기 중 바뀌면 먼저 종목의 차트는 만들지 않는다(마지막 요청의 봉만)"
    t = out["throws"]
    assert t["charts"] == 1 and t["removed"] == [True] and t["note"].startswith("차트를 그리지 못했습니다") and t["box"] == 0 and t["reported"] == 1, "setData 예외에도 차트가 새지 않고 오류를 알린다"
    assert out["after"] == {"charts": 2, "lastRemoved": False}, "던진 뒤에도 다시 그릴 수 있다"


def test_signal_mark_note_carries_the_recorded_time(tmp_path):
    """TC-SCH-09 · 신호 표식 풀이에 기록 시각(S195 · 날짜별 근거 안 A) — 정기면 「11-03 12:59 에 기록했습니다」 · 늦게 계산이면 「늦게 계산한 값이라 그날 이 화면에서 실제로
    보였던 값은 아닐 수 있습니다」 · 시각을 모르면 지금까지의 풀이 그대로. 이미 그린 차트에 setSignal 로 다른 날(늦게 계산)을 넘기면 풀이가 바뀐다."""
    out = _run(tmp_path, _FAKE_DOM + """
const mark = sc.scSignalMark({ asOf: lastDay, side: "매수" }, sc.scBars(rowsA));
out.notes = [sc.scSignalNote(mark, lastDay), sc.scSignalNote(mark, lastDay, {}), sc.scSignalNote(mark, lastDay, { computedAt: "", late: true }),
  sc.scSignalNote(mark, lastDay, { computedAt: "2026-11-03 12:59", late: false }), sc.scSignalNote(mark, lastDay, { computedAt: "2026-11-05 09:20", late: true })];
await (async () => {
  let t = fresh(); t.c.setSignal({ asOf: lastDay, side: "매수", computedAt: "2026-11-03 12:59", late: false });
  await t.c.draw({ symbol: "005930.KS", period: "3m" });
  out.regular = t.note.textContent;
  t.c.setSignal({ asOf: lastDay, side: "매수", computedAt: "2026-11-05 09:20", late: true });     // 날짜를 바꿔 늦게 계산된 기록을 고른 경우
  await sleep(30);
  out.late = t.note.textContent;
  t.c.setSignal(null); await sleep(30);
  out.none = t.note.textContent;
})();
""")
    base, empty_rec, no_time, regular, late = out["notes"]
    assert base == empty_rec == no_time and "다음 거래일 낮에 기록됩니다" in base                                       # 시각을 모르면 지금까지와 같은 풀이
    assert "11-03 12:59 에 기록했습니다(그날 종가에 이미 알 수 있던 값이 아닙니다)" in regular and "다음 거래일 낮" not in regular
    assert "11-05 09:20 에 늦게 계산한 값이라 그날 이 화면에서 실제로 보였던 값은 아닐 수 있습니다" in late and "이 표시 뒤 가격은 이 화면이 재지 않습니다" in late
    assert "11-03 12:59 에 기록했습니다" in out["regular"] and "11-05 09:20 에 늦게 계산한 값" in out["late"]
    assert "늦게 계산한 값" not in out["none"] and "11-03 12:59" not in out["none"]


def test_chart_indicators_short_gappy_and_single_bar_series(tmp_path):
    """TC-SCH-04b · 짧은 자료(14/20/26/60봉 미만) · 한 봉 · 결측에서도 화면 계산이 서버 `ta_utils` 와 같은 자리에서 비고 같은 값을 낸다.
    봉이 한 개뿐이어도 · 시가 · 고가 · 저가 · 거래량이 빠진 줄이 섞여도 차트는 던지지 않고 그린다."""
    import math
    import pandas as pd
    from app.services import ta_utils
    lengths = [1, 2, 5, 13, 14, 15, 19, 20, 21, 25, 26, 27, 34, 35, 59, 60, 61]
    series = {n: [round(50000 + 37 * i + (i % 5) * 311 - (i % 3) * 190, 2) for i in range(n)] for n in lengths}
    out = _run(tmp_path, f"""
const sets = {json.dumps({str(n): v for n, v in series.items()})};
out.res = {{}};
for (const [n, c] of Object.entries(sets)) {{
  const b = sc.scBollinger(c), m = sc.scMacd(c);
  out.res[n] = {{ sma20: sc.scSma(c, 20), sma60: sc.scSma(c, 60), bbU: b.upper, bbM: b.mid, bbL: b.lower, rsi: sc.scRsi(c), macd: m.macd, sig: m.signal, hist: m.hist }};
}}
""")
    for n in lengths:
        s = pd.Series(series[n], dtype=float)
        up, mid, lo = ta_utils.bollinger(s, 20, 2.0)
        macd, sig, hist = ta_utils.macd(s)
        want = {"sma20": ta_utils.sma(s, 20), "sma60": ta_utils.sma(s, 60), "bbU": up, "bbM": mid, "bbL": lo, "rsi": ta_utils.rsi(s, 14), "macd": macd, "sig": sig, "hist": hist}
        for key, ser in want.items():
            got = out["res"][str(n)][key]
            assert len(got) == n, (n, key)
            for i, (g, w) in enumerate(zip(got, ser.tolist())):
                if w is None or (isinstance(w, float) and math.isnan(w)):
                    assert g is None, f"n={n} {key}[{i}] 서버는 비었는데 화면은 {g}"
                else:
                    assert g is not None and abs(g - w) <= 1e-6 * max(1.0, abs(w)), f"n={n} {key}[{i}] 화면 {g} ≠ 서버 {w}"
    # 창이 차기 전에는 비어 있다(지어내지 않는다)
    res = out["res"]
    assert all(v is None for v in res["13"]["rsi"]) and res["15"]["rsi"][14] is not None and all(v is None for v in res["19"]["sma20"]) and res["20"]["sma20"][19] is not None
    assert all(v is None for v in res["59"]["sma60"]) and res["60"]["sma60"][59] is not None
    body = _FAKE_DOM + """
await (async () => {
  // 한 봉 · 두 봉 · 일부 줄에 시가 · 고가 · 저가 · 거래량이 빠진 자료 · 숫자가 아닌 종가 — 모든 선을 켠 채로
  const gap = mkRows(40); delete gap[10].high; gap[12].volume = null; gap[15] = { trade_date: gap[15].trade_date, close: gap[15].close };
  const junk = [{ trade_date: "2026-11-02", close: "abc" }, { trade_date: "2026-11-02", close: NaN }, { trade_date: "2026-11-02", close: Infinity }, { trade_date: "2026-11-03", close: 1000, volume: -5 }];
  for (const [name, rows] of [["one", mkRows(1)], ["two", mkRows(2)], ["gap", gap], ["junk", junk]]) {
    const t = fresh(); ohlcFor["005930"] = rows;
    const bar = () => t.wrap.children[0];
    const ret = await t.c.draw({ symbol: "005930", period: "1y", stop: 900 });
    for (const k of ["ma60", "bb", "rsi", "macd"]) { bar().children.find(b => b.dataset.pcDc === k).listeners.click(); await sleep(15); }
    const ch = log.charts[log.charts.length - 1];
    out[name] = { ret, charts: log.charts.length, removed: ch.removed, kinds: ch.series.filter(s => s.pane === 0).map(s => s.kind).slice(0, 2), main: ch.series[0].data.length, note: t.note.textContent.slice(0, 40) };
  }
})();
"""
    out2 = _run(tmp_path, body)
    assert out2["one"]["ret"] is True and out2["one"]["main"] == 1 and out2["one"]["removed"] is False, "봉이 하나여도 그린다"
    assert out2["two"]["ret"] is True and out2["two"]["main"] == 2
    assert out2["gap"]["ret"] is True and out2["gap"]["kinds"][0] == "line" and out2["gap"]["removed"] is False, "일부 줄에 시가 · 고가 · 저가가 없으면 값을 지어내지 않고 종가 선"
    assert out2["junk"]["ret"] is True and out2["junk"]["main"] == 1 and out2["junk"]["note"].startswith("최고"), "종가가 숫자가 아닌 줄은 빼고 남은 한 봉을 그린다"


def test_draw_return_contract_stop_only_update_and_quant_fallback(tmp_path):
    """TC-SCH-10 · draw() 반환 계약 — ① 칩을 눌러 그림이 다시 시작돼도 그 그림이 이어받아 true ② 새 요청 · destroy 에 밀리면 false ③ 받지 못하면 false 이고 호스트가 줄을 직접 줘서 다시 그리면 true(퀀트 대체 줄 흐름).
    스탑가만 바뀌면 차트를 다시 그리지 않고 점선 하나만 갈아 끼운다 · 가격 범위(autoscale)는 가까운 스탑가를 품고 먼 스탑가는 글로 알린다."""
    out = _run(tmp_path, _FAKE_DOM + """
const rafQ = [];
const doc2 = { ...doc, defaultView: { ...doc.defaultView, requestAnimationFrame: f => rafQ.push(f) } };     // 프레임을 손으로 흘려 보내 경합 순서를 정한다
const settle = async ps => { let done = false; Promise.all(ps).then(() => { done = true; }); while (!done) { await sleep(2); while (rafQ.length) rafQ.shift()(); } };
await (async () => {
  // ① 첫 그림이 프레임을 기다리는 사이 하위 창 칩(RSI) → 그 그림이 이어받아 draw 가 true
  let t = fresh(); const c2 = sc.mountDailyChart(doc2, t.box, t.note, { api });
  const p = c2.draw({ symbol: "005930.KS", period: "3m" });
  while (!rafQ.length) await sleep(1);
  t.wrap.children[0].children.find(b => b.dataset.pcDc === "rsi").listeners.click();
  await settle([p]);
  out.chip = { ret: await p, charts: log.charts.length, hasRsiPane: log.charts[log.charts.length - 1].series.some(s => s.pane === 1) };
  // ② 새 요청에 밀리면 false · destroy 에 밀려도 false
  t = fresh(); delays["000660"] = 30; ohlcFor["000660"] = mkRows(150, true, 60000);
  const a = t.c.draw({ symbol: "000660.KS", period: "3m" }); const b = t.c.draw({ symbol: "005930.KS", period: "3m" });
  out.superseded = await Promise.all([a, b]);
  t = fresh(); const d = t.c.draw({ symbol: "005930.KS", period: "3m" }); t.c.destroy(); out.destroyed = await d; out.afterDestroy = log.charts.length;
  // ③ 퀀트 대체 줄 흐름 — 수집 일봉을 못 받으면 false, 호스트가 줄을 줘서 다시 그리면 true(요청 없이)
  t = fresh(); ohlcFail = true;
  const r1 = await t.c.draw({ symbol: "005930.KS", period: "6m" });
  const afterFail = { calls: log.calls.length, note: t.note.textContent, charts: log.charts.length };
  ohlcFail = false;
  const fallback = mkRows(60, false).map(r => ({ trade_date: r.trade_date, close: r.close }));
  const r2 = await t.c.draw({ symbol: "005930.KS", period: "6m", rows: fallback });
  out.fallback = { r1, r2, afterFail, callsAfter: log.calls.length, charts: log.charts.length, kinds: log.charts[0].series.map(s => s.kind).slice(0, 2), note: t.note.textContent.slice(0, 2) };
  // 정상으로 그려지면 true 하나로 끝나 대체 줄이 필요 없다
  t = fresh(); out.normal = await t.c.draw({ symbol: "005930.KS", period: "6m" });
  // ④ 스탑가만 바뀜 — 다시 그리지 않는다
  t = fresh(); await t.c.draw({ symbol: "005930.KS", period: "3m", stop: 99000 });
  const first = log.charts[0], main = first.series[0], bar = t.wrap.children[0], legend = t.wrap.children[1];
  const legendBefore = legend.textContent, calls0 = log.calls.length;
  const lo = Math.min(...main.data.map(x => x.low)), hi = Math.max(...main.data.map(x => x.high));
  const near = Math.round(lo * 0.93);
  const rs = await t.c.draw({ symbol: "005930.KS", period: "3m", stop: near });
  out.stopOnly = { ret: rs, charts: log.charts.length, firstRemoved: first.removed, calls: log.calls.length - calls0, lines: main.lines.map(l => l.price), barHidden: bar.hidden, legendKept: legend.textContent === legendBefore,
    note: t.note.textContent, loading: t.note.textContent === "일봉을 불러오는 중…", pressed: bar.children.map(x => x.attrs["aria-pressed"]).join(",") };
  // 가격 범위 보조 — 가까운 스탑가는 범위를 넓히고(점선이 화면 안에) · 범위 안이면 그대로 · 먼 스탑가는 넓히지 않는다
  const prov = main.o.autoscaleInfoProvider;
  const orig = () => ({ priceRange: { minValue: lo, maxValue: hi }, margins: { above: 0, below: 0 } });
  const far = Math.round(lo * 0.5);
  const rangeOf = () => { const r = prov(orig); return r && [r.priceRange.minValue, r.priceRange.maxValue]; };
  const r_near = rangeOf();
  await t.c.draw({ symbol: "005930.KS", period: "3m", stop: Math.round((lo + hi) / 2) }); const r_in = rangeOf();
  await t.c.draw({ symbol: "005930.KS", period: "3m", stop: far }); const r_far = rangeOf(); const farNote = t.note.textContent;
  await t.c.draw({ symbol: "005930.KS", period: "3m", stop: null }); const r_none = rangeOf(); const noneLines = main.lines.length; const noneNote = t.note.textContent;
  out.range = { fn: typeof prov, near, lo, hi, r_near, r_in, r_far, r_none, farNote, noneLines, noneNote, orig: [lo, hi], nullOrig: prov(() => null), charts: log.charts.length };
  // 종목 · 기간이 바뀌면 다시 그린다
  await t.c.draw({ symbol: "005930.KS", period: "1y", stop: 99000 }); out.period = log.charts.length;
})();
""")
    c = out["chip"]
    assert c["ret"] is True and c["charts"] == 1 and c["hasRsiPane"], "칩이 그림을 다시 시작해도 draw 는 true — 호스트가 정상 캔들을 대체 줄로 덮지 않는다"
    assert out["superseded"] == [False, True] and out["destroyed"] is False and out["afterDestroy"] == 0, "새 요청 · destroy 에 밀린 draw 는 false"
    f = out["fallback"]
    assert f["r1"] is False and "일봉을 받지 못했습니다" in f["afterFail"]["note"] and f["afterFail"]["charts"] == 0, "받지 못하면 false"
    assert f["r2"] is True and f["callsAfter"] == f["afterFail"]["calls"] and f["charts"] == 1 and f["kinds"] == ["line", "hist"] and f["note"] == "최고", "대체 줄은 요청 없이 종가 선으로 그려 true"
    assert out["normal"] is True, "정상이면 한 번에 true — 대체 줄 호출이 없다"
    s = out["stopOnly"]
    assert s["ret"] is True and s["charts"] == 1 and s["firstRemoved"] is False and s["calls"] == 0, "스탑가만 바뀌면 다시 그리지도 다시 받지도 않는다"
    assert [round(x) for x in s["lines"]] == [out["range"]["near"]], "점선은 하나만 — 이전 것을 지우고 새로 만든다"
    assert "점선이 보이도록 가격 범위를 넓혀" in s["note"], "범위를 넓혔으면 그 사실을 글로 알린다(봉이 작아 보이는 까닭)"
    assert s["barHidden"] is False and s["legendKept"] and s["loading"] is False and "스탑가 " in s["note"], "칩 줄 · 값 줄이 그대로이고 「불러오는 중…」이 뜨지 않으며 글만 갱신"
    assert s["pressed"] == "true,true,false,false,false,false"
    r = out["range"]
    assert r["fn"] == "function", "메인 시리즈에 가격 범위 보조가 달린다"
    assert r["r_near"] == [r["near"], r["hi"]], "범위 밖이지만 가까운 스탑가(−7%)는 범위를 스탑가까지 넓힌다"
    assert r["r_in"] == r["orig"] and r["r_none"] == r["orig"] and r["nullOrig"] is None, "범위 안 · 스탑가 없음 · 원래 값이 없으면 손대지 않는다"
    assert r["r_far"] == r["orig"] and "가격 범위 밖입니다" in r["farNote"] and "30%" in r["farNote"], "너무 먼 스탑가는 차트를 납작하게 만들지 않고 글로 알린다"
    assert r["noneLines"] == 0 and "스탑가" not in r["noneNote"] and r["charts"] == 1, "스탑가를 비우면 점선이 걷히고 그대로 한 차트"
    assert out["period"] == 2, "기간이 바뀌면 다시 그린다"
    quant = (PUB / "js" / "quant.js").read_text(encoding="utf-8")
    assert "if (!drawn && domestic)" in quant and "rows: domestic ? undefined : quantRows(data)" in quant and "rows: quantRows(data)" in quant, "퀀트의 대체 줄 호출은 draw 가 false 일 때만"


def test_chart_cache_expiry_events_retry_signal_symbol_and_hidden_box(tmp_path):
    """TC-SCH-11 · 일봉 · 일정 캐시는 5분 뒤 다시 받는다 · 일정을 못 받은 채로 캐시하지 않고 다음 draw 에서 일정만 다시 받는다 · 신호는 같은 종목 칸에만(다른 종목을 받는 중에는 옛 줄로 다시 그리지 않음) ·
    숨은 칸이면 높이를 150 으로 굳히지 않는다 · 차트 칸 이름표(role=img) · 칩 색 견본."""
    out = _run(tmp_path, _FAKE_DOM + """
await (async () => {
  // ① 캐시 만료
  let t = fresh();
  await t.c.draw({ symbol: "005930.KS", period: "3m" }); const c1 = log.calls.length;
  await t.c.draw({ symbol: "005930.KS", period: "1y" }); const c2 = log.calls.length;
  const realNow = Date.now; Date.now = () => realNow() + sc.SC_CACHE_MS + 1000;
  try { await t.c.draw({ symbol: "005930.KS", period: "3m" }); } finally { Date.now = realNow; }
  out.ttl = { first: c1, cached: c2, afterExpiry: log.calls.length, ms: sc.SC_CACHE_MS };
  // ② 일정 실패는 캐시하지 않는다
  t = fresh(); calendarFail = true;
  await t.c.draw({ symbol: "005930.KS", period: "3m" }); const e1 = { calls: log.calls.length, note: t.note.textContent };
  calendarFail = false; log.calls = [];
  await t.c.draw({ symbol: "005930.KS", period: "1y" });
  out.events = { failedNote: /일정 표시는 받지 못해/.test(e1.note), retryCalls: log.calls.map(u => u.split("?")[0]), okNote: /일정 표시는 받지 못해/.test(t.note.textContent), eventNote: /네모 표시/.test(t.note.textContent) };
  log.calls = [];
  await t.c.draw({ symbol: "005930.KS", period: "3m" });
  out.eventsAgain = log.calls.length;
  // ③ 신호는 같은 종목 칸에만
  t = fresh(); await t.c.draw({ symbol: "005930.KS", period: "3m" }); const base = log.charts.length;
  t.c.setSignal({ asOf: lastDay, side: "매수", symbol: "000660" });                  // 다른 종목의 신호 — 다시 그리지 않는다
  const afterOther = log.charts.length;
  t.c.setSignal({ asOf: lastDay, side: "매수", symbol: "005930" });                  // 같은 종목(코드만 같으면 같은 종목) — 다시 그려 표식
  await sleep(20);
  out.sig = { base, afterOther, afterSame: log.charts.length, texts: log.markers.map(m => m.markers.map(x => x.text)) };
  // 다른 종목을 받는 중에 도착한 신호 — 옛 종목 줄로 다시 그리지 않는다
  t = fresh(); await t.c.draw({ symbol: "005930.KS", period: "3m" }); const n0 = log.charts.length; delays["000660"] = 30; ohlcFor["000660"] = mkRows(150, true, 60000);
  const slow = t.c.draw({ symbol: "000660.KS", period: "3m" });
  t.c.setSignal({ asOf: lastDay, side: "매수" });                                    // 종목을 밝히지 않은 옛 호출이어도 캐시가 다른 종목이면 건너뛴다
  const duringFlight = log.charts.length;
  await slow; await sleep(10);
  const lastOf = c => c.series[0].data[c.series[0].data.length - 1].close;
  out.flight = { n0, duringFlight, after: log.charts.length, firstClose: lastOf(log.charts[0]), secondClose: lastOf(log.charts[log.charts.length - 1]), want: ohlcFor["000660"][ohlcFor["000660"].length - 1].close };
  // ④ 숨은 칸 — 높이를 못 재면 이번만 150, 다음에 보이면 다시 잰다
  t = fresh(); t.box.style.height = ""; t.box.clientHeight = 0;
  await t.c.draw({ symbol: "005930.KS", period: "3m" }); const h1 = t.box.style.height;
  t.box.clientHeight = 220;
  await t.c.draw({ symbol: "005930.KS", period: "1y" }); const h2 = t.box.style.height;
  t.c.destroy();
  out.hidden = { h1, h2 };
  // ⑤ 이름표 · 색 견본
  t = fresh(); await t.c.draw({ symbol: "005930.KS", period: "3m" });
  const label = { role: t.box.attrs.role, name: t.box.attrs["aria-label"] };
  const bar = t.wrap.children[0];
  const sw = Object.fromEntries(bar.children.map(b => [b.dataset.pcDc, b.children.length]));
  const swColors = bar.children.find(b => b.dataset.pcDc === "macd").children.slice(0, -1).map(s => s.style.background);
  const swHidden = bar.children.find(b => b.dataset.pcDc === "ma20").children[0].attrs["aria-hidden"];
  t.c.destroy();
  out.a11y = { label, sw, swColors, swHidden, afterDestroy: [t.box.attrs.role ?? null, t.box.attrs["aria-label"] ?? null] };
  await t.c.draw({ symbol: "AAPL" }); out.noLabel = [t.box.attrs.role ?? null, t.box.attrs["aria-label"] ?? null];
})();
""")
    ttl = out["ttl"]
    assert ttl["ms"] == 300000 and ttl["first"] == 2 and ttl["cached"] == 2 and ttl["afterExpiry"] == 4, "5분 안에는 다시 받지 않고 지나면 일봉 · 일정을 다시 받는다"
    ev = out["events"]
    assert ev["failedNote"] and ev["retryCalls"] == ["/api/calendar/events"] and not ev["okNote"] and ev["eventNote"], "일정만 다시 받아(일봉은 캐시) 못 받은 채로 두지 않는다"
    assert out["eventsAgain"] == 0, "받고 나면 다시 받지 않는다"
    g = out["sig"]
    assert g["afterOther"] == g["base"] and g["afterSame"] == g["base"] + 1 and g["texts"][-1][0] == "신호 기록", "다른 종목의 신호는 다시 그리지 않고 같은 종목이면 표식"
    fl = out["flight"]
    assert fl["duringFlight"] == fl["n0"] and fl["after"] == fl["n0"] + 1, "다른 종목을 받는 중에 옛 줄로 다시 그리지 않는다(새 종목 한 번만 그림)"
    assert fl["secondClose"] == fl["want"] and fl["firstClose"] != fl["want"], "새로 그린 차트는 새 종목의 줄이다"
    assert out["hidden"]["h1"] == "150px" and out["hidden"]["h2"] == "220px", "숨은 칸이면 150px 로 굳히지 않고 보이게 된 뒤 다시 잰다"
    a = out["a11y"]
    assert a["label"]["role"] == "img" and a["label"]["name"].startswith("005930.KS 3개월 일봉 차트 — 마지막 종가 ") and a["afterDestroy"] == [None, None] and out["noLabel"] == [None, None]
    assert a["sw"]["ma20"] == 2 and a["sw"]["macd"] == 3 and a["sw"]["vol"] == 1 and a["swColors"] == ["#0369a1", "#c2410c"] and a["swHidden"] == "true", "선 칩에는 색 견본(MACD 는 두 선), 견본은 낭독에서 뺀다"
    sc = SC.read_text(encoding="utf-8")
    assert "function scLoadLwc(" in sc and "function loadLwc(" not in sc and "scLoadLwc(doc)" in sc, "다른 차트 파일의 loadLwc 와 이름이 겹치지 않는다"
    assert "#f59e0b" not in sc, "대비가 약한 호박색을 쓰지 않는다"
    drawer = (PUB / "js" / "stockdrawer.js").read_text(encoding="utf-8")
    assert 'b.setAttribute("aria-pressed", String(b === btn))' in drawer and 'aria-pressed="${k === period}"' in drawer, "서랍 · 모달의 기간 칩도 aria-pressed (paper.js 의 칩은 그 파일 몫 — 건드리지 않았다)"
