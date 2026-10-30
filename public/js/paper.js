/* 모의투자(주식·코인·대체자산·Open API) + QuantConnect LEAN 백테스트 화면 로직. */
import { api, setToast, escHtml, fmt, fmtPct } from "/js/common.js";
import {
  COIN_SOURCE_NOTE, COIN_LIVE_NOTE, COIN_ORDER_NOTE, UPBIT_WS_URL, PING_MS,
  coinPoints, coinChartSummary, coinSubscribeMessage, decodeWsData, parseUpbitTicker, coinCandleDate,
  liveBadge, priceGap, orderPriceLine, reconnectDelay,
} from "/js/coinview.js";

const $ = (id) => document.getElementById(id);
const won = (n, d = 0) => `${fmt(n, d)}원`;
const signCls = (n) => (parseFloat(n) >= 0 ? "text-emerald-600" : "text-red-600");
const ts = (ms) => new Date(ms).toLocaleString("ko-KR", { hour12: false });
const sideBadge = (t) => `<span class="${String(t).toUpperCase() === "BUY" ? "badge-buy" : "badge-sell"}">${String(t).toUpperCase() === "BUY" ? "매수" : "매도"}</span>`;
const kpi = (label, value, cls = "") => `
  <div class="rounded-xl border border-white/10 bg-black/20 p-3">
    <div class="text-xs" style="color:var(--text-mute);">${escHtml(label)}</div>
    <div class="text-lg font-bold ${cls}">${value}</div>
  </div>`;
const emptyRow = (cols, text) => `<tr><td colspan="${cols}" style="color:var(--text-mute);text-align:center;">${escHtml(text)}</td></tr>`;

let altChart = null;
let leanChart = null;
let cryptoMarkets = [];
let _pdAllocationChart = null;
let _pdEquityChart = null;

/* ────────────────────────────────────────────────────────────────
 * 1. 모의투자 대시보드
 * ──────────────────────────────────────────────────────────────── */
async function loadPaperDashboard() {
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
  } catch (e) { setToast(e.message, "error"); }

  try {
    const [s, c, alt] = await Promise.all([
      api("/api/paper/stocks/orders/history?limit=30"),   // ← SIM 포함 위해 30건
      api("/api/paper/trade/order/history?limit=10"),
      api("/api/paper/alternatives/orders/history?limit=10"),
    ]);
    const rows = [
      ...s.history.map(o => ({ ts: o.ts, kind: "주식", name: `${o.name} (${o.symbol})`, type: o.type, qty: fmt(o.quantity), price: won(o.price), amount: won(o.amount), source: o.source })),
      ...c.history.map(o => ({ ts: o.ts, kind: "코인", name: `${o.koreanName} (${o.marketCode})`, type: o.type, qty: fmt(o.quantity, 8), price: won(o.price), amount: won(o.amount), source: o.source })),
      ...alt.history.map(o => ({ ts: o.ts, kind: o.category, name: o.name, type: o.type, qty: fmt(o.quantity), price: won(o.price), amount: won(o.amount), source: o.source })),
    ].sort((x, y) => y.ts - x.ts).slice(0, 15);

    // 이슈: SIM(백테스트) 주문을 실시간과 구분
    const sourceLabel = (src) => src === 'SIM'
      ? `<span class="text-xs" style="color:#d97706;font-weight:600;" title="100일 historical replay 백테스트 주문">🧪 SIM</span>`
      : escHtml(src);
    const simCount = rows.filter(r => r.source === 'SIM').length;

    $("pd-recent").innerHTML =
      (simCount > 0
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
        <td class="text-xs">${sourceLabel(r.source)}</td>
      </tr>`).join("") : emptyRow(8, "아직 체결 내역이 없습니다.")}</tbody></table>`;
  } catch (e) { $("pd-recent").innerHTML = `<div class="text-sm text-red-500">${escHtml(e.message)}</div>`; }
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
    loadPaperDashboard();
  } catch (e) { setToast(e.message, "error"); }
}

/* ────────────────────────────────────────────────────────────────
 * 2. 국내주식 모의주문
 * ──────────────────────────────────────────────────────────────── */
async function loadPaperStock() {
  loadStockPositions();
  loadStockHistory();
  loadStopOrders();          // ★ B5 스탑 주문 목록
  try {
    const a = await api("/api/paper/account");
    $("ps-cash").textContent = won(a.cash);
  } catch { }
}

async function stockQuote() {
  const symbol = $("ps-symbol").value.trim();
  if (!symbol) return setToast("종목코드를 입력하세요.", "error");
  $("ps-quote").innerHTML = `<span style="color:var(--text-mute);">조회 중…</span>`;
  try {
    const q = await api(`/api/paper/stocks/quote?symbol=${encodeURIComponent(symbol)}`);
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
  } catch (e) { $("ps-quote").innerHTML = `<span class="text-red-500">${escHtml(e.message)}</span>`; }
}

async function stockPreview(side) {
  const symbol = $("ps-symbol").value.trim();
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
  const symbol = $("ps-symbol").value.trim();
  const quantity = parseInt($("ps-qty").value);
  if (!symbol || !quantity) return setToast("종목코드와 수량을 입력하세요.", "error");

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

async function loadStockPositions() {
  try {
    const { positions } = await api("/api/paper/stocks/positions");
    $("ps-positions").innerHTML = `<table><thead><tr><th>종목</th><th style="text-align:right">수량</th><th style="text-align:right">평균단가</th><th style="text-align:right">현재가</th><th style="text-align:right">평가금액</th><th style="text-align:right">손익</th><th></th></tr></thead>
      <tbody>${positions.length ? positions.map(p => `<tr>
        <td>${escHtml(p.name)}<div class="text-xs" style="color:var(--text-mute);">${escHtml(p.symbol)}</div></td>
        <td style="text-align:right">${fmt(p.quantity)}</td><td style="text-align:right">${won(p.avgPrice)}</td><td style="text-align:right">${won(p.currentPrice)}</td>
        <td style="text-align:right">${won(p.evalAmount)}</td><td style="text-align:right" class="${signCls(p.pnl)}">${won(p.pnl)}<div class="text-xs">${fmtPct(p.pnlRate)}</div></td>
        <td style="text-align:right"><button class="btn-secondary text-xs ps-sell-all" data-symbol="${escHtml(p.symbol)}" data-qty="${p.quantity}">전량매도</button></td></tr>`).join("") : emptyRow(7, "보유 종목이 없습니다.")}</tbody></table>`;
    $("ps-positions").querySelectorAll(".ps-sell-all").forEach(b => b.addEventListener("click", () => {
      $("ps-symbol").value = b.dataset.symbol; $("ps-qty").value = b.dataset.qty; stockOrder("SELL");
    }));
  } catch (e) { $("ps-positions").innerHTML = `<div class="text-sm text-red-500">${escHtml(e.message)}</div>`; }
}

async function loadStockHistory() {
  try {
    const { history } = await api("/api/paper/stocks/orders/history?limit=30");

    $("ps-history").innerHTML = `<table>
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
          <td>${escHtml(o.name)} <span class="text-xs" style="color:var(--text-mute);">${escHtml(o.symbol)}</span></td>
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
  } catch { }
}

/* ────────────────────────────────────────────────────────────────
 * B5 · 스탑(감시) 주문 (paper-stock)
 * ──────────────────────────────────────────────────────────────── */
async function loadStopOrders() {
  const el = $("ps-stop-list");
  if (!el) return;
  try {
    const { orders } = await api("/api/paper/stocks/orders/stop");
    if (!orders.length) {
      el.innerHTML = `<div class="text-xs" style="color:var(--text-mute);">대기 중인 스탑 주문이 없습니다.</div>`;
      return;
    }
    el.innerHTML = `<table><thead><tr>
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
    el.querySelectorAll(".ps-stop-cancel").forEach(b => b.addEventListener("click", () => cancelStopOrder(b.dataset.id)));
  } catch (e) {
    el.innerHTML = `<div class="text-xs text-red-500">${escHtml(e.message)}</div>`;
  }
}

async function stockStopQuote() {
  const symbol = $("ps-stop-symbol").value.trim();
  if (!symbol) return setToast("종목코드를 입력하세요.", "error");
  $("ps-stop-quote").innerHTML = `<span style="color:var(--text-mute);">조회 중…</span>`;
  try {
    const q = await api(`/api/paper/stocks/quote?symbol=${encodeURIComponent(symbol)}`);
    const chg = q.prev_close ? ((q.price - q.prev_close) / q.prev_close * 100) : null;
    $("ps-stop-quote").innerHTML = `<strong>${escHtml(q.name)}</strong> <span class="text-xs" style="color:var(--text-mute);">${escHtml(q.symbol)} · ${escHtml(q.market)}</span>
      <div class="text-lg font-bold mt-1">${fmt(q.price, q.currency === "KRW" ? 0 : 2)} ${escHtml(q.currency)} ${chg != null ? `<span class="text-sm ${signCls(chg)}">${fmtPct(chg)}</span>` : ""}</div>`;
    // 자동으로 스탑가 input에 현재가 채우기 (편의)
    if (!$("ps-stop-price").value && q.price) {
      $("ps-stop-price").value = Math.round(q.price);
    }
    // 종목코드 정규화 (005930 → 005930.KS)
    $("ps-stop-symbol").value = q.symbol;
  } catch (e) { $("ps-stop-quote").innerHTML = `<span class="text-red-500">${escHtml(e.message)}</span>`; }
}

async function placeStopOrder(side) {
  const symbol = $("ps-stop-symbol").value.trim();
  const quantity = parseInt($("ps-stop-qty").value);
  const stop_price = parseFloat($("ps-stop-price").value);
  if (!symbol || !quantity || !stop_price) return setToast("종목코드 · 수량 · 스탑가를 입력하세요.", "error");
  try {
    const r = await api("/api/paper/stocks/orders/stop", {
      method: "POST",
      body: { symbol, side, quantity, stop_price },
    });
    setToast(`${r.name} ${side === "BUY" ? "매수" : "매도"} 스탑 ${fmt(r.quantity)}주 @${won(r.stop_price)} 등록됨`, "ok");
    $("ps-stop-symbol").value = "";
    $("ps-stop-qty").value = "";
    $("ps-stop-price").value = "";
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
    rightPriceScale: { borderColor: "#dde2ec", scaleMargins: { top: 0.08, bottom: 0.18 } },
    timeScale: { borderColor: "#dde2ec", fixLeftEdge: true, fixRightEdge: true, lockVisibleTimeRangeOnResize: true },
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

async function cryptoPreview(side) {
  const marketCode = $("pc-market").value;
  const body = { marketCode, side };
  if (side === "BUY") body.buyKrw = parseFloat(String($("pc-buy-krw").value).replace(/,/g, ""));
  else body.sellCount = parseFloat($("pc-sell-count").value);
  if (side === "BUY" ? !body.buyKrw : !body.sellCount) return setToast(side === "BUY" ? "매수 금액을 입력하세요." : "매도 수량을 입력하세요.", "error");
  try {
    const p = await api("/api/paper/trade/order/preview", { method: "POST", body });
    $("pc-preview").innerHTML = `<div class="rounded-xl border p-3 text-sm" style="border-color:${p.executable ? "var(--green-bd)" : "var(--red-bd)"}">
      <div class="flex items-center gap-2 mb-2">${sideBadge(p.side)} <strong>${escHtml(p.koreanName)}</strong> <span class="text-xs" style="color:var(--text-mute);">${escHtml(p.marketCode)}</span>
        <span class="ml-auto text-xs font-bold ${p.executable ? "text-emerald-600" : "text-red-600"}">${p.executable ? "체결 가능" : escHtml(p.reason || "체결 불가")}</span></div>
      <div class="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs"><div>예상 단가<br><b>${won(p.estimatedPrice)}</b></div><div>수량<br><b>${fmt(p.quantity, 8)}</b></div><div>예상 금액<br><b>${won(p.estimatedAmount)}</b></div><div>현금 / 보유<br><b>${won(p.cashBefore)}</b> / ${fmt(p.heldQuantity, 8)}</div></div>
      <div class="text-xs mt-2" style="color:var(--text-mute);">${escHtml(p.notice)}</div></div>`;
  } catch (e) { setToast(e.message, "error"); }
}

async function cryptoOrder(side) {
  const marketCode = $("pc-market").value;
  try {
    let r;
    if (side === "BUY") {
      const buyKrw = parseFloat(String($("pc-buy-krw").value).replace(/,/g, ""));
      if (!buyKrw) return setToast("매수 금액을 입력하세요.", "error");
      r = await api("/api/paper/trade/order/buy", { method: "POST", body: { marketCode, buyKrw } });
    } else {
      const sellCount = parseFloat($("pc-sell-count").value);
      if (!sellCount) return setToast("매도 수량을 입력하세요.", "error");
      r = await api("/api/paper/trade/order/sell", { method: "POST", body: { marketCode, sellCount } });
    }
    setToast(`${marketCode} ${side === "BUY" ? "매수" : "매도"} 체결 · 수량 ${fmt(r.quantity, 8)} @${won(r.price)}`, "ok");
    $("pc-preview").innerHTML = "";
    loadCryptoHold(); loadCryptoHistory();
  } catch (e) { setToast(e.message, "error"); }
}

async function loadCryptoHold() {
  try {
    const h = await api("/api/paper/trade/hold");
    $("pc-cash").textContent = won(h.memberAsset);
    $("pc-hold").innerHTML = `<div class="text-xs mb-2" style="color:var(--text-mute);">매수 원금 ${won(h.totalBuyKrw)} · 평가금액 ${won(h.totalEvalKrw)}</div>
      <table><thead><tr><th>코인</th><th style="text-align:right">보유수량</th><th style="text-align:right">매수평균</th><th style="text-align:right">현재가</th><th style="text-align:right">평가금액</th><th style="text-align:right">손익</th><th></th></tr></thead>
      <tbody>${h.holdCryptoList.length ? h.holdCryptoList.map(c => `<tr><td>${escHtml(c.koreanName)} <span class="text-xs" style="color:var(--text-mute);">${escHtml(c.marketCode)}</span></td>
        <td style="text-align:right">${fmt(c.holdCount, 8)}</td><td style="text-align:right">${won(c.buyAverage)}</td><td style="text-align:right">${won(c.currentPrice)}</td><td style="text-align:right">${won(c.evalKrw)}</td>
        <td style="text-align:right" class="${signCls(c.pnl)}">${won(c.pnl)}<div class="text-xs">${fmtPct(c.pnlRate)}</div></td>
        <td style="text-align:right"><button class="btn-secondary text-xs pc-sell-all" data-market="${escHtml(c.marketCode)}" data-qty="${c.holdCount}">전량매도</button></td></tr>`).join("") : emptyRow(7, "보유 코인이 없습니다.")}</tbody></table>`;
    $("pc-hold").querySelectorAll(".pc-sell-all").forEach(b => b.addEventListener("click", () => {
      $("pc-market").value = b.dataset.market; $("pc-sell-count").value = b.dataset.qty; cryptoOrder("SELL");
    }));
  } catch (e) { $("pc-hold").innerHTML = `<div class="text-sm text-red-500">${escHtml(e.message)}</div>`; }
}

async function loadCryptoHistory() {
  try {
    const { history } = await api("/api/paper/trade/order/history?limit=30");
    $("pc-history").innerHTML = `<table><thead><tr><th>시각</th><th>매매</th><th>코인</th><th style="text-align:right">수량</th><th style="text-align:right">단가</th><th style="text-align:right">금액</th></tr></thead>
      <tbody>${history.length ? history.map(o => `<tr><td class="text-xs">${ts(o.ts)}</td><td>${sideBadge(o.type)}</td><td>${escHtml(o.koreanName)} <span class="text-xs" style="color:var(--text-mute);">${escHtml(o.marketCode)}</span></td><td style="text-align:right">${fmt(o.quantity, 8)}</td><td style="text-align:right">${won(o.price)}</td><td style="text-align:right">${won(o.amount)}</td></tr>`).join("") : emptyRow(6, "거래 내역이 없습니다.")}</tbody></table>`;
  } catch { }
}

async function loadCryptoRankings() {
  try {
    const { rankings } = await api("/api/paper/crypto/rankings?limit=15");
    $("pc-rankings").innerHTML = `<table><thead><tr><th>#</th><th>코인</th><th style="text-align:right">현재가</th><th style="text-align:right">24h</th><th style="text-align:right">거래대금(24h)</th></tr></thead>
      <tbody>${rankings.map((r, i) => `<tr class="cursor-pointer pc-rank-row" data-market="${escHtml(r.market)}"><td>${i + 1}</td><td>${escHtml(r.koreanName)} <span class="text-xs" style="color:var(--text-mute);">${escHtml(r.symbol)}</span></td><td style="text-align:right">${won(r.price)}</td><td style="text-align:right" class="${signCls(r.changeRate)}">${fmtPct(r.changeRate)}</td><td style="text-align:right">${fmt(r.accTradePrice24h / 1e8, 1)}억</td></tr>`).join("")}</tbody></table>`;
    $("pc-rankings").querySelectorAll(".pc-rank-row").forEach(r => r.addEventListener("click", () => { $("pc-market").value = r.dataset.market; cryptoTicker(); }));
  } catch { }
}

/* ────────────────────────────────────────────────────────────────
 * 4. 대체자산 (선물·옵션·파생·금속·부동산)
 * ──────────────────────────────────────────────────────────────── */
async function loadPaperAlt() {
  try {
    const { markets, notice } = await api("/api/paper/alternatives/markets");
    $("pa-notice").textContent = notice;
    const sel = $("pa-symbol");
    const prev = sel.value;
    sel.innerHTML = markets.map(m => `<option value="${escHtml(m.symbol)}">[${escHtml(m.category)}] ${escHtml(m.name)}</option>`).join("");
    if (prev) sel.value = prev;
    $("pa-markets").innerHTML = markets.map(m => `
      <div class="rounded-xl border border-white/10 bg-black/20 p-3 cursor-pointer pa-card" data-symbol="${escHtml(m.symbol)}">
        <div class="flex items-center justify-between"><span class="text-xs font-semibold" style="color:var(--accent);">${escHtml(m.category)}</span><span class="text-xs ${signCls(m.changeRate)}">${fmtPct(m.changeRate)}</span></div>
        <div class="font-semibold mt-1">${escHtml(m.name)}</div>
        <div class="text-lg font-bold">${won(m.price)} <span class="text-xs font-normal" style="color:var(--text-mute);">/ ${escHtml(m.unit)}</span></div>
        <div class="text-xs" style="color:var(--text-mute);">1단위 주문금액 ${won(m.tradeAmountPerUnit)}${m.marginRate < 100 ? ` (증거금 ${m.marginRate}%)` : ""}</div>
        <div class="text-xs mt-1" style="color:var(--text-mute);">${escHtml(m.source)}</div>
      </div>`).join("");
    $("pa-markets").querySelectorAll(".pa-card").forEach(c => c.addEventListener("click", () => { sel.value = c.dataset.symbol; altChartLoad(); }));
  } catch (e) { setToast(e.message, "error"); }
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

async function loadAltPositions() {
  try {
    const { positions, totalEvalAmount } = await api("/api/paper/alternatives/positions?volatility=1");
    $("pa-positions").innerHTML = `<div class="text-xs mb-2" style="color:var(--text-mute);">총 평가금액 ${won(totalEvalAmount)}</div>
      <table><thead><tr><th>상품</th><th style="text-align:right">수량</th><th style="text-align:right">평균가</th><th style="text-align:right">현재가</th><th style="text-align:right">평가금액</th><th style="text-align:right">손익</th><th style="text-align:right">변동성</th><th></th></tr></thead>
      <tbody>${positions.length ? positions.map(p => `<tr><td>${escHtml(p.name)} <span class="text-xs" style="color:var(--text-mute);">${escHtml(p.category)}</span></td><td style="text-align:right">${fmt(p.quantity)} ${escHtml(p.unit)}</td><td style="text-align:right">${won(p.avgPrice)}</td><td style="text-align:right">${won(p.currentPrice)}</td><td style="text-align:right">${won(p.evalAmount)}</td><td style="text-align:right" class="${signCls(p.pnl)}">${won(p.pnl)}</td><td style="text-align:right">${p.volatility != null ? p.volatility + "%" : "-"}</td>
        <td style="text-align:right"><button class="btn-secondary text-xs pa-sell-all" data-symbol="${escHtml(p.symbol)}" data-qty="${p.quantity}">전량매도</button></td></tr>`).join("") : emptyRow(8, "보유 포지션이 없습니다.")}</tbody></table>`;
    $("pa-positions").querySelectorAll(".pa-sell-all").forEach(b => b.addEventListener("click", () => {
      $("pa-symbol").value = b.dataset.symbol; $("pa-qty").value = b.dataset.qty; altOrder("SELL");
    }));
  } catch (e) { $("pa-positions").innerHTML = `<div class="text-sm text-red-500">${escHtml(e.message)}</div>`; }
}

async function loadAltHistory() {
  try {
    const { history } = await api("/api/paper/alternatives/orders/history?limit=30");
    $("pa-history").innerHTML = `<table><thead><tr><th>시각</th><th>매매</th><th>상품</th><th style="text-align:right">수량</th><th style="text-align:right">단가</th><th style="text-align:right">금액</th></tr></thead>
      <tbody>${history.length ? history.map(o => `<tr><td class="text-xs">${ts(o.ts)}</td><td>${sideBadge(o.type)}</td><td>${escHtml(o.name)} <span class="text-xs" style="color:var(--text-mute);">${escHtml(o.category)}</span></td><td style="text-align:right">${fmt(o.quantity)}</td><td style="text-align:right">${won(o.price)}</td><td style="text-align:right">${won(o.amount)}</td></tr>`).join("") : emptyRow(6, "주문 내역이 없습니다.")}</tbody></table>`;
  } catch { }
}

/* ────────────────────────────────────────────────────────────────
 * 5. Open API 키 + 외부 연동 문서 + Alpaca 연결 테스트
 * ──────────────────────────────────────────────────────────────── */
async function loadPaperOpenApi() {
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
  if (leanChart) { leanChart.destroy(); leanChart = null; }
  if (window.ApexCharts) {
    leanChart = new ApexCharts($("ql-chart"), {
      chart: { type: "line", height: 280, toolbar: { show: false }, background: "transparent", zoom: { enabled: false } },
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

async function loadLeanHistory() {
  try {
    const { runs } = await api("/api/backtests/lean/history?limit=15");
    $("ql-history").innerHTML = `<table><thead><tr><th>실행 시각</th><th>티커</th><th>전략</th><th>기간</th><th style="text-align:right">수익률</th><th style="text-align:right">MDD</th><th style="text-align:right">샤프</th><th>엔진</th></tr></thead>
      <tbody>${runs.length ? runs.map(r => `<tr><td class="text-xs">${new Date(r.created_at).toLocaleString("ko-KR")}</td><td>${escHtml(r.ticker)}</td><td class="text-xs">${escHtml(r.strategy_label)}</td><td class="text-xs">${escHtml(r.start_date)}~${escHtml(r.end_date)}</td>
        <td style="text-align:right" class="${signCls(r.strategy_return_pct)}">${fmtPct(r.strategy_return_pct)}</td><td style="text-align:right">${r.max_drawdown_pct}%</td><td style="text-align:right">${r.sharpe_ratio}</td><td>${r.lean_ok ? `<span class="badge-buy">LEAN</span>` : `<span class="badge-hold">pandas</span>`}</td></tr>`).join("") : emptyRow(8, "실행 이력이 없습니다.")}</tbody></table>`;
  } catch { }
}

/* ────────────────────────────────────────────────────────────────
 * 공개 API: app.html 메인 모듈에서 호출
 * ──────────────────────────────────────────────────────────────── */
export function initPaperViews() {
  const on = (id, ev, fn) => $(id)?.addEventListener(ev, fn);
  on("pd-reset", "click", resetPaperAccount);
  on("pd-refresh", "click", loadPaperDashboard);

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
    loadPaperDashboard();
    loadPaperAllocation();
    loadPaperPerformance();
    loadPaperBacktest();
  }
  if (view === "paper-stock") loadPaperStock();
  if (view === "paper-crypto") loadPaperCrypto();
  if (view === "paper-alternative") loadPaperAlt();
  if (view === "paper-openapi") loadPaperOpenApi();
  if (view === "quant-lean") loadLeanView();
}

/* ═══════════════════════════════════════════════════════════
 * 자산 구성 도넛 (paper-dashboard)
 * ═══════════════════════════════════════════════════════════ */
async function loadPaperAllocation() {
  const el = document.getElementById("pd-allocation-chart");
  if (!el) return;

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
      return;
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
  } catch (e) {
    el.innerHTML = `<div class="text-xs" style="color:var(--red);padding:20px;">${escHtml(e.message)}</div>`;
  }
}

/* ═══════════════════════════════════════════════════════════
 * QFRS 성과 지표 + Equity Curve (paper-dashboard)
 * ═══════════════════════════════════════════════════════════ */
async function loadPaperPerformance() {
  const cardsEl = document.getElementById("pd-metrics-cards");
  const chartEl = document.getElementById("pd-equity-chart");
  if (!cardsEl) return;

  cardsEl.innerHTML = `<div class="text-xs col-span-2" style="color:var(--text-mute);padding:20px;">계산 중...</div>`;

  try {
    const data = await api("/api/paper/performance/metrics");

    if (data.status === "insufficient_data") {
      cardsEl.innerHTML = `
        <div class="text-xs col-span-2" style="color:var(--text-mute);padding:20px;">
          📊 스냅샷 ${data.snapshot_count}개 — 매일 조회 시 자동으로 쌓입니다.
        </div>`;
      if (chartEl) chartEl.innerHTML = "";
      return;
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
  } catch (e) {
    cardsEl.innerHTML = `<div class="text-xs col-span-2" style="color:var(--red);padding:20px;">
      지표를 불러오지 못했습니다: ${escHtml(e.message)}
    </div>`;
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
      <span style="color:#d97706;">⚠️ 실행 시 SIM 주문·일별 스냅샷이 백테스트 데이터로 대체되고, 모의투자·직접매매 주문, 모의 장부 보유, 코인·대체자산 보유/주문이 함께 삭제되며 계좌가 현금 1억으로 초기화됩니다(회차 +1). 자동매매·파인·외부 API·증권사 체결 주문과 자동매매 보유는 보존됩니다. 되돌릴 수 없습니다.</span>
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
    '· SIM 주문·일별 스냅샷을 백테스트 데이터로 대체합니다.\n' +
    '· 모의투자·직접매매 주문, 모의 장부 보유, 코인·대체자산 보유/주문이 함께 삭제되고 현금 1억으로 초기화됩니다(회차 +1).\n' +
    '· 자동매매·파인·외부 API·증권사 체결 주문과 자동매매 보유는 보존됩니다.\n' +
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
    '100일 백테스트 데이터(SIM 주문·스냅샷)를 삭제하고, 모의투자·직접매매 주문, 모의 장부 보유, 코인·대체자산 보유/주문도 함께 삭제한 뒤 현금 1억으로 초기화합니다(회차 +1).\n\n' +
    '자동매매·파인·외부 API·증권사 체결 주문과 자동매매 보유는 보존됩니다. 되돌릴 수 없습니다.\n\n' +
    '계속할까요?'
  )) return;
  const status = document.getElementById('pd-backtest-status');
  try {
    await api('/api/paper/performance/backtest-100d', { method: 'DELETE' });
    status.innerHTML = '<span style="color:var(--green);">✅ 삭제 완료 · 계좌 1억으로 복구</span>';
    loadPaperPerformance();
    loadPaperAllocation();
    loadPaperBacktest();
    if (window.loadPaperDashboard) window.loadPaperDashboard();
  } catch (e) {
    status.innerHTML = `<span style="color:var(--red);">삭제 실패: ${escHtml(e.message)}</span>`;
  }
}

window.loadPaperBacktest = loadPaperBacktest;