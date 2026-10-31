/* 종목 허브 서랍 — 한 종목의 근거를 보던 화면 옆에 모아 보인다 (할 일 ②-10 · ②-20 · 2026-10-31)
 *
 * 결정(Figma 「Qurious · 종목 허브」 03 설계 B 서랍 — 2026-10-17 결정 알림 #259): 종목 이름 옆 단추를 누르면 보던 화면을 떠나지 않고
 * 오른쪽에 서랍이 열려, 우리 앱의 화면마다 이미 아는 값을 기준일 · 출처와 함께 칸별로 모은다.
 *   · 값 · 기준일 · 까닭 · 고지는 서버 묶음(GET /api/stock-hub) 그대로 옮긴다 — 새로 계산하지 않고, 칸을 합친 한 줄 결론도 만들지 않는다.
 *   · 칸이 비었거나 「준비 중」 · 오류면 값을 지어내지 않고 서버가 준 까닭을 보인다(칸 하나가 실패해도 나머지는 그린다).
 *   · 칸마다 「그 화면으로」 단추 — 값을 만든 화면으로 옮겨 종목을 넣어 준다.
 * 이 파일의 sd* 함수는 DOM 없이 글만 만든다(Node 로 시험 — tests/test_stock_drawer.py TC-SDR).
 * mountStockDrawer 가 문서에 붙어 `[data-hub-open]` 단추의 클릭을 받아 서랍을 열고 닫는다.
 */
// DOM 없는 글자 막기는 한 곳(howtoview.js) — 상대 경로라 브라우저(/js/)와 Node 시험이 같은 파일을 읽는다.
import { esc } from "./howtoview.js";

/** 서랍에 그릴 칸 차례 — 서버 stock_hub.SECTIONS 에서 머리(identity)를 뺀 일곱(시험이 맞댐) */
export const DRAWER_SECTIONS = ["price", "signal", "financials", "disclosures", "news", "schedule", "sector"];
const SD_MARKETS = { KOSPI: "코스피", KOSDAQ: "코스닥", KONEX: "코넥스", ETF: "ETF" };
const SD_STATE = { empty: "자료 없음", error: "불러오지 못함", pending: "준비 중" };   // 서버 stock_hub.EMPTY / ERROR / PENDING
const SD_MINUS = "−";                       // 등락의 빼기 — 하이픈과 헷갈리지 않게 수학 기호
const SD_LIST = 3;                          // 공시 · 기사 · 일정 칸에 보일 줄 수(전체는 그 화면에서)

/** 그 종목의 허브 주소 — 칸 전부 */
export function hubDrawerPath(symbol) {
  return `/api/stock-hub?symbol=${encodeURIComponent(symbol)}`;
}

function sdOk(sec) { return !!sec && sec.status === "ok"; }
function sdNum(v, digits = 0) { return Number(v).toLocaleString("ko-KR", { maximumFractionDigits: digits }); }
function sdPct(v) {
  const n = Number(v);
  return `${n > 0 ? "+" : n < 0 ? SD_MINUS : ""}${Math.abs(n).toFixed(2)}%`;
}
function sdSafeUrl(u) { return /^https?:\/\//i.test(u || "") ? u : ""; }
/** 「2026-10-15」 → 「10월 15일」 · 날짜가 아니면 빈 글 */
export function sdMonthDay(day) {
  const m = String(day || "").match(/^\d{4}-(\d{2})-(\d{2})/);
  return m ? `${Number(m[1])}월 ${Number(m[2])}일` : "";
}
function sdLink(url, text) {
  const safe = sdSafeUrl(url);
  return safe ? `<a href="${esc(safe)}" target="_blank" rel="noopener noreferrer">${esc(text)}</a>` : esc(text);
}

/** 칸 본문 — 칸마다 서버 data 모양 그대로 읽는다 */
function sdPriceBody(d) {
  const arrow = d.change_pct > 0 ? "up" : d.change_pct < 0 ? "dn" : "";
  const prev = d.prev_close != null ? ` · 전일 ${esc(sdNum(d.prev_close))}원` : "";
  return `<p class="sd-main">${esc(sdNum(d.close))}원 <b class="${arrow}">${esc(sdPct(d.change_pct))}</b>`
    + ` <small>${esc(sdMonthDay(d.trade_date))} 종가${prev}</small></p>`
    + (d.basis === "adj_base" ? `<p class="sd-note">수정주가 기준입니다 — 배당 · 분할이 있으면 증권사 화면의 값과 다를 수 있습니다.</p>` : "");
}

function sdReasonLines(label, items) {
  const list = (items || []).slice(0, SD_LIST).map(r => `<li>${esc(r.label || "")} · ${esc(r.text || "")}</li>`).join("");
  return list ? `<p class="sd-sub">${esc(label)}</p><ul class="sd-list">${list}</ul>` : "";
}

function sdSignalBody(d) {
  const side = d.signal ? `${d.signal}${d.signal === "관망" ? "" : " 쪽"}` : "";
  const chip = [side, d.strength].filter(Boolean).join(" · ");
  return (chip ? `<p class="sd-main"><span class="sd-chip">${esc(chip)}</span> <small>${esc(d.confidence_text || "")}</small></p>` : "")
    + (d.summary ? `<p class="sd-text">${esc(d.summary)}</p>` : "")
    + sdReasonLines("그렇게 본 까닭", d.reasons) + sdReasonLines("반대로 본 까닭", d.counter_reasons);
}

function sdFinancialsBody(d) {
  const s = d.summary || {};
  const chip = [`그렇다 ${s.pass ?? 0}`, s.fail ? `아니다 ${s.fail}` : "", s.unknown ? `모름 ${s.unknown}` : ""].filter(Boolean).join(" · ");
  const metrics = (d.metrics || []).map(m => `<li>${esc(m.sentence || `${m.label} ${m.value == null ? "셀 수 없음" : sdNum(m.value, 1) + (m.unit || "")}`)}</li>`).join("");
  const z = d.zscore && d.zscore.value != null
    ? `<p class="sd-text">부실 위험 점수(Z″) ${esc(sdNum(d.zscore.value, 2))} — ${esc(d.zscore.zone_label || "")}</p>`
    : (d.zscore && d.zscore.reason ? `<p class="sd-note">${esc(d.zscore.reason)}</p>` : "");
  const latest = d.latest || {};
  const report = latest.report ? `<p class="sd-note">${sdLink(latest.url, `${latest.report}${latest.period_end ? `(${latest.period_end})` : ""}`)} 기준${latest.restated ? " · 정정 보고서" : ""}</p>` : "";
  return `<p class="sd-main"><span class="sd-chip">${esc(chip)}</span></p>${metrics ? `<ul class="sd-list">${metrics}</ul>` : ""}${z}${report}`
    + (d.kind_note ? `<p class="sd-note">${esc(d.kind_note)}</p>` : "");
}

function sdItemsBody(d, emptyText) {
  const items = (d.items || []).slice(0, SD_LIST);
  if (!items.length) return `<p class="sd-text">${esc(emptyText)}</p>`;
  const rows = items.map(it => `<li><span class="sd-date">${esc(String(it.published || "").slice(5, 10))}</span> ${sdLink(it.url, it.title || "")}`
    + `${it.source_label ? ` <span class="sd-chip sd-chip--soft">${esc(it.source_label)}</span>` : ""}`
    + `${it.attribution ? `<small class="sd-note"> ${esc(it.attribution)}</small>` : ""}</li>`).join("");
  return `<ul class="sd-list">${rows}</ul>${d.total ? `<p class="sd-note">전체 ${esc(sdNum(d.total))}건 가운데 최근 ${items.length}건입니다.</p>` : ""}`;
}

function sdScheduleBody(d) {
  const events = (d.events || []).slice(0, SD_LIST + 1);
  if (!events.length) return `<p class="sd-text">앞으로 ${esc(String(d.days || 60))}일 안의 일정이 없습니다.</p>`;
  const rows = events.map(e => `<li><span class="sd-date">${esc(sdMonthDay(e.date))}${e.weekday ? `(${esc(e.weekday)})` : ""}</span> ${esc(e.title || e.kind_label || "")}`
    + `${e.confidence_label ? ` <span class="sd-chip sd-chip--soft">${esc(e.confidence_label)}</span>` : ""}</li>`).join("");
  return `<ul class="sd-list">${rows}</ul>`;
}

function sdSectorBody(d) {
  const path = [d.section_name, d.division_name].filter(Boolean).join(" › ");
  return `<p class="sd-main">${esc(path)}</p>`
    + (d.peer_count != null ? `<p class="sd-text">같은 업종(KSIC ${esc(d.induty_code || "")}) 수집 상장사 ${esc(sdNum(d.peer_count))}곳</p>` : "");
}

const SD_BODY = {
  price: sdPriceBody, signal: sdSignalBody, financials: sdFinancialsBody,
  disclosures: d => sdItemsBody(d, "최근 공시가 없습니다."), news: d => sdItemsBody(d, "최근 기사가 없습니다."),
  schedule: sdScheduleBody, sector: sdSectorBody,
};

/** 칸 하나 — 머리(이름 · 상태 · 기준일) + 본문 + 출처 · 그 화면으로 */
export function sdSectionHtml(key, sec, labelOf) {
  const label = sec?.label || key;
  if (!sec) {
    return `<section class="sd-sec sd-sec--empty" data-hub-sec="${esc(key)}"><div class="sd-head"><b>${esc(label)}</b><span class="sd-state">자료 없음</span></div>`
      + `<p class="sd-why">서버가 이 칸을 주지 않았습니다.</p></section>`;
  }
  if (!sdOk(sec)) {
    const state = SD_STATE[sec.status] || "확인 필요";
    return `<section class="sd-sec sd-sec--empty" data-hub-sec="${esc(key)}"><div class="sd-head"><b>${esc(label)}</b><span class="sd-state">${esc(state)}</span></div>`
      + `<p class="sd-why">${esc(sec.reason || "이 칸의 자료가 없습니다.")}</p></section>`;
  }
  const body = (SD_BODY[key] || (() => ""))(sec.data || {});
  const asOf = sdMonthDay(sec.as_of);
  const go = sec.view && labelOf?.get(sec.view)
    ? `<button type="button" class="sd-go" data-hub-go="${esc(sec.view)}">${esc(labelOf.get(sec.view))} →</button>` : "";
  return `<section class="sd-sec" data-hub-sec="${esc(key)}"><div class="sd-head"><b>${esc(label)}</b>${asOf ? `<span class="sd-asof">${esc(asOf)} 기준</span>` : ""}</div>`
    + `${body}<div class="sd-foot"><small class="sd-source">${esc(sec.source || "")}</small>${go}</div></section>`;
}

/** 서랍 안쪽 전체 — hub 는 GET /api/stock-hub 응답 그대로 */
export function stockDrawerHtml(hub) {
  const s = hub.sections || {};
  const labelOf = new Map((hub.links || []).map(l => [l.view, l.label]));
  const identity = s.identity?.data || {};
  const name = hub.name || identity.name || hub.symbol;
  const market = SD_MARKETS[hub.market || identity.market] || hub.market || "";
  const price = s.price;
  const head = `<header class="sd-top"><div><strong id="hub-dr-title">${esc(name)}</strong> <span class="sd-chip">${esc(hub.symbol)}</span>`
    + `${market ? ` <span class="sd-chip">${esc(market)}</span>` : ""}`
    + `${sdOk(price) ? ` <span class="sd-top-price">${esc(sdNum(price.data.close))}원 <b class="${price.data.change_pct > 0 ? "up" : price.data.change_pct < 0 ? "dn" : ""}">${esc(sdPct(price.data.change_pct))}</b></span>` : ""}</div>`
    + `<button type="button" class="sd-close" data-hub-close aria-label="서랍 닫기">✕</button></header>`;
  const sections = DRAWER_SECTIONS.map(k => sdSectionHtml(k, s[k], labelOf)).join("");
  const generated = hub.generated_at ? `<small class="sd-note">${esc(String(hub.generated_at).slice(0, 16).replace("T", " "))} 에 모았습니다</small>` : "";
  return `${head}<p class="sd-lead">${esc(hub.note || "새로 계산하지 않고 앱의 다른 화면이 쓰는 값을 그대로 모았습니다.")}</p>`
    + `<div class="sd-body">${sections}</div><footer class="sd-bottom"><p class="sd-notice">${esc(hub.notice || "투자 권유가 아닙니다.")}</p>${generated}</footer>`;
}

/** 불러오기 실패 글 — 로그인 풀림 · 연결 끊김 · 그 밖을 가른다 */
export function sdFailText(err) {
  const msg = String(err?.message || err || "");
  if (/401|로그인/.test(msg)) return "로그인이 풀렸습니다. 다시 로그인한 뒤 열어 주세요.";
  if (/404|찾을 수 없/.test(msg)) return "이 종목의 자료를 찾지 못했습니다. 종목 코드를 확인해 주세요.";
  return `종목 근거를 불러오지 못했습니다${msg ? ` — ${msg}` : ""}. 잠시 뒤 다시 열어 주세요.`;
}

/** 칸의 「그 화면으로」 — 옮기고 종목 칸이 있으면 코드를 넣는다(카드의 다른 화면 단추와 같은 꼴). deps: { navigate, openResearchSymbol, doc } */
export function openViewForSymbol(view, code, name, { navigate, openResearchSymbol, doc }) {
  navigate(view);
  const byId = id => doc.getElementById(id);
  const fill = (id, then) => { const el = byId(id); if (el) { el.value = code; then?.(el); } };
  if (view === "robo-patterns") fill("pt-symbol", () => byId("pt-run")?.click());
  else if (view === "agent-cb") fill("rc-q", el => el.dispatchEvent(new doc.defaultView.KeyboardEvent("keydown", { key: "Enter", bubbles: true })));
  else if (view === "agent-news") openResearchSymbol?.(code, name);
  else if (view === "paper-stock") fill("ps-symbol", el => { byId("ps-quote-btn")?.click(); el.focus(); });
}

/** 문서에 붙인다 — `[data-hub-open="코드"]` 단추(+ data-hub-name)가 서랍을 연다. deps: { api, navigate, openResearchSymbol } */
export function mountStockDrawer(doc, deps) {
  let host = null;
  let last = null;            // 서랍을 연 단추 — 닫으면 초점을 돌려준다
  let token = 0;              // 늦게 온 응답이 새로 연 서랍을 덮지 않게

  function ensureHost() {
    if (host) return host;
    host = doc.createElement("aside");
    host.id = "hub-drawer";
    host.className = "sd-drawer";
    host.setAttribute("role", "dialog");
    host.setAttribute("aria-labelledby", "hub-dr-title");
    host.hidden = true;
    doc.body.appendChild(host);
    host.addEventListener("click", ev => {
      if (ev.target.closest("[data-hub-close]")) { close(); return; }
      const go = ev.target.closest("[data-hub-go]");
      if (go) {
        const { symbol, name } = host.dataset;
        const view = go.dataset.hubGo;
        close(false);
        openViewForSymbol(view, symbol, name, { navigate: deps.navigate, openResearchSymbol: deps.openResearchSymbol, doc });
      }
    });
    return host;
  }

  function close(restoreFocus = true) {
    token += 1;
    if (host) host.hidden = true;
    doc.body.classList.remove("sd-open");
    if (restoreFocus && last && doc.contains(last)) last.focus();
  }

  async function open(symbol, name, trigger) {
    const h = ensureHost();
    last = trigger || null;
    const mine = ++token;
    h.dataset.symbol = symbol;
    h.dataset.name = name || "";
    h.hidden = false;
    doc.body.classList.add("sd-open");
    h.innerHTML = `<header class="sd-top"><strong id="hub-dr-title">${esc(name || symbol)}</strong>`
      + `<button type="button" class="sd-close" data-hub-close aria-label="서랍 닫기">✕</button></header><p class="sd-lead" role="status">근거를 모으는 중입니다…</p>`;
    h.querySelector("[data-hub-close]")?.focus();
    try {
      const hub = await deps.api(hubDrawerPath(symbol));
      if (mine !== token) return;
      h.dataset.name = hub.name || name || "";
      h.innerHTML = stockDrawerHtml(hub);
      h.querySelector("[data-hub-close]")?.focus();
    } catch (err) {
      if (mine !== token) return;
      h.innerHTML = `<header class="sd-top"><strong id="hub-dr-title">${esc(name || symbol)}</strong>`
        + `<button type="button" class="sd-close" data-hub-close aria-label="서랍 닫기">✕</button></header><p class="sd-why" role="alert">${esc(sdFailText(err))}</p>`;
      h.querySelector("[data-hub-close]")?.focus();
    }
  }

  doc.addEventListener("click", ev => {
    const btn = ev.target.closest?.("[data-hub-open]");
    if (!btn) return;
    ev.preventDefault();
    open(btn.dataset.hubOpen, btn.dataset.hubName || "", btn);
  });
  doc.addEventListener("keydown", ev => { if (ev.key === "Escape" && host && !host.hidden) close(); });
  doc.defaultView.addEventListener("hashchange", () => { if (host && !host.hidden) close(false); });   // 다른 화면으로 가면 닫는다
  return { open, close };
}
