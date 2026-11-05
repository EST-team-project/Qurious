// 증권사 실주문 · 알림 발송 이력 · 리밸런싱 이력 · TradingView 신호 · 데이터 관제 표의 필터 칩 정의 — 순수 함수만 둔다(DOM 을 만지지 않는다 · 2026-11-05).
// 배경: 「필터 · 새로고침 단추가 안 보인다」 지적 → 화면 전수 점검(docs/_local/화면-필터-새로고침-점검-2026-11-05.md)에서 이 다섯 화면이 남았다.
// 규칙:
//  1) 걸러 보는 것은 「브라우저가 이미 받은 줄 안」 이다 — 서버 인자는 늘리지 않는다. 서버가 자르는 크기(아래 *_LIMIT)를 안내 글에서 숨기지 않는다.
//  2) 칩 낱말은 응답에서 읽는다(없는 상태를 지어내지 않는다). 눌러 둔 값이 새 응답에 없어도 칩을 남겨 풀 수 있게 한다(paperlists.js 가 한다).
//  3) 새로고침은 「서버에서 다시 읽기」 뿐이다 — 주문 · 취소 · 발송 · 저장 · 실행 · 다시 계산을 이 파일은 알지도 못한다.
//  4) 표 모양(HTML)은 각 화면 파일이 그린다 — 여기서는 칩 · 걸러내기 · 안내 글만 정한다.
import { createListPanel, distinctOptions } from "/js/paperlists.js";
import { listBarHtml, applyFilters, filterSummary } from "/js/listbar.js";

const ANY = { value: "", label: "전체" };

// 화면이 서버에 요청하는 줄 수 — 안내 글의 숫자와 같아야 한다(화면 파일이 이 값으로 주소를 만든다).
export const LIVE_ORDERS_LIMIT = 30;
export const NOTI_HISTORY_LIMIT = 30;
export const REBAL_RUNS_LIMIT = 20;
export const REBAL_CASHFLOWS_LIMIT = 20;
export const TV_SIGNALS_LIMIT = 30;
export const TV_COMPARISONS_LIMIT = 15;

/** 「받은 N줄 안에서만 거릅니다(서버가 최근 M줄까지 보냅니다)」 — 서버가 자르는 화면의 한계 안내. */
export function limitText(received, cap, unit = "줄") {
  return `받은 ${received}${unit} 안에서만 거릅니다(서버가 최근 ${cap}${unit}까지 보냅니다)`;
}

/** 값 하나를 응답에서 읽은 낱말로 — 비어 있으면 빈 글. */
const str = v => (v == null ? "" : String(v));

/**
 * createListPanel 에 「한 줄이 여러 값을 가질 때 하나라도 맞으면」 을 더한 것(리밸런싱 한 회차에 트리거가 둘일 수 있다).
 * cfg.multi = { key: row => [값…] } · cfg.limitNote 는 (rows, filtered, meta, filters) 로 지금 걸린 조건도 받는다.
 * createListPanel 은 칩 묶음 함수를 거르기 직전에 부르므로 거기서 지금 조건을 받아 둔다(tests/test_listbar_screens.py 가 이 순서를 굳힌다).
 */
export function createScreenPanel(cfg, deps) {
  let current = {};
  const getters = { ...(cfg.getters || {}) };
  for (const [key, valuesOf] of Object.entries(cfg.multi || {})) {
    getters[key] = row => {
      const want = current[key];
      return want !== "" && want != null && valuesOf(row).includes(want) ? want : "";
    };
  }
  const limitNote = typeof cfg.limitNote === "function" ? (rows, filtered, meta) => cfg.limitNote(rows, filtered, meta, current) : cfg.limitNote;
  return createListPanel({
    ...cfg, getters, limitNote, multi: undefined,
    groups: (rows, filters) => { current = filters || {}; return cfg.groups(rows, filters); },
  }, deps);
}

/** 화면에 이미 있는 새로고침 단추를 패널에 잇는다 — 받는 중에는 눌리지 않게 하고, 한 번만 잇는다. */
export function bindRefreshButton(btn, panel) {
  if (!btn || btn.__lbRefresh) return;
  btn.__lbRefresh = true;
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    btn.setAttribute("aria-busy", "true");
    try { await panel.refresh(); } finally { btn.disabled = false; btn.setAttribute("aria-busy", "false"); }
  });
}

// ── 1. KIS 실주문 현황 (settings · GET /api/quant/live-orders 의 orders) ────────────────────────
// 상태 낱말은 증권사 주문 추적 상태(app/routes/kis_monitor.py ORDER_STATUSES). 칩은 「미체결 · 체결 · 취소 · 그 밖」 네 갈래이고, 응답에 있는 갈래만 나온다.
const LIVE_BUCKETS = [
  { value: "open", label: "미체결", codes: ["PENDING", "ACCEPTED", "PARTIALLY_FILLED"] },
  { value: "filled", label: "체결", codes: ["FILLED"] },
  { value: "cancelled", label: "취소", codes: ["CANCEL_REQUESTED", "CANCELLED"] },
  { value: "other", label: "그 밖", codes: [] },
];
export function liveStatusBucket(order) {
  const code = str(order && order.status);
  const hit = LIVE_BUCKETS.find(b => b.codes.includes(code));
  return hit ? hit.value : "other";
}
/** 표가 환경을 보이는 규칙과 같다 — real 이면 실전, 그 밖은 모의. */
export const liveEnvironment = order => (order && order.environment === "real" ? "real" : "paper");
/** 표가 구분을 보이는 규칙과 같다 — BUY 면 매수, 그 밖은 매도. */
export const liveSide = order => (order && order.side === "BUY" ? "BUY" : "SELL");

export function liveOrderGroups(rows) {
  const present = new Set(rows.map(liveStatusBucket));
  return [
    { key: "status", label: "상태", options: [ANY, ...LIVE_BUCKETS.filter(b => present.has(b.value)).map(({ value, label }) => ({ value, label }))] },
    { key: "env", label: "환경", options: [ANY, { value: "real", label: "실전" }, { value: "paper", label: "모의" }] },
    { key: "side", label: "매매", options: [ANY, { value: "BUY", label: "매수" }, { value: "SELL", label: "매도" }] },
  ];
}
export const LIVE_GETTERS = { status: liveStatusBucket, env: liveEnvironment, side: liveSide };
export const LIVE_STATUS_HELP = "미체결 = 접수 · 대기 · 일부 체결(잔량이 남은 주문) / 취소 = 취소 요청 · 취소 완료 / 그 밖 = 거부 · 오류 · 확인 불가";
export const liveLimitNote = (rows, filtered, meta, filters = {}) =>
  [limitText(rows.length, LIVE_ORDERS_LIMIT, "건"), "서버가 2분마다 증권사 체결을 확인해 저장한 값을 읽습니다", filters.status ? LIVE_STATUS_HELP : ""].filter(Boolean).join(" · ");
export const LIVE_TAIL = "저장된 주문 상태를 다시 읽은 것이고 증권사에 새로 묻거나 주문 · 취소를 하지 않습니다";

// ── 2. 알림 발송 이력 (settings · GET /api/notification/history 의 events) ──────────────────────
// 「실패 · 결과 불명」 은 화면이 이미 빨강으로 보이는 두 낱말(failed · sending)이다.
export const NOTI_BAD_STATUSES = ["failed", "sending"];
export const notiIsBad = ev => NOTI_BAD_STATUSES.includes(str(ev && ev.delivery_status));

export function notiGroups(events, filters = {}) {
  const labelOf = new Map();
  for (const ev of events) {
    const s = str(ev && ev.delivery_status);
    if (s && !labelOf.has(s)) labelOf.set(s, str(ev.status_label) || s);
  }
  const statuses = distinctOptions([...labelOf.keys()], ["failed", "sending", "partial", "delivered", "no_channels"], filters.state);
  const groups = [{ key: "bad", label: "결과", options: [ANY, { value: "bad", label: "실패 · 결과 불명만" }] }];
  if (statuses.length > 1) groups.push({ key: "state", label: "전달 상태", options: [ANY, ...statuses.map(s => ({ value: s, label: labelOf.get(s) || s }))] });
  return groups;
}
export const NOTI_GETTERS = { bad: ev => (notiIsBad(ev) ? "bad" : ""), state: ev => str(ev && ev.delivery_status) };
export const notiLimitNote = rows => `${limitText(rows.length, NOTI_HISTORY_LIMIT, "건")} · 「결과 불명」 은 보냈는지 확인하지 못한 건이라 자동으로 다시 보내지 않습니다`;
export const NOTI_TAIL = "저장된 발송 이력을 다시 읽은 것이고 알림을 새로 보내지 않습니다";

// ── 3. 리밸런싱 실행 이력 · 입출금 이력 (rebalance · GET /api/rebalance/runs · cashflows) ───────────
export const REBAL_STATUS_LABEL = {
  proposed: "제안", scheduled: "시가 체결 대기", executed: "체결", partial: "부분 체결", open_not_tradable: "미체결",
  cancelled: "취소", skipped: "생략", failed: "실패",
};
const REBAL_STATUS_ORDER = ["proposed", "scheduled", "executed", "partial", "open_not_tradable", "cancelled", "skipped", "failed"];
export const REBAL_TRIGGER_LABEL = { TIME: "시간", DRIFT: "이탈률", CASHFLOW: "현금흐름", MANUAL: "수동" };
const REBAL_TRIGGER_ORDER = Object.keys(REBAL_TRIGGER_LABEL);
export const REBAL_KIND_LABEL = { DEPOSIT: "입금", WITHDRAW: "출금", DIVIDEND: "배당" };

/** 화면의 배지와 같은 규칙 — 장이 열리지 않아 취소된 예약은 status 와 무관하게 「미체결」 로 보인다. */
export const rebalStatus = run => (run && run.context && run.context.cancel_reason === "open_not_tradable" ? "open_not_tradable" : str(run && run.status));
/** 한 회차의 트리거들 — triggers 가 있으면 그것, 없으면 trigger 하나. */
export const rebalTriggers = run => {
  const list = Array.isArray(run && run.triggers) && run.triggers.length ? run.triggers : [run && run.trigger];
  return list.map(str).filter(Boolean);
};

export function rebalRunGroups(runs, filters = {}) {
  const statuses = distinctOptions(runs.map(rebalStatus), REBAL_STATUS_ORDER, filters.status);
  const triggers = distinctOptions(runs.flatMap(rebalTriggers), REBAL_TRIGGER_ORDER, filters.trigger);
  return [
    { key: "status", label: "상태", options: [ANY, ...statuses.map(v => ({ value: v, label: REBAL_STATUS_LABEL[v] || v }))] },
    { key: "trigger", label: "트리거", options: [ANY, ...triggers.map(v => ({ value: v, label: REBAL_TRIGGER_LABEL[v] || v }))] },
  ];
}
export const REBAL_RUN_GETTERS = { status: rebalStatus };
export const REBAL_RUN_MULTI = { trigger: rebalTriggers };
export const rebalRunLimitNote = rows => `${limitText(rows.length, REBAL_RUNS_LIMIT, "건")} · 한 회차에 트리거가 둘이면 둘 중 어느 쪽 칩으로도 보입니다`;
export const REBAL_RUN_TAIL = "저장된 실행 이력을 다시 읽은 것이고 리밸런싱을 새로 계산 · 실행하지 않습니다";

export function rebalCashflowGroups(events, filters = {}) {
  const kinds = distinctOptions([...Object.keys(REBAL_KIND_LABEL), ...events.map(e => str(e && e.kind))], Object.keys(REBAL_KIND_LABEL), filters.kind);
  return [{ key: "kind", label: "구분", options: [ANY, ...kinds.map(v => ({ value: v, label: REBAL_KIND_LABEL[v] || v }))] }];
}
export const REBAL_CASHFLOW_GETTERS = { kind: e => str(e && e.kind) };
export const rebalCashflowLimitNote = rows => limitText(rows.length, REBAL_CASHFLOWS_LIMIT, "건");
export const REBAL_CASHFLOW_TAIL = "저장된 입출금 · 배당 이력을 다시 읽은 것이고 이벤트를 새로 반영하지 않습니다";

// ── 4. TradingView 수신 신호 (tradingview · GET /api/tradingview/signals 의 signals) ─────────────
export const TV_STATUS_LABEL = {
  filled: "체결", alert: "알림", duplicate: "중복", rejected: "거절", error: "오류", late: "늦음", rejected_format: "형식 오류",
};
const TV_STATUS_ORDER = Object.keys(TV_STATUS_LABEL);
/** 표가 방향을 보이는 규칙과 같다 — BUY 매수 · SELL 매도 · 그 밖은 알림. */
export const tvDirection = sig => (sig && sig.side === "BUY" ? "BUY" : sig && sig.side === "SELL" ? "SELL" : "ALERT");

export function tvSignalGroups(signals, filters = {}) {
  const statuses = distinctOptions(signals.map(s => str(s && s.status)), TV_STATUS_ORDER, filters.status);
  return [
    { key: "dir", label: "방향", options: [ANY, { value: "BUY", label: "매수" }, { value: "SELL", label: "매도" }, { value: "ALERT", label: "알림" }] },
    { key: "status", label: "처리", options: [ANY, ...statuses.map(v => ({ value: v, label: TV_STATUS_LABEL[v] || v }))] },
  ];
}
export const TV_GETTERS = { dir: tvDirection, status: s => str(s && s.status) };
export const tvLimitNote = rows => limitText(rows.length, TV_SIGNALS_LIMIT, "건");
export const TV_TAIL = "수신 신호와 교차 검증 이력을 저장된 값에서 다시 읽은 것이고 신호를 보내거나 LEAN 비교를 다시 돌리지 않습니다";

// ── 5. 데이터 관제 「자료별 기준일」 표 (datahub · GET /api/data/status 의 tables) ───────────────
// 이 표는 화면 전체가 30초마다 다시 그려진다 → 칩 값은 화면 파일이 모듈 변수로 쥐고, 여기서는 그릴 때마다 받아 쓴다.
const DATA_VERDICT_ORDER = ["fresh", "ok", "late", "stale", "missing", "info"];
// 서버(app/services/data_status.py VERDICT_LABEL)가 판정마다 쓰는 기본 글 — 같은 판정이라도 줄마다 verdict_label 이 달라질 수 있다(「정상 · 공개 전」 「늦음 · 다시 받기」).
// 칩은 판정(verdict) 하나를 가리키므로 기본 글을 쓰고, 줄 안의 알약은 서버가 준 글을 그대로 보인다. 모르는 판정은 응답에서 처음 본 글.
export const DATA_VERDICT_LABEL = { fresh: "최신", ok: "정상", late: "늦음", stale: "멈춤", missing: "없음", info: "참고" };
export function dataTableGroups(tables, filters = {}) {
  const labelOf = new Map();
  for (const t of tables) {
    const v = str(t && t.verdict);
    if (v && !labelOf.has(v)) labelOf.set(v, str(t.verdict_label) || v);
  }
  const verdicts = distinctOptions([...labelOf.keys()], DATA_VERDICT_ORDER, filters.verdict);
  return [{ key: "verdict", label: "판정", options: [ANY, ...verdicts.map(v => ({ value: v, label: DATA_VERDICT_LABEL[v] || labelOf.get(v) || v }))] }];
}
export const DATA_GETTERS = { verdict: t => str(t && t.verdict) };

/**
 * 자료별 기준일 표의 한 화면분 — 칩 줄(barHtml) + 걸러 남긴 줄(kept). 새로고침 단추는 화면 위쪽의 것을 쓰므로 여기서는 만들지 않는다.
 * @param tables   서버가 준 자료 배열(없으면 빈 목록)
 * @param filters  { verdict }
 */
export function dataTableView(tables, filters, { esc }) {
  const list = Array.isArray(tables) ? tables : [];
  const f = filters || {};
  // 고를 값이 「전체」 하나뿐인 묶음은 줄에서 빼고, 눌린 칩 표시(value)는 여기서 채운다(createListPanel 을 안 쓰는 화면이라)
  const groups = dataTableGroups(list, f).filter(g => g.options.length > 1).map(g => ({ ...g, value: f[g.key] ?? "" }));
  const kept = applyFilters(list, f, DATA_GETTERS);
  const summary = filterSummary(groups, f, list.length, kept.length, "개");
  const note = summary || `자료 ${list.length}개 — 30초마다 · 새로 고침을 눌러도 걸어 둔 조건은 그대로입니다`;
  const barHtml = listBarHtml(esc, { groups, refresh: false, label: "자료별 기준일 필터", note });
  return { groups, kept, barHtml, total: list.length, shown: kept.length };
}
