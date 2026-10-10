/* 화면에서 수집 단추 — 「수집 일정 · 단계」 화면의 요청 부분과 데이터 관제의 요청 한 줄 (2026-10-10 · Figma 「데이터 수집 화면」
 * 03-2 설계 · 결정 안 A)
 *
 *   GET  /api/data/runner/requests?limit=10      요청 목록 · PC 작업자 상태 · 막는 때(rules · blocked_now)   API-DATA-13
 *   POST /api/data/runner/requests               만들기 — 단계 하나 · 전체 수집 · 빠진 날 채우기             API-DATA-12
 *   POST /api/data/runner/requests/{id}/cancel   취소 — 대기일 때만                                         API-DATA-14
 *
 * 화면은 요청 줄만 남기고, 이 PC 의 수집 작업자(scripts/collect_worker.py · 작업 스케줄러 매 분)가 가져가 러너를 돌린다 — 화면이
 * PC 쪽 일을 직접 돌리지 않는다(2026-10-08 결정 ① 의 뜻 그대로 · TC-CL-06). 상태를 바꾸는 두 부름은 늘 화면 머리글을 붙인다.
 * 글(요청 상태 · 작업자 상태 · 기다리는 까닭 · 결과 한 줄)은 서버가 준 글 그대로 — 화면은 색만 고른다(TC-CL-09).
 * 막는 때에는 단추를 끈다(2026-10-10 결정 ②) — 판정은 서버의 rules.blocked_now 그대로, 화면이 시계로 다시 세지 않는다(TC-CL-10).
 * 빠진 날 채우기(2026-10-10 · Figma 03-3 결정) — 러너가 적은 채울 날이 있는 단계만 「다시 받기」 가 「빠진 날 채우기(n일)」 로
 * 바뀌고, 누르면 확인 창 → 러너가 적은 첫날 · 마지막 날 그대로 요청한다(화면은 날짜를 셈하지 않는다 · TC-CL-17 · 18).
 * 실패한 요청의 까닭(DF-101) — 작업자가 결과 한 줄 끝에 붙인 까닭을 떼어 결과 아래 한 줄로 보인다(결정 안 A · TC-CL-16).
 *
 * 대기 창은 강사님 기초 코드(lumina-invest 2026-10-08 판)의 「데이터 조회 대기 모달」 — app.html 의 #app-loading-modal ·
 * app.css 의 .app-modal-box · .app-hourglass · indicator.js 의 열기 · 닫기 — 꼴을 가져와 고쳤다(2026-10-10 결정 ③):
 * 모래시계 · 경과 시간은 그대로 두고, 단계 이름 · 요청 상태 · 결과 한 줄 · 「창 닫기」(요청은 계속) · 대기일 때 「요청 취소」 를
 * 더했다. app.html 에는 넣지 않고 이 파일이 창을 만든다(강사님 파일을 고치지 않아 다음 반영 때 부딪히지 않게).
 */
import { api, escHtml, getMe, setToast } from "/js/common.js";

//: 상태를 바꾸는 요청에 붙이는 화면 머리글 — 서버 app/services/collect_requests.py 의 ACTION_HEADER · ACTION_VALUE 와 같다(TC-CL-06)
const ACTION = { "X-Qurious-Action": "collect" };
//: 결과 한 줄과 까닭 사이 — 작업자 scripts/collect_worker.py 의 WHY_SEP 와 같다(TC-CL-16 이 맞대 본다)
const WHY_SEP = " · 까닭: ";
//: 대기 · 도는 중인 줄이 있는 동안 다시 묻는 간격 — 작업자는 1분마다 가져가므로 이보다 자주 물을 까닭이 없다
const POLL_MS = 5000;
//: 그 밖에는 1분마다 — 작업자 띠(꺼짐 · 신호)와 막는 때(단추 끄기)가 화면을 열어 둔 채로도 1분 안에 따라오게.
//: 요청이 없을 때 멈추게 했더니 띠가 25분 넘게 「꺼짐」 으로 남았다(2026-10-10 실측) — 11:00 에 막는 때가 와도 단추가 켜진 채였을 것
const IDLE_POLL_MS = 60000;
const ACTIVE = ["queued", "running"];
//: 요청 상태 → 칩 색(글은 서버 status_label 그대로 · 열쇠는 서버 STATUS_LABEL 과 같다 — TC-CL-09)
const REQ_TONE = { queued: "queued", running: "running", done: "done", warning: "warning", failed: "failed",
  rejected: "muted", cancelled: "muted", expired: "muted" };
//: 작업자 상태 → 점 · 띠 색(글은 서버 status_label 그대로 · 열쇠는 서버 WORKER_LABEL 과 같다)
const WORKER_TONE = { idle: "idle", waiting: "wait", running: "busy", off: "off", missing: "off" };

let state = null;          // 마지막 목록 응답 {requests, worker, rules, checked_at}
let loadError = null;      // 목록을 읽지 못한 까닭(화면 띠에 보인다)
let pollTimer = null;
let onChange = null;       // 수집 일정 화면이 넘긴 다시 그리기 — 목록이 바뀌면 "requests", 도는 줄이 끝나면 "finished"
let waitFor = null;        // 대기 창이 보는 요청 번호
let tick = null;           // 대기 창의 경과 시간(1초)
let adminCheck = null;

// ── 작은 도구 ──────────────────────────────────────────────────────────
function hm(iso) { return iso ? iso.slice(11, 16) : ""; }
function clock(sec) {
  const s = Math.max(0, Math.round(sec || 0));
  return s >= 3600 ? `${Math.floor(s / 3600)}:${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`
    : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
function since(iso) { return iso ? (Date.now() - new Date(iso).getTime()) / 1000 : 0; }
function took(r) {
  if (!r.started_at || !r.finished_at) return "";
  const s = Math.round((new Date(r.finished_at) - new Date(r.started_at)) / 1000);
  return s >= 60 ? `${Math.floor(s / 60)}분 ${s % 60}초` : `${s}초`;
}
function ago(sec) {
  if (sec == null) return "";
  return sec >= 3600 ? `${Math.floor(sec / 3600)}시간 전` : sec >= 60 ? `${Math.floor(sec / 60)}분 전` : `${sec}초 전`;
}
/** 요청이 무엇인가 — 전체 수집 · 「시세 다시 받기」 · 「신호 빠진 날 채우기 · 10-02 ~ 10-06」(날짜는 서버 글을 잘라 보인다) */
function what(r) {
  if (r.kind === "all") return r.kind_label;
  if (r.kind === "fill") {
    const range = !(r.date_from && r.date_to) ? ""
      : r.date_from === r.date_to ? ` · ${r.date_from.slice(5)}` : ` · ${r.date_from.slice(5)} ~ ${r.date_to.slice(5)}`;
    return `${r.step_label || r.step} ${r.kind_label}${range}`;
  }
  return `${r.step_label || r.step} 다시 받기`;
}
/** 결과 한 줄 — 작업자가 끝에 붙인 까닭(WHY_SEP 뒤)은 떼어 결과 아래 한 줄로(실패한 단계의 까닭 · DF-101 · 결정 안 A) */
function resultHtml(r) {
  const text = r.status === "queued" ? (r.wait || "") : (r.result || "");
  const at = r.status === "queued" ? -1 : text.indexOf(WHY_SEP);
  if (at < 0) return escHtml(text);
  return `${escHtml(text.slice(0, at))}<span class="cq-why"><span class="cl-why-k">까닭</span>${escHtml(text.slice(at + WHY_SEP.length))}</span>`;
}
function isActive(r) { return ACTIVE.includes(r.status); }

// ── 읽기 ───────────────────────────────────────────────────────────────
/** 관리자인가 — 처음 한 번 묻는다(데이터 관제의 요청 한 줄이 일반 사용자에게 요청 API 를 부르지 않게) */
export function isCollectAdmin() {
  if (!adminCheck) {
    adminCheck = getMe().then(({ user }) => (user?.roles || []).includes("admin")).catch(() => false);
  }
  return adminCheck;
}

export async function loadRequests() {
  try {
    state = await api("/api/data/runner/requests?limit=10");
    loadError = null;
  } catch (err) {
    loadError = err;
    throw err;
  }
  return state;
}

/** 같은 대상(종류 + 단계)의 대기 · 도는 중 요청 — 서버도 활성 줄을 하나만 둔다(멱등) */
function activeFor(kind, step) {
  return (state?.requests || []).find(r => isActive(r) && r.kind === kind && (kind === "all" || r.step === step)) || null;
}
/** 지금 막는 때인가 — 서버가 서버 시각으로 정한 값 그대로({blocked, until} · 모르면 null) · 채우기는 그 단계의 채우기 창 */
function blockedFor(kind, step) {
  if (kind === "all") return state?.rules?.blocked_now?.full || null;
  if (kind === "fill") return state?.rules?.blocked_now?.fill?.[step] || null;
  return state?.rules?.blocked_now?.steps?.[step] || null;
}

// ── 그리기 ─────────────────────────────────────────────────────────────
/** 화면 위 작업자 띠 — 상태 · 마지막 신호 · 기다리는 까닭(서버 글) · 막는 때 */
export function workerBandHtml() {
  if (!state) {
    const why = loadError?.status === 403 ? "관리자만 볼 수 있습니다" : escHtml(loadError?.message || "불러오는 중…");
    return `<div class="cq-band cq-band--off"><span class="cq-dot cq-dot--off"></span><b>수집 요청</b><span>${why}</span></div>`;
  }
  const w = state.worker || {};
  const tone = WORKER_TONE[w.status] || "off";
  const run = (state.requests || []).find(r => r.status === "running");
  let detail = "";
  if (tone === "idle") detail = `${ago(w.seen_ago_s)} 신호 · 요청은 1분 안에 시작합니다`;
  else if (tone === "busy") detail = run ? `${what(run)} · 경과 ${clock(since(run.started_at))}` : `${ago(w.seen_ago_s)} 신호`;
  else if (tone === "wait") detail = w.note || `${ago(w.seen_ago_s)} 신호`;
  else detail = `요청은 받지만 작업자가 켜질 때까지 기다립니다 — ${w.note || ""}`;
  const full = state.rules?.full;
  const guard = full ? `막는 때 — 전체 수집 ${full.from} ~ ${full.to} · 단계마다 다름` : (state.rules?.note || "");
  return `<div class="cq-band cq-band--${tone}" role="status"><span class="cq-dot cq-dot--${tone}"></span>
    <b>PC 작업자 ${escHtml(w.status_label || "")}</b><span>${escHtml(detail)}</span>
    <span class="cq-band-right">${escHtml(guard)}</span></div>`;
}

/** 맨 위 「전체 수집」 단추 — 막는 때 · 수집 중 · 이미 요청한 때는 꺼진다 */
export function fullButtonHtml(runnerBusy) {
  const act = activeFor("all", "");
  const b = blockedFor("all");
  let why = "";
  if (act) why = `이미 요청했습니다 — ${act.status_label}`;
  else if (runnerBusy) why = "수집 중에는 요청할 수 없습니다";
  else if (b?.blocked) why = `막는 때입니다 — ${b.until} 뒤에 누를 수 있습니다`;
  else if (!state) why = "수집 요청을 읽지 못했습니다";
  return `<button type="button" class="cq-primary cq-full" ${why ? `disabled title="${escHtml(why)}"` : ""}>
    <i class="fa-solid fa-rotate" aria-hidden="true"></i> ${act ? "전체 수집 요청함" : "전체 수집"}</button>`;
}

/** 단계 줄의 「다시 받기」 + 「명령」 + 그 줄의 요청 상태. `fill`({from, to, days} · collect.js 의 fillFor)이 있으면 단추가
 *  「빠진 날 채우기(n일)」 로 바뀐다 — 날짜 · 날 수는 러너가 적은 그대로 단추에 싣는다(2026-10-10 결정 「빠진 날이 있을 때만」) */
export function stepActionHtml(name, runnerBusy, fill = null) {
  const act = activeFor(fill ? "fill" : "step", name);
  const b = blockedFor(fill ? "fill" : "step", name);
  let why = "";
  if (act) why = `이미 요청했습니다 — ${act.status_label}`;
  else if (runnerBusy) why = "수집 중에는 요청할 수 없습니다";
  else if (b?.blocked) why = `막는 때입니다 — ${b.until} 뒤에 누를 수 있습니다`;
  else if (!state) why = "수집 요청을 읽지 못했습니다";
  let line = "";
  if (act) {
    // 줄 칸은 좁다 — 서버 글의 앞마디만(「PC 작업자 꺼짐」 · 「곧 시작합니다(…)」) · 긴 까닭은 위 띠 · 대기 창 · 요청 목록에 그대로
    const how = act.status === "running" ? `경과 ${clock(since(act.started_at))}` : (act.wait || "").split(" — ")[0];
    line = `<div class="cq-rowstate cq-rowstate--${REQ_TONE[act.status]}">${escHtml(act.status_label)}${how ? ` · ${escHtml(how)}` : ""}</div>`;
  } else if (b?.blocked && !runnerBusy) {
    line = `<div class="cq-rowstate cq-rowstate--muted">${escHtml(b.until)} 뒤에 누를 수 있음</div>`;
  }
  const off = why ? `disabled title="${escHtml(why)}"` : "";
  const main = fill
    ? `<button type="button" class="cq-btn cq-fill" data-step="${escHtml(name)}" data-from="${escHtml(fill.from)}" data-to="${escHtml(fill.to)}" data-days="${fill.days}" ${off}>${act ? "요청함" : `빠진 날 채우기(${fill.days}일)`}</button>`
    : `<button type="button" class="cq-btn cq-rerun" data-step="${escHtml(name)}" ${off}>${act ? "요청함" : "다시 받기"}</button>`;
  return `${main}<button type="button" class="cq-link cl-cmd-open" data-step="${escHtml(name)}" aria-expanded="false">명령</button>${line}`;
}

/** 아래 「수집 요청」 카드 — 최근 10건 · 대기 줄에만 「취소」 */
export function requestsCardHtml() {
  const reqs = state?.requests || [];
  const rows = reqs.map(r => `<tr class="${isActive(r) ? "cq-row--active" : ""}" data-req="${escHtml(r.id)}">
      <td><span class="cq-chip cq-chip--${REQ_TONE[r.status] || "muted"}">${escHtml(r.status_label)}</span></td>
      <td class="cq-what">${escHtml(what(r))}</td>
      <td class="cq-when">${hm(r.requested_at)}${r.requested_by_name ? ` · ${escHtml(r.requested_by_name)}` : ""}</td>
      <td class="cq-when">${r.started_at ? `${hm(r.started_at)} → ${r.finished_at ? `${hm(r.finished_at)} · ${took(r)}` : "도는 중"}` : "—"}</td>
      <td class="cq-res ${r.status === "queued" ? "cq-res--wait" : ""}">${resultHtml(r)}</td>
      <td class="cl-act">${r.status === "queued" ? `<button type="button" class="cl-btn-sm cq-cancel" data-id="${escHtml(r.id)}">취소</button>` : ""}</td></tr>`).join("");
  const body = reqs.length ? `<div class="cl-table-wrap"><table class="cl-table cq-req"><thead><tr><th>상태</th><th>무엇</th><th>요청</th>
      <th>시작 → 끝</th><th>결과</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`
    : `<p class="q-muted">아직 요청이 없습니다 — 단계 줄의 「다시 받기」 · 「빠진 날 채우기」 나 위의 「전체 수집」 으로 남깁니다.</p>`;
  return `<div class="card"><h3 class="cl-h">수집 요청 <span class="q-muted">최근 10건 · 대기 · 도는 중인 요청이 있으면 5초, 없으면 1분마다 새로 고칩니다</span></h3>${body}</div>`;
}

// ── 쓰기 ───────────────────────────────────────────────────────────────
async function refresh() {
  try { await loadRequests(); } catch { /* 띠에 까닭을 보인다 · 다음 바퀴에 다시 */ }
  onChange?.("requests");
  updateWaitModal();
  schedulePoll();
}

/** 요청 만들기 — 새 줄이면 「요청했습니다」, 같은 대상이 이미 대기 · 도는 중이면 그 줄(새 줄 없음 · 서버 멱등).
 *  빠진 날 채우기는 `range`({from, to} — 러너가 적은 날짜 그대로)를 날짜 두 칸으로 싣는다 · 다른 종류에는 싣지 않는다(서버가 422) */
export async function requestCollect(kind, step, range = null) {
  const body = { kind, step: kind === "all" ? null : step };
  if (kind === "fill") Object.assign(body, { date_from: range.from, date_to: range.to });
  let res;
  try {
    res = await api("/api/data/runner/requests", { method: "POST", headers: ACTION, body });
  } catch (err) {
    // 403 은 관리자 아님(또는 머리글 없음) · 409 · 422 는 서버 글 그대로(422 = 단계 목록이 바뀜 → 단계 표를 다시 읽는다)
    setToast(err.status === 403 ? "관리자만 요청할 수 있습니다" : err.message, "error");
    if (err.status === 422) onChange?.("finished");
    else await refresh();
    return null;
  }
  const r = res.request;
  if (res.created) setToast(`요청했습니다 — ${what(r)} · PC 작업자가 1분 안에 가져갑니다`, "ok");
  else setToast(`이미 기다리는 요청이 있습니다 — ${what(r)} · ${r.status_label}`, "info");
  await refresh();
  openWaitModal(r.id);
  return r;
}

/** 대기 요청 취소 — 대기가 아니면 서버가 409(그 글 그대로) */
export async function cancelRequest(id) {
  try {
    await api(`/api/data/runner/requests/${id}/cancel`, { method: "POST", headers: ACTION });
    setToast("요청을 취소했습니다", "ok");
  } catch (err) {
    setToast(err.status === 403 ? "관리자만 요청할 수 있습니다" : err.message, "error");
  }
  await refresh();
}

/** 「전체 수집」 확인 창 — 단계 수 · 지난 회차 길이 · 올리기 · 막는 때 · 만료를 보이고 누르면 요청 */
export function confirmFullCollect({ steps, lastSeconds }) {
  document.getElementById("cq-confirm-modal")?.remove();
  const w = state?.worker || {};
  const full = state?.rules?.full;
  const mins = lastSeconds ? `${Math.floor(lastSeconds / 60)}분 ${Math.round(lastSeconds % 60)}초` : "";
  const m = document.createElement("div");
  m.id = "cq-confirm-modal";
  m.className = "cq-modal-bg";
  m.innerHTML = `<div class="cq-modal" role="dialog" aria-modal="true" aria-labelledby="cq-confirm-title">
      <h3 id="cq-confirm-title">전체 수집을 요청할까요?</h3>
      <ul><li>받기 → 계산 → 백업 → 근거 문서, ${steps}단계를 차례로 돌립니다.</li>
        ${mins ? `<li>지난 회차는 <b>${mins}</b> 걸렸습니다.</li>` : ""}
        <li>${w.allow_upload === false ? "이 PC 의 작업자는 HF 데이터셋 올리기를 하지 않습니다." : "HF 데이터셋 올리기까지 합니다 — 정기 회차와 같습니다."}</li>
        ${full ? `<li>${full.from} ~ ${full.to} 에는 정기 회차를 지키려고 단추를 끕니다. 요청한 뒤 ${state.rules.expire_hours}시간 안에 시작하지 못하면 만료됩니다.</li>` : ""}</ul>
      <div class="cq-mnote">지금 PC 작업자: ${escHtml(w.status_label || "모름")}${w.seen_ago_s != null ? `(${ago(w.seen_ago_s)} 신호)` : ""}</div>
      <div class="cq-mfoot"><button type="button" class="btn-secondary cq-confirm-no">닫기</button>
        <button type="button" class="cq-primary cq-confirm-yes">전체 수집 요청</button></div></div>`;
  document.body.appendChild(m);
  const close = () => m.remove();
  m.querySelector(".cq-confirm-no").addEventListener("click", close);
  m.addEventListener("click", e => { if (e.target === m) close(); });
  m.addEventListener("keydown", e => { if (e.key === "Escape") close(); });
  m.querySelector(".cq-confirm-yes").addEventListener("click", () => { close(); requestCollect("all"); });
  m.querySelector(".cq-confirm-no").focus();
}

/** 「빠진 날 채우기」 확인 창 — 단계 · 첫날 ~ 마지막 날 · 날 수 · 상한(서버 fill_max_days) · 막는 때(서버 rules.fill)를 보이고
 *  누르면 요청한다. 날짜는 러너가 적은 그대로 넘긴다(화면이 셈하지 않는다 · TC-CL-18) */
export function confirmFill({ step, label, from, to, days }) {
  document.getElementById("cq-confirm-modal")?.remove();
  const w = state?.worker || {};
  const win = state?.rules?.fill?.[step];
  const max = state?.rules?.fill_max_days;
  const m = document.createElement("div");
  m.id = "cq-confirm-modal";
  m.className = "cq-modal-bg";
  m.innerHTML = `<div class="cq-modal" role="dialog" aria-modal="true" aria-labelledby="cq-confirm-title">
      <h3 id="cq-confirm-title">${escHtml(label)} 빠진 날을 채울까요?</h3>
      <ul><li><b>${from === to ? escHtml(from) : `${escHtml(from)} ~ ${escHtml(to)}`}</b> — 빠진 거래일 ${days}일을 한 번에 계산합니다.</li>
        <li>같은 날을 다시 계산해도 값만 바뀝니다 — 여러 번 돌려도 안전합니다.</li>
        ${max ? `<li>한 번에 ${max}일까지 채웁니다. 더 남은 날은 다음 묶음으로 다시 나옵니다.</li>` : ""}
        ${win ? `<li>${win.from} ~ ${win.to} 에는 정기 회차를 지키려고 단추를 끕니다. 요청한 뒤 ${state.rules.expire_hours}시간 안에 시작하지 못하면 만료됩니다.</li>` : ""}</ul>
      <div class="cq-mnote">지금 PC 작업자: ${escHtml(w.status_label || "모름")}${w.seen_ago_s != null ? `(${ago(w.seen_ago_s)} 신호)` : ""}</div>
      <div class="cq-mfoot"><button type="button" class="btn-secondary cq-confirm-no">닫기</button>
        <button type="button" class="cq-primary cq-confirm-yes">빠진 날 채우기 요청</button></div></div>`;
  document.body.appendChild(m);
  const close = () => m.remove();
  m.querySelector(".cq-confirm-no").addEventListener("click", close);
  m.addEventListener("click", e => { if (e.target === m) close(); });
  m.addEventListener("keydown", e => { if (e.key === "Escape") close(); });
  m.querySelector(".cq-confirm-yes").addEventListener("click", () => { close(); requestCollect("fill", step, { from, to }); });
  m.querySelector(".cq-confirm-no").focus();
}

// ── 대기 창(강사님 대기 모달 꼴을 고침) ─────────────────────────────────
function ensureWaitModal() {
  let m = document.getElementById("cq-wait-modal");
  if (m) return m;
  m = document.createElement("div");
  m.id = "cq-wait-modal";
  m.className = "cq-modal-bg";
  m.hidden = true;
  m.innerHTML = `<div class="cq-modal cq-wait-box" role="dialog" aria-modal="true" aria-live="polite" aria-labelledby="cq-wait-title">
      <div class="cq-hourglass" aria-hidden="true"><i class="fa-solid fa-hourglass-half"></i></div>
      <h3 id="cq-wait-title" class="cq-wait-title"></h3>
      <div class="cq-wait-state"></div>
      <div class="cq-wait-elapsed">0:00</div>
      <p class="cq-wait-note">창을 닫아도 요청은 그대로 돕니다 — 결과는 단계 표와 아래 「수집 요청」 에 남습니다.</p>
      <div class="cq-mfoot"><button type="button" class="btn-secondary cq-wait-cancel">요청 취소</button>
        <button type="button" class="cq-primary cq-wait-close">창 닫기</button></div></div>`;
  document.body.appendChild(m);
  m.querySelector(".cq-wait-close").addEventListener("click", closeWaitModal);
  m.querySelector(".cq-wait-cancel").addEventListener("click", () => { if (waitFor) cancelRequest(waitFor); });
  m.addEventListener("keydown", e => { if (e.key === "Escape") closeWaitModal(); });
  return m;
}

export function openWaitModal(id) {
  waitFor = id;
  const m = ensureWaitModal();
  m.hidden = false;
  updateWaitModal();
  clearInterval(tick);
  tick = setInterval(updateWaitElapsed, 1000);
  m.querySelector(".cq-wait-close").focus();
  schedulePoll();
}

function updateWaitElapsed() {
  const m = document.getElementById("cq-wait-modal");
  const r = (state?.requests || []).find(x => x.id === waitFor);
  if (!m || m.hidden || !r) return;
  const from = r.status === "running" ? r.started_at : r.requested_at;
  if (isActive(r)) m.querySelector(".cq-wait-elapsed").textContent = clock(since(from));
}

function updateWaitModal() {
  const m = document.getElementById("cq-wait-modal");
  if (!m || m.hidden || !waitFor) return;
  const r = (state?.requests || []).find(x => x.id === waitFor);
  if (!r) return;
  m.querySelector(".cq-wait-title").textContent = what(r);
  m.querySelector(".cq-wait-state").innerHTML = `<span class="cq-chip cq-chip--${REQ_TONE[r.status] || "muted"}">${escHtml(r.status_label)}</span>
    <span>${resultHtml(r)}</span>`;
  m.querySelector(".cq-wait-cancel").hidden = r.status !== "queued";
  const done = !isActive(r);
  m.querySelector(".cq-hourglass").classList.toggle("cq-hourglass--done", done);
  if (done) m.querySelector(".cq-wait-elapsed").textContent = took(r) || "—";
  else updateWaitElapsed();
}

function closeWaitModal() {
  waitFor = null;
  clearInterval(tick);
  tick = null;
  const m = document.getElementById("cq-wait-modal");
  if (m) m.hidden = true;
  schedulePoll();
}

// ── 다시 묻기 — 대기 · 도는 중 · 대기 창이 열린 동안 5초 · 그 밖에는 1분(수집 일정 화면에 있는 동안만) ───────────
function needPoll() {
  return !!(waitFor || (state?.requests || []).some(isActive) || state?.worker?.status === "running");
}
function schedulePoll() {
  clearTimeout(pollTimer);
  pollTimer = onChange ? setTimeout(pollOnce, needPoll() ? POLL_MS : IDLE_POLL_MS) : null;
}
async function pollOnce() {
  const before = new Set((state?.requests || []).filter(isActive).map(r => r.id));
  try { await loadRequests(); } catch { /* 다음 바퀴에 다시 */ }
  const finished = (state?.requests || []).filter(r => before.has(r.id) && !isActive(r));
  // 도는 줄이 끝나면 단계 표(회차 기록)를 한 번 다시 읽는다 — 그 단계의 결과 · 걸린 시간이 바뀐다
  onChange?.(finished.length ? "finished" : "requests");
  updateWaitModal();
  schedulePoll();
}

/** 수집 일정 화면이 그린 뒤 부른다 — 바뀌면 cb("requests" | "finished") */
export function startRequestPolling(cb) {
  onChange = cb;
  schedulePoll();
}
/** 다른 화면으로 가면 멈춘다(main.js 의 진입 훅 · collect.js) */
export function stopRequestPolling() {
  clearTimeout(pollTimer);
  pollTimer = null;
  onChange = null;
  closeWaitModal();
  document.getElementById("cq-confirm-modal")?.remove();
}

// ── 데이터 관제의 요청 한 줄(관리자만 · 2026-10-10 결정 ① — 안 B 의 작업자 · 최근 요청) ───────────────
export async function renderHubRequestLine(el, goCollect) {
  if (!el) return;
  if (!(await isCollectAdmin())) { el.hidden = true; return; }   // 일반 사용자에게는 칸도 요청 API 도 없다
  try {
    const d = await api("/api/data/runner/requests?limit=10");
    const w = d.worker || {};
    const reqs = d.requests || [];
    const queued = reqs.filter(r => r.status === "queued").length;
    const running = reqs.filter(r => r.status === "running").length;
    const last = reqs[0];
    el.innerHTML = `<span class="cq-dot cq-dot--${WORKER_TONE[w.status] || "off"}"></span>
      <span><strong>PC 작업자 ${escHtml(w.status_label || "")}</strong> · 대기 ${queued} · 도는 중 ${running}${last
        ? ` · 최근 ${escHtml(what(last))} ${escHtml(last.status_label)} ${hm(last.requested_at)}` : " · 요청 없음"}</span>
      <button type="button" class="dh-more cq-hub-more">수집 요청 →</button>`;
    el.querySelector(".cq-hub-more")?.addEventListener("click", () => goCollect?.());
  } catch (err) {
    el.innerHTML = `<span class="q-muted">수집 요청을 읽지 못했습니다 — ${escHtml(err.message)}</span>`;
  }
}
