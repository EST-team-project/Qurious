/* 직접매매: 주가 차트, 포트폴리오, 주문
 * app.html 인라인 스크립트에서 분리됨. 엔트리는 main.js */
import { api, getMe, setToast, escHtml, fmt, fmtPct, colorPct } from "/js/common.js";
// Qurious: 보유 표 · 최근 주문 위 줄(새로고침 + 매수/매도 칩)은 제어기 한 곳(listbar-trade.js · node 시험 TC-LBT · 2026-11-05)
import { portfolioPanel, tradeOrderPanel } from "/js/listbar-trade.js";

let chartInstance = null;
// ── 주가 차트 ────────────────────────────────────────────────────
async function loadStockChart() {
  const symbol = document.getElementById("chart-symbol").value.trim() || "005930.KS";
  const period = document.getElementById("chart-period").value;
  const infoEl = document.getElementById("stock-info");
  const container = document.getElementById("chart-container");

  infoEl.textContent = "로딩 중...";
  try {
    const [quote, candles] = await Promise.all([
      // 머리 값은 지금 값과 그 출처 · 시각(quote_now · 2026-10-19) — 차트 봉은 수집 DB 일봉(직전 거래일까지)이라 날짜가 다를 수 있다
      api(`/api/quote/now?symbol=${encodeURIComponent(symbol)}`).catch(() => api(`/api/stocks/quote?symbol=${encodeURIComponent(symbol)}`)),
      api(`/api/stocks/candles?symbol=${encodeURIComponent(symbol)}&period=${period}`),
    ]);

    const price = quote.price ?? "-";
    const prevClose = quote.prev_close ?? 0;
    const chg = quote.change_pct != null ? Number(quote.change_pct).toFixed(2) : prevClose ? ((price - prevClose) / prevClose * 100).toFixed(2) : null;
    const chgClass = chg >= 0 ? "text-emerald-400" : "text-red-400";
    infoEl.innerHTML = `<span class="font-semibold">${escHtml(symbol)}</span>
      <span class="ml-3">${fmt(price)}</span>
      ${chg != null ? `<span class="ml-2 ${chgClass}">${chg >= 0 ? "+" : ""}${chg}%</span>` : ""}
      ${quote.label ? `<span class="ml-2 text-xs" style="color:var(--text-mute);">${escHtml(quote.label)}</span>` : ""}`;

    // Chart — ApexCharts 캔들스틱
    container.innerHTML = "";
    if (chartInstance) { chartInstance.destroy(); chartInstance = null; }
    const ohlcv = candles.candles
      .filter(c => c.open && c.high && c.low && c.close)
      .map(c => ({ x: new Date(c.time * 1000), y: [c.open, c.high, c.low, c.close] }));
    chartInstance = new ApexCharts(container, {
      chart: { type: "candlestick", height: 380, background: "#fff", toolbar: { show: true },
               animations: { enabled: false }, fontFamily: "Pretendard, sans-serif" },
      series: [{ name: "OHLC", data: ohlcv }],
      xaxis: { type: "datetime", labels: { style: { colors: "#434651" } } },
      yaxis: { tooltip: { enabled: true }, labels: { style: { colors: "#434651" },
               formatter: v => v?.toLocaleString() } },
      plotOptions: { candlestick: { colors: { upward: "#10b981", downward: "#ef4444" },
                     wick: { useFillColor: true } } },
      grid: { borderColor: "#e0e3eb" },
      theme: { mode: "light" },
      tooltip: { theme: "light" },
    });
    chartInstance.render();
  } catch (e) {
    infoEl.textContent = "오류: " + e.message;
  }
}

document.getElementById("chart-load").addEventListener("click", loadStockChart);

// ── 포트폴리오 ───────────────────────────────────────────────────
// 보유 표 — 새로고침은 서버에서 보유와 현재가를 다시 읽을 뿐이다(주문 · 계산 없음). 안내 두 줄과 표 모양은 제어기가 옛 글 그대로 그린다.
const portfolioView = portfolioPanel({ esc: escHtml, fmt, byId: id => document.getElementById(id), api });
async function loadPortfolio() {
  await portfolioView.load();
}

document.getElementById("pf-add")?.addEventListener("click", () => {
  setToast("포트폴리오는 국내주식 모의주문으로만 바뀝니다.", "error");
});

// ── 주문 ─────────────────────────────────────────────────────────
async function placeOrder(type) {
  const symbol = document.getElementById("ord-symbol").value.trim();
  const name = document.getElementById("ord-name").value.trim();
  const price = parseFloat(document.getElementById("ord-price").value);
  const qty = parseInt(document.getElementById("ord-qty").value);
  const broker = document.getElementById("ord-broker").value;
  if (!symbol || !name || !price || !qty) return setToast("모든 항목을 입력하세요.", "error");
  if (!(price > 0) || !(qty >= 1)) return setToast("가격은 0보다 크고 수량은 1주 이상이어야 합니다.", "error");   // 클릭 점검 R1 — 음수가 장부에 들어가던 것
  try {
    await api("/api/orders", { method: "POST", body: { symbol, name, order_type: type, quantity: qty, price, broker } });
    // 증권사로 나간 주문이 아니다 — 앱 안 기록(서버 /api/orders 는 증권사를 부르지 않는다)
    setToast(`${type === "buy" ? "매수" : "매도"} 기록 완료 (앱 안 기록 · 가상 매매 · 거래 비용 및 현금 반영)`, "ok");
    loadOrderHistory();
  } catch (e) { setToast(e.message, "error"); }
}
document.getElementById("ord-buy").addEventListener("click", () => placeOrder("buy"));
document.getElementById("ord-sell").addEventListener("click", () => placeOrder("sell"));

// 최근 주문 — 매수/매도 칩 + 새로고침(주문 기록을 서버에서 다시 읽을 뿐 주문은 내지 않는다). 자동매매 · Open API 주문 안내는 제어기가 줄 아래에 붙인다.
const orderHistoryView = tradeOrderPanel({ esc: escHtml, fmt, byId: id => document.getElementById(id), api });
async function loadOrderHistory() {
  await orderHistoryView.load();
}

async function loadBrokerStatus() {
  try {
    const s = await api("/api/broker/settings");
    const el = document.getElementById("trading-broker-status");
    if (!el) return;
    el.innerHTML = `
      <div>선택 브로커: <span class="text-slate-200">${escHtml(s.broker || "mock")}</span></div>
      <div>연결 상태: <span class="${s.connected ? "text-emerald-400" : "text-red-400"}">${s.connected ? "연동됨" : "미연동"}</span></div>
    `;
  } catch {}
}
// 「설정 저장」 단추는 2026-10-30 에 없앴다 — 주문 칸의 증권사 선택값(가상 매매 → mock)과 마이페이지 입력칸(broker-app-key 등)을
// 몰래 읽어 /api/broker/settings 로 보냈고, 서버는 mock · KIS 로 저장하면 저장된 키 · 계좌를 비운다. 증권사 설정은 마이페이지(settings.js)만 바꾼다.


export { loadBrokerStatus, loadOrderHistory, loadPortfolio, loadStockChart };
