/* 종목 일봉 차트 칸 — 모의주문 시세 조회 · 스탑 주문 · 종목 허브 서랍 · 크게 보기 모달 · 퀀트 대시보드가 같은 부품을 크기만 달리해 쓴다 (2026-11-02 · 사용자 결정 「서랍과 모달 융합」 · 설계 Figma 「Qurious · 종목 허브」 07 쪽 안 C · 안 D)
 * 2026-11-03 S195 — 선 하나였던 차트를 캔들 + 거래량 + 이동평균 · 볼린저 + 크로스헤어 값 + 마지막 신호 한 점 + RSI · MACD 하위 창 + 일정 표식으로 올렸다.
 *
 *   · 데이터는 새로 만들지 않는다 — 종목 허브가 쓰는 수집 일봉 `/api/data/ohlcv` 한 길(야후 참조를 늘리지 않는다 · TC-YH).
 *     일정 표식만 `/api/calendar/events`(수집 DB 일정) 를 더 읽는다.
 *   · 선(이동평균 · 볼린저 · RSI · MACD)은 같은 일봉 종가로 이 화면에서 계산한 표시용 값이다. 정의는 서버 지표(`ta_utils` tv-2026)와 같고
 *     시험(TC-SCH-04)이 같은 종가에서 서버 값과 맞는지 대조한다. 서버의 지표 길(`indicator-strategy/chart`)은 쓰지 않는다 —
 *     그 길은 상대강도 기준선(지수) 때문에 서버가 야후를 다시 부르고, 기간 1개월을 받지 않고, 봉에 거래량이 없다.
 *   · 순수 함수(sc*)는 DOM 없이 글 · 점 · 숫자만 만든다(Node 시험 — tests/test_stockchart.py TC-SCH).
 *   · mountDailyChart 는 차트 라이브러리(Lightweight Charts)를 불러 그린다. 스탑가가 있으면 점선 가격선을 더한다.
 *   · 신호 표식은 기록을 읽어서만 찍는다(새 계산 없음) — 호스트가 setSignal 로 마지막 기록 한 점을 넘긴다.
 *     표식은 화살표가 아니라 중립 점이다 — 기준일 봉 마감에 신호가 났던 것처럼 읽히지 않게(기록은 다음 거래일 낮에 만들어진다).
 *   · draw() 가 돌려주는 값은 「이 칸에 지금 차트가 있는가」다. 종목 · 기간이 같고 스탑가만 바뀌면 차트를 다시 그리지 않고 스탑 점선만 갈아 끼운다.
 *   · 일봉 · 일정은 5분(SC_CACHE_MS) 동안만 캐시한다. 일정을 못 받은 경우는 캐시하지 않고 다음 draw 에서 일정만 다시 받는다.
 */
import { cvSlice, CV_PERIODS } from "./companyview.js";

/** 기간 단추 — companyview.js CV_PERIODS 의 키와 같다 */
export const SC_PERIODS = [["1m", "1개월"], ["3m", "3개월"], ["1y", "1년"]];
export const SC_DEFAULT_PERIOD = "3m";
const LWC_SRC = "/js/vendor/lightweight-charts/lightweight-charts-5.2.1.min.js";
/** 스탑가 빠른 입력(현재가 대비 아래로 · 매도 스탑 쪽) */
export const SC_QUICK_PCTS = [3, 5, 10];

/** 오름 빨강 · 내림 파랑(우리 시장 관례 · 사용자 결정 2026-11-03) */
export const SC_UP = "#dc2626";
export const SC_DOWN = "#2563eb";
/** 스탑가 점선 — 오름 봉 빨강에 묻히지 않게 짙은 남색 */
export const SC_STOP_COLOR = "#0f172a";
/** 이동평균을 처음 창이 차는 날부터 그리려고 더 받는 날수(달력일) — 1년(366) + 60봉 + MACD 35봉 여유 */
const SC_WARM_DAYS = 500;
/** 하위 창 하나가 더하는 높이(px) */
const SC_PANE_H = 92;
/** 켜고 끄는 칩 — [키, 글, 처음 상태] (처음에는 거래량과 20일선만 켠다 — 많이 켜 둘수록 정밀해 보이는 착시를 막는다) */
export const SC_TOGGLES = [["vol", "거래량", true], ["ma20", "20일선", true], ["ma60", "60일선", false], ["bb", "볼린저", false], ["rsi", "RSI", false], ["macd", "MACD", false]];
/** 선 색 — 흰 바탕에서 선(1px)이 읽히도록 짙게 잡았다(옛 호박색은 흰 바탕과 대비 2.1:1). 칩의 색 견본과 같은 값을 쓴다 */
export const SC_LINE_COLORS = { ma20: "#b45309", ma60: "#047857", bb: "#64748b", rsi: "#0369a1", macd: "#0369a1", macdSignal: "#c2410c" };
/** 칩 글자 앞의 색 견본 — 어느 선이 무엇인지 칩으로 알 수 있게 (MACD 는 MACD선 · 신호선 둘) */
export const SC_CHIP_SWATCH = { ma20: [SC_LINE_COLORS.ma20], ma60: [SC_LINE_COLORS.ma60], bb: [SC_LINE_COLORS.bb], rsi: [SC_LINE_COLORS.rsi], macd: [SC_LINE_COLORS.macd, SC_LINE_COLORS.macdSignal] };
/** 받아 둔 일봉 · 일정을 그대로 쓰는 시간(ms) — 지나면 다시 받는다 */
export const SC_CACHE_MS = 5 * 60 * 1000;
/** 칸 높이를 잴 수 없을 때(숨은 칸) 이번 그림에만 쓰는 높이(px) — 굳히지 않는다 */
const SC_BASE_H_FALLBACK = 150;
/** 스탑가가 마지막 종가에서 이만큼(%) 안이면 가격 범위를 넓혀 점선을 화면 안에 둔다. 더 멀면 차트가 납작해지므로 넓히지 않고 글로 알린다 */
export const SC_STOP_NEAR_PCT = 30;

/** 일봉 요청에 보낼 6자리 단축코드 — 「005930」 · 「005930.KS」 · ETF 「0000D0」. 아니면 빈 글(요청을 보내지 않는다) */
export function scCode(symbol) {
  const m = /^([0-9A-Za-z]{6})(?:\.(?:KS|KQ))?$/i.exec(String(symbol || "").trim());
  return m ? m[1].toUpperCase() : "";
}

export function scPath(symbol) {
  const code = scCode(symbol);
  return code ? `/api/data/ohlcv?symbol=${code}` : "";
}

/** 오늘(한국 날짜) — 서버 날짜 규칙과 같이 KST 로 읽는다 */
export function scToday(nowMs = Date.now()) {
  return new Date(nowMs + 9 * 3600 * 1000).toISOString().slice(0, 10);
}

function scShiftDay(day, delta) {
  return new Date(Date.parse(`${day}T00:00:00Z`) + delta * 86400000).toISOString().slice(0, 10);
}

/** 계산용으로 이동평균 창이 찰 만큼 앞에서부터 받는 일봉 주소 (scPath 에 시작일만 더한다) */
export function scPathWarm(symbol, today) {
  const base = scPath(symbol);
  return base ? `${base}&from=${scShiftDay(today || scToday(), -SC_WARM_DAYS)}` : "";
}

/** 종목 일정 주소 — 실적 · 배당락 · 주주총회만(공시는 실적과 겹치고 뉴스는 이름이 같은 다른 기사가 섞여 찍지 않는다) */
export function scEventsPath(symbol, from, to) {
  const code = scCode(symbol);
  return code ? `/api/calendar/events?symbol=${code}&kind=earnings,dividend_ex,agm&from=${from}&to=${to}&limit=300` : "";
}

/** 일봉 줄 → 선 차트 점(마지막 날 기준 기간 안) */
export function scPoints(rows, period) {
  return cvSlice(rows, period || SC_DEFAULT_PERIOD);
}

/** 수집 일봉의 종가 종류 — 서버(`/api/data/ohlcv`)가 준 basis 그대로. 주식은 수정주가(adj_base)가 기본이고 ETF · 지수는 수정하지 않은 값(raw)이다.
 *  응답에 basis 가 없으면(호스트가 준 줄) 어느 쪽인지 모르므로 말하지 않는다 */
export function scBasisWords(basis) {
  if (basis === "adj_base") return "일봉(수정주가) 종가";
  if (basis === "raw") return "일봉 중 수정하지 않은 종가";
  return "일봉 종가";
}

/** 차트 아래 글 — 최고 · 최저 · 마지막 종가 + 출처 · 한계(실시간 차트가 아님). 스탑가가 있으면 그 값도 적는다. basis 는 서버가 준 종가 종류 */
export function scSummary(points, stop, basis) {
  if (!points.length) return "일봉 자료가 없습니다 — 수집 범위 밖의 종목이거나 아직 받지 못했습니다.";
  const fmt = n => `${Math.round(n).toLocaleString("ko-KR")}원`;
  const vals = points.map(p => p.value);
  const last = points[points.length - 1];
  let text = `최고 ${fmt(Math.max(...vals))} · 최저 ${fmt(Math.min(...vals))} · 마지막 종가 ${fmt(last.value)}(${last.time}) — 우리 수집 ${scBasisWords(basis)}이며 실시간 차트가 아닙니다.`;
  if (Number.isFinite(stop) && stop > 0) text += ` 검은 점선은 입력한 스탑가 ${fmt(stop)}입니다.`;
  return text;
}

/** 가격 글 — 국내 코드는 정수(원), 그 밖은 1000 이상이면 정수 · 미만이면 소수 둘(해외 종목 · 지수) */
export function scPrice(v, whole = true) {
  return (whole || Math.abs(v) >= 1000) ? Math.round(v).toLocaleString("ko-KR") : v.toFixed(2);
}

/** 국내 코드가 아닌 종목(통화를 모른다)의 아래 글 — 원 · 수정주가를 말하지 않고 최고 · 최저 · 마지막 종가만 */
export function scSummaryPlain(points) {
  if (!points.length) return "일봉 자료가 없습니다.";
  const vals = points.map(p => p.value);
  const last = points[points.length - 1];
  const f = n => scPrice(n, false);
  return `최고 ${f(Math.max(...vals))} · 최저 ${f(Math.min(...vals))} · 마지막 종가 ${f(last.value)}(${last.time}) — 일봉 종가이며 실시간 차트가 아닙니다.`;
}

/** 스탑가를 현재가와 견준 한 줄 — 어느 쪽 스탑으로 써야 하는지, 반대로 등록하면 어떻게 되는지 */
export function scDirection(current, stop) {
  const c = Number(current), s = Number(stop);
  if (!Number.isFinite(c) || c <= 0 || !Number.isFinite(s) || s <= 0) return "";
  const pct = Math.abs((s - c) / c * 100).toFixed(1);
  if (s < c) return `스탑가가 현재가보다 ${pct}% 낮습니다 — 매도 스탑(손절)으로 쓰는 값입니다. 매수 스탑은 서버 기준 시세보다 높아야 등록할 수 있습니다.`;
  if (s > c) return `스탑가가 현재가보다 ${pct}% 높습니다 — 매수 스탑으로 쓰는 값입니다. 매도 스탑은 서버 기준 시세보다 낮아야 등록할 수 있습니다.`;
  return "스탑가가 현재가와 같습니다 — 서버 기준 시세와 같은 스탑가는 등록할 수 없습니다.";
}

/** 지금 시세에서 이미 닿아 있어 등록 즉시 발동할 스탑인가(서버 check_stop_orders 와 같은 조건 — 매도는 현재가 ≤ 스탑가 · 매수는 현재가 ≥ 스탑가) */
export function scWouldFireNow(side, current, stop) {
  const c = Number(current), s = Number(stop);
  if (!Number.isFinite(c) || !Number.isFinite(s) || c <= 0 || s <= 0) return false;
  const sd = String(side || "").toUpperCase();
  return (sd === "SELL" && c <= s) || (sd === "BUY" && c >= s);
}

/** 빠른 단추 값 — 현재가 −3% · −5% · −10%(원 단위 반올림). 현재가가 없으면 빈 목록 */
export function scQuickStops(current) {
  const c = Number(current);
  if (!Number.isFinite(c) || c <= 0) return [];
  return SC_QUICK_PCTS.map(p => ({ label: `−${p}%`, value: Math.round(c * (100 - p) / 100) }));
}

/** 스탑가와 보이는 가격 범위의 관계 — "in"(이미 범위 안) · "extend"(범위 밖이지만 마지막 종가에서 가까워 범위를 넓힌다) · "far"(너무 멀어 넓히지 않는다) · "none"(스탑가 없음).
 *  lo · hi 는 보이는 봉의 최저 · 최고, lastClose 는 마지막 종가 */
export function scStopFit(stop, lo, hi, lastClose) {
  const s = Number(stop);
  if (!Number.isFinite(s) || s <= 0 || !Number.isFinite(lo) || !Number.isFinite(hi)) return "none";
  if (s >= lo && s <= hi) return "in";
  const c = Number(lastClose);
  return Number.isFinite(c) && c > 0 && Math.abs(s - c) / c * 100 <= SC_STOP_NEAR_PCT ? "extend" : "far";
}

/** 기간 키 → 말 (칩 글자와 같게 · 칩에 없는 기간은 「6개월」 꼴로) */
export function scPeriodLabel(period) {
  const hit = SC_PERIODS.find(p => p[0] === period);
  if (hit) return hit[1];
  const m = /^(\d+)([my])$/.exec(String(period || ""));
  return m ? `${m[1]}${m[2] === "m" ? "개월" : "년"}` : String(period || "");
}

/** 차트 칸의 화면 낭독용 이름표 — 종목 · 기간 · 마지막 종가. 점이 없으면 빈 글 */
export function scAriaLabel(symbol, period, points) {
  if (!points || !points.length) return "";
  const last = points[points.length - 1];
  const whole = !!scCode(symbol);
  return `${String(symbol || "종목")} ${scPeriodLabel(period)} 일봉 차트 — 마지막 종가 ${scPrice(last.value, whole)}${whole ? "원" : ""}(${last.time})`;
}

// ── 봉 · 지표 계산(순수) ───────────────────────────────────────────────────────

const scNum = v => typeof v === "number" && Number.isFinite(v);

/** 일봉 줄 → 날짜 순 봉 목록 {time, open, high, low, close, volume}. 종가나 날짜가 없는 줄은 뺀다 · 같은 날짜는 나중 줄 · 시가 · 고가 · 저가 · 거래량은 없으면 null */
export function scBars(rows) {
  const byDay = new Map();
  (Array.isArray(rows) ? rows : []).forEach(r => {
    if (!r || !scNum(r.close) || !r.trade_date) return;
    const day = String(r.trade_date).slice(0, 10);
    byDay.set(day, {
      time: day, open: scNum(r.open) ? r.open : null, high: scNum(r.high) ? r.high : null, low: scNum(r.low) ? r.low : null,
      close: r.close, volume: scNum(r.volume) && r.volume >= 0 ? r.volume : null,
    });
  });
  return [...byDay.values()].sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : 0));
}

/** 모든 봉에 시가 · 고가 · 저가가 있는가 — 하나라도 비면 값을 지어내지 않고 종가 선으로 그린다 */
export function scHasOhlc(bars) {
  return bars.length > 0 && bars.every(b => b.open !== null && b.high !== null && b.low !== null && b.high >= b.low);
}

/** 기간 안에서 가장 앞선 봉의 위치 — cvSlice 와 같은 규칙(마지막 날 기준 기간 날수) */
export function scStart(bars, period) {
  if (!bars.length) return 0;
  const days = CV_PERIODS[period] || CV_PERIODS["6m"];
  const lo = Date.parse(`${bars[bars.length - 1].time}T00:00:00Z`) - days * 86400000;
  const i = bars.findIndex(b => Date.parse(`${b.time}T00:00:00Z`) >= lo);
  return i < 0 ? 0 : i;
}

/** 단순 이동평균 — 창이 차기 전은 null (`ta_utils.sma`) */
export function scSma(vals, n) {
  const out = vals.map(() => null);
  let sum = 0;
  vals.forEach((v, i) => {
    sum += v;
    if (i >= n) sum -= vals[i - n];
    if (i >= n - 1) out[i] = sum / n;
  });
  return out;
}

/** 볼린저 밴드 20 · 2σ — 표준편차는 모집단(나눗수 n) (`ta_utils.bollinger`) */
export function scBollinger(vals, n = 20, mult = 2) {
  const mid = scSma(vals, n);
  const upper = vals.map(() => null), lower = vals.map(() => null);
  for (let i = n - 1; i < vals.length; i += 1) {
    let sq = 0;
    for (let j = i - n + 1; j <= i; j += 1) sq += (vals[j] - mid[i]) ** 2;
    const sd = Math.sqrt(sq / n);
    upper[i] = mid[i] + mult * sd;
    lower[i] = mid[i] - mult * sd;
  }
  return { upper, mid, lower };
}

/** RSI(14) — Wilder 평활, 처음 n개 변화의 평균을 씨앗으로 (`ta_utils.rsi`) */
export function scRsi(vals, n = 14) {
  const out = vals.map(() => null);
  if (vals.length <= n) return out;
  const value = (g, l) => (l === 0 ? 100 : g === 0 ? 0 : 100 - 100 / (1 + g / l));
  let g = 0, l = 0;
  for (let i = 1; i <= n; i += 1) { const d = vals[i] - vals[i - 1]; g += Math.max(d, 0); l += Math.max(-d, 0); }
  g /= n; l /= n;
  out[n] = value(g, l);
  for (let i = n + 1; i < vals.length; i += 1) {
    const d = vals[i] - vals[i - 1];
    g = (g * (n - 1) + Math.max(d, 0)) / n;
    l = (l * (n - 1) + Math.max(-d, 0)) / n;
    out[i] = value(g, l);
  }
  return out;
}

/** 지수이동평균 — 첫 값에서 시작, α = 2/(span+1) (`ta_utils.ema` · pandas ewm adjust=False) */
export function scEma(vals, span) {
  const a = 2 / (span + 1);
  const out = [];
  vals.forEach((v, i) => out.push(i === 0 ? v : a * v + (1 - a) * out[i - 1]));
  return out;
}

/** MACD 12 · 26 · 9 — 선 · 신호선 · 막대 (`ta_utils.macd`) */
export function scMacd(vals, fast = 12, slow = 26, signal = 9) {
  const f = scEma(vals, fast), s = scEma(vals, slow);
  const macd = f.map((v, i) => v - s[i]);
  const sig = scEma(macd, signal);
  return { macd, signal: sig, hist: macd.map((v, i) => v - sig[i]) };
}

// ── 글 · 표식(순수) ─────────────────────────────────────────────────────────────

const scWon = n => Math.round(n).toLocaleString("ko-KR");

/** 크로스헤어를 따라가는 값 줄 — 날짜 · 시가 · 고가 · 저가 · 종가 · 전일 대비 · 거래량 (+ 그날의 기록 · 일정). 시가 · 고가 · 저가가 없으면 종가만 */
export function scLegendText(bar, prev, marks, whole = true) {
  if (!bar) return "";
  const won = n => scPrice(n, whole);
  const parts = [bar.time];
  if (bar.open !== null && bar.high !== null && bar.low !== null) {
    parts.push(`시 ${won(bar.open)}`, `고 ${won(bar.high)}`, `저 ${won(bar.low)}`);
  }
  let close = `종 ${won(bar.close)}`;
  if (prev && scNum(prev.close) && prev.close > 0) {
    const pct = (bar.close - prev.close) / prev.close * 100;
    close += ` (${pct > 0 ? "+" : pct < 0 ? "−" : ""}${Math.abs(pct).toFixed(2)}%)`;
  }
  parts.push(close);
  if (bar.volume !== null) parts.push(`거래량 ${scWon(bar.volume)}`);
  let text = parts.join(" · ");
  if (marks && marks.length) text += ` — ${marks.join(" · ")}`;
  return text;
}

/** 신호 표식 — 매수 · 매도 · 관망 모두 같은 중립 점이다. 화살표(▲ ▼)는 그 봉 마감에 신호가 난 것처럼 읽혀 쓰지 않는다.
 *  어느 쪽 기록인지는 점이 아니라 값 줄 · 아래 풀이 글이 말한다 */
const SC_SIGNAL_LOOK = {
  buy: { words: "매수 쪽" },
  sell: { words: "매도 쪽" },
  hold: { words: "관망" },
};
const SC_SIGNAL_DOT = { text: "신호 기록", shape: "circle", position: "belowBar", glyph: "●" };
/** 신호 표식 색 — 봉 · 선 어느 쪽과도 겹치지 않는 보라 (색만으로 구분하지 않고 모양과 글자를 함께 쓴다) */
const SC_SIGNAL_COLOR = "#7c3aed";
const SC_EVENT_COLOR = "#475569";
/** 신호가 여러 주기를 합친 값이라는 말 — 서버 신호 칸의 출처 줄(60분 · 일 · 주봉 규칙 점수의 합)과 같다 */
const SC_SIGNAL_MULTI = "여러 주기(60분 · 일 · 주)를 합친 기록";

/** 호스트가 준 신호가 지금 그리는 종목의 것인가 — 종목을 밝히지 않은 신호(옛 호출)는 그대로 쓴다. 「005930」 · 「005930.KS」 는 같은 종목 */
export function scSignalFits(sig, symbol) {
  if (!sig) return false;
  if (!sig.symbol) return true;
  const key = s => scCode(s) || String(s || "").trim().toUpperCase();
  return key(sig.symbol) === key(symbol);
}

/** 마지막으로 기록된 신호 한 줄 → 차트 표식. 기록의 기준일 봉에만 찍는다(그 이후 값으로 과거 봉을 바꾸지 않는다). 그 날짜 봉이 보이는 기간에 없으면 null.
 *  표식 위치를 다음 거래일 봉으로 옮기지 않는다 — 그 봉은 기록이 만들어질 때 아직 없는 경우가 많다. 대신 풀이 글이 기록 시점을 말한다.
 *  sig: { asOf: "YYYY-MM-DD", side: "매수" | "매도" | "관망" } */
export function scSignalMark(sig, bars) {
  if (!sig || typeof sig.asOf !== "string" || !/^\d{4}-\d{2}-\d{2}/.test(sig.asOf)) return null;
  const day = sig.asOf.slice(0, 10);
  if (!bars.some(b => b.time === day)) return null;
  const side = String(sig.side || "");
  const look = side.includes("매수") ? SC_SIGNAL_LOOK.buy : side.includes("매도") ? SC_SIGNAL_LOOK.sell : SC_SIGNAL_LOOK.hold;
  return { time: day, kind: "signal", text: SC_SIGNAL_DOT.text, shape: SC_SIGNAL_DOT.shape, position: SC_SIGNAL_DOT.position, glyph: SC_SIGNAL_DOT.glyph, words: look.words, color: SC_SIGNAL_COLOR };
}

/** 신호 표식 풀이 — 기준일 · 기록 시점(다음 거래일 낮) · 여러 주기를 합친 값 · 뒤 가격은 재지 않음. 그날 종가에 이미 알 수 있던 값처럼 읽히지 않게 */
export function scSignalNote(mark, asOf, rec) {
  if (!mark) return "";
  const day = String(asOf || mark.time).slice(5, 10);
  const what = mark.words === "관망" ? "관망이었다는" : `${mark.words}이었다는`;
  const at = rec && /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(String(rec.computedAt || "")) ? String(rec.computedAt).slice(5, 16) : "";   // 「11-03 12:59」 — 기록 시각(서버가 줄 때만)
  const when = !at ? "이 신호는 그날 종가까지로 계산해 다음 거래일 낮에 기록됩니다(그날 종가에 이미 알 수 있던 값이 아닙니다)."
    : rec.late ? `이 신호는 ${at} 에 늦게 계산한 값이라 그날 이 화면에서 실제로 보였던 값은 아닐 수 있습니다.`
      : `이 신호는 그날 종가까지로 계산해 ${at} 에 기록했습니다(그날 종가에 이미 알 수 있던 값이 아닙니다).`;
  return `${mark.glyph} 표시는 ${day} 종가까지의 규칙 점수가 ${what} 기록이며, ${when} 이 표시 뒤 가격은 이 화면이 재지 않습니다. 점수는 ${SC_SIGNAL_MULTI}이라 이 차트의 일봉 하나만으로 만든 값이 아닙니다(분봉이 없는 종목은 일 · 주). `
    + `같은 기준일의 일봉 근거는 이 차트와 같은 수정주가 일봉이라 값이 같지만, 다를 수 있는 때가 셋 있습니다 — 60분 · 주 근거(이 차트에 없는 주기) · 차트 마지막 봉이 기록 기준일보다 뒤일 때 · 기준일 뒤 분할 · 증자로 수정주가가 다시 계산되어 이동평균 · 볼린저 같은 가격 값이 바뀐 때입니다.`;
}

/** 신호 표식을 못 찍은 까닭 — 기준일이 마지막 봉보다 뒤(아직 그 날 일봉이 안 들어옴) · 보이는 기간 앞 · 기간 안인데 봉이 없는 날(휴장 · 미수집)을 가른다 */
export function scSignalMissNote(sig, shown) {
  if (!sig || !shown || !shown.length) return "";
  if (typeof sig.asOf !== "string" || !/^\d{4}-\d{2}-\d{2}/.test(sig.asOf)) return "기록된 신호의 기준일을 읽지 못해 신호 표시는 그리지 않았습니다.";
  const day = sig.asOf.slice(0, 10), first = shown[0].time, lastDay = shown[shown.length - 1].time;
  if (day > lastDay) return `기록된 신호의 기준일(${day.slice(5)})이 일봉의 마지막 봉(${lastDay.slice(5)})보다 뒤라 아직 그 날의 일봉이 들어오지 않아 신호 표시는 그리지 않았습니다.`;
  if (day < first) return "기록된 신호의 기준일 봉이 지금 보이는 기간에 없어 신호 표시는 그리지 않았습니다.";
  return `기록된 신호의 기준일(${day.slice(5)})에는 일봉이 없어(휴장일이거나 수집되지 않은 날) 신호 표시는 그리지 않았습니다.`;
}

const SC_EVENT_LOOK = { earnings: ["실적", "실적 발표"], dividend_ex: ["배당락", "배당락일"], agm: ["주총", "주주총회"] };

/** 일정 응답의 events → 차트 표식. 봉이 있는 날짜의 일정만 찍는다. 봉이 없는 날은 오늘(KST) 기준으로 가른다 —
 *  오늘 이후면 upcoming(앞으로 예정), 지난 날인데 봉이 없으면 noBar 로 센다(휴장일이거나 일봉이 아직 안 들어온 날 — 월요일 오전에 지난 일정이 「예정」으로 나오지 않게).
 *  마지막 봉이 아니라 today 를 기준으로 삼는 이유: 일봉은 하루 늦게 들어올 수 있다. today 는 시험에서 고정해 쓴다 */
export function scEventMarks(events, bars, today = scToday()) {
  const days = new Set(bars.map(b => b.time));
  const first = bars.length ? bars[0].time : "";
  const marks = [], upcoming = [];
  let noBar = 0;
  (Array.isArray(events) ? events : []).forEach(e => {
    const look = e && SC_EVENT_LOOK[e.kind];
    const day = e && typeof e.date === "string" ? e.date.slice(0, 10) : "";
    if (!look || !day) return;
    const label = `${e.kind_label || look[1]}${e.confidence_label ? `(${e.confidence_label})` : ""}`;
    if (days.has(day)) marks.push({ time: day, kind: e.kind, text: look[0], shape: "square", position: "aboveBar", color: SC_EVENT_COLOR, label });
    else if (day >= today) upcoming.push({ time: day, label });
    else if (first && day >= first) noBar += 1;
  });
  upcoming.sort((a, b) => (a.time < b.time ? -1 : 1));
  return { marks, upcoming, noBar };
}

/** 표식 두 묶음을 하나의 시간순 목록으로 — 한 계열에는 한 번에 한 배열만 건다(라이브러리 표식 묶음이 덮어쓰기라서) */
export function scMarkerList(signalMark, eventMarks) {
  const all = [...(signalMark ? [signalMark] : []), ...(eventMarks || [])];
  return all.map(m => ({ time: m.time, position: m.position, color: m.color, shape: m.shape, text: m.text }))
    .sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : 0));
}

/** 날짜별 표식 풀이(크로스헤어 값 줄 끝에 붙는다) */
export function scMarksByDay(signalMark, eventMarks, sig) {
  const map = new Map();
  const add = (day, text) => map.set(day, [...(map.get(day) || []), text]);
  if (signalMark) add(signalMark.time, `기록된 신호 ${signalMark.words} (${sig && sig.asOf ? `${String(sig.asOf).slice(5, 10)} 기준 · ` : ""}${SC_SIGNAL_MULTI})`);
  (eventMarks || []).forEach(m => add(m.time, m.label));
  return map;
}

/** 크로스헤어 time → 날짜 글(라이브러리가 글 · 연월일 객체 어느 쪽으로 줘도) */
export function scTimeKey(t) {
  if (typeof t === "string") return t.slice(0, 10);
  if (t && typeof t === "object" && Number.isFinite(t.year)) return `${t.year}-${String(t.month).padStart(2, "0")}-${String(t.day).padStart(2, "0")}`;
  return "";
}

let lwcPromise = null;
/** 차트 라이브러리 한 번만 불러오기 — 상품 차트(productchart.js) · tradingview.js 의 loadLwc 와 이름이 겹치지 않게 sc 를 붙였다 */
function scLoadLwc(doc) {
  const w = doc.defaultView;
  if (w.LightweightCharts) return Promise.resolve(w.LightweightCharts);
  if (!lwcPromise) {
    lwcPromise = new Promise((resolve, reject) => {
      const el = doc.createElement("script");
      el.src = LWC_SRC;
      const timer = setTimeout(() => reject(new Error("timeout")), 15000);
      el.onload = () => { clearTimeout(timer); w.LightweightCharts ? resolve(w.LightweightCharts) : reject(new Error("empty")); };
      el.onerror = () => { clearTimeout(timer); reject(new Error("load")); };
      doc.head.appendChild(el);
    }).catch(e => { lwcPromise = null; throw e; });
  }
  return lwcPromise;
}

/** 칸 하나에 일봉 차트를 그린다. 돌려주는 draw(opts) 는 종목 · 기간 · 스탑가가 바뀔 때마다 다시 부른다(늦게 온 응답은 버린다).
 *  돌려주는 값은 「이 칸에 지금 차트가 있는가」다 — 그렸으면 true, 못 그렸거나 새 요청(다른 종목 · 기간 · destroy)에 밀렸으면 false.
 *  칩 누름 · 신호 도착(setSignal)이 그림을 다시 시작해도 그 그림이 이어받으므로 그 결과를 돌려준다(그냥 false 로 돌려주면 호스트가 정상 캔들을 대체 줄로 덮는다).
 *  종목 · 기간이 같고 스탑가만 다르면 차트를 다시 그리지 않고 스탑 점선 하나만 갈아 끼운 뒤 true 를 돌려준다.
 *  opts: { symbol, period, stop, rows } — rows(선택)는 호스트가 가진 일봉 줄({ trade_date, close, … })이다 — 주면 요청을 보내지 않는다.
 *  box 는 높이가 정해진 칸 · note 는 아래 글 칸.
 *  box 바로 앞에 켜고 끄는 칩 줄을 끼운다(box 안이 아니라 형제 — 다시 그릴 때 지워지지 않게). 돌려주는 setSignal(sig) 은 마지막 기록 한 점(기준일 · 매수/매도/관망)을 받는다 */
export function mountDailyChart(doc, box, note, { api, onError } = {}) {
  let chart = null, seq = 0, drawId = 0, bar = null, legendEl = null, chips = [], baseH = 0, ownH = "";
  // 받아 둔 일봉 · 일정 — symbol 은 이 줄이 어느 종목 요청의 것인가(다른 종목이 그려지는 중에 옛 줄로 다시 그리지 않게) · at 은 받은 시각
  let cache = { code: "", symbol: "", rows: [], events: null, eventsFailed: false, basis: "", at: 0 };
  let sig = null;
  let last = { symbol: "", period: SC_DEFAULT_PERIOD, stop: undefined };
  const on = Object.fromEntries(SC_TOGGLES.map(([k, , v]) => [k, v]));
  let lines = {};                                   // 다시 그리지 않고 켜고 끄는 계열
  let ctx = null;                                   // 아래 글을 만들 재료
  let mainSeries = null, stopLine = null;           // 스탑가만 바뀔 때 점선 하나만 갈아 끼우려고 잡아 둔다
  let task = null;                                  // 가장 나중에 시작한 그림 작업 — 밀린 draw 가 이 작업을 이어받아 기다린다

  box.classList.add("pc-dc-box");

  const stopOk = s => Number.isFinite(s) && s > 0;

  function ensureBar() {
    if (bar && bar.isConnected) return;
    if (!box.parentNode) return;
    bar = doc.createElement("div");
    bar.className = "pc-dc-bar";
    bar.setAttribute("role", "group");
    bar.setAttribute("aria-label", "차트에 겹쳐 볼 것 고르기");
    chips = SC_TOGGLES.map(([key, label]) => {
      const btn = doc.createElement("button");
      btn.type = "button";
      btn.className = "pc-dc-chip";
      btn.dataset.pcDc = key;
      // 색 견본 — 선이 여럿일 때 어느 선이 무엇인지 칩으로 알게 한다(견본은 장식이라 낭독에서 뺀다)
      (SC_CHIP_SWATCH[key] || []).forEach(color => {
        const sw = doc.createElement("span");
        sw.className = "pc-dc-sw";
        sw.setAttribute("aria-hidden", "true");
        sw.style.background = color;
        btn.appendChild(sw);
      });
      const text = doc.createElement("span");
      text.textContent = label;
      btn.appendChild(text);
      btn.setAttribute("aria-pressed", "false");
      btn.addEventListener("click", () => {
        on[key] = !on[key];
        syncChips();
        if (key === "rsi" || key === "macd") { renderSoon(); return; }        // 하위 창은 칸 높이가 바뀌어 다시 그린다
        (lines[key] || []).forEach(s => s.applyOptions({ visible: on[key] }));
        if (key === "vol" && chart) chart.priceScale("right").applyOptions({ scaleMargins: { top: 0.08, bottom: on.vol ? 0.24 : 0.08 } });
        paintNote();
      });
      bar.appendChild(btn);
      return btn;
    });
    box.parentNode.insertBefore(bar, box);
    // 크로스헤어 값 줄 — 차트 위에 겹치지 않고 칩 줄 아래 한 줄(좁은 화면에서는 석 줄 높이를 미리 잡아 둔다)로 둔다. box 의 형제라 다시 그려도 남는다
    legendEl = doc.createElement("div");
    legendEl.className = "pc-dc-legend";
    legendEl.setAttribute("aria-hidden", "true");
    box.parentNode.insertBefore(legendEl, box);
  }
  function syncChips() {
    chips.forEach(b => b.setAttribute("aria-pressed", String(!!on[b.dataset.pcDc])));
  }
  function removeChart() {
    if (chart) { try { chart.remove(); } catch { /* 이미 걷힌 차트 */ } chart = null; }
    lines = {};
    mainSeries = null;
    stopLine = null;
  }
  /** 차트 칸의 화면 낭독용 이름표 — 그림이 있을 때만(없으면 걷는다) */
  function setLabel(points) {
    const text = points && points.length ? scAriaLabel(last.symbol, last.period, points) : "";
    if (text) { box.setAttribute("role", "img"); box.setAttribute("aria-label", text); return; }
    box.removeAttribute?.("role");
    box.removeAttribute?.("aria-label");
  }
  /** 지금 그리는 종목의 신호만 — 다른 종목용으로 넘어온 신호는 쓰지 않는다 */
  const sigNow = () => (scSignalFits(sig, last.symbol) ? sig : null);

  /** 아래 글 — 켠 것에 해당하는 풀이만 붙인다 */
  function paintNote() {
    if (!ctx) return;
    const t = [ctx.foreign ? scSummaryPlain(ctx.pts) : scSummary(ctx.pts, ctx.stop, ctx.basis)];
    t.push(ctx.ohlc ? "봉은 오름 빨강 · 내림 파랑입니다." : "시가 · 고가 · 저가가 없어 종가 선으로 보입니다.");
    if (stopOk(ctx.stop) && scStopFit(ctx.stop, ctx.lo, ctx.hi, ctx.lastClose) === "far") {
      t.push(`스탑가 ${scPrice(ctx.stop, !ctx.foreign)}은 마지막 종가에서 ${SC_STOP_NEAR_PCT}% 넘게 떨어져 이 차트의 가격 범위 밖입니다 — 차트가 납작해지지 않게 범위를 넓히지 않아 점선이 화면에 보이지 않습니다.`);
    }
    if (stopOk(ctx.stop) && scStopFit(ctx.stop, ctx.lo, ctx.hi, ctx.lastClose) === "extend") t.push("스탑가 점선이 보이도록 가격 범위를 넓혀 봉이 작게 보일 수 있습니다.");
    if (on.vol && ctx.hasVolume) t.push("막대는 그날 거래량이고, 색은 종가가 시가보다 높았는지(빨강) 낮았는지(파랑)입니다.");
    if (on.ma20 || on.ma60 || on.bb || on.rsi || on.macd) t.push("선은 같은 일봉 종가로 이 화면에서 계산한 표시용 값이며(서버가 기록한 신호 값이 아닙니다) 앞으로의 가격을 알려 주지 않습니다.");
    if (on.rsi) t.push("RSI의 30 · 70 점선은 많이 쓰는 관례 기준선이며, 넘었다고 가격의 방향이 바뀐다는 뜻은 아닙니다.");
    if (on.macd) t.push("MACD 창의 막대는 MACD선과 신호선의 차이이고, 오른쪽 이름표가 두 선을 가립니다.");
    if (ctx.signalNote) t.push(ctx.signalNote);
    if (ctx.eventNote) t.push(ctx.eventNote);
    note.textContent = t.join(" ");
  }

  const nextFrame = () => new Promise(r => { const w = doc.defaultView; (w && w.requestAnimationFrame ? w.requestAnimationFrame.bind(w) : cb => setTimeout(cb, 16))(r); });

  /** 칸의 기본 높이 — 처음 한 번 잰 값을 쓴다. 숨은 칸이라 잴 수 없으면(0) 이번 그림에만 150px 를 쓰고 굳히지 않는다(다음 그림에서 다시 잰다) */
  function measureBase() {
    if (baseH) return baseH;
    if (box.style.height === ownH) box.style.height = "";        // 이 부품이 박아 둔 높이(하위 창 몫이 섞임)는 읽지 않는다 — 걷고 본래 높이를 다시 잰다
    const h = parseFloat(box.style.height) || box.clientHeight;
    if (h > 0) { baseH = h; return h; }
    return SC_BASE_H_FALLBACK;
  }

  /** 가격 범위 계산 보조 — 스탑가가 범위 밖이지만 가까우면 범위를 스탑가까지 넓혀 점선이 화면 안에 놓이게 한다. 지금 스탑가를 읽으므로 스탑가가 바뀌어도 같은 함수를 쓴다 */
  const autoscale = original => {
    const r = original();
    if (!r || !r.priceRange || !ctx || !stopOk(last.stop)) return r;
    if (scStopFit(last.stop, ctx.lo, ctx.hi, ctx.lastClose) !== "extend") return r;
    return { ...r, priceRange: { minValue: Math.min(r.priceRange.minValue, last.stop), maxValue: Math.max(r.priceRange.maxValue, last.stop) } };
  };
  const stopOpts = price => ({ price, color: SC_STOP_COLOR, lineWidth: 2, lineStyle: 2, axisLabelVisible: true, title: "스탑가" });
  /** 스탑 점선 하나를 지우고(있으면) 지금 스탑가로 다시 만든다 — 차트는 그대로 두고 가격 범위만 다시 재게 한다 */
  function applyStop() {
    if (!mainSeries) return;
    if (stopLine) { try { mainSeries.removePriceLine(stopLine); } catch { /* 이미 없는 선 */ } stopLine = null; }
    if (stopOk(last.stop)) stopLine = mainSeries.createPriceLine(stopOpts(last.stop));
    mainSeries.applyOptions({ autoscaleInfoProvider: autoscale });
  }

  /** 받아 둔 일봉으로 차트를 그린다. 그렸으면 true — 못 그렸거나(자료 없음 · 라이브러리 · 예외) 새 요청에 밀렸으면 false */
  async function render(mine) {
    removeChart();
    box.replaceChildren();
    const bars = scBars(cache.rows);
    const startAt = scStart(bars, last.period);
    const shown = bars.slice(startAt);
    ctx = null;
    const pts = shown.map(b => ({ time: b.time, value: b.close }));
    if (!pts.length) { note.textContent = scSummary([], last.stop); if (bar) bar.hidden = true; if (legendEl) legendEl.textContent = ""; setLabel(null); return false; }
    const ohlc = scHasOhlc(shown);
    const sg = sigNow();
    const signalMark = scSignalMark(sg, shown);
    const today = scToday();
    const ev = scEventMarks(cache.events, shown, today);
    const whole = !!scCode(last.symbol);            // 국내 코드가 아니면(해외 · 지수) 가격에 소수를 보인다
    ctx = {
      pts, stop: last.stop, ohlc, signalNote: "", eventNote: "", foreign: !whole, hasVolume: shown.some(b => b.volume !== null), basis: cache.basis,
      lo: Math.min(...shown.map(b => (b.low !== null ? b.low : b.close))), hi: Math.max(...shown.map(b => (b.high !== null ? b.high : b.close))), lastClose: pts[pts.length - 1].value,
    };
    if (signalMark) ctx.signalNote = scSignalNote(signalMark, sg.asOf, sg);
    else if (sg) ctx.signalNote = scSignalMissNote(sg, shown);
    if (cache.events && (ev.marks.length || ev.upcoming.length || ev.noBar)) {
      const nxt = ev.upcoming.slice(0, 3).map(u => `${u.time.slice(5)} ${u.label}`).join(" · ");
      ctx.eventNote = `네모 표시(실적 · 배당락 · 주총)는 공시와 규칙으로 모은 일정이라 바뀔 수 있으며, 날짜에 마우스를 올리면 확정인지 예정인지 나옵니다. 실적은 공시를 낸 날이지 좋고 나쁨의 평가가 아닙니다.`
        + `${nxt ? ` 앞으로 예정(오늘 ${today.slice(5)} 이후): ${nxt}.` : ""}`
        + `${ev.noBar ? ` 봉이 없는 지난 날의 일정 ${ev.noBar}건(휴장일이거나 그날 일봉이 아직 들어오지 않음)은 찍지 않았습니다.` : ""}`;
    } else if (cache.eventsFailed) ctx.eventNote = "일정 표시는 받지 못해 그리지 않았습니다.";
    paintNote();
    setLabel(pts);
    ensureBar();
    if (bar) { bar.hidden = false; syncChips(); }
    let L;
    try { L = await scLoadLwc(doc); } catch (e) { note.textContent += " (차트 라이브러리를 불러오지 못했습니다.)"; return false; }
    if (mine !== seq) return false;
    await nextFrame();                              // 칸 크기가 정해진 다음 프레임에 그린다
    if (mine !== seq) return false;
    const base = measureBase();
    const panes = (on.rsi ? 1 : 0) + (on.macd ? 1 : 0);
    ownH = `${base + panes * SC_PANE_H}px`;
    box.style.height = ownH;
    const css = doc.defaultView.getComputedStyle ? doc.defaultView.getComputedStyle(doc.documentElement) : null;
    const pick = (name, dflt) => (css && css.getPropertyValue(name).trim()) || dflt;
    const border = pick("--border", "#dde2ec");
    chart = L.createChart(box, {
      autoSize: true,
      layout: { background: { color: pick("--surf", "#ffffff") }, textColor: pick("--text-dim", "#334155"), fontSize: 11, attributionLogo: true },
      grid: { vertLines: { color: "#f1f5f9" }, horzLines: { color: "#eef1f6" } },
      rightPriceScale: { borderColor: border, scaleMargins: { top: 0.08, bottom: on.vol ? 0.24 : 0.08 }, ensureEdgeTickMarksVisible: true },
      timeScale: { borderColor: border, fixLeftEdge: true, fixRightEdge: true, lockVisibleTimeRangeOnResize: true, ensureEdgeTickMarksVisible: true },
      localization: { locale: "ko-KR", dateFormat: "yyyy-MM-dd" },
      handleScroll: false, handleScale: false,
    });
    try {
      const priceFormat = { type: "custom", formatter: v => scPrice(v, whole), minMove: whole ? 1 : 0.01 };
      let main;
      if (ohlc) {
        main = chart.addSeries(L.CandlestickSeries, { upColor: SC_UP, downColor: SC_DOWN, borderVisible: false, wickUpColor: SC_UP, wickDownColor: SC_DOWN, priceLineVisible: false, priceFormat, autoscaleInfoProvider: autoscale });
        main.setData(shown.map(b => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close })));
      } else {
        main = chart.addSeries(L.LineSeries, { color: "#4361ee", lineWidth: 2, priceLineVisible: false, priceFormat, autoscaleInfoProvider: autoscale });
        main.setData(pts);
      }
      mainSeries = main;
      // 거래량(아래 한 줄 막대) — 값이 있는 날만
      const vol = chart.addSeries(L.HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "", priceLineVisible: false, lastValueVisible: false, visible: on.vol });
      vol.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
      // 막대 색 — 시가가 있으면 종가가 시가 이상인가, 없으면 전 봉 종가 이상인가
      vol.setData(shown.map((b, i) => {
        if (b.volume === null) return null;
        const ref = b.open !== null ? b.open : (i ? shown[i - 1].close : (startAt > 0 ? bars[startAt - 1].close : b.close));
        return { time: b.time, value: b.volume, color: b.close >= ref ? "rgba(220,38,38,0.45)" : "rgba(37,99,235,0.45)" };
      }).filter(Boolean));
      lines.vol = [vol];
      // 이동평균 · 볼린저 — 기간 앞쪽 봉도 창이 찬 값이 나오게 받은 전체 종가로 계산한 뒤 보이는 기간만 자른다
      const closes = bars.map(b => b.close);
      const slice = arr => shown.map((b, i) => (arr[startAt + i] === null ? null : { time: b.time, value: arr[startAt + i] })).filter(Boolean);
      const line = (arr, color, width, style, key) => {
        const s = chart.addSeries(L.LineSeries, { color, lineWidth: width, lineStyle: style || 0, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, visible: on[key], priceFormat });
        s.setData(slice(arr));
        return s;
      };
      lines.ma20 = [line(scSma(closes, 20), SC_LINE_COLORS.ma20, 1, 0, "ma20")];
      lines.ma60 = [line(scSma(closes, 60), SC_LINE_COLORS.ma60, 1, 0, "ma60")];
      const bb = scBollinger(closes);
      lines.bb = [line(bb.upper, SC_LINE_COLORS.bb, 1, 2, "bb"), line(bb.lower, SC_LINE_COLORS.bb, 1, 2, "bb")];
      if (stopOk(last.stop)) stopLine = main.createPriceLine(stopOpts(last.stop));
      const markers = scMarkerList(signalMark, ev.marks);
      if (markers.length && L.createSeriesMarkers) L.createSeriesMarkers(main, markers);
      // 하위 창 — 켠 것만
      let pane = 0;
      if (on.rsi) {
        pane += 1;
        const rsi = chart.addSeries(L.LineSeries, { color: SC_LINE_COLORS.rsi, lineWidth: 1, priceLineVisible: false, lastValueVisible: true, crosshairMarkerVisible: false, title: "RSI 14", priceFormat: { type: "price", precision: 1, minMove: 0.1 } }, pane);
        rsi.setData(slice(scRsi(closes)));
        [30, 70].forEach(p => rsi.createPriceLine({ price: p, color: "#94a3b8", lineWidth: 1, lineStyle: 1, axisLabelVisible: false, title: "" }));
      }
      if (on.macd) {
        pane += 1;
        const m = scMacd(closes);
        const hist = chart.addSeries(L.HistogramSeries, { priceLineVisible: false, lastValueVisible: false, priceFormat: { type: "price", precision: 2, minMove: 0.01 } }, pane);
        hist.setData(slice(m.hist).map(p => ({ ...p, color: p.value >= 0 ? "rgba(220,38,38,0.4)" : "rgba(37,99,235,0.4)" })));
        const mk = (arr, color, title) => {
          const s = chart.addSeries(L.LineSeries, { color, lineWidth: 1, priceLineVisible: false, lastValueVisible: true, crosshairMarkerVisible: false, title, priceFormat: { type: "price", precision: 2, minMove: 0.01 } }, pane);
          s.setData(slice(arr));
        };
        mk(m.macd, SC_LINE_COLORS.macd, "MACD");
        mk(m.signal, SC_LINE_COLORS.macdSignal, "신호선");
      }
      if (pane > 0 && chart.panes) {
        try { chart.panes()[0].setStretchFactor(base / SC_PANE_H); } catch { /* 옛 라이브러리 — 같은 비율로 둔다 */ }
      }
      // 크로스헤어를 따라가는 값 줄(왼쪽 위)
      const legend = legendEl || { textContent: "" };
      const marksByDay = scMarksByDay(signalMark, ev.marks, sg);
      const at = new Map(shown.map((b, i) => [b.time, { bar: b, prev: i ? shown[i - 1] : (startAt > 0 ? bars[startAt - 1] : null) }]));
      const lastDay = shown[shown.length - 1].time;
      const paint = day => { const e = at.get(day) || at.get(lastDay); legend.textContent = scLegendText(e.bar, e.prev, marksByDay.get(e.bar.time), whole); };
      paint(lastDay);
      chart.subscribeCrosshairMove(p => paint(p && p.time ? scTimeKey(p.time) : lastDay));
      chart.timeScale().fitContent();
      return true;
    } catch (e) {
      removeChart();                                // 반쯤 그려진 차트와 창 크기 관찰자를 남기지 않는다
      box.replaceChildren();
      setLabel(null);
      note.textContent = `차트를 그리지 못했습니다: ${e?.message || e}`;
      onError?.(e);
      return false;
    }
  }

  /** 하위 창을 켜고 끌 때 · 신호가 바뀔 때 — 받아 둔 일봉으로 다시 그린다(요청 번호는 새로 매겨 먼저 가던 그림을 버린다).
   *  받아 둔 일봉이 지금 요청한 종목의 것일 때만 — 다른 종목을 받는 중이면 옛 종목 줄로 그리지 않고 그 요청이 끝나서 그린다 */
  function renderSoon() {
    if (!cache.rows.length || !last.symbol || cache.symbol !== last.symbol) return;
    const mine = ++seq;
    task = render(mine);
  }

  async function draw({ symbol, period, stop, rows } = {}) {
    const per = period || SC_DEFAULT_PERIOD;
    const given = Array.isArray(rows) ? rows : null;     // 호스트가 일봉 줄을 직접 줄 때(해외 · 지수 — 퀀트 대시보드) 요청을 보내지 않는다
    const same = v => (stopOk(v) ? v : null);
    // 종목 · 기간이 같고 스탑가만 다르면 차트를 다시 그리지 않는다 — 칩 줄이 숨겨지고 「불러오는 중…」이 뜨는 깜박임을 막는다
    if (!given && chart && mainSeries && ctx && symbol === last.symbol && per === last.period && cache.symbol === symbol
        && Date.now() - cache.at <= SC_CACHE_MS && same(stop) !== same(last.stop)) {
      last = { symbol, period: per, stop };
      ctx.stop = stop;
      applyStop();
      paintNote();
      return true;
    }
    ++seq;                                              // 먼저 가던 그림을 버린다
    const myDraw = ++drawId;
    last = { symbol, period: per, stop };
    removeChart();
    box.replaceChildren();
    ctx = null;
    setLabel(null);
    if (bar) bar.hidden = true;
    if (legendEl) legendEl.textContent = "";
    const today = scToday();
    const path = scPathWarm(symbol, today);
    if (!path && !given) { note.textContent = "이 종목은 수집 일봉이 없어 차트를 그리지 못합니다(국내 6자리 코드만)."; return false; }
    const code = scCode(symbol);
    note.textContent = "일봉을 불러오는 중…";
    const evPath = () => scEventsPath(symbol, scShiftDay(today, -SC_WARM_DAYS), scShiftDay(today, 90));
    const eventsOf = res => (res.status === "fulfilled" && Array.isArray(res.value?.events) ? res.value.events : null);
    if (given) {
      cache = { code: `given:${symbol}`, symbol, rows: given, events: null, eventsFailed: false, basis: "", at: Date.now() };   // 줄이 바뀌었을 수 있어 항상 새로 받은 것으로 바꾼다
    } else if (cache.code !== code || Date.now() - cache.at > SC_CACHE_MS) {
      const [rowsRes, evRes] = await Promise.allSettled([api(path), api(evPath())]);
      if (myDraw !== drawId) return false;
      if (rowsRes.status === "rejected") {
        const e = rowsRes.reason;
        note.textContent = `일봉을 받지 못했습니다: ${e?.message || e}`;
        onError?.(e);
        return false;
      }
      cache = {
        code, symbol, rows: Array.isArray(rowsRes.value?.rows) ? rowsRes.value.rows : [],
        events: eventsOf(evRes), eventsFailed: evRes.status === "rejected", basis: String(rowsRes.value?.basis || ""), at: Date.now(),
      };
    } else {
      cache = { ...cache, symbol };                      // 같은 종목(코드)의 받아 둔 줄을 그대로 쓴다
      if (cache.eventsFailed) {                          // 일정을 못 받은 채로 두지 않는다 — 일정만 다시 받는다
        const [evRes] = await Promise.allSettled([api(evPath())]);
        if (myDraw !== drawId) return false;
        cache = { ...cache, events: eventsOf(evRes), eventsFailed: evRes.status === "rejected" };
      }
    }
    if (myDraw !== drawId) return false;                // 더 새 요청(다른 종목 · 기간) 또는 destroy 에 밀렸다
    const first = task = render(++seq);                 // 받는 동안 칩이 눌려 시작된 그림이 있어도 새로 시작한다(같은 줄이다)
    let t = first, ok = await t;
    // 이 요청이 새 draw 가 아니라 칩 누름 · 신호 도착으로 밀렸으면 그 그림이 이어받은 것이다 — 그 결과를 돌려준다
    while (myDraw === drawId && task !== t) { t = task; ok = await t; }
    return myDraw === drawId && ok && chart !== null;
  }

  /** 마지막으로 기록된 신호 한 점 { asOf, side, symbol?, computedAt?, late? }(기록 시각 · 늦게 계산 여부는 표식 풀이에, 종목은 다른 종목 칸에 찍히지 않게 쓴다) — 비우면 표시를 걷는다.
   *  이미 그린 뒤에 바뀌면 다시 그린다 */
  function setSignal(next) {
    const had = !!sigNow();
    sig = next && next.asOf ? { asOf: String(next.asOf), side: String(next.side || ""), symbol: String(next.symbol || ""), computedAt: String(next.computedAt || ""), late: !!next.late } : null;
    if (!had && !sigNow()) return;                      // 이 칸에는 보일 신호가 없고 새 신호도 이 칸 것이 아니다 — 다시 그릴 까닭이 없다
    renderSoon();
  }
  function destroy() {
    seq += 1;
    drawId += 1;
    removeChart();
    box.replaceChildren();
    setLabel(null);
    if (bar) { bar.remove(); bar = null; }
    if (legendEl) { legendEl.remove(); legendEl = null; }
  }
  return { draw, destroy, setSignal };
}
