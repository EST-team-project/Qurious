/* 지표 대시보드 작업 공간 — 구역 이동 단추 · 따라오는 「기업 스냅샷」 · 차트 4장 (D10 · 2026-11-04 · node 로 시험 · TC-CW).
 *
 * 어디서 왔나 — 강사님 lumina-invest 의 `company-dashboard.js` 화면 꼴(구역 점프 · 사이드 스냅샷 · 차트 4장)을 가져왔다.
 * 데이터는 강사님 것(외부 시세 모양 d.quarters / d.revenue …)이 아니라 우리 읽기 길이다 — 이 파일이 새로 부르는 API 는 없다.
 * companyview.js 의 cvLoad 가 받은 응답(parts)을 cvSubscribe 로 함께 받아 쓴다(company.js 는 건드리지 않는다).
 *   parts.fin     /api/data/financials  periods[].key · accounts — 서버가 계정 이름을 묶어 준 요약(key)을 먼저 쓴다
 *   parts.ind     /api/data/indicators  PER · PBR · ROE · 영업이익률 · 배당수익률 · 종가 · 시가총액
 *   parts.health  /api/risk/company     부채비율
 *
 * 규칙(화면은 값을 계산하지 않는다 — 지표 대시보드 설계 결정 ① 안 A)
 *   1. 차트의 series 에는 서버가 준 숫자를 그대로 넣는다. 합 · 차 · 비율 · 환산이 없다. 조 · 억 글은 표시 함수(formatter)에서만 바꾼다.
 *   2. 분기 막대는 1분기 · 반기 · 3분기 보고서의 3개월 값만 쓴다(서버 note: 분기 · 반기 amount 는 그 3개월 값, cumulative 는 누적).
 *      사업보고서 amount 는 12개월 값이라 같은 축에 두면 해마다 4배쯤 튀어 오르고, 4분기 단독 값은 보고서에 없어
 *      연간 − 3분기 누적으로 만들면 화면이 셈하는 것이 되므로 이어 붙이지 않는다(연간 값은 아래 분기 실적 표에 있다).
 *   3. 없는 값은 null 로 둔다(0 으로 채우지 않는다). 막대가 없는 까닭은 칸 안에 글로 적는다.
 *   4. 도넛은 서버의 부채총계 · 자본총계만 쓴다. 가운데 합계는 서버의 자산총계를 그대로 보이고(부채 + 자본을 더하지 않는다),
 *      조각 비율(%) 글자는 달지 않는다. 자본이 0 이하(자본잠식)면 그리지 않는다.
 *   5. 수익성 막대는 서버가 계산한 ROE · 영업이익률만 쓴다(ROA · 순이익률은 서버가 주지 않아 그리지 않는다 — 화면이 셈하지 않는다).
 *   6. 숫자마다 기준일 · 출처를 글로 붙인다. 판단 낱말(우수 · 적기 · 저평가 …)과 투자 권유 문장은 쓰지 않는다.
 *
 * 이 파일은 company.js 가 채우는 칸(co-overview · co-quarterly …)에 쓰지 않는다 — 자기 칸(cw-*)만 채운다.
 */
import { cvSubscribe, cvValueText, basisText } from "./companyview.js";
import { wonText, accountMap, latestPeriod } from "./fundview.js";

const DASH = "—";
const isNum = v => typeof v === "number" && Number.isFinite(v);
const QUARTER_NAME = { "1분기보고서": "1분기(3개월)", "반기보고서": "반기(3개월)", "3분기보고서": "3분기(3개월)" };
export const CW_QUARTER_REPORTS = Object.keys(QUARTER_NAME);
export const CW_PROFIT_KEYS = ["roe", "operating_margin"];
export const CW_COLORS = { blue: "#2563eb", orange: "#ea580c", text: "#334155", mute: "#5b6b82", grid: "#dde2ec" };   // 앱의 --accent · --text-dim · --text-mute · --border 와 같은 값(차트 안은 CSS 변수를 못 읽는다)

// 서버 key 칸이 없는 응답(옛 캐시)에서 같은 이름의 계정을 찾을 때 쓴다 — data_financials.py KEY 와 같은 이름들. 찾기만 하고 셈하지 않는다.
const ACCOUNT_NAMES = {
  revenue: ["IS", ["매출액", "수익(매출액)", "영업수익"]],
  operating_income: ["IS", ["영업이익", "영업이익(손실)"]],
  net_income: ["IS", ["당기순이익(손실)", "당기순이익"]],
  assets: ["BS", ["자산총계"]], liabilities: ["BS", ["부채총계"]], equity: ["BS", ["자본총계"]],
};

// ── 표시 글(단위 글만 바꾼다) ─────────────────────────────────────────────
/** 축 눈금 글 — 1조 이상 「171.5조」 · 1억 이상 「3,389억」. 값은 바꾸지 않고 읽기 좋게만 쓴다. */
export function cwAxisText(n) {
  if (!isNum(n)) return DASH;
  const sign = n < 0 ? "−" : "";
  const a = Math.abs(n);
  if (a >= 1e12) return `${sign}${+(a / 1e12).toFixed(1)}조`;       // 눈금이 180.0조 로 보이지 않게 뒤의 0 을 뗀다(표시만)
  if (a >= 1e8) return `${sign}${Math.round(a / 1e8).toLocaleString("ko-KR")}억`;
  return `${sign}${a.toLocaleString("ko-KR")}`;
}

/** 「2026-06-30 …」 → 「26.06」 (막대 아래 글 · 자세한 이름은 마우스를 올리면 보인다). */
export function cwShortDate(label) {
  const m = /^(\d{4})-(\d{2})/.exec(String(label || ""));
  return m ? `${m[1].slice(2)}.${m[2]}` : String(label || "");
}

// ── 어댑터(서버 응답 → 차트 입력, 재배열만) ─────────────────────────────────
/** 한 기간의 계정 값 — 서버 key 요약이 있으면 그 값, 없을 때만 계정 목록에서 같은 이름을 찾는다. 없으면 null. */
export function cwPeriodValue(period, field) {
  if (!period) return null;
  const key = period.key;
  if (key && typeof key === "object" && field in key) return isNum(key[field]) ? key[field] : null;
  const spec = ACCOUNT_NAMES[field];
  if (!spec) return null;
  const map = accountMap(period.accounts);
  for (const name of spec[1]) {
    const a = map[`${spec[0]}|${name}`];
    if (a && isNum(a.amount)) return a.amount;
  }
  return null;
}

export const cwHasValues = arr => Array.isArray(arr) && arr.some(isNum);

/** 분기 막대 입력 — 3개월 보고서(1분기 · 반기 · 3분기)만 · 오래된 쪽이 왼쪽. series 값은 서버 값 그대로(없으면 null). */
export function cwQuarterSeries(fin) {
  const all = fin && Array.isArray(fin.periods) ? fin.periods : [];
  const quarters = all.filter(p => p && p.period_end && CW_QUARTER_REPORTS.includes(p.report))
    .slice().sort((a, b) => String(a.period_end).localeCompare(String(b.period_end)));
  const meta = quarters.map(p => ({ period_end: p.period_end, report: p.report, known_at: p.known_at || "", label: `${p.period_end} ${QUARTER_NAME[p.report]}` }));
  return {
    categories: meta.map(m => m.label),
    meta,
    revenue: quarters.map(p => cwPeriodValue(p, "revenue")),
    operating: quarters.map(p => cwPeriodValue(p, "operating_income")),
    net: quarters.map(p => cwPeriodValue(p, "net_income")),
    total: all.length,
    skippedAnnual: all.filter(p => p && p.report === "사업보고서").length,
  };
}

/** 도넛 입력 — 가장 최근 기간의 부채총계 · 자본총계(자산총계는 서버 값을 가운데 글로만). 그릴 수 없으면 까닭. */
export function cwStructure(fin) {
  const row = latestPeriod(fin);
  if (!row) return { ok: false, reason: "이 종목의 재무제표 자료가 없습니다." };
  const equity = cwPeriodValue(row, "equity"), liabilities = cwPeriodValue(row, "liabilities"), assets = cwPeriodValue(row, "assets");
  const base = { period_end: row.period_end, report: row.report || "", known_at: row.known_at || "", equity, liabilities, assets };
  if (!isNum(equity) || !isNum(liabilities)) return { ...base, ok: false, reason: "가장 최근 보고서에 자본총계 또는 부채총계가 없어 그리지 않습니다." };
  if (equity <= 0) return { ...base, ok: false, reason: `자본총계가 ${wonText(equity)}(0 이하 · 자본잠식 등)라 구성 도넛을 그리지 않습니다. 금액은 아래 재무상태 표에 있습니다.` };
  if (liabilities < 0) return { ...base, ok: false, reason: "부채총계가 음수로 와서 구성 도넛을 그리지 않습니다." };
  return { ...base, ok: true };
}

const findMetric = (ind, key) => (ind && Array.isArray(ind.metrics) ? ind.metrics.find(m => m && m.key === key) : null);

/** 수익성 막대 입력 — 서버가 계산한 ROE · 영업이익률 가운데 값이 있는 것만. 없는 것은 까닭과 함께 missing 으로. */
export function cwProfitBars(ind) {
  const bars = [], missing = [];
  for (const key of CW_PROFIT_KEYS) {
    const m = findMetric(ind, key);
    if (!m) continue;
    if (isNum(m.value)) bars.push({ key, label: m.label || key, value: m.value, unit: m.unit || "%", approx: !!m.approx, formula: m.formula || "", basis: basisText(m.basis), sentence: m.sentence || "" });
    else missing.push({ key, label: m.label || key, reason: m.reason || m.sentence || "계산하지 않았습니다." });
  }
  return { bars, missing };
}

// ── 차트 옵션(ApexCharts 3.49 — 새 라이브러리 없음) ─────────────────────────
function baseOptions(type) {
  return {
    chart: { type, height: 240, fontFamily: "inherit", foreColor: CW_COLORS.text, background: "transparent", toolbar: { show: false }, animations: { enabled: false }, zoom: { enabled: false } },
    dataLabels: { enabled: false },
    grid: { borderColor: CW_COLORS.grid, strokeDashArray: 3 },
    legend: { position: "bottom", fontSize: "12px", labels: { colors: CW_COLORS.text } },
    noData: { text: "제공된 데이터가 없습니다." },
  };
}

function quarterBarOptions(series, seriesList, colors) {
  return {
    ...baseOptions("bar"),
    series: seriesList,
    colors,
    plotOptions: { bar: { borderRadius: 3, columnWidth: "55%" } },
    xaxis: { categories: series.categories, labels: { formatter: v => cwShortDate(v), style: { fontSize: "11px", colors: CW_COLORS.mute }, hideOverlappingLabels: true } },
    yaxis: { labels: { formatter: v => cwAxisText(v), style: { fontSize: "11px", colors: CW_COLORS.mute } } },
    tooltip: { theme: "light", y: { formatter: v => (isNum(v) ? wonText(v) : DASH) } },
  };
}

/** 매출액 막대 — 3개월 보고서의 매출액(서버 key.revenue 그대로). */
export function cwRevenueOptions(series) {
  return quarterBarOptions(series, [{ name: "매출액(3개월)", data: series.revenue }], [CW_COLORS.blue]);
}

/** 영업이익 · 당기순이익 막대 — 서버 key.operating_income · key.net_income 그대로. */
export function cwIncomeOptions(series) {
  return quarterBarOptions(series, [{ name: "영업이익(3개월)", data: series.operating }, { name: "당기순이익(3개월)", data: series.net }], [CW_COLORS.blue, CW_COLORS.orange]);
}

/** 부채 · 자본 도넛 — 조각 비율 글자 없음 · 가운데는 서버의 자산총계. */
export function cwStructureOptions(st) {
  const values = [st.liabilities, st.equity];
  return {
    ...baseOptions("donut"),
    series: values,
    labels: ["부채총계", "자본총계"],
    colors: [CW_COLORS.orange, CW_COLORS.blue],
    stroke: { width: 2, colors: ["#ffffff"] },
    legend: { position: "bottom", fontSize: "12px", labels: { colors: CW_COLORS.text }, formatter: (name, o) => `${name} ${wonText(values[o.seriesIndex])}` },
    plotOptions: { pie: { donut: { size: "62%", labels: {
      show: true,
      name: { show: true, fontSize: "12px", color: CW_COLORS.text },
      value: { show: true, fontSize: "14px", color: CW_COLORS.text, formatter: v => wonText(Number(v)) },
      total: { show: isNum(st.assets), label: "자산총계", fontSize: "12px", color: CW_COLORS.text, formatter: () => wonText(st.assets) },
    } } } },
    tooltip: { theme: "light", y: { formatter: v => wonText(v) } },
  };
}

/** 수익성 막대 — 서버가 계산한 ROE · 영업이익률(사업보고서 기준). */
export function cwProfitOptions(bars) {
  return {
    ...baseOptions("bar"),
    series: [{ name: "수익성(%)", data: bars.map(b => b.value) }],
    colors: [CW_COLORS.blue],
    legend: { show: false },
    // 값 글은 짙은 알약 위의 흰 글자 — 막대가 짧아 글이 막대 밖으로 나가도 읽힌다
    dataLabels: { enabled: true, formatter: v => `${v}%`, style: { fontSize: "12px", colors: ["#ffffff"] }, background: { enabled: true, foreColor: "#0f172a", padding: 4, borderRadius: 3, borderWidth: 0, opacity: 1 } },
    plotOptions: { bar: { horizontal: true, borderRadius: 3, barHeight: "42%", dataLabels: { position: "top" } } },
    xaxis: { categories: bars.map(b => b.label), labels: { formatter: v => `${v}%`, style: { fontSize: "11px", colors: CW_COLORS.mute } } },
    yaxis: { labels: { style: { fontSize: "12px", colors: CW_COLORS.text } } },
    tooltip: { theme: "light", y: { formatter: v => `${v}%` } },
  };
}

// ── 글(차트 밑 요약 · 빈 칸 까닭 · 출처 줄 · 스냅샷) ───────────────────────────
const MSG_UNSUPPORTED = "이 화면은 국내 상장사(종목코드 6자리)의 전자공시 재무로 지표를 계산합니다. 이 종목은 지원하지 않습니다.";

/** 분기 막대 밑 한 줄 — 마지막 3개월 값과 기준 · 접수일. 그림이 못 읽어 주는 값을 글로. */
export function cwQuarterSummary(series, field, label) {
  const arr = series[field] || [];
  for (let i = arr.length - 1; i >= 0; i--) {
    if (isNum(arr[i])) {
      const m = series.meta[i];
      return `${label} 가장 최근 ${m.label} ${wonText(arr[i])} · 공시 접수 ${m.known_at || DASH} · 막대 ${arr.length}개(1분기 · 반기 · 3분기 보고서의 3개월 값)`;
    }
  }
  return "";
}

/** 분기 막대가 비는 까닭 — 응답에 따라 가장 알맞은 글 하나. 그릴 수 있으면 빈 글. */
export function cwQuarterEmpty(parts, series, field, label) {
  if (parts.unsupported) return MSG_UNSUPPORTED;
  if (parts.finErr) return parts.finErr.message || "재무제표를 받지 못했습니다.";
  if (!parts.fin || !series.total) return "이 종목의 재무제표 자료가 없습니다.";
  if (!series.categories.length) return "받은 보고서가 사업보고서(12개월 값)뿐이라 3개월 막대를 그리지 않습니다. 연간 값은 아래 분기 실적 표에 있습니다.";
  if (!cwHasValues(series[field])) return `이 종목의 보고서에는 ${label} 항목이 없습니다(금융회사 등) — 서버가 준 값이 없어 그리지 않습니다.`;
  return "";
}

/** 도넛 밑 글 — 기준 보고서와 서버의 세 금액 · 서버가 준 부채비율(있으면). */
export function cwStructureSummary(st, health) {
  if (!st.ok) return "";
  const debt = health && Array.isArray(health.metrics) ? health.metrics.find(m => m && m.key === "debt_ratio") : null;
  const lines = [`${st.period_end} 기준 ${st.report} · 공시 접수 ${st.known_at || DASH} · 부채총계 ${wonText(st.liabilities)} · 자본총계 ${wonText(st.equity)} · 자산총계 ${wonText(st.assets)}`];
  if (debt && isNum(debt.value)) {
    const how = [debt.formula, basisText(debt.basis)].filter(Boolean).join(" · ");
    lines.push(`서버가 준 부채비율 ${cvValueText(debt)}${how ? ` — ${how}` : ""}`);
  }
  return lines.join("\n");
}

/** 수익성 막대 밑 글 — 막대마다 식 · 기준(서버 글) · 근사면 한계 · 값이 없는 지표는 까닭. */
export function cwProfitSummary(pb) {
  const lines = pb.bars.map(b => `${b.label} ${cvValueText({ value: b.value, unit: b.unit, approx: b.approx })} — ${[b.formula, b.basis].filter(Boolean).join(" · ") || "식 · 기준 미기록"}${b.approx && b.sentence ? ` (${b.sentence})` : ""}`);
  for (const m of pb.missing) lines.push(`${m.label} — ${m.reason}`);
  return lines.join("\n");
}

/** 수익성 막대가 비는 까닭. */
export function cwProfitEmpty(parts, pb) {
  if (parts.unsupported) return MSG_UNSUPPORTED;
  if (parts.indErr) return parts.indErr.message || "지표를 받지 못했습니다.";
  if (!parts.ind) return "지표 자료가 없습니다.";
  if (!pb.bars.length) return "서버가 ROE · 영업이익률을 계산하지 못해 그리지 않습니다. 까닭은 아래에 있습니다.";
  return "";
}

/** 차트 구역 아래 출처 · 기준일 줄들. */
export function cwSourceLines(parts) {
  const out = [];
  if (!parts || parts.unsupported) return out;
  const fin = parts.fin;
  const periods = fin && Array.isArray(fin.periods) ? fin.periods : [];
  if (periods.length) {
    const ends = periods.map(p => p.period_end).filter(Boolean).sort();
    const known = periods.map(p => p.known_at).filter(Boolean).sort();
    out.push(`실적 · 재무구조 출처: ${fin.source || "전자공시(DART)"} · 받은 보고서 ${periods.length}개(기준 ${ends[0]} ~ ${ends[ends.length - 1]}) · 공시 접수 ${known[known.length - 1] || DASH} 까지.`);
    out.push("실적 막대는 1분기 · 반기 · 3분기 보고서의 3개월 값입니다. 4분기 단독 값은 보고서에 없어 연간 값에서 빼서 만들지 않았고, 연간 값은 아래 분기 실적 표에 있습니다. 값이 없는 곳은 0으로 채우지 않고 비워 둡니다.");
  }
  if (parts.ind && Array.isArray(parts.ind.metrics)) {
    out.push("수익성 막대는 서버가 계산한 ROE · 영업이익률이며 사업보고서 기준입니다. ROA · 순이익률은 서버가 주지 않아 그리지 않았습니다. 화면은 값을 다시 계산하지 않습니다.");
  }
  out.push("정보 제공용이며 투자 권유가 아닙니다.");
  return out;
}

/** 스냅샷 한 줄 입력 — 이름 · 값 · 그 밑 근거(기준일 · 출처). 서버 값 그대로 · 없으면 줄표와 까닭. */
function snapRow(key, label, m) {
  if (!m) return { key, label, value: DASH, sub: "서버가 이 지표를 주지 않았습니다." };
  const sub = isNum(m.value)
    ? [basisText(m.basis), m.approx ? "근사" : ""].filter(Boolean).join(" · ")
    : (m.reason || m.sentence || "계산하지 않았습니다.");
  return { key, label: m.label || label, value: cvValueText(m), sub };
}

export function cwSnapshotRows(parts) {
  const ind = parts && parts.ind, health = parts && parts.health;
  const rows = [];
  const px = ind && ind.price;
  rows.push(px && isNum(px.close)
    ? { key: "close", label: "종가", value: `${Math.round(px.close).toLocaleString("ko-KR")}원`, sub: px.note || `${px.trade_date || DASH} 마지막 종가` }
    : { key: "close", label: "종가", value: DASH, sub: "종가 자료가 없습니다." });
  rows.push(px && isNum(px.market_cap)
    ? { key: "market_cap", label: "시가총액", value: wonText(px.market_cap), sub: `${px.trade_date || DASH} 종가 기준 · 보통주만(우선주 제외)` }
    : { key: "market_cap", label: "시가총액", value: DASH, sub: "종가 자료가 없습니다." });
  for (const [key, label] of [["per", "PER"], ["pbr", "PBR"], ["roe", "ROE"], ["operating_margin", "영업이익률"], ["dividend_yield", "배당수익률"]]) {
    rows.push(snapRow(key, label, findMetric(ind, key)));
  }
  const debt = health && Array.isArray(health.metrics) ? health.metrics.find(m => m && m.key === "debt_ratio") : null;
  if (debt) rows.push(snapRow("debt_ratio", "부채비율", debt));
  const row = latestPeriod(parts && parts.fin);
  rows.push(row
    ? { key: "fin_basis", label: "재무 기준", value: row.period_end, sub: `${row.report || ""} · 공시 접수 ${row.known_at || DASH}`.trim() }
    : { key: "fin_basis", label: "재무 기준", value: DASH, sub: "재무제표 자료가 없습니다." });
  return rows;
}

/** 기업 스냅샷 HTML — esc 는 화면이 넘겨 준다(서버 글은 모두 이스케이프). */
export function cwSnapshotHtml(parts, esc) {
  if (!parts) return "";
  if (parts.unsupported) return `<p class="cw-snap-note">${esc(MSG_UNSUPPORTED)}</p>`;
  if (parts.indErr && !parts.fin) return `<p class="cw-snap-note">${esc(parts.indErr.message || "지표를 받지 못했습니다.")}</p>`;
  const name = (parts.ind && parts.ind.name) || parts.code || "";
  const head = `<div class="cw-snap-id"><strong>${esc(name)}</strong><span>${esc(parts.code || "")}</span></div>`;
  const rows = cwSnapshotRows(parts).map(r =>
    `<div class="cw-snap-row" data-cw-snap="${esc(r.key)}"><span class="cw-snap-k">${esc(r.label)}</span><b class="cw-snap-v">${esc(r.value)}</b><div class="cw-snap-sub">${esc(r.sub)}</div></div>`).join("");
  return `${head}<div class="cw-snap">${rows}</div>`
    + `<p class="cw-snap-note">값은 서버가 계산해 준 그대로이며 화면은 다시 계산하지 않습니다. 출처 전자공시(DART) 재무 · 수집 일봉 종가. 정보 제공용이며 투자 권유가 아닙니다.</p>`;
}

// ── 화면 연결(브라우저에서만) ──────────────────────────────────────────────
const state = { latest: "", parts: null, charts: [] };

function byId(id) { return typeof document !== "undefined" ? document.getElementById(id) : null; }
function setText(id, text) { const el = byId(id); if (el) el.textContent = text || ""; }
const escHtml = s => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
const VIZ = ["revenue", "income", "structure", "profit"];

function destroyCharts() {
  for (const c of state.charts) { try { c.destroy(); } catch (_) { /* 이미 지워진 차트 */ } }
  state.charts = [];
}

function setViz(name, message) {
  const el = byId(`cw-chart-${name}`);
  if (el) el.innerHTML = message ? `<div class="cw-empty">${escHtml(message)}</div>` : "";
}

function drawChart(name, options) {
  const el = byId(`cw-chart-${name}`);
  if (!el) return;
  if (typeof window === "undefined" || !window.ApexCharts) { setViz(name, "차트 라이브러리를 불러오지 못했습니다. 아래 표의 값을 확인하세요."); return; }
  el.innerHTML = "";
  try {
    const chart = new window.ApexCharts(el, options);
    state.charts.push(chart);
    chart.render().catch(() => setViz(name, "차트를 그리지 못했습니다. 아래 표의 값을 확인하세요."));
  } catch (_) { setViz(name, "차트를 그리지 못했습니다. 아래 표의 값을 확인하세요."); }
}

function showLoading() {
  destroyCharts();
  VIZ.forEach(n => { setViz(n, "불러오는 중…"); setText(`cw-sum-${n}`, ""); });
  setText("cw-chart-source", "");
  const snap = byId("cw-snapshot");
  if (snap) snap.innerHTML = `<p class="cw-snap-note">불러오는 중…</p>`;
}

/** 응답 하나로 작업 공간 전체를 다시 그린다. 칸이 숨겨져 있으면(다른 화면) 글만 채우고 차트는 다음에 이 화면을 열 때 그린다. */
export function cwRender(parts) {
  const root = byId("cw-root");
  if (!root || !parts) return;
  destroyCharts();
  const snap = byId("cw-snapshot");
  if (snap) snap.innerHTML = cwSnapshotHtml(parts, escHtml);
  const src = byId("cw-chart-source");
  if (src) src.innerHTML = cwSourceLines(parts).map(l => `<p>${escHtml(l)}</p>`).join("");

  const series = cwQuarterSeries(parts.fin);
  const st = cwStructure(parts.fin);
  const pb = cwProfitBars(parts.ind);
  const visible = !!root.offsetParent;

  const plan = [
    ["revenue", cwQuarterEmpty(parts, series, "revenue", "매출액"), () => cwRevenueOptions(series), cwQuarterSummary(series, "revenue", "매출액")],
    ["income", cwQuarterEmpty(parts, series, "operating", "영업이익") && cwQuarterEmpty(parts, series, "net", "당기순이익"),
      () => cwIncomeOptions(series),
      [["operating", "영업이익"], ["net", "당기순이익"]].map(([f, l]) => cwQuarterSummary(series, f, l) || cwQuarterEmpty(parts, series, f, l)).filter(Boolean).join("\n")],
    ["structure", parts.unsupported ? MSG_UNSUPPORTED : parts.finErr ? (parts.finErr.message || "재무제표를 받지 못했습니다.") : (st.ok ? "" : st.reason),
      () => cwStructureOptions(st), cwStructureSummary(st, parts.health)],
    ["profit", cwProfitEmpty(parts, pb), () => cwProfitOptions(pb.bars), cwProfitSummary(pb)],
  ];
  for (const [name, empty, options, summary] of plan) {
    setText(`cw-sum-${name}`, summary);
    const box = byId(`cw-chart-${name}`);
    if (box) box.setAttribute("aria-label", `${{ revenue: "매출액 추이", income: "영업이익 · 당기순이익 추이", structure: "부채 · 자본 구성", profit: "수익성 지표" }[name]} 차트. ${(empty || summary || "").replace(/\n/g, " ")}`);
    if (empty) { setViz(name, empty); continue; }
    if (!visible) { setViz(name, ""); continue; }
    drawChart(name, options());
  }
}

function onLoadEvent(evt) {
  if (!evt) return;
  try {
    if (evt.phase === "start") { state.latest = evt.symbol; showLoading(); return; }
    if (evt.phase === "done") {
      if (state.latest && evt.symbol !== state.latest) return;       // 더 늦게 고른 종목이 있으면 이 응답은 버린다(탭을 빨리 바꾸면 응답이 뒤집혀 올 수 있다)
      state.parts = evt.parts;
      cwRender(evt.parts);
    }
  } catch (_) { /* 작업 공간 오류가 본 화면을 막지 않는다 */ }
}

function onNavClick(ev) {
  const btn = ev.target && ev.target.closest ? ev.target.closest("[data-cw-target]") : null;
  if (!btn || !btn.closest("#cw-root")) return;
  const target = byId(btn.dataset.cwTarget);
  if (!target) return;
  document.querySelectorAll("#cw-root [data-cw-target]").forEach(b => {
    b.classList.toggle("active", b === btn);
    b.setAttribute("aria-current", b === btn ? "true" : "false");
  });
  const calm = typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  target.scrollIntoView({ behavior: calm ? "auto" : "smooth", block: "start" });
}

if (typeof document !== "undefined") {
  cvSubscribe(onLoadEvent);
  document.addEventListener("click", onNavClick);
}
