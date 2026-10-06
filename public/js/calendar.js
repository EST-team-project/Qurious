/* 금융 일정 — 「투자분석 기초 › 일정」 달력 화면 + 「다가오는 일정」 카드 (2026-10-02 · 2판 2026-10-06)
 *
 * 화면 설계 결정(Figma 「데이터 관제 · 금융 일정」):
 *   ② A + C 융합 — 월 달력 화면의 오른쪽에 「다가오는 일정」 카드(내 보유 종목 일정을 맨 위에), 같은 카드를 시세를 보는
 *     화면 오른쪽에도 붙인다(이번에는 「거시경제 지표」). 휴대폰(좁은 화면)은 달력 대신 같은 자료를 목록(안 B)으로 보인다.
 *   ③ 아직 모으지 않는 종류의 자리는 두지 않는다 — 자료가 들어오는 날 종류를 더한다.
 *   일정 2판(「10 일정 2판」 · 결정 기록 2026-10-05 안 B) — 종류가 열이 되고(주주총회 · 배당금 지급 · 실적 · 보고서 기한 ·
 *     금통위 · FOMC) 3월은 한 달 3,532건이라 한 번에 받을 수 없다(DF-66). 그래서
 *     · 칸에는 시장 전체 일정은 이름까지, 종목 일정은 종류별 개수만(주총 731 · 락 27) — 한 달 요약 API 하나로 받는다
 *     · 날짜나 칸의 숫자를 누르면 오른쪽에 그날 목록(종목 찾기 · 그날 종류 거르기 · 50건씩) — 휴대폰은 서랍으로
 *     · 처음 범위는 모든 종목, 그날 목록에서 모의계좌에 가진 종목(내 종목)을 맨 위에
 * 읽는 API: GET /api/calendar/events/summary(한 달 요약) · /api/calendar/events(그날 목록 · 종목 하나 · 카드)
 *           GET /api/calendar/trading-days · /api/paper/stocks/positions(내 보유 종목) — 일정은 로그인 없이
 */
import { api, escHtml } from "/js/common.js";
import { navigate } from "/js/core.js";

const VIEW = "market-calendar";
//: 일정 종류 → [칸 배지 이름, 이름, 색 이름]. 2판 — 서버의 열 종류 모두(칩 차례는 Figma 「일정 2판」 그대로).
const KINDS = {
  market_closure: ["휴장", "휴장", "closure"],
  deriv_expiry: ["만기", "파생 만기", "expiry"],
  policy_rate: ["금통위", "금통위", "policy"],
  fomc: ["FOMC", "FOMC", "fomc"],
  report_deadline: ["기한", "보고서 기한", "deadline"],
  dividend_record: ["기준", "배당 기준일", "divrec"],
  dividend_ex: ["락", "배당락일", "divex"],
  dividend_pay: ["지급", "배당금 지급", "divpay"],
  agm: ["주총", "주주총회", "agm"],
  earnings: ["실적", "실적 발표", "earn"],
};
//: 시장 전체 일정 — 칸에 이름까지 보인다(서버 MARKET_KINDS 와 같다). 나머지는 종목 일정이라 칸에는 개수만.
const MARKET_KINDS = ["market_closure", "deriv_expiry", "policy_rate", "fomc", "report_deadline"];
//: 설명 창 아래 — 그 일정을 어떻게 만들었나(종류마다 한 줄)
const HOW = {
  market_closure: "공휴일 정보(한국천문연구원 특일 정보)와 거래소 규칙(근로자의 날 · 연말 휴장일)으로 만들었습니다.",
  deriv_expiry: "각 결제월 두 번째 목요일(휴장이면 앞당김) 규칙으로 계산했습니다.",
  policy_rate: "한국은행이 공개한 금융통화위원회 회의 일정입니다.",
  fomc: "미국 연방준비제도가 공개한 FOMC 회의 일정입니다 — 결과는 한국 시각으로 다음 날 새벽에 나옵니다.",
  report_deadline: "자본시장법의 정기보고서 제출 기한(사업보고서 90일 · 반기 · 분기보고서 45일)으로 계산했습니다.",
  dividend_record: "전자공시의 배당 결정 공시에서 읽었습니다.",
  dividend_ex: "배당 기준일 하루 전 거래일로 계산했습니다 — 이날부터 사면 이번 배당을 받지 못합니다.",
  dividend_pay: "배당 결정 공시 본문의 배당금 지급 예정일입니다 — 결산배당은 주주총회에서 정해 비어 있는 일이 많습니다.",
  agm: "주주총회 소집결의 공시 본문의 일시입니다(정정 공시가 있으면 마지막 정정본).",
  earnings: "잠정실적 · 손익구조 변동 공시가 나온 날입니다(공시 접수일).",
};
const PAGE = 50;                                  // 그날 목록 한 쪽 — 결정 안 B 「50건씩」
const MAX_NAMES = 2;                              // 칸에 이름을 보이는 시장 일정 수 — 넘으면 「+N」
const MAX_FIRST = 50;                             // 맨 위에 올릴 내 종목 수(서버 상한과 같다)
const WEEK = "일월화수목금토";

const state = {
  y: 0, m: 0,
  kinds: new Set(Object.keys(KINDS)),            // 처음에는 열 종류 모두(결정 기록 「처음 범위 모든 종목」)
  symbol: "",                                    // 「이 종목의 일정만 보기」
  sumDays: {}, monthTotal: 0, days: {}, calendar: null, error: "",
  symEvents: [],                                 // 종목 하나만 볼 때 그 종목의 일정(이름까지)
  mine: null,                                    // 내 보유 종목(Set) — 화면에 처음 들어올 때 읽는다
  panel: null,                                   // 그날 목록 { date, kinds:Set, q, offset, events, total, error, loading }
};
let qTimer = 0;
let monthSeq = 0;

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
function korDay(s) { return `${Number(s.slice(5, 7))}월 ${Number(s.slice(8, 10))}일 (${WEEK[dow(s)]})`; }
function gridRange(y, m) {
  const first = iso(y, m, 1);
  const last = iso(y, m, new Date(Date.UTC(y, m + 1, 0)).getUTCDate());
  return [addDays(first, -dow(first)), addDays(last, 6 - dow(last))];
}
function inMonth(d) { return Number(d.slice(0, 4)) === state.y && Number(d.slice(5, 7)) === state.m + 1; }
function num(n) { return Number(n || 0).toLocaleString("ko-KR"); }

function tone(kind) { return (KINDS[kind] || ["", "", "closure"])[2]; }
function kindTag(ev) {
  const [, label, t] = KINDS[ev.kind] || ["", ev.kind_label || ev.kind, "closure"];
  return `<span class="cal-tag cal-tag--${t}">${escHtml(label)}</span>`;
}
function chip(ev) {
  return `<button type="button" class="cal-chip cal-chip--${tone(ev.kind)}" data-ev="${escHtml(ev.id)}" title="${escHtml(ev.title)}">${escHtml(ev.title.replace(/ 배당락일$| 배당 기준일$/, ""))}</button>`;
}
/** 종목 일정 제목의 앞 낱말(회사 이름)을 굵게 — 「영풍 정기주주총회」 → <strong>영풍</strong> 정기주주총회 */
function titleHtml(ev) {
  const t = ev.title || "";
  const cut = ev.symbol ? t.indexOf(" ") : -1;
  return cut > 0 ? `<strong>${escHtml(t.slice(0, cut))}</strong> ${escHtml(t.slice(cut + 1))}` : `<strong>${escHtml(t)}</strong>`;
}

// ── 자료 ───────────────────────────────────────────────────────────────
async function holdings() {
  try {
    const r = await api("/api/paper/stocks/positions", { redirectOnUnauthorized: false });
    return new Set((r.positions || []).map(p => String(p.symbol || "").slice(0, 6)).filter(Boolean));
  } catch { return new Set(); }
}
function firstParam(mine) {
  const syms = [...(mine || [])].filter(s => /^[0-9A-Z]{6}$/.test(s)).slice(0, MAX_FIRST);
  return syms.length ? `&first=${syms.join(",")}` : "";
}

async function loadMonth() {
  const [from, to] = gridRange(state.y, state.m);
  const seq = ++monthSeq;                          // 달을 빠르게 넘기면 늦게 온 앞 달 응답이 지금 달을 덮지 않게
  const stale = () => seq !== monthSeq;
  state.error = "";
  try {
    // 한 달은 요약 하나 — 날짜 × 종류 개수 + 시장 전체 일정 이름(3월 3,532건도 날짜 수만큼 · DF-66). 칩은 받은 뒤에 거른다
    const reqs = [
      api(`/api/calendar/events/summary?from=${from}&to=${to}`, { redirectOnUnauthorized: false }),
      api(`/api/calendar/trading-days?from=${from}&to=${to}`, { redirectOnUnauthorized: false }),
    ];
    if (state.symbol) {
      reqs.push(api(`/api/calendar/events?from=${from}&to=${to}&kind=all&symbol=${state.symbol}&limit=500`, { redirectOnUnauthorized: false }));
    }
    const [sum, td, sym] = await Promise.all(reqs);
    if (stale()) return false;
    state.sumDays = Object.fromEntries((sum.days || []).map(d => [d.date, d]));
    state.calendar = sum.calendar || td.calendar || null;
    state.days = Object.fromEntries((td.days || []).map(d => [d.date, d]));
    state.symEvents = sym ? (sym.events || []) : [];
  } catch (err) {
    if (stale()) return false;
    state.sumDays = {}; state.days = {}; state.symEvents = []; state.error = err.message;
  }
  return true;
}

/** 그날의 종류별 개수 — 위의 칩으로 거른 종류만 */
function dayCounts(d) {
  const counts = (state.sumDays[d] || {}).counts || {};
  return Object.keys(KINDS).filter(k => counts[k] && state.kinds.has(k)).map(k => [k, counts[k]]);
}
function marketEvents(d) {
  const sd = state.sumDays[d];
  return (sd?.market_events || []).filter(e => state.kinds.has(e.kind)).map(e => ({ ...e, date: d, weekday: sd.weekday, market: "" }));
}
function symVisible(d) { return state.symEvents.filter(e => e.date === d && state.kinds.has(e.kind)); }

// ── 달력 칸 · 휴대폰 목록 ──────────────────────────────────────────────────────
function countBadges(d) {
  return dayCounts(d).filter(([k]) => !MARKET_KINDS.includes(k)).map(([k, n]) =>
    `<button type="button" class="cal-cnt cal-chip--${tone(k)}" data-day="${d}" data-kind="${k}" title="${escHtml(KINDS[k][1])} ${num(n)}건 — 누르면 그날 목록">${escHtml(KINDS[k][0])} ${num(n)}</button>`).join("");
}
function cellBody(d) {
  if (state.symbol) {
    const evs = symVisible(d);
    return evs.slice(0, 3).map(chip).join("") + (evs.length > 3 ? `<button type="button" class="cal-more" data-day="${d}">+${evs.length - 3} 더</button>` : "");
  }
  const names = marketEvents(d);
  const shown = names.slice(0, MAX_NAMES).map(chip).join("");
  const more = names.length > MAX_NAMES ? `<button type="button" class="cal-more" data-day="${d}">+${names.length - MAX_NAMES}</button>` : "";
  const badges = countBadges(d);
  return `${shown}${more}${badges ? `<div class="cal-cnts">${badges}</div>` : ""}`;
}

function gridHtml() {
  const [from, to] = gridRange(state.y, state.m);
  const today = todayIso();
  let cells = "";
  for (let d = from; d <= to; d = addDays(d, 1)) {
    const day = state.days[d];
    const closed = day ? !day.is_trading_day : [0, 6].includes(dow(d));
    const picked = state.panel?.date === d;
    cells += `<div class="cal-cell ${inMonth(d) ? "" : "cal-out"} ${closed ? "cal-closed" : ""} ${d === today ? "cal-today" : ""} ${picked ? "cal-picked" : ""}"
        data-dow="${dow(d)}" data-cell="${d}"><button type="button" class="cal-num" data-day="${d}" aria-label="${escHtml(korDay(d))} 일정 목록">${Number(d.slice(8, 10))}</button>${cellBody(d)}</div>`;
  }
  return `<div class="cal-grid"><div class="cal-wk">${[...WEEK].map((w, i) => `<div data-dow="${i}">${w}</div>`).join("")}</div>
    <div class="cal-cells">${cells}</div></div>`;
}

/** 휴대폰(결정 ② 안 B) — 이 달의 일정 있는 날을 주마다 한 줄씩 · 줄을 누르면 그날 목록 서랍 */
function listHtml() {
  const [from, to] = gridRange(state.y, state.m);
  const rows = [];
  for (let d = from; d <= to; d = addDays(d, 1)) {
    if (!inMonth(d)) continue;
    const names = state.symbol ? symVisible(d) : marketEvents(d);
    const badges = state.symbol ? "" : countBadges(d);
    if (!names.length && !badges) continue;
    rows.push([d, `<div class="cal-list-row" data-day-row="${d}">
        <button type="button" class="cal-list-date" data-day="${d}"><strong>${mmdd(d)}</strong><span>${WEEK[dow(d)]}</span></button>
        <div class="cal-list-body">${names.map(e => `<button type="button" class="cal-list-ev" data-ev="${escHtml(e.id)}">${kindTag(e)} ${escHtml(e.title)}</button>`).join("")}
          ${badges ? `<div class="cal-cnts">${badges}</div>` : ""}</div></div>`]);
  }
  if (!rows.length) return `<div class="cal-list"><p class="q-muted">이 달에 고른 종류의 일정이 없습니다</p></div>`;
  const weeks = {};
  for (const [d, html] of rows) { const k = addDays(d, -((dow(d) + 6) % 7)); (weeks[k] ||= []).push(html); }   // 월요일로 묶기
  return `<div class="cal-list">${Object.entries(weeks).map(([mon, list]) =>
    `<div class="cal-list-wk">${mmdd(mon)} ~ ${mmdd(addDays(mon, 6))}</div>${list.join("")}`).join("")}</div>`;
}

function noticeHtml() {
  if (state.error) return `<p class="dh-alert q-tone--stale">일정을 읽지 못했습니다 — ${escHtml(state.error)}</p>`;
  const end = state.calendar?.end;
  if (end && iso(state.y, state.m, 1) > end) {
    return `<p class="dh-alert q-tone--info">이 달은 공휴일이 아직 발표되지 않아 일정을 만들지 않았습니다 — 달력은 ${escHtml(end)} 까지 있습니다.</p>`;
  }
  return "";
}

function monthTotal() {
  if (state.symbol) return state.symEvents.filter(e => inMonth(e.date) && state.kinds.has(e.kind)).length;
  return Object.values(state.sumDays).filter(d => inMonth(d.date))
    .reduce((s, d) => s + Object.entries(d.counts || {}).filter(([k]) => state.kinds.has(k)).reduce((a, [, n]) => a + n, 0), 0);
}

// ── 그날 목록(오른쪽 칸 · 휴대폰은 서랍) ─────────────────────────────────────────
function openDay(date, kind = "") {
  const visible = dayCounts(date).map(([k]) => k);
  const kinds = new Set(kind && visible.includes(kind) ? [kind] : (visible.length ? visible : [...state.kinds]));
  state.panel = { date, kinds, q: "", offset: 0, events: [], total: 0, error: "", loading: true };
  paintCells();
  renderSide();
  loadDay();
}
function closeDay() {
  if (!state.panel) return;
  state.panel = null;
  paintCells();
  renderSide();
}

async function loadDay() {
  const p = state.panel;
  if (!p) return;
  const want = p;                                  // 늦게 온 응답이 다른 날 목록을 덮지 않게
  p.loading = true; paintDay();
  const q = p.q.trim();
  let url = `/api/calendar/events?from=${p.date}&to=${p.date}&kind=${[...p.kinds].join(",")}&limit=${PAGE}&offset=${p.offset}`;
  if (state.symbol) url += `&symbol=${state.symbol}`;
  else if (/^[0-9A-Za-z]{6}$/.test(q) && /\d/.test(q)) url += `&symbol=${q.toUpperCase()}`;   // 종목 코드(숫자가 든 6자)
  else if (q) url += `&q=${encodeURIComponent(q)}`;
  url += firstParam(state.mine);
  try {
    const r = await api(url, { redirectOnUnauthorized: false });
    if (state.panel !== want) return;
    p.events = r.events || []; p.total = r.total || 0; p.error = "";
  } catch (err) {
    if (state.panel !== want) return;
    p.events = []; p.total = 0; p.error = err.message;
  }
  p.loading = false;
  paintDay();
}

function dayHeadHtml(p) {
  const counts = dayCounts(p.date);
  const all = counts.reduce((a, [, n]) => a + n, 0);
  const sub = state.symbol ? `종목 ${escHtml(state.symbol)} 만` : counts.map(([k, n]) => `${escHtml(KINDS[k][1])} ${num(n)}`).join(" · ");
  return `<h3 class="cal-h" id="cal-day-title">${escHtml(korDay(p.date))} · ${num(state.symbol ? p.total : all)}건</h3>
    <p class="q-muted cal-day-sub">${sub || "고른 종류의 일정이 없습니다"}</p>`;
}
function dayKindsHtml(p) {
  if (state.symbol) return "";
  return dayCounts(p.date).map(([k, n]) =>
    `<button type="button" class="cal-filter cal-chip--${tone(k)} ${p.kinds.has(k) ? "on" : ""}" data-day-kind="${k}" aria-pressed="${p.kinds.has(k)}">${escHtml(KINDS[k][1])} ${num(n)}</button>`).join("");
}
function dayListHtml(p) {
  if (p.error) return `<p class="dh-alert q-tone--stale">그날 일정을 읽지 못했습니다 — ${escHtml(p.error)}</p>`;
  if (p.loading && !p.events.length) return `<p class="q-muted">불러오는 중…</p>`;
  if (!p.events.length) return `<p class="q-muted">${p.q ? `「${escHtml(p.q)}」 이 든 일정이 없습니다` : "이날 고른 종류의 일정이 없습니다"}</p>`;
  return `<ul class="cal-day-list">${p.events.map(e => {
    // 주총 설명은 「09:00 · 장소 …」 처럼 시각으로 시작한다 — 시각은 제목 줄에 있으니 설명에서는 뺀다
    const detail = e.time && (e.detail || "").startsWith(`${e.time} · `) ? e.detail.slice(e.time.length + 3) : (e.detail || "");
    return `<li><button type="button" class="cal-day-row ${e.mine ? "cal-day-row--mine" : ""}" data-ev="${escHtml(e.id)}">
      <span class="cal-day-line">${e.mine ? `<span class="q-up-star" title="내 보유 종목">★</span>` : ""}${titleHtml(e)}${e.time ? `<span class="q-muted"> · ${escHtml(e.time)}</span>` : ""}</span>
      <span class="cal-day-meta">${kindTag(e)}${detail ? `<span class="q-muted">${escHtml(detail)}</span>` : ""}</span></button></li>`;
  }).join("")}</ul>`;
}
function dayPagerHtml(p) {
  const pages = Math.max(1, Math.ceil(p.total / PAGE));
  const page = Math.floor(p.offset / PAGE) + 1;
  return `<div class="cal-day-pager"><button type="button" class="cal-nav" data-page="-1" aria-label="앞 쪽" ${page <= 1 ? "disabled" : ""}>‹</button>
    <span>${num(page)} / ${num(pages)} 쪽 · ${PAGE}건씩</span>
    <button type="button" class="cal-nav" data-page="1" aria-label="다음 쪽" ${page >= pages ? "disabled" : ""}>›</button></div>`;
}

/** 오른쪽 칸 — 그날 목록이 열려 있으면 목록, 아니면 「다가오는 일정」 카드 */
function renderSide() {
  const side = document.querySelector(`.view[data-view="${VIEW}"] .cal-side`);
  if (!side) return;
  const p = state.panel;
  document.querySelector(`.view[data-view="${VIEW}"] .cal-layout`)?.classList.toggle("cal-day-open", Boolean(p));
  if (!p) { renderCard(side, { limit: 6, linkToCalendar: false }); return; }
  side.dataset.cardToken = "";                     // 아직 오는 중인 카드는 버린다(이 칸은 이제 그날 목록)
  side.innerHTML = `<div class="cal-day-back" data-day-close></div>
    <section class="card cal-day" role="dialog" aria-labelledby="cal-day-title">
      <div class="cal-day-top"><div class="cal-day-head">${dayHeadHtml(p)}</div>
        <button type="button" class="q-dd-close cal-day-x" data-day-close aria-label="그날 목록 닫기"><i class="fa-solid fa-xmark"></i></button></div>
      ${state.symbol ? "" : `<input type="search" class="cal-day-q" placeholder="종목 이름 · 코드로 찾기" aria-label="그날 일정에서 종목 찾기" value="${escHtml(p.q)}">`}
      <div class="cal-day-kinds">${dayKindsHtml(p)}</div>
      <div class="cal-day-body">${dayListHtml(p)}</div>
      <div class="cal-day-foot">${dayPagerHtml(p)}</div>
      <p class="q-up-note">${state.mine?.size ? "★ 모의계좌에 가진 종목의 일정을 맨 위에 올렸습니다" : "모의계좌에 가진 종목이 있으면 그 일정을 맨 위에 올립니다"} · 줄을 누르면 설명 창이 열립니다</p>
    </section>`;
  side.querySelectorAll("[data-day-close]").forEach(b => b.addEventListener("click", closeDay));
  side.querySelector(".cal-day-q")?.addEventListener("input", e => {
    clearTimeout(qTimer);
    const v = e.target.value;
    qTimer = setTimeout(() => { if (state.panel === p) { p.q = v; p.offset = 0; loadDay(); } }, 300);
  });
  bindDayParts(side, p);
}
/** 목록 · 쪽 · 머리만 다시 그린다(찾기 칸의 입력 · 커서를 지키려고 칸은 그대로) */
function paintDay() {
  const side = document.querySelector(`.view[data-view="${VIEW}"] .cal-side`);
  const p = state.panel;
  if (!side || !p || !side.querySelector(".cal-day")) return;
  side.querySelector(".cal-day-head").innerHTML = dayHeadHtml(p);
  side.querySelector(".cal-day-kinds").innerHTML = dayKindsHtml(p);
  side.querySelector(".cal-day-body").innerHTML = dayListHtml(p);
  side.querySelector(".cal-day-foot").innerHTML = dayPagerHtml(p);
  bindDayParts(side, p);
}
function bindDayParts(side, p) {
  side.querySelectorAll("[data-day-kind]").forEach(b => b.addEventListener("click", () => {
    const k = b.dataset.dayKind;
    if (p.kinds.has(k) && p.kinds.size > 1) p.kinds.delete(k); else p.kinds.add(k);
    p.offset = 0; loadDay();
  }));
  side.querySelectorAll("[data-page]").forEach(b => b.addEventListener("click", () => {
    const pages = Math.max(1, Math.ceil(p.total / PAGE));
    const next = Math.floor(p.offset / PAGE) + Number(b.dataset.page);
    if (next < 0 || next >= pages) return;
    p.offset = next * PAGE; loadDay();
    side.querySelector(".cal-day")?.scrollTo?.({ top: 0 });
  }));
  const byId = Object.fromEntries(p.events.map(e => [e.id, e]));
  side.querySelectorAll(".cal-day-body [data-ev]").forEach(b => b.addEventListener("click", () => byId[b.dataset.ev] && openEventModal(byId[b.dataset.ev])));
}
/** 고른 날 칸 표시만 바꾼다(달력 전체를 다시 그리지 않게) */
function paintCells() {
  document.querySelectorAll(`.view[data-view="${VIEW}"] [data-cell]`).forEach(c => c.classList.toggle("cal-picked", state.panel?.date === c.dataset.cell));
}

// ── 「다가오는 일정」 카드(달력 화면의 오른쪽 · 다른 화면의 오른쪽 공용) ──────────────────────
async function upcomingHtml({ limit = 5, linkToCalendar = true } = {}) {
  const today = todayIso();
  const end = addDays(today, 45);
  const mine = state.mine || await holdings();
  let market = [], own = [], others = [];
  try {
    // 시장 전체 일정은 요약에서 이름까지, 종목 일정은 내 종목을 맨 위로 받은 앞쪽만(2판 — 종류가 열이라 통째로 받지 않는다)
    const [sum, ev] = await Promise.all([
      api(`/api/calendar/events/summary?from=${today}&to=${end}&kind=${MARKET_KINDS.join(",")}`, { redirectOnUnauthorized: false }),
      api(`/api/calendar/events?from=${today}&to=${end}&kind=all&limit=${Math.max(limit * 4, 20)}${firstParam(mine)}`, { redirectOnUnauthorized: false }),
    ]);
    market = (sum.days || []).flatMap(d => (d.market_events || []).map(e => ({ ...e, date: d.date, weekday: d.weekday, market: "" })));
    own = (ev.events || []).filter(e => e.mine);
    others = (ev.events || []).filter(e => !e.mine && e.symbol);
  } catch (err) {
    return `<div class="card q-upcoming"><h3 class="cal-h">다가오는 일정</h3><p class="q-err">일정을 읽지 못했습니다 — ${escHtml(err.message)}</p></div>`;
  }
  // 내 종목 일정이 맨 위, 그다음 시장 전체 일정, 다른 종목 일정은 남는 자리만 — 고른 뒤 날짜순(내 종목은 그대로 위)
  const picked = [...own, ...market, ...others].slice(0, limit)
    .sort((a, b) => (Number(Boolean(b.mine)) - Number(Boolean(a.mine))) || a.date.localeCompare(b.date));
  const rows = picked.map(e => `<li class="q-up-row ${e.mine ? "q-up-row--mine" : ""}">
      <div class="q-up-date"><strong>${mmdd(e.date)}</strong><span>${escHtml(e.weekday || WEEK[dow(e.date)])}</span></div>
      <div class="q-up-body">${e.mine ? `<span class="q-up-star" title="내 보유 종목">★</span>` : ""}${kindTag(e)}
        <div class="q-up-title">${escHtml(e.title)}</div>${e.detail ? `<div class="q-up-detail">${escHtml(e.detail)}</div>` : ""}</div></li>`).join("");
  return `<div class="card q-upcoming"><h3 class="cal-h">다가오는 일정 <span class="q-muted">${mmdd(today)} (${WEEK[dow(today)]}) 기준</span></h3>
    <ul class="q-up-list">${rows || `<li class="q-muted">45일 안에 일정이 없습니다</li>`}</ul>
    ${linkToCalendar ? `<button type="button" class="q-up-more">전체 일정 보기 →</button>` : `<p class="q-up-note">달력의 날짜나 칸의 숫자를 누르면 그날 목록이 이 자리에 열립니다</p>`}
    <p class="q-up-note">${own.length ? "★ 내 보유 종목의 일정을 맨 위에 올렸습니다" : "모의계좌에 가진 종목이 있으면 그 일정을 맨 위에 올립니다"}</p></div>`;
}

async function renderCard(container, opts) {
  // 카드는 자료를 받은 뒤에 그린다 — 그사이 같은 칸에 그날 목록이 열렸으면(날짜를 바로 누름) 늦게 온 카드가 목록을
  // 덮어쓰지 않게 표를 단다(2026-10-06 브라우저 확인: 달을 넘기자마자 날짜를 누르면 목록이 0.2초 뒤 사라졌다)
  const token = `${Date.now()}-${Math.random()}`;
  container.dataset.cardToken = token;
  const html = await upcomingHtml(opts);
  if (container.dataset.cardToken !== token) return;
  container.innerHTML = html;
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

// ── 설명 창 ───────────────────────────────────────────────────────────────
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
  }
  const evs = Array.isArray(ev) ? ev : [ev];
  const how = [...new Set(evs.map(e => HOW[e.kind]).filter(Boolean))];
  m.querySelector(".cal-modal-body").innerHTML = evs.map(e => `<div class="cal-modal-ev">
      <div class="cal-modal-kind">${kindTag(e)}</div><h3 id="cal-modal-title">${escHtml(e.title)}</h3>
      <div class="cal-modal-meta"><div><span>날짜</span>${escHtml(e.date)} (${escHtml(e.weekday || WEEK[dow(e.date)])})${e.time ? ` ${escHtml(e.time)}` : ""}</div>
        <div><span>어떻게 정했나</span>${escHtml(e.confidence_label || "—")}</div>
        ${e.symbol ? `<div><span>종목</span>${escHtml(e.symbol)}</div>` : `<div><span>시장</span>${escHtml(e.market || "유가증권 · 코스닥")}</div>`}</div>
      ${e.detail ? `<p>${escHtml(e.detail)}</p>` : ""}
      ${e.symbol && e.symbol !== state.symbol ? `<button type="button" class="btn-secondary cal-only" data-sym="${escHtml(e.symbol)}">이 종목의 일정만 보기</button>` : ""}</div>`).join("") +
    `<p class="q-up-note">${how.map(escHtml).join("<br>")}</p>`;
  m.querySelectorAll(".cal-only").forEach(b => b.addEventListener("click", () => {
    m.classList.remove("open");
    state.symbol = b.dataset.sym;
    state.panel = null;
    if (document.querySelector(`.view[data-view="${VIEW}"]`)?.classList.contains("active")) renderCalendar();
    else navigate(VIEW);                           // 다른 화면의 카드에서 열었으면 일정 화면으로
  }));
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
  if (reload) {
    if (!root.innerHTML) root.innerHTML = `<p class="q-muted">불러오는 중…</p>`;
    const [mine, fresh] = await Promise.all([state.mine ? Promise.resolve(state.mine) : holdings(), loadMonth()]);
    state.mine = mine;
    if (!fresh) return;                            // 그사이 다른 달을 골랐다 — 그 달의 그리기가 따로 온다
  }
  const filters = Object.entries(KINDS).map(([k, [, label, t]]) =>
    `<button type="button" class="cal-filter cal-chip--${t} ${state.kinds.has(k) ? "on" : ""}" data-kind="${k}" aria-pressed="${state.kinds.has(k)}">${state.kinds.has(k) ? "✓ " : ""}${escHtml(label)}</button>`).join("");
  root.innerHTML = `<div class="dh-head"><div><h2>증시 일정</h2>
      <p class="q-muted">휴장 · 파생 만기 · 금통위 · FOMC · 보고서 기한 · 배당 · 주주총회 · 실적 발표 — 공휴일 정보 · 거래소 규칙 · 공식 일정 · 전자공시로 만든 일정</p></div></div>
    <div class="cal-layout ${state.panel ? "cal-day-open" : ""}"><div class="card cal-main">
      <div class="cal-filters">${filters}</div>
      <div class="cal-bar"><button type="button" class="cal-nav" data-step="-1" aria-label="지난달">‹</button>
        <strong class="cal-title">${state.y}년 ${state.m + 1}월</strong>
        <button type="button" class="cal-nav" data-step="1" aria-label="다음 달">›</button>
        <button type="button" class="btn-secondary cal-today-btn">오늘</button>
        <span class="q-muted cal-sum">한 달 ${num(monthTotal())}건 · ${state.symbol ? "종목 하나만 보는 중" : "칸의 숫자나 날짜를 누르면 그날 목록"}</span>
        ${state.symbol ? `<button type="button" class="cal-symbol">종목 ${escHtml(state.symbol)} 만 · 풀기 ✕</button>` : ""}</div>
      ${noticeHtml()}${gridHtml()}${listHtml()}
      <p class="q-up-note">거래일 달력은 ${escHtml(state.calendar?.end || "—")} 까지 있습니다(공휴일이 발표된 해까지) · 이름이 보이는 일정을 누르면 설명 창이 열립니다</p></div>
      <div class="cal-side"></div></div>`;
  root.querySelectorAll(".cal-nav[data-step]").forEach(b => b.addEventListener("click", () => {
    const d = new Date(Date.UTC(state.y, state.m + Number(b.dataset.step), 1));
    state.y = d.getUTCFullYear(); state.m = d.getUTCMonth(); state.panel = null; renderCalendar();
  }));
  root.querySelector(".cal-today-btn").addEventListener("click", () => {
    const t = todayIso(); state.y = +t.slice(0, 4); state.m = +t.slice(5, 7) - 1; state.panel = null; renderCalendar();
  });
  root.querySelectorAll(".cal-filters [data-kind]").forEach(b => b.addEventListener("click", () => {
    const k = b.dataset.kind;
    if (state.kinds.has(k) && state.kinds.size > 1) state.kinds.delete(k); else state.kinds.add(k);
    if (state.panel) {
      const left = [...state.panel.kinds].filter(x => state.kinds.has(x));
      state.panel.kinds = new Set(left.length ? left : dayCounts(state.panel.date).map(([x]) => x));
      state.panel.offset = 0;
    }
    renderCalendar(false);
    if (state.panel) loadDay();
  }));
  root.querySelector(".cal-symbol")?.addEventListener("click", () => { state.symbol = ""; state.panel = null; renderCalendar(); });
  // 날짜 · 칸의 숫자 → 그날 목록 / 이름이 보이는 일정 → 설명 창
  root.querySelectorAll(".cal-main [data-day]").forEach(b => b.addEventListener("click", ev => {
    ev.stopPropagation();
    openDay(b.dataset.day, b.dataset.kind || "");
  }));
  // 칸의 빈 곳 · 휴대폰 목록의 줄을 눌러도 그날 목록(단추를 누른 것은 위에서 멈춘다)
  root.querySelectorAll("[data-cell], [data-day-row]").forEach(c => c.addEventListener("click", () => openDay(c.dataset.cell || c.dataset.dayRow)));
  const named = {};
  for (const d of Object.keys(state.sumDays)) for (const e of marketEvents(d)) named[e.id] = e;
  for (const e of state.symEvents) named[e.id] = e;
  root.querySelectorAll(".cal-main [data-ev]").forEach(b => b.addEventListener("click", ev => {
    ev.stopPropagation();
    if (named[b.dataset.ev]) openEventModal(named[b.dataset.ev]);
  }));
  renderSide();
}

document.addEventListener("keydown", e => {
  if (e.key !== "Escape") return;
  const m = document.getElementById("cal-modal");
  if (m?.classList.contains("open")) { m.classList.remove("open"); return; }   // 설명 창이 먼저 — 그다음 그날 목록
  if (state.panel && document.querySelector(`.view[data-view="${VIEW}"]`)?.classList.contains("active")) closeDay();
});

/** main.js 의 화면 진입 훅 — 달력 화면이면 이번 달로 그리고, 카드를 붙이는 화면이면 오른쪽 카드를 붙인다. */
export function onCalendarViewActivated(view) {
  // 화면이 바뀌면 설명 창 · 그날 목록 서랍을 닫는다 — 열린 채 뒤로 가기 · 주소로 옮기면 다른 화면을 덮는다(2026-10-02 브라우저 확인)
  document.getElementById("cal-modal")?.classList.remove("open");
  if (view !== "market-calendar") state.panel = null;
  // 화면 키는 글자 그대로 — 화면 스캐너(scripts/view_scan.py)가 이 모양으로 「화면 ↔ 부르는 API」 를 잇는다
  if (view === "market-calendar") renderCalendar();
  // 카드를 붙이는 화면은 내 담당만(결정 기록 ②의 뒤집을 조건 — 주가 차트 · 모의투자는 화면 주인과 정한다)
  if (view === "macro-dashboard") mountSideCard(view);
}
