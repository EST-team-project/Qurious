/* 개념 학습 — 위 탭 「학습」 안의 앱 화면 (2026-10-19)
 *
 * 전에는 따로 된 쪽(/learn/ · 왼쪽 메뉴의 「새 화면」)에서 읽었다. 사용자 10-19 「학습을 금융필수지식 + 개념학습으로
 * 하기로 했는데 분리되어 있는 오류」 — 이제 금융 필수 지식 강의실과 같은 틀(fl-card · fl-reader)로 앱 안에서 읽는다.
 *
 *   learn-home   학습 홈 — 세 갈래 카드 · 이어 읽기 · 로그인하면 팀 자료
 *   learn-dev · learn-python   갈래 홈 — 강의실(finlearn.js)과 같은 카드 꼴(부 카드, 부가 하나면 장 카드)
 *   learn-part   부 목차 — 한 부의 장 줄 · 앞뒤 부(메뉴 줄 없음 · 주소 #learn-part/<갈래>/<부>)
 *   learn-page   장 한 편 — 머리(부 · 번호 · 상태 · 먼저 읽을 장) · 왼쪽 「이 장의 차례」 · 본문 · 앞뒤 장(메뉴 줄 없음)
 *
 * 장 주소는 #learn/<slug>(?h=<제목 id>) — 사용법 창 · 상품 안내 · 글 속 링크가 쓴다. 앱의 첫 화면 고르기(main.js)와
 * 해시 처리(core.js)는 화면 키만 알아서, 장 이름은 이 모듈이 받아 두고 주소를 화면 키(#learn-page)로 바꾼 뒤 옮긴다
 * (바꿔 두지 않으면 뒤로 가기가 #learn/<slug> 로 돌아와 다시 옮겨지고, 앞 화면으로 못 간다).
 * 읽던 장은 이 탭(sessionStorage — 새로 고침)과 다음 방문(localStorage — 「이어 읽기」)에 남긴다.
 *
 * 글 그리기는 /learn/ 과 같다: 마크다운(marked) → 거르기(DOMPurify — 스크립트 · 폼 막음) → 거른 뒤의 DOM 고치기
 * (알림 상자 · 출력 상자 · Mermaid 그림 · 코드 색칠 · 제목 id · 바깥 링크 새 창 · 글 속 옛 /learn/ 주소를 앱 주소로).
 * 렌더러를 고치지 않고 거른 뒤 DOM 을 고치는 까닭: marked 의 렌더러 API 는 판마다 바뀌어 왔다(판이 바뀌어도 덜 깨진다).
 * 서버 · API 는 그대로(/api/learn/catalog · /api/learn/pages/{slug}). /learn/ 은 관리자의 팀 자료 받기 · 원문 확인용으로 남는다.
 */
import { escHtml } from "/js/common.js";
import { navigate, showUnder } from "/js/core.js";   // showUnder — 메뉴 줄 없는 화면(부 목차 · 장)이 들어온 갈래를 알린다
import { noticeCardHtml, noticeLineHtml } from "/js/learnnotice.js";   // 「시작하기 전에」 고지 한 벌(장 대장 F00 · 2026-10-20)

const API = "/api/learn";
// 학습 세 갈래(2026-10-20 안 A · 10-23 세 갈래로 — 금융 필수 지식 · 개발 개념 · 파이썬 중급).
// 서버 응답(section · part)은 그대로 두고 화면이 가른다 — section finance → 금융 필수 지식 ·
// 부 이름에 「파이썬」 → 파이썬 중급 · 그 밖 → 개발 개념(clBranchOf). 금융 필수 지식 갈래의 첫 화면은 강의실(fin-lectures)이다.
const BRANCHES = [
  { key: "finance", view: "fin-lectures", label: "금융 필수 지식", icon: "fa-solid fa-coins",
    blurb: "강의실 4일 과정 · 교재 단원 · 보충 장 — 상품의 구조와 위험을 읽고 내 기준으로 비교합니다" },
  { key: "dev", view: "learn-dev", label: "개발 개념", icon: "fa-solid fa-microchip",
    blurb: "수집 · 근거 답 · 차트 · 서버 · AI 에이전트 · 백테스트 — Qurious 기능이 움직이는 원리" },
  { key: "python", view: "learn-python", label: "파이썬 중급", icon: "fa-solid fa-code",
    blurb: "우리 코드에 쓰인 import · 타입 힌트 · 인터페이스 · 예외 처리 · 문자열을 차례로" },
];
const BRANCH = Object.fromEntries(BRANCHES.map(b => [b.key, b]));
// 부 카드의 한 줄 — 강의실 카드의 한 줄과 같은 자리. 장 제목에서 뽑지 않고 사람이 쓴다(부가 바뀌면 이 표에 한 줄)
const PART_BLURB = {
  "dev:0": "자료를 모아 근거로 답하고, 신호 · 성과 검증 · 자산배분 · 주문으로 이어지는 흐름을 한 장의 그림으로 봅니다.",
  "dev:1": "봉이 만들어지는 규칙부터 수정주가 · 분봉 시간대 · 품질 검사까지, 차트에 그리는 숫자가 어디서 오는지 익힙니다.",
  "dev:2": "원문 · 정제 · 파생의 세 층, 공식 API 호출, 자료 판 공유, 정기 배치와 거래일 달력을 다룹니다.",
  "dev:3": "질문에 맞는 근거 문서를 찾아 붙이는 방법 — 임베딩 · 섞어 찾기 · 문서 쪼개기 · 출처 표기 · 평가를 차례로 봅니다.",
  "dev:4": "용어 사전과 시소러스로 낱말의 관계를 잇고, 지식 그래프의 노드 · 간선 · 탐색 깊이를 봅니다.",
  "dev:5": "가격 차트를 그리고, Pine Script 로 지표 · 전략을 적고, 경보를 서버로 받는 길을 봅니다.",
  "dev:7": "FastAPI · Docker Compose · 시험 코드 · 동시 수정 막기 · 저장소 다섯 · 예약 작업 — 서비스를 돌리는 바탕입니다.",
  "dev:8": "LangChain 체인과 LangGraph 상담 에이전트, PostgreSQL 안의 벡터(pgvector), 관계 그래프를 더한 검색을 봅니다.",
  "dev:9": "지표 계산 정의, 패턴 · 지지 · 저항 찾기, 여러 주기 신호 합치기, 사건 연구, 추천 이유 설명을 다룹니다.",
  "dev:10": "체결 시점 · 비용을 지킨 백테스트, 성과 지표 계산, 모의 주문 장부, 시장과 견주는 지표를 봅니다.",
  "dev:11": "성향 점수에서 자산군 비중까지, 리밸런싱 세 방식, 증권사 Open API, 주문 안전장치를 봅니다.",
  "dev:12": "그래디언트 부스팅, 시간 순서를 지킨 평가, 종목 군집화, 계절성 검정 — 모델을 믿을 수 있게 만드는 순서입니다.",
};
// 장 상태 낱말 — 화면에는 「완성」 · 「뼈대」 같은 작업 말을 쓰지 않는다(읽을 수 있는 장은 꼬리표 없음)
const STATUS = { ready: "", draft: "다듬는 중", skeleton: "준비 중" };
const STATUS_ICON = { ready: "fa-solid fa-circle-check", draft: "fa-solid fa-pen", skeleton: "fa-regular fa-circle" };
const CALLOUT = {
  GOAL: ["goal", "이 장에서 할 수 있게 되는 것", "fa-solid fa-bullseye"],
  NOTE: ["note", "참고", "fa-solid fa-circle-info"],
  TIP: ["tip", "도움말", "fa-solid fa-lightbulb"],
  IMPORTANT: ["important", "중요", "fa-solid fa-star"],
  WARNING: ["warning", "주의", "fa-solid fa-triangle-exclamation"],
  CAUTION: ["warning", "주의", "fa-solid fa-triangle-exclamation"],
};
// 장 이름 규칙은 서버(app/services/learn_pages.py SLUG_RE)와 같게 — 다른 글자가 든 주소는 장 주소로 보지 않는다
const SLUG = "[a-z0-9][a-z0-9-]{1,62}[a-z0-9]";
const HASH_RE = new RegExp(`^#learn/(${SLUG})(?:\\?h=([^&#]*))?$`);
const OLD_PAGE_RE = new RegExp(`^(?:/learn/)?#/p/(${SLUG})(?:\\?h=([^&#]*))?$`);   // 글 속 옛 /learn/ 장 주소
const OLD_HOME_RE = /^(?:\/learn\/)?#\/(?:s\/[a-z]+)?$/;                            // 글 속 옛 /learn/ 목차 주소
const NOW_KEY = "q-learn-now";     // 이 탭에서 읽던 장
const LAST_KEY = "q-learn-last";   // 다음 방문의 「이어 읽기」
const READ_KEY = "q-learn-read";   // 연 장 — 갈래 카드 · 부 목차의 「읽은 장 n / N」(이 브라우저에만)
const PART_KEY = "q-learn-part";   // 이 탭에서 보던 부 목차(새로 고침)
const LIB = {
  marked: "https://cdn.jsdelivr.net/npm/marked@18.0.14/lib/marked.umd.js",
  purify: "https://cdn.jsdelivr.net/npm/dompurify@3.4.16/dist/purify.min.js",
  hljs: "https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@11.12.0/highlight.min.js",
  hljsCss: "https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@11.12.0/styles/github.min.css",
  mermaid: "https://cdn.jsdelivr.net/npm/mermaid@12.0.0/dist/mermaid.min.js",
};

// 브라우저 저장소 — 개인 창 · 막힌 저장소에서도 화면이 깨지지 않게 감싼다
const store = kind => ({
  get(k) { try { return window[kind].getItem(k) || ""; } catch { return ""; } },
  set(k, v) { try { window[kind].setItem(k, v); } catch { /* 저장이 안 돼도 읽기는 된다 */ } },
});
const tabStore = store("sessionStorage");
const keepStore = store("localStorage");

// 연 장 — 장을 열면 더한다(끝까지 읽었는지는 재지 않는다 · 사용법 글에도 「연 장의 수」)
function readSet() {
  try { const a = JSON.parse(keepStore.get(READ_KEY) || "[]"); return new Set(Array.isArray(a) ? a : []); } catch { return new Set(); }
}
function markRead(slug) {
  const s = readSet();
  if (s.has(slug)) return;
  s.add(slug);
  keepStore.set(READ_KEY, JSON.stringify([...s].slice(-500)));
}

// ── 장 주소(#learn/<slug>) 받기 ─────────────────────────────────────
function takeHash() {
  const m = location.hash.match(HASH_RE);
  if (!m) return null;
  // 화면 키 주소로 바꾸고 장 이름은 이 기록 칸에 — 첫 화면 고르기가 learn-page 를 열고, 뒤로 가기가 그 장으로 돌아온다(popstate)
  history.replaceState({ clSlug: m[1] }, "", "#learn-page");
  let h = "";
  try { h = decodeURIComponent(m[2] || ""); } catch { h = ""; }
  return { slug: m[1], h };
}
// 부 목차 주소(#learn-part/<갈래>/<부>) — 장 주소와 같은 방식: 화면 키 주소(#learn-part)로 바꾸고 갈래 · 부는 기록 칸에
const PART_RE = /^#learn-part\/(dev|python)\/(\d{1,2})$/;
function takePartHash() {
  const m = location.hash.match(PART_RE);
  if (!m) return null;
  history.replaceState({ clPart: `${m[1]}/${m[2]}` }, "", "#learn-part");
  return `${m[1]}/${m[2]}`;
}
// 모듈을 읽는 순간(main.js 가 첫 화면을 고르기 전)에 한 번 — 북마크 · 다른 쪽에서 #learn/<slug> 로 들어온 때
let pending = takeHash();
let pendingPart = takePartHash();
// 앱 안 링크(사용법 창 · 상품 안내 · 글 속 링크 · 카드)가 #learn/<slug> · #learn-part/… 로 바꾼 때 — core.js 의 해시 처리는 화면 키가 아니라 그냥 둔다
window.addEventListener("hashchange", () => {
  const part = takePartHash();
  if (part) { pendingPart = part; navigate("learn-part"); return; }
  const p = takeHash();
  if (!p) return;
  pending = p;
  navigate("learn-page");
});
// 장에서 장(부에서 부)으로 옮긴 기록은 주소가 모두 #learn-page(#learn-part)라 뒤로 · 앞으로 가기에 hashchange 가 나지 않는다 — 기록 칸으로 다시 그린다
window.addEventListener("popstate", e => {
  const part = e.state && e.state.clPart;
  if (part && location.hash === "#learn-part") { pendingPart = part; navigate("learn-part"); return; }
  const slug = e.state && e.state.clSlug;
  if (!slug || location.hash !== "#learn-page") return;
  pending = { slug, h: "" };
  navigate("learn-page");
});

// ── 목록 · 글 받기 ──────────────────────────────────────────────────
let cat = null;
let catAt = 0;
let catLoading = null;
async function loadCatalog() {
  if (cat && Date.now() - catAt < 60_000) return cat;
  if (!catLoading) {
    catLoading = fetch(`${API}/catalog`, { credentials: "same-origin" })
      .then(r => { if (!r.ok) throw new Error(`목차를 불러오지 못했습니다 (${r.status})`); return r.json(); })
      .then(d => {
        const bySlug = new Map();
        for (const p of d.pages || []) if (!bySlug.has(p.slug)) bySlug.set(p.slug, p);   // 같은 이름이면 기본 교재가 먼저(서버와 같은 규칙)
        cat = { pages: d.pages || [], bySlug, team: d.team || {} };
        catAt = Date.now();
        return cat;
      })
      .finally(() => { catLoading = null; });
  }
  return catLoading;
}

async function fetchPage(slug) {
  const r = await fetch(`${API}/pages/${encodeURIComponent(slug)}`, { credentials: "same-origin" });
  let d = null;
  try { d = await r.json(); } catch { d = null; }
  if (!r.ok) {
    const det = d && d.detail;
    const msg = (det && typeof det.message === "string" && det.message) || (typeof det === "string" && det) || `글을 불러오지 못했습니다 (${r.status})`;
    const err = new Error(msg);
    err.status = r.status;
    throw err;
  }
  return d;
}

// ── 글 그리기 도구(처음 쓸 때만 받는다) ─────────────────────────────
const loading = new Map();
function addScript(src) {
  if (!loading.has(src)) {
    loading.set(src, new Promise((ok, fail) => {
      const s = document.createElement("script");
      s.src = src;
      s.onload = ok;
      s.onerror = () => { loading.delete(src); fail(new Error(`도구를 받지 못했습니다: ${src}`)); };
      document.head.appendChild(s);
    }));
  }
  return loading.get(src);
}
function markdownTools() {
  if (window.marked && window.DOMPurify) return Promise.resolve();   // 강의실(finlearn.js)이 먼저 받았으면 그대로 쓴다
  return Promise.all([addScript(LIB.marked), addScript(LIB.purify)]);
}
function highlightTools() {
  if (!document.querySelector(`link[href="${LIB.hljsCss}"]`)) {
    const l = document.createElement("link");
    l.rel = "stylesheet";
    l.href = LIB.hljsCss;
    document.head.appendChild(l);
  }
  return window.hljs ? Promise.resolve() : addScript(LIB.hljs);
}

// ── 목차 ────────────────────────────────────────────────────────────
function groupBy(items, keyFn) {
  const map = new Map();
  for (const it of items) {
    const k = keyFn(it);
    if (!map.has(k)) map.set(k, []);
    map.get(k).push(it);
  }
  return map;
}

function statusChip(st) {
  if (!STATUS[st]) return "";   // 읽을 수 있는 장(ready)은 꼬리표 없이
  return `<span class="cl-st cl-st-${escHtml(st)}"><i class="${STATUS_ICON[st] || "fa-regular fa-circle"}" aria-hidden="true"></i>${escHtml(STATUS[st])}</span>`;
}

// 장 번호 — 팀 자료는 「팀」
function chapterNum(p) {
  return p.store === "team" ? "팀" : (p.order || "");
}

function chapterRow(p, read) {
  const done = read && read.has(p.slug) ? ' <span class="cl-read"><i class="fa-solid fa-check" aria-hidden="true"></i>읽음</span>' : "";
  return `<li><span class="cl-num">${escHtml(chapterNum(p))}</span><span class="cl-row">`
    + `<a href="#learn/${escHtml(p.slug)}">${escHtml(p.title)}</a> ${statusChip(p.status)}${done}`
    + `<span class="cl-sum">${escHtml(p.summary || "")}</span></span></li>`;
}

// 장 세기 — 읽을 수 있는 장 = 준비 중(뼈대)이 아닌 장. 다듬는 중(초안)도 본문이 있어 읽을 수 있다
function clCounts(pages) {
  const soon = pages.filter(p => p.status === "skeleton").length;
  return { readable: pages.length - soon, soon };
}

function partCard(part, items) {
  const { readable } = clCounts(items);
  const pct = items.length ? Math.round((100 * readable) / items.length) : 0;
  return `<article class="fl-card cl-part">
      <div class="cl-part-head"><h3>${escHtml(part)}</h3><span class="fl-chip">장 ${items.length} · 읽을 수 있는 장 ${readable}</span></div>
      <div class="fl-bar" aria-hidden="true"><i style="width:${pct}%"></i></div>
      <ul class="cl-list">${items.map(p => chapterRow(p)).join("")}</ul>
    </article>`;
}

// 갈래 — 장 머리말(section · part)로 가른다(서버 응답 그대로)
function clBranchOf(p) {
  if (p.section === "finance") return "finance";
  return /파이썬/.test(p.part || "") ? "python" : "dev";
}

function clBranchCard(b, pages) {
  const { readable, soon } = clCounts(pages);
  const meta = b.key === "finance"
    ? `강의 4일 과정 · 교재 단원 · 보충 장 ${pages.length}`
    : `장 ${pages.length} · 읽을 수 있는 장 ${readable}${soon ? ` · 준비 중 ${soon}` : ""}`;
  return `<a class="fl-card cl-branch" href="#${b.view}">
      <div class="cl-branch-top"><i class="${b.icon}" aria-hidden="true"></i><h3>${escHtml(b.label)}</h3></div>
      <p>${escHtml(b.blurb)}</p><span class="fl-chip">${escHtml(meta)}</span></a>`;
}

async function renderHome(el) {
  el.innerHTML = '<div class="fl-card fl-muted">학습 목차를 불러오는 중…</div>';
  let c;
  try { c = await loadCatalog(); } catch (e) {
    el.innerHTML = `<div class="fl-card">${escHtml(e.message)} — 잠시 뒤 다시 열어 주세요.</div>`;
    return;
  }
  const builtin = c.pages.filter(p => p.store === "builtin");
  const team = c.pages.filter(p => p.store === "team");
  const last = c.bySlug.get(keepStore.get(LAST_KEY));
  let html = `<div class="fl-hub-head"><h2>학습</h2>
      <span class="fl-muted">금융 필수 지식부터 Qurious 를 만든 개발 개념 · 파이썬 중급까지, 세 갈래로 나눠 읽습니다.</span>
      ${last ? `<a class="fl-link cl-resume" href="#learn/${escHtml(last.slug)}">이어 읽기 — ${escHtml(last.order)} ${escHtml(last.title)} →</a>` : ""}</div>`;
  html += `<div class="cl-branch-grid">${BRANCHES.map(b => clBranchCard(b, builtin.filter(p => clBranchOf(p) === b.key))).join("")}</div>`;
  if (team.length) {
    html += `<div class="fl-section-title cl-sec"><i class="fa-solid fa-users" aria-hidden="true"></i>팀 자료 <small>팀이 정리한 학습 자료 · 장 ${team.length}</small></div>`
      + `<div class="fl-grid">${partCard("팀 자료", team)}</div>`;
  }
  html += `<p class="fl-muted cl-note">「준비 중」 장은 다룰 질문과 참고 자료를 먼저 실었습니다. 「다듬는 중」 장은 본문이 있고 그림 · 확인 문제를 더하는 중입니다.</p>`;
  html += `<p class="cl-note cl-videos-link"><a class="fl-link" href="#learn-videos"><i class="fa-solid fa-circle-play" aria-hidden="true"></i> 화면 쓰는 법은 사용법 영상으로 →</a></p>`;
  html += noticeLineHtml();
  if (c.team && c.team.admin) {
    html += `<p class="fl-muted cl-note">관리자 — 팀 자료 받기 · 고친 기록은 <a href="/learn/#/team" target="_blank" rel="noopener">개념 학습 원문 쪽(새 창)</a>에서 봅니다.</p>`;
  }
  el.innerHTML = html;
}

// ── 갈래 홈 · 부 목차 (2026-10-20 사용자 「강의실처럼 깔끔하게 · 나눠서 · 통일」) ──
// 강의실(finlearn.js)과 같은 꼴: 갈래 홈은 부 카드(번호 · 제목 · 분량 · 한 줄 · 장 둘 · 막대 · 읽은 장)이고,
// 카드를 누르면 부 목차(learn-part)에서 장을 고른다. 부가 하나뿐인 갈래(파이썬 중급)는 강의실 「교재」 카드처럼 장마다 카드.

// 부 번호 — 장 차례의 앞자리(3.2 → 3 · 서버 learn_pages.ORDER_RE 와 같은 꼴)
function partNoOf(p) {
  return String(p.order || "").split(".")[0];
}

// 갈래의 부 목록 — 목차 차례 그대로(서버 정렬)
function clParts(c, key) {
  const pages = c.pages.filter(p => p.store === "builtin" && clBranchOf(p) === key);
  return [...groupBy(pages, partNoOf)].map(([no, items]) => ({ key, no, items, label: items[0].part || "" }));
}
const partBadge = x => x.no.padStart(2, "0");
const partTitle = x => x.label.replace(/^\d+부\s*/, "");
// 앞뒤 부 단추 · 장 머리 되돌아가기 글 — 「3부 근거 RAG」
const partName = x => x.label;
const minsOf = items => items.reduce((s, p) => s + (Number(p.minutes) || 0), 0);
const minsText = m => (m >= 90 ? `약 ${Math.round(m / 30) / 2}시간` : `약 ${m}분`);

// 부 카드 — 강의실 「4일 과정」 카드(finlearn courseCard)와 같은 꼴
function clCourseCard(x, read) {
  const n = x.items.length;
  const done = x.items.filter(p => read.has(p.slug)).length;
  const { soon } = clCounts(x.items);
  const chip = `${n}장 · ${minsText(minsOf(x.items))}`;
  const cta = soon === n ? "목차 보기 →" : !done ? "학습 시작 →" : done < n ? "이어 읽기 →" : "다시 보기 →";
  return `<a class="fl-card fl-course cl-course" href="#learn-part/${x.key}/${x.no}">
      <div class="fl-top"><span class="fl-no">${escHtml(partBadge(x))}</span><h3>${escHtml(partTitle(x))}</h3>
        <span class="fl-chip">${escHtml(chip)}</span></div>
      <p>${escHtml(PART_BLURB[`${x.key}:${x.no}`] || x.items[0].summary || "")}</p>
      <ul>${x.items.slice(0, 2).map(p => `<li title="${escHtml(p.title)}">${escHtml(p.title)}</li>`).join("")}</ul>
      <div class="fl-bar" aria-hidden="true"><i style="width:${Math.round((100 * done) / n)}%"></i></div>
      <div class="fl-foot"><span class="fl-muted">읽은 장 ${done} / ${n}${soon ? ` · 준비 중 ${soon}` : ""}</span><span class="fl-link">${cta}</span></div>
    </a>`;
}

// 장 카드 — 부가 하나뿐인 갈래는 강의실 「교재」 카드(finlearn unitCard)처럼 장마다 카드로 바로 읽는다
function clChapterCard(p, read) {
  const done = read.has(p.slug);
  const title = String(p.title || "");
  const cut = title.indexOf(" — ");   // 「import 와 타입 힌트 — 패키지 · …」 → 제목 · 다루는 것
  return `<a class="fl-card fl-course cl-course" href="#learn/${escHtml(p.slug)}">
      <div class="fl-top"><span class="fl-no">${escHtml(p.order || "")}</span><h3>${escHtml(cut < 0 ? title : title.slice(0, cut))}</h3>
        ${p.minutes ? `<span class="fl-chip">${escHtml(minsText(Number(p.minutes)))}</span>` : ""}</div>
      ${cut < 0 ? "" : `<p class="cl-keys">${escHtml(title.slice(cut + 3))}</p>`}
      <p class="cl-clamp">${escHtml(p.summary || "")}</p>
      <div class="fl-foot"><span class="fl-muted">${done ? '<i class="fa-solid fa-check" aria-hidden="true"></i> 읽음' : statusChip(p.status)}</span>
        <span class="fl-link">${p.status === "skeleton" ? "다룰 질문 보기 →" : done ? "다시 보기 →" : "읽기 →"}</span></div>
    </a>`;
}

// 갈래 홈 — 개발 개념 · 파이썬 중급
async function clRenderBranch(el, key) {
  const b = BRANCH[key];
  el.innerHTML = `<div class="fl-card fl-muted">${escHtml(b.label)} 목차를 불러오는 중…</div>`;
  let c;
  try { c = await loadCatalog(); } catch (e) {
    el.innerHTML = `<div class="fl-card">${escHtml(e.message)} — 잠시 뒤 다시 열어 주세요.</div>`;
    return;
  }
  const parts = clParts(c, key);
  const pages = parts.flatMap(x => x.items);
  const read = readSet();
  const { readable, soon } = clCounts(pages);
  const drafts = pages.filter(p => p.status === "draft").length;
  const single = parts.length === 1;
  const course = single ? `${pages.length}장 과정` : `${parts.length}부 과정`;
  const stat = pages.length ? `장 ${pages.length} · 읽을 수 있는 장 ${readable}${soon ? ` · 준비 중 ${soon}` : ""} · 모두 읽으면 ${minsText(minsOf(pages))}` : "";
  el.innerHTML = `<div class="fl-hub-head"><h2>${escHtml(b.label)}</h2>
      <span class="fl-muted">${escHtml(b.blurb)}</span>
      <a class="fl-link cl-home-link" href="#learn-home">← 학습 홈</a></div>
    <div class="fl-section-title">${escHtml(course)} <small>${escHtml(stat)}</small></div>
    ${single ? `<div class="fl-grid three">${parts[0].items.map(p => clChapterCard(p, read)).join("")}</div>`
      : `<div class="fl-grid">${parts.map(x => clCourseCard(x, read)).join("")}</div>`}
    ${soon || drafts ? '<p class="fl-muted cl-note">「준비 중」 장은 다룰 질문과 참고 자료를 먼저 실었습니다. 「다듬는 중」 장은 본문이 있고 그림 · 확인 문제를 더하는 중입니다.</p>' : ""}
    ${noticeLineHtml()}`;
}

// 장 머리의 되돌아가기 · 왼쪽 트리 — 부 목차가 있는 갈래(개발 개념)는 그 부 목차로, 그 밖은 갈래 첫 화면으로
function backOf(m, store) {
  const home = { href: "#learn-home", label: "학습 홈", parent: "learn-home" };
  if (store === "team") return home;
  const key = clBranchOf(m);
  const b = BRANCH[key];
  if (!b) return home;
  if (key === "dev") {
    const x = { key, no: partNoOf(m), label: m.part || "" };
    return { href: `#learn-part/${key}/${x.no}`, label: `${partName(x)} 목차`, parent: b.view };
  }
  return { href: `#${b.view}`, label: b.label, parent: b.view };
}

// 부 목차 — 부 카드를 누르면 열린다(강의실의 주제 화면 자리)
async function clRenderPart(el, want) {
  const [key, no] = String(want || "").split("/");
  const b = BRANCH[key];
  el.innerHTML = '<div class="fl-card fl-muted">목차를 불러오는 중…</div>';
  let c;
  try { c = await loadCatalog(); } catch (e) {
    el.innerHTML = `<div class="fl-card">${escHtml(e.message)} — 잠시 뒤 다시 열어 주세요.</div>`;
    return;
  }
  const parts = b && key !== "finance" ? clParts(c, key).filter(x => x.items.length) : [];
  const i = parts.findIndex(x => x.no === no);
  if (i < 0) {
    el.innerHTML = '<div class="fl-card">찾는 목차가 없습니다. <a class="fl-link" href="#learn-home">학습 홈</a></div>';
    return;
  }
  const x = parts[i], prev = parts[i - 1], after = parts[i + 1];
  const read = readSet();
  const n = x.items.length;
  const done = x.items.filter(p => read.has(p.slug)).length;
  const open = x.items.filter(p => p.status !== "skeleton");   // 본문이 있는 장(다듬는 중 포함)
  const unread = open.find(p => !read.has(p.slug));
  const next = unread || open[0];
  const go = !done ? "첫 장부터 읽기" : unread ? "이어 읽기" : "처음부터 다시 읽기";
  const blurb = PART_BLURB[`${key}:${no}`] || "";
  tabStore.set(PART_KEY, want);
  if (location.hash === "#learn-part") history.replaceState({ clPart: want }, "", "#learn-part");   // 새로 고침 · 뒤로 가기가 이 부로
  el.innerHTML = `<div class="fl-card fl-topic-head cl-part-page">
      <div class="fl-title-row"><span class="cl-part-no">${escHtml(partBadge(x))}</span><h2>${escHtml(partTitle(x))}</h2>
        <span class="fl-chip is-accent">${escHtml(b.label)}</span>
        <span class="fl-chip">${n}장</span>
        <span class="fl-chip"><i class="fa-regular fa-clock" aria-hidden="true"></i> ${escHtml(minsText(minsOf(x.items)))}</span>
        <a class="fl-link cl-home-link" href="#${b.view}">← ${escHtml(b.label)}</a></div>
      ${blurb ? `<p>${escHtml(blurb)}</p>` : ""}
      <div class="fl-bar" aria-hidden="true"><i style="width:${Math.round((100 * done) / n)}%"></i></div>
      <div class="cl-part-foot"><span class="fl-muted">읽은 장 ${done} / ${n}</span>
        ${next ? `<a class="fl-link" href="#learn/${escHtml(next.slug)}">${go} — ${escHtml(chapterNum(next))} ${escHtml(next.title)} →</a>` : '<span class="fl-muted">모든 장이 준비 중입니다 — 장을 누르면 다룰 질문을 볼 수 있습니다.</span>'}</div>
    </div>
    <div class="fl-card"><ul class="cl-list">${x.items.map(p => chapterRow(p, read)).join("")}</ul></div>
    <div class="fl-nav cl-pager">
      <span>${prev ? `<a class="fl-link" href="#learn-part/${key}/${prev.no}">← ${escHtml(partName(prev))}</a>` : ""}</span>
      <span>${after ? `<a class="fl-link" href="#learn-part/${key}/${after.no}">${escHtml(partName(after))} →</a>` : `<a class="fl-link" href="#${b.view}">${escHtml(b.label)} 전체 →</a>`}</span>
    </div>
    ${noticeLineHtml()}`;
  showUnder("learn-part", b.view);
}

// ── 장 한 편 ────────────────────────────────────────────────────────
let pageSeq = 0;      // 빠르게 다른 장을 누르면, 늦게 온 앞 장 응답이 뒤 장을 덮지 않게
let spy = null;       // 차례의 「지금 읽는 절」 표시

function firstReadable(c) {
  const b = c.pages.filter(p => p.store === "builtin");
  return (b.find(p => p.status === "ready") || b[0] || {}).slug || "";
}

function pagerHtml(c, m, store) {
  if (store !== "builtin") return "";
  const key = clBranchOf(m);   // 앞뒤 장은 같은 갈래 안에서(개발 개념 끝 장 다음이 파이썬 중급 첫 장으로 넘어가지 않게)
  const list = c.pages.filter(p => p.store === "builtin" && clBranchOf(p) === key);
  const i = list.findIndex(p => p.slug === m.slug);
  const prev = i > 0 ? list[i - 1] : null;
  const next = i >= 0 && i < list.length - 1 ? list[i + 1] : null;
  return `<div class="fl-nav cl-pager">
      <span>${prev ? `<a class="fl-link" href="#learn/${escHtml(prev.slug)}">← ${escHtml(prev.order)} ${escHtml(prev.title)}</a>` : ""}</span>
      <span>${next ? `<a class="fl-link" href="#learn/${escHtml(next.slug)}">${escHtml(next.order)} ${escHtml(next.title)} →</a>` : `<a class="fl-link" href="#${(BRANCH[key] || { view: "learn-home" }).view}">${escHtml((BRANCH[key] || { label: "학습 홈" }).label)} 전체 →</a>`}</span>
    </div>`;
}

function headCard(c, data) {
  const m = data.meta || {};
  const back = backOf(m, data.store);
  const chips = [
    `<span class="fl-chip is-accent">${escHtml(data.store === "team" ? "팀 자료" : (BRANCH[clBranchOf(m)] || {}).label || "")}</span>`,
    m.part ? `<span class="fl-chip">${escHtml(m.part)}</span>` : "",
    m.order ? `<span class="fl-chip">${escHtml(m.order)}</span>` : "",
    statusChip(m.status || "skeleton"),
    m.level ? `<span class="fl-chip">${escHtml(m.level)}</span>` : "",
    m.minutes ? `<span class="fl-chip"><i class="fa-regular fa-clock" aria-hidden="true"></i> ${escHtml(m.minutes)}분</span>` : "",
  ].join("");
  const prereq = (m.prereq || []).map(s => {
    const p = c.bySlug.get(s);
    return `<a href="#learn/${escHtml(s)}">${escHtml(p ? p.title : s)}</a>`;
  }).join(" · ");
  return `<div class="fl-card fl-topic-head">
      <div class="fl-title-row"><h2>${escHtml(m.title || data.slug || "")}</h2>${chips}
        <a class="fl-link cl-home-link" href="${back.href}">← ${escHtml(back.label)}</a></div>
      ${m.summary ? `<p>${escHtml(m.summary)}</p>` : ""}
      ${prereq ? `<p class="cl-prereq">먼저 읽을 장 — ${prereq}</p>` : ""}
    </div>`;
}

async function renderPage(el, slug, h) {
  const seq = ++pageSeq;
  el.innerHTML = '<div class="fl-card fl-muted">글을 불러오는 중…</div>';
  let c;
  try { c = await loadCatalog(); } catch (e) {
    if (seq === pageSeq) el.innerHTML = `<div class="fl-card">${escHtml(e.message)} — 잠시 뒤 다시 열어 주세요.</div>`;
    return;
  }
  if (!slug || !c.bySlug.has(slug)) slug = firstReadable(c);   // 기억한 장이 목차에서 빠졌으면 첫 「완성」 장
  if (!slug) {
    if (seq === pageSeq) el.innerHTML = '<div class="fl-card">읽을 장이 아직 없습니다. <a class="fl-link" href="#learn-home">전체 목차</a></div>';
    return;
  }
  let data;
  try {
    [data] = await Promise.all([fetchPage(slug), markdownTools()]);
  } catch (e) {
    if (seq !== pageSeq) return;
    el.innerHTML = e.status === 401
      ? '<div class="fl-card">팀 자료는 로그인한 뒤 볼 수 있습니다. <a class="fl-link" href="/login.html">로그인</a></div>'
      : `<div class="fl-card">${escHtml(e.message)} — <a class="fl-link" href="#learn-home">전체 목차</a></div>`;
    return;
  }
  if (seq !== pageSeq) return;
  el.innerHTML = `${headCard(c, data)}
    <div class="fl-reader cl-reader">
      <nav class="fl-card fl-toc" aria-label="이 장의 차례"><b>이 장의 차례</b><div class="fl-toc-list"></div></nav>
      <article class="fl-card fl-article cl-prose"></article>
    </div>
    ${pagerHtml(c, data.meta || {}, data.store)}
    ${noticeLineHtml()}`;
  el.dataset.slug = slug;
  tabStore.set(NOW_KEY, slug);
  keepStore.set(LAST_KEY, slug);
  markRead(slug);
  showUnder("learn-page", backOf(data.meta || {}, data.store).parent);   // 왼쪽 트리 · 머리 경로를 이 장의 갈래로
  // 지금 기록 칸에 장 이름 — 메뉴 「장 읽기」 로 들어와 이어 읽은 장도 뒤로 가기로 돌아오게(다른 화면 기록은 건드리지 않는다)
  if (location.hash === "#learn-page") history.replaceState({ clSlug: slug }, "", "#learn-page");
  const art = el.querySelector(".cl-prose");
  drawMarkdown(data.body || "", art);
  buildToc(el.querySelector(".fl-toc-list"), art);
  await Promise.all([colorCode(art), drawMermaid(art)]);
  if (seq !== pageSeq) return;
  const target = h && document.getElementById(h);
  if (target && art.contains(target)) target.scrollIntoView({ block: "start" });
  else document.getElementById("main-content")?.scrollTo(0, 0);   // 굴러가는 칸은 창이 아니라 #main-content(DF-134)
}

function drawMarkdown(md, el) {
  const parse = window.marked.parse || window.marked.marked;
  const raw = parse(md, { gfm: true });
  el.innerHTML = window.DOMPurify.sanitize(raw, {
    USE_PROFILES: { html: true, svg: true, svgFilters: true },
    FORBID_TAGS: ["style", "form", "input", "button", "textarea", "select"],
  });
  enhance(el);
}

function slugifyHeading(s) {
  return "cl-" + (String(s).trim().toLowerCase().replace(/[^\p{L}\p{N}\s-]/gu, "").replace(/\s+/g, "-").slice(0, 60) || "sec");
}

function enhance(el) {
  // 1) 알림 상자 — > [!NOTE] 첫 줄(GitHub 와 같은 표기) · [!GOAL] 은 우리 교재의 학습 목표 상자
  el.querySelectorAll("blockquote").forEach(bq => {
    const first = bq.firstElementChild;
    if (!first || first.tagName !== "P") return;
    const hit = first.innerHTML.match(/^\s*\[!(GOAL|NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*(<br\s*\/?>)?\s*/i);
    if (!hit) return;
    const [cls, label, icon] = CALLOUT[hit[1].toUpperCase()];
    first.innerHTML = first.innerHTML.slice(hit[0].length);
    if (!first.textContent.trim() && !first.querySelector("img,svg")) first.remove();
    const box = document.createElement("div");
    box.className = `cl-callout ${cls}`;
    box.innerHTML = `<div class="cl-callout-title"><i class="${icon}" aria-hidden="true"></i>${label}</div>`;
    while (bq.firstChild) box.appendChild(bq.firstChild);
    bq.replaceWith(box);
  });
  // 2) 코드 블록 — mermaid 는 그림 자리로, output 은 「출력」 상자로, 나머지는 머리 띠(언어 · 복사)
  el.querySelectorAll("pre > code").forEach(code => {
    const pre = code.parentElement;
    const lang = ([...code.classList].find(c => c.startsWith("language-")) || "").slice(9);
    if (lang === "mermaid") {
      const box = document.createElement("div");
      box.className = "cl-mermaid";
      box.textContent = code.textContent;
      pre.replaceWith(box);
      return;
    }
    const isOut = lang === "output";
    const block = document.createElement("div");
    block.className = `cl-code${isOut ? " output" : ""}`;
    const head = document.createElement("div");
    head.className = "cl-code-head";
    const name = document.createElement("span");
    name.textContent = isOut ? "출력" : (lang || "코드");
    head.appendChild(name);
    if (!isOut) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = "복사";
      btn.addEventListener("click", async () => {
        try { await navigator.clipboard.writeText(code.textContent); btn.textContent = "복사됨"; } catch { btn.textContent = "복사 안 됨"; }
        setTimeout(() => { btn.textContent = "복사"; }, 1500);
      });
      head.appendChild(btn);
    }
    pre.replaceWith(block);
    block.appendChild(head);
    block.appendChild(pre);
    if (lang && !isOut) code.dataset.clLang = lang;   // 색칠은 도구를 받은 뒤(colorCode)
  });
  // 3) 제목 id — 왼쪽 차례 · #learn/<slug>?h= 주소가 쓴다(앱의 다른 화면 id 와 겹치지 않게 cl- 를 붙인다)
  const used = new Set();
  el.querySelectorAll("h2, h3").forEach(hd => {
    const base = slugifyHeading(hd.textContent);
    let id = base;
    let n = 2;
    while (used.has(id) || document.getElementById(id)) id = `${base}-${n++}`;
    used.add(id);
    hd.id = id;
  });
  // 4) 링크 — 바깥 주소는 새 창, 글 속 옛 /learn/ 주소는 앱 주소로, 같은 장 안 제목 링크는 그 자리로만 굴린다
  el.querySelectorAll("a[href]").forEach(a => {
    const href = a.getAttribute("href") || "";
    let m = href.match(OLD_PAGE_RE);
    if (m) { a.setAttribute("href", `#learn/${m[1]}${m[2] ? `?h=${m[2]}` : ""}`); return; }
    if (OLD_HOME_RE.test(href)) { a.setAttribute("href", "#learn-home"); return; }
    if (/^https?:\/\//i.test(href)) { a.target = "_blank"; a.rel = "noopener noreferrer"; return; }
    if (href.startsWith("#") && !href.startsWith("#learn")) {
      a.addEventListener("click", e => {
        const t = el.querySelector(`[id="${CSS.escape(href.slice(1))}"]`);
        if (!t) return;
        e.preventDefault();   // 앱의 주소(#화면키)를 건드리지 않고 그 절로만
        t.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    }
  });
  // 5) 그림 — 늦게 읽기
  el.querySelectorAll("img").forEach(img => { img.loading = "lazy"; });
}

async function colorCode(el) {
  const codes = [...el.querySelectorAll("code[data-cl-lang]")];
  if (!codes.length) return;
  try { await highlightTools(); } catch { return; }   // 색칠이 안 돼도 글은 보인다
  for (const code of codes) {
    if (window.hljs && window.hljs.getLanguage(code.dataset.clLang)) {
      try { window.hljs.highlightElement(code); } catch { /* 색칠만 빠진다 */ }
    }
  }
}

let mermaidReady = false;
async function drawMermaid(el) {
  const nodes = [...el.querySelectorAll(".cl-mermaid")];
  if (!nodes.length) return;
  try { if (!window.mermaid) await addScript(LIB.mermaid); } catch {
    nodes.forEach(n => n.classList.add("cl-mermaid-error"));
    return;
  }
  if (!mermaidReady) {
    window.mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "neutral", fontFamily: "Pretendard Variable, Pretendard, sans-serif" });
    mermaidReady = true;
  }
  for (const n of nodes) {
    const src = n.textContent;
    try {
      // 그림 글씨는 mermaid 의 strict 모드가 거른다 — SVG 를 DOMPurify 로 다시 거르면 글자 칸(foreignObject)이 지워져 글씨가 사라진다
      const { svg } = await window.mermaid.render(`cl-mm-${Math.random().toString(36).slice(2)}`, src);
      n.innerHTML = svg;
    } catch (e) {
      n.textContent = "";
      const pre = document.createElement("pre");
      pre.className = "cl-mermaid-error";
      pre.textContent = `그림을 그리지 못했습니다: ${(e && e.message) || e}\n\n${src}`;
      n.appendChild(pre);
    }
  }
}

function buildToc(toc, art) {
  if (spy) { spy.disconnect(); spy = null; }
  const hs = [...art.querySelectorAll("h2, h3")];
  if (!hs.length) { toc.innerHTML = '<span class="fl-muted">절이 없는 짧은 장입니다.</span>'; return; }
  toc.innerHTML = hs.map(hd => `<a href="#${hd.id}" data-target="${hd.id}" class="${hd.tagName === "H3" ? "cl-toc-h3" : ""}">${escHtml(hd.textContent)}</a>`).join("");
  toc.querySelectorAll("a[data-target]").forEach(a => a.addEventListener("click", e => {
    e.preventDefault();   // 앱의 주소(#화면키)를 건드리지 않고 그 절로만 내려간다
    document.getElementById(a.dataset.target)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }));
  if (!("IntersectionObserver" in window)) return;
  spy = new IntersectionObserver(entries => {
    for (const en of entries) {
      if (en.isIntersecting) toc.querySelectorAll("a").forEach(a => a.classList.toggle("is-on", a.dataset.target === en.target.id));
    }
  }, { rootMargin: "-80px 0px -70% 0px" });
  hs.forEach(hd => spy.observe(hd));
}

// ── 화면 진입 ───────────────────────────────────────────────────────
export function onConceptLearnViewActivated(view) {
  if (view === "learn-dev") { const el = document.getElementById("cl-dev"); if (el) clRenderBranch(el, "dev"); return; }
  if (view === "learn-python") { const el = document.getElementById("cl-python"); if (el) clRenderBranch(el, "python"); return; }
  if (view === "learn-part") {
    const el = document.getElementById("cl-part");
    if (!el) return;
    const want = pendingPart || (history.state && history.state.clPart) || tabStore.get(PART_KEY);
    pendingPart = null;
    clRenderPart(el, want);
    return;
  }
  if (view === "learn-home") {
    const el = document.getElementById("cl-home");
    if (el) renderHome(el);
    return;
  }
  if (view !== "learn-page") return;
  const el = document.getElementById("cl-page");
  if (!el) return;
  const want = pending || { slug: tabStore.get(NOW_KEY) || keepStore.get(LAST_KEY), h: "" };
  pending = null;
  if (!want.h && want.slug && el.dataset.slug === want.slug && el.querySelector(".cl-prose")) return;   // 같은 장으로 돌아오면 다시 받지 않는다(읽던 자리)
  renderPage(el, want.slug, want.h);
}
