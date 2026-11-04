/* 비교 트레이 분석 — 담아 둔 백테스트 · ML 결과를 숫자 표로 모으고 Markdown 메모로 복사한다 (2026-11-04 · D8)
 *
 * 강사님 lumina-invest 의 core.js(compareTrayMetrics · compareTrayAnalysis · compareTrayCopy)를 읽고 우리 규칙으로 다시 설계했다.
 * 달라진 곳
 *  1. 지표를 요약 글에서 정규식으로 뽑지 않는다 — 「비교에 추가」 가 서버 응답의 숫자를 `metrics` 구조 칸으로 함께 담고(backtestTrayFields),
 *     여기서는 그 칸을 읽는다. 구조 칸이 없는 항목(옛 항목 · 다른 화면)만 우리 화면이 실제로 내는 요약 글 두 꼴에 맞춘 좁은 읽기로
 *     읽고 「요약 글에서 읽음」 이라고 표시한다. 어느 쪽도 못 읽으면 지어내지 않고 「분석에서 뺀 항목」 에 이유와 함께 둔다.
 *  2. 문구는 숫자 · 정의 · 주의만 쓴다 — 별표 · 「수익 · 위험 모두 우수」 같은 판단 문장 · 권유로 읽히는 말을 쓰지 않는다.
 *     표 순서는 샤프 비율 큰 순이지만 정렬 기준일 뿐이고, 「최대」 · 「최소」 는 그 열에서 가장 큰 · 작은 값의 위치 표시다.
 *  3. 숫자마다 기준일 · 자료 기간 · 추가된 곳을 옆에 단다. 기준일을 모르면 「기준일 없음」 이라고 쓴다(담은 시각은 기준일이 아니다).
 *  4. HTML 과 Markdown 을 한 자료(buildComparison)에서 만든다 — 화면 글을 긁어 Markdown 을 만들지 않는다.
 *
 * 「교육 · 연습용이며 투자 권유가 아님」 고지는 learnnotice.js 의 NOTICE_LINE 을 그대로 쓴다(글을 여기서 새로 쓰지 않는다).
 * core.js 를 가져오지 않는다(core.js 가 이 파일을 가져간다) · 가져올 때 하는 일이 없다 — 시험이 node 로 그대로 불러 돌린다.
 */
import { NOTICE_LINE } from "./learnnotice.js";

// ── 작은 도구 ───────────────────────────────────────────────────────
const esc = s => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
// 숫자 아님(null · "" · 불리언 · NaN)은 null — Number(null) 이 0 이 되는 함정을 막는다
const num = v => {
  if (v === null || v === undefined || v === "" || typeof v === "boolean") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};
const abs = v => (v === null ? null : Math.abs(v));
const text = v => (v === null || v === undefined ? "" : String(v));
const dateOf = v => (/^\d{4}-\d{2}-\d{2}/.test(text(v)) ? text(v).slice(0, 10) : "");
// toFixed 가 만드는 「-0.00」 을 「0.00」 으로
const fx = (v, d = 2) => { const s = v.toFixed(d); return /^-0(\.0+)?$/.test(s) ? s.slice(1) : s; };
const fixed = (v, d = 2) => (v === null || v === undefined ? "-" : fx(v, d));
const signedPct = v => (v === null || v === undefined ? "-" : `${v > 0 ? "+" : ""}${fx(v)}%`);
const signedPp = v => (v === null || v === undefined ? "-" : `${v > 0 ? "+" : ""}${fx(v)}%p`);
const plainPct = (v, d = 1) => (v === null || v === undefined ? "-" : `${fx(v, d)}%`);
const dropPct = v => (v === null || v === undefined ? "-" : `-${fx(v)}%`);
const tone = v => (v === null || v === undefined ? "" : v > 0 ? "pos" : v < 0 ? "neg" : "");
const uniq = arr => [...new Set(arr.filter(Boolean))];
const mdCell = s => text(s).replace(/\r?\n/g, " ").replace(/\|/g, "\\|");
const mdLine = s => text(s).replace(/\r?\n/g, " ");

// ── 담을 때 — 서버 응답의 숫자를 구조 칸으로 (indicator.js 의 「비교에 추가」 가 쓴다) ──────────────
/**
 * 성과 검증(/api/quant/pipeline) 응답 → 비교 트레이 항목에 더할 칸.
 * 값은 서버 응답 칸 그대로(수익률 · 샤프 · 낙폭 · 승률은 %), 거래 0회면 수익률 · 샤프 · 낙폭 · 승률은 0 이 아니라 null.
 */
export function backtestTrayFields(d) {
  const x = d || {};
  const noTrade = num(x.trade_count) === 0;
  return {
    kind: "backtest",
    symbol: text(x.symbol),
    as_of: dateOf(x.data_as_of),
    data_from: dateOf(x.data_from),
    data_note: text(x.data_note),
    metrics: {
      return_pct: noTrade ? null : num(x.total_return_pct),
      bh_pct: num(x.buy_hold_return_pct),
      sharpe: noTrade ? null : num(x.sharpe_ratio),
      mdd_pct: noTrade ? null : num(x.mdd_pct),
      win_rate_pct: noTrade ? null : num(x.win_rate_pct),
      trade_count: num(x.trade_count),
    },
  };
}

// ── 읽을 때 — 항목 하나를 지표로 ───────────────────────────────────────
const NUM = "[+-]?\\d[\\d,]*(?:\\.\\d+)?";
const parseNum = s => num(String(s).replace(/,/g, ""));
const re = body => new RegExp(body);

/**
 * 구조 칸이 없는 항목의 요약 글 읽기 — 우리 화면이 실제로 내는 꼴만 읽는다(좁게).
 *  ML:        「CV 평균 a% (±b%) · 검증 정확도 c%」 (+ 「 · 기간 p」)                       ← ml.js
 *  백테스트:  「수익률 a%」 로 시작하고 「 · 」 로 이은 「샤프 x」 「MDD x%」 「승률 x%」 「자료 날짜 ~ 날짜」  ← indicator.js 옛 항목 · paper.js(LEAN)
 *  거래 0회:  「거래 0회 · 신호 없음 · 매수 후 보유 a%」                                    ← indicator.js 옛 항목
 * 못 읽으면 null — 읽은 척하지 않는다.
 */
export function readSummary(summary) {
  const s = text(summary).trim();
  let m = s.match(re(`^CV 평균 (${NUM})% \\(±(${NUM})%\\) · 검증 정확도 (${NUM})%(?: · 기간 (.+))?$`));
  if (m) return { kind: "ml", m: { cv: parseNum(m[1]), cvStd: parseNum(m[2]), val: parseNum(m[3]) }, periodLabel: m[4] || "", from: "", asOf: "" };
  m = s.match(re(`^거래 0회 · 신호 없음 · 매수 후 보유 (${NUM})%`));
  if (m) return { kind: "backtest", m: { ret: null, bh: parseNum(m[1]), sharpe: null, mddAbs: null, win: null, trades: 0 }, periodLabel: "", from: "", asOf: "" };
  const parts = s.split(" · ");
  const head = parts[0].match(re(`^수익률 (${NUM})%$`));
  if (!head) return null;
  const out = { kind: "backtest", m: { ret: parseNum(head[1]), bh: null, sharpe: null, mddAbs: null, win: null, trades: null }, periodLabel: "", from: "", asOf: "" };
  for (const part of parts.slice(1)) {
    let x;
    if ((x = part.match(re(`^샤프 (${NUM})$`)))) out.m.sharpe = parseNum(x[1]);
    else if ((x = part.match(re(`^MDD (${NUM})%$`)))) out.m.mddAbs = abs(parseNum(x[1]));
    else if ((x = part.match(re(`^승률 (${NUM})%$`)))) out.m.win = parseNum(x[1]);
    else if ((x = part.match(/^자료 (\d{4}-\d{2}-\d{2}) ~ (\d{4}-\d{2}-\d{2})$/))) { out.from = x[1]; out.asOf = x[2]; }
  }
  return out;
}

function structuredMetrics(kind, mm) {
  if (kind === "ml") return { cv: num(mm.cv_mean), cvStd: num(mm.cv_std), val: num(mm.val_acc) };
  return { ret: num(mm.return_pct), bh: num(mm.bh_pct), sharpe: num(mm.sharpe), mddAbs: abs(num(mm.mdd_pct)), win: num(mm.win_rate_pct), trades: num(mm.trade_count) };
}

/** 트레이 항목 → { kind, origin, m, 날짜 · 출처 칸 }. origin: structured(구조 칸) | summary(요약 글에서 읽음) | none(못 읽음) */
function readEntry(x) {
  const base = {
    id: text(x.id), label: text(x.label) || "(이름 없음)", source: text(x.source), summary: text(x.summary),
    symbol: text(x.symbol), asOf: dateOf(x.as_of), from: dateOf(x.data_from), note: text(x.data_note), periodLabel: "",
  };
  if (x.metrics && typeof x.metrics === "object") {
    const kind = x.kind === "ml" || x.kind === "backtest" ? x.kind : ("cv_mean" in x.metrics || "val_acc" in x.metrics ? "ml" : "backtest");
    return { ...base, kind, origin: "structured", m: structuredMetrics(kind, x.metrics) };
  }
  const read = readSummary(base.summary);
  if (!read) return { ...base, kind: null, origin: "none", m: {} };
  return { ...base, kind: read.kind, origin: "summary", m: read.m, periodLabel: read.periodLabel, from: read.from || base.from, asOf: read.asOf || base.asOf };
}

// ── 표 자료 만들기 ───────────────────────────────────────────────────
function whenText(e) {
  if (e.from && e.asOf) return `${e.from} ~ ${e.asOf}`;
  if (e.asOf) return `기준일 ${e.asOf}`;
  if (e.periodLabel) return `기간 ${e.periodLabel} · 기준일 없음`;
  return "기준일 없음";
}

// 열마다 가장 큰 · 가장 작은 값에 「최대」 · 「최소」 — 값이 둘 이상이고 서로 다를 때만(좋고 나쁨이 아니라 위치 표시)
function markExtremes(rows, keys) {
  keys.forEach(k => {
    const vals = rows.map(r => r.v[k]).filter(v => v !== null && v !== undefined);
    if (vals.length < 2) return;
    const hi = Math.max(...vals), lo = Math.min(...vals);
    if (hi === lo) return;
    rows.forEach(r => { if (r.v[k] === hi) r.tag[k] = "최대"; else if (r.v[k] === lo) r.tag[k] = "최소"; });
  });
}

const BT_COLS = [
  { key: "ret", label: "누적 수익률", fmt: signedPct, color: true },
  { key: "bh", label: "단순 보유", fmt: signedPct, color: true },
  { key: "excess", label: "차이(%p)", fmt: signedPp, color: true },
  { key: "sharpe", label: "샤프", fmt: v => fixed(v) },
  { key: "mddAbs", label: "최대 낙폭", fmt: dropPct },
  { key: "ratio", label: "수익/낙폭", fmt: v => fixed(v) },
  { key: "win", label: "승률", fmt: v => plainPct(v) },
  { key: "trades", label: "매매 횟수", fmt: v => (v === null || v === undefined ? "-" : `${v}회`) },
];
const BT_MARK = ["ret", "excess", "sharpe", "mddAbs", "ratio", "win"];
const ML_COLS = [
  { key: "cv", label: "CV 평균", fmt: v => plainPct(v) },
  { key: "cvStd", label: "CV 편차", fmt: v => (v === null || v === undefined ? "-" : `±${fx(v, 1)}%`) },
  { key: "val", label: "검증 정확도", fmt: v => plainPct(v) },
  { key: "gap", label: "CV−검증(%p)", fmt: signedPp },
];
const ML_MARK = ["cv", "val", "gap"];

// 샤프 큰 순(값 없는 항목은 뒤) — 같으면 담은 차례
const cmpDesc = key => (a, b) => {
  const x = a.v[key], y = b.v[key];
  if (x === null && y === null) return a.i - b.i;
  if (x === null) return 1;
  if (y === null) return -1;
  return (y - x) || (a.i - b.i);
};

function makeTable(rows, cols, markKeys, sortKey) {
  rows.sort(cmpDesc(sortKey));
  markExtremes(rows, markKeys);
  return rows.map((r, n) => ({
    rank: n + 1,
    name: r.e.label,
    source: r.e.source,
    fromSummary: r.e.origin === "summary",
    cells: Object.fromEntries(cols.map(c => [c.key, { text: c.fmt(r.v[c.key]), tag: r.tag[c.key] || "", tone: c.color ? tone(r.v[c.key]) : "" }])),
    when: whenText(r.e),
    note: r.e.note,
  }));
}

/**
 * 트레이 목록 → 분석 자료. 화면(HTML)과 복사(Markdown)가 같은 자료를 읽는다.
 * 반환: { count, backtest, ml, excluded, definitions, cautions, notice }
 */
export function buildComparison(list) {
  const entries = (Array.isArray(list) ? list : []).filter(x => x && typeof x === "object").map(readEntry);
  const excluded = [];

  const btRows = [], mlRows = [];
  entries.forEach((e, i) => {
    if (e.kind === "backtest" && e.m.ret !== null && e.m.ret !== undefined) {
      const { ret, bh, sharpe, mddAbs, win, trades } = e.m;
      btRows.push({ e, i, tag: {}, v: {
        ret, bh: bh ?? null, excess: bh !== null && bh !== undefined ? ret - bh : null, sharpe: sharpe ?? null, mddAbs: mddAbs ?? null,
        ratio: mddAbs !== null && mddAbs !== undefined && mddAbs >= 0.01 ? ret / mddAbs : null, win: win ?? null, trades: trades ?? null } });
    } else if (e.kind === "ml" && (e.m.val !== null || e.m.cv !== null)) {
      const { cv, cvStd, val } = e.m;
      mlRows.push({ e, i, tag: {}, v: { cv, cvStd, val, gap: cv !== null && val !== null ? cv - val : null } });
    } else if (e.kind === "backtest" && e.m.trades === 0) {
      excluded.push({ label: e.label, source: e.source, reason: `거래 0회 — 수익률 · 샤프 · 낙폭 · 승률을 매기지 않았습니다(0 이 아니라 값이 없는 것).${e.m.bh !== null && e.m.bh !== undefined ? ` 같은 기간 매수 후 보유는 ${signedPct(e.m.bh)} 입니다.` : ""}` });
    } else {
      excluded.push({ label: e.label, source: e.source, reason: e.origin === "none"
        ? `지표 칸이 없고 요약 글도 읽을 수 없는 꼴이라 비교 표에 넣지 않았습니다. 요약: ${e.summary || "(없음)"}`
        : "읽을 수 있는 숫자가 없어 비교 표에 넣지 않았습니다." });
    }
  });

  const backtest = btRows.length ? { cols: BT_COLS.map(c => c.label), keys: BT_COLS.map(c => c.key), rows: makeTable(btRows, BT_COLS, BT_MARK, "sharpe"),
    sortNote: "표 순서는 샤프 비율이 큰 순입니다(값이 없는 항목은 뒤). 순서는 정렬 기준일 뿐 좋고 나쁨의 판단이 아닙니다." } : null;
  const ml = mlRows.length ? { cols: ML_COLS.map(c => c.label), keys: ML_COLS.map(c => c.key), rows: makeTable(mlRows, ML_COLS, ML_MARK, "val"),
    sortNote: "표 순서는 검증 정확도가 큰 순입니다. 순서는 정렬 기준일 뿐 좋고 나쁨의 판단이 아닙니다." } : null;

  const definitions = [];
  if (btRows.length) {
    definitions.push(
      { term: "누적 수익률", text: "담은 화면이 계산한 전체 기간의 수익률(%)입니다." },
      { term: "단순 보유", text: "같은 기간 처음에 사서 끝에 판 수익률(%)입니다. 담은 화면이 알려 준 경우에만 적습니다." },
      { term: "차이(%p)", text: "누적 수익률에서 단순 보유를 뺀 값입니다. 둘 다 있는 항목만 계산합니다." },
      { term: "샤프", text: "수익률의 평균을 변동성(표준편차)으로 나눈 값입니다. 성과 검증 화면은 일별 수익률로 계산해 √252 를 곱하고 무위험수익률을 0 으로 둡니다. 다른 화면은 계산 가정이 다를 수 있습니다." },
      { term: "최대 낙폭", text: "기간 중 고점에서 저점까지 가장 크게 내려간 비율입니다. 표에는 내려간 폭의 크기(절댓값)로 적습니다." },
      { term: "수익/낙폭", text: "누적 수익률을 최대 낙폭(절댓값)으로 나눈 값입니다. 낙폭이 0.01% 미만이면 계산하지 않습니다." },
      { term: "승률", text: "성과 검증 화면에서는 포지션을 가진 날 중 수익이 난 날의 비율입니다(거래 한 건 단위의 승률이 아닙니다)." },
      { term: "매매 횟수", text: "성과 검증 화면에서는 포지션이 바뀐 횟수입니다(매수와 매도를 각각 셉니다).", },
    );
  }
  if (mlRows.length) {
    definitions.push(
      { term: "CV 평균 · CV 편차", text: "교차검증(데이터를 여러 구간으로 나눠 번갈아 검증)에서 방향을 맞힌 비율의 평균과 흩어진 정도입니다." },
      { term: "검증 정확도", text: "따로 떼어 둔 검증 구간에서 방향을 맞힌 비율입니다." },
      { term: "CV−검증(%p)", text: "CV 평균에서 검증 정확도를 뺀 값입니다. 두 값은 서로 다른 구간에서 잰 값입니다." },
    );
  }
  if (btRows.length || mlRows.length) {
    definitions.push({ term: "최대 · 최소 표시", text: "그 열에서 가장 큰 값 · 가장 작은 값이 있는 곳의 표시입니다. 값의 위치를 알릴 뿐 좋고 나쁨을 뜻하지 않으며, 비교할 값이 둘 이상이고 서로 다를 때만 붙입니다." });
  }

  const cautions = [];
  const bt = btRows.map(r => r.e);
  const all = [...btRows, ...mlRows].map(r => r.e);
  if (all.length) cautions.push("표의 숫자는 모두 과거 자료로 계산한 값입니다.");
  const symbols = uniq(bt.map(e => e.symbol));
  if (symbols.length > 1) cautions.push(`서로 다른 종목(${symbols.join(", ")})의 결과가 함께 있습니다. 종목마다 가격 흐름이 달라, 값의 차이가 규칙 때문인지 종목 때문인지 이 표만으로는 알 수 없습니다.`);
  const spans = uniq(bt.filter(e => e.from && e.asOf).map(e => `${e.from} ~ ${e.asOf}`));
  if (spans.length > 1) cautions.push(`자료 기간이 서로 다릅니다(${spans.join(" / ")}). 기간 길이가 다르면 누적 수익률과 최대 낙폭은 같은 길이의 값이 아닙니다.`);
  const asOfs = uniq(all.map(e => e.asOf));
  if (asOfs.length > 1) cautions.push(`기준일이 서로 다른 항목이 있습니다(${asOfs.join(" / ")}).`);
  const noDate = all.filter(e => !e.asOf);
  if (noDate.length) cautions.push(`기준일 정보가 없는 항목: ${noDate.map(e => e.label).join(", ")}. 값이 언제까지의 자료인지 알 수 없습니다.`);
  const sources = uniq(all.map(e => e.source));
  if (sources.length > 1) cautions.push(`추가된 곳이 서로 다릅니다(${sources.join(" / ")}). 화면마다 비용 가정 · 체결 시점 · 가격 기준 · 샤프 비율의 계산 가정이 같다고 확인되지 않았습니다.`);
  const few = bt.filter(e => e.m.trades !== null && e.m.trades !== undefined && e.m.trades < 30);
  if (few.length) cautions.push(`매매 횟수가 30회 미만인 항목: ${few.map(e => `${e.label} ${e.m.trades}회`).join(", ")}. 거래가 적으면 승률과 샤프 비율이 몇 번의 거래에 크게 좌우됩니다.`);
  const read = all.filter(e => e.origin === "summary");
  if (read.length) cautions.push(`구조화된 지표 칸이 없어 요약 글에서 숫자를 읽은 항목: ${read.map(e => e.label).join(", ")}. 요약 글의 꼴이 바뀌면 값이 빠지거나 달라질 수 있습니다.`);
  if (btRows.length && mlRows.length) cautions.push("ML 정확도(방향을 맞힌 비율)와 백테스트 수익률은 단위와 뜻이 달라 한 열에서 견줄 수 없습니다.");

  const notes = [...btRows, ...mlRows].filter(r => r.e.note).map(r => ({ label: r.e.label, note: r.e.note }));
  return { count: entries.length, backtest, ml, excluded, definitions, cautions, notes, notice: NOTICE_LINE };
}

// ── 화면(HTML) ───────────────────────────────────────────────────────
const TAG_STYLE = "margin-left:4px;padding:0 4px;border:1px solid var(--border2);border-radius:4px;font-size:10.5px;font-weight:400;color:var(--text-mute);white-space:nowrap;";
const TONE_COLOR = { pos: "var(--green)", neg: "var(--red)", "": "" };

function tableHtml(t, heading) {
  const head = `<tr><th>#</th><th>이름</th>${t.cols.map(c => `<th style="text-align:right">${esc(c)}</th>`).join("")}<th>기준일 · 자료 기간</th></tr>`;
  const body = t.rows.map(r => `<tr>
        <td style="color:var(--text-mute)">${r.rank}</td>
        <td><div style="font-weight:600">${esc(r.name)}</div><div class="text-xs" style="color:var(--text-mute)">${esc(r.source)}${r.fromSummary ? " · 요약 글에서 읽음" : ""}</div></td>
        ${t.keys.map(k => { const c = r.cells[k]; return `<td style="text-align:right;${c.tone ? `color:${TONE_COLOR[c.tone]};` : ""}">${esc(c.text)}${c.tag ? `<span style="${TAG_STYLE}">${esc(c.tag)}</span>` : ""}</td>`; }).join("")}
        <td class="text-xs" style="color:var(--text-mute);white-space:nowrap">${esc(r.when)}</td></tr>`).join("");
  return `<h4 class="font-semibold text-sm mt-3 mb-1">${esc(heading)}</h4>
      <p class="text-xs mb-1" style="color:var(--text-mute);">${esc(t.sortNote)}</p>
      <div class="overflow-x-auto"><table><thead>${head}</thead><tbody>${body}</tbody></table></div>`;
}

const listHtml = (title, items, icon = "") => (items.length
  ? `<h4 class="font-semibold text-sm mt-3 mb-1">${esc(title)}</h4><ul class="text-xs space-y-1" style="color:var(--text-dim);line-height:1.7;">${items.map(t => `<li>${icon}${t}</li>`).join("")}</ul>`
  : "");

/** 비교 트레이 카드 안에 붙일 분석 칸 — 담은 항목이 없으면 빈 글. */
export function comparisonHtml(c) {
  if (!c.count) return "";
  const parts = [];
  if (c.backtest) parts.push(tableHtml(c.backtest, "백테스트 결과 비교표"));
  if (c.ml) parts.push(tableHtml(c.ml, "ML 모델 결과 비교표"));
  if (!c.backtest && !c.ml) parts.push(`<p class="text-xs mt-2" style="color:var(--text-mute);">숫자 지표를 읽을 수 있는 항목이 아직 없어 비교 표를 만들지 못했습니다.</p>`);
  if (c.notes.length) parts.push(listHtml("자료 출처", c.notes.map(n => `${esc(n.label)} — ${esc(n.note)}`)));
  if (c.excluded.length) parts.push(listHtml("분석에서 뺀 항목", c.excluded.map(x => `${esc(x.label)}${x.source ? ` (${esc(x.source)})` : ""} — ${esc(x.reason)}`)));
  parts.push(listHtml("읽는 법", c.definitions.map(d => `<b>${esc(d.term)}</b> — ${esc(d.text)}`)));
  parts.push(listHtml("주의", c.cautions.map(esc), `<i class="fa-solid fa-triangle-exclamation" aria-hidden="true"></i> `));
  return `
      <div class="mt-3 pt-3" style="border-top:1px solid var(--border);" data-compare-analysis>
        <div class="flex items-center justify-between flex-wrap gap-2">
          <h3 class="font-semibold text-sm"><i class="fa-solid fa-chart-column" aria-hidden="true"></i> 비교 분석</h3>
          <button type="button" class="btn-secondary text-xs" onclick="compareTrayCopy()">분석 메모 복사 (Markdown)</button>
        </div>
        <p class="text-xs mt-1" style="color:var(--text-mute);">담아 둔 결과의 숫자를 한 표에 모았습니다. 값마다 기준일 · 추가된 곳을 옆에 적었습니다.</p>
        ${parts.join("")}
        <p class="text-xs mt-3" style="color:var(--text-mute);">${esc(c.notice)}</p>
      </div>`;
}

/** core.js 가 비교 트레이 카드 안에서 부르는 한 줄 */
export function compareTrayAnalysisHtml(list) {
  // 이 칸이 예외를 던지면 트레이 표까지 사라진다(core.js 의 renderCompareTray 안에서 불린다) — 분석만 접고 이유를 알린다
  try { return comparisonHtml(buildComparison(list)); }
  catch { return `<p class="text-xs mt-3" style="color:var(--text-mute);">비교 분석을 만들지 못했습니다. 위 표는 그대로 쓸 수 있습니다.</p>`; }
}

// ── 복사(Markdown) ───────────────────────────────────────────────────
function tableMd(t, heading) {
  const head = `| # | 이름 | 추가된 곳 | ${t.cols.join(" | ")} | 기준일 · 자료 기간 |`;
  const sep = `|---|---|---|${t.cols.map(() => "---:").join("|")}|---|`;
  const rows = t.rows.map(r => `| ${r.rank} | ${mdCell(r.name)} | ${mdCell(r.source + (r.fromSummary ? " (요약 글에서 읽음)" : ""))} | ${t.keys.map(k => { const c = r.cells[k]; return mdCell(c.text + (c.tag ? ` (${c.tag})` : "")); }).join(" | ")} | ${mdCell(r.when)} |`);
  return [`## ${heading}`, "", mdLine(t.sortNote), "", head, sep, ...rows, ""];
}

/** KST 기준 만든 시각 글 */
export function kstStamp(d = new Date()) {
  try { return `${d.toLocaleString("ko-KR", { timeZone: "Asia/Seoul", hour12: false })} (KST)`; } catch { return d.toISOString(); }
}

/** 분석 메모(Markdown) — 고지 한 줄이 머리와 꼬리에 모두 있다. */
export function comparisonMarkdown(c, stamp = kstStamp()) {
  const lines = ["# 비교 트레이 분석 메모", "", `- 만든 시각: ${mdLine(stamp)}`, `- 담은 항목: ${c.count}개`, "", `> ${mdLine(c.notice)}`, ""];
  if (c.backtest) lines.push(...tableMd(c.backtest, "백테스트 결과 비교표"));
  if (c.ml) lines.push(...tableMd(c.ml, "ML 모델 결과 비교표"));
  if (!c.backtest && !c.ml) lines.push("숫자 지표를 읽을 수 있는 항목이 아직 없어 비교 표를 만들지 못했습니다.", "");
  if (c.notes.length) lines.push("## 자료 출처", "", ...c.notes.map(n => `- ${mdLine(n.label)} — ${mdLine(n.note)}`), "");
  if (c.excluded.length) lines.push("## 분석에서 뺀 항목", "", ...c.excluded.map(x => `- ${mdLine(x.label)}${x.source ? ` (${mdLine(x.source)})` : ""} — ${mdLine(x.reason)}`), "");
  if (c.definitions.length) lines.push("## 읽는 법", "", ...c.definitions.map(d => `- **${mdLine(d.term)}** — ${mdLine(d.text)}`), "");
  if (c.cautions.length) lines.push("## 주의", "", ...c.cautions.map(t => `- ${mdLine(t)}`), "");
  lines.push(`_${mdLine(c.notice)}_`);
  return lines.join("\n");
}

/** 「분석 메모 복사 (Markdown)」 — 클립보드가 막히면 글을 띄워 직접 복사하게 한다. */
export async function copyComparison(list, setToast) {
  const md = comparisonMarkdown(buildComparison(list));
  try {
    if (!globalThis.navigator?.clipboard?.writeText) throw new Error("clipboard unavailable");
    await globalThis.navigator.clipboard.writeText(md);
    setToast?.("분석 메모를 복사했습니다", "ok");
  } catch {
    globalThis.prompt?.("복사해 쓰세요:", md);
  }
}
