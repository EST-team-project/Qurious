/* 기본 인디케이터 전략 화면(indicator-strategy)의 판정 · 낱말 · 카드 입력 — DOM 을 만지지 않는 함수만(TC-ISC 가 Node 로 돌린다).
 * B1 볼린저는 실제 밴드(종가 vs 상단 · 하단) · B2 체크한 지표만 표와 판정에 · B3 「AI 판단」 · 「강력」 대신 결정 대장 10-27 낱말
 * 「규칙 신호 · 매수 쪽 / 매도 쪽」 + 「근거 n개」(#392 · 설계서 4.6). 값은 서버 차트 응답(/api/indicator-strategy/chart) 그대로 읽는다. */

const lastOf = arr => {
  for (let i = (arr || []).length - 1; i >= 0; i--) if (arr[i] !== null && arr[i] !== undefined) return arr[i];
  return null;
};
const n2 = v => Number(v).toLocaleString("ko-KR", { maximumFractionDigits: 2 });

// checks: { ma5, ma20, ma60, rsi, macd, bb } — 체크박스 그대로. 반환 줄: [지표, 지금 값, 상태, 쪽("매수 쪽" · "매도 쪽" · "중립")]
export function buildRows(chart, checks) {
  const s = chart?.series || {};
  const close = lastOf((chart?.bars || []).map(b => b.close));
  const rows = [];
  if (close === null) return rows;
  const ma5 = lastOf(s.ma5), ma20 = lastOf(s.ma20), ma60 = lastOf(s.ma60);
  if (checks.ma5 && checks.ma20 && ma5 !== null && ma20 !== null) {
    const up = ma5 > ma20;
    rows.push(["5일선 vs 20일선", `${n2(ma5)} vs ${n2(ma20)}`, up ? "5일선이 20일선 위" : "5일선이 20일선 아래", up ? "매수 쪽" : "매도 쪽"]);
  }
  if (checks.ma60 && ma60 !== null) {
    const up = close > ma60;
    rows.push(["종가 vs 60일선", `${n2(close)} vs ${n2(ma60)}`, up ? "종가가 60일선 위" : "종가가 60일선 아래", up ? "매수 쪽" : "매도 쪽"]);
  }
  const rsi = lastOf(s.rsi);
  if (checks.rsi && rsi !== null) {
    rows.push(["RSI(14)", rsi.toFixed(1), rsi < 30 ? "30 아래(과매도)" : rsi > 70 ? "70 위(과매수)" : "30 ~ 70",
      rsi < 30 ? "매수 쪽" : rsi > 70 ? "매도 쪽" : "중립"]);
  }
  const macd = lastOf(s.macd), sig = lastOf(s.macd_signal);
  if (checks.macd && macd !== null && sig !== null) {
    const up = macd > sig;
    rows.push(["MACD(12 · 26 · 9)", `${n2(macd)} / 신호선 ${n2(sig)}`, up ? "MACD 가 신호선 위" : "MACD 가 신호선 아래", up ? "매수 쪽" : "매도 쪽"]);
  }
  const hi = lastOf(s.bb_upper), lo = lastOf(s.bb_lower);
  if (checks.bb && hi !== null && lo !== null) {
    rows.push(["볼린저밴드(20 · 2σ)", `종가 ${n2(close)} · 하단 ${n2(lo)} · 상단 ${n2(hi)}`,
      close < lo ? "종가가 하단 밴드 아래" : close > hi ? "종가가 상단 밴드 위" : "밴드 안",
      close < lo ? "매수 쪽" : close > hi ? "매도 쪽" : "중립"]);
  }
  return rows;
}

// 근거 n개 = 표의 줄 수(체크한 지표만) · 쪽 = 매수 쪽과 매도 쪽 줄 수를 견줌(같으면 중립)
export function summarize(rows) {
  const buy = rows.filter(r => r[3] === "매수 쪽").length, sell = rows.filter(r => r[3] === "매도 쪽").length;
  const neutral = rows.length - buy - sell;
  const side = buy > sell ? "매수 쪽" : sell > buy ? "매도 쪽" : "중립";
  return { n: rows.length, buy, sell, neutral, side,
    text: rows.length ? `규칙 신호 · ${side} — 근거 ${rows.length}개(매수 쪽 ${buy} · 중립 ${neutral} · 매도 쪽 ${sell})`
                      : "고른 지표가 없어 규칙 신호를 내지 않습니다." };
}

// 카드 입력 칸 → 저장 요청 본문. 빈 칸 · 숫자가 아닌 칸은 그대로 보내 서버가 까닭을 돌려준다(화면이 값을 짓지 않는다).
export const CARD_FIELDS = ["slug", "name", "symbol", "short_window", "long_window", "atr_period", "atr_mult", "take_rr",
  "risk_pct", "max_position_pct", "max_symbols", "entry_mode", "exit_mode", "judge"];
export function cardBody(values) {
  const out = {};
  for (const k of CARD_FIELDS) if (values[k] !== undefined && values[k] !== "") out[k] = values[k];
  return out;
}

// 저장된 카드(판 2 꼴) → 입력 칸 값. 카드에 없는 칸은 비운다.
export function cardValues(card) {
  const p = card?.entry?.params || {}, st = card?.stops || {}, ps = card?.position_sizing || {};
  return { slug: card?.strategy_id ?? "", name: card?.name ?? "", symbol: (card?.universe || [])[0] ?? "",
    short_window: p.short_window ?? "", long_window: p.long_window ?? "", atr_period: st.atr_period ?? "",
    atr_mult: st.atr_mult ?? "", take_rr: st.take_rr ?? "", risk_pct: ps.risk_pct ?? "", max_position_pct: ps.max_position_pct ?? "",
    max_symbols: ps.max_symbols ?? "", entry_mode: card?.entry_mode ?? "", exit_mode: card?.exit_mode ?? "", judge: st.judge ?? "" };
}

// 카드 한 줄 요약 — 목록에 보일 글(쉬운 말 · 내부 칸 이름 없이)
export function cardLine(card) {
  const v = cardValues(card);
  const when = { open: "다음 봉 시가", close: "그날 종가" };
  return `${v.name || v.slug} — ${v.short_window}일선이 ${v.long_window}일선 위면 매수 · 아래면 매도 · 손절 평균 진폭 ${v.atr_mult}배 · ` +
    `익절 손절 거리의 ${v.take_rr}배 · 1회 위험 ${v.risk_pct}% · 체결 ${when[v.entry_mode] || v.entry_mode}`;
}
