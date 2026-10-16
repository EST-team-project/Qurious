/* 화면 사용법 — 창 크기 · 이어 줄 개념 학습 장 · 그릴 HTML 을 정하는 곳(2026-10-16)
 *
 * 결정(Figma 「투자 대시보드 · 메뉴 정리」 05 결정 기록 ④ ~ ⑧ · 설계 docs/화면/설계안/2026-10-16-사용법모달/설계안.md):
 *   ④ 담는 틀 = 가운데 창 — 차트 · 시각 자료를 넣을 자리 · 상품 상세 창과 같은 꼴(창은 js/howto.js 가 연다)
 *   ⑤ 단추 = 화면 맨 위 윗줄(지금 위치 + 「사용법」) ⑥ 영상이 없으면 칸을 숨긴다
 *   ⑦ 창 크기는 화면마다(sizeOf) ⑧ 끝줄 = 그 화면의 개념 학습 장 + 용어사전 + 개념 학습 목차
 *
 * 이 파일은 아무것도 가져오지 않는다(DOM · 서버 없음) — 시험이 node 로 그대로 불러 돌린다(TC-HT).
 * 사용법 글(VIEW_GUIDES) · 용어(TERMS) · 메뉴 이름은 core.js 가 넘긴다 — 여기에 따로 적지 않는다.
 */

// 창 폭(px) — 「작게 · 보통 · 크게」. 높이는 내용만큼(최대 화면 − 48) · 760 아래는 화면 전체(howto.css).
export const SIZE_PX = Object.freeze({ s: 560, m: 680, l: 840 });

// 차트 · 분석 화면 — 사용법에 차트 · 시각 자료가 들어갈 자리라 글이 짧아도 「크게」(결정 ④ 의 까닭).
export const WIDE_VIEWS = new Set([
  "trading-chart", "us-chart", "robo-patterns", "indicator-tradingview", "invest-technical",
  "quant-backtest", "indicator-backtest", "quant-lean", "ml-compare", "ml-cluster", "quant-seasonal",
  "macro-dashboard", "company-compare", "robo-portfolio", "robo-rebalance", "data-status", "data-guide",
]);

// 글 양 문턱 — 요약 + 단계 글 자수 + 용어 하나당 10. 이 아래면 「작게」 · 그다음 「보통」 · 그 위 「크게」.
export const SIZE_LIMITS = Object.freeze({ s: 120, m: 260 });

// 화면 → 개념 학습 장(public/learn/content/<slug>.md · 제목은 머리말 title 의 「 — 」 앞) — 없는 화면은 목차만.
// 장 제목이 바뀌면 시험(TC-HT-08)이 이 표와 머리말을 맞대어 잡는다.
export const LEARN_OF = Object.freeze({
  "agent-chat":            { slug: "rag-basics", title: "RAG" },
  "robo-portfolio":        { slug: "investor-profile-suitability", title: "투자 성향과 적합성" },
  "robo-testbed":          { slug: "robo-advisor-rules", title: "로보어드바이저와 법" },
  "agent-products":        { slug: "funds-etf", title: "펀드와 ETF" },
  "agent-news":            { slug: "prompt-citation", title: "프롬프트와 출처 표기" },
  "robo-rebalance":        { slug: "asset-allocation-quant", title: "자산배분과 퀀트" },
  "robo-patterns":         { slug: "ohlcv-bars", title: "봉과 OHLCV" },
  "data-status":           { slug: "data-quality-check", title: "데이터 품질 검사" },
  "data-guide":            { slug: "data-layers", title: "원문 · 정제 · 파생" },
  "crawl-auto":            { slug: "batch-scheduling", title: "정기 배치" },
  "crawl-manual":          { slug: "public-api-basics", title: "공식 API 다루기" },
  "crawl-ingest":          { slug: "dataset-versioning-hf", title: "데이터셋 판과 공유" },
  "market-calendar":       { slug: "trading-calendar", title: "거래일 달력과 금융 일정" },
  "trading-chart":         { slug: "ohlcv-bars", title: "봉과 OHLCV" },
  "trading-order":         { slug: "stock-basics", title: "주식 · 시장 · 주문의 기본" },
  "paper-stock":           { slug: "stock-basics", title: "주식 · 시장 · 주문의 기본" },
  "paper-crypto":          { slug: "bonds-crypto", title: "채권과 코인" },
  "paper-alternative":     { slug: "derivatives-futures-options", title: "선물과 옵션" },
  "paper-openapi":         { slug: "public-api-basics", title: "공식 API 다루기" },
  "settings":              { slug: "public-api-basics", title: "공식 API 다루기" },
  "indicator-api":         { slug: "public-api-basics", title: "공식 API 다루기" },
  "us-chart":              { slug: "intraday-timezone", title: "분봉과 시간대" },
  "us-order":              { slug: "stock-basics", title: "주식 · 시장 · 주문의 기본" },
  "indicator-strategy":    { slug: "pine-script-basics", title: "Pine Script 기초" },
  "indicator-tradingview": { slug: "tradingview-webhook", title: "TradingView 경보를 서버로 받기" },
  "indicator-formula":     { slug: "pine-script-basics", title: "Pine Script 기초" },
  "indicator-custom":      { slug: "pine-script-basics", title: "Pine Script 기초" },
  "invest-technical":      { slug: "ohlcv-bars", title: "봉과 OHLCV" },
  "fin-products":          { slug: "funds-etf", title: "펀드와 ETF" },
  "fin-allocation":        { slug: "asset-allocation-quant", title: "자산배분과 퀀트" },
  "fin-topic-futures":     { slug: "derivatives-futures-options", title: "선물과 옵션" },
  "fin-topic-funds":       { slug: "funds-etf", title: "펀드와 ETF" },
  "fin-topic-bonds":       { slug: "bonds-crypto", title: "채권과 코인" },
  "fin-topic-allocation":  { slug: "asset-allocation-quant", title: "자산배분과 퀀트" },
  "fin-topic-stocks":      { slug: "stock-basics", title: "주식 · 시장 · 주문의 기본" },
  "fin-topic-technical":   { slug: "ohlcv-bars", title: "봉과 OHLCV" },
  "fin-glossary":          { slug: "thesaurus-skos", title: "용어 사전과 시소러스" },
  "sysadmin-dashboard":    { slug: "docker-compose-dev", title: "Docker Compose 와 개발 모드" },
});

// 화면 → 영상 { src, captions, duration } — 시연 녹화 묶음(D82 · 단계 파일 → 녹화 → git 밖 보관)에서 채운다.
// 지금은 비어 있어 모든 화면에서 영상 칸 · 윗줄 「▶ 영상」 이 숨는다(결정 ⑥).
export const VIDEOS = Object.freeze({});

// common.js 의 escHtml 과 같은 규칙(& < > " ') — node 시험에서 불러 쓰려고 가져오지 않는다(시험이 둘을 맞댄다).
export function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/** 글 양 = 요약 + 단계 글 자수 + 용어 하나당 10(칩 한 줄이 차지하는 자리). */
export function textAmount(guide) {
  if (!guide) return 0;
  const steps = (guide.steps || []).reduce((a, s) => a + String(s).length, 0);
  return String(guide.summary || "").length + steps + 10 * (guide.relatedTerms || []).length;
}

/** 화면의 창 크기 "s" | "m" | "l" — 차트 · 분석 화면이나 영상이 있으면 「크게」, 아니면 글 양으로. */
export function sizeOf(viewKey, guide, { video = null } = {}) {
  if (WIDE_VIEWS.has(viewKey) || video) return "l";
  const n = textAmount(guide);
  if (n < SIZE_LIMITS.s) return "s";
  if (n < SIZE_LIMITS.m) return "m";
  return "l";
}

/** 화면에 이어 줄 개념 학습 장 { slug, title } — 없으면 null(끝줄은 목차만). */
export function learnOf(viewKey) {
  return LEARN_OF[viewKey] || null;
}

/** 윗줄 — 왼쪽 지금 위치(묶음 › 화면) · 오른쪽 「▶ 영상」(있을 때만) · 「사용법」. */
export function topRowHtml(viewKey, { group = "", label = "", video = null } = {}) {
  const path = `${group ? `<span class="q-howto-path-group">${esc(group)}</span><i class="fa-solid fa-chevron-right" aria-hidden="true"></i>` : ""}`
    + `<span class="q-howto-path-here" aria-current="page">${esc(label || viewKey)}</span>`;
  const videoBtn = video
    ? `<button type="button" class="q-howto-btn q-howto-btn--video" data-howto-open="video" aria-haspopup="dialog" aria-controls="q-howto-dialog">`
      + `<i class="fa-solid fa-play" aria-hidden="true"></i><span>영상 ${esc(video.duration || "")}</span></button>`
    : "";
  return `<nav class="q-howto-path" aria-label="지금 위치">${path}</nav>
    <div class="q-howto-actions">${videoBtn}<button type="button" class="q-howto-btn" data-howto-open="guide" aria-haspopup="dialog" aria-controls="q-howto-dialog">`
    + `<i class="fa-solid fa-circle-question" aria-hidden="true"></i><span>사용법</span></button></div>`;
}

function videoHtml(viewKey, video) {
  return `<div class="q-howto-video"><button type="button" class="q-howto-video-btn" data-howto-video="${esc(viewKey)}">
      <span class="q-howto-play" aria-hidden="true"><i class="fa-solid fa-play"></i></span>
      <span><b>영상으로 보기</b><small>${esc(video.duration || "")}${video.captions ? " · 한국어 자막" : ""}</small></span></button></div>`;
}

/** 창 안 — 머리(사용법 · 화면 이름 · 닫기) → 요약 → 영상 칸(있을 때만) → 이렇게 써요 → 이 화면의 용어 → 끝줄. */
export function howtoHtml(viewKey, guide, { terms = {}, label = "", video = null } = {}) {
  const chips = (guide.relatedTerms || []).filter((k) => terms[k]);
  const learn = learnOf(viewKey);
  const foot = [
    learn ? `<a class="q-howto-link" href="/learn/#/p/${esc(learn.slug)}" target="_blank" rel="noopener">개념 학습 「${esc(learn.title)}」 →</a>` : "",
    viewKey !== "fin-glossary" ? `<a class="q-howto-link" href="#fin-glossary" data-howto="leave">용어사전에서 더 찾기 →</a>` : "",
    `<a class="q-howto-link" href="/learn/#/" target="_blank" rel="noopener">개념 학습 목차 →</a>`,
  ].filter(Boolean).join("");
  return `<header class="q-howto-head"><div class="q-howto-head-txt">
      <p class="q-howto-kicker"><i class="fa-solid fa-circle-question" aria-hidden="true"></i> 사용법</p>
      <h2 id="q-howto-title" tabindex="-1">${esc(label || "이 화면")}</h2></div>
      <button type="button" class="q-howto-close" data-howto="close" aria-label="사용법 닫기">닫기 <i class="fa-solid fa-xmark" aria-hidden="true"></i></button></header>
    <div class="q-howto-body"><div class="q-howto-guide">
      <p class="q-howto-summary">${esc(guide.summary)}</p>
      ${video ? videoHtml(viewKey, video) : ""}
      <h3 class="q-howto-h">이렇게 써요</h3>
      <ol class="q-howto-steps">${(guide.steps || []).map((s, i) => `<li><span class="q-howto-n" aria-hidden="true">${i + 1}</span><span>${esc(s)}</span></li>`).join("")}</ol>
      ${chips.length ? `<h3 class="q-howto-h">이 화면의 용어</h3><div class="q-howto-terms">${chips.map((k) => `<button type="button" class="term-chip q-howto-term" data-howto-term="${esc(k)}">${esc(terms[k].title || k)} <i class="fa-solid fa-circle-info" aria-hidden="true"></i></button>`).join("")}</div>` : ""}
      <div class="q-howto-foot">${foot}</div>
    </div><div class="q-howto-termview" hidden></div></div>`;
}
