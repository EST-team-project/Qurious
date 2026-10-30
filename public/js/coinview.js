/* 코인 모의매매 화면의 정직한 글 · 가격 차트 판단(DOM 없이 글 · 점만 정한다 · node 로 시험 · TC-CRY · 2026-10-30 · 할 일 ①-20).
 *
 * 왜 따로 두나 — 클릭 처리는 paper.js 에 있고, 「시세가 어디서 왔고 주문이 어떻게 체결되나」 를 말하는 글과 차트 점 만들기는 여기 한 곳에 둔다(companyview.js 와 같은 방식).
 *
 * 무엇을 바꿨나 — 옛 화면은 시세에 출처 · 받은 시각이 없었고, 주문이 수수료 · 슬리피지 없이 현재가로 즉시 체결되며 이 앱의 모의 장부에만 기록된다는 말도 없었다
 * (서버 코드를 읽고 가짜 연결 실패로 확인: 업비트에서 시세를 못 받으면 마지막으로 저장한 값이 나이 표시 없이 나오고 주문 가격으로도 쓰인다 — 서버 고침은 모의투자 장부 담당 몫).
 * 설계 결정(2026-10-30 · 질문 · 바로): 글을 시세 밑 · 주문 칸 위에 한 줄씩(A) + 가격 차트(일봉).
 *
 * 규칙
 *   1. 글은 코드가 실제로 하는 일만 — 수수료 · 슬리피지 없음 · 모의 장부에만 기록 · 시세 저장 약 5초 · 못 받으면 마지막 값.
 *   2. 차트는 업비트 공개 시세의 일봉 종가다 — 화면에만 보이고 저장하지 않는다 · 오늘 봉은 진행 중 · 초 단위 실시간이 아니다.
 */
const isNum = v => typeof v === "number" && Number.isFinite(v);

/** 시세 밑 한 줄 — 출처 · 저장 시간 · 시각 미표시 · 못 받으면 마지막 값. */
export const COIN_SOURCE_NOTE =
  "출처: 업비트 공개 시세(원화 현재가) · 약 5초까지 저장해 둔 값 · 받은 시각은 표시되지 않음 — 시세를 받지 못하면 마지막으로 받은 값이 나올 수 있습니다.";

/** 주문 칸 위 글 — 어디에 기록되나 · 어떻게 체결되나. */
export const COIN_ORDER_NOTE = [
  "이 주문은 이 앱의 모의 장부에만 기록됩니다 — 업비트로 주문이 나가지 않습니다.",
  "위 현재가로 수수료 · 슬리피지 없이 즉시 체결합니다(실제 거래소 수수료는 반영하지 않음).",
];

/** 업비트 일봉 응답(`[{time: "2026-10-30T09:00:00", close}]`) → 선 차트 점. 종가가 없거나 날짜가 없는 줄은 뺀다. */
export function coinPoints(candles) {
  return (Array.isArray(candles) ? candles : [])
    .filter(c => c && isNum(c.close) && typeof c.time === "string" && c.time.length >= 10)
    .map(c => ({ time: c.time.slice(0, 10), value: c.close }));
}

/** 차트 아래 글 — 최고 · 최저 · 마지막 일봉 종가 + 출처 · 저장 안 함 · 진행 중 · 실시간이 아님. */
export function coinChartSummary(points) {
  if (!points.length) return "일봉 자료를 받지 못했습니다.";
  const vals = points.map(p => p.value);
  const fmt = n => `${Math.round(n).toLocaleString("ko-KR")}원`;
  const last = points[points.length - 1];
  return `최근 ${points.length}일 최고 ${fmt(Math.max(...vals))} · 최저 ${fmt(Math.min(...vals))} · 마지막 일봉 ${fmt(last.value)}(${last.time}) — 업비트 공개 시세의 일봉입니다. `
    + "화면에만 보이고 저장하지 않으며, 오늘 봉은 진행 중이라 값이 바뀝니다. 초 단위 실시간 차트가 아닙니다.";
}
