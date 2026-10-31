/* AI 투자 상담 — 답 위 앱 판단 카드 그리기 (DOM 없는 판단 모듈 · 2026-10-17 · 모의투자 점검 L2)
 *
 * 결정(Figma 「AI 투자 상담 — 근거 답과 출처」 03-2 [결정] 설계 A): 질문에 종목 이름이 그대로 있으면 AI 답보다 먼저, 우리 앱이 그 종목에
 * 대해 이미 아는 것을 카드 한 장으로 보인다 — 종목 허브 묶음(GET /api/stock-hub)의 마지막 종가 · 다중 주기 신호 · 재무 건전성 · 최근 공시.
 *   · 값 · 기준일 · 까닭 · 고지는 서버 글 그대로 옮긴다 — 새로 계산하지 않고 칸을 합친 한 줄 결론도 만들지 않는다(허브 note).
 *     카드 값은 서버 묶음 그대로라 AI 가 숫자를 바꿀 수 없다(DF-124 와 같은 뜻 — 답 옆에 서버 값).
 *   · 머리 「질문의 ○○ 을 종목으로 읽었습니다」 — 무엇을 종목으로 읽었는지 밝혀, 흔한 낱말과 같은 이름을 잘못 읽어도 사용자가 안다.
 *   · 다른 화면으로 — 결정의 다섯(차트 패턴 · 스크리닝 · 재무 · 신용 위험 · 공시 · 기사 시간표 · 모의 주문) · 이름은 서버 links 글.
 *   · 칸이 비거나 「준비 중」 · 오류면 값을 지어내지 않고 서버 까닭을 보인다.
 * kbchat.js 가 부르고 단추를 잇는다 — 이 파일은 글만 만든다(Node 로 시험 — tests/test_chat_stock_card.py TC-SCC).
 */
// DOM 없는 글자 막기는 한 곳(common.js escHtml 과 시험으로 맞댐 — TC-HT). 상대 경로 — 브라우저(/js/)와 Node 시험(파일 자리)이
// 같은 파일을 읽게(절대 경로 「/js/…」 는 Node 에서 디스크 뿌리로 풀린다).
import { esc } from "./howtoview.js";

/** 카드가 허브에서 받는 칸 — 주소의 sections(서버 stock_hub.SECTIONS 안 · 시험이 맞댐) */
export const STOCK_CARD_SECTIONS = ["price", "signal", "financials", "disclosures"];
/** 다른 화면으로 — 결정 A 의 다섯 · 이 차례(이름은 서버 links 의 글을 쓴다 · 서버에 없는 화면은 그리지 않는다) */
export const STOCK_CARD_VIEWS = ["robo-patterns", "robo-screening", "agent-cb", "agent-news", "paper-stock"];
const MARKETS = { KOSPI: "코스피", KOSDAQ: "코스닥", KONEX: "코넥스", ETF: "ETF" };
const MINUS = "−";                     // 등락의 빼기 — 하이픈(-)과 헷갈리지 않게 수학 기호

/** 그 종목 카드에 쓸 허브 주소 */
export function stockHubPath(symbol) {
  return `/api/stock-hub?symbol=${encodeURIComponent(symbol)}&sections=${STOCK_CARD_SECTIONS.join(",")}`;
}

/** 마지막 글자 받침에 따라 을 · 를(한글이 아니면 「을(를)」) */
function objectJosa(word) {
  const ch = String(word || "").trim().slice(-1);
  const code = ch.charCodeAt(0) - 0xac00;
  if (!(code >= 0 && code < 11172)) return "을(를)";
  return code % 28 ? "을" : "를";
}

function cardNum(v, digits = 0) {
  return Number(v).toLocaleString("ko-KR", { maximumFractionDigits: digits });
}

function cardPct(v) {
  const n = Number(v);
  const s = Math.abs(n).toFixed(2);
  return `${n > 0 ? "+" : n < 0 ? MINUS : ""}${s}%`;
}

function cardSafeUrl(u) { return /^https?:\/\//i.test(u || "") ? u : ""; }

/** 「2026-10-15」 → 「10월 15일」 */
function cardMonthDay(day) {
  const m = String(day || "").match(/^\d{4}-(\d{2})-(\d{2})/);
  return m ? `${Number(m[1])}월 ${Number(m[2])}일` : "";
}

function cardOk(sec) { return sec && sec.status === "ok"; }

/** 칸 한 줄 — 머리(이름 · 칩 · 오른쪽 글) + 본문 · 서버가 값을 못 준 칸은 그 까닭 */
function cardRowHtml(sec, label, { chip = "", right = "", body = "" } = {}) {
  if (!cardOk(sec)) {
    const why = sec?.reason || "이 칸의 자료가 없습니다.";
    return `<div class="kb-sc-row kb-sc-row--empty"><div class="kb-sc-rowhead"><span class="kb-sc-label">${esc(label)}</span></div>
      <p class="kb-sc-why">${esc(why)}</p></div>`;
  }
  return `<div class="kb-sc-row"><div class="kb-sc-rowhead"><span class="kb-sc-label">${esc(label)}</span>${chip ? `<span class="kb-sc-chip">${esc(chip)}</span>` : ""}
      ${right ? `<span class="kb-sc-right">${esc(right)}</span>` : ""}</div>${body}</div>`;
}

function cardSignalRow(sec) {
  const d = sec?.data || {};
  const side = d.signal ? `${d.signal}${d.signal === "관망" ? "" : " 쪽"}` : "";
  const chip = [side, d.strength].filter(Boolean).join(" · ");
  return cardRowHtml(sec, sec?.label || "다중 주기 신호", { chip, right: cardMonthDay(sec?.as_of) ? `${cardMonthDay(sec.as_of)} 기록` : "",
    body: d.summary ? `<p class="kb-sc-text">${esc(d.summary)}</p>` : "" });
}

function cardFinancialsRow(sec) {
  const d = sec?.data || {};
  const s = d.summary || {};
  const chip = [`그렇다 ${s.pass ?? 0}`, s.fail ? `아니다 ${s.fail}` : "", s.unknown ? `모름 ${s.unknown}` : ""].filter(Boolean).join(" · ");
  const latest = d.latest || {};
  const right = latest.report ? `${latest.report}${latest.period_end ? `(${latest.period_end})` : ""}` : "";
  const metrics = (d.metrics || []).map(m => `${m.label} ${m.value == null ? "셀 수 없음" : `${cardNum(m.value, 1)}${m.unit || ""}`}`).join(" · ");
  const body = (metrics ? `<p class="kb-sc-text">${esc(metrics)}</p>` : "")
    + (d.kind_note ? `<p class="kb-sc-note">${esc(d.kind_note)}</p>` : "");
  return cardRowHtml(sec, sec?.label || "재무 건전성", { chip, right, body });
}

function cardDisclosuresRow(sec) {
  const d = sec?.data || {};
  const first = (d.items || [])[0];
  if (cardOk(sec) && !first) return cardRowHtml({ status: "empty", reason: "최근 공시가 없습니다." }, sec.label || "최근 공시");
  const url = cardSafeUrl(first?.url);
  const title = first ? (url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(first.title)}</a>` : esc(first.title)) : "";
  return cardRowHtml(sec, sec?.label || "최근 공시", { chip: String(first?.published || "").slice(5, 10),
    right: d.total ? `전자공시 ${cardNum(d.total)}건 가운데` : "", body: title ? `<p class="kb-sc-text">${title}</p>` : "" });
}

function cardLinksHtml(hub) {
  const byView = new Map((hub.links || []).map(l => [l.view, l.label]));
  const buttons = STOCK_CARD_VIEWS.filter(v => byView.has(v)).map(v =>
    `<button type="button" class="kb-sc-link" data-sc-view="${esc(v)}" data-sc-code="${esc(hub.symbol)}" data-sc-name="${esc(hub.name || "")}">${esc(byView.get(v))} →</button>`);
  return buttons.length ? `<div class="kb-sc-links">${buttons.join("")}</div>` : "";
}

/** 카드 한 장 — hub 는 GET /api/stock-hub 응답 그대로 · mention 은 GET /api/stock-hub/mentions 의 한 줄 */
export function stockCardHtml(hub, mention) {
  const s = hub.sections || {};
  const price = s.price;
  const p = price?.data || {};
  const priceHtml = cardOk(price)
    ? `<span class="kb-sc-price">${esc(cardNum(p.close))}원 <b class="${p.change_pct > 0 ? "up" : p.change_pct < 0 ? "dn" : ""}">${esc(cardPct(p.change_pct))}</b>
       <small>${esc(String(p.trade_date || price.as_of || "").slice(5))} 종가</small></span>` : "";
  const read = mention?.matched || hub.name || hub.symbol;
  return `<section class="kb-sc" aria-label="앱 판단 — ${esc(hub.name || hub.symbol)}">
    <div class="kb-sc-head"><strong>${esc(hub.name || hub.symbol)}</strong><span class="kb-sc-chip">${esc(hub.symbol)}</span>
      <button type="button" class="sd-open-btn" data-hub-open="${esc(hub.symbol)}" data-hub-name="${esc(hub.name || "")}">근거 서랍 →</button>
      ${hub.market ? `<span class="kb-sc-chip">${esc(MARKETS[hub.market] || hub.market)}</span>` : ""}${priceHtml}</div>
    ${price && !cardOk(price) ? `<p class="kb-sc-why">${esc(price.label || "마지막 종가")} — ${esc(price.reason || "이 칸의 자료가 없습니다.")}</p>` : ""}
    <p class="kb-sc-read">질문의 「${esc(read)}」 ${objectJosa(read)} 종목으로 읽었습니다 · 우리 앱 화면마다의 값을 그대로 옮겼습니다(하나로 합친 결론이 아닙니다)</p>
    ${s.signal ? cardSignalRow(s.signal) : ""}${s.financials ? cardFinancialsRow(s.financials) : ""}${s.disclosures ? cardDisclosuresRow(s.disclosures) : ""}
    ${cardLinksHtml(hub)}
    <p class="kb-sc-foot">${esc(hub.notice || "투자 권유가 아닙니다.")}</p>
  </section>`;
}

/** 카드 여럿(서버 최대 둘) — 첫째는 펼치고 둘째부터는 접어 둔다(답이 아래로 너무 밀리지 않게) */
export function stockCardsHtml(cards) {
  return (cards || []).map(({ hub, mention }, i) => {
    const html = stockCardHtml(hub, mention);
    if (i === 0) return html;
    const read = mention?.matched || hub.name || hub.symbol;
    return `<details class="kb-sc-more"><summary>질문의 「${esc(read)}」 도 종목으로 읽었습니다 — 카드 펼치기</summary>${html}</details>`;
  }).join("");
}
