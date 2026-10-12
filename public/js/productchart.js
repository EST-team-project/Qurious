/* 상품 상세 창 — 투자 성향별 상품 안내에서 ETF 이름을 누르면 화면 가운데에 크게 열리는 창(모달) (2026-10-12 · API-PROD-04)
 *
 * 창의 꼴(사용자 화면 피드백 2026-10-12 — 오른쪽 서랍 580 → 가운데 모달 · 반응형 · Figma 03-3 두 안을 융합 · 사용자 결정):
 *   위 = 전체 폭(주의 띠 · 숫자 셋) / 가운데 = 두 단(왼쪽 칩 · 쉬운 말 · 오른쪽 큰 그림 · 캡션 · 기간 · 표 — 문장과 그림을
 *   한눈에) / 아래 = 출처 · 고지. 1024 아래는 한 단(같은 차례) · 760 아래는 화면 전체 — 배치는 CSS 만 바꾼다(products.css).
 *   창 높이는 고정이다(칩 · 기간을 바꿔 내용 길이가 달라져도 창이 다시 가운데로 움직여 칩이 손 밑에서 달아나지 않게).
 *
 * 화면 설계 결정(Figma 「Qurious · 투자 성향별 상품 안내」 03-2 · 05 [결정] 안 B · 사용자 결정 2026-10-12):
 *   숫자 셋(1년 수익률 · 1년 변동성 · 1년 최대 낙폭 — 같은 크기) + 질문 칩 + 그림 한 칸.
 *   - 칩은 만든 것만 보인다(얼마나 벌었나 · 가장 크게 잃은 때 · 레버리지 · 인버스면 「왜 n배가 아닌가」) — 다음 단계 칩을
 *     점선으로 미리 보이지 않는다(실제 서비스처럼 · 사용자 결정).
 *   - 그림 위 글은 서버가 만든 한 줄 요약(sentence)과 근거 줄(points)을 그대로 쓴다 — 화면이 문장을 다시 짓지 않는다
 *     (부호를 낱말로 바꾸는 규칙 · 문장 숫자 = 요약 칸 숫자는 서버 한 곳에서 지키고 시험 TC-PCH 가 본다).
 *   - 머리 숫자는 목록 줄과 같은 값이다(서버가 목록 계산 결과의 그 줄을 `item` 으로 싣는다) — 여기서 다시 재지 않는다.
 *   - 그림마다 캡션(기간 · 세전 · 출처 · 과거 수익률 고지) · 「표로 보기」(캔버스 그림은 화면 읽기 프로그램이 못 읽는다) ·
 *     「재는 법」(식 · 한계).
 *   - 레버리지 · 인버스는 닫을 수 없는 주의 띠(요건 상수표 그대로). 기초지수와 견줄 수 없는 상품(해외 지수 · 지수 바뀜)은
 *     세 값을 그리지 않고 실제 ETF 선 하나와 서버가 낸 까닭만 보인다(말없는 fallback 금지).
 *   - 색은 좋고 나쁨으로 읽히지 않게 — 오른 쪽 · 내린 쪽을 빨강 · 파랑으로 칠하지 않는다(목록과 같은 규칙).
 * 차트: TradingView Lightweight Charts™ 5.2.1(public/js/vendor/lightweight-charts — 강사님 기초 코드에 있던 사본 그대로 ·
 *   npm 5.2.1 과 같은 파일). 창을 처음 열 때만 불러온다(198 KB — 목록만 보는 사람은 받지 않게). 표시 의무: 차트 위 로고
 *   (attributionLogo — tradingview.com 링크)는 끄지 않고, NOTICE 의 문구는 창 아래 크레딧 줄과 저장소 NOTICE.md 에 둔다.
 * 기간 칩을 빨리 바꾸면 앞 요청을 취소한다(늦게 온 옛 응답이 새 기간 그림을 덮지 않게 · 번호로 한 번 더 막는다).
 *
 * 응답을 읽는 변수 이름은 객체마다 하나로 고정한다 — 시험(TC-PCS)이 「변수.칸」 을 모아 서버 응답 칸과 맞댄다.
 *   r 창 응답 · it 목록 줄(r.item) · st 요약 묶음(r.stats) · sr 얼마나 벌었나(st.return) · dd 가장 크게 잃은 때
 *   (st.drawdown) · lv 왜 n배가 아닌가(st.leverage) · ex 칩 글 한 칸(r.explain) · s 계열(r.series — 칸마다 배열) ·
 *   pr 기간 칩 한 칸(r.periods) · ev 사건 묶음(r.events)
 */
import { api, escHtml } from "/js/common.js";

const LWC_SRC = "/js/vendor/lightweight-charts/lightweight-charts-5.2.1.min.js";
const LWC_TIMEOUT_MS = 15000;
const CREDIT_URL = "https://www.tradingview.com/";
//: 칩 차례 — 레버리지 · 인버스는 「왜 n배가 아닌가」 를 앞에(서버 default_chip 이 그 칩을 고른다)
const CHIP_ORDER = ["leverage", "return", "drawdown"];
const COLORS = { ink: "#0f172a", gray: "#94a3b8", slate: "#475569", mark: "#64748b" };

let state = null;               // { code, period, chip, r, loading, error, how, table, seq, abort, returnFocus, picked, autoNote }
let chart = null;               // 지금 그린 차트 하나 — 칩 · 기간을 바꾸거나 닫을 때 remove()
let lwcPromise = null;
let seq = 0;

// ── 작은 도구 ──────────────────────────────────────────────────────────
/** +12.3% · −4.0% — 숫자 칸에만(문장은 서버가 부호를 낱말로 바꿔 보낸다) */
function sgn(v, d = 1) {
  if (v == null || !Number.isFinite(v)) return "—";
  const a = Math.abs(v).toLocaleString("ko-KR", { minimumFractionDigits: d, maximumFractionDigits: d });
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${a}%`;
}
function plain(v, d = 1) { return v == null || !Number.isFinite(v) ? "—" : `${v.toFixed(d)}%`; }
function wonFull(v) { return v == null || !Number.isFinite(v) ? "—" : `${Math.round(v).toLocaleString("ko-KR")}원`; }
function aum(v) {
  if (v == null) return "—";
  if (v >= 1e12) return `${(v / 1e12).toFixed(1)}조 원`;
  if (v >= 1e8) return `${Math.round(v / 1e8).toLocaleString("ko-KR")}억 원`;
  return `${Math.round(v / 1e4).toLocaleString("ko-KR")}만 원`;
}
function multipleText(m) { return `${m < 0 ? "−" : ""}${Math.abs(m)}배`; }
function accent() {
  return getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#2563eb";
}
function root() { return document.getElementById("pc-modal"); }

/** 차트 도구를 한 번만 불러온다 — 실패하면 그림 없이 글 · 표만 보인다(까닭을 함께) */
function loadLwc() {
  if (window.LightweightCharts) return Promise.resolve(window.LightweightCharts);
  if (lwcPromise) return lwcPromise;
  lwcPromise = new Promise((resolve, reject) => {
    const el = document.createElement("script");
    el.src = LWC_SRC;
    el.async = true;
    const timer = setTimeout(() => reject(new Error("timeout")), LWC_TIMEOUT_MS);
    el.onload = () => { clearTimeout(timer); window.LightweightCharts ? resolve(window.LightweightCharts) : reject(new Error("empty")); };
    el.onerror = () => { clearTimeout(timer); reject(new Error("load")); };
    document.head.appendChild(el);
  }).catch(e => { lwcPromise = null; throw e; });       // 다음에 열 때 다시 시도
  return lwcPromise;
}

// ── 창 틀 ──────────────────────────────────────────────────────────────
function ensureRoot() {
  let el = root();
  if (el) return el;
  el = document.createElement("div");
  el.id = "pc-modal";
  el.innerHTML = `<div class="pc-dim" data-pc="close"></div>
    <div class="pc-panel" role="dialog" aria-modal="true" aria-labelledby="pc-title">
      <div class="pc-head"><div class="pc-head-txt"><h3 id="pc-title">상품 상세</h3><p class="pc-sub"></p></div>
        <button type="button" class="pc-close" data-pc="close">닫기 <i class="fa-solid fa-xmark" aria-hidden="true"></i></button></div>
      <div class="pc-body" aria-live="polite"></div></div>`;
  document.body.appendChild(el);
  el.addEventListener("click", onClick);
  el.addEventListener("keydown", trapTab);
  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && root()?.classList.contains("open")) { e.preventDefault(); closeProductChart(); }
  });
  return el;
}

/** 창 안에서 Tab 이 밖으로 나가지 않게(aria-modal) — 처음 · 끝에서 돌린다(자료 안내 서랍과 같은 꼴) */
function trapTab(e) {
  if (e.key !== "Tab") return;
  const panel = root()?.querySelector(".pc-panel");
  if (!panel) return;
  const f = [...panel.querySelectorAll("button, [href], [tabindex]:not([tabindex='-1'])")]
    .filter(el => !el.disabled && el.offsetParent !== null);
  if (!f.length) return;
  if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
  else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
}

function clearChart() {
  if (chart) { try { chart.remove(); } catch (_) { /* 이미 지운 차트 */ } }
  chart = null;
}

// ── 조각 ─────────────────────────────────────────────────────────────
function bandHtml(r) {
  if (!r.band) return "";
  return `<div class="pc-band" role="note"><b>주의</b> ${escHtml(r.band)}${r.requirement_note
    ? `<span class="pc-band-req">${escHtml(r.requirement_note)}</span>` : ""}</div>`;
}

function tilesHtml(it) {
  return `<div class="pc-tiles">
      <div class="pc-tile"><span>1년 수익률</span><strong>${sgn(it.return_1y_pct)}</strong><small>분배금 포함 · 세전</small></div>
      <div class="pc-tile"><span>1년 변동성</span><strong>${plain(it.vol_1y_pct)}</strong><small>하루 등락의 크기</small></div>
      <div class="pc-tile"><span>1년 최대 낙폭</span><strong>${sgn(it.mdd_1y_pct)}</strong><small>고점에서 가장 크게 내린 폭</small></div>
    </div>
    <p class="pc-tiles-note">우리가 모은 자료로 잰 숫자이며, 금융회사가 매기는 공식 투자위험등급이 아닙니다.</p>`;
}

function chipsHtml(r) {
  const have = new Set((r.explain || []).map(ex => ex.chip));
  const chips = CHIP_ORDER.filter(k => have.has(k)).map(k => {
    const ex = r.explain.find(e => e.chip === k);
    const on = k === state.chip;
    return `<button type="button" role="tab" class="pc-chip${k === "leverage" ? " pc-chip--warn" : ""}${on ? " is-on" : ""}"
      aria-selected="${on}" data-chip="${k}">${escHtml(ex.title)}</button>`;
  }).join("");
  return `<div class="pc-chips" role="tablist" aria-label="무엇을 볼까요">${chips}</div>`;
}

function sayHtml(ex) {
  if (!ex) return "";
  const pts = (ex.points || []).map(p => `<li>${escHtml(p)}</li>`).join("");
  return `<div class="pc-say"><p>${escHtml(ex.sentence)}</p>${pts ? `<ul class="pc-why">${pts}</ul>` : ""}</div>`;
}

function periodsHtml(r) {
  const btns = (r.periods || []).map(pr => `<button type="button" class="pc-per${pr.key === state.period ? " is-on" : ""}"
      data-period="${escHtml(pr.key)}"${pr.available ? "" : " disabled"}${pr.reason ? ` title="${escHtml(pr.reason)}"` : ""}
      aria-pressed="${pr.key === state.period}">${escHtml(pr.label)}</button>`).join("");
  return `<div class="pc-periods" role="group" aria-label="기간">${btns}</div>`;
}

function toolsHtml(r) {
  return `<div class="pc-tools">${periodsHtml(r)}
      <div class="pc-links">
        <button type="button" class="pc-link" data-pc="table" aria-expanded="${state.table}">표로 보기</button>
        <button type="button" class="pc-link" data-pc="how" aria-expanded="${state.how}">재는 법 <i class="fa-solid fa-chevron-down" aria-hidden="true"></i></button>
      </div></div>`;
}

function howHtml(ex) {
  if (!state.how || !ex) return "";
  return `<dl class="pc-how"><dt>재는 법</dt><dd>${escHtml(ex.how)}</dd><dt>한계</dt><dd>${escHtml(ex.limits)}</dd></dl>`;
}

/** 칩마다 표 칸 — 그림과 같은 숫자를 글로(화면 읽기 · 숫자를 옮겨 적고 싶은 사람) */
function tableHtml(r) {
  if (!state.table) return "";
  const s = r.series;
  const lv = r.stats.leverage;
  let head, cell;
  if (state.chip === "leverage" && lv && lv.comparable) {
    head = ["날짜", `기초지수 × ${multipleText(lv.multiple)}`, "날마다 다시 맞춘 값", "실제 ETF"];
    cell = i => [s.date[i], sgn(s.lev_naive[i] - 100), sgn(s.lev_reset[i] - 100), sgn(s.tr[i] == null ? null : s.tr[i] - 100)];
  } else if (state.chip === "drawdown") {
    head = ["날짜", "분배금 포함(100만 원 시작)", "최고점 대비"];
    cell = i => [s.date[i], wonFull(s.tr[i] == null ? null : s.tr[i] * 10000), sgn(s.drawdown_pct[i])];
  } else {
    head = ["날짜", "분배금 포함(100만 원 시작)", "가격만"];
    cell = i => [s.date[i], wonFull(s.tr[i] == null ? null : s.tr[i] * 10000), wonFull(s.px[i] * 10000)];
  }
  const rows = s.date.map((_, i) => `<tr>${cell(i).map((v, j) => j ? `<td>${v}</td>` : `<th scope="row">${escHtml(v)}</th>`).join("")}</tr>`);
  return `<div class="pc-table-wrap" tabindex="0"><table class="pc-table">
      <caption>${escHtml(r.window.from)} ~ ${escHtml(r.window.to)} · 거래일 ${r.window.trading_days}일</caption>
      <thead><tr>${head.map(h => `<th scope="col">${escHtml(h)}</th>`).join("")}</tr></thead>
      <tbody>${rows.reverse().join("")}</tbody></table></div>`;
}

function footHtml(r) {
  return `<div class="pc-foot"><ul class="pc-notes">${(r.notes || []).map(n => `<li>${escHtml(n)}</li>`).join("")}</ul>
    <p class="pc-credit">차트: TradingView Lightweight Charts™ · <a href="${CREDIT_URL}" target="_blank" rel="noopener noreferrer">tradingview.com</a></p></div>`;
}

function subText(it, r) {
  return `${it.code} · ${it.asset_class} · 기초지수 ${it.index_name || "—"} · 순자산 ${aum(it.aum)} · 기준일 ${r.as_of || "—"}`;
}

// ── 그림 — 칩마다 ─────────────────────────────────────────────────────
const pts = (s, key, f = v => v) => s.date.map((d, i) => (s[key][i] == null ? null : { time: d, value: f(s[key][i]) })).filter(Boolean);

function newChart(L, el) {
  return L.createChart(el, {
    autoSize: true,
    layout: {
      background: { color: "#ffffff" }, textColor: "#334155", fontSize: 11, attributionLogo: true,
      fontFamily: getComputedStyle(document.body).fontFamily, panes: { separatorColor: "#e2e8f0", enableResize: false },
    },
    grid: { vertLines: { color: "#f1f5f9" }, horzLines: { color: "#eef1f6" } },
    // 아래 여백 18% — 왼쪽 아래 TradingView 로고(표시 의무 · 끄지 않음)가 맨 아래 선 · 분배 표시 글자를 가리지 않게
    rightPriceScale: { borderColor: "#dde2ec", scaleMargins: { top: 0.08, bottom: 0.18 } },
    // 창 크기가 바뀌어도(창 폭은 화면 폭을 따른다) 그린 기간 전체가 보이게 — 이 줄이 없으면 처음 맞춘 막대 간격을 지키느라
    // 폭이 줄면 오른쪽(기준일 쪽)이 잘렸다(2026-10-12 화면 확인 — 1280 → 1024 에서 그림이 2026-04 에서 끝남)
    timeScale: { borderColor: "#dde2ec", fixLeftEdge: true, fixRightEdge: true, lockVisibleTimeRangeOnResize: true },
    crosshair: { mode: 0 },
    localization: { locale: "ko-KR", dateFormat: "yyyy-MM-dd" },
    handleScroll: false, handleScale: false,
  });
}
const MAN = { type: "custom", formatter: v => `${Math.round(v / 1e4).toLocaleString("ko-KR")}만`, minMove: 1 };
const PCT = { type: "custom", formatter: v => sgn(v, 0), minMove: 0.1 };
const PCT1 = { type: "custom", formatter: v => sgn(v, 1), minMove: 0.1 };
const legendLine = (color, text, dash) => `<span><i class="${dash ? "dash" : ""}" style="border-color:${color}"></i>${text}</span>`;

function drawReturn(L, el, r) {
  const s = r.series, sr = r.stats.return, ev = r.events;
  const c = newChart(L, el);
  const tr = c.addSeries(L.LineSeries, { color: accent(), lineWidth: 2, priceFormat: MAN, priceLineVisible: false });
  const px = c.addSeries(L.LineSeries, { color: COLORS.gray, lineWidth: 2, lineStyle: 2, priceFormat: MAN, priceLineVisible: false });
  tr.setData(pts(s, "tr", v => v * 10000));
  px.setData(pts(s, "px", v => v * 10000));
  // 분배락 표시 — 월 분배 상품도 1년 12개라 그대로 둔다(3년이면 많아져 표시 글자는 뺀다)
  const many = ev.distributions.length > 14;
  L.createSeriesMarkers(px, ev.distributions.map(e => ({ time: e.date, position: "belowBar", color: COLORS.mark, shape: "circle",
    text: many ? "" : `분배 ${e.amount.toLocaleString("ko-KR")}원` })));
  c.timeScale().fitContent();
  chart = c;
  return legendLine(accent(), `분배금을 다시 넣었다고 본 값 <b>${wonFull(sr.tr_value)}</b>`)
    + legendLine(COLORS.gray, `가격만 본 값 <b>${wonFull(sr.px_value)}</b>`, true)
    + (ev.distributions.length ? `<span><i class="dot"></i>분배락일 ${ev.distributions.length}번</span>` : "");
}

function drawDrawdown(L, el, r) {
  const s = r.series, dd = r.stats.drawdown;
  const c = newChart(L, el);
  const tr = c.addSeries(L.LineSeries, { color: accent(), lineWidth: 2, priceFormat: MAN, priceLineVisible: false });
  const pk = c.addSeries(L.LineSeries, { color: COLORS.gray, lineWidth: 1, lineStyle: 2, lineType: 1, priceFormat: MAN,
    priceLineVisible: false, lastValueVisible: false });
  tr.setData(pts(s, "tr", v => v * 10000));
  pk.setData(pts(s, "peak", v => v * 10000));
  const uw = c.addSeries(L.BaselineSeries, {
    baseValue: { type: "price", price: 0 }, topLineColor: "rgba(0,0,0,0)", topFillColor1: "rgba(0,0,0,0)", topFillColor2: "rgba(0,0,0,0)",
    bottomLineColor: COLORS.slate, bottomFillColor1: "rgba(71,85,105,0.10)", bottomFillColor2: "rgba(71,85,105,0.40)",
    lineWidth: 1, priceFormat: PCT, priceLineVisible: false,
  }, 1);
  uw.setData(pts(s, "drawdown_pct"));
  const mk = [];
  if (dd && dd.peak_date) {
    mk.push({ time: dd.peak_date, position: "aboveBar", color: COLORS.ink, shape: "arrowDown", text: "고점" });
    mk.push({ time: dd.trough_date, position: "belowBar", color: COLORS.ink, shape: "arrowUp", text: `바닥 ${sgn(dd.depth_pct)}` });
    if (dd.recovered_date) mk.push({ time: dd.recovered_date, position: "aboveBar", color: accent(), shape: "circle", text: "되찾음" });
  }
  L.createSeriesMarkers(tr, mk);
  c.panes()[1]?.setHeight(Math.round(el.clientHeight * 0.32));
  c.timeScale().fitContent();
  chart = c;
  return legendLine(accent(), "분배금을 다시 넣은 값(100만 원으로 시작)")
    + legendLine(COLORS.gray, "그날까지의 최고점", true)
    + legendLine(COLORS.slate, "아래 칸: 최고점보다 얼마나 아래인가(물속 그림)");
}

function drawLeverage(L, el, r) {
  const s = r.series, lv = r.stats.leverage;
  const c = newChart(L, el);
  const ml = multipleText(lv.multiple);
  if (!lv.comparable) {
    // 견줄 수 없으면 세 값을 만들어 내지 않는다 — 실제 ETF 선 하나와 서버가 낸 까닭(글)만
    const ac = c.addSeries(L.LineSeries, { color: COLORS.ink, lineWidth: 2, priceFormat: PCT, priceLineVisible: false });
    ac.setData(pts(s, "tr", v => v - 100));
    c.timeScale().fitContent();
    chart = c;
    return legendLine(COLORS.ink, "실제 ETF(분배금 포함) — 기초지수와 견줄 수 없어 세 값을 그리지 않습니다");
  }
  const nv = c.addSeries(L.LineSeries, { color: COLORS.gray, lineWidth: 2, lineStyle: 2, priceFormat: PCT, priceLineVisible: false });
  const rs = c.addSeries(L.LineSeries, { color: accent(), lineWidth: 3, priceFormat: PCT, priceLineVisible: false });
  const ac = c.addSeries(L.LineSeries, { color: COLORS.ink, lineWidth: 2, priceFormat: PCT, priceLineVisible: false });
  nv.setData(pts(s, "lev_naive", v => v - 100));
  rs.setData(pts(s, "lev_reset", v => v - 100));
  ac.setData(pts(s, "tr", v => v - 100));
  const hist = c.addSeries(L.HistogramSeries, { color: COLORS.gray, priceFormat: PCT1, priceLineVisible: false, lastValueVisible: false }, 1);
  hist.setData(pts(s, "idx_ret_d_pct"));
  c.panes()[1]?.setHeight(Math.round(el.clientHeight * 0.26));
  c.timeScale().fitContent();
  chart = c;
  return legendLine(COLORS.gray, `① 기초지수 × ${ml}(단순 계산) <b>${sgn(lv.naive_pct)}</b>`, true)
    + legendLine(accent(), `② 날마다 ${ml}로 다시 맞춘 값 <b>${sgn(lv.reset_pct)}</b>`)
    + legendLine(COLORS.ink, `③ 실제 ETF <b>${sgn(lv.actual_pct)}</b>`)
    + legendLine(COLORS.gray, "아래 칸: 기초지수 하루 등락");
}

const DRAW = { return: drawReturn, drawdown: drawDrawdown, leverage: drawLeverage };

// ── 그리기 ─────────────────────────────────────────────────────────────
function render() {
  const el = root();
  if (!el || !state) return;
  clearChart();
  const body = el.querySelector(".pc-body");
  const r = state.r;
  const it = r?.item;
  el.querySelector("#pc-title").textContent = it?.name || state.name || "상품 상세";
  el.querySelector(".pc-sub").textContent = it ? subText(it, r) : state.code;
  if (state.loading && !r) { body.innerHTML = `<p class="pc-msg">불러오는 중…</p>`; return; }
  if (state.error) {
    body.innerHTML = `<p class="pc-msg pc-msg--err">${escHtml(state.error)}</p>`;
    return;
  }
  if (!r) return;
  if (r.status !== "ok" && r.status !== "short") {
    const msg = { no_data: "상품 자료가 아직 없습니다.", error: "상품 자료를 읽지 못했습니다. 잠시 뒤 다시 열어 주세요." }[r.status]
      || "상품 자료를 불러오지 못했습니다.";
    body.innerHTML = `<p class="pc-msg pc-msg--err">${escHtml(msg)}</p>`;
    return;
  }
  // 위 = 주의 띠 · 숫자 셋(전체 폭) / 왼쪽 단 = 칩 · 쉬운 말 / 오른쪽 단 = 그림 · 캡션 · 기간 · 표 / 아래 = 출처 · 고지
  const head = `${bandHtml(r)}${tilesHtml(it)}`;
  if (r.status === "short") {
    body.innerHTML = `<div class="pc-top">${head}<p class="pc-msg">${escHtml(r.reason)}</p>${periodsHtml(r)}</div>${footHtml(r)}`;
    return;
  }
  const ex = (r.explain || []).find(e => e.chip === state.chip);
  const tall = state.chip !== "return";
  const note = state.autoNote ? `<p class="pc-msg pc-msg--note">${escHtml(state.autoNote)}</p>` : "";
  body.innerHTML = `<div class="pc-top">${head}${note}</div>
    <div class="pc-left">${chipsHtml(r)}${sayHtml(ex)}</div>
    <div class="pc-right">
      <div class="pc-chart${tall ? " pc-chart--tall" : ""}" role="img" aria-label="${escHtml(ex ? ex.sentence : "")}"></div>
      <div class="pc-legend"></div>
      <p class="pc-cap">${escHtml(r.caption)}</p>${toolsHtml(r)}${howHtml(ex)}${tableHtml(r)}
      ${state.loading ? `<p class="pc-msg">새 기간을 불러오는 중…</p>` : ""}</div>${footHtml(r)}`;
  const box = body.querySelector(".pc-chart");
  const legend = body.querySelector(".pc-legend");
  const mySeq = state.seq;
  // 그림은 칸의 크기가 정해진 뒤(다음 프레임)에 그린다 — 도구가 이미 불려 있으면 그리기가 화면 배치보다 먼저 돌아
  // 크기 0 인 칸에서 fitContent() 를 잡고, 그 뒤 칸이 커져도 마지막 거래일(기준일)이 화면 밖에 남았다
  // (2026-10-12 화면 확인 — 축 라벨이 하루 전 값 · 레버리지 +224% ↔ 실제 기준일 +212%)
  loadLwc().then(L => new Promise(res => requestAnimationFrame(() => res(L)))).then(L => {
    if (!state || state.seq !== mySeq || !box.isConnected) return;     // 그사이 칩 · 기간 · 종목이 바뀌었다
    legend.innerHTML = DRAW[state.chip](L, box, r);
  }).catch(() => {
    if (!box.isConnected) return;
    box.classList.add("pc-chart--none");
    box.innerHTML = `<p class="pc-msg">그림 도구를 불러오지 못해 그림을 그리지 않았습니다 — 위 글과 「표로 보기」 의 숫자는 그대로입니다.</p>`;
  });
}

async function load() {
  const my = ++seq;
  state.seq = my;
  state.abort?.abort();
  const ctl = new AbortController();
  state.abort = ctl;
  state.loading = true;
  state.error = "";
  render();
  try {
    const r = await api(`/api/products/etfs/${encodeURIComponent(state.code)}/chart?period=${encodeURIComponent(state.period)}`,
      { signal: ctl.signal });
    if (!state || state.seq !== my) return;
    state.r = r;
    // 처음 연 기간(1년)이 그 상품에 없으면(상장 1년 안) 열 수 있는 가장 긴 기간으로 다시 연다 — 까닭은 한 줄로 보인다
    // (말없이 바꾸지 않는다 · 사용자가 기간을 고른 뒤에는 바꾸지 않는다)
    if (r.status === "short" && !state.picked) {
      const open = (r.periods || []).filter(pr => pr.available);
      if (open.length) {
        const pr = open[open.length - 1];
        state.autoNote = `${r.reason} 그래서 ${pr.label} 그림을 보입니다.`;
        state.period = pr.key;
        state.picked = true;
        load();
        return;
      }
    }
    const have = new Set((r.explain || []).map(ex => ex.chip));
    if (!state.chip || !have.has(state.chip)) state.chip = r.default_chip;
  } catch (e) {
    if (e.name === "AbortError" || !state || state.seq !== my) return;
    state.error = e.status === 404 ? "이 상품은 기준일 목록에 없습니다." : (e.message || "상품 자료를 불러오지 못했습니다.");
  }
  state.loading = false;
  render();
}

function onClick(event) {
  const t = event.target.closest("button, [data-pc]");
  if (!t || !state) return;
  const d = t.dataset;
  if (d.pc === "close") { closeProductChart(); return; }
  if (d.pc === "how") { state.how = !state.how; render(); return; }
  if (d.pc === "table") { state.table = !state.table; render(); return; }
  if (d.chip && d.chip !== state.chip) { state.chip = d.chip; state.seq = ++seq; render(); return; }
  if (d.period && d.period !== state.period && !t.disabled) { state.period = d.period; state.picked = true; state.autoNote = ""; load(); }
}

/** 목록의 ETF 이름 단추가 부른다 — returnFocus 는 닫을 때 초점을 돌려줄 단추 */
export function openProductChart(code, { name = "", returnFocus = null } = {}) {
  const el = ensureRoot();
  state = { code, name, period: "1y", chip: null, r: null, loading: false, error: "", how: false, table: false, seq: 0,
            abort: null, returnFocus, picked: false, autoNote: "" };
  el.classList.add("open");
  document.body.classList.add("pc-open");
  load();
  el.querySelector(".pc-close")?.focus();
}

export function closeProductChart() {
  const el = root();
  if (!el) return;
  state?.abort?.abort();
  clearChart();
  el.classList.remove("open");
  document.body.classList.remove("pc-open");
  const back = state?.returnFocus;
  state = null;
  if (back && back.isConnected) back.focus();
}
