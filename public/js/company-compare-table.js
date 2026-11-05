/* 지표 비교 표 — 수집 대상 전체 종목 표(시장 · 업종 필터 · 열 정렬 · 30종목 쪽) (D11 · 2026-11-04).
 *
 * 강사님 lumina-invest 의 지표 비교는 AG Grid 로 전체 종목 표를 보여 준다. 우리는 같은 꼴(필터 · 정렬 · 30종목 쪽)을 일반 표로 옮겼고,
 * 값은 서버(`GET /api/data/indicators/table`)가 수집 DB(전자공시 사업보고서 + 종가)로 계산해 준 것만 그린다.
 *
 * 규칙(companyview.js 와 같다)
 *   1. 화면은 값을 셈하지 않는다 — 필터 · 정렬 · 쪽 자르기도 서버가 한다. 여기서는 받은 줄을 글로 옮길 뿐이다(자릿수 · 쉼표 · 단위).
 *   2. 값이 없으면 줄표(—) 이고, 까닭은 「조회 상태」 칸에 눈에 보이는 글로 적는다(호버가 없는 휴대폰에서도 보인다).
 *   3. 줄마다 기준 한 줄(재무 보고서 · 공시 접수일 · 종가 날짜) · 표 아래에 출처 · 식 · 한계.
 *   4. 판단 낱말(싸다 · 좋다 · 사라 …)을 쓰지 않는다 — 숫자와 사실만.
 *
 * 구성 — 위쪽은 DOM 을 건드리지 않는 순수 함수(node 로 시험 · TC-IT), 맨 아래 `ctMount` 만 화면에 연결한다.
 * 이 파일은 `/js/common.js` 를 import 하지 않는다 — 요청 함수(`fetchPage`)와 이스케이프(`esc`)를 인자로 받아야 node 가 불러 시험할 수 있다.
 * 요청 주소(`/api/data/indicators/table`)는 company.js 가 적는다 — 화면 ↔ API 대응 스캐너(scripts/view_scan.py)가 그 글자를 보고 화면에 잇는다.
 */

export const CT_PAGE_SIZE = 30;
export const CT_DEBOUNCE_MS = 350;
const DASH = "—";
const isNum = v => typeof v === "number" && Number.isFinite(v);

/** 처음 상태 — 이름 가나다 순 · 첫 쪽. */
export function ctDefaultState() {
  return { q: "", market: "", sector: "", sort: "name", order: "asc", page: 1, size: CT_PAGE_SIZE };
}

/** 서버로 보낼 질의 문자열 — 비어 있는 필터는 보내지 않는다. */
export function ctQueryString(state) {
  const p = new URLSearchParams();
  for (const k of ["q", "market", "sector"]) if (state[k]) p.set(k, state[k]);
  p.set("sort", state.sort);
  p.set("order", state.order);
  p.set("page", String(state.page));
  p.set("size", String(state.size));
  return p.toString();
}

/** 열 머리를 눌렀을 때 — 같은 열이면 오름 ↔ 내림, 다른 열이면 오름차순으로 시작 · 첫 쪽으로. */
export function ctNextSort(state, key) {
  const same = state.sort === key;
  return { ...state, sort: key, order: same && state.order === "asc" ? "desc" : "asc", page: 1 };
}

/** 「1~30 / 351종목」 — 필터로 줄어든 때는 전체 수를 함께. 결과가 없으면 「0종목」. */
export function ctRangeText(data) {
  if (!data || !data.total) return "0종목";
  const base = `${data.start}~${data.end} / ${data.total}종목`;
  return data.total < data.universe ? `${base} (수집 대상 ${data.universe}종목 중)` : base;
}

/** 지표 값 글 — 서버 값을 자릿수만 맞춘다. 없으면 줄표 · 근사면 「(근사)」. 단위는 열 머리에 있다. */
export function ctValueText(col, m) {
  if (!m || !isNum(m.value)) return DASH;
  const d = col && isNum(col.digits) ? col.digits : 2;
  const s = m.value.toLocaleString("ko-KR", { minimumFractionDigits: d, maximumFractionDigits: d });
  return m.approx ? `${s} (근사)` : s;
}

/** 시장 코드 → 이름 (응답의 필터 목록에서). 모르면 코드 그대로, 없으면 줄표. */
export function ctMarketNames(data) {
  const out = {};
  for (const m of (data && data.filters && data.filters.markets) || []) out[m.code] = m.name;
  return out;
}

/** 필터 select 의 option 들 — 맨 앞 「전체」 + 서버가 준 목록(곳 수 함께). */
export function ctFilterOptions(list, allLabel, esc, selected) {
  const opt = (value, label) => `<option value="${esc(value)}"${value === (selected || "") ? " selected" : ""}>${esc(label)}</option>`;
  return opt("", allLabel) + (list || []).map(x => opt(x.code, `${x.name} (${x.n})`)).join("");
}

const SORT_MARK = { asc: "▲", desc: "▼" };
const ARIA_SORT = { asc: "ascending", desc: "descending" };

function headCell(label, unit, key, state, esc, extra = {}) {
  const on = state.sort === key;
  const aria = on ? ARIA_SORT[state.order] : "none";
  const next = on && state.order === "asc" ? "내림차순" : "오름차순";
  const cls = ["ct-th", extra.num ? "ct-num" : "", extra.name ? "ct-name" : ""].filter(Boolean).join(" ");
  const tip = extra.formula ? `식 · ${extra.formula}` : "";
  return `<th scope="col" class="${cls}" aria-sort="${aria}"${tip ? ` title="${esc(tip)}"` : ""}>`
    + `<button type="button" class="ct-sort" data-ct-sort="${esc(key)}" aria-label="${esc(label)} ${next}으로 정렬">`
    + `<span>${esc(label)}${unit ? `<span class="ct-unit">(${esc(unit)})</span>` : ""}</span>`
    + `<span class="ct-mark" aria-hidden="true">${on ? SORT_MARK[state.order] : ""}</span></button></th>`;
}

/** 표 머리 — 정렬 단추(현재 열에는 ▲▼ 와 aria-sort). */
export function ctHeadHtml(columns, state, esc) {
  return `<thead><tr>${headCell("종목", "", "name", state, esc, { name: true })}${headCell("코드", "", "code", state, esc)}`
    + `${headCell("시장", "", "market", state, esc)}${headCell("업종", "", "sector", state, esc)}`
    + (columns || []).map(c => headCell(c.label, c.unit, c.key, state, esc, { num: true, formula: c.formula })).join("")
    + `<th scope="col" class="ct-th">기준</th><th scope="col" class="ct-th">조회 상태</th></tr></thead>`;
}

/** 조회 상태 칸 — 상태 글 + 값이 없는 까닭 · 근사 · 별도재무제표 풀이를 눈에 보이게. */
export function ctStatusHtml(row, esc) {
  const st = row.status || {};
  return `<span class="ct-badge" data-ct-status="${esc(st.code || "")}">${esc(st.text || DASH)}</span>`
    + ((row.notes || []).length ? `<ul class="ct-notes">${row.notes.map(n => `<li>${esc(n)}</li>`).join("")}</ul>` : "");
}

/** 줄 하나 — picked 는 비교에 담은 종목코드 집합. */
export function ctRowHtml(row, columns, marketNames, esc, picked) {
  const on = !!(picked && picked.has(row.code));
  const names = marketNames || {};
  const pick = `<button type="button" class="ct-pick" data-ct-pick="${esc(row.code)}" data-ct-name="${esc(row.name)}" aria-pressed="${on}" `
    + `aria-label="${esc(row.name)} ${on ? "비교에서 빼기" : "비교에 담기"}">${on ? "✓" : "＋"}</button>`;
  const cells = (columns || []).map(c => `<td class="ct-num" data-ct-metric="${esc(c.key)}">${esc(ctValueText(c, row.metrics && row.metrics[c.key]))}</td>`).join("");
  return `<tr data-ct-row="${esc(row.code)}"><td class="ct-name">${pick}<span class="ct-nm">${esc(row.name)}</span></td>`
    + `<td class="ct-code">${esc(row.code)}</td><td>${esc(row.market ? names[row.market] || row.market : DASH)}</td>`
    + `<td class="ct-sector">${esc(row.sector && row.sector.name ? row.sector.name : DASH)}</td>${cells}`
    + `<td class="ct-basis">${esc(row.basis || DASH)}</td><td class="ct-state">${ctStatusHtml(row, esc)}</td></tr>`;
}

/** 표 전체 — 결과가 없으면 안내 한 줄. */
export function ctTableHtml(data, state, esc, picked) {
  const cols = (data && data.columns) || [];
  const names = ctMarketNames(data);
  const span = 6 + cols.length;
  const body = data && data.rows && data.rows.length
    ? data.rows.map(r => ctRowHtml(r, cols, names, esc, picked)).join("")
    : `<tr><td colspan="${span}" class="ct-empty">조건에 맞는 종목이 없습니다. 검색어나 시장 · 업종을 바꿔 보세요.</td></tr>`;
  return `<table class="ct-table"><caption class="sr-only">수집 대상 종목의 투자 지표 표 — 열 머리 단추로 정렬합니다</caption>${ctHeadHtml(cols, state, esc)}<tbody>${body}</tbody></table>`;
}

/** 표 아래 글 — 기준일 · 출처 · 식 · 한계. 서버가 준 문장을 그대로 늘어놓는다. */
export function ctFootHtml(data, esc) {
  if (!data) return "";
  const p = t => `<p class="ct-foot">${esc(t)}</p>`;
  const formulas = (data.columns || []).map(c => `${c.label} = ${c.formula}`).join(" · ");
  return p(`종가 최신일 ${data.as_of || DASH} · 출처 ${data.source || DASH}`)
    + (formulas ? p(`식 — ${formulas}`) : "")
    + (data.limits || []).map(p).join("") + (data.notice ? p(data.notice) : "");
}

/** 비교에 담은 개수 글. */
export function ctPickText(count, max) { return `비교에 담은 종목 ${count}/${max}`; }

/** 새로고침 단추 — app.html 에 이미 있으면 그것, 없으면 「나란히 비교 보기」 앞에 JS 가 만든다(app.html 을 건드리지 않는다). */
function ensureRefreshButton($) {
  let btn = $("ct-refresh");
  if (btn) return btn;
  const go = $("ct-goto");
  if (!go || !go.parentNode || typeof document === "undefined") return null;
  btn = document.createElement("button");
  btn.type = "button"; btn.id = "ct-refresh"; btn.className = "btn-secondary text-xs"; btn.textContent = "새로고침";
  btn.title = "같은 시장 · 업종 · 검색 · 정렬 · 쪽으로 서버에서 다시 읽습니다 — 새로 계산하지 않습니다";
  go.parentNode.insertBefore(btn, go);
  return btn;
}

// ── 화면 연결 ────────────────────────────────────────────────────────────────────────────
/**
 * 표를 화면에 붙인다(한 번). 칸 id 는 app.html 지표 비교 view 의 `ct-*`.
 * deps — fetchPage(질의 문자열) → 서버 응답 · esc(글) → 이스케이프 · isPicked(코드) · pickedCount() · max · onPick(코드, 이름) → 담지 못한 까닭 글(없으면 빈 글)
 *        · refreshNote() → 새로고침 뒤 안내 글(선택 · 2026-11-05)
 * 돌려주는 것 — ensureLoaded() (아직 못 받았으면 받는다) · syncPicks() (담은 종목 표시만 다시) · reload()
 */
export function ctMount(deps) {
  const $ = id => document.getElementById(id);
  const host = $("ct-table");
  if (!host) return null;
  const { fetchPage, esc } = deps;
  let state = ctDefaultState();
  let last = null, seq = 0, timer = null, loading = false, stampNext = false;
  const refreshBtn = ensureRefreshButton($);

  const say = (text, color) => { const el = $("ct-msg"); if (el) { el.textContent = text || ""; el.style.color = color || "var(--text-mute)"; } };

  function syncPicks() {
    host.querySelectorAll("[data-ct-pick]").forEach(b => {
      const on = !!deps.isPicked(b.dataset.ctPick);
      b.setAttribute("aria-pressed", String(on));
      b.textContent = on ? "✓" : "＋";
      b.setAttribute("aria-label", `${b.dataset.ctName} ${on ? "비교에서 빼기" : "비교에 담기"}`);
    });
    const el = $("ct-picked");
    if (el) el.textContent = ctPickText(deps.pickedCount(), deps.max);
  }

  function render(data) {
    last = data;
    host.innerHTML = ctTableHtml(data, state, esc, new Set(data.rows.filter(r => deps.isPicked(r.code)).map(r => r.code)));
    const foot = $("ct-foot");
    if (foot) foot.innerHTML = ctFootHtml(data, esc);
    const m = $("ct-market"), s = $("ct-sector");
    if (m && m.options.length <= 1) m.innerHTML = ctFilterOptions(data.filters.markets, "전체 시장", esc, state.market);
    if (s && s.options.length <= 1) s.innerHTML = ctFilterOptions(data.filters.sectors, "전체 업종", esc, state.sector);
    const range = $("ct-range"); if (range) range.textContent = ctRangeText(data);
    const page = $("ct-page"); if (page) page.textContent = `${data.page} / ${data.pages}쪽`;
    const prev = $("ct-prev"), next = $("ct-next");
    if (prev) prev.disabled = data.page <= 1;
    if (next) next.disabled = data.page >= data.pages;
    syncPicks();
  }

  async function load() {
    const my = ++seq;
    const stamp = stampNext; stampNext = false;       // 새로고침 단추가 건 읽기에만 시각을 남긴다
    loading = true;
    say(last ? "불러오는 중…" : "불러오는 중… (처음 한 번은 수집 대상을 모두 계산해 몇 초 걸립니다)");
    host.setAttribute("aria-busy", "true");
    try {
      const data = await fetchPage(ctQueryString(state));
      if (my !== seq) return;
      state = { ...state, page: data.page };              // 서버가 끝을 넘은 쪽을 마지막 쪽으로 맞췄을 수 있다
      render(data);
      say(stamp && deps.refreshNote ? deps.refreshNote() : "");            // 새로고침으로 읽었으면 다시 읽은 시각 · 뜻을 남긴다(실패하면 시각을 찍지 않는다)
    } catch (e) {
      if (my === seq) say(e && e.message ? e.message : "지표 표를 받지 못했습니다.", "var(--red)");
    } finally {
      if (my === seq) { loading = false; host.removeAttribute("aria-busy"); if (refreshBtn) { refreshBtn.disabled = false; refreshBtn.setAttribute("aria-busy", "false"); } }
    }
  }

  const change = patch => { state = { ...state, ...patch, page: 1 }; load(); };
  const q = $("ct-q");
  if (q) q.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => change({ q: q.value.trim() }), CT_DEBOUNCE_MS); });
  const m = $("ct-market"), s = $("ct-sector");
  if (m) m.addEventListener("change", () => change({ market: m.value }));
  if (s) s.addEventListener("change", () => change({ sector: s.value }));
  const prev = $("ct-prev"), next = $("ct-next");
  if (prev) prev.addEventListener("click", () => { if (state.page > 1) { state = { ...state, page: state.page - 1 }; load(); } });
  if (next) next.addEventListener("click", () => { if (last && state.page < last.pages) { state = { ...state, page: state.page + 1 }; load(); } });
  host.addEventListener("click", ev => {
    const sort = ev.target.closest("[data-ct-sort]");
    if (sort) { state = ctNextSort(state, sort.dataset.ctSort); load(); return; }
    const pick = ev.target.closest("[data-ct-pick]");
    if (pick) {
      const note = deps.onPick(pick.dataset.ctPick, pick.dataset.ctName);   // 담지 못한 까닭이 있으면 글로 돌려받는다(예: 최대 8개)
      syncPicks();
      say(typeof note === "string" ? note : "");
    }
  });
  // 새로고침 — 같은 시장 · 업종 · 검색 · 정렬 · 쪽으로 서버에서 다시 읽는다(state 를 건드리지 않는다). 읽는 중에는 다시 눌러도 무시.
  if (refreshBtn) refreshBtn.addEventListener("click", () => {
    if (loading) return;
    stampNext = true;
    refreshBtn.disabled = true; refreshBtn.setAttribute("aria-busy", "true");
    load();
  });
  const go = $("ct-goto");
  if (go) go.addEventListener("click", () => { const t = $("co-compare-chips"); if (t) t.scrollIntoView({ behavior: "smooth", block: "start" }); });

  return {
    ensureLoaded() { if (!last && !loading) load(); },
    reload() { load(); },
    refresh() { if (!loading && refreshBtn) refreshBtn.click(); },
    syncPicks,
  };
}
