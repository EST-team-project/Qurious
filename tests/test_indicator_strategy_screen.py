"""TC-ISC — 기본 인디케이터 전략 화면(public/js/indstrategy.js · indicator.js · app.html) B1 ~ B3 · U6 · U7 자리 · 2026-10-29 · #392

바뀐 동작을 한 줄씩 남긴다(#392 이동원 님 부탁).
1. B1 볼린저 — 실제 밴드(종가 vs 상단 · 하단)로 판정한다 · 전일 등락률로 판정하지 않는다. (TC-ISC-01)
2. B2 체크박스 — 고른 지표만 표와 규칙 신호에 들어간다 · MA60 · MACD · 볼린저도 고르면 들어간다. (TC-ISC-02)
3. B3 낱말 — 「규칙 신호 · 매수 쪽 / 매도 쪽」 + 「근거 n개」(결정 대장 10-27) · 「AI 판단」 · 「강력」 · BUY/SELL 안 씀. (TC-ISC-03)
4. 카드 입력 ↔ 카드 — 빈 칸은 보내지 않고 서버가 까닭을 준다 · 저장된 카드를 칸으로 되돌린다 · 한 줄 요약은 쉬운 말. (TC-ISC-04)
5. 화면 연결 — 기존 칸 id 그대로 · 차트 · 카드 편집은 indicator-strategy 화면 안 · 차트는 접을 수 있는 제자리 칸. (TC-ISC-05)
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "public" / "js" / "indstrategy.js"
IND = ROOT / "public" / "js" / "indicator.js"
HTML = ROOT / "public" / "app.html"

ALL = {"ma5": True, "ma20": True, "ma60": True, "rsi": True, "macd": True, "bb": True}


def _chart(close, prev=None, **last):
    """마지막 봉만 의미 있는 가짜 차트 응답 — series 는 [이전 값, 마지막 값]."""
    s = {k: [None, v] for k, v in last.items()}
    return {"bars": [{"time": 1, "close": prev if prev is not None else close}, {"time": 2, "close": close}], "series": s}


def _run(tmp_path: Path, body: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node 가 없어 화면 함수를 돌릴 수 없다")
    script = tmp_path / "run.mjs"
    script.write_text(f'import * as m from "{MOD.resolve().as_uri()}";\nconst out = {{}};\n{body}\n'
                      "process.stdout.write(JSON.stringify(out));\n", encoding="utf-8")
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_b1_bollinger_uses_real_band(tmp_path):
    """TC-ISC-01"""
    # 전일보다 5% 떨어졌지만 하단 밴드 안 → 중립 / 등락이 없어도 하단 밴드 아래 → 매수 쪽
    drop = _chart(95, prev=100, bb_upper=110, bb_lower=90)
    flat_below = _chart(88, prev=88, bb_upper=110, bb_lower=90)
    above = _chart(112, prev=111, bb_upper=110, bb_lower=90)
    out = _run(tmp_path, f"""
      const only = {{bb: true}};
      out.drop = m.buildRows({json.dumps(drop)}, only); out.below = m.buildRows({json.dumps(flat_below)}, only);
      out.above = m.buildRows({json.dumps(above)}, only);
    """)
    assert out["drop"][0][2] == "밴드 안" and out["drop"][0][3] == "중립"
    assert out["below"][0][2] == "종가가 하단 밴드 아래" and out["below"][0][3] == "매수 쪽"
    assert out["above"][0][2] == "종가가 상단 밴드 위" and out["above"][0][3] == "매도 쪽"
    src = IND.read_text(encoding="utf-8")
    assert "chgPct>2?\"상단 돌파\"" not in src and "chgPct<-2?\"매수\"" not in src           # 옛 등락률 판정은 없다


def test_b2_only_checked_indicators(tmp_path):
    """TC-ISC-02"""
    d = _chart(100, ma5=101, ma20=99, ma60=98, rsi=25, macd=1.2, macd_signal=0.8, bb_upper=110, bb_lower=90)
    out = _run(tmp_path, f"""
      const d = {json.dumps(d)};
      out.all = m.buildRows(d, {json.dumps(ALL)}).map(r => r[0]);
      out.noBb = m.buildRows(d, {{...{json.dumps(ALL)}, bb: false}}).map(r => r[0]);
      out.none = m.buildRows(d, {{}}); out.sumNone = m.summarize([]);
      out.ma5only = m.buildRows(d, {{ma5: true}});
    """)
    assert out["all"] == ["5일선 vs 20일선", "종가 vs 60일선", "RSI(14)", "MACD(12 · 26 · 9)", "볼린저밴드(20 · 2σ)"]
    assert "볼린저밴드(20 · 2σ)" not in out["noBb"] and len(out["noBb"]) == 4
    assert out["none"] == [] and out["sumNone"]["n"] == 0 and "고른 지표가 없어" in out["sumNone"]["text"]
    assert out["ma5only"] == []                                                       # 교차 줄은 5일선 · 20일선을 둘 다 골라야


def test_b3_words(tmp_path):
    """TC-ISC-03"""
    d = _chart(100, ma5=101, ma20=99, rsi=50, macd=-1, macd_signal=0, bb_upper=110, bb_lower=90)
    out = _run(tmp_path, f"out.s = m.summarize(m.buildRows({json.dumps(d)}, {json.dumps(ALL)}));")
    s = out["s"]
    assert (s["n"], s["buy"], s["neutral"], s["sell"], s["side"]) == (4, 1, 2, 1, "중립")
    assert s["text"] == "규칙 신호 · 중립 — 근거 4개(매수 쪽 1 · 중립 2 · 매도 쪽 1)"
    w7 = IND.read_text(encoding="utf-8").split("// ── 투자 인디케이터: 커스텀 인디케이터 개발")[0]
    for word in ("AI 판단", "강력", "\"BUY\"", "\"SELL\"", "골든크로스", "데드크로스"):
        assert word not in w7, word
    assert "규칙 신호" in w7 and "근거 ${sum.n}개" in w7


def test_card_inputs_round_trip(tmp_path):
    """TC-ISC-04"""
    card = json.loads((ROOT / "docs/phase-3/02-design/system/예시/strategy-card-ma-cross-v2.json").read_text(encoding="utf-8"))
    out = _run(tmp_path, f"""
      const card = {json.dumps(card, ensure_ascii=False)};
      out.v = m.cardValues(card); out.body = m.cardBody({{slug: "a", short_window: "", long_window: "60", judge: "close"}});
      out.line = m.cardLine(card); out.empty = m.cardValues(null);
    """)
    v = out["v"]
    assert (v["short_window"], v["long_window"], v["atr_period"], v["atr_mult"], v["take_rr"], v["risk_pct"]) == (20, 60, 14, 2.0, 2.0, 1.0)
    assert v["entry_mode"] == "open" and v["judge"] == "close" and v["symbol"] == "005930"
    assert out["body"] == {"slug": "a", "long_window": "60", "judge": "close"}
    assert "20일선이 60일선 위면 매수" in out["line"] and "다음 봉 시가" in out["line"] and "atr" not in out["line"].lower().replace("평균 진폭", "")
    assert out["empty"]["slug"] == "" and out["empty"]["short_window"] == ""


def test_screen_wiring():
    """TC-ISC-05"""
    html = HTML.read_text(encoding="utf-8")
    view = html.split('data-view="indicator-strategy"')[1].split('<div class="view" data-view=')[0]
    for old in ("ind-symbol", "ind-period", "ind-load-btn", "ind-ma5", "ind-ma20", "ind-ma60", "ind-rsi", "ind-macd", "ind-bb",
                "ind-strategy-result", "ind-summary-cards", "ind-analysis-table", "ind-signal-summary"):
        assert f'id="{old}"' in view, old                                             # 기존 칸 id 그대로(#392)
    for new in ("ind-chart-box", "ind-chart", "ind-sub", "ind-card-box", "ic-save", "ic-mine", "ic-judge"):
        assert f'id="{new}"' in view, new                                             # U6 · U7 은 이 화면 안
    assert re.search(r'<details id="ind-chart-box" class="card" open>', view)        # 표 위에 겹치지 않는 제자리 칸 · 접기
    assert "종가 기준" in view                                                         # 손절 · 익절 입력 화면의 문구(#161 Q3)
    for word in ("U6", "U7", "#392", "warmup"):
        assert word not in re.sub(r"<!--.*?-->", "", view, flags=re.S), word          # 화면 글자에 요구 ID · 내부 말 없음
    src = IND.read_text(encoding="utf-8")
    assert "/api/indicator-strategy/chart" in src and "/api/indicator-strategy/cards" in src
    assert 'from "/js/indstrategy.js"' in src


def test_screening_says_why_it_differs():
    """TC-ISC-05 — 스크리닝 표가 다중 주기 신호와 다르게 둔 까닭을 밝힌다(#197 5 · #213 · 10-29)"""
    robo = (ROOT / "public" / "js" / "robo.js").read_text(encoding="utf-8")
    note = robo.split("function renderScreenTable")[1].split("screen-xai-panel")[0]
    assert "다를 수 있습니다" in note and "다르게 둔 까닭" in note
    assert "일봉 규칙 하나" in note and "일 · 주 · 60분" in note and "매일 기록" in note
