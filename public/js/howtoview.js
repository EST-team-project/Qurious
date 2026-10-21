/* 화면 사용법 — 창 크기 · 이어 줄 개념 학습 장 · 그릴 HTML 을 정하는 곳(2026-10-16)
 *
 * 결정(Figma 「투자 대시보드 · 메뉴 정리」 05 결정 기록 ④ ~ ⑧ · 설계 docs/2차/화면/설계안/2026-10-16-사용법모달/설계안.md):
 *   ④ 담는 틀 = 가운데 창 — 차트 · 시각 자료를 넣을 자리 · 상품 상세 창과 같은 꼴(창은 js/howto.js 가 연다)
 *   ⑤ 단추 = 화면 맨 위 윗줄(지금 위치 + 「사용법」) ⑥ 영상이 없으면 칸을 숨긴다
 *   ⑦ 창 크기는 화면마다(sizeOf) ⑧ 끝줄 = 그 화면의 개념 학습 장 + 용어사전 + 학습 홈
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

// 화면 → 영상 — 영상 표(videos.json)는 git · 이미지 밖 로컬 폴더(data/help/)에 있다(D132 · 2026-10-18).
// tools/demo/help_videos.py 가 녹화 기록의 단계 시각 · 화면 키와 장 파일을 맞대어 만들고, 앱은 로그인한 사람에게 /help/ 로 낸다.
// 표를 못 받았거나(영상을 받지 않은 PC) 그 화면 줄이 없거나 꼴이 틀리면 videoOf 가 null → 영상 칸 · 윗줄 「▶ 영상」 을 숨긴다(결정 ⑥).
export const VIDEO_MANIFEST_URL = "/help/videos.json";
export const VIDEO_FORMAT = 1;
// 우리 폴더의 파일 주소만 받는다 — 바깥 주소 · 경로 오르기 · 다른 꼴은 표에 있어도 쓰지 않는다
const HELP_MEDIA_URL = /^\/help\/media\/[A-Za-z0-9%._~-]+(\?v=[0-9a-f]{6,64})?$/;
const CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳";

// 창 바닥 고지 한 줄(10-1 시안 ④) — 영상 · 사용법 모두 기능 안내이지 투자 권유가 아니다
export const HOWTO_NOTE = "투자 권유가 아닙니다 · 투자 판단과 결과는 이용자 몫입니다";

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

/** 초 → 「분:초」(1:03) — 영상 길이 · 장 시작 시각. 브라우저 재생 막대처럼 내림(30.6초 → 0:30). */
export function fmtTime(sec) {
  const s = Math.max(0, Math.floor(Number(sec) || 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function helpUrl(u) {
  return typeof u === "string" && HELP_MEDIA_URL.test(u) && !u.includes("..") ? u : "";
}

/** 영상 표의 한 편 — 편 이름(표의 videos 키)과 시작 장으로 { src, captions, chaptersSrc, chapters[{title, start, end, poster}],
 *  startChapter, start, poster, duration, durationSec }. 화면 영상(videoOf)과 사용법 영상 목록(helpvideosview.js)이 같은 꼴을 쓴다.
 *  표 · 편이 없거나 꼴이 틀리면 null. */
export function videoById(id, manifest, chapter = 0) {
  if (!manifest || manifest.format !== VIDEO_FORMAT) return null;
  const v = manifest.videos?.[id];
  const src = helpUrl(v?.src);
  if (!src || !Array.isArray(v.chapters) || !v.chapters.length) return null;
  const chapters = v.chapters.map((c) => ({
    title: String(c?.title ?? ""),
    start: Math.max(0, Number(c?.start) || 0),
    end: Math.max(0, Number(c?.end) || 0),
    poster: helpUrl(c?.poster),
  }));
  const k = Math.min(Math.max(0, Math.trunc(Number(chapter) || 0)), chapters.length - 1);
  const durationSec = Number(v.duration) || chapters[chapters.length - 1].end;
  return {
    src,
    captions: helpUrl(v.captions),
    chaptersSrc: helpUrl(v.chapters_src),
    chapters,
    startChapter: k,
    start: chapters[k].start,
    poster: chapters[k].poster,
    durationSec,
    duration: fmtTime(durationSec),
  };
}

/** 영상 표에서 한 화면의 영상 — videoById 와 같은 꼴.
 *  여러 화면에 걸친 영상은 그 화면이 처음 나오는 장부터(D132 · 차트 패턴 = ② 0:15). 표 · 줄이 없거나 꼴이 틀리면 null. */
export function videoOf(viewKey, manifest) {
  if (!manifest || manifest.format !== VIDEO_FORMAT) return null;
  const ref = manifest.views?.[viewKey];
  return ref ? videoById(ref.video, manifest, ref.chapter) : null;
}

/** 재생 시각이 든 장 차례 — 장 시작이 지금보다 늦지 않은 마지막 장(장 사이 틈은 앞 장). */
export function chapterIndexAt(chapters, t) {
  let k = 0;
  (chapters || []).forEach((c, i) => { if (c.start <= Number(t) + 0.05) k = i; });
  return k;
}

/** 영상 왼쪽 위 장 표시 「② / 3」. */
export function chapterBadge(k, n) {
  return `${CIRCLED[k] || String(k + 1)} / ${n}`;
}

/** 「영상으로 보기」 를 누른 뒤의 칸 — 영상(그 화면의 장부터) + 장 단추(지금 장은 파랑 · Tab 으로 닿음).
 *  자막은 영상에 들어 있어 자막 트랙은 켜지 않는다(켜면 같은 글이 두 줄로 겹친다 · 브라우저 CC 단추로 켤 수 있음). */
export function playerHtml(video) {
  const n = video.chapters.length;
  const k = video.startChapter;
  const at = video.start > 0 ? `#t=${video.start}` : "";
  const tracks = (video.captions ? `<track kind="captions" srclang="ko" label="한국어" src="${esc(video.captions)}">` : "")
    + (video.chaptersSrc ? `<track kind="chapters" srclang="ko" label="장" src="${esc(video.chaptersSrc)}">` : "");
  const chaps = video.chapters.map((c, i) => `<button type="button" class="q-howto-chap" data-howto-chap="${i}"${i === k ? ' aria-current="true"' : ""}>`
    + `<i class="fa-regular fa-clock" aria-hidden="true"></i><b>${esc(c.title)}</b><small>${fmtTime(c.start)}</small></button>`).join("");
  return `<div class="q-howto-stage"><video class="q-howto-player" controls preload="metadata" playsinline`
    + `${video.poster ? ` poster="${esc(video.poster)}"` : ""} src="${esc(video.src + at)}">${tracks}</video>`
    + `<span class="q-howto-chapbadge" aria-hidden="true">${chapterBadge(k, n)}</span></div>`
    + `<div class="q-howto-chaps" role="group" aria-label="장으로 가기">${chaps}</div>`;
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
    learn ? `<a class="q-howto-link" href="#learn/${esc(learn.slug)}" data-howto="leave">개념 학습 「${esc(learn.title)}」 →</a>` : "",
    viewKey !== "fin-glossary" ? `<a class="q-howto-link" href="#fin-glossary" data-howto="leave">용어사전에서 더 찾기 →</a>` : "",
    `<a class="q-howto-link" href="#learn-home" data-howto="leave">학습 홈 →</a>`,   // 2026-10-20 학습 한 묶음 — 목차 대신 학습 홈
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
      <p class="q-howto-note">${esc(HOWTO_NOTE)}</p>
    </div><div class="q-howto-termview" hidden></div></div>`;
}
