/* 모의투자(주식·코인·대체자산·Open API) + QuantConnect LEAN 백테스트 화면 로직. */
import { api, setToast, escHtml, fmt, fmtPct } from "/js/common.js";
import { mountPaperRisk } from "/js/paper-risk.js";
import {
  COIN_SOURCE_NOTE, COIN_LIVE_NOTE, COIN_ORDER_NOTE, UPBIT_WS_URL, PING_MS,
  coinPoints, coinChartSummary, coinSubscribeMessage, decodeWsData, parseUpbitTicker, coinCandleDate,
  liveBadge, priceGap, orderPriceLine, reconnectDelay,
} from "/js/coinview.js";
import { resolveSymbolInput } from "/js/stockfind.js";                                  // 칸에 이름을 쳐도 종목으로 풀어 준다 (2026-11-02)
import { openStockSearch } from "/js/company.js";
import { mountDailyChart, scCode, SC_PERIODS, SC_DEFAULT_PERIOD, scDirection, scQuickStops, scWouldFireNow } from "/js/stockchart.js";
import { createListPanel, createRefreshGroup, sideOf, directionOf, sideGroup, kindGroup, directionGroup, sourceGroup, categoryGroup } from "/js/paperlists.js";   // 표 위 필터 칩 · 새로고침 (2026-11-05)
import { leanHistoryCfg, ensureBarHost } from "/js/listbar-misc.js";   // LEAN 실행 이력 표 위 줄 (2026-11-05)

const $ = (id) => document.getElementById(id);
const won = (n, d = 0) => `${fmt(n, d)}원`;
const signCls = (n) => (parseFloat(n) >= 0 ? "text-emerald-700" : "text-red-700");   // 2026-11-04 대비 3.77 → 5.5
const ts = (ms) => new Date(ms).toLocaleString("ko-KR", { hour12: false });
const sideBadge = (t) => `<span class="${String(t).toUpperCase() === "BUY" ? "badge-buy" : "badge-sell"}">${String(t).toUpperCase() === "BUY" ? "매수" : "매도"}</span>`;
const kpi = (label, value, cls = "") => `
  <div class="rounded-xl border border-white/10 bg-black/20 p-3">
    <div class="text-xs" style="color:var(--text-mute);">${escHtml(label)}</div>
    <div class="text-lg font-bold ${cls}">${value}</div>
  </div>`;
const emptyRow = (cols, text) => `<tr><td colspan="${cols}" style="color:var(--text-mute);text-align:center;">${escHtml(text)}</td></tr>`;
// 표 위 줄(필터 칩 + 새로고침 + 안내) 한 곳 — 제어기는 js/paperlists.js, 칩 모양은 js/listbar.js · css/signalrankview.css
const listPanel = (cfg) => createListPanel(cfg, { esc: escHtml, byId: $ });

let altChart = null;
let leanChart = null;
let cryptoMarkets = [];
let _pdAllocationChart = null;
let _pdEquityChart = null;

/* ────────────────────────────────────────────────────────────────
 * 1. 모의투자 대시보드
 * ──────────────────────────────────────────────────────────────── */
// 최근 체결 목록 — 주식 30 · 코인 10 · 대체자산 10건을 받아 합친 뒤, 칩으로 거르고 나서 최신 15줄까지 보인다(거르기 전에 자르면 코인이 0줄로 보일 수 있다).
const PD_RECENT_CAP = 15;
// 이슈: SIM(백테스트) 주문을 실시간과 구분
const pdSourceLabel = (src) => src === 'SIM'
  ? `<span class="text-xs" style="color:#d97706;font-weight:600;" title="100일 historical replay 백테스트 주문">🧪 SIM</span>`
  : escHtml(src);

function pdRecentBody(rows) {
  const simCount = rows.filter(r => r.source === 'SIM').length;
  return (simCount > 0
    ? `<p class="text-xs mb-2" style="color:var(--text-mute);">
         ※ <b>🧪 SIM(백테스트)</b> 주문 ${simCount}건 포함 — 자산추이·QFRS 카드에 반영됨.
       </p>`
    : '') +
    `<table><thead><tr>
      <th>시각</th><th>구분</th><th>종목</th><th>매매</th>
      <th style="text-align:right">수량</th>
      <th style="text-align:right">단가</th>
      <th style="text-align:right">금액</th>
      <th>출처</th>
    </tr></thead>
    <tbody>${rows.length ? rows.map(r => `<tr>
      <td class="text-xs">${ts(r.ts)}</td>
      <td>${escHtml(r.kind)}</td>
      <td>${escHtml(r.name)}</td>
      <td>${sideBadge(r.type)}</td>
      <td style="text-align:right">${r.qty}</td>
      <td style="text-align:right">${r.price}</td>
      <td style="text-align:right">${r.amount}</td>
      <td class="text-xs">${pdSourceLabel(r.source)}</td>
    </tr>`).join("") : emptyRow(8, "아직 체결 내역이 없습니다.")}</tbody></table>`;
}

async function pdRecentRows() {
  const [s, c, alt] = await Promise.all([
    api("/api/paper/stocks/orders/history?limit=30"),   // ← SIM 포함 위해 30건
    api("/api/paper/trade/order/history?limit=10"),
    api("/api/paper/alternatives/orders/history?limit=10"),
  ]);
  const rows = [
    ...s.history.map(o => ({ ts: o.ts, group: "STOCK", kind: "주식", name: `${o.name} (${o.symbol})`, type: o.type, qty: fmt(o.quantity), price: won(o.price), amount: won(o.amount), source: o.source })),
    ...c.history.map(o => ({ ts: o.ts, group: "CRYPTO", kind: "코인", name: `${o.koreanName} (${o.marketCode})`, type: o.type, qty: fmt(o.quantity, 8), price: won(o.price), amount: won(o.amount), source: o.source })),
    ...alt.history.map(o => ({ ts: o.ts, group: "ALT", kind: o.category, name: o.name, type: o.type, qty: fmt(o.quantity), price: won(o.price), amount: won(o.amount), source: o.source })),
  ].sort((x, y) => y.ts - x.ts);
  return { rows };
}

// 칩: 구분(주식 · 코인 · 대체자산) · 매매 · 출처. 새로고침 단추는 머리글의 것(pd-refresh) 하나만 둔다.
const pdRecentPanel = listPanel({
  host: "pd-recent", label: "최근 체결 필터", unit: "줄", refresh: false, cap: PD_RECENT_CAP,
  groups: (rows, f) => [kindGroup(), sideGroup(), sourceGroup(rows, f.source)],
  getters: { kind: r => r.group, side: r => sideOf(r.type), source: r => r.source },
  limitNote: `주식 30 · 코인 10 · 대체자산 10줄까지 받아 합친 뒤, 받은 줄 안에서 거르고 최신 ${PD_RECENT_CAP}줄까지 보입니다`,
  load: pdRecentRows,
  body: pdRecentBody,
});

// 새로고침 안내 글(pd-refresh-note)은 그 시각의 값에 대한 말이다 — 화면에 다시 들어오거나 계좌를 초기화하면 치운다
const pdClearRefreshNote = () => { const el = $("pd-refresh-note"); if (el) el.textContent = ""; };

/** 계좌 현황의 KPI 와 최근 체결을 읽는다. 둘 다 읽었으면 true(새로고침 묶음이 결과를 알리려고 돌려받는다). */
async function loadPaperDashboard() {
  let ok = true;
  try {
    const a = await api("/api/paper/account");
    $("pd-kpis").innerHTML = [
      kpi("보유 현금", won(a.cash)),
      kpi("주식 평가액", won(a.stockEval)),
      kpi("코인 평가액", won(a.cryptoEval)),
      kpi("대체자산 평가액", won(a.alternativeEval)),
      kpi("총 자산", won(a.totalAsset)),
      kpi("총 손익", `${won(a.totalPnl)} <span class="text-sm">(${fmtPct(a.totalPnlRate)})</span>`, signCls(a.totalPnl)),
    ].join("");
    $("pd-counts").textContent = `보유: 주식 ${a.counts.stocks}종목 · 코인 ${a.counts.crypto}종목 · 대체자산 ${a.counts.alternatives}종목 · 초기자금 ${won(a.initialCash)}`;
  } catch (e) { setToast(e.message, "error"); ok = false; }

  const recentOk = await pdRecentPanel.load();
  return ok && recentOk;
}

async function resetPaperAccount() {
  if (!confirm(
    "모의투자(PAPER)·직접매매(WEB) 주문, 모의 장부 보유, 코인·대체자산 보유/주문을 모두 삭제하고 현금을 1억원으로 초기화합니다(회차 +1).\n\n" +
    "자동매매·파인·외부 API·증권사 체결 주문과 자동매매 보유는 보존됩니다.\n" +
    "되돌릴 수 없습니다. 계속할까요?"
  )) return;
  try {
    const r = await api("/api/paper/account/reset", { method: "POST" });
    setToast(`계좌를 초기화했습니다. 현금 ${won(r.cash)}`, "ok");
    pdClearRefreshNote();
    loadPaperDashboard();
  } catch (e) { setToast(e.message, "error"); }
}

/* ────────────────────────────────────────────────────────────────
 * 2. 국내주식 모의주문
 * ──────────────────────────────────────────────────────────────── */
async function refreshStockCash() {
  const a = await api("/api/paper/account");
  $("ps-cash").textContent = won(a.cash);
}

async function loadPaperStock() {
  loadStockPositions();
  loadStockHistory();
  loadStopOrders();          // ★ B5 스탑 주문 목록
  try { await refreshStockCash(); } catch { }
}

/* 종목 칸의 글(코드 또는 이름)을 기호로 — 이름이면 찾아 칸을 채우고, 여럿이거나 없으면 종목 찾기 창을 그 글자로 열어 두고 null 을 돌려준다.
 * 창에서 고르면 칸이 채워지고 again 이 불린다(시세 조회는 다시 조회 · 주문은 「다시 눌러 주세요」 안내). */
function symbolFromInput(id, again) {
  return resolveSymbolInput(document, $(id), {
    search: async q => ((await api(`/api/stocks/search?q=${encodeURIComponent(q)}`)).results) || [],
    open: openStockSearch,
    onPicked: () => { if (again) again(); },
  });
}
const pickedToast = () => setToast("종목을 골랐습니다. 수량을 확인하고 다시 눌러 주세요.", "ok");

/* 시세 조회 결과 아래 일봉 차트 — 왼쪽(주문 입력) · 오른쪽(스탑, 스탑가 점선). 같은 부품(js/stockchart.js) */
let psMain = null, psMainSym = "", psMainPeriod = SC_DEFAULT_PERIOD;
let psStop = null, psStopSym = "", psStopCurrent = null, psStopTimer = null, psStopPeriod = SC_DEFAULT_PERIOD;

function psPeriodChips() {
  const el = $("ps-chart-periods");
  if (!el) return;
  el.innerHTML = SC_PERIODS.map(([k, label]) => `<button type="button" data-ps-period="${k}" class="text-xs px-2 rounded-full border"
    style="${k === psMainPeriod ? "background:var(--accent);color:#fff;border-color:var(--accent);" : ""}">${label}</button>`).join("");
}

function psDrawMain() {
  if (!psMain) psMain = mountDailyChart(document, $("ps-chart"), $("ps-chart-note"), { api });
  psPeriodChips();
  psMain.draw({ symbol: psMainSym, period: psMainPeriod });
}

function psStopStopValue() {
  const v = parseFloat($("ps-stop-price").value);
  return Number.isFinite(v) && v > 0 ? v : null;
}

function psStopPeriodChips() {
  const el = $("ps-stop-chart-periods");
  if (!el) return;
  el.innerHTML = SC_PERIODS.map(([k, label]) => `<button type="button" data-ps-stop-period="${k}" class="text-xs px-2 rounded-full border"
    style="${k === psStopPeriod ? "background:var(--accent);color:#fff;border-color:var(--accent);" : ""}">${label}</button>`).join("");
}

function psDrawStop() {
  if (!psStopSym) return;
  if (!psStop) psStop = mountDailyChart(document, $("ps-stop-chart"), $("ps-stop-chart-note"), { api });
  psStopPeriodChips();
  psStop.draw({ symbol: psStopSym, period: psStopPeriod, stop: psStopStopValue() });
}

/** 스탑가 칸 아래 방향 안내 — 현재가와 견준 쪽 · 반대로 등록하면 바로 체결될 수 있음 */
function psStopHint() {
  const hint = $("ps-stop-hint");
  if (!hint) return;
  const note = scDirection(psStopCurrent, psStopStopValue());
  hint.textContent = note || "시세를 조회하면 현재가와 견준 방향을 알려 드립니다. 매도 스탑은 현재가보다 낮게, 매수 스탑은 현재가보다 높게 넣습니다.";
  hint.style.color = note ? "var(--text)" : "var(--text-mute)";
}

function psStopQuick() {
  const box = $("ps-stop-quick");
  if (!box) return;
  const list = scQuickStops(psStopCurrent);
  box.hidden = !list.length;
  box.innerHTML = list.length
    ? `<span class="text-xs" style="color:var(--text-mute);align-self:center;">손절용(매도 스탑)</span>` + list.map(s =>
      `<button type="button" class="btn-secondary text-xs ps-stop-quick" data-v="${s.value}">${escHtml(s.label)} · ${won(s.value)}</button>`).join("")
    : "";
  box.querySelectorAll(".ps-stop-quick").forEach(b => b.addEventListener("click", () => {
    $("ps-stop-price").value = b.dataset.v;
    psStopHint(); psDrawStop();
  }));
}

let stockQuoteRevision = 0;
async function stockQuote() {
  const revision = ++stockQuoteRevision;
  const symbol = await symbolFromInput("ps-symbol", stockQuote);
  if (symbol === null) return;                       // 종목 찾기 창에서 고르는 중
  if (!symbol) return setToast("종목코드를 입력하세요.", "error");
  $("ps-quote").innerHTML = `<span style="color:var(--text-mute);">조회 중…</span>`;
  try {
    const q = await api(`/api/paper/stocks/quote?symbol=${encodeURIComponent(symbol)}`);
    if (revision !== stockQuoteRevision || $("ps-symbol").value.trim() !== symbol) return;
    const chg = q.prev_close ? ((q.price - q.prev_close) / q.prev_close * 100) : null;
    const isForeign = q.price_local != null && q.currency && q.currency !== "KRW";

    const priceHtml = isForeign
      ? `<div class="text-xl font-bold mt-1">${fmt(q.price_local, 2)} ${escHtml(q.currency)} ${chg != null ? `<span class="text-sm ${signCls(chg)}">${fmtPct(chg)}</span>` : ""}</div>
         <div class="text-sm" style="color:var(--text-mute);">약 ${won(q.price)}</div>`
      : `<div class="text-xl font-bold mt-1">${fmt(q.price, 0)} ${escHtml(q.currency)} ${chg != null ? `<span class="text-sm ${signCls(chg)}">${fmtPct(chg)}</span>` : ""}</div>`;

    $("ps-quote").innerHTML = `<strong>${escHtml(q.name)}</strong> <span class="text-xs" style="color:var(--text-mute);">${escHtml(q.symbol)} · ${escHtml(q.market)}</span>
      ${priceHtml}
      ${q.fx_note ? `<div class="text-xs mt-1" style="color:var(--text-mute);">${escHtml(q.fx_note)}</div>` : ""}
      ${q.quote_label ? `<div class="text-xs" style="color:var(--text-mute);">${escHtml(q.quote_label)} · 체결 직전에 다시 확인합니다</div>` : ""}`;
    $("ps-symbol").value = q.symbol;
    // 일봉 차트 + 종목 서랍 입구(국내 6자리 코드일 때만 — 수집 일봉 · 종목 허브가 국내 종목 기준)
    const domestic = !!scCode(q.symbol);
    $("ps-chart-wrap").hidden = !domestic;
    $("ps-hub-open").dataset.hubOpen = domestic ? scCode(q.symbol) : "";
    $("ps-hub-open").dataset.hubName = q.name || "";
    $("ps-hub-open").hidden = !domestic;
    if (domestic) { psMainSym = q.symbol; psDrawMain(); }
  } catch (e) {
    if (revision === stockQuoteRevision && $("ps-symbol").value.trim() === symbol) {
      $("ps-quote").innerHTML = `<span class="text-red-500">${escHtml(e.message)}</span>`;
      $("ps-chart-wrap").hidden = true;
    }
  }
}

async function stockPreview(side) {
  const symbol = await symbolFromInput("ps-symbol", pickedToast);
  if (symbol === null) return;
  const quantity = parseInt($("ps-qty").value);
  if (!symbol || !quantity) return setToast("종목코드와 수량을 입력하세요.", "error");
  try {
    const p = await api("/api/paper/stocks/orders/preview", { method: "POST", body: { symbol, side, quantity } });
    $("ps-preview").innerHTML = `
      <div class="rounded-xl border p-3 text-sm" style="border-color:${p.executable ? "var(--green-bd)" : "var(--red-bd)"}">
        <div class="flex items-center gap-2 mb-2">${sideBadge(p.side)} <strong>${escHtml(p.name)}</strong> <span class="text-xs" style="color:var(--text-mute);">${escHtml(p.symbol)}</span>
          <span class="ml-auto text-xs font-bold ${p.executable ? "text-emerald-600" : "text-red-600"}">${p.executable ? "체결 가능" : escHtml(p.reason || "체결 불가")}</span></div>
        <div class="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
          <div>예상 단가<br><b>${won(p.estimatedPrice)}</b></div>
          <div>예상 금액<br><b>${won(p.estimatedAmount)}</b></div>
          <div>수수료·세금<br><b>${won(p.totalCost || 0)}</b></div>
          <div>순정산액<br><b>${won(p.netAmount ?? p.estimatedAmount)}</b></div>
          <div>현금 ${won(p.cashBefore)} → <b>${won(p.cashAfter)}</b></div>
          <div class="col-span-3">보유 ${fmt(p.positionBefore)}주 → <b>${fmt(p.positionAfter)}주</b></div>
        </div>
        ${p.market_open === false ? `<div class="text-sm mt-2 font-semibold" style="color:#d97706;">
           장이 닫혀 있습니다 — 마지막 종가(${p.quoteAsOf ? p.quoteAsOf.slice(5,10) : "최근"})로 모의 체결됩니다
        </div>` : ""}
        <div class="text-xs mt-2" style="color:var(--text-mute);">${escHtml(p.notice)}</div>
      </div>`;
  } catch (e) { setToast(e.message, "error"); }
}

async function stockOrder(side) {
  const symbol = await symbolFromInput("ps-symbol", pickedToast);
  if (symbol === null) return;
  const quantity = parseInt($("ps-qty").value);
  if (!symbol || !(quantity >= 1)) return setToast("종목코드와 수량(1주 이상)을 입력하세요.", "error");

  // 이슈 #256 — 장 닫힘 안내. resolve_stock 은 60초 캐시라 이미 조회했으면 즉시 반환.
  // 시세 조회 실패해도 주문은 진행(안내만 생략).
  let closedLine = "";
  try {
    const q = await api(`/api/paper/stocks/quote?symbol=${encodeURIComponent(symbol)}`);
    if (q.market_open === false) {
      const when = q.quote_as_of ? `${q.quote_as_of.slice(5, 10)} 종가` : "최근 종가";
      closedLine = `지금은 장이 닫혀 있습니다 — 마지막 ${when}로 모의 체결합니다.\n\n`;
    }
  } catch { /* 무시 */ }

  const ok = confirm(
    closedLine +
    `${side === "BUY" ? "매수" : "매도"} 주문을 냅니다.\n\n` +
    `종목: ${symbol}\n수량: ${quantity}주\n유형: 시장가 (즉시 체결)\n\n` +
    `체결가는 체결 직전에 다시 받은 가격입니다 — 증권사 키를 연결했으면 증권사 조회 값, 아니면 지연 시세(약 20분)입니다.\n미체결·취소는 지원하지 않습니다. 계속할까요?`
  );
  if (!ok) return;
  try {
    const r = await api("/api/paper/stocks/orders", { method: "POST", body: { symbol, side, quantity } });
    const closedTag = (r.market_open === false) ? " · 장 닫힘" : "";
    setToast(
      `${r.name} ${side === "BUY" ? "매수" : "매도"} ${fmt(r.quantity)}주 체결 ` +
      `(@${won(r.price)}${r.quote_label ? ` · ${r.quote_label}` : ""}${closedTag})`,
      "ok"
    );
    $("ps-preview").innerHTML = "";
    loadPaperStock();
  } catch (e) { setToast(e.message, "error"); }
}

function psPositionsBody(positions) {
  return `<table><thead><tr><th>종목</th><th style="text-align:right">수량</th><th style="text-align:right">평균단가</th><th style="text-align:right">현재가</th><th style="text-align:right">평가금액</th><th style="text-align:right">손익</th><th></th></tr></thead>
      <tbody>${positions.length ? positions.map(p => `<tr>
        <td>${escHtml(p.name)}<div class="text-xs" style="color:var(--text-mute);">${escHtml(p.symbol)}</div></td>
        <td style="text-align:right">${fmt(p.quantity)}</td><td style="text-align:right">${won(p.avgPrice)}</td><td style="text-align:right">${won(p.currentPrice)}</td>
        <td style="text-align:right">${won(p.evalAmount)}</td><td style="text-align:right" class="${signCls(p.pnl)}">${won(p.pnl)}<div class="text-xs">${fmtPct(p.pnlRate)}</div></td>
        <td style="text-align:right"><button class="btn-secondary text-xs ps-sell-all" data-symbol="${escHtml(p.symbol)}" data-qty="${p.quantity}">전량매도</button></td></tr>`).join("") : emptyRow(7, "보유 종목이 없습니다.")}</tbody></table>`;
}

// 보유 종목 — 필터 칩 없이 새로고침만. 현재가는 서버가 읽을 때마다 시세를 다시 붙이고(받지 못한 종목은 평균단가가 그대로 보인다), 머리글의 보유 현금도 같이 다시 읽는다.
const psPositionsPanel = listPanel({
  host: "ps-positions", label: "보유 종목", unit: "종목",
  meaning: "보유 종목을 다시 읽었습니다",
  tail: "현재가는 읽는 때 서버가 시세를 다시 붙입니다(시세를 못 받은 종목은 평균단가로 보입니다) · 신호는 새로 계산하지 않습니다",
  load: async () => ({ rows: (await api("/api/paper/stocks/positions")).positions }),
  body: psPositionsBody,
  after: host => host.querySelectorAll(".ps-sell-all").forEach(b => b.addEventListener("click", () => {
    $("ps-symbol").value = b.dataset.symbol; $("ps-qty").value = b.dataset.qty; stockOrder("SELL");
  })),
  alsoOnRefresh: refreshStockCash,
});

function loadStockPositions() { return psPositionsPanel.load(); }

function psHistoryBody(history) {
  return `<table>
      <thead><tr>
        <th>시각</th>
        <th>매매</th>
        <th>종목</th>
        <th style="text-align:right">수량</th>
        <th style="text-align:right">단가</th>
        <th style="text-align:right">거래금액</th>
        <th style="text-align:right">수수료</th>
        <th style="text-align:right">세금</th>
        <th style="text-align:right">순정산액</th>
        <th>출처</th>
      </tr></thead>
      <tbody>${history.length ? history.map(o => {
      const isBuy = (o.type || "").toUpperCase() === "BUY";
      const fee = (o.commission || 0) + (o.fee_clearing || 0);
      const tax = (o.tax_transfer || 0) + (o.tax_rural || 0);
      const net = o.net_amount != null ? o.net_amount : o.amount;
      const sign = isBuy ? "−" : "+";
      const netColor = isBuy ? "var(--red)" : "var(--green)";

      return `<tr>
          <td class="text-xs">${ts(o.ts)}</td>
          <td>${sideBadge(o.type)}</td>
          <td>${escHtml(o.name)} <span class="text-xs" style="color:var(--text-mute);">${escHtml(o.symbol)}</span>
            <div class="text-xs">주문번호 ${escHtml(o.order_id || '-')} · ${o.order_kind === 'stop' ? '스탑' : '시장가'}</div></td>
          <td style="text-align:right">${fmt(o.quantity)}</td>
          <td style="text-align:right">${won(o.price)}</td>
          <td style="text-align:right">${won(o.amount)}</td>
          <td style="text-align:right;color:var(--text-dim);">${fee > 0 ? won(fee) : "-"}</td>
          <td style="text-align:right;color:var(--text-dim);">${tax > 0 ? won(tax) : "-"}</td>
          <td style="text-align:right;font-weight:700;color:${netColor};white-space:nowrap;">
            ${sign}${won(net)}
          </td>
          <td class="text-xs">${escHtml(o.source)}</td>
        </tr>`;
    }).join("") : emptyRow(10, "주문 내역이 없습니다.")}</tbody>
    </table>`;
}

// 주문 내역 — 칩: 매매 · 출처(응답에 있는 값만). 서버는 limit=30 으로 주므로 그 줄 안에서만 거른다.
const psHistoryPanel = listPanel({
  host: "ps-history", label: "주문 내역 필터", unit: "줄",
  groups: (rows, f) => [sideGroup(), sourceGroup(rows, f.source)],
  getters: { side: r => sideOf(r.type), source: r => r.source },
  limitNote: "받은 줄(최근 30줄까지) 안에서 거릅니다",
  meaning: "주문 내역을 다시 읽었습니다",
  tail: "신호는 새로 계산하지 않습니다",
  load: async () => ({ rows: (await api("/api/paper/stocks/orders/history?limit=30")).history }),
  body: psHistoryBody,
});

function loadStockHistory() { return psHistoryPanel.load(); }

/* ────────────────────────────────────────────────────────────────
 * B5 · 스탑(감시) 주문 (paper-stock)
 * ──────────────────────────────────────────────────────────────── */
function psStopBody(orders) {
  if (!orders.length) return `<div class="text-xs" style="color:var(--text-mute);">대기 중인 스탑 주문이 없습니다.</div>`;
  return `<table><thead><tr>
      <th>등록 시각</th><th>매매</th><th>종목</th>
      <th style="text-align:right">수량</th>
      <th style="text-align:right">스탑가</th>
      <th></th></tr></thead><tbody>${
      orders.map(o => `<tr>
        <td class="text-xs">${escHtml((o.created_at || "").slice(0, 19).replace("T", " "))}</td>
        <td>${sideBadge(o.side)}</td>
        <td>${escHtml(o.name)} <span class="text-xs" style="color:var(--text-mute);">${escHtml(o.symbol)}</span></td>
        <td style="text-align:right">${fmt(o.quantity)}</td>
        <td style="text-align:right">${won(o.stop_price)}</td>
        <td style="text-align:right"><button class="btn-secondary text-xs ps-stop-cancel" data-id="${escHtml(o.order_id)}">취소</button></td>
      </tr>`).join("")}</tbody></table>`;
}

// 대기 중인 스탑 주문 — 새로고침만(목록이 짧아 칩은 두지 않는다)
const psStopPanel = listPanel({
  host: "ps-stop-list", label: "대기 중인 스탑 주문", unit: "줄",
  meaning: "대기 중인 스탑 주문을 다시 읽었습니다",
  tail: "신호는 새로 계산하지 않습니다",
  load: async () => ({ rows: (await api("/api/paper/stocks/orders/stop")).orders }),
  body: psStopBody,
  after: host => host.querySelectorAll(".ps-stop-cancel").forEach(b => b.addEventListener("click", () => cancelStopOrder(b.dataset.id))),
});

function loadStopOrders() { return psStopPanel.load(); }

async function stockStopQuote() {
  const symbol = await symbolFromInput("ps-stop-symbol", stockStopQuote);
  if (symbol === null) return;                       // 종목 찾기 창에서 고르는 중
  if (!symbol) return setToast("종목코드를 입력하세요.", "error");
  $("ps-stop-quote").innerHTML = `<span style="color:var(--text-mute);">조회 중…</span>`;
  try {
    const q = await api(`/api/paper/stocks/quote?symbol=${encodeURIComponent(symbol)}`);
    const chg = q.prev_close ? ((q.price - q.prev_close) / q.prev_close * 100) : null;
    $("ps-stop-quote").innerHTML = `<strong>${escHtml(q.name)}</strong> <span class="text-xs" style="color:var(--text-mute);">${escHtml(q.symbol)} · ${escHtml(q.market)}</span>
      <div class="text-lg font-bold mt-1">${fmt(q.price, q.currency === "KRW" ? 0 : 2)} ${escHtml(q.currency)} ${chg != null ? `<span class="text-sm ${signCls(chg)}">${fmtPct(chg)}</span>` : ""}</div>`;
    // 스탑가 칸은 채우지 않는다(2026-11-02 · 현재가를 그대로 두고 등록하면 다음 1분 점검에서 바로 체결됐다) —
    // 대신 현재가와 견준 방향 안내 · 빠른 단추(−3% · −5% · −10%) · 일봉 차트의 스탑가 점선으로 돕는다.
    // 종목코드 정규화 (005930 → 005930.KS)
    $("ps-stop-symbol").value = q.symbol;
    psStopSym = q.symbol;
    psStopCurrent = Number(q.price) > 0 ? Number(q.price) : null;
    const domestic = !!scCode(q.symbol);
    $("ps-stop-chart-wrap").hidden = !domestic;
    psStopHint(); psStopQuick();
    if (domestic) psDrawStop();
  } catch (e) {
    $("ps-stop-quote").innerHTML = `<span class="text-red-500">${escHtml(e.message)}</span>`;
    psStopCurrent = null; $("ps-stop-chart-wrap").hidden = true; psStopHint(); psStopQuick();
  }
}

async function placeStopOrder(side) {
  const symbol = await symbolFromInput("ps-stop-symbol", pickedToast);
  if (symbol === null) return;                       // 종목 찾기 창에서 고르는 중
  const quantity = parseInt($("ps-stop-qty").value);
  const stop_price = parseFloat($("ps-stop-price").value);
  if (!symbol || !quantity || !stop_price) return setToast("종목코드 · 수량 · 스탑가를 입력하세요.", "error");
  // 방향 검사는 서버의 새 기준 시세로 확정한다. 이전 화면 시세로 승인 여부를 정하지 않는다.
  const sameStock = psStopSym && symbol.toUpperCase() === psStopSym.toUpperCase();
  if (sameStock && scWouldFireNow(side, psStopCurrent, stop_price)) {
    setToast("표시 시세 기준으로 스탑 방향이 맞지 않습니다. 서버에서 최신 기준 시세로 다시 확인합니다.", "error");
  }
  try {
    const r = await api("/api/paper/stocks/orders/stop", {
      method: "POST",
      body: { symbol, side, quantity, stop_price },
    });
    setToast(`${r.name} ${side === "BUY" ? "매수" : "매도"} 스탑 ${fmt(r.quantity)}주 @${won(r.stop_price)} 등록됨`, "ok");
    $("ps-stop-symbol").value = "";
    $("ps-stop-qty").value = "";
    $("ps-stop-price").value = "";
    psStopSym = ""; psStopCurrent = null; $("ps-stop-chart-wrap").hidden = true; psStopHint(); psStopQuick();
    loadStopOrders();
  } catch (e) { setToast(e.message, "error"); }
}

async function cancelStopOrder(orderId) {
  if (!confirm("이 스탑 주문을 취소할까요?")) return;
  try {
    await api(`/api/paper/stocks/orders/stop/${encodeURIComponent(orderId)}`, { method: "DELETE" });
    setToast("스탑 주문을 취소했습니다.", "ok");
    loadStopOrders();
  } catch (e) { setToast(e.message, "error"); }
}

/* ────────────────────────────────────────────────────────────────
 * 3. 코인 모의매매 (Upbit KRW 마켓)
 * ──────────────────────────────────────────────────────────────── */
async function loadPaperCrypto() {
  if (!cryptoMarkets.length) {
    try {
      const { markets } = await api("/api/paper/crypto/market-list");
      const major = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL", "KRW-DOGE", "KRW-ADA", "KRW-USDT"];
      cryptoMarkets = [...markets].sort((a, b) => {
        const ia = major.indexOf(a.market), ib = major.indexOf(b.market);
        return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib) || a.koreanName.localeCompare(b.koreanName, "ko");
      });
      $("pc-market").innerHTML = cryptoMarkets.map(m => `<option value="${escHtml(m.market)}">${escHtml(m.koreanName)} (${escHtml(m.market)})</option>`).join("");
      if (cryptoMarkets.some(m => m.market === "KRW-BTC")) $("pc-market").value = "KRW-BTC";
    } catch (e) { setToast(e.message, "error"); }
  }
  cryptoTicker();
  loadCryptoHold();
  loadCryptoHistory();
  loadCryptoRankings();
}

// ── 코인 일봉 차트(업비트 공개 시세 · 화면에만 · 저장하지 않음 · 2026-10-30 ①-20) ──────────────────────────────
const PC_LWC_SRC = "/js/vendor/lightweight-charts/lightweight-charts-5.2.1.min.js";
let pcChart = null, pcChartSeq = 0, pcLwcPromise = null;
let pcSeries = null, pcLastPoint = null, pcPts = [];          // 실시간이 오늘 봉(마지막 점)을 움직이려고 들고 있는다

function pcLoadLwc() {
  if (window.LightweightCharts) return Promise.resolve(window.LightweightCharts);
  if (!pcLwcPromise) {
    pcLwcPromise = new Promise((resolve, reject) => {
      const el = document.createElement("script");
      el.src = PC_LWC_SRC;
      const timer = setTimeout(() => reject(new Error("timeout")), 15000);
      el.onload = () => { clearTimeout(timer); window.LightweightCharts ? resolve(window.LightweightCharts) : reject(new Error("empty")); };
      el.onerror = () => { clearTimeout(timer); reject(new Error("load")); };
      document.head.appendChild(el);
    }).catch(e => { pcLwcPromise = null; throw e; });
  }
  return pcLwcPromise;
}

async function pcDrawChart(code) {
  const box = $("pc-chart"), note = $("pc-chart-note");
  if (!box || !note) return;
  const seq = ++pcChartSeq;
  if (pcChart) { pcChart.remove(); pcChart = null; }
  pcSeries = null; pcLastPoint = null; pcPts = [];
  box.innerHTML = "";
  note.textContent = "일봉을 불러오는 중…";
  let pts = [];
  try {
    const r = await api(`/api/paper/crypto/${encodeURIComponent(code)}/candles?unit=days&count=120`);
    pts = coinPoints(r.candles);
  } catch (e) { if (seq === pcChartSeq) note.textContent = `일봉을 받지 못했습니다: ${e.message}`; return; }
  if (seq !== pcChartSeq) return;
  pcPts = pts;
  note.textContent = coinChartSummary(pts, pcWsState === "live");
  if (!pts.length) return;
  let L;
  try { L = await pcLoadLwc(); } catch (e) { note.textContent += " (차트 라이브러리를 불러오지 못했습니다.)"; return; }
  if (seq !== pcChartSeq) return;
  pcChart = L.createChart(box, {
    autoSize: true,
    layout: { background: { color: "#ffffff" }, textColor: "#334155", fontSize: 11, attributionLogo: true },
    grid: { vertLines: { color: "#f1f5f9" }, horzLines: { color: "#eef1f6" } },
    // 가장자리 눈금 글자가 반쯤 잘리던 문제(위 가격 「120,000,000」 · 왼쪽 날짜 「15일」 · 사용자 11-01) — 라이브러리의 가장자리 눈금 보이기 옵션을 켠다
    rightPriceScale: { borderColor: "#dde2ec", scaleMargins: { top: 0.08, bottom: 0.18 }, ensureEdgeTickMarksVisible: true },
    timeScale: { borderColor: "#dde2ec", fixLeftEdge: true, fixRightEdge: true, lockVisibleTimeRangeOnResize: true, ensureEdgeTickMarksVisible: true },
    localization: { locale: "ko-KR", dateFormat: "yyyy-MM-dd" },
    handleScroll: false, handleScale: false,
  });
  const series = pcChart.addSeries(L.LineSeries, {
    color: "#4361ee", lineWidth: 2, priceLineVisible: false,
    priceFormat: { type: "custom", formatter: v => Math.round(v).toLocaleString("ko-KR"), minMove: 1 },
  });
  pcLastPoint = { time: pts[pts.length - 1].time, value: pts[pts.length - 1].value };   // 라이브러리가 넘긴 객체를 바꿀 수 있어 먼저 복사해 둔다
  series.setData(pts.map(p => ({ time: p.time, value: p.value })));
  pcChart.timeScale().fitContent();
  pcSeries = series;
  if (pcLive) pcOnTick(pcLive);                                  // 차트보다 먼저 온 체결이 있으면 오늘 봉에 바로 반영
}

// ── 코인 실시간(업비트 공개 WebSocket · 브라우저가 직접 연결 · 화면에만 · 2026-10-30 사용자 결정 · 설계 Figma 「Qurious · 코인 모의매매」 03) ──────
// 현재가 · 오늘 봉은 체결마다 움직이고, 주문에 쓰이는 가격은 앱이 따로 확인한 값이라 옆에 같이 보인다(둘이 다르면 알림).
let pcWs = null, pcWsCode = "", pcWsState = "connecting", pcWsAttempt = 0, pcWsRetry = null, pcWsPing = null, pcWsGuard = null, pcOrderPoll = null, pcResumeCode = "";
let pcLive = null;          // 마지막 체결 {price, tradeTs, changeRate}
let pcOrderQuote = null;    // 앱이 확인한 주문 가격 {price, checkedAt} — checkedAt 은 앱에 물어본 시각이다(값 자체의 시각이 아님)

function pcRenderGap() {
  const line = $("pc-order-price-line"), warn = $("pc-gap-warn"), note = $("pc-order-price-note");
  if (!line || !warn) return;
  line.textContent = orderPriceLine(pcOrderQuote && pcOrderQuote.price, pcOrderQuote && pcOrderQuote.checkedAt);
  if (note) note.textContent = COIN_SOURCE_NOTE;
  const g = priceGap({ live: pcLive && pcLive.price, order: pcOrderQuote && pcOrderQuote.price, checkedAt: pcOrderQuote && pcOrderQuote.checkedAt, now: Date.now() });
  warn.textContent = g.text;
  warn.style.display = g.warn ? "" : "none";
}

function pcRenderLive() {
  const b = liveBadge(pcWsState, pcLive && pcLive.tradeTs), el = $("pc-live-badge");
  if (el) {
    el.textContent = b.text;
    el.style.color = b.tone === "ok" ? "#059669" : b.tone === "warn" ? "#d97706" : "var(--text-mute)";
  }
  const p = $("pc-live-price"), r = $("pc-live-rate");
  if (p && pcLive) p.textContent = won(pcLive.price);
  if (p) p.style.opacity = pcWsState === "reconnecting" ? "0.55" : "1";      // 연결이 끊기면 마지막 값을 흐리게
  if (r && pcLive && pcLive.changeRate != null) { r.textContent = fmtPct(pcLive.changeRate); r.className = `text-sm ${signCls(pcLive.changeRate)}`; }
  const cn = $("pc-chart-note");
  if (cn && pcPts.length) cn.textContent = coinChartSummary(pcPts, pcWsState === "live");
  pcRenderGap();
}

function pcOnTick(t) {
  pcLive = t;
  if (pcSeries && pcLastPoint) {
    const day = coinCandleDate(t.tradeTs);
    if (day >= pcLastPoint.time) {                               // 날짜가 앞서면(한국 시각 09:00 경계) 새 봉
      pcLastPoint = { time: day, value: t.price };
      // 차트 라이브러리는 update 에 넘긴 객체의 time 을 제자리에서 바꾼다 — 복사본을 넘겨야 다음 체결의 날짜 비교가 문자열로 남는다
      try { pcSeries.update({ time: day, value: t.price }); } catch (_) { /* 차트가 다시 그려지는 중이면 다음 체결에 */ }
    }
  }
  pcRenderLive();
}

function pcStopLive() {
  clearTimeout(pcWsRetry); clearInterval(pcWsPing); clearInterval(pcWsGuard); clearInterval(pcOrderPoll);
  pcWsRetry = pcWsPing = pcWsGuard = pcOrderPoll = null;
  if (pcWs) { pcWs.onopen = pcWs.onmessage = pcWs.onclose = pcWs.onerror = null; try { pcWs.close(); } catch (_) { /* 이미 닫힘 */ } pcWs = null; }
}

async function pcPollOrderQuote() {
  const code = pcWsCode;
  if (!code) return;
  try {
    const { tickers } = await api(`/api/paper/crypto/ticker?markets=${encodeURIComponent(code)}`);
    if (code !== pcWsCode) return;
    const t = tickers && tickers[0];
    pcOrderQuote = t ? { price: t.price, checkedAt: Date.now() } : null;
  } catch (_) { /* 확인에 실패하면 이전 값과 시각을 그대로 둔다 — 확인 나이가 늘어 경고가 뜬다 */ }
  pcRenderGap();
}

function pcConnect() {
  const code = pcWsCode;
  let ws;
  try { ws = new WebSocket(UPBIT_WS_URL); } catch (_) { pcWsState = "unsupported"; pcRenderLive(); return; }
  ws.binaryType = "arraybuffer";
  pcWs = ws;
  ws.onopen = () => {
    if (pcWs !== ws) return;
    pcWsAttempt = 0; pcWsState = "live";
    ws.send(coinSubscribeMessage(code, `qurious-${Date.now().toString(36)}`));
    clearInterval(pcWsPing);
    pcWsPing = setInterval(() => { try { ws.send("PING"); } catch (_) { /* 끊기면 onclose 가 다시 연결 */ } }, PING_MS);
    pcRenderLive();
  };
  ws.onmessage = ev => {
    if (pcWs !== ws) return;
    const t = parseUpbitTicker(decodeWsData(ev.data), code);
    if (t) pcOnTick(t);
  };
  ws.onclose = () => {
    if (pcWs !== ws) return;
    clearInterval(pcWsPing);
    pcWsState = "reconnecting"; pcRenderLive();
    pcWsRetry = setTimeout(pcConnect, reconnectDelay(pcWsAttempt++));
  };
  ws.onerror = () => { try { ws.close(); } catch (_) { /* 이미 닫힘 */ } };
}

function pcStartLive(code) {
  pcStopLive();
  pcWsCode = code; pcLive = null; pcWsAttempt = 0;
  if (typeof WebSocket === "undefined") { pcWsState = "unsupported"; pcRenderLive(); return; }
  pcWsState = "connecting"; pcRenderLive();
  pcConnect();
  // 이 화면을 떠나면 연결을 닫고, 5초마다 주문 가격 확인 나이를 다시 잰다
  pcWsGuard = setInterval(() => { const el = $("pc-ticker"); if (!el || !el.offsetParent) { pcStopLive(); return; } pcRenderGap(); }, 5000);
  pcOrderPoll = setInterval(pcPollOrderQuote, 5000);
}

// 탭이 숨겨지면 연결을 닫고 돌아오면 다시 연결한다(설계 제안 — 보지 않는 동안 연결을 붙들지 않는다)
document.addEventListener("visibilitychange", () => {
  if (document.hidden) { if (pcWsCode && pcWs) { pcResumeCode = pcWsCode; pcStopLive(); } return; }
  if (!pcResumeCode) return;
  const c = pcResumeCode; pcResumeCode = "";
  const el = $("pc-ticker"), sel = $("pc-market");
  if (el && el.offsetParent && sel && sel.value === c) cryptoTicker();
});

async function cryptoTicker() {
  const code = $("pc-market").value;
  if (!code) return;
  try {
    const [{ tickers }, dom] = await Promise.all([
      api(`/api/paper/crypto/ticker?markets=${encodeURIComponent(code)}`),
      api(`/api/paper/crypto/${encodeURIComponent(code)}/domestic-prices`),
    ]);
    const t = tickers[0];
    const m = cryptoMarkets.find(x => x.market === code) || {};
    $("pc-ticker").innerHTML = t ? `<strong>${escHtml(m.koreanName || code)}</strong> <span class="text-xs" style="color:var(--text-mute);">${escHtml(code)}</span>
      <div class="text-xl font-bold mt-1"><span id="pc-live-price">${won(t.price)}</span> <span id="pc-live-rate" class="text-sm ${signCls(t.changeRate)}">${fmtPct(t.changeRate)}</span></div>
      <div class="text-xs" style="color:var(--text-mute);">24h 고가 ${won(t.high24h)} · 저가 ${won(t.low24h)} · 거래대금 ${fmt(t.accTradePrice24h / 1e8, 1)}억</div>` : `<span class="text-red-500">시세 없음</span>`;
    // 시세 출처 · 한계 · 주문 체결 방식 글(설계 결정 ① 2026-10-30 — coinview.js) + 일봉 차트 + 실시간(오늘 봉 · 현재가 · 주문 가격 옆 비교)
    $("pc-source-note").textContent = COIN_LIVE_NOTE;
    $("pc-order-note").innerHTML = COIN_ORDER_NOTE.map(l => `<div>${escHtml(l)}</div>`).join("");
    pcOrderQuote = t ? { price: t.price, checkedAt: Date.now() } : null;
    pcDrawChart(code);
    if (pcWs && pcWsCode === code && pcWsState === "live") pcRenderLive(); else pcStartLive(code);
    const p = dom.prices || {};
    $("pc-domestic").innerHTML = `<div class="text-xs font-semibold mb-1">국내 거래소 가격 비교 ${dom.spreadPct != null ? `<span style="color:var(--text-mute);">(최대 스프레드 ${dom.spreadPct}%)</span>` : ""}</div>
      <div class="grid grid-cols-3 gap-2 text-xs">${[["upbit", "Upbit"], ["bithumb", "Bithumb"], ["korbit", "Korbit"]].map(([k, label]) => `<div class="rounded-lg p-2" style="background:var(--surf);border:1px solid var(--border);"><div style="color:var(--text-dim);font-weight:600;">${label}</div><b>${p[k] ? won(p[k]) : "-"}</b></div>`).join("")}</div>`;
  } catch (e) { $("pc-ticker").innerHTML = `<span class="text-red-500">${escHtml(e.message)}</span>`; }
}

const MIN_CRYPTO_ORDER_KRW = 1000;

async function cryptoPreview(side) {
  const marketCode = $("pc-market").value;
  const body = { marketCode, side };
  if (side === "BUY") body.buyKrw = parseFloat(String($("pc-buy-krw").value).replace(/,/g, ""));
  else body.sellCount = parseFloat($("pc-sell-count").value);
  if (side === "BUY" && (!Number.isFinite(body.buyKrw) || body.buyKrw < MIN_CRYPTO_ORDER_KRW))
    return setToast(body.buyKrw ? "최소 주문 금액은 1,000원입니다." : "매수 금액을 입력하세요.", "error");
  if (side === "SELL" && !body.sellCount) return setToast("매도 수량을 입력하세요.", "error");
  if (side === "BUY" ? !body.buyKrw : !body.sellCount) return setToast(side === "BUY" ? "매수 금액을 입력하세요." : "매도 수량을 입력하세요.", "error");
  // 2026-11-04 #530 2-2 — 실행 단추와 같은 최소 금액을 미리보기에도(1,000원은 이 앱 화면의 정책이며 거래소 공식 최소 금액이 아니다)
  if (side === "BUY" && !(body.buyKrw >= 1000)) return setToast("최소 주문 금액은 1,000원입니다(이 앱의 정책).", "error");
  try {
    const p = await api("/api/paper/trade/order/preview", { method: "POST", body });
    const settlementLabel = side === "BUY" ? "예상 현금 차감" : "예상 순정산액";
    $("pc-preview").innerHTML = `<div class="rounded-xl border p-3 text-sm" style="border-color:${p.executable ? "var(--green-bd)" : "var(--red-bd)"}">
      <div class="flex items-center gap-2 mb-2">${sideBadge(p.side)} <strong>${escHtml(p.koreanName)}</strong> <span class="text-xs" style="color:var(--text-mute);">${escHtml(p.marketCode)}</span>
        <span class="ml-auto text-xs font-bold ${p.executable ? "text-emerald-600" : "text-red-600"}">${p.executable ? "체결 가능" : escHtml(p.reason || "체결 불가")}</span></div>
      <div class="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
        <div>기준 시세<br><b>${won(p.referencePrice)}</b></div>
        <div>예상 체결가<br><b>${won(p.estimatedPrice)}</b></div>
        <div>수량<br><b>${fmt(p.quantity, 8)}</b></div>
        <div>체결금액<br><b>${won(p.estimatedAmount)}</b></div>
        <div>예상 수수료<br><b>${won(p.estimatedCommission)}</b></div>
        <div>슬리피지 추정액<br><b>${won(p.estimatedSlippage)}</b></div>
        <div>${settlementLabel}<br><b>${won(p.estimatedNetAmount)}</b></div>
        <div>현금 / 보유<br><b>${won(p.cashBefore)}</b> / ${fmt(p.heldQuantity, 8)}</div>
      </div>
      <div class="text-xs mt-2" style="color:var(--text-mute);">${escHtml(p.notice)}</div></div>`;
  } catch (e) { setToast(e.message, "error"); }
}

async function cryptoOrder(side) {
  const marketCode = $("pc-market").value;
  try {
    let r;
    if (side === "BUY") {
      const buyKrw = parseFloat(String($("pc-buy-krw").value).replace(/,/g, ""));
      if (!(buyKrw >= MIN_CRYPTO_ORDER_KRW)) return setToast(buyKrw ? "최소 주문 금액은 1,000원입니다." : "매수 금액을 입력하세요.", "error");   // 클릭 점검 Y1 — 최소 금액이 화면 속성에만 있던 것
      if (!(buyKrw >= 1000)) return setToast(buyKrw ? "최소 주문 금액은 1,000원입니다(이 앱의 정책)." : "매수 금액을 입력하세요.", "error");   // 클릭 점검 Y1 — 최소 금액이 화면 속성에만 있던 것
      r = await api("/api/paper/trade/order/buy", { method: "POST", body: { marketCode, buyKrw } });
    } else {
      const sellCount = parseFloat($("pc-sell-count").value);
      if (!(sellCount > 0)) return setToast("매도 수량을 입력하세요.", "error");
      r = await api("/api/paper/trade/order/sell", { method: "POST", body: { marketCode, sellCount } });
    }
    const settlementLabel = side === "BUY" ? "현금 차감" : "순정산";
    setToast(
      `${marketCode} ${side === "BUY" ? "매수" : "매도"} 체결 · ${fmt(r.quantity, 8)} @${won(r.price)} · 수수료 ${won(r.commission)} · ${settlementLabel} ${won(r.netAmount)}`,
      "ok"
    );
    $("pc-preview").innerHTML = "";
    loadCryptoHold(); loadCryptoHistory();
  } catch (e) { setToast(e.message, "error"); }
}

function pcHoldHead(h) {
  return `<div class="text-xs mb-2" style="color:var(--text-mute);">매수 원금 ${won(h.totalBuyKrw)} · 평가금액 ${won(h.totalEvalKrw)}</div>`;
}

function pcHoldBody(list) {
  return `<table><thead><tr><th>코인</th><th style="text-align:right">보유수량</th><th style="text-align:right">매수평균</th><th style="text-align:right">현재가</th><th style="text-align:right">평가금액</th><th style="text-align:right">손익</th><th></th></tr></thead>
      <tbody>${list.length ? list.map(c => `<tr><td>${escHtml(c.koreanName)} <span class="text-xs" style="color:var(--text-mute);">${escHtml(c.marketCode)}</span></td>
        <td style="text-align:right">${fmt(c.holdCount, 8)}</td><td style="text-align:right">${won(c.buyAverage)}</td><td style="text-align:right">${won(c.currentPrice)}</td><td style="text-align:right">${won(c.evalKrw)}</td>
        <td style="text-align:right" class="${signCls(c.pnl)}">${won(c.pnl)}<div class="text-xs">${fmtPct(c.pnlRate)}</div></td>
        <td style="text-align:right"><button class="btn-secondary text-xs pc-sell-all" data-market="${escHtml(c.marketCode)}" data-qty="${c.holdCount}">전량매도</button></td></tr>`).join("") : emptyRow(7, "보유 코인이 없습니다.")}</tbody></table>`;
}

// 보유 코인 — 새로고침만. 현금(머리글)도 같은 응답에서 같이 바뀐다. 코인 「시세」 단추(선택 1종목 ticker)와는 따로다.
const pcHoldPanel = listPanel({
  host: "pc-hold", label: "보유 코인", unit: "종목",
  meaning: "보유 코인을 다시 읽었습니다",
  tail: "현재가는 읽는 때 서버가 시세를 다시 붙입니다 · 신호는 새로 계산하지 않습니다",
  load: async () => { const h = await api("/api/paper/trade/hold"); return { rows: h.holdCryptoList, meta: h }; },
  onData: h => { $("pc-cash").textContent = won(h.memberAsset); },
  head: pcHoldHead,
  body: pcHoldBody,
  after: host => host.querySelectorAll(".pc-sell-all").forEach(b => b.addEventListener("click", () => {
    $("pc-market").value = b.dataset.market; $("pc-sell-count").value = b.dataset.qty; cryptoOrder("SELL");
  })),
});

function loadCryptoHold() { return pcHoldPanel.load(); }

function pcHistoryBody(history) {
  return `<table><thead><tr>
    <th>시각</th><th>매매</th><th>코인</th>
    <th style="text-align:right">수량</th>
    <th style="text-align:right">기준가 / 체결가</th>
    <th style="text-align:right">체결금액</th>
    <th style="text-align:right">수수료</th>
    <th style="text-align:right">슬리피지</th>
    <th style="text-align:right">순정산</th>
    </tr></thead>
    <tbody>${history.length ? history.map(o => `<tr>
      <td class="text-xs">${ts(o.ts)}</td>
      <td>${sideBadge(o.type)}</td>
      <td>${escHtml(o.koreanName)} <span class="text-xs" style="color:var(--text-mute);">${escHtml(o.marketCode)}</span></td>
      <td style="text-align:right">${fmt(o.quantity, 8)}</td>
      <td style="text-align:right">${won(o.referencePrice ?? o.price)}<div class="text-xs" style="color:var(--text-mute);">체결 ${won(o.price)}</div></td>
      <td style="text-align:right">${won(o.amount)}</td>
      <td style="text-align:right">${o.commission == null ? "-" : won(o.commission)}</td>
      <td style="text-align:right">${o.slippageBps == null ? "-" : `${o.slippageBps} bps<div class="text-xs">${won(o.slippageAmount)}</div>`}</td>
      <td style="text-align:right">${o.netAmount == null ? "-" : won(o.netAmount)}${o.realizedPnl == null ? "" : `<div class="text-xs ${signCls(o.realizedPnl)}">실현손익 ${won(o.realizedPnl)}</div>`}</td>
    </tr>`).join("") : emptyRow(9, "거래 내역이 없습니다.")}</tbody></table>`;
}

// 거래 내역 — 칩: 매매. 서버는 limit=30 으로 준다.
const pcHistoryPanel = listPanel({
  host: "pc-history", label: "거래 내역 필터", unit: "줄",
  groups: () => [sideGroup()],
  getters: { side: r => sideOf(r.type) },
  limitNote: "받은 줄(최근 30줄까지) 안에서 거릅니다",
  meaning: "거래 내역을 다시 읽었습니다",
  tail: "신호는 새로 계산하지 않습니다",
  load: async () => ({ rows: (await api("/api/paper/trade/order/history?limit=30")).history }),
  body: pcHistoryBody,
});

function loadCryptoHistory() { return pcHistoryPanel.load(); }

function pcRankingsBody(rankings) {
  return `<table><thead><tr><th>#</th><th>코인</th><th style="text-align:right">현재가</th><th style="text-align:right">24h</th><th style="text-align:right">거래대금(24h)</th></tr></thead>
      <tbody>${rankings.map(r => `<tr class="cursor-pointer pc-rank-row" data-market="${escHtml(r.market)}"><td>${r.rank}</td><td>${escHtml(r.koreanName)} <span class="text-xs" style="color:var(--text-mute);">${escHtml(r.symbol)}</span></td><td style="text-align:right">${won(r.price)}</td><td style="text-align:right" class="${signCls(r.changeRate)}">${fmtPct(r.changeRate)}</td><td style="text-align:right">${fmt(r.accTradePrice24h / 1e8, 1)}억</td></tr>`).join("")}</tbody></table>`;
}

// 거래대금 상위 24h — 칩: 상승 · 하락(등락률 부호). 칩 줄은 스크롤 상자 밖(pc-rankings-bar)에 둬 표를 넘겨도 보인다. 번호(#)는 거르기 전 거래대금 순위 그대로.
const pcRankingsPanel = listPanel({
  host: "pc-rankings", barHost: "pc-rankings-bar", label: "거래대금 상위 필터", unit: "종목",
  groups: () => [directionGroup()],
  getters: { dir: r => directionOf(r.changeRate) },
  limitNote: "거래대금 상위 15종목 안에서 거릅니다 · 등락 0 은 상승 · 하락 어느 쪽에도 넣지 않습니다",
  meaning: "거래대금 순위를 다시 읽었습니다",
  tail: "서버가 업비트 시세를 다시 받아 옵니다 · 신호는 새로 계산하지 않습니다",
  load: async () => ({ rows: (await api("/api/paper/crypto/rankings?limit=15")).rankings.map((r, i) => ({ ...r, rank: i + 1 })) }),
  body: pcRankingsBody,
  after: host => host.querySelectorAll(".pc-rank-row").forEach(r => r.addEventListener("click", () => { $("pc-market").value = r.dataset.market; cryptoTicker(); })),
});

function loadCryptoRankings() { return pcRankingsPanel.load(); }

/* ────────────────────────────────────────────────────────────────
 * 4. 대체자산 (선물·옵션·파생·금속·부동산)
 * ──────────────────────────────────────────────────────────────── */
// 상품 구분(선물 · 옵션 · 파생상품 …)의 순서 — 상품 목록 응답에서 읽는다. 보유 · 내역 칩도 이 순서를 따라 세 곳의 칩 줄이 같다.
let altCategoryOrder = [];

function altCardHtml(m) {
  return `
      <div class="rounded-xl border border-white/10 bg-black/20 p-3 cursor-pointer pa-card" data-symbol="${escHtml(m.symbol)}">
        <div class="flex items-center justify-between"><span class="text-xs font-semibold" style="color:var(--accent);">${escHtml(m.category)}</span><span class="text-xs ${signCls(m.changeRate)}">${fmtPct(m.changeRate)}</span></div>
        <div class="font-semibold mt-1">${escHtml(m.name)}</div>
        <div class="text-lg font-bold">${won(m.price)} <span class="text-xs font-normal" style="color:var(--text-mute);">/ ${escHtml(m.unit)}</span></div>
        <div class="text-xs" style="color:var(--text-mute);">1단위 주문금액 ${won(m.tradeAmountPerUnit)}${m.marginRate < 100 ? ` (증거금 ${m.marginRate}%)` : ""}</div>
        <div class="text-xs mt-1" style="color:var(--text-mute);">${escHtml(m.source)}</div>
      </div>`;
}

// 상품 카드 — 칩: 구분(응답의 category). 새로고침은 상품 시세를 서버에서 다시 읽는다(차트는 그대로 · 주문 칸 목록은 값을 유지한 채 같이 맞춘다).
const altMarketsPanel = listPanel({
  host: "pa-markets", barHost: "pa-markets-bar", label: "대체자산 상품 필터", unit: "상품",
  groups: (rows, f) => [categoryGroup(rows, [], f.category)],
  getters: { category: r => r.category },
  limitNote: rows => `받은 ${rows.length}개 상품 안에서 거릅니다(주문 칸의 상품 목록은 거르지 않습니다)`,
  meaning: "상품 시세를 다시 읽었습니다",
  tail: "상품 시세는 읽는 때 서버가 받아 옵니다(교육용 기준 시세 포함) · 신호는 새로 계산하지 않습니다",
  load: async () => { const { markets, notice } = await api("/api/paper/alternatives/markets"); return { rows: markets, meta: { notice } }; },
  onData: (meta, markets) => {
    $("pa-notice").textContent = meta.notice;
    altCategoryOrder = markets.map(m => m.category).filter((c, i, a) => c && a.indexOf(c) === i);
    const sel = $("pa-symbol");
    const prev = sel.value;
    sel.innerHTML = markets.map(m => `<option value="${escHtml(m.symbol)}">[${escHtml(m.category)}] ${escHtml(m.name)}</option>`).join("");
    if (prev) sel.value = prev;
  },
  onError: e => setToast(e.message, "error"),
  body: markets => markets.map(altCardHtml).join(""),
  after: host => host.querySelectorAll(".pa-card").forEach(c => c.addEventListener("click", () => { $("pa-symbol").value = c.dataset.symbol; altChartLoad(); })),
});

async function loadPaperAlt() {
  await altMarketsPanel.load();
  altChartLoad();
  loadAltPositions();
  loadAltHistory();
}

async function altChartLoad() {
  const symbol = $("pa-symbol").value;
  if (!symbol) return;
  try {
    const { data } = await api(`/api/paper/alternatives/markets/${encodeURIComponent(symbol)}/chart?days=120`);
    const el = $("pa-chart");
    if (altChart) { altChart.destroy(); altChart = null; }
    if (!window.ApexCharts) { el.innerHTML = `<div class="text-xs" style="color:var(--text-mute);">차트 라이브러리 로드 실패</div>`; return; }
    altChart = new ApexCharts(el, {
      chart: { type: "candlestick", height: 260, toolbar: { show: false }, background: "transparent" },
      series: [{ data: data.map(d => ({ x: d.time, y: [d.open, d.high, d.low, d.close] })) }],
      xaxis: { type: "category", labels: { show: false } },
      yaxis: { labels: { formatter: v => fmt(v) } },
      theme: { mode: "light" },
      plotOptions: { candlestick: { colors: { upward: "#059669", downward: "#dc2626" } } },
    });
    altChart.render();
  } catch (e) { $("pa-chart").innerHTML = `<div class="text-xs text-red-500">${escHtml(e.message)}</div>`; }
}

async function altPreview(side) {
  const symbol = $("pa-symbol").value, quantity = parseInt($("pa-qty").value);
  if (!symbol || !quantity) return setToast("상품과 수량을 입력하세요.", "error");
  try {
    const p = await api("/api/paper/alternatives/orders/preview", { method: "POST", body: { symbol, side, quantity } });
    $("pa-preview").innerHTML = `<div class="rounded-xl border p-3 text-sm" style="border-color:${p.executable ? "var(--green-bd)" : "var(--red-bd)"}">
      <div class="flex items-center gap-2 mb-2">${sideBadge(p.side)} <strong>${escHtml(p.name)}</strong> <span class="text-xs" style="color:var(--text-mute);">${escHtml(p.category)}</span>
        <span class="ml-auto text-xs font-bold ${p.executable ? "text-emerald-600" : "text-red-600"}">${p.executable ? "체결 가능" : escHtml(p.reason || "체결 불가")}</span></div>
      <div class="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs"><div>기준가<br><b>${won(p.estimatedPrice)}</b></div><div>주문금액${p.marginRate < 100 ? ` (증거금 ${p.marginRate}%)` : ""}<br><b>${won(p.estimatedAmount)}</b></div><div>보유 현금<br><b>${won(p.cashBefore)}</b></div><div>보유 수량<br><b>${fmt(p.heldQuantity)}</b></div></div>
      <div class="text-xs mt-2" style="color:var(--text-mute);">${escHtml(p.notice)}</div></div>`;
  } catch (e) { setToast(e.message, "error"); }
}

async function altOrder(side) {
  const symbol = $("pa-symbol").value, quantity = parseInt($("pa-qty").value);
  if (!symbol || !quantity) return setToast("상품과 수량을 입력하세요.", "error");
  try {
    const r = await api("/api/paper/alternatives/orders", { method: "POST", body: { symbol, side, quantity } });
    setToast(`${r.symbol} ${side === "BUY" ? "매수" : "매도"} ${fmt(r.quantity)}단위 체결 · 금액 ${won(r.amount)}`, "ok");
    $("pa-preview").innerHTML = "";
    loadAltPositions(); loadAltHistory();
  } catch (e) { setToast(e.message, "error"); }
}

function altPositionsHead(meta, ctx) {
  const filtered = Object.values(ctx.filters).some(Boolean);
  return `<div class="text-xs mb-2" style="color:var(--text-mute);">총 평가금액 ${won(meta.total)}${filtered ? " (거르기와 상관없이 전체 보유 기준)" : ""}</div>`;
}

function altPositionsBody(positions) {
  return `<table><thead><tr><th>상품</th><th style="text-align:right">수량</th><th style="text-align:right">평균가</th><th style="text-align:right">현재가</th><th style="text-align:right">평가금액</th><th style="text-align:right">손익</th><th style="text-align:right">변동성</th><th></th></tr></thead>
      <tbody>${positions.length ? positions.map(p => `<tr><td>${escHtml(p.name)} <span class="text-xs" style="color:var(--text-mute);">${escHtml(p.category)}</span></td><td style="text-align:right">${fmt(p.quantity)} ${escHtml(p.unit)}</td><td style="text-align:right">${won(p.avgPrice)}</td><td style="text-align:right">${won(p.currentPrice)}</td><td style="text-align:right">${won(p.evalAmount)}</td><td style="text-align:right" class="${signCls(p.pnl)}">${won(p.pnl)}</td><td style="text-align:right">${p.volatility != null ? p.volatility + "%" : "-"}</td>
        <td style="text-align:right"><button class="btn-secondary text-xs pa-sell-all" data-symbol="${escHtml(p.symbol)}" data-qty="${p.quantity}">전량매도</button></td></tr>`).join("") : emptyRow(8, "보유 포지션이 없습니다.")}</tbody></table>`;
}

// 보유 포지션 — 칩: 구분. 총 평가금액은 서버가 계산한 전체 보유 합계라 거르기와 상관없다.
const altPositionsPanel = listPanel({
  host: "pa-positions", label: "보유 포지션 필터", unit: "줄",
  groups: (rows, f) => [categoryGroup(rows, altCategoryOrder, f.category)],
  getters: { category: r => r.category },
  limitNote: "받은 보유 포지션 안에서 거릅니다",
  meaning: "보유 포지션을 다시 읽었습니다",
  tail: "현재가는 읽는 때 서버가 상품 시세로 다시 붙입니다 · 신호는 새로 계산하지 않습니다",
  load: async () => { const { positions, totalEvalAmount } = await api("/api/paper/alternatives/positions?volatility=1"); return { rows: positions, meta: { total: totalEvalAmount } }; },
  head: altPositionsHead,
  body: altPositionsBody,
  after: host => host.querySelectorAll(".pa-sell-all").forEach(b => b.addEventListener("click", () => {
    $("pa-symbol").value = b.dataset.symbol; $("pa-qty").value = b.dataset.qty; altOrder("SELL");
  })),
});

function loadAltPositions() { return altPositionsPanel.load(); }

function altHistoryBody(history) {
  return `<table><thead><tr><th>시각</th><th>매매</th><th>상품</th><th style="text-align:right">수량</th><th style="text-align:right">단가</th><th style="text-align:right">금액</th></tr></thead>
      <tbody>${history.length ? history.map(o => `<tr><td class="text-xs">${ts(o.ts)}</td><td>${sideBadge(o.type)}</td><td>${escHtml(o.name)} <span class="text-xs" style="color:var(--text-mute);">${escHtml(o.category)}</span></td><td style="text-align:right">${fmt(o.quantity)}</td><td style="text-align:right">${won(o.price)}</td><td style="text-align:right">${won(o.amount)}</td></tr>`).join("") : emptyRow(6, "주문 내역이 없습니다.")}</tbody></table>`;
}

// 주문 내역 — 칩: 구분. 서버는 limit=30 으로 준다.
const altHistoryPanel = listPanel({
  host: "pa-history", label: "주문 내역 필터", unit: "줄",
  groups: (rows, f) => [categoryGroup(rows, altCategoryOrder, f.category)],
  getters: { category: r => r.category },
  limitNote: "받은 줄(최근 30줄까지) 안에서 거릅니다",
  meaning: "주문 내역을 다시 읽었습니다",
  tail: "신호는 새로 계산하지 않습니다",
  load: async () => ({ rows: (await api("/api/paper/alternatives/orders/history?limit=30")).history }),
  body: altHistoryBody,
});

function loadAltHistory() { return altHistoryPanel.load(); }

/* ────────────────────────────────────────────────────────────────
 * 5. Open API 키 + 외부 연동 문서 + Alpaca 연결 테스트
 * ──────────────────────────────────────────────────────────────── */
// 마이페이지 「외부 연동」 구역이 열릴 때 mypage.js 가 부른다(Open API 설정 본체가 그 구역으로 옮겨 갔다 · 2026-11-03 S195)
export async function loadPaperOpenApi() {
  loadApiKeys();
  try {
    const d = await api("/openapi/v1/docs-summary");
    const origin = window.location.origin;
    $("po-docs").innerHTML = `
      <div class="text-xs mb-2" style="color:var(--text-mute);">Base URL <code>${escHtml(origin + d.baseUrl)}</code> · 인증 <code>${escHtml(d.auth)}</code> · 제한 ${escHtml(d.rateLimit)}</div>
      <table><thead><tr><th>Method</th><th>Path</th><th>설명</th></tr></thead><tbody>
        ${d.endpoints.map(e => `<tr><td><span class="${e.method === "POST" ? "badge-buy" : "badge-hold"}">${e.method}</span></td><td><code class="text-xs">${escHtml(e.path)}</code></td><td class="text-sm">${escHtml(e.desc)}</td></tr>`).join("")}
      </tbody></table>
      <pre class="text-xs mt-3 p-3 rounded-lg overflow-x-auto" style="background:var(--surf2);border:1px solid var(--border);">curl -H "Authorization: Bearer &lt;API_KEY&gt;" ${escHtml(origin)}/openapi/v1/quote/005930
curl -X POST -H "Authorization: Bearer &lt;API_KEY&gt;" -H "Content-Type: application/json" \\
     -d '{"symbol":"005930","side":"BUY","quantity":10}' ${escHtml(origin)}/openapi/v1/orders</pre>`;
  } catch (e) { $("po-docs").innerHTML = `<div class="text-sm text-red-500">${escHtml(e.message)}</div>`; }
}

async function loadApiKeys() {
  try {
    const { keys } = await api("/api/paper/api-keys");
    $("po-keys").innerHTML = `<table><thead><tr><th>라벨</th><th>키 앞부분</th><th>상태</th><th style="text-align:right">호출수</th><th>마지막 사용</th><th>발급일</th><th></th></tr></thead>
      <tbody>${keys.length ? keys.map(k => `<tr><td>${escHtml(k.label)}</td><td><code class="text-xs">${escHtml(k.keyPrefix)}…</code></td><td>${k.isActive ? `<span class="badge-buy">활성</span>` : `<span class="badge-hold">폐기</span>`}</td><td style="text-align:right">${fmt(k.callCount)}</td><td class="text-xs">${k.lastUsedAt ? new Date(k.lastUsedAt).toLocaleString("ko-KR") : "-"}</td><td class="text-xs">${new Date(k.createdAt).toLocaleDateString("ko-KR")}</td>
        <td style="text-align:right">${k.isActive ? `<button class="btn-secondary text-xs po-revoke" data-id="${escHtml(k.id)}">폐기</button>` : ""}</td></tr>`).join("") : emptyRow(7, "발급된 API 키가 없습니다.")}</tbody></table>`;
    const sum = $("mp-sum-external");   // 마이페이지 외부 연동 요약도 같은 구역에 있어 발급 · 폐기 직후 어긋나지 않게 맞춘다
    if (sum) { const n = keys.filter(k => k.isActive).length; sum.textContent = n ? `사용 중인 Open API 키: ${n}개` : "사용 중인 Open API 키가 없습니다."; }
    $("po-keys").querySelectorAll(".po-revoke").forEach(b => b.addEventListener("click", async () => {
      if (!confirm("이 키를 폐기하면 외부 시스템에서 더 이상 사용할 수 없습니다. 계속할까요?")) return;
      try { await api(`/api/paper/api-keys/${b.dataset.id}`, { method: "DELETE" }); setToast("키를 폐기했습니다.", "ok"); loadApiKeys(); }
      catch (e) { setToast(e.message, "error"); }
    }));
  } catch (e) { $("po-keys").innerHTML = `<div class="text-sm text-red-500">${escHtml(e.message)}</div>`; }
}

async function createApiKey() {
  const label = $("po-label").value.trim() || "My API Key";
  try {
    const k = await api("/api/paper/api-keys", { method: "POST", body: { label } });
    $("po-new-key").innerHTML = `<div class="rounded-xl border p-3 text-sm" style="border-color:var(--green-bd);">
      <div class="font-semibold mb-1">새 API 키가 발급되었습니다. 지금만 표시되니 안전한 곳에 복사하세요.</div>
      <code class="text-xs break-all" id="po-new-key-value">${escHtml(k.apiKey)}</code>
      <button class="btn-secondary text-xs ml-2" id="po-copy-key">복사</button></div>`;
    $("po-copy-key").addEventListener("click", () => navigator.clipboard?.writeText(k.apiKey).then(() => setToast("복사했습니다.", "ok")));
    $("po-label").value = "";
    loadApiKeys();
  } catch (e) { setToast(e.message, "error"); }
}

async function alpacaTest(kind) {
  const body = { api_key: $("po-alpaca-key").value.trim(), secret_key: $("po-alpaca-secret").value.trim() };
  $("po-alpaca-result").innerHTML = `<span style="color:var(--text-mute);">Alpaca Paper API 호출 중…</span>`;
  try {
    const r = await api(`/api/paper/alpaca/${kind}`, { method: "POST", body });
    $("po-alpaca-result").innerHTML = `<pre class="text-xs p-3 rounded-lg overflow-x-auto" style="background:var(--surf2);border:1px solid var(--border);">${escHtml(JSON.stringify(r, null, 2))}</pre>`;
  } catch (e) { $("po-alpaca-result").innerHTML = `<span class="text-red-500">${escHtml(e.message)}</span>`; }
}

/* ────────────────────────────────────────────────────────────────
 * 6. QuantConnect LEAN 백테스트
 * ──────────────────────────────────────────────────────────────── */
const LEAN_EXAMPLES = [
  {
    id: "bh", tag: "기준선", title: "삼성전자 매수 후 보유", ticker: "005930.KS", strategy: "buy_hold", start: "2023-01-01", cmpStart: "2022-01-01",
    focus: "아무 규칙 없이 첫날 사서 끝까지 들고 있으면 어떤 결과인가?", read: "다른 전략의 수익률·MDD를 이 값과 비교합니다."
  },
  {
    id: "ma", tag: "추세", title: "골든/데드크로스 (20·60일)", ticker: "005930.KS", strategy: "ma_cross", start: "2023-01-01", cmpStart: "2022-01-01",
    focus: "이동평균 교차 규칙이 횡보장에서 잦은 매매로 손해를 보는지 확인", read: "규칙 변경 횟수와 시장 노출 일수를 함께 보세요."
  },
  {
    id: "dca", tag: "적립", title: "SPY 월 1회 정액 매수", ticker: "SPY", strategy: "dca", start: "2022-01-01", cmpStart: "2021-01-01",
    focus: "하락장에서 분할 매수가 낙폭을 얼마나 줄이는지", read: "MDD가 매수 후 보유보다 작아지는지 확인합니다."
  },
  {
    id: "mom", tag: "모멘텀", title: "SK하이닉스 20일 돌파", ticker: "000660.KS", strategy: "momentum", start: "2023-01-01", cmpStart: "2022-01-01",
    focus: "신고가 돌파 진입이 강한 추세에서 수익을 지키는지", read: "돌파 후 되돌림으로 손절이 반복되는지 거래 횟수를 확인합니다."
  },
];

async function loadLeanView() {
  try {
    const s = await api("/api/backtests/lean/status");
    const modeLabel = { ssh: `원격 서버(${s.ssh_host}) Docker`, docker: `로컬 Docker (${s.docker_via})`, local: "LEAN 미실행 · pandas 계산만" }[s.mode] || s.mode;
    $("ql-status").innerHTML = `<span class="${s.engine_runs ? "badge-buy" : "badge-hold"}">${s.engine_runs ? "LEAN 엔진 연결됨" : "LEAN 미연결"}</span>
      <span class="text-xs ml-2" style="color:var(--text-mute);">실행 모드: ${escHtml(modeLabel)} · 이미지 ${escHtml(s.image)} · 참조데이터 ${s.reference_data_ok ? "OK" : "누락"}</span>`;
    const sel = $("ql-strategy");
    if (!sel.options.length) {
      sel.innerHTML = s.strategies.map(x => `<option value="${x.value}">${escHtml(x.label)}</option>`).join("");
      sel.dataset.hints = JSON.stringify(Object.fromEntries(s.strategies.map(x => [x.value, x.hint])));
      leanStrategyHint();
    }
  } catch (e) { $("ql-status").innerHTML = `<span class="text-red-500">${escHtml(e.message)}</span>`; }
  if (!$("ql-examples").children.length) {
    $("ql-examples").innerHTML = LEAN_EXAMPLES.map(e => `<button type="button" class="rounded-xl border border-white/10 bg-black/20 p-3 text-left ql-example" data-id="${e.id}">
      <div class="text-xs font-semibold" style="color:var(--accent);">${escHtml(e.tag)}</div><div class="font-semibold">${escHtml(e.title)}</div>
      <div class="text-xs mt-1" style="color:var(--text-mute);">${escHtml(e.focus)}</div></button>`).join("");
    $("ql-examples").querySelectorAll(".ql-example").forEach(b => b.addEventListener("click", () => applyLeanExample(b.dataset.id)));
    const today = new Date().toISOString().slice(0, 10);
    $("ql-end").value = today; $("ql-cmp-end").value = today;
  }
  loadLeanHistory();
}

function leanStrategyHint() {
  const sel = $("ql-strategy");
  const hints = JSON.parse(sel.dataset.hints || "{}");
  $("ql-strategy-hint").textContent = hints[sel.value] || "";
  const v = sel.value;
  $("ql-p-ma").style.display = v === "ma_cross" ? "" : "none";
  $("ql-p-dca").style.display = v === "dca" ? "" : "none";
  $("ql-p-mom").style.display = v === "momentum" ? "" : "none";
}

function applyLeanExample(id) {
  const e = LEAN_EXAMPLES.find(x => x.id === id);
  if (!e) return;
  $("ql-ticker").value = e.ticker; $("ql-strategy").value = e.strategy;
  $("ql-start").value = e.start; $("ql-cmp-start").value = e.cmpStart;
  leanStrategyHint();
  $("ql-example-detail").innerHTML = `<div class="rounded-xl border border-white/10 bg-black/20 p-3 text-sm"><div class="font-semibold mb-1">${escHtml(e.title)}</div><div><b>질문:</b> ${escHtml(e.focus)}</div><div><b>읽는 법:</b> ${escHtml(e.read)}</div></div>`;
}

async function runLeanBacktest() {
  const btn = $("ql-run");
  const payload = {
    ticker: $("ql-ticker").value.trim(), strategy: $("ql-strategy").value,
    start_date: $("ql-start").value, end_date: $("ql-end").value,
    compare_start_date: $("ql-cmp-start").value, compare_end_date: $("ql-cmp-end").value,
    initial_cash: parseFloat($("ql-cash").value) || 10000,
    short_window: parseInt($("ql-short").value) || 20, long_window: parseInt($("ql-long").value) || 60,
    dca_interval_days: parseInt($("ql-dca").value) || 21, breakout_window: parseInt($("ql-breakout").value) || 20,
  };
  if (!payload.ticker || !payload.start_date || !payload.end_date) return setToast("티커와 기간을 입력하세요.", "error");
  btn.disabled = true;
  $("ql-result").innerHTML = `<div class="text-sm" style="color:var(--text-mute);"><i class="fa-solid fa-spinner fa-spin"></i> Yahoo Finance 데이터를 정리하고 LEAN 컨테이너를 실행하고 있습니다. (최대 수 분 소요)</div>`;
  try {
    const d = await api("/api/backtests/lean/run", { method: "POST", body: payload });
    renderLeanResult(d);
    loadLeanHistory();
  } catch (e) { $("ql-result").innerHTML = `<div class="text-sm text-red-500">${escHtml(e.message)}</div>`; }
  finally { btn.disabled = false; }
}

function renderLeanResult(d) {
  // 이전 차트는 자리(innerHTML)를 바꾸기 *전에* 없앤다 — 지운 자리에 남은 차트가 크기를 다시 맞추다 「translate(NaN, 0)」 오류를 냈다
  // (2026-11-01 클릭 점검 Y3: 검증을 다시 실행하거나 전략을 바꿀 때 2건 · 정리본 S111 L272 과 같은 뿌리)
  if (leanChart) { try { leanChart.destroy(); } catch (_) { /* 이미 지워진 자리 */ } leanChart = null; }
  const up = v => v >= 0 ? "text-emerald-600" : "text-red-600";
  const stats = d.lean_statistics || {};
  const statRows = Object.keys(stats).length ? Object.entries(stats).map(([k, v]) => `<tr><td class="text-xs">${escHtml(k)}</td><td class="text-xs" style="text-align:right">${escHtml(v)}</td></tr>`).join("") : emptyRow(2, d.lean_ok ? "통계 없음" : "LEAN 엔진 결과 없음 (로그 확인)");
  $("ql-result").innerHTML = `
    <div class="flex items-center gap-2 flex-wrap mb-3"><span class="badge-hold">${escHtml(d.engine)}</span><span class="text-sm font-semibold">${escHtml(d.ticker)} · ${escHtml(d.strategy_label)}</span>
      <span class="text-xs" style="color:var(--text-mute);">${escHtml(d.start_date)} ~ ${escHtml(d.end_date)} (비교 ${escHtml(d.compare_start_date)} ~ ${escHtml(d.compare_end_date)})</span>
      ${d.lean_ok ? `<span class="badge-buy">LEAN 실행 완료</span>` : `<span class="badge-sell">LEAN 미실행/실패</span>`}
      <button type="button" class="btn-secondary text-xs ml-auto" id="ql-add-compare">비교에 추가</button></div>
    <div class="grid grid-cols-2 md:grid-cols-4 gap-2 mb-3">
      ${kpi("전략 수익률", fmtPct(d.strategy_return_pct), up(d.strategy_return_pct))}
      ${kpi("단순 보유 수익률", fmtPct(d.benchmark_return_pct), up(d.benchmark_return_pct))}
      ${kpi("비교 기간 보유 수익률", fmtPct(d.comparison_return_pct), up(d.comparison_return_pct))}
      ${kpi("초과 수익 (vs 비교기간)", fmtPct(d.outperformance_pct), up(d.outperformance_pct))}
      ${kpi("최대 낙폭 (MDD)", `${d.max_drawdown_pct}%`, "text-red-600")}
      ${kpi("연환산 수익률", fmtPct(d.annualized_return_pct), up(d.annualized_return_pct))}
      ${kpi("연환산 변동성", `${d.annualized_volatility_pct}%`)}
      ${kpi("샤프 비율", d.sharpe_ratio)}
      ${kpi("시장 노출 일수", `${d.invested_days_pct}%`)}
      ${kpi("규칙 변경 횟수", `${d.trade_count}회`)}
      ${kpi("현재 추세", escHtml(d.market_snapshot?.trend || "-"))}
      ${kpi("52주 범위 내 위치", `${d.market_snapshot?.range_252d_position_pct ?? "-"}%`)}
    </div>
    <div id="ql-chart" class="mb-3"></div>
    <div class="grid md:grid-cols-2 gap-3">
      <div><h4 class="text-sm font-semibold mb-1">LEAN 엔진 통계 (summary.json)</h4><table><tbody>${statRows}</tbody></table></div>
      <div><h4 class="text-sm font-semibold mb-1">시장 스냅샷 (${escHtml(d.market_snapshot?.as_of || "")})</h4>
        <table><tbody>
          <tr><td class="text-xs">마지막 종가</td><td class="text-xs" style="text-align:right">${fmt(d.market_snapshot?.last_price, 2)}</td></tr>
          <tr><td class="text-xs">20일 수익률</td><td class="text-xs" style="text-align:right">${d.market_snapshot?.return_20d_pct ?? "-"}%</td></tr>
          <tr><td class="text-xs">MA20 / MA60</td><td class="text-xs" style="text-align:right">${fmt(d.market_snapshot?.ma20, 2)} / ${fmt(d.market_snapshot?.ma60, 2)}</td></tr>
        </tbody></table></div>
    </div>
    <p class="text-xs mt-3" style="color:var(--text-mute);">${escHtml(d.disclaimer)}</p>
    <details class="mt-2"><summary class="text-sm cursor-pointer">LEAN 실행 로그</summary><pre class="text-xs p-3 rounded-lg overflow-x-auto" style="background:var(--surf2);border:1px solid var(--border);max-height:320px;">${escHtml(d.lean_log || "로그 없음")}</pre></details>
    <details class="mt-2"><summary class="text-sm cursor-pointer">생성된 LEAN 알고리즘 (main.py)</summary><pre class="text-xs p-3 rounded-lg overflow-x-auto" style="background:var(--surf2);border:1px solid var(--border);max-height:360px;">${escHtml(d.algorithm_source || "")}</pre></details>`;
  $("ql-add-compare").addEventListener("click", () => window.compareTrayAdd?.({
    source: "LEAN 백테스트", label: `${d.ticker} · ${d.strategy_label}`,
    summary: `수익률 ${fmtPct(d.strategy_return_pct)} · MDD ${d.max_drawdown_pct}% · 샤프 ${d.sharpe_ratio}`,
  }));
  if (window.ApexCharts) {
    leanChart = new ApexCharts($("ql-chart"), {
      chart: { type: "line", height: 280, toolbar: { show: false }, background: "transparent", zoom: { enabled: false },
        redrawOnWindowResize: false, redrawOnParentResize: false },
      series: [
        { name: d.strategy_label, data: d.points.map(p => ({ x: p.date, y: p.value })) },
        { name: "단순 보유", data: (d.benchmark_points || []).map(p => ({ x: p.date, y: p.value })) },
      ],
      stroke: { width: [3, 2], curve: "smooth", dashArray: [0, 4] },
      colors: ["#2563eb", "#94a3b8"],
      xaxis: { type: "category", tickAmount: 8, labels: { rotate: 0 } },
      yaxis: { labels: { formatter: v => fmt(v) }, title: { text: "자산 가치" } },
      theme: { mode: "light" }, legend: { position: "top" },
    });
    leanChart.render();
  }
}

// LEAN 실행 이력 — 전략 · 티커 칩 + 새로고침(2026-11-05). 새로고침은 저장된 기록을 서버에서 다시 읽을 뿐 LEAN 을 다시 돌리지 않는다(실행은 「이 조건으로 검증 실행」 단추만).
// 설정 · 표 모양은 js/listbar-misc.js(leanHistoryCfg) 한 곳 — 칩 줄은 가로 스크롤 상자(#ql-history) 밖에 JS 가 만든 칸(#ql-history-bar)에 그린다.
const leanHistoryPanel = listPanel(leanHistoryCfg({
  esc: escHtml, fmtPct, signCls, emptyRow,
  load: () => api("/api/backtests/lean/history?limit=15"),
}));

async function loadLeanHistory() {
  if (!ensureBarHost(document, "ql-history", "ql-history-bar")) return;
  await leanHistoryPanel.load();
}

/* ────────────────────────────────────────────────────────────────
 * 공개 API: app.html 메인 모듈에서 호출
 * ──────────────────────────────────────────────────────────────── */
export function initPaperViews() {
  mountPaperRisk({ doc: document, api, resolveSymbol: () => symbolFromInput("ps-symbol", () => $("ps-risk-calc").click()) });
  const on = (id, ev, fn) => $(id)?.addEventListener(ev, fn);
  on("pd-reset", "click", resetPaperAccount);
  // 계좌 현황 새로고침 — KPI · 최근 체결뿐 아니라 자산 구성 · QFRS 지표 · 자산 추이까지 서버에서 다시 읽는다(2026-11-05).
  // 저장된 값을 읽을 뿐이다: 100일 백테스트 카드(loadPaperBacktest · 생성 · 삭제)와 신호 계산은 일부러 부르지 않는다.
  on("pd-refresh", "click", createRefreshGroup({
    tasks: [loadPaperDashboard, loadPaperAllocation, loadPaperPerformance],
    setNote: text => { const el = $("pd-refresh-note"); if (el) el.textContent = text; },
    setBusy: busy => { const b = $("pd-refresh"); if (b) { b.disabled = busy; b.setAttribute("aria-busy", String(busy)); } },
    tail: "KPI · 자산 구성 · QFRS 지표 · 자산 추이 · 최근 체결을 저장된 값으로 다시 읽었고, 신호나 백테스트는 새로 계산하지 않습니다",
  }));

  on("ps-quote-btn", "click", stockQuote);
  on("ps-symbol", "keydown", e => { if (e.key === "Enter") stockQuote(); });
  on("ps-preview-buy", "click", () => stockPreview("BUY"));
  on("ps-preview-sell", "click", () => stockPreview("SELL"));
  on("ps-buy", "click", () => stockOrder("BUY"));
  on("ps-sell", "click", () => stockOrder("SELL"));

  // ★ B5 스탑 주문 버튼 + 시세 조회
  on("ps-stop-quote-btn", "click", stockStopQuote);
  on("ps-stop-symbol", "keydown", e => { if (e.key === "Enter") stockStopQuote(); });
  on("ps-stop-buy", "click", () => placeStopOrder("BUY"));
  on("ps-stop-sell", "click", () => placeStopOrder("SELL"));
  // 스탑가를 바꾸면 방향 안내와 차트의 점선을 다시 맞춘다(타자 중에는 0.3초 쉬었다가 차트)
  on("ps-stop-price", "input", () => { psStopHint(); clearTimeout(psStopTimer); psStopTimer = setTimeout(psDrawStop, 300); });
  // 시세 조회 결과 차트의 기간 단추
  on("ps-chart-periods", "click", e => {
    const b = e.target.closest("[data-ps-period]");
    if (b) { psMainPeriod = b.dataset.psPeriod; psDrawMain(); }
  });
  // 스탑 차트의 기간 단추
  on("ps-stop-chart-periods", "click", e => {
    const b = e.target.closest("[data-ps-stop-period]");
    if (b) { psStopPeriod = b.dataset.psStopPeriod; psDrawStop(); }
  });

  on("pc-market", "change", cryptoTicker);
  on("pc-refresh", "click", cryptoTicker);
  on("pc-preview-buy", "click", () => cryptoPreview("BUY"));
  on("pc-preview-sell", "click", () => cryptoPreview("SELL"));
  on("pc-buy", "click", () => cryptoOrder("BUY"));
  on("pc-sell", "click", () => cryptoOrder("SELL"));

  on("pa-symbol", "change", altChartLoad);
  on("pa-preview-buy", "click", () => altPreview("BUY"));
  on("pa-preview-sell", "click", () => altPreview("SELL"));
  on("pa-buy", "click", () => altOrder("BUY"));
  on("pa-sell", "click", () => altOrder("SELL"));

  on("po-create", "click", createApiKey);
  on("po-alpaca-account", "click", () => alpacaTest("account"));
  on("po-alpaca-positions", "click", () => alpacaTest("positions"));

  on("ql-strategy", "change", leanStrategyHint);
  on("ql-run", "click", runLeanBacktest);
}

export function onPaperViewActivated(view) {
  if (view === "paper-dashboard") {
    pdClearRefreshNote();
    loadPaperDashboard();
    loadPaperAllocation();
    loadPaperPerformance();
    loadPaperBacktest();
  }
  if (view === "paper-stock") loadPaperStock();
  if (view === "paper-crypto") loadPaperCrypto();
  if (view === "paper-alternative") loadPaperAlt();
  if (view === "quant-lean") loadLeanView();
}

/* ═══════════════════════════════════════════════════════════
 * 자산 구성 도넛 (paper-dashboard)
 * ═══════════════════════════════════════════════════════════ */
async function loadPaperAllocation() {
  const el = document.getElementById("pd-allocation-chart");
  if (!el) return true;

  try {
    const snap = await api("/api/paper/account");
    const parts = [
      { label: "국내주식", value: Number(snap.stockEval || 0), color: "#2962ff" },
      { label: "코인", value: Number(snap.cryptoEval || 0), color: "#f59e0b" },
      { label: "대체자산", value: Number(snap.alternativeEval || 0), color: "#a855f7" },
      { label: "현금", value: Number(snap.cash || 0), color: "#787b86" },
    ].filter(p => p.value > 0);

    if (!parts.length) {
      el.innerHTML = `<div class="text-xs" style="color:var(--text-mute);text-align:center;padding:40px 0;">자산이 없습니다.</div>`;
      return true;
    }

    if (_pdAllocationChart) { _pdAllocationChart.destroy(); _pdAllocationChart = null; }

    _pdAllocationChart = new ApexCharts(el, {
      chart: { type: "donut", height: 280, fontFamily: "Pretendard, sans-serif" },
      series: parts.map(p => Math.round(p.value)),
      labels: parts.map(p => p.label),
      colors: parts.map(p => p.color),
      legend: { position: "bottom", fontSize: "11px" },
      dataLabels: {
        enabled: true,
        formatter: (val) => val.toFixed(1) + "%",
        style: { fontSize: "11px" },
      },
      plotOptions: {
        pie: {
          donut: {
            size: "62%",
            labels: {
              show: true,
              name: { fontSize: "11px", color: "#888" },
              value: {
                fontSize: "15px", fontWeight: 700, color: "#111",
                formatter: (v) => {
                  const n = Number(v) || 0;
                  return (typeof window.formatKrw === 'function')
                    ? window.formatKrw(n, { compact: true })
                    : (n / 10000).toFixed(0) + "만";
                },
              },
              total: {
                show: true, label: "총자산",
                fontSize: "11px", color: "#888",
                formatter: () => {
                  const n = Number(snap?.totalAsset) || 0;
                  return (typeof window.formatKrw === 'function')
                    ? window.formatKrw(n, { compact: true })
                    : (n / 10000).toFixed(0) + "만원";
                },
                color: "#111",
              },
            },
          },
        },
      },
      tooltip: {
        y: { formatter: (v) => Number(v).toLocaleString() + "원" },
      },
    });
    _pdAllocationChart.render();
    return true;
  } catch (e) {
    el.innerHTML = `<div class="text-xs" style="color:var(--red);padding:20px;">${escHtml(e.message)}</div>`;
    return false;
  }
}

/* ═══════════════════════════════════════════════════════════
 * QFRS 성과 지표 + Equity Curve (paper-dashboard)
 * ═══════════════════════════════════════════════════════════ */
async function loadPaperPerformance() {
  const cardsEl = document.getElementById("pd-metrics-cards");
  const chartEl = document.getElementById("pd-equity-chart");
  if (!cardsEl) return true;

  cardsEl.innerHTML = `<div class="text-xs col-span-2" style="color:var(--text-mute);padding:20px;">계산 중...</div>`;

  try {
    const data = await api("/api/paper/performance/metrics");

    if (data.status === "insufficient_data") {
      cardsEl.innerHTML = `
        <div class="text-xs col-span-2" style="color:var(--text-mute);padding:20px;">
          📊 스냅샷 ${data.snapshot_count}개 — 매일 조회 시 자동으로 쌓입니다.
        </div>`;
      if (chartEl) chartEl.innerHTML = "";
      return true;
    }

    const m = data.metrics || {};
    const pct = (v) => v == null ? "-" : (v * 100).toFixed(2) + "%";
    const num = (v) => v == null ? "-" : Number(v).toFixed(3);
    const trColor = (data.total_return || 0) >= 0 ? "var(--green)" : "var(--red)";
    const dsrColor = (m.dsr || 0) >= 0.95 ? "var(--green)" : "var(--text)";

    if (m.reason) {
      cardsEl.innerHTML = `<div class="text-xs col-span-2" style="color:var(--text-mute);padding:20px;">📊 ${escHtml(m.reason)}</div>`;
    } else {
      cardsEl.innerHTML = `
        <div class="card" style="padding:10px;text-align:center;">
          <div class="text-xs" style="color:var(--text-mute);">누적 수익률</div>
          <div class="font-bold" style="color:${trColor}">${pct(data.total_return)}</div>
        </div>
        <div class="card" style="padding:10px;text-align:center;">
          <div class="text-xs" style="color:var(--text-mute);">MDD</div>
          <div class="font-bold" style="color:var(--red)">${pct(m.mdd)}</div>
        </div>
        <div class="card" style="padding:10px;text-align:center;">
          <div class="text-xs" style="color:var(--text-mute);">Sharpe</div>
          <div class="font-bold">${num(m.sharpe_ratio)}</div>
        </div>
        <div class="card" style="padding:10px;text-align:center;">
          <div class="text-xs" style="color:var(--text-mute);">DSR</div>
          <div class="font-bold" style="color:${dsrColor}">${m.dsr == null ? "-" : (m.dsr * 100).toFixed(1) + "%"}</div>
        </div>`;
    }

    // 자산 추이는 reason과 무관하게 그림
    if (chartEl && Array.isArray(data.equity_curve) && data.equity_curve.length > 1) {
      if (_pdEquityChart) { _pdEquityChart.destroy(); _pdEquityChart = null; }

      const rawDates = Array.isArray(data.snap_dates) ? data.snap_dates : [];
      const labels = data.equity_curve.map((_, i) => {
        const d = rawDates[i];
        return d ? d.slice(5) : `#${i + 1}`;
      });

      _pdEquityChart = new ApexCharts(chartEl, {
        chart: {
          type: "area", height: 260,
          toolbar: { show: false }, background: "transparent",
          fontFamily: "Pretendard, sans-serif",
        },
        series: [{
          name: "총자산",
          data: data.equity_curve.map((v, i) => ({ x: labels[i], y: v })),
        }],
        xaxis: {
          type: "category",
          labels: { rotate: -45, style: { fontSize: "10px", colors: "#888" } },
          tickAmount: Math.min(8, labels.length),
        },
        yaxis: {
          labels: {
            formatter: (v) => v == null ? "" : window.formatYAxisLabel(v),
            style: { fontSize: "10px", colors: "#888" },
          },
        },
        colors: ["#2962ff"],
        stroke: { curve: "smooth", width: 2 },
        fill: {
          type: "gradient",
          gradient: { shadeIntensity: 0.4, opacityFrom: 0.35, opacityTo: 0.05 },
        },
        dataLabels: { enabled: false },
        grid: { borderColor: "rgba(255,255,255,0.06)", strokeDashArray: 3 },
        tooltip: {
          x: { formatter: (val) => `📅 ${val}` },
          y: { formatter: (v) => v == null ? "-" : Math.round(Number(v)).toLocaleString('ko-KR') + "원" },
        },
      });
      _pdEquityChart.render();
    }
    return true;
  } catch (e) {
    cardsEl.innerHTML = `<div class="text-xs col-span-2" style="color:var(--red);padding:20px;">
      지표를 불러오지 못했습니다: ${escHtml(e.message)}
    </div>`;
    return false;
  }
}

// 전역 노출 (main.js에서 접근 가능하도록)
window.loadPaperAllocation = loadPaperAllocation;
window.loadPaperPerformance = loadPaperPerformance;

// ═══════════════════════════════════════════════════════════
// 100일 historical replay 백테스트 카드 (paper-dashboard)
// ═══════════════════════════════════════════════════════════
let _btPollTimer = null;
let _btBound = false;

function _ensureBacktestCard() {
  const view = document.querySelector('.view[data-view="paper-dashboard"]');
  if (!view) return null;
  let card = document.getElementById('pd-backtest-card');
  if (card) return card;

  card = document.createElement('div');
  card.id = 'pd-backtest-card';
  card.className = 'card';
  card.style.cssText = 'padding:14px;margin-top:14px;';
  card.innerHTML = `
    <div class="flex items-center justify-between mb-2">
      <h3 class="font-semibold text-sm">🧪 100일 백테스트 (historical replay)</h3>
      <span id="pd-backtest-badge" class="text-xs" style="color:var(--text-mute);"></span>
    </div>
    <p class="text-xs mb-2" style="color:var(--text-mute);line-height:1.5;">
      <b>auto_trade.py</b> 의 실시간 신호 함수(RSI·이평·볼린저)를 <b>그대로 재생</b>합니다. 실제 과거 시세·그날의 수수료·세율로 장부를 정산하며, 완료 후 QFRS 지표가 100일치로 계산됩니다.<br>
      <span style="color:#d97706;">⚠️ 실행 시 백테스트 전용 계좌의 SIM 주문·보유 종목·일별 스냅샷이 초기화되고, 백테스트 현금은 1억 원으로 복구됩니다. 일반 모의투자·직접매매·자동매매 및 코인·대체자산 데이터는 유지됩니다.</span>
    </p>
    <div class="flex gap-2 mb-2">
      <button type="button" class="btn-secondary text-xs" id="pd-backtest-generate">생성 (2~5분)</button>
      <button type="button" class="btn-secondary text-xs" id="pd-backtest-delete">삭제 · 초기화</button>
    </div>
    <div id="pd-backtest-status" class="text-xs" style="color:var(--text-mute);"></div>
  `;
  view.appendChild(card);

  if (!_btBound) {
    document.getElementById('pd-backtest-generate')?.addEventListener('click', _startBacktest);
    document.getElementById('pd-backtest-delete')?.addEventListener('click', _deleteBacktest);
    _btBound = true;
  }
  return card;
}

async function loadPaperBacktest() {
  if (!_ensureBacktestCard()) return;
  try {
    const r = await api('/api/paper/performance/backtest-100d/exists');
    const badge = document.getElementById('pd-backtest-badge');
    if (badge) {
      badge.textContent = r.exists ? `백테스트 데이터 ${r.count}건 있음` : '아직 없음';
      badge.style.color = r.exists ? 'var(--green)' : 'var(--text-mute)';
    }
  } catch { /* 무시 */ }
}

async function _startBacktest() {
  if (!confirm(
    '100일 백테스트를 시작합니다.\n\n' +
    '· auto_trade.py 의 실시간 신호 로직을 그대로 재생합니다.\n' +
    '· 기존 백테스트 전용 SIM 주문·보유 종목·일별 스냅샷을 새 백테스트 데이터로 대체합니다.\n' +
    '· 백테스트 전용 계좌의 현금은 1억 원으로 초기화됩니다.\n' +
    '· 일반 모의투자·직접매매·자동매매 및 코인·대체자산 데이터는 유지됩니다.\n' +
    '· 2~5분 소요. 되돌릴 수 없습니다.\n\n' +
    '계속할까요?'
  )) return;

  const status = document.getElementById('pd-backtest-status');
  const genBtn = document.getElementById('pd-backtest-generate');
  const delBtn = document.getElementById('pd-backtest-delete');
  try {
    const r = await api('/api/paper/performance/backtest-100d', { method: 'POST' });
    if (genBtn) genBtn.disabled = true;
    if (delBtn) delBtn.disabled = true;
    status.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> 시작 중…';
    _pollBacktest(r.task_id);
  } catch (e) {
    status.innerHTML = `<span style="color:var(--red);">${escHtml(e.message)}</span>`;
  }
}

function _pollBacktest(taskId) {
  const status = document.getElementById('pd-backtest-status');
  const genBtn = document.getElementById('pd-backtest-generate');
  const delBtn = document.getElementById('pd-backtest-delete');

  if (_btPollTimer) clearInterval(_btPollTimer);
  _btPollTimer = setInterval(async () => {
    try {
      const r = await api(`/api/paper/performance/backtest-100d/status/${taskId}`);
      const pct = r.progress ?? 0;
      status.innerHTML =
        `<div style="height:4px;background:var(--surf2);border-radius:2px;overflow:hidden;margin-bottom:4px;">` +
        `<div style="height:100%;width:${pct}%;background:var(--accent);transition:width .3s;"></div></div>` +
        `<span>${escHtml(r.phase || '')}</span>`;

      if (r.status === 'done') {
        clearInterval(_btPollTimer); _btPollTimer = null;
        status.innerHTML = `<span style="color:var(--green);">✅ ${escHtml(r.phase || '완료')}</span>`;
        if (genBtn) genBtn.disabled = false;
        if (delBtn) delBtn.disabled = false;
        loadPaperPerformance();
        loadPaperAllocation();
        loadPaperBacktest();
      } else if (r.status === 'error') {
        clearInterval(_btPollTimer); _btPollTimer = null;
        status.innerHTML = `<span style="color:var(--red);">❌ ${escHtml(r.phase || '실패')}</span>`;
        if (genBtn) genBtn.disabled = false;
        if (delBtn) delBtn.disabled = false;
      }
    } catch (e) {
      clearInterval(_btPollTimer); _btPollTimer = null;
      status.innerHTML = `<span style="color:var(--red);">상태 확인 실패: ${escHtml(e.message)}</span>`;
      if (genBtn) genBtn.disabled = false;
      if (delBtn) delBtn.disabled = false;
    }
  }, 2000);
}

async function _deleteBacktest() {
  if (!confirm(
    '백테스트 전용 SIM 주문·보유 종목·일별 스냅샷을 삭제하고 백테스트 전용 계좌의 현금을 1억 원으로 초기화합니다.\n\n' +
    '일반 모의투자·직접매매·자동매매 및 코인·대체자산 데이터는 유지됩니다. 되돌릴 수 없습니다.\n\n' +
    '계속할까요?'
  )) return;
  const status = document.getElementById('pd-backtest-status');
  try {
    await api('/api/paper/performance/backtest-100d', { method: 'DELETE' });
    status.innerHTML = '<span style="color:var(--green);">✅ 삭제 완료 · 백테스트 전용 계좌 1억 원으로 복구</span>';
    loadPaperPerformance();
    loadPaperAllocation();
    loadPaperBacktest();
    if (window.loadPaperDashboard) window.loadPaperDashboard();
  } catch (e) {
    status.innerHTML = `<span style="color:var(--red);">삭제 실패: ${escHtml(e.message)}</span>`;
  }
}

window.loadPaperBacktest = loadPaperBacktest;
