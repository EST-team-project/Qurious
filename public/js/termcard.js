/* 용어 풀이 카드 — 서비스 어디서 용어를 누르든 같은 카드가 열린다 (2026-10-02 · 화면 설계 결정 ②).
 *
 * 열리는 모양 — 내 계정 › 화면 설정에서 고른다(이 브라우저에 저장):
 *   drawer    오른쪽 서랍(기본) — 뒤 화면을 흐리게 하지 않아 보던 숫자를 보며 읽는다.
 *             좁은 화면(768px 이하)에서는 아래에서 올라오는 시트(화면 높이의 85%).
 *   modal-sm  가운데 작은 창
 *   modal-lg  가운데 큰 창
 * 풀이에 표 · 그림 · 긴 글이 있으면 크기를 키운다(서랍 → 넓은 서랍, 작은 창 → 큰 창).
 * 어느 모양이든 화면보다 커지지 않는다 — 너비 · 높이를 창 크기에 맞춰 줄이고 안에서 스크롤한다
 * (2026-10-02 피드백: 작은 창이 화면을 자르거나 가득 채워 안 보이던 문제를 이 카드에서는 되풀이하지 않는다).
 *
 * 내용 — 용어사전 API(GET /api/glossary/{이름}). 화면 키(sharpe) · 약어 · 다른 이름 어느 것으로도 찾는다.
 * 용어사전에 없거나 불러오지 못하면, 부른 쪽이 넘긴 짧은 설명(fallback · 예전 설명창의 글)을 보여 준다
 * — 칩을 눌렀는데 아무것도 안 뜨는 일이 없게(화면 경우 표 11 · 12).
 */
import { api, escHtml } from "/js/common.js";

const VIEW_KEY = "qurious.termView";
export const TERM_VIEWS = [
  { value: "drawer",   label: "오른쪽 서랍",    hint: "보던 화면 옆에서 읽어요 (추천)" },
  { value: "modal-sm", label: "가운데 작은 창", hint: "짧은 풀이를 화면 가운데에" },
  { value: "modal-lg", label: "가운데 큰 창",   hint: "긴 풀이 · 그림을 넓게" },
];

export function getTermView() {
  try {
    const v = localStorage.getItem(VIEW_KEY);
    if (TERM_VIEWS.some(x => x.value === v)) return v;
  } catch { /* 저장소를 못 쓰는 브라우저 — 기본값 */ }
  return "drawer";
}

export function setTermView(value) {
  try { localStorage.setItem(VIEW_KEY, value); } catch { /* 저장 못 해도 이번 화면에는 적용 */ }
}

const PRIMARY = "대표 이름";
const EASY_CLIP = 360;          // 「쉽게 풀면」 이 이보다 길면 첫 부분만 보이고 「더 보기」(경우 표 13)
const STACK_MAX = 5;            // 「← 이전 용어」 로 돌아갈 수 있는 수(경우 표 10)
const WIDE_TEXT = 1400;         // 카드 글이 이보다 길면 넓게

let root = null;
let current = null;             // { key, opts }
let stack = [];
let seq = 0;                    // 늦게 온 응답이 새 용어를 덮지 않게

// ── 카드 HTML ───────────────────────────────────────────────────────
function box(label, text, extra = "") {
  if (!text) return "";
  return `<div class="q-term-box ${extra}"><div class="q-term-box-label">${escHtml(label)}</div>
    <div class="q-term-box-text">${escHtml(text)}</div></div>`;
}

function easyBox(text) {
  if (!text) return "";
  if (text.length <= EASY_CLIP) return box("쉽게 풀면", text);
  return `<div class="q-term-box"><div class="q-term-box-label">쉽게 풀면</div>
    <div class="q-term-box-text q-term-clip">${escHtml(text.slice(0, EASY_CLIP))}…</div>
    <div class="q-term-box-text q-term-full" hidden>${escHtml(text)}</div>
    <button type="button" class="q-term-link q-term-toggle">더 보기</button></div>`;
}

// 연관 개념(결정 ④) — 칩(함께 · 더 넓은) + 헷갈리기 쉬운 말은 차이 한 줄. 관계 자료가 없으면 칸을 숨긴다(경우 표 15).
// 관계 자료(API 의 related[])는 아직 없다 — 생기면 이 함수가 그대로 그린다.
function relatedHtml(t) {
  const rel = Array.isArray(t.related) ? t.related : [];
  if (!rel.length) return "";
  const chips = (items) => items.map(r =>
    `<button type="button" class="q-term-chip q-term-chip--link" data-term="${escHtml(r.id || r.term)}">${escHtml(r.term)} →</button>`).join("");
  const near = rel.filter(r => r.kind === "related");
  const wide = rel.filter(r => r.kind === "broader" || r.kind === "narrower");
  const conf = rel.filter(r => r.kind === "confused_with");
  return `<section class="q-term-related"><h4>연관 개념</h4>
    ${near.length ? `<div class="q-term-rel-group"><span>함께 알면 좋은 개념</span><div>${chips(near)}</div></div>` : ""}
    ${wide.length ? `<div class="q-term-rel-group"><span>더 넓은 · 좁은 개념</span><div>${chips(wide)}</div></div>` : ""}
    ${conf.length ? `<div class="q-term-rel-group"><span class="q-term-warn">헷갈리기 쉬운 말</span>${conf.map(r =>
      `<div class="q-term-confused"><button type="button" class="q-term-link" data-term="${escHtml(r.id || r.term)}">${escHtml(r.term)} →</button>
       <p>${escHtml(r.note || "")}</p></div>`).join("")}</div>` : ""}
  </section>`;
}

/** 용어 한 건(API 응답) → 카드 HTML. 용어사전 화면(용어 한 장)도 이 함수를 쓴다.
 *  label = 부른 화면에 적힌 이름(예: 칩의 「샤프지수」) — 화면 키(sharpe)로 찾았을 때 키 대신 이 이름을 보여 준다. */
export function termCardHtml(t, { page = false, label = "" } = {}) {
  // 다른 이름 — 화면 키(내부 이름) · 영어 이름(위에 따로 보인다) · 대표 이름과 같은 것은 뺀다
  const others = (t.aliases || []).filter(a => a.kind !== "화면 키" && a.kind !== "영어" && a.alias !== t.term && a.alias !== t.english)
    .map(a => a.alias);
  const sub = [t.english, t.hanja, others.length ? `다른 이름 ${others.slice(0, 4).join(" · ")}` : ""]
    .filter(Boolean).join(" · ");
  const m = t.matched || {};
  const shown = m.kind === "화면 키" ? label : m.alias;     // 화면 키는 사람에게 보이는 이름이 아니다
  const matched = shown && m.kind !== PRIMARY && shown !== t.term
    ? `<p class="q-term-matched">「${escHtml(shown)}」 로 찾은 용어예요 — 대표 이름은 ${escHtml(t.term)}</p>` : "";
  const easy = t.definition || (Array.isArray(t.notes) && t.notes[0] ? t.notes[0].text : "");
  const sources = (t.sources || []).map(s => s.title).join(" · ");
  return `${matched}
    <div class="q-term-title-row"><h3 class="q-term-title">${escHtml(t.term)}</h3>
      ${t.category ? `<span class="q-term-chip">${escHtml(t.category.name)}</span>` : ""}</div>
    ${sub ? `<p class="q-term-sub">${escHtml(sub)}</p>` : ""}
    ${t.summary ? `<p class="q-term-summary">${escHtml(t.summary)}</p>` : ""}
    ${box("이 화면에서는", t.app_note)}
    ${easyBox(easy)}
    ${box("계산식", t.formula)}
    ${box("예시", t.example)}
    ${box("주의할 점", t.caution, "q-term-box--warn")}
    ${relatedHtml(t)}
    <div class="q-term-foot">
      ${page ? "" : `<button type="button" class="q-term-link q-term-more" data-term-page="${escHtml(t.id)}">용어사전에서 자세히 →</button>`}
      ${sources ? `<p class="q-term-src">출처 · ${escHtml(sources)}</p>` : ""}
    </div>`;
}

/** 카드 안의 단추(더 보기 · 연관 개념 · 용어사전에서 자세히)를 잇는다. 용어사전 화면도 쓴다. */
export function wireCard(el, { onTerm } = {}) {
  el.querySelectorAll(".q-term-toggle").forEach(b => b.addEventListener("click", () => {
    const boxEl = b.closest(".q-term-box");
    boxEl.querySelector(".q-term-clip").hidden = true;
    boxEl.querySelector(".q-term-full").hidden = false;
    b.remove();
  }));
  el.querySelectorAll("[data-term]").forEach(b => b.addEventListener("click", () => {
    if (onTerm) onTerm(b.dataset.term); else openTerm(b.dataset.term);
  }));
  el.querySelectorAll("[data-term-page]").forEach(b => b.addEventListener("click", () => goToGlossary(b.dataset.termPage)));
}

// 「용어사전에서 자세히」 — 용어사전 화면의 「용어 한 장」 으로
const PENDING_KEY = "qurious.glossary.open";
export function takePendingTerm() {
  try { const v = sessionStorage.getItem(PENDING_KEY); sessionStorage.removeItem(PENDING_KEY); return v; } catch { return null; }
}
function goToGlossary(id) {
  closeTerm();
  if (window.QGlossary && document.querySelector('.view.active[data-view="fin-glossary"]')) {
    window.QGlossary.openTerm(id);
    return;
  }
  try { sessionStorage.setItem(PENDING_KEY, id); } catch { /* 없으면 첫 화면으로 */ }
  location.hash = "fin-glossary";
}

// ── 서랍 · 창 ───────────────────────────────────────────────────────
function ensureRoot() {
  if (root) return root;
  root = document.createElement("div");
  root.id = "q-term-root";
  root.hidden = true;
  root.innerHTML = `<div class="q-term-dim"></div>
    <aside class="q-term-panel" role="dialog" aria-label="용어 풀이">
      <div class="q-term-head">
        <button type="button" class="q-term-link q-term-back" hidden>← 이전 용어</button>
        <span class="q-term-kicker">용어</span>
        <button type="button" class="q-term-close" aria-label="닫기">✕</button>
      </div>
      <div class="q-term-body"></div>
    </aside>`;
  document.body.appendChild(root);
  root.querySelector(".q-term-close").addEventListener("click", closeTerm);
  root.querySelector(".q-term-dim").addEventListener("click", closeTerm);
  root.querySelector(".q-term-back").addEventListener("click", () => {
    const prev = stack.pop();
    if (prev) show(prev.key, prev.opts, false);
  });
  document.addEventListener("keydown", e => { if (e.key === "Escape" && root && !root.hidden) closeTerm(); });
  return root;
}

function fallbackHtml(fb, failed) {
  const title = fb?.title || "";
  return `<div class="q-term-title-row"><h3 class="q-term-title">${escHtml(title)}</h3></div>
    ${fb?.body ? `<p class="q-term-summary q-term-summary--plain">${escHtml(fb.body)}</p>` : ""}
    <p class="q-term-note">${failed
      ? `용어사전을 불러오지 못해 이 화면의 짧은 설명을 보여 드려요. <button type="button" class="q-term-link q-term-retry">다시 시도</button>`
      : "아직 용어사전에 없는 말이에요."}</p>`;
}

function notFoundHtml(key, failed) {
  return `<div class="q-term-title-row"><h3 class="q-term-title">${escHtml(key)}</h3></div>
    <p class="q-term-note">${failed
      ? `용어사전을 불러오지 못했습니다. <button type="button" class="q-term-link q-term-retry">다시 시도</button>`
      : "아직 용어사전에 없는 말이에요."}</p>`;
}

// 풀이에 표 · 그림 · 다이어그램이 있거나 글이 길면 크게(결정 ②)
function needsRoom(body) {
  return !!body.querySelector("table, img, svg, pre, figure, .mermaid") || body.textContent.length > WIDE_TEXT;
}

async function show(key, opts = {}, push = true) {
  ensureRoot();
  if (push && current && current.key !== key) {
    stack.push(current);
    if (stack.length > STACK_MAX) stack.shift();
  }
  if (!push && !current) stack = [];
  current = { key, opts };
  const mode = opts.view || getTermView();
  const panel = root.querySelector(".q-term-panel");
  root.className = `q-term--${mode}`;
  root.hidden = false;
  panel.setAttribute("aria-modal", mode === "drawer" ? "false" : "true");
  root.querySelector(".q-term-back").hidden = stack.length === 0;
  const body = root.querySelector(".q-term-body");
  body.innerHTML = `<div class="q-term-loading" aria-label="불러오는 중"><span></span><span></span><span></span></div>`;

  const mine = ++seq;
  let term = null;
  let failed = false;
  try {
    term = await api(`/api/glossary/${encodeURIComponent(key)}`, { redirectOnUnauthorized: false });
  } catch (err) {
    failed = err?.status !== 404;
  }
  if (mine !== seq) return;               // 그사이 다른 용어를 눌렀다
  if (term) body.innerHTML = termCardHtml(term, { label: opts.label || opts.fallback?.title || "" });
  else if (opts.fallback) body.innerHTML = fallbackHtml(opts.fallback, failed);
  else body.innerHTML = notFoundHtml(key, failed);
  wireCard(body);
  body.querySelector(".q-term-retry")?.addEventListener("click", () => show(key, opts, false));
  const room = needsRoom(body);
  root.classList.toggle("q-term--wide", room && mode === "drawer");
  if (room && mode === "modal-sm") root.className = "q-term--modal-lg";
  body.scrollTop = 0;
  root.querySelector(".q-term-close").focus({ preventScroll: true });
}

/** 용어 풀이를 연다. key = 화면 키 · 대표 이름 · 약어 · 다른 이름. opts.fallback = { title, body } */
export function openTerm(key, opts = {}) {
  if (!key) return;
  return show(String(key), opts, true);
}

export function closeTerm() {
  if (!root) return;
  root.hidden = true;
  current = null;
  stack = [];
}

// 강사님 기초 코드의 설명창(core.js openTermModal)이 이 카드를 쓰게 — 전역으로 연다.
window.QTerm = { open: openTerm, close: closeTerm, getView: getTermView, setView: setTermView, views: TERM_VIEWS };
