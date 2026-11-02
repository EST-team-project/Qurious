"""TC-TUL — 할 일 ①-23 B : 교재 용어 밑줄(public/js/termunderline.js + js/conceptlearn.js 연결 + css/qurious.css) · 2026-11-02

개념 학습 장 본문 속 용어사전 낱말에 점선 밑줄을 긋고, 누르면 용어 카드가 열린다. 낱말은 서버(POST /api/glossary/scan · TC-GS)가 찾는다 —
이 시험은 화면 쪽이 그 응답을 제대로 보내고 · 읽고 · 감싸는지를 본다. 브라우저 없이 — JS 는 글자로 읽고, 순수 함수와 감싸기는 node 로
가짜 DOM 위에서 돌린다(node 가 없으면 그 시험만 건너뛴다). 눈으로 보는 확인(점선 · 초점 · 390 폭)은 손 시험.

1. 서버 상한을 지킨다 — 덩어리 ≤ MAX_TEXT · 용어 수는 MAX_LIMIT 를 요청(안 보내면 기본 6개만 온다) · 요청 모양. (TC-TUL-01)
2. 덩어리 나누기 — 절(h2)을 넘지 않고 · 4000자 안 · 블록 사이엔 BREAK, 같은 블록의 인라인 글 노드는 이어 붙이고 · 긴 글 노드는 조각내고 · 글을 빠뜨리지 않는다. (TC-TUL-02)
3. 제외 — 코드 · 그림 · 링크 · 단추 · 제목 · 표 머리 · summary · 알림 상자 제목 · 이미 감싼 낱말은 서버에 보내지도 않는다. (TC-TUL-03)
4. 실제 서버 scan 과 맞물려 — 같은 용어는 한 절에서 첫 등장만 · 이모지 뒤 위치 · 글 노드 둘에 걸친 낱말은 버림 · 문단 끝 두 글자 용어도 읽힘. (TC-TUL-04)
5. 접근성 · 안전 — 단추 이름에 화면 글자 · 끄면 글자로 복원 · 늦은 응답 버림 · 일부 실패해도 나머지는 긋고 · 20개로 꽉 찬 응답은 이어 묻고 · 위치 변환. (TC-TUL-05)
6. 연결 — 용어 카드는 window.QTerm.open · termcard.js 는 이 기능을 모름 · conceptlearn.js 는 한 곳에서만 부르고 기다리지 않는다 · 켜고 끄기. (TC-TUL-06)
7. CSS — 하드코딩 색 없음 · 앱 변수만 · 점선 + 호버 실선 + 초점 윤곽(색만으로 구분하지 않음). (TC-TUL-07)
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.services import glossary_scan as G

ROOT = Path(__file__).resolve().parents[1]
PUB = ROOT / "public"
MOD = PUB / "js" / "termunderline.js"
CL = PUB / "js" / "conceptlearn.js"
CARD = PUB / "js" / "termcard.js"
QCSS = PUB / "css" / "qurious.css"
APPCSS = PUB / "css" / "app.css"

SRC = MOD.read_text(encoding="utf-8")


def _code(src: str) -> str:
  """주석을 뺀 코드만 (한 줄 주석 · 블록 주석)."""
  return re.sub(r"/\*.*?\*/", "", re.sub(r"(?m)^\s*//.*$", "", src), flags=re.S)


def _const(name: str) -> int:
  m = re.search(rf"export const {name} = (\d+);", SRC)
  assert m, name
  return int(m.group(1))


# ── 가짜 DOM 위에서 모듈을 돌리는 node 도구 ────────────────────────────────

HARNESS = r"""
import { readFileSync } from "node:fs";
const m = await import("./tu.mjs");
const input = JSON.parse(readFileSync(process.argv[2], "utf8"));

class Txt {
  constructor(v) { this.nodeType = 3; this.nodeValue = v; this.parentNode = null; }
  get textContent() { return this.nodeValue; }
  splitText(i) { const tail = new Txt(this.nodeValue.slice(i)); this.nodeValue = this.nodeValue.slice(0, i); this.parentNode.insertAfter(tail, this); return tail; }
  replaceWith(x) { this.parentNode.replaceChild(typeof x === "string" ? new Txt(x) : x, this); }
}
class El {
  constructor(tag, cls = "", attrs = {}) { this.nodeType = 1; this.tagName = tag.toUpperCase(); this.className = cls; this.attrs = { ...attrs }; this.childNodes = []; this.parentNode = null; }
  add(n) { n.parentNode = this; this.childNodes.push(n); return n; }
  insertAfter(n, ref) { n.parentNode = this; this.childNodes.splice(this.childNodes.indexOf(ref) + 1, 0, n); }
  replaceChild(n, old) { n.parentNode = this; this.childNodes[this.childNodes.indexOf(old)] = n; old.parentNode = null; }
  getAttribute(k) { return k === "class" ? this.className : (k in this.attrs ? this.attrs[k] : null); }
  setAttribute(k, v) { if (k === "class") this.className = v; else this.attrs[k] = String(v); }
  get textContent() { return this.childNodes.map(c => c.textContent).join(""); }
  set textContent(v) { this.childNodes = []; this.add(new Txt(String(v))); }
  querySelectorAll(sel) {
    const cls = sel.slice(1), out = [];
    const walk = n => { for (const c of n.childNodes) if (c.nodeType === 1) { if (c.className.split(/\s+/).includes(cls)) out.push(c); walk(c); } };
    walk(this);
    return out;
  }
  replaceWith(x) { this.parentNode.replaceChild(typeof x === "string" ? new Txt(x) : x, this); }
  normalize() {
    const out = [];
    for (const c of this.childNodes) {
      if (c.nodeType === 3) {
        if (!c.nodeValue) continue;
        const last = out[out.length - 1];
        if (last && last.nodeType === 3) { last.nodeValue += c.nodeValue; continue; }
      } else c.normalize();
      out.push(c);
    }
    this.childNodes = out;
  }
}
const build = s => {
  if (typeof s === "string") return new Txt(s);
  const e = new El(s.t, s.c, s.a);
  for (const k of s.k) e.add(build(k));
  return e;
};
const isBtn = n => n.nodeType === 1 && n.className === m.UL_CLASS;
const ser = n => n.nodeType === 3 ? n.nodeValue : isBtn(n) ? "⟦" + n.textContent + "⟧"
  : `<${n.tagName.toLowerCase()}>` + n.childNodes.map(ser).join("") + `</${n.tagName.toLowerCase()}>`;
const buttons = (n, out = []) => { for (const c of n.childNodes) if (c.nodeType === 1) { if (isBtn(c)) out.push({ text: c.textContent, type: c.type, attrs: c.attrs }); else buttons(c, out); } return out; };
const doc = { createElement: t => new El(t) };

const fakeScan = (requests, state) => async (text, limit) => {
  requests.push(text);
  if (input.staleAfter !== undefined && requests.length >= input.staleAfter) state.alive = false;
  if (input.failOn && text.includes(input.failOn)) throw new Error("boom");
  if (input.responses) {
    if (!(text in input.responses)) throw new Error("기록된 응답이 없는 글: " + JSON.stringify(text));
    return input.responses[text];
  }
  const items = [];
  for (const t of input.terms || []) {
    const i = text.indexOf(t.term);
    if (i >= 0) items.push({ id: t.id, term: t.shown || t.term, matched: t.term, at: [...text.slice(0, i)].length });
  }
  items.sort((a, b) => a.at - b.at);
  return items.slice(0, limit);
};

const op = input.op;
let out;
if (op === "plan") {
  const { sections } = m.collectSections(build(input.tree));
  out = { sections: sections.map(s => m.buildChunks(s).map(c => ({ text: c.text, segs: c.segs.map(g => ({ text: g.text, start: g.start, sep: g.sep })) }))) };
} else if (op === "apply" || op === "unwrap") {
  const root = build(input.tree);
  const before = ser(root);
  const requests = [], fails = [], state = { alive: true };
  const wrapped = await m.underlineTree(root, {
    scan: fakeScan(requests, state), makeButton: p => m.makeButton(p, doc),
    isCurrent: () => state.alive, onFail: e => fails.push(String(e && e.message)),
  });
  const html = ser(root), btns = buttons(root);
  if (op === "unwrap") m.unwrapAll(root);
  out = { wrapped, before, html, after: ser(root), buttons: btns, requests, fails };
} else if (op === "saturate") {
  const requests = [], state = { alive: true };
  const hits = await m.scanText(input.text, fakeScan(requests, state), { limit: input.limit });
  out = { hits, calls: requests.length, requests };
} else if (op === "utf16") {
  out = input.cases.map(([t, cp]) => m.cpToUtf16(t, cp));
} else if (op === "pieces") {
  out = m.splitPieces(input.text, input.max);
} else if (op === "label") {
  out = input.picks.map(p => m.labelOf(p));
}
process.stdout.write(JSON.stringify(out));
"""


def el(tag: str, *kids, cls: str = "", **attrs) -> dict:
  """가짜 DOM 노드 설명 — 자식은 글(str) 또는 노드."""
  return {"t": tag, "c": cls, "k": list(kids), "a": {k.replace("_", "-"): v for k, v in attrs.items()}}


@pytest.fixture(scope="module")
def run(tmp_path_factory):
  """termunderline.js 를 그대로 복사해 node 로 불러 입력마다 결과(JSON)를 돌려주는 함수 — 모듈은 import 가 없어 고칠 것이 없다."""
  node = shutil.which("node")
  if not node:
    pytest.skip("Node 가 없어 화면 함수를 돌릴 수 없다")
  base = tmp_path_factory.mktemp("tul")
  (base / "tu.mjs").write_text(SRC, encoding="utf-8")
  (base / "run.mjs").write_text(HARNESS, encoding="utf-8")

  def go(payload: dict):
    (base / "in.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    done = subprocess.run([node, str(base / "run.mjs"), str(base / "in.json")], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)

  return go


# ── 1. 서버 상한 ──────────────────────────────────────────────────────────

def test_chunk_size_and_term_limit_follow_the_server_caps():
  """TC-TUL-01 · 덩어리는 서버 글 상한(MAX_TEXT) 안 · 요청에 limit = 서버 상한(MAX_LIMIT)을 싣는다(안 싣으면 기본 6개만 온다) ·
  요청은 POST /api/glossary/scan 에 {text, limit} · 모듈 맨 위에는 import · window · document 가 없다(node 가 바로 불러 돌린다)."""
  assert _const("CHUNK_MAX") <= G.MAX_TEXT - 500, "BREAK · 줄바꿈 몫을 남기고 서버 상한 안"
  assert _const("SCAN_LIMIT") == G.MAX_LIMIT and G.MAX_LIMIT > G.DEFAULT_LIMIT
  assert 1 <= _const("PARALLEL") <= 4 and _const("MAX_ROUNDS") >= 2
  code = _code(SRC)
  assert 'export const SCAN_URL = "/api/glossary/scan";' in code
  assert re.search(r'method: "POST"', code) and "body: JSON.stringify({ text, limit })" in code
  assert "const items = await scan(part, limit);" in code, "20개로 꽉 찬 응답을 이어 묻는 길"
  assert not re.search(r"(?m)^import\b", code), "맨 위 import 가 있으면 node 가 절대 경로(/js/…)를 못 연다"
  top = _code(SRC[:SRC.index("// ── 브라우저 연결")])
  assert "window." not in top and "document." not in top, "순수 함수 구역은 window · document 를 건드리지 않는다"


# ── 2. 덩어리 나누기 ──────────────────────────────────────────────────────

def test_chunks_stay_inside_sections_and_server_cap_and_keep_all_text(run):
  """TC-TUL-02 · 덩어리 ≤ CHUNK_MAX ≤ MAX_TEXT · 절(h2)을 넘지 않는다 · 블록 사이는 BREAK, 같은 블록의 인라인 글 노드는 이어 붙임 ·
  5천 자 글 노드는 조각내고(공백에서 자르고 이모지 쌍은 안 가름) · 제외 안 된 글은 하나도 빠지지 않는다."""
  para = lambda tag, n: f"{tag}절 " + ("가나다라마바사 " * 100)[:n]  # noqa: E731
  tree = el("div",
            el("p", "머리말 앞 글"),
            el("h2", "A절 제목"),
            el("p", para("A", 700)), el("p", para("A", 700)), el("p", para("A", 700)), el("p", para("A", 700)),
            el("p", "앞", el("strong", "굵게"), el("em", "기울여"), "뒤"),
            el("h2", "B절 제목"),
            el("p", "B절 " + "긴글 " * 1500),
            el("h1", "새 큰 제목"), el("p", "C절 끝"))
  sections = run({"op": "plan", "tree": tree})["sections"]
  assert len(sections) == 4, "머리말(0절) · A · B · C(h1 도 새 절)"
  cap = _const("CHUNK_MAX")
  every = [c for sec in sections for c in sec]
  assert every and all(len(c["text"]) <= cap <= G.MAX_TEXT for c in every), [len(c["text"]) for c in every]
  assert all("B절" not in c["text"] and "C절" not in c["text"] for c in sections[1]), "A절 덩어리에 다른 절 글이 섞이지 않는다"
  assert all("A절" not in c["text"] and "C절" not in c["text"] for c in sections[2]) and len(sections[1]) >= 2, "긴 절은 덩어리를 나눈다"
  assert len(sections[2]) >= 3, "5천 자 글 노드 하나도 조각으로 나눠 상한 안에 담는다"
  # 덩어리 안 조각의 start · 글이 덩어리 글과 맞는다 · 블록 사이 BREAK · 인라인은 이어 붙임
  brk = "\n·\n"
  for c in every:
    for g in c["segs"]:
      assert c["text"][g["start"]:g["start"] + len(g["text"])] == g["text"]
  inline = next(c for c in sections[1] if "굵게" in c["text"])
  assert "앞굵게기울여뒤" in inline["text"], "strong · em 경계는 구분 없이 이어 붙인다(「배당<strong>금</strong>」 이 「배당」 으로 읽히지 않게)"
  assert any(brk in c["text"] for c in sections[1]), "블록(문단) 사이는 BREAK"
  # 빠뜨리지 않는다 — 5천 자 글은 조각들을 이으면 원래 글
  joined = "".join(g["text"] for c in sections[2] for g in c["segs"])
  assert joined == "B절 " + "긴글 " * 1500
  _check_split_pieces(run)


def _u16(s: str) -> int:
  return len(s.encode("utf-16-le")) // 2


def _check_split_pieces(run):
  """(TC-TUL-02 의 일부) 긴 글 노드 조각 나누기 — 공백에서 자르고 · 서로게이트 쌍(이모지)은 가르지 않고 · 이으면 원래 글 · 조각 시작 위치가 맞는다."""
  text = "가나 다라 " * 30 + "😀" * 40
  pieces = run({"op": "pieces", "text": text, "max": 25})
  assert "".join(p["text"] for p in pieces) == text
  assert all(_u16(p["text"]) <= 25 for p in pieces) and len(pieces) >= 9
  assert all(p["base"] == sum(_u16(q["text"]) for q in pieces[:i]) for i, p in enumerate(pieces))
  assert not any(0xD800 <= ord(p["text"][-1]) <= 0xDBFF for p in pieces), "서로게이트 쌍을 가르지 않는다"


# ── 3. 제외 ───────────────────────────────────────────────────────────────

def test_skipped_elements_never_reach_the_server(run):
  """TC-TUL-03 · 코드(pre · code · .cl-code) · 그림(.cl-mermaid · svg) · 링크 · 단추 · 제목 · 표 머리 · summary · 알림 상자 제목 · 이미 감싼 낱말 ·
  data-no-term-ul 은 서버에 보내지도 않는다. 본문 글(p · li · td · blockquote · 알림 상자 본문 · 인라인 강조)은 그대로 보낸다."""
  tree = el("div",
            el("h2", "SKIP제목2"), el("h1", "SKIP제목1"), el("h3", "SKIP제목3"), el("h6", "SKIP제목6"),
            el("p", "KEEP본문 ", el("code", "SKIP인라인코드"), " KEEP이어서 ", el("a", "SKIP링크", el("strong", "SKIP링크안강조"), href="#x"), " KEEP끝"),
            el("div", el("pre", el("code", "SKIP코드블록")), cls="cl-code"),
            el("pre", el("code", "SKIP맨코드")),
            el("div", "SKIP머메이드원문", cls="cl-mermaid"),
            el("div", el("svg", el("text", "SKIP그림글자")), cls="cl-mermaid"),
            el("p", "KEEP앞 ", el("button", "SKIP단추"), " KEEP뒤"),
            el("div", el("div", "SKIP참고제목", cls="cl-callout-title"), el("p", "KEEP알림본문"), cls="cl-callout"),
            el("details", el("summary", "SKIP요약줄"), el("p", "KEEP펼침본문")),
            el("table", el("thead", el("tr", el("th", "SKIP표머리"))), el("tbody", el("tr", el("th", "SKIP행머리"), el("td", "KEEP셀")))),
            el("ul", el("li", "KEEP목록", el("ul", el("li", "KEEP중첩목록")))),
            el("blockquote", el("p", "KEEP인용")),
            el("p", "KEEP감쌈앞 ", el("button", "SKIP이미감싼", cls="q-term-ul", data_ul_term="rsi"), " KEEP감쌈뒤"),
            el("p", el("span", "SKIP직접제외", data_no_term_ul=""), " KEEP제외뒤"),
            el("p", el("em", "KEEP강조"), "와 ", el("mark", "KEEP표시")))
  sections = run({"op": "plan", "tree": tree})["sections"]
  text = "\n".join(c["text"] for sec in sections for c in sec)
  assert "SKIP" not in text, re.findall(r"SKIP\S*", text)
  for want in ("KEEP본문", "KEEP이어서", "KEEP끝", "KEEP앞", "KEEP뒤", "KEEP알림본문", "KEEP펼침본문", "KEEP셀", "KEEP목록", "KEEP중첩목록",
               "KEEP인용", "KEEP감쌈앞", "KEEP감쌈뒤", "KEEP제외뒤", "KEEP강조", "KEEP표시"):
    assert want in text, want
  # 제외한 자리(인라인 code · 링크 · 단추)는 앞뒤 글을 한 낱말로 붙이지 않는다 — BREAK 가 낀다
  assert "KEEP본문 \n·\n KEEP이어서" in text and "KEEP이어서 \n·\n KEEP끝" in text


# ── 4. 실제 서버 scan 과 맞물려 ───────────────────────────────────────────

def _roundtrip(run, tree: dict):
  """node 가 덩어리를 만들면, 서버와 같은 함수(glossary_scan.scan)로 물어 그 응답을 그대로 돌려주어 감싸게 한다."""
  texts = [c["text"] for sec in run({"op": "plan", "tree": tree})["sections"] for c in sec]
  responses = {t: G.scan(t, limit=G.MAX_LIMIT) for t in texts}
  return texts, run({"op": "apply", "tree": tree, "responses": responses})


def test_real_scan_first_mention_per_section_emoji_and_cross_node(run):
  """TC-TUL-04 · 같은 용어는 한 절에서 첫 등장만(다음 절에서는 다시) · 이모지 뒤 위치도 맞고 · 코드 · 링크 · 제목 · 표 머리의 낱말은 긋지 않고 ·
  인라인 강조 안의 낱말도 긋고 · 문단 사이 BREAK / 글 노드 둘에 걸친 낱말 / 문단 끝 두 글자 용어까지 서버 응답과 맞춰 본다."""
  tree = el("div",
            el("h2", "첫 절 RSI"),
            el("p", "RSI 가 30 아래이고 ", el("strong", "MACD"), " 가 높습니다. 😀 볼린저 밴드 쪽"),
            el("p", "다시 RSI 와 볼린저 밴드 그리고 ", el("code", "RSI"), " 코드"),
            el("div", el("pre", el("code", "골든크로스 RSI")), cls="cl-code"),
            el("div", "골든크로스 머메이드", cls="cl-mermaid"),
            el("p", "링크 ", el("a", "골든크로스", href="#x"), " 끝"),
            el("h2", "둘째 절"),
            el("p", "RSI 는 둘째 절에서 다시 나옵니다. 골든크로스 도 있습니다."),
            el("table", el("thead", el("tr", el("th", "MACD"))), el("tbody", el("tr", el("td", "골든크로스")))))
  texts, out = _roundtrip(run, tree)
  assert out["fails"] == [] and sorted(out["requests"]) == sorted(texts), "덩어리마다 한 번(꽉 찬 응답이 없으니 이어 묻기 없음)"
  assert [b["text"] for b in out["buttons"]] == ["RSI", "MACD", "볼린저 밴드", "RSI", "골든크로스"], out["html"]
  assert out["wrapped"] == 5
  html = out["html"]
  assert "<strong>⟦MACD⟧</strong>" in html, "강조 안의 글 노드 하나를 그대로 단추로"
  assert "😀 ⟦볼린저 밴드⟧ 쪽" in html, "이모지(UTF-16 두 칸) 뒤에서도 서버의 코드포인트 위치가 맞게 옮겨진다"
  assert html.count("⟦RSI⟧") == 2 and html.index("⟦RSI⟧") < html.index("<h2>둘째 절</h2>") < html.rindex("⟦RSI⟧"), "첫 절 한 번 · 둘째 절 한 번"
  assert "<code>RSI</code>" in html and "<code>골든크로스 RSI</code>" in html and "<a>골든크로스</a>" in html, "제외한 자리는 글 그대로"
  assert "<th>MACD</th>" in html and "<td>골든크로스</td>" in html, "표 머리는 제외 · 같은 절의 두 번째 등장은 긋지 않는다"
  assert "<h2>첫 절 RSI</h2>" in html, "제목의 낱말은 긋지 않는다"
  # 단추 모양: 모두 용어 ID 를 들고 있다
  assert {b["attrs"]["data-ul-term"] for b in out["buttons"]} == {"rsi", "macd", "볼린저밴드", "골든크로스"}
  _check_block_break_cross_node_and_short_term(run)


def _check_block_break_cross_node_and_short_term(run):
  """(TC-TUL-04 의 일부) 서버는 공백을 지우고 견주므로 — 문단 끝 「볼린저」 + 다음 문단 첫 「밴드」 가 한 용어로 잡히지 않게 BREAK 를 끼우고(서버 쪽 원인 확인 포함) ·
  글 노드 둘에 걸친 낱말(볼린저<strong>밴드</strong>)은 버리고 · 문단 끝의 두 글자 용어(「배당」)는 그대로 읽힌다."""
  assert [x["id"] for x in G.scan("앞 문단 끝 볼린저\n밴드 다음 문단")] == ["볼린저밴드"], "BREAK 가 없으면 이렇게 잡힌다 — 구분자가 필요한 까닭"
  tree = el("div",
            el("h2", "절"),
            el("p", "앞 문단 끝 볼린저"), el("p", "밴드 다음 문단"),
            el("p", "우리는 매년 배당"), el("p", "다음 문단"),
            el("p", "볼린저", el("strong", "밴드"), " 는 한 용어이나 글 노드가 둘"))
  texts, out = _roundtrip(run, tree)
  assert "앞 문단 끝 볼린저\n·\n밴드 다음 문단" in texts[0]
  found = [x for x in G.scan(texts[0], limit=G.MAX_LIMIT) if x["id"] == "볼린저밴드"]
  assert len(found) == 1 and found[0]["matched"] == "볼린저밴드", "서버가 찾는 것은 마지막 문단(글 노드만 둘) 하나 — 문단 사이는 붙지 않는다"
  assert [b["text"] for b in out["buttons"]] == ["배당"], out["html"]
  assert "⟦배당⟧</p>" in out["html"]
  assert out["fails"] == []


# ── 5. 접근성 · 안전 ──────────────────────────────────────────────────────

TERMS = [{"id": "rsi", "term": "RSI"}, {"id": "per", "term": "PER", "shown": "주가수익비율"}, {"id": "mdd", "term": "최대 낙폭", "shown": "MDD"}]
TREE3 = el("div", el("h2", "하나"), el("p", "RSI 와 PER 이 있습니다"), el("h2", "둘"), el("p", "최대 낙폭 과 RSI"), el("h2", "셋"), el("p", "PER 한 번"))


def test_buttons_are_named_with_visible_text_and_keyboard_reachable(run):
  """TC-TUL-05 · 단추 이름은 「용어 설명 열기: 화면 글자」 (WCAG 2.5.3 — 화면에 보이는 글자를 포함) · 대표 이름이 다르면 괄호로 덧붙임 ·
  type=button(폼 제출 방지) · aria-haspopup=dialog · 진짜 <button> 이라 Tab · Enter · 스페이스가 그대로 된다 ·
  끄면 글자로 복원 · 장 전환 뒤 늦은 응답 버림 · 일부 실패 격리 · 20개로 꽉 찬 응답 이어 묻기 · 코드포인트 → UTF-16 변환."""
  out = run({"op": "apply", "tree": TREE3, "terms": TERMS})
  by = {}
  for b in out["buttons"]:
    by.setdefault(b["text"], b)
  assert by["RSI"]["attrs"]["aria-label"] == "용어 설명 열기: RSI"
  assert by["PER"]["attrs"]["aria-label"] == "용어 설명 열기: PER (주가수익비율)"
  assert by["최대 낙폭"]["attrs"]["aria-label"] == "용어 설명 열기: 최대 낙폭 (MDD)"
  for b in out["buttons"]:
    assert b["type"] == "button" and b["attrs"]["aria-haspopup"] == "dialog" and b["attrs"]["aria-label"].startswith("용어 설명 열기: ")
    assert b["text"] in b["attrs"]["aria-label"], "이름에 화면 글자가 든다"
  assert run({"op": "label", "picks": [{"matched": "볼린저\n 밴드", "term": "볼린저밴드"}]}) == ["용어 설명 열기: 볼린저 밴드"]
  code = _code(SRC)
  assert 'doc.createElement("button")' in code and 'b.type = "button"' in code and "tabindex" not in code.lower()
  _check_toggle_off_stale_failure_saturation(run)


def _check_toggle_off_stale_failure_saturation(run):
  """(TC-TUL-05 의 일부) 끄면 단추가 글자로 되돌아간다(Tab 순서에 안 남음 · 글은 처음과 같다) · 장 전환(isCurrent 거짓)이면 아무것도 감싸지 않고 ·
  한 덩어리가 실패해도 나머지는 긋고 · 서버가 20개로 꽉 채운 응답은 마지막 낱말 뒤부터 이어 물어 빠뜨리지 않고 · 위치 변환은 이모지에도 맞는다."""
  out = run({"op": "unwrap", "tree": TREE3, "terms": TERMS})
  assert out["wrapped"] == 5 and "⟦" in out["html"], out["html"]
  assert out["after"] == out["before"] and "⟦" not in out["after"], "끈 뒤에는 처음 글 그대로(빈 글 노드는 합쳐진다)"
  stale = run({"op": "apply", "tree": TREE3, "terms": TERMS, "staleAfter": 1})
  assert stale["wrapped"] == 0 and "⟦" not in stale["html"], "늦게 온 응답은 버린다"
  part = run({"op": "apply", "tree": TREE3, "terms": TERMS, "failOn": "최대 낙폭"})
  assert len(part["fails"]) == 1 and [b["text"] for b in part["buttons"]] == ["RSI", "PER", "PER"], "실패한 덩어리만 빠진다"
  many = [{"id": f"t{i}", "term": f"용어{i}번"} for i in range(5)]
  sat = run({"op": "saturate", "text": " ".join(t["term"] for t in many), "limit": 2, "terms": many})
  assert [h["id"] for h in sat["hits"]] == [t["id"] for t in many] and sat["calls"] >= 3, "limit 2 로 꽉 찬 응답은 이어 묻는다"
  assert run({"op": "utf16", "cases": [["a😀b", 2], ["abc", 3], ["abc", 4], ["abc", -1], ["가😀😀나", 3]]}) == [3, 3, -1, -1, 5]


# ── 6. 연결 ──────────────────────────────────────────────────────────────

def test_wiring_card_open_and_chapter_hook_and_toggle():
  """TC-TUL-06 · 클릭은 window.QTerm.open(용어 ID) · 모듈은 termcard.js 를 import 하지 않고 termcard.js 는 이 기능을 모른다 ·
  conceptlearn.js 는 모듈을 한 곳에서만 부르고(장을 그린 뒤 · 기다리지 않음 · 장 전환 번호를 넘김) · 켜고 끄기는 localStorage 를 감싸 쓴다."""
  code = _code(SRC)
  assert "window.QTerm.open(id)" in code and 'closest(`.${UL_CLASS}`)' in code and 'data-ul-term' in code
  assert "termcard" not in code and "data-term" not in code.replace("data-ul-term", ""), "용어 카드 파일 · 다른 화면의 data-term 과 얽히지 않는다"
  card = CARD.read_text(encoding="utf-8")
  assert "q-term-ul" not in card and "termunderline" not in card and "window.QTerm = {" in card
  cl = CL.read_text(encoding="utf-8")
  assert cl.count('import { mountTermUnderline } from "/js/termunderline.js";') == 1
  calls = re.findall(r"(?m)^(.*)\bmountTermUnderline\(", cl)
  assert len(calls) == 1 and "await" not in calls[0] and "import" not in calls[0], calls
  page = cl[cl.index("async function renderPage("):cl.index("function drawMarkdown(")]
  call = 'mountTermUnderline(art, el.querySelector(".fl-toc"), () => seq === pageSeq);'
  assert call in page
  assert page.index("await Promise.all([colorCode(art), drawMermaid(art)]);") < page.index(call) < page.index("target.scrollIntoView"), "다 그린 뒤 · 스크롤 앞"
  assert re.search(r"if \(seq !== pageSeq\) return;\s*mountTermUnderline", page), "장이 바뀌었으면 시작도 안 한다"
  assert "drawMarkdown(" in page and "FORBID_TAGS" in cl, "글 거르기(TC-CLV-04)는 그대로"
  # 켜고 끄기 — 저장소가 막혀도 동작 · 기본 켬 · 끄면 글자로 되돌림
  assert 'localStorage.getItem(PREF_KEY) !== "off"' in code and re.search(r"try \{ return localStorage\.getItem", code)
  assert re.search(r"try \{ localStorage\.setItem\(PREF_KEY", code)
  assert "stopRun(root);" in code and "unwrapAll(root);" in code and "label.append(box, text);" in code
  assert '"용어 밑줄 보기"' in code
  # 실패해도 장 화면은 그대로 — 시작 함수 전체를 감싸고 한 줄만 남긴다
  mount = code[code.index("export function mountTermUnderline"):]
  assert "try {" in mount and "console.warn(" in mount


# ── 7. CSS ───────────────────────────────────────────────────────────────

def _zone() -> str:
  css = QCSS.read_text(encoding="utf-8")
  start = "/* ── 교재 용어 밑줄 (할 일 ①-23 B"
  assert css.count(start) == 1 and css.count("/* ── 교재 용어 밑줄 끝 ── */") == 1
  return css[css.index(start):css.index("/* ── 교재 용어 밑줄 끝 ── */")]


def test_css_uses_only_app_variables_and_does_not_rely_on_color_alone():
  """TC-TUL-07 · 교재 밑줄 구역(표시 주석 사이)에 하드코딩 색이 없고 · 쓰는 var(--…)는 앱에 정의돼 있고 ·
  점선 밑줄(모양) + 호버 실선 · 배경 + 키보드 초점 윤곽을 갖는다(색만으로 구분하지 않음) · 단추 기본 모양(테두리 · 배경 · 글꼴)은 글에 맞춰 초기화."""
  zone = _zone()
  body = re.sub(r"/\*.*?\*/", "", zone, flags=re.S)
  assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", body), "하드코딩 색"
  named = r"\b(?:red|blue|green|white|black|gray|grey|orange|yellow|purple|pink|navy|teal)\b"
  assert not re.search(named, body, re.I)
  used = set(re.findall(r"var\((--[a-z0-9-]+)", body))
  defined = set(re.findall(r"(--[a-z0-9-]+)\s*:", APPCSS.read_text(encoding="utf-8") + QCSS.read_text(encoding="utf-8")))
  assert used and used <= defined, used - defined
  assert "text-decoration: underline dotted var(--accent)" in body
  hover = re.search(r"button\.q-term-ul:hover \{([^}]*)\}", body)
  focus = re.search(r"button\.q-term-ul:focus-visible \{([^}]*)\}", body)
  assert hover and "background: var(--accent-glow)" in hover.group(1) and "text-decoration-style: solid" in hover.group(1)
  assert focus and "outline: 2px solid var(--accent)" in focus.group(1) and "outline-offset" in focus.group(1)
  base = re.search(r"button\.q-term-ul \{([^}]*)\}", body).group(1)
  for want in ("border: 0", "background: transparent", "color: inherit", "font: inherit", "cursor: pointer"):
    assert want in base, want
  assert ".q-term-ul-toggle" in body and "@media (max-width: 768px)" in body
  # 다른 구역(관계 지도)은 건드리지 않았다 — 표시 주석이 그대로 한 쌍
  css = QCSS.read_text(encoding="utf-8")
  assert css.count("/* ── 용어 관계 지도 (js/glossary.js") == 1 and css.count("/* ── 용어 관계 지도 끝") == 1
