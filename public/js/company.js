/* 기업분석(지표 대시보드·비교·섹터) + 종목 검색 모달
 * app.html 인라인 스크립트에서 분리됨. 엔트리는 main.js */
import { api, getMe, setToast, escHtml, fmt, fmtPct, colorPct } from "/js/common.js";
import {
  cvLoad, cvOverviewCards, cvValuationRows, cvProfitRows, cvQuarterTable, cvBalanceTable, cvSlice, cvChartSummary, CV_PERIODS,
  cvQuoteLive, CV_QUOTE_POLL_MS,
  cvCompareLoad, cvCompareTable, cvFindCompany, CV_COMPARE_DEFAULT, CV_COMPARE_MAX,
  cvSectorCards, cvSectorNote,
} from "/js/companyview.js";

// ── 기업분석 (Mockup) ────────────────────────────────────────────
const COMPANIES = [
  { code:"005930", name:"삼성전자",      sector:"반도체/전자",  market:"KOSPI" },
  { code:"000660", name:"SK하이닉스",    sector:"반도체",       market:"KOSPI" },
  { code:"035420", name:"NAVER",         sector:"IT플랫폼",     market:"KOSPI" },
  { code:"005380", name:"현대자동차",    sector:"자동차",       market:"KOSPI" },
  { code:"105560", name:"KB금융",        sector:"금융",         market:"KOSPI" },
];

// 대시보드의 기본 종목 다섯(COMPANIES) — 지표는 전자공시 · 수집 일봉으로 계산한다(지표 비교는 CV_COMPARE_DEFAULT 를 쓴다).
let dashboardStocks = COMPANIES.map(c => ({ symbol: `${c.code}.KS`, name: c.name }));
let selectedCompanySymbol = dashboardStocks[0].symbol;
const companyFundCache = {};

function loadCompanyDashboard() {
  renderCompanyTabs();
  fetchAndRenderCompany(selectedCompanySymbol);
}

function renderCompanyTabs() {
  const el = document.getElementById("company-tabs");
  if (!el) return;
  el.innerHTML = dashboardStocks.map(c => `
    <button onclick="selectCompany('${c.symbol}')"
      style="padding:5px 14px; border-radius:20px; font-size:12px; font-weight:600; cursor:pointer; border:1px solid ${selectedCompanySymbol===c.symbol?"var(--accent)":"var(--border)"}; background:${selectedCompanySymbol===c.symbol?"var(--accent)":"var(--surf)"}; color:${selectedCompanySymbol===c.symbol?"#fff":"var(--text-dim)"}; transition:all .15s;">
      ${escHtml(c.name)}
    </button>
  `).join("");
}

function selectCompany(symbol) {
  selectedCompanySymbol = symbol;
  renderCompanyTabs();
  fetchAndRenderCompany(symbol);
}
window.selectCompany = selectCompany;

function addAndSelectCompany(symbol, name) {
  if (!dashboardStocks.some(c => c.symbol === symbol)) {
    dashboardStocks.push({ symbol, name });
  }
  selectCompany(symbol);
}

// 지표 대시보드 — 숫자 · 근거 글은 companyview.js 가 정한다(서버 응답 그대로 · 화면이 셈하지 않음 · 할 일 ①-16 · 2026-10-30)
const LWC_SRC = "/js/vendor/lightweight-charts/lightweight-charts-5.2.1.min.js";
let coChart = null, coChartRows = [], coChartPeriod = "6m", coChartSeq = 0, coLwcPromise = null;
let coLast = null, coQuoteTimer = null, coSeries = null, coLastTime = "";   // 현재가 카드 · 오늘 점을 10초마다 다시 그리려고 마지막 응답과 차트 줄을 들고 있는다

function coLoadLwc() {
  if (window.LightweightCharts) return Promise.resolve(window.LightweightCharts);
  if (!coLwcPromise) {
    coLwcPromise = new Promise((resolve, reject) => {
      const el = document.createElement("script");
      el.src = LWC_SRC;
      const timer = setTimeout(() => reject(new Error("timeout")), 15000);
      el.onload = () => { clearTimeout(timer); window.LightweightCharts ? resolve(window.LightweightCharts) : reject(new Error("empty")); };
      el.onerror = () => { clearTimeout(timer); reject(new Error("load")); };
      document.head.appendChild(el);
    }).catch(e => { coLwcPromise = null; throw e; });
  }
  return coLwcPromise;
}

function coMessage(text, color) {
  return `<div class="text-xs" style="color:${color || "var(--text-mute)"};grid-column:1/-1;line-height:1.6;">${escHtml(text)}</div>`;
}

async function fetchAndRenderCompany(symbol) {
  document.getElementById("co-overview").innerHTML = coMessage("불러오는 중…");
  const parts = await cvLoad(api, symbol);
  if (selectedCompanySymbol === symbol) renderCompanyData(parts);
}

// 내 증권사 키로 받은 현재가만 약 10초마다 다시 받는다(설계 Figma 「Qurious · 기업 지표」 03 · 1단계) — 키가 없거나 장이 닫혔거나 탭이 숨겨지면 받지 않는다
function coApplyToday() {
  const q = coLast && coLast.quote;
  if (!coSeries || !cvQuoteLive(q)) return;
  const day = String(q.fetched_at || "").slice(0, 10);              // 서버가 한국 시각으로 적은 날짜
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day) || day <= coLastTime) return;  // 수집 일봉이 이미 있는 날은 종가를 덮지 않는다
  try { coSeries.update({ time: day, value: q.price }); } catch (_) { /* 차트가 다시 그려지는 중이면 다음 갱신에 */ }
}

function coStopQuotePoll() { clearInterval(coQuoteTimer); coQuoteTimer = null; }

function coStartQuotePoll(symbol) {
  coStopQuotePoll();
  coQuoteTimer = setInterval(async () => {
    const box = document.getElementById("co-overview");
    if (!box || !box.offsetParent || document.hidden || selectedCompanySymbol !== symbol) { coStopQuotePoll(); return; }
    if (!coLast || !cvQuoteLive(coLast.quote) || coLast.quote.market_state === "closed") return;
    try {
      const q = await api(`/api/quote/now?symbol=${encodeURIComponent(symbol)}`);
      if (selectedCompanySymbol !== symbol || !coLast) return;
      coLast.quote = q;
      if (!coLast.indErr) box.innerHTML = cvOverviewCards(coLast.ind, q, escHtml);
      coApplyToday();
    } catch (_) { /* 이번 갱신은 건너뛴다 — 카드의 시각이 그대로라 오래된 값임이 보인다 */ }
  }, CV_QUOTE_POLL_MS);
}

document.addEventListener("visibilitychange", () => {
  if (document.hidden) { coStopQuotePoll(); return; }
  const box = document.getElementById("co-overview");
  if (coLast && box && box.offsetParent) coStartQuotePoll(selectedCompanySymbol);
});

function renderCompanyData(p) {
  const ids = ["co-overview", "co-valuation", "co-profitability", "co-quarterly", "co-balance"];
  const put = (id, html) => { const el = document.getElementById(id); if (el) el.innerHTML = html; };
  coLast = p;
  if (p.unsupported) {
    coStopQuotePoll();
    put("co-overview", coMessage("이 화면은 국내 상장사(종목코드 6자리)의 전자공시 재무로 지표를 계산합니다. 이 종목은 지원하지 않습니다."));
    ids.slice(1).forEach(id => put(id, ""));
    renderCompanyChart([]);
    return;
  }
  if (p.indErr) {
    put("co-overview", coMessage(p.indErr.message || "지표를 받지 못했습니다.", "var(--red)"));
    put("co-valuation", ""); put("co-profitability", "");
  } else {
    put("co-overview", cvOverviewCards(p.ind, p.quote, escHtml));
    put("co-valuation", cvValuationRows(p.ind, escHtml));
    put("co-profitability", cvProfitRows(p.ind, p.health, escHtml));
  }
  put("co-quarterly", p.finErr ? coMessage(p.finErr.message || "분기 실적을 받지 못했습니다.", "var(--red)") : cvQuarterTable(p.fin, escHtml));
  put("co-balance", p.finErr ? coMessage(p.finErr.message || "재무상태를 받지 못했습니다.", "var(--red)") : cvBalanceTable(p.fin, escHtml));
  const nm = (p.ind && p.ind.name) || "";
  const t = document.getElementById("co-chart-title");
  if (t) t.textContent = `${nm ? nm + " " : ""}일봉 종가`;
  renderCompanyChart(p.ohlcv && Array.isArray(p.ohlcv.rows) ? p.ohlcv.rows : [], p.ohlcvErr);
  if (p.code && !p.indErr) coStartQuotePoll(selectedCompanySymbol); else coStopQuotePoll();
}

function renderCompanyChart(rows, err) {
  coChartRows = rows;
  const chips = document.getElementById("co-chart-periods");
  if (chips) {
    chips.innerHTML = Object.keys(CV_PERIODS).map(k => {
      const on = k === coChartPeriod;
      return `<button data-co-period="${k}" style="padding:3px 10px;border-radius:12px;font-size:12px;font-weight:600;cursor:pointer;border:1px solid ${on ? "var(--accent)" : "var(--border)"};background:${on ? "var(--accent)" : "var(--surf)"};color:${on ? "#fff" : "var(--text-dim)"};">${{ "1m": "1개월", "3m": "3개월", "6m": "6개월", "1y": "1년" }[k]}</button>`;
    }).join("");
    chips.querySelectorAll("[data-co-period]").forEach(b => b.addEventListener("click", () => { coChartPeriod = b.dataset.coPeriod; renderCompanyChart(coChartRows, err); }));
  }
  drawCompanyChart(err);
}

async function drawCompanyChart(err) {
  const box = document.getElementById("co-chart"), note = document.getElementById("co-chart-note");
  if (!box || !note) return;
  const seq = ++coChartSeq;
  const pts = cvSlice(coChartRows, coChartPeriod);
  note.textContent = err ? (err.message || "일봉을 받지 못했습니다.") : cvChartSummary(pts, cvQuoteLive(coLast && coLast.quote), !!(coLast && coLast.quote && coLast.quote.market_state === "closed"));
  if (coChart) { coChart.remove(); coChart = null; }
  coSeries = null; coLastTime = "";
  box.innerHTML = "";
  if (!pts.length) return;
  let L;
  try { L = await coLoadLwc(); } catch (e) { note.textContent += " (차트 라이브러리를 불러오지 못했습니다.)"; return; }
  if (seq !== coChartSeq) return;
  coChart = L.createChart(box, {
    autoSize: true,
    layout: { background: { color: "#ffffff" }, textColor: "#334155", fontSize: 11, attributionLogo: true },
    grid: { vertLines: { color: "#f1f5f9" }, horzLines: { color: "#eef1f6" } },
    rightPriceScale: { borderColor: "#dde2ec", scaleMargins: { top: 0.08, bottom: 0.18 } },
    timeScale: { borderColor: "#dde2ec", fixLeftEdge: true, fixRightEdge: true, lockVisibleTimeRangeOnResize: true },
    localization: { locale: "ko-KR", dateFormat: "yyyy-MM-dd" },
    handleScroll: false, handleScale: false,
  });
  // 가격축 숫자는 쉼표 정수(원) — 기본값은 360000.00 처럼 소수점까지 나온다
  const series = coChart.addSeries(L.LineSeries, {
    color: "#4361ee", lineWidth: 2, priceLineVisible: false,
    priceFormat: { type: "custom", formatter: v => Math.round(v).toLocaleString("ko-KR"), minMove: 1 },
  });
  coLastTime = pts[pts.length - 1].time;                           // 라이브러리가 넘긴 객체의 time 을 바꿀 수 있어 setData 전에 읽어 둔다
  series.setData(pts.map(p => ({ time: p.time, value: p.value })));
  coSeries = series;
  coApplyToday();                                                  // 내 증권사 시세가 있으면 오늘 점을 맨 끝에 더한다
  coChart.timeScale().fitContent();
}

// ── 지표 비교(설계 결정 ② 안 A — 기본 5종목 + 종목 추가 · 수집 대상 안에서만 · 2026-10-30 · 할 일 ①-16) ──────────────
let compareCodes = CV_COMPARE_DEFAULT.slice(), compareUniverse = null, compareSeq = 0;

async function coCompareUniverse() {
  if (!compareUniverse) compareUniverse = (await api("/api/data/indicators/universe")).companies || [];
  return compareUniverse;
}

function coCompareMsg(text, color) {
  const el = document.getElementById("co-compare-msg");
  if (el) { el.textContent = text || ""; el.style.color = color || "var(--text-mute)"; }
}

function renderCompareChips(cols) {
  const el = document.getElementById("co-compare-chips");
  if (!el) return;
  el.innerHTML = cols.map(c => {
    const nm = (c.ind && c.ind.name) || c.code;
    return `<span style="display:inline-flex;align-items:center;gap:6px;padding:4px 6px 4px 12px;border-radius:16px;font-size:12px;font-weight:600;border:1px solid var(--border);background:var(--surf);">${escHtml(nm)}`
      + `<button type="button" data-co-del="${escHtml(c.code)}" aria-label="${escHtml(nm)} 빼기" style="border:0;background:transparent;cursor:pointer;color:var(--text-dim);font-size:14px;line-height:1;">×</button></span>`;
  }).join("");
  el.querySelectorAll("[data-co-del]").forEach(b => b.addEventListener("click", () => {
    compareCodes = compareCodes.filter(x => x !== b.dataset.coDel);
    coCompareMsg("");
    loadCompanyCompare();
  }));
}

function bindCompareForm() {
  const form = document.getElementById("co-compare-form");
  if (!form || form.dataset.bound) return;
  form.dataset.bound = "1";
  form.addEventListener("submit", async ev => {
    ev.preventDefault();
    const input = document.getElementById("co-compare-add");
    try {
      const list = await coCompareUniverse();
      const hit = cvFindCompany(list, input.value);
      if (!hit) { coCompareMsg(`수집 대상 ${list.length}곳 안에서 「${input.value.trim()}」 을(를) 찾지 못했습니다. 이름이나 종목코드 6자리를 확인하세요.`, "var(--red)"); return; }
      if (compareCodes.includes(hit.code)) { coCompareMsg(`${hit.name} 은(는) 이미 표에 있습니다.`); return; }
      if (compareCodes.length >= CV_COMPARE_MAX) { coCompareMsg(`최대 ${CV_COMPARE_MAX}개까지 나란히 볼 수 있습니다. 하나를 빼고 추가하세요.`); return; }
      compareCodes.push(hit.code);
      input.value = "";
      coCompareMsg("");
      loadCompanyCompare();
    } catch (e) {
      coCompareMsg(`종목 목록을 받지 못했습니다: ${e.message}`, "var(--red)");
    }
  });
}

async function loadCompanyCompare() {
  const el = document.getElementById("co-compare-table");
  if (!el) return;
  bindCompareForm();
  const seq = ++compareSeq;
  el.innerHTML = coMessage("불러오는 중…");
  const cols = await cvCompareLoad(api, compareCodes);
  if (seq !== compareSeq) return;
  renderCompareChips(cols);
  el.innerHTML = cvCompareTable(cols, escHtml);
  coCompareUniverse().then(list => {
    const dl = document.getElementById("co-compare-universe");
    if (dl && !dl.childElementCount) dl.innerHTML = list.map(c => `<option value="${escHtml(c.name)}">${escHtml(c.code)}</option>`).join("");
  }).catch(e => coCompareMsg(`종목 목록을 받지 못했습니다: ${e.message}`, "var(--red)"));
}

// ── 섹터(설계 결정 ③ 안 C — 섹터 = 업종별 PER · PBR 중앙값 · 하루 등락은 「산업」 화면 · 2026-10-30 · 할 일 ①-16) ──────
let sectorSeq = 0;

async function loadCompanySector() {
  const cards = document.getElementById("co-sector-cards"), note = document.getElementById("co-sector-note");
  if (!cards) return;
  const seq = ++sectorSeq;
  cards.innerHTML = coMessage("업종별 PER · PBR 을 계산하는 중… (처음 한 번은 몇 초 걸립니다)");
  if (note) note.innerHTML = "";
  try {
    const data = await api("/api/data/indicators/sectors");
    if (seq !== sectorSeq) return;
    cards.innerHTML = cvSectorCards(data, escHtml);
    if (note) note.innerHTML = cvSectorNote(data, escHtml);
  } catch (e) {
    if (seq === sectorSeq) cards.innerHTML = coMessage(e.message || "업종별 지표를 받지 못했습니다.", "var(--red)");
  }
}

// 종목 검색 창 열기 — 아래 즉시 실행 함수가 채운다(다른 화면의 「찾기」 단추가 부른다 · js/stockfind.js)
let _openStockSearch = null;
export function openStockSearch(callback) { if (_openStockSearch) _openStockSearch(callback); }

// ── 종목 검색 모달 ────────────────────────────────────────────────
(function () {
  let _resolve = null;
  let _debounceTimer = null;

  const modal = document.getElementById("stock-search-modal");
  const inputEl = document.getElementById("ssm-query");
  const resultsEl = document.getElementById("ssm-results");

  function openModal(callback) {
    _resolve = callback;
    inputEl.value = "";
    resultsEl.innerHTML = `<div class="ssm-empty">종목명 또는 코드를 입력하세요</div>`;
    modal.classList.add("open");
    setTimeout(() => inputEl.focus(), 60);
  }

  function closeModal() {
    modal.classList.remove("open");
    _resolve = null;
  }

  function selectItem(symbol, name) {
    if (_resolve) _resolve({ symbol, name });
    closeModal();
  }

  async function doSearch(q) {
    if (!q.trim()) {
      resultsEl.innerHTML = `<div class="ssm-empty">종목명 또는 코드를 입력하세요</div>`;
      return;
    }
    resultsEl.innerHTML = `<div class="ssm-loading">검색 중…</div>`;
    try {
      const data = await api(`/api/stocks/search?q=${encodeURIComponent(q)}`);
      if (!data.results?.length) {
        resultsEl.innerHTML = `<div class="ssm-empty">검색 결과가 없습니다</div>`;
        return;
      }
      resultsEl.innerHTML = data.results.map(r => `
        <div class="ssm-item" data-symbol="${escHtml(r.symbol)}" data-name="${escHtml(r.name)}">
          <div>
            <div class="ssm-item-name">${escHtml(r.name)}</div>
            <div class="ssm-item-meta">${escHtml(r.exchange)} · ${escHtml(r.type)}</div>
          </div>
          <span class="ssm-item-ticker">${escHtml(r.symbol)}</span>
        </div>
      `).join("");
      resultsEl.querySelectorAll(".ssm-item").forEach(el => {
        el.addEventListener("click", () => selectItem(el.dataset.symbol, el.dataset.name));
      });
    } catch (e) {
      resultsEl.innerHTML = `<div class="ssm-empty" style="color:var(--red);">오류: ${escHtml(e.message)}</div>`;
    }
  }

  _openStockSearch = openModal;

  inputEl.addEventListener("input", () => {
    clearTimeout(_debounceTimer);
    _debounceTimer = setTimeout(() => doSearch(inputEl.value), 320);
  });
  inputEl.addEventListener("keydown", e => { if (e.key === "Escape") closeModal(); });

  modal.addEventListener("click", e => { if (e.target === modal) closeModal(); });
  document.getElementById("ssm-close").addEventListener("click", closeModal);

  // 퀀트 대시보드 차트 종목 버튼
  document.getElementById("quant-symbol-btn").addEventListener("click", () => {
    openModal(({ symbol, name }) => {
      document.getElementById("quant-symbol").value = symbol;
      const btn = document.getElementById("quant-symbol-btn");
      btn.querySelector(".ssm-btn-label").textContent = name;
      btn.querySelector(".ssm-btn-ticker").textContent = symbol;
    });
  });

  // 주가 차트 종목 버튼
  document.getElementById("chart-symbol-btn").addEventListener("click", () => {
    openModal(({ symbol, name }) => {
      document.getElementById("chart-symbol").value = symbol;
      const btn = document.getElementById("chart-symbol-btn");
      btn.querySelector(".ssm-btn-label").textContent = name;
      btn.querySelector(".ssm-btn-ticker").textContent = symbol;
    });
  });

  // 지표 대시보드 종목 검색 (기존 5개 목업 종목 외 임의 종목 추가)
  document.getElementById("company-search-btn")?.addEventListener("click", () => {
    openModal(({ symbol, name }) => addAndSelectCompany(symbol, name));
  });
})();


export { loadCompanyCompare, loadCompanyDashboard, loadCompanySector };
