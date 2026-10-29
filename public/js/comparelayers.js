/* TradingView ↔ LEAN 대사 결과를 「층별」 로 보이는 판단 — DOM 없이 글 · 표시만 정한다(node 로 시험 · TC-CLY · 2026-10-29 · 화면 벤치마킹 S5 · S6).
 *
 * 왜 — 옛 화면은 서버의 `verdict`(수익률 · MDD 차이 3%p / 10%p → 일치 · 부분 일치)를 맨 위 배지 하나로 보였다. 이슈 원칙은
 * 「수익률 유사성만으로 통과시키지 않는다」 이고 서버 응답에는 이미 층별 결과(`signal_comparison` · `fill_comparison` ·
 * `performance_comparison`)가 있다. 서버(강민석 님 코드)는 그대로 두고 **화면이 층별 응답을 그대로 읽는다.**
 *
 * 규칙
 *   1. 층마다 배지 하나: 신호 · 체결(날짜 · 방향). 성과(수익률 · MDD …)는 배지 없이 「참고」 — 색 기준(3%p / 10%p)도 없앴다.
 *   2. 신호 층은 **정확 일치**(허용 오차 없음 · 이슈 3절 판정 정책). 체결가 · 성과의 허용 오차는 아직 정해지지 않았다 → 「기준 미정」 으로 숫자만.
 *   3. 층 하나로 합친 「검증 통과」 총평 배지를 만들지 않는다 — 층이 엇갈리는 것이 실제 모양이다.
 *   4. 비교하지 않은 층은 빈칸이 아니라 「비교 안 함 — 까닭」(서버 글 그대로). LEAN 이 안 돌고 대체 계산이면 맨 위에 「비교 불가」.
 *   5. 숫자는 응답 값 그대로. 화면이 새로 셈하는 것은 「어긋난 날이 0이고 한쪽에만 있는 날도 0인가」 뿐이다.
 */

const DASH = "—";
const isNum = v => typeof v === "number" && Number.isFinite(v);
const num = (v, d = 1) => (isNum(v) ? String(Number(v.toFixed(d))) : DASH);

export const PERF_NOTE =
  "성과 숫자는 참고로만 보입니다 — 수익률이 비슷하다는 이유만으로 통과로 보지 않으며, 허용 오차는 아직 정해지지 않았습니다(강민석 님 요청 값 대기).";

const BADGE_CLS = { "일치": "badge-buy", "불일치": "badge-sell" };
/** 배지 → CSS 클래스(색) — 일치 · 불일치만 색을 쓰고 나머지는 중립색. */
export const badgeClass = badge => BADGE_CLS[badge] || "badge-hold";

function unavailable(c, label) {
  if (c && c.status === "not_requested") return { badge: "비교 안 함", lines: [c.reason || `${label} 비교를 요청하지 않았습니다.`] };
  return { badge: "비교 불가", lines: [(c && (c.reason || c.message)) || `${label} 비교를 수행하지 못했습니다.`] };
}

/** 신호 층 — 날짜별 진입 · 청산 상태. 정확 일치. */
export function signalLayer(c) {
  const label = "신호";
  if (!c || c.status !== "compared") return { key: "signal", label: "신호(날짜별 진입 · 청산 상태)", ...unavailable(c, label), limit: "" };
  const mism = isNum(c.mismatch_date_count) ? c.mismatch_date_count : 0;
  const only = (c.tradingview_only_date_count || 0) + (c.lean_only_date_count || 0);
  const badge = mism > 0 ? "불일치" : only > 0 ? "겹친 날만 일치" : "일치";
  const lines = [
    `겹친 날짜 ${num(c.matched_date_count, 0)}일 · 어긋난 날 ${num(mism, 0)}일`,
    `진입 상태 일치 ${num(c.entry_match_count, 0)} / ${num(c.entry_compared_count, 0)}` + (isNum(c.entry_match_rate_pct) ? ` (${num(c.entry_match_rate_pct)}%)` : ""),
    `청산 상태 일치 ${num(c.exit_match_count, 0)} / ${num(c.exit_compared_count, 0)}` + (isNum(c.exit_match_rate_pct) ? ` (${num(c.exit_match_rate_pct)}%)` : ""),
  ];
  if (only > 0) lines.push(`한쪽에만 있는 날 — TradingView ${num(c.tradingview_only_date_count, 0)}일 · LEAN ${num(c.lean_only_date_count, 0)}일`);
  const dates = Array.isArray(c.mismatch_dates) ? c.mismatch_dates : [];
  if (dates.length) lines.push(`어긋난 날 ${dates.slice(0, 5).map(d => (typeof d === "string" ? d : d && d.date) || DASH).join(" · ")}${dates.length > 5 ? ` 외 ${dates.length - 5}일` : ""}`);
  return { key: "signal", label: "신호(날짜별 진입 · 청산 상태)", badge, lines, limit: c.alignment_method || "" };
}

/** 체결 층 — 날짜 · 방향은 정확 일치, 체결가 차이는 참고(시점차 · 허용 오차 미정). */
export function fillLayer(c) {
  const label = "체결";
  if (!c || c.status !== "compared") return { key: "fill", label: "체결(날짜 · 방향 · 가격)", ...unavailable(c, label), limit: "" };
  const unT = Array.isArray(c.unmatched_tradingview_events) ? c.unmatched_tradingview_events.length : 0;
  const unL = Array.isArray(c.unmatched_lean_events) ? c.unmatched_lean_events.length : 0;
  const exact = c.date_match_rate_pct === 100 && c.side_match_rate_pct === 100 && unT === 0 && unL === 0;
  const lines = [
    `짝지은 체결 ${num(c.paired_event_count, 0)}건 · 날짜 일치 ${num(c.date_match_rate_pct)}% · 방향 일치 ${num(c.side_match_rate_pct)}%`,
    `짝이 없는 체결 — TradingView ${unT}건 · LEAN ${unL}건`,
  ];
  if (isNum(c.avg_abs_price_diff_bps)) lines.push(`체결가 평균 차이 ${num(c.avg_abs_price_diff_bps, 2)}bp — 참고(체결 시점 차이 포함 · 기준 미정)`);
  return { key: "fill", label: "체결(날짜 · 방향 · 가격)", badge: exact ? "일치" : "불일치", lines, limit: "체결가 허용 오차는 아직 정해지지 않았습니다." };
}

/** 성과 층 — 배지 없이 「참고」. */
export function performanceLayer(c) {
  if (!c || c.status !== "compared") {
    const u = unavailable(c, "성과");
    return { key: "performance", label: "성과(참고)", badge: u.badge, lines: u.lines, limit: PERF_NOTE };
  }
  return { key: "performance", label: "성과(참고)", badge: "참고", lines: ["수익률 · MDD · 거래 횟수 · 승률 · 샤프를 아래 표에 나란히 보입니다."], limit: PERF_NOTE };
}

/** 맨 위 경고 — LEAN 이 안 돌아 대체 계산이면 「비교 불가」(작은 글씨로 두지 않는다). 아니면 null. */
export function banner(r) {
  const lean = r && r.lean;
  if (lean && lean.lean_ok === false) {
    return { badge: "비교 불가", text: "LEAN 엔진이 실행되지 않아 pandas 대체 계산입니다. 아래 층별 결과를 LEAN 과의 비교로 읽지 마세요." };
  }
  return null;
}

/** 층 셋 + 경고. */
export function layersOf(r) {
  return {
    banner: banner(r),
    layers: [signalLayer(r && r.signal_comparison), fillLayer(r && r.fill_comparison), performanceLayer(r && r.performance_comparison)],
  };
}

/** 층 카드들의 HTML — 총평 배지는 없다. */
export function renderLayers(r, esc) {
  const { banner: b, layers } = layersOf(r);
  const head = b ? `<div class="flex flex-wrap items-center gap-2 mb-2"><span class="${badgeClass(b.badge)}">${esc(b.badge)}</span>`
    + `<span class="text-sm">${esc(b.text)}</span></div>` : "";
  const cards = layers.map(l =>
    `<div class="rounded p-3" data-layer="${esc(l.key)}" style="background:var(--bg);">`
    + `<div class="flex items-center gap-2 mb-1"><span class="text-xs font-semibold">${esc(l.label)}</span>`
    + `<span class="${badgeClass(l.badge)}">${esc(l.badge)}</span></div>`
    + l.lines.map(t => `<div class="text-xs">${esc(t)}</div>`).join("")
    + (l.limit ? `<div class="text-xs mt-1" style="color:var(--text-mute);">${esc(l.limit)}</div>` : "")
    + `</div>`).join("");
  return `${head}<div class="grid md:grid-cols-3 gap-2 mb-3">${cards}</div>`;
}
