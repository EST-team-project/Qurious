// 자동매매 현황(quant-auto) · 모의 투자 의사결정(robo-decision) 화면의 필터 칩 — 순수 함수만 둔다(DOM 을 만지지 않는다 · 2026-11-05).
// 배경: 퀀트 대시보드 점검에서 이 두 화면이 「새로고침은 있고 필터가 없음」 으로 나왔다. 줄 위 칩 · 안내는 공용 도우미(listbar.js)를 쓴다.
// 규칙: 두 화면의 API 는 인자가 없다 → 걸러 보는 것은 「브라우저가 이미 받은 줄 안」 이고, 그 한계(서버가 자른 90줄 · 40개 · 50회차)를 안내 글에서 숨기지 않는다.
//       서버 응답·판정은 바꾸지 않는다. 칩은 응답에 실제로 나온 값에서만 만든다(없는 종류를 지어내지 않는다).
import { listBarHtml, applyFilters, filterSummary } from "/js/listbar.js";

// 서버가 자르는 크기 — app/routes/stocks.py quant_auto_status 의 logs[-90:] · signals[-40:] 와 같아야 한다(tests/test_autotrade_listbar.py 가 글자를 맞춰 본다).
export const ROBO_LOG_CAP = 90;
export const ROBO_SIGNAL_CAP = 40;

const ALL = { value: "", label: "전체" };

// ── 신호 갈래 ────────────────────────────────────────────────────────
/**
 * 신호 한 건이 어느 갈래인지 — 서버(stocks.py quant_auto_status)가 BUY/SELL/HOLD 를 정하는 규칙과 같다:
 * 계산 실패(error) → 판단 불가 · 「매수」 가 들어간 action → 매수 · 「매도」 가 들어간 action → 매도 · 그 밖(관망 · 데이터 대기 등) → 관망.
 * 의사결정 화면은 서버가 준 signal(BUY/SELL/HOLD/UNAVAILABLE)을 먼저 읽는다 — 카드 배지가 말하는 것과 칩이 어긋나지 않게.
 */
export function signalBucket(sig) {
  if (!sig || typeof sig !== "object") return "판단 불가";
  if (sig.error || sig.signal === "UNAVAILABLE") return "판단 불가";
  if (sig.signal === "BUY") return "매수";
  if (sig.signal === "SELL") return "매도";
  if (sig.signal === "HOLD") return "관망";
  const action = String(sig.action ?? "");
  if (action.includes("매수")) return "매수";
  if (action.includes("매도")) return "매도";
  return "관망";
}

/** 신호 칩 — 매수 · 매도 · 관망은 늘 두고, 판단 불가는 응답에 있거나 이미 걸려 있을 때만(걸린 칩은 사라져도 풀 수 있게 남긴다). */
function signalOptions(present, active) {
  const list = ["매수", "매도", "관망"];
  if (present.includes("판단 불가") || active === "판단 불가") list.push("판단 불가");
  return [ALL, ...list.map(v => ({ value: v, label: v }))];
}

// ── 1. 자동매매 현황 (quant-auto · GET /api/auto-trade/status 의 log = 회차 목록) ──────────────────
/** 이 회차에 주문(가상 기록 포함)이 있었는지 — 위험관리가 막은 「주문 생략」(type "risk" · 수량 0)은 주문이 아니다. */
export function cycleHasOrder(cycle) {
  return ((cycle && cycle.trades) || []).some(t => t && t.type !== "risk" && ((t.execution && t.execution.status) ?? t.status) !== "skipped");
}

/** 이 회차 신호들의 갈래(중복 없이). */
export function cycleBuckets(cycle) {
  return [...new Set(((cycle && cycle.signals) || []).map(signalBucket))];
}

/** 칩 묶음 — 회차(주문 있는 회차만) · 신호. 신호는 한 회차에 여럿이라 「그 갈래가 하나라도 있는 회차」 로 읽는다. */
export function autoFilterGroups(cycles, filters) {
  const f = filters || {};
  const present = [...new Set(cycles.flatMap(cycleBuckets))];
  return [
    { key: "order", label: "회차", value: f.order ?? "", options: [ALL, { value: "yes", label: "체결·주문이 있는 회차만" }] },
    { key: "signal", label: "신호", value: f.signal ?? "", options: signalOptions(present, f.signal) },
  ];
}

/** 거르기 — applyFilters 는 값이 같은지로 비교하므로 「신호」 는 건 값이 그 회차에 있을 때만 그 값을 돌려준다. */
export function filterCycles(cycles, filters) {
  const f = filters || {};
  return applyFilters(cycles, f, {
    order: c => (cycleHasOrder(c) ? "yes" : ""),
    signal: c => (cycleBuckets(c).includes(f.signal) ? f.signal : ""),
  });
}

/**
 * 자동매매 회차 로그 한 화면분 — 줄 위 칩 줄(barHtml) + 회차 카드(listHtml). 최신 회차가 위로 온다(기존 순서).
 * @param log       서버가 준 회차 배열(없거나 배열이 아니면 빈 목록)
 * @param filters   { order, signal }
 * @param opts.esc  화면의 escHtml · opts.cycleHtml(cycle) 회차 카드 HTML(화면이 그린다) · opts.note 새로고침 뒤 안내
 */
export function autoTradeView(log, filters, { esc, cycleHtml, note = "" }) {
  const cycles = Array.isArray(log) ? log : [];
  const f = filters || {};
  const groups = autoFilterGroups(cycles, f);
  const kept = filterCycles(cycles, f);
  const summary = filterSummary(groups, f, cycles.length, kept.length, "회차");
  const limit = "서버가 보낸 최근 회차 안에서만 거른 결과";
  const text = !cycles.length ? "받은 회차가 없습니다"
    : summary ? [summary, limit, f.order ? "주문 생략(위험관리가 막은 것)만 있는 회차는 뺌" : ""].filter(Boolean).join(" · ")
      : `받은 ${cycles.length}회차 — 서버가 보낸 최근 회차 안에서 거릅니다`;
  const barHtml = listBarHtml(esc, { groups, refresh: false, label: "자동매매 회차 필터", note: [text, note].filter(Boolean).join(" · ") });
  let listHtml;
  if (!cycles.length) listHtml = `<div style="color:var(--text-mute);">자동매매 로그가 없습니다.</div>`;
  else if (!kept.length) listHtml = `<div style="color:var(--text-mute);">이 조건에 맞는 회차가 없습니다. 필터를 풀어 보세요.</div>`;
  else listHtml = [...kept].reverse().map(cycleHtml).join("");
  return { groups, barHtml, listHtml, total: cycles.length, shown: kept.length };
}

// ── 2. 모의 투자 의사결정 (robo-decision · GET /api/quant/auto/status 의 logs · signals) ──────────────
// 로그에는 종류 낱말이 없다 — 주문·체결 줄만 execution(구조 값)이 있고, 나머지는 서버가 붙인 글머리(「[위험관리 생략]」 등)로만 갈린다.
// 칩 이름은 아래 고정 낱말이다(메시지 글을 칩 이름으로 쓰지 않는다). 글머리 모양은 tests/test_autotrade_listbar.py 가 stocks.py 글자와 맞춰 본다.
export const ROBO_LOG_KINDS = [
  { value: "order", label: "주문·체결" },
  { value: "risk", label: "위험관리 생략" },
  { value: "aggressive", label: "공격 모드" },
  { value: "reconcile", label: "정합성" },
  { value: "account", label: "계좌 평가" },
  { value: "other", label: "기타" },
];

/** 로그 한 줄의 종류. 시스템 배치 줄은 앞에 「[배치] 」 가 붙는다. */
export function roboLogKind(log) {
  if (log && log.execution) return "order";
  const msg = String((log && log.message) ?? "").replace(/^\[배치\]\s*/, "");
  if (msg.startsWith("[위험관리 생략]")) return "risk";
  if (msg.startsWith("[공격 모드]")) return "aggressive";
  if (msg.startsWith("[정합성]")) return "reconcile";
  if (msg.startsWith("KIS 계좌 평가") || msg.startsWith("퀀트 가상 장부 평가")) return "account";
  return "other";
}

const LEVEL_LABELS = { error: "오류", warning: "경고", success: "성공", info: "참고" };

/** 로그 줄 한 칸 HTML(기존 모양 그대로 + 종류 표시용 data 칸). time = 한국 시각 글로 바꾸는 함수. */
export function roboLogLineHtml(l, esc, time) {
  const color = l.level === "error" ? "var(--red)" : l.level === "warning" ? "var(--amber)" : "var(--text)";
  return `
    <div class="rounded p-2" style="background:var(--surf2);border:1px solid var(--border);" data-rb-kind="${esc(roboLogKind(l))}">
      <span style="color:var(--text-mute);">${esc(time(l.time))}</span>
      <span style="margin-left:8px;color:${color};">${esc(l.message || "")}</span>
    </div>`;
}

/** 로그 칩 묶음 — 종류(응답에 나온 종류만) · 수준(응답에 나온 level 만). 걸려 있는 칩은 응답에서 사라져도 남겨 풀 수 있게 한다. */
export function roboLogGroups(logs, filters) {
  const f = filters || {};
  const kinds = new Set(logs.map(roboLogKind));
  const levels = new Set(logs.map(l => (l && l.level) || "").filter(Boolean));
  const known = Object.keys(LEVEL_LABELS).filter(k => levels.has(k) || f.level === k);
  const other = [...levels].filter(k => !(k in LEVEL_LABELS)).sort();
  if (f.level && !(f.level in LEVEL_LABELS) && !other.includes(f.level)) other.push(f.level);
  const levelOptions = [...known, ...other].map(v => ({ value: v, label: LEVEL_LABELS[v] || String(v) }));
  const groups = [{
    key: "kind", label: "종류", value: f.kind ?? "",
    options: [ALL, ...ROBO_LOG_KINDS.filter(k => kinds.has(k.value) || f.kind === k.value)],
  }];
  if (levelOptions.length) groups.push({ key: "level", label: "수준", value: f.level ?? "", options: [ALL, ...levelOptions] });
  return groups;
}

export function filterRoboLogs(logs, filters) {
  return applyFilters(logs, filters, { kind: roboLogKind, level: l => (l && l.level) || "" });
}

/** 의사결정 로그 한 화면분 — barHtml + listHtml(서버가 준 순서 그대로). opts.time = 한국 시각 글 함수. */
export function roboLogView(logs, filters, { esc, time, note = "" }) {
  const list = Array.isArray(logs) ? logs : [];
  const f = filters || {};
  const groups = roboLogGroups(list, f);
  const kept = filterRoboLogs(list, f);
  const summary = filterSummary(groups, f, list.length, kept.length, "줄");
  const text = !list.length ? "받은 로그가 없습니다"
    : summary ? `${summary} · 서버가 보낸 최근 ${ROBO_LOG_CAP}줄 안에서만 거른 결과입니다`
      : `서버가 보낸 최근 ${ROBO_LOG_CAP}줄 안에서 거릅니다(받은 ${list.length}줄)`;
  const barHtml = listBarHtml(esc, { groups, refresh: false, label: "의사결정 로그 필터", note: [text, note].filter(Boolean).join(" · ") });
  let listHtml;
  if (!list.length) listHtml = `<div style="color:var(--text-mute);">AI 의사결정 로그가 없습니다. 시작 버튼을 눌러 실행하세요.</div>`;
  else if (!kept.length) listHtml = `<div style="color:var(--text-mute);">이 조건에 맞는 로그가 없습니다. 필터를 풀어 보세요.</div>`;
  else listHtml = kept.map(l => roboLogLineHtml(l, esc, time)).join("");
  return { groups, barHtml, listHtml, total: list.length, shown: kept.length };
}

/**
 * 근거 카드 필터 — 카드는 가장 최근 회차의 신호(최대 3장)라서, 이미 그린 카드를 숨기고 보이는 쪽으로 거른다(다시 그리면 카드마다 다중 주기 설명을 또 받는다).
 * @param shown  카드로 그린 신호 배열(latestCycleSignals 결과 그대로 · 순서 같음)
 * @returns { groups, keep: 카드 순서대로 보일지, total, shown, barHtml }
 */
export function roboCardView(shown, filters, { esc, note = "" }) {
  const cards = Array.isArray(shown) ? shown : [];
  const f = filters || {};
  const groups = [{ key: "signal", label: "신호", value: f.signal ?? "", options: signalOptions(cards.map(signalBucket), f.signal) }];
  const keep = cards.map(s => !f.signal || signalBucket(s) === f.signal);
  const count = keep.filter(Boolean).length;
  const summary = filterSummary(groups, f, cards.length, count, "장");
  const text = !cards.length ? "받은 신호가 없습니다"
    : summary ? `${summary} · 최근 ${ROBO_SIGNAL_CAP}개 신호 중 가장 최근 회차 카드 안에서만 거른 결과입니다`
      : `최근 ${ROBO_SIGNAL_CAP}개 신호 중 가장 최근 회차 카드 ${cards.length}장 안에서 거릅니다`;
  const barHtml = listBarHtml(esc, { groups, refresh: false, label: "판단 근거 카드 필터", note: [text, note].filter(Boolean).join(" · ") });
  return { groups, keep, total: cards.length, shown: count, barHtml };
}
