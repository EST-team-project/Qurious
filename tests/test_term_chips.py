"""글 끝 「이 글의 용어」 칩 부품 화면 시험 (TC-TCH) · 2026-10-17 · 모의투자 점검 L5.

결정: Figma 「AI 투자 상담 — 근거 답과 출처」 03-2 [결정] 용어 칩 (가) — 본문 글에서 용어 풀이(오른쪽 서랍)로 가는 길을 글 끝 칩 줄로.
AI 답 글은 건드리지 않는다(몰래 고치지 않음). 글 속 용어는 서버가 찾는다(POST /api/glossary/scan · TC-GS) — 부품은 그리고 잇기만.
같은 부품을 다른 화면(차트 패턴 · 스크리닝 — 다른 주담당)도 부를 수 있게 따로 둔다(js/termchips.js).

여기서 지키는 것 —
1. 부품: 서버 상한(글 4,000자 · 용어 수)을 넘겨 보내지 않는다(화면 → API) · 칩은 용어 ID 로 서랍을 연다(termcard.js openTerm) ·
   글자를 막는다 · 찾은 용어가 없거나 찾기가 실패하면 줄을 그리지 않는다(답은 그대로) · 다른 화면이 부를 이름은 하나.
2. 상담 연결(js/kbchat.js): 일반 AI 답 · 근거 답 · 다른 엔진 답 끝에 「이 답의 용어」 · 답하지 않는 질문에는 붙이지 않는다.
3. 용어 카드를 닫으면 연 요소로 키보드 포커스 복귀(js/termcard.js · 2026-11-02 · TC-TCH-04 · 05) — 칩 · 교재 밑줄 단추 · 어떤 단추에서 열었든 같은 길(열기 직전의
   document.activeElement 를 기억 → 닫을 때 아직 문서에 있고 보이면 돌려줌). 코드는 글자로 읽고, 동작은 node 로 가짜 DOM 위에서 돌린다(node 가 없으면 그 시험만 건너뜀).
   눈으로 보는 확인(서랍 · 작은 창 · 큰 창의 실제 포커스 링)은 손 시험.
네트워크 · 실제 DB 없이 돈다.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.services import glossary_scan

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "public" / "js"


def _code(name: str) -> str:
    return re.sub(r"^\s*//.*$", "", (JS / name).read_text(encoding="utf-8"), flags=re.M)


def test_chip_part_respects_the_server_limits_and_opens_the_card():
    """TC-TCH-01 · 부품 — 글은 서버 상한(MAX_TEXT)까지 잘라 보내고 · 용어 수는 서버 상한 안 · 칩은 data-term(용어 ID)으로 서랍을 연다 ·
    글자를 막는다 · 줄 이름은 부른 쪽이 준다(기본 「이 글의 용어」)."""
    src = _code("termchips.js")
    assert int(re.search(r"export const TERM_SCAN_MAX = (\d+);", src).group(1)) == glossary_scan.MAX_TEXT
    limit = int(re.search(r"export const TERM_CHIPS_MAX = (\d+);", src).group(1))
    assert 1 <= limit <= glossary_scan.MAX_LIMIT and limit == 6                    # 결정 — 최대 여섯
    assert 'api("/api/glossary/scan", { method: "POST", body: { text: String(text).slice(0, TERM_SCAN_MAX), limit } })' in src
    assert 'import { openTerm } from "/js/termcard.js";' in src
    assert re.search(r'data-term="\$\{escHtml\(t\.id\)\}"', src) and "escHtml(t.term)" in src and "escHtml(label)" in src
    assert re.search(r'addEventListener\("click", \(\) => openTerm\(b\.dataset\.term\)\)', src)
    assert 'label = "이 글의 용어"' in src


def test_chip_part_draws_nothing_when_nothing_was_found():
    """TC-TCH-02 · 찾은 용어가 없거나 찾기가 실패하면 줄을 그리지 않는다 — 답은 그대로 두고, 실패는 콘솔에 남긴다(말없이 삼키지 않음)."""
    src = _code("termchips.js")
    fn = src[src.index("export async function appendTermChips"):src.index("\n}\n", src.index("export async function appendTermChips"))]
    assert re.search(r"if \(!items\.length\) return null;", fn)
    assert re.search(r"catch \(err\) \{\s*console\.warn\(", fn)
    assert "host.appendChild(row)" in fn


def test_chat_answers_get_the_chip_row():
    """TC-TCH-03 · 상담 연결 — 일반 AI 답 · 근거 답 · 다른 엔진 답 끝에 「이 답의 용어」 · 답하지 않는 질문(declined)에는 붙이지 않는다 ·
    다른 화면이 부를 부품 이름은 하나(appendTermChips)."""
    code = _code("kbchat.js")
    assert 'import { appendTermChips } from "/js/termchips.js";' in code
    general = code[code.index("async function askGeneralAi"):code.index("export async function sendKbChat")]
    assert re.search(r'appendTermChips\(bubble, chat\.answer, \{ label: "이 답의 용어" \}\)', general)
    kb = code[code.index("function renderKbAnswer"):code.index("function renderDeclined")]
    assert re.search(r'if \(!excerpt\) appendTermChips\(bubble, res\.answer, \{ label: "이 답의 용어" \}\);', kb)
    declined = code[code.index("function renderDeclined"):code.index("function failedExcerpt")]
    assert "appendTermChips" not in declined
    after = code[code.index("export function afterChatAnswer"):]
    # 다른 엔진 답 — 칩 자리를 먼저 잡아(「근거 답으로 다시 묻기」 단추보다 위) 거기에 채운다
    assert re.search(r'appendTermChips\(chipsHost, bubble\.querySelector\("pre"\)\?\.textContent \|\| "", \{ label: "이 답의 용어" \}\)', after)
    assert after.index("bubble.appendChild(chipsHost)") < after.index("bubble.appendChild(wrap)")


# ── 3. 용어 카드를 닫으면 연 요소로 포커스 복귀 (js/termcard.js) ─────────────────────────────────────────────

def test_card_remembers_the_opener_and_gives_focus_back_safely():
    """TC-TCH-04 · 글자로 읽는 계약 — 카드가 닫혀 있던 때만 열기 직전의 document.activeElement 를 기억(body · 카드 안 요소는 제외) · 닫을 때
    isConnected · 보임(getClientRects) 을 보고 focus({ preventScroll: true }) · 전부 try/catch · 용어사전으로 넘어가는 길은 돌려주지 않는다 ·
    닫으면 아직 오는 응답이 카드를 되살리지 못하게 seq 를 올린다 · 공개 모양(QTerm.open/close · 함수 머리)은 그대로 · 어느 단추에서 열었는지는 모른다."""
    src = _code("termcard.js")
    assert "let opener = null;" in src
    assert re.search(r"if \(!root \|\| root\.hidden\) rememberOpener\(\);\s*return show\(String\(key\), opts, true\);", src), "닫혀 있던 때만 기억 · 열린 채 교체하면 처음 것을 지킨다"
    remember = src[src.index("function rememberOpener()"):src.index("function restoreOpener(")]
    assert "document.activeElement" in remember and "document.body" in remember and "root.contains(el)" in remember
    assert re.search(r"try \{.*\} catch \{", remember, re.S), "포커스를 못 읽어도 오류 없이"
    restore = src[src.index("function restoreOpener("):src.index("function hideCard(")]
    assert "el.isConnected" in restore and "el.getClientRects().length === 0" in restore and "el.focus({ preventScroll: true });" in restore
    assert re.search(r"try \{.*\} catch \{", restore, re.S), "돌려주지 못해도 오류 없이"
    hide = src[src.index("function hideCard("):src.index("export function closeTerm()")]
    assert "const back = opener;" in hide and "opener = null;" in hide and "seq++;" in hide
    assert hide.index("opener = null;") < hide.index("restoreOpener(back)"), "기억을 비운 뒤 돌려준다"
    assert "if (restoreFocus && wasOpen && lost) restoreOpener(back);" in hide, "닫는 순간 포커스가 카드 안(또는 잃은 상태)일 때만"
    # 공개 모양은 그대로 — 닫기 단추 · 바깥 클릭 · Esc · API 가 모두 closeTerm(= 돌려줌), 용어사전으로 가는 길만 hideCard(false)
    assert "export function openTerm(key, opts = {}) {" in src and "export function closeTerm() {\n  hideCard(true);" in src
    assert src.count('addEventListener("click", closeTerm)') == 2 and 'e.key === "Escape" && root && !root.hidden) closeTerm();' in src
    assert "hideCard(false);" in src[src.index("function goToGlossary("):src.index("function ensureRoot()")]
    assert "window.QTerm = { open: openTerm, close: closeTerm, getView: getTermView, setView: setTermView, views: TERM_VIEWS };" in src
    # 열기 단추의 종류(칩 · 교재 밑줄 단추 등)를 모른다 — 누구든 같은 길. 교재 밑줄 쪽은 QTerm.open 만 부른다(TC-TUL-06)
    full = (JS / "termcard.js").read_text(encoding="utf-8")
    assert "q-term-ul" not in full and "termunderline" not in full
    assert "window.QTerm.open(id)" in _code("termunderline.js")


_CARD_HARNESS = r"""
import { readFileSync } from "node:fs";
const input = JSON.parse(readFileSync(process.argv[2], "utf8"));

// 가짜 DOM — 포커스 · 연결 · 보임 · 숨겨진 부모만 브라우저처럼 흉내 낸다
const doc = { activeElement: null, body: null, documentElement: null, listeners: {} };
const els = {};
let rootEl = null;
let termPageBtn = null;      // 카드 안 「용어사전에서 자세히」 단추
class El {
  constructor(id, parent = null) {
    this.id = id; this.parent = parent; this.kids = {}; this.connected = true; this.visible = true; this.throwOnFocus = false;
    this.focusCalls = []; this.handlers = {}; this._hidden = false; this.className = ""; this.textContent = ""; this.scrollTop = 0;
    this.attrs = {}; this.dataset = {}; this._html = ""; this.classList = { toggle() {} };
  }
  get isConnected() { return this.connected; }
  get hidden() { return this._hidden; }
  set hidden(v) { this._hidden = !!v; if (this._hidden && doc.activeElement && this.contains(doc.activeElement)) doc.activeElement = doc.body; }
  get innerHTML() { return this._html; }
  set innerHTML(v) {
    this._html = String(v);
    if (this.isRoot) for (const sel of [".q-term-dim", ".q-term-panel", ".q-term-back", ".q-term-close", ".q-term-body"]) this.kids[sel] = new El(sel.slice(1), this);
  }
  contains(el) { return el === this || Object.values(this.kids).includes(el); }
  querySelector(sel) { return this.kids[sel] || null; }
  querySelectorAll(sel) {
    if (sel !== "[data-term-page]") return [];
    return [...this._html.matchAll(/data-term-page="([^"]*)"/g)].map(m => { const b = new El("termpage", this); b.dataset.termPage = m[1]; termPageBtn = b; return b; });
  }
  addEventListener(type, fn) { (this.handlers[type] ||= []).push(fn); }
  click() { for (const fn of this.handlers.click || []) fn({ type: "click" }); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  hiddenAncestor() { for (let p = this.parent; p; p = p.parent) if (p._hidden) return true; return false; }
  getClientRects() { return this.visible && !this.hiddenAncestor() ? [{}] : []; }
  focus(opts) {
    this.focusCalls.push(opts === undefined ? null : { ...opts });
    if (this.throwOnFocus) throw new Error("focus 실패");
    if (!this.connected || !this.visible || this.hiddenAncestor()) return;     // 숨겨진 요소는 포커스를 못 받는다
    doc.activeElement = this;
  }
}
const el = id => els[id] || (els[id] = new El(id));

doc.body = new El("body"); doc.body.appendChild = () => {};
doc.documentElement = new El("html");
doc.activeElement = doc.body;
doc.createElement = () => { rootEl = new El("root"); rootEl.isRoot = true; return rootEl; };     // termcard 가 id 를 바꾸므로 표시를 따로 둔다
doc.querySelector = () => null;
doc.addEventListener = (type, fn) => { (doc.listeners[type] ||= []).push(fn); };
const holds = [];
let hold = false;
let pending = null;
globalThis.__api = async () => { if (hold) await new Promise(r => holds.push(r)); return { id: "rsi", term: "RSI" }; };
globalThis.window = {};
globalThis.document = doc;
globalThis.localStorage = { getItem: () => input.view ?? null, setItem() {} };     // 열리는 모양(drawer · modal-sm · modal-lg)
globalThis.sessionStorage = { getItem: () => null, setItem() {}, removeItem() {} };
globalThis.location = { hash: "" };
await import("./tc.mjs");
const Q = globalThis.window.QTerm;
const tick = () => new Promise(r => setTimeout(r, 5));

const snaps = [], errors = [];
for (const s of input.steps) {
  try {
    if (s.op === "el") Object.assign(el(s.id), s.set || {});
    else if (s.op === "focus") doc.activeElement = el(s.id);           // 사용자가 누르거나 Tab 으로 옮겨 포커스가 간 요소
    else if (s.op === "blur") doc.activeElement = s.to === "null" ? null : doc.body;
    else if (s.op === "open") await Q.open(s.key);
    else if (s.op === "openNoWait") pending = Q.open(s.key);
    else if (s.op === "hold") hold = s.on;
    else if (s.op === "release") { holds.splice(0).forEach(r => r()); if (pending) await pending; await tick(); }
    else if (s.op === "settle") await tick();
    else if (s.op === "close") {
      if (s.via === "api") Q.close();
      else if (s.via === "esc") for (const fn of doc.listeners.keydown || []) fn({ key: "Escape" });
      else rootEl.querySelector(s.via === "button" ? ".q-term-close" : ".q-term-dim").click();
    }
    else if (s.op === "back") { rootEl.querySelector(".q-term-back").click(); await tick(); }
    else if (s.op === "glossary") termPageBtn.click();
    else if (s.op === "snap") snaps.push({ name: s.name, active: doc.activeElement ? doc.activeElement.id : null, hidden: rootEl ? rootEl.hidden : null, mode: rootEl ? rootEl.className : null });
  } catch (e) { errors.push(`${s.op}: ${e && e.message}`); }
}
process.stdout.write(JSON.stringify({
  snaps, errors, hash: globalThis.location.hash,
  focus: Object.fromEntries(Object.entries(els).map(([k, v]) => [k, v.focusCalls])),
  closeFocus: rootEl ? rootEl.kids[".q-term-close"].focusCalls : [],
}));
"""


@pytest.fixture(scope="module")
def card_run(tmp_path_factory):
    """termcard.js 를 복사해 맨 위 import(/js/common.js)만 가짜로 바꾼 뒤 node 로 불러, 단계 목록(steps)마다 결과(JSON)를 돌려주는 함수."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node 가 없어 화면 함수를 돌릴 수 없다")
    src = (JS / "termcard.js").read_text(encoding="utf-8")
    patched, n = re.subn(r'(?m)^import \{ api, escHtml \} from "/js/common\.js";$',
                         "const api = (...a) => globalThis.__api(...a); const escHtml = s => String(s ?? '');", src)
    assert n == 1, "termcard.js 맨 위 import 모양이 달라졌다 — 시험의 바꿔치기를 맞춰야 한다"
    base = tmp_path_factory.mktemp("tcard")
    (base / "tc.mjs").write_text(patched, encoding="utf-8")
    (base / "run.mjs").write_text(_CARD_HARNESS, encoding="utf-8")

    def go(*steps: dict, view: str | None = None) -> dict:
        (base / "in.json").write_text(json.dumps({"steps": list(steps), "view": view}, ensure_ascii=False), encoding="utf-8")
        done = subprocess.run([node, str(base / "run.mjs"), str(base / "in.json")], capture_output=True, text=True, encoding="utf-8", timeout=60)
        assert done.returncode == 0, done.stderr
        out = json.loads(done.stdout)
        assert out["errors"] == [], out["errors"]
        return out

    return go


def _s(op: str, **kw) -> dict:
    return {"op": op, **kw}


def _active(out: dict, name: str):
    return next(s["active"] for s in out["snaps"] if s["name"] == name)


def test_card_gives_focus_back_on_every_close_path(card_run):
    """TC-TCH-05 · 동작(node · 가짜 DOM) — 단추에서 열고 닫기 단추 · Esc · 바깥 클릭(어두운 막) · QTerm.close() 로 닫으면 그 단추로 포커스가 돌아간다
    (preventScroll 한 번) · 열린 동안은 닫기 단추에 있다 · 다음 열기에서는 새 요소를 기억한다(이전 것이 남지 않는다)."""
    # 열리는 모양 셋(오른쪽 서랍 · 가운데 작은 창 · 가운데 큰 창) × 닫는 길 넷 — 닫는 코드는 모양을 가리지 않는다는 증거
    for view in ("drawer", "modal-sm", "modal-lg"):
        for via in ("button", "esc", "dim", "api"):
            out = card_run(_s("el", id="A"), _s("focus", id="A"), _s("open", key="rsi"), _s("snap", name="opened"),
                           _s("close", via=via), _s("snap", name="closed"), view=view)
            assert out["snaps"][0]["mode"] == f"q-term--{view}", (view, out["snaps"][0])
            assert _active(out, "opened") == "q-term-close", (view, via)
            assert _active(out, "closed") == "A" and out["snaps"][-1]["hidden"] is True, (view, via)
            assert out["focus"]["A"] == [{"preventScroll": True}], (view, via)
    # 두 번째 열기는 새 요소를 기억한다
    out = card_run(_s("el", id="A"), _s("el", id="B"), _s("focus", id="A"), _s("open", key="rsi"), _s("close", via="esc"),
                   _s("focus", id="B"), _s("open", key="rsi"), _s("close", via="button"), _s("snap", name="closed"))
    assert _active(out, "closed") == "B" and len(out["focus"]["A"]) == 1 and len(out["focus"]["B"]) == 1


def test_card_keeps_the_first_opener_when_the_term_is_replaced(card_run):
    """TC-TCH-05b · 열린 채 다른 용어로 바꿔도(다른 단추 · ← 이전 용어) 처음 연 단추를 지킨다 — 닫으면 처음 것으로, 바꾼 쪽 단추로는 가지 않는다."""
    out = card_run(_s("el", id="A"), _s("el", id="B"), _s("focus", id="A"), _s("open", key="rsi"),
                   _s("focus", id="B"), _s("open", key="per"), _s("back"), _s("close", via="esc"), _s("snap", name="closed"))
    assert _active(out, "closed") == "A" and out["focus"].get("B", []) == []


def test_card_does_nothing_when_there_is_no_opener_to_return_to(card_run):
    """TC-TCH-05c · 열기 직전 포커스가 body · null 이거나, 닫을 때 그 요소가 문서에서 사라졌거나 보이지 않거나, focus() 가 던져도 — 아무것도 하지 않고 오류도 없다
    (card_run 이 오류 목록이 비었는지 매번 확인한다)."""
    # 열기 직전 포커스 없음(body) · 완전히 없음(null)
    out = card_run(_s("open", key="rsi"), _s("close", via="esc"), _s("snap", name="closed"))
    assert _active(out, "closed") == "body" and out["focus"] == {}
    out = card_run(_s("blur", to="null"), _s("open", key="rsi"), _s("blur", to="null"), _s("close", via="api"), _s("snap", name="closed"))
    assert _active(out, "closed") is None and out["focus"] == {}
    # 닫을 때 사라졌다 / 숨겨졌다 — focus() 를 부르지도 않는다
    for gone in ({"connected": False}, {"visible": False}):
        out = card_run(_s("el", id="A"), _s("focus", id="A"), _s("open", key="rsi"), _s("el", id="A", set=gone), _s("close", via="esc"), _s("snap", name="closed"))
        assert _active(out, "closed") == "body" and out["focus"]["A"] == [], gone
    # focus() 가 던져도 삼킨다
    out = card_run(_s("el", id="A", set={"throwOnFocus": True}), _s("focus", id="A"), _s("open", key="rsi"), _s("close", via="esc"), _s("snap", name="closed"))
    assert len(out["focus"]["A"]) == 1 and _active(out, "closed") == "body"


def test_card_leaves_focus_alone_when_the_user_moved_it_elsewhere_or_is_navigating(card_run):
    """TC-TCH-05d · 서랍을 연 채 뒤 화면의 다른 입력칸으로 포커스를 옮겼으면 닫아도 뺏지 않는다 · 로딩 중에 닫으면 늦게 온 응답이 카드를 되살리거나
    닫기 단추로 포커스를 가져가지 못한다 · 「용어사전에서 자세히」 로 화면을 옮기는 길은 열던 자리로 돌리지 않는다."""
    out = card_run(_s("el", id="A"), _s("el", id="INPUT"), _s("focus", id="A"), _s("open", key="rsi"),
                   _s("focus", id="INPUT"), _s("close", via="esc"), _s("snap", name="closed"))
    assert _active(out, "closed") == "INPUT" and out["focus"]["A"] == []
    # 로딩 중 닫기 — 포커스는 아직 열던 단추에 있고(닫기 단추로 안 갔다), 응답이 늦게 와도 숨은 카드를 다시 그리거나 포커스를 가져가지 않는다
    out = card_run(_s("el", id="A"), _s("focus", id="A"), _s("hold", on=True), _s("openNoWait", key="rsi"), _s("close", via="esc"),
                   _s("snap", name="closed"), _s("release"), _s("snap", name="late"))
    assert _active(out, "closed") == "A" and _active(out, "late") == "A" and out["snaps"][-1]["hidden"] is True
    assert out["closeFocus"] == [], "늦게 온 응답이 닫힌 카드의 닫기 단추로 포커스를 옮기려 했다"
    # 용어사전으로 넘어가는 길 — 카드는 닫히지만 열던 자리로 돌리지 않고, 화면은 용어사전으로 옮긴다
    out = card_run(_s("el", id="A"), _s("focus", id="A"), _s("open", key="rsi"), _s("glossary"), _s("snap", name="gone"))
    assert out["snaps"][-1]["hidden"] is True and _active(out, "gone") == "body" and out["focus"]["A"] == [] and out["hash"] == "fin-glossary"
