/* 로보 어드바이저: 자산배분 최적화, XAI 블록, 투자성향 설문, 목표 달성 시뮬레이션, 스크리닝, 패턴/멀티타임프레임, 모의 의사결정
 * app.html 인라인 스크립트에서 분리됨. 엔트리는 main.js */
import { api, getMe, setToast, escHtml, fmt, fmtPct, colorPct } from "/js/common.js";
import { tt } from "/js/core.js";

// ── 로보 어드바이저: 자산배분 최적화 ────────────────────────────────
const ALLOC_PROFILES = {
  conservative: { label: "보수적", 국내주식: 15, 해외주식: 10, 국내채권: 50, 대체자산: 5, 현금: 20 },
  moderate: { label: "중립", 국내주식: 30, 해외주식: 25, 국내채권: 30, 대체자산: 10, 현금: 5 },
  aggressive: { label: "공격적", 국내주식: 40, 해외주식: 35, 국내채권: 10, 대체자산: 10, 현금: 5 },
};
const ALLOC_COLORS = { 국내주식: "#2962ff", 해외주식: "#0097a7", 국내채권: "#089981", 대체자산: "#f59e0b", 현금: "#787b86" };
const ROBO_PICKS = {
  conservative: [
    { name: "삼성전자", code: "005930.KS", weight: 8, reason: "배당 안정성·시총 1위" },
    { name: "KB금융", code: "105560.KS", weight: 7, reason: "고배당·안정적 수익" },
    { name: "한국전력채", code: "BOND", weight: 50, reason: "국채 대신 우량 공기업채" },
  ],
  moderate: [
    { name: "삼성전자", code: "005930.KS", weight: 15, reason: "반도체 사이클 회복 수혜" },
    { name: "SK하이닉스", code: "000660.KS", weight: 10, reason: "HBM 수요 급증" },
    { name: "NAVER", code: "035420.KS", weight: 5, reason: "AI 플랫폼 성장성" },
    { name: "AAPL", code: "AAPL", weight: 10, reason: "빅테크 안정 수익" },
  ],
  aggressive: [
    { name: "SK하이닉스", code: "000660.KS", weight: 15, reason: "AI 반도체 최대 수혜" },
    { name: "NVDA", code: "NVDA", weight: 12, reason: "GPU AI 시장 독점" },
    { name: "TSLA", code: "TSLA", weight: 8, reason: "전기차 반등 모멘텀" },
    { name: "LG에너지솔", code: "373220.KS", weight: 5, reason: "2차전지 장기 성장" },
  ],
};

// ── XAI: SHAP 기여도 블록 렌더 (로보 추천 · 스크리닝 · 파이프라인 공용) ──
function renderXaiBlock(ex, { compact = false } = {}) {
  if (!ex) return "";
  const rows = (compact ? [...(ex.top_positive || []), ...(ex.top_negative || [])] : (ex.contributions || [])).slice(0, compact ? 4 : 12);
  const maxAbs = Math.max(0.0001, ...rows.map(r => Math.abs(r.contribution)));
  const bars = rows.map(r => {
    const pos = r.contribution >= 0;
    const w = Math.round(Math.abs(r.contribution) / maxAbs * 100);
    return `<div class="flex items-center gap-2 text-xs" style="line-height:1.2;">
      <span style="width:${compact ? 110 : 150}px;flex:none;color:var(--text-dim);" title="${escHtml(r.interpretation || "")}">${escHtml(r.label || r.feature)} <span style="color:var(--text-mute);">${escHtml(r.value_text || "")}</span></span>
      <div style="flex:1;height:8px;background:var(--surf3);border-radius:4px;overflow:hidden;position:relative;">
        <div style="width:${w}%;height:100%;background:${pos ? "var(--green)" : "var(--red)"};"></div>
      </div>
      <span style="width:52px;flex:none;text-align:right;color:${pos ? "var(--green)" : "var(--red)"};">${r.contribution >= 0 ? "+" : ""}${Number(r.contribution).toFixed(2)}</span>
    </div>`;
  }).join("");
  const sigCls = ex.signal === 1 ? "badge-buy" : ex.signal === -1 ? "badge-sell" : "badge-hold";
  return `<div class="mt-2 rounded-lg p-2" style="background:var(--surf2);border:1px solid var(--border);">
    <div class="flex items-center justify-between mb-1">
      <span class="text-xs font-semibold">🧠 ${tt("AI 판단 근거 (XAI)", "SHAP 기여도: 각 지표가 모델의 매수/관망/매도 판단을 얼마나 밀어 올렸는지(+)/끌어내렸는지(−)", "shap")}</span>
      <span class="${sigCls}" style="font-size:11px;">${escHtml(ex.signal_label)} ${ex.probability_pct}%</span>
    </div>
    ${ex.quality_warning ? `<p class="text-xs mb-1 px-2 py-1 rounded" style="background:rgba(242,54,69,.08);color:var(--red);border:1px solid rgba(242,54,69,.25);">⚠ 모델 성능 기준선 미달 — ${escHtml(ex.quality_warning)}</p>` : ""}
    <p class="text-xs mb-2" style="color:var(--text-dim);">${escHtml((ex.summary || "").replace(/^⚠ [^ ]*.*?참고용입니다\. /, ""))}</p>
    <div class="space-y-1">${bars}</div>
    ${compact ? "" : `<p class="text-xs mt-2" style="color:var(--text-mute);">${escHtml(ex.method || "")} · ${escHtml(ex.disclaimer || "")}</p>`}
  </div>`;
}

document.getElementById("robo-optimize-btn").addEventListener("click", async () => {
  const profile = document.getElementById("robo-risk").value;
  const horizon = parseInt(document.getElementById("robo-horizon").value);
  const amount = parseInt(document.getElementById("robo-amount").value) || 5000;
  const optimizeBtn = document.getElementById("robo-optimize-btn");
  const originalBtnText = optimizeBtn.textContent;
  // 유니버스 전체(~30종목) 스캔 + AI 학습이라 수 초~수십 초 걸릴 수 있어 로딩 표시 필수
  optimizeBtn.disabled = true;
  optimizeBtn.textContent = "AI 분석 중... (최대 30초 소요)";
  try {
    const data = await api("/api/ml/robo/allocation", {
      method: "POST",
      body: { risk_profile: profile, horizon_years: horizon, amount_manwon: amount },
    });
    const allocEntries = Object.entries(data.allocations || {});
    document.getElementById("robo-alloc-cards").innerHTML = allocEntries.map(([cls, pct]) => `
      <div class="card" style="padding:14px; text-align:center;">
        <div class="text-xs mb-1" style="color:var(--text-mute);">${cls}</div>
        <div style="font-size:22px; font-weight:700; color:${ALLOC_COLORS[cls] || "var(--accent)"};">${pct}%</div>
        <div class="text-xs mt-1" style="color:var(--text-dim);">${Math.round(amount * pct / 100).toLocaleString()}만원</div>
      </div>
    `).join("");
    document.getElementById("robo-alloc-bar").innerHTML = allocEntries.map(([cls, pct]) =>
      `<div style="width:${pct}%;background:${ALLOC_COLORS[cls] || "#2962ff"};transition:width .4s;" title="${cls} ${pct}%"></div>`
    ).join("");
    document.getElementById("robo-alloc-legend").innerHTML = allocEntries.map(([cls, pct]) =>
      `<span style="display:flex;align-items:center;gap:4px;"><span style="width:10px;height:10px;border-radius:2px;background:${ALLOC_COLORS[cls] || "#2962ff"};display:inline-block;"></span>${cls} ${pct}%</span>`
    ).join("");

    const picks = data.stock_picks || [];
    document.getElementById("robo-stock-picks").innerHTML = picks.map(p => `
      <div class="card" style="padding:14px;">
        <div class="flex items-center justify-between mb-1">
          <span class="font-semibold text-sm">${escHtml(p.name)}</span>
          <span class="text-xs font-bold" style="color:var(--accent);">${p.weight}%</span>
        </div>
        <div class="text-xs" style="color:var(--text-mute);">${escHtml(p.reason)}</div>
        <div class="text-xs mt-1" style="color:var(--text-dim);">${Math.round(amount * p.weight / 100).toLocaleString()}만원</div>
        ${renderXaiBlock(p.ai_prediction?.explanation, { compact: true })}
      </div>
    `).join("");

    const rows = data.projections || [];
    document.getElementById("robo-perf-table").innerHTML = `
      <table><thead><tr><th>기간</th><th style="text-align:right;">예상 수익률</th><th style="text-align:right;">예상 수익 (만원)</th><th style="text-align:right;">최대낙폭 (MDD)</th></tr></thead>
      <tbody>
        ${rows.map(r => `<tr><td style="color:var(--text-dim);">${r.years}년</td><td style="text-align:right;color:var(--green);font-weight:600;">${r.expected_return_pct >= 0 ? "+" : ""}${r.expected_return_pct}%</td><td style="text-align:right;font-weight:600;">${r.expected_profit_manwon.toLocaleString()}만원</td><td style="text-align:right;color:var(--red);">${r.expected_mdd_pct}%</td></tr>`).join("")}
      </tbody></table>
      <p class="text-xs mt-2" style="color:var(--text-mute);">※ 시장 데이터 기반 추정치이며 실제 수익을 보장하지 않습니다.</p>
    `;
    document.getElementById("robo-alloc-result").classList.remove("hidden");
    // 목표 달성 시뮬레이션 기본값: 최적화 포트폴리오의 기대수익·변동성 (주식 바스켓 비중 반영)
    const opt = data.optimization || {};
    const stockBucket = ((data.allocations?.["국내주식"] || 0) + (data.allocations?.["해외주식"] || 0)) / 100;
    const mu = (opt.expected_return_pct || 0) * stockBucket + 2.5 * (1 - stockBucket);
    const sigma = (opt.expected_volatility_pct || 0) * stockBucket;
    document.getElementById("gs-mu").value = mu.toFixed(1);
    document.getElementById("gs-sigma").value = sigma.toFixed(1);
    lastGoalSim = null; document.getElementById("gs-result").innerHTML = "";
  } catch (e) {
    setToast("포트폴리오 최적화 오류: " + e.message, "error");
  } finally {
    optimizeBtn.disabled = false;
    optimizeBtn.textContent = originalBtnText;
  }
});


// ── 로보 어드바이저: 투자성향 진단 설문 ─────────────────────────────
let rpQuestions = null;
async function loadRiskQuestions() {
  if (rpQuestions) return rpQuestions;
  const r = await api("/api/ml/robo/questions");
  rpQuestions = r.questions;
  document.getElementById("rp-form").innerHTML = rpQuestions.map((q, qi) => `
    <div class="rounded-lg p-3" style="background:var(--surf2);border:1px solid var(--border);">
      <div class="text-sm font-semibold mb-2">Q${qi + 1}. ${escHtml(q.text)}</div>
      <div class="flex flex-wrap gap-2">${q.options.map((o, oi) => `<label class="text-xs flex items-center gap-1 px-2 py-1 rounded cursor-pointer" style="border:1px solid var(--border);"><input type="radio" name="rp-${q.id}" value="${oi}" /> ${escHtml(o.label)}</label>`).join("")}</div>
    </div>`).join("") + `<div class="flex gap-2"><button id="rp-submit" class="btn-primary text-xs">진단하기</button><span class="text-xs self-center" style="color:var(--text-mute);">모든 문항에 답해야 진단됩니다.</span></div>`;
  document.getElementById("rp-submit").addEventListener("click", submitRiskProfile);
  return rpQuestions;
}
async function submitRiskProfile() {
  const answers = {};
  for (const q of rpQuestions) { const v = document.querySelector(`input[name="rp-${q.id}"]:checked`); if (v) answers[q.id] = Number(v.value); }
  try {
    const r = await api("/api/ml/robo/risk-profile", { method: "POST", body: { answers } });
    const cls = r.risk_profile === "aggressive" ? "badge-sell" : r.risk_profile === "moderate" ? "badge-hold" : "badge-buy";
    document.getElementById("rp-result").innerHTML = `
      <div class="flex flex-wrap items-center gap-2 mb-1"><span class="${cls}" style="font-size:14px;">${escHtml(r.level)}</span><span class="text-xs" style="color:var(--text-mute);">점수 ${r.score} / ${r.max_score} · 시스템 프로파일 <b>${escHtml(r.risk_profile)}</b> (자산배분 성향에 반영됨)</span></div>
      <p class="text-xs" style="color:var(--text-dim);">${escHtml(r.description)}</p>
      <div class="flex gap-1 mt-2">${r.scale.map(sc => `<span class="text-xs px-2 py-0.5 rounded" style="background:${sc.level === r.level ? "var(--accent)" : "var(--surf3)"};color:${sc.level === r.level ? "#fff" : "var(--text-mute)"};">${escHtml(sc.level)} ${sc.min}+</span>`).join("")}</div>`;
    document.getElementById("robo-risk").value = r.risk_profile;
    document.getElementById("rp-form").classList.add("hidden"); document.getElementById("rp-toggle").textContent = "설문 다시 하기";
    try { localStorage.setItem("robo_risk_profile", JSON.stringify({ level: r.level, risk_profile: r.risk_profile, score: r.score })); } catch (_) { }
    setToast(`투자성향: ${r.level} → 자산배분 성향을 ${r.risk_profile}로 설정했습니다.`, "ok");
  } catch (e) { setToast(e.message, "error"); }
}
document.getElementById("rp-toggle")?.addEventListener("click", async () => {
  await loadRiskQuestions();
  const f = document.getElementById("rp-form"); f.classList.toggle("hidden");
  document.getElementById("rp-toggle").textContent = f.classList.contains("hidden") ? "설문 펼치기" : "설문 접기";
});
(() => { try { const saved = JSON.parse(localStorage.getItem("robo_risk_profile") || "null"); if (saved) { document.getElementById("rp-result").innerHTML = `<span class="text-xs" style="color:var(--text-mute);">최근 진단: <b>${escHtml(saved.level)}</b> (${saved.score}점) — 자산배분 성향 ${escHtml(saved.risk_profile)}</span>`; document.getElementById("robo-risk").value = saved.risk_profile; } } catch (_) { } })();

// ── 로보 어드바이저: 목표 수익률 달성 확률 시뮬레이션 ────────────────
let lastGoalSim = null, goalChart = null;
async function runGoalSimulation() {
  const body = {
    amount_manwon: parseInt(document.getElementById("robo-amount").value) || 5000,
    horizon_years: parseInt(document.getElementById("robo-horizon").value) || 3,
    target_return_pct: Number(document.getElementById("gs-target").value || 8),
    monthly_contribution_manwon: Number(document.getElementById("gs-monthly").value || 0),
    expected_return_pct: Number(document.getElementById("gs-mu").value || 7),
    expected_volatility_pct: Number(document.getElementById("gs-sigma").value || 12),
  };
  const el = document.getElementById("gs-result");
  el.innerHTML = `<div class="text-xs" style="color:var(--text-mute);">3,000개 경로 시뮬레이션 중…</div>`;
  try {
    const r = await api("/api/ml/robo/goal-simulation", { method: "POST", body });
    lastGoalSim = r;
    const pc = r.probability_pct, color = pc >= 80 ? "var(--green)" : pc >= 50 ? "var(--accent)" : "var(--red)";
    el.innerHTML = `
      <div class="grid grid-cols-2 md:grid-cols-5 gap-3 mb-3">
        ${[["목표 달성 확률", `<span style="color:${color}">${pc}%</span>`], ["목표 금액", `${fmt(r.target_value_manwon)}만원`], ["총 투입 원금", `${fmt(r.invested_manwon)}만원`], ["중앙값(50%) 최종자산", `${fmt(r.percentiles_manwon.p50)}만원 (${r.median_return_pct >= 0 ? "+" : ""}${r.median_return_pct}%)`], ["원금 손실 확률", `${r.loss_probability_pct}%`]]
        .map(([l, v]) => `<div class="card" style="padding:12px;text-align:center;"><div class="text-xs mb-1" style="color:var(--text-mute);">${l}</div><div style="font-size:17px;font-weight:700;">${v}</div></div>`).join("")}
      </div>
      <div class="text-sm mb-2"><b>${escHtml(r.verdict)}</b> · 목표 달성에 필요한 연수익률 ${r.required_annual_return_pct}% vs 포트폴리오 기대 ${r.inputs.expected_return_pct}% (변동성 ${r.inputs.expected_volatility_pct}%)</div>
      <div id="gs-chart"></div>
      <table class="mt-2"><thead><tr><th>백분위</th><th style="text-align:right">5% (비관)</th><th style="text-align:right">25%</th><th style="text-align:right">50% (중앙)</th><th style="text-align:right">75%</th><th style="text-align:right">95% (낙관)</th></tr></thead>
      <tbody><tr><td>${r.inputs.horizon_years}년 후 자산 (만원)</td>${["p5", "p25", "p50", "p75", "p95"].map(k => `<td style="text-align:right;${r.percentiles_manwon[k] >= r.target_value_manwon ? "color:var(--green);font-weight:600" : ""}">${fmt(r.percentiles_manwon[k])}</td>`).join("")}</tr></tbody></table>
      <p class="text-xs mt-2" style="color:var(--text-mute);">${escHtml(r.disclaimer)} 초록색은 목표 금액 이상인 구간입니다.</p>`;
    if (window.ApexCharts) {
      const opts = {
        chart: { type: "line", height: 240, toolbar: { show: false }, background: "transparent" },
        theme: { mode: document.documentElement.dataset.theme === "light" ? "light" : "dark" },
        series: [
          { name: "낙관 (95%)", data: r.curves.p95 }, { name: "중앙 (50%)", data: r.curves.p50 }, { name: "비관 (5%)", data: r.curves.p5 },
          { name: "목표 금액", data: r.curve_years.map((y, i) => i === r.curve_years.length - 1 ? r.target_value_manwon : null) },
        ],
        xaxis: { categories: r.curve_years.map(y => `${y}년`), tickAmount: 8 }, yaxis: { labels: { formatter: v => `${fmt(v)}만` } },
        stroke: { width: [2, 3, 2, 0], dashArray: [4, 0, 4, 0] }, markers: { size: [0, 0, 0, 6] }, colors: ["#089981", "#2962ff", "#f23645", "#f59e0b"],
        dataLabels: { enabled: false }, legend: { position: "top" }, tooltip: { y: { formatter: v => v == null ? "" : `${fmt(v)}만원` } }
      };
      if (goalChart) goalChart.destroy();
      goalChart = new ApexCharts(document.getElementById("gs-chart"), opts); goalChart.render();
    }
  } catch (e) { el.innerHTML = `<span class="text-red-500 text-sm">${escHtml(e.message)}</span>`; }
}
document.getElementById("gs-run")?.addEventListener("click", runGoalSimulation);
// ── 로보 어드바이저: 종목 스크리닝 ──────────────────────────────────
async function loadRoboScreening() {
  const signal = document.getElementById("screen-signal")?.value || "all";
  const model = document.getElementById("screen-model")?.value || "lightgbm";
  const confidence = document.getElementById("screen-confidence")?.value || "65";
  try {
    const { signals } = await api(`/api/stocks/signals?signal=${encodeURIComponent(signal)}&model=${encodeURIComponent(model)}&min_confidence=${encodeURIComponent(confidence)}`);
    renderScreenSignalCards(signals);
    renderScreenTable(signals);
  } catch { renderScreenSignalCards([]); }
}

function renderScreenSignalCards(signals) {
  const el = document.getElementById("screen-signal-cards");
  if (!el) return;
  if (!signals?.length) { el.innerHTML = `<div class="text-slate-400 col-span-5">시그널 데이터를 불러올 수 없습니다.</div>`; return; }
  el.innerHTML = signals.map(s => {
    const cls = s.signal === "BUY" ? "var(--green)" : s.signal === "SELL" ? "var(--red)" : "var(--text-mute)";
    return `<div class="card" style="padding:12px; text-align:center;">
      <div class="font-semibold" style="font-size:12px;">${escHtml(s.name || s.symbol)}</div>
      <div style="font-size:18px;font-weight:700;color:${cls};margin:6px 0;">${s.signal}</div>
      <div style="font-size:11px;color:var(--text-mute);">RSI ${s.rsi?.toFixed(0) ?? "--"}</div>
      <div style="font-size:11px;color:${s.change_pct >= 0 ? "var(--green)" : "var(--red)"};">${s.change_pct >= 0 ? "+" : ""}${s.change_pct?.toFixed(2) ?? "--"}%</div>
    </div>`;
  }).join("");
}

function renderScreenTable(signals) {
  const el = document.getElementById("screen-result-table");
  if (!el) return;
  if (!signals?.length) { el.innerHTML = `<p class="text-slate-400 text-sm">조회된 종목이 없습니다.</p>`; return; }
  el.innerHTML = `<table>
    <thead><tr><th>종목명</th><th style="text-align:right;">현재가</th><th style="text-align:right;">등락률</th><th style="text-align:right;">RSI</th><th>AI 신호</th><th>패턴 근거</th><th>XAI</th></tr></thead>
    <tbody>${signals.map(s => {
    const pct = s.change_pct ?? 0;
    const sigClass = s.signal === "BUY" ? "badge-buy" : s.signal === "SELL" ? "badge-sell" : "badge-hold";
    return `<tr>
        <td style="font-weight:600;">${escHtml(s.name || s.symbol)}</td>
        <td style="text-align:right;">${fmt(s.price)}</td>
        <td style="text-align:right;color:${pct >= 0 ? "var(--green)" : "var(--red)"};">${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%</td>
        <td style="text-align:right;">${s.rsi?.toFixed(1) ?? "--"}</td>
        <td><span class="${sigClass}">${s.signal}</span></td>
        <td style="font-size:11px;color:var(--text-mute);">${escHtml(s.reason || "계산된 패턴 신호")}${s.xai ? `<div style="color:var(--text-dim);margin-top:2px;">🧠 ${escHtml(s.xai.signal_label)} ${s.xai.probability_pct}% — ${escHtml((s.xai.top_positive?.[0]?.label) || "")}</div>` : ""}</td>
        <td><button class="btn-secondary text-xs" onclick="showScreenXai('${escHtml(s.symbol)}')" title="LightGBM SHAP 기여도로 판단 근거 설명">🧠 설명</button></td>
      </tr>`;
  }).join("")}</tbody>
  </table>
  <div id="screen-xai-panel" class="mt-3"></div>`;
}

async function showScreenXai(symbol) {
  const panel = document.getElementById("screen-xai-panel");
  if (!panel) return;
  panel.innerHTML = `<div class="text-xs" style="color:var(--text-mute);">🧠 ${escHtml(symbol)} LightGBM 학습 + SHAP 계산 중… (최초 1회 수 초 소요, 3시간 캐시)</div>`;
  try {
    const r = await api(`/api/ml/explain?symbol=${encodeURIComponent(symbol)}`);
    const pr = r.prediction || {};
    panel.innerHTML = `<div class="card" style="padding:14px;">
      <div class="flex items-center justify-between mb-1">
        <h3 class="font-semibold text-sm">🧠 ${escHtml(r.name)} <span class="text-xs font-mono" style="color:var(--text-mute);">${escHtml(r.symbol)}</span> — AI 판단 근거</h3>
        <span class="text-xs" style="color:var(--text-mute);">5일 예측 ${pr.pred_5d_return_pct ?? "-"}% · 모델 ${escHtml(pr.model || "")} · 신뢰도 ${pr.confidence ?? "-"}</span>
      </div>
      ${r.explanation ? renderXaiBlock(r.explanation) : `<p class="text-xs" style="color:var(--text-mute);">이 종목은 LightGBM 분류를 학습할 수 없어 설명을 제공하지 못했습니다.</p>`}
    </div>`;
  } catch (e) { panel.innerHTML = `<span class="text-xs text-red-500">${escHtml(e.message)}</span>`; }
}
window.showScreenXai = showScreenXai;

document.getElementById("screen-run-btn").addEventListener("click", loadRoboScreening);


// ── 로보 어드바이저: 차트 패턴 · 지지/저항 · 멀티타임프레임 ─────────────
async function loadPatternAnalysis() {
  const symbol = document.getElementById("pt-symbol").value.trim() || "005930.KS";
  const box = (id, html) => { const el = document.getElementById(id); el.innerHTML = html; el.classList.remove("hidden"); };
  box("pt-mtf", `<div class="text-sm" style="color:var(--text-mute);">분봉·일봉·주봉 데이터 수집 및 계산 중…</div>`);
  try {
    const [mtf, pat] = await Promise.all([
      api(`/api/stocks/mtf-signal?symbol=${encodeURIComponent(symbol)}`),
      api(`/api/stocks/patterns?symbol=${encodeURIComponent(symbol)}`),
    ]);
    const actCls = mtf.action.includes("매수") ? "badge-buy" : mtf.action.includes("매도") ? "badge-sell" : "badge-hold";
    box("pt-mtf", `
      <div class="flex flex-wrap items-center gap-3 mb-3">
        <h3 class="font-semibold text-sm">📐 멀티타임프레임 종합 신호 — ${escHtml(symbol)}</h3>
        <span class="${actCls}" style="font-size:14px;">${escHtml(mtf.action)}</span>
        <span class="text-xs" style="color:var(--text-dim);">종합 점수 ${mtf.composite} · ${tt("신뢰도", "타임프레임 방향 일치도(50%) + 점수 크기(50%)", "confidence")} <b>${mtf.confidence}%</b> · 방향 일치 ${mtf.agreement}%</span>
      </div>
      <table><thead><tr><th>타임프레임</th><th style="text-align:right">가중치</th><th style="text-align:right">점수</th><th style="text-align:right">RSI</th><th style="text-align:right">MA5 / MA20</th><th>근거</th><th>기준 시점</th></tr></thead><tbody>${mtf.timeframes.map(t => t.error ? `<tr><td>${escHtml(t.label)}</td><td colspan="6" class="text-xs" style="color:var(--text-mute)">${escHtml(t.error)}</td></tr>` :
      `<tr><td>${escHtml(t.label)}</td><td style="text-align:right">${Math.round(t.weight * 100)}%</td><td style="text-align:right;font-weight:700;color:${t.score > 0 ? "var(--green)" : t.score < 0 ? "var(--red)" : "var(--text-mute)"}">${t.score > 0 ? "+" : ""}${t.score}</td><td style="text-align:right">${t.rsi}</td><td style="text-align:right">${fmt(t.ma5)} / ${fmt(t.ma20)}</td><td class="text-xs" style="color:var(--text-dim)">${t.reasons.map(escHtml).join(" · ")}</td><td class="text-xs" style="color:var(--text-mute)">${escHtml(t.as_of)}</td></tr>`).join("")}</tbody></table>
      <p class="text-xs mt-2" style="color:var(--text-mute);">${escHtml(mtf.disclaimer)}</p>`);
    const dirBadge = (d) => d === "bullish" ? `<span class="badge-buy">상승</span>` : d === "bearish" ? `<span class="badge-sell">하락</span>` : `<span class="badge-hold">중립</span>`;
    box("pt-patterns", `<h3 class="font-semibold text-sm mb-2">🕯️ 캔들 패턴 (최근 5봉) · 패턴 점수 ${pat.pattern_score} (${escHtml(pat.pattern_bias)})</h3>${pat.patterns.length ? `<table><thead><tr><th>일자</th><th>패턴</th><th>방향</th><th>해설</th></tr></thead><tbody>${pat.patterns.map(p => `<tr><td class="text-xs">${p.date}${p.bars_ago === 0 ? " <b>(최신)</b>" : ""}</td><td style="font-weight:600">${escHtml(p.name)}</td><td>${dirBadge(p.direction)}</td><td class="text-xs" style="color:var(--text-dim)">${escHtml(p.description)}</td></tr>`).join("")}</tbody></table>`
      : `<p class="text-sm" style="color:var(--text-mute)">최근 5봉에서 뚜렷한 캔들 패턴이 없습니다.</p>`}`);
    const sr = pat.support_resistance;
    box("pt-sr", `<h3 class="font-semibold text-sm mb-2">📏 지지·저항선 (최근 ${sr.lookback_bars}봉 피벗 군집) · 현재가 ${fmt(sr.last_price)}</h3>
      <div class="flex gap-3 text-xs mb-2">${sr.nearest_resistance ? `<span class="badge-sell">가장 가까운 저항 ${fmt(sr.nearest_resistance.price)} (${sr.nearest_resistance.distance_pct > 0 ? "+" : ""}${sr.nearest_resistance.distance_pct}%)</span>` : ""}${sr.nearest_support ? `<span class="badge-buy">가장 가까운 지지 ${fmt(sr.nearest_support.price)} (${sr.nearest_support.distance_pct}%)</span>` : ""}</div>
      ${sr.levels.length ? `<table><thead><tr><th>가격대</th><th>구분</th><th style="text-align:right">터치</th><th>강도</th><th style="text-align:right">현재가 대비</th></tr></thead><tbody>${sr.levels.map(l => `<tr><td style="font-weight:600">${fmt(l.price)}</td><td>${l.type === "support" ? '<span class="badge-buy">지지</span>' : '<span class="badge-sell">저항</span>'}</td><td style="text-align:right">${l.touches}회</td><td>${l.strength}</td><td style="text-align:right;color:${l.distance_pct >= 0 ? "var(--green)" : "var(--red)"}">${l.distance_pct > 0 ? "+" : ""}${l.distance_pct}%</td></tr>`).join("")}</tbody></table>` : `<p class="text-sm" style="color:var(--text-mute)">레벨을 찾지 못했습니다.</p>`}`);
    box("pt-breakouts", `<h3 class="font-semibold text-sm mb-2">🚀 돌파·크로스 이벤트 (${pat.as_of} 기준)</h3>${pat.breakouts.length ? `<div class="flex flex-wrap gap-2">${pat.breakouts.map(e => `<div class="rounded-lg p-2 text-xs" style="background:var(--surf2);border:1px solid var(--border);min-width:220px;">${dirBadge(e.direction)} <b>${escHtml(e.name)}</b>${e.confirmed ? ' <span style="color:var(--green)">✔ 확인</span>' : ''}<div style="color:var(--text-dim);margin-top:2px;">${escHtml(e.detail || "")}</div></div>`).join("")}</div>`
      : `<p class="text-sm" style="color:var(--text-mute)">현재 봉에서 돌파·크로스 이벤트가 없습니다.</p>`}`);
  } catch (e) { box("pt-mtf", `<span class="text-red-500 text-sm">${escHtml(e.message)}</span>`); }
}
document.getElementById("pt-run")?.addEventListener("click", loadPatternAnalysis);
document.getElementById("pt-symbol")?.addEventListener("keydown", e => { if (e.key === "Enter") loadPatternAnalysis(); });
// ── 로보 어드바이저: 모의 투자 의사결정 ─────────────────────────────
async function loadRoboDecision() {
  try {
    const data = await api("/api/quant/auto/status");
    const el = document.getElementById("robo-decision-status");
    if (el) el.textContent = data.running ? "🟢 실행 중" : "⚫ 중지됨";
    renderRoboDecisionLog(data.logs || []);
    renderRoboRationale(data.signals || []);
  } catch { }

  // 🆕 QFRS 성과 지표 로드
  loadRoboPerformanceMetrics();
}

function renderRoboDecisionLog(logs) {
  const el = document.getElementById("robo-decision-log");
  if (!el) return;
  el.innerHTML = logs.length ? logs.map(l => `
    <div class="rounded p-2" style="background:var(--surf2);border:1px solid var(--border);">
      <span style="color:var(--text-mute);">${escHtml(l.time || "")}</span>
      <span style="margin-left:8px;">${escHtml(l.message || "")}</span>
    </div>`).join("") : `<div style="color:var(--text-mute);">AI 의사결정 로그가 없습니다. 시작 버튼을 눌러 실행하세요.</div>`;
}

function renderRoboRationale(signals) {
  const el = document.getElementById("robo-rationale");
  if (!el) return;
  if (!signals?.length) { el.innerHTML = `<div class="col-span-3 text-sm" style="color:var(--text-mute);">실행 후 판단 근거가 표시됩니다.</div>`; return; }
  el.innerHTML = signals.slice(0, 3).map(s => `
    <div class="card" style="padding:14px;">
      <div class="font-semibold text-sm mb-1">${escHtml(s.name || s.symbol)}</div>
      <div class="text-xs mb-2" style="color:var(--text-mute);">신호 점수 ${Number(s.score ?? 0).toFixed(1)} | ${s.signal}</div>
      <div class="text-xs" style="color:var(--text-dim);">${s.signal === "BUY" ? "📈 매수 신호: 과매도 구간 진입, 반등 기대" : s.signal === "SELL" ? "📉 매도 신호: 과매수, 차익 실현 권고" : "⏸ 홀드: 추세 확인 중, 관망 권고"}</div>
    </div>`).join("");
}

document.getElementById("robo-decision-start").addEventListener("click", async () => {
  try { await api("/api/quant/auto/start", { method: "POST" }); setToast("AI 의사결정 시작됨", "ok"); loadRoboDecision(); } catch (e) { setToast(e.message, "error"); }
});
document.getElementById("robo-decision-stop").addEventListener("click", async () => {
  try { await api("/api/quant/auto/stop", { method: "POST" }); setToast("중지됨", "ok"); loadRoboDecision(); } catch (e) { setToast(e.message, "error"); }
});
document.getElementById("robo-decision-refresh").addEventListener("click", loadRoboDecision)

document.getElementById("robo-metrics-simulate")?.addEventListener("click", async () => {
  if (!confirm("기존 스냅샷을 지우고 15일치 데모 데이터를 생성합니다. 계속할까요?")) return;
  try {
    await api("/api/paper/performance/simulate", { method: "POST", body: { days: 15, seed: 42 } });
    setToast("데모 데이터 생성 완료", "ok");
    loadRoboPerformanceMetrics();
  } catch (e) {
    setToast("실패: " + e.message, "error");
  }
});;


// ═══════════════════════════════════════════════════════════
// 🆕 QFRS 성과 지표 (Bailey & Lopez de Prado, 2014)
// ═══════════════════════════════════════════════════════════
let _roboMetricsChart = null;

async function loadRoboPerformanceMetrics() {
  const cardsEl = document.getElementById("robo-metrics-cards");
  const chartEl = document.getElementById("robo-metrics-chart");
  const tableEl = document.getElementById("robo-metrics-table");   // 🆕
  if (!cardsEl) return;

  cardsEl.innerHTML = `<div class="text-xs col-span-4" style="color:var(--text-mute);">지표 계산 중...</div>`;
  if (chartEl) chartEl.innerHTML = "";
  if (tableEl) tableEl.innerHTML = "";                             // 🆕

  try {
    const data = await api("/api/paper/performance/metrics");

    if (data.status === "insufficient_data") {
      cardsEl.innerHTML = `
        <div class="text-xs col-span-4" style="color:var(--text-mute);">
          📊 ${escHtml(data.message)} (현재 스냅샷: ${data.snapshot_count}개)
        </div>`;
      return;
    }

    const m = data.metrics || {};
    const pct = (v) => v == null ? "-" : (v * 100).toFixed(2) + "%";
    const num = (v) => v == null ? "-" : Number(v).toFixed(3);
    const trColor = (data.total_return || 0) >= 0 ? "var(--green)" : "var(--red)";
    const dsrColor = (m.dsr || 0) >= 0.95 ? "var(--green)" : "var(--text)";

    // ── 요약 카드 4개 ──────────────────────────────────
    cardsEl.innerHTML = `
      <div class="card" style="padding:12px;text-align:center;">
        <div class="text-xs" style="color:var(--text-mute);">누적 수익률</div>
        <div class="font-bold" style="color:${trColor}">${pct(data.total_return)}</div>
      </div>
      <div class="card" style="padding:12px;text-align:center;">
        <div class="text-xs" style="color:var(--text-mute);">MDD</div>
        <div class="font-bold" style="color:var(--red)">${pct(m.mdd)}</div>
      </div>
      <div class="card" style="padding:12px;text-align:center;">
        <div class="text-xs" style="color:var(--text-mute);">Sharpe</div>
        <div class="font-bold">${num(m.sharpe_ratio)}</div>
      </div>
      <div class="card" style="padding:12px;text-align:center;">
        <div class="text-xs" style="color:var(--text-mute);">DSR</div>
        <div class="font-bold" style="color:${dsrColor}">${m.dsr == null ? "-" : (m.dsr * 100).toFixed(1) + "%"}</div>
      </div>`;

    // ── 차트 (스타일 그대로 유지) ─────────────────────
    if (chartEl && Array.isArray(data.equity_curve) && data.equity_curve.length > 1) {
      if (_roboMetricsChart) { _roboMetricsChart.destroy(); _roboMetricsChart = null; }

      const rawDates = Array.isArray(data.snap_dates) ? data.snap_dates : [];
      const labels = data.equity_curve.map((_, i) => {
        const d = rawDates[i];
        return d ? d.slice(5) : `#${i + 1}`;
      });

      const series = [{
        name: "총자산",
        data: data.equity_curve.map((v, i) => ({ x: labels[i], y: v })),
      }];

      _roboMetricsChart = new ApexCharts(chartEl, {
        chart: {
          type: "area", height: 300,
          toolbar: { show: false }, background: "transparent",
          fontFamily: "Pretendard, sans-serif",
        },
        series,
        xaxis: {
          type: "category",
          labels: {
            rotate: -45,
            rotateAlways: false,
            style: { fontSize: "10px", colors: "#888" },
          },
          tickAmount: Math.min(8, labels.length),
        },
        yaxis: {
          labels: {
            formatter: (v) => v == null ? "" : (v / 10000).toFixed(1) + "만",
            style: { fontSize: "11px", colors: "#888" },
          },
        },
        colors: ["#2962ff"],
        stroke: { curve: "smooth", width: 2 },
        fill: {
          type: "gradient",
          gradient: { shadeIntensity: 0.4, opacityFrom: 0.35, opacityTo: 0.05 },
        },
        markers: { size: 0, hover: { size: 5 } },
        dataLabels: { enabled: false },
        grid: { borderColor: "rgba(255,255,255,0.06)", strokeDashArray: 3 },
        tooltip: {
          x: { formatter: (val) => `📅 ${val}` },
          y: { formatter: (v) => v == null ? "-" : `${(v / 10000).toFixed(1)}만원` },
        },
      });
      _roboMetricsChart.render();
    }

    // ── 🆕 상세 지표 테이블 ───────────────────────────
    if (tableEl) {
      const rows = [
        {
          name: "누적 수익률",
          value: pct(data.total_return),
          tone: (data.total_return || 0) >= 0 ? "up" : "down",
          desc: "전체 기간 누적 수익률 (스냅샷 시작 대비)",
          ref: "기본 지표",
        },
        {
          name: "MDD (Maximum Drawdown)",
          value: pct(m.mdd),
          tone: "down",
          desc: "고점 대비 최대 하락폭 — 위험의 크기, 낮을수록 좋음",
          ref: "Magdon-Ismail & Atiya (2004)",
        },
        {
          name: "Sharpe Ratio",
          value: num(m.sharpe_ratio),
          tone: (m.sharpe_ratio || 0) >= 1 ? "up" : "neutral",
          desc: "위험 1단위당 초과수익. 1.0 이상 양호, 2.0 이상 우수",
          ref: "Sharpe (1966)",
        },
        {
          name: "Sortino Ratio",
          value: num(m.sortino_ratio),
          tone: (m.sortino_ratio || 0) >= 1 ? "up" : "neutral",
          desc: "하방 변동성만 반영한 위험조정 수익률 — 상승 변동은 페널티 없음",
          ref: "Sortino & Price (1994)",
        },
        {
          name: "Sterling Ratio",
          value: num(m.sterling_ratio),
          tone: (m.sterling_ratio || 0) >= 0.5 ? "up" : "neutral",
          desc: "상위 3개 MDD 평균 대비 연환산 초과수익 — 이상치에 강건",
          ref: "Sterling (1970s)",
        },
        {
          name: "Calmar Ratio",
          value: num(m.calmar_ratio),
          tone: (m.calmar_ratio || 0) >= 0.5 ? "up" : "neutral",
          desc: "최대 MDD 대비 연환산 초과수익 — 보수적 하방 리스크 지표",
          ref: "Young (1991)",
        },
        {
          name: "Deflated Sharpe Ratio (DSR)",
          value: m.dsr == null ? "-" : (m.dsr * 100).toFixed(1) + "%",
          tone: (m.dsr || 0) >= 0.95 ? "up" : "down",
          desc: "이 샤프 지수가 우연이 아닐 확률 (0~1). 0.95 이상 통계적 유의",
          ref: "Bailey & López de Prado (2014)",
        },
      ];

      const toneColor = (t) =>
        t === "up" ? "var(--green)" : t === "down" ? "var(--red)" : "var(--text)";

      tableEl.innerHTML = `
        <h4 class="text-sm font-semibold mb-3" style="color:var(--text-dim);">
          📋 상세 지표 (${data.snapshot_count}개 스냅샷 기준)
        </h4>
        <div class="overflow-x-auto">
          <table class="w-full text-xs" style="border-collapse:collapse;">
            <thead>
              <tr style="border-bottom:1px solid var(--border);color:var(--text-mute);">
                <th style="text-align:left;padding:8px 6px;">지표</th>
                <th style="text-align:right;padding:8px 6px;">값</th>
                <th style="text-align:left;padding:8px 6px;">의미</th>
                <th style="text-align:left;padding:8px 6px;">참조</th>
              </tr>
            </thead>
            <tbody>
              ${rows.map(r => `
                <tr style="border-bottom:1px solid var(--border);">
                  <td style="padding:8px 6px;font-weight:600;">${escHtml(r.name)}</td>
                  <td style="padding:8px 6px;text-align:right;font-weight:700;color:${toneColor(r.tone)};">${r.value}</td>
                  <td style="padding:8px 6px;color:var(--text-dim);">${escHtml(r.desc)}</td>
                  <td style="padding:8px 6px;font-size:11px;color:var(--text-mute);">${escHtml(r.ref)}</td>
                </tr>`).join("")}
            </tbody>
          </table>
        </div>
        <p class="text-xs mt-3" style="color:var(--text-mute);">
          ※ 모든 지표는 무위험수익률 ${(data.params?.risk_free_rate * 100).toFixed(1)}% · 시도 횟수 ${data.params?.n_trials}회 기준으로 산출됩니다.
          DSR이 0.95 미만이면 이 전략은 우연일 가능성을 배제할 수 없습니다.
        </p>`;
    }
  } catch (e) {
    cardsEl.innerHTML = `<div class="text-xs col-span-4" style="color:var(--red);">
      지표를 불러오지 못했습니다: ${escHtml(e.message)}
    </div>`;
  }
}

document.getElementById("robo-metrics-refresh")?.addEventListener("click", loadRoboPerformanceMetrics);


// ═══════════════════════════════════════════════════════════
// 코스콤 테스트베드 기준
// ═══════════════════════════════════════════════════════════
const _rtCharts = {
  base: null, turnover: null, radar: null,
  riskScatter: null, allocation: null, benchmark: null,
};
let _rtBenchmarkData = null;
let _rtBenchmarkDays = 0;

async function loadRoboTestbed() {
  await Promise.all([
    _rtLoadBase(),
    _rtLoadTurnoverChart(),
    _rtLoadRadar(),
    _rtLoadRiskScatter(),
    _rtLoadAllocation(),
    _rtLoadBenchmark(),
    _rtLoadReturnsTable(),
    _rtLoadRiskTable(),
    _rtLoadTurnoverTable(),
  ]);
}

const _rtErr = (e) => `<div class="text-xs" style="color:var(--red);padding:20px;">${escHtml(e.message)}</div>`;
const _rtEmpty = (msg) => `<div class="text-xs" style="color:var(--text-mute);padding:40px 0;text-align:center;">${msg}</div>`;

// ① 기준가 라인
async function _rtLoadBase() {
  const el = document.getElementById("rt-base-chart");
  if (!el) return;
  try {
    const data = await api("/api/paper/performance/metrics");
    if (data.status !== "ok") { el.innerHTML = _rtEmpty("데이터 부족"); return; }
    if (_rtCharts.base) _rtCharts.base.destroy();

    const dates = data.snap_dates || [];
    const eq = data.equity_curve || [];
    const labels = dates.map(d => d.slice(5));

    _rtCharts.base = new ApexCharts(el, {
      chart: { type: "line", height: 260, toolbar: { show: false }, background: "transparent" },
      series: [{ name: "자산", data: eq }],
      xaxis: { categories: labels, tickAmount: 5, labels: { style: { fontSize: "10px", colors: "#888" } } },
      yaxis: {
        labels: {
          formatter: v => v == null ? "" : (v / 10000).toFixed(1) + "만",
          style: { fontSize: "10px", colors: "#888" },
        },
        tickAmount: 5,
      },
      colors: ["#f23645"],
      stroke: { curve: "smooth", width: 2 },
      dataLabels: { enabled: false },
      grid: { borderColor: "rgba(255,255,255,0.06)" },
    });
    _rtCharts.base.render();
  } catch (e) { el.innerHTML = _rtErr(e); }
}

// ② 매매회전율 vs 누적수익률 (산점도)
async function _rtLoadTurnoverChart() {
  const el = document.getElementById("rt-turnover-chart");
  if (!el) return;
  try {
    const [t, r] = await Promise.all([
      api("/api/paper/performance/turnover"),
      api("/api/paper/performance/returns-table"),
    ]);
    if (t.status !== "ok" || r.status !== "ok") { el.innerHTML = _rtEmpty("데이터 부족"); return; }
    if (_rtCharts.turnover) _rtCharts.turnover.destroy();

    const x = t.annualized_turnover_pct || 0;
    const y = (r.return_cumulative || 0) * 100;

    _rtCharts.turnover = new ApexCharts(el, {
      chart: { type: "scatter", height: 260, toolbar: { show: false }, background: "transparent" },
      series: [{ name: "우리", data: [[x, y]] }],
      xaxis: {
        title: { text: "연환산 회전율 (%)", style: { fontSize: "10px", color: "#888" } },
        labels: {
          formatter: (v) => v == null ? "" : Number(v).toFixed(1),
          style: { fontSize: "10px", colors: "#888" },
        },
        tickAmount: 5,
      },
      yaxis: {
        title: { text: "누적수익률 (%)", style: { fontSize: "10px", color: "#888" } },
        labels: {
          formatter: (v) => v == null ? "" : Number(v).toFixed(2),
          style: { fontSize: "10px", colors: "#888" },
        },
        tickAmount: 5,
      },
      colors: ["#089981"],
      markers: { size: 12 },
      dataLabels: { enabled: true, formatter: () => "우리", offsetY: -12, style: { fontSize: "10px" } },
    });
    _rtCharts.turnover.render();
  } catch (e) { el.innerHTML = _rtErr(e); }
}

// ③ 레이더 차트
async function _rtLoadRadar() {
  const el = document.getElementById("rt-radar-chart");
  if (!el) return;
  try {
    const data = await api("/api/paper/performance/risk-metrics");
    if (data.status !== "ok") { el.innerHTML = _rtEmpty("데이터 부족"); return; }
    if (_rtCharts.radar) _rtCharts.radar.destroy();

    const m = data["1y"] || data["6m"] || data["3m"] || data["1m"] || {};
    // 정규화 (0~100 스케일)
    const std = Math.min(100, Math.abs(m.std_dev || 0) * 100);
    const sharpe = Math.min(100, Math.max(0, (m.sharpe || 0) * 30));
    const mddScore = 50;  // MDD 별도 계산 필요 (지금은 placeholder)
    const alpha = Math.min(100, Math.max(0, (m.jensen_alpha || 0) * 500));
    const ir = Math.min(100, Math.max(0, (m.information_ratio || 0) * 50));

    _rtCharts.radar = new ApexCharts(el, {
      chart: { type: "radar", height: 260, toolbar: { show: false }, background: "transparent" },
      series: [{ name: "우리 어드바이저", data: [std, sharpe, mddScore, alpha, ir] }],
      labels: ["표준편차", "샤프", "MDD", "젠센알파", "정보비율"],
      colors: ["#089981"],
      stroke: { width: 2 },
      fill: { opacity: 0.25 },
      markers: { size: 4 },
      yaxis: { show: false, min: 0, max: 100 },
      plotOptions: { radar: { polygons: { strokeColors: "#444", connectorColors: "#444" } } },
    });
    _rtCharts.radar.render();
  } catch (e) { el.innerHTML = _rtErr(e); }
}

// ④ 표준편차 vs 샤프 (기간별 산점도)
async function _rtLoadRiskScatter() {
  const el = document.getElementById("rt-risk-scatter-chart");
  if (!el) return;
  try {
    const data = await api("/api/paper/performance/risk-metrics");
    if (data.status !== "ok") { el.innerHTML = _rtEmpty("데이터 부족"); return; }
    if (_rtCharts.riskScatter) _rtCharts.riskScatter.destroy();

    const periods = ["1m", "3m", "6m", "1y"];
    const points = periods
      .filter(k => data[k]?.std_dev != null && data[k]?.sharpe != null)
      .map(k => ({ x: data[k].std_dev, y: data[k].sharpe, label: k }));

    if (!points.length) { el.innerHTML = _rtEmpty("기간별 데이터 부족"); return; }

    _rtCharts.riskScatter = new ApexCharts(el, {
      chart: { type: "scatter", height: 280, toolbar: { show: false }, background: "transparent" },
      series: [{ name: "기간별", data: points.map(p => ({ x: p.x, y: p.y })) }],
      xaxis: {
        title: { text: "표준편차 (연환산)", style: { fontSize: "10px", color: "#888" } },
        labels: {
          formatter: (v) => v == null ? "" : Number(v).toFixed(2),
          style: { fontSize: "10px", colors: "#888" },
        },
        tickAmount: 5,
      },
      yaxis: {
        title: { text: "샤프지수", style: { fontSize: "10px", color: "#888" } },
        labels: {
          formatter: (v) => v == null ? "" : Number(v).toFixed(2),
          style: { fontSize: "10px", colors: "#888" },
        },
        tickAmount: 5,
      },
      colors: ["#2962ff"],
      markers: { size: 12 },
      dataLabels: {
        enabled: true,
        formatter: (v, { dataPointIndex }) => points[dataPointIndex]?.label || "",
        offsetY: -10,
        style: { fontSize: "10px" },
      },
    });
    _rtCharts.riskScatter.render();
  } catch (e) { el.innerHTML = _rtErr(e); }
}

// ⑤ 자산 비중 스택바
async function _rtLoadAllocation() {
  const el = document.getElementById("rt-allocation-chart");
  if (!el) return;
  try {
    const data = await api("/api/paper/performance/allocation-history");
    if (data.status !== "ok" || !data.series?.length) { el.innerHTML = _rtEmpty("데이터 부족"); return; }
    if (_rtCharts.allocation) _rtCharts.allocation.destroy();

    const dates = data.series.map(s => s.date.slice(5));
    _rtCharts.allocation = new ApexCharts(el, {
      chart: { type: "bar", height: 280, stacked: true, toolbar: { show: false }, background: "transparent" },
      series: [
        { name: "현금", data: data.series.map(s => s.cash_pct) },
        { name: "주식", data: data.series.map(s => s.stock_pct) },
        { name: "코인", data: data.series.map(s => s.crypto_pct) },
        { name: "대체자산", data: data.series.map(s => s.alt_pct) },
      ],
      xaxis: { categories: dates, labels: { style: { fontSize: "10px", colors: "#888" } } },
      yaxis: { max: 100, labels: { formatter: v => v.toFixed(0) + "%", style: { fontSize: "10px", colors: "#888" } } },
      colors: ["#787b86", "#2962ff", "#f59e0b", "#a855f7"],
      dataLabels: { enabled: false },
      legend: { position: "bottom", fontSize: "11px" },
      plotOptions: { bar: { columnWidth: "60%" } },
    });
    _rtCharts.allocation.render();
  } catch (e) { el.innerHTML = _rtErr(e); }
}

// ⑥ KOSPI 비교
async function _rtLoadBenchmark() {
  const el = document.getElementById("rt-benchmark-chart");
  if (!el) return;
  try {
    const data = await api("/api/paper/performance/benchmark");
    if (data.status !== "ok") { el.innerHTML = _rtEmpty("벤치마크 데이터 부족"); return; }
    _rtBenchmarkData = data;
    _rtRenderBenchmark();
  } catch (e) { el.innerHTML = _rtErr(e); }
}

function _rtRenderBenchmark() {
  const el = document.getElementById("rt-benchmark-chart");
  if (!el || !_rtBenchmarkData) return;
  if (_rtCharts.benchmark) _rtCharts.benchmark.destroy();

  const d = _rtBenchmarkData;
  const days = _rtBenchmarkDays;
  const our = days ? d.our_series.slice(-days) : d.our_series;
  const bench = days ? d.benchmark_series.slice(-days) : d.benchmark_series;
  const dates = days ? d.dates.slice(-days) : d.dates;
  const labels = dates.map(x => x.slice(5));

  _rtCharts.benchmark = new ApexCharts(el, {
    chart: { type: "line", height: 300, toolbar: { show: false }, background: "transparent" },
    series: [
      { name: d.benchmark_name || "KOSPI", data: bench },
      { name: "우리 어드바이저", data: our },
    ],
    xaxis: { categories: labels, tickAmount: 8, labels: { style: { fontSize: "10px", colors: "#888" } } },
    yaxis: { labels: { formatter: v => v.toFixed(1), style: { fontSize: "10px", colors: "#888" } } },
    colors: ["#f23645", "#089981"],
    stroke: { curve: "smooth", width: [1.5, 2.5] },
    dataLabels: { enabled: false },
    legend: { position: "bottom", fontSize: "11px" },
    grid: { borderColor: "rgba(255,255,255,0.06)" },
  });
  _rtCharts.benchmark.render();
}

// 기간 버튼 (이벤트 위임)
document.addEventListener("click", (e) => {
  if (e.target.classList.contains("rt-period")) {
    _rtBenchmarkDays = Number(e.target.dataset.days) || 0;
    document.querySelectorAll(".rt-period").forEach(b => {
      b.classList.toggle("btn-primary", b === e.target);
      b.classList.toggle("btn-secondary", b !== e.target);
    });
    _rtRenderBenchmark();
  }
});

// ⑦ 수익률표
async function _rtLoadReturnsTable() {
  const el = document.getElementById("rt-returns-table");
  if (!el) return;
  try {
    const data = await api("/api/paper/performance/returns-table");
    if (data.status !== "ok") { el.innerHTML = _rtEmpty("데이터 부족"); return; }

    const rows = [
      ["1개월 수익률", data.return_1m],
      ["3개월 수익률", data.return_3m],
      ["6개월 수익률", data.return_6m],
      ["1년 수익률", data.return_1y],
      ["누적 수익률", data.return_cumulative],
    ];

    el.innerHTML = `<table class="w-full text-sm" style="border-collapse:collapse;">
      <thead><tr style="border-bottom:1px solid var(--border);color:var(--text-mute);">
        <th style="text-align:left;padding:8px;">구분</th>
        <th style="text-align:right;padding:8px;">해당계좌</th>
      </tr></thead>
      <tbody>${rows.map(([label, v]) => {
      const color = v == null ? "var(--text-mute)" : (v >= 0 ? "var(--green)" : "var(--red)");
      return `<tr style="border-bottom:1px solid var(--border);">
          <td style="padding:8px;">${label}</td>
          <td style="padding:8px;text-align:right;font-weight:600;color:${color};">
            ${v == null ? "-" : (v * 100).toFixed(2)}
          </td>
        </tr>`;
    }).join("")}</tbody>
    </table>`;
  } catch (e) { el.innerHTML = _rtErr(e); }
}

// ⑧ 위험지표표
async function _rtLoadRiskTable() {
  const el = document.getElementById("rt-risk-table");
  if (!el) return;
  try {
    const data = await api("/api/paper/performance/risk-metrics");
    if (data.status !== "ok") { el.innerHTML = _rtEmpty("데이터 부족"); return; }

    const periods = ["1m", "3m", "6m", "1y"];
    const labels = { "1m": "1개월", "3m": "3개월", "6m": "6개월", "1y": "1년" };
    const metrics = [
      ["std_dev", "표준편차"],
      ["beta", "베타"],
      ["sharpe", "샤프지수"],
      ["jensen_alpha", "젠센알파"],
      ["tracking_error", "트래킹에러"],
      ["information_ratio", "정보비율(IR)"],
    ];

    el.innerHTML = `<div class="overflow-x-auto"><table class="w-full text-xs" style="border-collapse:collapse;">
      <thead><tr style="border-bottom:1px solid var(--border);color:var(--text-mute);">
        <th style="text-align:left;padding:8px;">구분</th>
        ${periods.map(p => `<th style="text-align:right;padding:8px;">${labels[p]}</th>`).join("")}
      </tr></thead>
      <tbody>${metrics.map(([key, label]) => `
        <tr style="border-bottom:1px solid var(--border);">
          <td style="padding:8px;">${label}</td>
          ${periods.map(p => {
      const v = data[p]?.[key];
      return `<td style="padding:8px;text-align:right;">${v == null ? "-" : v.toFixed(3)}</td>`;
    }).join("")}
        </tr>`).join("")}</tbody>
    </table></div>`;
  } catch (e) { el.innerHTML = _rtErr(e); }
}

// ⑨ 매매회전율표
async function _rtLoadTurnoverTable() {
  const el = document.getElementById("rt-turnover-table");
  if (!el) return;
  try {
    const data = await api("/api/paper/performance/turnover");
    if (data.status !== "ok") { el.innerHTML = _rtEmpty("데이터 부족"); return; }

    const fmt = (n) => n == null ? "-" : Number(n).toLocaleString("ko-KR", { maximumFractionDigits: 0 });
    el.innerHTML = `<table class="w-full text-sm" style="border-collapse:collapse;">
      <thead><tr style="border-bottom:1px solid var(--border);color:var(--text-mute);">
        <th style="text-align:left;padding:8px;">구분</th>
        <th style="text-align:right;padding:8px;">값</th>
      </tr></thead>
      <tbody>
        <tr style="border-bottom:1px solid var(--border);">
          <td style="padding:8px;">총 매수금액</td>
          <td style="padding:8px;text-align:right;">${fmt(data.total_buy)}원</td>
        </tr>
        <tr style="border-bottom:1px solid var(--border);">
          <td style="padding:8px;">총 매도금액</td>
          <td style="padding:8px;text-align:right;">${fmt(data.total_sell)}원</td>
        </tr>
        <tr style="border-bottom:1px solid var(--border);">
          <td style="padding:8px;">평균 자산</td>
          <td style="padding:8px;text-align:right;">${fmt(data.avg_equity)}원</td>
        </tr>
        <tr style="border-bottom:1px solid var(--border);">
          <td style="padding:8px;">매매회전율</td>
          <td style="padding:8px;text-align:right;font-weight:700;">${data.turnover_ratio?.toFixed(2) ?? "-"}%</td>
        </tr>
        <tr>
          <td style="padding:8px;">연환산 매매회전율</td>
          <td style="padding:8px;text-align:right;font-weight:700;color:var(--accent);">${data.annualized_turnover_pct?.toFixed(2) ?? "-"}%</td>
        </tr>
      </tbody>
    </table>
    <p class="text-xs mt-2" style="color:var(--text-mute);">
      공식: (총매수 + 총매도) / 2 / 평균자산, 연환산은 기간(년)으로 나눔.
    </p>`;
  } catch (e) { el.innerHTML = _rtErr(e); }
}

document.getElementById("rt-refresh")?.addEventListener("click", loadRoboTestbed);


export {
  loadPatternAnalysis,
  loadRoboDecision,
  loadRoboScreening,
  renderXaiBlock,
  loadRoboPerformanceMetrics,
  loadRoboTestbed,
};