/* 퀀트자동매매: 대시보드, 자동매매·위험관리 상태, 전략 분석
 * app.html 인라인 스크립트에서 분리됨. 엔트리는 main.js */
import { api, getMe, setToast, escHtml, fmt, fmtPct, colorPct, kstTime } from "/js/common.js";
import { compareTrayAdd, renderCompareTrayAll } from "/js/core.js";
// Qurious: 전략 분석 종목 칸 = 찾기 칸 하나(최근 본 종목 + 대표 종목 · Figma 03-6 결정 · 2026-10-16)
import { mountStockPick, labelOf } from "/js/stockpick.js";
import { renderTradeExecution } from "/js/trade-status.js";
import { renderDecisionBasis } from "/js/decision-signals.js";
// 종목 검색 줄(안 A1) — 이름 · 코드를 종목으로 풀고, 신호 기록이 있는 국내 코드만 종목 근거 모달을 연다(신호 순위 화면과 같은 부품)
import { resolveSymbolInput } from "/js/stockfind.js";
import { openStockSearch } from "/js/company.js";
import { findQuery, rowView, renderFreshness, drawerFailText } from "/js/signal-rank.js";
import { scCode, mountDailyChart } from "/js/stockchart.js";   // 6자리 단축코드 꼴 판정 한 곳 + 공용 일봉 차트 부품
import { hubExtChartUrl } from "/js/stockdrawer.js";    // 외부 차트(새 탭) 주소 — 모달과 같은 한 곳

const QD_CARD_FIRST = 10;                       // 관찰 목록 카드는 처음 10장만 그리고 나머지는 「더 보기」 로 받는다(안 A3)
let qdStocks = [];                              // 관찰 목록 전체(/api/stocks/quant/list)
let qdCardsDrawn = 0;                           // 지금까지 그린 카드 수
let qdPrevDay = "";                             // 서버가 알려 준 전 거래일(카드의 「최신 아님」 판정용)
let qdListPromise = null;                       // 관찰 목록 요청 하나를 표 · 카드가 나눠 쓴다(새로고침 때만 다시 받는다)
let qdCardsLoaded = false;                      // 카드는 「일봉 단독 규칙」 칸을 펼칠 때 처음 받는다
let qdCardFilter = { signal: "", market: "" };  // 일봉 단독 규칙 카드 필터(2026-11-05) — 신호 · 시장
let qdFilterShown = 0;                          // 필터에 맞는 카드 수
let qdWatchSeq = 0;                             // 표 요청이 겹치면 마지막 것만 그린다
const qdRankByCode = new Map();                 // 표에서 읽은 기록된 신호(6자리 코드 → 줄) — 신호 띠가 같은 종목을 다시 묻지 않게

// ── 전략 분석 종목 칸 ─────────────────────────────────────────────
// 대표 종목 — 옛 고르기 상자의 다섯(한 곳). 고른 기호는 숨은 칸 #bt-symbol 에 넣어 아래 두 단추가 그대로 읽는다.
const BT_PRESETS = [
  { symbol: "005930.KS", name: "삼성전자" }, { symbol: "000660.KS", name: "SK하이닉스" }, { symbol: "035420.KS", name: "NAVER" },
  { symbol: "005380.KS", name: "현대자동차" }, { symbol: "051910.KS", name: "LG화학" },
];
let btPicked = BT_PRESETS[0];
const btHost = document.getElementById("bt-symbol-pick");
if (btHost) {
  mountStockPick(btHost, {
    presets: BT_PRESETS, recentKey: "qurious.recent.quant-backtest", initial: btPicked,
    search: q => api(`/api/stocks/search?q=${encodeURIComponent(q)}`, { redirectOnUnauthorized: false }).then(r => r.results || []),
    onPick: it => { btPicked = it; const h = document.getElementById("bt-symbol"); if (h) h.value = it.symbol; },
  });
}
const btLabel = symbol => (btPicked && btPicked.symbol === symbol ? labelOf(btPicked) : symbol);
// ── 퀀트 대시보드 ────────────────────────────────────────────────
async function loadQuantDashboard() {
  qdListPromise = null;
  loadMarketCards();
  loadWatchTable();                                      // 관찰 목록 표 — 기록된 신호를 요청 한 번으로
  qdCardsReset();                                        // 일봉 단독 규칙 카드는 펼쳐 있을 때만 다시 받는다
  loadQuantChart();
}

// 화면에 보이는 신호 낱말 — 「강력 매수」 → 「매수 · 강」 (#161 A7 · #153)
// 코드의 sig.action(원본)은 바꾸지 않음 — 자동매매가 그 글자를 읽음
function _displayAction(action) {
  if (!action) return "-";
  if (action === "강력 매수") return "매수 · 강";
  if (action === "강력 매도" || action === "강력매도") return "매도 · 강";
  return action;
}

/** 카드 필터용 신호 낱말(2026-11-05) — 「강력 매수」 도 매수 쪽, 「강력 매도」 도 매도 쪽, 그 밖은 관망. 신호가 없으면 빈 글(필터에 안 걸린다). */
function qdBucket(action) {
  if (!action) return "";
  if (/매수/.test(action)) return "매수";
  if (/매도/.test(action)) return "매도";
  return "관망";
}

/** 관찰 목록 종목의 시장 — 종목 기호 꼬리(.KS = KOSPI · .KQ = KOSDAQ)로 읽는다. 모르면 빈 글. */
function qdMarketOf(symbol) {
  const m = /\.(KS|KQ)$/i.exec(String(symbol || ""));
  return m ? (m[1].toUpperCase() === "KS" ? "KOSPI" : "KOSDAQ") : "";
}

async function loadMarketCards() {
  const host = document.getElementById("market-cards");
  try {
    const { indices } = await api("/api/stocks/market");
    // 오름 빨강 · 내림 파랑 — 종목 근거 창과 같은 우리 시장 관례(글자 부호도 함께 보인다)
    host.innerHTML = indices.map(idx => {
      const pct = idx.change_pct;
      const sign = pct != null && pct >= 0 ? "+" : "";
      const cls = pct == null ? "" : (pct >= 0 ? "qd-up" : "qd-dn");
      return `<div class="rounded-xl border p-3 text-center" style="border-color:var(--border);background:var(--surf2);">
        <div class="text-xs" style="color:var(--text-dim);">${escHtml(idx.name)}</div>
        <div class="text-lg font-semibold mt-1">${fmt(idx.price)}</div>
        <div class="${cls} text-xs">${sign}${pct?.toFixed(2) ?? "-"}%</div>
      </div>`;
    }).join("") + `<div class="col-span-3 text-xs" style="color:var(--text-mute);">외부 시세 기준이며 지연될 수 있습니다.</div>`;
  } catch (e) {
    host.innerHTML = `<div class="col-span-3 text-xs" style="color:var(--text-dim);">시장 지수를 불러오지 못했습니다: ${escHtml(e?.message || "")}</div>`;
  }
}

// 규칙 신호 카드(②-21 · ②-22 · 2026-10-30) — 서버 응답의 근거(`signal.reasons`) · 기준일(`as_of`) · 출처 한 줄(`data_note`)을 그대로 보인다.
// 응답 · 판정(`_generate_signal` · 일지 판 지문)은 건드리지 않는다 — 화면만. 낱말은 「규칙 신호」 · 「근거 n개」(결정 대장 10-27 · 「AI 판단」 안 씀).
// 2026-11-03(안 A): 카드의 신호는 「일봉 단독 규칙」 이라 이름표를 달고, 색 관행(빨강=오름)과 부딪히지 않게 카드 색은 빼고 글자 칩만 쓴다.

/** 카드 하나의 HTML — `prevDay` 는 서버가 알려 주는 전 거래일(`/api/data/status` · 없으면 경고를 못 낸다). */
export function signalCardHtml(s, r, prevDay) {
  const sig = r?.signal || {};
  const reasons = Array.isArray(sig.reasons) ? sig.reasons : [];
  const asOf = r?.as_of || "";
  const late = !!(asOf && prevDay && asOf.slice(0, 10) < prevDay.slice(0, 10));      // 마지막 봉이 전 거래일보다 앞이면 최신이 아니다
  const code = String(s.symbol || '').split('.')[0];
  const hub = /^[0-9A-Z]{6}$/.test(code) ? `<button type="button" class="sd-open-btn text-xs" data-hub-open="${escHtml(code)}" data-hub-name="${escHtml(s.name || '')}" title="12:30에 기록한 60분 · 일 · 주 신호와 근거를 엽니다">기록된 신호 · 근거 →</button> <button type="button" class="btn-secondary text-xs" data-paper-open="${escHtml(code)}">PAPER 모의주문 →</button>` : '';
  const basis = reasons.length
    ? `<details class="mt-1"><summary class="text-xs cursor-pointer" style="color:var(--text-dim);">근거 ${reasons.length}개</summary>
        <ul class="text-xs pl-3 list-disc" style="color:var(--text-dim);">${reasons.map(t => `<li>${escHtml(t)}</li>`).join("")}</ul>
        ${r?.data_note ? `<div class="text-xs mt-1" style="color:var(--text-mute);">${escHtml(r.data_note)}</div>` : ""}</details>`
    : `<div class="text-xs mt-1" style="color:var(--text-mute);">근거 없음</div>`;
  return `<div class="rounded-xl border p-2" style="border-color:var(--border);background:var(--surf2);" data-qd-signal="${escHtml(qdBucket(sig.action))}" data-qd-market="${escHtml(qdMarketOf(s.symbol))}">
        <div class="font-semibold">${escHtml(s.name)}</div>
        ${hub}
        <div class="text-xs" style="color:var(--text-mute);">${escHtml(s.symbol)}</div>
        <div class="mt-1 font-medium">${fmt(r?.current_price)} <span class="text-xs font-normal" style="color:var(--text-mute);">종가</span></div>
        ${asOf ? `<div class="text-xs" style="color:${late ? "var(--red)" : "var(--text-mute)"};">${escHtml(asOf.slice(5, 10))} 기준${late ? " · ⚠ 최신 아님" : ""}</div>` : ""}
        <div class="mt-1 text-xs" style="color:var(--text-mute);">일봉 단독 규칙</div>
        <div class="text-xs font-semibold"><span class="qd-chip">${escHtml(_displayAction(sig.action))}</span></div>
        <div class="text-xs" style="color:var(--text-dim);">RSI: ${r?.current_rsi?.toFixed(1) ?? "-"}</div>
        ${basis}
      </div>`;
}

/** 카드 묶음 — stocks 의 종목마다 지표(`quant/indicators`)를 받아 카드로 그린다. 요청은 이 묶음 수만큼만 나간다. */
async function qdCardsHtml(stocks) {
  const results = await Promise.allSettled(stocks.map(s => api(`/api/stocks/quant/indicators?symbol=${encodeURIComponent(s.symbol)}&period=2y`)));
  return stocks.map((s, i) => signalCardHtml(s, results[i].status === "fulfilled" ? results[i].value : null, qdPrevDay)).join("");
}

function qdCardsCount() {
  const c = document.getElementById("signal-cards-count");
  const active = !!(qdCardFilter.signal || qdCardFilter.market);
  if (c) c.textContent = !qdStocks.length ? "" : active ? `${qdStocks.length}종목 중 ${qdFilterShown}개 일치` : `${qdStocks.length}종목 중 ${qdCardsDrawn}개 표시`;
}

/** 「나머지 n종목 보기」 · 「접기」 단추와 신호 순위로 가는 길 — 나머지는 처음 펼칠 때만 받는다(안 A3). */
function qdMoreBar(expanded) {
  const rest = qdStocks.length - QD_CARD_FIRST;
  const host = document.getElementById("signal-cards-more");
  if (!host) return;
  // 단추는 한 번만 만들고 글 · aria 속성만 바꾼다 — 매번 새로 만들면 누른 단추가 사라져 키보드 초점이 문서 처음으로 돌아간다.
  let btn = document.getElementById("signal-cards-toggle");
  if (rest > 0) {
    if (!btn) {
      btn = document.createElement("button");
      btn.type = "button";
      btn.id = "signal-cards-toggle";
      btn.className = "btn-secondary text-xs";
      btn.setAttribute("aria-controls", "signal-cards");
      host.prepend(btn);
    }
    btn.setAttribute("aria-expanded", expanded ? "true" : "false");
    btn.removeAttribute("aria-disabled");
    btn.textContent = expanded ? "나머지 접기" : `나머지 ${rest}종목 보기`;
    // 필터를 건 동안은 관찰 목록 전체에서 거른 결과라 접을 수 없다 — 접으면 개수 글(「n개 일치」)과 보이는 카드가 어긋난다(#556 확인). 필터를 풀면 되살린다.
    btn.hidden = !!(qdCardFilter.signal || qdCardFilter.market) && qdCardsDrawn >= qdStocks.length;
  } else if (btn) btn.remove();
  if (!document.getElementById("signal-cards-rank")) {
    const a = document.createElement("a");
    a.id = "signal-cards-rank";
    a.className = "btn-secondary text-xs";
    a.setAttribute("href", "#signal-rank");
    a.textContent = "신호 순위에서 전체 종목 보기 →";
    host.append(a);
  }
}

// ── 일봉 단독 규칙 카드 필터(2026-11-05 · 「매수/매도/관망 · KOSPI/KOSDAQ 로 거르고 싶다」 피드백) ──────────────
// 카드는 처음 10장만 받으므로, 필터를 거는 순간 나머지도 받아 관찰 목록 전체에서 거른다. 서버 응답은 바꾸지 않고 카드의 data 칸만 읽는다.
const QD_FILTER_SIGNALS = ["", "매수", "매도", "관망"];
const QD_FILTER_MARKETS = ["", "KOSPI", "KOSDAQ"];

function qdFilterBarHtml() {
  const chip = (kind, v, label) => `<button type="button" class="qd-fchip text-xs" data-qd-filter="${kind}" data-value="${escHtml(v)}" aria-pressed="${qdCardFilter[kind] === v}">${escHtml(label)}</button>`;
  // 관찰 목록에 시장이 하나뿐이면(전부 .KS 같은 경우) 시장 줄은 거를 것이 없어 보이지 않는다 — 항상 0개인 「KOSDAQ」 칩을 안 만든다(2026-11-05 신장환 님 #556 확인).
  // 이미 걸려 있는 시장 값은 목록에 없어도 줄을 남겨 풀 수 있게 한다.
  const present = new Set(qdStocks.map(s => qdMarketOf(s.symbol)).filter(Boolean));
  const markets = QD_FILTER_MARKETS.filter(v => !v || present.has(v) || qdCardFilter.market === v);
  const marketRow = present.size >= 2 || qdCardFilter.market
    ? `<div class="qd-frow"><span class="text-xs font-semibold" style="color:var(--text-dim);">시장</span>${markets.map(v => chip("market", v, v || "전체")).join("")}</div>` : "";
  return `<div class="qd-frow"><span class="text-xs font-semibold" style="color:var(--text-dim);">신호</span>${QD_FILTER_SIGNALS.map(v => chip("signal", v, v || "전체")).join("")}</div>`
    + marketRow
    + `<div class="text-xs" style="color:var(--text-mute);" id="signal-cards-filter-note" role="status" aria-live="polite"></div>`;
}

function qdMountCardFilter() {
  const grid = document.getElementById("signal-cards");
  if (!grid || !grid.parentNode || document.getElementById("signal-cards-filter")) return;
  const bar = document.createElement("div");
  bar.id = "signal-cards-filter";
  bar.className = "qd-filter mb-3";
  bar.setAttribute("role", "group");
  bar.setAttribute("aria-label", "규칙 신호 카드 필터");
  bar.innerHTML = qdFilterBarHtml();
  grid.parentNode.insertBefore(bar, grid);
  bar.addEventListener("click", ev => {
    const btn = ev.target.closest ? ev.target.closest("button[data-qd-filter]") : null;
    if (btn) qdSetCardFilter(btn.dataset.qdFilter, btn.dataset.value);
  });
}

/** 나머지 카드(11번째부터)를 받아 붙인다 — 이미 받았으면 그대로. 필터를 걸 때와 「나머지 보기」 가 같은 길을 쓰지는 않는다(후자는 qdToggleCards). */
async function qdLoadExtraCards() {
  const el = document.getElementById("signal-cards");
  if (!el || el.querySelector("[data-qd-extra]") || qdStocks.length <= QD_CARD_FIRST) return true;
  const btn = document.getElementById("signal-cards-toggle");
  if (btn) { btn.setAttribute("aria-disabled", "true"); btn.textContent = "불러오는 중…"; }
  let ok = false;
  try {
    const extra = document.createElement("div");
    extra.setAttribute("data-qd-extra", "");
    extra.className = "contents";
    extra.innerHTML = await qdCardsHtml(qdStocks.slice(QD_CARD_FIRST));
    el.appendChild(extra);
    qdCardsDrawn = qdStocks.length;
    ok = true;
  } finally {
    qdCardsCount(); qdMoreBar(ok);
  }
  return ok;
}

function qdApplyCardFilter() {
  const el = document.getElementById("signal-cards");
  if (!el) return;
  const f = qdCardFilter;
  const active = !!(f.signal || f.market);
  const extra = el.querySelector("[data-qd-extra]");
  if (active && extra) {                                  // 거르는 동안은 접어 둔 나머지도 펼쳐 놓는다
    extra.hidden = false; extra.style.display = "contents";
    qdCardsDrawn = qdStocks.length; qdMoreBar(true);
  }
  let shown = 0;
  el.querySelectorAll("[data-qd-signal]").forEach(card => {
    const ok = (!f.signal || card.dataset.qdSignal === f.signal) && (!f.market || card.dataset.qdMarket === f.market);
    card.hidden = !ok;
    if (ok) shown++;
  });
  qdFilterShown = shown;
  const empty = el.querySelector("[data-qd-filter-empty]");
  if (active && shown === 0) {
    if (!empty) el.insertAdjacentHTML("beforeend", `<div class="col-span-full text-xs" data-qd-filter-empty style="color:var(--text-mute);">이 조건에 맞는 종목이 없습니다. 필터를 풀어 보세요.</div>`);
  } else if (empty) empty.remove();
  const note = document.getElementById("signal-cards-filter-note");
  if (note) {
    const parts = [f.signal, f.market].filter(Boolean);
    const partial = active && qdCardsDrawn < qdStocks.length ? ` · 나머지 종목을 받지 못해 처음 ${QD_CARD_FIRST}종목만 거른 결과입니다` : "";
    note.textContent = active ? `조건 ${parts.join(" · ")} — 관찰 목록 ${qdStocks.length}종목 중 ${shown}개${partial}` : "";
  }
  qdMoreBar(!!extra && !extra.hidden);                    // 필터를 풀면 숨겼던 「나머지 접기」 를 되살리고, 걸면 숨긴다
  qdCardsCount();
}

async function qdSetCardFilter(kind, value) {
  if (!["signal", "market"].includes(kind)) return;
  if (!(kind === "signal" ? QD_FILTER_SIGNALS : QD_FILTER_MARKETS).includes(value)) return;
  qdCardFilter = { ...qdCardFilter, [kind]: value };
  const bar = document.getElementById("signal-cards-filter");
  if (bar) bar.innerHTML = qdFilterBarHtml();
  if (qdCardFilter.signal || qdCardFilter.market) { try { await qdLoadExtraCards(); } catch { /* 못 받아도 받은 카드만으로 건다 — 아래 안내가 말한다 */ } }
  qdApplyCardFilter();
}

async function qdToggleCards() {
  const el = document.getElementById("signal-cards");
  const btn = document.getElementById("signal-cards-toggle");
  if (!el || !btn || btn.getAttribute("aria-disabled") === "true") return;           // 받는 중 다시 누르면 무시(disabled 는 초점을 잃게 해 aria-disabled 로 막는다)
  let extra = el.querySelector("[data-qd-extra]");
  if (!extra) {                                                                       // 처음 펼침 — 나머지 종목 지표를 이때 받는다
    btn.setAttribute("aria-disabled", "true"); btn.textContent = "불러오는 중…";
    let ok = false;
    try {
      extra = document.createElement("div");
      extra.setAttribute("data-qd-extra", "");
      extra.className = "contents";
      extra.innerHTML = await qdCardsHtml(qdStocks.slice(QD_CARD_FIRST));
      el.appendChild(extra);
      qdCardsDrawn = qdStocks.length;
      ok = true;
    } finally {
      qdCardsCount(); qdMoreBar(ok);                                                  // 실패해도 단추를 되살린다(접힌 상태로)
    }
    return;
  }
  const open = extra.hidden;                                                          // 접힌 상태였으면 다시 펼친다
  extra.hidden = !open;
  extra.style.display = open ? "contents" : "none";
  qdCardsDrawn = open ? qdStocks.length : QD_CARD_FIRST;
  qdCardsCount(); qdMoreBar(open);
}

async function loadSignalCards() {
  const el = document.getElementById("signal-cards");
  el.innerHTML = "<div class='col-span-full text-xs' style='color:var(--text-mute);'>규칙 신호 불러오는 중...</div>";
  try {
    const { stocks } = await qdWatchList();
    const title = document.getElementById("signal-cards-title");
    if (title) title.textContent = `기본 일봉 규칙 신호 (관찰 목록 ${stocks.length}종목)`;
    qdStocks = stocks;
    const [html, st] = await Promise.all([
      qdCardsHtml(stocks.slice(0, QD_CARD_FIRST)),                                    // 처음 10종목만 받는다(요청 31 → 10)
      api("/api/data/status").catch(() => null),                                      // 전 거래일 — 못 받으면 경고만 못 낸다
    ]);
    qdPrevDay = st?.calendar?.previous_trading_day || "";
    el.innerHTML = html;
    qdCardsDrawn = Math.min(QD_CARD_FIRST, stocks.length);
    qdCardsLoaded = true;
    qdCardsCount(); qdMoreBar(false);
    qdMountCardFilter();
    if (qdCardFilter.signal || qdCardFilter.market) { try { await qdLoadExtraCards(); } catch { /* 위와 같다 */ } qdApplyCardFilter(); }   // 새로 받았는데 필터가 걸려 있으면 다시 건다
  } catch (e) {
    el.innerHTML = `<div class='col-span-full text-xs' style='color:var(--red);'>${escHtml(e.message)}</div>`;
  }
}

// ── 일봉 단독 규칙 카드 칸(펼칠 때 받는다) ──────────────────────────────────
function qdCardsReset() {
  qdCardsLoaded = false;
  const panel = document.getElementById("signal-cards-panel");
  if (panel && panel.open) loadSignalCards();
}

// ── 관찰 목록 표 — 기록된 신호(60분 · 일 · 주)를 신호 순위 API 한 번으로 읽는다 ──────────────
/** 관찰 목록(/api/stocks/quant/list) — 표와 카드가 한 번만 받아 나눠 쓴다. 실패하면 다음에 다시 받는다. */
function qdWatchList() {
  if (!qdListPromise) qdListPromise = api("/api/stocks/quant/list").catch(e => { qdListPromise = null; throw e; });
  return qdListPromise;
}

const qdCodeOf = symbol => String(symbol || "").split(".")[0];

const QD_WATCH_SIGNALS = ["", "매수", "매도", "관망"];

/** 표 위 줄 — 신호 단추(눌림 상태는 aria-pressed) + 새로고침 + 안내. 시장 줄은 없다(관찰 목록이 전부 .KS 라 거를 것이 없다). */
function qdWatchBarHtml(signal, note, recorded, shown) {
  const chip = v => `<button type="button" class="qd-fchip text-xs" data-qd-wfilter data-value="${escHtml(v)}" aria-pressed="${signal === v}">${escHtml(v || "전체")}</button>`;
  const count = signal ? `조건 ${escHtml(signal)} — 기록된 ${recorded}종목 중 ${shown}종목` : "";
  return `<div class="qd-filter mb-2" role="group" aria-label="관찰 목록 신호 필터"><div class="qd-frow"><span class="text-xs font-semibold" style="color:var(--text-dim);">신호</span>`
    + `${QD_WATCH_SIGNALS.map(chip).join("")}`
    + `<button type="button" class="btn-secondary text-xs" data-qd-wrefresh>새로고침</button></div>`
    + `<div class="text-xs" style="color:var(--text-mute);" role="status" aria-live="polite" data-qd-watch-note>${[count, escHtml(note)].filter(Boolean).join(" · ")}</div></div>`;
}

/** 표 HTML — 기록이 있는 종목은 신호 · 근거 · 기준일, 없는 종목은 서버 까닭 그대로. 줄을 누르면 차트가 그 종목으로 바뀌고 「종목 근거」 는 모달을 연다. */
function qdWatchHtml(resp, stocks, signal = "", note = "") {
  const byCode = new Map(stocks.map(s => [qdCodeOf(s.symbol), s]));
  const allRows = (resp && resp.rows) || [];
  // 신호 필터(2026-11-05 · 표를 직접 거르고 싶다는 피드백) — 이미 받은 응답을 브라우저에서 거른다(서버 요청은 그대로). 기준은 신호 순위 화면과 같은 매수 · 매도 · 관망.
  const rows = signal ? allRows.filter(r => qdBucket(rowView(r).signal) === signal) : allRows;
  const missing = signal ? [] : ((resp && resp.missing) || []);      // 기록 없는 종목은 어느 신호에도 속하지 않으므로 거르는 중에는 안 보인다
  const col = "기록된 신호(60분 · 일 · 주)";
  const head = renderFreshness(resp && resp.freshness, escHtml) + qdWatchBarHtml(signal, note, allRows.length, rows.length);
  const body = rows.map(r => {
    const st = byCode.get(r.symbol);
    const v = rowView(r, c => (byCode.get(c) || {}).name);
    const sym = st ? st.symbol : r.symbol;
    return `<tr data-qd-pick="${escHtml(sym)}" data-qd-name="${escHtml(v.name)}" tabindex="0">`
      + `<td data-label="종목"><b>${escHtml(v.name || r.symbol)}</b> <span class="text-xs">${escHtml(r.symbol)}</span></td>`
      + `<td data-label="${col}"><span class="qd-chip">${escHtml(v.signal)}${v.strength ? " · " + escHtml(v.strength) : ""}</span>`
      + `${v.noIntraday ? `<div class="text-xs" style="color:var(--text-mute);">분봉 없이 계산(일봉 · 주봉만)</div>` : ""}</td>`
      + `<td data-label="근거">${escHtml(v.countsText)}${v.countsNote ? `<div class="text-xs" style="color:var(--text-mute);">${escHtml(v.countsNote)}</div>` : ""}</td>`
      + `<td data-label="기준일">${escHtml(v.asOf)}</td>`
      + `<td data-label="근거 열기"><button type="button" class="sd-open-btn text-xs" data-hub-open="${escHtml(r.symbol)}" data-hub-name="${escHtml(v.name)}">종목 근거 →</button></td></tr>`;
  }).join("");
  const miss = missing.map(m => {
    const st = byCode.get(m.symbol);
    return `<tr data-qd-pick="${escHtml(st ? st.symbol : m.symbol)}" data-qd-name="${escHtml(st ? st.name : "")}" tabindex="0">`
      + `<td data-label="종목"><b>${escHtml(st ? st.name : m.symbol)}</b> <span class="text-xs">${escHtml(m.symbol)}</span></td>`
      + `<td data-label="${col}" colspan="4" style="color:var(--text-mute);">기록 없음 — ${escHtml(m.message || "")}</td></tr>`;
  }).join("");
  const foot = `<div class="text-xs mt-2" style="color:var(--text-mute);">${escHtml((resp && resp.notice) || "")}</div>`;
  if (signal && !rows.length) return `${head}<div class="text-sm">이 조건에 맞는 종목이 없습니다. 필터를 풀어 보세요.</div>${foot}`;
  if (!rows.length && !missing.length) return `${head}<div class="text-sm">이 날짜의 신호 기록이 아직 없습니다.</div>${foot}`;
  return `${head}<div class="qd-table-wrap"><table class="w-full text-sm"><thead><tr><th>종목</th><th>${col}</th><th>근거</th><th>기준일</th><th>근거 열기</th></tr></thead>`
    + `<tbody>${body}${miss}</tbody></table></div>${foot}`;
}

function qdMarkSelected() {
  const now = (document.getElementById("quant-symbol") || {}).value || "";
  document.querySelectorAll("#quant-watch tr[data-qd-pick]").forEach(tr => {
    const on = tr.dataset.qdPick === now;
    tr.classList.toggle("qd-sel", on);
    if (on) tr.setAttribute("aria-current", "true"); else tr.removeAttribute("aria-current");
  });
}

let qdWatchSignal = "";                         // 관찰 목록 표의 신호 필터("" = 전체)
let qdWatchLast = null;                         // 마지막으로 받은 {resp, stocks} — 필터를 바꿀 때 다시 받지 않고 이것을 거른다
let qdWatchNote = "";                           // 새로고침 뒤 안내 글

/** 받아 둔 응답을 지금 필터로 다시 그린다(서버를 부르지 않는다). */
function qdWatchRepaint() {
  const host = document.getElementById("quant-watch");
  if (!host || !qdWatchLast) return;
  const { resp, stocks } = qdWatchLast;
  host.innerHTML = qdWatchHtml(resp, stocks, qdWatchSignal, qdWatchNote);
  const all = (resp.rows || []).length;
  const shown = qdWatchSignal ? (resp.rows || []).filter(r => qdBucket(rowView(r).signal) === qdWatchSignal).length : all;
  const n = document.getElementById("quant-watch-count");
  if (n) n.textContent = qdWatchSignal ? `${stocks.length}종목 중 ${shown}종목 일치` : `${stocks.length}종목 중 ${all}종목 기록`;
  qdMarkSelected();
}

function qdWatchSetSignal(value) {
  if (!QD_WATCH_SIGNALS.includes(value)) return;                     // 모르는 낱말은 무시
  qdWatchSignal = value;
  qdWatchRepaint();
}

/** 새로고침 — 신호 기록을 서버에서 다시 읽는다(새로 계산하지 않는다). 걸어 둔 필터는 그대로 두고 다시 읽은 시각을 안내한다. */
async function qdWatchRefresh() {
  qdWatchNote = "";
  await loadWatchTable();
  if (!qdWatchLast) return;                                          // 실패했으면 표가 실패 글을 이미 보인다
  const clock = new Date().toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Seoul" });
  qdWatchNote = `기록을 다시 읽었습니다(${clock}) — 신호는 새로 계산하지 않고 기록된 값을 그대로 보입니다`;
  qdWatchRepaint();
}

let qdWatchBusy = null;                         // 표를 받는 중이면 그 약속 — 신호 띠가 같은 종목을 따로 묻지 않고 기다린다
function loadWatchTable() {
  qdWatchBusy = qdWatchRun();
  return qdWatchBusy;
}

async function qdWatchRun() {
  const host = document.getElementById("quant-watch");
  if (!host) return;
  const mine = ++qdWatchSeq;
  host.textContent = "관찰 목록의 기록된 신호를 불러오는 중…";
  try {
    const { stocks } = await qdWatchList();
    if (mine !== qdWatchSeq) return;
    // 신호 순위 API 는 한 번에 최대 100종목 — 관찰 목록이 늘어도 요청이 422 로 실패하지 않게 앞 100개만 읽는다(S196 후속 점검)
    const codes = stocks.map(s => qdCodeOf(s.symbol)).filter(c => /^[0-9A-Z]{6}$/.test(c)).slice(0, 100);
    if (!codes.length) {                                                              // 읽을 국내 코드가 없으면 서버에 빈 목록을 보내지 않는다
      qdRankByCode.clear();
      host.textContent = "관찰 목록에 신호 기록을 읽을 수 있는 국내 종목(6자리 코드)이 없습니다.";
      const n0 = document.getElementById("quant-watch-count");
      if (n0) n0.textContent = "";
      return;
    }
    const resp = await api(`/api/stock-hub/signal-rank?symbols=${codes.join(",")}`);   // 요청 한 번(최대 100종목)
    if (mine !== qdWatchSeq) return;
    qdRankByCode.clear();
    (resp.rows || []).forEach(r => qdRankByCode.set(r.symbol, r));
    qdWatchLast = { resp, stocks };
    qdWatchRepaint();
  } catch (e) {
    if (mine === qdWatchSeq) host.textContent = drawerFailText(e);
  }
}

// ── 선택 종목 신호 띠(안 B2) — 기록된 신호 + 일봉 단독 규칙을 이름표를 달아 두 줄로 ──────────
const qdStrip = { symbol: "", rec: undefined, msg: "", daily: undefined, dailyMsg: "" };

function qdStripPaint() {
  const el = document.getElementById("quant-strip");
  if (!el) return;
  const symbol = qdStrip.symbol;
  if (!symbol) { el.innerHTML = ""; return; }
  const label = document.querySelector("#quant-symbol-btn .ssm-btn-label");
  const name = label ? label.textContent : "";
  const q = findQuery(symbol);
  let rec;
  if (qdStrip.rec === undefined) rec = `<span style="color:var(--text-mute);">불러오는 중…</span>`;
  else if (qdStrip.rec) {
    const v = rowView(qdStrip.rec);
    rec = `<span class="qd-chip">${escHtml(v.signal)}${v.strength ? " · " + escHtml(v.strength) : ""}</span> ${escHtml(v.countsText)} · ${escHtml(v.asOf)} 기준`;
  } else rec = `<span style="color:var(--text-dim);">기록 없음</span> <span class="text-xs" style="color:var(--text-mute);">${escHtml(qdStrip.msg)}</span>`;
  const entry = q.ok ? ` <button type="button" class="sd-open-btn text-xs" data-hub-open="${escHtml(q.code)}" data-hub-name="${escHtml(name)}">종목 근거 →</button>` : "";
  let daily;
  if (qdStrip.daily === undefined) daily = `<span style="color:var(--text-mute);">계산 중…</span>`;
  else if (!qdStrip.daily) daily = `<span style="color:var(--text-mute);">${escHtml(qdStrip.dailyMsg || "계산하지 못했습니다")}</span>`;
  else {
    const d = qdStrip.daily, sig = d.signal || {};
    const n = Array.isArray(sig.reasons) ? sig.reasons.length : 0;
    daily = `<span class="qd-chip">${escHtml(_displayAction(sig.action))}</span> RSI ${d.current_rsi?.toFixed(1) ?? "-"} · 근거 ${n}개${d.as_of ? ` · ${escHtml(String(d.as_of).slice(5, 10))} 기준` : ""}`;
  }
  el.innerHTML = `<div class="qd-strip-line"><span class="qd-strip-k">기록된 신호(60분 · 일 · 주)</span>${rec}${entry}</div>`
    + `<div class="qd-strip-line"><span class="qd-strip-k">일봉 단독 규칙</span>${daily}</div>`
    + `<div class="text-xs" style="color:var(--text-mute);">두 값은 계산 방식이 달라 다를 수 있습니다. 참고용이며 투자 권유가 아닙니다.</div>`;
}

/** 종목이 바뀔 때 띠의 기록된 신호 줄을 채운다 — 표에 있으면 그 줄, 없으면 신호 순위 API 로 그 종목만 묻는다. keepDaily 가 참이고 같은 종목이면 일봉 줄은 그대로 둔다. */
async function qdStripLoad(symbol, keepDaily = false) {
  const same = qdStrip.symbol === symbol;
  qdStrip.symbol = symbol; qdStrip.rec = undefined; qdStrip.msg = "";
  if (!(keepDaily && same)) { qdStrip.daily = undefined; qdStrip.dailyMsg = ""; }
  const q = findQuery(symbol);
  if (!q.ok) { qdStrip.rec = null; qdStrip.msg = q.message; qdStripPaint(); return; }
  qdStripPaint();
  if (qdWatchBusy) { try { await qdWatchBusy; } catch { /* 표 실패는 표가 알린다 — 띠는 아래에서 이 종목만 따로 묻는다 */ } }
  if (qdStrip.symbol !== symbol) return;
  const hit = qdRankByCode.get(q.code);
  if (hit) { qdStrip.rec = hit; qdStripPaint(); return; }
  try {
    const r = await api(`/api/stock-hub/signal-rank${q.query}`);
    if (qdStrip.symbol !== symbol) return;                                          // 그 사이 다른 종목으로 바뀌었다
    qdStrip.rec = (r.rows || [])[0] || null;
    qdStrip.msg = qdStrip.rec ? "" : (((r.missing || [])[0] || {}).message || "이 종목의 신호 기록이 없습니다.");
  } catch (e) {
    if (qdStrip.symbol !== symbol) return;
    qdStrip.rec = null; qdStrip.msg = drawerFailText(e);
  }
  qdStripPaint();
}

// ── 차트(공용 일봉 차트 부품) ───────────────────────────────────────────────────
// 2026-11-03 S195 — 종목 근거 창 · 모의투자 시세 · 스탑 차트와 같은 부품(`/js/stockchart.js` mountDailyChart)으로 합쳤다. 캔들 + 거래량 + 이동평균 · 볼린저 +
// 크로스헤어 값 + RSI · MACD 하위 창은 그 부품이 그린다. 국내 6자리 코드는 부품이 수집 일봉(`/api/data/ohlcv`)을 직접 받고, 해외 종목은 지표 응답의
// 종가(`quant/indicators`)를 줄로 넘겨 종가 선으로 보인다. 이 화면 고유의 것 — 신호 띠 · 외부 차트 링크 · 요청 경합 가드(qdChartSeq) — 은 그대로다.
let qdChartSeq = 0;                             // 종목을 빠르게 바꿔도 마지막 요청만 그린다
let qdChart = null;                             // mountDailyChart 결과 — 처음 그릴 때 한 번 만든다
const QD_PERIOD = "6m";                         // 처음 보이는 기간(지표 응답이 주던 최근 100거래일과 비슷하다)

/** 지표 응답의 유닉스 초 → 거래일 글(YYYY-MM-DD, KST 기준).
 * 경로마다 봉의 시각이 다르다 — 수집 DB 는 그날 00:00 UTC(= 09:00 KST), KIS(`kis_market_data._ts_of`)는 그날 00:00 KST(= 전날 15:00 UTC), 야후는 장 시작 시각.
 * UTC 날짜로 읽으면 KIS 경로가 하루 앞서 보여 수집 일봉과 날짜가 안 맞는다. 응답의 source 로 가르지 않고 항상 +9시간(KST)으로 읽으면
 * 세 경로 모두 같은 거래일이 된다(09:00 KST · 00:00 KST · 미국 장 시작 23:30 KST 모두 같은 날). */
function qdDay(t) {
  return new Date(Number(t) * 1000 + 9 * 3600 * 1000).toISOString().slice(0, 10);
}

/** 같은 날짜가 두 번 나오면(야후 마지막 봉 중복 · KST 변환 뒤 겹침) 나중 것을 남기고 시간순으로 세운다 — 차트 라이브러리는 시간이 엄격히 늘어야 한다. */
function qdDedupe(points) {
  const byTime = new Map();
  points.forEach(p => byTime.set(p.time, p));
  return [...byTime.values()].sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : 0));
}

/** 지표 응답의 종가 → 공용 차트가 받는 일봉 줄({ trade_date, close }) — 해외 종목(수집 일봉 없음)과 수집 일봉을 못 받은 국내 종목의 대신 줄. 시가 · 고가 · 저가가 없어 종가 선으로 보인다. */
export function quantRows(data) {
  const days = (data.times || []).map(qdDay);
  return qdDedupe((data.closes || []).map((c, i) => (typeof c === "number" && Number.isFinite(c) && days[i] ? { time: days[i], trade_date: days[i], close: c } : null)).filter(Boolean));
}

/** 공용 차트를 이 화면의 칸에 붙인다(처음 한 번). 부품의 풀이 글은 크레딧 줄(quant-chart-note) 바로 앞 줄에 쓰고, 크레딧 줄은 이 화면이 따로 쓴다. */
function qdChartHost() {
  if (qdChart) return qdChart;
  const credit = document.getElementById("quant-chart-note");
  const view = document.createElement("p");
  view.id = "quant-chart-view-note";
  view.className = "text-xs mt-2";
  view.style.color = "var(--text-mute)";
  if (credit && credit.parentNode) credit.parentNode.insertBefore(view, credit);
  qdChart = mountDailyChart(document, document.getElementById("quant-chart-container"), view, { api });
  return qdChart;
}

function qdChartNote(data, domestic) {
  const el = document.getElementById("quant-chart-note");
  if (!el) return;
  if (!data || !(data.times || []).length) { el.textContent = ""; return; }     // 오류 · 빈 응답에는 「최근 0거래일」 안내를 붙이지 않는다
  const what = domestic ? "그림은 수집 일봉을 최근 6개월로 그린 것이며 실시간 차트가 아닙니다." : `그림은 그중 최근 ${(data.times || []).length}거래일 종가 선이며 실시간 차트가 아닙니다.`;
  el.innerHTML = `${escHtml(data.data_note || "")} — ${escHtml(what)}`
    + ` · 차트: TradingView Lightweight Charts™ · <a href="https://www.tradingview.com/" target="_blank" rel="noopener noreferrer">tradingview.com</a>`;
}

/** 차트 줄의 「외부 차트에서 열기」 — 국내 숫자 6자리 코드일 때만 보인다(그 밖의 종목은 링크를 만들지 않는다). */
function qdChartLink(symbol) {
  const a = document.getElementById("quant-ext-chart");
  const note = document.getElementById("quant-ext-note");
  if (!a) return;
  const url = hubExtChartUrl(symbol);
  a.hidden = !url;
  if (note) note.hidden = !url;
  if (url) a.setAttribute("href", url);
}

async function loadQuantChart() {
  const symbol = document.getElementById("quant-symbol").value;
  const container = document.getElementById("quant-chart-container");
  const mine = ++qdChartSeq;
  const chart = qdChartHost();
  chart.destroy();                                                           // 이전 종목 차트는 로딩 시작에 걷는다(textContent 로 비우면 창 크기 관찰자가 남는다)
  container.textContent = "불러오는 중…";
  const view = document.getElementById("quant-chart-view-note");
  if (view) view.textContent = "";
  qdMarkSelected();
  qdStripLoad(symbol);
  qdChartLink(symbol);
  try {
    const data = await api(`/api/stocks/quant/indicators?symbol=${encodeURIComponent(symbol)}&period=2y`);
    if (mine !== qdChartSeq) return;
    if (qdStrip.symbol === symbol) { qdStrip.daily = data.error ? null : data; qdStrip.dailyMsg = data.error || ""; qdStripPaint(); }
    if (data.error) { chart.destroy(); container.textContent = data.error; qdChartNote(null, false); return; }
    const domestic = !!scCode(symbol);
    container.textContent = "";
    // 국내 코드는 부품이 수집 일봉을 받는다. 못 그리면(받지 못함 · 수집 범위 밖) 지표 응답의 종가 줄로 대신한다 — 해외 종목은 처음부터 그 줄이다.
    let drawn = await chart.draw({ symbol, period: QD_PERIOD, rows: domestic ? undefined : quantRows(data) });
    if (mine !== qdChartSeq) return;
    if (!drawn && domestic) {
      drawn = await chart.draw({ symbol, period: QD_PERIOD, rows: quantRows(data) });
      if (mine !== qdChartSeq) return;
    }
    qdChartNote(data, domestic && drawn);
  } catch (e) {
    if (mine !== qdChartSeq) return;
    if (qdStrip.symbol === symbol) { qdStrip.daily = null; qdStrip.dailyMsg = "일봉 규칙을 계산하지 못했습니다."; qdStripPaint(); }
    chart.destroy();
    qdChartNote(null, false);
    container.textContent = "차트 오류: " + e.message;
  }
}

document.getElementById("quant-chart-load").addEventListener("click", loadQuantChart);
// 고른 종목의 규칙 신호와 근거 — 종목 검색(돋보기)으로 아무 종목이나 골라도 시그널 카드(관찰 목록 5종목)와 별개로 근거를 본다(2026-11-03 피드백).
// 단추 자체가 종목 근거 모달 입구다(`data-hub-open` — 문서 전체의 클릭 위임이 연다). 누를 때 고른 종목으로 속성을 맞춘 뒤 위임이 읽는다.
(function mountQuantHubButton() {
  const loadBtn = document.getElementById("quant-chart-load");
  if (!loadBtn || document.getElementById("quant-hub-open")) return;
  const btn = document.createElement("button");
  btn.type = "button";
  btn.id = "quant-hub-open";
  btn.className = "btn-secondary text-xs";
  btn.textContent = "기록된 신호 · 근거 →";
  btn.title = "고른 종목의 기록된 신호(60분 · 일 · 주)와 근거를 엽니다(국내 종목)";
  btn.setAttribute("data-hub-open", "");
  btn.addEventListener("click", () => {
    const symbol = String((document.getElementById("quant-symbol") || {}).value || "");
    const m = /^([0-9A-Za-z]{6})(?:\.[A-Za-z]+)?$/.exec(symbol.trim());
    const label = document.querySelector("#quant-symbol-btn .ssm-btn-label");
    btn.setAttribute("data-hub-open", m ? m[1].toUpperCase() : "");
    btn.setAttribute("data-hub-name", label ? label.textContent : "");
    if (!m) setToast("신호 기록은 국내 종목(6자리 코드)에만 있습니다.", "error");
  });
  loadBtn.insertAdjacentElement("afterend", btn);
})();
document.getElementById("refresh-market").addEventListener("click", loadQuantDashboard);

// ── 종목 고르기 · 검색 줄 (안 A1 · A4) ─────────────────────────────────────
/** 차트에 올릴 종목을 바꾼다 — 숨은 칸 · 종목 단추 글을 맞추고 차트를 다시 그린다. */
function qdSelectSymbol(symbol, name) {
  const hidden = document.getElementById("quant-symbol");
  if (!hidden) return;
  hidden.value = symbol;
  const btn = document.getElementById("quant-symbol-btn");
  const label = btn && btn.querySelector(".ssm-btn-label");
  const ticker = btn && btn.querySelector(".ssm-btn-ticker");
  if (label) label.textContent = name || symbol;
  if (ticker) ticker.textContent = symbol;
  loadQuantChart();
}

// 종목 찾기 창에서 고르면 company.js 가 칸 값을 바꾸고 change 를 알린다 — 고르는 즉시 차트를 다시 그린다(「차트 로드」 를 따로 누르지 않아도 된다)
document.getElementById("quant-symbol").addEventListener("change", () => loadQuantChart());

function qdFindNote(text) {
  const el = document.getElementById("quant-find-note");
  if (el) el.textContent = text;
}

/** 종목을 정한 뒤 — 차트를 그 종목으로 바꾸고, 신호 기록이 있는 국내 코드면 종목 근거 창을 연다. 그 밖의 종목은 까닭과 일봉 규칙 안내만. */
function qdApplyPick(symbol, name) {
  qdSelectSymbol(symbol, name);
  const q = findQuery(symbol);
  if (!q.ok) {
    qdFindNote(`${q.message} 일봉 규칙(RSI · 이동평균 · 볼린저)은 아래 차트에서 계산해 보입니다.`);
    return;
  }
  qdFindNote(`${name ? `${name}(${q.code})` : q.code} — 기록된 신호와 근거를 엽니다. 기록이 없는 종목이면 창에 그 까닭이 나오고, 일봉 규칙은 아래 차트에서 봅니다.`);
  const entry = document.getElementById("quant-hub-open");
  if (entry) entry.click();                                                        // 차트 줄의 입구 단추를 그대로 누른다(문서 전체의 클릭 위임이 모달을 연다 · 닫으면 초점이 이 단추로 돌아온다)
}

/** 입력 글을 종목으로 풀어 적용한다. 이름이 여럿이면 종목 찾기 창에서 고른 뒤 이어서 한다. */
async function qdFindSubmit(input) {
  const raw = String(input.value || "").trim();
  if (!raw) { qdFindNote("종목 이름이나 코드를 입력해 주세요."); return; }
  const search = async q => ((await api(`/api/stocks/search?q=${encodeURIComponent(q)}`, { redirectOnUnauthorized: false })).results) || [];
  const sym = await resolveSymbolInput(document, input, {
    search, open: openStockSearch,
    onPicked: item => { qdApplyPick(item && item.symbol, item && item.name); },
  });
  if (!sym) return;
  // 코드만 쳤으면 시장 꼬리표(.KS · .KQ)가 없고, 이름으로 찾았으면 종목 이름이 비어 있다 — 검색 결과에서 둘 다 채운다
  let item = null;
  const m = /^([0-9A-Za-z]{6})(?:\.[A-Za-z]+)?$/.exec(sym);
  if (m) {
    try { item = (await search(m[1])).find(r => String(r.symbol || "").toUpperCase().startsWith(m[1].toUpperCase())) || null; } catch { item = null; }
  }
  qdApplyPick(item && !/\./.test(sym) ? item.symbol : sym, item ? item.name : "");
}

/** 대시보드 맨 위 종목 검색 줄 — 신호 순위 화면의 검색과 같은 입구(종목 근거 창)를 쓴다. 칸 번호가 겹치지 않게 이 화면 전용 id 를 쓴다. */
(function qdMountFind() {
  const host = document.getElementById("quant-find-host");
  if (!host) return;
  host.innerHTML = `<form class="qd-find" data-qd-find role="search" aria-label="종목 검색">
      <label for="quant-find-input" class="text-xs font-semibold" style="color:var(--text-dim);">종목 검색</label>
      <div class="qd-find-row">
        <input id="quant-find-input" class="input qd-find-input" type="search" autocomplete="off" placeholder="종목 이름 또는 코드 (예: 삼성전자, 005930)" />
        <button type="submit" class="btn-primary text-xs">검색</button>
      </div>
      <div id="quant-find-note" class="text-xs" style="color:var(--text-mute);" role="status" aria-live="polite">국내 종목(6자리 코드)은 기록된 신호와 근거를 종목 근거 창에서 봅니다. 그 밖의 종목은 일봉 규칙만 아래 차트에서 계산합니다. 참고용이며 투자 권유가 아닙니다.</div>
    </form>`;
  const input = host.querySelector("#quant-find-input");
  host.querySelector("form").addEventListener("submit", ev => { ev.preventDefault(); qdFindSubmit(input); });
})();

// 표의 줄을 누르면(또는 Enter) 차트가 그 종목으로 바뀐다. 「종목 근거」 단추 · 링크는 자기 일을 한다(문서 전체의 클릭 위임).
(function qdMountWatch() {
  const host = document.getElementById("quant-watch");
  if (!host) return;
  const pick = tr => { if (tr && tr.dataset.qdPick) qdSelectSymbol(tr.dataset.qdPick, tr.dataset.qdName || ""); };
  host.addEventListener("click", ev => {
    if (ev.target.closest("button, a")) return;
    pick(ev.target.closest("tr[data-qd-pick]"));
  });
  host.addEventListener("keydown", ev => {
    if (ev.key !== "Enter" && ev.key !== " ") return;
    const tr = ev.target.closest && ev.target.closest("tr[data-qd-pick]");
    if (!tr || ev.target !== tr) return;
    ev.preventDefault();
    pick(tr);
  });
})();

// 일봉 단독 규칙 카드 칸 — 처음 펼칠 때만 지표를 받는다(펼치기 전에는 요청이 없다)
(function qdMountCardsPanel() {
  const panel = document.getElementById("signal-cards-panel");
  if (panel) panel.addEventListener("toggle", () => { if (panel.open && !qdCardsLoaded) loadSignalCards(); });
})();

// 카드의 「나머지 보기 · 접기」 — 단추는 카드를 다시 그릴 때마다 새로 만들어지므로 문서에서 받는다
document.addEventListener("click", ev => {
  if (ev.target.closest && ev.target.closest("#signal-cards-toggle")) qdToggleCards();
  const wf = ev.target.closest && ev.target.closest("button[data-qd-wfilter]");          // 관찰 목록 표의 신호 필터 · 새로고침(표를 다시 그릴 때마다 단추가 새로 생겨 문서에서 받는다)
  if (wf) { qdWatchSetSignal(wf.dataset.value); return; }
  if (ev.target.closest && ev.target.closest("button[data-qd-wrefresh]")) qdWatchRefresh();
});

// ── 자동매매 ─────────────────────────────────────────────────────
// 회차 로그 필터(2026-11-05 · 화면 전수 점검 「새로고침은 있고 필터가 없음」) — 칩 줄은 공용 listbar.js, 거르는 규칙은 autotrade-filter.js(순수 함수).
// import 는 파일 맨 위로 끌어올려지므로(ES 모듈) 이 구역에 둔다.
import { bindListBar, isAllowed, refreshStamp } from "/js/listbar.js";
import { autoTradeView } from "/js/autotrade-filter.js";

let autoLast = null;                            // 마지막으로 받은 /api/auto-trade/status 응답 — 칩을 누르면 다시 받지 않고 이것을 거른다
let autoFilter = { order: "", signal: "" };     // 걸린 조건("" = 전체) — 새로고침해도 유지
let autoGroups = [];                            // 지금 그려진 칩 묶음(모르는 낱말을 막는 데 쓴다)
let autoNote = "";                              // 새로고침 뒤 안내 글

/** 회차 카드 한 장 — 서버가 준 한 회차(신호 · 주문 · 위험관리). 글은 모두 이스케이프한다. */
function autoCycleHtml(cycle) {
  const trades = (cycle.trades || []).map(t => renderTradeExecution(t, escHtml, fmt)).join("");
  const risk = cycle.risk
    ? `<div class="ml-3" style="color:var(--text-dim);">위험관리: 당일 ${cycle.risk.day_pnl_pct ?? "-"}% · ${escHtml(cycle.risk.valuation?.label || "이전 기록 · 평가 기준 미기록")} · 주문 ${cycle.risk.orders_today ?? "-"}건${cycle.risk.halted ? ` · <span style="color:var(--red);font-weight:600;">🛑 ${escHtml(cycle.risk.reason || "비상 정지")}</span>` : ""}</div>`
    : "";
  const stops = Object.entries(cycle.risk?.stop_checks || {}).map(([symbol, stop]) =>
    `<div class="ml-3 text-xs">${escHtml(symbol)} · ${stop.origin === 'transition' ? '전환 시 고정' : '진입 시 고정'} 손절 ${fmt(stop.stop_price)}원 (${escHtml(stop.stop_kind || '%')})</div>`
  ).join('');
  const sigs = (cycle.signals || []).map(sig =>
    `<div class="ml-3" style="color:var(--text-dim);">${escHtml(sig.name || sig.symbol)}: <b style="color:var(--text);">${escHtml(sig.error ? '판단 불가' : _displayAction(sig.action))}</b>${renderDecisionBasis({...sig, cycle_at: cycle.time}, escHtml, kstTime)}</div>`
  ).join("");
  return `<div class="rounded-xl border p-2 mb-1" style="background:var(--surf2);border-color:var(--border);">
    <div class="font-semibold" style="color:var(--accent);">${escHtml(kstTime(cycle.time))}${cycle.note ? ` <span style="color:var(--red);font-weight:400;">· ${escHtml(cycle.note)}</span>` : ""}</div>
    ${risk}${stops}${sigs}${trades ? `<div class="mt-1 font-semibold text-xs" style="color:var(--text-dim);">가상 기록 / 증권사 주문:</div>` + trades : ""}
  </div>`;
}

/** 칩 줄 자리 — 스크롤 칸(#auto-trade-log) 바로 앞에 한 번만 만든다. 로그 칸은 불러올 때마다 innerHTML 이 바뀌어 그 안에 두면 칩이 같이 사라진다. */
function autoMountBar() {
  let host = document.getElementById("auto-trade-bar");
  if (host) return host;
  const log = document.getElementById("auto-trade-log");
  if (!log || !log.parentNode) return null;
  host = document.createElement("div");
  host.id = "auto-trade-bar";
  log.parentNode.insertBefore(host, log);
  bindListBar(host, { onFilter: autoSetFilter });
  return host;
}

/** 받아 둔 응답을 지금 조건으로 다시 그린다(서버를 부르지 않는다). 로그가 비어 있어도 칩 줄은 그린다. */
function autoRepaint() {
  const el = document.getElementById("auto-trade-log");
  if (!el || !autoLast) return;
  const view = autoTradeView(autoLast.log, autoFilter, { esc: escHtml, cycleHtml: autoCycleHtml, note: autoNote });
  autoGroups = view.groups;
  const host = autoMountBar();
  if (host) host.innerHTML = view.barHtml;
  el.innerHTML = view.listHtml;
}

function autoSetFilter(key, value) {
  if (!isAllowed(autoGroups, key, value)) return;                    // 모르는 낱말은 무시
  autoFilter = { ...autoFilter, [key]: value };
  autoRepaint();
}

async function loadAutoTradeStatus() {
  loadRiskStatus(); // 로그가 없어 아래에서 조기 return 되더라도 위험관리 상태는 항상 표시
  try {
    const s = await api("/api/auto-trade/status");
    document.getElementById("auto-trade-status").textContent =
      (s.running ? "🟢 실행 중" : "⭕ 정지") + (s.scheduler ? ` · ${s.scheduler}` : "") + (s.last_cycle_at ? ` · 마지막 사이클 ${kstTime(s.last_cycle_at)}` : "");
    autoLast = s;
    autoNote = "";
    autoRepaint();
  } catch { }
}

/** 「로그 새로고침」 단추 — 기존 동작(서버에서 다시 읽기) 그대로, 성공하면 다시 읽은 시각만 안내한다. 걸어 둔 조건은 유지. */
async function autoRefreshClick() {
  const before = autoLast;
  await loadAutoTradeStatus();
  if (autoLast === before) return;                                   // 못 받았으면 이전 화면 그대로(거짓 안내 금지)
  autoNote = `${refreshStamp("서버에서 다시 읽었습니다")} — 새로 계산하지 않고 기록된 값을 그대로 보입니다`;
  autoRepaint();
}

async function loadRiskStatus() {
  try {
    const r = await api("/api/quant/risk/status");
    const L = r.limits || {};
    const valuationLabel = r.valuation?.label || "평가 기준 미확인";
    const pnlCls = r.day_pnl_pct == null ? "" : (r.day_pnl_pct >= 0 ? "text-emerald-400" : "text-red-400");
    const tile = (label, value, cls = "") => `<div class="rounded-lg p-2" style="background:var(--surf3);"><div style="color:var(--text-mute);">${label}</div><div class="font-bold ${cls}">${value}</div></div>`;
    document.getElementById("risk-kpis").innerHTML = [
      tile("비상 정지", r.kill_switch ? `<span class="text-red-400">🛑 ON</span>` : `<span class="text-emerald-400">OFF</span>`),
      tile(`당일 손익 · ${escHtml(valuationLabel)}`, r.day_pnl_pct == null ? "-" : `${r.day_pnl_pct > 0 ? "+" : ""}${r.day_pnl_pct}% <span class="font-normal" style="color:var(--text-mute)">/ 한도 -${L.daily_loss_limit_pct}%</span>`, r.daily_loss_breached ? "text-red-400" : pnlCls),
      tile("당일 자동 주문", `${r.orders_today ?? 0}건 <span class="font-normal" style="color:var(--text-mute)">/ 최대 ${L.max_orders_per_day || "∞"}</span>`),
      tile("종목 비중 한도", `${L.max_position_pct || "∞"}%`),
      tile("중복 주문 쿨다운", `${L.cooldown_min || 0}분`),
    ].join("");
    document.getElementById("risk-note").textContent = r.kill_switch
      ? `정지 사유: ${r.halt_reason || "수동 비상 정지"} — 해제 후 자동매매를 다시 시작할 수 있습니다.`
      : `시작 자산 ${r.day_start_equity != null ? fmt(r.day_start_equity) + "원" : "-"} · 현재 자산 ${r.current_equity != null ? fmt(r.current_equity) + "원" : "-"} (${r.date})`;
    const g = r.execution_guidance;
    document.getElementById("risk-execution-detail").textContent = g
      ? `서버가 ${g.cycle_seconds}초 간격으로 판단합니다. 작업 지연·중단 시 더 늦어질 수 있습니다. 증권사 상주 감시 주문이 아니며, 판단 사이의 가격 변동이나 손절가 체결을 보장하지 않습니다. `
      + (g.cancel_open_after_min > 0 ? `게이트웨이 주문은 ${g.cancel_open_after_min}분 이상 미체결이면 취소를 요청합니다.` : "시간 경과에 따른 미체결 자동 취소는 꺼져 있습니다.")
      : "실행 주기와 비용 가정을 불러오지 못했습니다.";
    const example = g?.cost_example;
    document.getElementById("risk-cost-example").innerHTML = example ? `
      <p>공격 모드 ${g.aggressive_enabled ? "켜짐" : "꺼짐"} · 설정상 익절 +${escHtml(g.take_profit_pct)}% / 손절 −${escHtml(g.stop_loss_pct)}%의 비용 비교 (${escHtml(example.as_of)})</p>
      <p>${escHtml(example.basis)}</p>
      ${(example.scenarios || []).map(s => `<p>편도 슬리피지 ${escHtml(s.slippage_bps_per_side)}bp 가정: 익절 순수익 ${escHtml(s.net_take_profit_pct)}% · 손절 순손익 ${escHtml(s.net_stop_loss_pct)}% · 손익비 ${s.reward_risk_ratio == null ? "산출 불가(익절 순이익 없음)" : escHtml(s.reward_risk_ratio)} · 본전 승률 ${s.break_even_win_rate_pct == null ? "산출 불가" : escHtml(s.break_even_win_rate_pct) + "%"}</p>`).join("")}
      <p>익절·손절가 체결을 가정한 예시입니다. 갭 하락·미체결·수량별 절사는 반영하지 않으며 실제 승률 예측이 아닙니다.</p>` : "";
  } catch (e) { document.getElementById("risk-kpis").innerHTML = `<span class="text-red-400">${escHtml(e.message)}</span>`; }
}

document.getElementById("risk-kill-on").addEventListener("click", async () => {
  if (!confirm("자동매매를 중지하고 추적 중인 미체결 게이트웨이 주문의 취소를 요청합니다. 이미 전달된 주문의 체결이나 취소 성공을 보장하지 않으며 보유 종목을 자동 청산하지 않습니다. 계속할까요?")) return;
  try {
    const r = await api("/api/quant/risk/kill-switch", { method: "POST", body: { enabled: true, reason: "사용자 수동 비상 정지" } });
    const c = r.cancellation;
    const attention = c?.failed > 0 || c?.skipped > 0;
    setToast(`비상 정지 ON · 취소 요청 ${c?.requested || 0}건. 보유 종목은 유지됩니다.`
      + (attention ? " 취소 실패·미확인 주문은 증권사에서 확인하세요." : " 접수 여부가 불명확한 주문도 증권사에서 확인하세요."), attention ? "error" : "ok"); loadAutoTradeStatus();
  } catch (e) { setToast(e.message, "error"); }
});
document.getElementById("risk-kill-off").addEventListener("click", async () => {
  try {
    await api("/api/quant/risk/kill-switch", { method: "POST", body: { enabled: false } });
    setToast("비상 정지를 해제했습니다.", "ok"); loadAutoTradeStatus();
  } catch (e) { setToast(e.message, "error"); }
});

document.getElementById("auto-start").addEventListener("click", async () => {
  try {
    await api("/api/auto-trade/start", { method: "POST" });
    setToast("자동매매 시작", "ok");
    loadAutoTradeStatus();
  } catch (e) { setToast(e.message, "error"); }
});
document.getElementById("auto-stop").addEventListener("click", async () => {
  try {
    await api("/api/auto-trade/stop", { method: "POST" });
    setToast("자동매매 중지", "ok");
    loadAutoTradeStatus();
  } catch (e) { setToast(e.message, "error"); }
});
document.getElementById("auto-refresh").addEventListener("click", autoRefreshClick);

// ── 백테스트 ─────────────────────────────────────────────────────
document.getElementById("bt-load").addEventListener("click", async () => {
  const symbol = document.getElementById("bt-symbol").value;
  const el = document.getElementById("bt-result");
  el.innerHTML = "<div style='color:var(--text-mute);'>분석 중…</div>";
  try {
    const data = await api(`/api/stocks/quant/indicators?symbol=${encodeURIComponent(symbol)}&period=10y`);
    if (data.error) { el.innerHTML = `<div class='text-red-400'>${escHtml(data.error)}</div>`; return; }
    const sig = data.signal || {};
    // Qurious(2026-10-16 · Figma 03-6): 「10년」 은 부른 기간일 뿐 실제 자료 기간은 「자료」 줄(서버 data_note)이 말한다 ·
    // 신호는 RSI · 이동평균 · 볼린저 규칙의 합산이라 「AI」 라 부르지 않는다 · 카드 색은 화면 색 변수(밝은 화면에서도 읽힘)
    el.innerHTML = `
      <div class="rounded-xl p-4" style="background:var(--surf2);border:1px solid var(--border);">
        <div class="font-semibold mb-2" style="color:var(--text);">${escHtml(btLabel(symbol))} 퀀트 분석</div>
        <div class="grid grid-cols-2 gap-2">
          <div>마지막 종가: <span class="font-semibold">${fmt(data.current_price)}</span></div>
          <div>마지막 봉 RSI: <span class="font-semibold">${data.current_rsi?.toFixed(2) ?? "-"}</span></div>
          <div>규칙 신호(RSI · 이동평균 · 볼린저 합산): <span class="font-semibold ${sig.action === "매수" || sig.action === "강력 매수" ? "text-emerald-400" : sig.action === "매도" || sig.action === "강력 매도" ? "text-red-400" : ""}">${escHtml(_displayAction(sig.action))}</span></div>
          <div>신호 점수: <span class="font-semibold">${sig.score ?? "-"}</span></div>
        </div>
        ${data.data_note ? `<div class="mt-2 text-xs" style="color:var(--text-dim);">자료: ${escHtml(data.data_note)}</div>` : ""}
        <div class="mt-3 text-xs" style="color:var(--text-dim);">${(sig.reasons || []).map(r => "• " + escHtml(r)).join("<br>")}</div>
        <button type="button" class="btn-secondary text-xs mt-3" onclick='compareTrayAdd(${JSON.stringify({
      source: "퀀트 전략 분석", label: btLabel(symbol),
      summary: `RSI ${data.current_rsi?.toFixed(1) ?? "-"} · 규칙 신호 ${_displayAction(sig.action)} (점수 ${sig.score ?? "-"})`,
    }).replace(/'/g, "&#39;")})'>⚖️ 비교에 추가</button>
      </div>
    `;
    renderCompareTrayAll();
  } catch (e) { el.innerHTML = `<div class='text-red-400'>${escHtml(e.message)}</div>`; }
});

// 전략 이름 — 서버가 주는 약어(ma)를 사용자가 읽는 말로(2026-10-30 · 화면 글에 개발 티 나는 말을 쓰지 않는다)
const BT_STRATEGY_NAMES = { ma: "이동평균 교차" };

// B3 · 체결 시점 백테스트 (/api/quant/pipeline)
document.getElementById("bt-pipeline-run").addEventListener("click", async () => {
  const symbol = document.getElementById("bt-symbol").value;
  const entryMode = document.getElementById("bt-entry-mode")?.value || "close";
  const el = document.getElementById("bt-result");
  el.innerHTML = "<div style='color:var(--text-mute);'>전략 백테스트 중…</div>";
  try {
    const url = `/api/quant/pipeline?symbol=${encodeURIComponent(symbol)}`
      + `&period=10y&strategy=ma&entry_mode=${entryMode}&exit_mode=${entryMode}`;
    const d = await api(url);
    if (d.error) { el.innerHTML = `<div class='text-red-400'>${escHtml(d.error)}</div>`; return; }
    const up = (v) => (v ?? 0) >= 0 ? "text-emerald-400" : "text-red-400";
    el.innerHTML = `
      <div class="rounded-xl p-4" style="background:var(--surf2);border:1px solid var(--border);">
        <div class="flex items-center gap-2 mb-2">
          <span class="font-semibold" style="color:var(--text);">${escHtml(btLabel(symbol))} · ${escHtml(BT_STRATEGY_NAMES[d.strategy || "ma"] || d.strategy)}</span>
          <span class="text-xs px-2 py-0.5 rounded" style="background:var(--surf3);">체결: ${escHtml(entryMode === "open" ? "다음 봉 시가" : "그날 종가")}</span>
        </div>
        <div class="grid grid-cols-2 md:grid-cols-4 gap-2">
          <div>총 수익률: <span class="font-semibold ${up(d.total_return_pct)}">${(d.total_return_pct ?? 0).toFixed(2)}%</span></div>
          <div>비용 전: <span class="font-semibold">${(d.gross_return_pct ?? 0).toFixed(2)}%</span></div>
          <div>MDD: <span class="font-semibold text-red-400">${(d.mdd_pct ?? 0).toFixed(2)}%</span></div>
          <div>샤프: <span class="font-semibold">${(d.sharpe_ratio ?? 0).toFixed(3)}</span></div>
          <div>단순 보유: <span class="font-semibold ${up(d.buy_hold_return_pct)}">${(d.buy_hold_return_pct ?? 0).toFixed(2)}%</span></div>
          <div>거래 횟수: <span class="font-semibold">${d.trade_count ?? 0}</span></div>
          <div>승률: <span class="font-semibold">${(d.win_rate_pct ?? 0).toFixed(2)}%</span></div>
          <div>비용: <span class="font-semibold">${(d.cost_pct ?? 0).toFixed(3)}%</span></div>
        </div>
        ${d.data_note ? `<div class="text-xs mt-1" style="color:var(--text-mute);">자료: ${escHtml(d.data_note)}</div>` : ""}
      </div>`;
  } catch (e) { el.innerHTML = `<div class='text-red-400'>${escHtml(e.message)}</div>`; }
});


export { loadAutoTradeStatus, loadQuantDashboard };
