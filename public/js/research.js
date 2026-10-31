/* 투자 정보 리서치 — 수집 자료 검색(공시 · 정책뉴스 · 언론사 기사) + 종목 시간표 (2026-10-06)
 *
 * 화면 설계 결정(Figma 「투자 정보 리서치 — 공시 · 뉴스 찾기」 · 결정 기록 2026-10-05):
 *   안 B + C 융합 · 해석 1 — 한 화면. 평소엔 찾기 + 거름 칸(종류 · 종목 · 주제 · 기간 · 차례)의 목록이고,
 *   거름 칸에서 종목 하나를 고르면 같은 자리가 그 종목의 공시 · 기사 · 일정(주주총회 · 배당 · 실적)을 섞은
 *   날짜 한 줄(시간표)로 바뀐다(「보기 — 목록 · 시간표」). 처음 차례는 낱말이 있으면 관련도순 · 없으면 최신순
 *   (최신순만 쓰면 오늘 언론사 기사가 위를 덮는다). 언론사 기사는 원문 링크만 · 출처 표시를 결과마다.
 * DF-61 — 옛 화면(강사님 agent.js)은 「AI RAG로 검색」 이라 적고 수집 기사 표를 글자로 찾아 5건을 돌려줬다.
 *   이 화면은 AI 가 답을 쓰지 않는다(근거를 단 답은 「AI 투자 상담」 · js/kbchat.js). 찾는 것은 수집기가 매일 12:30 에
 *   다시 짓는 검색 색인(공시 77만 · 정책뉴스 3만 · 언론사 기사 제목)이다.
 * 2026-10-17 고침(Figma 같은 파일 03-2 — 설계 A · 세 안 공통 · 모의투자 점검 L4 · L11):
 *   첫 목록은 「투자 관련만」(서버 tagged — 공시 + 종목 · 주제 이름표가 붙은 뉴스) · 스위치 「이름표 없는 기사까지 보기 (n건 숨김)」
 *   (n 은 서버 facets.untagged) · 같은 제목은 한 줄로 · 제목이 사이트 이름뿐인 기사는 목록 끝에 모음(판단은 js/researchrows.js) ·
 *   종목 칸은 찾기 줄로(낱말 칸 옆 · 사용자 결정) — Enter · 「검색」 이 제안 목록을 기다리지 않고 바로 종목을 찾는다.
 * 읽는 API: GET /api/data/search(API-DATA-03 · source · facets · tagged) · /api/calendar/events(종목 일정 · API-CAL-02)
 *           GET /api/stocks/search(종목 이름 → 코드)
 */
import { api, escHtml } from "/js/common.js";
import { groupResearchRows, researchSwitchText, resolveStockQuery } from "/js/researchrows.js";

const VIEW = "agent-news";
//: 출처 → [이름, 색 이름] — 서버 data_search.SOURCES 와 같은 셋
const SOURCES = {
  dart: ["공시", "dart"],
  policy_news: ["정책뉴스", "policy"],
  gdelt: ["언론사 기사", "press"],
};
//: 주제 이름표 — 수집기 이름표(collector/tagging.py TOPICS)의 스물하나. 자주 쓰는 것을 앞에(나머지는 「더 보기」)
const TOPICS = ["실적", "공급계약", "증자", "배당", "지분", "자기주식", "합병·분할", "주주총회", "금리",
  "정기보고서", "감자", "사채", "주식분할", "지배구조", "투자·출자", "소송·제재", "거래정지·상장", "임상·기술",
  "기업설명회", "회계·감사", "환율"];
const TOPICS_SHOWN = 9;
//: 공시 유형 글자(DART pblntf_ty) → 이름
const DTYPES = { A: "정기공시", B: "주요사항보고", C: "발행공시", D: "지분공시", E: "기타공시", F: "외부감사관련",
  G: "펀드공시", H: "자산유동화", I: "거래소공시", J: "공정위공시" };
//: 기간(오늘부터 거슬러 며칠) — 목록 · 시간표가 고를 수 있는 것
const PERIODS = { "1w": ["1주", 7], "1m": ["1달", 31], "3m": ["3달", 92], "6m": ["6달", 183], "1y": ["1년", 366], all: ["전체", 0] };
const LIST_PERIODS = ["1w", "1m", "3m", "1y", "all"];
const TL_PERIODS = ["1m", "6m", "1y"];
const PAGE = 20;                                  // 목록 한 번에 — 「더 보기」 로 이어 받는다
const TL_PAGE = 100;                              // 시간표 출처마다 한 번에(서버 상한 100)
const TL_AHEAD = 60;                              // 시간표에 넣는 앞으로의 일정(오늘부터 며칠 뒤까지)
const WEEK = "일월화수목금토";

const S = {
  q: "", source: "", symbol: "", symbolName: "", topic: "", period: "1m", tlPeriod: "6m", sort: "",   // sort "" = 자동
  view: "list", tlKinds: new Set(["disclosure", "news", "event"]), topicsOpen: false,
  tagged: true,                                   // 첫 목록은 「투자 관련만」(2026-10-17 설계 A) — 스위치로 이름표 없는 기사까지
  items: [], total: 0, capped: false, facets: null, untagged: null, offset: 0, loading: false, error: "", hint: "",
  tl: null,                                       // 시간표 { disc, news, events, totals, offsets, error }
};
let seq = 0;                                      // 늦게 온 응답이 새 조건의 결과를 덮지 않게
let suggestTimer = 0;

// ── 도구 ──────────────────────────────────────────────────────────────
function todayIso() {
  const p = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date());
  const g = t => p.find(x => x.type === t).value;
  return `${g("year")}-${g("month")}-${g("day")}`;
}
function addDays(s, n) { const d = new Date(`${s}T12:00:00Z`); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); }
function dayOf(v) { return String(v || "").slice(0, 10); }
function shortDay(v) {
  const d = dayOf(v);
  if (!d) return "";
  const wd = WEEK[new Date(`${d}T12:00:00Z`).getUTCDay()];
  return `${d.slice(0, 4) === todayIso().slice(0, 4) ? d.slice(5) : d} (${wd})`;
}
function timeOf(v) { const m = String(v || "").match(/T(\d{2}:\d{2})/); return m && m[1] !== "00:00" ? m[1] : ""; }
function num(n) { return Number(n || 0).toLocaleString("ko-KR"); }
function won(v) {
  const n = Number(String(v ?? "").replace(/,/g, ""));
  if (!Number.isFinite(n) || String(v ?? "") === "") return "";
  const a = Math.abs(n);
  if (a >= 1e12) return `${(n / 1e12).toFixed(1)}조원`;
  if (a >= 1e8) return `${num(Math.round(n / 1e8))}억원`;
  return `${num(n)}원`;
}
function safeUrl(u) { return /^https?:\/\//i.test(u || "") ? u : ""; }
function fromDate(key) { const days = PERIODS[key][1]; return days ? addDays(todayIso(), -days) : ""; }
function sortNow() { return S.sort || (S.q ? "relevance" : "date"); }   // 결정 — 낱말이 있으면 관련도순

function root() {
  const view = document.querySelector(`.view[data-view="${VIEW}"]`);
  if (!view) return null;
  let r = view.querySelector(".rs-root");
  if (!r) { r = document.createElement("div"); r.className = "rs-root"; view.appendChild(r); }
  return r;
}

// ── 자료 ──────────────────────────────────────────────────────────────
function listParams(offset) {
  const p = new URLSearchParams({ limit: String(PAGE), offset: String(offset), sort: sortNow() });
  if (S.q) p.set("q", S.q);
  if (S.source) p.set("source", S.source);
  if (S.symbol) p.set("symbol", S.symbol);
  if (S.topic) p.set("topic", S.topic);
  if (S.tagged) p.set("tagged", "true");
  const from = fromDate(S.period);
  if (from) p.set("from", from);
  if (!offset) p.set("facets", "true");            // 종류 칸의 개수 · 숨긴 수는 첫 쪽에서만(같은 조건이면 그대로)
  return p.toString();
}

async function loadList(more = false) {
  const my = ++seq;
  S.loading = true; S.error = ""; S.hint = "";
  if (!more) { S.offset = 0; S.items = []; }
  paintResults();
  try {
    // 주소는 「/api/data/search?」 글자로 시작하게 — 화면 스캐너(scripts/view_scan.py)가 이 글자로 「화면 ↔ API」 를 잇는다
    const r = await api(`/api/data/search?${listParams(more ? S.offset : 0)}`);
    if (my !== seq) return;
    S.items = more ? [...S.items, ...(r.items || [])] : (r.items || []);
    S.total = r.total || 0; S.capped = Boolean(r.total_capped);
    if (r.facets) { S.facets = r.facets.source; S.untagged = r.facets.untagged || null; }
    S.offset = S.items.length;
  } catch (err) {
    if (my !== seq) return;
    S.error = err.message; S.hint = err.detail?.hint || "";
  }
  S.loading = false;
  paintFilters(); paintResults();
}

async function loadTimeline(more = false) {
  const my = ++seq;
  const from = fromDate(S.tlPeriod);
  const to = addDays(todayIso(), TL_AHEAD);
  const prev = more && S.tl ? S.tl : null;
  S.loading = true; S.error = ""; S.hint = "";
  if (!prev) S.tl = null;
  paintResults();
  const q = S.q ? `&q=${encodeURIComponent(S.q)}` : "";
  const off = prev ? prev.offsets : { disc: 0, news: 0 };
  const want = (k, cond) => S.tlKinds.has(k) && cond;
  try {
    const [disc, news, ev] = await Promise.all([
      want("disclosure", !prev || prev.totals.disc > off.disc)
        ? api(`/api/data/search?symbol=${S.symbol}&source=dart&from=${from}${q}&sort=date&limit=${TL_PAGE}&offset=${off.disc}`) : null,
      want("news", !prev || prev.totals.news > off.news)
        ? api(`/api/data/search?symbol=${S.symbol}&kind=news&from=${from}${q}&sort=date&limit=${TL_PAGE}&offset=${off.news}`) : null,
      want("event", !prev) ? api(`/api/calendar/events?from=${from}&to=${to}&kind=all&symbol=${S.symbol}&limit=500`, { redirectOnUnauthorized: false }) : null,
    ]);
    if (my !== seq) return;
    const tl = prev || { disc: [], news: [], events: [], totals: { disc: 0, news: 0, events: 0 }, offsets: { disc: 0, news: 0 } };
    if (disc) { tl.disc.push(...(disc.items || [])); tl.totals.disc = disc.total || 0; tl.offsets.disc = tl.disc.length; }
    if (news) { tl.news.push(...(news.items || [])); tl.totals.news = news.total || 0; tl.offsets.news = tl.news.length; }
    if (ev) {
      // 일정에는 낱말 찾기가 없다 — 낱말이 있으면 일정 이름에 든 것만
      tl.events = (ev.events || []).filter(e => !S.q || S.q.split(/\s+/).every(w => (e.title || "").includes(w)));
      tl.totals.events = tl.events.length;
    }
    S.tl = tl;
  } catch (err) {
    if (my !== seq) return;
    S.error = err.message; S.hint = err.detail?.hint || "";
  }
  S.loading = false;
  paintResults();
}

function reload() { return S.view === "timeline" && S.symbol ? loadTimeline() : loadList(); }

/** 지금 조건의 정확한 건수 — 줄 수는 서버가 1만에서 끊는다(COUNT_CAP). 종류 칸 개수(facets)는 같은 조건에서 출처마다
 *  센 정확한 수라, 있으면 그것을 쓴다(전체 = 셋의 합 · 하나를 골랐으면 그 수). */
function exactTotal() {
  const f = S.facets;
  if (!f) return null;
  return S.source ? (f[S.source] ?? null) : Object.values(f).reduce((a, n) => a + n, 0);
}

// ── 거름 칸 ────────────────────────────────────────────────────────────
function chipBtn(attr, value, label, on, extra = "") {
  return `<button type="button" class="rs-chip ${on ? "on" : ""}" ${attr}="${escHtml(value)}" aria-pressed="${on}" ${extra}>${escHtml(label)}</button>`;
}

function filtersHtml() {
  const f = S.facets || {};
  const all = Object.values(f).reduce((a, n) => a + n, 0);
  const kinds = [["", "전체", S.facets ? all : null], ...Object.entries(SOURCES).map(([k, [label]]) => [k, label, S.facets ? (f[k] || 0) : null])]
    .map(([k, label, n]) => `<button type="button" class="rs-kind ${S.source === k ? "on" : ""}" data-source="${k}" aria-pressed="${S.source === k}">
      <span>${escHtml(label)}</span><span class="rs-count">${n === null ? "—" : num(n)}</span></button>`).join("");
  // 종목 칸은 찾기 줄로 옮겼다(2026-10-17 사용자 결정) — 거름 칸에는 고른 종목 칩(풀기 ✕)만
  const sym = S.symbol
    ? `<div class="rs-sym-chip"><span>${escHtml(S.symbolName || S.symbol)} ${escHtml(S.symbol)}</span><button type="button" class="rs-sym-x" aria-label="종목 거름 풀기">✕</button></div>`
    : `<p class="q-muted rs-sym-hint">찾기 줄의 종목 칸에서 고릅니다.</p>`;
  const tl = S.view === "timeline" && S.symbol;
  const topics = (S.topicsOpen ? TOPICS : TOPICS.slice(0, TOPICS_SHOWN)).map(t => chipBtn("data-topic", t, t, S.topic === t)).join("")
    + `<button type="button" class="rs-more-topics">${S.topicsOpen ? "접기" : `더 보기 ${TOPICS.length - TOPICS_SHOWN}`}</button>`;
  const periods = (tl ? TL_PERIODS : LIST_PERIODS).map(k => chipBtn("data-period", k, PERIODS[k][0], (tl ? S.tlPeriod : S.period) === k)).join("");
  return `
    ${tl ? "" : `<div class="rs-sec"><h4>종류</h4><div class="rs-kinds">${kinds}</div></div>`}
    <div class="rs-sec"><h4>종목</h4>${sym}</div>
    ${S.symbol ? `<div class="rs-sec"><h4>보기</h4><div class="rs-chips">${chipBtn("data-rs-view", "list", "목록", S.view === "list")}${chipBtn("data-rs-view", "timeline", "시간표", S.view === "timeline")}</div></div>` : ""}
    ${tl ? `<div class="rs-sec"><h4>종류</h4><div class="rs-chips">${[["disclosure", "공시"], ["news", "기사"], ["event", "일정"]].map(([k, l]) => chipBtn("data-tlkind", k, l, S.tlKinds.has(k))).join("")}</div></div>`
      : `<div class="rs-sec"><h4>주제</h4><div class="rs-chips">${topics}</div></div>`}
    <div class="rs-sec"><h4>기간</h4><div class="rs-chips">${periods}</div></div>
    ${tl ? "" : `<div class="rs-sec"><h4>차례</h4><div class="rs-chips">${chipBtn("data-sort", "date", "최신순", sortNow() === "date")}${chipBtn("data-sort", "relevance", "관련도순", sortNow() === "relevance", S.q ? "" : 'disabled title="낱말을 넣으면 고를 수 있습니다"')}</div></div>`}`;
}

function paintFilters() {
  const box = root()?.querySelector(".rs-filters-body");
  if (!box) return;
  box.innerHTML = filtersHtml();
  box.querySelectorAll("[data-source]").forEach(b => b.addEventListener("click", () => { S.source = b.dataset.source; loadList(); }));
  box.querySelectorAll("[data-topic]").forEach(b => b.addEventListener("click", () => { S.topic = S.topic === b.dataset.topic ? "" : b.dataset.topic; paintFilters(); loadList(); }));
  box.querySelector(".rs-more-topics")?.addEventListener("click", () => { S.topicsOpen = !S.topicsOpen; paintFilters(); });
  box.querySelectorAll("[data-period]").forEach(b => b.addEventListener("click", () => {
    if (S.view === "timeline" && S.symbol) S.tlPeriod = b.dataset.period; else S.period = b.dataset.period;
    paintFilters(); reload();
  }));
  box.querySelectorAll("[data-sort]").forEach(b => b.addEventListener("click", () => { S.sort = b.dataset.sort; paintFilters(); loadList(); }));
  // data-view 는 앱 전체가 화면 이름으로 쓰는 속성이라(메뉴 · 화면 칸) 이 단추는 data-rs-view 로 — 겹치면 화면으로 읽힌다
  box.querySelectorAll("[data-rs-view]").forEach(b => b.addEventListener("click", () => { S.view = b.dataset.rsView; paintAll(); reload(); }));
  box.querySelectorAll("[data-tlkind]").forEach(b => b.addEventListener("click", () => {
    const k = b.dataset.tlkind;
    if (S.tlKinds.has(k) && S.tlKinds.size > 1) S.tlKinds.delete(k); else S.tlKinds.add(k);
    paintFilters(); loadTimeline();
  }));
  box.querySelector(".rs-sym-x")?.addEventListener("click", () => clearResearchSymbol());
}

// ── 종목 칸(찾기 줄) ──────────────────────────────────────────────────────
/** 국내 종목 후보 — 이름 · 코드로 찾아 6자리 코드만(제안 목록 · Enter · 「검색」 이 함께 쓴다) · 찾기가 실패하면 null */
async function fetchResearchStocks(q) {
  try {
    const r = await api(`/api/stocks/search?q=${encodeURIComponent(q)}`, { redirectOnUnauthorized: false });
    return (r.results || []).map(x => ({ code: String(x.symbol || "").replace(/\.(KS|KQ)$/i, ""), name: x.name || "", market: x.exchange || "" }))
      .filter(x => /^[0-9A-Z]{6}$/.test(x.code)).slice(0, 8);
  } catch (err) {
    // 「찾지 못함」 은 서버가 200 · 빈 목록으로 준다(DF-125 고침 · #257 — 해외 자동완성의 400 을 서버가 「없음」 으로 바꿈).
    // 여기로 오는 오류(502 · 연결 끊김)는 진짜 찾기 실패라 「없음」 으로 덮지 않는다(2026-10-17 손 시험 · 옛 우회 지움).
    return null;
  }
}

/** 제안 목록을 그린다 — 줄을 누르거나(Enter) 고르면 그 종목 · ↑ ↓ 로 옮기고 Esc 로 닫는다 */
function showResearchSuggest(input, rows) {
  const list = input.parentElement.querySelector(".rs-suggest");
  list.innerHTML = rows === null
    ? `<li class="rs-suggest-none q-muted">종목 찾기가 잠시 안 됩니다 — 다시 눌러 보세요</li>`
    : rows.length
      ? rows.map(x => `<li role="option" tabindex="-1" data-code="${escHtml(x.code)}" data-name="${escHtml(x.name)}"><strong>${escHtml(x.name)}</strong> <span class="q-muted">${escHtml(x.code)} · ${escHtml(x.market)}</span></li>`).join("")
      : `<li class="rs-suggest-none q-muted">국내 상장 종목에서 찾지 못했습니다</li>`;
  list.hidden = false;
  input.setAttribute("aria-expanded", "true");
  const items = [...list.querySelectorAll("li[data-code]")];
  items.forEach((li, i) => {
    li.addEventListener("click", () => pickSymbol(li.dataset.code, li.dataset.name));
    li.addEventListener("keydown", e => {
      if (e.key === "Enter") { e.preventDefault(); li.click(); }
      if (e.key === "ArrowDown") { e.preventDefault(); (items[i + 1] || li).focus(); }
      if (e.key === "ArrowUp") { e.preventDefault(); (items[i - 1] || input).focus(); }
      if (e.key === "Escape") { e.preventDefault(); hideResearchSuggest(input); input.focus(); }
    });
  });
}

function hideResearchSuggest(input) {
  const list = input?.parentElement?.querySelector(".rs-suggest");
  if (list) list.hidden = true;
  input?.setAttribute("aria-expanded", "false");
}

/** 치는 동안의 제안 목록(0.25초 쉼 뒤) — 이름 · 코드로 찾아 국내 종목(6자리)만 보인다 */
async function suggest(input) {
  const q = input.value.trim();
  if (!q) { hideResearchSuggest(input); return; }
  const rows = await fetchResearchStocks(q);
  if (input.value.trim() !== q) return;            // 그사이 더 쳤다
  showResearchSuggest(input, rows);
}

/** Enter · 「검색」 — 제안 목록을 기다리지 않고 바로 찾는다(점검 <표 2> 라 · 마). 이름 · 코드가 정확히 같은 것 하나면 그 종목으로
 *  바로 · 여럿이면 제안 목록을 열고 첫 줄에 초점 · 없으면 「찾지 못했습니다」(판단은 researchrows.js). 돌려주는 값: 판단 종류 · "stale". */
async function findResearchStock(input, { keepQuery = false } = {}) {
  clearTimeout(suggestTimer);                      // 쉬는 중인 제안 목록 부르기는 버린다(같은 글을 두 번 찾지 않게)
  const q = input.value.trim();
  const rows = q ? await fetchResearchStocks(q) : [];
  if (input.value.trim() !== q) return "stale";
  if (rows === null) { showResearchSuggest(input, null); return "failed"; }
  const got = resolveStockQuery(rows, q);
  if (got.kind === "pick") { pickSymbol(got.code, got.name, { keepQuery }); return "pick"; }
  if (got.kind === "empty") { hideResearchSuggest(input); return "empty"; }
  showResearchSuggest(input, rows);
  if (got.kind === "list") input.parentElement.querySelector(".rs-suggest li[data-code]")?.focus();
  return got.kind;
}

/** 종목 칸 키 — Enter 는 「검색」 과 같은 길(낱말 · 종목을 함께 · 제안 목록을 기다리지 않음) · ↓ 는 제안 목록으로 · Esc 는 닫기 */
function onResearchSymbolKey(e) {
  const input = e.currentTarget;
  if (e.key === "Enter") { e.preventDefault(); input.form?.requestSubmit(); }
  if (e.key === "ArrowDown") {
    const first = input.parentElement.querySelector(".rs-suggest:not([hidden]) li[data-code]");
    if (first) { e.preventDefault(); first.focus(); }
  }
  if (e.key === "Escape") hideResearchSuggest(input);
}

/** 종목 칸 글을 지금 고른 종목에 맞춘다 — 고르면 그 이름 · 풀면 빈칸 */
function syncResearchSymbolInput() {
  const input = root()?.querySelector(".rs-sym-q");
  if (input) input.value = S.symbol ? (S.symbolName || S.symbol) : "";
}

/** 종목 거름 풀기(거름 칸 칩 ✕ · 종목 칸을 비우고 검색 · 칸의 ✕) — 목록으로 돌아간다 · 낱말 · 다른 거름은 그대로 */
function clearResearchSymbol() {
  S.symbol = ""; S.symbolName = ""; S.view = "list";
  syncResearchSymbolInput();
  paintAll(); loadList();
}

/** 찾기 줄의 종목 칸 묶기 — 치는 동안 제안 목록(0.25초 쉼) · 키 · 칸의 ✕ · 칸 밖으로 나가면 목록 닫기 */
function wireResearchBar(r) {
  const input = r.querySelector(".rs-sym-q");
  input.addEventListener("input", () => { clearTimeout(suggestTimer); suggestTimer = setTimeout(() => suggest(input), 250); });
  input.addEventListener("keydown", onResearchSymbolKey);
  input.addEventListener("search", () => { if (!input.value.trim() && S.symbol) clearResearchSymbol(); });   // 칸의 ✕
  const box = input.parentElement;
  box.addEventListener("focusout", e => { if (!box.contains(e.relatedTarget)) hideResearchSuggest(input); });
  // 「검색」 단추로 연 목록은 초점이 이미 칸 밖이라 초점 잃음으로는 못 닫는다 — 칸 밖을 누르면 닫는다(손 시험에서 찾음)
  document.addEventListener("click", e => { if (!box.contains(e.target)) hideResearchSuggest(input); });
}

/** 종목 하나를 고르면 같은 자리가 시간표로 바뀐다(결정 해석 1). 제안 목록에서 고르면 그 종목 전부로 시작한다 — 찾던 낱말이
 *  남으면(「반도체」 로 찾다 삼성전기를 누름) 공시 0 · 기사 1 처럼 비어 보인다(2026-10-06 화면 확인). 낱말은 다시 넣어 좁힌다.
 *  「검색」 이 낱말 칸 · 종목 칸을 함께 보낼 때만(keepQuery) 친 낱말을 남긴다(2026-10-17 — 두 칸이 한 찾기 줄에 있다). */
function pickSymbol(code, name, { keepQuery = false } = {}) {
  S.symbol = code; S.symbolName = name || ""; S.view = "timeline";
  if (!keepQuery) {
    S.q = "";
    const input = root()?.querySelector(".rs-q");
    if (input) input.value = "";
  }
  const symInput = root()?.querySelector(".rs-sym-q");
  hideResearchSuggest(symInput);
  syncResearchSymbolInput();
  paintAll(); loadTimeline();
  if (!S.symbolName) {                             // 이름표에는 코드만 있을 때 — 이름을 채운다(실패해도 코드로 보인다)
    api(`/api/stocks/search?q=${encodeURIComponent(code)}`, { redirectOnUnauthorized: false }).then(r => {
      const hit = (r.results || []).find(x => String(x.symbol || "").replace(/\.(KS|KQ)$/i, "") === code);
      if (hit && S.symbol === code) { S.symbolName = hit.name || ""; syncResearchSymbolInput(); paintFilters(); paintResults(); }
    }).catch(() => {});
  }
}

// ── 결과 ──────────────────────────────────────────────────────────────
function keyNumbersHtml(k) {
  if (!k) return "";
  if (k.dps !== undefined) {
    return `<p class="rs-key">1주당 ${escHtml(won(k.dps))}${k.record_date ? ` · 기준일 ${escHtml(k.record_date)}` : ""}${k.div_kind ? ` · ${escHtml(k.div_kind)}` : ""}</p>`;
  }
  const parts = [["revenue", "매출액"], ["operating_income", "영업이익"], ["net_income", "당기순이익"]]
    .filter(([key]) => k[key] !== undefined && k[key] !== null).map(([key, label]) => `${label} ${won(k[key])}`);
  if (!parts.length) return "";
  return `<p class="rs-key">${escHtml(parts.join(" · "))} <span class="q-muted">(${k.fs_div === "CFS" ? "연결" : "별도"}${k.same_filing ? "" : " · 같은 기간의 가장 최근 판"})</span></p>`;
}

/** 같은 제목 묶음 — 「같은 제목 n건」 을 펴면 묶인 기사마다 시각 · 게시처 · 원문(쪽 넘기기는 그대로 · 2026-10-17 설계 A) */
function sameTitleHtml(it, same) {
  if (!same.length) return "";
  const all = [it, ...same];
  return `<details class="rs-same"><summary>같은 제목 ${num(all.length)}건</summary><ul>${all.map(x => {
    const url = safeUrl(x.url);
    const where = [shortDay(x.published) + (timeOf(x.published) ? ` ${timeOf(x.published)}` : ""),
      (x.extra || {}).publisher || SOURCES[x.source]?.[0] || ""].filter(Boolean).join(" · ");
    return `<li>${escHtml(where)}${url ? ` · <a href="${escHtml(url)}" target="_blank" rel="noopener noreferrer">원문 ›</a>` : ""}</li>`;
  }).join("")}</ul></details>`;
}

/** 제목이 사이트 이름뿐인 기사 묶음(서버 site_name_title · L11) — 받은 목록 끝에 게시처마다 접힌 한 줄 */
function siteGroupHtml(g) {
  const lines = g.items.map(x => {
    const url = safeUrl(x.url);
    const at = shortDay(x.published) + (timeOf(x.published) ? ` ${timeOf(x.published)}` : "");
    return `<li>${escHtml(at)}${url ? ` · <a href="${escHtml(url)}" target="_blank" rel="noopener noreferrer">기사 원문 ›</a>` : ""}</li>`;
  }).join("");
  // 수는 받은 줄 가운데 몇 건인지다(전체 수가 아님 — 「더 보기」 로 더 받으면 는다)
  return `<details class="rs-sitegroup"><summary>제목에 사이트 이름만 있는 기사 — 「${escHtml(g.title)}」${g.publisher ? ` · ${escHtml(g.publisher)}` : ""} · 받은 ${num(g.items.length)}건</summary>
    <p class="q-muted">제목만으로는 무슨 기사인지 알 수 없어 목록 끝에 모았습니다. 원문을 열어 확인하세요.</p><ul>${lines}</ul></details>`;
}

function itemHtml(it, same = []) {
  const [label, tone] = SOURCES[it.source] || [it.source, "dart"];
  const ex = it.extra || {};
  const meta = [shortDay(it.published) + (timeOf(it.published) ? ` ${timeOf(it.published)}` : "")];
  if (it.source === "dart") {
    if (it.corp_name) meta.push(it.corp_name);
    if (ex.pblntf_ty && DTYPES[ex.pblntf_ty]) meta.push(DTYPES[ex.pblntf_ty]);
    if (ex.flr_nm && ex.flr_nm !== it.corp_name) meta.push(`제출 ${ex.flr_nm}`);
  } else if (ex.publisher) {
    meta.push(ex.publisher);
  }
  const syms = (it.tags?.symbol || []).slice(0, 3).map(code =>
    `<button type="button" class="rs-tagbtn" data-pick="${escHtml(code)}" data-pick-name="${escHtml(code === it.stock_code ? it.corp_name : "")}">종목 ${escHtml(code === it.stock_code && it.corp_name ? it.corp_name : code)}</button>`);
  const topics = (it.tags?.topic || []).slice(0, 3).map(t => `<button type="button" class="rs-tagbtn" data-topic-tag="${escHtml(t)}">주제 ${escHtml(t)}</button>`);
  const sum = it.summary && !it.title.includes(it.summary.replace(/^\(|\)$/g, "")) ? `<p class="rs-sum">${escHtml(it.summary)}</p>` : "";
  const url = safeUrl(it.url);
  const linkLabel = it.source === "dart" ? "공시 원문" : "기사 원문";
  return `<article class="rs-item">
    <div class="rs-meta"><span class="rs-tag rs-tag--${tone}">${escHtml(label)}</span><span>${escHtml(meta.filter(Boolean).join(" · "))}</span></div>
    <h3 class="rs-title">${url ? `<a href="${escHtml(url)}" target="_blank" rel="noopener noreferrer">${escHtml(it.title)}</a>` : escHtml(it.title)}</h3>
    ${syms.length || topics.length ? `<div class="rs-tags">${[...syms, ...topics].join("")}</div>` : ""}
    ${sum}${keyNumbersHtml(it.key_numbers)}
    ${ex.attribution ? `<p class="rs-attr">출처: ${escHtml(ex.attribution)}</p>` : ""}
    ${url ? `<a class="rs-link" href="${escHtml(url)}" target="_blank" rel="noopener noreferrer">${linkLabel} ›</a>` : ""}
    ${sameTitleHtml(it, same)}
  </article>`;
}

function conditionText() {
  const parts = [];
  if (S.q) parts.push(`낱말 「${S.q}」`);
  if (S.symbol) parts.push(`종목 ${S.symbolName || S.symbol}`);
  if (S.view === "timeline" && S.symbol) {
    parts.push(PERIODS[S.tlPeriod][0], [["disclosure", "공시"], ["news", "기사"], ["event", "일정"]]
      .filter(([k]) => S.tlKinds.has(k)).map(([, l]) => l).join(" · "));   // 누른 차례가 아니라 늘 같은 차례로
    return parts.join(" · ");
  }
  if (S.source) parts.push(SOURCES[S.source][0]);
  if (S.topic) parts.push(`주제 「${S.topic}」`);
  parts.push(PERIODS[S.period][0], sortNow() === "relevance" ? "관련도순" : "최신순");
  if (S.tagged && S.source !== "dart") parts.push("투자 관련만");   // 공시만 볼 때는 거름이 하는 일이 없다
  return parts.join(" · ");
}

/** 스위치 「이름표 없는 기사까지 보기 (n건 숨김)」 — 목록일 때만 · n 은 서버 facets.untagged · 숨길 것이 없으면 감춘다 */
function switchHtml() {
  if (S.view === "timeline" && S.symbol) return "";
  if (S.source === "dart" || !S.untagged) return "";
  const { n, text } = researchSwitchText(S.tagged, S.untagged);
  if (!n) return "";
  return `<button type="button" class="rs-switch" role="switch" aria-checked="${!S.tagged}"><span class="rs-switch-knob" aria-hidden="true"></span>${escHtml(text)}</button>`;
}

function listHtml() {
  if (S.error) {
    return `<p class="dh-alert q-tone--stale">찾지 못했습니다 — ${escHtml(S.error)}${S.hint ? `<br><span class="q-muted">${escHtml(S.hint)}</span>` : ""}</p>`;
  }
  if (S.loading && !S.items.length) return `<p class="q-muted">찾는 중…</p>`;
  if (!S.items.length) return `<p class="q-muted">고른 조건의 자료가 없습니다 — 기간을 넓히거나 낱말 · 주제를 바꿔 보세요.</p>`;
  const exact = exactTotal();
  const more = S.items.length < S.total
    ? `<button type="button" class="btn-secondary rs-more">더 보기 (${num(S.items.length)} / ${num(exact ?? S.total)}${exact === null && S.capped ? "+" : ""})</button>` : "";
  // 같은 제목은 한 줄로 · 제목이 사이트 이름뿐인 기사는 끝에(판단은 researchrows.js — 받은 줄 전부를 다시 묶는다)
  const g = groupResearchRows(S.items);
  const sites = g.siteGroups.length ? `<div class="rs-sitegroups">${g.siteGroups.map(siteGroupHtml).join("")}</div>` : "";
  return `<div class="rs-list">${g.rows.map(row => itemHtml(row.it, row.same)).join("")}</div>${sites}${more}`;
}

function tlItemHtml(x) {
  if (x.type === "event") {
    const e = x.ev;
    return `<li class="rs-tl-item"><div class="rs-meta"><span class="rs-tag rs-tag--event">일정</span>
        <span>${escHtml([e.kind_label, e.time, e.confidence_label].filter(Boolean).join(" · "))}</span></div>
      <div class="rs-title">${escHtml(e.title)}</div>${e.detail ? `<p class="rs-sum">${escHtml(e.detail)}</p>` : ""}</li>`;
  }
  const it = x.it;
  const [label, tone] = SOURCES[it.source] || [it.source, "dart"];
  const url = safeUrl(it.url);
  const ex = it.extra || {};
  const meta = [timeOf(it.published), it.source === "dart" ? (DTYPES[ex.pblntf_ty] || "") : (ex.publisher || "")].filter(Boolean);
  return `<li class="rs-tl-item"><div class="rs-meta"><span class="rs-tag rs-tag--${tone}">${escHtml(label)}</span><span>${escHtml(meta.join(" · "))}</span></div>
      <div class="rs-title">${url ? `<a href="${escHtml(url)}" target="_blank" rel="noopener noreferrer">${escHtml(it.title)}</a>` : escHtml(it.title)}</div>
      ${keyNumbersHtml(it.key_numbers)}${ex.attribution ? `<p class="rs-attr">출처: ${escHtml(ex.attribution)}</p>` : ""}</li>`;
}

function timelineHtml() {
  if (S.error) return `<p class="dh-alert q-tone--stale">시간표를 만들지 못했습니다 — ${escHtml(S.error)}</p>`;
  const tl = S.tl;
  if (!tl) return `<p class="q-muted">${escHtml(S.symbolName || S.symbol)} 의 공시 · 기사 · 일정을 모으는 중…</p>`;
  const rows = [];
  if (S.tlKinds.has("disclosure")) rows.push(...tl.disc.map(it => ({ day: dayOf(it.published), at: it.published, type: "doc", it })));
  if (S.tlKinds.has("news")) rows.push(...tl.news.map(it => ({ day: dayOf(it.published), at: it.published, type: "doc", it })));
  if (S.tlKinds.has("event")) rows.push(...tl.events.map(ev => ({ day: ev.date, at: `${ev.date}T${ev.time || "00:00"}`, type: "event", ev })));
  rows.sort((a, b) => b.at.localeCompare(a.at));   // 앞으로의 일정이 맨 위 · 그다음 최근 것부터
  const today = todayIso();
  const counts = [S.tlKinds.has("disclosure") ? `공시 ${num(tl.disc.length)}${tl.totals.disc > tl.disc.length ? ` / ${num(tl.totals.disc)}` : ""}` : "",
    S.tlKinds.has("news") ? `기사 ${num(tl.news.length)}${tl.totals.news > tl.news.length ? ` / ${num(tl.totals.news)}` : ""}` : "",
    S.tlKinds.has("event") ? `일정 ${num(tl.events.length)}` : ""].filter(Boolean).join(" · ");
  if (!rows.length) return `<p class="q-muted">이 기간에 ${escHtml(S.symbolName || S.symbol)} 의 공시 · 기사 · 일정이 없습니다 — 기간을 넓혀 보세요.</p>`;
  const groups = [];
  for (const r of rows) { const last = groups[groups.length - 1]; if (last && last.day === r.day) last.rows.push(r); else groups.push({ day: r.day, rows: [r] }); }
  const more = (S.tlKinds.has("disclosure") && tl.totals.disc > tl.disc.length) || (S.tlKinds.has("news") && tl.totals.news > tl.news.length)
    ? `<button type="button" class="btn-secondary rs-tl-more">더 보기 — 공시 · 기사 ${TL_PAGE}건씩</button>` : "";
  return `<p class="q-muted rs-tl-count">${escHtml(counts)}</p>
    <ol class="rs-tl">${groups.map(g => `<li class="rs-tl-day ${g.day > today ? "rs-tl-day--ahead" : ""}"><div class="rs-tl-date">${escHtml(shortDay(g.day))}${g.day > today ? ` <span class="rs-ahead">예정</span>` : ""}</div>
      <ul>${g.rows.map(tlItemHtml).join("")}</ul></li>`).join("")}</ol>${more}`;
}

function paintResults() {
  const r = root();
  if (!r) return;
  const box = r.querySelector(".rs-results");
  const head = r.querySelector(".rs-cond");
  if (!box || !head) return;
  const tl = S.view === "timeline" && S.symbol;
  const exact = exactTotal();
  head.innerHTML = `${escHtml(conditionText())}${S.symbol ? ` <button type="button" class="sd-open-btn" data-hub-open="${escHtml(S.symbol)}" data-hub-name="${escHtml(S.symbolName || "")}">근거 서랍 →</button>` : ""}${tl ? "" : ` — <strong>${S.loading ? "…" : num(exact ?? S.total)}${exact === null && S.capped ? "+" : ""}건</strong>`}`;
  const sw = r.querySelector(".rs-switch-box");
  if (sw) {
    sw.innerHTML = switchHtml();
    sw.querySelector(".rs-switch")?.addEventListener("click", () => { S.tagged = !S.tagged; loadList(); });
  }
  box.innerHTML = tl ? timelineHtml() : listHtml();
  box.querySelector(".rs-more")?.addEventListener("click", () => loadList(true));
  box.querySelector(".rs-tl-more")?.addEventListener("click", () => loadTimeline(true));
  box.querySelectorAll("[data-pick]").forEach(b => b.addEventListener("click", () => pickSymbol(b.dataset.pick, b.dataset.pickName)));
  box.querySelectorAll("[data-topic-tag]").forEach(b => b.addEventListener("click", () => {
    S.topic = b.dataset.topicTag; S.view = "list"; paintAll(); loadList();
  }));
}

function paintAll() {
  const r = root();
  if (!r) return;
  const tl = S.view === "timeline" && S.symbol;
  const input = r.querySelector(".rs-q");
  if (input) input.placeholder = tl ? "낱말(비우면 그 종목 전부)" : "낱말 — 예: 반도체 · 유상증자 · 배당 (띄어 쓴 낱말은 모두 든 것만)";
  paintFilters(); paintResults();
}

/** 검색어를 비운 순간 — 낱말 조건을 빼고 차례를 자동으로 되돌려 다시 받는다. 이미 비어 있고 자동 차례면 다시 받지 않는다. */
function clearResearchQuery() {
  if (!S.q && S.sort !== "relevance") return;
  S.q = "";
  if (S.sort === "relevance") S.sort = "";
  paintFilters();
  reload();
}

function renderResearch() {
  const r = root();
  if (!r || r.querySelector(".rs-layout")) return;  // 다시 들어오면 고른 조건 · 결과를 그대로 둔다
  r.innerHTML = `<div class="dh-head"><div><h2>투자 정보 리서치</h2>
      <p class="q-muted">전자공시 공시 · 정책브리핑 정책뉴스 · 언론사 기사 제목을 낱말 · 종목 · 주제 · 기간으로 찾습니다. 종목을 고르면 그 종목의 공시 · 기사 · 일정을 날짜 한 줄로 봅니다.
        AI 가 답을 쓰는 화면이 아닙니다 — 법 · 규정 근거를 단 답은 「AI 투자 상담」 에서 물어보세요.</p></div></div>
    <div class="rs-layout">
      <details class="card rs-filters" open><summary>거름 칸</summary><div class="rs-filters-body"></div></details>
      <div class="card rs-main">
        <form class="rs-bar" role="search"><input type="search" class="input rs-q" aria-label="찾을 낱말" value="${escHtml(S.q)}">
          <div class="rs-sym-box"><input type="search" class="input rs-sym-q" placeholder="종목 — 이름 · 코드" aria-label="종목 이름이나 코드로 고르기"
            autocomplete="off" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="rs-suggest-list" value="${escHtml(S.symbol ? (S.symbolName || S.symbol) : "")}">
            <ul class="rs-suggest" id="rs-suggest-list" role="listbox" aria-label="종목 후보" hidden></ul></div>
          <button type="submit" class="btn-primary">검색</button></form>
        <div class="rs-cond-row"><p class="rs-cond q-muted"></p><div class="rs-switch-box"></div></div>
        <div class="rs-results"></div>
        <p class="q-up-note">자료는 수집기가 매일 12:30 에 받아 검색 색인을 다시 짓습니다. 공시는 전자공시(DART) 목록, 정책뉴스는 공공누리 제1유형 기사만 본문을 두고,
          언론사 기사는 제목 · 주소만(GDELT 메타데이터) — 본문은 원문 링크로 엽니다. 이름표(종목 · 주제)는 규칙으로 붙였습니다.</p>
      </div></div>`;
  if (window.matchMedia?.("(max-width: 900px)").matches) r.querySelector(".rs-filters").open = false;   // 좁은 화면은 접어 두기
  r.querySelector(".rs-bar").addEventListener("submit", async e => {
    e.preventDefault();
    S.q = r.querySelector(".rs-q").value.trim();   // 차례를 고르지 않았으면 낱말이 생길 때 관련도순으로(sortNow)
    if (!S.q && S.sort === "relevance") S.sort = "";   // 낱말 없는 관련도순은 뜻이 없다 — 자동(최신순)으로(DF-86)
    // 종목 칸 — 새로 친 종목은 먼저 찾는다(제안 목록을 기다리지 않음 · 점검 <표 2> 마 「검색은 종목 칸 글을 버린다」 고침).
    // 정확히 같은 것 하나면 낱말과 함께 그 종목의 시간표로 · 여럿 · 없음이면 목록 · 알림을 보이고 사용자가 고른다.
    const symInput = r.querySelector(".rs-sym-q");
    const typed = symInput.value.trim();
    const current = S.symbol ? (S.symbolName || S.symbol) : "";
    if (typed && typed !== current) {
      await findResearchStock(symInput, { keepQuery: true });
      return;
    }
    if (!typed && S.symbol) { clearResearchSymbol(); return; }   // 종목 칸을 비우고 검색 — 종목 거름을 푼다
    paintFilters();
    reload();
  });
  wireResearchBar(r);
  // 검색어를 비우면 바로 최신 소식으로(2026-10-08 결정 · DF-86) — ✕ 를 누르거나 글을 다 지운 순간 낱말 조건을 빼고 차례를
  // 자동(낱말이 없으면 최신순)으로 되돌려 다시 받는다. 종류 · 종목 · 주제 · 기간 거름은 그대로 둔다(옛 동작: 칸만 비고 결과는 옛 낱말).
  const qInput = r.querySelector(".rs-q");
  const onResearchQueryCleared = () => { if (!qInput.value.trim()) clearResearchQuery(); };
  qInput.addEventListener("input", onResearchQueryCleared);
  qInput.addEventListener("search", onResearchQueryCleared);   // 검색 칸의 ✕ (input 과 함께 오면 두 번째는 아무것도 안 한다)
  paintAll();
  loadList();                                       // 처음은 늘 목록(종목을 고르기 전)
}

/** 다른 화면(AI 투자 상담의 앱 판단 카드 · js/kbchat.js)에서 종목을 넘겨 연다 — 제안 목록에서 고른 것처럼 그 종목 전부의 시간표로.
 *  화면 진입 훅이 먼저 그렸으면 그대로 두고(renderResearch 가 가린다) 종목만 바꾼다(앞 목록 응답은 seq 로 버린다). */
export function openResearchSymbol(code, name) {
  renderResearch();
  pickSymbol(code, name);
}

/** main.js 의 화면 진입 훅 — 처음 들어올 때 그리고, 다시 들어오면 고른 조건 · 결과를 그대로 둔다(renderResearch 가 가린다). */
export function onResearchViewActivated(view) {
  // 화면 키는 글자 그대로 · 한 줄 호출 — 화면 스캐너(scripts/view_scan.py)가 이 모양으로 「화면 ↔ 부르는 API」 를 잇는다
  if (view === "agent-news") renderResearch();
}
