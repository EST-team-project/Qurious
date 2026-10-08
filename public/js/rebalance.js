/* 리밸런싱 엔진 화면 (robo-rebalance)
 * 목표 비중 플랜 · 현재 비중/이탈률 · 주문 제안/실행 · 입출금/배당 이벤트 · 실행 이력
 * app.html 메인 모듈에서 initRebalanceView() / onRebalanceViewActivated(view) 로 연결한다. */
import { api, setToast, escHtml, fmt, fmtPct } from "/js/common.js";

const $ = (id) => document.getElementById(id);
const won = (n, d = 0) => `${fmt(n, d)}원`;
const ts = (iso) => iso ? new Date(iso).toLocaleString("ko-KR", { hour12: false, timeZone: "Asia/Seoul" }) : "-";
const PERIOD_LABEL = { none: "사용 안 함", monthly: "매월", quarterly: "매분기", yearly: "매년" };
const TRIGGER_LABEL = { TIME: "시간", DRIFT: "이탈률", CASHFLOW: "현금흐름", MANUAL: "수동" };
const STATUS_BADGE = {
  executed: `<span class="badge-buy">체결</span>`, proposed: `<span class="badge-hold">제안</span>`,
  scheduled: `<span class="badge-hold">시가 체결 대기</span>`,
  cancelled: `<span class="badge-hold">취소</span>`,
  partial: `<span class="badge-sell">부분 체결</span>`,
  skipped: `<span class="badge-hold">생략</span>`, failed: `<span class="badge-sell">실패</span>`,
};
const KIND_LABEL = { full: "전체 조정", buy_only: "매수 전용", sell_only: "매도 전용" };
const sideBadge = (s) => s === "BUY" ? `<span class="badge-buy">매수</span>` : `<span class="badge-sell">매도</span>`;

let weightChart = null;
let targetRows = [];   // [{symbol, name, weight_pct}]
let lastProposal = null;

/* ── 플랜 편집 ────────────────────────────────────────────── */
function renderTargets() {
  const tbody = $("rb-targets-body");
  if (!targetRows.length) {
    tbody.innerHTML = `<tr><td colspan="4" class="text-center" style="color:var(--text-mute);">종목을 추가하세요. 합계가 100% 미만이면 나머지는 현금으로 배분됩니다.</td></tr>`;
  } else {
    tbody.innerHTML = targetRows.map((t, i) => `
      <tr>
        <td class="font-mono text-xs">${escHtml(t.symbol)}</td>
        <td>${escHtml(t.name || "")}</td>
        <td style="text-align:right"><input type="number" min="0" max="100" step="0.5" value="${t.weight_pct}" data-idx="${i}" class="input rb-w" style="width:90px;text-align:right;" /></td>
        <td style="text-align:center"><button class="btn-secondary text-xs rb-del" data-idx="${i}">삭제</button></td>
      </tr>`).join("");
    tbody.querySelectorAll(".rb-w").forEach(el => el.addEventListener("input", e => {
      targetRows[+e.target.dataset.idx].weight_pct = parseFloat(e.target.value) || 0; updateSum();
    }));
    tbody.querySelectorAll(".rb-del").forEach(el => el.addEventListener("click", e => {
      targetRows.splice(+e.target.dataset.idx, 1); renderTargets();
    }));
  }
  updateSum();
}

function updateSum() {
  const sum = targetRows.reduce((a, t) => a + (parseFloat(t.weight_pct) || 0), 0);
  const cash = Math.max(0, 100 - sum);
  $("rb-target-sum").innerHTML = `주식 합계 <b>${sum.toFixed(1)}%</b> · 현금 <b>${cash.toFixed(1)}%</b>` +
    (sum > 100 ? ` <span class="text-red-500">합계가 100%를 초과합니다</span>` : "");
}

async function addTarget() {
  const raw = $("rb-add-symbol").value.trim();
  const w = parseFloat($("rb-add-weight").value);
  if (!raw) return setToast("종목코드를 입력하세요.", "error");
  if (!(w >= 0)) return setToast("비중(%)을 입력하세요.", "error");
  try {
    const q = await api(`/api/paper/stocks/quote?symbol=${encodeURIComponent(raw)}`);
    const exist = targetRows.find(t => t.symbol === q.symbol);
    if (exist) exist.weight_pct = w; else targetRows.push({ symbol: q.symbol, name: q.name, weight_pct: w });
    $("rb-add-symbol").value = ""; $("rb-add-weight").value = "";
    renderTargets();
  } catch (e) { setToast(e.message, "error"); }
}

function importFromPositions(snapshot) {
  // 현재 보유 비중을 목표로 복사
  const held = snapshot.rows.filter(r => r.quantity > 0);
  const total = snapshot.cash + held.reduce((sum, r) => sum + r.current_amount, 0);
  targetRows = held.map(r => ({ symbol: r.symbol, name: r.name,
    weight_pct: total > 0 ? Math.floor(r.current_amount / total * 10000) / 100 : 0 }));
  renderTargets();
}

function fillPlanForm(plan) {
  targetRows = (plan.targets || []).map(t => ({ ...t }));
  renderTargets();
  $("rb-name").value = plan.name || "";
  $("rb-period").value = plan.time_period || "none";
  $("rb-drift-enabled").checked = !!plan.drift_enabled;
  $("rb-drift").value = plan.drift_threshold_pct;
  $("rb-cf-enabled").checked = !!plan.cashflow_enabled;
  $("rb-cf-min").value = plan.cashflow_min_amount;
  $("rb-drift-mode").value = plan.drift_check_mode || "always";
  $("rb-protect").checked = !!plan.exclude_unplanned;
  syncPreset("rb-drift-preset", "rb-drift");
  syncPreset("rb-cf-preset", "rb-cf-min");
  $("rb-auto").checked = !!plan.auto_execute;
  $("rb-min-order").value = plan.min_order_amount;
  $("rb-active").checked = !!plan.is_active;
}

async function savePlan() {
  const body = {
    name: $("rb-name").value.trim() || undefined,
    is_active: $("rb-active").checked,
    targets: targetRows.map(t => ({ symbol: t.symbol, name: t.name || "", weight_pct: parseFloat(t.weight_pct) || 0 })),
    time_period: $("rb-period").value,
    drift_enabled: $("rb-drift-enabled").checked,
    drift_threshold_pct: parseFloat($("rb-drift").value),
    drift_check_mode: $("rb-drift-mode").value,
    exclude_unplanned: $("rb-protect").checked,
    cashflow_enabled: $("rb-cf-enabled").checked,
    cashflow_min_amount: parseFloat($("rb-cf-min").value),
    auto_execute: $("rb-auto").checked,
    min_order_amount: parseFloat($("rb-min-order").value) || 0,
  };
  if (![body.drift_threshold_pct, body.cashflow_min_amount, body.min_order_amount].every(Number.isFinite)) return setToast("설정 금액과 이탈률을 입력하세요.", "error");
  try {
    await api("/api/rebalance/plan", { method: "PUT", body });
    setToast("리밸런싱 플랜을 저장했습니다.", "ok");
    await loadStatus();
  } catch (e) { setToast(e.message, "error"); }
}

/* ── 현황 ────────────────────────────────────────────────── */
async function loadStatus() {
  try {
    const r = await api("/api/rebalance/status");
    const { plan, snapshot: s, triggers } = r;
    fillPlanForm(plan);
    const daily = r.automatic_check;
    $("rb-daily-check").textContent = daily ? `자동 정기 점검: ${daily.message}`
      + (daily.state === "checked" && daily.last_checked_at ? ` (${ts(daily.last_checked_at)} · 한국시간)` : "") : "";
    $("rb-schedule-warning").hidden = !plan.time_schedule_error;
    $("rb-schedule-warning").textContent = plan.time_schedule_error ? `시간 예약 확인 대기: ${plan.time_schedule_error}` : "";
    $("rb-import-positions").disabled = !s || !!s.excluded_prices_unavailable?.length;
    $("rb-import-positions").title = s?.excluded_prices_unavailable?.length ? "일부 보유 종목의 종가가 없어 비중을 복사할 수 없습니다." : "전 거래일 종가 기준 보유 비중을 목표로 복사";
    if (!s) {
      lastProposal = null;
      $("rb-execute").disabled = true;
      $("rb-proposal").textContent = "자료 준비 후 다시 주문을 산출하세요.";
      $("rb-proposal-summary").textContent = "";
      $("rb-kpis").textContent = r.valuation_error || "종가 자료 확인 대기";
      $("rb-trigger-badges").textContent = "가격 자료가 준비되면 조건을 확인합니다.";
      $("rb-weight-table").textContent = "전 거래일 종가 기준 비중 확인 대기";
      if (weightChart) { weightChart.destroy(); weightChart = null; }
      await Promise.all([loadRuns(), loadCashflows()]);
      return;
    }
    $("rb-kpis").innerHTML = [
      kpi("관리 자산 (현금+대상 주식)", won(s.total_asset)),
      kpi("제외한 주식 평가액", s.excluded_prices_unavailable?.length ? "일부 종가 확인 대기" : won(s.excluded_asset || 0)),
      kpi("목표 대비 현금 초과(+)/부족(-)", won(s.cash_excess)),
      kpi("미사용 현금흐름 예산 (+매수 / -매도)", won(s.pending_budget)),
      kpi("현금 비중", `${s.cash_weight_pct}% <span class="text-xs" style="color:var(--text-mute)">목표 ${s.cash_target_pct}%</span>`),
      kpi("최대 이탈", `${s.max_drift_pct}%p`, s.drift_exceeded ? "text-red-500" : "text-emerald-600"),
      kpi("다음 시간 리밸런싱 (한국시간)", plan.time_period === "none" ? "-" : `${PERIOD_LABEL[plan.time_period]} 첫 거래일<div class="text-xs font-normal" style="color:var(--text-mute)">${plan.time_schedule_error ? '달력 확인 대기' : escHtml(plan.next_run_at ? new Date(plan.next_run_at).toLocaleDateString('ko-KR', { timeZone: 'Asia/Seoul' }) + ' 갱신 완료 후' : '-')}</div>`),
    ].join("");
    const badges = [`<span class="badge-hold">판단 기준 ${escHtml(s.valuation_date)} 종가</span>`];
    if (triggers.time_due) badges.push(`<span class="badge-sell">시간 트리거 도래</span>`);
    if (triggers.drift_due) badges.push(`<span class="badge-sell">이탈률 기준 이상 (허용 ${plan.drift_threshold_pct}%p)</span>`);
    if (triggers.cashflow_due) badges.push(`<span class="badge-sell">현금흐름 기준 충족 (${won(s.cashflow_available)})</span>`);
    if (badges.length === 1) badges.push(`<span class="badge-buy">트리거 조건 미충족 — 현재 실행 조건 없음</span>`);
    badges.push(`<span class="badge-hold">${plan.auto_execute ? "자동 예약" : "제안만 생성 (수동 승인)"}</span>`);
    $("rb-trigger-badges").innerHTML = badges.join(" ");

    renderWeightTable(s);
    renderWeightChart(s);
    $("rb-import-positions").onclick = () => importFromPositions(s);
  } catch (e) { setToast(e.message, "error"); }
  loadRuns(); loadCashflows();
}

const kpi = (label, value, cls = "") => `
  <div class="rounded-xl border border-white/10 bg-black/20 p-3">
    <div class="text-xs" style="color:var(--text-mute);">${escHtml(label)}</div>
    <div class="text-lg font-bold ${cls}">${value}</div>
  </div>`;

function renderWeightTable(s) {
  const rows = [...s.rows, { symbol: "CASH", name: "현금", quantity: "", price: null, current_amount: s.cash,
    current_weight_pct: s.cash_weight_pct, target_weight_pct: s.cash_target_pct, drift_pct: s.cash_drift_pct, in_plan: true }];
  $("rb-weight-table").innerHTML = `<table><thead><tr><th>종목</th><th style="text-align:right">수량</th><th style="text-align:right">평가액</th><th style="text-align:right">현재 비중</th><th style="text-align:right">목표 비중</th><th style="text-align:right">이탈(%p)</th></tr></thead><tbody>${
    rows.map(r => `<tr${r.in_plan ? "" : ' style="opacity:.7"'}><td>${escHtml(r.name)} <span class="text-xs font-mono" style="color:var(--text-mute)">${escHtml(r.symbol)}</span>${r.in_plan ? "" : ` <span class="badge-hold text-xs">${r.managed ? '플랜 외 → 매도 대상' : '플랜 외 → 유지·계산 제외'}</span>`}</td>
      <td style="text-align:right">${r.quantity === "" ? "-" : fmt(r.quantity)}</td><td style="text-align:right">${r.quantity > 0 && r.price == null ? "종가 확인 대기" : won(r.current_amount)}</td>
      <td style="text-align:right">${r.current_weight_pct}%</td><td style="text-align:right">${r.target_weight_pct}%</td>
      <td style="text-align:right" class="${Math.abs(r.drift_pct) >= 0.01 ? (r.drift_pct > 0 ? "text-red-500" : "text-emerald-600") : ""}">${r.drift_pct > 0 ? "+" : ""}${r.drift_pct}</td></tr>`).join("")}</tbody></table>`;
}

function renderWeightChart(s) {
  const managed = s.rows.filter(r => r.managed !== false);
  const cats = [...managed.map(r => r.name), "현금"];
  const cur = [...managed.map(r => r.current_weight_pct), s.cash_weight_pct];
  const tgt = [...managed.map(r => r.target_weight_pct), s.cash_target_pct];
  const opts = {
    chart: { type: "bar", height: 260, toolbar: { show: false }, background: "transparent" },
    theme: { mode: document.documentElement.dataset.theme === "light" ? "light" : "dark" },
    series: [{ name: "현재 비중", data: cur }, { name: "목표 비중", data: tgt }],
    xaxis: { categories: cats }, yaxis: { labels: { formatter: v => `${v}%` } },
    plotOptions: { bar: { columnWidth: "55%", borderRadius: 3 } }, dataLabels: { enabled: false },
    colors: ["#2962ff", "#089981"], legend: { position: "top" },
    tooltip: { y: { formatter: v => `${v}%` } },
  };
  if (weightChart) { weightChart.updateOptions(opts); return; }
  if (window.ApexCharts) { weightChart = new ApexCharts($("rb-weight-chart"), opts); weightChart.render(); }
}

/* ── 제안/실행 ────────────────────────────────────────────── */
function renderOrders(orders, containerId, opts = {}) {
  const el = $(containerId);
  if (!orders?.length) { el.innerHTML = `<div class="text-sm" style="color:var(--text-mute);">${opts.empty || "생성된 주문이 없습니다 (이미 목표 비중 근처이거나 최소 주문금액 미만)."}</div>`; return; }
  el.innerHTML = `<table><thead><tr><th>매매</th><th>종목</th><th style="text-align:right">수량</th><th style="text-align:right">단가</th><th style="text-align:right">금액</th><th style="text-align:right">비용</th><th>상태</th></tr></thead><tbody>${
    orders.map(o => `<tr><td>${sideBadge(o.side)}</td><td>${escHtml(o.name)} <span class="text-xs font-mono" style="color:var(--text-mute)">${escHtml(o.symbol)}</span></td>
      <td style="text-align:right">${fmt(o.quantity)}</td><td style="text-align:right">${won(o.price)}</td><td style="text-align:right">${won(o.amount)}</td>
      <td style="text-align:right">${o.cost ? won(o.cost.total_cost, 2) : "-"}</td><td class="text-xs">${escHtml(o.status)}${o.error ? ` <span class="text-red-500">${escHtml(o.error)}</span>` : ""}</td></tr>`).join("")}</tbody></table>`;
}

async function previewRebalance() {
  lastProposal = null;
  $("rb-execute").disabled = true;
  $("rb-proposal-summary").textContent = "";
  $("rb-proposal").innerHTML = `<span style="color:var(--text-mute);">전 거래일 종가 기준으로 예상 주문을 산출 중…</span>`;
  try {
    lastProposal = await api("/api/rebalance/preview", { method: "POST" });
    renderOrders(lastProposal.orders, "rb-proposal");
    $("rb-proposal-summary").textContent = `판단 기준 ${lastProposal.snapshot.valuation_date} 종가 · 체결 수량은 시가로 재계산 · 예상 회전 금액 ${won(lastProposal.estimated_turnover)} · 예상 비용 ${won(lastProposal.estimated_cost, 2)} · 비용 반영 후 현금 ${won(lastProposal.estimated_cash_after)}` +
      (lastProposal.skipped?.length ? ` · 시세 실패 ${lastProposal.skipped.map(x => x.symbol).join(", ")}` : "");
    $("rb-execute").disabled = !lastProposal.orders.length;
  } catch (e) { $("rb-proposal").innerHTML = `<span class="text-red-500">${escHtml(e.message)}</span>`; }
}

async function executeRebalance(runId = null, scheduled = false) {
  if (!confirm("전 거래일 종가로 판단한 목표 비중을 다음 거래일 시가 체결로 예약합니다. 시가 수집 후 수량을 다시 계산하며, 조건이 해소되면 취소될 수 있습니다. 계속할까요?")) return;
  try {
    const r = await api("/api/rebalance/execute", { method: "POST", body: runId ? { run_id: runId } : { note: "화면에서 수동 실행" } });
    const filled = r.orders.filter(o => o.status === "filled").length;
    if (r.status === "scheduled") setToast(`${r.context.scheduled_for} 시가 체결을 예약했습니다. 데이터 수집 후 확정됩니다.`, "ok");
    else setToast(`리밸런싱 ${r.status === "executed" ? "체결" : r.status === "partial" ? "부분 체결" : "미체결"} — 주문 ${filled}/${r.orders.length}건`, r.status === "executed" ? "ok" : "error");
    renderOrders(r.orders, "rb-proposal");
    $("rb-execute").disabled = true;
    await loadStatus();
  } catch (e) { setToast(e.message, "error"); }
}

async function checkTriggers() {
  try {
    const r = await api("/api/rebalance/check", { method: "POST" });
    const msg = r.message || (r.status === "scheduled" ? (r.already_processed ? "기존 시가 체결 예약을 기다립니다." : "다음 거래일 시가 체결을 예약했습니다.") : r.already_processed ? "오늘 자동 조건 계획은 이미 처리되었습니다. 새 현금흐름 예산은 다음 날로 이월됩니다." : r.trigger ? `${(r.triggers || [r.trigger]).map(t => TRIGGER_LABEL[t]).join(" + ")} 조건 충족 → ${r.status === "executed" ? "자동 체결" : r.status === "proposed" ? "제안 생성" : "주문 없음 또는 일부 실패"}`
      : `트리거 미충족 (시간 ${r.time_due ? "도래" : "대기"} · 최대 이탈 ${r.max_drift_pct ?? "-"}%p)`);
    setToast(msg + (r.time_schedule_error ? ` · 시간 예약 확인 대기: ${r.time_schedule_error}` : ""), r.trigger ? "ok" : "error");
    await loadStatus();
  } catch (e) { setToast(e.message, "error"); }
}

/* ── 현금흐름 ────────────────────────────────────────────── */
async function submitCashflow() {
  const kind = $("rb-cf-kind").value;
  const amount = parseFloat($("rb-cf-amount").value);
  if (!(amount > 0)) return setToast("금액을 입력하세요.", "error");
  const body = { kind, amount, symbol: kind === "DIVIDEND" ? $("rb-cf-symbol").value.trim() : "", memo: $("rb-cf-memo").value.trim() };
  try {
    const r = await api("/api/rebalance/cashflow", { method: "POST", body });
    const label = { DEPOSIT: "입금", WITHDRAW: "출금", DIVIDEND: "배당" }[kind];
    lastProposal = null;
    $("rb-execute").disabled = true;
    const outcome = { executed: "자동 체결", proposed: "제안 생성", partial: "부분 체결", skipped: "주문 없음", failed: "체결 실패" };
    setToast(`${label} ${won(amount)} 반영 (현금 ${won(r.event.cash_after)})` + (r.check_deferred ? " → 다음 일별 점검에서 판단" : r.already_processed ? " → 오늘 계획 처리됨 · 미사용 예산 이월" : r.run ? ` → 리밸런싱 ${outcome[r.run.status] || r.run.status}` : ""), "ok");
    if (r.check_error) setToast(`현금은 반영됐습니다. 리밸런싱 판정 대기: ${r.check_error}`, "error");
    $("rb-cf-amount").value = ""; $("rb-cf-memo").value = "";
    await loadStatus();
  } catch (e) { setToast(e.message, "error"); }
}

async function loadCashflows() {
  try {
    const r = await api("/api/rebalance/cashflows?limit=20");
    const label = { DEPOSIT: `<span class="badge-buy">입금</span>`, WITHDRAW: `<span class="badge-sell">출금</span>`, DIVIDEND: `<span class="badge-buy">배당</span>` };
    $("rb-cashflows").innerHTML = r.events.length ? `<table><thead><tr><th>시각</th><th>구분</th><th style="text-align:right">금액</th><th>종목</th><th>메모</th><th style="text-align:right">반영 후 현금</th><th>리밸런싱</th></tr></thead><tbody>${
      r.events.map(e => `<tr><td class="text-xs">${ts(e.created_at)}</td><td>${label[e.kind] || e.kind}</td><td style="text-align:right">${won(e.amount)}</td><td class="font-mono text-xs">${escHtml(e.symbol || "-")}</td><td class="text-xs">${escHtml(e.memo || "")}</td><td style="text-align:right">${won(e.cash_after)}</td><td class="text-xs">${e.rebalance_run_id ? "연결됨" : "-"}</td></tr>`).join("")}</tbody></table>`
      : `<div class="text-sm" style="color:var(--text-mute);">아직 입출금·배당 이벤트가 없습니다.</div>`;
  } catch (e) { $("rb-cashflows").innerHTML = `<span class="text-red-500">${escHtml(e.message)}</span>`; }
}

/* ── 실행 이력 ────────────────────────────────────────────── */
async function cancelReservation(runId) {
  if (!confirm("이 예약을 취소할까요? 현금·보유 종목·미사용 예산은 유지됩니다. 이후 새 판단으로 다시 예약할 수 있습니다.")) return;
  try {
    await api(`/api/rebalance/runs/${encodeURIComponent(runId)}/cancel`, { method: "POST" });
    lastProposal = null;
    $("rb-execute").disabled = true;
    setToast("예약을 취소했습니다.", "ok");
    await loadStatus();
  } catch (e) { setToast(e.message, "error"); }
}

async function loadRuns() {
  try {
    const r = await api("/api/rebalance/runs?limit=20");
    if (!r.runs.length) { $("rb-runs").innerHTML = `<div class="text-sm" style="color:var(--text-mute);">아직 리밸런싱 이력이 없습니다.</div>`; return; }
    $("rb-runs").innerHTML = r.runs.map(run => {
      const filled = run.orders.filter(o => o.status === "filled").length;
      const wchg = Object.keys(run.target_weights).map(k => {
        const b = run.before_weights[k] ?? 0, a = run.after_weights?.[k], t = run.target_weights[k];
        return `<span class="text-xs mr-2">${escHtml(k === "CASH" ? "현금" : k)}: ${b}%${a !== undefined ? ` → ${a}%` : ""} <span style="color:var(--text-mute)">(목표 ${t}%)</span></span>`;
      }).join("");
      return `<div class="rounded-lg p-3 mb-2" style="background:var(--surf2);border:1px solid var(--border);">
        <div class="flex flex-wrap items-center gap-2 text-sm">
          <span class="badge-hold">${(run.triggers || [run.trigger]).map(t => escHtml(TRIGGER_LABEL[t] || t)).join(" + ")}</span> <span class="badge-hold">${escHtml(KIND_LABEL[run.plan_kind] || "전체 조정")}</span> ${run.context?.cancel_reason === "open_not_tradable" ? '<span class="badge-hold">미체결</span>' : STATUS_BADGE[run.status] || run.status}
          <span class="text-xs" style="color:var(--text-mute)">${run.decision_date || ts(run.created_at)} · 자산 ${won(run.total_asset)} · 최대 이탈 ${run.max_drift_pct}%p · 주문 ${filled}/${run.orders.length}건</span>
          ${run.status === "proposed" ? `<button class="btn-green text-xs ml-auto rb-approve" data-id="${run.id}" data-scheduled="${run.context?.price_basis === 'previous_close'}">${run.context?.price_basis === 'previous_close' ? '승인·예약' : '이전 제안 (재산출 필요)'}</button>` : ""}
          ${run.status === "scheduled" ? `<button class="btn text-xs ml-auto rb-cancel" data-id="${run.id}">${run.context?.review_required ? "확인 대기 예약 취소" : "예약 취소"}</button>` : ""}
        </div>
        <div class="text-xs mt-1" style="color:var(--text-dim)">${escHtml(run.note || "")}</div>
        <div class="text-xs mt-1">${run.context?.price_basis === "previous_close" ? `종가 기준일 ${escHtml(run.context.valuation_date)} · 예약 체결일 ${escHtml(run.context.scheduled_for || "승인 후 결정")}${run.context.fill_date ? ` · 체결일 ${escHtml(run.context.fill_date)}` : ""}${run.context.confirmed_at ? ` · 확정 ${ts(run.context.confirmed_at)}` : ""}` : `현재 시세 조회 ${ts(run.context?.observed_at)}`} · 예상 비용 ${won(run.context?.estimated_cost || 0, 2)}${run.context?.actual_cost !== undefined ? ` · 체결 비용 ${won(run.context.actual_cost, 2)}` : ""}</div>
        <div class="text-xs mt-1">${escHtml(run.context?.waiting_reason || "")}</div>
        ${(run.context?.reschedules || []).map(change => `<div class="text-xs mt-1">휴장일 변경: ${escHtml(change.previous_date)} → ${escHtml(change.scheduled_for)} · 변경 ${ts(change.changed_at)}</div>`).join("")}
        <div class="mt-1">${wchg}</div>
        <details class="mt-1"><summary class="text-xs cursor-pointer" style="color:var(--text-mute)">주문 상세</summary><div id="rb-run-${run.id}" class="mt-1"></div></details>
      </div>`;
    }).join("");
    r.runs.forEach(run => renderOrders(run.orders, `rb-run-${run.id}`, { empty: "주문 없음" }));
    $("rb-runs").querySelectorAll(".rb-approve").forEach(b => b.addEventListener("click", () => executeRebalance(b.dataset.id, b.dataset.scheduled === "true")));
    $("rb-runs").querySelectorAll(".rb-cancel").forEach(b => b.addEventListener("click", () => cancelReservation(b.dataset.id)));
  } catch (e) { $("rb-runs").innerHTML = `<span class="text-red-500">${escHtml(e.message)}</span>`; }
}

/* ── 초기화 ─────────────────────────────────────────────── */
function syncPreset(selectId, inputId) {
  const select = $(selectId), input = $(inputId);
  const match = [...select.options].find(o => o.value !== "custom" && Number(o.value) === Number(input.value));
  select.value = match ? match.value : "custom";
}

export function initRebalanceView() {
  const on = (id, ev, fn) => $(id)?.addEventListener(ev, fn);
  for (const [selectId, inputId] of [["rb-drift-preset", "rb-drift"], ["rb-cf-preset", "rb-cf-min"]]) {
    on(selectId, "change", () => { if ($(selectId).value !== "custom") $(inputId).value = $(selectId).value; else $(inputId).focus(); });
    on(inputId, "input", () => syncPreset(selectId, inputId));
  }
  on("rb-add", "click", addTarget);
  on("rb-add-symbol", "keydown", e => { if (e.key === "Enter") addTarget(); });
  on("rb-save", "click", savePlan);
  on("rb-refresh", "click", loadStatus);
  on("rb-preview", "click", previewRebalance);
  on("rb-execute", "click", () => executeRebalance());
  on("rb-check", "click", checkTriggers);
  on("rb-cf-submit", "click", submitCashflow);
  on("rb-cf-kind", "change", () => { $("rb-cf-symbol-wrap").classList.toggle("hidden", $("rb-cf-kind").value !== "DIVIDEND"); });
}

export function onRebalanceViewActivated(view) {
  if (view === "robo-rebalance") loadStatus();
}
