/* 용어사전 화면 — 「금융 필수 지식」 › 용어사전 (2026-10-02 · 화면 설계 결정 ①: 두 안을 합친다)
 *
 *   찾기 첫 화면   큰 검색창 · 자주 찾는 용어 · 분류 카드 · 최근 본 용어 (처음 온 사람이 둘러보기 쉽게)
 *   찾기          글자를 치면 0.2초 뒤 GET /api/glossary?q= — 줄마다 「무엇으로 찾았나」(matched · 약어 · 영어 · 초성 · 풀이)
 *   분류          분류 카드를 누르면 그 분류의 용어를 가나다순으로(GET /api/glossary?category=)
 *   용어 한 장     풀이 카드를 넓게 + 그 아래 「관계 지도」 — 다른 화면의 서랍과 같은 카드
 *   관계 지도     GET /api/glossary/{ID}/graph — 가운데 용어와 이어진 말을 종류별로 둘러 놓는다 (2026-11-02 · 할 일 ①-23 A)
 *
 * 카드 HTML 은 js/termcard.js 의 termCardHtml 하나 — 서랍 · 작은 창 · 큰 창 · 이 화면이 같은 모양이다.
 * 관계 지도는 이 파일만의 구역이다(서랍은 연관 개념 칩까지만) — termcard.js 를 고치지 않는다.
 */
import { api, escHtml } from "/js/common.js";
import { termCardHtml, takePendingTerm, wireCard } from "/js/termcard.js";

const RECENT_KEY = "qurious.glossary.recent";
const RECENT_MAX = 8;
// 처음 온 사람이 눌러 볼 만한 말 — 이 서비스의 화면(성과 검증 · 리밸런싱 · ETF)에서 자주 나오는 것
const POPULAR = ["PER", "샤프 비율", "MDD", "ETF", "리밸런싱", "괴리율", "RSI", "배당수익률"];
const MATCH_LABEL = { "약어": "약어로 찾음", "영어": "영어 이름으로 찾음", "다른 이름": "다른 이름으로 찾음",
  "화면 키": "화면 이름으로 찾음", "초성": "초성으로 찾음", "본문": "풀이에서 찾음" };

let rootEl = null;
let timer = null;
let lastQuery = "";

function recent() {
  try { return JSON.parse(localStorage.getItem(RECENT_KEY) || "[]").slice(0, RECENT_MAX); } catch { return []; }
}
function remember(t) {
  try {
    const list = recent().filter(x => x.id !== t.id);
    list.unshift({ id: t.id, term: t.term });
    localStorage.setItem(RECENT_KEY, JSON.stringify(list.slice(0, RECENT_MAX)));
  } catch { /* 저장 못 해도 화면은 그대로 */ }
}

function shell(inner) {
  return `<div class="q-gl">
    <div class="q-gl-search">
      <h2 class="q-gl-title">무엇이 궁금하세요?</h2>
      <p class="q-gl-lead" id="q-gl-lead">이름 · 약어 · 영어 · 초성으로 찾아요</p>
      <label class="q-gl-box"><i class="fa-solid fa-magnifying-glass"></i>
        <input id="q-gl-q" type="search" autocomplete="off" placeholder="PER, 샤프 비율, ㅅㄱㅊㅇ …" aria-label="용어 찾기" value="${escHtml(lastQuery)}" /></label>
      <div class="q-gl-popular"><span>자주 찾는 용어</span>${POPULAR.map(p =>
        `<button type="button" class="q-term-chip q-term-chip--link" data-open="${escHtml(p)}">${escHtml(p)}</button>`).join("")}</div>
    </div>
    <div id="q-gl-main">${inner}</div>
  </div>`;
}

function bindShell() {
  const input = rootEl.querySelector("#q-gl-q");
  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => search(input.value), 200);
  });
  input.addEventListener("keydown", e => {
    if (e.key === "Enter") {
      const first = rootEl.querySelector("#q-gl-main [data-open]");
      if (first) openTermPage(first.dataset.open);
    }
  });
  rootEl.querySelectorAll(".q-gl-popular [data-open]").forEach(b => b.addEventListener("click", () => openTermPage(b.dataset.open)));
}

function bindMain() {
  const main = rootEl.querySelector("#q-gl-main");
  main.querySelectorAll("[data-open]").forEach(b => b.addEventListener("click", () => openTermPage(b.dataset.open)));
  main.querySelectorAll("[data-category]").forEach(b => b.addEventListener("click", () => showCategory(b.dataset.category, b.dataset.name)));
  main.querySelectorAll("[data-home]").forEach(b => b.addEventListener("click", () => home()));
}

async function home() {
  lastQuery = "";
  rootEl.innerHTML = shell(`<div class="q-gl-loading">분류를 불러오는 중…</div>`);
  bindShell();
  let cats = null;
  try { cats = await api("/api/glossary/categories", { redirectOnUnauthorized: false }); } catch (e) {
    rootEl.querySelector("#q-gl-main").innerHTML = `<p class="q-term-note">용어사전을 불러오지 못했습니다 — ${escHtml(e.message)}
      <button type="button" class="q-term-link" data-home>다시 시도</button></p>`;
    bindMain();
    return;
  }
  rootEl.querySelector("#q-gl-lead").textContent = `용어 ${cats.total_terms.toLocaleString("ko-KR")}개 · 이름 · 약어 · 영어 · 초성으로 찾아요`;
  const rec = recent();
  rootEl.querySelector("#q-gl-main").innerHTML = `
    <h3 class="q-gl-h">분류로 둘러보기</h3>
    <div class="q-gl-cats">${cats.categories.map(c => `
      <button type="button" class="q-gl-cat" data-category="${escHtml(c.code)}" data-name="${escHtml(c.name)}">
        <strong>${escHtml(c.name)}</strong> <span class="q-gl-count">${c.terms}</span>
        ${c.description ? `<p>${escHtml(c.description)}</p>` : ""}</button>`).join("")}</div>
    ${rec.length ? `<h3 class="q-gl-h">최근 본 용어</h3><div class="q-gl-recent">${rec.map(r =>
      `<button type="button" class="q-term-chip q-term-chip--link" data-open="${escHtml(r.id)}">${escHtml(r.term)}</button>`).join("")}</div>` : ""}`;
  bindMain();
}

function rowHtml(i) {
  const m = i.matched || {};
  const why = m.kind && m.kind !== "대표 이름"
    ? `<span class="q-gl-why">${escHtml(MATCH_LABEL[m.kind] || m.kind)}${m.alias && m.kind !== "초성" ? ` · ${escHtml(m.alias)}` : ""}</span>` : "";
  return `<button type="button" class="q-gl-row" data-open="${escHtml(i.id)}">
    <span class="q-gl-row-head"><strong>${escHtml(i.term)}</strong>${i.english ? `<em>${escHtml(i.english)}</em>` : ""}${why}</span>
    <span class="q-gl-row-sum">${escHtml(i.summary || "")}</span>
    <span class="q-gl-row-cat">${escHtml(i.category?.name || "")}</span></button>`;
}

async function search(q) {
  lastQuery = q.trim();
  const main = rootEl.querySelector("#q-gl-main");
  if (!lastQuery) { home(); return; }
  main.innerHTML = `<div class="q-gl-loading">찾는 중…</div>`;
  let res;
  try { res = await api(`/api/glossary?limit=40&q=${encodeURIComponent(lastQuery)}`, { redirectOnUnauthorized: false }); } catch (e) {
    main.innerHTML = `<p class="q-term-note">찾지 못했습니다 — ${escHtml(e.message)}</p>`;
    return;
  }
  if (q.trim() !== lastQuery) return;     // 그사이 글자가 바뀌었다
  main.innerHTML = res.items.length
    ? `<p class="q-gl-total">「${escHtml(lastQuery)}」 — ${res.total}개</p><div class="q-gl-list">${res.items.map(rowHtml).join("")}</div>`
    : `<div class="q-gl-empty"><p>「${escHtml(lastQuery)}」 을(를) 찾지 못했습니다.</p>
        <p>다른 이름 · 영어 · 초성(예: ㅅㄱㅊㅇ)으로 찾아 보거나, 분류에서 둘러보세요.</p>
        <button type="button" class="q-term-link" data-home>← 분류로 둘러보기</button></div>`;
  bindMain();
}

/** 서버는 한 번에 100개까지만 준다(API-GLOS-01 · limit ≤ 100). 분류 하나를 다 보이려고 100개씩 이어 받는다.
 *  2026-10-03 — 처음에는 limit=200 한 번이라 서버가 422 를 돌려 분류 카드를 누르면 「불러오지 못했습니다」 가 떴다. */
const GL_PAGE = 100;

async function fetchCategory(code) {
  const items = [];
  let total = 0;
  for (let offset = 0; ; offset += GL_PAGE) {
    const res = await api(`/api/glossary?limit=${GL_PAGE}&offset=${offset}&category=${encodeURIComponent(code)}`, { redirectOnUnauthorized: false });
    total = res.total;
    items.push(...res.items);
    if (!res.items.length || items.length >= total) break;
  }
  return { total, items };
}

async function showCategory(code, name) {
  const main = rootEl.querySelector("#q-gl-main");
  main.innerHTML = `<div class="q-gl-loading">불러오는 중…</div>`;
  let res;
  try { res = await fetchCategory(code); } catch (e) {
    main.innerHTML = `<p class="q-term-note">불러오지 못했습니다 — ${escHtml(e.message)}</p>`;
    return;
  }
  main.innerHTML = `<div class="q-gl-crumb"><button type="button" class="q-term-link" data-home>← 분류로 둘러보기</button>
      <h3 class="q-gl-h">${escHtml(name)} <span class="q-gl-count">${res.total}</span></h3></div>
    <div class="q-gl-list">${res.items.map(rowHtml).join("")}</div>`;
  bindMain();
}

// ── 관계 지도 (할 일 ①-23 A · 2026-11-02) ──────────────────────────────────────────────────────────────
// 서버 응답 GET /api/glossary/{용어 ID}/graph?depth=1 (처음) · depth=2 (「더 보기」 를 누를 때) (app/services/glossary.py graph()):
//   { center, depth, truncated, nodes: [{ id, term, category(분류 코드 글자), summary, level }],
//     edges: [{ from, to, kind, kind_label, note }] }
//   · kind 는 저장된 그대로(confused_with · related · broader) — narrower 는 응답에 없다. broader 는 (좁은 쪽 → 넓은 쪽) 한 줄이라
//     가운데 용어에서 보면 from 이 가운데면 상대가 「상위」, to 가 가운데면 상대가 「하위」다(서버 related_terms 와 같은 규칙).
//   · 응답에 없는 숫자 · 사실은 화면에서 만들지 않는다 — 보이는 개수는 받은 노드를 센 것이고, 노드 상한(서버 값)은 적지 않는다.
//   · 한 줄 근거(edge.note)는 종류와 상관없이 올 수 있다 — 서버가 관계마다 그대로 싣는다(헷갈리는 말 · 함께 알면 좋은 말 · 상위 모두).
// 깊이는 요청한 만큼만 받는다(2026-11-02) — 처음에는 가운데와 바로 이어진 말(깊이 1)만 요청하고, 「이웃에서 이어진 말 더 보기」 를 누를 때
// 비로소 깊이 2 를 요청한다. 깊이 1 응답에는 이웃의 이웃을 알 수 있는 값이 없어 단추는 이웃이 있으면 늘 보이고, 눌러서 비어 오면
// 「더 이어진 말이 없어요」 로 그대로 알린다(눌러도 아무것도 안 나오는 단추를 숨기는 길은 서버 응답에 근거가 없어 쓰지 않는다).
const GRAPH_DEPTH_FIRST = 1;            // 처음 요청 — 가운데와 바로 이어진 말
const GRAPH_DEPTH_MORE = 2;             // 「더 보기」 를 누를 때 — 이웃에서 한 걸음 더(서버 상한)
// 종류마다 [글자 이름] + [기호] + [테두리 모양]이 다르다 — 색만으로 구분하지 않는다(css/qurious.css 「용어 관계 지도」).
const GRAPH_KINDS = {
  confused_with: { zone: "confused", glyph: "≠", label: "헷갈리기 쉬운 말" },     // 점선 · 네모
  related:       { zone: "related",  glyph: "↔", label: "함께 알면 좋은 말" },     // 실선 · 둥근 모양
  broader:       { zone: "broader",  glyph: "▲", label: "더 넓은 말 (상위)" },     // 위쪽 굵은 선
  narrower:      { zone: "narrower", glyph: "▼", label: "더 좁은 말 (하위)" },     // 아래쪽 굵은 선
};
const GRAPH_ZONES = ["broader", "confused_with", "related", "narrower"];          // 넓은 화면의 위 · 왼쪽 · 오른쪽 · 아래 (읽는 차례)
let graphSeq = 0;                       // 늦게 온 응답이 새 용어 화면을 덮지 않게

function graphKind(kind) {
  return GRAPH_KINDS[kind] ? kind : "related";      // 모르는 종류는 「함께 알면 좋은 말」 로 — 서버가 새 종류를 만들면 이 표에 먼저 올린다
}

/** from 쪽에서 본 간선 — 상대 끝과 종류. broader 는 방향에 따라 상위 · 하위가 된다. */
function graphView(edge, fromId) {
  if (edge.from === fromId) return { other: edge.to, kind: graphKind(edge.kind) };
  return { other: edge.from, kind: edge.kind === "broader" ? "narrower" : graphKind(edge.kind) };
}

/** 응답 → 화면 자료. first = 가운데와 바로 이어진 말 · further = 이웃에서 한 걸음 더 이어진 말(이웃별). */
export function graphModel(g) {
  const nodes = new Map((g?.nodes || []).map(n => [n.id, n]));
  const center = nodes.get(g?.center) || null;
  const first = [];
  const firstSeen = new Set();
  const further = new Map();              // 이웃 id → [{ node, kind, note }]
  const furtherSeen = new Set();
  for (const e of g?.edges || []) {
    if (e.from === g.center || e.to === g.center) {
      const v = graphView(e, g.center);
      const node = nodes.get(v.other);
      if (!node || node.id === g.center || firstSeen.has(`${node.id}|${v.kind}`)) continue;
      firstSeen.add(`${node.id}|${v.kind}`);
      first.push({ node, kind: v.kind, note: e.note || "" });
      continue;
    }
    const a = nodes.get(e.from);
    const b = nodes.get(e.to);
    if (!a || !b) continue;
    const parentId = (a.level ?? 0) <= (b.level ?? 0) ? a.id : b.id;       // 가운데에 가까운 쪽에서 본다
    const v = graphView(e, parentId);
    const node = nodes.get(v.other);
    if (!node || furtherSeen.has(`${parentId}|${node.id}|${v.kind}`)) continue;
    furtherSeen.add(`${parentId}|${node.id}|${v.kind}`);
    if (!further.has(parentId)) further.set(parentId, []);
    further.get(parentId).push({ node, kind: v.kind, note: e.note || "" });
  }
  const byName = (x, y) => x.node.term.localeCompare(y.node.term, "ko");
  first.sort((x, y) => GRAPH_ZONES.indexOf(x.kind) - GRAPH_ZONES.indexOf(y.kind) || byName(x, y));
  const groups = [...further].map(([id, items]) => ({ parent: nodes.get(id), items: items.sort(byName) }))
    .filter(x => x.parent).sort((x, y) => x.parent.term.localeCompare(y.parent.term, "ko"));
  return { center, first, further: groups, truncated: !!g?.truncated };
}

function graphGlyph(spec) {
  return `<span class="q-gm-glyph" aria-hidden="true">${spec.glyph}</span>`;
}

/** 지도의 노드 하나 — 누르면 그 용어 한 장으로 이동하는 단추. withKind = 종류 이름을 글로 한 번 더 적는다(두 번째 단계 목록). */
function graphNodeHtml(item, withKind = false) {
  const spec = GRAPH_KINDS[item.kind];
  const line = item.note || item.node.summary || "";       // 관계의 한 줄 근거(note)가 있으면 그것, 없으면 한 줄 풀이
  const label = `${spec.label}: ${item.node.term}${line ? ` — ${line}` : ""} (누르면 이 용어로 이동)`;
  return `<div class="q-gm-leaf"><button type="button" class="q-gm-node q-gm-node--${spec.zone}" data-graph-open="${escHtml(item.node.id)}" aria-label="${escHtml(label)}">
      ${graphGlyph(spec)}
      <span class="q-gm-node-body">
        ${withKind ? `<span class="q-gm-kind">${escHtml(spec.label)}</span>` : ""}
        <strong class="q-gm-term">${escHtml(item.node.term)}</strong>
        ${line ? `<span class="q-gm-line">${escHtml(line)}</span>` : ""}
      </span></button></div>`;
}

function graphZoneHtml(kind, items) {
  const spec = GRAPH_KINDS[kind];
  return `<div class="q-gm-zone q-gm-zone--${spec.zone}" role="group" aria-label="${escHtml(`${spec.label} ${items.length}개`)}">
      <h5 class="q-gm-zone-h">${graphGlyph(spec)}<span>${escHtml(spec.label)}</span></h5>
      <div class="q-gm-leaves">${items.map(i => graphNodeHtml(i)).join("")}</div>
    </div>`;
}

/** 관계가 하나도 없는 용어(대부분) — 「없다」 가 아니라 「아직 연결해 둔 말이 없다」 고 정직하게 말하고 갈 길을 준다. */
export function graphEmptyHtml(term) {
  const cat = term?.category;
  return `<div class="q-gm-empty">
      <strong>이 용어는 아직 연결된 말이 없어요</strong>
      <p>용어사전에 「헷갈리기 쉬운 말」 · 「함께 알면 좋은 말」 로 이어 둔 용어가 아직 없다는 뜻이에요. 풀이는 위 카드에서 볼 수 있어요.</p>
      ${cat?.code ? `<button type="button" class="q-term-link" data-graph-category="${escHtml(cat.code)}" data-name="${escHtml(cat.name || "")}">같은 분류${cat.name ? `(${escHtml(cat.name)})` : ""}의 다른 용어 둘러보기 →</button>` : ""}
    </div>`;
}

function graphErrorHtml(message) {
  return `<p class="q-term-note" role="status">관계 지도를 불러오지 못했어요 — ${escHtml(message || "잠시 뒤 다시 시도해 주세요")}
      <button type="button" class="q-term-link" data-graph-retry>다시 시도</button></p>`;
}

/** 지도 본문 — 가운데 용어 + 종류별 이웃. 이웃이 있으면 「이웃에서 이어진 말 더 보기」 단추(누를 때 깊이 2 를 요청). uid = 한 화면 안에서 겹치지 않는 번호. */
export function graphViewHtml(term, g, uid = 1) {
  const m = graphModel(g);
  if (!m.center || !m.first.length) return graphEmptyHtml(term);
  const name = escHtml(m.center.term);
  const count = new Set(m.first.map(i => i.node.id)).size;
  const zones = GRAPH_ZONES.map(k => ({ k, items: m.first.filter(i => i.kind === k) })).filter(z => z.items.length);
  const moreId = `q-gm-more-${uid}`;
  return `<p class="q-gm-lead">「${name}」 에 바로 이어진 말 ${count}개 — 누르면 그 용어로 이동해요.</p>
    <div class="q-gm-map" role="group" aria-label="${escHtml(`${m.center.term} 의 관계 지도`)}">
      <div class="q-gm-hub" aria-current="true"><span class="q-gm-hub-label">지금 보는 용어</span><strong>${name}</strong></div>
      ${zones.map(z => graphZoneHtml(z.k, z.items)).join("")}
    </div>
    ${m.truncated ? `<p class="q-gm-note">이어진 말이 많아 일부만 보여요.</p>` : ""}
    <div class="q-gm-more-wrap">
      <button type="button" class="q-term-link q-gm-more-btn" data-graph-more data-label="${GRAPH_MORE_LABEL}" aria-expanded="false" aria-controls="${moreId}">${GRAPH_MORE_LABEL}</button>
      <div class="q-gm-more" id="${moreId}" aria-live="polite" hidden></div>
    </div>`;
}

const GRAPH_MORE_LABEL = "이웃에서 이어진 말 더 보기";
const GRAPH_LESS_LABEL = "이웃에서 이어진 말 접기";

/** 「더 보기」 를 눌러 받은 깊이 2 응답 → 이웃에서 한 걸음 더 이어진 말의 목록. 이어진 말이 없으면 없다고 그대로 알린다
 *  (개수는 받은 노드를 센 값이다. 서버가 노드 상한에서 잘랐으면 「없다」 고 단정하지 않고 일부만 가져왔다고 알린다). */
export function graphMoreHtml(g) {
  const m = graphModel(g);
  if (!m.further.length) {
    return m.truncated
      ? `<p class="q-gm-note" role="status">이어진 말이 많아 이웃에서 이어진 말은 다 가져오지 못했어요.</p>`
      : `<p class="q-gm-note" role="status">이웃에서 더 이어진 말이 없어요. 위에 보이는 말이 지금 이어 둔 전부예요.</p>`;
  }
  const count = new Set(m.further.flatMap(x => x.items.map(i => i.node.id))).size;
  return `<h5 class="q-gm-zone-h">한 걸음 더 — 이웃에서 이어진 말 ${count}개</h5>
    ${m.further.map(x => `<div class="q-gm-via" role="group" aria-label="${escHtml(`${x.parent.term} 에서 이어진 말`)}">
      <p class="q-gm-via-h">「${escHtml(x.parent.term)}」 에서 이어진 말</p>
      <div class="q-gm-via-list">${x.items.map(i => graphNodeHtml(i, true)).join("")}</div>
    </div>`).join("")}
    ${m.truncated ? `<p class="q-gm-note">이어진 말이 많아 일부만 보여요.</p>` : ""}`;
}

function graphHostHtml(uid) {
  return `<section class="q-gm" data-graph-host aria-labelledby="q-gm-h-${uid}" aria-busy="true">
      <h4 class="q-gm-h" id="q-gm-h-${uid}">관계 지도</h4>
      <div class="q-gm-body"><p class="q-gm-loading">관계 지도를 불러오는 중…</p></div>
    </section>`;
}

/** 노드(이동) · 빈 상태의 분류 단추를 잇는다 — 처음 그린 자리와, 「더 보기」 로 나중에 채운 자리 둘 다. */
function wireGraphLinks(scope) {
  scope.querySelectorAll("[data-graph-open]").forEach(b => b.addEventListener("click", () => openTermPage(b.dataset.graphOpen, { focusTitle: true })));
  scope.querySelectorAll("[data-graph-category]").forEach(b => b.addEventListener("click", () => showCategory(b.dataset.graphCategory, b.dataset.name)));
}

function fetchGraph(term, depth) {
  return api(`/api/glossary/${encodeURIComponent(term.id)}/graph?depth=${depth}`, { redirectOnUnauthorized: false });
}

/** 「더 보기」 단추 — 눌렀을 때의 일. 칸(panel)은 처음엔 비어 있고, 첫 누름에 깊이 2 를 한 번 요청해 채운다.
 *  상태는 단추의 data-state 에 둔다: idle(아직 안 받음) → loading → done(받음 · 이제 열고 닫기만) / error(실패 — 다시 시도).
 *  · 받는 중에 또 눌러도 요청을 겹쳐 보내지 않는다.
 *  · 그사이 다른 용어로 옮겼거나 자리가 화면에서 사라졌으면 응답을 조용히 버린다(늦은 응답이 다른 용어 화면을 덮지 않게).
 *  · 실패는 「없다」 로 보이지 않는다 — 오류 문구 + 다시 시도. 응답이 비어 오면 그때만 「더 이어진 말이 없어요」 로 알린다.
 *  export 는 시험(tests/test_glossary_graph_view.py)이 가짜 칸으로 흐름을 돌려 보려는 것이다. */
export async function graphMoreToggle(btn, panel, term, uid) {
  const state = btn.dataset.state || "idle";
  if (state === "loading") return;
  const show = (open) => {
    panel.hidden = !open;
    btn.setAttribute("aria-expanded", String(open));
    btn.textContent = open ? GRAPH_LESS_LABEL : (btn.dataset.label || GRAPH_MORE_LABEL);
  };
  if (state === "done" || (state === "error" && !panel.hidden)) {      // 이미 받았거나, 오류 문구가 열려 있으면 열고 닫기만
    show(panel.hidden);
    return;
  }
  btn.dataset.state = "loading";
  panel.hidden = false;                                                  // 받는 동안은 단추 글자를 그대로 둔다(눌러도 겹쳐 보내지 않는다)
  btn.setAttribute("aria-expanded", "true");
  panel.setAttribute("aria-busy", "true");
  panel.innerHTML = `<p class="q-gm-loading">이웃에서 이어진 말을 불러오는 중…</p>`;
  const stale = () => uid !== graphSeq || !panel.isConnected;           // 그사이 다른 용어로 옮겼다
  let html;
  let next = "done";
  try {
    const g = await fetchGraph(term, GRAPH_DEPTH_MORE);
    if (stale()) return;
    if (g?.center === term.id) {
      html = graphMoreHtml(g);
    } else {                                                             // 이 용어의 지도가 아닌 응답은 그리지 않는다
      html = graphMoreErrorHtml("이 용어의 지도가 아닌 응답이 왔어요");
      next = "error";
    }
  } catch (e) {
    if (stale()) return;
    html = graphMoreErrorHtml(e?.message);
    next = "error";
  }
  btn.dataset.state = next;
  btn.textContent = GRAPH_LESS_LABEL;
  panel.removeAttribute("aria-busy");
  panel.innerHTML = html;
  wireGraphLinks(panel);
  panel.querySelectorAll("[data-graph-more-retry]").forEach(b => b.addEventListener("click", () => {
    btn.dataset.state = "idle";                                          // 다시 시도 — 깊이 2 만 다시 묻는다(처음 지도는 그대로)
    graphMoreToggle(btn, panel, term, uid);
  }));
}

function graphMoreErrorHtml(message) {
  return `<p class="q-term-note" role="status">이웃에서 이어진 말을 불러오지 못했어요 — ${escHtml(message || "잠시 뒤 다시 시도해 주세요")}
      <button type="button" class="q-term-link" data-graph-more-retry>다시 시도</button></p>`;
}

function wireGraph(host, term, uid) {
  wireGraphLinks(host);
  host.querySelectorAll("[data-graph-retry]").forEach(b => b.addEventListener("click", () => loadGraph(term, host, uid)));
  const more = host.querySelector("[data-graph-more]");
  const panel = more ? host.querySelector(`#${more.getAttribute("aria-controls")}`) : null;
  if (more && panel) more.addEventListener("click", () => graphMoreToggle(more, panel, term, uid));
}

/** 용어 한 장 아래 지도 자리를 채운다. 연관 개념이 하나도 없으면(같은 표를 읽는 graph 도 비어 있다) 묻지 않고 빈 상태를 보인다. */
async function loadGraph(term, host, uid) {
  const body = host.querySelector(".q-gm-body");
  const stale = () => uid !== graphSeq || !host.isConnected;       // 그사이 다른 용어로 옮겼다
  const finish = (html) => {
    body.innerHTML = html;
    host.removeAttribute("aria-busy");
    wireGraph(host, term, uid);
  };
  if (Array.isArray(term.related) && term.related.length === 0) {
    finish(graphEmptyHtml(term));
    return;
  }
  host.setAttribute("aria-busy", "true");
  body.innerHTML = `<p class="q-gm-loading">관계 지도를 불러오는 중…</p>`;
  let g;
  try {
    g = await fetchGraph(term, GRAPH_DEPTH_FIRST);
  } catch (e) {
    if (stale()) return;
    // 불러오지 못한 것을 「연결된 말이 없다」 로 보이면 거짓이다 — 실패는 실패로 알리고 다시 시도를 준다
    finish(graphErrorHtml(e?.message));
    return;
  }
  if (stale()) return;                                  // 다른 용어로 옮겼으면 조용히 버린다
  // 이 용어의 지도가 아닌 응답이 왔다면 그리지 않는다 — 그렇다고 「불러오는 중」 으로 남겨 두지도 않는다
  finish(g?.center === term.id ? graphViewHtml(term, g, uid) : graphErrorHtml("이 용어의 지도가 아닌 응답이 왔어요"));
}

/** 용어 한 장 — 풀이 카드를 넓게. key = 용어 ID · 이름 · 약어 어느 것이든. focusTitle = 지도의 노드로 옮겨 온 경우 제목에 초점을 둔다. */
async function openTermPage(key, { focusTitle = false } = {}) {
  const main = rootEl.querySelector("#q-gl-main");
  main.innerHTML = `<div class="q-gl-loading">불러오는 중…</div>`;
  let t;
  try { t = await api(`/api/glossary/${encodeURIComponent(key)}`, { redirectOnUnauthorized: false }); } catch (e) {
    main.innerHTML = `<div class="q-gl-empty"><p>${e.status === 404 ? `「${escHtml(key)}」 은(는) 아직 용어사전에 없는 말이에요.` : `불러오지 못했습니다 — ${escHtml(e.message)}`}</p>
      <button type="button" class="q-term-link" data-home>← 분류로 둘러보기</button></div>`;
    bindMain();
    return;
  }
  remember(t);
  const uid = ++graphSeq;                       // 이 용어 한 장의 번호 — 지도 응답이 늦게 와도 다른 용어 화면을 덮지 못한다
  main.innerHTML = `<div class="q-gl-crumb"><button type="button" class="q-term-link" data-home>← ${lastQuery ? `「${escHtml(lastQuery)}」 찾기로` : "분류로 둘러보기"}</button>
      <span class="q-gl-crumb-cat">${escHtml(t.category?.name || "")}</span></div>
    <article class="q-gl-page">${termCardHtml(t, { page: true })}${graphHostHtml(uid)}</article>`;
  // 찾기로 돌아가기는 검색어가 있으면 그 결과로
  main.querySelector(".q-gl-crumb [data-home]").addEventListener("click", e => {
    if (lastQuery) { e.stopImmediatePropagation(); search(lastQuery); }
  }, { capture: true });
  bindMain();
  wireCard(main.querySelector(".q-gl-page"), { onTerm: openTermPage });
  loadGraph(t, main.querySelector("[data-graph-host]"), uid);     // 기다리지 않는다 — 풀이 카드는 먼저 보인다
  if (focusTitle) {                             // 지도의 노드를 눌러 왔으면 화면 읽기 프로그램이 새 용어 이름부터 읽게
    const title = main.querySelector(".q-term-title");
    if (title) { title.setAttribute("tabindex", "-1"); title.focus({ preventScroll: true }); }
  }
  rootEl.scrollIntoView({ block: "start" });
}

export function renderGlossary(el) {
  rootEl = el;
  const pending = takePendingTerm();
  if (pending) {
    rootEl.innerHTML = shell("");
    bindShell();
    openTermPage(pending);
    return;
  }
  if (!rootEl.querySelector(".q-gl")) home();
}

// 서랍의 「용어사전에서 자세히」 가 이미 이 화면에 있을 때 바로 연다(js/termcard.js goToGlossary)
window.QGlossary = { openTerm: (id) => { if (rootEl) { if (!rootEl.querySelector(".q-gl")) { rootEl.innerHTML = shell(""); bindShell(); } openTermPage(id); } } };
