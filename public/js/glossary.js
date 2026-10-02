/* 용어사전 화면 — 「금융 필수 지식」 › 용어사전 (2026-10-02 · 화면 설계 결정 ①: 두 안을 합친다)
 *
 *   찾기 첫 화면   큰 검색창 · 자주 찾는 용어 · 분류 카드 · 최근 본 용어 (처음 온 사람이 둘러보기 쉽게)
 *   찾기          글자를 치면 0.2초 뒤 GET /api/glossary?q= — 줄마다 「무엇으로 찾았나」(matched · 약어 · 영어 · 초성 · 풀이)
 *   분류          분류 카드를 누르면 그 분류의 용어를 가나다순으로(GET /api/glossary?category=)
 *   용어 한 장     풀이 카드를 넓게 + 이어진 개념(관계 자료가 생기면 관계 지도) — 다른 화면의 서랍과 같은 카드
 *
 * 카드 HTML 은 js/termcard.js 의 termCardHtml 하나 — 서랍 · 작은 창 · 큰 창 · 이 화면이 같은 모양이다.
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

async function showCategory(code, name) {
  const main = rootEl.querySelector("#q-gl-main");
  main.innerHTML = `<div class="q-gl-loading">불러오는 중…</div>`;
  let res;
  try { res = await api(`/api/glossary?limit=200&category=${encodeURIComponent(code)}`, { redirectOnUnauthorized: false }); } catch (e) {
    main.innerHTML = `<p class="q-term-note">불러오지 못했습니다 — ${escHtml(e.message)}</p>`;
    return;
  }
  main.innerHTML = `<div class="q-gl-crumb"><button type="button" class="q-term-link" data-home>← 분류로 둘러보기</button>
      <h3 class="q-gl-h">${escHtml(name)} <span class="q-gl-count">${res.total}</span></h3></div>
    <div class="q-gl-list">${res.items.map(rowHtml).join("")}</div>`;
  bindMain();
}

/** 용어 한 장 — 풀이 카드를 넓게. key = 용어 ID · 이름 · 약어 어느 것이든. */
async function openTermPage(key) {
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
  main.innerHTML = `<div class="q-gl-crumb"><button type="button" class="q-term-link" data-home>← ${lastQuery ? `「${escHtml(lastQuery)}」 찾기로` : "분류로 둘러보기"}</button>
      <span class="q-gl-crumb-cat">${escHtml(t.category?.name || "")}</span></div>
    <article class="q-gl-page">${termCardHtml(t, { page: true })}</article>`;
  // 찾기로 돌아가기는 검색어가 있으면 그 결과로
  main.querySelector(".q-gl-crumb [data-home]").addEventListener("click", e => {
    if (lastQuery) { e.stopImmediatePropagation(); search(lastQuery); }
  }, { capture: true });
  bindMain();
  wireCard(main.querySelector(".q-gl-page"), { onTerm: openTermPage });
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
