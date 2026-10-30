/* 기업 지표 화면 판단(지표 대시보드) — DOM 없이 글 · 표시만 정한다(node 로 시험 · TC-CV · 2026-10-30 · 할 일 ①-16).
 *
 * 왜 따로 두나 — 이 화면의 클릭 · 차트 그리기는 company.js 에 있고, 숫자를 어떻게 글로 옮기는지는 여기 한 곳에 둔다(fundview.js 와 같은 방식).
 *
 * 무엇을 바꿨나 — 옛 화면은 야후 파이낸스 재무 요약을 그대로 그려, 삼성전자가 EPS · BPS · PBR · 영업이익 N/A 에 PER 3.11 · ROE 30.79 처럼
 * 우리 전자공시 값(PER 35.1 · ROE 10.4)과 다른 숫자를 냈고 숫자마다 기준 기간 · 기준일이 없었다. 지금은 읽기 길 다섯만 쓴다.
 *   /api/data/indicators   PER · PBR · ROE · EPS · 영업이익률 · 배당 — 값마다 식 · 기준 기간 · 공시 접수일 · 종가 날짜(서버가 글까지 준다)
 *   /api/data/financials   DART 주요계정 — 분기 실적 · 재무상태 표
 *   /api/risk/company      재무 건전성(부채비율)
 *   /api/quote/now         현재가(지연 시세 약 20분 · 시각 라벨)
 *   /api/data/ohlcv        일봉 종가(우리 수집 일봉 · 가격 차트)
 *
 * 규칙(설계 결정 ① 안 A · 2026-10-30)
 *   1. 숫자는 응답에 있는 값만. 없으면 줄표와 서버 까닭. 화면이 값을 셈하지 않는다(단위 글만 바꾼다).
 *   2. 숫자 바로 밑에 근거 한 줄(식 · 기준 기간 · 공시 접수일 · 종가 날짜). 근사 · 한계는 한 줄 더.
 *   3. 종가는 「종가」 라 부르고 「현재 주가」 라 하지 않는다 · 현재가 카드만 지연 시세 라벨을 단다.
 *   4. 차트는 일봉 종가(저장 자료)다 — 초 단위 실시간이 아니다. 그 사실을 차트 아래 글로 밝힌다.
 */
import { wonText, accountMap, latestPeriod } from "./fundview.js";

const DASH = "—";
const isNum = v => typeof v === "number" && Number.isFinite(v);
const SHORT_REPORT = { "사업보고서": "연간", "반기보고서": "반기(3개월)", "1분기보고서": "1분기(3개월)", "3분기보고서": "3분기(3개월)" };
export const CV_PERIODS = { "1m": 31, "3m": 92, "6m": 183, "1y": 366 };

/** 지표 값 글 — 값 · 단위 · (근사). 없으면 줄표. */
export function cvValueText(m) {
  if (!m || !isNum(m.value)) return DASH;
  const unit = m.unit || "";
  const num = unit === "원" ? Math.round(m.value).toLocaleString("ko-KR") : String(m.value);
  return `${num}${unit}${m.approx ? " (근사)" : ""}`;
}

/** 기준 글 — 서버가 글(기업 지표)로도, 기간 묶음(재무 건전성의 {period_end · report})으로도 준다. */
function basisText(b) {
  if (!b) return "";
  if (typeof b === "string") return b;
  return [b.period_end ? `${b.period_end} 기준` : "", b.report || ""].filter(Boolean).join(" ");
}

/** 숫자 밑 근거 줄들 — 값이 없으면 까닭 · 있으면 식 · 기준 · 근사면 한계 문장 한 줄 더. */
export function cvBasisLines(m) {
  if (!m) return [];
  if (!isNum(m.value)) return [m.reason || m.sentence || "계산하지 않았습니다."];
  const lines = [[m.formula, basisText(m.basis)].filter(Boolean).join(" · ")];
  if (m.approx && m.sentence) lines.push(m.sentence);
  return lines;
}

const small = (s, esc) => `<div class="text-xs" style="color:var(--text-mute);line-height:1.55;">${esc(s)}</div>`;

/** 상자 안 한 줄 — 이름 · 값 · 그 밑 근거. */
export function cvMetricRow(m, esc) {
  return `<div data-cv-metric="${esc(m.key || "")}" style="padding:8px 0;border-bottom:1px solid var(--border);">`
    + `<div class="flex justify-between items-center"><span style="font-size:12px;color:var(--text-dim);">${esc(m.label || m.key || DASH)}</span>`
    + `<span style="font-size:13px;font-weight:600;">${esc(cvValueText(m))}</span></div>`
    + cvBasisLines(m).map(l => small(l, esc)).join("") + `</div>`;
}

/** 개요 카드 하나. */
export function cvCard(label, valueText, lines, esc, subColor, extraHtml = "") {
  return `<div class="card" style="padding:16px;"><div class="text-xs" style="color:var(--text-mute);">${esc(label)}</div>`
    + `<div style="font-size:20px;font-weight:700;margin:4px 0;">${esc(valueText)}</div>`
    + (lines || []).filter(Boolean).map(l => `<div class="text-xs" style="color:${subColor || "var(--text-mute)"};line-height:1.55;">${esc(l)}</div>`).join("")
    + extraHtml
    + `</div>`;
}

// ── 현재가 — 내 증권사 키 방식(2026-10-30 사용자 결정 「주식은 내 키 방식으로 일단 · 확장 설계까지」 · 설계 Figma 「Qurious · 기업 지표」 03) ──
// 국내 주식은 거래소(코스콤) 계약이 없어 공유 키로 모든 사용자에게 실시간을 줄 수 없다(KIS 약관 제5조③). 본인 KIS 키가 마이페이지에 연결된 사람만
// 자기 화면에서 증권사 시세를 보고(quote.source === "kis_user"), 그 값은 약 10초마다 다시 받는다. 「실시간」 이라는 낱말은 쓰지 않는다(체결마다가 아니라 10초 저장본).
export const CV_QUOTE_POLL_MS = 10000;
export const CV_KEY_CTA = "내 증권사를 연결하면 이 화면에서 지금 시세를 볼 수 있어요(마이페이지 › 증권사).";
/** 내 증권사 키로 받은 값인가 — 이 값만 오늘 점으로 차트에 더하고 10초마다 다시 받는다. */
export function cvQuoteLive(quote) { return !!(quote && quote.source === "kis_user" && isNum(quote.price)); }

const find = (map, st, name) => {
  if (`${st}|${name}` in map) return map[`${st}|${name}`];
  const k = Object.keys(map).find(x => x.startsWith(`${st}|${name}`));
  return k ? map[k] : null;
};
const metricOf = (ind, key) => (ind && Array.isArray(ind.metrics) ? ind.metrics.find(m => m.key === key) : null);

/** 개요 카드 넷 — 현재가(지연 시세) · 시가총액(종가 기준) · 종가 · EPS. */
export function cvOverviewCards(ind, quote, esc) {
  const out = [];
  if (quote && isNum(quote.price)) {
    const chg = isNum(quote.change_pct) ? `${quote.change_pct >= 0 ? "+" : ""}${quote.change_pct.toFixed(2)}%` : "";
    const live = cvQuoteLive(quote);
    const every = live && quote.market_state !== "closed" ? "약 10초마다 갱신" : "";      // 장이 닫혔으면 다시 받지 않는다
    const cta = live ? "" : `<div class="text-xs" style="color:var(--accent);line-height:1.55;margin-top:4px;" data-co-key-cta>${esc(CV_KEY_CTA)}</div>`;
    out.push(cvCard("현재가", `${Math.round(quote.price).toLocaleString("ko-KR")}원`, [[chg, quote.label, every].filter(Boolean).join(" · ")], esc,
      isNum(quote.change_pct) && quote.change_pct < 0 ? "var(--red)" : "var(--green)", cta));
  } else {
    out.push(cvCard("현재가", DASH, ["지금 가격을 받지 못했습니다."], esc));
  }
  const px = ind && ind.price;
  out.push(px && isNum(px.market_cap)
    ? cvCard("시가총액", wonText(px.market_cap), [`${px.trade_date} 종가 기준 · 보통주만(우선주 제외)`], esc)
    : cvCard("시가총액", DASH, ["종가 자료가 없습니다."], esc));
  out.push(px && isNum(px.close)
    ? cvCard("종가", `${Math.round(px.close).toLocaleString("ko-KR")}원`, [px.note], esc)
    : cvCard("종가", DASH, ["종가 자료가 없습니다."], esc));
  const eps = metricOf(ind, "eps");
  out.push(cvCard(eps ? eps.label : "주당이익(EPS)", cvValueText(eps), cvBasisLines(eps), esc));
  return out.join("");
}

/** 밸류에이션 · 수익성 상자 안 줄들 — 서버가 준 지표를 정해 둔 차례로. health 는 부채비율 한 줄만 더한다. */
export function cvValuationRows(ind, esc) {
  return ["per", "pbr", "dividend_yield"].map(k => metricOf(ind, k)).filter(Boolean).map(m => cvMetricRow(m, esc)).join("");
}
export function cvProfitRows(ind, health, esc) {
  const rows = ["roe", "operating_margin"].map(k => metricOf(ind, k)).filter(Boolean);
  const debt = health && Array.isArray(health.metrics) ? health.metrics.find(m => m.key === "debt_ratio") : null;
  if (debt) rows.push(debt);
  return rows.map(m => cvMetricRow(m, esc)).join("");
}

/** 분기 실적 표 — 최근 네 기간(오래된 쪽이 왼쪽) · 값은 보고서 기간 값 그대로(분기 · 반기는 3개월, 사업보고서는 연간). */
export function cvQuarterTable(fin, esc) {
  const periods = (fin && Array.isArray(fin.periods) ? fin.periods : []).slice(0, 4).reverse();
  if (!periods.length) return small("이 종목의 재무제표 자료가 없습니다.", esc);
  const rows = [["매출액", "IS", "매출액"], ["영업이익", "IS", "영업이익"], ["당기순이익", "IS", "당기순이익"]];
  const head = periods.map(p => `<th style="text-align:right;">${esc(p.period_end)}<br><span class="text-xs" style="font-weight:400;">${esc(SHORT_REPORT[p.report] || p.report || "")}</span></th>`).join("");
  const body = rows.map(([label, st, nm]) => `<tr><td style="color:var(--text-dim);font-size:12px;">${esc(label)}</td>`
    + periods.map(p => { const a = find(accountMap(p.accounts), st, nm); return `<td style="text-align:right;font-weight:600;">${esc(wonText(a ? a.amount : null))}</td>`; }).join("") + `</tr>`).join("");
  const last = periods[periods.length - 1];
  return `<table><thead><tr><th>구분</th>${head}</tr></thead><tbody>${body}</tbody></table>`
    + small(`공시 접수 ${last.known_at || DASH} 까지 · ${(fin && fin.source) || "전자공시(DART)"} · 분기 · 반기 보고서의 손익은 그 기간(3개월) 값입니다.`, esc);
}

/** 재무상태 표 — 가장 최근 기간의 자산 · 부채 · 자본(비율은 화면이 셈하지 않는다 — 건전성 지표는 서버 글). */
export function cvBalanceTable(fin, esc) {
  const row = latestPeriod(fin);
  if (!row) return small("이 종목의 재무제표 자료가 없습니다.", esc);
  const map = accountMap(row.accounts);
  const items = [["자산총계", "BS", "자산총계"], ["부채총계", "BS", "부채총계"], ["자본총계", "BS", "자본총계"]];
  const body = items.map(([label, st, nm]) => { const a = find(map, st, nm);
    return `<tr><td style="color:var(--text-dim);font-size:12px;">${esc(label)}</td><td style="text-align:right;font-weight:600;">${esc(wonText(a ? a.amount : null))}</td></tr>`; }).join("");
  return `<table><thead><tr><th>항목</th><th style="text-align:right;">금액</th></tr></thead><tbody>${body}</tbody></table>`
    + small(`${row.period_end} 기준 ${row.report || ""} · 공시 접수 ${row.known_at || DASH} · ${(fin && fin.source) || "전자공시(DART)"}`, esc);
}

/** 일봉 줄 → 선 차트 점(마지막 날 기준 days 일 안). 종가가 없는 줄은 뺀다. */
export function cvSlice(rows, key) {
  const list = (Array.isArray(rows) ? rows : []).filter(r => r && isNum(r.close) && r.trade_date);
  if (!list.length) return [];
  const days = CV_PERIODS[key] || CV_PERIODS["6m"];
  const last = new Date(`${list[list.length - 1].trade_date}T00:00:00Z`).getTime();
  const lo = last - days * 86400000;
  return list.filter(r => new Date(`${r.trade_date}T00:00:00Z`).getTime() >= lo).map(r => ({ time: r.trade_date, value: r.close }));
}

/** 차트 아래 글 — 그림이 못 읽어 주는 최고 · 최저 · 마지막 종가를 글로 + 실시간이 아니라는 한계. */
export function cvChartSummary(points, liveToday = false, closed = false) {
  if (!points.length) return "일봉 자료가 없습니다.";
  const vals = points.map(p => p.value);
  const fmt = n => `${Math.round(n).toLocaleString("ko-KR")}원`;
  const last = points[points.length - 1];
  const head = `최고 ${fmt(Math.max(...vals))} · 최저 ${fmt(Math.min(...vals))} · 마지막 종가 ${fmt(last.value)}(${last.time}) — 우리 수집 일봉(공공데이터포털) 종가입니다. `;
  // 요약의 최고 · 최저 · 마지막 종가는 수집 일봉만으로 센다 — 오늘 점(증권사 시세)은 종가가 아니라서 섞지 않는다
  if (liveToday && closed) return head + "차트 맨 끝의 오늘 점은 내 증권사에서 받은 오늘 마지막 가격입니다. 장이 닫혀 있어 다시 받지 않습니다.";
  if (liveToday) return head + "차트 맨 끝의 오늘 점은 내 증권사에서 받은 지금 가격이며 약 10초마다 바뀝니다. 체결마다 움직이는 차트는 아닙니다.";
  return head + `초 단위 실시간 차트가 아니며, 오늘의 지금 가격은 위쪽 「현재가」 카드(지연 시세 약 20분)에만 나옵니다. ${CV_KEY_CTA}`;
}

/** 요청 다섯을 한꺼번에 — 하나가 실패해도 나머지는 보인다. */
export async function cvLoad(api, symbol) {
  const code = (/^(\d{6})(?:\.[A-Za-z]+)?$/.exec(String(symbol || "").trim()) || [])[1];
  if (!code) return { code: "", unsupported: true };
  const settled = await Promise.allSettled([
    api(`/api/data/indicators?symbol=${code}`), api(`/api/data/financials?symbol=${code}`), api(`/api/risk/company?symbol=${code}`),
    api(`/api/quote/now?symbol=${encodeURIComponent(symbol)}`), api(`/api/data/ohlcv?symbol=${code}`),
  ]);
  const ok = r => (r.status === "fulfilled" ? r.value : null);
  const err = r => (r.status === "rejected" ? r.reason : null);
  const [ind, fin, health, quote, ohlcv] = settled;
  return { code, ind: ok(ind), indErr: err(ind), fin: ok(fin), finErr: err(fin), health: ok(health), quote: ok(quote), ohlcv: ok(ohlcv), ohlcvErr: err(ohlcv) };
}

// ── 지표 비교(설계 결정 ② 안 A — 기본 5종목 + 종목 추가 · 수집 대상 안에서만 · 2026-10-30) ─────────────────────
export const CV_COMPARE_ROWS = [["per", "PER(배)"], ["pbr", "PBR(배)"], ["roe", "ROE(%)"], ["operating_margin", "영업이익률(%)"], ["dividend_yield", "배당수익률(%)"]];
export const CV_COMPARE_DEFAULT = ["005930", "000660", "035420", "005380", "105560"];
export const CV_COMPARE_MAX = 8;

/** 수집 대상 목록에서 코드(6자리) 또는 이름으로 찾는다 — 정확히 같은 것 → 이름이 그 낱말로 시작 → 이름에 들어 있음. 없으면 null. */
export function cvFindCompany(list, query) {
  const q = String(query || "").trim();
  if (!q || !Array.isArray(list)) return null;
  const lower = q.toLowerCase();
  const by = f => list.find(f) || null;
  return by(c => c.code === q) || by(c => c.name === q) || by(c => (c.name || "").toLowerCase().startsWith(lower)) || by(c => (c.name || "").toLowerCase().includes(lower));
}

/** 종목마다 따로 불러온다 — 한 종목이 실패해도 그 열만 오류 표시 · 나머지는 그대로. */
export async function cvCompareLoad(api, codes) {
  const settled = await Promise.allSettled(codes.map(c => api(`/api/data/indicators?symbol=${c}`)));
  return settled.map((r, i) => ({ code: codes[i], ind: r.status === "fulfilled" ? r.value : null, err: r.status === "rejected" ? r.reason : null }));
}

/** 비교 표 + 아래 「까닭 · 한계」 목록 — 값은 서버 응답 그대로 · 칸 위에 식 · 기준(title) · 줄표에는 까닭을 아래에 적는다. */
export function cvCompareTable(cols, esc) {
  if (!cols.length) return small("비교할 종목을 추가하세요.", esc);
  const name = c => (c.ind && c.ind.name) || c.code;
  const head = cols.map(c => `<th style="text-align:right;">${esc(name(c))}<br><span class="text-xs" style="font-weight:400;">${esc(c.code)}</span></th>`).join("");
  const metric = (c, key) => (c.ind && Array.isArray(c.ind.metrics) ? c.ind.metrics.find(m => m.key === key) : null);
  const body = CV_COMPARE_ROWS.map(([key, label]) => `<tr><td style="color:var(--text-dim);font-size:12px;font-weight:600;">${esc(label)}</td>`
    + cols.map(c => { const m = metric(c, key);
      return `<td style="text-align:right;font-weight:600;" title="${esc(cvBasisLines(m).join(" / ") || (c.err && c.err.message) || "")}">${esc(m ? cvValueText(m) : DASH)}</td>`; }).join("") + `</tr>`).join("");
  const notes = [];
  for (const c of cols) {
    if (c.err) { notes.push(`${name(c)} — ${c.err.message || "지표를 받지 못했습니다."}`); continue; }
    const r = c.ind && c.ind.report;
    if (r) notes.push(`${name(c)} — ${r.bsns_year} ${r.report}(${r.fs === "CFS" ? "연결" : "별도"}) · 공시 접수 ${r.known_at || DASH} · 종가 ${(c.ind.price && c.ind.price.trade_date) || DASH}`);
    for (const [key, label] of CV_COMPARE_ROWS) {
      const m = metric(c, key);
      if (m && !isNum(m.value)) notes.push(`${name(c)} ${label.replace(/\(.*\)/, "")} — ${m.reason || "계산하지 않았습니다."}`);
      else if (m && m.approx) notes.push(`${name(c)} ${label.replace(/\(.*\)/, "")} — 근사: ${m.sentence}`);
    }
  }
  return `<table><thead><tr><th>지표</th>${head}</tr></thead><tbody>${body}</tbody></table>`
    + `<ul style="margin-top:10px;padding-left:18px;list-style:disc;">${notes.map(n => `<li class="text-xs" style="color:var(--text-mute);line-height:1.6;">${esc(n)}</li>`).join("")}</ul>`
    + small("값 위에 마우스를 올리면(휴대폰은 길게 눌러) 식 · 기준이 보입니다. 업종마다 보통 수준이 다르므로 같은 업종끼리 견주어야 뜻이 있습니다. 투자 권유가 아닙니다.", esc);
}

// ── 섹터(설계 결정 ③ 안 C — 섹터 = 밸류에이션 · 산업 = 하루 등락 · 2026-10-30) ─────────────────────────────────
const med = (x, unit) => (x && isNum(x.median) ? `${x.median}${unit} (${x.n}곳)` : DASH);

/** 업종 카드들 — 서버가 계산한 PER · PBR 중앙값 그대로 · 몇 곳으로 낸 값인지 · 종목이 적은 업종은 표시. 응답에 업종이 없으면 안내 한 줄. */
export function cvSectorCards(data, esc) {
  if (!data || !Array.isArray(data.groups) || !data.groups.length) return small("업종별 자료를 아직 받지 못했습니다.", esc);
  return data.groups.map(g => `<div class="card" data-cv-sector="${esc(g.code)}">`
    + `<div class="flex items-center justify-between mb-2"><span class="font-semibold" style="font-size:13px;">${esc(g.name)}</span>`
    + (g.thin ? `<span style="font-size:11px;font-weight:700;color:var(--amber, #b45309);">적은 종목</span>` : "") + `</div>`
    + `<div class="text-xs" style="color:var(--text-mute);margin-bottom:8px;">${esc(g.section && g.section.name ? g.section.name + " · " : "")}종목 ${esc(String(g.n))}곳 · 대표 ${esc((g.top || []).map(t => t.name).join(" · ") || DASH)}</div>`
    + `<div class="flex gap-4"><div><div class="text-xs" style="color:var(--text-mute);">PER 중앙값</div><div style="font-size:15px;font-weight:700;">${esc(med(g.per, "배"))}</div></div>`
    + `<div><div class="text-xs" style="color:var(--text-mute);">PBR 중앙값</div><div style="font-size:15px;font-weight:700;">${esc(med(g.pbr, "배"))}</div></div></div></div>`).join("");
}

/** 업종 카드 아래 글 — 기준일 · 계산식 · 한계(서버 글 그대로). */
export function cvSectorNote(data, esc) {
  if (!data || !data.notice) return "";
  const f = data.formula || {};
  return small(`기준 ${data.as_of || DASH} 종가 · PER = ${f.per || DASH} · PBR = ${f.pbr || DASH}`, esc) + small(data.notice, esc);
}
