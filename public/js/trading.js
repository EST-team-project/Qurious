/* 직접매매: 주가 차트, 포트폴리오, 주문
 * app.html 인라인 스크립트에서 분리됨. 엔트리는 main.js */
import { api, getMe, setToast, escHtml, fmt, fmtPct, colorPct } from "/js/common.js";

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
async function loadPortfolio() {
  try {
    const { holdings } = await api("/api/portfolio");
    const el = document.getElementById("portfolio-table");
    if (!holdings.length) {
      el.innerHTML = "<div class='text-slate-400 text-xs'>보유 종목이 없습니다.</div>";
      return;
    }
    el.innerHTML = `
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
          ${holdings.map(h => `
            <tr class="border-b border-white/5">
              <td class="py-2">${escHtml(h.name)}<div class="text-slate-500">${escHtml(h.symbol)}</div></td>
              <td class="py-2 text-right">${fmt(h.quantity)}</td>
              <td class="py-2 text-right">${fmt(h.avg_price)}</td>
              <td class="py-2 text-right">${h.current_price != null ? fmt(h.current_price) : "-"}</td>
              <td class="py-2 text-right">${h.eval_amount != null ? fmt(h.eval_amount) + "원" : "-"}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>`;
  } catch (e) {
    const el = document.getElementById("portfolio-table");
    if (el) el.innerHTML = `<div class="text-xs" style="color:var(--red);">보유 종목을 불러오지 못했습니다 — ${escHtml(e.message || "까닭 모름")}</div>`;
  }
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
  try {
    await api("/api/orders", { method: "POST", body: { symbol, name, order_type: type, quantity: qty, price, broker } });
    // 증권사로 나간 주문이 아니다 — 앱 안 기록(서버 /api/orders 는 증권사를 부르지 않는다)
    setToast(`${type === "buy" ? "매수" : "매도"} 기록 완료 (앱 안 기록 · ${broker === "virtual" ? "가상 매매" : broker + " 꼬리표 · 현금 그대로"})`, "ok");
    loadOrderHistory();
  } catch (e) { setToast(e.message, "error"); }
}
document.getElementById("ord-buy").addEventListener("click", () => placeOrder("buy"));
document.getElementById("ord-sell").addEventListener("click", () => placeOrder("sell"));

async function loadOrderHistory() {
  try {
    const { orders } = await api("/api/orders");
    const el = document.getElementById("order-history");
    el.innerHTML = orders.slice(0, 20).map(o => `
      <div class="flex items-center justify-between rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-xs">
        <span class="${o.order_type === "buy" ? "badge-buy" : "badge-sell"}">${o.order_type === "buy" ? "매수" : "매도"}</span>
        <span class="ml-2">${escHtml(o.name)} (${escHtml(o.symbol)})</span>
        <span class="ml-auto">${fmt(o.price)}원 × ${fmt(o.quantity)}주</span>
        <span class="ml-3 text-slate-500">${escHtml(o.broker)} · ${(o.created_at||"").slice(0,10)}</span>
      </div>
    `).join("") || "<div class='text-slate-400'>주문 내역 없음</div>";
    // 서버가 자동매매 · Open API · 예약 주문을 뺀다(#219 와 같은 규칙) — 빠진 주문을 어디서 보는지 알린다
    el.insertAdjacentHTML("beforeend", `<div class="text-xs mt-1" style="color:var(--text-mute);">자동매매 · Open API 주문은 <a href="#quant-auto" class="underline">자동매매 현황</a>에서 봅니다.</div>`);
  } catch {}
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
