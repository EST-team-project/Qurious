// 미국주식 · 직접매매 화면의 목록 위 줄 — 필터 칩 + 새로고침을 paperlists.js 의 제어기 위에 얹는다(2026-11-05 화면 전수 점검 뒤).
// 대상: us-order 주문 내역 · us-dashboard 종목 카드 · trading-portfolio 보유 표 · trading-order 최근 주문.
// 규칙(paperlists.js 와 같다)
//  1) 걸러 보는 것은 「이미 받은 줄 안」 이다 — 서버 인자는 늘리지 않는다. 그 한계는 안내 글에 밝힌다.
//  2) 새로고침은 「서버에서 다시 읽기」 뿐이다 — 주문 · 예약 취소 · 계산을 하지 않는다(그 길은 이 파일이 알지도 못한다).
//  3) 칩의 값은 응답에서 읽는다(매매 두 낱말 · 등락 문턱은 quoteview.js 의 MOVE_LIMIT / moveTag 그대로 — 새 문턱을 만들지 않는다).
// 순수 함수와 제어기 설정은 DOM 없이 node 로 시험한다(tests/test_listbar_trade.py) — DOM 은 얇게(ensureBarHost 한 곳).
import { createListPanel, sideOf, sideGroup } from "/js/paperlists.js";
import { moveTag, direction, pctText, MOVE_LIMIT } from "/js/quoteview.js";

const TRADE_ALL = { value: "", label: "전체" };
export const US_ORDER_CAP = 20;     // 미국주식 주문 내역에 보이는 줄 상한(옛 화면과 같다) — 거른 뒤에 자른다
export const TRADE_ORDER_CAP = 20;  // 직접매매 최근 주문 상한(옛 화면과 같다)
export const US_ORDER_FETCH = 200;  // 서버에 요청하는 내역 줄 수(미국만 자르기 전)

/** 칩 줄을 그릴 빈 칸을 목록 칸 앞에 만든다(app.html 을 건드리지 않으려고) — 이미 있으면 그대로. doc 이 없거나 기준 칸이 없으면 null. */
export function ensureBarHost(doc, anchorId, barId) {
  if (!doc || !doc.getElementById) return null;
  const hit = doc.getElementById(barId);
  if (hit) return hit;
  const anchor = doc.getElementById(anchorId);
  if (!anchor || !anchor.parentNode || !doc.createElement) return null;
  const el = doc.createElement("div");
  el.id = barId;
  anchor.parentNode.insertBefore(el, anchor);
  return el;
}

// ── 1. 미국주식 주문 내역 ────────────────────────────────────────────────────────────
/** 주문 한 줄 — 옛 화면 글 그대로(옛 WEB 주문은 달러로 적고 그 사실을 붙인다). deps: { esc, fmt, fmtTime }. */
export function usOrderRowHtml(o, deps) {
  const { esc, fmt, fmtTime } = deps;
  const buy = sideOf(o.type) === "BUY";
  const old = o.source === "WEB";
  return `
      <div class="flex flex-wrap items-center gap-3 rounded-lg px-3 py-2" data-us-order-row style="background:var(--surf2);border:1px solid var(--border);font-size:12px;">
        <span class="${buy ? "badge-buy" : "badge-sell"}">${buy ? "BUY" : "SELL"}</span>
        <span class="font-semibold">${esc(o.symbol)}</span>
        <span>${fmt(o.quantity)}주</span>
        <span style="color:var(--text-dim);">${old ? `$${fmt(o.price, 2)}` : `${fmt(o.price)}원`}</span>
        ${old ? `<span style="color:var(--text-mute);font-size:11px;">옛 주문 — 달러 금액이 원화 장부에 그대로 들어감</span>` : ""}
        <span class="ml-auto" style="color:var(--text-mute);">${o.ts ? esc(fmtTime(o.ts)) : ""}</span>
      </div>`;
}

export function usOrderBodyHtml(rows, deps) {
  if (!rows.length) return "<div style='color:var(--text-mute);'>주문 내역 없음</div>";
  return rows.map(o => usOrderRowHtml(o, deps)).join("");
}

/**
 * 미국주식 주문 내역 제어기. deps: { esc, fmt, fmtTime, byId, api, isKrSymbol, alsoRefresh?, now? }
 * 새로고침 = 내역(200줄 받아 미국만) + 예약 주문 목록(alsoRefresh)을 서버에서 다시 읽는다. 예약은 전부 매수라 매매 칩이 필요 없다.
 */
export function usOrderPanel(deps) {
  return createListPanel({
    host: "us-order-history",
    label: "미국주식 주문 내역 필터",
    unit: "건",
    groups: () => [sideGroup()],
    getters: { side: o => sideOf(o.type) },
    cap: US_ORDER_CAP,
    limitNote: (rows, filtered, meta) => (meta
      ? `서버에서 받은 ${meta.received}줄 중 미국 종목 ${rows.length}건 안에서 거릅니다${filtered.length > US_ORDER_CAP ? ` · 최근 ${US_ORDER_CAP}건만 보입니다` : ""}`
      : ""),
    meaning: "서버에서 다시 읽었습니다",
    tail: "주문 내역과 예약 주문 목록을 다시 읽었을 뿐 주문 · 취소는 하지 않습니다",
    alsoOnRefresh: deps.alsoRefresh,
    load: async () => {
      // 모의 장부(원화)의 주문 기록 — 미국 종목만(국내 종목은 국내주식 모의주문 화면에서 본다)
      const r = await deps.api(`/api/paper/stocks/orders/history?limit=${US_ORDER_FETCH}`);
      const all = (r && r.history) || [];
      return { rows: all.filter(o => !deps.isKrSymbol(String(o.symbol || ""))), meta: { received: all.length } };
    },
    body: rows => usOrderBodyHtml(rows, deps),
  }, { esc: deps.esc, byId: deps.byId, now: deps.now });
}

// ── 2. 미국주식 대시보드 종목 카드 ───────────────────────────────────────────────────
/** 전일 대비 등락률 → up / down / flat / unknown. 문턱은 quoteview.js moveTag 그대로(±MOVE_LIMIT %). 등락을 모르면 unknown(「그대로」 로 세지 않는다). */
export function usMoveBucket(pct) {
  if (typeof pct !== "number" || !Number.isFinite(pct)) return "unknown";
  const t = moveTag(pct);
  return t.dir === "up" ? "up" : t.dir === "down" ? "down" : "flat";
}

/** 카드의 등락률 — 옛 화면과 같은 읽기(change_p 먼저). */
export const usCardPct = s => s.change_p ?? s.change_pct;

/** 「크게 오름 / 크게 내림 / 그대로」 칩 — 등락을 모르는 종목이 응답에 있을 때만 「등락 모름」 칩을 더한다. */
export function usMoveGroup(rows) {
  const opts = [TRADE_ALL, { value: "up", label: "크게 오름" }, { value: "down", label: "크게 내림" }, { value: "flat", label: `그대로(±${MOVE_LIMIT}% 안)` }];
  if (rows.some(s => usMoveBucket(usCardPct(s)) === "unknown")) opts.push({ value: "unknown", label: "등락 모름" });
  return { key: "move", label: "움직임", options: opts };
}

/** 종목 카드 하나 — 옛 화면 모양 그대로. deps: { esc, fmt, dirColor }. */
export function usCardHtml(s, deps) {
  const { esc, fmt, dirColor } = deps;
  const pct = usCardPct(s);
  const tag = moveTag(pct);
  return `<div class="card" data-us-card="${esc(s.symbol)}" style="padding:12px;">
      <div class="font-bold text-sm">${esc(s.symbol)}</div>
      <div class="text-xs" style="color:var(--text-dim);">${esc(s.name || "")}</div>
      <div class="font-semibold mt-2">$${fmt(s.price, 2)}</div>
      <div class="text-xs mt-1" style="color:${dirColor[direction(pct)]};">${pctText(pct)}</div>
      <div class="text-xs font-bold mt-2" style="color:${dirColor[tag.dir]};min-height:16px;">${esc(tag.text)}</div>
    </div>`;
}

/** 카드 묶음 + 맨 아래 한 줄 안내(meta.noteHtml — 서버 머리 글 · 새로고침 안내를 부른 쪽이 이미 이스케이프한 글). 종목이 없으면 옛 안내 글. */
export function usCardsBodyHtml(rows, meta, deps) {
  if (!rows.length) return `<div class="text-sm" style="color:var(--text-mute);grid-column:1/-1;">시세를 받지 못했습니다 — 잠시 뒤 「새로고침」 을 눌러 주세요.</div>`;
  const note = meta && meta.noteHtml
    ? `<div class="text-xs" style="color:var(--text-mute);grid-column:1/-1;text-align:right;" data-us-cards-note>${meta.noteHtml}</div>` : "";
  return rows.map(s => usCardHtml(s, deps)).join("") + note;
}

/**
 * 종목 카드 제어기. deps: { esc, fmt, dirColor, byId, load, now? }
 * load() 는 loadUsDashboard 가 방금 받아 둔 { rows, meta } 를 돌려준다 — 이 제어기는 서버를 부르지 않는다.
 * 새로고침 단추는 두지 않는다(화면 위쪽 「새로고침」 이 서버 저장본을 건너뛰고 다시 받는다 — loadUsDashboard({refresh:true})).
 * 칩 줄은 격자 밖(barHost)에 그린다 — 칩이 카드 칸 하나를 차지하지 않게.
 */
export function usCardsPanel(deps) {
  return createListPanel({
    host: "us-signal-cards",
    barHost: "us-signal-bar",
    label: "미국 대형주 움직임 필터",
    unit: "종목",
    refresh: false,
    groups: rows => [usMoveGroup(rows)],
    getters: { move: s => usMoveBucket(usCardPct(s)) },
    limitNote: () => "받은 종목 안에서 거릅니다 · 다시 받으려면 위쪽 「새로고침」",
    load: deps.load,
    body: (rows, ctx) => usCardsBodyHtml(rows, ctx.meta, deps),
  }, { esc: deps.esc, byId: deps.byId, now: deps.now });
}

// ── 3. 직접매매 보유 표 · 최근 주문 ──────────────────────────────────────────────────
/** 보유 표(안내 두 줄 + 표) — 옛 화면 글 그대로. 보유가 없으면 한 줄. deps: { esc, fmt }. */
export function tradeHoldingsHtml(rows, deps) {
  const { esc, fmt } = deps;
  if (!rows.length) return "<div class='text-slate-400 text-xs'>보유 종목이 없습니다.</div>";
  return `
      <div class="text-xs mb-2" style="color:var(--text-mute);">
        ※ 보유 종목은 <b>국내주식 모의주문</b>의 매수·매도로만 바뀝니다.
        <a class="underline" href="#paper-stock">국내주식 모의주문 →</a>
      </div>
      <div data-pf-basis class="text-xs mb-2" style="color:var(--text-mute);line-height:1.6;">
        현재가는 이 화면을 연 시점에 받은 시세로, 지연 시세일 수 있습니다 — 이 화면의 응답에는 출처 · 시각이 없어 칸마다 적지 못합니다.
        시세를 받지 못한 종목은 「-」 로 두고 평단가로 대신하지 않습니다.
      </div>
      <table class="w-full text-xs border-collapse">
        <thead><tr class="text-slate-400 border-b border-white/10">
          <th class="py-2 text-left">종목</th>
          <th class="py-2 text-right">수량</th>
          <th class="py-2 text-right">평균단가</th>
          <th class="py-2 text-right">현재가</th>
          <th class="py-2 text-right">평가금액</th>
        </tr></thead>
        <tbody>
          ${rows.map(h => `
            <tr class="border-b border-white/5">
              <td class="py-2">${esc(h.name)}<div class="text-slate-500">${esc(h.symbol)}</div></td>
              <td class="py-2 text-right">${fmt(h.quantity)}</td>
              <td class="py-2 text-right">${fmt(h.avg_price)}</td>
              <td class="py-2 text-right">${h.current_price != null ? fmt(h.current_price) : "-"}</td>
              <td class="py-2 text-right">${h.eval_amount != null ? fmt(h.eval_amount) + "원" : "-"}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>`;
}

/** 보유 표 제어기(새로고침만 — 고를 칩이 없다). deps: { esc, fmt, byId, api, now? } */
export function portfolioPanel(deps) {
  return createListPanel({
    host: "portfolio-table",
    label: "내 포트폴리오",
    unit: "종목",
    meaning: "서버에서 다시 읽었습니다",
    tail: "보유와 현재가를 다시 읽었을 뿐 주문 · 계산은 하지 않습니다",
    load: async () => {
      try {
        const r = await deps.api("/api/portfolio");
        return { rows: (r && r.holdings) || [], meta: null };
      } catch (e) {
        throw new Error(`보유 종목을 불러오지 못했습니다 — ${(e && e.message) || "까닭 모름"}`);
      }
    },
    body: rows => tradeHoldingsHtml(rows, deps),
  }, { esc: deps.esc, byId: deps.byId, now: deps.now });
}

/** 최근 주문 한 줄 — 옛 화면 글 그대로. */
export function tradeOrderRowHtml(o, deps) {
  const { esc, fmt } = deps;
  const buy = sideOf(o.order_type) === "BUY";
  return `
      <div class="flex items-center justify-between rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-xs" data-trade-order-row>
        <span class="${buy ? "badge-buy" : "badge-sell"}">${buy ? "매수" : "매도"}</span>
        <span class="ml-2">${esc(o.name)} (${esc(o.symbol)})</span>
        <span class="ml-auto">${fmt(o.price)}원 × ${fmt(o.quantity)}주</span>
        <span class="ml-3 text-slate-500">${esc(o.broker)} · ${esc((o.created_at || "").slice(0, 10))}</span>
      </div>`;
}

/** 최근 주문 줄들 + 빠진 주문을 어디서 보는지 안내(서버가 자동매매 · Open API · 예약 주문을 뺀다). */
export function tradeOrdersBodyHtml(rows, deps) {
  const list = rows.length ? rows.map(o => tradeOrderRowHtml(o, deps)).join("") : "<div class='text-slate-400'>주문 내역 없음</div>";
  return `${list}<div class="text-xs mt-1" style="color:var(--text-mute);">자동매매 · Open API 주문은 <a href="#quant-auto" class="underline">자동매매 현황</a>에서 봅니다.</div>`;
}

/** 최근 주문 제어기 — 매매 칩 + 새로고침. deps: { esc, fmt, byId, api, now? } */
export function tradeOrderPanel(deps) {
  return createListPanel({
    host: "order-history",
    label: "최근 주문 내역 필터",
    unit: "건",
    groups: () => [sideGroup()],
    getters: { side: o => sideOf(o.order_type) },
    cap: TRADE_ORDER_CAP,
    limitNote: (rows, filtered, meta) => (meta ? `서버가 준 ${rows.length}건 안에서 거릅니다${filtered.length > TRADE_ORDER_CAP ? ` · 최근 ${TRADE_ORDER_CAP}건만 보입니다` : ""}` : ""),
    meaning: "서버에서 다시 읽었습니다",
    tail: "주문 기록을 다시 읽었을 뿐 주문은 내지 않습니다",
    load: async () => {
      const r = await deps.api("/api/orders");
      const orders = (r && r.orders) || [];
      return { rows: orders, meta: { received: orders.length } };
    },
    body: rows => tradeOrdersBodyHtml(rows, deps),
  }, { esc: deps.esc, byId: deps.byId, now: deps.now });
}
