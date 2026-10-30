"""TC-CCH — TradingView ↔ LEAN 대사 결과를 가격 차트 위에 얹는 판단(public/js/comparechart.js · tradingview.js) · 2026-10-30 · ①-15

서버(강민석 님 코드)는 안 바꾸고 응답의 fill_comparison.rows · signal_comparison.mismatch_dates 를 화면이 읽는다.
1. 체결 표시는 응답 행 그대로 — TradingView(화살표) · LEAN(동그라미) 두 갈래, 짝 없는 체결은 글에 「짝 없음」. (TC-CCH-01)
2. 어긋난 날은 서버가 준 날짜뿐이고, 비교하지 않은 층은 표시 대신 서버 까닭을 적는다. LEAN 미실행이면 그 사실을 적는다. (TC-CCH-02)
3. 손절 · 익절 선은 응답에 값이 없어 그리지 않고, 그리지 않았다고 적는다. (TC-CCH-03)
4. 캔들 기간 고르기 · 봉 날짜 변환(초 단위 UTC) · 차트에 봉이 없는 날의 표시는 숨기지 않고 센다 · 데이터 기준일 줄. (TC-CCH-04)
5. 화면이 새 모듈을 부르고, 차트 위에 새로 셈하는 판정 · 색 기준이 화면 코드에 없다. (TC-CCH-05)
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CC = ROOT / "public" / "js" / "comparechart.js"
TVJS = ROOT / "public" / "js" / "tradingview.js"

# S168 ①-11 실제 대사와 같은 모양 — TV 9-29 매수 266,500 · LEAN 9-30 매수 268,768.5 · 청산 10-23 둘 다
FILL = {
    "status": "compared",
    "rows": [
        {"match_status": "paired", "tradingview_comparison_date": "2026-09-29", "lean_comparison_date": "2026-09-30",
         "tradingview_side": "buy", "lean_side": "buy", "tradingview_price": 266500, "lean_fill_price": 268768.5},
        {"match_status": "paired", "tradingview_comparison_date": "2026-10-23", "lean_comparison_date": "2026-10-23",
         "tradingview_side": "sell", "lean_side": "sell", "tradingview_price": 205500, "lean_fill_price": 215284.5},
    ],
}
SIG = {"status": "compared", "mismatch_dates": [{"date": "2026-09-29"}, {"date": "2026-09-30"}], "mismatch_dates_truncated": False}
R_OK = {"ticker": "005930.KS", "period": {"start": "2026-09-01", "end": "2026-10-27"}, "lean": {"lean_ok": True},
        "fill_comparison": FILL, "signal_comparison": SIG}


def _run(tmp_path: Path, body: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node 가 없어 화면 함수를 돌릴 수 없다")
    script = tmp_path / "run.mjs"
    script.write_text(f'import * as cc from "{CC.resolve().as_uri()}";\n'
                      f"const R_OK = {json.dumps(R_OK, ensure_ascii=False)};\n"
                      f"const out = {{}};\n{body}\nprocess.stdout.write(JSON.stringify(out));\n", encoding="utf-8")
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_TC_CCH_01_체결_표시는_응답_행_그대로(tmp_path):
    o = _run(tmp_path, "out.o = cc.overlayFromResult(R_OK);")["o"]
    by = {(m["kind"], m["time"]): m for m in o["markers"]}
    assert set(by) == {("tv", "2026-09-29"), ("lean", "2026-09-30"), ("tv", "2026-10-23"), ("lean", "2026-10-23")}
    tv_buy = by[("tv", "2026-09-29")]
    assert (tv_buy["shape"], tv_buy["position"], tv_buy["price"]) == ("arrowUp", "belowBar", 266500)
    assert by[("lean", "2026-09-30")]["shape"] == "circle" and by[("lean", "2026-09-30")]["price"] == 268768.5
    assert by[("tv", "2026-10-23")]["position"] == "aboveBar"
    assert o["counts"]["tv"] == 2 and o["counts"]["lean"] == 2 and o["counts"]["paired"] == 2
    assert all("짝 없음" not in m["text"] for m in o["markers"])


def test_TC_CCH_01_짝_없는_체결은_글에_짝_없음(tmp_path):
    body = ('const r = JSON.parse(JSON.stringify(R_OK)); r.fill_comparison.rows = [{match_status:"unmatched_lean", '
            'lean_comparison_date:"2026-09-30", lean_side:"buy", lean_fill_price: 1}];'
            "out.o = cc.overlayFromResult(r);")
    o = _run(tmp_path, body)["o"]
    assert len(o["markers"]) == 1 and "짝 없음" in o["markers"][0]["text"] and o["counts"]["leanOnly"] == 1


def test_TC_CCH_02_어긋난_날과_비교_안_한_층(tmp_path):
    o = _run(tmp_path, "out.o = cc.overlayFromResult(R_OK);")["o"]
    assert o["mismatchDays"] == ["2026-09-29", "2026-09-30"]
    body = ('const r = {ticker:"X", period:{start:"2026-09-01", end:"2026-10-27"}, lean:{lean_ok:false}, '
            'fill_comparison:{status:"not_requested", reason:"거래 목록 CSV가 없어 체결을 비교하지 않았습니다."}, '
            'signal_comparison:{status:"not_requested", reason:"신호 CSV가 없습니다."}};'
            "out.o = cc.overlayFromResult(r);")
    o = _run(tmp_path, body)["o"]
    assert o["markers"] == [] and o["mismatchDays"] == [] and o["fromLean"] is False
    joined = " | ".join(o["notes"])
    assert "거래 목록 CSV가 없어" in joined and "신호 CSV가 없습니다" in joined and "LEAN 이 실행되지 않아" in joined


def test_TC_CCH_03_손절_익절_선은_그리지_않고_그렇다고_적는다(tmp_path):
    o = _run(tmp_path, "out.o = cc.overlayFromResult(R_OK); out.note = cc.NO_STOP_NOTE;")
    assert o["note"] in o["o"]["notes"] and "그리지 않았습니다" in o["note"]
    src = CC.read_text(encoding="utf-8")
    assert "stop_loss" not in src and "take_profit" not in src and "createPriceLine" not in src


def test_TC_CCH_04_기간_봉_날짜_기준일(tmp_path):
    body = ('out.p1 = cc.periodFor("2026-09-01","2026-10-30"); out.p2 = cc.periodFor("2020-01-01","2026-10-30");'
            'out.p3 = cc.periodFor("2013-01-01","2026-10-30");'
            "out.d = cc.barDay({time: 1790640000});"  # 2026-09-29T00:00:00Z
            'out.bars = cc.toChartBars([{time:1790640000,open:1,high:2,low:0.5,close:1.5},{time:1,open:1,high:2,low:0.5,close:1.5},'
            '{time:1790726400,open:null,high:2,low:0.5,close:1.5}], "2026-09-01", "2026-10-27");'
            'out.fit = cc.fitToBars(cc.overlayFromResult(R_OK), ["2026-09-30","2026-10-23"]);'
            'out.asof = cc.asOfLine({source:"collector", as_of:"2026-10-29", candles:[]}, false);'
            'out.asof2 = cc.asOfLine({source:"collector", candles:[{time:1790640000}]}, true);')
    o = _run(tmp_path, body)
    assert o["p1"] == {"period": "3mo", "truncated": False}
    assert o["p2"]["period"] == "10y" and o["p2"]["truncated"] is False and o["p3"] == {"period": "10y", "truncated": True}
    assert o["d"] == "2026-09-29"
    assert [b["time"] for b in o["bars"]] == ["2026-09-29"]  # 시작 열흘 앞보다 이른 봉 · 값이 빈 봉은 뺀다
    assert {m["time"] for m in o["fit"]["markers"]} == {"2026-09-30", "2026-10-23"}
    assert any("차트에 봉이 없는 날의 체결 표시 1건" in n for n in o["fit"]["notes"])
    assert any("차트에 봉이 없는 어긋난 날 1일" in n for n in o["fit"]["notes"])
    assert o["asof"] == "차트 데이터 기준일 2026-10-29 · 수집 DB 일봉"
    assert o["asof2"] == "차트 데이터 기준일 2026-09-29 · 수집 DB 일봉 · 요청 기간이 길어 최근 10년만 보입니다"


def test_TC_CCH_05_화면이_새_모듈을_부르고_판정을_새로_셈하지_않는다():
    tv = TVJS.read_text(encoding="utf-8")
    assert '"/js/comparechart.js"' in tv and "drawPriceChart(r)" in tv and 'id="tvc-price"' in tv
    assert "/api/stocks/candles" in tv
    for bad in ("일치", "불일치", "tolerance", "PRICE_TOL"):
        assert bad not in CC.read_text(encoding="utf-8"), bad
