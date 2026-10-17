/**
 * 미국주식 › 주문/매매 — 시세 카드 · 예상 금액 · 확인 상자 · 예약 목록 그리기 (DOM 없음 · Node 로 시험 · TC-USS · 2026-10-17)
 *
 * 결정: Figma 「Qurious · 미국주식 주문 화면」 C — B(시세 카드 + 예상 금액 + 앱 안 확인 상자) + 장이 닫힌 날은 예약 주문.
 * 무엇이 틀렸었나(모의투자 점검 셋째 바퀴 L10 · 끊긴 곳 30 · #256 미국 쪽): 주문 칸에 시세 · 마지막 체결 · 장 상태 · 환율이
 * 하나도 없고, 단추를 누르면 확인 없이 바로 체결됐다 — 토요일에는 금요일 마감 값으로(안내 없음).
 *
 * 지키는 것 —
 *   · 글은 서버 응답 그대로 옮긴다: 장 상태 글(`market.label`) · 환율 글(`fx_note`) · 예약 안내(`note`) · 체결 까닭(`reason`).
 *     이 파일은 이스케이프해 보이기만 한다(화면이 다시 짓지 않음 · SSoT). 등락 글 · 체결 시각 글은 quoteview.js 한 곳.
 *   · 모르는 값은 「—」 · 빈 글(지어내지 않음). 장 상태를 서버가 모르면(null) 「닫힘」 으로 짐작하지 않는다.
 *   · 「매수 추천」 같은 권유 낱말을 쓰지 않는다 — 모의투자 · 지연 시세라는 사실만.
 */
import { pctText, direction, asOfText } from "./quoteview.js";

/** 시세 출처 이름 — 서버 `data_provenance.QUOTE_SOURCE_LABEL` 과 같은 글(시험이 맞댄다 · 두 곳에 적힐 수밖에 없는 값). */
export const USO_SOURCE = "야후 파이낸스";
const DIR_COLOR = { up: "var(--green)", down: "var(--red)", flat: "var(--text-dim)", none: "var(--text-mute)" };
const STATUS_TEXT = { pending: "대기", filled: "체결", skipped: "건너뜀", cancelled: "취소함", triggered: "처리 중" };

export function usoEsc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/** 원화 글 — 모르면 「—」 */
export function usoWon(n) {
  return n === null || n === undefined || n === "" || !Number.isFinite(+n) ? "—" : `${Math.round(+n).toLocaleString("ko-KR")}원`;
}

/** 현지 통화 글 — 달러는 「$1.38」 · 그 밖은 「1.38 JPY」 · 모르면 「—」 */
export function usoLocal(n, cur) {
  if (n === null || n === undefined || n === "" || !Number.isFinite(+n)) return "—";
  const v = (+n).toFixed(2);
  return cur === "USD" ? `$${v}` : `${v}${cur ? " " + cur : ""}`;
}

/** 장이 닫혔나 — 서버가 「닫힘」 이라고 한 때만 true(모름은 닫힘이 아니다). */
export function usoClosed(market) {
  return !!market && market.open === false;
}

/** 매수 단추 글 — 장이 닫히면 예약 매수 */
export function usoBuyLabel(market) {
  return usoClosed(market) ? "예약 매수 (다음 정규장)" : "매수 (Buy)";
}

/** 장 상태 배지 */
function usoBadge(market) {
  if (!market) return "";
  const [text, bg, fg] = market.open === true ? ["장 열림", "rgba(34,197,94,.16)", "var(--green)"]
    : market.open === false ? ["장 닫힘", "rgba(245,158,11,.18)", "#d97706"] : ["장 상태 모름", "rgba(148,163,184,.2)", "var(--text-dim)"];
  return `<span data-uso-badge style="font-size:11px;padding:2px 8px;border-radius:999px;background:${bg};color:${fg};font-weight:600;">${text}</span>`;
}

/**
 * 시세 카드 — q: GET /api/stocks/quote(현지 통화 · 등락률 · 마지막 체결 시각) · pq: GET /api/paper/stocks/quote(원화 환산 · 환율 글)
 * market: GET /api/paper/stocks/us-market. 셋 중 하나가 없어도 아는 것만 그린다.
 */
export function usoQuoteHtml(q, pq, market) {
  if (!q && !pq) return "";
  q = q || {}; pq = pq || {};
  const cur = pq.currency || q.currency || "";
  const local = pq.price_local ?? q.price;
  const dir = direction(q.change_pct);
  const asOf = asOfText(q.as_of) || "마지막 체결 시각 모름";
  return `<div data-uso-quote style="border:1px solid var(--border);border-radius:10px;padding:10px 12px;margin-top:2px;">
    <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;">
      <span class="text-sm font-semibold">${usoEsc(pq.name || q.name || "")} <span class="text-xs" style="color:var(--text-mute);">${usoEsc(pq.symbol || q.symbol || "")}</span></span>
      ${usoBadge(market)}
    </div>
    <div class="mt-1"><span class="text-lg font-bold">${usoEsc(usoLocal(local, cur))}</span>
      <span class="text-sm" style="color:${DIR_COLOR[dir]};">${usoEsc(pctText(q.change_pct))}</span>
      <span class="text-sm" style="color:var(--text-mute);">≈ ${usoEsc(usoWon(pq.price))}</span></div>
    <div class="text-xs mt-1" style="color:var(--text-mute);line-height:1.55;">${usoEsc(USO_SOURCE)} 지연 시세 · ${usoEsc(asOf)}${pq.fx_note ? "<br>" + usoEsc(pq.fx_note) : ""}${market && market.label ? "<br>" + usoEsc(market.label) : ""}</div>
  </div>`;
}

/** 예상 금액 — p: POST /api/paper/stocks/orders/preview(BUY) 응답 그대로(체결과 같은 비용 셈) */
export function usoEstimateHtml(p, market) {
  if (!p) return "";
  const rows = [
    ["예상 금액(원화 환산)", usoWon(p.estimatedAmount)],
    ["수수료 · 세금", usoWon(p.totalCost ?? 0)],
    ["순정산", usoWon(p.netAmount ?? p.estimatedAmount)],
    ["현금", `${usoWon(p.cashBefore)} → ${usoWon(p.cashAfter)}`],
  ];
  const lines = rows.map(([k, v]) =>
    `<div style="display:flex;justify-content:space-between;gap:8px;"><span style="color:var(--text-mute);">${k}</span><b>${usoEsc(v)}</b></div>`).join("");
  const short = p.executable === false
    ? `<div class="mt-1" style="color:var(--red);">${usoEsc(p.reason || "주문할 수 없습니다")}</div>` : "";
  const basis = usoClosed(market)
    ? `<div class="mt-1" style="color:var(--text-mute);">지금 시세로 셈한 값입니다 — 예약은 다음 정규장 시작가로 체결돼 금액이 달라집니다.</div>` : "";
  return `<div data-uso-estimate class="text-xs" style="line-height:1.7;">${lines}${short}${basis}</div>`;
}

/**
 * 확인 상자 — { title, html, okLabel, reserve } · 장이 닫혔으면 예약으로 받는다고 먼저 말한다.
 * a: { symbol, qty, q, pq, p, market }
 */
export function usoConfirm(a) {
  const { symbol, qty, q = {}, pq = {}, p = null, market = null } = a || {};
  const reserve = usoClosed(market);
  const cur = pq.currency || q.currency || "";
  const rows = [
    ["종목", `${symbol || pq.symbol || ""}${pq.name ? " · " + pq.name : ""}`],
    ["수량 · 유형", `${qty}주 · ${reserve ? "예약(다음 정규장 시작가)" : "시장가"}`],
    // 원화 단가는 서버 미리 보기의 체결 단가(원 단위로 버림 — 체결과 같은 셈) — 카드의 「≈」 반올림 값과 섞지 않는다(손 시험에서 1원 어긋남을 찾음)
    ["지금 시세", `${usoLocal(pq.price_local ?? q.price, cur)} → ${usoWon(p && p.estimatedPrice != null ? p.estimatedPrice : pq.price)}`],
    ["환율", pq.fx_note || "—"],
    ["순정산 · 현금", p ? `${usoWon(p.netAmount ?? p.estimatedAmount)} · ${usoWon(p.cashBefore)} → ${usoWon(p.cashAfter)}` : "—"],
  ];
  const warn = reserve
    ? `미국 정규장이 닫혀 있습니다 — 예약 주문으로 받아 ${market.next_open_kst || "다음 정규장"}(KST) 정규장 시작가로 체결합니다. 체결 전에는 취소할 수 있습니다.`
    : market && market.open === null ? `${market.label} — 지금 지연 시세로 바로 체결됩니다.` : "";
  const html = rows.map(([k, v]) =>
    `<div style="display:flex;justify-content:space-between;gap:12px;font-size:13px;padding:3px 0;"><span style="color:var(--text-mute);">${k}</span><span style="text-align:right;">${usoEsc(v)}</span></div>`).join("")
    + (warn ? `<div data-uso-warn style="margin-top:8px;padding:8px 10px;border-radius:8px;font-size:12px;line-height:1.55;background:rgba(245,158,11,.12);border:1px solid rgba(245,158,11,.45);color:#b45309;">${usoEsc(warn)}</div>` : "")
    + `<div style="margin-top:8px;font-size:11.5px;color:var(--text-mute);">${usoEsc(USO_SOURCE)} 지연 시세로 체결하는 모의 주문이며 실제 주문이 나가지 않습니다.</div>`;
  return {
    title: reserve ? "매수 예약 확인 · 모의투자" : "매수 주문 확인 · 모의투자",
    okLabel: reserve ? "예약 걸기" : "매수 주문 내기",
    reserve,
    html,
  };
}

/** 예약 목록 — d: GET /api/paper/stocks/reservations 응답 그대로(fired = 이번에 처리한 예약) */
export function usoReservationsHtml(d) {
  const list = (d && d.reservations) || [];
  const fired = (d && d.fired) || [];
  const notes = fired.map(f => {
    if (f.status === "filled") {
      return `예약 체결: ${f.symbol} · ${f.filled_at_kst || ""} 정규장 시작가 ${usoLocal(f.open_local, f.currency)} → ${usoWon(f.fill_price)}${f.fx_note ? " · " + f.fx_note : ""}`;
    }
    return `${f.symbol} 예약 ${f.status === "skipped" ? "건너뜀" : "기다림"} — ${f.reason || "까닭 모름"}`;
  });
  if (!list.length && !notes.length) return "";
  const rows = list.map(r => {
    const when = r.status === "pending" ? `${r.next_open_kst || "다음 정규장"} 체결 예정`
      : r.status === "filled" ? `${r.filled_at_kst || ""} 체결 · ${usoWon(r.fill_price)}` : (r.created_at_kst || "");
    const cancel = r.status === "pending"
      ? ` <button type="button" data-uso-cancel="${usoEsc(r.order_id)}" class="text-xs" style="text-decoration:underline;color:var(--text-dim);">취소</button>` : "";
    return `<div data-uso-row style="display:flex;justify-content:space-between;gap:8px;font-size:12px;padding:4px 0;border-top:1px dashed var(--border);">
      <span><b>${usoEsc(r.symbol)}</b> ${usoEsc(r.quantity)}주 매수 · ${usoEsc(STATUS_TEXT[r.status] || r.status)}</span>
      <span style="color:var(--text-mute);text-align:right;">${usoEsc(when)}${cancel}</span></div>`;
  }).join("");
  return `<div data-uso-reservations style="border:1px solid var(--border);border-radius:10px;padding:10px 12px;">
    <div class="text-xs font-semibold mb-1">예약 주문</div>
    ${notes.map(n => `<div data-uso-fired class="text-xs" style="color:var(--text-dim);margin-bottom:4px;">${usoEsc(n)}</div>`).join("")}
    ${rows}
    ${d && d.note ? `<div class="text-xs mt-1" style="color:var(--text-mute);">${usoEsc(d.note)}</div>` : ""}
  </div>`;
}
