/* 데이터 관제 — 위 메뉴의 「자료 날짜 · 판정」 표시 · 오른쪽 서랍 · 「데이터 › 데이터 관제」 화면 (2026-10-02)
 *
 * 화면 설계 결정(Figma 「데이터 관제 · 금융 일정」 · 결정 ① = 안 C + A):
 *   어느 화면에서든 위 메뉴에 「자료 10-01 · 정상」 을 보이고(색 = 판정), 누르면 서랍에 요약,
 *   「자세히 보기」 는 새 화면(요약 카드 넷 · 오늘 갱신 단계 · 자료별 기준일 · 지난 회차 · 판정 읽는 법).
 * 읽는 API 는 하나 — GET /api/data/status (로그인 뒤 · 30초 응답 캐시 · 행 수는 서버가 뒤에서 센다).
 *
 * 「5분 전 동기화」(sync-badge)는 외부 현재가 캐시의 신선도이고, 이 표시는 우리가 모은 자료의 기준일이다 —
 * 둘을 헷갈리지 않게 글자를 「자료 MM-DD」 로 시작한다(Figma 안 C 의 아쉬운 점).
 */
import { api, escHtml, fmt } from "/js/common.js";
import { navigate } from "/js/core.js";

const VIEW = "data-status";
const BADGE_MS = 60_000;     // 위 메뉴 표시 — 1분마다(러너는 하루 한 번이라 이보다 자주 볼 까닭이 없다)
const VIEW_MS = 30_000;      // 화면이 떠 있는 동안 — 30초마다(서버 응답 캐시와 같은 간격)

const VERDICT_CLASS = { fresh: "fresh", ok: "ok", info: "info", late: "late", stale: "stale", missing: "stale" };
//: 전체 판정 — 정상은 초록(표 안의 「정상 = 하루 밀림」 파랑과 다르다 · Figma 와 위 메뉴 표시가 초록)
const OVERALL = { ok: ["fresh", "정상"], warning: ["late", "확인 필요"], error: ["stale", "멈춤"] };
const RUNNER_CLASS = { ok: "fresh", warning: "late", failed: "stale", running: "ok", late: "late", missing: "info" };
const STEP_MARK = { ok: ["✓", "fresh"], warning: ["!", "late"], failed: ["✕", "stale"], skipped: ["–", "info"] };
const WEEK = "일월화수목금토";

let lastStatus = null;
let viewTimer = null;

// ── 작은 도구 ──────────────────────────────────────────────────────────
function mmdd(iso) { return iso ? `${iso.slice(5, 7)}-${iso.slice(8, 10)}` : "—"; }
function withWeekday(iso) {
  if (!iso) return "—";
  const d = new Date(`${iso.slice(0, 10)}T00:00:00+09:00`);
  return `${iso.slice(0, 10)} (${WEEK[d.getDay()]})`;
}
function hm(iso) { return iso ? iso.slice(11, 16) : ""; }
function dur(sec) {
  const s = Math.round(sec || 0);
  return s >= 60 ? `${Math.floor(s / 60)}분 ${s % 60}초` : `${Math.max(s, 0)}초`;
}
function pill(verdict, label) {
  return `<span class="q-pill q-pill--${VERDICT_CLASS[verdict] || "info"}">${escHtml(label)}</span>`;
}
function lateTables(st) {
  return (st.tables || []).filter(t => ["late", "stale", "missing"].includes(t.verdict));
}
function lastUpload(st) {
  const ups = (st.hf || []).map(h => h.uploaded_at).filter(Boolean).sort();
  return ups.length ? ups[ups.length - 1] : null;
}
async function fetchStatus() {
  lastStatus = await api("/api/data/status");
  return lastStatus;
}

// ── 위 메뉴의 표시 ────────────────────────────────────────────────────
function renderBadge(st, err) {
  const el = document.getElementById("q-data-badge");
  if (!el) return;
  if (err || !st) {
    el.className = "q-data-badge q-data-badge--info";
    el.innerHTML = `<span class="q-dot"></span><span>자료 상태 —</span>`;
    el.title = `자료 상태를 읽지 못했습니다${err ? ` — ${err.message}` : ""}`;
    return;
  }
  const [cls, label] = OVERALL[st.verdict] || ["info", st.verdict_label || "—"];
  el.className = `q-data-badge q-data-badge--${cls}`;
  el.innerHTML = `<span class="q-dot"></span><span>자료 ${escHtml(mmdd(st.as_of))} · ${escHtml(label)}</span>`;
  el.title = `${st.summary} — 눌러서 자세히`;
}

async function refreshBadge() {
  try { renderBadge(await fetchStatus()); } catch (err) { renderBadge(null, err); }
}

/** 부트에서 한 번 — 위 메뉴의 「5분 전 동기화」 왼쪽에 표시를 넣고 1분마다 다시 읽는다. */
export function initDataBadge() {
  const right = document.querySelector("#gnb .gnb-right");
  if (!right || document.getElementById("q-data-badge")) return;
  const b = document.createElement("button");
  b.type = "button";
  b.id = "q-data-badge";
  b.className = "q-data-badge q-data-badge--info";
  b.setAttribute("aria-haspopup", "dialog");
  b.innerHTML = `<span class="q-dot"></span><span>자료 상태 …</span>`;
  b.addEventListener("click", openDrawer);
  right.insertBefore(b, document.getElementById("sync-badge") || right.firstChild);
  refreshBadge();
  setInterval(refreshBadge, BADGE_MS);
}

// ── 서랍 — 요약 ───────────────────────────────────────────────────────
function drawerRoot() {
  let root = document.getElementById("q-data-drawer");
  if (root) return root;
  root = document.createElement("div");
  root.id = "q-data-drawer";
  root.innerHTML = `<div class="q-dd-dim"></div>
    <aside class="q-dd-panel" role="dialog" aria-modal="true" aria-labelledby="q-dd-title">
      <div class="q-dd-head"><h3 id="q-dd-title">데이터 상태</h3>
        <button type="button" class="q-dd-close" aria-label="닫기"><i class="fa-solid fa-xmark"></i></button></div>
      <div class="q-dd-body"></div>
    </aside>`;
  document.body.appendChild(root);
  root.querySelector(".q-dd-close").addEventListener("click", closeDrawer);
  root.querySelector(".q-dd-dim").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", e => { if (e.key === "Escape" && root.classList.contains("open")) closeDrawer(); });
  return root;
}

function drawerHtml(st) {
  const [cls, label] = OVERALL[st.verdict] || ["info", st.verdict_label];
  const r = st.runner || {};
  const last = r.last || {};
  const late = lateTables(st);
  const up = lastUpload(st);
  const rows = [
    ["주식 시세 기준일", `${withWeekday(st.as_of)} — 시세는 다음 날 낮에 들어옵니다`],
    ["낮 갱신", r.state === "running" ? `도는 중 — ${hm(r.running_since)} 에 시작` :
      `${escHtml(r.label || "—")}${last.minutes != null ? ` · ${Math.round(last.minutes)}분` : ""}${last.started_at ? ` (${mmdd(last.started_at)} ${hm(last.started_at)} → ${hm(last.finished_at)})` : ""}`],
    ["다음 갱신", r.next_expected ? `${withWeekday(r.next_expected)} ${hm(r.next_expected)}` : "—"],
    ["늦은 자료", late.length ? late.map(t => `${escHtml(t.label)} ${pill(t.verdict, t.verdict_label)}`).join(" ") : "없음"],
    ["팀 공유 저장소", up ? `${mmdd(up)} 올림 — ${(st.hf || []).map(h => escHtml(h.what)).join(" · ")}` : "올린 기록 없음"],
  ];
  return `<div class="q-dd-verdict q-tone--${cls}"><span class="q-dot"></span><strong>${escHtml(label)}</strong>
      <span>${escHtml(st.summary || "")}</span></div>
    ${rows.map(([k, v]) => `<div class="q-dd-row"><div class="q-dd-k">${k}</div><div class="q-dd-v">${v}</div></div>`).join("")}
    <button type="button" class="btn-primary q-dd-go">데이터 관제에서 자세히 보기 →</button>
    <p class="q-dd-note">표시 색 — 정상 초록 · 확인 필요 주황 · 멈춤 빨강. 「분 전 동기화」 는 외부 현재가의 갱신이고,
      이 표시는 우리가 모은 자료의 기준일입니다.</p>`;
}

async function openDrawer() {
  const root = drawerRoot();
  const body = root.querySelector(".q-dd-body");
  body.innerHTML = lastStatus ? drawerHtml(lastStatus) : `<p class="q-muted">불러오는 중…</p>`;
  root.classList.add("open");
  try {
    const st = await fetchStatus();
    renderBadge(st);
    body.innerHTML = drawerHtml(st);
  } catch (err) {
    body.innerHTML = `<p class="q-err">자료 상태를 읽지 못했습니다 — ${escHtml(err.message)}</p>`;
  }
  body.querySelector(".q-dd-go")?.addEventListener("click", () => { closeDrawer(); navigate(VIEW); });
}

function closeDrawer() { document.getElementById("q-data-drawer")?.classList.remove("open"); }

// ── 화면 — 데이터 › 데이터 관제 ───────────────────────────────────────
function summaryCards(st) {
  const [cls, label] = OVERALL[st.verdict] || ["info", st.verdict_label];
  const r = st.runner || {};
  const last = r.last || {};
  const up = lastUpload(st);
  const runText = r.state === "running" ? "도는 중" : `${r.label || "—"}${last.minutes != null ? ` · ${Math.round(last.minutes)}분` : ""}`;
  const runSub = r.state === "running" ? `${hm(r.running_since)} 에 시작 — 끝나면 이 화면이 새 값을 보입니다`
    : `${last.started_at ? `${mmdd(last.started_at)} ${hm(last.started_at)} → ${hm(last.finished_at)}` : "기록 없음"} · 다음 ${r.next_expected ? `${mmdd(r.next_expected)} ${hm(r.next_expected)}` : "—"}`;
  const cards = [
    ["판정", `<span class="q-tone--${cls} dh-big"><span class="q-dot"></span>${escHtml(label)}</span>`,
      st.verdict === "ok" ? "모든 자료가 최신이거나 하루 밀림" : `늦은 자료 ${lateTables(st).length}개 · 아래 표에서 봅니다`],
    ["주식 시세 기준일", `<span class="dh-big">${escHtml(withWeekday(st.as_of))}</span>`, "시세는 다음 날 낮에 들어옵니다"],
    ["낮 갱신", `<span class="dh-big q-tone--${RUNNER_CLASS[r.state] || "info"}">${escHtml(runText)}</span>`, runSub],
    ["팀 공유 저장소", `<span class="dh-big">${up ? `${mmdd(up)} 올림` : "기록 없음"}</span>`, (st.hf || []).map(h => h.what).join(" · ") || "—"],
  ];
  return `<div class="dh-sum">${cards.map(([k, v, d]) => `<div class="card dh-card"><div class="dh-k">${k}</div>${v}<div class="dh-d">${escHtml(d)}</div></div>`).join("")}</div>`;
}

function runCard(st) {
  const r = st.runner || {};
  const last = r.last;
  if (!last) {
    return `<div class="card"><h3 class="dh-h">오늘 갱신</h3><p class="q-muted">${escHtml(r.detail || "갱신 기록이 없습니다")}</p></div>`;
  }
  const steps = last.steps || [];
  const total = steps.reduce((a, s) => a + (s.seconds || 0), 0) || 1;
  const bar = steps.map(s => `<span class="dh-seg dh-seg--${STEP_MARK[s.status]?.[1] || "info"}" style="flex:${Math.max(s.seconds || 0, total * 0.004)}" title="${escHtml(s.label)} · ${dur(s.seconds)}"></span>`).join("");
  const list = steps.map(s => {
    const [mark, tone] = STEP_MARK[s.status] || ["·", "info"];
    return `<li><span class="q-tone--${tone} dh-mark">${mark}</span>${escHtml(s.label)}
      <span class="q-muted">${s.status === "skipped" ? escHtml(s.note || "건너뜀") : dur(s.seconds)}</span></li>`;
  }).join("");
  const head = r.state === "running" ? `도는 중 — ${hm(r.running_since)} 에 시작 · 아래는 지난 회차` :
    `${mmdd(last.started_at)} ${hm(last.started_at)} 시작 · ${escHtml(r.label || "")}`;
  return `<div class="card"><h3 class="dh-h">오늘 갱신 — 단계 ${steps.length}개 <span class="q-muted">${head}</span></h3>
    ${r.state !== "ok" && r.detail ? `<p class="dh-alert q-tone--${RUNNER_CLASS[r.state] || "info"}">${escHtml(r.detail)}</p>` : ""}
    <div class="dh-bar">${bar}</div><ul class="dh-steps">${list}</ul></div>`;
}

function tableCard(st) {
  const today = (st.checked_at || "").slice(0, 10);
  const prev = st.calendar?.previous_trading_day;
  const rows = (st.tables || []).map(t => `<tr>
      <td class="dh-name">${escHtml(t.label)}</td>
      <td class="q-muted">${escHtml(t.source || "")}</td>
      <td>${escHtml(t.last_date || "—")}</td>
      <td>${pill(t.verdict, t.verdict_label || t.verdict)}</td>
      <td class="dh-num">${t.rows == null ? `<span class="q-muted">세는 중…</span>` : fmt(t.rows)}</td>
      <td class="q-muted dh-detail">${escHtml(t.detail || "")}</td></tr>`).join("");
  const none = (st.tables || []).every(t => t.verdict === "missing");
  return `<div class="card"><h3 class="dh-h">자료별 기준일
      <span class="q-muted">오늘(${mmdd(today)}) 앞 마지막 거래일 ${mmdd(prev)} 까지 있으면 「최신」</span></h3>
    ${st.rows_note ? `<p class="dh-alert q-tone--info">${escHtml(st.rows_note)}</p>` : ""}
    ${none ? `<p class="dh-alert q-tone--late">이 PC 에는 수집 자료가 없습니다. 자료를 모으는 PC 가 아니면 비어 있는 것이 정상이고,
      팀 공유 저장소에서 받아 두면 이 표가 채워집니다(로컬 실행 안내서 — 자료 되살리기).</p>` : ""}
    <div class="dh-table-wrap"><table class="dh-table"><thead><tr><th>자료</th><th>어디서</th><th>기준일</th><th>판정</th>
      <th class="dh-num">줄 수</th><th>설명</th></tr></thead><tbody>${rows}</tbody></table></div></div>`;
}

function lowCards(st) {
  const hist = (st.runner?.history || []).map(h => {
    const ok = h.skipped ? ["info", "건너뜀"] : h.ok ? ["fresh", "성공"] : ["stale", "실패"];
    return `<li><strong>${escHtml(withWeekday(h.started_at).slice(5))}</strong> ${pill(ok[0], ok[1])}
      <span class="q-muted">${h.minutes != null ? `${Math.round(h.minutes)}분` : ""}${h.price_max ? ` · 시세 ${mmdd(h.price_max)}` : ""}${h.skipped ? ` · ${escHtml(h.skipped)}` : ""}${h.stopped ? ` · 멈춘 단계 ${escHtml(h.stopped)}` : ""}</span></li>`;
  }).join("") || `<li class="q-muted">기록이 없습니다</li>`;
  const legend = [["fresh", "최신", "오늘 앞 마지막 거래일까지 있다"],
    ["ok", "정상", "하루 밀림 — 시세는 다음 날 낮에 들어온다 · 계산 자료는 주식 일봉과 같은 날"],
    ["late", "늦음", "거래일 이틀이 비었다"], ["stale", "멈춤", "사흘 이상 비었다 — 갱신 기록부터 본다"],
    ["info", "참고", "날짜로 판정하지 않는 자료(공시 · 일정)"]]
    .map(([c, k, d]) => `<li>${pill(c, k)} <span>${d}</span></li>`).join("");
  return `<div class="dh-low"><div class="card"><h3 class="dh-h">지난 회차</h3><ul class="dh-hist">${hist}</ul></div>
    <div class="card"><h3 class="dh-h">판정 읽는 법</h3><ul class="dh-legend">${legend}</ul></div></div>`;
}

function dataHubRoot() {
  const view = document.querySelector(`.view[data-view="${VIEW}"]`);
  if (!view) return null;
  let root = view.querySelector(".dh-root");
  if (!root) { root = document.createElement("div"); root.className = "dh-root"; view.appendChild(root); }
  return root;
}

async function renderDataHub() {
  const root = dataHubRoot();
  if (!root) return;
  if (!root.innerHTML) root.innerHTML = `<p class="q-muted">불러오는 중…</p>`;
  try {
    const st = await fetchStatus();
    renderBadge(st);
    root.innerHTML = `<div class="dh-head"><div><h2>데이터 관제</h2>
        <p class="q-muted">모은 자료가 며칠 것까지 있는지, 매일 낮 갱신이 돌았는지 봅니다 · 30초마다 다시 봅니다 · ${escHtml(hm(st.checked_at))} 기준</p></div>
        <button type="button" class="btn-secondary dh-refresh">새로 고침</button></div>
      ${summaryCards(st)}${runCard(st)}${tableCard(st)}${lowCards(st)}`;
  } catch (err) {
    root.innerHTML = `<div class="card"><p class="q-err">자료 상태를 읽지 못했습니다 — ${escHtml(err.message)}</p>
      <button type="button" class="btn-secondary dh-refresh">다시 시도</button></div>`;
  }
  root.querySelector(".dh-refresh")?.addEventListener("click", renderDataHub);
}

/** main.js 의 화면 진입 훅 — 이 화면이면 그리고 30초마다 다시, 다른 화면이면 멈춘다. */
export function onDataHubViewActivated(view) {
  closeDrawer();                    // 화면이 바뀌면 서랍을 닫는다(뒤로 가기 · 주소로 옮겨도 남지 않게)
  clearInterval(viewTimer);
  viewTimer = null;
  if (view !== "data-status") return;   // 글자 그대로 — 화면 스캐너(scripts/view_scan.py)가 이 모양으로 진입 훅을 읽는다
  renderDataHub();
  viewTimer = setInterval(() => {
    if (document.querySelector(`.view.active[data-view="${VIEW}"]`)) renderDataHub();
    else { clearInterval(viewTimer); viewTimer = null; }
  }, VIEW_MS);
}
