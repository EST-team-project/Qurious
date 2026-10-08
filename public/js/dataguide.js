/* 자료 안내 — 「데이터」 묶음 둘째 화면(데이터 관제 바로 아래 · 모든 로그인 사용자) (2026-10-08)
 *
 * 화면 설계 결정(Figma 「자료 안내」 · 03 [결정] 안 B 1280 · 390 + 안 A 의 「자료 한 장」 서랍 · 05 [결정] 정할 것 넷):
 *   한 장 보고서 — 숫자 띠 → 무엇이 있나(연도별 바둑판 · 자료 목록) → 어떻게 모으나(흐름) → 무엇을 읽나(길잡이 · 틀리기 쉬운 것).
 *   목록 줄 · 바둑판 칸 · 길잡이의 자료 이름을 누르면 오른쪽에서 「자료 한 장」 서랍이 열린다(폭 390 은 화면 전체).
 * 읽는 API 는 하나 — GET /api/data/guide(로그인 뒤). 설명은 대장 생성물, 숫자는 상태 · 백업 목록에서 서버가 묶는다.
 *   - 개발 정보(표 이름 · 읽는 길 · 백업 · 받는 명령)는 서버가 관리자에게만 싣는다 — 이 파일은 응답에 있으면 그릴 뿐 숨기지 않는다
 *     (CSS 로 숨기면 응답에는 남는다 · 결정 ①).
 *   - 늦음 판정 색은 데이터 관제 몫이다 — 여기는 마지막 날짜를 글자로만 보이고 「데이터 관제 →」 로 보낸다(겹치지 않게).
 *   - 값 미리보기 · 내려받기 단추는 두지 않는다(원자료 재배포 금지 · 공공누리 제4유형).
 *   - 화면 이름(쓰는 화면 · 어디서)은 메뉴 표(core.js GNB_MENUS)에서 읽는다 — 이름을 여기 따로 적지 않는다.
 * 강사님 파일(app.html · main.js · core.js)에는 뿌리 칸 · 부르는 줄 · 메뉴 한 줄만 두고 그리기는 모두 여기서 한다(datahub.js 처럼).
 *
 * 응답을 읽는 변수 이름은 객체마다 하나로 고정한다 — 시험 TC-DG-04 가 「변수.칸」 을 정규식으로 모아 서버 응답과 맞댄다
 * (서버가 칸 이름을 바꾸면 화면은 오류 없이 빈칸을 그리므로 시험이 먼저 깨지게).
 *   r 응답 · st 숫자 · g 설명 · grp 묶음 · it 자료 · s 자료 숫자 · src 출처 · run 매일 수집 · lastRun 마지막 회차 · gx 단계 묶음 ·
 *   fbox 흐름 상자 · fnote 흐름 덧말 · task 길잡이 · pit 틀리기 쉬운 것 · ear 이른 해 · mk 시장
 */
import { api, escHtml, fmt, setToast } from "/js/common.js";
import { GNB_MENUS, navigate } from "/js/core.js";

const VIEW = "data-guide";
const SECTIONS = [["have", "무엇이 있나"], ["collect", "어떻게 모으나"], ["read", "무엇을 읽나"]];
//: 바둑판 칸 진하기 — 그 자료에서 가장 많은 해를 1 로 볼 때(Figma 범례 · 설계 03 문서 4절)
const LEVELS = [[0.9, 4, "0.9 이상"], [0.7, 3, "0.7 이상"], [0.4, 2, "0.4 이상"], [0, 1, "그 밑"]];
//: 자료 줄의 숫자 상태 → 칸 모양(서버 data_guide.ITEM_WHY 의 열쇠와 같다 — TC-DG-04 가 맞댄다)
const STATE_TONE = { ok: "", counting: "dg-wait", partial: "dg-wait", none: "dg-none", no_link: "dg-none", error: "dg-err" };
//: 서버가 「자료 상태를 세는 중」(status_pending) · 「줄 수를 세는 중」(total_state counting)이면 설명을 먼저 그리고 잠시 뒤 몇 번만
//: 다시 묻는다 — 주기적으로 다시 묻지는 않는다(숫자는 하루 한 번 바뀐다 · 설계 12절 요소 1). 줄 수 세기는 컨테이너에서 15 ~ 20초.
const PENDING_RETRY_MS = 4000;
const PENDING_MAX_TRIES = 6;
//: 자료 목록은 처음 다섯 줄 + 「… 모두 N줄」(Figma 안 B 1280 · 390) — 「전체」 일 때만 접는다(묶음을 고르면 그 묶음 전부)
const LIST_FOLD = 5;

let res = null;              // 마지막 응답
let pickedGroup = "";        // 자료 목록 거름("" = 전체)
let listOpen = false;        // 「전체」 목록을 다 펼쳤나
let openKey = null;          // 열린 서랍의 자료 열쇠
let opener = null;           // 서랍을 연 단추 — 닫으면 포커스를 돌려준다
let seq = 0;                 // 늦게 온 응답이 새로 고친 화면을 덮지 않게
let pendingTries = 0;
let retryTimer = null;
const openBoxes = new Set(); // 펼친 흐름 상자

// ── 작은 도구 ──────────────────────────────────────────────────────────
const VIEW_LABELS = (() => {
  const out = {};
  Object.values(GNB_MENUS).forEach(menu => menu.items.forEach(mi => { if (mi.key && !mi.href) out[mi.key] = mi.label; }));
  return out;
})();
function hm(iso) { return iso ? iso.slice(11, 16) : ""; }
function mmdd(iso) { return iso ? `${iso.slice(5, 7)}-${iso.slice(8, 10)}` : "—"; }
/** 61.7만 · 5,391 — 바둑판 · 연도별 막대 */
function man1(n) { return n == null ? "—" : n >= 10000 ? `${(n / 10000).toFixed(1)}만` : fmt(n); }
/** 449만 · 77만 · 2,922 — 자료 목록 */
function man0(n) { return n == null ? "—" : n >= 10000 ? `${fmt(Math.round(n / 10000))}만` : fmt(n); }
/** 끝 날은 올해면 MM-DD, 아니면 날짜 그대로(Figma 「2020-01-02 ~ 10-06」) */
function endText(iso, today) { return !iso ? "—" : iso.slice(0, 4) === (today || "").slice(0, 4) ? iso.slice(5, 10) : iso.slice(0, 10); }
function periodText(s, today, full = false) {
  const end = full ? (s.last || "—") : endText(s.last, today);
  if (s.first) return `${s.first} ~ ${end}`;
  if (s.first_year) return `${s.first_year} ~ ${end}`;
  if (s.last) return `~ ${end}`;
  return "—";
}
/** 좁은 칸에서도 날짜 가운데(「2026-」 / 「10-07」)서 끊지 않게 — 끊어야 하면 「~」 앞뒤에서 */
function periodHtml(s, today, full = false) {
  return periodText(s, today, full).split(" ~ ").map(part => `<span class="dg-nowrap">${escHtml(part)}</span>`).join(" ~ ");
}
function itemByKey(key) { return (res?.guide?.items || []).find(it => it.key === key); }
function statOf(key) { return res?.stats?.items?.[key] || { state: "none", why: "" }; }
function sourceByKey(key) { return (res?.guide?.sources || []).find(src => src.key === key); }
function externalSources() { return (res?.guide?.sources || []).filter(src => src.kind === "바깥"); }
function runnerGroup(key) { return (res?.stats?.runner?.groups || []).find(gx => gx.key === key); }
/** 이용 조건 표시 → 알약 색. 대장에 새 표시가 생기면 회색으로 보인다(깨지지 않는다). */
function tagTone(tag) {
  if (/우리 계산/.test(tag)) return "violet";
  if (/공개 자료/.test(tag)) return "green";
  if (/비상업|출처 표시/.test(tag)) return "amber";
  if (/제목 · 링크|기사마다/.test(tag)) return "blue";
  return "gray";
}
function tagPill(tag) { return tag ? `<span class="dg-tag dg-tag--${tagTone(tag)}">${escHtml(tag)}</span>` : ""; }
function viewLink(key) {
  const label = VIEW_LABELS[key];
  return label ? `<button type="button" class="dg-view" data-view-go="${escHtml(key)}">${escHtml(label)} ›</button>` : "";
}
/** 화면 링크들 — 열 수 있는 화면이 없으면 「화면 없음 · 백업 파일」 처럼 대장의 읽는 길(쉬운 말)을 함께 */
function viewLinks(keys, hint = "") {
  const links = (keys || []).map(viewLink).filter(Boolean);
  return links.length ? links.join(`<span class="dg-sep"> · </span>`) : `<span class="q-muted">화면 없음${hint ? ` · ${escHtml(hint)}` : ""}</span>`;
}
function itemButton(key, label) {
  const it = itemByKey(key);
  if (!it) return "";
  return `<button type="button" class="dg-item" data-item="${escHtml(key)}" aria-haspopup="dialog" aria-expanded="false">${escHtml(label || it.name)}</button>`;
}

// ── 머리 · 숫자 띠 ─────────────────────────────────────────────────────
function headHtml(r) {
  const st = r.stats;
  const at = st.measured_at || r.checked_at;
  return `<div class="dg-head"><div><h2>자료 안내</h2>
      <p class="dg-lead">Qurious 가 모으는 자료가 무엇이고, 어떻게 모으고, 무엇을 읽으면 되는지 봅니다 · 지금 자료가 며칠 것까지 있는지는
        <button type="button" class="dg-link dg-go-status">데이터 관제 →</button></p></div>
      <div class="dg-head-right"><span class="q-muted">숫자 기준 ${escHtml(mmdd(at))} ${escHtml(hm(at))}</span>
        <button type="button" class="btn-secondary dg-refresh"><i class="fa-solid fa-rotate" aria-hidden="true"></i> 새로 고침</button></div></div>
    <nav class="dg-toc" aria-label="이 화면의 절">${SECTIONS.map(([k, label]) => `<button type="button" class="dg-toc-btn" data-jump="${k}">${label}</button>`).join("")}</nav>
    ${st.note ? `<p class="dg-note" role="status">${escHtml(st.note)}</p>` : ""}
    ${(st.problems || []).map(msg => `<p class="dg-note dg-note--err">${escHtml(msg)}</p>`).join("")}`;
}

function bandHtml(r) {
  const g = r.guide, st = r.stats, run = st.runner || {};
  const ext = externalSources();
  const early = (st.early || []).map(ear => {
    const it = itemByKey(ear.item);
    return it ? `${it.name} ${ear.year} 년부터` : "";
  }).filter(Boolean).join(" · ");
  const time = (run.schedule || "").replace(/^매일\s*/, "");
  const groupsLine = (run.groups || []).map(gx => `${gx.key} ${gx.count}`).join(" · ");
  const total = st.total_rows != null ? `약 ${fmt(Math.round(st.total_rows / 10000))}만`
    : st.total_state === "counting" ? "세는 중…" : "—";
  const cards = [
    // 묶음 이름 안에 「 · 」 가 있어(공시 · 재무) 같은 기호로 이으면 9 묶음이 11 개로 읽힌다 — 이 목록만 쉼표로 잇는다
    ["have-list", "자료 묶음", `${g.groups.length}`, g.groups.map(grp => grp.name).join(", ")],
    ["collect", "출처", `${ext.length}곳`, ext.slice(0, 4).map(src => src.name).join(" · ") + (ext.length > 4 ? " …" : "")],
    ["have", "모은 기간", st.first ? `${st.first} ~` : "—", st.first ? (early || "가장 이른 시세 날부터") : "이 PC 에는 모은 자료가 없습니다"],
    // 단계 목록이 없는 PC(팀원 PC 대부분)는 시각만 — 「0단계」 로 보이지 않게(설계 11절 경우 표 「비어 있음」)
    ["collect", "매일 낮 수집", run.total_steps ? `${time} · ${run.total_steps}단계` : (time || "—"),
      run.total_steps ? groupsLine : "이 PC 에서는 매일 수집을 돌리지 않습니다"],
    ["have-list", "모은 줄", total, st.total_state === "none" ? "이 PC 에는 모은 자료가 없습니다"
      : st.total_partial ? "이 PC 에 없는 자료는 빼고 · 부를 때 계산하는 자료도 빼고" : "주봉처럼 부를 때 계산하는 자료는 빼고"],
  ];
  return `<div class="dg-band">${cards.map(([jump, k, v, d]) => `<button type="button" class="dg-band-card" data-jump="${jump}">
      <span class="dg-band-k">${k}</span><strong class="dg-band-v">${escHtml(v)}</strong><span class="dg-band-d">${escHtml(d)}</span></button>`).join("")}</div>`;
}

function sectionHead(key) {
  const label = SECTIONS.find(([k]) => k === key)[1];
  return `<h3 class="dg-sec" id="dg-sec-${key}" tabindex="-1"><span>${label}</span></h3>`;
}

// ── 무엇이 있나 — 연도별 바둑판(넓은 화면) · 기간 막대(좁은 화면) ──────────────
function gridRows(r) {
  return r.guide.items.filter(it => it.grid && Object.keys(r.stats.items[it.key]?.years || {}).length);
}
function level(n, max) {
  if (!n) return 0;
  const ratio = max ? n / max : 0;
  return LEVELS.find(([t]) => ratio >= t)[1];
}
function gridHtml(r) {
  const rows = gridRows(r);
  const head = `<div class="dg-card-head"><h4 class="dg-h">연도별로 얼마나 있나</h4>
    <span class="q-muted">칸 = 그해 모은 줄 수 · 칸을 누르면 그 자료 한 장</span></div>`;
  if (!rows.length) {
    return `<div class="card dg-card">${head}<p class="dg-empty">모은 자료가 있는 PC 에서 보입니다 — 이 PC 에는 연도별 숫자가 없습니다.</p></div>`;
  }
  const years = r.stats.years || [];
  const body = rows.map(it => {
    const s = r.stats.items[it.key];
    const ys = s.years || {};
    const max = Math.max(1, ...Object.values(ys));
    const cells = years.map(y => {
      const n = ys[y];
      const lv = level(n, max);
      if (!lv) return `<td><span class="dg-cell dg-l0" title="${escHtml(`${it.grid} ${y}년 — 없음`)}">·</span></td>`;
      return `<td><button type="button" class="dg-cell dg-l${lv}" data-item="${escHtml(it.key)}" aria-haspopup="dialog"
        aria-label="${escHtml(`${it.grid} ${y}년 ${fmt(n)}줄 — 자료 한 장 열기`)}" title="${escHtml(`${it.grid} ${y}년 ${fmt(n)}줄`)}">${man1(n)}</button></td>`;
    }).join("");
    return `<tr><th scope="row">${itemButton(it.key, it.grid)}</th>${cells}<td class="dg-span">${escHtml(periodText(s, r.checked_at))}</td></tr>`;
  }).join("");
  const lastYear = years[years.length - 1];
  const asOf = r.stats.as_of;
  const notes = [asOf && lastYear && asOf.startsWith(lastYear) ? `${lastYear} 은 ${mmdd(asOf)} 까지` : "",
    ...rows.filter(it => it.note).map(it => `${it.grid} — ${it.note}`)].filter(Boolean);
  const legend = LEVELS.map(([, lv, label]) => `<span><i class="dg-sw dg-l${lv}"></i>${label}</span>`).join("")
    + `<span><i class="dg-sw dg-l0"></i>없음</span>`;
  return `<div class="card dg-card dg-grid-card">${head}
    <div class="dg-grid-wrap"><table class="dg-grid"><thead><tr><th scope="col"><span class="sr-only">자료</span></th>
      ${years.map(y => `<th scope="col">${y}</th>`).join("")}<th scope="col" class="dg-span">처음 ~ 마지막</th></tr></thead>
      <tbody>${body}</tbody></table></div>
    ${barsHtml(r, rows, years)}
    <div class="dg-legend"><span class="q-muted">진하기 = 그 자료에서 가장 많은 해를 1 로 볼 때</span>${legend}
      ${notes.length ? `<span class="q-muted dg-legend-note">${escHtml(notes.join(" · "))}</span>` : ""}</div>
    ${r.stats.backup_at ? `<p class="dg-foot">연도별 숫자는 ${escHtml(mmdd(r.stats.backup_at))} ${escHtml(hm(r.stats.backup_at))} 백업 기준입니다.</p>` : ""}</div>`;
}
/** 폭 390 — 바둑판을 가로로 넘기지 않고 「처음 ~ 마지막」 막대로 바꾼다(Figma 7:2) */
function barsHtml(r, rows, years) {
  if (!years.length) return "";
  const t0 = Date.parse(`${years[0]}-01-01`), t1 = Date.parse(`${years[years.length - 1]}-12-31`);
  const pos = iso => Math.min(100, Math.max(0, ((Date.parse(iso) - t0) / (t1 - t0)) * 100));
  const axis = years.filter((y, i) => i % 2 === 0).map(y => `<span style="left:${pos(`${y}-01-01`).toFixed(1)}%">${y}</span>`).join("");
  const lines = rows.map(it => {
    const s = r.stats.items[it.key];
    const first = s.first || (s.first_year ? `${s.first_year}-01-01` : null);
    const last = s.last || `${years[years.length - 1]}-12-31`;
    if (!first) return "";
    const left = pos(first), width = Math.max(1.5, pos(last) - left);
    return `<li>${itemButton(it.key, it.grid)}<span class="dg-track" title="${escHtml(periodText(s, r.checked_at, true))}">
      <span class="dg-bar" style="left:${left.toFixed(1)}%;width:${width.toFixed(1)}%"></span></span></li>`;
  }).join("");
  return `<div class="dg-bars" aria-label="자료마다 처음 ~ 마지막"><div class="dg-axis">${axis}</div><ul>${lines}</ul>
    <p class="dg-foot">막대 = 처음 ~ 마지막 날 · 그 밖의 자료는 아래 목록의 자료 한 장에서 봅니다</p></div>`;
}

// ── 무엇이 있나 — 자료 목록 ──────────────────────────────────────────────
function listRowsHtml(r) {
  const items = r.guide.items.filter(it => !pickedGroup || it.group === pickedGroup);
  const foldable = !pickedGroup && items.length > LIST_FOLD;
  const shown = foldable && !listOpen ? items.slice(0, LIST_FOLD) : items;
  const more = !foldable ? "" : listOpen
    ? `<tr class="dg-more-row"><td colspan="7"><button type="button" class="dg-more" aria-expanded="true">접기 — 처음 ${LIST_FOLD}줄만</button></td></tr>`
    : `<tr class="dg-more-row"><td colspan="7"><button type="button" class="dg-more" aria-expanded="false">… 모두 ${items.length}줄 ·
        ${escHtml(items.slice(LIST_FOLD).map(it => it.name).join(" · "))} <strong>모두 보기</strong></button></td></tr>`;
  return shown.map(it => {
    const s = statOf(it.key);
    const tone = STATE_TONE[s.state] ?? "";
    const rowsCell = s.rows != null ? man0(s.rows) : (s.state === "counting" ? "세는 중…" : "—");
    return `<tr data-item="${escHtml(it.key)}">
      <td class="dg-name">${itemButton(it.key)}</td>
      <td class="dg-line">${escHtml(it.line)}</td>
      <td class="dg-period ${tone}" title="${escHtml(s.why || "")}">${escHtml(periodText(s, r.checked_at))}</td>
      <td class="dg-num ${tone}" title="${escHtml(s.why || (s.rows_from === "backup" ? "백업 목록 기준" : ""))}">${escHtml(rowsCell)}</td>
      <td class="dg-update">${escHtml(it.update)}</td>
      <td class="dg-terms">${tagPill(it.tag)}</td>
      <td class="dg-views">${viewLinks(it.views, it.read_hint)}</td></tr>`;
  }).join("") + more;
}
function listHtml(r) {
  const g = r.guide;
  const chips = [["", `전체 ${g.items.length}`], ...g.groups.map(grp => [grp.key, `${grp.name} ${grp.items}`])]
    .map(([k, label]) => `<button type="button" class="dg-chip" data-group="${escHtml(k)}" aria-pressed="${k === pickedGroup}">${escHtml(label)}</button>`).join("");
  return `<div class="card dg-card dg-list" id="dg-sec-have-list" tabindex="-1">
    <div class="dg-card-head"><h4 class="dg-h">자료 목록</h4><span class="q-muted">줄을 누르면 오른쪽에 자료 한 장이 열립니다</span></div>
    <div class="dg-chips" role="group" aria-label="자료 묶음으로 거르기">${chips}</div>
    <div class="dg-table-wrap"><table class="dg-table"><thead><tr><th scope="col">자료</th><th scope="col">한 줄 설명</th><th scope="col">기간</th>
      <th scope="col" class="dg-num">줄 수</th><th scope="col">갱신</th><th scope="col">이용 조건</th><th scope="col">쓰는 화면</th></tr></thead>
      <tbody>${listRowsHtml(r)}</tbody></table></div></div>`;
}

// ── 어떻게 모으나 — 흐름 한 장 ────────────────────────────────────────────
function flowHtml(r) {
  const run = r.stats.runner || {};
  const lastRun = run.last;
  const ext = externalSources();
  const boxes = r.guide.flow || [];
  const shown = new Set(boxes.map(fbox => fbox.key).concat((r.guide.flow_notes || []).map(fnote => fnote.key)));
  const time = (run.schedule || "매일 12:30").replace(/^매일\s*/, "");
  const right = `${lastRun?.started_at ? `${mmdd(lastRun.started_at)} 회차${lastRun.minutes != null ? ` ${Math.round(lastRun.minutes)}분` : ""} · ` : "이 PC 에서는 매일 수집을 돌리지 않습니다 · "}`
    + (r.viewer?.admin ? `단계마다 걸린 시간은 <button type="button" class="dg-link dg-go-runner">수집 일정 · 단계 →</button>`
      : `지금 상태는 <button type="button" class="dg-link dg-go-status">데이터 관제 →</button>`);
  const parts = boxes.map((fbox, i) => {
    const gx = runnerGroup(fbox.key);
    // 상자 글은 대장의 짧은 설명(Figma 그대로) · 전체 이름(출처 · 자료)은 마우스를 올리면 보인다
    const names = fbox.key === "출처" ? ext.map(src => src.name) : (fbox.items || []).map(k => itemByKey(k)?.name).filter(Boolean);
    const text = fbox.text || names.join(" · ");
    const full = names.length ? ` title="${escHtml(names.join(" · "))}"` : "";
    const title = fbox.key === "출처" ? `${fbox.title} ${ext.length}곳` : fbox.title;
    const soft = fbox.key === "백업" ? "dg-flow-box--soft" : "";
    const mark = gx?.attention ? `<span class="dg-flow-mark" title="확인할 단계가 있습니다 — 데이터 관제에서 봅니다">확인할 단계 ${gx.attention}</span>` : "";
    const arrow = i === 0 ? "" : `<div class="dg-flow-arrow" aria-hidden="true"><span>${escHtml(fbox.key)}${gx ? ` ${gx.count}` : ""}</span><i class="fa-solid fa-arrow-right"></i></div>`;
    const box = gx && gx.steps.length
      ? `<button type="button" class="dg-flow-box ${soft}" data-box="${escHtml(fbox.key)}" aria-expanded="${openBoxes.has(fbox.key)}"
          aria-controls="dg-steps"${full}><strong>${escHtml(title)}</strong><span>${escHtml(text)}</span>${mark}</button>`
      : `<div class="dg-flow-box ${soft}"${full}><strong>${escHtml(title)}</strong><span>${escHtml(text)}</span></div>`;
    return arrow + box;
  }).join("");
  const opened = [...openBoxes].map(runnerGroup).filter(Boolean);
  const steps = opened.length ? opened.map(gx => `<p><strong>${escHtml(gx.key)} ${gx.count}단계</strong> — ${escHtml(gx.steps.join(" · "))}</p>`).join("")
    : `<p class="q-muted">상자를 누르면 그 묶음의 단계 이름이 펼쳐집니다.</p>`;
  const others = (run.groups || []).filter(gx => !shown.has(gx.key));
  const notes = (r.guide.flow_notes || []).map(fnote => {
    const gx = fnote.key ? runnerGroup(fnote.key) : null;
    return `<li>${escHtml(fnote.text)}${gx ? ` <span class="q-muted">(${escHtml(gx.key)} ${gx.count}단계)</span>` : ""}</li>`;
  }).join("");
  return `<div class="card dg-card dg-flow-card">
    <div class="dg-card-head"><h4 class="dg-h">매일 낮 ${escHtml(time)} — 받고 · 계산하고 · 백업합니다</h4><span class="q-muted dg-flow-right">${right}</span></div>
    <div class="dg-flow">${parts}</div>
    <div class="dg-steps" id="dg-steps" role="region" aria-label="단계 이름">${steps}</div>
    ${others.length ? `<p class="q-muted dg-foot">그 밖의 단계 — ${others.map(gx => `${escHtml(gx.key)} ${gx.count}`).join(" · ")}</p>` : ""}
    <ul class="dg-notes">${notes}</ul></div>`;
}

// ── 무엇을 읽나 — 길잡이 · 틀리기 쉬운 것 ──────────────────────────────────
function tasksHtml(r) {
  const rows = (r.guide.tasks || []).map(task => `<tr>
      <td class="dg-task">${escHtml(task.title)}</td>
      <td class="dg-reads">${(task.items || []).map(k => itemButton(k)).filter(Boolean).join(`<span class="dg-sep"> · </span>`)}
        ${task.text ? `<span class="dg-task-text">${escHtml(task.text)}</span>` : ""}</td>
      <td class="dg-where">${viewLinks(task.views)}${task.dev ? `<code class="dg-dev-line">${escHtml(task.dev)}</code>` : ""}</td></tr>`).join("");
  return `<div class="card dg-card">
    <div class="dg-card-head"><h4 class="dg-h">하려는 일에 맞는 자료</h4><span class="q-muted">「어디서」 를 누르면 그 화면으로 갑니다</span></div>
    <div class="dg-table-wrap"><table class="dg-table dg-tasks"><thead><tr><th scope="col">하려는 일</th><th scope="col">읽을 자료</th><th scope="col">어디서</th></tr></thead>
      <tbody>${rows}</tbody></table></div></div>`;
}
function pitfallsHtml(r) {
  const pits = r.guide.pitfalls || [];
  if (!pits.length) return "";
  const body = pits.map(pit => `<li><strong>${escHtml(pit.title)}</strong><p>${escHtml(pit.text)}</p>
      ${(pit.items || []).length ? `<div class="dg-pit-items">${pit.items.map(k => itemButton(k)).filter(Boolean).join(`<span class="dg-sep"> · </span>`)}</div>` : ""}</li>`).join("");
  return `<div class="card dg-card dg-pit">
    <button type="button" class="dg-pit-toggle" aria-expanded="false" aria-controls="dg-pit-body">
      <span class="dg-pit-title">틀리기 쉬운 것 ${pits.length}</span>
      <span class="dg-pit-preview">${escHtml(pits.map(pit => pit.title).join(" · "))}</span>
      <i class="fa-solid fa-chevron-down" aria-hidden="true"></i></button>
    <ol class="dg-pit-body" id="dg-pit-body" hidden>${body}</ol></div>`;
}

function pageHtml(r) {
  return `${headHtml(r)}${bandHtml(r)}
    ${sectionHead("have")}${gridHtml(r)}${listHtml(r)}
    ${sectionHead("collect")}${flowHtml(r)}
    ${sectionHead("read")}${tasksHtml(r)}${pitfallsHtml(r)}`;
}

// ── 자료 한 장(서랍) ──────────────────────────────────────────────────────
function drawerRoot() {
  let root = document.getElementById("dg-drawer");
  if (root) return root;
  root = document.createElement("div");
  root.id = "dg-drawer";
  root.innerHTML = `<div class="dg-dim"></div>
    <aside class="dg-panel" role="dialog" aria-modal="true" aria-labelledby="dg-d-title">
      <div class="dg-d-head"><h3 id="dg-d-title">자료 한 장</h3>
        <button type="button" class="dg-d-close">닫기 <i class="fa-solid fa-xmark" aria-hidden="true"></i></button></div>
      <div class="dg-d-body"></div></aside>`;
  document.body.appendChild(root);
  root.addEventListener("click", onDrawerClick);
  root.addEventListener("keydown", trapTab);
  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && root.classList.contains("open")) { e.preventDefault(); closeGuideDrawer(); }
  });
  return root;
}
/** 서랍 안에서 Tab 이 서랍 밖으로 나가지 않게(aria-modal) — 처음 · 끝에서 돌린다 */
function trapTab(e) {
  if (e.key !== "Tab") return;
  const panel = document.querySelector("#dg-drawer .dg-panel");
  const f = [...panel.querySelectorAll("button, [href], [tabindex]:not([tabindex='-1'])")].filter(el => !el.disabled && el.offsetParent !== null);
  if (!f.length) return;
  if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
  else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
}
function rowHtml(k, v) { return v ? `<div class="dg-d-row"><span class="dg-d-k">${k}</span><span class="dg-d-v">${v}</span></div>` : ""; }
function drawerHtml(it, s) {
  const srcs = (it.sources || []).map(sourceByKey).filter(Boolean);
  const years = s.years || {};
  const ys = Object.keys(years);
  const max = Math.max(1, ...Object.values(years));
  const foot = [s.last && ys.length && s.last.startsWith(ys[ys.length - 1]) ? `${ys[ys.length - 1]} 은 ${mmdd(s.last)} 까지` : "",
    s.markets ? `시장별 — ${s.markets.map(mk => `${mk.name} ${man0(mk.rows)}`).join(" · ")}` : "", it.note].filter(Boolean).join(" · ");
  const bars = ys.length ? `<section class="dg-d-sec"><h4>연도별${s.markets ? " · 시장별" : ""}</h4>
      <ul class="dg-d-years">${ys.map(y => `<li><span>${y}</span><span class="dg-d-track"><span style="width:${((years[y] / max) * 100).toFixed(1)}%"></span></span>
        <span class="dg-d-n">${man1(years[y])}</span></li>`).join("")}</ul>
      ${foot ? `<p class="dg-foot">${escHtml(foot)}</p>` : ""}</section>` : "";
  const devRows = it.dev ? [["표 · 키", [it.dev.tables.join(" · "), it.dev.keys].filter(Boolean).join(" — ")],
    ["읽는 길", it.dev.read], ["백업", it.dev.backup], ["받는 명령", it.dev.command]].filter(([, v]) => v) : [];
  const dev = it.dev ? `<section class="dg-d-sec dg-d-dev">
      <button type="button" class="dg-dev-toggle" aria-expanded="false" aria-controls="dg-dev-body">개발 정보 <span class="dg-admin">관리자</span>
        <i class="fa-solid fa-chevron-down" aria-hidden="true"></i></button>
      <dl class="dg-dev" id="dg-dev-body" hidden>${devRows.map(([k, v]) => `<div><dt>${k}</dt><dd><code>${escHtml(v)}</code>
          <button type="button" class="dg-copy" data-copy="${escHtml(v)}" aria-label="${k} 복사"><i class="fa-regular fa-copy" aria-hidden="true"></i></button></dd></div>`).join("")}</dl></section>` : "";
  return `<p class="dg-d-line">${escHtml(it.line)}</p>
    <div class="dg-d-tiles">
      <div class="dg-d-tile"><span>기간</span><strong>${periodHtml(s, "", true)}</strong></div>
      <div class="dg-d-tile"><span>줄 수</span><strong>${s.rows != null ? fmt(s.rows) : s.state === "counting" ? "세는 중…" : "—"}</strong>
        ${s.rows_from === "backup" ? `<small>백업 목록 기준</small>` : ""}</div>
      <div class="dg-d-tile"><span>범위</span><strong>${escHtml(it.scope)}</strong></div>
      <div class="dg-d-tile"><span>갱신</span><strong>${escHtml(it.update)}</strong></div></div>
    ${s.why ? `<p class="dg-d-why">${escHtml(s.why)}</p>` : ""}
    ${bars}
    <section class="dg-d-sec"><h4>어떻게 모았나</h4>
      ${rowHtml("출처", srcs.map(src => `${escHtml(src.name)} <span class="q-muted">— ${escHtml(src.org)}</span>`).join("<br>"))}
      ${rowHtml("모으는 법", escHtml(it.how))}
      ${rowHtml("공개", srcs.filter(src => src.kind === "바깥").map(src => escHtml(src.release)).join("<br>"))}
      ${rowHtml("다듬기", escHtml(it.processing))}</section>
    <section class="dg-d-sec"><h4>무엇에 쓰나</h4>
      ${rowHtml("쓰는 곳", escHtml(it.uses))}
      ${rowHtml("쓰지 말 곳", escHtml(it.avoid))}
      ${rowHtml("쓰는 화면", viewLinks(it.views, it.read_hint))}</section>
    <section class="dg-d-sec"><h4>이용 조건</h4>
      <p class="dg-d-terms">${tagPill(it.tag)}</p>
      ${srcs.map(src => `<p class="dg-d-terms-line"><strong>${escHtml(src.name)}</strong> — ${escHtml(src.terms)}</p>`).join("")}</section>
    ${dev}`;
}
function renderDrawer() {
  const it = itemByKey(openKey);
  const root = drawerRoot();
  if (!it) { closeGuideDrawer(); return; }
  root.querySelector("#dg-d-title").textContent = it.name;
  root.querySelector(".dg-d-body").innerHTML = drawerHtml(it, statOf(openKey));
}
function setExpanded(key) {
  document.querySelectorAll(".dg-root [data-item][aria-expanded]").forEach(el => el.setAttribute("aria-expanded", String(el.dataset.item === key)));
}
function openGuideDrawer(key, trigger) {
  if (!itemByKey(key)) return;
  openKey = key;
  opener = trigger || null;
  const root = drawerRoot();
  renderDrawer();
  root.classList.add("open");
  root.querySelector(".dg-d-body").scrollTop = 0;
  setExpanded(key);
  root.querySelector(".dg-d-close").focus();
}
/** 서랍을 닫는다 — 다른 화면으로 옮길 때는 포커스를 돌려주지 않는다(숨은 단추로 가지 않게). */
export function closeGuideDrawer({ restoreFocus = true } = {}) {
  const root = document.getElementById("dg-drawer");
  if (!root || !root.classList.contains("open")) return;
  root.classList.remove("open");
  setExpanded(null);
  // 새로 고침으로 화면을 다시 그렸으면 연 단추는 문서에서 떨어져 있다 — 새 화면의 같은 자료 단추로 돌아간다
  const back = opener && document.body.contains(opener) ? opener
    : document.querySelector(`.dg-root .dg-item[data-item="${CSS.escape(openKey || "")}"]`);
  openKey = null;
  opener = null;
  if (restoreFocus && back && back.offsetParent !== null) back.focus();
}
async function copyText(btn) {
  try {
    await navigator.clipboard.writeText(btn.dataset.copy);
    setToast("복사했습니다", "ok");
  } catch {
    // 클립보드를 못 쓰는 창(보안 문맥 밖)이면 글을 골라 두어 Ctrl+C 로 복사하게 한다(collect.js 와 같다)
    const code = btn.closest("dd")?.querySelector("code");
    if (code) window.getSelection()?.selectAllChildren(code);
    setToast("복사하지 못했습니다 — 골라 둔 글을 Ctrl+C 로 복사하세요", "error");
  }
}
function onDrawerClick(e) {
  if (e.target.closest(".dg-d-close") || e.target.classList.contains("dg-dim")) { closeGuideDrawer(); return; }
  const go = e.target.closest("[data-view-go]");
  if (go) { closeGuideDrawer({ restoreFocus: false }); navigate(go.dataset.viewGo); return; }
  const devBtn = e.target.closest(".dg-dev-toggle");
  if (devBtn) {
    const body = document.getElementById(devBtn.getAttribute("aria-controls"));
    const open = devBtn.getAttribute("aria-expanded") !== "true";
    devBtn.setAttribute("aria-expanded", String(open));
    if (body) body.hidden = !open;
    return;
  }
  const copyBtn = e.target.closest(".dg-copy");
  if (copyBtn) copyText(copyBtn);
}

// ── 화면 — 그리기 · 누르기 ───────────────────────────────────────────────
function guideRoot() {
  const view = document.querySelector(`.view[data-view="${VIEW}"]`);
  if (!view) return null;
  let root = view.querySelector(".dg-root");
  if (!root) { root = document.createElement("div"); root.className = "dg-root"; view.appendChild(root); }
  if (!root.dataset.bound) { root.dataset.bound = "1"; root.addEventListener("click", onPageClick); }
  return root;
}
function jumpTo(key) {
  const target = document.getElementById(key === "have-list" ? "dg-sec-have-list" : `dg-sec-${key}`);
  if (!target) return;
  target.scrollIntoView({ behavior: "smooth", block: "start" });
  target.focus({ preventScroll: true });
}
function onPageClick(e) {
  const root = e.currentTarget;
  if (e.target.closest(".dg-refresh")) { pendingTries = 0; renderDataGuide(); return; }
  if (e.target.closest(".dg-go-status")) { navigate("data-status"); return; }
  if (e.target.closest(".dg-go-runner")) { navigate("crawl-auto"); return; }
  const jump = e.target.closest("[data-jump]");
  if (jump) { jumpTo(jump.dataset.jump); return; }
  const go = e.target.closest("[data-view-go]");
  if (go) { navigate(go.dataset.viewGo); return; }
  const chip = e.target.closest("[data-group]");
  if (chip) {
    pickedGroup = chip.dataset.group;
    root.querySelectorAll(".dg-chip").forEach(el => el.setAttribute("aria-pressed", String(el.dataset.group === pickedGroup)));
    root.querySelector(".dg-list tbody").innerHTML = listRowsHtml(res);
    setExpanded(openKey);
    return;
  }
  if (e.target.closest(".dg-more")) {
    listOpen = !listOpen;
    root.querySelector(".dg-list tbody").innerHTML = listRowsHtml(res);
    setExpanded(openKey);
    root.querySelector(".dg-more")?.focus();
    return;
  }
  const boxEl = e.target.closest("[data-box]");
  if (boxEl) {
    const key = boxEl.dataset.box;
    if (openBoxes.has(key)) openBoxes.delete(key); else openBoxes.add(key);
    root.querySelector(".dg-flow-card").outerHTML = flowHtml(res);
    root.querySelector(`[data-box="${CSS.escape(key)}"]`)?.focus();
    return;
  }
  const pitBtn = e.target.closest(".dg-pit-toggle");
  if (pitBtn) {
    const open = pitBtn.getAttribute("aria-expanded") !== "true";
    pitBtn.setAttribute("aria-expanded", String(open));
    root.querySelector("#dg-pit-body").hidden = !open;
    pitBtn.closest(".dg-pit").classList.toggle("open", open);
    return;
  }
  const btn = e.target.closest("[data-item]");
  if (btn && btn.tagName === "BUTTON") { openGuideDrawer(btn.dataset.item, btn); return; }
  // 목록 줄 아무 데나 눌러도 그 자료 한 장(링크 · 단추 밖) — 포커스는 그 줄의 이름 단추로 돌아온다
  const row = e.target.closest("tr[data-item]");
  if (row && !e.target.closest("a, button")) openGuideDrawer(row.dataset.item, row.querySelector(".dg-item"));
}

async function renderDataGuide() {
  const root = guideRoot();
  if (!root) return;
  if (!root.innerHTML) root.innerHTML = `<p class="q-muted dg-loading">자료 안내를 불러오는 중…</p>`;
  const my = ++seq;
  let next;
  try {
    next = await api("/api/data/guide");
  } catch (err) {
    if (my !== seq) return;
    root.innerHTML = `<div class="card dg-card"><p class="q-err">자료 안내를 읽지 못했습니다 — ${escHtml(err.message)}</p>
      <button type="button" class="btn-secondary dg-refresh" style="margin-top:10px">다시 시도</button></div>`;
    return;
  }
  if (my !== seq) return;   // 새로 고침을 빠르게 두 번 누르면 앞 응답을 버린다
  res = next;
  if (pickedGroup && !res.guide.groups.some(grp => grp.key === pickedGroup)) pickedGroup = "";
  root.innerHTML = pageHtml(res);
  if (openKey) { renderDrawer(); setExpanded(openKey); }   // 새로 고침 때 열린 서랍은 새 숫자로
  clearTimeout(retryTimer);
  if ((res.stats?.status_pending || res.stats?.total_state === "counting") && pendingTries < PENDING_MAX_TRIES) {
    pendingTries += 1;
    retryTimer = setTimeout(() => {
      if (document.querySelector(`.view.active[data-view="${VIEW}"]`)) renderDataGuide();
    }, PENDING_RETRY_MS);
  }
}

/** main.js 의 화면 진입 훅 — 화면이 바뀌면 서랍을 닫고(뒤로 가기 · 주소로 옮겨도 남지 않게), 이 화면이면 그린다. */
export function onDataGuideViewActivated(view) {
  closeGuideDrawer({ restoreFocus: false });
  clearTimeout(retryTimer);
  if (view !== "data-guide") return;   // 글자 그대로 — 화면 스캐너(scripts/view_scan.py)가 이 모양으로 진입 훅을 읽는다
  pendingTries = 0;
  renderDataGuide();
}
