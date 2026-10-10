/* 데이터 수집 화면 셋 — 「데이터」 묶음의 관리자 화면 (2026-10-08 · Figma 「데이터 수집 화면」 설계 1 ~ 3)
 *
 *   crawl-auto    수집 일정 · 단계   GET /api/data/runner
 *   crawl-manual  자료 직접 받기     GET /api/data/fetch-sources · /api/data/fetch-plan · /api/data/url-rules ·
 *                                    POST /api/data/url-check · POST /api/ingest/crawl/url · GET /api/ingest/crawl/list
 *   crawl-ingest  적재 · 백업        GET /api/data/backup
 *
 * 화면 키는 옛 크롤링 그대로 두고 이름만 바꿨다(옛 주소가 열리고 기초 코드 반영 때 부딪히는 곳이 적다). 강사님 파일(app.html ·
 * agent.js · main.js)에는 뿌리 칸과 부르는 줄만 두고 그리기는 모두 여기서 한다(datahub.js 처럼).
 *
 * 화면은 PC 쪽 일을 하지 않는다(2026-10-08 결정 ①) — 앱은 수집 폴더를 읽기만 하게 붙어 있으므로 「받기」 · 「원격 다시 확인」 ·
 * 「복원 리허설」 은 PC 에서 돌릴 명령과 막히는 때를 보이고 복사하게 한다. 주소로 받기만 앱이 받는다(근거 문서 — 앱 DB · 검색 색인).
 * 「다시 받기」 · 「전체 수집」 은 요청 표에 줄만 남기고 이 PC 의 수집 작업자가 가져가 돌린다(2026-10-10 · js/collect-requests.js) —
 * 단계 줄의 「명령」 은 작업자가 꺼져 있을 때 이 PC 에서 직접 돌리는 길로 남겼다.
 * 단계 줄 · 묶음 · 하는 일은 러너 기록에서 온다 — 수집 단계가 늘면 이 화면이 손대지 않아도 따라온다(결정 ④).
 * 관리자 화면이다 — 일반 사용자에게는 메뉴를 숨기고(css/collect.css 의 body.q-admin), 서버도 403 으로 막는다.
 */
import { api, escHtml, fmt, getMe, setToast } from "/js/common.js";
import { cancelRequest, confirmFullCollect, fullButtonHtml, loadRequests, requestCollect, requestsCardHtml,
  startRequestPolling, stepActionHtml, stopRequestPolling, workerBandHtml } from "/js/collect-requests.js";

const WEEK = "일월화수목금토";
//: 러너 단계 결과 → [글자, 막대 · 글자 색]
const STEP_RESULT = { ok: ["성공", "pass"], warning: ["경고", "pending"], failed: ["실패", "fail"], skipped: ["건너뜀", "skip"] };
//: 받을 범위 상태 → 범례 순서(서버 fetch_plan.STATES 와 같은 열쇠 — TC-CL 이 맞대 본다)
const PLAN_ORDER = ["done", "missing", "error", "partial", "pending", "closed"];
const GROUP_TONE = { pass: "pass", pending: "pending", fail: "fail" };

let roleChecked = null;
let runnerData = null;
let pickedRun = "last";
let fetchKinds = null;
let fetchKind = "price";

// ── 작은 도구 ──────────────────────────────────────────────────────────
function day(iso) {
  if (!iso) return "—";
  const d = new Date(`${iso.slice(0, 10)}T00:00:00+09:00`);
  return `${iso.slice(5, 7)}-${iso.slice(8, 10)}(${WEEK[d.getDay()]})`;
}
function hm(iso) { return iso ? iso.slice(11, 16) : ""; }
function dur(sec) {
  const s = Math.round(sec || 0);
  if (s >= 3600) return `${Math.floor(s / 3600)}시간 ${Math.floor((s % 3600) / 60)}분`;
  return s >= 60 ? `${Math.floor(s / 60)}분 ${s % 60}초` : `${Math.max(s, 0)}초`;
}
function isoToday() {
  const kst = new Date(Date.now() + 9 * 3600_000);
  return kst.toISOString().slice(0, 10);
}
function isoDaysAgo(n) {
  const kst = new Date(Date.now() + 9 * 3600_000 - n * 86_400_000);
  return kst.toISOString().slice(0, 10);
}
function head(title, lead, extra = "") {
  return `<div class="cl-head"><div><h2>${title}</h2><p>${lead}</p></div>
    <div class="cl-head-right">${extra}<span class="cl-admin" title="관리자에게만 보이는 화면">관리자</span></div></div>`;
}
function errorCard(what, err) {
  const msg = err?.status === 403 ? "관리자만 볼 수 있는 화면입니다." : `${what} — ${escHtml(err?.message || "")}`;
  return `<div class="card"><p class="q-err">${msg}</p>
    ${err?.status === 403 ? "" : `<button type="button" class="btn-secondary cl-retry" style="margin-top:10px">다시 시도</button>`}</div>`;
}
/** PC 에서 돌릴 명령 상자 — 복사 단추 · 막히는 때 */
function cmdBox(command, note = "", title = "이 PC 에서 돌릴 명령") {
  return `<div class="cl-cmd"><div class="cl-cmd-head"><span>${escHtml(title)}</span>
      <button type="button" class="cl-btn-sm cl-copy" data-cmd="${escHtml(command)}"><i class="fa-regular fa-copy"></i> 복사</button></div>
    <code>${escHtml(command)}</code>${note ? `<p>${note}</p>` : ""}</div>`;
}
async function copyCommand(btn) {
  try {
    await navigator.clipboard.writeText(btn.dataset.cmd);
    setToast("명령을 복사했습니다 — PowerShell 이나 Git Bash 에서 저장소 폴더로 옮겨 돌리세요", "ok");
  } catch {
    // 클립보드를 못 쓰는 창(보안 문맥 밖)이면 글을 골라 두어 Ctrl+C 로 복사하게 한다
    const code = btn.closest(".cl-cmd")?.querySelector("code");
    if (code) window.getSelection()?.selectAllChildren(code);
    setToast("복사하지 못했습니다 — 골라 둔 명령을 Ctrl+C 로 복사하세요", "error");
  }
}
function bindCopy(root) {
  root.querySelectorAll(".cl-copy").forEach(b => b.addEventListener("click", () => copyCommand(b)));
}
function collectRoot(view) {
  return document.querySelector(`.view[data-view="${view}"] .cl-root`);
}
/** 관리자 여부 — 처음 한 번 묻고 몸통에 q-admin 을 붙인다(메뉴 셋을 CSS 가 숨기고 보인다) */
function ensureCollectRole() {
  if (!roleChecked) {
    roleChecked = getMe().then(({ user }) => {
      const admin = (user?.roles || []).includes("admin");
      document.body.classList.toggle("q-admin", admin);
      return admin;
    }).catch(() => false);
  }
  return roleChecked;
}

// ══ 1. 수집 일정 · 단계 ═════════════════════════════════════════════════
/** 회차 고르기 — 마지막 회차 + 지난 회차(한 단계만 다시 돌린 줄은 「다시 돌림」 으로 따로 · DF-82) */
function runOptions(d) {
  const opts = [];
  if (d.last) opts.push({ key: "last", label: `회차 ${day(d.last.started_at)} ${hm(d.last.started_at)} · ${d.label || ""}` });
  (d.history || []).forEach((h, i) => {
    if (d.last && h.started_at === d.last.started_at && !h.only) return;   // 마지막 회차와 같은 줄
    const what = h.only ? `↳ ${day(h.started_at)} ${hm(h.started_at)} 다시 돌림 · ${stepLabel(d, h.only)}`
      : `회차 ${day(h.started_at)} ${hm(h.started_at)} · ${h.skipped ? "건너뜀" : h.ok ? "성공" : "실패"}`;
    opts.push({ key: String(i), label: what });
  });
  return opts;
}
function stepLabel(d, name) {
  return (d.catalog?.steps || []).find(s => s.name === name)?.label || name;
}
/** 고른 회차 → {run, steps(없으면 null), rerun(한 단계만 다시 돌린 줄인가)} */
function pickedRunView(d) {
  if (pickedRun === "last" || !d.history?.[Number(pickedRun)]) return { run: d.last, steps: d.last?.steps || null, rerun: false };
  const h = d.history[Number(pickedRun)];
  return { run: h, steps: h.steps, rerun: !!h.only };
}
function scheduleTiles(d, view) {
  const run = view.run;
  // 도는 중이면 맨 위에 한 줄 — 아래 타일 · 표는 지난 회차 그대로(끝나면 새 회차로 바뀐다)
  const step = d.running_step ? ` — ${d.running_step.index}번째 ${escHtml(d.running_step.label)}` : "";
  const running = d.running ? `<div class="cl-alert">수집 중${step} · ${hm(d.running_since)} 에 시작했습니다. 아래는 지난 회차이고,
      끝나면(보통 13:30 무렵) 새 회차로 바뀝니다. 수집 중에는 단계를 다시 돌릴 수 없습니다.</div>` : "";
  if (!run) {
    return running || `<div class="cl-alert">아직 회차 기록이 없습니다 — 첫 수집은 12:30 에 돕니다. ${escHtml(d.detail || "")}</div>`;
  }
  const steps = view.steps || [];
  const n = s => steps.filter(x => x.status === s).length;
  const held = steps.filter(x => x.status === "skipped" && x.followup).length;   // 채울 날이 남은 건너뜀
  const okAll = steps.length ? n("ok") === steps.length : run.ok;
  const result = steps.length
    ? `<div class="v ${okAll ? "q-tone--fresh" : "q-tone--stale"}">${view.rerun ? "다시 돌림 " : "성공 "}${n("ok")} / ${steps.length}</div>
       <div class="d">실패 ${n("failed")} · 경고 ${n("warning")} · 건너뜀 ${n("skipped")}${held ? ` (채울 것 ${held})` : ""}</div>`
    : `<div class="v ${run.ok ? "q-tone--fresh" : "q-tone--stale"}">${run.skipped ? "건너뜀" : run.ok ? "성공" : "실패"}</div>
       <div class="d">이 회차는 단계별 기록이 없습니다</div>`;
  const end = run.finished_at ? hm(run.finished_at) : (run.minutes != null ? "" : "—");
  // 한 단계만 다시 돌린 줄은 회차 기록의 분(소수 한 자리)이 0.0 으로 남는다 → 그 단계의 초를 더해 보인다
  const secs = view.rerun && steps.length ? steps.reduce((a, s) => a + (s.seconds || 0), 0)
    : run.minutes != null ? run.minutes * 60 : null;
  const runTile = `<div class="k">${view.rerun ? "다시 돌린 때" : pickedRun === "last" ? "마지막 회차" : "고른 회차"}</div>
    <div class="v">${hm(run.started_at)}${end ? ` → ${end}` : ""}</div>
    <div class="d">${day(run.started_at)}${secs != null ? ` · ${dur(secs)}` : ""}</div>`;
  const asOf = run.price_max || d.last?.price_max;
  return `${running}<div class="cl-tiles">
    <div class="cl-tile">${runTile}</div>
    <div class="cl-tile"><div class="k">결과</div>${result}</div>
    <div class="cl-tile"><div class="k">자료 기준일</div><div class="v">${asOf ? day(asOf) : "—"}</div>
      <div class="d">주식 시세 기준일 — 출처는 다음 영업일 13시 뒤에 공개합니다</div></div>
    <div class="cl-tile"><div class="k">다음 회차</div><div class="v">${d.next_expected ? `${day(d.next_expected)} ${hm(d.next_expected)}` : "—"}</div>
      <div class="d">${escHtml(d.schedule || "매일 12:30")} · 이 PC 의 작업 스케줄러</div></div></div>`;
}
function rerunCommand(d, name) {
  const base = (d.rerun?.command || "python scripts/daily_update.py run --only <단계>").replace("<단계>", name);
  const cat = (d.catalog?.steps || []).find(s => s.name === name);
  return cat?.upload ? `${base} --upload` : base;   // 올리기 단계는 --upload 와 함께만(러너가 막는다)
}
function stepsTable(d, view) {
  // 고른 회차의 단계 — 단계별 기록이 없는 옛 회차는 러너 단계 목록을 「기록 없음」 으로
  const rows = view.steps || (d.catalog?.steps || []).map(s => ({ ...s, status: null, seconds: null }));
  if (!rows.length) return `<div class="card"><p class="q-muted">러너 단계 목록이 아직 없습니다 — 다음 회차가 돌면 생깁니다.</p></div>`;
  const max = Math.max(1, ...rows.map(s => s.seconds || 0));
  const order = (d.groups || []).map(g => g.key);
  const groupsSeen = [...new Set(rows.map(s => s.group || "기타"))].sort((a, b) =>
    (order.indexOf(a) + 1 || 99) - (order.indexOf(b) + 1 || 99));
  const note = Object.fromEntries((d.groups || []).map(g => [g.key, g.note]));
  const reruns = new Set((d.last?.reruns || []).map(r => r.name));
  let idx = 0;
  const body = groupsSeen.map(g => {
    const mine = rows.filter(s => (s.group || "기타") === g);
    const head = `<tr class="cl-group"><td colspan="6">${escHtml(g)}${note[g] ? ` <span class="q-muted">— ${escHtml(note[g])}</span>` : ""}</td></tr>`;
    return head + mine.map(s => {
      idx += 1;
      // 돌 조건이 없어 건너뛰고 채울 날이 남은 줄(러너가 적은 followup — 신호 단계 앱 DB 꺼짐 · 2026-10-08)만 노랑.
      // 할 일이 없어 건너뛴 줄(새 자료 없음 · 업로드 끔)은 회색 그대로 — 매일 보여도 눈을 빼앗지 않게
      const held = s.status === "skipped" && s.followup;
      const [txt, tone] = held ? ["건너뜀", "pending"]
        : s.status ? (STEP_RESULT[s.status] || [s.status, "pending"]) : ["기록 없음", "skip"];
      const w = s.seconds != null ? Math.max(2, Math.round(((s.seconds || 0) / max) * 220)) : 0;
      const time = s.seconds != null
        ? `<div class="cl-time"><span class="cl-bar cl-bar--${tone === "fail" ? "fail" : tone === "pending" ? "warn" : tone === "skip" ? "skip" : "ok"}" style="width:${w}px"></span><span>${dur(s.seconds)}</span></div>`
        : `<span class="q-muted">—</span>`;
      const isRerun = pickedRun === "last" && reruns.has(s.name);
      return `<tr class="${s.status === "failed" ? "cl-row--fail" : ""} ${isRerun ? "cl-row--rerun" : ""}" data-step="${escHtml(s.name)}">
        <td class="cl-n">${idx}</td><td class="cl-name">${escHtml(s.label || s.name)}</td>
        <td class="cl-desc">${escHtml(s.desc || "")}${s.status === "skipped" && s.note ? ` <span class="q-muted">· ${escHtml(s.note)}</span>` : ""}${held && s.date ? ` <span class="q-muted">· 빠진 거래일 ${escHtml(s.date)}</span>` : ""}</td>
        <td>${time}</td><td class="cl-res cl-st--${tone === "skip" ? "pending" : tone}">${txt}</td>
        <td class="cl-act">${stepActionHtml(s.name, d.running)}</td></tr>`;
    }).join("");
  }).join("");
  return `<div class="card"><h3 class="cl-h">단계 ${rows.length}개 <span class="q-muted">받기 → 계산 → 백업 → 근거 문서 차례로 돕니다 · 막대는 모두 같은 눈금(가장 긴 단계가 끝까지)</span></h3>
    <div class="cl-table-wrap"><table class="cl-table"><thead><tr><th>#</th><th>단계</th><th>하는 일</th><th>걸린 시간</th><th>결과</th><th>다시 받기</th></tr></thead>
    <tbody>${body}</tbody></table></div></div>`;
}
function scheduleHtml(d) {
  const opts = runOptions(d);
  const pick = opts.length > 1
    ? `<select class="cl-run-pick" aria-label="회차 고르기">${opts.map(o => `<option value="${o.key}" ${o.key === pickedRun ? "selected" : ""}>${escHtml(o.label)}</option>`).join("")}</select>`
    : "";
  const view = pickedRunView(d);
  return `${head("수집 일정 · 단계", "매일 12:30 에 시세 · 공시 · 뉴스를 받아 계산하고 백업합니다. 고른 회차의 단계별 결과와 걸린 시간입니다.",
      fullButtonHtml(d.running) + pick)}
    <div class="cq-band-slot">${workerBandHtml()}</div>
    ${scheduleTiles(d, view)}${stepsTable(d, view)}
    <div class="cq-req-slot">${requestsCardHtml()}</div>
    <div class="cl-alert">「다시 받기」 · 「전체 수집」 은 요청만 남기고, 이 PC 의 수집 작업자가 1분 안에 가져가 돌립니다 — 화면이 수집을
      직접 돌리지 않습니다. 정기 회차와 겹치는 때(막는 때)와 수집 중에는 단추가 꺼집니다. 작업자가 꺼져 있으면 「명령」 으로 이 PC 에서
      직접 돌릴 수 있습니다. ${escHtml(d.rerun?.blocked ? `명령이 막히는 때: ${d.rerun.blocked}` : "")}</div>`;
}
function bindSchedule(root, d) {
  root.querySelector(".cl-run-pick")?.addEventListener("change", e => {
    pickedRun = e.target.value;
    root.innerHTML = scheduleHtml(d);
    bindSchedule(root, d);
  });
  root.querySelector(".cl-retry")?.addEventListener("click", renderCollectSchedule);
  // 단계 줄 단추 · 요청 카드는 요청 목록을 다시 물을 때마다(대기 · 도는 중 5초 · 그 밖 1분) 다시 그리므로 누름은 뿌리 칸 하나에 한 번만 건다
  if (!root.dataset.cqBound) {
    root.dataset.cqBound = "1";
    root.addEventListener("click", onScheduleClick);
  }
}
/** 수집 일정 화면의 누름 — 「다시 받기」 · 「전체 수집」 · 요청 「취소」 · 「명령」 열고 닫기 */
function onScheduleClick(e) {
  const root = e.currentTarget;
  const d = runnerData;
  const btn = e.target.closest("button");
  if (!btn || !d || btn.disabled) return;
  if (btn.classList.contains("cq-rerun")) { requestCollect("step", btn.dataset.step); return; }
  if (btn.classList.contains("cq-cancel")) { cancelRequest(btn.dataset.id); return; }
  if (btn.classList.contains("cq-full")) {
    confirmFullCollect({ steps: (d.catalog?.steps || []).length, lastSeconds: d.last?.minutes != null ? d.last.minutes * 60 : null });
    return;
  }
  if (!btn.classList.contains("cl-cmd-open")) return;
  {
    const tr = btn.closest("tr");
    const open = tr.nextElementSibling?.classList.contains("cl-cmd-row");
    root.querySelectorAll(".cl-cmd-row").forEach(r => r.remove());
    root.querySelectorAll(".cl-cmd-open").forEach(b => b.setAttribute("aria-expanded", "false"));
    if (open) return;
    btn.setAttribute("aria-expanded", "true");
    const row = document.createElement("tr");
    row.className = "cl-cmd-row";
    // 빠진 날 채우기 명령 — 단계 목록(러너 한 곳의 `fill`)에 있는 단계만. 화면은 명령 글을 지어내지 않는다(#142 답글)
    const cat = (d.catalog?.steps || []).find(c => c.name === btn.dataset.step);
    row.innerHTML = `<td colspan="6">${cmdBox(rerunCommand(d, btn.dataset.step),
      `막히는 때: ${escHtml(d.rerun?.blocked || "12:30 회차와 겹치는 때")} · 끝나면 이 화면의 그 줄 결과가 바뀝니다(새로 고침).`)}${cat?.fill
      ? cmdBox(cat.fill, "날짜 칸(YYYY-MM-DD)을 채울 첫날 · 마지막 날로 바꿔 돌립니다 · 같은 날을 다시 돌려도 값만 바뀝니다.", "빠진 날 채우기")
      : ""}</td>`;
    tr.after(row);
    bindCopy(row);
  }
}
/** 요청 목록이 바뀌면 띠 · 단추 · 요청 카드만 다시(열어 둔 명령 상자는 그대로) · 도는 줄이 끝나면 회차 기록부터 다시 읽는다 */
function onRequestsChanged(kind) {
  if (kind === "finished") { renderCollectSchedule(); return; }
  const root = collectRoot("crawl-auto");
  if (!root || !runnerData || !root.querySelector(".cq-band-slot")) return;
  root.querySelector(".cq-band-slot").innerHTML = workerBandHtml();
  root.querySelector(".cq-req-slot").innerHTML = requestsCardHtml();
  const full = root.querySelector(".cq-full");
  if (full) full.outerHTML = fullButtonHtml(runnerData.running);
  root.querySelectorAll("tr[data-step] > .cl-act").forEach(td => {
    const tr = td.closest("tr");
    td.innerHTML = stepActionHtml(tr.dataset.step, runnerData.running);
    if (tr.nextElementSibling?.classList.contains("cl-cmd-row")) td.querySelector(".cl-cmd-open")?.setAttribute("aria-expanded", "true");
  });
}
async function renderCollectSchedule() {
  const root = collectRoot("crawl-auto");
  if (!root) return;
  if (!root.innerHTML) root.innerHTML = `<p class="q-muted">불러오는 중…</p>`;
  try {
    // 요청 목록은 따로 받는다 — 못 읽어도 단계 표는 그리고, 까닭은 작업자 띠에 보인다
    [runnerData] = await Promise.all([api("/api/data/runner"), loadRequests().catch(() => null)]);
  } catch (err) {
    root.innerHTML = head("수집 일정 · 단계", "매일 12:30 수집 회차의 단계별 결과") + errorCard("수집 기록을 읽지 못했습니다", err);
    root.querySelector(".cl-retry")?.addEventListener("click", renderCollectSchedule);
    return;
  }
  root.innerHTML = scheduleHtml(runnerData);
  bindSchedule(root, runnerData);
  startRequestPolling(onRequestsChanged);
}

// ══ 2. 자료 직접 받기 ═══════════════════════════════════════════════════
function planHtml(p) {
  const c = p.counts || {};
  const todoCount = (c.missing || 0) + (c.error || 0) + (c.partial || 0);
  const unit = p.unit === "year" ? "해" : "날";
  const tiles = `<div class="cl-tiles cl-tiles--3">
      <div class="cl-tile cl-tile--soft"><div class="k">이미 받은 ${unit}</div><div class="v">${c.done || 0}${unit === "날" ? "일" : "년"}</div></div>
      <div class="cl-tile cl-tile--soft"><div class="k">받을 ${unit}</div><div class="v ${todoCount ? "q-tone--stale" : ""}">${todoCount}${unit === "날" ? "일" : "년"}</div>
        <div class="d">빈 날 ${c.missing || 0} · 실패 ${c.error || 0} · 일부 ${c.partial || 0}</div></div>
      <div class="cl-tile cl-tile--soft"><div class="k">받지 않아도 되는 ${unit}</div><div class="v">${(c.closed || 0) + (c.pending || 0)}${unit === "날" ? "일" : "년"}</div>
        <div class="d">휴장 ${c.closed || 0} · 아직 공개 전 ${c.pending || 0}</div></div></div>`;
  let detail = "";
  if (p.days) {
    const cells = p.days.map(x => `<span class="cl-day cl-day--${x.state}" title="${escHtml(`${x.date}(${x.weekday}) · ${x.state_label}${x.note ? ` · ${x.note}` : ""}`)}"></span>`).join("");
    const legend = PLAN_ORDER.filter(s => p.days.some(x => x.state === s))
      .map(s => `<span><i class="cl-day--${s}"></i>${escHtml(p.days.find(x => x.state === s).state_label)}</span>`).join("");
    const todo = p.days.filter(x => ["missing", "error", "partial"].includes(x.state));
    detail = `<div class="cl-days" role="img" aria-label="날마다 받은 상태">${cells}</div><div class="cl-legend">${legend}</div>
      ${todo.length ? `<div class="cl-todo">받을 날: ${todo.slice(0, 12).map(x => `${day(x.date)}${x.note ? ` <span class="q-muted">${escHtml(x.note)}</span>` : ""}`).join(" · ")}${todo.length > 12 ? ` 외 ${todo.length - 12}일` : ""}</div>` : ""}`;
  } else if (p.years) {
    detail = `<table class="cl-years"><tbody>${p.years.map(y => `<tr><td><strong>${y.year}</strong></td>
      <td class="cl-st--${y.state === "done" ? "pass" : y.state === "partial" ? "pending" : "fail"}">${escHtml(y.state_label)}</td>
      <td>묶음 ${y.done} / ${y.expected}</td><td class="q-muted">${escHtml(y.note || "")}</td></tr>`).join("")}</tbody></table>`;
  }
  const clip = p.clipped_to_today ? ` · 끝을 오늘(${day(p.to)})까지로 줄였습니다` : "";
  return `${tiles}${detail}<p class="cl-note" style="margin-top:10px">${escHtml(p.note || "")}${clip}</p>`;
}
function fetchFormHtml() {
  const kinds = fetchKinds?.kinds || [];
  const k = kinds.find(x => x.kind === fetchKind) || kinds[0];
  const unitYear = k?.unit === "year";
  return `<div class="card"><h3 class="cl-h">무엇을 받을까</h3>
    <div class="cl-field"><span class="cl-label">자료 종류</span><div class="cl-kinds" role="group" aria-label="자료 종류">
      ${kinds.map(x => `<button type="button" class="cl-kind" data-kind="${x.kind}" aria-pressed="${x.kind === fetchKind}">${escHtml(x.label)}</button>`).join("")}</div></div>
    <div class="cl-field"><label for="cl-from">기간${unitYear ? " (재무는 해 단위로 봅니다)" : ""}</label><div class="cl-dates">
      <input type="date" id="cl-from" value="${isoDaysAgo(30)}" max="${isoToday()}" aria-label="시작" /><span>~</span>
      <input type="date" id="cl-to" value="${isoToday()}" max="${isoToday()}" aria-label="끝" /></div></div>
    <div class="cl-field"><span class="cl-label">출처</span><div class="cl-origin">${escHtml(k?.origin || "—")}
      <span class="q-muted">${escHtml(k?.how || "")}</span></div></div>
    <div class="cl-actions"><button type="button" class="btn-secondary cl-plan-go">받을 범위 보기</button>
      <button type="button" class="btn-primary cl-fetch-go" disabled title="먼저 받을 범위를 보세요">받기</button></div>
    <div class="cl-fetch-cmd"></div></div>`;
}
function sourcesHtml() {
  const rows = [...(fetchKinds?.kinds || []), ...(fetchKinds?.extra || [])]
    .map(x => `<tr><td>${escHtml(x.label)}</td><td>${escHtml(x.origin)}<br><span class="q-muted">${escHtml(x.terms)}</span></td></tr>`).join("");
  return `<div class="card"><h3 class="cl-h">출처 · 이용 조건</h3><table class="cl-src"><tbody>${rows}</tbody></table></div>`;
}
function urlCardHtml(rules) {
  const li = (r, ok) => `<li><span class="q-dot ${ok ? "q-tone--fresh" : "q-tone--stale"}"></span><strong>${escHtml(r.host)}</strong>
    <span class="q-muted">${escHtml(r.label)}</span><span class="${ok ? "ok" : "no"}">${escHtml(r.verdict)}</span></li>`;
  return `<div class="card"><h3 class="cl-h">주소로 받기 — 허용 목록에 있는 곳만 <span class="q-muted">받기 전에 주소를 검사합니다 · 받은 글은 근거 문서 검색에 들어갑니다</span></h3>
    <div class="cl-url"><input type="url" id="cl-url" placeholder="https://" aria-label="받을 주소" maxlength="2000" />
      <button type="button" class="btn-secondary cl-url-check">주소 검사</button>
      <button type="button" class="btn-primary cl-url-fetch" disabled title="먼저 주소를 검사하세요">받기</button></div>
    <div class="cl-url-result"></div>
    <ul class="cl-rules">${(rules?.allowed || []).map(r => li(r, true)).join("")}${(rules?.blocked || []).map(r => li(r, false)).join("")}</ul>
    <h4 class="cl-h" style="margin:16px 0 0;font-size:13px">주소로 받은 문서 <span class="q-muted">최근 100건</span></h4>
    <ul class="cl-docs"><li class="q-muted">불러오는 중…</li></ul></div>`;
}
async function loadCollectDocs(root) {
  const ul = root.querySelector(".cl-docs");
  if (!ul) return;
  try {
    const { items } = await api("/api/ingest/crawl/list");
    ul.innerHTML = (items || []).slice(0, 100).map(it => `<li>${escHtml(it.title || it.url)}
      <span class="q-muted"> · ${escHtml(it.source || "")} · ${escHtml((it.crawled_at || "").slice(0, 10))}</span></li>`).join("")
      || `<li class="q-muted">아직 주소로 받은 문서가 없습니다</li>`;
  } catch (err) {
    ul.innerHTML = `<li class="q-err">목록을 읽지 못했습니다 — ${escHtml(err.message)}</li>`;
  }
}
async function runFetchPlan(root) {
  const box = root.querySelector(".cl-plan-box");
  const go = root.querySelector(".cl-fetch-go");
  const cmd = root.querySelector(".cl-fetch-cmd");
  const from = root.querySelector("#cl-from").value;
  const to = root.querySelector("#cl-to").value;
  cmd.innerHTML = "";
  go.disabled = true;
  if (!from) { setToast("시작 날짜를 넣으세요", "error"); return; }
  box.innerHTML = `<p class="q-muted">받을 범위를 세는 중…</p>`;
  try {
    const p = await api(`/api/data/fetch-plan?kind=${encodeURIComponent(fetchKind)}&from=${from}&to=${to || ""}`);
    box.innerHTML = planHtml(p);
    go.disabled = !p.command;
    go.title = p.command ? "이 PC 에서 돌릴 명령을 보입니다" : "받을 것이 없습니다";
    go.dataset.command = p.command || "";
  } catch (err) {
    box.innerHTML = `<p class="q-err">${escHtml(err.message)}</p>`;
  }
}
function bindFetch(root) {
  bindFetchForm(root);
  const input = root.querySelector("#cl-url");
  const fetchBtn = root.querySelector(".cl-url-fetch");
  const out = root.querySelector(".cl-url-result");
  input.addEventListener("input", () => { fetchBtn.disabled = true; out.innerHTML = ""; });
  root.querySelector(".cl-url-check").addEventListener("click", async () => {
    const url = input.value.trim();
    if (!url) { setToast("받을 주소를 넣으세요", "error"); return; }
    out.innerHTML = `<p class="q-muted" style="margin-top:8px">검사하는 중…</p>`;
    try {
      const v = await api("/api/data/url-check", { method: "POST", body: { url } });
      const checks = (v.checks || []).map(c => `<span class="${c.ok ? "q-tone--fresh" : "q-tone--stale"}">${c.ok ? "✓" : "✕"} ${escHtml(c.name)}
        <span class="q-muted">${escHtml(c.note || "")}</span></span>`).join("");
      out.innerHTML = `<div class="cl-alert ${v.ok ? "cl-alert--ok" : "cl-alert--err"}" style="margin-top:10px">${v.ok ? "받을 수 있는 주소입니다" : "받을 수 없는 주소입니다"} — ${escHtml(v.reason)}
        ${v.source ? ` · ${escHtml(v.source)}` : ""}</div><div class="cl-checks">${checks}</div>`;
      fetchBtn.disabled = !v.ok;
    } catch (err) {
      out.innerHTML = `<p class="q-err" style="margin-top:8px">${escHtml(err.message)}</p>`;
    }
  });
  fetchBtn.addEventListener("click", async () => {
    const url = input.value.trim();
    fetchBtn.disabled = true;
    out.insertAdjacentHTML("beforeend", `<p class="q-muted cl-url-busy" style="margin-top:8px">받는 중…(글을 나눠 검색 색인에 넣습니다)</p>`);
    try {
      const r = await api("/api/ingest/crawl/url", { method: "POST", body: { url } });
      out.querySelector(".cl-url-busy")?.remove();
      // 서버 기록(log)은 받은 글이 없을 때만 까닭으로 보인다 — 받았으면 몇 조각인지만(화면에 개발 말을 쓰지 않는다)
      const why = r.chunks ? "" : (r.log || []).map(x => x.replace(/^\[(ERROR|SKIP)\]\s*/, "")).join(" · ");
      out.insertAdjacentHTML("beforeend", `<div class="cl-alert ${r.chunks ? "cl-alert--ok" : ""}" style="margin-top:10px">
        ${r.chunks ? `${r.chunks}조각으로 나눠 근거 문서 검색에 넣었습니다.` : "받은 글이 없거나 너무 짧습니다."}
        ${why ? `<span class="q-muted">${escHtml(why)}</span>` : ""}</div>`);
      loadCollectDocs(root);
    } catch (err) {
      out.querySelector(".cl-url-busy")?.remove();
      out.insertAdjacentHTML("beforeend", `<div class="cl-alert cl-alert--err" style="margin-top:10px">${escHtml(err.message)}</div>`);
    }
  });
}
/** 「무엇을 받을까」 칸 — 종류를 바꾸면 이 칸만 다시 그리므로 단추 리스너도 여기서 다시 건다 */
function bindFetchForm(root) {
  root.querySelectorAll(".cl-kind").forEach(b => b.addEventListener("click", () => {
    fetchKind = b.dataset.kind;
    const keep = { from: root.querySelector("#cl-from")?.value, to: root.querySelector("#cl-to")?.value };
    root.querySelector(".cl-form-slot").innerHTML = fetchFormHtml();
    if (keep.from) root.querySelector("#cl-from").value = keep.from;
    if (keep.to) root.querySelector("#cl-to").value = keep.to;
    bindFetchForm(root);
    runFetchPlan(root);
  }));
  root.querySelector(".cl-plan-go").addEventListener("click", () => runFetchPlan(root));
  root.querySelector(".cl-fetch-go").addEventListener("click", e => {
    const cmd = e.currentTarget.dataset.command;
    const slot = root.querySelector(".cl-fetch-cmd");
    if (!cmd) return;
    slot.innerHTML = slot.innerHTML ? "" : cmdBox(cmd, "받을 것의 처음 ~ 끝을 한 번에 받습니다 — 그 사이의 이미 받은 것은 수집기가 건너뜁니다. " +
      "12:30 회차가 도는 동안에는 돌리지 마세요. 돌린 뒤 「받을 범위 보기」 로 다시 확인합니다.");
    bindCopy(slot);
  });
}
async function renderCollectFetch() {
  const root = collectRoot("crawl-manual");
  if (!root) return;
  if (!root.innerHTML) root.innerHTML = `<p class="q-muted">불러오는 중…</p>`;
  let rules;
  try {
    [fetchKinds, rules] = await Promise.all([api("/api/data/fetch-sources"), api("/api/data/url-rules")]);
  } catch (err) {
    root.innerHTML = head("자료 직접 받기", "매일 수집이 빠뜨린 날이나 과거분을 메웁니다") + errorCard("화면을 준비하지 못했습니다", err);
    root.querySelector(".cl-retry")?.addEventListener("click", renderCollectFetch);
    return;
  }
  if (!(fetchKinds.kinds || []).some(k => k.kind === fetchKind)) fetchKind = fetchKinds.kinds?.[0]?.kind || "price";
  root.innerHTML = `${head("자료 직접 받기", "매일 수집이 빠뜨린 날이나 과거분을 손으로 메웁니다. 받을 범위를 먼저 보고, 받은 자료에는 출처와 이용 조건이 붙습니다.")}
    <div class="cl-two"><div class="cl-col"><div class="cl-form-slot">${fetchFormHtml()}</div></div>
      <div class="cl-col"><div class="card"><h3 class="cl-h">받을 범위</h3><div class="cl-plan-box"></div></div>${sourcesHtml()}</div></div>
    ${urlCardHtml(rules)}`;
  bindFetch(root);
  runFetchPlan(root);
  loadCollectDocs(root);
}

// ══ 3. 적재 · 백업 ══════════════════════════════════════════════════════
function gb(bytes) { return bytes ? `${(bytes / 1e9).toFixed(1)} GB` : "—"; }
function backupHtml(b) {
  const disk = b.disk;
  const diskCard = `<div class="card"><h3 class="cl-h">이 PC 용량</h3>
    ${disk ? `<div class="cl-tile cl-tile--soft" style="margin-bottom:10px"><div class="k">${escHtml(disk.drive || "")} 드라이브 여유</div><div class="v">${disk.free_gb} GB</div>
        <div class="d">전체 ${disk.total_gb} GB</div></div>
      <div class="cl-tile cl-tile--soft"><div class="k">수집 DB</div><div class="v">${disk.collector_db_gb} GB</div></div>
      <p class="cl-note" style="margin-top:10px">${day(disk.measured_at)} ${hm(disk.measured_at)} 기준 — 매일 수집 회차 끝에 잽니다</p>`
      : `<p class="q-muted">아직 잰 기록이 없습니다 — 다음 수집 회차 끝에 잽니다.</p>`}</div>`;
  const others = (b.datasets || []).map(h => `${escHtml(h.repo?.split("/").pop() || h.repo)} ${h.uploaded_at ? `${day(h.uploaded_at)} 올림` : "올린 기록 없음"}`).join(" · ");
  if (!b.available) {
    return `<div class="cl-backup"><div class="card"><div class="cl-alert">${escHtml(b.message)}</div>
        ${cmdBox(b.command, "이 PC 에서 한 번 돌리면 판정 기록이 생깁니다.")}
        <p class="cl-others">다른 데이터셋 — ${others || "이 PC 기록 없음"}</p></div>${diskCard}</div>`;
  }
  const m = b.manifest || {};
  const ratio = m.db_bytes ? `${Math.round((m.bytes / m.db_bytes) * 100)}%` : "—";
  const tiles = `<div class="cl-tiles">
      <div class="cl-tile cl-tile--soft"><div class="k">크기</div><div class="v">${gb(m.bytes)}</div></div>
      <div class="cl-tile cl-tile--soft"><div class="k">파일</div><div class="v">${m.files != null ? `${fmt(m.files)}개` : "—"}</div></div>
      <div class="cl-tile cl-tile--soft"><div class="k">행</div><div class="v">${m.rows != null ? fmt(m.rows) : "—"}</div></div>
      <div class="cl-tile cl-tile--soft"><div class="k">원본 ${gb(m.db_bytes)} 대비</div><div class="v">${ratio}</div></div></div>`;
  const up = b.uploaded;
  const list = (b.groups || []).map(g => {
    const label = g.key === "upload" && up?.at
      ? `마지막 올림 ${day(up.at)} ${hm(up.at)}${up.files_total ? ` · 파일 ${up.files_same} / ${up.files_total} 일치` : ""}` : g.label;
    return `<li><span class="q-dot cl-st--${GROUP_TONE[g.state]}"></span><span>${escHtml(label)}<span class="why">${escHtml(g.why || "")}</span></span>
      <span class="cl-st cl-st--${GROUP_TONE[g.state]}">${escHtml(g.state_label)}</span></li>`;
  }).join("");
  const verdict = b.can_delete
    ? `<div class="cl-alert cl-alert--ok">로컬 원본을 지워도 됩니다 — 조건 여섯이 모두 확인됐습니다.</div>`
    : `<div class="cl-alert">로컬 원본을 지워도 되나 — 아직 아닙니다. 남은 조건 ${b.remaining.length}(${b.remaining.map(escHtml).join(" · ")}).</div>`;
  return `<div class="cl-backup"><div class="card">
      <div class="cl-ds-head"><h3>시세 데이터셋 · ${escHtml((b.repo_id || "").split("/").pop() || "—")}</h3>
        <span class="q-muted">이 PC 기록 · ${day(b.written_at)} ${hm(b.written_at)}${b.remote_checked ? " · 원격까지 확인" : ""}</span></div>
      ${b.schema_note ? `<div class="cl-alert cl-alert--err">${escHtml(b.schema_note)}</div>` : ""}
      ${tiles}<ul class="cl-checklist">${list}</ul>${verdict}
      <div class="cl-actions" style="margin-top:12px"><button type="button" class="btn-secondary cl-bk-cmd" data-cmd="${escHtml(b.commands.remote)}"
          data-note="원격(Hugging Face)을 읽기만 합니다 — 올리거나 지우지 않습니다." aria-expanded="false">원격 다시 확인</button>
        <button type="button" class="btn-secondary cl-bk-cmd" data-cmd="${escHtml(b.commands.restore)}"
          data-note="임시 폴더에 파케이로 되살렸다가 지웁니다(수집 DB 는 그대로). 끝나면 판정 기록이 바뀝니다." aria-expanded="false">복원 리허설</button></div>
      <div class="cl-bk-slot"></div>
      <p class="cl-others">다른 데이터셋 — ${others || "이 PC 기록 없음"}</p></div>${diskCard}</div>`;
}
function bindBackup(root) {
  root.querySelectorAll(".cl-bk-cmd").forEach(btn => btn.addEventListener("click", () => {
    const slot = root.querySelector(".cl-bk-slot");
    const open = btn.getAttribute("aria-expanded") === "true";
    root.querySelectorAll(".cl-bk-cmd").forEach(b => b.setAttribute("aria-expanded", "false"));
    slot.innerHTML = open ? "" : cmdBox(btn.dataset.cmd, escHtml(btn.dataset.note || ""));
    if (!open) btn.setAttribute("aria-expanded", "true");
    bindCopy(slot);
  }));
  bindCopy(root);
}
async function renderCollectBackup() {
  const root = collectRoot("crawl-ingest");
  if (!root) return;
  if (!root.innerHTML) root.innerHTML = `<p class="q-muted">불러오는 중…</p>`;
  const lead = "수집 자료의 Hugging Face 백업 상태와 이 PC 용량을 봅니다. 새 자료는 매일 정해진 수집 단계로 들어옵니다.";
  try {
    const b = await api("/api/data/backup");
    root.innerHTML = `${head("적재 · 백업", lead)}${backupHtml(b)}`;
    bindBackup(root);
  } catch (err) {
    root.innerHTML = head("적재 · 백업", lead) + errorCard("백업 상태를 읽지 못했습니다", err);
    root.querySelector(".cl-retry")?.addEventListener("click", renderCollectBackup);
  }
}

/** main.js 의 화면 진입 훅 — 화면 키는 글자 그대로(화면 스캐너 scripts/view_scan.py 가 이 모양으로 읽는다). */
export function onCollectViewActivated(view) {
  ensureCollectRole();
  if (view !== "crawl-auto") stopRequestPolling();   // 다른 화면으로 가면 요청 다시 묻기 · 대기 창을 멈춘다
  if (view === "crawl-auto") { pickedRun = "last"; renderCollectSchedule(); }   // 들어올 때마다 마지막 회차부터
  if (view === "crawl-manual") renderCollectFetch();
  if (view === "crawl-ingest") renderCollectBackup();
}
