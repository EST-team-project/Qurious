/* 미국주식 대시보드·차트·주문·포트폴리오
 * app.html 인라인 스크립트에서 분리됨. 엔트리는 main.js */
import { api, getMe, setToast, escHtml, fmt, fmtPct, colorPct } from "/js/common.js";
// Qurious: 등락 글 · ±1.5% 표시 · 시세 시각 글은 판단 모듈 한 곳(node 시험 TC-QVS · Figma 03-5 결정 · 2026-10-16)
import { pctText, direction, moveTag, asOfText, MOVE_LIMIT } from "/js/quoteview.js";

// ── 미국주식 ──────────────────────────────────────────────────────
// Qurious(2026-10-16): 고정 종목 목록 · 예시 가격(mockUsPrice)을 지웠다 — 시세를 못 받으면 예시 가격을 말없이 보이던
// 길(말없는 fallback)이었다. 종목 목록은 서버 한 곳(`app/services/sync_scheduler.py` US_STOCKS)이 정한다.

const US_INDEX_SYMBOLS = [
  { symbol:"^GSPC", name:"S&P 500" },
  { symbol:"^IXIC", name:"NASDAQ" },
  { symbol:"^DJI",  name:"DOW" },
  { symbol:"KRW=X", name:"USD/KRW" },
];

let usChartInstance = null;

const DIR_COLOR = { up: "var(--green)", down: "var(--red)", flat: "var(--text-dim)", none: "var(--text-mute)" };

async function loadUsDashboard() {
  const marketEl = document.getElementById("us-market-cards");
  const sigEl    = document.getElementById("us-signal-cards");

  // 지수/환율 카드: /api/stocks/quote(외부 지연 시세) — 등락률은 서버가 낸 값(`change_pct` · 모르면 「—」)을 그대로 쓴다
  try {
    const quotes = await Promise.all(
      US_INDEX_SYMBOLS.map(idx => api(`/api/stocks/quote?symbol=${encodeURIComponent(idx.symbol)}`).catch(() => null))
    );
    marketEl.innerHTML = US_INDEX_SYMBOLS.map((idx, i) => {
      const q = quotes[i];
      if (!q || q.price == null) {
        return `<div class="card text-center" style="padding:14px;">
          <div class="text-xs" style="color:var(--text-dim);">${escHtml(idx.name)}</div>
          <div class="text-sm mt-1" style="color:var(--text-mute);">데이터 없음</div>
        </div>`;
      }
      return `<div class="card text-center" style="padding:14px;">
        <div class="text-xs" style="color:var(--text-dim);">${escHtml(idx.name)}</div>
        <div class="text-xl font-bold mt-1">${fmt(q.price, 2)}</div>
        <div class="text-xs font-semibold mt-1" style="color:${DIR_COLOR[direction(q.change_pct)]};">${pctText(q.change_pct)}</div>
      </div>`;
    }).join("");
  } catch (e) {
    marketEl.innerHTML = `<div class="text-xs" style="color:var(--red);grid-column:1/-1;">${escHtml(e.message)}</div>`;
  }

  // 종목 카드: /api/macro/us-stocks(저장본 최대 2시간) — 평소 등락률만 · ±1.5% 를 넘은 종목에만 「크게 오름 · 크게 내림」
  // (Figma 03-5 융합안). 머리 글 한 줄(지연 · 장 닫힘 · 마지막 체결 · 받은 시각 · 저장본 나이)은 서버 한 곳(`data_provenance.quote_note`).
  let resp = null;
  try { resp = await api("/api/macro/us-stocks"); } catch {}
  const stocks = (resp && resp.stocks || []).filter(s => s && s.price != null);
  const titleEl = document.getElementById("us-signal-count");
  if (titleEl) titleEl.textContent = stocks.length ? String(stocks.length) : "";
  const ruleEl = document.getElementById("us-signal-rule");   // 문턱 숫자는 판단 모듈 한 곳(MOVE_LIMIT)에서
  if (ruleEl) ruleEl.textContent = `전일 대비 ±${MOVE_LIMIT}% 를 넘은 종목에만 「크게 오름」 · 「크게 내림」 을 붙입니다 — 규칙 표시일 뿐 매매 신호가 아닙니다(학습 모델 아님).`;
  if (!stocks.length) {
    sigEl.innerHTML = `<div class="text-sm" style="color:var(--text-mute);grid-column:1/-1;">시세를 받지 못했습니다 — 잠시 뒤 「새로고침」 을 눌러 주세요.</div>`;
    return;
  }
  sigEl.innerHTML = stocks.map(s => {
    const pct = s.change_p ?? s.change_pct;
    const tag = moveTag(pct);
    return `<div class="card" style="padding:12px;">
      <div class="font-bold text-sm">${escHtml(s.symbol)}</div>
      <div class="text-xs" style="color:var(--text-dim);">${escHtml(s.name || "")}</div>
      <div class="font-semibold mt-2">$${fmt(s.price,2)}</div>
      <div class="text-xs mt-1" style="color:${DIR_COLOR[direction(pct)]};">${pctText(pct)}</div>
      <div class="text-xs font-bold mt-2" style="color:${DIR_COLOR[tag.dir]};min-height:16px;">${escHtml(tag.text)}</div>
    </div>`;
  }).join("");
  if (resp.note) {
    sigEl.insertAdjacentHTML("beforeend", `<div class="text-xs" style="color:var(--text-mute);grid-column:1/-1;text-align:right;">${escHtml(resp.note)}</div>`);
  }
}

async function loadUsChart() {
  const symbol = document.getElementById("us-symbol").value.trim().toUpperCase() || "AAPL";
  const period = document.getElementById("us-period")?.value || "1y";
  const container = document.getElementById("us-chart-container");
  const infoEl    = document.getElementById("us-stock-info");
  infoEl.textContent = "로딩 중...";
  try {
    const [quote, candles] = await Promise.all([
      api(`/api/stocks/quote?symbol=${encodeURIComponent(symbol)}`),
      api(`/api/stocks/candles?symbol=${encodeURIComponent(symbol)}&period=${period}`),
    ]);
    const price = quote.price ?? null;
    const when = asOfText(quote.as_of);   // 그 값이 생긴 시각 — 장이 닫혔으면 마감 시각이 온다(L8)
    infoEl.innerHTML = `<span class="font-semibold">${escHtml(symbol)}</span>
      <span class="ml-3">${price != null ? "$" + fmt(price,2) : "-"}</span>
      <span class="ml-2 font-semibold" style="color:${DIR_COLOR[direction(quote.change_pct)]};">${pctText(quote.change_pct)}</span>
      <span class="ml-3 text-xs" style="color:var(--text-mute);">지연 시세${when ? " · " + escHtml(when) : ""}</span>`;

    if (usChartInstance) { usChartInstance.destroy(); usChartInstance = null; }
    const ohlcv = (candles.candles || [])
      .filter(c => c.open && c.high && c.low && c.close)
      .map(c => ({ x: new Date(c.time * 1000), y: [c.open, c.high, c.low, c.close] }));
    usChartInstance = new ApexCharts(container, {
      chart: { type: "candlestick", height: 400, background: "#fff", toolbar: { show: true },
               animations: { enabled: false }, fontFamily: "Pretendard, sans-serif" },
      series: [{ name: "OHLC", data: ohlcv }],
      xaxis: { type: "datetime", labels: { style: { colors: "#434651" } } },
      yaxis: { tooltip: { enabled: true }, labels: { style: { colors: "#434651" },
               formatter: v => "$" + v?.toFixed(2) } },
      plotOptions: { candlestick: { colors: { upward: "#10b981", downward: "#f43f5e" },
                     wick: { useFillColor: true } } },
      grid: { borderColor: "#e0e3eb" },
      theme: { mode: "light" },
      tooltip: { theme: "light" },
    });
    usChartInstance.render();
  } catch (e) {
    infoEl.textContent = "오류: " + e.message;
  }
}

// 국내 종목인가 — 서버 `app/services/overseas_orders.py` `is_domestic` 과 같은 규칙(TC-USO 가 두 곳을 맞댄다).
const isKrSymbol = s => /\.(KS|KQ|KN)$/i.test(s) || (/^[0-9A-Z]{6}$/i.test(s) && /\d/.test(s));
const KST_TIME = new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });

async function loadUsOrderHistory() {
  const el = document.getElementById("us-order-history");
  if (!el) return;
  try {
    // 모의 장부(원화)의 주문 기록 — 새 주문은 서버가 환율을 곱한 원화 체결가다. 옛 주문(원화 가상 매매 길 · source WEB)은
    // 달러 금액이 원화 장부에 그대로 들어갔으므로 달러로 적고 그 사실을 붙인다(2026-10-16 점검 🔴).
    const { history } = await api("/api/paper/stocks/orders/history?limit=200");
    const usOnly = (history || []).filter(o => !isKrSymbol(String(o.symbol || "")));
    if (!usOnly.length) { el.innerHTML = "<div style='color:var(--text-mute);'>주문 내역 없음</div>"; return; }
    el.innerHTML = usOnly.slice(0, 20).map(o => {
      const buy = String(o.type || "").toUpperCase() === "BUY";
      const old = o.source === "WEB";
      return `
      <div class="flex items-center gap-3 rounded-lg px-3 py-2" style="background:var(--surf2);border:1px solid var(--border);font-size:12px;">
        <span class="${buy?"badge-buy":"badge-sell"}">${buy?"BUY":"SELL"}</span>
        <span class="font-semibold">${escHtml(o.symbol)}</span>
        <span>${fmt(o.quantity)}주</span>
        <span style="color:var(--text-dim);">${old ? `$${fmt(o.price,2)}` : `${fmt(o.price)}원`}</span>
        ${old ? `<span style="color:var(--text-mute);font-size:11px;">옛 주문 — 달러 금액이 원화 장부에 그대로 들어감</span>` : ""}
        <span class="ml-auto" style="color:var(--text-mute);">${o.ts ? KST_TIME.format(new Date(o.ts)) : ""}</span>
      </div>`;
    }).join("");
  } catch (e) {
    el.innerHTML = `<div style='color:var(--red);'>${escHtml(e.message)}</div>`;
  }
}
function renderUsOrders() { loadUsOrderHistory(); }

async function loadUsPortfolio() {
  const acEl = document.getElementById("us-account-summary");
  const pfEl = document.getElementById("us-portfolio-table");
  acEl.innerHTML = "<div class='text-xs' style='color:var(--text-mute);'>조회 중...</div>";
  try {
    // 모의 장부(원화)의 보유 — 평균단가 · 평가 · 손익은 서버가 원화로 셈한다(환율을 곱한 체결가 · 원화 환산 현재가).
    const { positions } = await api("/api/paper/stocks/positions");
    const usPos = (positions || []).filter(p => !isKrSymbol(String(p.symbol || "")));
    if (!usPos.length) {
      acEl.innerHTML = "";
      pfEl.innerHTML = "<div style='color:var(--text-mute);'>보유 종목이 없습니다. '미국주식 주문'에서 매수해보세요.</div>";
      return;
    }
    // 달러 시세 · 환율 글은 모의 시세(서버가 환율을 곱한 그 응답)에서 — 장부 셈에는 쓰지 않는다.
    const quotes = await Promise.all(
      usPos.map(p => api(`/api/paper/stocks/quote?symbol=${encodeURIComponent(p.symbol)}`).catch(() => ({})))
    );
    const totalMkt = usPos.reduce((a,p)=>a+(p.evalAmount||0),0);
    const totalPnl = usPos.reduce((a,p)=>a+(p.pnl||0),0);
    // 옛 주문 길로 생긴 보유는 단가가 달러 그대로라 원화 현재가와 수백 배 차이가 난다 — 그때만 바로잡는 법을 알린다.
    const oldBook = usPos.some(p => p.avgPrice > 0 && p.currentPrice / p.avgPrice > 100);
    const fxNote = (quotes.find(q => q && q.fx_note) || {}).fx_note;
    acEl.innerHTML = [
      { label:"주식 평가 합계", value:`${fmt(totalMkt)}원` },
      { label:"총 손익",       value:`${totalPnl>=0?"+":""}${fmt(totalPnl)}원`, color: totalPnl>=0?"var(--green)":"var(--red)" },
      { label:"보유 종목 수",   value:`${usPos.length}개` },
    ].map(c=>`<div class="card text-center" style="padding:14px;">
      <div class="text-xs" style="color:var(--text-dim);">${c.label}</div>
      <div class="text-lg font-bold mt-1" style="color:${c.color||"var(--text)"};">${c.value}</div>
    </div>`).join("");
    pfEl.innerHTML = `<table>
      <thead><tr><th>종목</th><th>수량</th><th>평균단가</th><th>현재가</th><th>평가금액</th><th>손익</th></tr></thead>
      <tbody>${usPos.map((p, i)=>{
        const q = quotes[i] || {};
        const pnlColor = p.pnl>=0?"var(--green)":"var(--red)";
        const sign = p.pnl>=0?"+":"";
        const local = q.price_local != null && q.currency && q.currency !== "KRW"
          ? `<div style="color:var(--text-mute);font-size:11px;">${fmt(q.price_local,2)} ${escHtml(q.currency)}</div>` : "";
        return `<tr>
          <td><div class="font-semibold">${escHtml(p.symbol)}</div><div style="color:var(--text-mute);font-size:11px;">${escHtml(p.name)}</div></td>
          <td>${fmt(p.quantity)}</td>
          <td>${fmt(p.avgPrice)}원</td>
          <td>${fmt(p.currentPrice)}원${local}</td>
          <td>${fmt(p.evalAmount)}원</td>
          <td style="color:${pnlColor};">${sign}${fmt(Math.abs(p.pnl))}원<div style="font-size:11px;">${sign}${Number(p.pnlRate||0).toFixed(2)}%</div></td>
        </tr>`;
      }).join("")}</tbody>
    </table>
    ${fxNote ? `<div class="text-xs mt-2" style="color:var(--text-mute);">${escHtml(fxNote)}</div>` : ""}
    ${oldBook ? `<div class="text-xs mt-1" style="color:var(--red);">예전 주문 방식으로 생긴 보유는 달러 금액이 원화 장부에 그대로 들어가 평균단가 · 손익이 맞지 않습니다 — 모의계좌 초기화로 바로잡을 수 있습니다.</div>` : ""}`;
  } catch (e) {
    acEl.innerHTML = `<div class="text-xs" style="color:var(--red);">${escHtml(e.message)}</div>`;
  }
}

async function placeUsOrder(side) {
  const symbol = document.getElementById("us-ord-symbol").value.trim().toUpperCase();
  const qty    = parseInt(document.getElementById("us-ord-qty").value);
  const type   = document.getElementById("us-ord-type").value;
  if (!symbol || !qty) return setToast("종목코드와 수량을 입력하세요.", "error");
  // 모의 장부는 원화 하나 — 서버가 시세 · 환율을 정하는 모의 주문 길로 보낸다(가격을 보내지 않는다 · 2026-10-16 점검 🔴).
  if (type === "limit") return setToast("지정가 모의 주문은 아직 없습니다 — 시장가로 주문하세요.", "error");
  // 해외 매도는 비용(증권사 해외 수수료 · 매도 SEC 수수료) 계산이 준비될 때까지 막는다 — 지금 서버 길은 해외 매도에서 멈춘다.
  if (side === "sell") return setToast("해외 종목 모의 매도는 아직 열지 않았습니다 — 해외 매도 비용 계산이 준비되면 열립니다.", "error");
  try {
    const r = await api("/api/paper/stocks/orders", { method: "POST", body: { symbol, side: "BUY", quantity: qty } });
    setToast(`매수 주문 완료: ${r.symbol} ${qty}주 · 원화 환산 체결가 ${fmt(r.price)}원`, "ok");
    loadUsOrderHistory();
  } catch (e) {
    setToast(e.message, "error");
  }
}

document.getElementById("us-ord-buy")?.addEventListener("click",  ()=>placeUsOrder("buy"));
document.getElementById("us-ord-sell")?.addEventListener("click", ()=>placeUsOrder("sell"));
document.getElementById("us-chart-load")?.addEventListener("click", loadUsChart);
document.getElementById("us-refresh")?.addEventListener("click",    loadUsDashboard);
document.getElementById("us-pf-refresh")?.addEventListener("click", loadUsPortfolio);
document.getElementById("alpaca-save")?.addEventListener("click", ()=>{
  const key    = document.getElementById("alpaca-key").value.trim();
  const secret = document.getElementById("alpaca-secret").value.trim();
  const paper  = document.getElementById("alpaca-paper").checked;
  const statusEl = document.getElementById("alpaca-status");
  if (!key || !secret) {
    statusEl.textContent = "⚠️ API 키가 없어 Mockup 모드로 동작합니다.";
    statusEl.style.color = "var(--text-mute)";
  } else {
    statusEl.textContent = `✅ 저장됨 – ${paper?"Paper Trading":"Live"} 모드 (Mockup 적용중)`;
    statusEl.style.color = "var(--green)";
  }
  setToast("Alpaca 설정 저장 완료", "ok");
});


export { loadUsChart, loadUsDashboard, loadUsPortfolio, renderUsOrders };
