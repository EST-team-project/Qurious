/* Qurious 개념 학습 — 주소(#/…)를 보고 목차 · 장 · 팀 자료를 그린다(팀 자료는 읽기만 — D133).
 *
 * 설계: docs/phase-3/02-design/system/개념학습-설계.md (8절 화면 · 6절 글 규격)
 *
 * 주소
 *   #/                 목차(기술 개념 · 금융 지식)        #/s/finance   금융 필수 지식만
 *   #/p/<slug>         장 한 편 (?h=제목id 면 그 제목으로)  #/team        팀 자료
 *   (앱 안 새 글 · 고치기는 없앴다 — 2026-10-19 D133 · 옛 주소 #/new · #/edit/… 는 팀 자료로 보낸다)
 *   #/search?q=…       찾기
 *
 * 글 그리기 — 마크다운 → HTML(marked) → 거르기(DOMPurify) → 후처리(알림 상자 · 출력 상자 · Mermaid · 코드 색칠 · 제목 id)
 *   marked 의 렌더러 API 는 판마다 바뀌어 왔다. 그래서 렌더러를 고치지 않고 **거른 뒤의 DOM 을 고친다** — 판이 바뀌어도 덜 깨진다.
 *   거르기는 모든 글(기본 교재 포함)에 한다. 글이 어디서 왔든 브라우저에서 스크립트가 돌지 않게.
 */
(() => {
  "use strict";

  const API = "/api/learn";
  // 섹션 차례 = 이 표의 차례(서버 SECTIONS 와 같게 — 특강은 2026-10-20 · 장 머리말 section special · 차례 S.<일차><교시>)
  const SECTION_LABEL = { tech: "개념 학습", finance: "금융 필수 지식", special: "특강" };
  const SECTION_ICON = { tech: "fa-solid fa-graduation-cap", finance: "fa-solid fa-coins", special: "fa-solid fa-person-chalkboard" };
  const STATUS_LABEL = { ready: "완성", draft: "초안", skeleton: "뼈대" };
  const STATUS_ICON = { ready: "fa-solid fa-circle-check", draft: "fa-solid fa-pen", skeleton: "fa-regular fa-circle" };
  const CALLOUT = {
    GOAL: ["goal", "이 장에서 할 수 있게 되는 것", "fa-solid fa-bullseye"],   // 우리 교재의 머리 상자(학습 목표)
    NOTE: ["note", "참고", "fa-solid fa-circle-info"],
    TIP: ["tip", "도움말", "fa-solid fa-lightbulb"],
    IMPORTANT: ["important", "중요", "fa-solid fa-star"],
    WARNING: ["warning", "주의", "fa-solid fa-triangle-exclamation"],
    CAUTION: ["warning", "주의", "fa-solid fa-triangle-exclamation"],
  };
  const F = "```";
  // 「장 틀 넣기」 — 설계서 3절의 아홉 칸. 머리 상자(읽는 시간 · 수준 · 닿는 기능)는 머리말 칸이 그린다.
  const TEMPLATE = [
    // 목록 줄을 비워 두면 안 된다 — 글 한 줄 바로 아래의 「-」 한 줄은 마크다운에서 제목 밑줄(setext)로 읽혀
    // [!GOAL] 이 큰 제목이 된다(2026-10-01 미리보기에서 확인). 그래서 자리표시 문장을 넣어 둔다.
    "> [!GOAL]", "> - 이 장을 읽으면 ○○ 를 설명할 수 있습니다.", "> - ○○ 를 직접 해 볼 수 있습니다.",
    "> - ○○ 가 우리 프로젝트의 어디에 쓰이는지 말할 수 있습니다.", "",
    "## 왜 필요할까요?", "", "문제 상황 하나로 시작합니다. 될 수 있으면 직접 겪었거나 잰 사례로.", "",
    "## 한 문장으로 말하면", "", "정의 한 문장 + 비유 하나.", "",
    "## 어떻게 동작할까요?", "", "단계를 그림과 표로.", "",
    F + "mermaid", "flowchart LR", "    A[\"입력\"] --> B[\"처리\"] --> C[\"출력\"]", F, "",
    "## 직접 해 보기", "", "표준 라이브러리로 돌아가는 예제와, **직접 돌린** 출력.", "",
    F + "python", "print(\"직접 돌린 코드만 싣습니다\")", F, "",
    F + "output", "직접 돌린 코드만 싣습니다", F, "",
    "## 우리 프로젝트에서는", "", "닿는 파일 · 함수 · 설계서 절.", "",
    "## 흔한 실수", "", "- ", "",
    "## 정리", "", "1. ", "",
    "<details><summary>확인 문제 1. …?</summary>", "", "답.", "", "</details>", "",
    "## 더 읽을거리", "", "- 1차 출처(논문 · 공식 문서)의 제목과 주소", "",
  ].join("\n");

  const state = { pages: [], bySlug: new Map(), team: null, loadedAt: 0, spy: null };

  const $ = (sel, root = document) => root.querySelector(sel);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const local = {   // 브라우저 저장소 — 개인 창 · 막힌 저장소에서도 화면이 깨지지 않게 감싼다
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* 저장이 안 돼도 편집은 된다 */ } },
    del(k) { try { localStorage.removeItem(k); } catch { /* 무시 */ } },
  };

  async function api(path, opts = {}) {
    const res = await fetch(API + path, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
    let data = null;
    if (res.status !== 204) {
      try { data = await res.json(); } catch { data = null; }
    }
    if (!res.ok) {
      const d = data && data.detail;
      const msg = (d && d.message) || (typeof d === "string" ? d : `요청이 실패했습니다 (${res.status})`);
      const err = new Error(msg);
      err.status = res.status;
      err.detail = d;
      throw err;
    }
    return data;
  }

  function fmtTime(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso);
    const p = (n) => String(n).padStart(2, "0");
    return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
  }

  function groupBy(items, keyFn) {
    const map = new Map();
    for (const it of items) {
      const k = keyFn(it);
      if (!map.has(k)) map.set(k, []);
      map.get(k).push(it);
    }
    return map;
  }

  function toast(msg, bad = false) {
    const bar = $("#statusbar");
    const span = document.createElement("span");
    span.textContent = msg;
    span.style.color = bad ? "var(--bad)" : "var(--ok)";
    span.style.marginLeft = "auto";
    bar.appendChild(span);
    setTimeout(() => span.remove(), 5000);
  }

  // ── 목록 ──────────────────────────────────────────────────────────

  async function loadCatalog(force = false) {
    if (!force && state.pages.length && Date.now() - state.loadedAt < 30_000) return;
    const data = await api("/catalog");
    state.pages = data.pages;
    state.team = data.team;
    state.loadedAt = Date.now();
    state.bySlug = new Map();
    for (const p of data.pages) if (!state.bySlug.has(p.slug)) state.bySlug.set(p.slug, p);   // 기본 교재가 먼저
    if (data.builtin_errors && data.builtin_errors.length) console.warn("기본 교재 규격 오류", data.builtin_errors);
    renderNav();
    renderStatus();
  }

  function navItem(p, current) {
    const num = p.store === "team" ? "" : `${esc(p.order)} `;
    return `<a class="nav-item ${p.slug === current ? "active" : ""}" href="#/p/${esc(p.slug)}" title="${esc(p.summary)}">`
      + `<span class="st st-${esc(p.status)}"><i class="${STATUS_ICON[p.status] || ""}"></i></span>`
      + `<span>${num}${esc(p.title)}</span></a>`;
  }

  function renderNav() {
    const current = currentSlug();
    const team = state.pages.filter((p) => p.store === "team");
    let html = "";
    for (const sec of Object.keys(SECTION_LABEL)) {
      const parts = groupBy(state.pages.filter((p) => p.store === "builtin" && p.section === sec), (p) => p.part);
      if (!parts.size) continue;
      html += `<div class="nav-sec"><a class="nav-sec-title" href="#/s/${sec}"><i class="${SECTION_ICON[sec]}"></i>${SECTION_LABEL[sec]}</a>`;
      for (const [part, items] of parts) {
        html += `<div class="nav-part"><div class="nav-part-title">${esc(part)}</div>${items.map((p) => navItem(p, current)).join("")}</div>`;
      }
      html += "</div>";
    }
    html += `<div class="nav-sec"><a class="nav-sec-title" href="#/team"><i class="fa-solid fa-users"></i>팀 자료${team.length ? ` (${team.length})` : ""}</a>`;
    const t = state.team || {};
    if (t.state === "login_required") html += `<div class="nav-empty">로그인하면 보입니다 · <a href="/login.html">로그인</a></div>`;
    else if (!team.length) html += '<div class="nav-empty">아직 글이 없습니다</div>';
    else html += team.map((p) => navItem(p, current)).join("");
    html += "</div>";
    $("#nav-tree").innerHTML = html;
  }

  function renderStatus() {
    const t = state.team || {};
    // 저장소 이름 · HF 낱말 · 「새로 받기」 는 관리자에게만 — 서버가 일반 사용자 응답에서 저장소 이름 · 서버 글을 뺀다(2026-10-19 결정)
    const label = (t.admin ? {
      ok: "팀 자료 저장소 연결됨", off: "HF 토큰 없음 — 팀 자료 꺼짐", missing: "팀 자료 저장소 없음 · 권한 없음",
      error: "HF 에 닿지 못함 — 마지막으로 받은 글", never: "팀 자료 확인 전",
    } : {
      ok: "팀 자료", off: "팀 자료를 지금 볼 수 없습니다", missing: "팀 자료를 지금 볼 수 없습니다",
      error: "팀 자료 — 마지막으로 받은 글", never: "팀 자료 확인 전", login_required: "로그인하면 팀 자료가 보입니다",
    })[t.state] || (t.admin ? t.state || "" : "");
    const builtin = state.pages.filter((p) => p.store === "builtin");
    const ready = builtin.filter((p) => p.status === "ready").length;
    $("#statusbar").innerHTML = `<span class="dot ${esc(t.state)}"></span>`
      + `<span>${esc(label)}${t.admin && t.repo ? ` · ${esc(t.repo)}` : ""}${t.synced_at ? ` · 받은 때 ${esc(fmtTime(t.synced_at))}` : ""}</span>`
      + `<span class="muted">· 기본 교재 ${builtin.length}편(완성 ${ready})</span>`
      + (t.admin && t.state && t.state !== "off" ? '<button type="button" id="btn-sync">새로 받기</button>' : "");
    const btn = $("#btn-sync");
    if (btn) btn.addEventListener("click", syncNow);
  }

  async function syncNow() {
    try {
      const r = await api("/sync", { method: "POST" });
      await loadCatalog(true);
      toast(r.skipped ? "방금 받았습니다 — 10초 뒤에 다시 누르세요" : `받기 끝 — 새 글 ${r.added} · 바뀜 ${r.updated} · 지움 ${r.removed}`);
      route();
    } catch (e) {
      toast(e.message, true);
    }
  }

  // ── 주소 ──────────────────────────────────────────────────────────

  function parseHash() {
    const h = location.hash.replace(/^#/, "") || "/";
    const [path, query = ""] = h.split("?");
    return { parts: path.split("/").filter(Boolean).map(decodeURIComponent), params: new URLSearchParams(query) };
  }

  function currentSlug() {
    const { parts } = parseHash();
    return parts[0] === "p" || parts[0] === "edit" ? parts[1] : null;
  }

  async function route() {
    closeNav();
    const { parts, params } = parseHash();
    $("#toc").innerHTML = "";
    if (state.spy) { state.spy.disconnect(); state.spy = null; }
    try {
      await loadCatalog();
    } catch (e) {
      $("#view").innerHTML = `<div class="notice bad">목차를 불러오지 못했습니다: ${esc(e.message)}</div>`;
      return;
    }
    const [head, arg] = parts;
    if (!head) return renderHome(null);
    if (head === "s") return renderHome(arg);
    if (head === "p" && arg) return renderPage(arg, params);
    if (head === "team") return renderTeam();
    if (head === "new" || head === "edit") { location.replace("#/team"); return; }   // 옛 편집기 주소 — 쓰기는 없앴다(D133)
    if (head === "search") return renderSearch(params.get("q") || "");
    $("#view").innerHTML = '<div class="notice">없는 주소입니다. <a href="#/">목차로</a></div>';
  }

  // ── 목차 첫 화면 ──────────────────────────────────────────────────

  function renderHome(section) {
    const secs = section && SECTION_LABEL[section] ? [section] : Object.keys(SECTION_LABEL);
    const intro = section === "special"
      ? "외부 강사 특강의 개념을 날짜 · 교시 차례로 정리합니다. 강의 자료의 그림 · 수치는 공식 자료와 맞대어 다시 그렸고, 다르게 적은 곳은 장마다 표로 밝힙니다."
      : section === "finance"
      ? "투자 판단에 필요한 금융 지식을 장으로 정리합니다. 앱의 「금융 필수 지식」 화면(금융상품 이해 · 자산배분 모델 · 계절성 분석)을 보완합니다."
      : "Qurious 를 만들며 구현하는 개념을 교재처럼 설명합니다. 장마다 그림 · 직접 돌려 본 예제 · 우리 코드가 함께 있습니다. 「뼈대」 장은 그 기능을 구현하기 직전에 채웁니다.";
    let html = `<section class="hero"><p class="crumbs">Qurious · 개념 학습</p>`
      + `<h1>${section ? esc(SECTION_LABEL[section]) : "구현하기 전에 읽는 교재"}</h1><p>${esc(intro)}</p></section><div class="cards">`;
    for (const sec of secs) {
      const parts = groupBy(state.pages.filter((p) => p.store === "builtin" && p.section === sec), (p) => p.part);
      for (const [part, items] of parts) {
        const ready = items.filter((p) => p.status === "ready").length;
        html += `<article class="card"><h2>${esc(part)}</h2><div class="meta">${esc(SECTION_LABEL[sec])} · 장 ${items.length} · 완성 ${ready}</div>`
          + `<div class="progress" aria-hidden="true"><span style="width:${Math.round((100 * ready) / items.length)}%"></span></div><ul>`;
        for (const p of items) {
          html += `<li><span class="num">${esc(p.order)}</span><span><a href="#/p/${esc(p.slug)}">${esc(p.title)}</a> `
            + `<span class="badge ${esc(p.status)}">${STATUS_LABEL[p.status] || esc(p.status)}</span>`
            + `<span class="sum">${esc(p.summary)}</span></span></li>`;
        }
        html += "</ul></article>";
      }
    }
    html += "</div>";
    $("#view").innerHTML = html;
    document.title = section ? `${SECTION_LABEL[section]} — Qurious 개념 학습` : "Qurious 개념 학습";
    window.scrollTo(0, 0);
  }

  // ── 장 한 편 ──────────────────────────────────────────────────────

  async function renderPage(slug, params) {
    const view = $("#view");
    view.innerHTML = '<p class="muted">글을 불러오는 중…</p>';
    let data;
    try {
      data = await api(`/pages/${encodeURIComponent(slug)}`);
    } catch (e) {
      view.innerHTML = e.status === 401
        ? '<div class="notice warn">팀 자료는 로그인한 뒤 볼 수 있습니다. <a href="/login.html">로그인</a></div>'
        : `<div class="notice bad">${esc(e.message)}</div>`;
      return;
    }
    const m = data.meta;
    const prereq = (m.prereq || []).map((s) => {
      const p = state.bySlug.get(s);
      return `<a href="#/p/${esc(s)}">${esc(p ? p.title : s)}</a>`;
    }).join(" · ");
    const badges = [
      `<span class="badge ${esc(m.status)}"><i class="${STATUS_ICON[m.status] || ""}"></i>${STATUS_LABEL[m.status] || esc(m.status)}</span>`,
      data.store === "team" ? '<span class="badge team"><i class="fa-solid fa-users"></i>팀 자료</span>' : "",
      m.level ? `<span class="badge">${esc(m.level)}</span>` : "",
      m.minutes ? `<span class="badge"><i class="fa-regular fa-clock"></i>${esc(m.minutes)}분</span>` : "",
      m.feature ? `<span class="badge" title="닿는 요구 ID">${esc(m.feature)}</span>` : "",
      m.work ? `<span class="badge" title="구현 묶음">${esc(m.work)}</span>` : "",
      ...(m.tags || []).map((t) => `<span class="badge">#${esc(t)}</span>`),
    ].join("");
    const who = [
      m.owner ? `쓴 사람 ${esc(m.owner)}` : "",
      m.updated_by && m.updated_by !== m.owner ? `고친 사람 ${esc(m.updated_by)}` : "",
      m.updated ? `고친 날 ${esc(m.updated)}` : "",
    ].filter(Boolean).join(" · ");
    const actions = data.store === "team"
      ? '<div class="page-actions">'
        + '<button type="button" class="btn" id="btn-history"><i class="fa-solid fa-clock-rotate-left"></i>고친 기록</button>'
        + (data.history_url && state.team && state.team.admin ? `<a class="btn" href="${esc(data.history_url)}" target="_blank" rel="noopener noreferrer"><i class="fa-solid fa-arrow-up-right-from-square"></i>HF 에서 보기</a>` : "")
        + '</div><div id="history-box"></div>'
      : "";
    view.innerHTML = `<article class="page">
      <div class="crumbs"><a href="#/s/${esc(m.section)}">${esc(SECTION_LABEL[m.section] || m.section)}</a><span>›</span><span>${esc(m.part)}</span><span>›</span><span>${esc(m.order)}</span></div>
      <h1 class="page-title">${esc(m.title)}</h1>
      <p class="page-summary">${esc(m.summary)}</p>
      <div class="badges">${badges}</div>
      ${prereq || who ? `<p class="muted" style="font-size:13.5px;margin:-6px 0 14px">${prereq ? `먼저 읽을 장: ${prereq}` : ""}${prereq && who ? " · " : ""}${who}</p>` : ""}
      ${actions}
      <div class="prose" id="prose"></div>
      ${pagerHtml(m, data.store)}
    </article>`;
    const prose = $("#prose");
    await renderMarkdown(data.body, prose);
    buildToc(prose, slug);
    renderNav();
    document.title = `${m.title} — Qurious 개념 학습`;
    const btn = $("#btn-history");
    if (btn) btn.addEventListener("click", () => loadHistory(m.slug));
    const target = params.get("h") && document.getElementById(params.get("h"));
    if (target) target.scrollIntoView();
    else window.scrollTo(0, 0);
  }

  function pagerHtml(m, store) {
    if (store !== "builtin") return "";
    const list = state.pages.filter((p) => p.store === "builtin" && p.section === m.section);
    const i = list.findIndex((p) => p.slug === m.slug);
    const prev = i > 0 ? list[i - 1] : null;
    const next = i >= 0 && i < list.length - 1 ? list[i + 1] : null;
    if (!prev && !next) return "";
    return '<nav class="pager" aria-label="앞뒤 장">'
      + (prev ? `<a class="prev" href="#/p/${esc(prev.slug)}"><small>← 이전 장</small>${esc(prev.order)} ${esc(prev.title)}</a>` : "")
      + (next ? `<a class="next" href="#/p/${esc(next.slug)}"><small>다음 장 →</small>${esc(next.order)} ${esc(next.title)}</a>` : "")
      + "</nav>";
  }

  async function loadHistory(slug) {
    const box = $("#history-box");
    box.innerHTML = '<p class="muted">기록을 받는 중…</p>';
    try {
      const r = await api(`/pages/${encodeURIComponent(slug)}/history`);
      box.innerHTML = r.commits.length
        ? `<ul class="history">${r.commits.map((c) => `<li><code>${esc(String(c.id).slice(0, 8))}</code><span>${esc(c.title)}</span><span class="muted">${esc(fmtTime(c.date))}</span></li>`).join("")}</ul>`
        : '<p class="muted">기록이 없습니다.</p>';
    } catch (e) {
      box.innerHTML = `<div class="notice bad">${esc(e.message)}</div>`;
    }
  }

  // ── 글 그리기 ─────────────────────────────────────────────────────

  function slugify(s) {
    return String(s).trim().toLowerCase().replace(/[^\p{L}\p{N}\s-]/gu, "").replace(/\s+/g, "-").slice(0, 60) || "sec";
  }

  async function renderMarkdown(md, el) {
    if (!window.marked || !window.DOMPurify) {
      el.innerHTML = '<div class="notice warn">글 그리기 도구를 불러오지 못했습니다(인터넷 연결 확인) — 원문을 그대로 보여 줍니다.</div>';
      const pre = document.createElement("pre");
      pre.textContent = md || "";
      el.appendChild(pre);
      return;
    }
    const parse = window.marked.parse || window.marked.marked;
    const raw = parse(md || "", { gfm: true });
    el.innerHTML = window.DOMPurify.sanitize(raw, {
      USE_PROFILES: { html: true, svg: true, svgFilters: true },
      FORBID_TAGS: ["style", "form", "input", "button", "textarea", "select"],
    });
    enhance(el);
    await renderMermaid(el);
  }

  function enhance(el) {
    // 1) 알림 상자 — > [!NOTE] 첫 줄(GitHub 와 같은 표기) · [!GOAL] 은 우리 교재의 학습 목표 상자
    el.querySelectorAll("blockquote").forEach((bq) => {
      const first = bq.firstElementChild;
      if (!first || first.tagName !== "P") return;
      const hit = first.innerHTML.match(/^\s*\[!(GOAL|NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*(<br\s*\/?>)?\s*/i);
      if (!hit) return;
      const [cls, label, icon] = CALLOUT[hit[1].toUpperCase()];
      first.innerHTML = first.innerHTML.slice(hit[0].length);
      if (!first.textContent.trim() && !first.querySelector("img,svg")) first.remove();
      const box = document.createElement("div");
      box.className = `callout ${cls}`;
      box.innerHTML = `<div class="callout-title"><i class="${icon}"></i>${label}</div>`;
      while (bq.firstChild) box.appendChild(bq.firstChild);
      bq.replaceWith(box);
    });
    // 2) 코드 블록 — mermaid 는 그림 자리로, output 은 「출력」 상자로, 나머지는 색칠 + 머리 띠(언어 · 복사)
    el.querySelectorAll("pre > code").forEach((code) => {
      const pre = code.parentElement;
      const lang = ([...code.classList].find((c) => c.startsWith("language-")) || "").slice(9);
      if (lang === "mermaid") {
        const wrap = document.createElement("div");
        wrap.className = "mermaid-wrap";
        const box = document.createElement("div");
        box.className = "mermaid";
        box.textContent = code.textContent;
        wrap.appendChild(box);
        pre.replaceWith(wrap);
        return;
      }
      const isOut = lang === "output";
      const block = document.createElement("div");
      block.className = `code-block${isOut ? " output" : ""}`;
      const head = document.createElement("div");
      head.className = "code-head";
      const name = document.createElement("span");
      name.textContent = isOut ? "출력" : (lang || "코드");
      head.appendChild(name);
      if (!isOut) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.textContent = "복사";
        btn.addEventListener("click", async () => {
          try {
            await navigator.clipboard.writeText(code.textContent);
            btn.textContent = "복사됨";
          } catch {
            btn.textContent = "복사 안 됨";
          }
          setTimeout(() => { btn.textContent = "복사"; }, 1500);
        });
        head.appendChild(btn);
      }
      pre.replaceWith(block);
      block.appendChild(head);
      block.appendChild(pre);
      if (!isOut && lang && window.hljs && window.hljs.getLanguage(lang)) {
        try { window.hljs.highlightElement(code); } catch { /* 색칠이 안 돼도 글은 보인다 */ }
      }
    });
    // 3) 표 — 넓으면 가로로 밀어 보게 감싼다
    el.querySelectorAll("table").forEach((t) => {
      if (t.parentElement && t.parentElement.classList.contains("table-wrap")) return;
      const w = document.createElement("div");
      w.className = "table-wrap";
      t.replaceWith(w);
      w.appendChild(t);
    });
    // 4) 제목 id — 오른쪽 차례 · ?h= 주소가 쓴다
    const used = new Set();
    el.querySelectorAll("h2, h3").forEach((h) => {
      const base = slugify(h.textContent);
      let id = base;
      let n = 2;
      while (used.has(id) || document.getElementById(id)) id = `${base}-${n++}`;
      used.add(id);
      h.id = id;
    });
    // 5) 바깥 주소는 새 창으로
    el.querySelectorAll("a[href]").forEach((a) => {
      if (/^https?:\/\//i.test(a.getAttribute("href"))) {
        a.target = "_blank";
        a.rel = "noopener noreferrer";
      }
    });
  }

  let mermaidReady = false;
  async function renderMermaid(el) {
    const nodes = [...el.querySelectorAll(".mermaid")];
    if (!nodes.length) return;
    if (!window.mermaid) {
      nodes.forEach((n) => n.classList.add("mermaid-error"));
      return;
    }
    if (!mermaidReady) {
      window.mermaid.initialize({
        startOnLoad: false, securityLevel: "strict", theme: "neutral",
        fontFamily: "Pretendard Variable, Pretendard, sans-serif",
      });
      mermaidReady = true;
    }
    for (const n of nodes) {
      const src = n.textContent;
      try {
        const { svg } = await window.mermaid.render(`mm-${Math.random().toString(36).slice(2)}`, src);
        n.innerHTML = svg;
      } catch (e) {
        n.textContent = "";
        const pre = document.createElement("pre");
        pre.className = "mermaid-error";
        pre.textContent = `그림을 그리지 못했습니다: ${(e && e.message) || e}\n\n${src}`;
        n.appendChild(pre);
      }
    }
  }

  function buildToc(prose, slug) {
    const toc = $("#toc");
    const hs = [...prose.querySelectorAll("h2, h3")];
    if (hs.length < 2) { toc.innerHTML = ""; return; }
    toc.innerHTML = '<div class="toc-title">이 장의 차례</div>'
      + hs.map((h) => `<a href="#/p/${esc(slug)}?h=${esc(h.id)}" data-id="${esc(h.id)}" class="${h.tagName.toLowerCase()}">${esc(h.textContent)}</a>`).join("");
    toc.querySelectorAll("a").forEach((a) => a.addEventListener("click", (ev) => {
      ev.preventDefault();
      const t = document.getElementById(a.dataset.id);
      if (t) {
        t.scrollIntoView({ behavior: "smooth" });
        history.replaceState(null, "", a.getAttribute("href"));   // 주소만 바꾼다(hashchange 가 안 나 다시 그리지 않는다)
      }
    }));
    state.spy = new IntersectionObserver((entries) => {
      for (const en of entries) {
        if (en.isIntersecting) toc.querySelectorAll("a").forEach((a) => a.classList.toggle("active", a.dataset.id === en.target.id));
      }
    }, { rootMargin: "-70px 0px -70% 0px" });
    hs.forEach((h) => state.spy.observe(h));
  }

  // ── 팀 자료 · 찾기 ────────────────────────────────────────────────

  function teamNotice(t) {
    if (t.state === "login_required") return '<div class="notice warn">팀 자료는 로그인한 뒤 볼 수 있습니다. <a href="/login.html">로그인</a></div>';
    if (["off", "missing", "error"].includes(t.state)) return `<div class="notice ${t.state === "error" ? "warn" : "bad"}">${esc(t.message || (t.admin ? "팀 자료 저장소를 쓸 수 없습니다." : "팀 자료를 지금 볼 수 없습니다."))}</div>`;
    if (t.errors && t.errors.length) return `<div class="notice warn">규격이 깨져 목록에서 뺀 글 ${t.errors.length}편: ${t.errors.map((e) => esc(e.file)).join(", ")}</div>`;
    return "";
  }

  function listItems(items) {
    return `<ul>${items.map((p) => `<li><span class="num">${p.store === "team" ? "팀" : esc(p.order)}</span><span><a href="#/p/${esc(p.slug)}">${esc(p.title)}</a> `
      + `<span class="badge ${esc(p.status)}">${STATUS_LABEL[p.status] || esc(p.status)}</span>`
      + `<span class="sum">${esc(p.summary)}${p.store === "team" ? ` · ${esc(p.updated_by || p.owner || "")} ${esc(p.updated || "")}` : ""}</span></span></li>`).join("")}</ul>`;
  }

  function renderTeam() {
    const t = state.team || {};
    const team = state.pages.filter((p) => p.store === "team");
    let html = '<section class="hero"><p class="crumbs">Qurious · 개념 학습</p><h1>팀 자료</h1>'
      + (t.admin
        ? `<p>이동원이 HF 비공개 데이터셋 <code>${esc(t.repo || "")}</code> 에서 직접 쓰고 고치는 글입니다(앱 안 편집기는 없앴습니다 — 2026-10-19). 각자 PC 의 앱이 5분마다 새 글을 받아 옵니다.</p></section>`
        : "<p>팀이 정리한 학습 자료입니다. 새 글이 생기면 5분 안에 이 목록에 나타납니다.</p></section>");
    html += teamNotice(t);
    html += `<div class="cards"><article class="card"><h2>글 ${team.length}편</h2><div class="meta">${t.synced_at ? `마지막으로 받은 때 ${esc(fmtTime(t.synced_at))}` : ""}</div>`;
    if (team.length) html += listItems(team);
    html += "</article></div>";
    $("#view").innerHTML = html;
    document.title = "팀 자료 — Qurious 개념 학습";
    window.scrollTo(0, 0);
  }

  function renderSearch(q) {
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    const hits = state.pages.filter((p) => {
      const hay = [p.title, p.summary, p.part, p.slug, (p.tags || []).join(" ")].join(" ").toLowerCase();
      return words.every((w) => hay.includes(w));
    });
    $("#search-input").value = q;
    $("#view").innerHTML = `<section class="hero"><p class="crumbs">찾기</p><h1>「${esc(q)}」 — ${hits.length}편</h1></section>`
      + `<div class="cards"><article class="card">${hits.length ? listItems(hits) : '<p class="muted">맞는 장이 없습니다. 꼬리표나 짧은 낱말로 찾아 보세요.</p>'}</article></div>`;
    document.title = `찾기: ${q} — Qurious 개념 학습`;
  }

  // ── 좁은 화면 목차 서랍 · 찾기 ────────────────────────────────────

  function closeNav() {
    $("#sidenav").classList.remove("open");
    $("#nav-scrim").hidden = true;
    $("#nav-toggle").setAttribute("aria-expanded", "false");
  }
  $("#nav-toggle").addEventListener("click", () => {
    const open = !$("#sidenav").classList.contains("open");
    $("#sidenav").classList.toggle("open", open);
    $("#nav-scrim").hidden = !open;
    $("#nav-toggle").setAttribute("aria-expanded", String(open));
  });
  $("#nav-scrim").addEventListener("click", closeNav);
  $("#search-form").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const q = $("#search-input").value.trim();
    location.hash = q ? `#/search?q=${encodeURIComponent(q)}` : "#/";
  });

  window.addEventListener("hashchange", route);
  route();
})();
