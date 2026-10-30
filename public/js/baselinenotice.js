/* 전략 분석 · 성과 검증 — 탭 띠 + 「기준 전략」 안내 카드 (2026-10-30 · ①-18 · Figma 「Qurious · 전략 분석」 03 설계)
 *
 * 두 화면(전략 분석 · 성과 검증)은 주소 · 메뉴 항목 · 점검표 점수를 그대로 두고 탭 띠로 이어 붙인다(결정 3번).
 * 카드의 숫자는 이 코드에 적지 않는다 — 시험 결과 요약 파일(/js/baseline-result.json)에서 읽는다.
 *   요약 파일은 scripts/baseline_summary.py 가 원본 결과에서 만들고, 시험 TC-BNC 가 같은지 대조한다.
 * 의존이 없어 node 로 그대로 시험한다(판단 함수 = baselineCardModel). 이름은 bn- 으로 시작한다.
 */
export const RESULT_URL = "/js/baseline-result.json";
export const TABS = [
  { view: "quant-backtest", label: "전략 분석" },
  { view: "indicator-backtest", label: "성과 검증 (Python)" },
];

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const minus = (v) => `−${Math.abs(v)}%`;
const th = (v) => (Number.isInteger(v) ? v.toFixed(1) : String(v));   // 합격선 1 → 「1.0」(JS 는 1.0 을 1 로 쓴다)
const fixed = (v, d) => (typeof v === "number" ? v.toFixed(d) : "-");

/* 못 넘은 기준 이름 → 사용자가 읽는 말 */
function missedText(key, line) {
  if (key === "profit_factor") return `이익÷손실이 ${th(line.profit_factor)} 에 못 미쳐`;
  if (key === "mdd_pct") return `최대 낙폭이 ${minus(line.mdd_pct)} 보다 커서`;
  return `샤프가 ${th(line.sharpe_ratio)} 에 못 미쳐`;
}

/* 요약 파일 → 카드가 그릴 값. summary 가 null 이면 「불러오지 못함」. */
export function baselineCardModel(summary) {
  if (!summary || typeof summary !== "object" || !summary.pass_line || !summary.counts) {
    return { state: "error", badge: "확인 못 함", lead: "기준 전략 시험 결과를 불러오지 못했습니다. 아래 분석 기능에는 영향이 없습니다. 잠시 뒤 화면을 새로 고쳐 주세요.", stats: [], near: null, found: [], foot: "" };
  }
  const line = summary.pass_line;
  const n = summary.n_trials;
  const period = summary.period || {};
  const stats = [
    { label: `이익÷손실 ${th(line.profit_factor)} 초과`, value: `${summary.counts.profit_factor} / ${n}`, bad: summary.counts.profit_factor === 0 },
    { label: `최대 낙폭 ${minus(line.mdd_pct)} 이내`, value: `${summary.counts.mdd_pct} / ${n}`, bad: summary.counts.mdd_pct === 0 },
    { label: `샤프 ${th(line.sharpe_ratio)} 초과`, value: `${summary.counts.sharpe_ratio} / ${n}`, bad: summary.counts.sharpe_ratio === 0 },
  ];
  const foot = `${period.start} ~ ${period.end} 일봉(수정주가) · 거래 비용을 뺀 값 · ${period.sealed_from} 이후는 검증용으로 남겨 둔 구간이라 쓰지 않았습니다 · 과거 결과이며 투자 권유가 아닙니다 · ${summary.result_date} 시험`;
  const rule = `합격선 — 이익÷손실(PF) ${th(line.profit_factor)} 초과 · 최대 낙폭 ${minus(line.mdd_pct)} 이내 · 샤프 ${th(line.sharpe_ratio)} 초과 —`;
  const head = `${summary.family} ${summary.n_combos}가지 조합을 종목 ${summary.n_symbols}개에서 모두 시험했습니다(${n}번).`;
  if (summary.passed > 0) {
    return {
      state: "found", badge: "있음",
      lead: `${head} ${rule} 세 가지를 모두 넘은 조합이 ${summary.passed}개 있습니다. 샤프가 높은 순으로 최대 5개를 보입니다.`,
      stats, near: null,
      found: (summary.passed_trials || []).map((t) => ({
        title: `${t.name} · 단기 ${t.short}일 평균선과 장기 ${t.long}일 평균선 교차`,
        values: `이익÷손실 ${fixed(t.profit_factor, 3)} · 최대 낙폭 ${minus(t.mdd_pct)} · 샤프 ${fixed(t.sharpe_ratio, 3)}`,
      })),
      foot,
    };
  }
  let near = null;
  if (summary.nearest) {
    const t = summary.nearest;
    const parts = (t.missed || []).map((k) => missedText(k, line));
    near = {
      label: "가장 가까웠던 시도 — 참고용이며 고른 것이 아닙니다",
      title: `${t.name} · 단기 ${t.short}일 평균선과 장기 ${t.long}일 평균선 교차`,
      values: `이익÷손실 ${fixed(t.profit_factor, 3)} · 최대 낙폭 ${minus(t.mdd_pct)} · 샤프 ${fixed(t.sharpe_ratio, 3)}`,
      reason: parts.length ? `${parts.join(", ")} 합격하지 못했습니다.` : "",
    };
  }
  return { state: "none", badge: "아직 없음", lead: `${head} ${rule} 세 가지를 모두 넘은 조합이 없어 기준 전략을 정하지 못했습니다.`, stats, near, found: [], foot };
}

export function tabsHtml(activeView) {
  const items = TABS.map((t) => {
    const on = t.view === activeView;
    return `<a class="bn-tab${on ? " bn-tab-on" : ""}" href="#${t.view}"${on ? ' aria-current="page"' : ""}>${esc(t.label)}</a>`;
  }).join("");
  return `<nav class="bn-tabs" aria-label="전략 검증 화면">${items}</nav>`;
}

export function cardHtml(m) {
  const tone = m.state === "none" ? "bn-badge-warn" : (m.state === "found" ? "bn-badge-ok" : "bn-badge-mute");
  const stats = m.stats.length
    ? `<div class="bn-stats">${m.stats.map((s) => `<div class="bn-stat"><div class="bn-stat-l">${esc(s.label)}</div><div class="bn-stat-v${s.bad ? " bn-bad" : ""}">${esc(s.value)}</div></div>`).join("")}</div>`
    : "";
  const near = m.near
    ? `<div class="bn-near"><div class="bn-near-l">${esc(m.near.label)}</div><div class="bn-near-t">${esc(m.near.title)}</div><div>${esc(m.near.values)}</div>${m.near.reason ? `<div class="bn-near-r">${esc(m.near.reason)}</div>` : ""}</div>`
    : "";
  const found = m.found.length
    ? `<div class="bn-near">${m.found.map((f) => `<div class="bn-found"><div class="bn-near-t">${esc(f.title)}</div><div>${esc(f.values)}</div></div>`).join("")}</div>`
    : "";
  return `<div class="card bn-card" data-bn-state="${esc(m.state)}">
    <div class="bn-head"><h2 class="bn-title">기준 전략</h2><span class="bn-badge ${tone}">${esc(m.badge)}</span></div>
    <p class="bn-lead">${esc(m.lead)}</p>${stats}${near}${found}${m.foot ? `<p class="bn-foot">${esc(m.foot)}</p>` : ""}
  </div>`;
}

let summaryPromise = null;

/* 요약 파일을 읽는다 — 실패하면 null(카드가 「불러오지 못함」). 실패한 읽기는 다음 번에 다시 시도한다. */
export function loadBaselineSummary(fetchFn = (typeof fetch === "function" ? fetch : null)) {
  if (!summaryPromise) {
    summaryPromise = Promise.resolve()
      .then(() => fetchFn(RESULT_URL, { cache: "no-cache" }))
      .then((r) => (r && r.ok ? r.json() : null))
      .catch(() => null)
      .then((v) => { if (v === null) summaryPromise = null; return v; });
  }
  return summaryPromise;
}

/* 화면에 들어올 때 부른다(main.js) — 탭 띠는 바로, 카드는 읽은 뒤. */
export async function renderBaselineNotice(view, root = document) {
  const mount = root.getElementById ? root.getElementById(`bn-mount-${view}`) : null;
  if (!mount) return;
  mount.innerHTML = `${tabsHtml(view)}<div class="bn-slot"></div>`;
  const summary = await loadBaselineSummary();
  const slot = mount.querySelector(".bn-slot");
  if (slot) slot.innerHTML = cardHtml(baselineCardModel(summary));
}
