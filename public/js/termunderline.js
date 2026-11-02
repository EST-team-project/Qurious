/* 교재 용어 밑줄 — 개념 학습 장 본문 속 용어사전 낱말에 점선 밑줄을 긋고, 누르면 용어 풀이 카드가 열린다
 * (2026-11-02 · 할 일 ①-23 B · 점검표 용어사전 「100% 까지」 — 교재 밑줄).
 *
 * 무엇을 하나 — 장 본문을 그린 뒤(js/conceptlearn.js 가 한 번 부른다) 본문 글을 서버에 보내 용어사전 낱말의 자리를 받고,
 * 그 자리를 <button class="q-term-ul"> 로 감싼다. 어떤 낱말이 용어인지는 서버 한 곳(POST /api/glossary/scan —
 * app/services/glossary_scan.py)이 정한다 — 이 파일은 글을 나눠 보내고, 받은 자리를 글 노드에 옮겨 감싸기만 한다.
 * 장 글(마크다운 → DOMPurify)은 건드리지 않는다 — 거른 뒤의 DOM 에 단추만 끼운다. 숫자 · 설명은 새로 쓰지 않는다(밑줄만).
 *
 * 규칙
 *   · 밑줄 제외 — 코드(pre · code · .cl-code) · 그림(.cl-mermaid · svg) · 링크(a) · 단추 · 제목(h1~h6) · 표 머리(th) · summary ·
 *     알림 상자 제목(.cl-callout-title) · 이미 감싼 낱말(.q-term-ul). 코드 글자를 서버에 보내지도 않는다.
 *   · 같은 용어는 한 절에서 첫 등장만 긋는다 — 절 = h2 (왼쪽 차례 · ?h= 주소가 쓰는 단위 · h1 도 새 절 · 첫 h2 앞은 0절).
 *     한 장에서 한 번만이 아닌 까닭: 긴 장은 뒤 절을 읽다 처음 보는 사람이 많다 · 한 절에서 여러 번이면 밑줄 폭탄이 된다.
 *   · 서버 글 상한(4,000자)·용어 수 상한(20)을 지킨다 — 절 단위로 CHUNK_MAX 자 안에서 나눠 보내고(절을 넘는 덩어리는 없다: 서버가
 *     덩어리마다 용어의 첫 자리 하나만 돌려주기 때문), 20개로 꽉 찬 응답은 마지막 자리 뒤부터 다시 묻는다.
 *   · 실패하면 조용히 밑줄만 안 긋는다(콘솔에 한 줄) — 장은 그대로. 늦게 온 응답은 isCurrent()(장 전환 번호)로 버린다.
 *   · 켜고 끄기 — 차례 칸의 「용어 밑줄 보기」(기본 켬 · localStorage · 안 돼도 동작). 끄면 단추를 글자로 되돌린다(Tab 순서에 안 남게).
 *
 * 서버 글 이어 붙이기 — 서버는 공백을 지운 채 견주고 낱말 경계(앞뒤 글자)를 본다. 그래서
 *   같은 블록 안 인라인 글 노드(strong · em 경계)는 구분 없이 잇고(「배당<strong>금</strong>」 이 「배당」 으로 읽히지 않게),
 *   블록 사이 · 제외한 요소 자리에는 공백이 아닌 글자가 든 BREAK 를 둔다(앞 문단 끝 「볼린저」 + 다음 문단 첫 「밴드」 가 한 용어로 잡히지 않게 ·
 *   BREAK 의 줄바꿈 · 가운뎃점은 서버의 조사 · 문장부호 허용 글자라 문단 끝의 두 글자 용어도 그대로 읽힌다).
 * 서버의 자리(at)는 파이썬 코드포인트 위치다 — 자바스크립트는 UTF-16 이라 이모지 앞에서 어긋난다 → cpToUtf16 으로 바꾸고, 글과 대조해
 *   어긋나거나 글 노드 둘에 걸친 자리는 버린다.
 *
 * 이 파일은 맨 위에서 import · window · document 를 건드리지 않는다(순수 함수는 node 시험이 바로 불러 돌린다 · tests/test_term_underline.py).
 */

export const SCAN_URL = "/api/glossary/scan";
/** 한 번에 보내는 글 길이(UTF-16 단위) — 서버 상한(glossary_scan.MAX_TEXT 4,000)보다 넉넉히 작게. 실제 장은 4,000자에 용어 11개가 넘지 않았다 */
export const CHUNK_MAX = 2000;
/** 한 번에 받는 용어 수 — 서버 상한(glossary_scan.MAX_LIMIT). 안 보내면 기본 6개만 온다 */
export const SCAN_LIMIT = 20;
/** 꽉 찬 응답 뒤를 이어 묻는 횟수 상한 */
export const MAX_ROUNDS = 4;
/** 동시에 보내는 요청 수 */
export const PARALLEL = 3;
export const UL_CLASS = "q-term-ul";
export const PREF_KEY = "qurious.termUnderline";
/** 블록 사이 · 제외한 요소 자리의 구분 — 공백이 아닌 글자(·)가 있어 서버가 공백을 지워도 앞뒤가 한 낱말로 붙지 않는다 */
export const BREAK = "\n·\n";

const SECTION_TAGS = new Set(["h1", "h2"]);
const SKIP_TAGS = new Set(["pre", "code", "a", "button", "h1", "h2", "h3", "h4", "h5", "h6", "th", "thead", "summary", "svg", "math",
  "kbd", "samp", "script", "style", "noscript", "textarea", "select", "option", "input", "iframe", "canvas", "video", "audio"]);
const SKIP_CLASSES = ["cl-code", "cl-code-head", "cl-mermaid", "cl-callout-title", UL_CLASS, "q-term-chips"];
const BLOCK_TAGS = new Set(["p", "li", "ul", "ol", "dl", "dt", "dd", "div", "blockquote", "table", "thead", "tbody", "tfoot", "tr", "td", "th",
  "pre", "details", "summary", "figure", "figcaption", "section", "article", "header", "footer", "hr", "br", "h1", "h2", "h3", "h4", "h5", "h6"]);

// ── 글 모으기 · 나누기 (순수 함수) ───────────────────────────────────

function classesOf(el) {
  if (typeof el.className === "string") return el.className;
  return (el.getAttribute && el.getAttribute("class")) || "";   // svg 의 className 은 문자열이 아니다
}

/** 이 요소 안의 글은 밑줄을 긋지 않는다 · 서버에도 보내지 않는다 */
export function isSkipped(el) {
  const tag = String(el.tagName || "").toLowerCase();
  if (SKIP_TAGS.has(tag)) return true;
  const have = classesOf(el).split(/\s+/);
  if (SKIP_CLASSES.some(c => have.includes(c))) return true;
  const off = el.getAttribute ? el.getAttribute("data-no-term-ul") : null;   // 부른 쪽이 직접 빼고 싶은 자리
  return off !== null && off !== undefined;
}

const squashedLength = s => s.replace(/\s+/g, "").length;

/** 긴 글 노드 하나를 max 안의 조각으로 — 되도록 공백에서 자르고, 서로게이트 쌍은 가르지 않는다 */
export function splitPieces(text, max = CHUNK_MAX) {
  const out = [];
  let i = 0;
  while (i < text.length) {
    let end = Math.min(text.length, i + max);
    if (end < text.length) {
      const sp = text.lastIndexOf(" ", end - 1);   // end - 1 까지만 찾아야 조각이 max 를 넘지 않는다
      if (sp > i + max / 2) end = sp + 1;
      else if (end - 1 > i && /[\uD800-\uDBFF]/.test(text[end - 1])) end -= 1;
    }
    out.push({ base: i, text: text.slice(i, end) });
    i = end;
  }
  return out;
}

/** 본문 → 절 목록. 각 절은 글 조각(seg: 노드 · 노드 안 시작 · 글 · 앞 구분) 목록. seen = 이미 감싼 낱말("절:용어ID") */
export function collectSections(root, max = CHUNK_MAX) {
  const sections = [{ segs: [] }];
  const seen = new Set();
  let brk = true;   // 다음 글 조각 앞에 BREAK 를 둘 자리인가
  const push = (node, base, text) => {
    sections[sections.length - 1].segs.push({ node, base, text, sep: brk ? BREAK : "" });
    brk = false;
  };
  const walk = parent => {
    for (const el of Array.from(parent.childNodes || [])) {
      if (el.nodeType === 3) {
        const raw = String(el.nodeValue || "");
        if (!/\S/.test(raw)) {   // 공백뿐인 글 노드 — 인라인 사이의 띄어쓰기는 이어 붙이는 데 필요하고, 블록 사이는 버린다
          if (!brk && sections[sections.length - 1].segs.length) push(el, 0, " ");
          continue;
        }
        for (const piece of splitPieces(raw, max)) {
          push(el, piece.base, piece.text);
          if (piece.base + piece.text.length < raw.length) brk = true;   // 조각 사이도 이어 붙이지 않는다
        }
        continue;
      }
      if (el.nodeType !== 1) continue;
      const tag = String(el.tagName || "").toLowerCase();
      if (SECTION_TAGS.has(tag)) sections.push({ segs: [] });   // 절 경계 — 제목 글자는 밑줄 대상이 아니다
      if (classesOf(el).split(/\s+/).includes(UL_CLASS)) seen.add(`${sections.length - 1}:${el.getAttribute("data-ul-term")}`);
      if (isSkipped(el)) { brk = true; continue; }
      const block = BLOCK_TAGS.has(tag);
      if (block) brk = true;
      walk(el);
      if (block) brk = true;
    }
  };
  walk(root);
  return { sections, seen };
}

/** 절 하나 → 덩어리(text ≤ max). 덩어리 안 조각은 start(덩어리 안 시작)를 얻는다. 절을 넘는 덩어리는 만들지 않는다 */
export function buildChunks(section, max = CHUNK_MAX) {
  const chunks = [];
  let cur = null;
  const flush = () => {
    if (cur && cur.segs.reduce((n, s) => n + squashedLength(s.text), 0) >= 2) chunks.push(cur);   // 구분(·)만으로 채워진 덩어리는 묻지 않는다
    cur = null;
  };
  for (const seg of section.segs) {
    if (cur && cur.text.length + seg.sep.length + seg.text.length > max) flush();
    if (!cur) cur = { text: "", segs: [] };
    if (cur.segs.length) cur.text += seg.sep;
    cur.segs.push({ ...seg, start: cur.text.length });
    cur.text += seg.text;
  }
  flush();
  return chunks;
}

// ── 서버가 준 자리 → 글 노드 자리 (순수 함수) ─────────────────────────

/** 파이썬 코드포인트 위치 → UTF-16 위치 (맞는 위치가 없으면 -1) */
export function cpToUtf16(text, cp) {
  if (!Number.isInteger(cp) || cp < 0) return -1;
  let units = 0;
  let n = 0;
  for (const ch of text) {
    if (n === cp) return units;
    n += 1;
    units += ch.length;
  }
  return n === cp ? units : -1;
}

/** 덩어리 글 하나를 서버에 물어 용어 자리를 돌려준다 — [{ id, term, matched, start, end }] (UTF-16 · 덩어리 글 기준).
 *  scan(글, 개수) 은 서버 응답의 items 를 돌려주는 함수. 20개로 꽉 찬 응답은 마지막 낱말 뒤부터 이어 묻는다. */
export async function scanText(text, scan, { limit = SCAN_LIMIT, rounds = MAX_ROUNDS } = {}) {
  const out = [];
  let from = 0;
  for (let round = 0; round < rounds; round += 1) {
    const part = text.slice(from);
    if (squashedLength(part) < 2) break;
    const items = await scan(part, limit);
    let last = from;
    for (const it of items) {
      const u = cpToUtf16(part, Number(it.at));
      const matched = String(it.matched || "");
      if (u < 0 || !matched || part.slice(u, u + matched.length) !== matched) continue;   // 글과 안 맞는 자리는 쓰지 않는다
      out.push({ id: String(it.id), term: String(it.term || ""), matched, start: from + u, end: from + u + matched.length });
      last = Math.max(last, from + u + matched.length);
    }
    if (items.length < limit || last <= from) break;
    from = last;
  }
  return out;
}

/** 자리가 글 조각 하나 안에 있으면 그 조각 (둘에 걸치면 null — 감쌀 수 없다) */
export function segmentOf(chunk, hit) {
  return chunk.segs.find(s => hit.start >= s.start && hit.end <= s.start + s.text.length) || null;
}

/** 덩어리별 결과 → 감쌀 자리. 문서 차례로 훑어 같은 절의 같은 용어는 첫 등장만 남긴다. plans = [{ section, chunk, hits }] (문서 차례) */
export function pickHits(plans, seen = new Set()) {
  const picks = [];
  for (const plan of plans) {
    for (const hit of [...plan.hits].sort((a, b) => a.start - b.start)) {
      const seg = segmentOf(plan.chunk, hit);
      if (!seg) continue;
      const key = `${plan.section}:${hit.id}`;
      if (seen.has(key)) continue;
      seen.add(key);
      picks.push({ node: seg.node, offset: seg.base + hit.start - seg.start, matched: hit.matched, id: hit.id, term: hit.term });
    }
  }
  return picks;
}

const collapse = s => String(s).replace(/\s+/g, " ").trim();

/** 단추 이름 — 화면에 보이는 글자를 포함한다(WCAG 2.5.3). 대표 이름이 다르면 괄호로 덧붙인다 */
export function labelOf(pick) {
  const shown = collapse(pick.matched);
  const same = collapse(pick.term).replace(/\s/g, "") === shown.replace(/\s/g, "");
  return `용어 설명 열기: ${shown}${!pick.term || same ? "" : ` (${collapse(pick.term)})`}`;
}

/** 자리마다 글 노드를 갈라 단추로 바꾼다 — 한 노드 안에서는 뒤에서부터 (앞 자리가 밀리지 않게). 감싼 수를 돌려준다 */
export function wrapHits(picks, makeButton) {
  const byNode = new Map();
  for (const p of picks) {
    if (!byNode.has(p.node)) byNode.set(p.node, []);
    byNode.get(p.node).push(p);
  }
  let count = 0;
  for (const [node, list] of byNode) {
    if (!node.parentNode) continue;   // 그사이 글이 다시 그려져 떨어진 노드
    list.sort((a, b) => b.offset - a.offset);
    for (const p of list) {
      if (String(node.nodeValue).slice(p.offset, p.offset + p.matched.length) !== p.matched) continue;   // 글이 바뀌었으면 건너뜀
      const mid = node.splitText(p.offset);
      mid.splitText(p.matched.length);
      mid.parentNode.replaceChild(makeButton(p), mid);
      count += 1;
    }
  }
  return count;
}

/** 감싼 단추를 글자로 되돌린다 (끌 때 — 단추가 Tab 순서에 남지 않게) */
export function unwrapAll(root) {
  Array.from(root.querySelectorAll(`.${UL_CLASS}`)).forEach(b => b.replaceWith(b.textContent));
  root.normalize();
}

async function runPool(tasks, size) {
  let next = 0;
  const worker = async () => {
    while (next < tasks.length) await tasks[next++]();
  };
  await Promise.all(Array.from({ length: Math.min(size, tasks.length) }, worker));
}

/** 본문(root)을 훑어 밑줄을 긋는다 → 감싼 수. scan · makeButton 은 부른 쪽이 준다(시험이 가짜를 끼운다).
 *  isCurrent() 가 거짓이 되면(장 전환 · 끄기) 보내던 것을 멈추고 아무것도 감싸지 않는다. */
export async function underlineTree(root, { scan, makeButton, isCurrent = () => true, onFail = () => {} }) {
  const { sections, seen } = collectSections(root);
  const plans = [];
  sections.forEach((sec, si) => buildChunks(sec).forEach(chunk => plans.push({ section: si, chunk, hits: [] })));
  await runPool(plans.map(plan => async () => {
    if (!isCurrent()) return;
    try { plan.hits = await scanText(plan.chunk.text, scan); } catch (err) {
      if (isCurrent()) onFail(err);   // 이 덩어리만 밑줄이 빠진다 — 나머지는 그대로 긋는다
    }
  }), PARALLEL);
  if (!isCurrent()) return 0;
  return wrapHits(pickHits(plans, seen), makeButton);
}

// ── 브라우저 연결 (화면에서만 쓴다) ──────────────────────────────────

const memo = new Map();   // 덩어리 글 → 서버 응답(items) — 장을 다시 열거나 끄고 켤 때 다시 묻지 않는다
const MEMO_MAX = 120;

function makeScan(signal) {
  return async (text, limit) => {
    if (memo.has(`${limit}\n${text}`)) return memo.get(`${limit}\n${text}`);
    const res = await fetch(SCAN_URL, {
      method: "POST", signal, credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, limit }),
    });
    if (!res.ok) throw new Error(`용어 찾기 실패 (${res.status})`);
    const data = await res.json();
    const items = Array.isArray(data && data.items) ? data.items : [];
    if (memo.size >= MEMO_MAX) memo.delete(memo.keys().next().value);
    memo.set(`${limit}\n${text}`, items);
    return items;
  };
}

/** 감싼 자리 하나 → 단추. doc 는 시험이 가짜 DOM 을 끼우는 자리(화면에서는 document) */
export function makeButton(pick, doc = document) {
  const b = doc.createElement("button");
  b.type = "button";
  b.className = UL_CLASS;
  b.setAttribute("data-ul-term", pick.id);
  b.setAttribute("aria-haspopup", "dialog");
  b.setAttribute("aria-label", labelOf(pick));
  b.textContent = pick.matched;
  return b;
}

/** 용어 카드 열기 — termcard.js 가 만든 전역 (core.js 의 설명창과 같은 길) */
function openCard(id) {
  if (window.QTerm && typeof window.QTerm.open === "function") window.QTerm.open(id);
  else if (typeof window.openTermModal === "function") window.openTermModal(id);
}

function readPref() {
  try { return localStorage.getItem(PREF_KEY) !== "off"; } catch { return true; }
}
function writePref(on) {
  try { localStorage.setItem(PREF_KEY, on ? "on" : "off"); } catch { /* 저장이 안 돼도 이번 화면에는 적용된다 */ }
}

const runs = new WeakMap();    // 본문 → { ctl } — 진행 중인 요청
const wired = new WeakSet();   // 클릭을 이은 본문

function stopRun(root) {
  const run = runs.get(root);
  if (run) run.ctl.abort();
  runs.delete(root);
}

function startRun(root, isCurrent) {
  stopRun(root);
  const ctl = new AbortController();
  runs.set(root, { ctl });
  const alive = () => !ctl.signal.aborted && root.isConnected !== false && isCurrent();
  let warned = false;
  return underlineTree(root, {
    scan: makeScan(ctl.signal), makeButton, isCurrent: alive,
    onFail: err => {
      if (warned || (err && err.name === "AbortError")) return;
      warned = true;   // 한 줄만 — 밑줄이 없을 뿐 장은 그대로다
      console.warn("교재 용어 밑줄을 긋지 못한 덩어리가 있습니다:", err && err.message);
    },
  }).catch(() => 0);
}

function toggleEl(root, isCurrent, on) {
  const label = document.createElement("label");
  label.className = "q-term-ul-toggle";
  const box = document.createElement("input");
  box.type = "checkbox";
  box.checked = on;
  const text = document.createElement("span");
  text.textContent = "용어 밑줄 보기";
  label.append(box, text);
  box.addEventListener("change", () => {
    writePref(box.checked);
    if (box.checked) { startRun(root, isCurrent); return; }
    stopRun(root);
    unwrapAll(root);
  });
  return label;
}

/** 장 본문(root)에 용어 밑줄을 붙인다 — host(차례 칸)에 켜고 끄는 칸을 끼우고, 켜져 있으면 바로 긋기 시작한다(기다리지 않는다).
 *  isCurrent() = 지금도 이 장인가(장 전환 번호). 실패해도 장 화면은 그대로다. */
export function mountTermUnderline(root, host, isCurrent = () => true) {
  if (!root) return;
  try {
    if (!wired.has(root)) {
      wired.add(root);
      root.addEventListener("click", e => {
        const b = e.target && e.target.closest ? e.target.closest(`.${UL_CLASS}`) : null;
        if (b && root.contains(b)) openCard(b.getAttribute("data-ul-term"));
      });
    }
    const on = readPref();
    if (host) {
      const old = host.querySelector(".q-term-ul-toggle");
      if (old) old.remove();
      host.insertBefore(toggleEl(root, isCurrent, on), host.querySelector(".fl-toc-list"));
    }
    if (on) startRun(root, isCurrent);
  } catch (err) {
    console.warn("교재 용어 밑줄을 시작하지 못했습니다:", err && err.message);
  }
}
