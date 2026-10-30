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
 *   2. 차트는 업비트 공개 시세의 일봉 종가다 — 화면에만 보이고 저장하지 않는다 · 오늘 봉은 진행 중이다.
 *
 * 실시간(2026-10-30 사용자 결정 「실제 서비스에서 하듯이 그대로 … 지연되면 큰일나」 · 설계 Figma 「Qurious · 코인 모의매매」 03 · 05)
 *   3. 현재가와 오늘 봉은 업비트 공개 WebSocket(wss://api.upbit.com/websocket/v1 · 인증 없음)으로 체결마다 갱신한다 — 브라우저가 직접 연결하고 앱에는 저장하지 않는다.
 *   4. 시각은 응답의 「체결 타임스탬프(trade_timestamp)」 를 보인다(받은 시각이 아님 — 업비트 문서 ticker 필드 정의).
 *   5. 주문에 쓰이는 가격은 앱이 따로 확인한 값이라 화면 가격 옆에 같이 보이고, 둘이 많이 다르거나 오래되면 알린다 — 앱이 낡은 값을 주문 가격으로 쓸 수 있는 문제를 가리지 않는다.
 *   6. 연결이 안 되면 「실시간」 이라고 쓰지 않는다(연결하는 중 · 끊김 · 지원 안 됨을 글로 구분).
 *   경고 기준 0.5% · 30초는 사용자가 확정했다(2026-10-30 · 처음엔 설계 단계의 제안값이었다).
 */
const isNum = v => typeof v === "number" && Number.isFinite(v);

/** 시세 밑 한 줄 — 출처 · 저장 시간 · 시각 미표시 · 못 받으면 마지막 값. */
export const COIN_SOURCE_NOTE =
  "주문에 쓰이는 가격의 출처: 업비트 공개 시세(원화 현재가) · 약 5초까지 저장해 둔 값 · 받은 시각은 표시되지 않음 — 시세를 받지 못하면 마지막으로 받은 값이 나올 수 있습니다.";

/** 화면 가격(실시간)이 어디서 오는지 — 시세 밑 한 줄. */
export const COIN_LIVE_NOTE =
  "화면의 현재가와 오늘 봉은 업비트 공개 시세를 체결될 때마다 받아 보여 줍니다(연결된 동안). 이 앱에는 저장하지 않습니다.";

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
export function coinChartSummary(points, live = false) {
  if (!points.length) return "일봉 자료를 받지 못했습니다.";
  const vals = points.map(p => p.value);
  const fmt = n => `${Math.round(n).toLocaleString("ko-KR")}원`;
  const last = points[points.length - 1];
  return `최근 ${points.length}일 최고 ${fmt(Math.max(...vals))} · 최저 ${fmt(Math.min(...vals))} · 마지막 일봉 ${fmt(last.value)}(${last.time}) — 업비트 공개 시세의 일봉입니다. `
    + "화면에만 보이고 저장하지 않으며, 오늘 봉은 진행 중이라 값이 바뀝니다. "
    + (live ? "연결된 동안 오늘 봉이 체결마다 움직입니다." : "지금은 실시간으로 연결되어 있지 않아 초 단위로 움직이지 않습니다.");
}

// ── 실시간(업비트 공개 WebSocket · 브라우저 직접 연결) ────────────────────────────────────────────────────────────
export const UPBIT_WS_URL = "wss://api.upbit.com/websocket/v1";
/** 업비트는 120초 동안 오가는 것이 없으면 연결을 끊는다(문서) — 그 절반마다 PING 을 보낸다. */
export const PING_MS = 60000;
/** 경고 기준(제안 — 구현 전 사용자 확인): 화면 가격과 주문 가격 차이 % · 주문 가격 확인이 오래된 한도(초). */
export const GAP_PCT_LIMIT = 0.5;
export const ORDER_AGE_LIMIT_SEC = 30;

/** 구독 메시지 — 현재가(ticker) 한 종목. ticket 은 연결마다 달라야 한다. */
export function coinSubscribeMessage(code, ticket) {
  return JSON.stringify([{ ticket }, { type: "ticker", codes: [code] }, { format: "DEFAULT" }]);
}

/** 수신 데이터(문자열 · ArrayBuffer · 이미 풀린 객체) → 객체. 업비트 문서에는 수신 형식(바이너리 여부)이 적혀 있지 않아 둘 다 받는다. 못 풀면 null. */
export function decodeWsData(data) {
  try {
    if (data && typeof data === "object" && !(data instanceof ArrayBuffer) && !ArrayBuffer.isView(data)) return data;
    const text = typeof data === "string" ? data : new TextDecoder("utf-8").decode(data);
    return JSON.parse(text);
  } catch { return null; }
}

/** ticker 객체 → {code, price, tradeTs, changeRate(%)}. 종목이 다르거나 값이 없으면 null(다른 종목 값이 섞이지 않게). */
export function parseUpbitTicker(msg, code) {
  if (!msg || msg.type !== "ticker" || msg.code !== code) return null;
  const price = Number(msg.trade_price);
  const ts = Number(msg.trade_timestamp ?? msg.timestamp);
  if (!(price > 0) || !isNum(ts)) return null;
  const cr = Number(msg.signed_change_rate);
  return { code, price, tradeTs: ts, changeRate: Number.isFinite(cr) ? cr * 100 : null };
}

const KST_MS = 9 * 3600 * 1000;
const pad2 = n => String(n).padStart(2, "0");
/** 체결 시각(ms) → 한국 시각 「HH:MM:SS」. */
export function kstClock(ms) {
  const d = new Date(ms + KST_MS);
  return `${pad2(d.getUTCHours())}:${pad2(d.getUTCMinutes())}:${pad2(d.getUTCSeconds())}`;
}

/** 체결 시각이 속한 업비트 일봉 날짜 — 일봉은 한국 시각 09:00 에 바뀐다(candle_date_time_kst 의 날짜). 09:00 KST 는 00:00 UTC 라 UTC 날짜가 곧 일봉 날짜다. */
export function coinCandleDate(ms) {
  const d = new Date(ms);
  return `${d.getUTCFullYear()}-${pad2(d.getUTCMonth() + 1)}-${pad2(d.getUTCDate())}`;
}

/** 배지 한 줄 — state: connecting · live · reconnecting · unsupported. tone: ok · warn · mute. */
export function liveBadge(state, tradeTs) {
  if (state === "live" && isNum(tradeTs)) return { text: `● 실시간 · ${kstClock(tradeTs)} 체결`, tone: "ok" };
  if (state === "live") return { text: "● 연결됨 · 체결을 기다리는 중", tone: "ok" };
  if (state === "reconnecting") return { text: `● 다시 연결하는 중${isNum(tradeTs) ? ` · 마지막 체결 ${kstClock(tradeTs)}` : ""}`, tone: "warn" };
  if (state === "unsupported") return { text: "실시간이 아닙니다 · 이 브라우저는 실시간 연결을 지원하지 않습니다", tone: "mute" };
  return { text: "실시간 연결하는 중…", tone: "mute" };
}

/**
 * 화면 가격과 주문에 쓰이는 가격 비교.
 * live: 화면(실시간) 가격 · order: 앱이 확인한 주문 가격 · checkedAt: 그 가격을 앱에 물어본 시각(ms) — 값 자체의 시각이 아니다.
 * 반환 warn=true 면 text 를 경고 상자에 보인다. 두 값 중 하나라도 없으면 경고하지 않고(비교할 수 없음) text 는 빈 글.
 */
export function priceGap({ live, order, checkedAt, now }) {
  if (!(live > 0) || !(order > 0)) return { warn: false, pct: null, ageSec: null, text: "" };
  const pct = Math.abs(live - order) / order * 100;
  const ageSec = isNum(checkedAt) && isNum(now) ? Math.max(0, Math.round((now - checkedAt) / 1000)) : null;
  const parts = [];
  if (pct >= GAP_PCT_LIMIT) parts.push(`화면 가격과 주문 가격이 ${pct.toFixed(1)}% 다릅니다.`);
  if (ageSec != null && ageSec > ORDER_AGE_LIMIT_SEC) parts.push(`주문 가격 확인이 ${ageSec}초 전입니다.`);
  return { warn: parts.length > 0, pct, ageSec, text: parts.length ? `${parts.join(" ")} 주문은 아래 가격으로 체결됩니다.` : "" };
}

/** 주문 가격 줄 — 「98,115,000원 · 14:02:30 확인」. 확인 시각은 앱에 물어본 시각이다. */
export function orderPriceLine(price, checkedAt) {
  if (!(price > 0)) return "주문 가격을 확인하지 못했습니다";
  return `${Math.round(price).toLocaleString("ko-KR")}원${isNum(checkedAt) ? ` · ${kstClock(checkedAt)} 확인` : ""}`;
}

/** 재연결 대기(ms) — 1초에서 두 배씩 늘려 30초까지. attempt 는 0 부터. */
export function reconnectDelay(attempt) {
  return Math.min(30000, 1000 * 2 ** Math.max(0, attempt));
}
