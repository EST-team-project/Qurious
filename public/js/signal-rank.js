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
 *   5. 서랍의 설명과 신호 기준 종가는 **선택한 행의 as_of** 에 맞춘다 — 허브의 마지막 종가가 아니다. 그날 종가가 없으면 「확인 불가」.
 */

/** 「중립」 을 쉬운 말로 무엇이라 부를지 — 검토 결정(설계서 6절 4번 · 낱말 표 #159 T3) 전 임시 값. */
export const NEUTRAL_WORD = "중립";   // #373 오준영 님 답: 「중립」 유지(「판단 보류」 는 자료 부족 · 계산 실패로 읽힌다)

/** 표 위 안내 — 이 순위는 추천 순위가 아니라 기록된 점수를 줄 세운 것이다(정렬 기준은 서버 SIGNAL_RANK_NOTE 와 같다). */
export const RANK_ORDER_NOTE = "기록된 종합 점수 순입니다(종합 점수 → 신뢰도 → 종목코드). 추천 순위가 아닙니다.";
/** 개별 근거의 「중립」 과 종합 신호의 「관망」 을 가르는 한 줄 — 서버 설명 글(±1 기준)과 같은 뜻. */
export const NEUTRAL_HELP = `근거의 「${NEUTRAL_WORD}」 은 그 근거가 매수 · 매도 어느 쪽도 밀지 않는다는 뜻이고, 종합 신호의 「관망」 은 근거를 합친 점수가 매수 · 매도 기준(±1)에 닿지 않았다는 뜻입니다. 둘 다 자료 부족이나 계산 실패가 아닙니다.`;
const DASH = "—";
const isNum = v => typeof v === "number" && Number.isFinite(v);
/** 서랍에 보일 기사 수 — 서버(stock_hub.NEWS_LIMIT)가 이미 5건으로 자르지만 화면도 넘기지 않는다. */
export const NEWS_LIMIT = 5;

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

/** 순위 줄 하나의 표시 값 — name 은 응답에 없어(설계서 5절 요청 중) 부르는 쪽이 nameOf 로 넘길 때만 쓴다. */
export function rowView(row, nameOf) {
  const name = typeof nameOf === "function" ? nameOf(row.symbol) : null;
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
  };
}

/** 순위 표 — 상태 셋: 줄이 있음 / 비어 있음(서버 missing 문장 그대로) / 응답 없음. */
export function renderRankTable(resp, esc, { nameOf, selected } = {}) {
  const rows = (resp && resp.rows) || [];
  const missing = (resp && resp.missing) || [];
  const head = `<div class="text-xs mb-2" style="color:var(--text-mute);">`
    + `기준일 ${esc(mmdd(resp && resp.on))} · 전체 ${esc(isNum(resp && resp.total) ? resp.total : DASH)}종목 중 ${esc(rows.length)}줄`
    + `${resp && resp.definition ? " · " + esc(resp.definition) : ""}</div>`
    + `<div class="text-xs" style="color:var(--text-mute);">${esc(RANK_ORDER_NOTE)}</div>`
    + `<div class="text-xs mb-2" style="color:var(--text-mute);">${esc(NEUTRAL_HELP)}</div>`;
  const foot = `<div class="text-xs mt-2" style="color:var(--text-mute);">${esc((resp && resp.notice) || "")}</div>`
    + (resp && resp.note ? `<div class="text-xs" style="color:var(--text-mute);">${esc(resp.note)}</div>` : "");
  const missingHtml = missing.length
    ? `<ul class="text-xs mt-2">${missing.map(m => `<li>${esc(m.symbol)} — ${esc(m.message || "")}</li>`).join("")}</ul>` : "";
  if (!rows.length) {
    return `${head}<div class="text-sm">이 날짜의 신호 기록이 아직 없습니다.</div>${missingHtml}${foot}`;
  }
  const body = rows.map(r => {
    const v = rowView(r, nameOf);
    const on = selected && selected === v.symbol ? ' aria-selected="true"' : "";
    return `<tr data-sr-symbol="${esc(v.symbol)}" tabindex="0"${on}>`
      + `<td>${esc(v.rank)}</td>`
      + `<td>${v.name ? esc(v.name) + " " : ""}<span class="text-xs">${esc(v.symbol)}</span></td>`
      + `<td>${esc(v.signal)}${v.strength ? " · " + esc(v.strength) : ""}</td>`
      + `<td>${esc(v.composite)}</td>`
      + `<td>${esc(v.countsText)}${v.countsNote ? `<div class="text-xs" style="color:var(--text-mute);">${esc(v.countsNote)}</div>` : ""}</td>`
      + `<td>${esc(v.asOf)}</td></tr>`;
  }).join("");
  return `${head}<table class="w-full text-sm"><thead><tr><th>순위</th><th>종목</th><th>규칙 신호</th><th>종합 점수</th><th>근거</th><th>기준일</th></tr></thead>`
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
    ? { ok: true, text: `지금 가격 ${quote.price.toLocaleString("ko-KR")}원`, note: quote.label || "" }
    : { ok: false, text: "지금 가격을 받지 못했습니다", note: (quote && (quote.fallback || quote.label)) || "" };
  return { close: closeLine, quote: quoteLine };
}

/** 서랍 불러오기 실패 글 — explain 404 는 서버의 한국어 까닭 그대로(기록 없음 갈래), 로그인 풀림 · 연결 끊김은 따로. */
export function drawerFailText(err) {
  const status = err && err.status;
  if (status === 404) return (err && err.message) || "이 종목의 신호 기록이 없습니다.";
  if (status === 401) return "로그인이 풀렸습니다. 다시 로그인해 주세요.";
  if (status === 0) return "서버에 연결할 수 없습니다. 네트워크 상태를 확인해 주세요.";
  return (err && err.message) || "불러오지 못했습니다.";
}

/** http(s) 주소만 링크로 — 그 밖(javascript: 등)은 링크 없이 제목만 보인다. */
export function safeHttpUrl(u) {
  return /^https?:\/\//i.test(String(u || "")) ? String(u) : "";
}

/** "2026-10-28T09:00:00+09:00" → "2026-10-28" · 꼴이 다르면 줄표(뉴스는 오래되면 뜻이 달라서 연도까지 보인다). */
export function ymd(s) {
  const m = /^(\d{4}-\d{2}-\d{2})/.exec(String(s || ""));
  return m ? m[1] : DASH;
}

/** 서랍의 「관련 최신 뉴스」 — 허브 `news` 칸(`/api/stock-hub?sections=news`)을 그대로 그린다.
 *  기사는 제목 · 출처 · 날짜 · 원문 링크만(본문을 옮기지 않고, 기사로 설명 문장을 짓지 않는다). 칸 제목 아래의 `note`
 *  (「이름이 같은 다른 뜻의 기사가 섞일 수 있습니다」)는 응답 글 그대로 늘 보인다. 기사가 없거나 못 받았으면 서버 까닭을 보인다.
 *  산업 뉴스는 섹터 소속이 생긴 뒤(②-10) — 이 함수는 기업 기사만 안다. */
export function renderNews(section, esc) {
  const head = `<div class="text-xs mt-2">관련 최신 뉴스 (이 기업 이름이 붙은 기사)</div>`;
  if (!section) return `${head}<div class="text-xs">뉴스를 받지 못했습니다.</div>`;
  const items = (section.data && section.data.items) || [];
  const note = section.note ? `<div class="text-xs" style="color:var(--text-mute);">${esc(section.note)}</div>` : "";
  if (section.status !== "ok" || !items.length) {
    return `${head}<div class="text-xs">${esc(section.reason || "뉴스를 받지 못했습니다.")}</div>${note}`;
  }
  const rows = items.slice(0, NEWS_LIMIT).map(it => {
    const url = safeHttpUrl(it.url);
    const title = esc(it.title || DASH);
    const link = url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${title}</a>` : title;
    const src = it.source_label || it.source || "";
    return `<li>${link} <span class="text-xs" style="color:var(--text-mute);">· ${esc(src)} · ${esc(ymd(it.published))}</span></li>`;
  }).join("");
  const from = section.source ? `<div class="text-xs" style="color:var(--text-mute);">${esc(section.source)}</div>` : "";
  return `${head}<ul class="text-sm">${rows}</ul>${note}${from}`;
}

const reasonItems = (list, esc) => (list || []).map(r =>
  `<li><span class="text-xs">[${esc(r.label || DASH)}]</span> ${esc(r.text || "")}${r.observed ? ` <span class="text-xs">(${esc(r.observed)})</span>` : ""}</li>`).join("");   // 근거마다 주기(일봉 · 주봉 · 60분봉)를 앞에 — 오준영 님 #373 2번

/** 서랍 — explain 응답의 summary · reasons · counter_reasons · notes · disclaimer 를 그대로 그린다(문장을 새로 짓지 않는다). */
export function renderDrawer(explain, prices, esc, { name, news, counts } = {}) {
  const p = prices || priceLines(null, null, explain && explain.as_of);
  const line = l => `<div class="text-sm">${esc(l.text)}${l.note ? ` <span class="text-xs" style="color:var(--text-mute);">· ${esc(l.note)}</span>` : ""}</div>`;
  const reasons = (explain.reasons || []).length ? `<div class="text-xs mt-2">이 방향을 밀어 준 근거</div><ul class="text-sm">${reasonItems(explain.reasons, esc)}</ul>` : "";
  const counters = (explain.counter_reasons || []).length ? `<div class="text-xs mt-2">반대쪽 근거</div><ul class="text-sm">${reasonItems(explain.counter_reasons, esc)}</ul>` : "";
  const notes = (explain.notes || []).map(n => `<div class="text-xs">${esc(n)}</div>`).join("");
  return `<div data-sr-drawer>`
    + `<div class="font-semibold">${name ? esc(name) + " " : ""}${esc(explain.symbol)}</div>`
    // 한 줄 요약을 가장 위에(차트 위 · 「왜 매수 쪽인가」 를 빨리) — 오준영 님 #373 2번. 차트(일봉만)는 data-sr-chart 자리에 나중에 그린다.
    + `<div class="text-sm mt-1">${esc(explain.summary || "")}</div>`
    + `<div class="text-xs">${esc(explain.confidence_text || "")}</div>`
    + (counts ? `<div class="text-xs">${esc(counts)}</div>` : "")
    + line(p.close) + line(p.quote)
    + `<div data-sr-chart></div>`
    + reasons + counters + notes
    + renderNews(news, esc)
    + `<div class="text-xs mt-2" style="color:var(--text-mute);">기준일 ${esc(mmdd(explain.as_of))} · ${esc(explain.disclaimer || "")}</div></div>`;
}

/** 화면에 붙인다 — deps: { api, esc, nameOf? }. host 안을 통째로 그리고, 줄을 누르면 오른쪽 서랍(host 안 [data-sr-side])을 채운다. */
export function mountSignalRank(host, { api, esc, nameOf } = {}) {
  let selected = "";
  let resp = null;
  const side = () => host.querySelector("[data-sr-side]");
  const paint = () => {
    host.innerHTML = `<div data-sr-list>${renderRankTable(resp, esc, { nameOf, selected })}</div><div data-sr-side></div>`;
  };
  async function openDrawer(row) {
    const { symbol, as_of: asOf } = row;
    selected = symbol; paint();
    side().textContent = "불러오는 중…";
    const code = ohlcvCode(symbol);
    const [ex, close, hub, q] = await Promise.allSettled([
      // 설명과 신호 기준 종가는 모두 **이 행의 as_of** — 허브의 마지막 종가를 쓰지 않는다(오준영 님 #373 3번)
      api(`/api/explain?kind=signal&symbol=${encodeURIComponent(symbol)}&date=${encodeURIComponent(asOf)}`),
      code ? api(`/api/data/ohlcv?symbol=${code}&timeframe=1d&from=${encodeURIComponent(ymd(asOf))}&to=${encodeURIComponent(ymd(asOf))}&basis=raw`)
           : Promise.reject({ message: "종목코드를 알 수 없어 종가를 조회하지 않았습니다." }),
      api(`/api/stock-hub?symbol=${encodeURIComponent(symbol)}&sections=news`),
      api(`/api/quote/now?symbol=${encodeURIComponent(symbol)}`),
    ]);
    if (ex.status !== "fulfilled") { side().textContent = drawerFailText(ex.reason); return; }
    const hubValue = hub.status === "fulfilled" ? hub.value : null;
    const prices = priceLines(close.status === "fulfilled" ? close.value : null, q.status === "fulfilled" ? q.value : null,
      ex.value.as_of, close.status === "rejected" ? drawerFailText(close.reason) : "");
    const name = (typeof nameOf === "function" && nameOf(symbol)) || (hubValue && hubValue.name) || "";
    const news = hubValue && hubValue.sections ? hubValue.sections.news : null;     // 허브를 못 받았으면 null → 「뉴스를 받지 못했습니다」
    side().innerHTML = renderDrawer(ex.value, prices, esc, { name, news, counts: rowView(row, nameOf).countsText });
  }
  host.addEventListener("click", e => {
    const tr = e.target.closest && e.target.closest("[data-sr-symbol]");
    if (!tr) return;
    const row = ((resp && resp.rows) || []).find(r => r.symbol === tr.dataset.srSymbol);
    if (row) openDrawer(row);
  });
  return {
    async load(params = "") {
      host.textContent = "불러오는 중…";
      try { resp = await api(`/api/stock-hub/signal-rank${params}`); paint(); }
      catch (err) { host.textContent = drawerFailText(err); }
    },
  };
}
