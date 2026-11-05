/* 시스템 대시보드, 감사 로그
 * app.html 인라인 스크립트에서 분리됨. 엔트리는 main.js */
import { api, getMe, setToast, escHtml, fmt, fmtPct, colorPct } from "/js/common.js";
import { createListPanel } from "/js/paperlists.js";
import { auditCfg, ensureBarHost, AUDIT_LIMIT } from "/js/listbar-misc.js";

// ── 시스템 대시보드 ───────────────────────────────────────────────
async function loadSystemDashboard() {
  const hostEl  = document.getElementById("sys-host");
  const svcEl   = document.getElementById("sys-services");
  const contEl  = document.getElementById("sys-containers");
  if (!hostEl) return;
  hostEl.innerHTML = "<div class='col-span-3 text-slate-400 text-sm'>조회 중...</div>";
  try {
    const d = await api("/api/system/status");

    // 호스트 카드
    const h = d.host || {};
    hostEl.innerHTML = [
      { label: "CPU", value: h.cpu_pct != null ? `${h.cpu_pct}%` : "N/A", sub: "" },
      { label: "메모리", value: h.mem_pct != null ? `${h.mem_pct}%` : "N/A",
        sub: `${h.mem_used_gb ?? "-"}GB / ${h.mem_total_gb ?? "-"}GB` },
      { label: "디스크", value: `${d.disk?.pct ?? "-"}%`,
        sub: `${d.disk?.used_gb ?? "-"}GB / ${d.disk?.total_gb ?? "-"}GB` },
    ].map(c => `
      <div class="card text-center">
        <div class="text-xs text-slate-400">${c.label}</div>
        <div class="text-2xl font-bold text-indigo-300 mt-1">${c.value}</div>
        <div class="text-xs text-slate-500">${c.sub}</div>
      </div>
    `).join("");

    // 서비스 상태
    svcEl.innerHTML = (d.services || []).map(s => `
      <div class="card flex items-center gap-3">
        <span class="text-xl">${s.ok ? "🟢" : "🔴"}</span>
        <div>
          <div class="font-medium text-sm">${escHtml(s.name)}</div>
          <div class="text-xs text-slate-400">${s.ok ? `응답 ${s.ms}ms` : "연결 실패"}</div>
          <div class="text-xs text-slate-500 font-mono truncate max-w-[140px]">${escHtml(s.url)}</div>
        </div>
      </div>
    `).join("");

    // Docker 컨테이너
    if (!d.containers?.length) {
      contEl.innerHTML = "<div class='text-slate-400 text-sm'>Docker 정보를 가져올 수 없습니다 (CLI 미접근).</div>";
    } else {
      contEl.innerHTML = d.containers.map(c => `
        <div class="card flex items-center gap-3">
          <span class="text-lg">${c.up ? "🟩" : "🟥"}</span>
          <div class="flex-1 grid grid-cols-4 gap-2 text-sm">
            <div><span class="text-xs text-slate-500">이름</span><br>${escHtml(c.name)}</div>
            <div><span class="text-xs text-slate-500">이미지</span><br><span class="font-mono text-xs">${escHtml(c.image)}</span></div>
            <div><span class="text-xs text-slate-500">상태</span><br>${escHtml(c.status)}</div>
            <div><span class="text-xs text-slate-500">포트</span><br><span class="font-mono text-xs">${escHtml(c.ports || "-")}</span></div>
          </div>
        </div>
      `).join("");
    }
  } catch (e) {
    hostEl.innerHTML = `<div class='col-span-3 text-red-400 text-sm'>${escHtml(e.message)}</div>`;
  }
}

document.getElementById("sys-refresh")?.addEventListener("click", loadSystemDashboard);

// ── 시스템관리: 감사 로그 ────────────────────────────────────────
// 이벤트 유형 칩(응답 events 의 event_type) + 새로고침(2026-11-05). 위 입력 칸 2개와 「조회」 단추는 그대로 — 서버가 입력 칸 조건으로 먼저 거르고,
// 칩은 그렇게 받은 줄 안에서만 거른다. 새로고침은 같은 조건으로 서버에서 다시 읽을 뿐이다(설정 · 기록을 바꾸지 않는다). 설정은 js/listbar-misc.js(auditCfg).
async function fetchAuditLog() {
  const eventType = document.getElementById("audit-event-filter")?.value || "";
  const userId = document.getElementById("audit-user-filter")?.value || "";
  const qs = new URLSearchParams({ event_type: eventType, user_id: userId, limit: String(AUDIT_LIMIT) });
  return api(`/api/admin/audit-log?${qs.toString()}`);
}
const auditPanel = createListPanel(auditCfg({ esc: escHtml, load: fetchAuditLog }), { esc: escHtml, byId: id => document.getElementById(id) });

async function loadAuditLog() {
  const el = document.getElementById("audit-log");
  if (!el) return;
  ensureBarHost(document, "audit-log", "audit-log-bar");     // 칩 줄은 스크롤 상자(#audit-log) 밖에
  if (!auditPanel.state().rows.length) el.innerHTML = "<div class='text-slate-400'>조회 중...</div>";
  await auditPanel.load();
}
document.getElementById("audit-refresh-btn")?.addEventListener("click", loadAuditLog);


export { loadAuditLog, loadSystemDashboard };
