/* 종목 찾기 단추(돋보기 아이콘만 — 좁은 칸에서도 입력칸을 줄이지 않는다) — 직접 치는 종목 입력칸 옆에 「찾기」 단추를 달아 종목 검색 창을 연다 (2026-10-31 · Figma 「Qurious · 종목 찾기 단추」).
 *
 * 입력은 그대로 칠 수 있다 — 단추는 칸을 대신하지 않고 곁에서 돕는다. 칸에 `data-stock-find` 만 붙이면 된다.
 *   data-stock-find="symbol"   고른 기호를 그대로 넣는다(국내 `005930.KS` · 해외 `AAPL`)
 *   data-stock-find="code"     국내 종목이면 6자리 코드만 넣는다(해외는 기호 그대로)
 *   data-stock-name="<칸 id>"  고른 종목 이름도 그 칸에 넣는다(주문 화면의 종목명 칸)
 * 검색 창 자체(`stock-search-modal` · `/api/stocks/search`)는 company.js 가 이미 갖고 있다 — 여기서는 열기만 한다.
 *
 * 이 파일은 불러올 때 DOM 을 만지지 않는다(판단 함수는 node 로 그대로 돌린다 — TC-SFD).
 */

/** 국내 종목 기호 꼴(stockpick.js SYMBOL_RE 와 같다 — 시험이 맞댄다). */
export const DOMESTIC_RE = /^(\d{6})\.(KS|KQ)$/;

/** 고른 종목 → 칸에 넣을 글. mode "code" 는 국내만 6자리로 줄인다. */
export function valueFor(item, mode) {
  const sym = String(item && item.symbol || "").trim();
  if (mode === "code") {
    const m = DOMESTIC_RE.exec(sym.toUpperCase());
    if (m) return m[1];
  }
  return sym;
}

/** 단추를 달 칸인가 — 이미 달았거나 칸이 아니면 거른다. */
export function shouldMount(el) {
  if (!el || el.tagName !== "INPUT") return false;
  if (el.dataset.stockFindMounted === "1") return false;
  return el.dataset.stockFind !== undefined;
}

const SVG = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">'
  + '<circle cx="11" cy="11" r="7" stroke="currentColor" stroke-width="2.4"/>'
  + '<path d="m20 20-3.6-3.6" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/></svg>';

/** 칸의 값을 바꾸고 화면 코드가 듣는 입력 · 변경 이벤트를 보낸다. */
function fill(doc, el, value) {
  el.value = value;
  el.dispatchEvent(new doc.defaultView.Event("input", { bubbles: true }));
  el.dispatchEvent(new doc.defaultView.Event("change", { bubbles: true }));
}

/** 문서 안의 `data-stock-find` 칸마다 단추를 단다. open(callback) 은 검색 창 열기. 단 칸 수를 돌려준다. */
export function mountStockFind(doc, open) {
  if (typeof open !== "function") return 0;
  let n = 0;
  for (const el of doc.querySelectorAll("input[data-stock-find]")) {
    if (!shouldMount(el)) continue;
    el.dataset.stockFindMounted = "1";
    const wrap = doc.createElement("span");
    wrap.className = "sf-wrap";
    el.parentNode.insertBefore(wrap, el);
    wrap.appendChild(el);
    const btn = doc.createElement("button");
    btn.type = "button";
    btn.className = "sf-btn";
    btn.setAttribute("aria-label", "종목 찾기 — 이름이나 코드로 검색");
    btn.title = "종목 찾기";
    btn.innerHTML = SVG;
    btn.addEventListener("click", () => open(item => {
      fill(doc, el, valueFor(item, el.dataset.stockFind));
      const nameId = el.dataset.stockName;
      const nameEl = nameId ? doc.getElementById(nameId) : null;
      if (nameEl) fill(doc, nameEl, String(item.name || ""));
      el.focus();
    }));
    wrap.appendChild(btn);
    n += 1;
  }
  return n;
}
