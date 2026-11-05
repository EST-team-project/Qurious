// 모의투자 화면(주식 · 코인 · 대체자산 · 계좌 현황) 표 위 줄 — 필터 칩 + 새로고침을 listbar.js 위에 얹은 제어기(2026-11-05).
// 배경: 「필터 · 새로고침 단추가 안 보인다」는 지적 → 화면 전수 점검. 퀀트 대시보드 관찰 목록 표(quant.js qdWatch*)와 같은 모양 · 같은 동작이다.
// 규칙:
//  1) 걸러 보는 것은 「이미 받은 줄 안」 이다 — 서버 인자는 늘리지 않는다. 그 한계는 안내 글에 밝힌다.
//  2) 새로고침은 「서버에서 다시 읽기」 뿐이다. 신호 · 백테스트를 새로 계산하지 않는다(그 길은 이 파일이 알지도 못한다).
//  3) 읽기에 실패하면 새로 읽은 시각을 찍지 않고 실패를 알린다 — 옛 값 위에 「다시 읽었습니다」 를 얹지 않는다.
//  4) 출처 · 구분 칩의 값은 응답에서 읽는다(지어내지 않는다). 눌러 둔 값이 새 응답에 없어도 칩을 남겨 풀 수 있게 한다.
import { listBarHtml, applyFilters, isAllowed, filterSummary, refreshStamp, bindListBar } from "/js/listbar.js";

const ALL = { value: "", label: "전체" };
const SOURCE_ORDER = ["WEB", "PAPER", "PINE", "SIM"];                 // 서버(stock_order_history)가 돌려주는 출처 — 이 순서 뒤에 모르는 값을 붙인다
const KIND_OPTIONS = [ALL, { value: "STOCK", label: "주식" }, { value: "CRYPTO", label: "코인" }, { value: "ALT", label: "대체자산" }];

/** 매수 · 매도 낱말을 BUY / SELL 로 맞춘다(주식 내역은 서버가 대문자로, 코인 · 대체자산은 저장된 글 그대로 준다). 그 밖은 빈 글. */
export function sideOf(type) {
  const t = String(type ?? "").trim().toUpperCase();
  return t === "BUY" || t === "SELL" ? t : "";
}

/** 24h 등락률 부호 → UP / DOWN. 0 이거나 숫자가 아니면 빈 글(상승도 하락도 아니다). */
export function directionOf(rate) {
  if (rate == null || rate === "") return "";
  const n = Number(rate);
  if (!Number.isFinite(n) || n === 0) return "";
  return n > 0 ? "UP" : "DOWN";
}

/** 값 목록에서 중복 · 빈 값을 빼고 order 순서(없는 값은 나온 순서)로 세운다. keep 은 지금 눌려 있는 값 — 응답에 없어도 남긴다. */
export function distinctOptions(values, order = [], keep = "") {
  const seen = [];
  for (const v of values) {
    const s = String(v ?? "");
    if (s && !seen.includes(s)) seen.push(s);
  }
  if (keep && !seen.includes(String(keep))) seen.push(String(keep));
  const rank = s => { const i = order.indexOf(s); return i < 0 ? order.length : i; };
  return seen.map((s, i) => ({ s, i })).sort((a, b) => rank(a.s) - rank(b.s) || a.i - b.i).map(x => x.s);
}

export const sideGroup = () => ({ key: "side", label: "매매", options: [ALL, { value: "BUY", label: "매수" }, { value: "SELL", label: "매도" }] });
export const kindGroup = () => ({ key: "kind", label: "구분", options: KIND_OPTIONS });
export const directionGroup = () => ({ key: "dir", label: "24h", options: [ALL, { value: "UP", label: "상승" }, { value: "DOWN", label: "하락" }] });

/** 출처 칩 — rows 의 source 값만(SIM 등). */
export function sourceGroup(rows, keep = "") {
  const vals = distinctOptions(rows.map(r => r.source), SOURCE_ORDER, keep);
  return { key: "source", label: "출처", options: [ALL, ...vals.map(v => ({ value: v, label: v }))] };
}

/** 구분 칩(대체자산) — rows 의 category 값만. order 는 상품 목록 응답에서 읽은 순서(선물 · 옵션 …)라 세 목록의 칩 순서가 같다. */
export function categoryGroup(rows, order = [], keep = "") {
  const vals = distinctOptions(rows.map(r => r.category), order, keep);
  return { key: "category", label: "구분", options: [ALL, ...vals.map(v => ({ value: v, label: v }))] };
}

/**
 * 목록 하나(표 또는 카드 묶음)의 제어기.
 * cfg:
 *   host        본문을 그릴 칸 id (칩 줄도 같은 칸 안 맨 위에 그린다 — barHost 가 없으면)
 *   barHost     (선택) 칩 줄만 따로 그릴 칸 id — 본문 칸이 스크롤 상자 · 격자라 줄이 같이 흘러가면 안 될 때
 *   label       칩 줄 접근성 이름
 *   unit        셈 단위(줄 · 종목 · 상품)
 *   groups      (rows, filters) => 칩 묶음 배열 — 값(value)은 제어기가 채운다
 *   getters     { key: row => 값 }
 *   cap         (선택) 보이는 줄 상한 — 거른 뒤에 자른다
 *   refresh     새로고침 단추를 둘지(기본 true)
 *   limitNote   (선택) 한계 안내 — 글 또는 (rows, filtered, meta) => 글
 *   meaning     새로고침 뒤 안내 앞부분(기본 「서버에서 다시 읽었습니다」) · tail 뒤에 덧붙이는 설명
 *   load        async () => { rows, meta }  — 서버에서 읽는다(실패하면 throw)
 *   head        (선택) (meta, ctx) => 표 위 HTML (예: 매수 원금 한 줄)
 *   body        (shownRows, ctx) => 표 HTML   ctx = { rows, filtered, filters, meta }
 *   after       (선택) (hostEl, ctx) => 그린 뒤 줄 안 단추 연결
 *   onData      (선택) (meta, rows) => 읽은 직후 곁 칸 갱신(예: 보유 현금)
 *   onError     (선택) (error) => 읽기 실패 알림
 *   alsoOnRefresh (선택) async () => 새로고침 때만 곁에서 같이 읽을 것(실패해도 표는 그린다)
 * deps: { esc, byId, now? }
 */
export function createListPanel(cfg, deps) {
  const { esc, byId } = deps;
  const clock = deps.now || (() => new Date());
  const st = { rows: [], meta: null, filters: {}, note: "", error: "", seq: 0, busy: false };
  const unit = cfg.unit || "줄";
  const rootId = () => cfg.barHost || cfg.host;

  // 고를 값이 「전체」 하나뿐인 묶음(예: 내역이 비어 출처 값이 없다)은 칩 줄에서 뺀다 — 눌러 둔 값이 있으면 그 값이 선택지에 남아 있어 빠지지 않는다
  const groupsNow = () => (cfg.groups ? cfg.groups(st.rows, st.filters) : []).filter(g => g.options.length > 1).map(g => ({ ...g, value: st.filters[g.key] ?? "" }));

  function paint() {
    const host = byId(cfg.host);
    if (!host) return;
    const groups = groupsNow();
    const filtered = applyFilters(st.rows, st.filters, cfg.getters || {});
    const shown = cfg.cap ? filtered.slice(0, cfg.cap) : filtered;
    const ctx = { rows: st.rows, filtered, filters: st.filters, meta: st.meta };
    const limit = typeof cfg.limitNote === "function" ? cfg.limitNote(st.rows, filtered, st.meta) : (cfg.limitNote || "");
    const note = [st.note, filterSummary(groups, st.filters, st.rows.length, filtered.length, unit), limit].filter(Boolean).join(" · ");
    const bar = listBarHtml(esc, { groups, refresh: cfg.refresh !== false, note, label: cfg.label });
    let body;
    if (st.error && !st.rows.length) body = `<div class="col-span-full text-sm text-red-500">${esc(st.error)}</div>`;
    else if (st.rows.length && !filtered.length) body = `<div class="col-span-full text-sm">이 조건에 맞는 ${esc(unit)}이 없습니다. 필터를 풀어 보세요.</div>`;
    else body = (cfg.head && st.meta != null ? cfg.head(st.meta, ctx) : "") + cfg.body(shown, ctx);
    const barEl = cfg.barHost ? byId(cfg.barHost) : null;
    if (barEl) { barEl.innerHTML = bar; host.innerHTML = body; } else host.innerHTML = bar + body;
    bind();
    setBusy(st.busy);
    if (cfg.after) cfg.after(host, ctx);
  }

  function setBusy(on) {
    const root = byId(rootId());
    const btn = root && root.querySelector ? root.querySelector("button[data-lb-refresh]") : null;
    if (btn) { btn.disabled = !!on; btn.setAttribute("aria-busy", String(!!on)); }
  }

  function bind() {
    const root = byId(rootId());
    bindListBar(root, { onFilter: (key, value) => setFilter(key, value, true), onRefresh: () => { refresh(); } });
  }

  /** 칩 값을 바꾸고 받아 둔 줄을 다시 거른다(서버를 부르지 않는다). 허용 밖 낱말은 무시. */
  function setFilter(key, value, keepFocus = false) {
    if (!isAllowed(groupsNow(), key, value)) return false;
    st.filters = { ...st.filters, [key]: value };
    paint();
    if (keepFocus) {                                                  // 다시 그리면 눌렀던 칩이 사라져 키보드 초점이 날아간다 — 같은 칩에 되돌린다
      const root = byId(rootId());
      const chips = root && root.querySelectorAll ? Array.from(root.querySelectorAll("button[data-lb-filter]")) : [];
      const hit = chips.find(b => b.dataset.lbFilter === key && b.dataset.value === String(value));
      if (hit && hit.focus) hit.focus();
    }
    return true;
  }

  /** 서버에서 읽어 그린다. 성공 true · 실패 false(최신 읽기에만) · 더 새 읽기가 있으면 true(그쪽이 그린다). */
  async function load({ stamp = false } = {}) {
    const mine = ++st.seq;
    try {
      const r = await cfg.load();
      if (mine !== st.seq) return true;
      st.rows = r.rows || [];
      st.meta = r.meta == null ? null : r.meta;
      st.error = "";
      st.note = stamp ? `${refreshStamp(cfg.meaning || "서버에서 다시 읽었습니다", clock())}${cfg.tail ? ` — ${cfg.tail}` : ""}` : "";
      if (cfg.onData) { try { cfg.onData(st.meta, st.rows); } catch { /* 곁 칸 갱신 실패가 표를 막지 않는다 */ } }
      paint();
      return true;
    } catch (e) {
      if (mine !== st.seq) return true;
      st.error = (e && e.message) || "읽지 못했습니다";
      st.note = st.rows.length ? `다시 읽지 못했습니다(${st.error}) — 이전에 받은 값을 보입니다` : "";
      paint();
      if (cfg.onError) { try { cfg.onError(e); } catch { /* 알림 실패는 무시 */ } }
      return false;
    }
  }

  /** 새로고침 단추 — 받는 중 다시 누르면 무시. 걸어 둔 필터는 그대로. */
  async function refresh() {
    if (st.busy) return false;
    st.busy = true;
    setBusy(true);
    const root = byId(rootId());
    const noteEl = root && root.querySelector ? root.querySelector("[data-lb-note]") : null;
    if (noteEl) noteEl.textContent = "서버에서 다시 읽는 중…";
    try {
      const extra = cfg.alsoOnRefresh ? Promise.resolve().then(cfg.alsoOnRefresh).catch(() => { /* 곁 칸은 실패해도 표는 읽는다 */ }) : null;
      const ok = await load({ stamp: true });
      if (extra) await extra;
      return ok;
    } finally {
      st.busy = false;
      setBusy(false);
    }
  }

  return { load, refresh, setFilter, state: () => ({ rows: st.rows.slice(), filters: { ...st.filters }, note: st.note, error: st.error, busy: st.busy }) };
}

/**
 * 한 단추가 여러 읽기를 부르는 새로고침(계좌 현황) — tasks 는 각각 성공 true / 실패 false 를 돌려주는 함수.
 * 읽는 중 다시 누르면 무시하고, 하나라도 실패하면 새로 읽은 시각 대신 어느 쪽이 실패했는지 알린다.
 * setNote(text) · setBusy(on) 은 화면이 준다.
 */
export function createRefreshGroup({ tasks, setNote, setBusy, meaning = "서버에서 다시 읽었습니다", tail = "", now = () => new Date() }) {
  let busy = false;
  return async function run() {
    if (busy) return false;
    busy = true;
    if (setBusy) setBusy(true);
    if (setNote) setNote("서버에서 다시 읽는 중…");
    try {
      const results = await Promise.all(tasks.map(t => Promise.resolve().then(t).then(v => v !== false, () => false)));
      const failed = results.filter(ok => !ok).length;
      if (setNote) setNote(failed
        ? `${failed}곳은 다시 읽지 못했습니다 — 읽은 곳만 새 값입니다`
        : `${refreshStamp(meaning, now())}${tail ? ` — ${tail}` : ""}`);
      return failed === 0;
    } finally {
      busy = false;
      if (setBusy) setBusy(false);
    }
  };
}
