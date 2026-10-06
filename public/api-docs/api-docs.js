/* Qurious API 문서 — 화면 (2026-10-06 · 시스템관리 서랍 「API 문서」)
 *
 * 무엇을 그리나
 *   왼쪽 거름(메서드 · 인증 · 화면이 부르는 것만 · 라우터) → 가운데 목록(라우터별 묶음) → 줄을 누르면 오른쪽 자세히.
 *   자세히 = 우리 칸(API ID · 인증 · 닿는 곳 · 부르는 화면 · 파트 · 요구 · 오류 · 코드 위치) + Swagger UI(그 API 하나의
 *   인자 · 본문 · 응답 · 시험 호출). 우리 칸은 catalog.json(scripts/api_scan.py --catalog), Swagger 는 /openapi.json.
 *
 * 왜 Swagger 를 통째로 쓰지 않나
 *   /docs 는 228개를 태그 차례로 늘어놓기만 하고 「어느 화면이 부르나 · 로그인이 필요한가 · 어디에 닿나」 를 모른다.
 *   목록 · 거름 · 우리 칸은 이 화면이 맡고, 인자 · 응답 모양 · 시험 호출처럼 Swagger 가 잘하는 일만 Swagger 에 맡긴다.
 *
 * 시험 호출은 이 브라우저의 로그인 쿠키로 **실제로** 실행된다 → 기본은 읽기(GET)만 허용하고, 쓰기(주문 · 저장 · 삭제)는
 * 사용자가 「쓰기 API 시험 허용」 을 켤 때만 허용한다(Swagger supportedSubmitMethods).
 */
import { METHODS, ROUTER_LABELS, AUTH_GROUPS, authGroup, mergeOps, filterOps, groupByRouter, oneOpSpec,
  submitMethods, keyToHash, hashToKey, swaggerDeepLink, stats } from "./api-docs-core.js?v=20261006c";

// FastAPI 기본 /docs 와 같은 자원(fastapi.openapi.docs) — 앱의 다른 바깥 자원과 같은 CDN 이다.
const SWAGGER_JS = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js";
const SWAGGER_CSS = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css";
const AUTH_TAG = { none: "a-none", admin: "a-admin", apikey: "a-apikey" };

const S = {
  spec: null, catalog: null, catalogError: "", rows: [], byKey: new Map(), me: null,
  q: "", methods: new Set(), router: "", auth: "", screensOnly: false,
  openKey: "", allowWrite: false,
};
let detailSeq = 0;          // 늦게 끝난 Swagger 그리기가 다른 API 의 자세히를 덮지 않게(열 때마다 +1)
let swaggerReady = null;    // Swagger UI 자원은 자세히를 처음 열 때 한 번만 싣는다

const $ = sel => document.querySelector(sel);

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// 경로 인자({symbol})를 눈에 띄게
function pathHtml(p) {
  return esc(p).replace(/\{([^}]+)\}/g, "<i>{$1}</i>");
}

function authLabel(raw) {
  const hit = AUTH_GROUPS.find(([k]) => k === authGroup(raw));
  return hit ? hit[1] : raw;
}

async function getJson(url) {
  // no-cache — 카탈로그 · 명세가 바뀌면 바로 새것을(바뀌지 않았으면 304 라 비용이 거의 없다)
  const r = await fetch(url, { credentials: "same-origin", cache: "no-cache", headers: { Accept: "application/json" } });
  if (!r.ok) throw Object.assign(new Error(`${url} — HTTP ${r.status}`), { status: r.status });
  return r.json();
}

// ── 거름(왼쪽) ─────────────────────────────────────────────
function chip(attr, val, label, on, extra = "") {
  return `<button type="button" class="chip ${extra}" ${attr}="${esc(val)}" aria-pressed="${on}">${esc(label)}</button>`;
}

function renderSide() {
  const st = stats(S.rows);
  // 라우터 개수는 「라우터만 뺀」 거름으로 센다 — 다른 거름을 걸어도 라우터별로 몇 개 남는지 보이게
  const base = filterOps(S.rows, { q: S.q, methods: S.methods, auth: S.auth, screensOnly: S.screensOnly });
  const counts = new Map();
  base.forEach(r => counts.set(r.router, (counts.get(r.router) || 0) + 1));
  const routers = groupByRouter(S.rows).map(([name]) => name);
  $("#sidenav").innerHTML = `
    <div class="side-block"><div class="side-title">한눈에</div>
      <div class="stat-grid">
        <div class="stat" title="앱이 /openapi.json 으로 내놓는 API"><b>${st.inSpec}</b><span>명세</span></div>
        <div class="stat" title="소스를 읽어 찾은 API(카탈로그)"><b>${S.catalog ? S.catalog.count : "—"}</b><span>카탈로그</span></div>
        <div class="stat" title="메뉴 화면이 부르는 API"><b>${st.screens}</b><span>화면이 부름</span></div>
      </div></div>
    <div class="side-block"><div class="side-title">메서드</div><div class="chips">
      ${chip("data-m", "", "전체", S.methods.size === 0)}
      ${METHODS.map(m => chip("data-m", m.toUpperCase(), m.toUpperCase(), S.methods.has(m.toUpperCase()), "m-chip")).join("")}
    </div></div>
    <div class="side-block"><div class="side-title">인증</div><div class="chips">
      ${chip("data-auth", "", "전체", !S.auth)}
      ${AUTH_GROUPS.map(([k, label]) => chip("data-auth", k, label, S.auth === k)).join("")}
    </div></div>
    <div class="side-block"><label class="toggle"><input type="checkbox" id="screens-only"${S.screensOnly ? " checked" : ""}> 화면이 부르는 것만</label></div>
    <div class="side-block"><div class="side-title"><span>라우터</span><span>${routers.length}</span></div>
      <ul class="router-list">
        <li><button type="button" class="router-btn" data-router="" aria-pressed="${!S.router}"><span class="rname">전체</span><span class="n">${base.length}</span></button></li>
        ${routers.map(name => `<li><button type="button" class="router-btn" data-router="${esc(name)}" aria-pressed="${S.router === name}"${counts.get(name) ? "" : " disabled"}>
          <span class="rname">${esc(ROUTER_LABELS[name] || name)}</span><code>${esc(name)}</code><span class="n">${counts.get(name) || 0}</span></button></li>`).join("")}
      </ul></div>`;
}

// ── 목록(가운데) ────────────────────────────────────────────
function filtering() {
  return Boolean(S.q || S.methods.size || S.router || S.auth || S.screensOnly);
}

function opRow(r) {
  const tags = [];
  if (r.id) tags.push(`<span class="tag id">${esc(r.id)}</span>`);
  if (r.auth) tags.push(`<span class="tag ${AUTH_TAG[authGroup(r.auth)] || ""}">${esc(authLabel(r.auth))}</span>`);
  if (!r.inSpec) tags.push(`<span class="tag warn" title="명세(/openapi.json)에 없다">명세 밖</span>`);
  if (!r.cat) tags.push(`<span class="tag warn" title="카탈로그를 다시 만들어야 한다">카탈로그 없음</span>`);
  return `<li><button type="button" class="op" data-key="${esc(r.key)}" aria-current="${S.openKey === r.key}">
    <span class="m m-${r.method}">${r.method}</span><span class="path">${pathHtml(r.path)}</span>
    <span class="title">${esc(r.title)}</span><span class="tags">${tags.join("")}</span></button></li>`;
}

function renderList() {
  const rows = filterOps(S.rows, { q: S.q, methods: S.methods, router: S.router, auth: S.auth, screensOnly: S.screensOnly });
  const box = $("#list");
  const any = filtering();
  if (!rows.length) {
    box.innerHTML = `<div class="empty">조건에 맞는 API 가 없습니다.${any ? ` <button type="button" class="btn" data-reset>거름 풀기</button>` : ""}</div>`;
    return;
  }
  const head = `<div class="list-head"><span><b>${rows.length}</b>개${any ? ` · 전체 ${S.rows.length}개에서 거름` : " · 라우터 등록 차례"}</span>${any
    ? `<button type="button" class="btn reset" data-reset><i class="fa-solid fa-xmark"></i> 거름 풀기</button>` : ""}</div>`;
  box.innerHTML = head + groupByRouter(rows).map(([router, list]) => `
    <section class="group"><h2>${esc(ROUTER_LABELS[router] || router)} <code>${esc(router)}</code><span class="n">${list.length}</span></h2>
      <ul class="ops">${list.map(opRow).join("")}</ul></section>`).join("");
}

function refresh() {
  renderSide();
  renderList();
}

function resetFilters() {
  S.q = ""; S.methods.clear(); S.router = ""; S.auth = ""; S.screensOnly = false;
  $("#search-input").value = "";
  refresh();
}

function markCurrent() {
  document.querySelectorAll(".op").forEach(b => b.setAttribute("aria-current", String(b.dataset.key === S.openKey)));
}

// ── 자세히(오른쪽) ──────────────────────────────────────────
function meName() {
  const u = S.me || {};
  const admin = (u.roles || []).includes("admin") ? " · 관리자" : "";
  return `${u.name || u.email || "이름 없음"}${admin}`;
}

function tryNote(r) {
  const who = S.me ? `지금 로그인한 계정(${esc(meName())})으로` : "로그인하지 않은 상태로";
  if (r.method === "GET") return `「Try it out」 → 「Execute」 를 누르면 ${who} 실제로 부릅니다.`;
  return S.allowWrite
    ? `쓰기 API 입니다 — ${who} <b>실제로 실행</b>됩니다(주문 · 저장 · 삭제가 일어날 수 있음).`
    : `쓰기 API 는 시험 호출을 막아 두었습니다 — 「쓰기 API 시험 허용」 을 켜면 ${who} 실제로 실행됩니다.`;
}

function tagList(items) {
  return items.length ? items.map(x => `<span class="tag">${esc(x)}</span>`).join("") : "—";
}

function factsHtml(r) {
  const c = r.cat || {};
  const errs = (c.errors || []).filter(e => e !== "?");
  const reach = [...(c.reaches || []), ...(c.hosts || []).map(h => `외부 ${h}`)];
  const screens = (c.screens || []).map(v => `<a class="tag" href="/app.html#${encodeURIComponent(v)}">${esc(v)}</a>`).join("");
  return `<dl class="facts">
    <dt>API ID</dt><dd>${c.id ? `<code>${esc(c.id)}</code>` : "—"}</dd>
    <dt>라우터</dt><dd>${esc(ROUTER_LABELS[r.router] || r.router)} <code>${esc(r.router)}</code></dd>
    <dt>인증</dt><dd>${r.auth ? `<span class="tag ${AUTH_TAG[authGroup(r.auth)] || ""}">${esc(r.auth)}</span>` : "—"}</dd>
    <dt>닿는 곳</dt><dd>${tagList(reach)}</dd>
    <dt>부르는 화면</dt><dd>${screens || "—"}</dd>
    <dt>파트 · 요구</dt><dd>${esc(c.part || "—")} ${(c.req || []).map(x => `<span class="tag">${esc(x)}</span>`).join("")}</dd>
    <dt>오류 코드</dt><dd>${errs.length ? tagList(errs) : ((c.errors || []).includes("?") ? "코드에서 읽지 못함" : "—")}</dd>
    <dt>응답 칸</dt><dd>${(c.keys || []).length ? c.keys.map(k => `<code>${esc(k)}</code>`).join(" · ") : "—"}</dd>
    <dt>코드</dt><dd>${c.file ? `<code>${esc(c.file)}:${esc(c.line)}</code>` : "—"}</dd>
  </dl>`;
}

function openDetail(key, { push = true } = {}) {
  const r = S.byKey.get(key);
  if (!r) return;
  S.openKey = key;
  const my = ++detailSeq;
  if (push) history.replaceState(null, "", keyToHash(key));
  setNav(false);
  document.body.classList.add("detail-open");
  const d = $("#detail");
  d.hidden = false;
  $("#detail-scrim").hidden = false;
  const op = r.op || {};
  // 설명(docstring)의 첫 줄은 제목으로 썼으니 나머지만
  const rest = String(op.description || "").split(/\r?\n/).slice(r.cat && r.cat.summary ? 0 : 1).join("\n").trim();
  d.innerHTML = `
    <div class="detail-head">
      <button type="button" class="icon-btn back" data-close aria-label="목록으로"><i class="fa-solid fa-arrow-left"></i></button>
      <span class="m m-${r.method}">${r.method}</span><code class="path">${pathHtml(r.path)}</code>
      <button type="button" class="icon-btn" data-copy title="메서드 · 경로 복사" aria-label="메서드 · 경로 복사"><i class="fa-regular fa-copy"></i></button>
      <button type="button" class="icon-btn close" data-close aria-label="닫기"><i class="fa-solid fa-xmark"></i></button>
    </div>
    <div class="detail-body">
      <h2 class="detail-title" tabindex="-1">${esc(r.title || r.path)}</h2>
      ${rest ? `<p class="detail-desc">${esc(rest)}</p>` : ""}
      ${r.cat ? "" : `<p class="note">카탈로그에 없는 API 입니다 — 카탈로그를 만든 뒤에 생겼습니다. <code>python scripts/api_scan.py --catalog public/api-docs/catalog.json</code> 로 다시 만듭니다.</p>`}
      ${r.inSpec ? "" : `<p class="note">명세(/openapi.json)에 없는 API 입니다 — 코드에서 일부러 뺐거나(<code>include_in_schema=False</code>) 앱이 아직 새 코드를 읽지 않았습니다. 시험 호출 칸이 없습니다.</p>`}
      ${factsHtml(r)}
      ${r.inSpec ? `
      <div class="try-head"><h3>요청 · 응답 · 시험 호출</h3>
        <label class="toggle"><input type="checkbox" id="allow-write"${S.allowWrite ? " checked" : ""}> 쓰기 API 시험 허용</label>
        <a href="${esc(swaggerDeepLink(r.op))}" target="_blank" rel="noopener noreferrer">Swagger 원본에서 <i class="fa-solid fa-up-right-from-square"></i></a></div>
      <p class="note${r.method === "GET" ? " info" : ""}" id="try-note">${tryNote(r)}</p>
      <div class="swagger-host" id="swagger-host"><p class="muted">Swagger UI 불러오는 중…</p></div>` : ""}
    </div>`;
  markCurrent();
  d.scrollTop = 0;
  d.querySelector(".detail-title")?.focus({ preventScroll: true });
  if (r.inSpec) renderSwagger(r, my);
}

function closeDetail({ push = true } = {}) {
  detailSeq += 1;
  S.openKey = "";
  document.body.classList.remove("detail-open");
  const d = $("#detail");
  d.hidden = true;
  d.innerHTML = "";
  $("#detail-scrim").hidden = true;
  if (push) history.replaceState(null, "", location.pathname + location.search);
  markCurrent();
}

function loadSwagger() {
  if (swaggerReady) return swaggerReady;
  swaggerReady = new Promise((resolve, reject) => {
    const css = document.createElement("link");
    css.rel = "stylesheet";
    css.href = SWAGGER_CSS;
    document.head.insertBefore(css, document.getElementById("api-docs-css"));   // 우리 덧입힘(api-docs.css)이 뒤에 오게
    const js = document.createElement("script");
    js.src = SWAGGER_JS;
    js.async = true;
    js.onload = () => (window.SwaggerUIBundle ? resolve(window.SwaggerUIBundle) : reject(new Error("SwaggerUIBundle 이 없습니다")));
    js.onerror = () => { swaggerReady = null; js.remove(); reject(new Error("Swagger UI 를 받지 못했습니다(cdn.jsdelivr.net)")); };
    document.head.appendChild(js);
  });
  return swaggerReady;
}

async function renderSwagger(r, my) {
  const host = $("#swagger-host");
  if (!host) return;
  try {
    const SwaggerUIBundle = await loadSwagger();
    if (my !== detailSeq || !host.isConnected) return;
    host.innerHTML = "";
    const mount = document.createElement("div");
    host.appendChild(mount);
    SwaggerUIBundle({
      spec: oneOpSpec(S.spec, r.path, r.method),
      domNode: mount,
      deepLinking: false,
      docExpansion: "full",
      defaultModelsExpandDepth: -1,
      defaultModelExpandDepth: 2,
      displayRequestDuration: true,
      tryItOutEnabled: false,
      supportedSubmitMethods: submitMethods(S.allowWrite),
      // 같은 출처 쿠키(fin_session)로 부른다 — 로그인한 사람의 권한 그대로
      requestInterceptor: req => { req.credentials = "same-origin"; return req; },
    });
  } catch (e) {
    if (my !== detailSeq || !host.isConnected) return;
    host.innerHTML = `<div class="err">${esc(e.message)} — 인터넷 연결을 확인하거나 <a href="${esc(swaggerDeepLink(r.op))}" target="_blank" rel="noopener noreferrer">Swagger 원본</a>에서 여세요.
      <br><button type="button" class="btn" data-retry-swagger>다시 불러오기</button></div>`;
  }
}

async function copyKey(btn) {
  try {
    await navigator.clipboard.writeText(S.openKey);
    btn.innerHTML = `<i class="fa-solid fa-check"></i>`;
  } catch {
    btn.title = "복사하지 못했습니다 — 경로를 직접 골라 복사하세요";
  }
  setTimeout(() => { if (btn.isConnected) btn.innerHTML = `<i class="fa-regular fa-copy"></i>`; }, 1200);
}

// ── 좁은 화면의 거름 서랍 ───────────────────────────────────
function setNav(open) {
  $("#sidenav").classList.toggle("open", open);
  $("#nav-scrim").hidden = !open;
  $("#nav-toggle").setAttribute("aria-expanded", String(open));
}

function renderStatus() {
  const st = stats(S.rows);
  const login = S.me
    ? `<span class="dot ok"></span><span>로그인 ${esc(meName())} — 시험 호출이 이 계정으로 갑니다</span>`
    : `<span class="dot off"></span><span>로그인 안 됨 — 로그인이 필요한 API 의 시험 호출은 401</span>`;
  const parts = [`명세 ${st.inSpec}`, `카탈로그 ${S.catalog ? S.catalog.count : "없음"}`];
  if (st.catOnly) parts.push(`명세 밖 ${st.catOnly}`);
  if (st.specOnly) parts.push(`카탈로그에 없음 ${st.specOnly}`);
  $("#statusbar").innerHTML = `${login}<span class="sep">|</span><span>${parts.join(" · ")}</span>`
    + (S.catalogError ? `<span class="sep">|</span><span>카탈로그를 읽지 못함 — ${esc(S.catalogError)}</span>` : "");
}

function showLoadError(e) {
  $("#list").innerHTML = `<div class="err"><b>명세(/openapi.json)를 읽지 못했습니다.</b><br>${esc((e && e.message) || e)}
    <br><button type="button" class="btn" data-reload>다시 읽기</button></div>`;
  $("#sidenav").innerHTML = `<p class="muted pad">명세를 읽은 뒤에 거름이 생깁니다.</p>`;
  $("#statusbar").innerHTML = `<span class="dot error"></span><span>명세를 읽지 못함</span>`;
}

function bind() {
  const input = $("#search-input");
  let timer = 0;
  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => { S.q = input.value; refresh(); }, 120);
  });
  $("#search-form").addEventListener("submit", e => {
    e.preventDefault();
    S.q = input.value;
    refresh();
    document.querySelector(".op")?.focus();
  });
  $("#sidenav").addEventListener("click", e => {
    const m = e.target.closest("[data-m]");
    const a = e.target.closest("[data-auth]");
    const rt = e.target.closest("[data-router]");
    if (m) {
      const v = m.dataset.m;
      if (!v) S.methods.clear();
      else if (S.methods.has(v)) S.methods.delete(v);
      else S.methods.add(v);
    } else if (a) {
      S.auth = a.dataset.auth;
    } else if (rt) {
      S.router = rt.dataset.router;
      if (window.matchMedia("(max-width: 900px)").matches) setNav(false);
    } else {
      return;
    }
    refresh();
  });
  $("#sidenav").addEventListener("change", e => {
    if (e.target.id !== "screens-only") return;
    S.screensOnly = e.target.checked;
    refresh();
  });
  $("#list").addEventListener("click", e => {
    const b = e.target.closest(".op");
    if (b) { openDetail(b.dataset.key); return; }
    if (e.target.closest("[data-reset]")) { resetFilters(); return; }
    if (e.target.closest("[data-reload]")) location.reload();
  });
  $("#detail").addEventListener("click", e => {
    if (e.target.closest("[data-close]")) { closeDetail(); return; }
    const cp = e.target.closest("[data-copy]");
    if (cp) { copyKey(cp); return; }
    if (e.target.closest("[data-retry-swagger]")) {
      const r = S.byKey.get(S.openKey);
      if (r) renderSwagger(r, ++detailSeq);
    }
  });
  $("#detail").addEventListener("change", e => {
    if (e.target.id !== "allow-write") return;
    S.allowWrite = e.target.checked;
    const r = S.byKey.get(S.openKey);
    if (!r) return;
    const note = $("#try-note");
    if (note) note.innerHTML = tryNote(r);
    $("#swagger-host").innerHTML = `<p class="muted">Swagger UI 다시 그리는 중…</p>`;
    renderSwagger(r, ++detailSeq);
  });
  $("#detail-scrim").addEventListener("click", () => closeDetail());
  $("#nav-toggle").addEventListener("click", () => setNav(!$("#sidenav").classList.contains("open")));
  $("#nav-scrim").addEventListener("click", () => setNav(false));
  document.addEventListener("keydown", e => {
    const tag = (document.activeElement && document.activeElement.tagName) || "";
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(tag);
    if (e.key === "/" && !typing && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.preventDefault();
      input.focus();
      input.select();
    } else if (e.key === "Escape") {
      // Swagger 의 입력 칸에서 누른 Esc 는 그 칸의 일이다 — 자세히를 닫지 않는다
      if (typing && document.activeElement !== input && document.activeElement.closest("#swagger-host")) return;
      if (S.openKey) closeDetail();
      else if ($("#sidenav").classList.contains("open")) setNav(false);
    }
  });
  window.addEventListener("hashchange", () => {
    const k = hashToKey(location.hash);
    if (k && S.byKey.has(k)) { if (k !== S.openKey) openDetail(k, { push: false }); }
    else if (S.openKey) closeDetail({ push: false });
  });
}

async function boot() {
  bind();
  const [spec, catalog, me] = await Promise.allSettled([
    getJson("/openapi.json"), getJson("./catalog.json"), getJson("/api/me"),
  ]);
  if (spec.status !== "fulfilled") { showLoadError(spec.reason); return; }
  S.spec = spec.value;
  if (catalog.status === "fulfilled") S.catalog = catalog.value;
  else S.catalogError = (catalog.reason && catalog.reason.message) || "읽지 못함";
  S.me = me.status === "fulfilled" ? (me.value && me.value.user) || null : null;   // 로그인하지 않았으면 401 → 없음
  S.rows = mergeOps(S.spec, S.catalog);
  S.byKey = new Map(S.rows.map(r => [r.key, r]));
  refresh();
  renderStatus();
  const key = hashToKey(location.hash);
  if (key && S.byKey.has(key)) openDetail(key, { push: false });
}

boot();
