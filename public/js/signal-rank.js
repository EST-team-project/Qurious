/* 신호 기록 순위 화면 — DOM 없이 글 · 표시만 정한다(node 로 시험 · TC-RKS · 2026-10-29 · 할 일 ②-19).
 *
 * 설계: docs/phase-3/02-design/ui/신호순위-화면설계.md (v0.1 · 팀 검토 전 · #373).
 * 사용자가 검토 결정 전에 새 파일부터 시작하라고 해서(10-29) 「검토로 뒤집히지 않는 부분」 만 먼저 둔다.
 *   - 붙는 자리(W6 탭 안 B / 새 화면 안 A)를 모른다 — mountSignalRank 가 host 하나만 받는다. app.html 은 건드리지 않았다.
 *   - 「중립」 의 쉬운 말(설계서 6절 4번)은 NEUTRAL_WORD 한 곳에 둬서 검토 뒤 한 줄로 바꾼다.
 *
 * 규칙(설계서 2 · 3.3 · 8절)
 *   1. 숫자와 설명 문장은 응답에 있는 값만 쓴다 — 화면이 문장을 짓지 않는다(없으면 「모름」 · 줄표).
 *   2. 가격은 두 줄로 종류를 섞지 않는다 — 「종가(MM-DD)」 와 「지금 가격(출처 · 시각)」. 지금 가격을 못 받았다고
 *      종가를 그 칸에 대신 넣지 않는다. 출처 글은 `quote_now.label` 을 그대로 쓴다.
 *   3. 「기록 없음」 은 두 갈래(missing.reason)와 explain 404 를 서버 문장 그대로 보인다.
 *   4. 근거 개수 n = counts.buy + counts.neutral + counts.sell = evidence 줄 수(오준영 님 #373 답 · 코드 대조 일치).
 *      `/api/explain` 의 reasons 는 방향을 지지하는 근거만이라 n 이 아니다(#351 의 reasons 줄 수는 퀀트 카드 응답 얘기).
 *      개수를 못 세면 0개로 두지 않고 안내 문구를 보인다.
 *   5. 신호 기준 종가는 **그 신호 기록의 as_of** 에 맞춘다 — 허브의 마지막 종가가 아니다. 그날 종가가 없으면 「확인 불가」.
 *   6. 줄을 누르면 전용 서랍이 아니라 종목 근거 모달이 열린다(사용자 2026-11-02 · 입구 통일) — 줄(`<tr>`)에 `data-hub-open` 을 달아 두면
 *      문서 전체의 클릭 위임(stockdrawer.js)이 연다. 서랍에 있던 근거 개수 · 신호 기준 종가는 모달 신호 칸(stockdrawer.js)이 이어받았다.
 *      Figma: 전용 파일 t2BVPRrfnaJI3yfcymkeEq 「설계 — 입구 통일 (결정)」.
 */

/** 「중립」 을 쉬운 말로 무엇이라 부를지 — 검토 결정(설계서 6절 4번 · 낱말 표 #159 T3) 전 임시 값. */
export const NEUTRAL_WORD = "중립";   // #373 오준영 님 답: 「중립」 유지(「판단 보류」 는 자료 부족 · 계산 실패로 읽힌다)

/** 표 위 안내 — 이 순위는 추천 순위가 아니라 기록된 점수를 줄 세운 것이다(정렬 기준은 서버 SIGNAL_RANK_NOTE 와 같다). */
export const RANK_ORDER_NOTE = "기록된 종합 점수 순입니다(종합 점수 → 신뢰도 → 종목코드). 추천 순위가 아닙니다.";
/** 개별 근거의 「중립」 과 종합 신호의 「관망」 을 가르는 한 줄 — 서버 설명 글(±1 기준)과 같은 뜻. */
export const NEUTRAL_HELP = `근거의 「${NEUTRAL_WORD}」 은 그 근거가 매수 · 매도 어느 쪽도 밀지 않는다는 뜻이고, 종합 신호의 「관망」 은 근거를 합친 점수가 매수 · 매도 기준(±1)에 닿지 않았다는 뜻입니다. 둘 다 자료 부족이나 계산 실패가 아닙니다.`;
const DASH = "—";
const isNum = v => typeof v === "number" && Number.isFinite(v);

/** "2026-10-26" → "10-26" · 꼴이 다르면 줄표(지어내지 않는다). */
export function mmdd(s) {
  const m = /^\d{4}-(\d{2})-(\d{2})/.exec(String(s || ""));
  return m ? `${m[1]}-${m[2]}` : DASH;
}

/** 규칙 신호 글 — 매수 · 매도는 「쪽」 을 붙이고(권유가 아니라 기울기), 그 밖(관망)은 서버 글 그대로. */
export function signalWord(signal) {
  if (signal === "매수") return "매수 쪽";
  if (signal === "매도") return "매도 쪽";
  return signal ? String(signal) : DASH;
}

/** 근거 개수 글 — { text, total, note }. counts 가 없으면(낯선 근거 문장) 개수를 비우고 서버 까닭을 note 로. */
export function countsView(row) {
  const c = row && row.counts;
  if (c && isNum(c.buy) && isNum(c.neutral) && isNum(c.sell)) {
    const total = c.buy + c.neutral + c.sell;
    return { text: `근거 ${total}개 (매수 쪽 ${c.buy} · ${NEUTRAL_WORD} ${c.neutral} · 매도 쪽 ${c.sell})`, total, note: "" };
  }
  return { text: "근거 개수를 셀 수 없습니다", total: null, note: (row && row.counts_note) || "" };   // 0개로 두지 않는다
}

/** 상태 딱지 종류 — 색만으로 구분하지 않으려고 글자(최신 · 확인 필요 · 안내)를 늘 함께 보인다(설계 07 쪽 ③ 접근성). */
const BADGE_KIND = { "최신": "ok", "확인 필요": "warn", "안내": "info" };

/** 신호 순위 머리줄(설계 07 쪽 ①) — 서버 `freshness` 의 글을 그대로 보인다(화면이 날짜 · 상태를 새로 판정하지 않는다).
 *  「기준: 2026-10-30 KRX 정규장 종가 · 계산: 11-02 12:59」 + 딱지 + 안내 글 + 상태 설명 한 줄(서버 `detail`). 못 받았으면 빈 글. */
export function renderFreshness(fr, esc) {
  if (!fr || typeof fr !== "object") return "";
  const calc = /^\d{4}-(\d{2}-\d{2}) (\d{2}:\d{2})/.exec(String(fr.computed_at || ""));
  const base = `기준: ${esc(fr.as_of || DASH)} ${esc(fr.basis || "")} · 계산: ${calc ? esc(calc[1] + " " + calc[2]) : DASH}`;
  const badge = fr.badge ? ` <span class="sd-chip sr-badge" data-kind="${esc(BADGE_KIND[fr.badge] || "info")}">${esc(fr.badge)}</span>` : "";
  const msg = fr.message ? `<div class="text-sm" data-sr-fresh-msg="${esc(fr.state || "")}">${esc(fr.message)}</div>` : "";
  const older = fr.older_note ? `<div class="text-xs" style="color:var(--text-mute);">${esc(fr.older_note)}</div>` : "";
  // 서버 `detail` 은 사람이 읽는 한 줄이다(「정상 — 있어야 할 마지막 거래일 종가 기준」) — 「상태 이름 —」 같은 개발 티 접두어 없이 그대로 보인다(2026-11-02 S192)
  const detail = fr.detail ? `<div class="text-xs" style="color:var(--text-mute);" data-sr-fresh-detail>${esc(fr.detail)}</div>` : "";
  return `<div class="mb-2" data-sr-fresh><div class="font-semibold text-sm">${base}${badge}</div>${msg}${older}${detail}</div>`;
}

/** 지금 가격 딱지(설계 07 쪽 ②) — 응답의 source · market_state · as_of 만 읽어 「실시간 · 지연 · 종가」 로 가른다. 모르면 null(딱지 없음). */
export function quoteBadge(quote) {
  if (!quote || !isNum(quote.price)) return null;
  const closed = quote.market_state === "closed";
  if (quote.source === "kis_user" || quote.source === "kis_gateway") return { kind: "live", text: closed ? "증권사 조회 · 장 마감" : "실시간 · 정규장" };
  if (quote.source === "delayed") return { kind: "delay", text: "지연 시세 · 약 20분" };
  if (quote.source === "collector") return { kind: "close", text: `종가 · ${ymd(quote.as_of)}` };
  return null;
}

/** 순위 줄 하나의 표시 값 — name 은 응답에 없어(설계서 5절 요청 중) 부르는 쪽이 nameOf 로 넘길 때만 쓴다. */
export function rowView(row, nameOf) {
  // 이름: 화면이 넘긴 nameOf 가 먼저, 없으면 서버가 줄에 붙인 name(순위 화면 · 2026-11-02) — 둘 다 없으면 코드만 보인다
  const name = (typeof nameOf === "function" ? nameOf(row.symbol) : null) || (typeof row.name === "string" ? row.name : null);
  const counts = countsView(row);
  return {
    rank: row.rank,
    symbol: row.symbol,
    name: name || "",
    asOf: mmdd(row.as_of),
    signal: signalWord(row.signal),
    strength: row.strength || "",
    composite: isNum(row.composite) ? row.composite.toFixed(2) : DASH,
    confidence: isNum(row.confidence) ? `${Math.round(row.confidence * 100)}%` : DASH,
    countsText: counts.text,
    countsNote: counts.note,
    noIntraday: row.no_intraday === true,        // 서버가 기록의 60분 주기 오류에서 읽은 값 — 화면이 짐작하지 않는다
    market: typeof row.market === "string" ? row.market : "",   // 서버가 수집 DB 에서 읽은 시장 — 지금 가격 조회의 꼬리(.KS · .KQ)에만 쓴다
  };
}

/** 지금 값 조회(`/api/quote/now`)에 넣을 종목 — 서버는 6자리 코드만 받으면 수집 DB 를 못 찾아 빈손이 되고(2026-11-06 실제 화면 확인),
 *  **틀린 꼬리를 붙이면 다른 종목의 오래된 값이 나온다.** 그래서 이미 꼬리가 있으면 그대로, 없으면 서버가 알려 준 시장으로만 붙이고
 *  (코스피 .KS · 코스닥 .KQ) 시장을 모르거나 ETF 면 **짐작하지 않고 빈 글**을 돌려준다(빈 글이면 조회하지 않는다). */
export function nowSymbolOf(symbol, market) {
  const raw = String(symbol || "").trim().toUpperCase();
  if (/^\d{6}\.(KS|KQ)$/.test(raw)) return raw;
  if (!/^\d{6}$/.test(raw)) return "";
  const m = String(market || "").toUpperCase();
  return m === "KOSPI" ? `${raw}.KS` : m === "KOSDAQ" ? `${raw}.KQ` : "";
}

/** 순위 필터(2026-11-05 · 「매수 / 매도 / 관망 · KOSPI / KOSDAQ 로 거르고 싶다」 피드백) — 서버가 limit 전에 거른다.
 *  낱말은 서버(`stock_hub.SIGNAL_RANK_SIGNALS` · `SIGNAL_RANK_MARKETS`)와 같다. 「전체」 는 빈 글(인자를 보내지 않는다). */
export const FILTER_SIGNALS = ["", "매수", "매도", "관망"];
export const FILTER_MARKETS = ["", "KOSPI", "KOSDAQ", "ETF"];
export const FILTER_LIMITS = [50, 100, 200, 500];
export const FILTER_DEFAULT = { signal: "", market: "", limit: 50 };

/** 필터 상태 → 순위 API 질의 글. 모르는 낱말은 버린다(서버가 422 를 내기 전에 화면이 막는다). 기본값이면 빈 글(옛 호출과 같다). */
export function filterQuery(state = {}) {
  const q = [];
  if (FILTER_SIGNALS.includes(state.signal) && state.signal) q.push(`signal=${encodeURIComponent(state.signal)}`);
  if (FILTER_MARKETS.includes(state.market) && state.market) q.push(`market=${encodeURIComponent(state.market)}`);
  const limit = Number(state.limit);
  if (FILTER_LIMITS.includes(limit) && limit !== FILTER_DEFAULT.limit) q.push(`limit=${limit}`);
  return q.length ? `?${q.join("&")}` : "";
}

/** 필터 줄 — 신호 · 시장 단추(눌림 상태는 aria-pressed) + 보여줄 줄 수. 검색 줄 아래, 순위 표 위에 한 번 붙는다. */
export function filterBarHtml(esc, state = FILTER_DEFAULT) {
  const chip = (kind, value, label) =>
    `<button type="button" class="sr-chip text-xs" data-sr-filter="${kind}" data-value="${esc(value)}" aria-pressed="${(state[kind] || "") === value}">${esc(label)}</button>`;
  return `<div class="sr-filter" data-sr-filter-bar role="group" aria-label="순위 필터">`
    + `<div class="sr-filter-row"><span class="text-xs font-semibold" style="color:var(--text-dim);">신호</span>`
    + FILTER_SIGNALS.map(v => chip("signal", v, v || "전체")).join("") + `</div>`
    + `<div class="sr-filter-row"><span class="text-xs font-semibold" style="color:var(--text-dim);">시장</span>`
    + FILTER_MARKETS.map(v => chip("market", v, v || "전체")).join("") + `</div>`
    + `<div class="sr-filter-row"><label for="sr-limit" class="text-xs font-semibold" style="color:var(--text-dim);">보여줄 줄 수</label>`
    + `<select id="sr-limit" class="input text-xs" data-sr-limit>`
    + FILTER_LIMITS.map(n => `<option value="${n}"${Number(state.limit) === n ? " selected" : ""}>${n}줄</option>`).join("")
    + `</select>`
    + `<button type="button" class="btn-secondary text-xs" data-sr-refresh>새로고침</button>`
    + `<span class="text-xs" style="color:var(--text-mute);" data-sr-refresh-note role="status" aria-live="polite"></span>`
    + `</div></div>`;
}

/** 응답이 필터를 거쳤으면 머리줄에 붙일 글 — 「조건 매수 · KOSPI — 맞는 123종목 중 50줄」. 필터가 없으면 빈 글. */
export function filterNote(resp) {
  const f = (resp && resp.filter) || {};
  const parts = [f.signal, f.market].filter(Boolean);
  if (!parts.length) return "";
  const rows = (resp.rows || []).length;
  const matched = isNum(resp.matched) ? resp.matched : DASH;
  return `조건 ${parts.join(" · ")} — 맞는 ${matched}종목 중 ${rows}줄`;
}

/** 새로고침 때 상위 몇 종목에 붙이는 「지금 가격」 한 줄(2026-11-05 · 「새로고침하면 실시간 데이터와 같이 보고 싶다」 제안 (a)).
 *  신호는 다시 계산하지 않는다 — 기록된 신호 옆에 지금 가격과 그 출처 딱지(실시간 · 지연 · 종가)만 놓는다. 가격이 없으면 빈 글. */
export const REFRESH_QUOTE_COUNT = 10;
export function quoteLineText(quote) {
  const b = quoteBadge(quote);
  if (!b) return "";
  const px = Math.round(quote.price).toLocaleString("en-US");
  return `지금 ${px}원 · ${b.text}`;
}

/** 새로고침 안내 글 — 언제 다시 읽었는지(KST 시각)와 「신호는 새로 계산하지 않는다」 를 같이 말한다. */
export function refreshNote(at, quoted) {
  const d = at instanceof Date ? at : new Date(at);
  const kst = new Date(d.getTime() + 9 * 3600 * 1000);
  const hms = Number.isNaN(kst.getTime()) ? DASH : kst.toISOString().slice(11, 19);
  return `새로고침 ${hms} (KST) · 기록된 신호를 다시 읽었습니다${quoted ? `(위 ${quoted}종목에 지금 가격을 붙임)` : ""} — 신호는 새로 계산하지 않습니다`;
}

/** 순위 표 — 상태 셋: 줄이 있음 / 비어 있음(서버 missing 문장 그대로) / 응답 없음. */
export function renderRankTable(resp, esc, { nameOf } = {}) {
  const rows = (resp && resp.rows) || [];
  const missing = (resp && resp.missing) || [];
  const fresh = renderFreshness(resp && resp.freshness, esc);
  const head = fresh
    + `<div class="text-xs mb-2" style="color:var(--text-mute);">`
    + `${fresh ? "" : `기준일 ${esc(mmdd(resp && resp.on))} · `}전체 ${esc(isNum(resp && resp.total) ? resp.total : DASH)}종목 중 ${esc(rows.length)}줄`
    + `${resp && resp.definition ? " · " + esc(resp.definition) : ""}</div>`
    + (filterNote(resp) ? `<div class="text-xs mb-2" style="color:var(--text-dim);" data-sr-filter-note>${esc(filterNote(resp))}</div>` : "")
    + `<div class="text-xs" style="color:var(--text-mute);">${esc(RANK_ORDER_NOTE)}</div>`
    + `<div class="text-xs mb-2" style="color:var(--text-mute);">${esc(NEUTRAL_HELP)}</div>`;
  const foot = `<div class="text-xs mt-2" style="color:var(--text-mute);">${esc((resp && resp.notice) || "")}</div>`
    + (resp && resp.note ? `<div class="text-xs" style="color:var(--text-mute);">${esc(resp.note)}</div>` : "");
  const missingHtml = missing.length
    ? `<ul class="text-xs mt-2">${missing.map(m => `<li>${esc(m.symbol)} — ${esc(m.message || "")}</li>`).join("")}</ul>` : "";
  if (!rows.length) {
    const filtered = filterNote(resp) !== "";
    return `${head}<div class="text-sm">${filtered ? "이 조건에 맞는 종목이 없습니다. 필터를 풀어 보세요." : "이 날짜의 신호 기록이 아직 없습니다."}</div>${missingHtml}${foot}`;
  }
  const body = rows.map(r => {
    const v = rowView(r, nameOf);
    const code = ohlcvCode(v.symbol);
    // 줄 전체가 종목 근거 모달 입구 — 종목코드(6자리)를 모르는 줄은 입구를 달지 않는다(빈 코드로 부르면 422)
    const entry = code ? ` data-hub-open="${esc(code)}" data-hub-name="${esc(v.name)}" tabindex="0"` : "";
    // 칸마다 열 이름(data-label)을 단다 — 좁은 화면(640px 이하)에서 표가 줄마다 카드로 바뀔 때 CSS 가 이 이름을 칸 앞에 보인다(signalrankview.css)
    return `<tr data-sr-symbol="${esc(v.symbol)}" data-sr-market="${esc(v.market)}"${entry}>`
      + `<td data-label="순위">${esc(v.rank)}</td>`
      + `<td data-label="종목">${v.name ? esc(v.name) + " " : ""}<span class="text-xs">${esc(v.symbol)}</span></td>`
      + `<td data-label="규칙 신호">${esc(v.signal)}${v.strength ? " · " + esc(v.strength) : ""}`
      + `${v.noIntraday ? `<div class="text-xs" style="color:var(--text-mute);" data-sr-no-intraday>분봉 없이 계산(일봉 · 주봉만)</div>` : ""}</td>`
      + `<td data-label="종합 점수">${esc(v.composite)}</td>`
      + `<td data-label="근거">${esc(v.countsText)}${v.countsNote ? `<div class="text-xs" style="color:var(--text-mute);">${esc(v.countsNote)}</div>` : ""}</td>`
      + `<td data-label="기준일">${esc(v.asOf)}</td><td data-label="주문">${code ? `<button type="button" class="btn-secondary text-xs" data-paper-open="${esc(code)}">PAPER 모의주문</button>` : ''}</td></tr>`;
  }).join("");
  return `${head}<table class="w-full text-sm"><thead><tr><th>순위</th><th>종목</th><th>규칙 신호</th><th>종합 점수</th><th>근거</th><th>기준일</th><th>주문</th></tr></thead>`
    + `<tbody>${body}</tbody></table>${missingHtml}${foot}`;
}

/** `/api/data/ohlcv` 에 보낼 종목코드 6자리 — 「005930」 · 「005930.KS」 · ETF 「0000D0」. 아니면 빈 글(요청을 보내지 않는다). */
export function ohlcvCode(symbol) {
  const m = /^([0-9A-Za-z]{6})(?:\.[A-Za-z]+)?$/.exec(String(symbol || "").trim());
  return m ? m[1].toUpperCase() : "";
}

/** 가격 두 줄 — 못 받은 칸은 비워 두고 까닭만 보인다(대체값 금지).
 *  ohlcv: `/api/data/ohlcv?timeframe=1d&from=as_of&to=as_of` 응답 · quote: `/api/quote/now` 응답 · closeErr: ohlcv 요청이 실패한 글.
 *  종가는 **선택한 행의 as_of 날짜 줄**만 쓴다(오준영 님 #373) — 마지막 종가나 가까운 날 종가로 대신하지 않고, 그날 줄이 없으면 「확인 불가」. */
export function priceLines(ohlcv, quote, signalAsOf, closeErr = "") {
  const day = ymd(signalAsOf);
  const rows = (ohlcv && Array.isArray(ohlcv.rows)) ? ohlcv.rows : [];
  const hit = rows.find(r => r && ymd(r.trade_date) === day && isNum(r.close));
  const closeLine = hit
    ? { ok: true, text: `신호 기준 종가(${mmdd(day)}) ${hit.close.toLocaleString("ko-KR")}원`,
        note: ohlcv.basis === "raw" ? "수정하지 않은 종가" : (ohlcv.basis ? `수정 방식 ${ohlcv.basis}` : "") }
    : { ok: false, text: `신호 기준 종가(${mmdd(signalAsOf)}) 확인 불가`,
        note: closeErr || (ohlcv ? "이 날짜의 일봉이 없습니다." : "종가를 받지 못했습니다.") };
  const quoteOk = quote && isNum(quote.price);
  const quoteLine = quoteOk
    ? { ok: true, text: `지금 가격 ${quote.price.toLocaleString("ko-KR")}원`, note: quote.label || "", badge: quoteBadge(quote) }
    : { ok: false, text: "지금 가격을 받지 못했습니다", note: (quote && (quote.fallback || quote.label)) || "" };
  return { close: closeLine, quote: quoteLine };
}

/** 종목 검색 칸의 글 → 순위 API 에 보낼 꼴(2026-11-03 · 「모든 종목을 검색해 신호와 근거를 확인」 피드백).
 *  신호 기록은 국내 6자리 코드에만 있다 — 그 밖(해외 티커 · 코드 아닌 글)은 요청을 보내지 않고 까닭을 말한다(빈 코드는 422). */
export function findQuery(symbol) {
  const code = ohlcvCode(symbol);
  if (!code) return { ok: false, code: "", query: "", message: "신호 기록은 국내 종목(6자리 코드)에만 있습니다. 한글 종목 이름이나 6자리 코드로 다시 찾아 보세요." };
  return { ok: true, code, query: `?symbols=${code}`, message: "" };
}

/** 검색 칸 — 순위 표 위에 한 번 붙는 줄. 칸을 비우면 전체 순위로 돌아간다. 입구 단추는 종목 근거 모달(`data-hub-open`)을 연다. */
export function findBarHtml(esc) {
  return `<form class="sr-find" data-sr-find role="search" aria-label="종목 신호 검색">`
    + `<label for="sr-find-input" class="text-xs font-semibold" style="color:var(--text-dim);">종목 검색</label>`
    + `<div class="sr-find-row">`
    + `<input id="sr-find-input" class="input sr-find-input" type="search" autocomplete="off" placeholder="종목 이름 또는 코드 (예: 삼성전자, 005930)" />`
    + `<button type="submit" class="btn-primary text-xs">검색</button>`
    + `<button type="button" class="btn-secondary text-xs" data-sr-find-reset>전체 순위</button>`
    + `</div>`
    + `<div class="text-xs" style="color:var(--text-mute);" data-sr-find-note role="status" aria-live="polite">${esc("기록된 종목 중에서 찾습니다. 종목을 고르면 그 종목의 규칙 신호와 근거를 봅니다 — 과거 자료 기준 참고용이며 투자 권유가 아닙니다.")}</div>`
    + `</form>`;
}

/** 검색한 종목 아래 안내 — 순위 표에 줄이 없어도(기록 대상 밖) 종목 근거 모달은 열 수 있게 입구를 함께 둔다. 입구는 문서 전체의 클릭 위임이 받는다. */
export function findNoteHtml(code, name, esc) {
  return `검색한 종목: ${esc(name ? `${name}(${code})` : code)} · 아래 줄을 누르거나 `
    + `<button type="button" class="sd-open-btn text-xs" data-hub-open="${esc(code)}" data-hub-name="${esc(name || "")}">종목 근거 →</button> 를 눌러 근거를 봅니다. `
    + `기록이 없는 종목이면 아래에 그 까닭이 나옵니다.`;
}

/** 불러오기 실패 글 — 순위 · 신호 기록 404 는 서버의 한국어 까닭 그대로(기록 없음 갈래), 로그인 풀림 · 연결 끊김은 따로. */
export function drawerFailText(err) {
  const status = err && err.status;
  if (status === 404) return (err && err.message) || "이 종목의 신호 기록이 없습니다.";
  if (status === 401) return "로그인이 풀렸습니다. 다시 로그인해 주세요.";
  if (status === 0) return "서버에 연결할 수 없습니다. 네트워크 상태를 확인해 주세요.";
  return (err && err.message) || "불러오지 못했습니다.";
}

/** "2026-10-28T09:00:00+09:00" → "2026-10-28" · 꼴이 다르면 줄표(뉴스는 오래되면 뜻이 달라서 연도까지 보인다). */
export function ymd(s) {
  const m = /^(\d{4}-\d{2}-\d{2})/.exec(String(s || ""));
  return m ? m[1] : DASH;
}

/** 화면에 붙인다 — deps: { api, esc, nameOf? }. host 안을 통째로 그린다.
 *  줄을 누르는 일은 여기서 하지 않는다 — 줄에 달린 `data-hub-open` 을 문서 전체의 클릭 위임(stockdrawer.js)이 받아 종목 근거 모달을 연다.
 *  여기서는 키보드(Enter · 스페이스)만 같은 길로 이어 준다(줄이 단추가 아니라서 기본으로는 눌리지 않는다). */
export function mountSignalRank(host, { api, esc, nameOf } = {}) {
  let resp = null;
  let lastParams = "";    // 새로고침이 같은 조건으로 다시 읽게 마지막 질의를 기억한다
  let askSeq = 0;   // 마지막 요청만 반영한다 — 검색을 누른 뒤 응답 전에 「전체 순위」 를 누르면 늦게 온 응답이 표를 덮지 않게(코드 검수 S195)
  const paint = () => {
    host.innerHTML = `<div data-sr-list>${renderRankTable(resp, esc, { nameOf })}</div>`;
  };
  host.addEventListener("keydown", e => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const tr = e.target && e.target.closest ? e.target.closest("tr[data-hub-open]") : null;
    if (!tr || e.target !== tr) return;                    // 줄 안의 PAPER 단추는 자기 일을 한다
    e.preventDefault();                                    // 스페이스가 화면을 내리지 않게
    tr.click();                                            // 클릭과 같은 길 — 서랍이 아니라 종목 근거 모달
  });
  return {
    async loadRankRows(params = "") {   // 이름이 `load` 이면 화면 스캐너가 다른 화면의 load 와 이어 버린다(TC-RKS-12)
      lastParams = params;
      const mine = ++askSeq;
      host.textContent = "불러오는 중…";
      try { const got = await api(`/api/stock-hub/signal-rank${params}`); if (mine !== askSeq) return; resp = got; paint(); }
      catch (err) { if (mine === askSeq) host.textContent = drawerFailText(err); }
    },
    /** 새로고침(2026-11-05) — 마지막 조건으로 기록을 다시 읽고, 위 몇 종목에만 지금 가격을 붙인다. 가격을 못 받은 줄은 그냥 둔다(요청은 한 번에 5개씩).
     *  2026-11-06: 가격은 출처 딱지가 있는 `/api/quote/now` 로 읽는다(옛 `/api/stocks/quote` 는 출처가 없어 딱지를 못 만들었고, 꼬리 없는 6자리 코드는
     *  「데이터 없음」 이라 한 줄도 붙지 않았다). 시장을 모르는 줄(꼬리를 못 붙임)은 조회하지 않는다. */
    async refreshRankRows({ quoteCount = REFRESH_QUOTE_COUNT } = {}) {
      await this.loadRankRows(lastParams);
      const mine = askSeq;
      const rows = [...host.querySelectorAll("tr[data-sr-symbol]")].slice(0, quoteCount)
        .map(tr => ({ tr, sym: nowSymbolOf(tr.dataset.srSymbol, tr.dataset.srMarket) })).filter(x => x.sym);
      let quoted = 0;
      for (let i = 0; i < rows.length; i += 5) {
        const batch = rows.slice(i, i + 5).map(x => x.tr);
        const syms = rows.slice(i, i + 5).map(x => x.sym);
        const got = await Promise.allSettled(syms.map(sym => api(`/api/quote/now?symbol=${encodeURIComponent(sym)}`)));
        if (mine !== askSeq) return { quoted };           // 그 사이 다른 조건으로 다시 읽었다 — 낡은 가격은 붙이지 않는다
        got.forEach((g, k) => {
          const text = g.status === "fulfilled" ? quoteLineText(g.value) : "";
          const cell = batch[k].querySelector('td[data-label="종목"]');
          if (!text || !cell) return;
          cell.insertAdjacentHTML("beforeend", `<div class="text-xs" style="color:var(--text-dim);" data-sr-quote>${esc(text)}</div>`);
          quoted++;
        });
      }
      return { quoted };
    },
  };
}
