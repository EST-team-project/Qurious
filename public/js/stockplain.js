/* 종목 근거 모달의 쉬운 설명 — 규칙 열한 가지의 쉬운 풀이 · 칸마다 「읽는 법」 · 「내 판단 정리 틀」 글 (2026-11-02 · Figma 「종목 허브」 10 쪽)
 *
 * 원칙: 새 계산 · 한 줄 결론 · 목표가 · 손절가를 만들지 않는다. 서버가 준 값(`GET /api/stock-hub`)을 쉬운 말로 풀고, 사람이 매매사유를 정리할 때
 * 쓰는 순서(가격 자리 · 신호 · 실적 · 확인할 일정 · 내가 정할 것)에 맞춰 이미 보인 사실만 모아 준다. 투자 권유가 아니다.
 * 규칙 이름(key)은 서버 `signal_explain.RULES` 와 같다(시험 TC-SDR-10 이 맞댄다). DOM 없이 글만 만든다(Node 로 시험).
 */

/** 규칙 key → { 쉬운 뜻 · 조심할 점 } — 점수는 서버 규칙표의 `points` 를 그대로 쓴다(여기서 다시 적지 않는다) */
export const RULE_PLAIN = {
  rsi_low: { mean: "RSI 는 최근 14일 동안 오른 힘과 내린 힘을 견준 값(0~100)입니다. 30 아래는 내린 힘이 훨씬 컸다는 뜻이고, 규칙은 이를 매수 쪽 근거로 셉니다.", care: "더 떨어질 수도 있어 이 규칙 하나로 판단하지 않습니다." },
  rsi_high: { mean: "RSI 는 최근 14일 동안 오른 힘과 내린 힘을 견준 값(0~100)입니다. 70 위는 오른 힘이 훨씬 컸다는 뜻이고, 규칙은 이를 매도 쪽 근거로 셉니다.", care: "강한 상승장에서는 오래 머무는 때도 있습니다." },
  rsi_mid: { mean: "RSI 가 30~70 사이라 오른 힘과 내린 힘이 비슷하고, 규칙은 어느 쪽 근거로도 세지 않습니다.", care: "근거로 세지 않았다는 뜻이지 안전하다는 뜻이 아닙니다." },
  ma_up: { mean: "짧은 기간의 평균 가격이 더 긴 기간의 평균 가격보다 위에 있습니다. 규칙은 이를 매수 쪽 근거로 셉니다.", care: "평균이라 가격 변화가 늦게 반영됩니다." },
  ma_down: { mean: "짧은 기간의 평균 가격이 더 긴 기간의 평균 가격보다 아래에 있습니다. 규칙은 이를 매도 쪽 근거로 셉니다.", care: "이미 지나간 가격의 평균이라 변화가 늦게 반영됩니다." },
  macd_up: { mean: "MACD 는 12일 평균과 26일 평균의 차이이고 신호선은 그 차이의 9일 평균입니다. MACD 가 신호선 위에 있으면 규칙은 매수 쪽 근거로 셉니다.", care: "횡보장에서는 자주 엇갈립니다." },
  macd_down: { mean: "MACD 는 12일 평균과 26일 평균의 차이이고 신호선은 그 차이의 9일 평균입니다. MACD 가 신호선 아래에 있으면 규칙은 매도 쪽 근거로 셉니다.", care: "횡보장에서는 자주 엇갈립니다." },
  bb_upper: { mean: "볼린저 띠는 최근 20일 평균 가격 위아래로 표준편차의 2배만큼 그은 폭입니다. 종가가 띠 위로 나가면 평소 범위보다 많이 오른 상태이고, 규칙은 이를 매도 쪽 근거로 셉니다.", care: "띠를 벗어난 채 오래 가는 때도 있습니다." },
  bb_lower: { mean: "볼린저 띠는 최근 20일 평균 가격 위아래로 표준편차의 2배만큼 그은 폭입니다. 종가가 띠 아래로 나가면 평소 범위보다 많이 내린 상태이고, 규칙은 이를 매수 쪽 근거로 셉니다.", care: "띠를 벗어난 채 오래 가는 때도 있습니다." },
  mid_up: { mean: "종가가 20일 평균 가격보다 위에 있습니다. 규칙은 이를 매수 쪽 근거로 셉니다.", care: "평균과의 거리는 보지 않습니다." },
  mid_down: { mean: "종가가 20일 평균 가격보다 아래에 있습니다. 규칙은 이를 매도 쪽 근거로 셉니다.", care: "평균과의 거리는 보지 않습니다." },
};

/** 주기 이름 한 줄 풀이(서버 label 이 「일봉」 · 「주봉」 · 「분봉(60분)」 꼴) */
export function planTimeframeNote(label) {
  const s = String(label || "");
  if (s.startsWith("일봉")) return "하루에 한 번 찍는 종가 기준입니다.";
  if (s.startsWith("주봉")) return "한 주 단위로 본 것이라 며칠째 이어진 흐름을 봅니다.";
  if (s.startsWith("분봉")) return "장중 한 시간 단위로 본 것이며, 분봉을 모으는 종목에만 있습니다.";
  return "";
}

/** 칸마다 「이 칸 읽는 법」 한 줄 — 칸 key 는 서버 SECTIONS 와 같다 */
export const SECTION_HOWTO = {
  price: "마지막으로 확정된 종가와 전 거래일 대비 등락입니다. 지금 시세가 아니라 기준일 종가이고, 배당 · 분할이 있으면 증권사 화면과 다를 수 있습니다.",
  signal: "지표 규칙 열한 가지를 주기마다 세어 합친 결과입니다. 매수 · 매도를 권하는 말이 아니라 규칙이 어느 쪽 근거를 더 많이 찾았는지를 보여 줍니다. 「그렇게 본 까닭」 과 「반대로 본 까닭」 을 함께 읽으세요. 켜진 규칙과 그 값은 차트로 직접 확인할 수 있지만, 그 신호가 앞으로 맞을지는 이 화면에서 알 수 없습니다.",
  financials: "회사의 재무 상태를 몇 가지 기준으로 그렇다 · 아니다 · 모름으로 가른 것입니다. 가장 최근 보고서 기준이라 최근 분기 흐름과 다를 수 있습니다.",
  disclosures: "회사가 공식으로 낸 공시의 제목과 날짜입니다. 제목만으로는 좋고 나쁨을 알 수 없어, 눌러서 내용을 확인하세요.",
  news: "최근 기사의 제목과 출처입니다. 기사는 의견이 섞일 수 있어 사실 확인은 공시와 함께 하세요.",
  schedule: "앞으로 60일 안에 확인할 날(실적 발표 · 배당 등)입니다. 일정은 바뀔 수 있고 「예상」 딱지는 확정이 아니라는 뜻입니다.",
  sector: "이 종목이 속한 한국표준산업분류 업종과 같은 업종의 수집 상장사 수입니다. 같은 업종끼리 함께 움직이는지 보려는 참고용입니다.",
};

/** 시장 맥락 한 줄 — 수집 DB 지수 일봉(`/api/data/ohlcv`) 마지막 두 줄로 만든 {name, close, pct, day} 목록 → 글. 실패하면 까닭을 말한다 */
export function planMarketLine(items, failed) {
  if (failed) return "시장 지표를 불러오지 못했습니다.";
  const ok = (items || []).filter(x => x && Number.isFinite(x.close) && Number.isFinite(x.pct));
  if (!ok.length) return "시장 지표 자료가 없습니다.";
  const fmt = n => Number(n).toLocaleString("ko-KR", { maximumFractionDigits: 2 });
  const pct = p => `${p > 0 ? "+" : p < 0 ? "−" : ""}${Math.abs(p).toFixed(2)}%`;
  const day = ok[0].day ? ` · ${Number(ok[0].day.slice(5, 7))}월 ${Number(ok[0].day.slice(8, 10))}일 종가 기준` : "";
  return `시장 맥락 — ${ok.map(x => `${x.name} ${fmt(x.close)}(${pct(x.pct)})`).join(" · ")}${day}`;
}

/** 지수 일봉 응답 → {close, pct, day}. rows 는 날짜 오름차순 `[{trade_date, close}]` 마지막 두 줄로 등락을 셈한다(새 판정이 아니라 두 종가의 비율) */
export function planIndexMove(name, rows) {
  const r = (rows || []).filter(x => x && Number.isFinite(Number(x.close)));
  if (r.length < 2) return null;
  const last = r[r.length - 1], prev = r[r.length - 2];
  return { name, close: Number(last.close), pct: (Number(last.close) / Number(prev.close) - 1) * 100, day: String(last.trade_date || "") };
}

const won = n => `${Number(n).toLocaleString("ko-KR", { maximumFractionDigits: 0 })}원`;
const pctText = p => `${p > 0 ? "+" : p < 0 ? "−" : ""}${Math.abs(Number(p)).toFixed(2)}%`;
const mmdd = d => { const m = String(d || "").match(/^\d{4}-(\d{2})-(\d{2})/); return m ? `${m[1]}-${m[2]}` : ""; };

/** 「내 판단 정리 틀」 — 이미 모달에 보인 사실만 채우고, 정하는 칸은 밑줄로 비운다. 서버에 저장하지 않는다 */
export function planNoteText(hub, marketLine) {
  const s = hub.sections || {};
  const id = (s.identity && s.identity.data) || {};
  const name = hub.name || id.name || hub.symbol;
  const out = [];
  const price = s.price && s.price.status === "ok" ? s.price.data : null;
  out.push(`${name}(${hub.symbol})${price ? ` · 기준일 ${mmdd(price.trade_date)} 종가 ${won(price.close)}(${pctText(price.change_pct)})` : ""}`);
  if (marketLine && !/불러오지|없습니다/.test(marketLine)) out.push(`· ${marketLine}`);
  const sig = s.signal && s.signal.status === "ok" ? s.signal.data : null;
  if (sig) {
    const rs = (sig.reasons || []).map(r => `${r.label} ${r.text}`);
    const cs = (sig.counter_reasons || []).map(r => `${r.label} ${r.text}`);
    out.push(`· 규칙 신호: ${sig.signal || "—"}${sig.signal === "관망" ? "" : " 쪽"}${sig.strength ? ` · ${sig.strength}` : ""}${rs.length ? ` · 근거 ${rs.length}개(${rs.join(" · ")})` : ""}${cs.length ? ` · 반대 근거 ${cs.length}개(${cs.join(" · ")})` : ""}`);
  }
  const fin = s.financials && s.financials.status === "ok" ? s.financials.data : null;
  if (fin && fin.summary) out.push(`· 재무: 그렇다 ${fin.summary.pass ?? 0} · 아니다 ${fin.summary.fail ?? 0} · 모름 ${fin.summary.unknown ?? 0}`);
  const dis = s.disclosures && s.disclosures.status === "ok" ? (s.disclosures.data.items || []).slice(0, 3) : [];
  if (dis.length) out.push(`· 최근 공시: ${dis.map(x => `${mmdd(x.published)} ${x.title}`).join(" / ")}`);
  const ev = s.schedule && s.schedule.status === "ok" ? (s.schedule.data.events || []).slice(0, 4) : [];
  if (ev.length) out.push(`· 확인할 일정: ${ev.map(e => `${mmdd(e.date)} ${e.title || e.kind_label || ""}`).join(" / ")}`);
  out.push("· 수급(외국인 · 기관): 앱이 모으지 않는 자료입니다 — 직접 확인해 적기 ________");
  out.push("· 내가 정할 것(결과를 보기 전에 적기 — 적은 날 ______)");
  out.push("  - 본 것(사실) ________ / 왜 그게 이유인가 ________");
  out.push("  - 틀렸다고 볼 조건 ________");
  out.push("  - 목표가 1차 ______ 2차 ______ / 손절가 ______(이유: ______) / 비중 ____ %");
  out.push("  - 확인할 날과 그날 확인할 것 ______");
  out.push("· 한계: 규칙 신호는 지난 가격만 보고 세며, 이 화면은 그 규칙들이 과거에 맞았는지 재지 않았습니다. 앱이 모은 사실이고 투자 권유가 아닙니다.");
  return out.join("\n");
}
