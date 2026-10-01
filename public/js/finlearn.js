/* 금융 강의 — 「금융 필수 지식」 › 강의실 · 주제 화면
 *
 * 화면 설계(2026-10-01 결정): 강의실 한 곳에서 과정을 고르고, 주제마다 화면 하나에서 끝까지 읽는다
 * (자리 세 안 중 B 강의실 + C 주제 화면을 합친 안).
 *
 *   fin-lectures      강의실 — 4일 과정 카드 · 교재 단원 카드 · 실습 모음 · 읽은 정도
 *   fin-topic-*       주제 화면 — 머리(제목 · 출처 · 이 강의에서 답하는 질문) + 본문
 *                     본문: 4일 과정은 강의 페이지를 iframe 으로(/lectures/days/0N.html — 계산기 · 그림 · 용어 창이 그대로 돈다)
 *                           교재 단원은 마크다운을 그린다(/lectures/curriculum/unitNN.md — 목차 | 본문)
 *
 * 강의 파일 · 목록(catalog.json)은 scripts/lectures_build.py 가 만든다. 화면은 그 파일만 읽는다.
 * 「요약」 화면(금융상품 이해 · 자산배분 모델 · 계절성 분석) 아래에는 관련 주제로 가는 입구를 붙인다.
 */
import { escHtml, setToast } from "/js/common.js";
import { navigate } from "/js/core.js";

const BASE = "/lectures/";

// 주제 = 화면 하나. day 가 있으면 강의 페이지를, units 가 있으면 교재 단원(들)을 싣는다.
export const TOPICS = [
  { key: "fin-topic-futures",    label: "선물과 옵션",          icon: "fa-solid fa-scale-unbalanced", day: "01" },
  { key: "fin-topic-funds",      label: "펀드와 ETF",           icon: "fa-solid fa-basket-shopping",  day: "02" },
  { key: "fin-topic-bonds",      label: "채권 · 금리 · 코인",   icon: "fa-solid fa-landmark",         day: "03" },
  { key: "fin-topic-allocation", label: "자산배분과 퀀트",      icon: "fa-solid fa-chart-pie",        day: "04" },
  { key: "fin-topic-company",    label: "회사 구조 · 세무회계", icon: "fa-solid fa-building",         units: [1, 10] },
  { key: "fin-topic-stocks",     label: "주식시장 기초",        icon: "fa-solid fa-chart-simple",     units: [2] },
  { key: "fin-topic-technical",  label: "기술적 분석 기초",     icon: "fa-solid fa-chart-line",       units: [3] },
  { key: "fin-topic-industry",   label: "산업 · 기업 · 재무",   icon: "fa-solid fa-industry",         units: [4] },
  { key: "fin-topic-macro",      label: "거시경제와 시장",      icon: "fa-solid fa-globe",            units: [5] },
];
const TOPIC_BY_KEY = Object.fromEntries(TOPICS.map(t => [t.key, t]));
const TOPIC_BY_DAY = Object.fromEntries(TOPICS.filter(t => t.day).map(t => [t.day, t]));

// 10단원의 실습 목록(교재 원본의 화면 이름) → 이 서비스의 화면
const LAB_TO_VIEW = [
  { label: "전략 분석 (백테스트)", view: "quant-backtest" },
  { label: "LEAN 백테스트", view: "quant-lean" },
  { label: "성과 검증", view: "indicator-backtest" },
  { label: "모델 비교 · 교차 검증", view: "ml-compare" },
  { label: "AI 투자 상담 (근거 질의응답)", view: "agent-chat" },
];

// 강의 본문 속 「다른 화면으로」 링크(/?view=…) → 이 서비스의 화면. null 은 아직 없는 화면
const LECTURE_VIEW_TO_APP = {
  index: "fin-lectures", home: "fin-lectures", stocks: "trading-chart", learn: "agent-chat",
  simulation: "robo-portfolio", backtest: "quant-lean", basis: null, calendar: null,
};

// 「요약」 화면 아래에 붙일 강의 입구
const SUMMARY_ENTRIES = {
  "fin-products": ["fin-topic-stocks", "fin-topic-funds", "fin-topic-bonds", "fin-topic-futures"],
  "fin-allocation": ["fin-topic-allocation"],
  "quant-seasonal": ["fin-topic-macro"],
};

let catalogPromise = null;
function loadCatalog() {
  if (!catalogPromise) {
    catalogPromise = fetch(BASE + "catalog.json", { cache: "no-cache" }).then(r => {
      if (!r.ok) throw new Error("강의 목록을 불러오지 못했습니다");
      return r.json();
    }).catch(e => { catalogPromise = null; throw e; });
  }
  return catalogPromise;
}

const dayOf = (cat, d) => cat.days.find(x => x.day === d);
const unitOf = (cat, id) => cat.units.find(u => u.id === id);

// 강의 페이지가 절마다 남기는 「이해도」(브라우저 저장소 · 같은 주소라 여기서 읽힌다)
function understood(day) {
  try {
    const saved = JSON.parse(localStorage.getItem(`finance-rag:day-${day}-understanding:v1`) || "{}");
    return Object.values(saved || {}).filter(v => Number(v) > 0).length;
  } catch { return 0; }
}

// ── 강의실 ───────────────────────────────────────────────────────
function courseCard(cat, t) {
  const d = dayOf(cat, t.day);
  const unit = cat.units.find(u => u.day === Number(t.day));
  const done = understood(t.day);
  const pct = d.sections ? Math.min(100, Math.round(done * 100 / d.sections)) : 0;
  return `
    <div class="fl-card fl-course" data-go="${t.key}" role="button" tabindex="0">
      <div class="fl-top"><span class="fl-no">${t.day}</span><h3>${escHtml(t.label)}</h3>
        <span class="fl-chip">절 ${d.sections} · 용어 ${d.terms}</span></div>
      <p>${escHtml(d.blurb || d.subtitle)}</p>
      <ul>${d.questions.slice(0, 2).map(q => `<li>${escHtml(q)}</li>`).join("")}</ul>
      <div class="fl-bar"><i style="width:${pct}%"></i></div>
      <div class="fl-foot"><span class="fl-muted">이해도 표시 ${done} / ${d.sections}${unit ? ` · 교재 ${unit.id}단원과 같은 내용` : ""}</span>
        <span class="fl-link">${done ? "이어 읽기 →" : "학습 시작 →"}</span></div>
    </div>`;
}

function unitCard(cat, t) {
  const u = unitOf(cat, t.units[0]);
  return `
    <div class="fl-card fl-course" data-go="${t.key}" role="button" tabindex="0">
      <div class="fl-top"><span class="fl-no">${u.id}</span><h3>${escHtml(t.label)}</h3>
        <span class="fl-chip">절 ${u.sections}</span></div>
      <p>${escHtml(u.goal)}</p>
      <ul>${u.questions.slice(0, 2).map(q => `<li>${escHtml(q)}</li>`).join("")}</ul>
      <div class="fl-foot"><span class="fl-muted">교재 ${t.units.join(" · ")}단원</span><span class="fl-link">읽기 →</span></div>
    </div>`;
}

async function renderHub(el) {
  el.innerHTML = `<div class="fl-card fl-muted">강의 목록을 불러오는 중…</div>`;
  let cat;
  try { cat = await loadCatalog(); } catch (e) {
    el.innerHTML = `<div class="fl-card">강의 목록을 불러오지 못했습니다. 잠시 뒤 다시 열어 주세요.</div>`;
    return;
  }
  const days = TOPICS.filter(t => t.day);
  const units = TOPICS.filter(t => t.units);
  el.innerHTML = `
    <div class="fl-hub-head"><h2>강의실</h2>
      <span class="fl-muted">하루 한 주제씩, 상품의 구조와 위험을 읽고 내 기준으로 비교합니다.</span></div>
    <div class="fl-section-title">4일 과정 <small>금융상품 이해 · 자산배분 설계</small></div>
    <div class="fl-grid">${days.map(t => courseCard(cat, t)).join("")}</div>
    <div class="fl-section-title" style="margin-top:22px">교재 <small>투자 분석의 기초 — 회사 · 시장 · 차트 · 재무 · 거시</small></div>
    <div class="fl-grid three">${units.map(t => unitCard(cat, t)).join("")}
      <div class="fl-card fl-course" style="cursor:default">
        <div class="fl-top"><span class="fl-no">10</span><h3>퀀트 · AI 실습 모음</h3></div>
        <p>배운 개념을 이 서비스의 분석 화면에서 직접 돌려 봅니다.</p>
        <div style="display:flex;flex-direction:column;gap:6px">
          ${LAB_TO_VIEW.map(l => `<button class="fl-link" style="text-align:left" data-view="${l.view}">${escHtml(l.label)} →</button>`).join("")}
        </div>
      </div>
    </div>
    <p class="fl-muted" style="font-size:13px;margin-top:14px">교재 6~9단원은 4일 과정과 같은 내용이라 4일 과정에서 읽습니다. 10단원의 본문은 「회사 구조 · 세무회계」 뒤에 이어 붙였습니다.</p>`;
  el.querySelectorAll("[data-go]").forEach(c => {
    const go = () => navigate(c.dataset.go);
    c.addEventListener("click", go);
    c.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
  });
  el.querySelectorAll("button[data-view]").forEach(b => b.addEventListener("click", e => { e.stopPropagation(); navigate(b.dataset.view); }));
}

// ── 주제 화면 ────────────────────────────────────────────────────
function topicHead(cat, t) {
  let chips = [], subtitle = "", asks = [];
  if (t.day) {
    const d = dayOf(cat, t.day);
    const unit = cat.units.find(u => u.day === Number(t.day));
    chips = [`금융 이론 강의 ${Number(t.day)}일차`, unit ? `교재 ${unit.id}단원` : null, `절 ${d.sections}`, `용어 ${d.terms}`];
    subtitle = d.subtitle; asks = d.questions;
  } else {
    const us = t.units.map(id => unitOf(cat, id));
    chips = [`교재 ${t.units.join(" · ")}단원`, `절 ${us.reduce((s, u) => s + u.sections, 0)}`];
    subtitle = us[0].goal; asks = us[0].questions;
  }
  return `
    <div class="fl-card fl-topic-head">
      <div class="fl-title-row"><h2>${escHtml(t.label)}</h2>${chips.filter(Boolean).map((c, i) => `<span class="fl-chip${i === 0 ? " is-accent" : ""}">${escHtml(c)}</span>`).join("")}
        <button class="fl-link" style="margin-left:auto" data-view="fin-lectures">← 강의실</button></div>
      <p>${escHtml(subtitle)}</p>
      <div class="fl-asks">${asks.slice(0, 4).map((q, i) => `<div class="fl-ask"><span>이 강의에서 답하는 질문 ${i + 1}</span>${escHtml(q)}</div>`).join("")}</div>
    </div>`;
}

function topicNav(t) {
  const i = TOPICS.indexOf(t);
  const prev = TOPICS[i - 1], next = TOPICS[i + 1];
  return `<div class="fl-nav">
    <span>${prev ? `<button class="fl-link" data-view="${prev.key}">← ${escHtml(prev.label)}</button>` : ""}</span>
    <span>${next ? `<button class="fl-link" data-view="${next.key}">${escHtml(next.label)} →</button>` : `<button class="fl-link" data-view="fin-lectures">강의실로 →</button>`}</span>
  </div>`;
}

let mdReady = null;
function loadMarkdownTools() {
  // 개념 학습 사이트(/learn/)와 같은 판 — marked 로 그리고 DOMPurify 로 거른다
  if (window.marked && window.DOMPurify) return Promise.resolve();
  if (!mdReady) {
    const add = src => new Promise((ok, fail) => { const s = document.createElement("script"); s.src = src; s.onload = ok; s.onerror = fail; document.head.appendChild(s); });
    mdReady = Promise.all([
      add("https://cdn.jsdelivr.net/npm/marked@18.0.14/lib/marked.umd.js"),
      add("https://cdn.jsdelivr.net/npm/dompurify@3.4.16/dist/purify.min.js"),
    ]).catch(e => { mdReady = null; throw e; });
  }
  return mdReady;
}

const slug = (s, i) => "fl-" + i + "-" + s.replace(/[^\p{L}\p{N}]+/gu, "-").replace(/^-|-$/g, "").slice(0, 40);

// 굵은 글씨 바로 뒤에 한글 조사가 붙으면(**캔들 차트(…)**는) 마크다운 표준의 강조 규칙이 닫는 별표로 보지 않아
// 별표가 그대로 보인다. 그리기 전에 같은 줄 안의 **…** 를 <strong> 으로 바꾼다 — 코드 블록 · 코드 조각 안은 그대로 둔다.
function boldForKorean(md) {
  let fenced = false;
  return md.split("\n").map(line => {
    if (/^\s*(```|~~~)/.test(line)) { fenced = !fenced; return line; }
    if (fenced) return line;
    const codes = [];
    const kept = line.replace(/`[^`]*`/g, m => { codes.push(m); return `\u0000${codes.length - 1}\u0000`; });
    return kept.replace(/\*\*([^*\n]+?)\*\*/g, "<strong>$1</strong>").replace(/\u0000(\d+)\u0000/g, (_, i) => codes[Number(i)]);
  }).join("\n");
}

async function renderUnits(host, t, cat) {
  await loadMarkdownTools();
  const parse = window.marked.parse || window.marked.marked;
  const parts = [];
  for (const id of t.units) {
    const u = unitOf(cat, id);
    const r = await fetch(BASE + u.file, { cache: "no-cache" });
    if (!r.ok) throw new Error(`교재 ${id}단원을 불러오지 못했습니다`);
    let md = await r.text();
    md = md.replace(/^## 원문: .*$/gm, "");             // 원본 문서 번호 표시 줄 — 읽는 사람에게 뜻이 없다
    const html = window.DOMPurify.sanitize(parse(boldForKorean(md)));
    parts.push(id === t.units[0] ? html : `<div class="fl-unit-divider">이어서 — 교재 ${id}단원 · ${escHtml(u.title.replace(/^.*?\.\s*/, ""))}</div>${html}`);
  }
  host.innerHTML = `
    <div class="fl-reader">
      <nav class="fl-card fl-toc" aria-label="이 강의의 절"><b>이 강의의 절</b><div class="fl-toc-list"></div></nav>
      <article class="fl-card fl-article">${parts.join("")}</article>
    </div>`;
  const art = host.querySelector(".fl-article");
  // 그림 주소는 교재 파일 기준(img/…)이라 앱 주소에서 열면 틀린다 — 강의 폴더 기준으로 고친다
  art.querySelectorAll("img").forEach(img => {
    const src = img.getAttribute("src") || "";
    if (src && !/^(https?:)?\/\//.test(src) && !src.startsWith("/")) img.src = BASE + "curriculum/" + src;
    img.loading = "lazy";
  });
  art.querySelectorAll("a[href^='http']").forEach(a => { a.target = "_blank"; a.rel = "noopener noreferrer"; });
  const toc = host.querySelector(".fl-toc-list");
  const heads = [...art.querySelectorAll("h2, .fl-unit-divider")];
  toc.innerHTML = heads.map((h, i) => {
    if (h.classList.contains("fl-unit-divider")) return `<div class="fl-toc-unit">${escHtml(h.textContent)}</div>`;
    h.id = slug(h.textContent, i);
    return `<a href="#${h.id}" data-target="${h.id}">${escHtml(h.textContent)}</a>`;
  }).join("");
  // 앱의 주소(#화면키)를 건드리지 않고 그 절로만 내려간다
  toc.querySelectorAll("a[data-target]").forEach(a => a.addEventListener("click", e => {
    e.preventDefault();
    document.getElementById(a.dataset.target)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }));
}

async function renderTopic(el, t, hash = "") {
  const want = t.key + "|" + hash;
  if (el.dataset.rendered === want) return;           // 다시 들어올 때마다 강의 페이지를 새로 싣지 않는다
  el.dataset.rendered = want;
  el.innerHTML = `<div class="fl-card fl-muted">강의를 불러오는 중…</div>`;
  let cat;
  try { cat = await loadCatalog(); } catch {
    el.dataset.rendered = "";
    el.innerHTML = `<div class="fl-card">강의 목록을 불러오지 못했습니다. 잠시 뒤 다시 열어 주세요.</div>`;
    return;
  }
  el.innerHTML = `${topicHead(cat, t)}<div class="fl-body" style="margin-top:16px"></div><div style="margin-top:14px">${topicNav(t)}</div>`;
  const body = el.querySelector(".fl-body");
  if (t.day) {
    const d = dayOf(cat, t.day);
    body.innerHTML = `<iframe class="fl-frame" title="${escHtml(t.label)} 강의 본문" src="${BASE}${d.file}?embed=1${escHtml(hash)}" loading="lazy"></iframe>`;
  } else {
    try { await renderUnits(body, t, cat); } catch (e) {
      el.dataset.rendered = "";
      body.innerHTML = `<div class="fl-card">교재를 불러오지 못했습니다 — ${escHtml(e.message || "")}</div>`;
    }
  }
  el.querySelectorAll("button[data-view]").forEach(b => b.addEventListener("click", () => navigate(b.dataset.view)));
}

// 「요약」 화면 아래 강의 입구 — 한 번만 붙인다
function addSummaryEntry(view) {
  const keys = SUMMARY_ENTRIES[view];
  const host = document.querySelector(`.view[data-view="${view}"]`);
  if (!keys || !host || host.querySelector(".fl-entry")) return;
  const box = document.createElement("div");
  box.className = "fl-card fl-entry";
  box.innerHTML = `<div style="font-weight:800">강의에서 자세히</div>
    <div class="fl-muted" style="font-size:14px">이 화면은 요약입니다. 개념마다 질문형 절 · 그림 · 계산기로 이어지는 강의를 읽어 보세요.</div>
    <div class="fl-entry-links">${keys.map(k => `<button data-view="${k}"><i class="${TOPIC_BY_KEY[k].icon}"></i> ${escHtml(TOPIC_BY_KEY[k].label)}</button>`).join("")}
      <button data-view="fin-lectures"><i class="fa-solid fa-chalkboard-user"></i> 강의실 전체</button></div>`;
  box.querySelectorAll("button[data-view]").forEach(b => b.addEventListener("click", () => navigate(b.dataset.view)));
  host.appendChild(box);
}

// 강의 페이지(iframe) 안의 일차 · 화면 링크 → 앱 화면 이동 (scripts/lectures_build.py 가 강의 페이지에 넣은 신호)
let pendingHash = "";
window.addEventListener("message", e => {
  if (e.origin !== location.origin || !e.data || e.data.type !== "q-lecture-nav") return;
  if (e.data.day && TOPIC_BY_DAY[e.data.day]) {
    pendingHash = e.data.hash || "";
    navigate(TOPIC_BY_DAY[e.data.day].key);
    return;
  }
  const target = LECTURE_VIEW_TO_APP[e.data.view];
  if (target) navigate(target);
  else setToast("이 기능은 준비 중입니다", "info");
});

export function onFinLearnViewActivated(view) {
  if (view === "fin-lectures") {
    const el = document.getElementById("finlearn-hub");
    if (el) renderHub(el);
    return;
  }
  const t = TOPIC_BY_KEY[view];
  if (t) {
    const el = document.querySelector(`.view[data-view="${view}"] .finlearn-topic`);
    const hash = pendingHash; pendingHash = "";
    if (el) renderTopic(el, t, hash);
    return;
  }
  addSummaryEntry(view);
}
