"""TC-GLG — 할 일 ①-23 A : 용어사전 「관계 지도」 화면(public/js/glossary.js + css/qurious.css) · 2026-11-02

서버 graph API(GET /api/glossary/{이름}/graph)는 이미 있다(TC-GL-33). 이 시험은 그 응답을 화면이 제대로 읽고 그리는지를 본다.
브라우저 없이 — JS 는 글자로 읽고, 그리는 함수는 node 로 불러 HTML 글자를 받아 본다(없으면 그 시험만 건너뛴다).

1. glossary.js 가 graph 주소를 부르고(용어 ID · 깊이 둘이 서버 상한 안 — 처음 1 · 「더 보기」 때 2), 용어 카드(termcard.js)는 건드리지 않았다. (TC-GLG-01)
2. 화면이 읽는 필드 이름이 서버 graph() 가 돌려주는 필드와 맞는다 — 서버 이름을 바꾸면 여기서 깨진다. (TC-GLG-02)
3. 관계 종류를 색만으로 구분하지 않는다 — 글자 이름 · 기호 · 테두리 모양이 종류마다 다르다. (TC-GLG-03)
4. 실제 그리기(node): 종류별 자리 · 상위/하위 방향 · 한 줄 근거(note)는 종류와 상관없이 · 「더 보기」 단추는 처음엔 접힌 빈 칸 · 일부만 보여요 · 글자 이스케이프 · 노드는 단추. (TC-GLG-04)
5. 「더 보기」 로 받은 깊이 2 응답을 그린다 — 이웃에서 이어진 말 · 없으면 없다고 · 잘렸으면 단정하지 않고. (TC-GLG-04b)
6. 빈 상태는 정직하고, 불러오기 실패는 빈 상태로 둔갑하지 않으며, 늦은 응답이 다른 용어 화면을 덮지 않는다. (TC-GLG-05)
7. 「더 보기」 흐름(가짜 칸으로 node 에서 돌림): 첫 누름에만 깊이 2 요청 · 겹쳐 눌러도 한 번 · 이후엔 열고 닫기만 · 실패는 다시 시도 · 늦은 응답은 버림. (TC-GLG-05b)
8. CSS: 하드코딩 색이 없고, 앱 변수만 쓰고, 이음선은 넓은 구역(@container 720px~)에서만 — 좁은 구역(휴대폰 포함)은 가로 스크롤 없이 목록으로 쌓인다. (TC-GLG-06)
9. (실제 파일) 2026-11-02 적용한 관계 90건 — 한 줄 근거는 종류와 상관없이 있고, 상위 방향이 거꾸로 겹치지 않으며, 깊이 1 · 2 가 실제로 다르게 나온다. (TC-GLG-07)
"""
from __future__ import annotations

import inspect
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.services import glossary

ROOT = Path(__file__).resolve().parents[1]
PUB = ROOT / "public"
GL = PUB / "js" / "glossary.js"
CARD = PUB / "js" / "termcard.js"
COMMON = PUB / "js" / "common.js"
QCSS = PUB / "css" / "qurious.css"
APPCSS = PUB / "css" / "app.css"
ROUTE = ROOT / "app" / "routes" / "glossary.py"

GL_SRC = GL.read_text(encoding="utf-8")
CSS_SRC = QCSS.read_text(encoding="utf-8")


def _between(src: str, start: str, end: str) -> str:
  i = src.index(start)
  return src[i:src.index(end, i)]


#: glossary.js 의 관계 지도 구역 — 머리 주석부터 openTermPage 앞까지
GRAPH_JS = _between(GL_SRC, "// ── 관계 지도", "/** 용어 한 장 —")
#: qurious.css 의 관계 지도 구역(표시 주석 사이) — 같은 파일의 다른 구역에는 옛 하드코딩 색이 있어 이 구간만 본다
GRAPH_CSS = _between(CSS_SRC, "/* ── 용어 관계 지도 (js/glossary.js", "/* ── 용어 관계 지도 끝")


def _node() -> str:
  node = shutil.which("node")
  if not node:
    pytest.skip("Node 가 없어 화면 함수를 돌릴 수 없다")
  return node


def _server_keys() -> dict[str, set[str]]:
  """서버 graph() 가 돌려주는 필드 — 함수 글자에서 읽는다(최상위 · 노드 · 간선)."""
  src = inspect.getsource(glossary.graph)
  nodes = _between(src, "nodes = [", "links = [")
  edges = _between(src, "links = [", "return {")
  top = src[src.index("return {"):]
  keys = lambda s: set(re.findall(r'"(\w+)":', s))  # noqa: E731
  return {"top": keys(top), "node": keys(nodes), "edge": keys(edges)}


def test_screen_calls_graph_api_and_leaves_termcard_alone():
  """TC-GLG-01 · glossary.js 가 graph 주소를 용어 ID 로 부르고 · 깊이는 처음 1 / 「더 보기」 때 2 로 따로 요청하며 · 서버 상한 안이고 · 용어 카드 파일은 그대로"""
  assert "/api/glossary/${encodeURIComponent(term.id)}/graph?depth=${depth}" in GRAPH_JS
  first = int(re.search(r"const GRAPH_DEPTH_FIRST = (\d+);", GRAPH_JS).group(1))
  more = int(re.search(r"const GRAPH_DEPTH_MORE = (\d+);", GRAPH_JS).group(1))
  route = ROUTE.read_text(encoding="utf-8")
  limit = re.search(r"depth: int = Query\(1, ge=1, le=(\d+)", route)
  assert limit and 1 <= first < more <= int(limit.group(1)), "서버가 받는 depth 범위 안 — 처음은 가장 얕게, 더 보기는 한 걸음 더"
  assert first == 1, "처음 요청은 가운데와 바로 이어진 말만(깊이 1)"
  # 어느 요청이 어느 깊이를 쓰나 — 처음 지도(loadGraph)는 얕게, 더 보기(graphMoreToggle)는 깊게. 서로 섞이면 「요청한 만큼만」 이 깨진다
  load = GRAPH_JS[GRAPH_JS.index("async function loadGraph"):]
  toggle = _between(GRAPH_JS, "export async function graphMoreToggle", "function graphMoreErrorHtml")
  assert "fetchGraph(term, GRAPH_DEPTH_FIRST)" in load and "GRAPH_DEPTH_MORE" not in load
  assert "fetchGraph(term, GRAPH_DEPTH_MORE)" in toggle and "GRAPH_DEPTH_FIRST" not in toggle
  assert len(re.findall(r"\bapi\(", GRAPH_JS)) == 1, "서버를 부르는 곳은 fetchGraph 한 곳뿐"
  # 용어 한 장을 그릴 때 지도 자리를 만들고 불러온다 — 풀이 카드 아래, 카드를 기다리게 하지 않는다
  page = GL_SRC[GL_SRC.index("async function openTermPage"):GL_SRC.index("export function renderGlossary")]
  assert "termCardHtml(t, { page: true })}${graphHostHtml(uid)}" in page and "loadGraph(t," in page
  assert "await loadGraph" not in page, "지도를 기다리느라 풀이 카드가 늦어지면 안 된다"
  # 용어 카드(서랍이 공유)는 수정하지 않았다 — 해시 대신 「지도 흔적이 없고 · 가져오는 이름이 그대로」 를 본다
  card = CARD.read_text(encoding="utf-8")
  assert "/graph" not in card and "q-gm" not in card and "graph" not in card.lower()
  assert 'import { termCardHtml, takePendingTerm, wireCard } from "/js/termcard.js";' in GL_SRC, "카드에서 가져오는 이름은 기존 셋뿐"
  assert re.search(r"export function (termCardHtml|wireCard)\(", card) and "export function takePendingTerm()" in card
  # 노드는 검색창 Enter 가 집는 [data-open] 과 다른 이름을 쓴다 — 용어 한 장에서 Enter 가 지도 노드를 열면 안 된다
  assert "data-open=" not in GRAPH_JS and 'data-graph-open="' in GRAPH_JS


def test_fields_the_screen_reads_exist_in_server_response():
  """TC-GLG-02 · 화면이 읽는 필드 이름 = 서버 graph() 가 돌려주는 필드 이름. 노드의 category 는 코드 글자(객체가 아님)."""
  keys = _server_keys()
  assert keys["top"] == {"center", "depth", "nodes", "edges", "truncated"}, keys["top"]
  assert {"id", "term", "category", "summary", "level"} == keys["node"], keys["node"]
  assert {"from", "to", "kind", "kind_label", "note"} == keys["edge"], keys["edge"]
  view = _between(GRAPH_JS, "function graphView(", "/** 응답 → 화면 자료")
  # 응답을 읽는 구역 — graphView · graphModel · 그리는 함수들(graphHostHtml 앞까지). 단추 연결(wireGraph) · 불러오기(loadGraph)의 변수와 섞이지 않게 나눈다
  reading = GRAPH_JS[:GRAPH_JS.index("function graphHostHtml")]
  model = _between(GRAPH_JS, "function graphView(", "function graphGlyph")
  read = lambda var, text: set(re.findall(rf"\b{var}\??\.(\w+)", text))  # noqa: E731
  # g = 응답 · e = 간선 · a/b/node/center = 노드
  assert read("g", GRAPH_JS) <= keys["top"], read("g", GRAPH_JS)
  edge_reads = read("e", model) | read("edge", model)      # graphModel 의 e · graphView 의 edge
  assert edge_reads <= keys["edge"], edge_reads
  node_reads = read("a", model) | read("b", model) | read("node", reading) | read("center", reading)
  assert node_reads <= keys["node"], node_reads
  assert {"center", "nodes", "edges", "truncated"} <= read("g", GRAPH_JS), "중심 · 노드 · 간선 · 잘림 표시를 모두 읽는다"
  assert {"from", "to", "kind", "note"} <= edge_reads and {"id", "term", "summary", "level"} <= node_reads
  code = re.sub(r"//.*", "", GRAPH_JS)                  # 주석은 뺀 코드만
  assert "kind_label" not in code, "broader 는 어느 끝에서 보느냐로 상위/하위가 갈려 서버의 kind_label(항상 「상위 개념」)을 쓰지 않는다"
  assert ".category.name" not in reading and "node.category" not in code, "노드의 category 는 코드 글자 — 이름은 용어 한 건 응답(term.category)에서만"
  assert 'edge.kind === "broader" ? "narrower"' in view, "서버 related_terms 와 같은 규칙으로 broader 의 반대편은 하위"


def test_relation_kinds_differ_by_text_glyph_and_shape_not_only_color():
  """TC-GLG-03 · 종류 넷이 글자 이름 · 기호 · 테두리 모양으로 모두 달라서, 색을 못 보는 사람도 구분한다"""
  table = _between(GRAPH_JS, "const GRAPH_KINDS = {", "};")
  rows = re.findall(r'(\w+):\s*\{ zone: "(\w+)",\s+glyph: "([^"]+)", label: "([^"]+)" \}', table)
  assert [r[0] for r in rows] == ["confused_with", "related", "broader", "narrower"]
  for column, name in ((1, "zone"), (2, "기호"), (3, "글자 이름")):
    assert len({r[column] for r in rows}) == 4, f"{name} 이 종류마다 달라야 한다"
  # 기호는 화면 읽기 프로그램에 읽히지 않게 숨기고(글자 이름이 읽힌다) · 노드 이름에는 종류 이름이 들어간다
  assert 'class="q-gm-glyph" aria-hidden="true"' in GRAPH_JS
  assert "const label = `${spec.label}: ${item.node.term}" in GRAPH_JS and "aria-label=" in GRAPH_JS
  # 모양: 점선 · 둥근 실선 · 위쪽 굵은 선 · 아래쪽 굵은 선
  shape = {z: " ".join(re.findall(rf"\.q-gm-node--{z}(?:, [^{{]+)? \{{([^}}]*)\}}", GRAPH_CSS)) for z in ("confused", "related", "broader", "narrower")}
  assert "dashed" in shape["confused"] and "border-radius" in shape["confused"]
  assert "solid" in shape["related"] and "border-radius" in shape["related"]
  assert "border-top-width" in shape["broader"] and "border-bottom-width" in shape["narrower"]
  assert shape["confused"] != shape["related"] != shape["broader"] != shape["narrower"]
  # 이음선도 같은 종류끼리 모양이 다르다(점선 가로선 + 점선 줄기)
  assert "border-top-style: dashed" in GRAPH_CSS and "2px dashed var(--gm-c)" in GRAPH_CSS


def _fake_graph(center: str, nodes: list[tuple], edges: list[tuple], truncated: bool = False, depth: int = 1) -> dict:
  """서버가 돌려주는 모양 그대로 — 필드 이름은 서버 함수 글자에서 읽은 것을 쓴다(이름이 바뀌면 값이 비어 아래 단언이 깨진다)."""
  keys = _server_keys()
  node_vals = lambda i, term, level, summary: {"id": i, "term": term, "category": "quant", "summary": summary, "level": level}  # noqa: E731
  edge_vals = lambda f, t, k, note: {"from": f, "to": t, "kind": k, "kind_label": "표시이름", "note": note}  # noqa: E731
  out_nodes = [{k: node_vals(*n).get(k, "") for k in keys["node"]} for n in nodes]
  out_edges = [{k: edge_vals(*e).get(k, "") for k in keys["edge"]} for e in edges]
  return {"center": center, "depth": depth, "nodes": out_nodes, "edges": out_edges, "truncated": truncated}


@pytest.fixture(scope="module")
def node_env(tmp_path_factory):
  """glossary.js 를 node 로 불러 쓸 수 있게 한 폴더 — 파일을 바꾸지 않고 복사본의 import 만 stub 으로 바꾼다.
  stub api 는 globalThis.__api 가 있으면 그것을 부르고(흐름 시험이 요청을 가로챈다), 없으면 던진다."""
  node = _node()
  base = tmp_path_factory.mktemp("glg")
  common = COMMON.read_text(encoding="utf-8")
  esc = common[common.index("export function escHtml"):common.index("export function fmt(")]
  (base / "common.mjs").write_text('export async function api(path, opts) { if (globalThis.__api) return globalThis.__api(path, opts); throw new Error("stub"); }\n' + esc, encoding="utf-8")
  (base / "termcard.mjs").write_text("export function termCardHtml() { return \"\"; }\n"
                                     "export function takePendingTerm() { return null; }\nexport function wireCard() {}\n", encoding="utf-8")
  src = GL_SRC.replace('from "/js/common.js"', 'from "./common.mjs"').replace('from "/js/termcard.js"', 'from "./termcard.mjs"')
  assert "./common.mjs" in src and "./termcard.mjs" in src
  (base / "glossary.mjs").write_text(src, encoding="utf-8")
  return node, base


@pytest.fixture(scope="module")
def render(node_env):
  """입력마다 그리는 함수의 HTML 글자를 돌려주는 함수. 입력 한 건 = {term, graph, view} — view: "map"(기본 · 첫 지도) · "more"(「더 보기」 로 받은 응답)"""
  node, base = node_env
  (base / "run.mjs").write_text(
    'import { readFileSync } from "node:fs";\nglobalThis.window = {};\n'
    'const m = await import("./glossary.mjs");\n'
    'const input = JSON.parse(readFileSync(process.argv[2], "utf8"));\nconst out = {};\n'
    'for (const [k, v] of Object.entries(input)) {\n'
    '  if (v.view === "more") out[k] = m.graphMoreHtml(v.graph);\n'
    '  else out[k] = v.graph ? m.graphViewHtml(v.term, v.graph, 3) : m.graphEmptyHtml(v.term);\n}\n'
    'process.stdout.write(JSON.stringify(out));\n', encoding="utf-8")

  def run(cases: dict) -> dict:
    (base / "in.json").write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
    done = subprocess.run([node, str(base / "run.mjs"), str(base / "in.json")], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)

  return run


@pytest.fixture(scope="module")
def flow(node_env):
  """「더 보기」 단추의 흐름을 가짜 단추 · 가짜 칸으로 돌려 요청 횟수 · 깊이 · 칸의 모습을 돌려주는 함수.
  입력 한 건 = {term, uid, responses: [{ok: 응답} | {error: 글}], steps: ["click" | "double" | "retry"], disconnect: bool}.
  uid 0 = 지금 보는 용어 한 장의 번호(모듈 처음 값) · 그 밖의 번호 = 그사이 다른 용어로 옮겨 간 낡은 지도.
  단계마다 {immediate: 누른 직후(요청이 오가는 동안)의 칸 · after: 끝난 뒤의 칸} 을 남긴다."""
  node, base = node_env
  (base / "flow.mjs").write_text(
    'import { readFileSync } from "node:fs";\nglobalThis.window = {};\n'
    'const m = await import("./glossary.mjs");\n'
    'const cases = JSON.parse(readFileSync(process.argv[2], "utf8"));\nconst out = {};\n'
    'for (const [name, c] of Object.entries(cases)) {\n'
    '  const bAttrs = {}; const pAttrs = {}; const retries = [];\n'
    '  const btn = { dataset: { label: "이웃에서 이어진 말 더 보기" }, textContent: "이웃에서 이어진 말 더 보기",\n'
    '    setAttribute(k, v) { bAttrs[k] = String(v); } };\n'
    '  const panel = { hidden: true, innerHTML: "", isConnected: true,\n'
    '    setAttribute(k, v) { pAttrs[k] = String(v); }, removeAttribute(k) { delete pAttrs[k]; },\n'
    '    querySelectorAll(sel) { return sel === "[data-graph-more-retry]" && panel.innerHTML.includes("data-graph-more-retry")\n'
    '      ? [{ addEventListener(_, fn) { retries.push(fn); } }] : []; } };\n'
    '  const calls = []; const queue = [...c.responses];\n'
    '  globalThis.__api = async (path) => { calls.push(path); if (c.disconnect) panel.isConnected = false;\n'
    '    const r = queue.shift(); if (!r) throw new Error("응답 없음"); if (r.error) throw new Error(r.error); return r.ok; };\n'
    '  const snap = () => ({ state: btn.dataset.state || "idle", hidden: panel.hidden, expanded: bAttrs["aria-expanded"] ?? null,\n'
    '    label: btn.textContent, busy: pAttrs["aria-busy"] ?? null, html: panel.innerHTML });\n'
    '  const steps = [];\n'
    '  const press = () => m.graphMoreToggle(btn, panel, c.term, c.uid ?? 0);\n'
    '  for (const step of c.steps) {\n'
    '    const ps = step === "retry" ? [retries.pop()()] : step === "double" ? [press(), press()] : [press()];\n'
    '    const immediate = snap();\n'
    '    await Promise.all(ps); await new Promise(r => setTimeout(r, 5));\n'
    '    steps.push({ immediate, after: snap() });\n'
    '  }\n'
    '  out[name] = { calls, steps, unusedResponses: queue.length };\n}\n'
    'process.stdout.write(JSON.stringify(out));\n', encoding="utf-8")

  def run(cases: dict) -> dict:
    (base / "flow.json").write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
    done = subprocess.run([node, str(base / "flow.mjs"), str(base / "flow.json")], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)

  return run


def _node_html(html: str, node_id: str, zone: str) -> str:
  """지도에서 한 노드 단추의 HTML — 같은 용어가 두 종류로 이어졌으면 zone 으로 가른다."""
  m = re.search(rf'<button type="button" class="q-gm-node q-gm-node--{zone}" data-graph-open="{node_id}".*?</button>', html, re.S)
  assert m, f"{zone} 자리의 {node_id} 노드가 없다"
  return m.group(0)


def test_graph_drawing_zones_directions_notes_and_collapsed_more_button(render):
  """TC-GLG-04 · 종류별 자리 · broader 방향(상위/하위) · 한 줄 근거는 종류와 상관없이 · 「더 보기」 단추는 이웃이 있으면 늘 보이고 칸은 비어 접혀 있다 · 일부만 보여요 · 글자 이스케이프 · 노드는 단추"""
  term = {"id": "mdd", "term": "MDD", "category": {"code": "quant", "name": "퀀트"}}
  rich = _fake_graph(
    "mdd",
    nodes=[("mdd", "MDD", 0, "낙폭"), ("up", "위 <지표>", 1, "\"위험\" & 크기"), ("down", "하위 A", 1, "하위 요약"),
           ("calmar", "칼마 비율", 1, "연 수익률 ÷ MDD"), ("sharpe", "샤프 비율", 1, "초과수익 ÷ 변동성")],
    edges=[("mdd", "up", "broader", "MDD 는 위 <지표> 의 한 종류"), ("down", "mdd", "broader", ""),
           ("calmar", "mdd", "confused_with", "칼마는 낙폭 하나만 <b>x</b>"), ("mdd", "calmar", "related", ""),
           ("mdd", "sharpe", "related", "샤프와 함께 본다")],
    truncated=True)
  flat = _fake_graph("pbr", nodes=[("pbr", "PBR", 0, ""), ("per", "PER", 1, "주가 ÷ 이익")], edges=[("per", "pbr", "confused_with", "성장주는 PER")])
  alone = _fake_graph("alone", nodes=[("alone", "외톨이", 0, "")], edges=[])
  out = render({"rich": {"term": term, "graph": rich}, "flat": {"term": {"id": "pbr", "term": "PBR"}, "graph": flat},
                "alone": {"term": {"id": "alone", "term": "외톨이", "category": {"code": "basics", "name": "주식 기초"}}, "graph": alone}})
  h = out["rich"]
  # 종류별 자리 — 있는 종류만, 상위(위) 헷갈리기 쉬운 말(왼쪽) 함께 알면 좋은 말(오른쪽) 하위(아래) 차례
  order = [h.index(f"q-gm-zone--{z}") for z in ("broader", "confused", "related", "narrower")]
  assert order == sorted(order) and all(f'q-gm-zone--{z}"' in h for z in ("broader", "confused", "related", "narrower"))
  # 방향: mdd → up (broader) 이면 up 이 상위 · down → mdd (broader) 이면 down 이 하위
  assert 'q-gm-node--broader" data-graph-open="up"' in h and 'q-gm-node--narrower" data-graph-open="down"' in h
  assert "더 넓은 말 (상위): 위 &lt;지표&gt;" in h and "더 좁은 말 (하위): 하위 A" in h
  # 같은 용어가 두 종류로 이어졌으면 두 자리에 모두(칼마 비율: 헷갈리기 쉬운 말 + 함께 알면 좋은 말) · 개수는 서로 다른 용어를 센 값
  assert h.count('data-graph-open="calmar"') == 2
  assert "바로 이어진 말 4개" in h
  # 한 줄 근거(note) — 종류와 상관없이 있으면 그것이 노드 줄이고, 없으면 용어의 한 줄 풀이다
  up, down = _node_html(h, "up", "broader"), _node_html(h, "down", "narrower")
  assert "MDD 는 위 &lt;지표&gt; 의 한 종류" in up and "위험" not in up, "상위 관계의 note 가 풀이를 대신한다"
  assert "하위 요약" in down, "note 가 비면 한 줄 풀이"
  sharpe = _node_html(h, "sharpe", "related")
  assert "샤프와 함께 본다" in sharpe and "초과수익" not in sharpe, "함께 알면 좋은 말의 note 도 보인다"
  calmar_conf, calmar_rel = _node_html(h, "calmar", "confused"), _node_html(h, "calmar", "related")
  assert "칼마는 낙폭 하나만" in calmar_conf and "연 수익률" not in calmar_conf
  assert "연 수익률 ÷ MDD" in calmar_rel, "같은 용어라도 이어진 종류마다 따로 — 이쪽은 note 가 비어 풀이"
  # 글자는 이스케이프 — 응답의 꺾쇠 · 따옴표가 마크업이 되지 않는다
  assert "<b>x</b>" not in h and "&lt;b&gt;x&lt;/b&gt;" in h and "위 <지표>" not in h
  # 모든 노드는 단추(키보드로 닿는다) · 이름이 있다
  nodes = re.findall(r"<button type=\"button\" class=\"q-gm-node [^\"]+\" data-graph-open=\"[^\"]+\" aria-label=\"[^\"]+\">", h)
  assert len(nodes) >= 4 and 'aria-current="true"' in h and 'aria-label="MDD 의 관계 지도"' in h
  # 잘림은 응답의 truncated 로만 — 서버 상한 숫자는 화면에 쓰지 않는다
  assert "이어진 말이 많아 일부만 보여요" in h and "40" not in h
  # 「더 보기」 — 이웃이 있으면 단추가 있고(깊이 1 응답으로는 이웃의 이웃을 알 수 없다), 칸은 비어 접혀 있다. 개수는 아직 모르니 적지 않는다
  assert re.search(r'<button type="button" class="q-term-link q-gm-more-btn" data-graph-more data-label="이웃에서 이어진 말 더 보기" '
                   r'aria-expanded="false" aria-controls="q-gm-more-3">이웃에서 이어진 말 더 보기</button>', h)
  assert '<div class="q-gm-more" id="q-gm-more-3" aria-live="polite" hidden></div>' in h
  assert "한 걸음 더" not in h, "두 번째 단계는 누르기 전에는 그리지 않는다"
  # 이웃이 하나뿐이어도 단추는 있다(누르면 깊이 2) · 없는 종류의 자리는 만들지 않는다
  f = out["flat"]
  assert "data-graph-more" in f and "일부만 보여요" not in f and "q-gm-zone--confused" in f
  assert "q-gm-zone--broader" not in f and "q-gm-zone--related" not in f, "없는 종류의 자리는 만들지 않는다"
  # 이웃이 하나도 없으면 빈 상태 — 단추도 없다
  assert "이 용어는 아직 연결된 말이 없어요" in out["alone"] and "q-gm-map" not in out["alone"] and "data-graph-more" not in out["alone"]
  assert 'data-graph-category="basics"' in out["alone"] and "주식 기초" in out["alone"]


def test_more_html_lists_second_ring_and_is_honest_when_empty_or_cut(render):
  """TC-GLG-04b · 「더 보기」 로 받은 깊이 2 응답 — 이웃별로 이어진 말(종류 이름 · 한 줄 근거) · 개수는 받은 노드를 센 값 · 비면 없다고 · 잘렸으면 단정하지 않는다"""
  deep = _fake_graph(
    "mdd", depth=2,
    nodes=[("mdd", "MDD", 0, "낙폭"), ("calmar", "칼마 비율", 1, "연 수익률 ÷ MDD"), ("sharpe", "샤프 비율", 1, "초과수익 ÷ 변동성"),
           ("sterling", "스털링 비율", 2, "낙폭 평균"), ("sortino", "소르티노 비율", 2, "하방 편차")],
    edges=[("calmar", "mdd", "confused_with", "칼마는 낙폭 하나만"), ("mdd", "sharpe", "related", ""),
           ("sterling", "calmar", "confused_with", "스털링은 여러 낙폭 평균 <i>"), ("sharpe", "sortino", "confused_with", ""),
           ("calmar", "sharpe", "related", "둘 다 낙폭 · 변동성")])
  nothing = _fake_graph("mdd", depth=2, nodes=[("mdd", "MDD", 0, ""), ("calmar", "칼마 비율", 1, "")], edges=[("calmar", "mdd", "confused_with", "x")])
  cut_empty = {**nothing, "truncated": True}
  cut_some = {**deep, "truncated": True}
  out = render({"deep": {"view": "more", "graph": deep}, "nothing": {"view": "more", "graph": nothing},
                "cut_empty": {"view": "more", "graph": cut_empty}, "cut_some": {"view": "more", "graph": cut_some}})
  h = out["deep"]
  # 이웃별로 묶는다 — 가운데에 가까운 쪽(이웃)에서 본다. 이웃끼리 이어진 줄(칼마 ↔ 샤프)은 한 이웃 아래에 한 번
  assert "「칼마 비율」 에서 이어진 말" in h and "「샤프 비율」 에서 이어진 말" in h
  assert h.index("「샤프 비율」 에서") < h.index("「칼마 비율」 에서"), "이웃은 이름 가나다순"
  # 개수는 받은 노드를 센 값 — 스털링 · 샤프 · 소르티노 세 용어
  assert "한 걸음 더 — 이웃에서 이어진 말 3개" in h
  # 둘째 단계는 종류 이름을 글로 한 번 더 적고, 한 줄 근거(note)가 있으면 그것을 보인다 · 이스케이프
  assert "헷갈리기 쉬운 말" in h and "함께 알면 좋은 말" in h
  assert "스털링은 여러 낙폭 평균 &lt;i&gt;" in h and "<i>" not in h and "둘 다 낙폭 · 변동성" in h
  assert 'data-graph-open="sterling"' in h and 'data-graph-open="sortino"' in h
  assert "일부만 보여요" not in h and "40" not in h
  # 이웃에서 이어진 말이 없으면 「없다」 — 응답이 비었을 때만
  n = out["nothing"]
  assert "이웃에서 더 이어진 말이 없어요" in n and 'role="status"' in n and "data-graph-open" not in n and "한 걸음 더" not in n
  # 서버가 자른 응답은 「없다」 고 단정하지 않는다
  ce = out["cut_empty"]
  assert "다 가져오지 못했어요" in ce and "더 이어진 말이 없어요" not in ce
  assert "이어진 말이 많아 일부만 보여요" in out["cut_some"] and "한 걸음 더" in out["cut_some"]


def test_empty_state_is_honest_and_failure_is_not_empty(render):
  """TC-GLG-05 · 빈 상태 문구 · 연관 개념이 없으면 묻지 않음 · 불러오기 실패는 빈 상태가 아니라 다시 시도 · 늦은 응답 가드"""
  assert "이 용어는 아직 연결된 말이 없어요" in GRAPH_JS
  assert "없는 말" not in GRAPH_JS and "관계가 없" not in GRAPH_JS, "「없다」 고 단정하지 않는다 — 아직 이어 두지 않았을 뿐"
  load = GRAPH_JS[GRAPH_JS.index("async function loadGraph"):]
  # 연관 개념이 0개면(대부분) 같은 표를 읽는 graph 도 비어 있어 묻지 않고 빈 상태
  assert "term.related.length === 0" in load and load.index("term.related.length === 0") < load.index("await fetchGraph(")
  # 실패 가지는 빈 상태를 쓰지 않고 오류 문구 + 다시 시도 — 요청을 보낸 뒤의 어떤 가지도 graphEmptyHtml 을 직접 부르지 않는다
  after_request = load[load.index("await fetchGraph("):]
  assert "graphEmptyHtml" not in after_request
  catch = _between(load, "} catch (e) {", "if (stale()) return;                                  //")
  assert "graphErrorHtml(e?.message)" in catch
  err = _between(GRAPH_JS, "function graphErrorHtml", "/** 지도 본문")
  assert "관계 지도를 불러오지 못했어요" in err and "data-graph-retry" in err and "다시 시도" in err
  # 늦은 응답: 용어 한 장마다 번호를 매겨, 번호가 달라졌거나 자리가 화면에서 사라졌으면 조용히 버린다
  assert "uid !== graphSeq || !host.isConnected" in load
  # 응답의 중심이 이 용어가 아니면 그리지 않되 「불러오는 중」 으로 남겨 두지도 않는다(오류 + 다시 시도) — 멈춘 화면 방지
  assert "g?.center === term.id ? graphViewHtml(term, g, uid) : graphErrorHtml(" in after_request
  # 끝나는 길(빈 상태 · 오류 · 그림)은 모두 한 함수를 거쳐 aria-busy 를 걷는다
  finish = _between(load, "const finish = (html) => {", "};")
  assert 'host.removeAttribute("aria-busy")' in finish and "wireGraph(host, term, uid)" in finish
  assert "const uid = ++graphSeq;" in GL_SRC
  # 지도 노드를 눌러 옮겨 온 경우만 제목에 초점(검색창 흐름은 그대로)
  assert "{ focusTitle: true }" in GRAPH_JS and "if (focusTitle)" in GL_SRC
  # 화면 읽기 프로그램: 구역 제목 · 지도 묶음 · 가운데 용어 표시
  assert "aria-labelledby=" in GRAPH_JS and 'role="group"' in GRAPH_JS and 'aria-busy="true"' in GRAPH_JS


#: 흐름 시험이 쓰는 응답 — 깊이 2 (칼마 비율 이웃에서 스털링 비율이 이어진다)
_DEEP = _fake_graph(
  "mdd", depth=2,
  nodes=[("mdd", "MDD", 0, "낙폭"), ("calmar", "칼마 비율", 1, "연 수익률 ÷ MDD"), ("sterling", "스털링 비율", 2, "낙폭 평균")],
  edges=[("calmar", "mdd", "confused_with", "칼마는 낙폭 하나만"), ("sterling", "calmar", "confused_with", "스털링은 여러 낙폭 평균")])
_NOTHING = _fake_graph("mdd", depth=2, nodes=[("mdd", "MDD", 0, ""), ("calmar", "칼마 비율", 1, "")], edges=[("calmar", "mdd", "confused_with", "x")])
_MDD = {"id": "mdd", "term": "MDD"}
_DEPTH2 = "/api/glossary/mdd/graph?depth=2"


def test_more_button_asks_depth_two_once_then_only_opens_and_closes(flow):
  """TC-GLG-05b · 첫 누름에만 깊이 2 를 요청(받는 동안은 불러오는 중 · 겹쳐 눌러도 한 번) · 받은 뒤에는 열고 닫기만(다시 묻지 않음)"""
  out = flow({
    "once": {"term": _MDD, "responses": [{"ok": _DEEP}, {"ok": _DEEP}], "steps": ["click", "click", "click"]},
    "double": {"term": _MDD, "responses": [{"ok": _DEEP}, {"ok": _DEEP}], "steps": ["double"]},
  })
  once = out["once"]
  assert once["calls"] == [_DEPTH2], "요청은 깊이 2 한 번뿐 — 접었다 펴도 다시 묻지 않는다"
  s0, s1, s2 = once["steps"]
  # 누른 직후(응답이 오기 전): 칸은 열려 있고 「불러오는 중」 · 단추 글자는 그대로
  im = s0["immediate"]
  assert (im["state"], im["hidden"], im["expanded"], im["busy"]) == ("loading", False, "true", "true")
  assert "불러오는 중" in im["html"] and im["label"] == "이웃에서 이어진 말 더 보기"
  # 받은 뒤: 이웃에서 이어진 말이 채워지고 aria-busy 를 걷고 단추는 「접기」
  af = s0["after"]
  assert (af["state"], af["hidden"], af["expanded"], af["busy"]) == ("done", False, "true", None)
  assert "한 걸음 더" in af["html"] and 'data-graph-open="sterling"' in af["html"] and af["label"] == "이웃에서 이어진 말 접기"
  # 두 번째 누름 = 접기 · 세 번째 = 다시 펴기(같은 내용)
  assert (s1["after"]["hidden"], s1["after"]["expanded"], s1["after"]["label"]) == (True, "false", "이웃에서 이어진 말 더 보기")
  assert (s2["after"]["hidden"], s2["after"]["expanded"]) == (False, "true") and s2["after"]["html"] == af["html"]
  # 겹쳐 눌러도 요청은 한 번 — 두 번째 응답은 쓰이지 않는다
  assert out["double"]["calls"] == [_DEPTH2] and out["double"]["unusedResponses"] == 1


def test_more_button_says_none_only_when_the_response_is_empty_and_failure_is_not_none(flow):
  """TC-GLG-05b · 응답이 비어 오면 「더 이어진 말이 없어요」 · 실패는 오류 + 다시 시도(없다고 둔갑하지 않음) · 다시 시도는 깊이 2 만 · 엉뚱한 응답은 오류"""
  out = flow({
    "empty": {"term": _MDD, "responses": [{"ok": _NOTHING}], "steps": ["click"]},
    "cut": {"term": _MDD, "responses": [{"ok": {**_NOTHING, "truncated": True}}], "steps": ["click"]},
    "fail": {"term": _MDD, "responses": [{"error": "서버 <오류>"}, {"ok": _DEEP}], "steps": ["click", "click", "click"]},
    "retry": {"term": _MDD, "responses": [{"error": "끊김"}, {"ok": _DEEP}], "steps": ["click", "retry"]},
    "other": {"term": _MDD, "responses": [{"ok": {**_DEEP, "center": "per"}}], "steps": ["click"]},
  })
  e = out["empty"]["steps"][0]["after"]
  assert "이웃에서 더 이어진 말이 없어요" in e["html"] and e["state"] == "done" and e["hidden"] is False and "data-graph-open" not in e["html"]
  assert "다 가져오지 못했어요" in out["cut"]["steps"][0]["after"]["html"], "서버가 자른 응답은 「없다」 고 하지 않는다"
  # 실패 → 오류 문구(이스케이프) + 다시 시도, 「없어요」 가 아니다. 칸은 열린 채
  fail = out["fail"]
  f0 = fail["steps"][0]["after"]
  assert f0["state"] == "error" and f0["hidden"] is False and f0["busy"] is None
  assert "불러오지 못했어요" in f0["html"] and "서버 &lt;오류&gt;" in f0["html"] and "data-graph-more-retry" in f0["html"]
  assert "이어진 말이 없어요" not in f0["html"]
  # 오류가 열려 있을 때 단추 = 접기(다시 묻지 않음) · 접힌 오류에서 단추 = 다시 시도(두 번째 요청이 성공)
  s1 = fail["steps"][1]
  assert s1["immediate"]["state"] == "error" and s1["after"]["hidden"] is True and s1["after"]["label"] == "이웃에서 이어진 말 더 보기", "접기만 — 요청 중 상태로 가지 않는다"
  f2 = fail["steps"][2]["after"]
  assert fail["calls"] == [_DEPTH2, _DEPTH2] and f2["state"] == "done" and "한 걸음 더" in f2["html"] and f2["hidden"] is False
  # 칸 안의 「다시 시도」 단추 = 깊이 2 만 다시 묻는다
  r = out["retry"]
  assert r["calls"] == [_DEPTH2, _DEPTH2] and r["steps"][1]["after"]["state"] == "done" and "한 걸음 더" in r["steps"][1]["after"]["html"]
  assert r["steps"][1]["immediate"]["state"] == "loading"
  # 이 용어의 지도가 아닌 응답 → 그리지 않고 오류
  o = out["other"]["steps"][0]["after"]
  assert o["state"] == "error" and "이 용어의 지도가 아닌 응답" in o["html"] and "한 걸음 더" not in o["html"]


def test_more_button_drops_late_answers_for_another_term(flow):
  """TC-GLG-05b · 응답이 오기 전에 다른 용어로 옮겼거나(번호가 다름) 자리가 화면에서 사라졌으면 낡은 칸을 건드리지 않는다"""
  out = flow({
    "moved": {"term": _MDD, "uid": 7, "responses": [{"ok": _DEEP}], "steps": ["click"]},
    "gone": {"term": _MDD, "disconnect": True, "responses": [{"ok": _DEEP}], "steps": ["click"]},
    "gone_err": {"term": _MDD, "disconnect": True, "responses": [{"error": "끊김"}], "steps": ["click"]},
  })
  for name in ("moved", "gone", "gone_err"):
    a = out[name]["steps"][0]["after"]
    assert out[name]["calls"] == [_DEPTH2]
    assert "불러오는 중" in a["html"] and "한 걸음 더" not in a["html"] and "불러오지 못했어요" not in a["html"], name


def test_applied_relations_have_notes_direction_and_both_depths_differ():
  """TC-GLG-07 · (실제 파일) 2026-11-02 적용한 관계 — 후보표 🟢 51건(헷갈리는 말 12 · 상위 14 · 연관 25)과 승인한 🟡 8건(헷갈리는 말 6 · 상위 2)이 31건에 더해져 90건 ·
  한 줄 근거(note)는 사람이 고른 줄 모두에 있다 · 상위 방향이 거꾸로 겹치지 않는다 · 깊이 1 과 2 가 실제로 달라서 「더 보기」 가 뜻이 있다
  (둘 다 있다: 이웃의 이웃이 있는 용어 / 없는 용어). 보류한 1건(무차입 공매도 → 공매도)이 나중에 더해져 늘어도 깨지지 않게 하한으로 본다."""
  from collections import Counter, defaultdict

  data = glossary.read_seed()[0]
  rels = data["relations"]
  kinds = Counter(r["kind"] for r in rels)
  assert len(rels) >= 90 and kinds["confused_with"] >= 47 and kinds["related"] >= 27 and kinds["broader"] >= 16, kinds
  curated = [r for r in rels if r["source"] == "curated"]
  assert len(curated) >= 60, "자기자본비율 ↔ BIS 비율 1건 + 이번에 더한 59건"
  assert all(r["note"] for r in curated), "사람이 고른 줄은 종류와 상관없이 한 줄 근거가 있다"
  assert all(r["note"] for r in rels if r["kind"] in ("confused_with", "broader")), "혼동 · 상위 모두 근거가 있다"
  # 상위(broader)는 (좁은 쪽 → 넓은 쪽) — 거꾸로 한 쌍이 함께 있으면 서로가 서로의 상위가 된다
  broader = {(r["from"], r["to"]) for r in rels if r["kind"] == "broader"}
  assert not {(b, a) for a, b in broader} & broader and all(a != b for a, b in broader)
  # 서버 graph() 와 같은 규칙(양 끝에서 이웃) 으로 깊이 1 · 2 를 센다
  adj: dict[str, set[str]] = defaultdict(set)
  for r in rels:
    adj[r["from"]].add(r["to"])
    adj[r["to"]].add(r["from"])
  has_more = {t: any(adj[n] - {t} for n in adj[t]) for t in adj}
  assert any(has_more.values()), "이웃의 이웃이 있는 용어가 있다 — 「더 보기」 가 채워진다"
  assert not all(has_more.values()), "이웃의 이웃이 없는 용어도 있다 — 눌러서 비면 「더 이어진 말이 없어요」"
  assert len(adj["etf"]) >= 9 and has_more["etf"], "ETF 는 이웃이 많고(ETN · 펀드 · 괴리율 · 순자산가치 …) 한 걸음 더 이어진다"


def _media_block(css: str, header: str) -> str:
  i = css.index(header)
  depth, j = 0, css.index("{", i)
  for k in range(j, len(css)):
    depth += css[k] == "{"
    depth -= css[k] == "}"
    if depth == 0:
      return css[j + 1:k]
  raise AssertionError("닫는 괄호가 없다")


def test_css_uses_only_app_variables_and_folds_on_narrow_screens():
  """TC-GLG-06 · 하드코딩 색 없음(JS · CSS 구역) · 쓰는 변수는 앱에 모두 있음 · 이음선과 격자는 넓은 구역(@container)에서만(좁은 구역은 목록)"""
  # 하드코딩 색: 16진수 · rgb/hsl 함수 · 이름 있는 색을 값으로 쓰지 않는다
  color_value = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|:\s*(white|black|red|green|blue|gray|grey|orange|yellow|purple)\b", re.I)
  assert not color_value.search(GRAPH_CSS), color_value.search(GRAPH_CSS)
  assert not color_value.search(GL_SRC), "glossary.js 전체에 색 글자가 없다"
  assert "style=" not in GRAPH_JS, "JS 가 색을 직접 칠하지 않는다 — 종류별 색은 클래스로"
  # 쓰는 var(--…) 가 앱(app.css · qurious.css 의 :root)에 정의돼 있다 — 이 구역이 자체로 정의하는 --gm-c · --gm-t 는 제외
  roots = "".join(re.findall(r":root\s*\{([^}]*)\}", APPCSS.read_text(encoding="utf-8") + CSS_SRC))
  defined = set(re.findall(r"(--[\w-]+)\s*:", roots))
  used = set(re.findall(r"var\((--[\w-]+)", GRAPH_CSS)) - {"--gm-c", "--gm-t"}
  assert used and used <= defined, f"앱에 없는 변수 {used - defined}"
  assert "--red" not in used and "--green" not in used, "빨강 · 초록은 이 앱에서 손익 · 매수/매도 색"
  assert "--brand-text" in used, "주황 기호 글자는 대비가 검증된 --brand-text(5:1) — --brand 는 테두리만"
  # 넓은 모양은 화면 너비가 아니라 「구역 너비」 로 가른다(왼쪽 메뉴를 빼면 화면 1000px 쯤에서도 구역이 700px 안팎이다)
  assert re.search(r"\.q-gm \{[^}]*container-type: inline-size", GRAPH_CSS), "구역이 컨테이너"
  assert "@media (min-width" not in GRAPH_CSS, "화면 너비로 가르면 메뉴 옆 좁은 구역에서 열이 찌그러진다"
  # 좁은 화면 기본(컨테이너 쿼리 밖)에는 이음선 · 격자 · 고정 위치가 없다 — 모두 @container 안에만
  wide = _media_block(GRAPH_CSS, "@container (min-width: 720px)")
  narrow = GRAPH_CSS.replace(wide, "")
  assert "::before" not in narrow and "::after" not in narrow, "이음선은 넓은 구역에서만"
  assert "grid-template-columns" not in narrow and "position: absolute" not in narrow and "position: fixed" not in narrow
  assert "grid-template-columns" in wide and "::before" in wide and "::after" in wide
  assert re.search(r"\.q-gm-map \{ display: flex; flex-direction: column;", narrow), "좁은 화면은 위에서 아래로 쌓는다"
  # 긴 용어 이름 · 풀이가 가로로 넘치지 않는다
  assert narrow.count("overflow-wrap: anywhere") >= 3 and "min-width: 0" in narrow
  assert not re.search(r"(^|[\s;{])width:\s*\d+px", narrow), "고정 너비로 가로 스크롤을 만들지 않는다(최소 높이 44px 는 터치 크기)"
  assert "min-height: 44px" in narrow, "노드는 손가락으로 누를 만한 크기"
  assert ":focus-visible" in GRAPH_CSS, "키보드 초점 표시"
