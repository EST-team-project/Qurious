"""TC-TV2 — 기술적 분석 화면의 지표 값 칸(public/js/techview.js · ml.js · app.html) · 2026-10-29 · 할 일 ①-10

옛 화면은 캔들 패턴 · 엘리어트 파동 설명 글뿐이었다(점검표 40 · 설명 전용). 설명 위에 이 종목의 지표 값을 얹었다.
1. 값은 응답 배열의 마지막 값 그대로 · 끝이 비면(워밍업 · 결측) 앞의 오래된 값으로 대신하지 않고 줄표 · 종가는 「마지막 종가」 + 기준일 +
   「지금 가격이 아닙니다」 · 출처 글(data_note)은 서버 글 그대로. (TC-TV2-01)
2. 규칙 신호는 점수와 서버가 준 근거 문장만 — 판정 낱말(action)을 따로 내세우지 않는다. (TC-TV2-02)
3. 실패 · 데이터 부족 · 잘못된 종목코드는 서버 까닭 · 안내를 보이고 깨지지 않는다. (TC-TV2-03)
4. 화면에 적는 지표 인자(RSI 14 · 이동평균 5/20/60 · 볼린저 20일 2σ)가 서버 코드의 기본값과 같다 — 코드를 바꾸면 이 시험이 설명을 다시 보게 한다. (TC-TV2-04)
5. app.html 에 칸이 있고 ml.js 가 techview.js 를 부른다. (TC-TV2-05)
"""
from __future__ import annotations

import inspect
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TV = ROOT / "public" / "js" / "techview.js"

ESC = ('const esc = s => String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")'
       '.replace(/"/g,"&quot;").replace(/\'/g,"&#39;");')

DATA = {
    "symbol": "005930.KS", "current_price": 72300, "as_of": "2026-10-28",
    "rsi": [None, 55.1, 61.234], "ma5": [71000, 72010.4], "ma20": [70000, 70900.5], "ma60": [None, 68000.2],
    "bb_upper": [74000, 75010.6], "bb_mid": [70000, 70900.5], "bb_lower": [66000, 66790.4],
    "signal": {"action": "강력 매수", "color": "green", "score": 4,
               "reasons": ["RSI 중립 (61.2)", "골든크로스 (강력 매수)", "단기 이평 > 중기 이평 (매수 우위)"]},
    "data_note": "수집 DB 일봉 · 2026-10-28 기준 마지막 종가", "definition": "tv-2026", "source": "collector",
}


def _run(tmp_path: Path, body: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node 가 없어 화면 함수를 돌릴 수 없다")
    script = tmp_path / "run.mjs"
    script.write_text(f'import * as tv from "{TV.resolve().as_uri()}";\n{ESC}\nconst DATA = {json.dumps(DATA, ensure_ascii=False)};\n'
                      f"const out = {{}};\n{body}\nprocess.stdout.write(JSON.stringify(out));\n", encoding="utf-8")
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_values_are_last_values_with_provenance(tmp_path):
    """TC-TV2-01 — 마지막 값 그대로 · 끝이 비면 줄표 · 종가는 마지막 종가 + 기준일."""
    out = _run(tmp_path, """
      out.html = tv.renderTechnical({data: DATA}, esc);
      out.last = [tv.lastValue([1, 2, 3]), tv.lastValue([1, 2, null]), tv.lastValue([]), tv.lastValue(null), tv.lastValue(["x"])];
      out.gap = tv.renderTechnical({data: {...DATA, ma60: [68000, null]}}, esc);
    """)
    html = out["html"]
    assert "72,300원" in html and "2026-10-28 기준 · 지금 가격이 아닙니다" in html and "마지막 종가" in html
    assert "RSI (14일)" in html and "61.2" in html                                   # 소수 첫째 자리
    assert "5일선 <strong>72,010</strong>" in html and "20일선 <strong>70,901</strong>" in html and "60일선 <strong>68,000</strong>" in html
    assert "상단 <strong>75,011</strong>" in html and "중심 <strong>70,901</strong>" in html and "하단 <strong>66,790</strong>" in html
    assert "볼린저 밴드 (20일 · 2σ)" in html
    assert "수집 DB 일봉 · 2026-10-28 기준 마지막 종가" in html and "지표 정의 tv-2026" in html   # 서버 글 · 정의 이름
    assert out["last"] == [3, None, None, None, None]
    assert "60일선 <strong>—</strong>" in out["gap"] and "68,000" not in out["gap"]   # 끝이 비면 앞의 값으로 대신하지 않는다


def test_signal_shows_score_and_reasons_only(tmp_path):
    """TC-TV2-02 — 점수 + 서버 근거 문장만 · 판정 낱말을 따로 내세우지 않는다."""
    out = _run(tmp_path, "out.html = tv.renderTechnical({data: DATA}, esc);")
    html = out["html"]
    assert "규칙 점수 <strong>+4</strong>" in html and "매매 권유가 아닙니다" in html
    assert "RSI 중립 (61.2)" in html and "골든크로스 (강력 매수)" in html              # 서버가 쓴 문장은 그대로
    assert "강력 매수</strong>" not in html and 'color:green' not in html              # action 을 제목처럼 내세우지 않는다


def test_failures_show_reason(tmp_path):
    """TC-TV2-03 — 실패 · 데이터 부족 · 코드 오류."""
    out = _run(tmp_path, """
      out.err = tv.renderTechnical({err: {message: "서버에 연결할 수 없습니다."}}, esc);
      out.short = tv.renderTechnical({data: {symbol: "X", error: "데이터 부족"}}, esc);
      out.none = tv.renderTechnical({}, esc);
      out.bad = await tv.loadTechnical(async () => { throw new Error("호출되면 안 된다"); }, "../x");
      out.ok = await tv.loadTechnical(async path => ({path}), "005930.KS");
      out.failMsg = (await tv.loadTechnical(async () => { throw new Error("401"); }, "005930.KS")).err.message;
      out.badMsg = out.bad.err.message;
    """)
    assert "서버에 연결할 수 없습니다." in out["err"] and "데이터 부족" in out["short"] and "지표를 받지 못했습니다." in out["none"]
    assert out["badMsg"] == "종목코드가 올바르지 않습니다."
    assert out["ok"]["data"]["path"] == "/api/stocks/quant/indicators?symbol=005930.KS&period=2y"
    assert out["failMsg"] == "401"


def test_params_match_server_defaults():
    """TC-TV2-04 — 화면이 적는 지표 인자가 서버 코드의 기본값과 같다."""
    from app.services import stock

    assert inspect.signature(stock._calc_rsi).parameters["period"].default == 14
    bb = inspect.signature(stock._calc_bollinger).parameters
    assert bb["period"].default == 20 and bb["std_mult"].default == 2.0
    src = inspect.getsource(stock.get_quant_indicators)
    for n in (5, 20, 60):
        assert f"_calc_sma(closes, {n})" in src
    js = TV.read_text(encoding="utf-8")
    assert "rsiPeriod: 14" in js and "ma: [5, 20, 60]" in js and "bbPeriod: 20, bbStd: 2" in js


def test_wired_into_page():
    """TC-TV2-05 — app.html 칸 · ml.js 연결."""
    html = (ROOT / "public" / "app.html").read_text(encoding="utf-8")
    ml = (ROOT / "public" / "js" / "ml.js").read_text(encoding="utf-8")
    for ident in ('id="tech-symbol"', 'id="tech-run-btn"', 'id="tech-cards"'):
        assert html.count(ident) == 1, ident
    assert 'from "/js/techview.js"' in ml and "loadTechnical(api," in ml and "renderTechnical(" in ml
    assert re.search(r'getElementById\("tech-run-btn"\)\?\.addEventListener\("click"', ml)
