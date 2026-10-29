/* 기술적 분석 화면 판단 — DOM 없이 글 · 표시만 정한다(node 로 시험 · TC-TV2 · 2026-10-29 · 할 일 ①-10).
 *
 * 옛 화면은 캔들 패턴 · 엘리어트 파동 **설명 글**뿐이었다(점검표 40 · 설명 전용). 이제 설명 위에 「이 종목의 지표 값」 을 얹는다.
 * 읽는 길은 이미 있는 `GET /api/stocks/quant/indicators`(일봉 · 수집 DB 먼저 · 지표 정의 한 벌 `definition`) 하나다.
 *
 * 규칙
 *   1. 값은 응답 배열의 **마지막 값 그대로**(셈하지 않는다) · 없으면 줄표.
 *   2. 종가는 「마지막 종가」 라 부르고 기준일(as_of)을 붙인다 — 지금 가격이 아니다. 출처 · 기준일 글(data_note)은 서버 글 그대로.
 *   3. 규칙 신호는 점수(score)와 근거 문장(reasons)만 — 「강력 매수」 같은 판정 낱말을 따로 내세우지 않는다(권유처럼 읽힌다 · 문장 속에 서버가 쓴 말은 그대로).
 *   4. 지표 인자(RSI 14 · 이동평균 5/20/60 · 볼린저 20일 · 2σ)는 서버 코드의 기본값과 같은 값을 PARAMS 한 곳에 두고 시험이 맞댄다.
 */

const DASH = "—";
const isNum = v => typeof v === "number" && Number.isFinite(v);

/** 화면에 적는 지표 인자 — app/services/stock.py `_calc_rsi` · `_calc_bollinger` 의 기본값 · `ma5/ma20/ma60` 과 같아야 한다(TC-TV2 가 맞댄다). */
export const PARAMS = { rsiPeriod: 14, ma: [5, 20, 60], bbPeriod: 20, bbStd: 2 };

/** 배열의 마지막 숫자 — 끝이 비어 있으면(워밍업 · 결측) 그보다 앞의 마지막 숫자가 아니라 **줄표**(오래된 값을 최신처럼 보이지 않는다). */
export function lastValue(arr) {
  if (!Array.isArray(arr) || !arr.length) return null;
  const v = arr[arr.length - 1];
  return isNum(v) ? v : null;
}

const num = (v, d = 2) => (isNum(v) ? v.toLocaleString("ko-KR", { minimumFractionDigits: 0, maximumFractionDigits: d }) : DASH);
const card = (title, body, extra = "") =>
  `<div class="p-4 rounded" style="background:var(--bg);"><div class="text-xs text-slate-400 mb-1">${title}</div>${body}${extra}</div>`;
const small = (text, esc) => (text ? `<div class="text-xs text-slate-400 mt-1">${esc(text)}</div>` : "");

/** 요청 — 실패하면 { err } 로 돌려 화면이 까닭을 보인다. */
export async function loadTechnical(api, symbol) {
  const code = String(symbol || "").trim();
  if (!/^[0-9A-Za-z.\-]{1,20}$/.test(code)) return { err: { message: "종목코드가 올바르지 않습니다." } };
  try {
    return { data: await api(`/api/stocks/quant/indicators?symbol=${encodeURIComponent(code)}&period=2y`) };
  } catch (err) {
    return { err };
  }
}

/** 카드 격자 — 마지막 종가 · RSI · 이동평균 셋 · 볼린저 셋 · 규칙이 읽은 것 · 출처 줄. */
export function renderTechnical({ data, err } = {}, esc) {
  if (err || !data || data.error) {
    const why = (err && err.message) || (data && data.error) || "지표를 받지 못했습니다.";
    return card("지표 값", `<div class="text-lg font-bold">${DASH}</div>`, small(why, esc));
  }
  const rsi = lastValue(data.rsi);
  const out = [];
  out.push(card("마지막 종가", `<div class="text-lg font-bold">${esc(num(data.current_price, 0))}원</div>`,
    small(`${data.as_of || DASH} 기준 · 지금 가격이 아닙니다`, esc)));
  out.push(card(`RSI (${PARAMS.rsiPeriod}일)`, `<div class="text-lg font-bold">${esc(num(rsi, 1))}</div>`,
    small("최근 오른 폭과 내린 폭의 비율입니다. 흔히 70 위는 과열, 30 아래는 침체로 읽지만 참고용입니다.", esc)));
  out.push(card("이동평균", PARAMS.ma.map(n => `<div class="text-sm">${n}일선 <strong>${esc(num(lastValue(data[`ma${n}`]), 0))}</strong></div>`).join(""),
    small("최근 N일 종가의 평균입니다. 짧은 선이 긴 선 위에 있으면 최근 가격이 더 높다는 뜻입니다.", esc)));
  out.push(card(`볼린저 밴드 (${PARAMS.bbPeriod}일 · ${PARAMS.bbStd}σ)`,
    `<div class="text-sm">상단 <strong>${esc(num(lastValue(data.bb_upper), 0))}</strong></div>`
    + `<div class="text-sm">중심 <strong>${esc(num(lastValue(data.bb_mid), 0))}</strong></div>`
    + `<div class="text-sm">하단 <strong>${esc(num(lastValue(data.bb_lower), 0))}</strong></div>`,
    small("중심선(20일 평균) 위아래로 표준편차의 2배만큼 띠를 그린 것입니다.", esc)));
  const sig = data.signal || {};
  const reasons = Array.isArray(sig.reasons) ? sig.reasons : [];
  out.push(card("규칙이 읽은 것 (참고용 · 매매 권유가 아닙니다)",
    `<div class="text-sm">규칙 점수 <strong>${esc(isNum(sig.score) ? (sig.score > 0 ? "+" : "") + sig.score : DASH)}</strong></div>`,
    reasons.map(r => `<div class="text-xs text-slate-300">· ${esc(r)}</div>`).join("") || small("읽은 근거가 없습니다.", esc)));
  const foot = [data.data_note, data.definition ? `지표 정의 ${data.definition}` : "", data.source ? `자료 ${data.source}` : ""].filter(Boolean);
  if (foot.length) out.push(`<div style="grid-column:1/-1;">${foot.map(t => `<div class="text-xs text-slate-400">${esc(t)}</div>`).join("")}</div>`);
  return out.join("");
}
