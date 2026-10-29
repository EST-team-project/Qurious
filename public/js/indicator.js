/* 투자 인디케이터: 기본 전략, 커스텀 인디케이터(Pine/Python 생성·저장), 성과 검증, 증권사 API 자동화
 * app.html 인라인 스크립트에서 분리됨. 엔트리는 main.js */
import { api, getMe, setToast, escHtml, fmt, fmtPct, colorPct } from "/js/common.js";
import { compareTrayAdd, renderCompareTrayAll, tt } from "/js/core.js";
import { buildRows, summarize, cardBody, cardValues, cardLine } from "/js/indstrategy.js";

// ── 성과 검증 · 커스텀 인디케이터 결과가 같이 쓰는 것 (#245 · #250) ─────
// 거래 0회 — 수익률 · 샤프 · 낙폭 · 승률은 0 이 아니라 매길 수 없는 값이다. 글은 대시보드(dashboard.js noTradeMetric)와 같게(TC-RX 가 맞댄다).
function noTradeHtml(buyHoldPct) {
  const bh = buyHoldPct !== null && buyHoldPct !== undefined && Number.isFinite(Number(buyHoldPct))
    ? Number(buyHoldPct).toLocaleString("ko-KR", { maximumFractionDigits: 1 }) + "%" : "데이터 없음";
  return `<div class="card" style="padding:14px;"><div class="text-xs mb-1" style="color:var(--text-mute);">거래 0회</div><div style="font-size:18px;font-weight:700;">신호 없음</div>` +
    `<div class="text-xs mt-1" style="color:var(--text-dim);">이 기간에 한 번도 사고팔지 않아 수익률 · 샤프 · 최대 낙폭 · 승률을 매기지 않습니다. 같은 기간 매수 후 보유 수익률은 ${escHtml(bh)} 입니다.</div></div>`;
}
// 자료 출처 · 기간 — 글은 서버 data_note 그대로(app/services/data_provenance.py 한 곳 · 전략 분석과 같은 꼴)
const dataNoteHtml = d => (d && d.data_note ? `<p class="text-xs mt-2" style="color:var(--text-dim);">자료: ${escHtml(d.data_note)}</p>` : "");

// ── 투자 인디케이터: 기본 인디케이터 전략 ──────────────────────────
// 표 · 규칙 신호는 체크한 지표만(B2) · 볼린저는 실제 밴드(B1) · 낱말은 「규칙 신호 · 매수 쪽 / 매도 쪽 · 근거 n개」(B3 · 결정 대장 10-27).
// 값은 /api/indicator-strategy/chart(정의 한 벌 ta_utils) 그대로 — 판정 함수는 indstrategy.js(TC-ISC).
const IND_LWC_SRC = "/js/vendor/lightweight-charts/lightweight-charts-5.2.1.min.js";
let indLwcPromise = null, indChart = null, indChartData = null;
const indChecks = () => Object.fromEntries(["ma5", "ma20", "ma60", "rsi", "macd", "bb"].map(k => [k, document.getElementById(`ind-${k}`).checked]));
const indCardWindows = () => {
  const s = Number(document.getElementById("ic-short").value), l = Number(document.getElementById("ic-long").value);
  return Number.isInteger(s) && Number.isInteger(l) && s >= 2 && l > s ? [s, l] : [5, 20];
};

function loadIndLwc() {
  if (window.LightweightCharts) return Promise.resolve(window.LightweightCharts);
  if (indLwcPromise) return indLwcPromise;
  indLwcPromise = new Promise((resolve, reject) => {
    const el = document.createElement("script");
    el.src = IND_LWC_SRC;
    el.async = true;
    const timer = setTimeout(() => reject(new Error("차트 도구를 불러오지 못했습니다(시간 초과).")), 15000);
    el.onload = () => { clearTimeout(timer); window.LightweightCharts ? resolve(window.LightweightCharts) : reject(new Error("차트 도구가 비어 있습니다.")); };
    el.onerror = () => { clearTimeout(timer); reject(new Error("차트 도구를 불러오지 못했습니다.")); };
    document.head.appendChild(el);
  }).catch(e => { indLwcPromise = null; throw e; });
  return indLwcPromise;
}

async function drawIndChart() {
  const d = indChartData;
  if (!d) return;
  const LWC = await loadIndLwc();
  if (indChart) { indChart.remove(); indChart = null; }
  const css = getComputedStyle(document.documentElement);
  const bg = css.getPropertyValue("--surf").trim() || "#ffffff", text = css.getPropertyValue("--text-dim").trim() || "#334155";
  const border = css.getPropertyValue("--border").trim() || "#e0e3eb";
  indChart = LWC.createChart(document.getElementById("ind-chart"), {
    autoSize: true,
    layout: { background: { type: LWC.ColorType.Solid, color: bg }, textColor: text, fontFamily: "Pretendard, sans-serif", attributionLogo: true },
    grid: { vertLines: { color: border }, horzLines: { color: border } },
    rightPriceScale: { borderColor: border }, timeScale: { borderColor: border, timeVisible: false },
    localization: { locale: "ko-KR", priceFormatter: v => new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 2 }).format(v) },
  });
  const times = d.bars.map(b => b.time);
  const line = (key, color, pane = 0, width = 1) => {
    const s = indChart.addSeries(LWC.LineSeries, { color, lineWidth: width, priceLineVisible: false, lastValueVisible: false }, pane);
    s.setData(times.map((t, i) => (d.series[key]?.[i] ?? null) === null ? { time: t } : { time: t, value: d.series[key][i] }));
    return s;
  };
  const candle = indChart.addSeries(LWC.CandlestickSeries, { upColor: "#089981", downColor: "#ef4444", borderVisible: false,
    wickUpColor: "#089981", wickDownColor: "#ef4444" });
  candle.setData(d.bars);
  const c = indChecks();
  if (c.ma5) line("ma5", "#f59e0b"); if (c.ma20) line("ma20", "#3b82f6"); if (c.ma60) line("ma60", "#8b5cf6");
  if (c.bb) { line("bb_upper", "#94a3b8"); line("bb_lower", "#94a3b8"); }
  LWC.createSeriesMarkers(candle, d.markers.map(m => m.side === "buy"
    ? { time: m.time, position: "belowBar", color: "#089981", shape: "arrowUp", text: "매수" }
    : { time: m.time, position: "aboveBar", color: "#ef4444", shape: "arrowDown", text: "매도" }));
  const sub = document.getElementById("ind-sub").value;
  if (sub === "rsi") line("rsi", "#0ea5e9", 1);
  if (sub === "macd") { line("macd", "#0ea5e9", 1); line("macd_signal", "#f97316", 1); }
  if (sub === "dmi") { line("adx", "#0f172a", 1, 2); line("plus_di", "#089981", 1); line("minus_di", "#ef4444", 1); }
  if (sub === "rs") { if (d.series.rs20) { line("rs20", "#0ea5e9", 1); line("rs60", "#8b5cf6", 1); line("rs120", "#f97316", 1); } }
  indChart.timeScale().fitContent();
  const cc = d.card_condition, last = d.bars[d.bars.length - 1];
  const rsText = sub === "rs" ? (d.benchmark ? ` 아래 칸은 ${escHtml(d.benchmark.name)} 대비 20 · 60 · 120일 상대 강도(%)입니다.` : ` ${escHtml(d.rs_note || "")}`) : "";
  document.getElementById("ind-chart-note").innerHTML =
    `일봉 · 종가 기준(마지막 봉 ${new Date(last.time * 1000).toISOString().slice(0, 10)}). ▲매수 ▼매도 표시는 전략 카드 조건(${cc.short_window}일선이 ${cc.long_window}일선 위)이 바뀐 날입니다 — 체결은 카드의 체결 시점을 따릅니다.${rsText}` +
    (d.data_note ? ` 자료: ${escHtml(d.data_note)}` : "");
}

async function runIndStrategy() {
  const symbol = document.getElementById("ind-symbol").value;
  const period = document.getElementById("ind-period").value;
  const [short, long] = indCardWindows();
  try {
    const d = await api(`/api/indicator-strategy/chart?symbol=${encodeURIComponent(symbol)}&period=${encodeURIComponent(period)}&short=${short}&long=${long}`);
    indChartData = d;
    const rows = buildRows(d, indChecks());
    const sum = summarize(rows);
    const bars = d.bars, price = bars[bars.length - 1].close;
    const chgPct = bars.length > 1 ? ((price / bars[bars.length - 2].close) - 1) * 100 : 0;
    const rsi = buildRows(d, { rsi: true }).find(r => r[0].startsWith("RSI"));
    const ma = buildRows(d, { ma5: true, ma20: true })[0];

    // 「현재가」 는 지금 값 — 서버 quote_now(내 증권사 키 → 지연 시세 → 지난 종가)와 그 출처 · 시각 글(2026-10-19 · 화면에 지난 종가가
    // 「현재가」 로 보였다: 210,000 ↔ 실제 217,000). 지표 · 신호는 아래 「지표 기준」 의 일봉 그대로다. 받지 못하면 일봉 값에 기준 글을 단다.
    const now = await api(`/api/quote/now?symbol=${encodeURIComponent(symbol)}`).catch(() => null);
    const nowPrice = now?.price ?? price;
    const nowPct = now?.price != null ? (now.change_pct ?? 0) : chgPct;
    const nowNote = now?.price != null ? now.label : (d.data_note || "");
    const tone = side => side === "매수 쪽" ? "var(--green)" : side === "매도 쪽" ? "var(--red)" : "var(--text-mute)";
    document.getElementById("ind-summary-cards").innerHTML = [
      { label:"현재가",   value:`${fmt(nowPrice)}원`, sub:`${nowPct>=0?"+":""}${Number(nowPct).toFixed(2)}% · ${escHtml(nowNote)}`, color: nowPct>=0?"var(--green)":"var(--red)" },
      { label:"RSI(14)",  value: rsi ? rsi[1] : "—", sub: rsi ? rsi[2] : "값 없음", color: tone(rsi?.[3]) },
      { label:"5일선 · 20일선", value: ma ? ma[2].replace("5일선이 20일선 ", "") : "—", sub: ma ? ma[1] : "값 없음", color: tone(ma?.[3]) },
      { label:"규칙 신호", value: sum.n ? sum.side : "—", sub: sum.n ? `근거 ${sum.n}개 · 매수 쪽 ${sum.buy} · 중립 ${sum.neutral} · 매도 쪽 ${sum.sell}` : "고른 지표 없음", color: tone(sum.side) },
    ].map(c => `<div class="card" style="padding:14px;"><div class="text-xs" style="color:var(--text-mute);">${c.label}</div><div style="font-size:20px;font-weight:700;margin:4px 0;color:${c.color};">${c.value}</div><div style="font-size:12px;color:${c.color};">${c.sub}</div></div>`).join("")
      + (d.data_note ? `<div class="ind-basis text-xs" style="grid-column:1/-1;color:var(--text-mute);">지표 기준: ${escHtml(d.data_note)}</div>` : "");

    document.getElementById("ind-analysis-table").innerHTML = rows.length ? `<table>
      <thead><tr><th>인디케이터</th><th>지금 값</th><th>상태</th><th>쪽</th></tr></thead>
      <tbody>${rows.map(([n, val, st, side]) => `<tr><td style="font-weight:600;">${n}</td><td>${val}</td><td>${st}</td><td><span class="${side==="매수 쪽"?"badge-buy":side==="매도 쪽"?"badge-sell":"badge-hold"}">${side}</span></td></tr>`).join("")}</tbody>
    </table>` : `<p class="text-sm" style="color:var(--text-dim);">위에서 지표를 하나 이상 고르세요.</p>`;

    document.getElementById("ind-signal-summary").innerHTML = `
      <div class="flex gap-3 flex-wrap">
        <span class="badge-buy">매수 쪽: ${sum.buy}개</span>
        <span class="badge-sell">매도 쪽: ${sum.sell}개</span>
        <span class="badge-hold">중립: ${sum.neutral}개</span>
      </div>
      <p class="text-xs mt-2" style="color:var(--text-dim);">${escHtml(sum.text)} · 고른 지표만 셉니다. 매수 · 매도를 권하는 말이 아니라 규칙을 따른 결과입니다.</p>`;

    document.getElementById("ind-strategy-result").classList.remove("hidden");
    await drawIndChart().catch(e => { document.getElementById("ind-chart-note").textContent = e.message; });
  } catch(e) { setToast(e.message, "error"); }
}
document.getElementById("ind-load-btn").addEventListener("click", runIndStrategy);
document.getElementById("ind-sub").addEventListener("change", () => drawIndChart().catch(e => setToast(e.message, "error")));

// ── 전략 카드 편집(U6 · #392) — 저장은 사용자마다 · 「카드 → Pine 내려받기」 목록에도 나온다 ─────────
const IC_INPUTS = { slug:"ic-slug", name:"ic-name", short_window:"ic-short", long_window:"ic-long", atr_period:"ic-atr-period",
  atr_mult:"ic-atr-mult", take_rr:"ic-take-rr", risk_pct:"ic-risk", max_position_pct:"ic-maxpos", max_symbols:"ic-maxsym",
  entry_mode:"ic-mode", judge:"ic-judge" };
let icCards = [];
function icFill(values) {
  for (const [k, id] of Object.entries(IC_INPUTS)) document.getElementById(id).value = values[k] ?? "";
}
async function icRefresh(select) {
  const r = await api("/api/indicator-strategy/cards");
  icCards = (r.cards || []).filter(c => c.card);
  const sel = document.getElementById("ic-mine");
  sel.innerHTML = icCards.length ? icCards.map(c => `<option value="${escHtml(c.id)}">${escHtml(cardLine(c.card))}</option>`).join("")
    : `<option value="">저장한 카드가 없습니다</option>`;
  if (select) sel.value = select;
  if (!document.getElementById("ic-short").value) icFill({ ...cardValues(r.template), slug: "", name: "" });
}
document.getElementById("ic-load").addEventListener("click", () => {
  const c = icCards.find(x => x.id === document.getElementById("ic-mine").value);
  if (c) { icFill(cardValues(c.card)); document.getElementById("ic-msg").textContent = "카드를 불러왔습니다. 「전략 분석」 을 누르면 차트 표시가 이 조건을 따릅니다."; }
});
document.getElementById("ic-delete").addEventListener("click", async () => {
  const id = document.getElementById("ic-mine").value;
  if (!id) return;
  try { await api(`/api/indicator-strategy/cards/${encodeURIComponent(id)}`, { method: "DELETE" }); await icRefresh(); setToast("카드를 지웠습니다.", "ok"); }
  catch (e) { setToast(e.message, "error"); }
});
document.getElementById("ic-save").addEventListener("click", async () => {
  const values = Object.fromEntries(Object.entries(IC_INPUTS).map(([k, id]) => [k, document.getElementById(id).value]));
  values.exit_mode = values.entry_mode;
  values.symbol = document.getElementById("ind-symbol").value;
  try {
    const r = await api("/api/indicator-strategy/cards", { method: "POST", body: cardBody(values) });
    await icRefresh(r.id);
    document.getElementById("ic-msg").textContent = `저장했습니다 — ${cardLine(r.card)}`;
  } catch (e) { document.getElementById("ic-msg").textContent = e.message; setToast(e.message, "error"); }
});
document.getElementById("ind-card-box").addEventListener("toggle", e => { if (e.target.open) icRefresh().catch(err => setToast(err.message, "error")); });

// ── 투자 인디케이터: 커스텀 인디케이터 개발 ──────────────────────────
function generatePineCode() {
  const name   = document.getElementById("ci-name").value || "MyIndicator";
  const base   = document.getElementById("ci-base").value || "rsi_ma";
  const short  = document.getElementById("ci-short").value || 5;
  const mid    = document.getElementById("ci-mid").value || 20;
  const rsiLen = document.getElementById("ci-rsi").value || 14;
  const buyTh  = document.getElementById("ci-buy-th").value || 35;
  const signalCode = base === "macd_bb"
    ? `macd_line = ta.ema(close, 12) - ta.ema(close, 26)\nmacd_sig  = ta.ema(macd_line, 9)\nbb_mid = ta.sma(close, mid_len)\nbuy_signal  = ta.crossover(macd_line, macd_sig) and close < bb_mid\nsell_signal = ta.crossunder(macd_line, macd_sig) or close > bb_mid + 2 * ta.stdev(close, mid_len)`
    : base === "volume_rsi"
    ? `vol_ma = ta.sma(volume, mid_len)\nbuy_signal  = rsi_val < buy_th and volume > vol_ma\nsell_signal = rsi_val > sell_th`
    : base === "triple_ma"
    ? `ma_long = ta.sma(close, mid_len * 2)\nbuy_signal  = ta.crossover(ma_short, ma_mid) and ma_mid > ma_long\nsell_signal = ta.crossunder(ma_short, ma_mid) or ma_mid < ma_long`
    : `buy_signal  = ta.crossover(ma_short, ma_mid) and rsi_val < buy_th\nsell_signal = ta.crossunder(ma_short, ma_mid) or rsi_val > sell_th`;

  return `//@version=5
indicator("${name}", overlay=true)

// 파라미터
short_len = input.int(${short}, "단기 MA 기간")
mid_len   = input.int(${mid},   "중기 MA 기간")
rsi_len   = input.int(${rsiLen}, "RSI 기간")
buy_th    = input.int(${buyTh}, "매수 RSI 임계값")
sell_th   = input.int(100 - parseInt(buyTh), "매도 RSI 임계값")

// 인디케이터 계산
ma_short = ta.sma(close, short_len)
ma_mid   = ta.sma(close, mid_len)
rsi_val  = ta.rsi(close, rsi_len)

// 매매 신호 (${base})
${signalCode}

// 시각화
plot(ma_short, color=color.blue,  title="MA Short")
plot(ma_mid,   color=color.orange, title="MA Mid")
plotshape(buy_signal,  style=shape.triangleup,   location=location.belowbar, color=color.green, size=size.small, title="Buy")
plotshape(sell_signal, style=shape.triangledown, location=location.abovebar, color=color.red,   size=size.small, title="Sell")`;
}

function generatePythonCode() {
  const name   = document.getElementById("ci-name").value || "MyIndicator";
  const base   = document.getElementById("ci-base").value || "rsi_ma";
  const short  = document.getElementById("ci-short").value || 5;
  const mid    = document.getElementById("ci-mid").value || 20;
  const rsiLen = document.getElementById("ci-rsi").value || 14;
  const buyTh  = document.getElementById("ci-buy-th").value || 35;
  const pySignal = base === "macd_bb"
    ? `    macd = ta.macd(df["Close"])["MACD_12_26_9"]\n    macd_sig = ta.macd(df["Close"])["MACDs_12_26_9"]\n    bb = ta.bbands(df["Close"], length=${mid})\n    df["buy_signal"] = (macd > macd_sig) & (macd.shift(1) <= macd_sig.shift(1)) & (df["Close"] < bb.iloc[:, 1])\n    df["sell_signal"] = (macd < macd_sig) & (macd.shift(1) >= macd_sig.shift(1))`
    : base === "volume_rsi"
    ? `    vol_ma = df["Volume"].rolling(${mid}).mean()\n    df["buy_signal"] = (df["rsi"] < ${buyTh}) & (df["Volume"] > vol_ma)\n    df["sell_signal"] = df["rsi"] > ${100 - parseInt(buyTh)}`
    : base === "triple_ma"
    ? `    ma_long = ta.sma(df["Close"], length=${parseInt(mid) * 2})\n    df["buy_signal"] = df["golden_cross"] & (df["ma_mid"] > ma_long)\n    df["sell_signal"] = df["dead_cross"] | (df["ma_mid"] < ma_long)`
    : `    df["buy_signal"]  = df["golden_cross"] & (df["rsi"] < ${buyTh})\n    df["sell_signal"] = df["dead_cross"]   | (df["rsi"] > ${100 - parseInt(buyTh)})`;

  return `import pandas as pd
import pandas_ta as ta

def ${name.replace(/[^a-zA-Z0-9_]/g,"_")}(df: pd.DataFrame) -> pd.DataFrame:
    """커스텀 인디케이터: ${name}"""
    df["ma_short"] = ta.sma(df["Close"], length=${short})
    df["ma_mid"]   = ta.sma(df["Close"], length=${mid})
    df["rsi"]      = ta.rsi(df["Close"], length=${rsiLen})

    df["golden_cross"] = (df["ma_short"] > df["ma_mid"]) & (df["ma_short"].shift(1) <= df["ma_mid"].shift(1))
    df["dead_cross"]   = (df["ma_short"] < df["ma_mid"]) & (df["ma_short"].shift(1) >= df["ma_mid"].shift(1))

    # 선택 기반: ${base}
${pySignal}
    df["signal"] = "HOLD"
    df.loc[df["buy_signal"],  "signal"] = "BUY"
    df.loc[df["sell_signal"], "signal"] = "SELL"
    return df`;
}

document.getElementById("ci-generate-btn").addEventListener("click", () => {
  document.getElementById("ci-pine-code").textContent   = generatePineCode();
  document.getElementById("ci-python-code").textContent = generatePythonCode();
});
document.getElementById("ci-copy-pine").addEventListener("click", () => {
  navigator.clipboard.writeText(document.getElementById("ci-pine-code").textContent);
  setToast("PineScript 복사됨", "ok");
});
document.getElementById("ci-copy-py").addEventListener("click", () => {
  navigator.clipboard.writeText(document.getElementById("ci-python-code").textContent);
  setToast("Python 코드 복사됨", "ok");
});
document.getElementById("ci-test-btn").addEventListener("click", async () => {
  const name = document.getElementById("ci-name").value || "MyIndicator";
  const base = document.getElementById("ci-base").value || "rsi_ma";
  const short = parseInt(document.getElementById("ci-short").value || "5");
  const mid = parseInt(document.getElementById("ci-mid").value || "20");
  const rsi = parseInt(document.getElementById("ci-rsi").value || "14");
  const buyTh = parseFloat(document.getElementById("ci-buy-th").value || "35");
  const symbol = document.getElementById("ibt-symbol")?.value || "005930.KS";
  try {
    const q = new URLSearchParams({ symbol, period: "10y", base, short, mid, rsi, buy_th: buyTh, cost_bps: document.getElementById("ci-cost")?.value || "0", slippage_bps: "0" });
    const sl = document.getElementById("ci-sl")?.value, tp = document.getElementById("ci-tp")?.value;
    if (sl) q.set("stop_loss_pct", sl); if (tp) q.set("take_profit_pct", tp);
    const r = await api(`/api/quant/pipeline?${q}`);
    const c = r.costs || {};
    // 커스텀 화면엔 종목 칸이 없어 성과 검증 칸의 종목으로 계산한다 — 무슨 종목인지 결과 위에 밝힌다(#245)
    const ibtOpt = document.getElementById("ibt-symbol")?.selectedOptions?.[0];
    const symName = ibtOpt && ibtOpt.value === symbol ? ibtOpt.textContent.trim() : "";
    const ciSym = document.getElementById("ci-bt-symbol");
    if (ciSym) ciSym.innerHTML = `계산 종목: <b>${escHtml(symName ? `${symName}(${symbol.split(".")[0]})` : symbol)}</b> — 성과 검증 화면에서 고른 종목`;
    const noTrade = Number(r.trade_count) === 0;
    const data = [
      { label:"누적 수익률", value: `${(r.return_total*100 >= 0 ? "+" : "")}${(r.return_total*100).toFixed(1)}%`, color:"var(--green)" },
      { label:tt("샤프 비율","위험 대비 수익 지표. 높을수록 좋음","sharpe"),   value: Number(r.sharpe || 0).toFixed(2), color:"var(--accent)" },
      { label:tt("최대 낙폭","전략 보유 기간 중 최악의 손실 구간(MDD)","mdd"),   value: `${(r.mdd*100).toFixed(1)}%`, color:"var(--red)" },
      { label:tt("승률","수익이 난 거래의 비율","win_rate"),        value: `${Number(r.win_rate_pct || 0).toFixed(1)}%`, color:"var(--text)" },
      { label:tt("비용 차감","수수료+슬리피지 누적 차감(%p)","cost_bps"), value: `-${Number(c.cost_pct || 0).toFixed(2)}%p`, color:"var(--text-mute)" },
      { label:"손절/익절 발동", value: `${c.stop_loss_exits ?? 0}회 / ${c.take_profit_exits ?? 0}회`, color:"var(--text-mute)" },
    ];
    document.getElementById("ci-bt-cards").innerHTML = noTrade
      ? `<div class="col-span-2 md:col-span-4">${noTradeHtml(r.return_buy_hold === null || r.return_buy_hold === undefined ? null : Number(r.return_buy_hold) * 100)}</div>`
      : data.map(d=>`
      <div class="card" style="padding:14px;text-align:center;">
        <div class="text-xs mb-1" style="color:var(--text-mute);">${d.label}</div>
        <div style="font-size:18px;font-weight:700;color:${d.color};">${d.value}</div>
      </div>`).join("");
    // Qurious: 어떤 비용 모델로 뗐는지 글로도 밝힌다(대칭 수수료인지 · 실제 요율인지) — app.html 의 ci-bt-cost 자리
    const ciCost = document.getElementById("ci-bt-cost");
    if (ciCost) {
      const drag = Number(r.cost_drag_pct ?? 0);
      const gross = Number(r.return_gross ?? 0) * 100;
      ciCost.textContent = r.cost
        ? `매매비용: ${r.cost.label} — 비용 전 ${gross.toFixed(1)}% 에서 ${drag.toFixed(1)}%p 를 뺀 값입니다. 신호는 다음 거래일 수익률에 적용됩니다.`
        : "";
    }
    const ciSrc = document.getElementById("ci-bt-source");
    if (ciSrc) ciSrc.innerHTML = dataNoteHtml(r);
    document.getElementById("ci-backtest-result").classList.remove("hidden");
    setToast(`${name} 백테스트 완료 (${symbol})`, "ok");
  } catch (e) {
    setToast("백테스트 오류: " + e.message, "error");
  }
});
// 초기 코드 생성
generatePineCode && (() => {
  const pine = generatePineCode();
  const py   = generatePythonCode();
  const pineEl = document.getElementById("ci-pine-code");
  const pyEl   = document.getElementById("ci-python-code");
  if (pineEl) pineEl.textContent = pine;
  if (pyEl)   pyEl.textContent   = py;
})();

// ── 커스텀 인디케이터 저장/불러오기 ──────────────────────────────────
document.getElementById("ci-save-btn")?.addEventListener("click", async () => {
  const body = {
    name:          document.getElementById("ci-name").value || "MyIndicator",
    base:          document.getElementById("ci-base").value || "rsi_ma",
    short_window:  parseInt(document.getElementById("ci-short").value || "5"),
    mid_window:    parseInt(document.getElementById("ci-mid").value || "20"),
    rsi_period:    parseInt(document.getElementById("ci-rsi").value || "14"),
    buy_threshold: parseFloat(document.getElementById("ci-buy-th").value || "35"),
  };
  try {
    await api("/api/custom-indicators", { method: "POST", body });
    setToast(`'${body.name}' 저장 완료`, "ok");
    loadSavedIndicators();
  } catch (e) {
    setToast("저장 오류: " + e.message, "error");
  }
});

const CI_BASE_LABELS = { rsi_ma:"RSI+이동평균", macd_bb:"MACD+볼린저", volume_rsi:"거래량 가중 RSI", triple_ma:"삼중 이동평균" };

async function loadSavedIndicators() {
  const el = document.getElementById("ci-saved-list");
  if (!el) return;
  try {
    const { items } = await api("/api/custom-indicators");
    if (!items.length) { el.innerHTML = "<div style='color:var(--text-mute);'>저장된 인디케이터가 없습니다. 파라미터를 조정한 뒤 '저장'을 눌러보세요.</div>"; return; }
    el.innerHTML = items.map(it => `
      <div class="flex items-center gap-3 rounded-lg px-3 py-2" style="background:var(--surf2);border:1px solid var(--border);">
        <div class="flex-1">
          <span class="font-semibold">${escHtml(it.name)}</span>
          <span class="text-xs ml-2" style="color:var(--text-mute);">${escHtml(CI_BASE_LABELS[it.base] || it.base)} · 단기${it.short_window}/중기${it.mid_window} · RSI${it.rsi_period} · 매수임계값${it.buy_threshold}</span>
        </div>
        <button type="button" class="btn-secondary text-xs ci-apply-btn" data-id="${escHtml(it.id)}">불러오기</button>
        <button type="button" class="btn-secondary text-xs ci-delete-btn" data-id="${escHtml(it.id)}">삭제</button>
      </div>
    `).join("");
    const byId = Object.fromEntries(items.map(it => [it.id, it]));
    el.querySelectorAll(".ci-apply-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const it = byId[btn.dataset.id];
        if (!it) return;
        document.getElementById("ci-name").value = it.name;
        document.getElementById("ci-base").value = it.base;
        document.getElementById("ci-short").value = it.short_window;
        document.getElementById("ci-mid").value = it.mid_window;
        document.getElementById("ci-rsi").value = it.rsi_period;
        document.getElementById("ci-buy-th").value = it.buy_threshold;
        document.getElementById("ci-generate-btn")?.click();
        setToast(`'${it.name}' 불러왔습니다`, "ok");
      });
    });
    el.querySelectorAll(".ci-delete-btn").forEach(btn => {
      btn.addEventListener("click", async () => {
        try {
          await api(`/api/custom-indicators/${encodeURIComponent(btn.dataset.id)}`, { method: "DELETE" });
          loadSavedIndicators();
        } catch (e) { setToast(e.message, "error"); }
      });
    });
  } catch (e) {
    el.innerHTML = `<div style="color:var(--red);">${escHtml(e.message)}</div>`;
  }
}

// ── 투자 인디케이터: 성과 검증 (Python 백테스트) ───────────────────
async function loadIndicatorBacktest() {
  const sym = document.getElementById("ibt-symbol")?.value;
  const strategy = document.getElementById("ibt-strategy")?.value;
  if (!sym) return;
  try {
    const q = new URLSearchParams({ symbol: sym, period: "10y", strategy, cost_bps: document.getElementById("ibt-cost")?.value || "10", slippage_bps: document.getElementById("ibt-slip")?.value || "0" });
    const sl = document.getElementById("ibt-sl")?.value, tp = document.getElementById("ibt-tp")?.value;
    if (sl) q.set("stop_loss_pct", sl); if (tp) q.set("take_profit_pct", tp);
    const data = await api(`/api/quant/pipeline?${q}`);
    renderIndicatorBacktest(data);
  } catch {}
}

function renderIndicatorBacktest(data) {
  const el = document.getElementById("ibt-result");
  if (!el || !data) return;
  const strategy = document.getElementById("ibt-strategy")?.value || "rsi";
  const strategyLabel = { rsi:"RSI 역추세", ma:"이동평균 교차", bollinger:"볼린저밴드", composite:"복합 인디케이터" }[strategy] || "";
  // 거래 0회면 수익률 · 샤프 · 낙폭 · 승률 대신 「신호 없음」 글 — 대시보드와 같은 말(#245)
  const noTrade = Number(data.trade_count) === 0;
  const card = c => `<div class="card" style="padding:14px;text-align:center;"><div class="text-xs mb-1" style="color:var(--text-mute);">${c.l}</div><div style="font-size:18px;font-weight:700;color:${c.c};">${c.v}</div></div>`;
  el.innerHTML = `
    <div class="grid md:grid-cols-4 gap-3">
      ${card({ l:"전략", v: strategyLabel, c:"var(--accent)" })}
      ${noTrade ? `<div class="md:col-span-3">${noTradeHtml(data.buy_hold_return_pct)}</div>` : [
        { l:"누적 수익률", v: `${data?.total_return_pct >= 0 ? "+" : ""}${Number(data?.total_return_pct || 0).toFixed(1)}%`, c:"var(--green)" },
        { l:tt("샤프 비율","위험 대비 수익 지표. 높을수록 좋음","sharpe"),  v: Number(data?.sharpe_ratio || 0).toFixed(2), c:"var(--text)" },
        { l:tt("최대 낙폭","전략 보유 기간 중 최악의 손실 구간(MDD)","mdd"),  v: `${Number(data?.mdd_pct || 0).toFixed(1)}%`, c:"var(--red)" },
      ].map(card).join("")}
    </div>
    <div class="card">
      <h3 class="font-semibold mb-2 text-sm">📊 Python 백테스트 상세</h3>
      <table><thead><tr><th>비교 대상</th><th style="text-align:right;">누적 수익률</th><th style="text-align:right;">거래 횟수</th><th style="text-align:right;">${tt("승률","수익이 난 거래의 비율","win_rate")}</th></tr></thead>
      <tbody><tr><td>${strategyLabel}</td>${noTrade ? `<td style="text-align:right;">-</td><td style="text-align:right;">0회</td><td style="text-align:right;">-</td>` : `<td style="text-align:right;color:${Number(data.total_return_pct)>=0?"var(--green)":"var(--red)"};">${Number(data.total_return_pct)>=0?"+":""}${Number(data.total_return_pct).toFixed(2)}%</td><td style="text-align:right;">${data.trade_count}회</td><td style="text-align:right;">${Number(data.win_rate_pct).toFixed(1)}%</td>`}</tr><tr><td>매수 후 보유</td><td style="text-align:right;">${Number(data.buy_hold_return_pct).toFixed(2)}%</td><td style="text-align:right;">-</td><td style="text-align:right;">-</td></tr></tbody></table>
      <p class="text-xs mt-2" style="color:var(--text-mute);">비용 차감 전 수익률 ${Number(data.gross_return_pct ?? data.total_return_pct).toFixed(1)}% → 수수료 ${data.cost_bps ?? 0}bp + 슬리피지 ${data.slippage_bps ?? 0}bp 로 누적 ${Number(data.cost_pct || 0).toFixed(2)}%p 차감 · 손절 ${data.stop_loss_pct ? data.stop_loss_pct + "% (" + data.stop_loss_exits + "회 발동)" : "미적용"} · 익절 ${data.take_profit_pct ? data.take_profit_pct + "% (" + data.take_profit_exits + "회 발동)" : "미적용"} · 매매비용 모델: ${data.cost ? data.cost.label : "미반영"} · 매수 후 보유에도 같은 잣대(첫날 매수·마지막날 매도)를 적용했습니다 · 신호는 다음 거래일 수익률에 적용됩니다.</p>
      ${dataNoteHtml(data)}
      ${renderRuleExplain(data.explanation)}
      <button type="button" class="btn-secondary text-xs mt-2" onclick='compareTrayAdd(${JSON.stringify({
        source: "성과 검증 (Python)", label: `${strategyLabel}`,
        summary: noTrade ? `거래 0회 · 신호 없음 · 매수 후 보유 ${Number(data.buy_hold_return_pct||0).toFixed(1)}%` : `수익률 ${Number(data.total_return_pct)>=0?"+":""}${Number(data.total_return_pct).toFixed(1)}% · 샤프 ${Number(data.sharpe_ratio||0).toFixed(2)} · MDD ${Number(data.mdd_pct||0).toFixed(1)}% · 승률 ${Number(data.win_rate_pct||0).toFixed(1)}%`,
      }).replace(/'/g, "&#39;")})'>⚖️ 비교에 추가</button>
    </div>`;
  renderCompareTrayAll();
}

// 규칙 설명 — 마지막 봉에서 그 전략의 매수 · 매도 조건이 어떻게 읽혔는지(서버 explain_strategy · 강사님 원본 화면을 따름)
function renderRuleExplain(xai) {
  if (xai?.kind !== "strategy_rules") return "";
  const rows = (list = []) => list.map(r => `<li class="rounded-lg p-3 mb-2" style="background:var(--surf2);overflow-wrap:anywhere;"><strong style="color:${r.matched ? "var(--green)" : "var(--text-mute)"};">${r.matched ? "✓ 충족" : "○ 미충족"} · ${escHtml(r.label)}</strong><div class="mt-1">조건: ${escHtml(r.rule)}</div><div style="color:var(--text-dim);">관측값: ${escHtml(r.observed)}</div></li>`).join("");
  const action = { BUY: "매수 전환", SELL: "매도 전환", HOLD: "상태 유지" }[xai.action] || "확인 불가";
  return `
    <div class="mt-3">
      <h4 class="font-semibold text-sm mb-2">판단 근거 — 규칙 설명</h4>
      <p class="text-sm mb-1">${escHtml(String(xai.as_of || "").slice(0, 10))} 기준: <strong>${action}</strong> · 기본 전략 상태: ${escHtml(xai.position)}</p>
      <p class="text-xs mb-3" style="color:var(--text-mute);">이미 같은 상태라면 조건이 충족되어도 새 전환 신호는 나오지 않습니다.</p>
      <div class="grid md:grid-cols-2 gap-3">
        <div><h5 class="font-semibold text-sm mb-2">매수 · ${escHtml(xai.buy_logic)}</h5><ul>${rows(xai.buy_conditions)}</ul></div>
        <div><h5 class="font-semibold text-sm mb-2">매도 · ${escHtml(xai.sell_logic)}</h5><ul>${rows(xai.sell_conditions)}</ul></div>
      </div>
      <p class="text-xs mt-2" style="color:var(--text-mute);">${escHtml(xai.scope)}</p>
    </div>`;
}

document.getElementById("ibt-run-btn")?.addEventListener("click", loadIndicatorBacktest);

// ── 투자 인디케이터: 증권사 API 자동화 ──────────────────────────────
async function loadIndicatorApiSettings() {
  try {
    const data = await api("/api/broker/settings");
    if (data?.broker) {
      const t = document.getElementById("iapi-broker-type");
      if (t) t.value = data.broker;
    }
    const status = document.getElementById("iapi-status");
    if (status) status.textContent = data?.connected ? "✅ 연결됨" : "연결되지 않음";
  } catch {}
}

document.getElementById("iapi-save-btn")?.addEventListener("click", async () => {
  const body = {
    broker: document.getElementById("iapi-broker-type").value,
    app_key:     document.getElementById("iapi-app-key").value,
    app_secret:  document.getElementById("iapi-app-secret").value,
    account_no:  document.getElementById("iapi-account").value,
    paper: document.getElementById("iapi-paper").checked,
  };
  try {
    await api("/api/broker/settings", { method:"POST", body });
    setToast("API 설정 저장됨", "ok");
    document.getElementById("iapi-status").textContent = "✅ 저장 완료";
  } catch(e) { setToast(e.message, "error"); }
});
document.getElementById("iapi-test-btn")?.addEventListener("click", async () => {
  try {
    const r = await api("/api/broker/test");
    setToast(r.message || "연결 테스트 성공", "ok");
  } catch(e) { setToast(e.message || "연결 실패", "error"); }
});


export { loadIndicatorApiSettings, loadIndicatorBacktest, loadSavedIndicators };
