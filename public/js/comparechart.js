/* TradingView ↔ LEAN 대사 결과를 가격 차트 위에 얹는 판단 — DOM · 차트 없이 표시할 것만 정한다(node 로 시험 · TC-CCH · 2026-10-30 · ①-15).
 *
 * 왜 — 대사 결과는 층 카드와 표로만 보였다. 어긋난 날이 어느 봉인지 눈으로 찾으려면 가격 차트 위에서 봐야 한다.
 * 서버(강민석 님 코드)는 그대로 두고, 응답의 fill_comparison.rows · signal_comparison.mismatch_dates 를 화면이 읽는다.
 *
 * 규칙
 *   1. 표시는 응답에 있는 값뿐이다. 체결 표시 = fill_comparison.rows 의 TradingView · LEAN 체결(날짜 · 방향 · 체결가).
 *      어긋난 날 = signal_comparison.mismatch_dates. 둘 다 새로 셈하지 않는다(짝 여부도 서버의 match_status 그대로).
 *   2. 손절 · 익절 선은 응답에 값이 없어서 **그리지 않는다** — 그린다고 약속하는 글도 두지 않고, 그리지 않았다는 사실을 적는다.
 *   3. 비교하지 않은 층은 표시 대신 까닭을 보인다(서버 글 그대로). LEAN 이 안 돌고 대체 계산이면 맨 위에 그 사실.
 *   4. 데이터 기준일 = 캔들 응답의 as_of(없으면 마지막 봉 날짜). 요청 기간이 차트가 줄 수 있는 길이(10년)보다 길면 잘렸다고 적는다.
 */

const isStr = v => typeof v === "string" && v.length > 0;
const DATE_RE = /^\d{4}-\d{2}-\d{2}/;
const day = v => (isStr(v) && DATE_RE.test(v) ? v.slice(0, 10) : null);
/** 숫자가 아니거나 비어 있으면 null — Number(null) 이 0 으로 읽혀 가격 0 이 생기지 않게 한다. */
const numOrNull = v => (v === null || v === undefined || v === "" ? null : Number.isFinite(Number(v)) ? Number(v) : null);

/** 방향 낱말 → "buy" | "sell" | null (모르는 낱말은 지어내지 않고 건너뛴다). */
export function sideOf(v) {
  const s = String(v ?? "").trim().toLowerCase();
  if (["buy", "long", "매수", "b"].includes(s)) return "buy";
  if (["sell", "short", "매도", "s"].includes(s)) return "sell";
  return null;
}

/** 캔들 API 가 받는 기간 값(수집 DB 다리) 가운데 요청 시작일을 덮는 가장 짧은 것. 10년을 넘으면 truncated. */
const PERIODS = [["1mo", 1], ["3mo", 3], ["6mo", 6], ["1y", 12], ["2y", 24], ["3y", 36], ["5y", 60], ["10y", 120]];
export function periodFor(startIso, todayIso) {
  const a = day(startIso), b = day(todayIso);
  if (!a || !b) return { period: "1y", truncated: false };
  const [ay, am, ad] = a.split("-").map(Number), [by, bm, bd] = b.split("-").map(Number);
  let months = (by - ay) * 12 + (bm - am) + (bd > ad ? 1 : 0) + 1; // 한 달 여유
  if (months < 1) months = 1;
  const hit = PERIODS.find(([, m]) => m >= months);
  return hit ? { period: hit[0], truncated: false } : { period: "10y", truncated: true };
}

export const NO_STOP_NOTE = "손절 · 익절 선은 대사 응답에 값이 없어 그리지 않았습니다.";

const SRC = {
  tv: { label: "TV", color: "#2962ff" },
  lean: { label: "LEAN", color: "#f59e0b" },
};

function marker(kind, side, time, price, paired) {
  const buy = side === "buy";
  const tail = paired === false ? " · 짝 없음" : "";
  return {
    time, kind, side, price: numOrNull(price), paired,
    position: buy ? "belowBar" : "aboveBar",
    shape: kind === "tv" ? (buy ? "arrowUp" : "arrowDown") : "circle",
    color: SRC[kind].color,
    text: `${SRC[kind].label} ${buy ? "매수" : "매도"}${tail}`,
  };
}

/** 대사 응답 → 차트에 얹을 것. markers · mismatchDays · notes · counts. */
export function overlayFromResult(r) {
  const out = { markers: [], mismatchDays: [], notes: [], counts: { tv: 0, lean: 0, paired: 0, tvOnly: 0, leanOnly: 0, skipped: 0 }, fromLean: true };
  if (!r || typeof r !== "object") return { ...out, notes: ["대사 결과가 없습니다."] };
  if (r.lean && r.lean.lean_ok === false) {
    out.fromLean = false;
    out.notes.push("LEAN 이 실행되지 않아 대체 계산으로 비교했습니다 — 차트 표시는 참고용입니다.");
  }

  const f = r.fill_comparison;
  if (f && f.status === "compared" && Array.isArray(f.rows)) {
    for (const row of f.rows) {
      const paired = row.match_status === "paired" ? true : false;
      const tvT = day(row.tradingview_comparison_date || row.tradingview_date), tvS = sideOf(row.tradingview_side);
      const lnT = day(row.lean_comparison_date || row.lean_date), lnS = sideOf(row.lean_side);
      if (row.tradingview_side != null || tvT) {
        if (tvT && tvS) { out.markers.push(marker("tv", tvS, tvT, row.tradingview_price, paired)); out.counts.tv++; }
        else out.counts.skipped++;
      }
      if (row.lean_side != null || lnT) {
        if (lnT && lnS) { out.markers.push(marker("lean", lnS, lnT, row.lean_fill_price, paired)); out.counts.lean++; }
        else out.counts.skipped++;
      }
      if (row.match_status === "paired") out.counts.paired++;
      else if (row.match_status === "unmatched_tradingview") out.counts.tvOnly++;
      else if (row.match_status === "unmatched_lean") out.counts.leanOnly++;
    }
    if (out.counts.skipped) out.notes.push(`날짜나 방향을 읽을 수 없는 체결 ${out.counts.skipped}건은 차트에 표시하지 않았습니다.`);
  } else {
    const why = (f && (f.reason || f.message)) || "체결 비교를 하지 않았습니다.";
    out.notes.push(`체결 표시 없음 — ${why}`);
  }

  const s = r.signal_comparison;
  if (s && s.status === "compared" && Array.isArray(s.mismatch_dates)) {
    out.mismatchDays = s.mismatch_dates.map(m => day(typeof m === "string" ? m : m && m.date)).filter(Boolean);
    if (s.mismatch_dates_truncated) out.notes.push("어긋난 날이 많아 서버가 앞의 100일만 보냈습니다.");
  } else if (s && s.status !== "compared") {
    out.notes.push(`어긋난 날 표시 없음 — ${s.reason || s.message || "신호 비교를 하지 않았습니다."}`);
  }

  out.notes.push(NO_STOP_NOTE);
  out.markers.sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : a.kind < b.kind ? -1 : 1));
  return out;
}

/** 차트 안에 들어가는 표시만 골라 낸다(요청 기간이 차트보다 길거나 휴일에 걸린 표시를 숨기지 않고 센다). */
export function fitToBars(overlay, barDates) {
  const set = new Set(barDates || []);
  const keep = overlay.markers.filter(m => set.has(m.time));
  const dropped = overlay.markers.length - keep.length;
  const mismatch = overlay.mismatchDays.filter(d => set.has(d));
  const mDropped = overlay.mismatchDays.length - mismatch.length;
  const notes = [...overlay.notes];
  if (dropped) notes.push(`차트에 봉이 없는 날의 체결 표시 ${dropped}건은 그리지 않았습니다.`);
  if (mDropped) notes.push(`차트에 봉이 없는 어긋난 날 ${mDropped}일은 그리지 않았습니다.`);
  return { ...overlay, markers: keep, mismatchDays: mismatch, notes };
}

/** 한 봉의 날짜 — 캔들 응답의 time 은 초 단위 UTC 타임스탬프(수집 DB 다리) 또는 날짜 글자다. */
export function barDay(b) {
  const t = b && (b.time ?? b.date);
  if (typeof t === "number" && Number.isFinite(t)) return new Date(t * 1000).toISOString().slice(0, 10);
  return day(String(t ?? ""));
}

const shiftDay = (iso, delta) => { const d = new Date(`${iso}T00:00:00Z`); d.setUTCDate(d.getUTCDate() + delta); return d.toISOString().slice(0, 10); };

/** 차트에 넣을 봉 — 요청 시작일 열흘 앞부터 종료일 열흘 뒤까지(맥락 몇 봉) · 값이 비면 건너뛴다. */
export function toChartBars(candles, startIso, endIso) {
  const s = day(startIso), e = day(endIso);
  const from = s ? shiftDay(s, -10) : null, to = e ? shiftDay(e, 10) : null;
  const out = [];
  for (const b of candles || []) {
    const t = barDay(b);
    const o = numOrNull(b.open), h = numOrNull(b.high), l = numOrNull(b.low), c = numOrNull(b.close);
    if (!t || [o, h, l, c].some(v => v === null)) continue;
    if (from && t < from) continue;
    if (to && t > to) continue;
    out.push({ time: t, open: o, high: h, low: l, close: c });
  }
  return out;
}

/** 데이터 기준일 줄. 캔들 응답의 as_of → 없으면 마지막 봉. 요청이 10년을 넘어 잘렸으면 그 사실을 붙인다. */
export function asOfLine(candleRes, truncated) {
  const bars = (candleRes && candleRes.candles) || [];
  const last = bars.length ? barDay(bars[bars.length - 1]) : null;
  const asOf = day(candleRes && candleRes.as_of) || last;
  const src = candleRes && candleRes.source === "collector" ? "수집 DB 일봉" : candleRes && candleRes.source ? `${candleRes.source} 일봉` : "일봉";
  const head = asOf ? `차트 데이터 기준일 ${asOf} · ${src}` : "차트 데이터 기준일을 알 수 없습니다";
  return truncated ? `${head} · 요청 기간이 길어 최근 10년만 보입니다` : head;
}
