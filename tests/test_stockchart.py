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
    assert "스탑가" not in out["sum"] and "빨간 점선은 입력한 스탑가 210,400원" in out["sumStop"]
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
