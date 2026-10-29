/* 재무제표 분석 화면 판단 — DOM 없이 글 · 표시만 정한다(node 로 시험 · TC-FV · 2026-10-29 · 할 일 ①-10).
 *
 * 왜 따로 두나 — 이 화면의 클릭 처리는 ml.js(강사님 기초 코드에서 출발)에 있어서, 규칙은 여기 한 곳에 두고 ml.js 는 부르는 몇 줄만 둔다(S86 규칙).
 *
 * 무엇을 바꿨나 — 옛 화면은 `/api/macro/fundamental` 이 지어낸 값(DCF = 가격 × 1.15 · FCF 수익률 = 100 ÷ 가격 × 1000)을 「목업」 이라는 말만 붙여 보였다.
 * 지금은 이미 있는 읽기 길 셋만 쓴다.
 *   /api/data/financials   DART 주요계정(분기 · 반기 · 사업보고서) — 값마다 접수일 · 쓸 수 있는 날 · 원문 링크가 있다
 *   /api/risk/company      재무 건전성 지표 — 지표마다 뜻(sentence) · 식(formula) · 기준(basis)을 서버가 준다
 *   /api/stock-hub?sections=price   마지막 종가와 그 날짜
 *
 * 규칙
 *   1. 숫자는 응답에 있는 값만. 없으면 줄표와 서버 까닭. 화면이 값을 셈하지 않는다(합 · 비율 · 환산 없음 — 단위 글 조/억 만 바꾼다).
 *   2. 숫자마다 기준 기간 · 공시 접수일 · 쓸 수 있는 날 · 출처를 한 줄로 붙인다(카드 위 한 줄로 몰아 적지 않는다).
 *   3. DCF · FCF 수익률은 **계산하지 않는다** — 주요계정에는 영업현금흐름 · 설비투자가 없다. 그 사실과 까닭을 보이고, 개념 설명만 남긴다.
 *   4. 종가는 「종가(MM-DD)」 라고 부른다. 「현재 주가」 라는 이름으로 마지막 종가를 보이지 않는다.
 */

const DASH = "—";
const isNum = v => typeof v === "number" && Number.isFinite(v);

/** 화면 선택값("005930.KS")에서 단축코드 6자리 — 아니면 빈 글(요청을 보내지 않는다). */
export function shortCode(sym) {
  const m = /^(\d{6})(?:\.[A-Za-z]+)?$/.exec(String(sym || "").trim());
  return m ? m[1] : "";
}

/** 원 단위 금액 → 「171.50조 원」 · 「3,389억 원」 · 모르면 줄표. 값을 바꾸지 않고 단위 글만 붙인다. */
export function wonText(n) {
  if (!isNum(n)) return DASH;
  const sign = n < 0 ? "−" : "";
  const a = Math.abs(n);
  if (a >= 1e12) return `${sign}${(a / 1e12).toFixed(2)}조 원`;
  if (a >= 1e8) return `${sign}${Math.round(a / 1e8).toLocaleString("ko-KR")}억 원`;
  return `${sign}${a.toLocaleString("ko-KR")}원`;
}

/** 계정 목록 → { "BS|자산총계": 줄 } — DART 가 같은 계정을 두 번 주는 일이 있어(당기순이익) 처음 줄만 쓴다. */
export function accountMap(accounts) {
  const map = {};
  for (const a of Array.isArray(accounts) ? accounts : []) {
    const key = `${a.statement}|${a.name}`;
    if (!(key in map)) map[key] = a;
  }
  return map;
}

/** 가장 최근 기간 줄 — 기간 끝날(period_end) 가운데 가장 늦은 것. 없으면 null. */
export function latestPeriod(fin) {
  const rows = (fin && Array.isArray(fin.periods)) ? fin.periods : [];
  let best = null;
  for (const r of rows) if (r && r.period_end && (!best || String(r.period_end) > String(best.period_end))) best = r;
  return best;
}

/** 이름이 prefix 로 시작하는 계정(당기순이익 / 당기순이익(손실)) — 같은 구분(statement) 안에서만. */
function findAccount(map, statement, name) {
  if (`${statement}|${name}` in map) return map[`${statement}|${name}`];
  const hit = Object.keys(map).find(k => k.startsWith(`${statement}|${name}`));
  return hit ? map[hit] : null;
}

/** 숫자 아래 한 줄 — 어느 기간의 어떤 보고서이고 언제 공시됐고 언제부터 쓸 수 있는 판인가. */
export function provenanceLine(row, fin) {
  if (!row) return "";
  const parts = [
    `${row.period_end || DASH} 기준${row.report ? " " + row.report : ""}`,
    `공시 접수 ${row.known_at || DASH}`,
    `쓸 수 있는 날 ${row.available_from || DASH}`,
    fin && fin.source ? fin.source : "",
  ].filter(Boolean);
  return parts.join(" · ");
}

/** http(s) 주소만 링크로(그 밖은 링크 없이) — signal-rank.js safeHttpUrl 과 같은 규칙. */
function safeUrl(u) {
  return /^https?:\/\//i.test(String(u || "")) ? String(u) : "";
}

const card = (title, body, extra = "") =>
  `<div class="p-4 rounded" style="background:var(--bg);">`
  + `<div class="text-xs text-slate-400 mb-1">${title}</div>${body}${extra}</div>`;
const small = (text, esc) => text ? `<div class="text-xs text-slate-400 mt-1">${esc(text)}</div>` : "";

/** 손익 · 재무상태 계정 카드 — amount 는 보고서 기간 값(분기 · 반기면 그 3개월), cumulative 는 누적. */
function accountCard(label, acc, row, fin, esc) {
  if (!acc) return card(esc(label), `<div class="text-lg font-bold">${DASH}</div>`, small("이 보고서에 이 계정이 없습니다.", esc));
  const cum = isNum(acc.cumulative) ? small(`누적 ${wonText(acc.cumulative)}`, esc) : "";
  return card(esc(label), `<div class="text-lg font-bold">${esc(wonText(acc.amount))}</div>`, cum + small(provenanceLine(row, fin), esc));
}

/** 건전성 지표 카드 — 값 · 단위 · 뜻은 서버 글 그대로, 식은 있을 때만. */
function metricCard(m, esc) {
  const val = isNum(m.value) ? `${m.value}${m.unit || ""}` : DASH;
  return card(esc(m.label || m.key || DASH), `<div class="text-lg font-bold">${esc(val)}</div>`,
    small(m.sentence, esc) + small(m.formula ? `식: ${m.formula}` : "", esc) + small(m.basis, esc));
}

export const CONCEPTS = {
  DCF: "미래 현금흐름을 현재가치로 할인 (Discounted Cash Flow)",
  EVA: "경제적 부가가치 = NOPAT − 자본비용 (Economic Value Added)",
  FCF: "잉여현금흐름 = 영업현금흐름 − 설비투자 (Free Cash Flow)",
};

/** 계산하지 않는 것 — DCF 내재가치 · FCF 수익률. 까닭과 개념 설명만. */
export const NOT_COMPUTED_REASON =
  "계산하지 않습니다 — 잉여현금흐름에는 영업현금흐름과 설비투자가 필요한데, 지금 읽는 DART 주요계정에는 둘 다 없습니다. 전체 재무제표를 읽는 길이 생기면 보입니다.";

/** 요청 셋을 한꺼번에 — 하나가 실패해도 나머지는 보인다. 반환: { fin, finErr, health, healthErr, hub, hubErr }. */
export async function loadFundamental(api, symbol) {
  const code = shortCode(symbol);
  if (!code) return { finErr: { message: "종목코드가 올바르지 않습니다." } };
  const [fin, health, hub] = await Promise.allSettled([
    api(`/api/data/financials?symbol=${code}`),
    api(`/api/risk/company?symbol=${code}`),
    api(`/api/stock-hub?symbol=${code}&sections=price`),
  ]);
  const ok = r => (r.status === "fulfilled" ? r.value : null);
  const err = r => (r.status === "rejected" ? r.reason : null);
  return { fin: ok(fin), finErr: err(fin), health: ok(health), healthErr: err(health), hub: ok(hub), hubErr: err(hub) };
}

/** 카드 격자 전체 — 종가 · 손익 셋 · 재무상태 셋 · 건전성 지표 · 계산하지 않는 것. */
export function renderFundamental(parts, esc) {
  const p = parts || {};
  const out = [];

  // ① 종가 — 마지막 봉이고 지금 가격이 아니다
  const price = p.hub && p.hub.sections && p.hub.sections.price;
  const pd = price && price.data;
  out.push(isNum(pd && pd.close)
    ? card("종가", `<div class="text-lg font-bold">${esc(pd.close.toLocaleString("ko-KR"))}원</div>`,
      small(`${pd.trade_date || DASH} 마지막 종가 · 지금 가격이 아닙니다`, esc))
    : card("종가", `<div class="text-lg font-bold">${DASH}</div>`, small((price && price.reason) || "종가를 받지 못했습니다.", esc)));

  // ② 재무제표 — DART 주요계정
  const row = latestPeriod(p.fin);
  if (row) {
    const map = accountMap(row.accounts);
    out.push(accountCard("매출액", findAccount(map, "IS", "매출액"), row, p.fin, esc));
    out.push(accountCard("영업이익", findAccount(map, "IS", "영업이익"), row, p.fin, esc));
    out.push(accountCard("당기순이익", findAccount(map, "IS", "당기순이익"), row, p.fin, esc));
    out.push(accountCard("자산총계", findAccount(map, "BS", "자산총계"), row, p.fin, esc));
    out.push(accountCard("부채총계", findAccount(map, "BS", "부채총계"), row, p.fin, esc));
    out.push(accountCard("자본총계", findAccount(map, "BS", "자본총계"), row, p.fin, esc));
  } else {
    const why = p.finErr ? (p.finErr.message || "재무제표를 받지 못했습니다.") : "이 종목의 재무제표 자료가 없습니다.";
    out.push(card("재무제표", `<div class="text-lg font-bold">${DASH}</div>`, small(why, esc)));
  }

  // ③ 건전성 지표 — 서버 글 그대로
  const metrics = (p.health && Array.isArray(p.health.metrics)) ? p.health.metrics : [];
  if (metrics.length) metrics.forEach(m => out.push(metricCard(m, esc)));
  else if (p.healthErr) out.push(card("재무 건전성", `<div class="text-lg font-bold">${DASH}</div>`, small(p.healthErr.message || "건전성 지표를 받지 못했습니다.", esc)));

  // ④ 계산하지 않는 것
  out.push(card("DCF 내재가치 · FCF 수익률", `<div class="text-lg font-bold">${DASH}</div>`,
    small(NOT_COMPUTED_REASON, esc) + small(CONCEPTS.DCF, esc) + small(CONCEPTS.FCF, esc) + small(CONCEPTS.EVA, esc)));

  // ⑤ 아래 설명 — 기간 값 읽는 법 · 원문 링크 · 고지
  const notes = [];
  if (p.fin && p.fin.note) notes.push(`<div class="text-xs text-slate-400">${esc(p.fin.note)}</div>`);
  const url = safeUrl(row && row.url);
  if (url) notes.push(`<div class="text-xs"><a href="${esc(url)}" target="_blank" rel="noopener noreferrer">공시 원문 보기</a></div>`);
  if (p.health && p.health.fs_note) notes.push(`<div class="text-xs text-slate-400">${esc(p.health.fs_note)}</div>`);
  if (p.health && p.health.notice) notes.push(`<div class="text-xs text-slate-400">${esc(p.health.notice)}</div>`);
  if (notes.length) out.push(`<div style="grid-column:1/-1;">${notes.join("")}</div>`);

  return out.join("");
}
