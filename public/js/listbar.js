// 목록 위 줄 — 필터 칩 + 새로고침 단추 + 안내 글을 모든 화면이 같은 모양 · 같은 동작으로 쓰는 공용 도우미(2026-11-05).
// 배경: 퀀트 대시보드 표에 필터 · 새로고침이 없다는 지적 → 화면 전수 점검 → 화면마다 따로 만들지 않고 이 한 곳을 쓴다.
// 규칙: 걸러 보는 것은 「이미 받은 줄 안」 이다(서버 인자가 없는 화면). 그 한계를 안내 글에서 숨기지 않는다.
// 새로고침의 뜻은 화면이 밝힌다 — 대부분 「서버에서 다시 읽기」 이고 새로 계산하지 않는다(다시 계산은 판 1 지문 조각을 건드릴 수 있어 쓰지 않는다).

/** 칩 묶음 하나 — { key, label, options: [{ value, label }], value }. value "" 는 「전체」. */
function groupHtml(esc, g) {
  const chips = g.options.map(o =>
    `<button type="button" class="qd-fchip text-xs" data-lb-filter="${esc(g.key)}" data-value="${esc(o.value)}" aria-pressed="${String(g.value ?? "") === String(o.value)}">${esc(o.label)}</button>`).join("");
  return `<div class="qd-frow"><span class="text-xs font-semibold" style="color:var(--text-dim);">${esc(g.label)}</span>${chips}</div>`;
}

/**
 * 목록 위 줄 HTML.
 * @param esc       HTML 이스케이프 함수(화면의 것을 그대로)
 * @param opts.groups   칩 묶음 배열(없으면 새로고침만)
 * @param opts.refresh  새로고침 단추를 보일지(기본 true) — 단추 글은 refreshLabel
 * @param opts.note     아래 한 줄 안내(걸린 조건 · 다시 읽은 시각 · 한계)
 * @param opts.label    접근성 이름
 */
export function listBarHtml(esc, opts = {}) {
  const groups = opts.groups || [];
  const refresh = opts.refresh === false ? "" : `<button type="button" class="btn-secondary text-xs" data-lb-refresh>${esc(opts.refreshLabel || "새로고침")}</button>`;
  // 칩이 없고 새로고침만 있으면 한 줄에 단추만 둔다
  const rows = groups.map(g => groupHtml(esc, g));
  if (refresh) {
    if (rows.length) rows[rows.length - 1] = rows[rows.length - 1].replace(/<\/div>$/, `${refresh}</div>`);
    else rows.push(`<div class="qd-frow">${refresh}</div>`);
  }
  return `<div class="qd-filter mb-2" role="group" aria-label="${esc(opts.label || "목록 필터")}">${rows.join("")}`
    + `<div class="text-xs" style="color:var(--text-mute);" role="status" aria-live="polite" data-lb-note>${esc(opts.note || "")}</div></div>`;
}

/** 이미 받은 줄을 거른다 — filters { key: value } · getters { key: row => 그 줄의 값 }. 값이 빈 글이면 그 칸은 안 건다. 모르는 key 는 무시. */
export function applyFilters(rows, filters, getters) {
  const active = Object.entries(filters || {}).filter(([k, v]) => v !== "" && v != null && typeof (getters || {})[k] === "function");
  if (!active.length) return rows.slice();
  return rows.filter(r => active.every(([k, v]) => String(getters[k](r)) === String(v)));
}

/** 칩 값이 허용 목록 안에 있는지(모르는 낱말은 무시하려고). */
export function isAllowed(groups, key, value) {
  const g = groups.find(x => x.key === key);
  return !!g && g.options.some(o => String(o.value) === String(value));
}

/** 「조건 매수 · KOSPI — 받은 N줄 중 M줄」 같은 걸린 조건 글. 거는 조건이 없으면 빈 글. */
export function filterSummary(groups, filters, total, shown, unit = "줄") {
  const parts = groups.map(g => {
    const v = (filters || {})[g.key];
    if (v === "" || v == null) return "";
    const o = g.options.find(x => String(x.value) === String(v));
    return o ? o.label : "";
  }).filter(Boolean);
  return parts.length ? `조건 ${parts.join(" · ")} — 받은 ${total}${unit} 중 ${shown}${unit}` : "";
}

/** 새로고침 뒤 안내 — 「다시 읽었습니다(HH:MM)」 + 화면이 밝히는 뜻. */
export function refreshStamp(meaning = "서버에서 다시 읽었습니다", now = new Date()) {
  const clock = now.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Seoul" });
  return `${meaning}(${clock})`;
}

/** 서버가 새로고침 요청에 붙인 안내(`resp.refresh` — {requested, reused_cache, min_age_seconds})를 한 줄로. 요청이 아니었으면 빈 글. */
export function serverRefreshNote(refresh, now = new Date()) {
  if (!refresh || !refresh.requested) return "";
  const clock = refreshStamp("", now).replace(/^\(|\)$/g, "");
  return refresh.reused_cache
    ? `${refresh.min_age_seconds}초 안에 받은 값이라 그대로 보입니다(${clock})`
    : `외부 시세를 다시 받았습니다(${clock})`;
}

/**
 * 단추 연결 — root(화면이 다시 그려도 사라지지 않는 바깥 요소)에서 클릭을 받는다.
 * onFilter(key, value) · onRefresh() 중 필요한 것만 준다. 받는 중 다시 누르는 것은 onRefresh 쪽이 막는다.
 */
export function bindListBar(root, { onFilter, onRefresh } = {}) {
  if (!root || root.__lbBound) return;
  root.__lbBound = true;
  root.addEventListener("click", ev => {
    const t = ev.target && ev.target.closest ? ev.target : null;
    if (!t) return;
    const chip = t.closest("button[data-lb-filter]");
    if (chip && root.contains(chip)) { if (onFilter) onFilter(chip.dataset.lbFilter, chip.dataset.value); return; }
    const rf = t.closest("button[data-lb-refresh]");
    if (rf && root.contains(rf) && onRefresh) onRefresh();
  });
}
