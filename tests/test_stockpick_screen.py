"""TC-SPK — 종목 찾기 칸(public/js/stockpick.js) · 전략 분석 화면(quant.js · app.html) · 2026-10-16

무엇을 지키나(Figma 「Qurious · 모의투자 여정 고치기」 03-6 융합안 결정)
1. 판단 함수를 node 로 그대로 돌린다 — 이름표 「삼성전자(005930)」 · 찾기 결과는 수집 DB 다리가 받는 국내 기호만(같은 기호 한 번 ·
   최대 n) · 최근 목록은 맨 앞에 넣고 같은 기호는 앞으로 옮기며 RECENT_MAX 개까지(원래 목록은 그대로) · 펼친 목록 묶음은
   「최근 본 종목」 → 「대표 종목」(최근에 있는 기호는 대표에서 빼고 빈 묶음은 없다). (TC-SPK-01)
2. 화면 기호 규칙 = 서버 다리 규칙 — stockpick.js `SYMBOL_RE` 와 `collector_db._SYMBOL` 이 같은 글을 받는다(한쪽만 바뀌면
   고른 종목이 수집 DB 를 비켜 간다). (TC-SPK-02)
3. 전략 분석 연결 — 고르기 상자(고정 다섯)가 없고 찾기 칸 + 숨은 기호 칸 · 「10년 Mockup」 · 「근 10년」 · 「AI 시그널」 · 어두운 화면
   색(bg-black/20 · text-indigo-300)이 없다 · 찾기는 국내 종목 찾기 API · 최근 목록은 이 화면 이름으로 · CSS 링크. (TC-SPK-03)
4. 콤보 상자 접근성 — role="combobox" · aria-expanded · aria-controls · listbox · option · aria-activedescendant ·
   목록을 누를 때 초점을 잃지 않게(mousedown 막음) · 저장소를 못 써도 멈추지 않는다(try). (TC-SPK-04)
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.services import collector_db

ROOT = Path(__file__).resolve().parents[1]
PUB = ROOT / "public"
SP = PUB / "js" / "stockpick.js"
QUANT = PUB / "js" / "quant.js"
APP_HTML = PUB / "app.html"


def _node() -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node 가 없어 화면 함수를 돌릴 수 없다")
    return node


def _run(tmp_path: Path, body: str) -> dict:
    node = _node()
    script = tmp_path / "run.mjs"
    script.write_text(f'import * as sp from "{SP.resolve().as_uri()}";\nconst out = {{}};\n{body}\n'
                      "process.stdout.write(JSON.stringify(out));\n", encoding="utf-8")
    run = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def test_stockpick_pure_functions_in_node(tmp_path):
    """TC-SPK-01 · 이름표 · 찾기 결과 거르기 · 최근 목록 · 펼친 목록 묶음."""
    out = _run(tmp_path, """
out.label = [sp.labelOf({ symbol: "055550.KS", name: "신한지주" }), sp.labelOf({ symbol: "069500.KS" }), sp.labelOf({ symbol: "AAPL", name: "Apple" })];
out.filtered = sp.filterResults([
  { symbol: "055550.KS", name: "신한지주" }, { symbol: "055550.KS", name: "신한지주(중복)" }, { symbol: "AAPL", name: "Apple" },
  { symbol: "293940.ks", name: "신한알파리츠" }, { symbol: "123456", name: "꼬리 없음" }, { symbol: "035720.KQ", name: "카카오?" }, null,
], 3);
const r0 = [{ symbol: "005930.KS", name: "삼성전자" }, { symbol: "055550.KS", name: "신한지주" }];
out.pushed = sp.pushRecent(r0, { symbol: "055550.KS", name: "신한지주" });
out.r0 = r0;
out.cap = sp.pushRecent([1,2,3,4,5].map(i => ({ symbol: `00000${i}.KS`, name: String(i) })), { symbol: "999999.KQ", name: "새" }).map(x => x.symbol);
out.bad = sp.pushRecent(r0, { symbol: "AAPL", name: "Apple" });
const presets = [{ symbol: "005930.KS", name: "삼성전자" }, { symbol: "000660.KS", name: "SK하이닉스" }];
out.groups = sp.groupsFor([{ symbol: "005930.KS", name: "삼성전자" }], presets).map(g => [g.title, g.items.map(x => x.symbol)]);
out.groupsEmptyRecent = sp.groupsFor([], presets).map(g => g.title);
out.groupsNone = sp.groupsFor([], []);
out.max = sp.RECENT_MAX;
""")
    assert out["label"] == ["신한지주(055550)", "069500", "Apple(AAPL)"], "국내 기호는 코드만 · 그 밖은 기호 그대로"
    assert [x["symbol"] for x in out["filtered"]] == ["055550.KS", "293940.KS", "035720.KQ"]
    assert out["filtered"][0] == {"symbol": "055550.KS", "name": "신한지주", "code": "055550"}
    assert [x["symbol"] for x in out["pushed"]] == ["055550.KS", "005930.KS"], "같은 기호는 맨 앞으로"
    assert [x["symbol"] for x in out["r0"]] == ["005930.KS", "055550.KS"], "원래 목록은 그대로"
    assert out["max"] == 5 and out["cap"] == ["999999.KQ", "000001.KS", "000002.KS", "000003.KS", "000004.KS"]
    assert [x["symbol"] for x in out["bad"]] == ["005930.KS", "055550.KS"], "다리가 못 받는 기호는 최근 목록에 넣지 않는다"
    assert out["groups"] == [["최근 본 종목", ["005930.KS"]], ["대표 종목", ["000660.KS"]]]
    assert out["groupsEmptyRecent"] == ["대표 종목"] and out["groupsNone"] == []


def test_symbol_rule_matches_collector_bridge(tmp_path):
    """TC-SPK-02 · 화면 기호 규칙 = 수집 DB 다리 규칙 — 같은 표본에 같은 판정."""
    samples = ["005930.KS", "035720.KQ", "005930", "005930.KN", "AAPL", "05930.KS", "0059300.KS", "005930.ks"]
    out = _run(tmp_path, f"out.js = {json.dumps(samples)}.map(s => sp.SYMBOL_RE.test(s));")
    py = [bool(collector_db._SYMBOL.match(s)) for s in samples]
    assert out["js"] == py, (out["js"], py)


def _quant_backtest_html() -> str:
    src = APP_HTML.read_text(encoding="utf-8")
    i = src.index('data-view="quant-backtest"')
    return src[i:src.index('<div id="bt-result"', i)]


def test_quant_backtest_wiring():
    """TC-SPK-03 · 전략 분석 — 찾기 칸 · 숨은 기호 칸 · 옛 낱말 · 어두운 화면 색 없음 · 찾기 API · 최근 목록 이름 · CSS."""
    html = _quant_backtest_html()
    assert '<div id="bt-symbol-pick"></div>' in html and '<input type="hidden" id="bt-symbol" value="005930.KS" />' in html
    for bad in ("<select id=\"bt-symbol\"", "Mockup", "근 10년", "대표 5종목", "text-slate-400"):
        assert bad not in html, f"전략 분석 머리에 {bad}"
    q = QUANT.read_text(encoding="utf-8")
    code = "\n".join(ln for ln in q.splitlines() if not ln.lstrip().startswith("//"))
    i = code.index('getElementById("bt-load")')
    block = code[i:code.index("export {", i)]
    for bad in ("10년 퀀트 분석", "AI 시그널", "bg-black/20", "text-indigo-300", "10년치"):
        assert bad not in block, f"전략 분석 결과에 {bad}"
    assert "규칙 신호(RSI · 이동평균 · 볼린저 합산)" in block and "btLabel(symbol)" in block
    assert 'from "/js/stockpick.js"' in code and "mountStockPick(btHost" in code
    assert "/api/stocks/search?q=" in code and '"qurious.recent.quant-backtest"' in code
    assert '<link rel="stylesheet" href="/css/stockpick.css" />' in APP_HTML.read_text(encoding="utf-8")


def test_combobox_accessibility_markup():
    """TC-SPK-04 · 콤보 상자 접근성 · 목록을 누를 때 초점 · 저장소 실패에 멈추지 않음."""
    src = SP.read_text(encoding="utf-8")
    for need in ('role="combobox"', 'aria-autocomplete="list"', 'aria-expanded="false"', "aria-controls=", 'role="listbox"',
                 'role="option"', "aria-activedescendant", 'addEventListener("mousedown", ev => ev.preventDefault())',
                 '"ArrowDown"', '"ArrowUp"', '"Enter"', '"Escape"'):
        assert need in src, need
    assert re.search(r"function readRecent[\s\S]*?try \{[\s\S]*?catch", src) and re.search(r"function writeRecent[\s\S]*?try \{", src)
