/* 퀀트자동매매: 대시보드, 자동매매·위험관리 상태, 전략 분석
 * app.html 인라인 스크립트에서 분리됨. 엔트리는 main.js */
import { api, getMe, setToast, escHtml, fmt, fmtPct, colorPct } from "/js/common.js";
import { compareTrayAdd, renderCompareTrayAll } from "/js/core.js";

let quantChartInstance = null;
// ── 퀀트 대시보드 ────────────────────────────────────────────────
async function loadQuantDashboard() {
  loadMarketCards();
  loadSignalCards();
  loadQuantChart();
}

// 화면에 보이는 신호 낱말 — 「강력 매수」 → 「매수 · 강」 (#161 A7 · #153)
// 코드의 sig.action(원본)은 바꾸지 않음 — 자동매매가 그 글자를 읽음
function _displayAction(action) {
  if (!action) return "-";
  if (action === "강력 매수") return "매수 · 강";
  if (action === "강력 매도" || action === "강력매도") return "매도 · 강";
  return action;
}

async function loadMarketCards() {
  try {
    const { indices } = await api("/api/stocks/market");
    document.getElementById("market-cards").innerHTML = indices.map(idx => {
      const pct = idx.change_pct;
      const sign = pct != null && pct >= 0 ? "+" : "";
      const cls = pct != null && pct >= 0 ? "text-emerald-400" : "text-red-400";
      return `<div class="rounded-xl border border-white/10 bg-black/20 p-3 text-center">
        <div class="text-xs text-slate-400">${escHtml(idx.name)}</div>
        <div class="text-lg font-semibold mt-1">${fmt(idx.price)}</div>
        <div class="${cls} text-xs">${sign}${pct?.toFixed(2) ?? "-"}%</div>
      </div>`;
    }).join("");
  } catch {}
}

async function loadSignalCards() {
  const el = document.getElementById("signal-cards");
  el.innerHTML = "<div class='col-span-5 text-slate-400 text-xs'>시그널 로딩 중...</div>";
  try {
    const { stocks } = await api("/api/stocks/quant/list");
    const results = await Promise.allSettled(
      stocks.map(s => api(`/api/stocks/quant/indicators?symbol=${encodeURIComponent(s.symbol)}&period=2y`))
    );
    el.innerHTML = stocks.map((s, i) => {
      const r = results[i].status === "fulfilled" ? results[i].value : null;
      const sig = r?.signal || {};
      const price = r?.current_price;
      const rsiV = r?.current_rsi;
      const colorMap = { "강력 매수": "border-emerald-500/50 bg-emerald-500/10",
        "매수": "border-emerald-500/30 bg-emerald-500/5",
        "강력 매도": "border-red-500/50 bg-red-500/10",
        "매도": "border-red-500/30 bg-red-500/5",
        "관망": "border-white/10 bg-white/5" };
      const cls = colorMap[sig.action] || "border-white/10 bg-white/5";
      return `<div class="rounded-xl border p-2 ${cls}">
        <div class="font-semibold">${escHtml(s.name)}</div>
        <div class="text-slate-400 text-xs">${escHtml(s.symbol)}</div>
        <div class="mt-1 font-medium">${fmt(price)}</div>
        <div class="mt-1 text-xs font-semibold">${escHtml(_displayAction(sig.action))}</div>
        <div class="text-xs text-slate-500">RSI: ${rsiV?.toFixed(1) ?? "-"}</div>
      </div>`;
    }).join("");
  } catch (e) {
    el.innerHTML = `<div class='col-span-5 text-red-400 text-xs'>${escHtml(e.message)}</div>`;
  }
}

async function loadQuantChart() {
  const symbol = document.getElementById("quant-symbol").value;
  const container = document.getElementById("quant-chart-container");
  container.innerHTML = "";
  try {
    const data = await api(`/api/stocks/quant/indicators?symbol=${encodeURIComponent(symbol)}&period=2y`);
    if (data.error) { container.textContent = data.error; return; }

    if (quantChartInstance) { quantChartInstance.destroy(); quantChartInstance = null; }

    const times = data.times || [];
    const toMs = t => new Date(t * 1000).getTime();
    const mapS = (arr) => arr.map((v, i) => [toMs(times[i]), v != null ? +v.toFixed(2) : null]).filter(p => p[1] != null);

    quantChartInstance = new ApexCharts(container, {
      chart: { type: "line", height: 380, background: "#fff", toolbar: { show: true },
               animations: { enabled: false }, fontFamily: "Pretendard, sans-serif",
               zoom: { enabled: true } },
      series: [
        { name: "종가",   data: mapS(data.closes)   },
        { name: "MA20",   data: mapS(data.ma20 || []) },
        { name: "MA60",   data: mapS(data.ma60 || []) },
        { name: "BB 상단", data: mapS(data.bb_upper || []) },
        { name: "BB 하단", data: mapS(data.bb_lower || []) },
      ],
      colors: ["#6366f1", "#f59e0b", "#10b981", "#94a3b8", "#94a3b8"],
      stroke: { width: [2, 1.5, 1.5, 1, 1], dashArray: [0, 0, 0, 4, 4], curve: "smooth" },
      xaxis: { type: "datetime", labels: { style: { colors: "#434651" } } },
      yaxis: { labels: { style: { colors: "#434651" }, formatter: v => v?.toLocaleString() } },
      grid: { borderColor: "#e0e3eb" },
      legend: { show: true, position: "top" },
      tooltip: { shared: true, x: { format: "yyyy-MM-dd" }, theme: "light" },
    });
    quantChartInstance.render();
  } catch (e) {
    container.textContent = "차트 오류: " + e.message;
  }
}

document.getElementById("quant-chart-load").addEventListener("click", loadQuantChart);
document.getElementById("refresh-market").addEventListener("click", loadQuantDashboard);

// ── 자동매매 ─────────────────────────────────────────────────────
async function loadAutoTradeStatus() {
  loadRiskStatus(); // 로그가 없어 아래에서 조기 return 되더라도 위험관리 상태는 항상 표시
  try {
    const s = await api("/api/auto-trade/status");
    document.getElementById("auto-trade-status").textContent =
      (s.running ? "🟢 실행 중" : "⭕ 정지") + (s.scheduler ? ` · ${s.scheduler}` : "") + (s.last_cycle_at ? ` · 마지막 사이클 ${s.last_cycle_at} UTC` : "");
    const el = document.getElementById("auto-trade-log");
    if (!s.log?.length) { el.innerHTML = "<div class='text-slate-400'>자동매매 로그가 없습니다.</div>"; return; }
    el.innerHTML = [...s.log].reverse().map(cycle => {
      const trades = (cycle.trades || []).map(t =>
        t.type === "risk" || t.status === "skipped"
          ? `<div class="ml-3 text-amber-400">⚠️ ${t.action === "buy" ? "매수" : "매도"} 생략 ${escHtml(t.name)} — ${escHtml(t.reason || "")}</div>`
          : `<div class="ml-3 text-slate-300">${t.action === "buy" ? "🟢매수" : "🔴매도"} ${escHtml(t.name)} ${fmt(t.quantity)}주 @${fmt(t.price)}</div>`
      ).join("");
      const risk = cycle.risk ? `<div class="ml-3 text-slate-500">위험관리: 당일 ${cycle.risk.day_pnl_pct ?? "-"}% · 주문 ${cycle.risk.orders_today ?? "-"}건${cycle.risk.halted ? ` · <span class="text-red-400">🛑 ${escHtml(cycle.risk.reason || "비상 정지")}</span>` : ""}</div>` : "";
      const sigs = (cycle.signals || []).map(sig =>
        `<div class="ml-3 text-slate-500">${escHtml(sig.name||sig.symbol)}: ${escHtml(_displayAction(sig.action))} (점수:${sig.score??"-"})</div>`
      ).join("");
      return `<div class="rounded-xl border border-white/10 bg-black/20 p-2 mb-1">
        <div class="font-semibold text-indigo-300">${escHtml(cycle.time)}${cycle.note ? ` <span class="text-red-400 font-normal">· ${escHtml(cycle.note)}</span>` : ""}</div>
        ${risk}${sigs}${trades ? '<div class="mt-1 font-medium text-xs">체결/생략:</div>' + trades : ""}
      </div>`;
    }).join("");
  } catch {}
}

async function loadRiskStatus() {
  try {
    const r = await api("/api/quant/risk/status");
    const L = r.limits || {};
    const pnlCls = r.day_pnl_pct == null ? "" : (r.day_pnl_pct >= 0 ? "text-emerald-400" : "text-red-400");
    const tile = (label, value, cls = "") => `<div class="rounded-lg p-2" style="background:var(--surf3);"><div style="color:var(--text-mute);">${label}</div><div class="font-bold ${cls}">${value}</div></div>`;
    document.getElementById("risk-kpis").innerHTML = [
      tile("비상 정지", r.kill_switch ? `<span class="text-red-400">🛑 ON</span>` : `<span class="text-emerald-400">OFF</span>`),
      tile("당일 손익", r.day_pnl_pct == null ? "-" : `${r.day_pnl_pct > 0 ? "+" : ""}${r.day_pnl_pct}% <span class="font-normal" style="color:var(--text-mute)">/ 한도 -${L.daily_loss_limit_pct}%</span>`, r.daily_loss_breached ? "text-red-400" : pnlCls),
      tile("당일 자동 주문", `${r.orders_today ?? 0}건 <span class="font-normal" style="color:var(--text-mute)">/ 최대 ${L.max_orders_per_day || "∞"}</span>`),
      tile("종목 비중 한도", `${L.max_position_pct || "∞"}%`),
      tile("중복 주문 쿨다운", `${L.cooldown_min || 0}분`),
    ].join("");
    document.getElementById("risk-note").textContent = r.kill_switch
      ? `정지 사유: ${r.halt_reason || "수동 비상 정지"} — 해제 후 자동매매를 다시 시작할 수 있습니다.`
      : `시작 자산 ${r.day_start_equity != null ? fmt(r.day_start_equity) + "원" : "-"} · 현재 자산 ${r.current_equity != null ? fmt(r.current_equity) + "원" : "-"} (${r.date})`;
    const g = r.execution_guidance;
    document.getElementById("risk-execution-detail").textContent = g
      ? `서버가 ${g.cycle_seconds}초 간격으로 판단합니다. 작업 지연·중단 시 더 늦어질 수 있습니다. 증권사 상주 감시 주문이 아니며, 판단 사이의 가격 변동이나 손절가 체결을 보장하지 않습니다. `
        + (g.cancel_open_after_min > 0 ? `게이트웨이 주문은 ${g.cancel_open_after_min}분 이상 미체결이면 취소를 요청합니다.` : "시간 경과에 따른 미체결 자동 취소는 꺼져 있습니다.")
      : "실행 주기와 비용 가정을 불러오지 못했습니다.";
    const example = g?.cost_example;
    document.getElementById("risk-cost-example").innerHTML = example ? `
      <p>공격 모드 ${g.aggressive_enabled ? "켜짐" : "꺼짐"} · 설정상 익절 +${escHtml(g.take_profit_pct)}% / 손절 −${escHtml(g.stop_loss_pct)}%의 비용 비교 (${escHtml(example.as_of)})</p>
      <p>${escHtml(example.basis)}</p>
      ${(example.scenarios || []).map(s => `<p>편도 슬리피지 ${escHtml(s.slippage_bps_per_side)}bp 가정: 익절 순수익 ${escHtml(s.net_take_profit_pct)}% · 손절 순손익 ${escHtml(s.net_stop_loss_pct)}% · 손익비 ${s.reward_risk_ratio == null ? "산출 불가(익절 순이익 없음)" : escHtml(s.reward_risk_ratio)} · 본전 승률 ${s.break_even_win_rate_pct == null ? "산출 불가" : escHtml(s.break_even_win_rate_pct) + "%"}</p>`).join("")}
      <p>익절·손절가 체결을 가정한 예시입니다. 갭 하락·미체결·수량별 절사는 반영하지 않으며 실제 승률 예측이 아닙니다.</p>` : "";
  } catch (e) { document.getElementById("risk-kpis").innerHTML = `<span class="text-red-400">${escHtml(e.message)}</span>`; }
}

document.getElementById("risk-kill-on").addEventListener("click", async () => {
  if (!confirm("자동매매를 중지하고 추적 중인 미체결 게이트웨이 주문의 취소를 요청합니다. 이미 전달된 주문의 체결이나 취소 성공을 보장하지 않으며 보유 종목을 자동 청산하지 않습니다. 계속할까요?")) return;
  try {
    const r = await api("/api/quant/risk/kill-switch", { method: "POST", body: { enabled: true, reason: "사용자 수동 비상 정지" } });
    const c = r.cancellation;
    const attention = c?.failed > 0 || c?.skipped > 0;
    setToast(`비상 정지 ON · 취소 요청 ${c?.requested || 0}건. 보유 종목은 유지됩니다.`
      + (attention ? " 취소 실패·미확인 주문은 증권사에서 확인하세요." : " 접수 여부가 불명확한 주문도 증권사에서 확인하세요."), attention ? "error" : "ok"); loadAutoTradeStatus();
  } catch (e) { setToast(e.message, "error"); }
});
document.getElementById("risk-kill-off").addEventListener("click", async () => {
  try {
    await api("/api/quant/risk/kill-switch", { method: "POST", body: { enabled: false } });
    setToast("비상 정지를 해제했습니다.", "ok"); loadAutoTradeStatus();
  } catch (e) { setToast(e.message, "error"); }
});

document.getElementById("auto-start").addEventListener("click", async () => {
  try {
    await api("/api/auto-trade/start", { method: "POST" });
    setToast("자동매매 시작", "ok");
    loadAutoTradeStatus();
  } catch (e) { setToast(e.message, "error"); }
});
document.getElementById("auto-stop").addEventListener("click", async () => {
  try {
    await api("/api/auto-trade/stop", { method: "POST" });
    setToast("자동매매 중지", "ok");
    loadAutoTradeStatus();
  } catch (e) { setToast(e.message, "error"); }
});
document.getElementById("auto-refresh").addEventListener("click", loadAutoTradeStatus);

// ── 백테스트 ─────────────────────────────────────────────────────
document.getElementById("bt-load").addEventListener("click", async () => {
  const symbol = document.getElementById("bt-symbol").value;
  const el = document.getElementById("bt-result");
  el.innerHTML = "<div class='text-slate-400'>분석 중 (10년치 데이터)...</div>";
  try {
    const data = await api(`/api/stocks/quant/indicators?symbol=${encodeURIComponent(symbol)}&period=10y`);
    if (data.error) { el.innerHTML = `<div class='text-red-400'>${escHtml(data.error)}</div>`; return; }
    const sig = data.signal || {};
    el.innerHTML = `
      <div class="rounded-xl border border-white/10 bg-black/20 p-4">
        <div class="font-semibold text-indigo-300 mb-2">${escHtml(symbol)} 10년 퀀트 분석</div>
        <div class="grid grid-cols-2 gap-2">
          <div>현재가: <span class="font-semibold">${fmt(data.current_price)}</span></div>
          <div>현재 RSI: <span class="font-semibold">${data.current_rsi?.toFixed(2) ?? "-"}</span></div>
          <div>AI 시그널: <span class="font-semibold ${sig.action === "매수" || sig.action === "강력 매수" ? "text-emerald-400" : sig.action === "매도" || sig.action === "강력 매도" ? "text-red-400" : "text-slate-300"}">${escHtml(_displayAction(sig.action))}</span></div>
          <div>시그널 점수: <span class="font-semibold">${sig.score ?? "-"}</span></div>
        </div>
        <div class="mt-3 text-xs text-slate-400">${(sig.reasons || []).map(r => "• " + escHtml(r)).join("<br>")}</div>
        <button type="button" class="btn-secondary text-xs mt-3" onclick='compareTrayAdd(${JSON.stringify({
          source: "퀀트 전략 분석", label: symbol,
          summary: `RSI ${data.current_rsi?.toFixed(1) ?? "-"} · 시그널 ${_displayAction(sig.action)} (점수 ${sig.score ?? "-"})`,
        }).replace(/'/g, "&#39;")})'>⚖️ 비교에 추가</button>
      </div>
    `;
    renderCompareTrayAll();
  } catch (e) { el.innerHTML = `<div class='text-red-400'>${escHtml(e.message)}</div>`; }
});

// B3 · 체결 시점 백테스트 (/api/quant/pipeline)
document.getElementById("bt-pipeline-run").addEventListener("click", async () => {
  const symbol = document.getElementById("bt-symbol").value;
  const entryMode = document.getElementById("bt-entry-mode")?.value || "close";
  const el = document.getElementById("bt-result");
  el.innerHTML = "<div class='text-slate-400'>전략 백테스트 중 (10년치)...</div>";
  try {
    const url = `/api/quant/pipeline?symbol=${encodeURIComponent(symbol)}`
      + `&period=10y&strategy=ma&entry_mode=${entryMode}&exit_mode=${entryMode}`;
    const d = await api(url);
    if (d.error) { el.innerHTML = `<div class='text-red-400'>${escHtml(d.error)}</div>`; return; }
    const up = (v) => (v ?? 0) >= 0 ? "text-emerald-400" : "text-red-400";
    el.innerHTML = `
      <div class="rounded-xl border border-white/10 bg-black/20 p-4">
        <div class="flex items-center gap-2 mb-2">
          <span class="font-semibold text-indigo-300">${escHtml(symbol)} · ${escHtml(d.strategy || "ma")}</span>
          <span class="text-xs px-2 py-0.5 rounded" style="background:var(--surf3);">체결: ${escHtml(entryMode === "open" ? "다음 봉 시가" : "그날 종가")}</span>
        </div>
        <div class="grid grid-cols-2 md:grid-cols-4 gap-2">
          <div>총 수익률: <span class="font-semibold ${up(d.total_return_pct)}">${(d.total_return_pct ?? 0).toFixed(2)}%</span></div>
          <div>비용 전: <span class="font-semibold">${(d.gross_return_pct ?? 0).toFixed(2)}%</span></div>
          <div>MDD: <span class="font-semibold text-red-400">${(d.mdd_pct ?? 0).toFixed(2)}%</span></div>
          <div>샤프: <span class="font-semibold">${(d.sharpe_ratio ?? 0).toFixed(3)}</span></div>
          <div>단순 보유: <span class="font-semibold ${up(d.buy_hold_return_pct)}">${(d.buy_hold_return_pct ?? 0).toFixed(2)}%</span></div>
          <div>거래 횟수: <span class="font-semibold">${d.trade_count ?? 0}</span></div>
          <div>승률: <span class="font-semibold">${(d.win_rate_pct ?? 0).toFixed(2)}%</span></div>
          <div>비용: <span class="font-semibold">${(d.cost_pct ?? 0).toFixed(3)}%</span></div>
        </div>
        <div class="text-xs mt-2" style="color:var(--text-mute);">
          entry_mode=${escHtml(d.entry_mode || entryMode)} · exit_mode=${escHtml(d.exit_mode || entryMode)}
        </div>
      </div>`;
  } catch (e) { el.innerHTML = `<div class='text-red-400'>${escHtml(e.message)}</div>`; }
});


export { loadAutoTradeStatus, loadQuantDashboard };