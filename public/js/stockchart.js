/* 종목 일봉 차트 칸 — 모의주문 시세 조회 · 스탑 주문 · 종목 허브 서랍 · 크게 보기 모달이 같은 부품을 크기만 달리해 쓴다 (2026-11-02 · 사용자 결정 「서랍과 모달 융합」 · 설계 Figma 「Qurious · 종목 허브」 07 쪽 안 C · 안 D)
 *
 *   · 데이터는 새로 만들지 않는다 — 종목 허브가 쓰는 수집 일봉 `/api/data/ohlcv` 한 길(야후 참조를 늘리지 않는다 · TC-YH).
 *   · 순수 함수(sc*)는 DOM 없이 글 · 점 · 숫자만 만든다(Node 시험 — tests/test_stockchart.py TC-SCH).
 *   · mountDailyChart 는 차트 라이브러리(Lightweight Charts)를 불러 그린다. 스탑가가 있으면 점선 가격선을 더한다.
 */
import { cvSlice } from "./companyview.js";

/** 기간 단추 — companyview.js CV_PERIODS 의 키와 같다 */
export const SC_PERIODS = [["1m", "1개월"], ["3m", "3개월"], ["1y", "1년"]];
export const SC_DEFAULT_PERIOD = "3m";
const LWC_SRC = "/js/vendor/lightweight-charts/lightweight-charts-5.2.1.min.js";
/** 스탑가 빠른 입력(현재가 대비 아래로 · 매도 스탑 쪽) */
export const SC_QUICK_PCTS = [3, 5, 10];

/** 일봉 요청에 보낼 6자리 단축코드 — 「005930」 · 「005930.KS」 · ETF 「0000D0」. 아니면 빈 글(요청을 보내지 않는다) */
export function scCode(symbol) {
  const m = /^([0-9A-Za-z]{6})(?:\.(?:KS|KQ))?$/i.exec(String(symbol || "").trim());
  return m ? m[1].toUpperCase() : "";
}

export function scPath(symbol) {
  const code = scCode(symbol);
  return code ? `/api/data/ohlcv?symbol=${code}` : "";
}

/** 일봉 줄 → 선 차트 점(마지막 날 기준 기간 안) */
export function scPoints(rows, period) {
  return cvSlice(rows, period || SC_DEFAULT_PERIOD);
}

/** 차트 아래 글 — 최고 · 최저 · 마지막 종가 + 출처 · 한계(실시간 차트가 아님). 스탑가가 있으면 그 값도 적는다 */
export function scSummary(points, stop) {
  if (!points.length) return "일봉 자료가 없습니다 — 수집 범위 밖의 종목이거나 아직 받지 못했습니다.";
  const fmt = n => `${Math.round(n).toLocaleString("ko-KR")}원`;
  const vals = points.map(p => p.value);
  const last = points[points.length - 1];
  let text = `최고 ${fmt(Math.max(...vals))} · 최저 ${fmt(Math.min(...vals))} · 마지막 종가 ${fmt(last.value)}(${last.time}) — 우리 수집 일봉(수정주가) 종가이며 실시간 차트가 아닙니다.`;
  if (Number.isFinite(stop) && stop > 0) text += ` 빨간 점선은 입력한 스탑가 ${fmt(stop)}입니다.`;
  return text;
}

/** 스탑가를 현재가와 견준 한 줄 — 어느 쪽 스탑으로 써야 하는지, 반대로 등록하면 어떻게 되는지 */
export function scDirection(current, stop) {
  const c = Number(current), s = Number(stop);
  if (!Number.isFinite(c) || c <= 0 || !Number.isFinite(s) || s <= 0) return "";
  const pct = Math.abs((s - c) / c * 100).toFixed(1);
  if (s < c) return `스탑가가 현재가보다 ${pct}% 낮습니다 — 매도 스탑(손절)으로 쓰는 값입니다. 매수 스탑으로 등록하면 다음 1분 점검에서 바로 체결될 수 있습니다.`;
  if (s > c) return `스탑가가 현재가보다 ${pct}% 높습니다 — 매수 스탑으로 쓰는 값입니다. 매도 스탑으로 등록하면 다음 1분 점검에서 바로 체결될 수 있습니다.`;
  return "스탑가가 현재가와 같습니다 — 어느 쪽으로 등록해도 다음 1분 점검에서 바로 체결될 수 있습니다.";
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

let lwcPromise = null;
function loadLwc(doc) {
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
 *  opts: { symbol, period, stop } — box 는 높이가 정해진 칸 · note 는 아래 글 칸 */
export function mountDailyChart(doc, box, note, { api, onError } = {}) {
  let chart = null, seq = 0, rowsCache = { code: "", rows: [] };
  async function draw({ symbol, period, stop } = {}) {
    const mine = ++seq;
    const path = scPath(symbol);
    if (chart) { chart.remove(); chart = null; }
    box.replaceChildren();
    if (!path) { note.textContent = "이 종목은 수집 일봉이 없어 차트를 그리지 못합니다(국내 6자리 코드만)."; return; }
    const code = scCode(symbol);
    note.textContent = "일봉을 불러오는 중…";
    if (rowsCache.code !== code) {
      try {
        const r = await api(path);
        rowsCache = { code, rows: Array.isArray(r?.rows) ? r.rows : [] };
      } catch (e) {
        if (mine === seq) note.textContent = `일봉을 받지 못했습니다: ${e?.message || e}`;
        onError?.(e);
        return;
      }
    }
    if (mine !== seq) return;
    const pts = scPoints(rowsCache.rows, period);
    note.textContent = scSummary(pts, stop);
    if (!pts.length) return;
    let L;
    try { L = await loadLwc(doc); } catch (e) { note.textContent += " (차트 라이브러리를 불러오지 못했습니다.)"; return; }
    if (mine !== seq) return;
    chart = L.createChart(box, {
      autoSize: true,
      layout: { background: { color: "#ffffff" }, textColor: "#334155", fontSize: 11, attributionLogo: true },
      grid: { vertLines: { color: "#f1f5f9" }, horzLines: { color: "#eef1f6" } },
      rightPriceScale: { borderColor: "#dde2ec", scaleMargins: { top: 0.08, bottom: 0.18 }, ensureEdgeTickMarksVisible: true },
      timeScale: { borderColor: "#dde2ec", fixLeftEdge: true, fixRightEdge: true, lockVisibleTimeRangeOnResize: true, ensureEdgeTickMarksVisible: true },
      localization: { locale: "ko-KR", dateFormat: "yyyy-MM-dd" },
      handleScroll: false, handleScale: false,
    });
    const series = chart.addSeries(L.LineSeries, {
      color: "#4361ee", lineWidth: 2, priceLineVisible: false,
      priceFormat: { type: "custom", formatter: v => Math.round(v).toLocaleString("ko-KR"), minMove: 1 },
    });
    series.setData(pts.map(p => ({ time: p.time, value: p.value })));
    if (Number.isFinite(stop) && stop > 0) {
      series.createPriceLine({ price: stop, color: "#dc2626", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "스탑가" });
    }
    chart.timeScale().fitContent();
  }
  function destroy() { seq += 1; if (chart) { chart.remove(); chart = null; } box.replaceChildren(); }
  return { draw, destroy };
}
