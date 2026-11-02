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
import { mountDailyChart, scCode, SC_PERIODS, SC_DEFAULT_PERIOD } from "./stockchart.js";
import { RULE_PLAIN, SECTION_HOWTO, SIGNAL_HIT_NOTE, planTimeframeNote, planMarketLine, planIndexMove, planNoteText } from "./stockplain.js";

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

/** 증권사 화면(Npay 증권) 주소 — 코드가 6자리 영숫자(ETF 포함)일 때만. finance.naver.com 주소는 이리로 넘어온다(2026-11-02 직접 열어 확인) */
export function hubNaverUrl(symbol) {
  return /^[0-9A-Z]{6}$/.test(String(symbol || "")) ? `https://stock.naver.com/domestic/stock/${symbol}/price` : "";
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
    + (d.pending_note ? `<p class="sd-note">${esc(d.pending_note)}</p>` : "")
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

/** 신호 근거 한 줄 — 서버 글 그대로 + 규칙 점수 + 「쉬운 뜻」 · 「조심할 점」(규칙 key 로 stockplain.js 에서 찾음 · 모르는 key 면 서버 글만) */
function sdPlainReason(r, open = false) {
  const p = RULE_PLAIN[r.key];
  const n = Number(r.points);
  const pts = Number.isFinite(n) && r.points != null ? ` <small class="sd-note">(규칙 점수 ${n > 0 ? "+" : n < 0 ? SD_MINUS : ""}${Math.abs(n)})</small>` : "";
  const tf = planTimeframeNote(r.label);
  return `<li><b>${esc(r.label || "")} · ${esc(r.text || "")}</b>${pts}`
    + (p ? `<details class="sd-more"${open ? " open" : ""}><summary>쉬운 뜻 · 조심할 점</summary><div class="sd-plain"><span>쉬운 뜻</span> ${esc(p.mean)}${tf ? ` ${esc(tf)}` : ""}</div><div class="sd-care"><span>조심할 점</span> ${esc(p.care)}</div></details>` : "") + `</li>`;
}

function sdPlainReasonLines(label, items) {
  const list = (items || []).slice(0, SD_LIST).map((r, i) => sdPlainReason(r, i === 0)).join("");
  return list ? `<p class="sd-sub">${esc(label)} — ${(items || []).slice(0, SD_LIST).length}개</p><ul class="sd-list sd-list--plain">${list}</ul>` : "";
}

/** 모달 안 신호 칸 — 서버 한 줄 요약은 그대로, 근거마다 쉬운 풀이를 붙이고 「말하지 않는 것」 을 밝힌다 */
function sdSignalPlainBody(d) {
  const side = d.signal ? `${d.signal}${d.signal === "관망" ? "" : " 쪽"}` : "";
  const chip = [side, d.strength].filter(Boolean).join(" · ");
  return (chip ? `<p class="sd-main"><span class="sd-chip">${esc(chip)}</span> <small>${esc(d.confidence_text || "")}</small></p>` : "")
    + (d.summary ? `<p class="sd-text">${esc(d.summary)}</p>` : "")
    + sdPlainReasonLines("그렇게 본 까닭", d.reasons) + sdPlainReasonLines("반대로 본 까닭", d.counter_reasons)
    + `<p class="sd-note"><b>이 설명이 말하지 않는 것</b> — 앞으로 오를지 내릴지, 목표 가격, 얼마를 사고팔지. ${esc(SIGNAL_HIT_NOTE)} 신뢰도는 여러 기간의 판단이 같은 방향인 정도일 뿐 맞을 확률이 아닙니다.</p>`;
}

const SD_BODY_PLAIN = { signal: sdSignalPlainBody };

/** 칸 하나 — 머리(이름 · 상태 · 기준일) + 본문 + 출처 · 그 화면으로. opts.plain 이면(크게 보기 모달) 「이 칸 읽는 법」 과 쉬운 풀이를 더한다 */
export function sdSectionHtml(key, sec, labelOf, opts = {}) {
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
  const body = ((opts.plain && SD_BODY_PLAIN[key]) || SD_BODY[key] || (() => ""))(sec.data || {});
  const asOf = sdMonthDay(sec.as_of);
  const go = sec.view && labelOf?.get(sec.view)
    ? `<button type="button" class="sd-go" data-hub-go="${esc(sec.view)}">${esc(labelOf.get(sec.view))} →</button>` : "";
  const howto = opts.plain && SECTION_HOWTO[key]
    ? `<details class="sd-howto"><summary>이 칸 읽는 법</summary><p class="sd-note">${esc(SECTION_HOWTO[key])}</p></details>` : "";
  return `<section class="sd-sec" data-hub-sec="${esc(key)}"><div class="sd-head"><b>${esc(label)}</b>${asOf ? `<span class="sd-asof">${esc(asOf)} 기준</span>` : ""}</div>`
    + `${howto}${body}<div class="sd-foot"><small class="sd-source">${esc(sec.source || "")}</small>${go}</div></section>`;
}

/** 일봉 차트 칸(서랍 · 크게 보기 모달 공통 부품 — 설계 Figma 07 쪽 안 C). 6자리 코드가 아닌 종목(해외)이면 빈 글.
 *  expand 가 참이면 머리에 「크게 보기 ⤢」 단추 — 모달에서는 거짓. height 는 차트 칸 높이(px) */
export function sdChartBoxHtml(symbol, { expand = true, height = 150, period = SC_DEFAULT_PERIOD } = {}) {
  if (!scCode(symbol)) return "";
  const chips = SC_PERIODS.map(([k, label]) => `<button type="button" class="sd-period${k === period ? " on" : ""}" data-hub-period="${esc(k)}">${esc(label)}</button>`).join("");
  return `<div class="sd-chartbox" data-hub-chartbox><div class="sd-chart-head"><b>일봉 종가</b><span class="sd-periods">${chips}</span>`
    + `${expand ? `<button type="button" class="sd-expand" data-hub-expand>크게 보기 ⤢</button>` : ""}</div>`
    + `<div class="sd-chart" data-hub-chart style="height:${Number(height) || 150}px"></div><small class="sd-note" data-hub-chart-note></small></div>`;
}

/** 크게 보기 모달 안쪽 — 머리(이름 · 코드 · 지금가) + 큰 일봉 차트 + 신호 근거 칸(서버 값 그대로) + 닫기. hub 는 GET /api/stock-hub 응답 */
export function sdModalHtml(hub, { marketLine = "" } = {}) {
  const s = hub.sections || {};
  const labelOf = new Map((hub.links || []).map(l => [l.view, l.label]));
  const name = hub.name || (s.identity?.data || {}).name || hub.symbol;
  const price = s.price;
  const top = `<header class="sd-top"><div><strong id="hub-md-title">${esc(name)}</strong> <span class="sd-chip">${esc(hub.symbol)}</span>`
    + `${sdOk(price) ? ` <span class="sd-top-price">${esc(sdNum(price.data.close))}원 <b class="${price.data.change_pct > 0 ? "up" : price.data.change_pct < 0 ? "dn" : ""}">${esc(sdPct(price.data.change_pct))}</b></span>` : ""}</div>`
    + `<button type="button" class="sd-close" data-hub-modal-close aria-label="크게 보기 닫기">✕</button></header>`;
  const chart = sdChartBoxHtml(hub.symbol, { expand: false, height: 340 });
  // 큰 차트를 맨 위에 두고 그 아래로 일곱 칸을 차례로 — 모달 안에서 내리며 읽는다(사용자 11-02 「모달로 크게 띄워서 내리면서 보는 것이 편하겠다」)
  const sections = DRAWER_SECTIONS.map(k => sdSectionHtml(k, s[k], labelOf, { plain: true })).join("");
  const code = hubNaverUrl(hub.symbol);
  // 다른 화면으로 가는 입구 — 서랍에 있던 두 단추(PAPER 모의주문 · 리밸런싱 목표)를 모달 하나로 모았다(6자리 코드일 때만)
  const actions = code
    ? `<p class="sd-actions"><button type="button" class="btn-secondary" data-hub-go="paper-stock">PAPER 모의주문으로 →</button> `
      + `<button type="button" class="btn-secondary" data-hub-go="robo-rebalance">리밸런싱 목표 편집으로 →</button> `
      + `<small class="sd-note">종목코드만 전달합니다. 수량 · 비중은 그 화면에서 직접 확인하세요.</small></p>` : "";
  const tpl = `<details class="sd-tpl"><summary>내 판단 정리 틀 — 보고서처럼 정리할 때 복사</summary>`
    + `<p class="sd-note">위 칸에서 이미 보인 사실만 채웠고, 밑줄 칸은 직접 적습니다. 서버에 저장하지 않습니다.</p>`
    + `<pre class="sd-tpl-text" data-hub-tpl>${esc(planNoteText(hub, marketLine))}</pre>`
    + `<button type="button" class="btn-secondary" data-hub-copy>글 복사</button> <small class="sd-note" data-hub-copied role="status"></small></details>`;
  return `${top}<div class="sd-modal-body"><p class="sd-lead sd-modal-intro">아래는 앱이 이미 가진 값을 기준일 · 출처와 함께 모은 것이고, 새로 계산한 결론이 아닙니다. 쉬운 말로 바꾼 설명이며, 쉬워졌다고 더 확실해진 것은 아닙니다. 칸마다 「이 칸 읽는 법」 을 펼쳐 보세요.</p>`
    + `<p class="sd-market" data-hub-market>${esc(marketLine)}</p>${actions}`
    + `<div class="sd-modal-chart">${chart || `<p class="sd-why">이 종목은 수집 일봉이 없어 차트를 그리지 못합니다.</p>`}</div>`
    + `<div class="sd-modal-ev">${sections}</div>${tpl}</div>`
    + `<footer class="sd-bottom"><p class="sd-notice">${esc(hub.notice || "투자 권유가 아닙니다.")}</p></footer>`;
}

/** 서랍 안쪽 전체 — hub 는 GET /api/stock-hub 응답 그대로 */
export function stockDrawerHtml(hub) {
  const s = hub.sections || {};
  const labelOf = new Map((hub.links || []).map(l => [l.view, l.label]));
  const identity = s.identity?.data || {};
  const name = hub.name || identity.name || hub.symbol;
  const market = SD_MARKETS[hub.market || identity.market] || hub.market || "";
  const price = s.price;
  const naver = hubNaverUrl(hub.symbol);
  const head = `<header class="sd-top"><div><strong id="hub-dr-title">${esc(name)}</strong> <span class="sd-chip">${esc(hub.symbol)}</span>`
    + `${market ? ` <span class="sd-chip">${esc(market)}</span>` : ""}`
    + `${sdOk(price) ? ` <span class="sd-top-price">${esc(sdNum(price.data.close))}원 <b class="${price.data.change_pct > 0 ? "up" : price.data.change_pct < 0 ? "dn" : ""}">${esc(sdPct(price.data.change_pct))}</b></span>` : ""}`
    + `${naver ? ` <a class="sd-ext" href="${esc(naver)}" target="_blank" rel="noopener noreferrer">Npay 증권에서 보기 ↗</a>` : ""}</div>`
    + `<button type="button" class="sd-close" data-hub-close aria-label="서랍 닫기">✕</button></header>`;
  const sections = DRAWER_SECTIONS.map(k => sdSectionHtml(k, s[k], labelOf)).join("");
  const generated = hub.generated_at ? `<small class="sd-note">${esc(String(hub.generated_at).slice(0, 16).replace("T", " "))} 에 모았습니다</small>` : "";
  return `${head}<p class="sd-lead">${esc(hub.note || "새로 계산하지 않고 앱의 다른 화면이 쓰는 값을 그대로 모았습니다.")}</p>`
    + `${naver ? '<p class="sd-lead"><button type="button" class="btn-secondary" data-hub-go="robo-rebalance">리밸런싱 목표 편집으로 →</button> 종목코드만 전달합니다. 비중 입력·목표 추가·저장은 직접 확인하세요.</p>' : ''}`
    + `${naver ? '<p class="sd-lead"><button type="button" class="btn-secondary" data-hub-go="paper-stock">PAPER 모의주문으로 →</button> PAPER 계좌 기준으로 수량을 다시 계산하고 직접 확인하세요.</p>' : ''}`
    + `<div class="sd-body">${sections}</div><footer class="sd-bottom"><p class="sd-notice">${esc(hub.notice || "투자 권유가 아닙니다.")}</p>${generated}</footer>`;
}

/** 서랍 전체 + 일봉 차트 칸 — 칸이 있으면 본문(`sd-body`) 바로 위에 끼운다(2026-11-02 · stockDrawerHtml 의 줄을 건드리지 않아 다른 PR 의 한 줄 끼우기와 겹치지 않는다) */
export function stockDrawerWithChartHtml(hub) {
  const html = stockDrawerHtml(hub);
  const box = sdChartBoxHtml(hub.symbol);
  return box ? html.replace('<div class="sd-body">', box + '<div class="sd-body">') : html;
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
  else if (view === "paper-stock") fill("ps-symbol", el => {
    const quantity = byId("ps-qty");
    if (quantity) quantity.value = "";
    byId("ps-risk-calc")?.click();
    byId("ps-quote-btn")?.click();
    el.focus();
  });
  else if (view === "robo-rebalance" && /^[0-9A-Z]{6}$/.test(String(code))) {
    fill("rb-add-symbol");
    const weight = byId("rb-add-weight");
    if (weight) { weight.value = ""; weight.focus(); }
  }
}

/** 문서에 붙인다 — `[data-hub-open="코드"]` 단추(+ data-hub-name)가 서랍을 연다. deps: { api, navigate, openResearchSymbol } */
export function mountStockDrawer(doc, deps) {
  let host = null;
  let last = null;            // 서랍을 연 단추 — 닫으면 초점을 돌려준다
  let token = 0;              // 늦게 온 응답이 새로 연 서랍을 덮지 않게
  let hubLast = null;         // 서랍에 그린 마지막 응답 — 「크게 보기」 가 그대로 쓴다(다시 묻지 않는다)
  let drawerChart = null;     // 서랍 · 모달의 일봉 차트(같은 부품 stockchart.js)
  let modal = null, modalChart = null;
  const makeChart = (box, note) => (deps.mountChart || ((b, n) => mountDailyChart(doc, b, n, { api: deps.api })))(box, note);

  /** root 안의 차트 칸에 일봉을 그린다 — 칸이 없으면(해외 종목) null */
  function startChart(root, symbol, period) {
    const box = root.querySelector("[data-hub-chart]"), note = root.querySelector("[data-hub-chart-note]");
    if (!box || !note) return null;
    const c = makeChart(box, note);
    c.draw({ symbol, period: period || SC_DEFAULT_PERIOD });
    return c;
  }
  /** 기간 단추 — 눌린 표시를 옮기고 같은 root 의 차트를 다시 그린다 */
  function pickPeriod(root, btn, symbol, chart) {
    root.querySelectorAll("[data-hub-period]").forEach(b => b.classList.toggle("on", b === btn));
    if (chart) chart.draw({ symbol, period: btn.dataset.hubPeriod });
  }

  function ensureModal() {
    if (modal) return modal;
    modal = doc.createElement("div");
    modal.id = "hub-modal";
    modal.className = "sd-modal";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.setAttribute("aria-labelledby", "hub-md-title");
    modal.hidden = true;
    doc.body.appendChild(modal);
    modal.addEventListener("click", ev => {
      if (ev.target === modal || ev.target.closest("[data-hub-modal-close]")) { closeModal(); return; }
      const per = ev.target.closest("[data-hub-period]");
      if (per) { pickPeriod(modal, per, modal.dataset.symbol, modalChart); return; }
      const cp = ev.target.closest("[data-hub-copy]");
      if (cp) { copyPlainText(modal.querySelector("[data-hub-tpl]")?.textContent || "", modal.querySelector("[data-hub-copied]")); return; }
      const go = ev.target.closest("[data-hub-go]");
      if (go) {
        const { symbol, name } = modal.dataset;
        closeModal(false);
        openViewForSymbol(go.dataset.hubGo, symbol, name, { navigate: deps.navigate, openResearchSymbol: deps.openResearchSymbol, doc });
      }
    });
    return modal;
  }
  /** 글 복사 — 클립보드 API 가 막히면 임시 입력 칸으로. 결과를 말로 알린다 */
  async function copyPlainText(text, noteEl) {
    const say = msg => { if (noteEl) noteEl.textContent = msg; };
    try {
      await doc.defaultView.navigator.clipboard.writeText(text);
      say("복사했습니다.");
    } catch {
      try {
        const ta = doc.createElement("textarea");
        ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
        doc.body.appendChild(ta); ta.select();
        const ok = doc.execCommand("copy");
        ta.remove();
        say(ok ? "복사했습니다." : "복사하지 못했습니다 — 글을 직접 선택해 복사하세요.");
      } catch { say("복사하지 못했습니다 — 글을 직접 선택해 복사하세요."); }
    }
  }
  /** 시장 맥락 한 줄 — 수집 DB 지수 일봉(코스피 · 코스닥) 마지막 두 종가. 모달을 먼저 그리고 늦게 채운다(실패하면 까닭을 말함) */
  async function fillMarketLine(m, hub, seq) {
    const from = new Date(Date.now() - 14 * 86400000).toISOString().slice(0, 10);
    const one = name => deps.api(`/api/data/ohlcv?symbol=${encodeURIComponent(`${name.series}:${name.name}`)}&timeframe=1d&basis=raw&from=${from}`)
      .then(r => planIndexMove(name.name, r && r.rows));
    const res = await Promise.allSettled([one({ series: "KOSPI", name: "코스피" }), one({ series: "KOSDAQ", name: "코스닥" })]);
    if (seq !== modalSeq || m.hidden) return;                              // 그 사이 다른 종목을 열었다
    const items = res.filter(x => x.status === "fulfilled").map(x => x.value);
    const line = planMarketLine(items, res.every(x => x.status === "rejected"));
    const slot = m.querySelector("[data-hub-market]"), tplEl = m.querySelector("[data-hub-tpl]");
    if (slot) slot.textContent = line;
    if (tplEl) tplEl.textContent = planNoteText(hub, line);
  }
  let modalSeq = 0;
  function openModal(hub) {
    const m = ensureModal();
    m.dataset.symbol = hub.symbol;
    m.dataset.name = hub.name || "";
    m.innerHTML = sdModalHtml(hub);
    m.hidden = false;
    doc.body.classList.add("sd-open");
    if (modalChart) modalChart.destroy();
    modalChart = startChart(m, hub.symbol);
    m.querySelector("[data-hub-modal-close]")?.focus();
    fillMarketLine(m, hub, ++modalSeq);
  }
  /** 서랍을 거치지 않고 바로 모달 — `data-hub-mode="modal"` 입구(모의주문 시세 조회 결과) */
  async function openModalFor(symbol, name, trigger) {
    last = trigger || null;
    const mine = ++token;
    const m = ensureModal();
    m.dataset.symbol = symbol;
    m.dataset.name = name || "";
    m.hidden = false;
    doc.body.classList.add("sd-open");
    if (modalChart) { modalChart.destroy(); modalChart = null; }
    m.innerHTML = `<header class="sd-top"><strong id="hub-md-title">${esc(name || symbol)}</strong>`
      + `<button type="button" class="sd-close" data-hub-modal-close aria-label="크게 보기 닫기">✕</button></header><p class="sd-lead" role="status">근거를 모으는 중입니다…</p>`;
    m.querySelector("[data-hub-modal-close]")?.focus();
    try {
      const hub = await deps.api(hubDrawerPath(symbol));
      if (mine !== token || m.hidden) return;
      hubLast = hub;
      openModal(hub);
    } catch (err) {
      if (mine !== token) return;
      m.innerHTML = `<header class="sd-top"><strong id="hub-md-title">${esc(name || symbol)}</strong>`
        + `<button type="button" class="sd-close" data-hub-modal-close aria-label="크게 보기 닫기">✕</button></header><p class="sd-why" role="alert">${esc(sdFailText(err))}</p>`;
      m.querySelector("[data-hub-modal-close]")?.focus();
    }
  }
  function closeModal(restoreFocus = true) {
    token += 1;
    if (modalChart) { modalChart.destroy(); modalChart = null; }
    if (modal) modal.hidden = true;
    doc.body.classList.remove("sd-open");
    if (restoreFocus && last && doc.contains(last)) last.focus();
  }

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
      if (ev.target.closest("[data-hub-expand]")) {                 // 크게 보기 — 서랍은 닫고 같은 종목 · 같은 기간으로 모달
        if (hubLast) { const hub = hubLast; close(false); openModal(hub); }
        return;
      }
      const per = ev.target.closest("[data-hub-period]");
      if (per) { pickPeriod(host, per, host.dataset.symbol, drawerChart); return; }
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
    if (drawerChart) { drawerChart.destroy(); drawerChart = null; }
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
      h.innerHTML = stockDrawerWithChartHtml(hub);
      hubLast = hub;
      if (drawerChart) drawerChart.destroy();
      drawerChart = startChart(h, hub.symbol);
      h.querySelector("[data-hub-close]")?.focus();
    } catch (err) {
      if (mine !== token) return;
      h.innerHTML = `<header class="sd-top"><strong id="hub-dr-title">${esc(name || symbol)}</strong>`
        + `<button type="button" class="sd-close" data-hub-close aria-label="서랍 닫기">✕</button></header><p class="sd-why" role="alert">${esc(sdFailText(err))}</p>`;
      h.querySelector("[data-hub-close]")?.focus();
    }
  }

  doc.addEventListener("click", ev => {
    const paper = ev.target.closest?.("[data-paper-open]");
    if (paper) {
      ev.preventDefault();
      openViewForSymbol("paper-stock", paper.dataset.paperOpen, paper.dataset.hubName || "", {
        navigate: deps.navigate, openResearchSymbol: deps.openResearchSymbol, doc,
      });
      close(false);
      closeModal(false);
      return;
    }
    const btn = ev.target.closest?.("[data-hub-open]");
    if (!btn) return;
    ev.preventDefault();
    if (!String(btn.dataset.hubOpen || "").trim()) return;          // 종목 코드가 아직 없는 입구(시세 조회 전)는 열지 않는다 — 빈 코드로 부르면 422
    // 입구는 모두 큰 모달 직행(사용자 11-02 「처음부터 모달로 크게」) — 서랍이 필요한 입구만 `data-hub-mode="drawer"` 를 단다. 팀 파일의 단추 줄은 건드리지 않는다
    if (btn.dataset.hubMode !== "drawer") openModalFor(btn.dataset.hubOpen, btn.dataset.hubName || "", btn);
    else open(btn.dataset.hubOpen, btn.dataset.hubName || "", btn);
  });
  doc.addEventListener("keydown", ev => {
    if (ev.key !== "Escape") return;
    if (modal && !modal.hidden) closeModal();
    else if (host && !host.hidden) close();
  });
  doc.defaultView.addEventListener("hashchange", () => {            // 다른 화면으로 가면 닫는다
    if (host && !host.hidden) close(false);
    if (modal && !modal.hidden) closeModal(false);
  });
  return { open, close };
}
