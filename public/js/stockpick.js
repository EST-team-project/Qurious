/* 종목 찾기 칸(콤보 상자) — 전략 분석이 처음 쓴다 (2026-10-16 · Figma 「모의투자 여정 고치기」 03-6 융합안 결정).
 *
 * 화면에는 찾기 칸 하나만 둔다. 비어 있을 때 칸을 누르면 「최근 본 종목」(이 브라우저) + 「대표 종목」 이 펼쳐지고,
 * 글자를 치면 국내 상장 종목을 찾는다(`/api/stocks/search` — 계절성 · 재무 위험 화면과 같은 길). Enter · 화살표 · Esc.
 * 고른 종목은 `onPick({ symbol, name, code })` 로 넘긴다 — 기호는 수집 DB 다리가 받는 꼴(`000000.KS` · `.KQ`)만.
 *
 * 판단(목록 합치기 · 최근 목록 · 찾기 결과 거르기 · 이름표)은 DOM 없이 돌아가는 아래 함수들로 — node 시험(TC-SPK).
 * 최근 본 종목은 브라우저 저장소(localStorage)에 — 사람마다의 편의일 뿐이라 서버에 두지 않는다(못 읽으면 빈 목록).
 */

/** 수집 DB 다리가 받는 국내 종목 기호 꼴(`app/services/collector_db.py` `_SYMBOL` 과 같은 규칙 — 시험이 맞댄다). */
export const SYMBOL_RE = /^(\d{6})\.(KS|KQ)$/;
export const RECENT_MAX = 5;

/** { symbol, name } → 「삼성전자(005930)」 · 이름이 없으면 코드만. */
export function labelOf(item) {
  const m = SYMBOL_RE.exec(String(item && item.symbol || ""));
  const code = m ? m[1] : String(item && item.symbol || "");
  const name = String(item && item.name || "").trim();
  return name ? `${name}(${code})` : code;
}

/** 찾기 응답 → 국내 상장 종목만 { symbol, name, code } · 같은 기호는 한 번 · 최대 n. */
export function filterResults(results, n = 8) {
  const out = [];
  const seen = new Set();
  for (const r of results || []) {
    const sym = String(r && r.symbol || "").toUpperCase();
    const m = SYMBOL_RE.exec(sym);
    if (!m || seen.has(sym)) continue;
    seen.add(sym);
    out.push({ symbol: sym, name: String(r.name || ""), code: m[1] });
    if (out.length >= n) break;
  }
  return out;
}

/** 최근 목록 맨 앞에 넣는다 — 같은 기호는 앞으로 옮기고 RECENT_MAX 개까지. 원래 목록은 바꾸지 않는다. */
export function pushRecent(list, item, max = RECENT_MAX) {
  if (!item || !SYMBOL_RE.test(String(item.symbol || ""))) return (list || []).slice(0, max);
  const rest = (list || []).filter(x => x && x.symbol !== item.symbol);
  return [{ symbol: item.symbol, name: item.name || "" }, ...rest].slice(0, max);
}

/** 펼친 목록의 묶음 — [{ title, items }] · 대표 종목에서 최근에 이미 있는 기호는 뺀다 · 빈 묶음은 싣지 않는다. */
export function groupsFor(recent, presets) {
  const have = new Set((recent || []).map(x => x.symbol));
  const groups = [];
  if ((recent || []).length) groups.push({ title: "최근 본 종목", items: recent });
  const rest = (presets || []).filter(x => !have.has(x.symbol));
  if (rest.length) groups.push({ title: "대표 종목", items: rest });
  return groups;
}

function readRecent(key) {
  try { const v = JSON.parse(localStorage.getItem(key) || "[]"); return Array.isArray(v) ? v.filter(x => SYMBOL_RE.test(String(x && x.symbol || ""))) : []; }
  catch { return []; }
}
function writeRecent(key, list) {
  try { localStorage.setItem(key, JSON.stringify(list)); } catch { /* 저장소를 못 쓰면 이번 화면에서만 기억 */ }
}
const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/**
 * 찾기 칸을 host 안에 그린다.
 *   opts.presets   [{ symbol, name }] 대표 종목
 *   opts.recentKey 최근 본 종목 저장 이름
 *   opts.initial   처음 고른 종목 { symbol, name }
 *   opts.search    (q) => Promise<results>  — 화면이 api 를 넘긴다(이 모듈은 api 를 모른다 · node 시험용)
 *   opts.onPick    ({ symbol, name, code }) => void
 */
export function mountStockPick(host, opts) {
  const id = `sp-${Math.random().toString(36).slice(2, 8)}`;
  let recent = readRecent(opts.recentKey);
  let picked = opts.initial || null;
  let shown = [];          // 지금 목록의 고를 수 있는 줄(순서대로)
  let active = -1;
  let seq = 0;
  let timer = null;
  host.classList.add("sp-wrap");
  host.innerHTML = `<input class="input sp-input" type="text" role="combobox" aria-autocomplete="list" aria-expanded="false"
      aria-controls="${id}" autocomplete="off" spellcheck="false" aria-label="종목 이름 · 코드"
      placeholder="종목 이름 · 코드 — 예: 신한지주, 055550" value="${picked ? esc(labelOf(picked)) : ""}">
    <ul class="sp-list" id="${id}" role="listbox" hidden></ul>`;
  const input = host.querySelector(".sp-input");
  const list = host.querySelector(".sp-list");

  function paint(groups, hint) {
    shown = [];
    let html = "";
    for (const g of groups) {
      html += `<li class="sp-group" role="presentation">${esc(g.title)}</li>`;
      for (const it of g.items) {
        const i = shown.push(it) - 1;
        html += `<li class="sp-opt" role="option" id="${id}-${i}" data-i="${i}" aria-selected="false">`
          + `<strong>${esc(it.name || it.symbol)}</strong><span>${esc(SYMBOL_RE.exec(it.symbol)?.[1] || it.symbol)}</span></li>`;
      }
    }
    if (hint) html += `<li class="sp-hint" role="presentation">${esc(hint)}</li>`;
    list.innerHTML = html;
    active = -1;
    input.removeAttribute("aria-activedescendant");
    open(true);
  }
  function open(on) {
    list.hidden = !on;
    input.setAttribute("aria-expanded", on ? "true" : "false");
  }
  function mark(i) {
    active = i;
    for (const li of list.querySelectorAll(".sp-opt")) li.setAttribute("aria-selected", String(Number(li.dataset.i) === i));
    if (i >= 0) { input.setAttribute("aria-activedescendant", `${id}-${i}`); list.querySelector(`#${id}-${i}`)?.scrollIntoView({ block: "nearest" }); }
  }
  function choose(it) {
    if (!it) return;
    picked = { symbol: it.symbol, name: it.name || "" };
    recent = pushRecent(recent, picked);
    writeRecent(opts.recentKey, recent);
    input.value = labelOf(picked);
    open(false);
    opts.onPick && opts.onPick({ ...picked, code: SYMBOL_RE.exec(picked.symbol)[1] });
  }
  function showDefault() {
    paint(groupsFor(recent, opts.presets), "이름이나 코드를 치면 국내 상장 종목에서 찾습니다");
  }
  async function find(q) {
    const my = ++seq;
    let rows = null;
    try { rows = filterResults(await opts.search(q)); } catch { rows = null; }
    if (my !== seq) return;   // 더 새로 친 글자가 있다
    if (rows === null) { paint([], "찾기가 지금 되지 않습니다 — 6자리 종목코드를 넣고 Enter"); return; }
    paint(rows.length ? [{ title: "찾은 종목", items: rows }] : [], rows.length ? "" : "국내 상장 종목에서 찾지 못했습니다");
  }

  input.addEventListener("focus", () => { if (!input.value.trim() || (picked && input.value === labelOf(picked))) showDefault(); });
  input.addEventListener("click", () => { if (list.hidden) showDefault(); });
  input.addEventListener("input", () => {
    clearTimeout(timer);
    const q = input.value.trim();
    if (!q) { showDefault(); return; }
    timer = setTimeout(() => find(q), 250);
  });
  input.addEventListener("keydown", ev => {
    if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
      ev.preventDefault();
      if (list.hidden) { showDefault(); return; }
      if (!shown.length) return;
      mark(ev.key === "ArrowDown" ? (active + 1) % shown.length : (active <= 0 ? shown.length - 1 : active - 1));
    } else if (ev.key === "Enter") {
      ev.preventDefault();
      if (active >= 0 && shown[active]) { choose(shown[active]); return; }
      const q = input.value.trim();
      if (/^\d{6}$/.test(q)) {   // 코드만 친 경우 — 찾기로 이름을 붙여 고른다(못 찾으면 고르지 않는다)
        Promise.resolve(opts.search(q)).then(r => { const rows = filterResults(r); if (rows.length) choose(rows[0]); else find(q); }).catch(() => find(q));
      } else if (shown.length === 1) choose(shown[0]);
    } else if (ev.key === "Escape") {
      open(false);
      if (picked) input.value = labelOf(picked);
    }
  });
  list.addEventListener("mousedown", ev => ev.preventDefault());   // 고르기 전에 칸이 초점을 잃어 목록이 닫히지 않게
  list.addEventListener("click", ev => {
    const li = ev.target.closest(".sp-opt");
    if (li) choose(shown[Number(li.dataset.i)]);
  });
  input.addEventListener("blur", () => {
    setTimeout(() => { open(false); if (picked && !input.value.trim()) input.value = labelOf(picked); }, 120);
  });

  return { get value() { return picked; }, input };
}
