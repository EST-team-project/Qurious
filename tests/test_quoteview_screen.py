"""TC-QVS — 시세 표시 화면(public/js/quoteview.js · us.js · ml.js · app.html 미국주식 대시보드) · 2026-10-16

무엇을 지키나(Figma 「Qurious · 모의투자 여정 고치기」 03-5 융합안 결정 · 서버 짝은 TC-QL)
1. 판단 모듈을 node 로 그대로 돌린다 — 등락률 글은 common.js `fmtPct` 와 같은 꼴 · 모르면 「—」(0 으로 메우지 않는다) ·
   ±MOVE_LIMIT 를 넘을 때만 「▲ 크게 오름 · ▼ 크게 내림」(문턱 그대로 · 보합권 · 모름은 빈 글 · BUY · SELL 낱말 없음) ·
   서버 시세 시각 → 「마지막 체결 MM-DD HH:MM(KST)」(꼴이 다르면 빈 글 — 지어내지 않는다). (TC-QVS-01)
2. 미국주식 대시보드는 지연 시세를 실시간이라 부르지 않는다 — 「● LIVE」 · 「실시간 시세」 · 「AI 시그널 (Big Tech」 이
   app.html 에 없고, 칸 제목의 종목 수 · 문턱 숫자는 화면에 따로 적지 않는다(수는 응답 줄 수 · 문턱은 MOVE_LIMIT 한 곳). (TC-QVS-02)
3. us.js 는 서버 값을 그대로 쓴다 — 예시 가격(mockUsPrice) 길이 없고(말없는 fallback) · 머리 글은 응답 `note` ·
   등락률은 서버 `change_p` · `change_pct`(화면이 전일 종가로 다시 셈하지 않는다) · 차트 머리에 시세 시각 · 판단 모듈을 부른다. (TC-QVS-03)
4. 거시경제 지표 · 산업 분석은 모르는 등락을 「▲ 0.00%」 로 그리지 않는다(서버가 None 을 준다 · DF-123). (TC-QVS-04)
5. 거시경제 지표 · 산업 분석도 숫자 아래에 서버 출처 글(응답 `note` — 지연 시세 · 받은 시각)을 그대로 한 줄 보인다(2026-10-19). (TC-QVS-05)
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
QV = PUB / "js" / "quoteview.js"
US = PUB / "js" / "us.js"
ML = PUB / "js" / "ml.js"
COMMON = PUB / "js" / "common.js"
APP_HTML = PUB / "app.html"


def _node() -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node 가 없어 화면 함수를 돌릴 수 없다")
    return node


def _run(tmp_path: Path, body: str, extra_import: str = "") -> dict:
    """quoteview.js 를 node 로 불러 body(그 안에서 out 을 채움)를 돌린다 — 화면 파일을 바꾸지 않는다."""
    node = _node()
    script = tmp_path / "run.mjs"
    script.write_text(f'import * as qv from "{QV.resolve().as_uri()}";\n{extra_import}\nconst out = {{}};\n{body}\n'
                      "process.stdout.write(JSON.stringify(out));\n", encoding="utf-8")
    run = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def _us_dashboard_html() -> str:
    src = APP_HTML.read_text(encoding="utf-8")
    i = src.index('data-view="us-dashboard"')
    return src[i:src.index('data-view="us-chart"', i)]


def test_quoteview_rules_in_node(tmp_path):
    """TC-QVS-01 · 등락률 글 · ±문턱 표시 · 시세 시각 글을 node 로 — fmtPct 와 숫자 꼴이 같다(모름만 「—」)."""
    out = _run(tmp_path, """
const vals = [0.27, -0.28, 0, 1.5, -1.5, 1.4999, -1.84, 2.13, null, undefined, NaN, "1.2"];
out.pct = vals.map(qv.pctText);
out.tag = vals.map(v => qv.moveTag(v));
out.dir = vals.map(qv.direction);
out.limit = qv.MOVE_LIMIT;
out.asof = ["2026-10-16 05:00", "2026-10-16T05:00", "", null, "10-16 05:00"].map(qv.asOfText);
out.fmt = [0.27, -0.28, 0, -1.84].map(fmtPct);
""", extra_import=f'import {{ fmtPct }} from "{COMMON.resolve().as_uri()}";')
    assert out["limit"] == 1.5
    assert out["pct"][:8] == ["+0.27%", "-0.28%", "+0.00%", "+1.50%", "-1.50%", "+1.50%", "-1.84%", "+2.13%"]
    assert out["pct"][8:] == ["—", "—", "—", "—"], "모르는 값 · 글자는 0 으로 메우지 않는다"
    assert out["fmt"] == [out["pct"][0], out["pct"][1], out["pct"][2], out["pct"][6]], "숫자 꼴은 common.js fmtPct 와 같다"
    texts = [t["text"] for t in out["tag"]]
    assert texts == ["", "", "", "▲ 크게 오름", "▼ 크게 내림", "", "▼ 크게 내림", "▲ 크게 오름", "", "", "", ""]
    assert all("BUY" not in t and "SELL" not in t and "매수" not in t and "매도" not in t for t in texts)
    assert [t["dir"] for t in out["tag"]][3:5] == ["up", "down"]
    assert out["dir"][:3] == ["up", "down", "flat"] and set(out["dir"][8:]) == {"none"}
    assert out["asof"] == ["마지막 체결 10-16 05:00(KST)", "", "", "", ""], "꼴이 다르면 지어내지 않는다"


def test_us_dashboard_html_does_not_say_live():
    """TC-QVS-02 · 미국주식 대시보드 머리 — 실시간 · LIVE · AI 시그널 · 고정 종목 수 · 문턱 숫자가 없다 · 지연 시세 칩 · 빈 수 · 규칙 칸."""
    html = _us_dashboard_html()
    for bad in ("LIVE", "실시간", "AI 시그널", "Big Tech", "1.5%"):
        assert bad not in html, f"대시보드 머리에 {bad}"
    assert ">지연 시세</span>" in html and "야후 파이낸스 지연 시세" in html
    assert '<span id="us-signal-count"></span>' in html, "종목 수는 응답 줄 수로 채운다(빈 칸)"
    assert re.search(r'<p id="us-signal-rule"[^>]*></p>', html), "규칙 글은 MOVE_LIMIT 로 채운다(빈 칸)"


def test_us_js_uses_server_values_and_no_mock():
    """TC-QVS-03 · us.js — 예시 가격 길 없음 · 머리 글 = 응답 note · 등락률 = 서버 값 · 시세 시각 · 판단 모듈 · 「시세를 받지 못했습니다」."""
    src = US.read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("//"))
    assert "mockUsPrice" not in code and "실시간 데이터" not in code
    i = code.index("async function loadUsDashboard")
    dash = code[i:code.index("\n}\n", i)]
    for bad in ('"BUY"', '"SELL"', '"HOLD"', "prev_close) / ", "?? 0;", "Yahoo Finance"):
        assert bad not in dash, f"대시보드 함수에 {bad}"
    assert 'from "/js/quoteview.js"' in src and "MOVE_LIMIT" in code
    assert "escHtml(resp.note)" in code, "머리 글은 서버가 지은 글 그대로(이스케이프)"
    assert "s.change_p ?? s.change_pct" in code and "pctText(q.change_pct)" in code and "pctText(quote.change_pct)" in code
    assert "asOfText(quote.as_of)" in code and "지연 시세" in code
    assert "시세를 받지 못했습니다" in code
    assert "us-signal-count" in code and "us-signal-rule" in code


def test_macro_screens_show_dash_for_unknown_change():
    """TC-QVS-04 · 거시경제 지표 · 산업 분석 — change_p 가 숫자가 아니면 화살표 · 0.00% 대신 「—」."""
    src = ML.read_text(encoding="utf-8")
    for fn, var in (("async function loadMacroDashboard", "ind"), ("async function loadMacroIndustry", "s")):
        i = src.index(fn)
        body = src[i:src.index("\n}\n", i)]
        assert f'const known = typeof {var}.change_p === "number";' in body, fn
        guarded = '${known ? `${isUp ? "▲" : "▼"} ${Math.abs(' + var + '.change_p).toFixed(2)}%` : "—"}'
        assert guarded in body, f"{fn} — 화살표 · % 는 숫자일 때만"
        assert body.count("Math.abs(") == 1, f"{fn} — 지키지 않은 Math.abs 가 남았다"


def test_macro_screens_show_server_quote_note():
    """TC-QVS-05 · 거시경제 지표 · 산업 분석 — 숫자 아래 출처 · 받은 시각 한 줄은 응답 `note` 그대로(화면이 글을 만들지 않는다)."""
    src = ML.read_text(encoding="utf-8")
    helper = src[src.index("function macroQuoteNote"):src.index("async function loadMacroDashboard")]
    assert "el.textContent = note || \"\";" in helper and "innerHTML" not in helper      # 서버 글은 글자로만
    for fn, call in (("async function loadMacroDashboard", 'macroQuoteNote(grid, "macro-note", data.note);'),
                     ("async function loadMacroIndustry", 'macroQuoteNote(wrap, "industry-note", data.note);')):
        i = src.index(fn)
        body = src[i:src.index("\n}\n", i)]
        assert call in body, f"{fn} — 응답 note 를 그리지 않는다"
    assert "야후" not in helper and "지연 시세" not in helper                                  # 출처 낱말은 서버 한 곳
