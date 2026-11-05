// 화면 4곳의 목록 위 줄 — LEAN 실행 이력 · 감사 로그 · 업종별 카드 + 줄 만들기 도우미(2026-11-05 화면 전수 점검 4~7번).
// 배경: 「필터 · 새로고침 단추가 안 보인다」 지적 → 전수 점검. 퀀트 관찰 목록 표(quant.js qdWatch*) · 모의투자(paperlists.js) 와 같은 모양 · 같은 동작이다.
// 규칙(paperlists.js 와 같다)
//  1) 걸러 보는 것은 「이미 받은 줄 안」 이다 — 서버 인자는 늘리지 않는다. 한계는 안내 글에 밝힌다.
//  2) 새로고침은 「서버에서 다시 읽기」 뿐이다 — LEAN 을 다시 돌리지 않고 신호 · 백테스트를 새로 계산하지 않는다(그 길은 이 파일이 알지도 못한다).
//  3) 칩의 값은 응답에서 읽는다(지어내지 않는다). 눌러 둔 값이 새 응답에 없어도 칩을 남겨 풀 수 있게 한다.
//  4) 읽기에 실패하면 새로 읽은 시각을 찍지 않고 실패를 알린다.
// 이 파일은 DOM 을 직접 만지지 않는다(예외: ensureBarHost · createSectorPanel 의 byId 로 받은 칸) — 설정 만들기 · 걸러내기 · 줄 HTML 이 순수 함수라 node 로 시험한다(tests/test_listbar_misc.py).
import { distinctOptions } from "/js/paperlists.js";
import { listBarHtml, isAllowed, refreshStamp, bindListBar } from "/js/listbar.js";

const ALL_OPT = { value: "", label: "전체" };

/** 본문 칸 앞에 칩 줄 칸을 JS 가 만든다(app.html 을 건드리지 않는다). 본문 칸이 스크롤 상자라 줄이 같이 흘러가면 안 될 때 쓴다. 이미 있으면 그대로. */
export function ensureBarHost(doc, hostId, barId) {
  const host = doc.getElementById(hostId);
  if (!host || !host.parentNode) return null;
  let bar = doc.getElementById(barId);
  if (!bar) {
    bar = doc.createElement("div");
    bar.id = barId;
    host.parentNode.insertBefore(bar, host);
  }
  return bar;
}

/** 값 → 칩 목록. labels 는 값 → 보여 줄 글 기억(눌러 둔 값이 새 응답에서 사라져도 글을 잃지 않는다). */
function optionsOf(rows, valueOf, labelOf, keep, order, labels) {
  for (const r of rows) {
    const v = String(valueOf(r) ?? "");
    if (v && labelOf) labels.set(v, String(labelOf(r) || v));
  }
  return distinctOptions(rows.map(valueOf), order, keep).map(v => ({ value: v, label: labels.get(v) || v }));
}

// ── 4. quant-lean · LEAN 백테스트 실행 이력 ──────────────────────────────────────────────
export const LEAN_HISTORY_LIMIT = 15;                     // paper.js 가 부르는 `/api/backtests/lean/history?limit=15`

/** 전략 · 티커 칩 — 값은 응답(strategy · strategy_label · ticker)에서 읽는다. */
export function leanGroups(rows, filters, labels = new Map()) {
  const f = filters || {};
  const strategy = optionsOf(rows, r => r.strategy, r => r.strategy_label, f.strategy, [], labels);
  const ticker = distinctOptions(rows.map(r => r.ticker), [], f.ticker).map(v => ({ value: v, label: v }));
  return [
    { key: "strategy", label: "전략", options: [ALL_OPT, ...strategy] },
    { key: "ticker", label: "티커", options: [ALL_OPT, ...ticker] },
  ];
}

/** 이력 표 — 열 · 모양은 옛 loadLeanHistory 그대로. h: { esc, fmtPct, signCls, emptyRow, fmtTime? } */
export function leanHistoryTable(rows, h) {
  const { esc } = h;
  const when = h.fmtTime || (v => new Date(v).toLocaleString("ko-KR"));
  const body = rows.length
    ? rows.map(r => `<tr><td class="text-xs">${esc(when(r.created_at))}</td><td>${esc(r.ticker)}</td><td class="text-xs">${esc(r.strategy_label)}</td><td class="text-xs">${esc(r.start_date)}~${esc(r.end_date)}</td>`
      + `<td style="text-align:right" class="${esc(h.signCls(r.strategy_return_pct))}">${esc(h.fmtPct(r.strategy_return_pct))}</td><td style="text-align:right">${esc(r.max_drawdown_pct)}%</td><td style="text-align:right">${esc(r.sharpe_ratio)}</td>`
      + `<td>${r.lean_ok ? `<span class="badge-buy">LEAN</span>` : `<span class="badge-hold">pandas</span>`}</td></tr>`).join("")
    : h.emptyRow(8, "실행 이력이 없습니다.");
  return `<table><thead><tr><th>실행 시각</th><th>티커</th><th>전략</th><th>기간</th><th style="text-align:right">수익률</th><th style="text-align:right">MDD</th><th style="text-align:right">샤프</th><th>엔진</th></tr></thead><tbody>${body}</tbody></table>`;
}

/** createListPanel 설정 — h: leanHistoryTable 의 h + load(): 서버에서 { runs } 를 읽는 함수. */
export function leanHistoryCfg(h) {
  const labels = new Map();
  return {
    host: "ql-history", barHost: "ql-history-bar", label: "LEAN 실행 이력 필터", unit: "건",
    groups: (rows, filters) => leanGroups(rows, filters, labels),
    getters: { strategy: r => r.strategy ?? "", ticker: r => r.ticker ?? "" },
    limitNote: rows => `최근 ${LEAN_HISTORY_LIMIT}건까지만 받습니다 — 받은 ${rows.length}건 안에서 거릅니다`,
    meaning: "서버에서 이력을 다시 읽었습니다",
    tail: "저장된 실행 기록만 읽으며 LEAN 을 다시 돌리지 않습니다",
    load: async () => { const d = await h.load(); return { rows: (d && d.runs) || [], meta: null }; },
    body: rows => leanHistoryTable(rows, h),
  };
}

// ── 6. sysadmin-logs · 감사 로그 ─────────────────────────────────────────────────────────
export const AUDIT_LIMIT = 100;                           // sysadmin.js 가 서버에 보내는 limit

/** 이벤트 유형 칩 — 응답 events 의 event_type 그대로, 많이 나온 유형이 앞. */
export function auditGroups(rows, filters) {
  const count = new Map();
  for (const r of rows) { const t = String(r.event_type ?? ""); if (t) count.set(t, (count.get(t) || 0) + 1); }
  const order = [...count.keys()].sort((a, b) => count.get(b) - count.get(a));
  const types = distinctOptions(rows.map(r => r.event_type), order, (filters || {}).type).map(v => ({ value: v, label: v }));
  return [{ key: "type", label: "이벤트", options: [ALL_OPT, ...types] }];
}

/** 로그 한 줄 — 옛 loadAuditLog 의 HTML 그대로. */
export function auditRowHtml(ev, esc) {
  return `<div class="py-1 border-b" style="border-color:var(--border);">
        <span style="color:var(--text-mute);">${esc(ev.created_at || "")}</span>
        · <span style="color:var(--accent);font-weight:600;">${esc(ev.event_type || "")}</span>
        · <span style="color:var(--text-dim);">user=${esc(ev.user_id || "-")}</span>
        <span style="color:var(--text-mute);">${esc(JSON.stringify(ev.payload || {}))}</span>
      </div>`;
}

/** createListPanel 설정 — load(): 입력 칸 2개로 서버에서 { events } 를 읽는 함수(sysadmin.js 가 준다). */
export function auditCfg({ esc, load }) {
  return {
    host: "audit-log", barHost: "audit-log-bar", label: "감사 로그 이벤트 필터", unit: "건",
    groups: (rows, filters) => auditGroups(rows, filters),
    getters: { type: r => r.event_type ?? "" },
    limitNote: rows => `서버가 입력 칸 조건으로 먼저 거른 최근 ${AUDIT_LIMIT}건까지만 받습니다 — 받은 ${rows.length}건 안에서 거릅니다`,
    meaning: "서버에서 로그를 다시 읽었습니다",
    tail: "위 입력 칸 조건 그대로 읽습니다",
    load: async () => { const d = await load(); return { rows: (d && d.events) || [], meta: null }; },
    body: rows => (rows.length ? rows.map(ev => auditRowHtml(ev, esc)).join("") : "<div class='text-slate-400'>표시할 감사 로그가 없습니다.</div>"),
  };
}

// ── 7. company-sector · 업종별 PER · PBR 카드 ────────────────────────────────────────────
export const SECTOR_SORTS = [
  { value: "", label: "종목 수 순" },                         // 서버가 준 순서 그대로(종목 수 많은 순)
  { value: "per_asc", label: "PER 낮은 순" }, { value: "per_desc", label: "PER 높은 순" },
  { value: "pbr_asc", label: "PBR 낮은 순" }, { value: "pbr_desc", label: "PBR 높은 순" },
  { value: "name", label: "이름순" },
];

const median = (g, k) => (g && g[k] && typeof g[k].median === "number" && Number.isFinite(g[k].median) ? g[k].median : null);

/** 업종명 검색 + 정렬 — 이미 받은 groups 를 거를 뿐 값을 셈하지 않는다. 중앙값이 없는(null) 업종은 정렬 어느 쪽이든 맨 뒤. */
export function sectorView(groups, { q = "", sort = "" } = {}) {
  const needle = String(q || "").trim().toLowerCase();
  const kept = (groups || []).filter(g => !needle || String(g.name || "").toLowerCase().includes(needle));
  const by = { per_asc: ["per", 1], per_desc: ["per", -1], pbr_asc: ["pbr", 1], pbr_desc: ["pbr", -1] }[sort];
  const idx = new Map(kept.map((g, i) => [g, i]));
  if (by) {
    return kept.slice().sort((a, b) => {
      const x = median(a, by[0]), y = median(b, by[0]);
      if (x == null && y == null) return idx.get(a) - idx.get(b);
      if (x == null) return 1;
      if (y == null) return -1;
      return (x - y) * by[1] || idx.get(a) - idx.get(b);
    });
  }
  if (sort === "name") return kept.slice().sort((a, b) => String(a.name || "").localeCompare(String(b.name || ""), "ko") || idx.get(a) - idx.get(b));
  return kept;
}

/** 업종 화면의 도구 칸(검색 칸 + 칩 줄 칸)을 카드 칸 앞에 만든다. 이미 있으면 그대로. */
export function ensureSectorTools(doc, cardsId, searchId, barId) {
  const cards = doc.getElementById(cardsId);
  if (!cards || !cards.parentNode) return null;
  let tools = doc.getElementById(`${barId}-tools`);
  if (!tools) {
    tools = doc.createElement("div");
    tools.id = `${barId}-tools`;
    tools.innerHTML = `<div class="qd-frow"><label for="${searchId}" class="text-xs font-semibold" style="color:var(--text-dim);">업종명 검색</label>`
      + `<input id="${searchId}" class="input" type="search" style="max-width:240px;" placeholder="예: 제조, 금융" aria-label="업종명 검색" autocomplete="off" /></div>`
      + `<div id="${barId}"></div>`;
    cards.parentNode.insertBefore(tools, cards);
  }
  return tools;
}

/**
 * 업종 카드의 제어기 — 검색 칸(바깥에 두어 다시 그려도 입력이 안 사라진다) + 정렬 칩 + 새로고침.
 * cfg: { barHost, cardsHost, noteHost, searchId, load: async () => data, renderCards(data, esc), renderNote(data, esc), message(text, color) , loadingText }
 * deps: { esc, byId, now? }
 */
export function createSectorPanel(cfg, deps) {
  const { esc, byId } = deps;
  const clock = deps.now || (() => new Date());
  const st = { data: null, q: "", sort: "", note: "", error: "", seq: 0, busy: false };

  const groupsNow = () => [{ key: "sort", label: "정렬", options: SECTOR_SORTS, value: st.sort }];

  function paint() {
    const barEl = byId(cfg.barHost), cardsEl = byId(cfg.cardsHost);
    const all = (st.data && st.data.groups) || [];
    const view = sectorView(all, st);
    const sortLabel = (SECTOR_SORTS.find(o => o.value === st.sort) || {}).label;
    const cond = [String(st.q).trim() ? `업종명 「${String(st.q).trim()}」` : "", st.sort ? sortLabel : ""].filter(Boolean);
    const summary = cond.length ? `조건 ${cond.join(" · ")} — 받은 ${all.length}곳 중 ${view.length}곳` : "";
    const limit = st.data ? "받은 업종 전부 안에서 거릅니다" : "";
    const note = [st.note, summary, limit].filter(Boolean).join(" · ");
    if (barEl) {
      barEl.innerHTML = listBarHtml(esc, { groups: groupsNow(), refresh: true, note, label: "업종 정렬" });
      bindListBar(barEl, { onFilter: (key, value) => setSort(key, value), onRefresh: () => { refresh(); } });
      setBusy(st.busy);
    }
    if (!cardsEl) return;
    if (!st.data) cardsEl.innerHTML = st.error ? cfg.message(st.error, "var(--red)") : cfg.message(cfg.loadingText || "불러오는 중…");
    else if (all.length && !view.length) cardsEl.innerHTML = cfg.message("이 조건에 맞는 업종이 없습니다. 검색어를 지워 보세요.");
    else cardsEl.innerHTML = cfg.renderCards({ ...st.data, groups: view }, esc);
  }

  function setBusy(on) {
    const barEl = byId(cfg.barHost);
    const btn = barEl && barEl.querySelector ? barEl.querySelector("button[data-lb-refresh]") : null;
    if (btn) { btn.disabled = !!on; btn.setAttribute("aria-busy", String(!!on)); }
  }

  function setSort(key, value) {
    if (!isAllowed(groupsNow(), key, value)) return false;
    st.sort = value;
    paint();
    const barEl = byId(cfg.barHost);
    const chips = barEl && barEl.querySelectorAll ? Array.from(barEl.querySelectorAll("button[data-lb-filter]")) : [];
    const hit = chips.find(b => b.dataset.lbFilter === key && b.dataset.value === String(value));
    if (hit && hit.focus) hit.focus();                       // 다시 그리면 눌렀던 칩이 사라져 키보드 초점이 날아간다
    return true;
  }

  function setQuery(text) { st.q = String(text ?? ""); paint(); }

  async function load({ stamp = false } = {}) {
    const mine = ++st.seq;
    if (!st.data) paint();                                    // 처음이면 「계산하는 중」 글
    try {
      const data = await cfg.load();
      if (mine !== st.seq) return true;
      st.data = data; st.error = "";
      st.note = stamp ? `${refreshStamp(cfg.meaning || "서버에서 다시 읽었습니다", clock())}${cfg.tail ? ` — ${cfg.tail}` : ""}` : "";
      const noteEl = cfg.noteHost ? byId(cfg.noteHost) : null;
      if (noteEl && cfg.renderNote) noteEl.innerHTML = cfg.renderNote(data, esc);
      paint();
      return true;
    } catch (e) {
      if (mine !== st.seq) return true;
      st.error = (e && e.message) || "업종별 지표를 받지 못했습니다.";
      st.note = st.data ? `다시 읽지 못했습니다(${st.error}) — 이전에 받은 값을 보입니다` : "";
      paint();
      return false;
    }
  }

  async function refresh() {
    if (st.busy) return false;
    st.busy = true;
    setBusy(true);
    const barEl = byId(cfg.barHost);
    const noteEl = barEl && barEl.querySelector ? barEl.querySelector("[data-lb-note]") : null;
    if (noteEl) noteEl.textContent = "서버에서 다시 읽는 중…";
    try { return await load({ stamp: true }); } finally { st.busy = false; setBusy(false); }
  }

  const input = cfg.searchId ? byId(cfg.searchId) : null;
  if (input && input.addEventListener) input.addEventListener("input", () => setQuery(input.value));

  return { load, refresh, setSort, setQuery, state: () => ({ data: st.data, q: st.q, sort: st.sort, note: st.note, error: st.error, busy: st.busy }) };
}

// 표 위 안내 글 한 곳 — 세 화면(지표 비교 · 증시 일정 · 업종)이 같은 문장을 쓴다. 서버 저장본이 끼는 곳은 그 사실을 밝힌다.
export function refreshNoteText(tail, now = new Date()) {
  return `${refreshStamp("서버에서 다시 읽었습니다", now)}${tail ? ` — ${tail}` : ""}`;
}

