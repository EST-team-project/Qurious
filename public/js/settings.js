/* 증권사 Open API 설정, 알림 설정
 * app.html 인라인 스크립트에서 분리됨. 엔트리는 main.js */
import { api, getMe, setToast, escHtml, fmt, fmtPct, colorPct } from "/js/common.js";
import { executionModeView, renderExecutionMode } from "/js/execution-mode.js";
import { NOTIFY_CONSENT, NOTIFY_CONSENT_VERSION } from "/js/terms.js";

// ── 설정 (증권사 Open API) ────────────────────────────────────────
let lastLoadedMode = "paper";
let lastLiveGateway = null;
async function loadSettings() {
  try {
    const cfg = await api("/api/quant/settings");
    lastLoadedMode = cfg.mode || "paper";
    document.getElementById("quant-mode").value = cfg.mode || "paper";
    document.getElementById("quant-symbol-source").value = cfg.symbol_source || "ai";
    document.getElementById("broker-type").value   = cfg.broker || "mock";
    document.getElementById("broker-app-key").value = cfg.app_key || "";
    document.getElementById("broker-app-secret").value = "";
    document.getElementById("broker-account").value = cfg.account_no || "";
    document.getElementById("broker-paper").checked = cfg.paper !== false;
    document.getElementById("quant-ai-top-n").value = cfg.ai_top_n || 3;
    document.getElementById("quant-per-trade-budget").value = cfg.per_trade_budget || 1000000;
    document.getElementById("quant-buy-ratio").value = Math.round((cfg.buy_ratio ?? 1) * 100);
    document.getElementById("quant-sell-ratio").value = Math.round((cfg.sell_ratio ?? 0.5) * 100);
    const ep = cfg.execution_policy || {};
    document.getElementById("quant-size-kind").value = ep.size_kind || "fixed_budget";
    document.getElementById("quant-risk-pct").value = ep.risk_pct ?? 1;
    document.getElementById("quant-stop-pct").value = ep.stop_loss_pct ?? 1;
    document.getElementById("quant-risk-slip").value = ep.slippage_bps ?? 10;
    document.getElementById("quant-retry-enabled").checked = !!ep.retry_enabled;
    document.getElementById("quant-retry-attempts").value = ep.retry_max_attempts ?? 1;
    document.getElementById("quant-retry-window").value = ep.retry_window_min ?? 15;
    document.getElementById("quant-retry-deviation").value = ep.retry_price_deviation_pct ?? 1;
    document.getElementById("quant-execution-capabilities").textContent = [cfg.execution_capabilities?.retry_note, cfg.execution_capabilities?.stop_note].filter(Boolean).join(" ");
    const rk = cfg.risk || {};
    document.getElementById("risk-daily-loss").value   = rk.daily_loss_limit_pct ?? 3;
    document.getElementById("risk-max-position").value = rk.max_position_pct ?? 30;
    document.getElementById("risk-max-orders").value   = rk.max_orders_per_day ?? 20;
    document.getElementById("risk-cooldown").value     = rk.cooldown_min ?? 30;
    document.getElementById("risk-kill-badge").innerHTML = rk.kill_switch
      ? `<span class="badge-sell">🛑 비상 정지 ON${cfg.risk_halt_reason ? " · " + escHtml(cfg.risk_halt_reason) : ""}</span>`
      : `<span class="badge-buy">정상</span>`;
    const selected = new Set(cfg.selected_symbols || []);
    document.querySelectorAll(".quant-symbol").forEach((el) => {
      el.checked = selected.has(el.value);
    });
    toggleManualSymbols();
    managedBrokers = new Set(cfg.managed_brokers || []);   // Qurious: 서버가 대신 관리하는 증권사 없음(ADR-0004 · 서버도 [] 를 준다)
    lastKisManaged = cfg.kis_managed || null;
    renderManagedBroker();
    document.getElementById("broker-status").textContent = cfg.kis_managed
      ? (cfg.connected ? `✅ 연결됨 (KIS · 서버 관리 자격증명)` : "⚠️ KIS 자격증명 미연동 – Mockup 모드")
      : (cfg.connected ? `✅ 연결됨 (${cfg.broker})` : "⚠️ API 키 미설정 – Mockup 모드");
    lastLiveGateway = cfg.live_gateway || null;
    renderLiveRoute();
    await loadStrategies(cfg.strategy_id || "", cfg.strategy_version || 0);
    loadLiveOrders();
    loadCycleStatus();
  } catch {}
}

// ── 서버 관리 증권사(KIS): 키 입력칸 숨기고 연동 여부만 표시 ──────────────
let managedBrokers = new Set();   // Qurious: KIS 키는 사용자마다(ADR-0004) — 키 입력칸을 숨기지 않는다
let lastKisManaged = null;
function renderManagedBroker() {
  const broker = document.getElementById("broker-type")?.value || "mock";
  const wrap = document.getElementById("broker-credentials-wrap");
  const box = document.getElementById("broker-managed");
  if (!wrap || !box) return;
  const managed = managedBrokers.has(broker);
  wrap.classList.toggle("hidden", managed);
  box.classList.toggle("hidden", !managed);
  if (!managed) return;
  const st = lastKisManaged;
  if (!st) {
    box.innerHTML = `<b>🔐 자격증명 서버 관리</b> · App Key / Secret / 계좌번호는 입력하지 않습니다. 저장 후 연동 여부가 표시됩니다.`;
    return;
  }
  const badge = st.configured ? `<span class="badge-buy">연동됨</span>` : `<span class="badge-sell">미연동</span>`;
  const src = st.source === "secrets-manager" ? `AWS Secrets Manager${st.secret_name ? " · " + escHtml(st.secret_name) : ""}`
            : st.source === "env" ? "서버 환경변수" : "소스 미설정";
  const env = st.environment === "real" ? "실전" : "모의(Testbed)";
  box.innerHTML = `<b>🔐 KIS 자격증명 · 서버 관리</b> ${badge}<br>` +
    `<span style="color:var(--text-mute);">소스: ${src} · 환경: ${env}` +
    (st.account_masked ? ` · 계좌 ${escHtml(st.account_masked)}` : (st.configured ? " · 계좌번호 없음" : "")) +
    (st.error ? `<br>오류: ${escHtml(st.error)}` : "") + `</span>`;
}
document.getElementById("broker-type")?.addEventListener("change", () => {
  renderManagedBroker();
  renderLiveRoute();
});
document.getElementById("quant-mode")?.addEventListener("change", renderLiveRoute);

// ── 실주문 경로 안내 (live 모드 주문이 어디로 나가는지) ─────────────────
function selectedExecutionMode() {
  return { mode: document.getElementById("quant-mode").value,
    broker: document.getElementById("broker-type").value, live_gateway: lastLiveGateway };
}
function renderLiveRoute() {
  const el = document.getElementById("quant-live-route");
  if (!el) return;
  renderExecutionMode(document.getElementById("quant-mode"), el, selectedExecutionMode());
}

// ── domain-rag-lab 백테스트 합격 전략 드롭다운 ───────────────────────────
async function loadStrategies(selectedId, selectedVersion) {
  const sel = document.getElementById("quant-strategy");
  const hint = document.getElementById("quant-strategy-hint");
  if (!sel) return;
  try {
    const data = await api("/api/quant/strategies");
    const list = data.strategies || [];
    sel.innerHTML = `<option value="">기본 규칙 (기술지표 시그널)</option>` + list.map((s) => {
      const br = s.backtest_result || {};
      const label = `${escHtml(s.name)} v${s.version} · 연 ${fmtPct(br.annualized_return_pct ?? 0)} · MDD ${fmtPct(br.max_drawdown_pct ?? 0)}`;
      return `<option value="${escHtml(s.strategy_id)}" data-version="${s.version}">${label}</option>`;
    }).join("");
    if (selectedId && [...sel.options].some((o) => o.value === selectedId)) sel.value = selectedId;
    else if (selectedId) {
      sel.insertAdjacentHTML("beforeend", `<option value="${escHtml(selectedId)}" data-version="${selectedVersion}">${escHtml(selectedId)} v${selectedVersion} (목록에 없음)</option>`);
      sel.value = selectedId;
    }
    // Qurious: 서버 설정 이름 대신 사용자 말로(화면 결정 ③ C)
    if (hint) hint.textContent = data.configured
      ? (list.length ? `검증을 통과한 전략 ${list.length}개` : "검증을 통과한 전략이 아직 없어 기본 규칙으로 돕니다")
      : "검증을 통과한 전략이 아직 연결되지 않아 기본 규칙으로 돕니다";
  } catch (e) {
    if (hint) hint.textContent = "전략 목록을 불러오지 못했습니다";
  }
}

// ── 자동매매 사이클 상태: 마지막 실행·다음 예정·마지막 결과 ────────────────
async function loadCycleStatus() {
  const el = document.getElementById("quant-cycle-status");
  if (!el) return;
  try {
    const st = await api("/api/auto-trade/status");
    const intervalMin = Math.round((st.interval_sec || 600) / 60);
    const last = st.last_cycle_at ? new Date(st.last_cycle_at.replace(" ", "T") + "Z") : null;   // 서버 로그 시각은 UTC
    const fmtK = (d) => d.toLocaleString("ko-KR", { timeZone: "Asia/Seoul", hour12: false, month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
    const next = last && st.running ? new Date(last.getTime() + intervalMin * 60000) : null;
    const lastLog = (st.log || []).slice(-1)[0] || {};
    const trades = (lastLog.trades || []).filter((t) => t.type === "auto");
    const skipped = (lastLog.risk?.skipped || []).length;
    const strat = lastLog.settings?.strategy;
    const stratText = strat?.applied ? `전략 ${escHtml(strat.id)} v${strat.version}` : "기본 규칙";
    el.innerHTML = `<b>⏱ 자동매매 주기</b> · ${st.running ? "실행 중 (" + intervalMin + "분마다)" : "중지"}<br>` +
      `마지막 실행: ${last ? fmtK(last) : "없음"} · 다음 예정: ${next ? fmtK(next) + " 이전" : "-"}<br>` +
      `마지막 결과: 체결 ${trades.length}건 · 위험관리 생략 ${skipped}건 · ${stratText}` +
      (lastLog.risk?.halted ? ` · <span class="badge-sell">비상 정지: ${escHtml(lastLog.risk.reason || "")}</span>` : "") +
      (lastLog.risk?.live ? ` · 실계좌 당일 ${fmtPct(lastLog.risk.live.day_pnl_pct ?? 0)}` : "");
  } catch (e) {
    el.textContent = "사이클 상태를 불러오지 못했습니다.";
  }
}

// ── KIS 실주문 현황 (live_orders) ────────────────────────────────────────
const LIVE_STATUS_BADGE = {
  FILLED: "badge-buy", PARTIALLY_FILLED: "badge-buy", ACCEPTED: "badge-hold", PENDING: "badge-hold",
  CANCEL_REQUESTED: "badge-hold", CANCELLED: "badge-sell", REJECTED: "badge-sell", ERROR: "badge-sell", UNKNOWN: "badge-sell",
};
async function loadLiveOrders() {
  const el = document.getElementById("quant-live-orders");
  if (!el) return;
  try {
    const data = await api("/api/quant/live-orders?limit=30");
    const rows = data.orders || [];
    if (!rows.length) {
      el.innerHTML = "앱에서 추적 중인 증권사 주문이 없습니다. 과거·외부 주문은 KIS 주문 내역에서 확인해 주세요.";
      return;
    }
    el.innerHTML = `<div class="overflow-x-auto"><table class="w-full text-xs">
      <thead><tr class="text-slate-400"><th class="text-left py-1">시각</th><th class="text-left">환경</th><th class="text-left">종목</th><th>구분</th><th class="text-right">수량</th><th class="text-right">가격</th><th>상태</th><th class="text-right">체결</th><th class="text-left">주문번호 / 메시지</th></tr></thead>
      <tbody>${rows.map((r) => `<tr style="border-top:1px solid var(--border);">
        <td class="py-1">${escHtml((r.created_at || "").slice(5, 16).replace("T", " "))}</td>
        <td>${r.environment === "real" ? "실전" : "모의"}</td>
        <td>${escHtml(r.name || r.symbol)}</td>
        <td class="text-center">${r.side === "BUY" ? "매수" : "매도"}</td>
        <td class="text-right">${fmt(r.quantity)}</td>
        <td class="text-right">${fmt(Math.round(r.price))}</td>
        <td class="text-center"><span class="${LIVE_STATUS_BADGE[r.status] || "badge-hold"}">${escHtml(r.status)}</span></td>
        <td class="text-right">${r.filled_quantity ? `${fmt(r.filled_quantity)} @ ${fmt(Math.round(r.avg_filled_price))}` : "-"}</td>
        <td class="truncate max-w-[16rem]" title="${escHtml(r.message || "")}">${escHtml(r.order_no || "")}${r.message ? " · " + escHtml(r.message) : ""}</td>
      </tr>`).join("")}</tbody></table></div>`;
  } catch (e) {
    el.textContent = "실주문 현황을 불러오지 못했습니다.";
  }
}
document.getElementById("live-orders-refresh")?.addEventListener("click", loadLiveOrders);

function toggleManualSymbols() {
  const source = document.getElementById("quant-symbol-source")?.value || "ai";
  const wrap = document.getElementById("quant-manual-symbols-wrap");
  if (!wrap) return;
  if (source === "manual") wrap.classList.remove("hidden");
  else wrap.classList.add("hidden");
}
document.getElementById("quant-symbol-source")?.addEventListener("change", toggleManualSymbols);

document.getElementById("broker-save")?.addEventListener("click", async () => {
  const modeNow = document.getElementById("quant-mode").value;
  const view = executionModeView(selectedExecutionMode());
  if (modeNow === "live" && !view.available) {
    setToast(view.detail, "error");
    return;
  }
  if (modeNow === "live" && lastLoadedMode !== "live") {
    if (!confirm(`${view.label} 모드로 바꿉니다.\n${view.detail}\n\n계속할까요?`)) return;
  }
  try {
    const selectedSymbols = [...document.querySelectorAll(".quant-symbol:checked")].map((el) => el.value);
    const buyRatio = Math.max(10, Math.min(100, Number(document.getElementById("quant-buy-ratio").value || 100))) / 100;
    const sellRatio = Math.max(10, Math.min(100, Number(document.getElementById("quant-sell-ratio").value || 50))) / 100;
    await api("/api/quant/settings", {
      method: "POST",
      body: {
        mode:       document.getElementById("quant-mode").value,
        symbol_source: document.getElementById("quant-symbol-source").value,
        selected_symbols: selectedSymbols,
        ai_top_n: Number(document.getElementById("quant-ai-top-n").value || 3),
        per_trade_budget: Number(document.getElementById("quant-per-trade-budget").value || 1000000),
        buy_ratio:  buyRatio,
        sell_ratio: sellRatio,
        execution_policy: {
          size_kind: document.getElementById("quant-size-kind").value,
          risk_pct: Number(document.getElementById("quant-risk-pct").value),
          stop_loss_pct: Number(document.getElementById("quant-stop-pct").value),
          slippage_bps: Number(document.getElementById("quant-risk-slip").value),
          retry_enabled: document.getElementById("quant-retry-enabled").checked,
          retry_max_attempts: Number(document.getElementById("quant-retry-attempts").value),
          retry_window_min: Number(document.getElementById("quant-retry-window").value),
          retry_price_deviation_pct: Number(document.getElementById("quant-retry-deviation").value),
        },
        strategy_id: document.getElementById("quant-strategy")?.value || "",
        strategy_version: Number(document.getElementById("quant-strategy")?.selectedOptions?.[0]?.dataset?.version || 0),
        broker:     document.getElementById("broker-type").value,
        app_key:    managedBrokers.has(document.getElementById("broker-type").value) ? "" : document.getElementById("broker-app-key").value,
        app_secret: managedBrokers.has(document.getElementById("broker-type").value) ? "" : document.getElementById("broker-app-secret").value,
        account_no: managedBrokers.has(document.getElementById("broker-type").value) ? "" : document.getElementById("broker-account").value,
        paper:      document.getElementById("broker-paper").checked,
        risk_daily_loss_limit_pct: Number(document.getElementById("risk-daily-loss").value || 0),
        risk_max_position_pct:     Number(document.getElementById("risk-max-position").value || 0),
        risk_max_orders_per_day:   Number(document.getElementById("risk-max-orders").value || 0),
        risk_cooldown_min:         Number(document.getElementById("risk-cooldown").value || 0),
      },
    });
    setToast("증권사 API 설정이 저장되었습니다.", "ok");
    loadSettings();
  } catch (e) { setToast(e.message, "error"); }
});

document.getElementById("broker-test")?.addEventListener("click", async () => {
  const button = document.getElementById("broker-test");
  const el = document.getElementById("broker-status");
  if (button.disabled) return;
  button.disabled = true;
  el.textContent = "저장된 설정으로 현재가 조회 중...";
  try {
    const data = await api("/api/broker/price?symbol=005930.KS");
    if (data.source !== "broker") {
      el.textContent = "증권사 연결을 확인한 결과가 아닙니다. 증권사를 선택하고 API 키를 저장한 뒤 다시 테스트해 주세요.";
      setToast("증권사 연결 미확인", "error");
    } else {
      el.textContent = `✅ 현재가 조회 성공 – 삼성전자 현재가: ${fmt(data.current)}원. 계좌 잔고와 주문 가능 여부는 확인하지 않았습니다.`;
      setToast("현재가 조회 성공", "ok");
    }
  } catch (e) {
    const detail = e.detail;
    const message = detail?.scope === "quote" ? `${detail.message} ${detail.hint}`
      : e.status === 401 ? "로그인이 필요합니다. 다시 로그인해 주세요."
      : "현재가 조회를 완료하지 못했습니다. 잠시 뒤 다시 눌러 주세요.";
    el.textContent = `현재가 조회 미확인: ${message} 이 결과만으로 계좌 연결이 끊겼다고 판단할 수 없습니다.`;
    setToast(message, "error");
  } finally {
    button.disabled = false;
  }
});

// ── 알림 설정 ──────────────────────────────────────────────────────
function toggleNotiSections() {
  const chMap = { telegram: "noti-section-telegram", slack: "noti-section-slack",
                  email: "noti-section-email", kakao: "noti-section-kakao", sms: "noti-section-sms" };
  document.querySelectorAll(".noti-channel").forEach(cb => {
    const sec = document.getElementById(chMap[cb.value]);
    if (sec) sec.classList.toggle("hidden", !cb.checked);
  });
}
document.querySelectorAll(".noti-channel").forEach(cb => cb.addEventListener("change", toggleNotiSections));

// ── 알림 연동 정보 수집·이용(선택) 동의 (2026-10-29 · ①-09) ───────────────────
// 동의하면 서버가 동의 행을 저장과 같은 트랜잭션으로 쌓는다. 동의가 없는데 토큰 · 웹훅 · 비밀번호 · 번호를 새로 넣으면 서버가 422 로 막는다.
let notiConsentGranted = false;

function renderNotiConsent(state) {
  notiConsentGranted = !!state?.granted;
  document.getElementById("noti-consent-granted")?.classList.toggle("hidden", !notiConsentGranted);
  document.getElementById("noti-consent-ask")?.classList.toggle("hidden", notiConsentGranted);
  const label = document.getElementById("noti-consent-label");
  if (label) label.textContent = NOTIFY_CONSENT.short;
  const body = document.getElementById("noti-consent-body");
  if (body && !body.dataset.drawn) {
    body.innerHTML = `<p>${escHtml(NOTIFY_CONSENT.lead)}</p>` + NOTIFY_CONSENT.clauses.map(c =>
      `<div><div class="font-semibold">${escHtml(c.h)}</div>${c.b.map(p => `<p>${escHtml(p)}</p>`).join("")}</div>`).join("");
    body.dataset.drawn = "1";
  }
  const text = document.getElementById("noti-consent-granted-text");
  if (text && notiConsentGranted) {
    const when = state.at ? new Date(state.at).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" }) : "";
    text.textContent = `✅ 알림 연동 정보 수집·이용에 동의함 (${when} · 동의문 ${state.version || ""})`;
  }
}

document.getElementById("noti-consent-withdraw")?.addEventListener("click", async () => {
  if (!confirm("동의를 철회하면 저장된 알림 연동 정보(토큰 · 웹훅 · 비밀번호 · 휴대전화번호 · 키)가 바로 삭제됩니다. 계속할까요?")) return;
  try {
    await api("/api/notification/settings", { method: "POST", body: { channels: [], integration_consent: false } });
    setToast("동의를 철회하고 저장된 알림 연동 정보를 삭제했습니다.", "ok");
    document.getElementById("noti-status").textContent = "✅ 동의 철회 · 연동 정보 삭제 완료";
    loadNotificationSettings();
  } catch (e) { setToast(e.message, "error"); }
});

async function loadNotificationSettings() {
  try {
    const cfg = await api("/api/notification/settings");
    renderNotiConsent(cfg.integration_consent);
    const channels = cfg.channels || [];
    document.querySelectorAll(".noti-channel").forEach(cb => { cb.checked = channels.includes(cb.value); });
    toggleNotiSections();
    // Telegram
    document.getElementById("noti-telegram-token").value    = cfg.telegram_token    || "";
    document.getElementById("noti-telegram-chat-id").value  = cfg.telegram_chat_id  || "";
    // Slack
    document.getElementById("noti-slack-webhook").value     = cfg.slack_webhook_url || "";
    // Email
    document.getElementById("noti-email-host").value        = cfg.email_host        || "";
    document.getElementById("noti-email-port").value        = cfg.email_port        || 587;
    document.getElementById("noti-email-user").value        = cfg.email_user        || "";
    document.getElementById("noti-email-password").value    = cfg.email_password    || "";
    document.getElementById("noti-email-from").value        = cfg.email_from        || "";
    document.getElementById("noti-email-to").value          = cfg.email_to          || "";
    // Kakao
    document.getElementById("noti-kakao-api-key").value     = cfg.kakao_api_key     || "";
    document.getElementById("noti-kakao-api-secret").value  = cfg.kakao_api_secret  || "";
    document.getElementById("noti-kakao-sender-key").value  = cfg.kakao_sender_key  || "";
    document.getElementById("noti-kakao-phone").value       = cfg.kakao_phone       || "";
    // SMS
    document.getElementById("noti-sms-api-key").value       = cfg.sms_api_key       || "";
    document.getElementById("noti-sms-api-secret").value    = cfg.sms_api_secret    || "";
    document.getElementById("noti-sms-from").value          = cfg.sms_from          || "";
    document.getElementById("noti-sms-to").value            = cfg.sms_to            || "";
  } catch {}
  loadNotificationHistory();
}

async function loadNotificationHistory() {
  const el = document.getElementById("noti-history");
  if (!el) return;
  try {
    const data = await api("/api/notification/history?limit=30");
    if (!data.events?.length) {
      el.innerHTML = "발송 이력이 없습니다.";
      return;
    }
    el.innerHTML = data.events.map(ev => {
      const chBadges = (ev.channels || []).map(c =>
        `<span class="badge-${c.ok ? "buy" : "sell"}" style="margin-right:4px;">${escHtml(c.channel)}</span>`
      ).join("") || "<span style='color:var(--text-mute);'>발송 채널 없음</span>";
      // 전달 결과는 서버(status_label)가 정한 글을 그대로 보인다 — 실패 · 결과 불명은 빨강으로
      const bad = ["failed", "sending"].includes(ev.delivery_status);
      const stBadge = ev.status_label
        ? `<span style="margin-left:6px;color:${bad ? "var(--red)" : "var(--text-mute)"};">${escHtml(ev.status_label)}</span>` : "";
      return `<div class="py-1.5" style="border-bottom:1px solid var(--border);">
        <div style="color:var(--text-mute);">${escHtml(ev.created_at || "")}${stBadge}</div>
        <div style="color:var(--text-dim);">${escHtml(ev.subject || ev.message || "")}</div>
        <div class="mt-0.5">${chBadges}</div>
      </div>`;
    }).join("");
  } catch (e) {
    el.innerHTML = `<span style="color:var(--red);">${escHtml(e.message)}</span>`;
  }
}

document.getElementById("noti-save")?.addEventListener("click", async () => {
  try {
    const channels = [...document.querySelectorAll(".noti-channel:checked")].map(cb => cb.value);
    // 아직 동의 전이고 체크했을 때만 동의를 보낸다(이미 동의했으면 상태를 바꾸지 않는다 — 철회는 따로 단추)
    const giveConsent = !notiConsentGranted && !!document.getElementById("noti-consent-check")?.checked;
    await api("/api/notification/settings", {
      method: "POST",
      body: {
        integration_consent: giveConsent ? true : null,
        integration_consent_version: giveConsent ? NOTIFY_CONSENT_VERSION : null,
        channels,
        telegram_token:    document.getElementById("noti-telegram-token").value,
        telegram_chat_id:  document.getElementById("noti-telegram-chat-id").value,
        slack_webhook_url: document.getElementById("noti-slack-webhook").value,
        email_to:          document.getElementById("noti-email-to").value,
        email_host:        document.getElementById("noti-email-host").value,
        email_port:        Number(document.getElementById("noti-email-port").value || 587),
        email_user:        document.getElementById("noti-email-user").value,
        email_password:    document.getElementById("noti-email-password").value,
        email_from:        document.getElementById("noti-email-from").value,
        kakao_api_key:     document.getElementById("noti-kakao-api-key").value,
        kakao_api_secret:  document.getElementById("noti-kakao-api-secret").value,
        kakao_sender_key:  document.getElementById("noti-kakao-sender-key").value,
        kakao_phone:       document.getElementById("noti-kakao-phone").value,
        sms_api_key:       document.getElementById("noti-sms-api-key").value,
        sms_api_secret:    document.getElementById("noti-sms-api-secret").value,
        sms_from:          document.getElementById("noti-sms-from").value,
        sms_to:            document.getElementById("noti-sms-to").value,
      },
    });
    setToast("알림 설정이 저장되었습니다.", "ok");
    document.getElementById("noti-status").textContent = "✅ 저장 완료";
    loadNotificationSettings();
  } catch (e) { setToast(e.message, "error"); }
});

document.getElementById("noti-test")?.addEventListener("click", async () => {
  const el = document.getElementById("noti-status");
  el.textContent = "테스트 알림 전송 중...";
  try {
    await api("/api/notification/test", { method: "POST" });
    el.textContent = "✅ 테스트 알림을 전송했습니다. 수신 여부를 확인하세요.";
    setToast("테스트 알림 전송 완료", "ok");
    loadNotificationHistory();
  } catch (e) {
    el.textContent = `❌ 전송 실패: ${e.message}`;
    setToast(e.message, "error");
  }
});


export { loadNotificationSettings, loadSettings };
