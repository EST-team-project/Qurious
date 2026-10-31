"""TC-SFD — 종목 찾기 단추(public/js/stockfind.js) · 종목 입력칸 12곳 · 2026-10-31

무엇을 지키나(Figma 「Qurious · 종목 찾기 단추」 · 사용자 결정 10-31 「입력은 유지하고 검색 창으로 고른다」)
1. 판단 함수를 node 로 그대로 돌린다 — 고른 종목이 칸에 넣을 글(국내는 6자리로 줄이는 모드 · 해외는 기호 그대로) ·
   단추를 달 칸 거르기. 국내 기호 꼴은 stockpick.js `SYMBOL_RE` 와 같다. (TC-SFD-01)
2. 가짜 문서에서 단추를 달고 눌러 본다 — 칸마다 단추 하나 · 두 번 달지 않음 · 누르면 검색 창이 열리고 고르면 칸(과 이름 칸)이
   채워지며 화면 코드가 듣는 입력 · 변경 이벤트가 간다. (TC-SFD-02)
3. 화면 연결 — app.html 의 12칸에 속성이 있고 이름 칸 연결이 실재하며, company.js 가 창 열기를 내보내고 main.js 가 단추를
   단다. 검색 창은 새로 만들지 않고 기존 `stock-search-modal` 을 쓴다. (TC-SFD-03)
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
SF = PUB / "js" / "stockfind.js"
SP = PUB / "js" / "stockpick.js"
COMPANY = PUB / "js" / "company.js"
MAIN = PUB / "js" / "main.js"
APP_HTML = PUB / "app.html"

# 속성이 달려야 하는 12칸(칸 id → 모드). 칸을 더하거나 빼면 이 표와 화면을 함께 고친다.
EXPECTED = {
    "ord-symbol": "symbol", "ps-symbol": "symbol", "ps-stop-symbol": "symbol", "ql-ticker": "symbol",
    "us-symbol": "symbol", "us-ord-symbol": "symbol", "fx-symbol": "symbol", "pc-symbol": "code",
    "tvc-ticker": "symbol", "rb-add-symbol": "symbol", "rb-cf-symbol": "code", "pt-symbol": "symbol",
}


def _node() -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node 가 없어 화면 함수를 돌릴 수 없다")
    return node


def _run(tmp_path: Path, body: str) -> dict:
    node = _node()
    script = tmp_path / "run.mjs"
    script.write_text(f'import * as sf from "{SF.resolve().as_uri()}";\nconst out = {{}};\n{body}\n'
                      "process.stdout.write(JSON.stringify(out));\n", encoding="utf-8")
    run = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def test_stockfind_pure_functions_in_node(tmp_path):
    """TC-SFD-01 · 칸에 넣을 글 · 단추를 달 칸 거르기 · 국내 기호 꼴."""
    out = _run(tmp_path, """
out.sym = [sf.valueFor({ symbol: "005930.KS", name: "삼성전자" }, "symbol"), sf.valueFor({ symbol: "AAPL" }, "symbol")];
out.code = [sf.valueFor({ symbol: "005930.KS" }, "code"), sf.valueFor({ symbol: "035720.kq" }, "code"), sf.valueFor({ symbol: "AAPL" }, "code")];
out.empty = [sf.valueFor(null, "symbol"), sf.valueFor({}, "code")];
const mk = (tag, ds) => ({ tagName: tag, dataset: ds });
out.mount = [sf.shouldMount(mk("INPUT", { stockFind: "symbol" })), sf.shouldMount(mk("INPUT", {})),
  sf.shouldMount(mk("SELECT", { stockFind: "symbol" })), sf.shouldMount(mk("INPUT", { stockFind: "symbol", stockFindMounted: "1" })), sf.shouldMount(null)];
out.re = sf.DOMESTIC_RE.source;
""")
    assert out["sym"] == ["005930.KS", "AAPL"], "기호 모드는 그대로 넣는다"
    assert out["code"] == ["005930", "035720", "AAPL"], "코드 모드는 국내만 6자리 · 해외는 기호 그대로"
    assert out["empty"] == ["", ""]
    assert out["mount"] == [True, False, False, False, False], "속성이 있는 INPUT 이고 아직 안 단 칸만"
    pick = re.search(r"SYMBOL_RE\s*=\s*/(.+?)/;", SP.read_text(encoding="utf-8"))
    assert pick and pick.group(1) == out["re"], "국내 기호 꼴이 stockpick.js 와 갈라지면 고른 종목이 다리를 비켜 간다"


FAKE_DOM = """
class El {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.dataset = {}; this.children = []; this.parentNode = null; this.l = {}; this.value = ""; this.attrs = {}; this.className = ""; this.focused = false; }
  appendChild(c) { if (c.parentNode) c.parentNode.children = c.parentNode.children.filter(x => x !== c); c.parentNode = this; this.children.push(c); return c; }
  insertBefore(n, ref) { n.parentNode = this; this.children.splice(this.children.indexOf(ref), 0, n); return n; }
  setAttribute(k, v) { this.attrs[k] = v; }
  addEventListener(t, f) { (this.l[t] = this.l[t] || []).push(f); }
  dispatchEvent(e) { (this.l[e.type] || []).forEach(f => f(e)); return true; }
  click() { (this.l.click || []).forEach(f => f({})); }
  focus() { this.focused = true; }
}
const parent = new El("div");
const ord = new El("input"); ord.dataset.stockFind = "symbol"; ord.dataset.stockName = "ord-name"; ord.id = "ord-symbol";
const name = new El("input"); name.id = "ord-name";
const pine = new El("input"); pine.dataset.stockFind = "code"; pine.id = "pc-symbol";
const plain = new El("input"); plain.id = "plain";
[ord, name, pine, plain].forEach(e => parent.appendChild(e));
const events = [];
for (const e of [ord, name, pine]) { e.addEventListener("input", ev => events.push([e.id, ev.type])); e.addEventListener("change", ev => events.push([e.id, ev.type])); }
const byId = { "ord-name": name };
const doc = {
  createElement: t => new El(t),
  querySelectorAll: () => [ord, name, pine, plain].filter(e => e.dataset.stockFind !== undefined),
  getElementById: id => byId[id] || null,
  defaultView: { Event: class { constructor(type) { this.type = type; } } },
};
let opened = 0, cb = null;
const open = fn => { opened += 1; cb = fn; };
"""


def test_stockfind_mounts_and_fills_in_fake_dom(tmp_path):
    """TC-SFD-02 · 단추 달기 · 두 번 달지 않음 · 누르면 열리고 고르면 칸 · 이름 칸이 채워짐."""
    out = _run(tmp_path, FAKE_DOM + """
out.first = sf.mountStockFind(doc, open);
out.second = sf.mountStockFind(doc, open);
out.noOpen = sf.mountStockFind(doc, null);
const wrapOf = e => e.parentNode;
out.wrapped = [wrapOf(ord).className, wrapOf(pine).className, wrapOf(plain).className === "sf-wrap"];
const btn = wrapOf(ord).children.find(c => c.tagName === "BUTTON");
out.btn = [btn.className, btn.attrs["aria-label"], btn.type];
btn.click();
out.opened = opened;
cb({ symbol: "005930.KS", name: "삼성전자" });
out.filled = [ord.value, name.value, ord.focused];
const btn2 = wrapOf(pine).children.find(c => c.tagName === "BUTTON");
btn2.click(); cb({ symbol: "000660.KS", name: "SK하이닉스" });
out.code = pine.value;
out.events = events.filter(e => e[0] === "ord-symbol").map(e => e[1]).concat(events.filter(e => e[0] === "ord-name").map(e => e[1]));
""")
    assert out["first"] == 2 and out["second"] == 0 and out["noOpen"] == 0, "칸 수만큼 달고 두 번은 달지 않는다"
    assert out["wrapped"] == ["sf-wrap", "sf-wrap", False], "속성이 없는 칸은 그대로 둔다"
    assert out["btn"] == ["sf-btn", "종목 찾기 — 이름이나 코드로 검색", "button"]
    assert out["opened"] == 1
    assert out["filled"] == ["005930.KS", "삼성전자", True], "코드 칸과 이름 칸이 함께 채워지고 초점은 코드 칸으로"
    assert out["code"] == "000660", "코드 모드 칸은 6자리만"
    assert out["events"] == ["input", "change", "input", "change"], "화면 코드가 듣는 입력 · 변경 이벤트가 칸마다 간다"


def test_stockfind_wired_into_screen():
    """TC-SFD-03 · app.html 12칸 · 이름 칸 연결 · company.js 내보내기 · main.js 연결 · 새 검색 창을 만들지 않음."""
    html = APP_HTML.read_text(encoding="utf-8")
    found = {}
    for m in re.finditer(r"<input\b[^>]*?>", html, re.S):
        tag = m.group(0)
        mode = re.search(r'data-stock-find="(\w+)"', tag)
        if mode:
            found[re.search(r'\bid="([\w-]+)"', tag).group(1)] = mode.group(1)
    assert found == EXPECTED, f"속성이 달린 칸이 표와 다르다: {sorted(set(found) ^ set(EXPECTED))}"
    for target in re.findall(r'data-stock-name="([\w-]+)"', html):
        assert f'id="{target}"' in html, f"이름 칸 {target} 이 화면에 없다"
    assert '/css/stockfind.css' in html
    assert html.count('id="stock-search-modal"') == 1, "검색 창은 기존 하나만 쓴다"
    company = COMPANY.read_text(encoding="utf-8")
    assert re.search(r"export function openStockSearch\(callback\)", company)
    assert "_openStockSearch = openModal;" in company
    main = MAIN.read_text(encoding="utf-8")
    assert 'import { mountStockFind } from "/js/stockfind.js"' in main and "mountStockFind(document, openStockSearch)" in main
    css = (PUB / "css" / "stockfind.css").read_text(encoding="utf-8")
    assert ".sf-wrap" in css and ".sf-btn" in css
