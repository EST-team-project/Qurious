/* 금융 일정 — 「투자분석 기초 › 일정」 달력 화면 + 「다가오는 일정」 카드 (2026-10-02)
 *
 * 화면 설계 결정(Figma 「데이터 관제 · 금융 일정」):
 *   ② A + C 융합 — 월 달력 화면의 오른쪽 목록을 「다가오는 일정」 카드로(내 보유 종목의 배당 일정을 맨 위에),
 *     같은 카드를 시세를 보는 화면 오른쪽에도 붙인다(이번에는 「거시경제 지표」 — 다른 담당 화면은 팀에 묻고 나중에).
 *     휴대폰(좁은 화면)은 달력 대신 같은 자료를 목록(안 B)으로 보인다.
 *   ③ 아직 모으지 않는 종류(경제지표 · 실적 · 금통위 · FOMC)의 자리는 두지 않는다 — 자료가 들어오는 날 종류를 더한다.
 * 읽는 API: GET /api/calendar/events · /api/calendar/trading-days(로그인 없이 · 수집기가 매일 다시 만든다)
 *           GET /api/paper/stocks/positions(내 보유 종목 — 카드의 맨 위 줄)
 */
import { api, escHtml } from "/js/common.js";
import { navigate } from "/js/core.js";

const VIEW = "market-calendar";
//: 일정 종류 → [짧은 이름, 색 이름]. 결정 ③ — 이 넷만 둔다.
const KINDS = {
  market_closure: ["휴장", "closure"],
  deriv_expiry: ["만기", "expiry"],
  dividend_ex: ["배당락일", "divex"],
  dividend_record: ["배당 기준일", "divrec"],
};
const MAX_CHIPS = 3;                              // 한 칸에 칩 셋 — 넘으면 「+N 더」 (9월 29일 배당락일 10건)
const WEEK = "일월화수목금토";

const state = { y: 0, m: 0, kinds: new Set(Object.keys(KINDS)), symbol: "", events: [], days: {}, calendar: null, error: "" };

// ── 날짜 도구(모두 KST 달력 날짜 문자열로 다룬다 — 시간대 때문에 하루 밀리지 않게) ─────────
function iso(y, m, d) { return `${y}-${String(m + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`; }
function todayIso() {
  const p = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date());
  const g = t => p.find(x => x.type === t).value;
  return `${g("year")}-${g("month")}-${g("day")}`;
}
function addDays(s, n) { const d = new Date(`${s}T12:00:00Z`); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); }
function dow(s) { return new Date(`${s}T12:00:00Z`).getUTCDay(); }
function mmdd(s) { return `${s.slice(5, 7)}-${s.slice(8, 10)}`; }
function gridRange(y, m) {
  const first = iso(y, m, 1);
  const last = iso(y, m, new Date(Date.UTC(y, m + 1, 0)).getUTCDate());
  return [addDays(first, -dow(first)), addDays(last, 6 - dow(last))];
}

function chip(ev, cls = "") {
  const [label, tone] = KINDS[ev.kind] || [ev.kind_label, "closure"];
  return `<button type="button" class="cal-chip cal-chip--${tone} ${cls}" data-ev="${escHtml(ev.id)}" title="${escHtml(ev.title)}">${escHtml(ev.title.replace(/ 배당락일$| 배당 기준일$/, "") || label)}</button>`;
}
function kindTag(ev) {
  const [label, tone] = KINDS[ev.kind] || [ev.kind_label, "closure"];
  return `<span class="cal-tag cal-tag--${tone}">${escHtml(label)}</span>`;
}
function visible(ev) {
  return state.kinds.has(ev.kind) && (!state.symbol || ev.symbol === state.symbol);
}

// ── 자료 ───────────────────────────────────────────────────────────────
async function loadMonth() {
  const [from, to] = gridRange(state.y, state.m);
  state.error = "";
  try {
    const [ev, td] = await Promise.all([
      api(`/api/calendar/events?from=${from}&to=${to}&limit=2000`, { redirectOnUnauthorized: false }),
      api(`/api/calendar/trading-days?from=${from}&to=${to}`, { redirectOnUnauthorized: false }),
    ]);
    state.events = ev.events || [];
    state.calendar = ev.calendar || td.calendar || null;
    state.days = Object.fromEntries((td.days || []).map(d => [d.date, d]));
  } catch (err) {
    state.events = []; state.days = {}; state.error = err.message;
  }
}

async function holdings() {
  try {
    const r = await api("/api/paper/stocks/positions", { redirectOnUnauthorized: false });
    return new Set((r.positions || []).map(p => String(p.symbol || "").slice(0, 6)).filter(Boolean));
  } catch { return new Set(); }
}

// ── 「다가오는 일정」 카드(달력 화면의 오른쪽 · 다른 화면의 오른쪽 공용) ──────────────────────
async function upcomingHtml({ limit = 5, linkToCalendar = true } = {}) {
  const today = todayIso();
  let events = [];
  try {
    const r = await api(`/api/calendar/events?from=${today}&to=${addDays(today, 45)}&limit=500`, { redirectOnUnauthorized: false });
    events = r.events || [];
  } catch (err) {
    return `<div class="card q-upcoming"><h3 class="cal-h">다가오는 일정</h3><p class="q-err">일정을 읽지 못했습니다 — ${escHtml(err.message)}</p></div>`;
  }
  const mine = await holdings();
  // 내 종목의 배당 일정이 맨 위, 그다음 휴장 · 만기, 다른 종목의 배당은 남는 자리만
  const own = events.filter(e => e.symbol && mine.has(e.symbol));
  const market = events.filter(e => !e.symbol);
  const others = events.filter(e => e.symbol && !mine.has(e.symbol));
  const picked = [...own, ...market, ...others].slice(0, limit).sort((a, b) => (mine.has(b.symbol) - mine.has(a.symbol)) || a.date.localeCompare(b.date));
  const rows = picked.map(e => `<li class="q-up-row ${mine.has(e.symbol) ? "q-up-row--mine" : ""}">
      <div class="q-up-date"><strong>${mmdd(e.date)}</strong><span>${escHtml(e.weekday || WEEK[dow(e.date)])}</span></div>
      <div class="q-up-body">${mine.has(e.symbol) ? `<span class="q-up-star" title="내 보유 종목">★</span>` : ""}${kindTag(e)}
        <div class="q-up-title">${escHtml(e.title)}</div>${e.detail ? `<div class="q-up-detail">${escHtml(e.detail)}</div>` : ""}</div></li>`).join("");
  return `<div class="card q-upcoming"><h3 class="cal-h">다가오는 일정 <span class="q-muted">${mmdd(today)} (${WEEK[dow(today)]}) 기준</span></h3>
    <ul class="q-up-list">${rows || `<li class="q-muted">45일 안에 일정이 없습니다</li>`}</ul>
    ${linkToCalendar ? `<button type="button" class="q-up-more">전체 일정 보기 →</button>` : ""}
    <p class="q-up-note">${own.length ? "★ 내 보유 종목의 배당 일정을 맨 위에 올렸습니다" : "모의계좌에 가진 종목이 있으면 그 배당 일정을 맨 위에 올립니다"}</p></div>`;
}

async function renderCard(container, opts) {
  container.innerHTML = await upcomingHtml(opts);
  container.querySelector(".q-up-more")?.addEventListener("click", () => navigate(VIEW));
}

/** 시세를 보는 화면 오른쪽에 카드를 붙인다 — 화면의 원래 칸은 그대로 두고 둘레만 두 칸으로 감싼다(사용법 안내는 맨 위 그대로). */
function mountSideCard(viewKey) {
  const view = document.querySelector(`.view[data-view="${viewKey}"]`);
  if (!view) return;
  let side = view.querySelector(":scope > .q-with-side > .q-side");
  if (!side) {
    const wrap = document.createElement("div");
    wrap.className = "q-with-side";
    const main = document.createElement("div");
    main.className = "q-main";
    side = document.createElement("div");
    side.className = "q-side";
    [...view.children].filter(c => !c.classList.contains("view-guide")).forEach(c => main.appendChild(c));
    wrap.append(main, side);
    view.appendChild(wrap);
  }
  renderCard(side, { limit: 4 });
}

// ── 화면 — 달력 + 휴대폰 목록 + 설명 창 ──────────────────────────────────────
function gridHtml() {
  const [from, to] = gridRange(state.y, state.m);
  const today = todayIso();
  const byDay = {};
  for (const e of state.events) if (visible(e)) (byDay[e.date] ||= []).push(e);
  let cells = "";
  for (let d = from; d <= to; d = addDays(d, 1)) {
    const inMonth = Number(d.slice(5, 7)) === state.m + 1;
    const day = state.days[d];
    const closed = day ? !day.is_trading_day : [0, 6].includes(dow(d));
    const evs = byDay[d] || [];
    const chips = evs.slice(0, MAX_CHIPS).map(e => chip(e)).join("");
    const more = evs.length > MAX_CHIPS ? `<button type="button" class="cal-more" data-day="${d}">+${evs.length - MAX_CHIPS} 더</button>` : "";
    cells += `<div class="cal-cell ${inMonth ? "" : "cal-out"} ${closed ? "cal-closed" : ""} ${d === today ? "cal-today" : ""}"
        data-dow="${dow(d)}"><div class="cal-num">${Number(d.slice(8, 10))}</div>${chips}${more}</div>`;
  }
  return `<div class="cal-grid"><div class="cal-wk">${[...WEEK].map((w, i) => `<div data-dow="${i}">${w}</div>`).join("")}</div>
    <div class="cal-cells">${cells}</div></div>`;
}

function listHtml() {
  const evs = state.events.filter(e => visible(e) && Number(e.date.slice(5, 7)) === state.m + 1);
  if (!evs.length) return `<div class="cal-list"><p class="q-muted">이 달에 고른 종류의 일정이 없습니다</p></div>`;
  const weeks = {};
  for (const e of evs) { const k = addDays(e.date, -((dow(e.date) + 6) % 7)); (weeks[k] ||= []).push(e); }   // 월요일로 묶기
  return `<div class="cal-list">${Object.entries(weeks).map(([mon, list]) => `<div class="cal-list-wk">${mmdd(mon)} ~ ${mmdd(addDays(mon, 4))}</div>
      ${list.map(e => `<button type="button" class="cal-list-row" data-ev="${escHtml(e.id)}">
        <span class="cal-list-date"><strong>${mmdd(e.date)}</strong><span>${escHtml(e.weekday)}</span></span>
        <span class="cal-list-body">${kindTag(e)} <strong>${escHtml(e.title)}</strong>
          <span class="q-muted">${escHtml(e.detail || "")}</span></span></button>`).join("")}`).join("")}</div>`;
}

function noticeHtml() {
  if (state.error) return `<p class="dh-alert q-tone--stale">일정을 읽지 못했습니다 — ${escHtml(state.error)}</p>`;
  const end = state.calendar?.end;
  if (end && iso(state.y, state.m, 1) > end) {
    return `<p class="dh-alert q-tone--info">이 달은 공휴일이 아직 발표되지 않아 일정을 만들지 않았습니다 — 달력은 ${escHtml(end)} 까지 있습니다.</p>`;
  }
  return "";
}

function openEventModal(ev) {
  let m = document.getElementById("cal-modal");
  if (!m) {
    m = document.createElement("div");
    m.id = "cal-modal";
    m.innerHTML = `<div class="cal-modal-box" role="dialog" aria-modal="true" aria-labelledby="cal-modal-title">
      <button type="button" class="q-dd-close cal-modal-x" aria-label="닫기"><i class="fa-solid fa-xmark"></i></button>
      <div class="cal-modal-body"></div></div>`;
    document.body.appendChild(m);
    m.addEventListener("click", e => { if (e.target === m || e.target.closest(".cal-modal-x")) m.classList.remove("open"); });
    document.addEventListener("keydown", e => { if (e.key === "Escape") m.classList.remove("open"); });
  }
  const evs = Array.isArray(ev) ? ev : [ev];
  m.querySelector(".cal-modal-body").innerHTML = evs.map(e => `<div class="cal-modal-ev">
      <div class="cal-modal-kind">${kindTag(e)}</div><h3 id="cal-modal-title">${escHtml(e.title)}</h3>
      <div class="cal-modal-meta"><div><span>날짜</span>${escHtml(e.date)} (${escHtml(e.weekday)})</div>
        <div><span>어떻게 정했나</span>${escHtml(e.confidence_label || "—")}</div>
        ${e.symbol ? `<div><span>종목</span>${escHtml(e.symbol)}</div>` : `<div><span>시장</span>${escHtml(e.market || "유가증권 · 코스닥")}</div>`}</div>
      ${e.detail ? `<p>${escHtml(e.detail)}</p>` : ""}
      ${e.symbol ? `<button type="button" class="btn-secondary cal-only" data-sym="${escHtml(e.symbol)}">이 종목의 일정만 보기</button>` : ""}</div>`).join("") +
    `<p class="q-up-note">휴장은 공휴일 정보와 거래소 규칙(근로자의 날 · 연말 휴장일)으로, 파생 만기는 두 번째 목요일 규칙으로,
      배당은 전자공시의 배당 결정 공시로 만들었습니다. 배당락일은 기준일 하루 전 거래일로 계산한 값입니다.</p>`;
  m.querySelectorAll(".cal-only").forEach(b => b.addEventListener("click", () => { state.symbol = b.dataset.sym; m.classList.remove("open"); renderCalendar(false); }));
  m.classList.add("open");
}

function calendarRoot() {
  const view = document.querySelector(`.view[data-view="${VIEW}"]`);
  if (!view) return null;
  let root = view.querySelector(".cal-root");
  if (!root) { root = document.createElement("div"); root.className = "cal-root"; view.appendChild(root); }
  return root;
}

async function renderCalendar(reload = true) {
  const root = calendarRoot();
  if (!root) return;
  if (!state.y) { const t = todayIso(); state.y = +t.slice(0, 4); state.m = +t.slice(5, 7) - 1; }   // 처음 들어오면 이번 달
  if (reload) { if (!root.innerHTML) root.innerHTML = `<p class="q-muted">불러오는 중…</p>`; await loadMonth(); }
  const filters = Object.entries(KINDS).map(([k, [label, tone]]) =>
    `<button type="button" class="cal-filter cal-chip--${tone} ${state.kinds.has(k) ? "on" : ""}" data-kind="${k}">${state.kinds.has(k) ? "✓ " : ""}${label}</button>`).join("");
  root.innerHTML = `<div class="dh-head"><div><h2>증시 일정</h2>
      <p class="q-muted">휴장일 · 파생상품 만기 · 배당락일 · 배당 기준일 — 공휴일 정보 · 거래소 규칙 · 배당 공시로 만든 일정</p></div></div>
    <div class="cal-layout"><div class="card cal-main">
      <div class="cal-bar"><button type="button" class="cal-nav" data-step="-1" aria-label="지난달">‹</button>
        <strong class="cal-title">${state.y}년 ${state.m + 1}월</strong>
        <button type="button" class="cal-nav" data-step="1" aria-label="다음 달">›</button>
        <button type="button" class="btn-secondary cal-today-btn">오늘</button>
        <div class="cal-filters">${filters}</div>
        ${state.symbol ? `<button type="button" class="cal-symbol">종목 ${escHtml(state.symbol)} 만 · 풀기 ✕</button>` : ""}</div>
      ${noticeHtml()}${gridHtml()}${listHtml()}
      <p class="q-up-note">거래일 달력은 ${escHtml(state.calendar?.end || "—")} 까지 있습니다(공휴일이 발표된 해까지) · 일정을 누르면 설명 창이 열립니다</p></div>
      <div class="cal-side"></div></div>`;
  root.querySelectorAll(".cal-nav").forEach(b => b.addEventListener("click", () => {
    const d = new Date(Date.UTC(state.y, state.m + Number(b.dataset.step), 1));
    state.y = d.getUTCFullYear(); state.m = d.getUTCMonth(); renderCalendar();
  }));
  root.querySelector(".cal-today-btn").addEventListener("click", () => { const t = todayIso(); state.y = +t.slice(0, 4); state.m = +t.slice(5, 7) - 1; renderCalendar(); });
  root.querySelectorAll(".cal-filter").forEach(b => b.addEventListener("click", () => {
    const k = b.dataset.kind;
    if (state.kinds.has(k) && state.kinds.size > 1) state.kinds.delete(k); else state.kinds.add(k);
    renderCalendar(false);
  }));
  root.querySelector(".cal-symbol")?.addEventListener("click", () => { state.symbol = ""; renderCalendar(false); });
  const byId = Object.fromEntries(state.events.map(e => [e.id, e]));
  root.querySelectorAll("[data-ev]").forEach(b => b.addEventListener("click", () => byId[b.dataset.ev] && openEventModal(byId[b.dataset.ev])));
  root.querySelectorAll(".cal-more").forEach(b => b.addEventListener("click", () => openEventModal(state.events.filter(e => e.date === b.dataset.day && visible(e)))));
  renderCard(root.querySelector(".cal-side"), { limit: 6, linkToCalendar: false });
}

/** main.js 의 화면 진입 훅 — 달력 화면이면 이번 달로 그리고, 카드를 붙이는 화면이면 오른쪽 카드를 붙인다. */
export function onCalendarViewActivated(view) {
  // 화면이 바뀌면 설명 창을 닫는다 — 열린 채 뒤로 가기 · 주소로 옮기면 다른 화면을 덮는다(2026-10-02 브라우저 확인)
  document.getElementById("cal-modal")?.classList.remove("open");
  // 화면 키는 글자 그대로 — 화면 스캐너(scripts/view_scan.py)가 이 모양으로 「화면 ↔ 부르는 API」 를 잇는다
  if (view === "market-calendar") renderCalendar();
  // 카드를 붙이는 화면은 내 담당만(결정 기록 ②의 뒤집을 조건 — 주가 차트 · 모의투자는 화면 주인과 정한다)
  if (view === "macro-dashboard") mountSideCard(view);
}
