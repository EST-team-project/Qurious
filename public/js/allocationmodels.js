import { escHtml } from "/js/common.js";

const ASSETS = ["국내주식", "해외주식", "국내채권", "대체자산"];
const HELP = {
  profile: "성향과 기간에 따른 기존 자산군 비중을 사용합니다.",
  risk_parity: "현금은 성향 비중을 유지하고 네 자산군의 위험 기여도를 균등하게 맞춥니다. 자산군별 1~95% 제약으로 차이가 남으면 결과에 표시합니다.",
  minimum_variance: "현금 제외 네 자산군의 과거 공분산으로 추정 변동성을 최소화합니다. 미래 손실을 보장하는 지표는 아닙니다.",
  black_litterman: "기준 균형 비중에 자산군 간 상대 전망과 신뢰도를 반영합니다. 신뢰도 0%의 전망은 반영하지 않습니다.",
  regime: "국내주식 ETF의 120일 추세와 20일 변동성으로 네 국면을 판정합니다. 계산 시점의 목표를 저장하며, 리밸런싱에 적용하려면 가져온 뒤 직접 저장하세요.",
};
const el = id => document.getElementById(id);
const options = selected => ASSETS.map(a => `<option${a === selected ? " selected" : ""}>${a}</option>`).join("");

function controls() {
  const model = el("robo-allocation-model")?.value || "profile";
  el("robo-model-help").textContent = HELP[model];
  el("robo-bl-inputs").classList.toggle("hidden", model !== "black_litterman");
  el("robo-bl-benchmark").classList.toggle("hidden", !el("robo-bl-custom").checked);
}

function addView(view = {}) {
  const host = el("robo-bl-views");
  if (host.children.length >= 6) return;
  const row = document.createElement("div");
  row.className = "grid md:grid-cols-5 gap-2";
  row.innerHTML = `<label class="text-xs">자산군<select class="input bl-asset">${options(view.asset || ASSETS[0])}</select></label>
    <label class="text-xs">비교 자산군<select class="input bl-relative">${options(view.relative_to || ASSETS[1])}</select></label>
    <label class="text-xs">연 초과수익 (%p)<input class="input bl-return" type="number" min="-50" max="50" step="0.1" value="${escHtml(view.outperformance_pct ?? 3)}"></label>
    <label class="text-xs">전망 신뢰도 (%)<input class="input bl-confidence" type="number" min="0" max="99" step="1" value="${escHtml(view.confidence_pct ?? 50)}"></label>
    <button type="button" class="btn-secondary text-xs bl-remove">전망 삭제</button>`;
  row.querySelector(".bl-remove").addEventListener("click", () => row.remove());
  host.append(row);
}

export function initAllocationModels() {
  if (!el("robo-allocation-model")) return;
  el("robo-bl-benchmark").innerHTML = [...ASSETS, "현금"].map((a, i) =>
    `<label class="text-xs">${a} (%)<input data-asset="${a}" class="input" type="number" min="0" max="100" step="0.1" value="${[30, 25, 30, 10, 5][i]}"></label>`).join("");
  el("robo-allocation-model").addEventListener("change", controls);
  el("robo-bl-custom").addEventListener("change", controls);
  el("robo-bl-add").addEventListener("click", () => addView());
  controls();
}

function number(input) {
  if (!input.value.trim() || !input.checkValidity()) throw Error("전망과 기준 비중의 입력 범위를 확인하세요.");
  const value = Number(input.value);
  if (!Number.isFinite(value)) throw Error("숫자로 입력하세요.");
  return value;
}

export function allocationModelInput() {
  const model = el("robo-allocation-model")?.value || "profile";
  const body = { allocation_model: model };
  if (model !== "black_litterman") return body;
  body.views = [...el("robo-bl-views").children].map(row => ({
    asset: row.querySelector(".bl-asset").value,
    relative_to: row.querySelector(".bl-relative").value,
    outperformance_pct: number(row.querySelector(".bl-return")),
    confidence_pct: number(row.querySelector(".bl-confidence")),
  }));
  if (el("robo-bl-custom").checked) {
    body.benchmark_weights = Object.fromEntries([...el("robo-bl-benchmark").querySelectorAll("input")].map(input => [input.dataset.asset, number(input)]));
    if (Math.abs(Object.values(body.benchmark_weights).reduce((a, b) => a + b, 0) - 100) > 1e-7) throw Error("기준 비중의 합계를 100%로 맞추세요.");
  }
  return body;
}

export function restoreAllocationModel(data) {
  if (!el("robo-allocation-model")) return;
  el("robo-allocation-model").value = data.allocation_model || "profile";
  const m = data.asset_model;
  el("robo-bl-views").replaceChildren();
  (m?.views || []).forEach(addView);
  el("robo-bl-custom").checked = m?.benchmark_source === "user";
  if (m?.reference_allocations) el("robo-bl-benchmark").querySelectorAll("input").forEach(input => {
    input.value = m.reference_allocations[input.dataset.asset];
  });
  controls();
  const lines = m ? [`${m.name} · 자료 기준 ${m.as_of} · 공통 수익률 ${m.observations}거래일`, m.method] : ["성향·기간 기준 배분"];
  if (m?.benchmark_note) lines.push(m.benchmark_note);
  if (m?.risk_contribution_pct) lines.push("위험 기여도: " + Object.entries(m.risk_contribution_pct).map(([a, v]) => `${a} ${v}%`).join(" · "));
  if (m?.model === "risk_parity") lines.push(`균등 위험 기여도(25%)와 최대 차이 ${m.risk_parity_max_deviation_pct}%p`);
  if (m?.regime) lines.push(`${m.regime.trend === "up" ? "상승" : "하락"} 추세 · ${m.regime.volatility === "high" ? "고" : "저"}변동 · 기준 주식 비중 × ${m.regime.equity_multiplier}`, m.regime.rule);
  if (m?.proxies) lines.push("자산군 대용 시세: " + Object.values(m.proxies).map(p => p.name).join(" · "));
  el("robo-model-result").textContent = lines.join("\n");
}
