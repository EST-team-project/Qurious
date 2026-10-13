/* 재무 · 신용 위험 — 로보 어드바이저 화면(옛 「신용 리스크 분석」 자리 · 화면 키 agent-cb) (2026-10-13)
 *
 * 무엇을 그리나(서버가 숫자 · 문장 · 출처를 짓고 이 파일은 그대로 그린다 — 문장을 여기서 다시 짓지 않는다):
 *   GET /api/risk/company?symbol=  상장사 재무 건전성(우리 DART 주요계정 · API-RISK-01) — 숫자 넷 · 점검 일곱 · Altman Z'' ·
 *                                   해마다 영업이익 · 그림(분기 · 반기 · 사업보고서 비율) · 자료가 없는 둘은 까닭과 함께
 *   GET /api/risk/macro            시장 전체의 신용 스프레드(ECOS 시장금리 · API-RISK-02) — AA- · BBB- · CP − CD · 지난 10년 안 위치
 * 옛 칸은 조건을 글로 만들어 범용 대화 API 에 물었다(빈 CB 표 · 약 2분 — 점검표 「외부 의존」).
 *
 * 화면 꼴(Figma 「Qurious · 재무 · 신용 위험」 05 [결정] · 사용자 2026-10-13): 설계 D = B(탭 둘)와 C(점검 먼저 + 시장 신용 띠)의 융합.
 *   맨 위 시장 신용 한 줄 띠(늘 · 세 값 · 지난 10년 안 위치) → 탭 둘(회사 재무 건전성 · 시장 신용) → 회사 탭은 점검 먼저.
 *   띠의 「그림 · 읽는 법 →」 은 펼치지 않고 시장 신용 탭으로 옮겨 간다(띠 숫자만 보고 뜻을 잘못 읽지 않게).
 *   점검 낱말은 그렇다 · 아니다 · 자료 없음(통과 · 실패는 투자 판단처럼 읽힌다) · Altman Z'' 는 한계 문장과 함께 보인다.
 * 색 — 좋음 · 나쁨으로 읽히는 신호등 색을 쓰지 않는다(상품 안내와 같은 원칙). 구간 · 점검은 글자와 모양으로 가른다.
 * 차트: TradingView Lightweight Charts™ 5.2.1(public/js/vendor/lightweight-charts — 처음 그릴 때 한 번 불러온다 · 로고 · 출처 표시).
 * 강사님 파일(app.html · main.js · core.js · agent.js)에는 뿌리 칸 · 부르는 줄 · 메뉴 이름 · 옛 단추 가드만 둔다.
 *
 * 응답을 읽는 변수 이름은 객체마다 하나로 고정한다(시험 TC-FRS 가 「변수.칸」 을 모아 서버 응답 칸과 맞댄다 · S.co · S.mc 도 같다):
 *   co 재무 응답 · lb 최근 기준(co.latest) · sm 점검 요약 · m 비율 하나 · mh 비율 그림 점 하나 · ck 점검 하나 · zs Z'' 칸 ·
 *   zh Z'' 그림 점 하나 · op 영업이익 칸 · oy 영업이익 한 해 · un 자료 없음 하나 ·
 *   mc 거시 응답 · sp 스프레드 하나 · d 스프레드 그림 점 하나(하루)
 * 경계 · 기간 숫자(Z'' 1.10 · 2.60 · 10년)는 서버 응답에서만 읽는다 — 화면에 따로 적으면 서버를 고칠 때 한쪽만 바뀐다.
 */
import { api, escHtml, fmt } from "/js/common.js";

const VIEW = "agent-cb";
const LWC_SRC = "/js/vendor/lightweight-charts/lightweight-charts-5.2.1.min.js";
const LWC_TIMEOUT_MS = 15000;
const CREDIT_URL = "https://www.tradingview.com/";
const SYMBOL_KEY = "rc_symbol_v1";
//: 바로 고를 수 있는 예 — 일반 회사 · 금융회사(견줄 수 없음 까닭이 보이는 예)를 섞었다
const EXAMPLES = [["005930", "삼성전자"], ["000660", "SK하이닉스"], ["035720", "카카오"], ["105560", "KB금융"]];
const METRIC_KEYS = ["current_ratio", "debt_ratio", "equity_ratio"];
const COLORS = { ink: "#0f172a", gray: "#94a3b8", slate: "#475569", line2: "#64748b" };

const S = {
  symbol: "", name: "", tab: "company", metric: "current_ratio", spread: "aa",
  co: null, coErr: "", coBusy: false, mc: null, mcErr: "", mcBusy: false,
};
let lwcPromise = null;
let charts = [];

function root() { return document.querySelector(`.view[data-view="${VIEW}"] .rc-root`); }
function accentRc() { return getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#2563eb"; }

/** 차트 도구를 한 번만 불러온다 — 실패하면 그림 없이 숫자 · 글만 보인다(까닭을 함께) */
function loadChartsRc() {
  if (window.LightweightCharts) return Promise.resolve(window.LightweightCharts);
  if (lwcPromise) return lwcPromise;
  lwcPromise = new Promise((resolve, reject) => {
    const el = document.createElement("script");
    el.src = LWC_SRC;
    el.async = true;
    const timer = setTimeout(() => reject(new Error("timeout")), LWC_TIMEOUT_MS);
    el.onload = () => { clearTimeout(timer); window.LightweightCharts ? resolve(window.LightweightCharts) : reject(new Error("empty")); };
    el.onerror = () => { clearTimeout(timer); reject(new Error("load")); };
    document.head.appendChild(el);
  }).catch(e => { lwcPromise = null; throw e; });
  return lwcPromise;
}

// ── 숫자 꼴 ─────────────────────────────────────────────────────────────
const pct = v => (v == null ? "—" : `${fmt(v, 0)}%`);
const bp = v => (v == null ? "—" : `${fmt(v, 0)}bp`);
function won(v) {
  if (v == null) return "—";
  const a = Math.abs(v);
  if (a >= 1e12) return `${(v / 1e12).toFixed(1)}조원`;
  if (a >= 1e8) return `${Math.round(v / 1e8).toLocaleString("ko-KR")}억원`;
  return `${Math.round(v).toLocaleString("ko-KR")}원`;
}

// ── 불러오기 ─────────────────────────────────────────────────────────────
async function loadCompany(code) {
  S.symbol = code; S.co = null; S.coErr = ""; S.coBusy = true;
  try { sessionStorage.setItem(SYMBOL_KEY, code); } catch { /* 저장 못 해도 그리기는 그대로 */ }
  paint();
  try {
    const co = await api(`/api/risk/company?symbol=${encodeURIComponent(code)}`, { redirectOnUnauthorized: false });
    if (S.symbol !== code) return;                 // 그사이 다른 종목을 골랐다
    S.co = co;
    if (co.name) S.name = co.name;
    const m = pickMetric(co);
    if (S.metric !== "operating" && (!m || m.key !== S.metric || m.value == null)) {   // 고른 비율이 이 회사엔 없다(금융회사 등) — 빈 그림을 두지 않는다
      S.metric = (co.metrics || []).find(x => METRIC_KEYS.includes(x.key) && x.value != null)?.key || "operating";
    }
  } catch (e) {
    if (S.symbol !== code) return;
    S.coErr = (e && (e.detail?.message || e.message)) || "재무 자료를 불러오지 못했습니다";
  } finally {
    if (S.symbol === code) { S.coBusy = false; paint(); }
  }
}

async function loadMacro() {
  if (S.mc || S.mcBusy) return;
  S.mcBusy = true; S.mcErr = "";
  try { S.mc = await api("/api/risk/macro?years=3", { redirectOnUnauthorized: false }); }
  catch (e) { S.mcErr = (e && (e.detail?.message || e.message)) || "시장 신용 자료를 불러오지 못했습니다"; }
  finally { S.mcBusy = false; paint(); }
}

// ── 그리기 — 머리 · 종목 고르기 ──────────────────────────────────────────
function headHtml() {
  return `<header class="rc-head">
    <div class="rc-title"><h2>재무 · 신용 위험</h2>
      <p class="rc-sub">상장사의 재무 건전성(전자공시 재무제표)과 시장 전체의 신용 위험(한국은행 시장금리)을 숫자 · 그림 · 쉬운 말로 봅니다.</p></div>
    <div class="rc-pick">
      <label class="rc-pick-label" for="rc-q">회사</label>
      <div class="rc-pick-box"><input id="rc-q" class="rc-q input" autocomplete="off" placeholder="회사 이름이나 6자리 종목코드"
        aria-autocomplete="list" aria-controls="rc-suggest" /><ul id="rc-suggest" class="rc-suggest" role="listbox" hidden></ul></div>
      <div class="rc-examples" aria-label="예시 회사">${EXAMPLES.map(([c, n]) =>
        `<button type="button" class="rc-chip" data-code="${c}" data-name="${escHtml(n)}" aria-pressed="${S.symbol === c}">${escHtml(n)}</button>`).join("")}</div>
    </div></header>`;
}

function tabsHtml() {
  return `<div class="rc-tabs" role="tablist" aria-label="보기">
    <button type="button" role="tab" class="rc-tab" data-tab="company" aria-selected="${S.tab === "company"}">회사 재무 건전성</button>
    <button type="button" role="tab" class="rc-tab" data-tab="macro" aria-selected="${S.tab === "macro"}">시장 신용</button></div>`;
}

// ── 회사 ─────────────────────────────────────────────────────────────────
function bandHtml(co) {
  const lb = co.latest || {};
  const notes = [co.fs_note, co.kind_note].filter(Boolean);
  return `<div class="rc-band">
    <div class="rc-band-name"><strong>${escHtml(co.name || S.name || co.symbol)}</strong>
      <span class="q-muted">${escHtml(co.symbol)}${co.exchange ? ` · ${escHtml(co.exchange)}` : ""}</span></div>
    <div class="rc-band-basis">기준 ${escHtml(lb.report || "")} ${escHtml(lb.period_end || "")}
      ${lb.restated ? `<span class="rc-tag" title="정정 공시로 값이 바뀐 기간">정정됨</span>` : ""}
      ${lb.url ? ` · <a href="${escHtml(lb.url)}" target="_blank" rel="noopener noreferrer">공시 원문</a>` : ""}</div>
    ${notes.length ? `<p class="rc-band-note">${notes.map(escHtml).join(" · ")}</p>` : ""}</div>`;
}

function summaryHtml(co) {
  const sm = co.summary || {};
  return `<div class="rc-summary" aria-label="점검 요약"><span class="q-muted">점검 ${sm.total ?? 0}개 —</span>
    <span>${MARK.pass[1]}</span><span class="rc-sum-n">${sm.pass ?? 0}</span>
    <span>${MARK.fail[1]}</span><span class="rc-sum-n">${sm.fail ?? 0}</span>
    <span>${MARK.unknown[1]}</span><span class="rc-sum-n">${sm.unknown ?? 0}</span></div>`;
}

function tilesHtml(co) {
  return `<div class="rc-tiles">${(co.metrics || []).map(m => {
    const chartable = METRIC_KEYS.includes(m.key) && m.value != null;
    return `<button type="button" class="rc-tile${S.metric === m.key ? " is-on" : ""}" data-metric="${m.key}" ${chartable ? "" : "disabled"}
      aria-pressed="${S.metric === m.key}">
      <span class="rc-tile-label">${escHtml(m.label)}</span>
      <span class="rc-tile-value">${m.value == null ? "—" : pct(m.value)}</span>
      <span class="rc-tile-say">${escHtml(m.value == null ? (m.reason || "") : (m.sentence || ""))}</span></button>`;
  }).join("")}</div>`;
}

//: 점검 낱말 — 질문에 대한 사실 답처럼(사용자 결정 2026-10-13 · 「통과 · 실패」 는 투자 판단 · 등급처럼 읽힌다)
const MARK = { pass: ["✔", "그렇다"], fail: ["✕", "아니다"], unknown: ["?", "자료 없음"] };
function checksHtml(co) {
  return `<ol class="rc-checks">${(co.checks || []).map(ck => {
    const [icon, word] = MARK[ck.status] || MARK.unknown;
    return `<li class="rc-check is-${ck.status}"><span class="rc-check-icon" aria-hidden="true">${icon}</span>
      <span class="rc-check-body"><span class="rc-check-label">${escHtml(ck.label)}</span>
      <span class="rc-check-why">${escHtml(word)} · ${escHtml(ck.reason)}</span></span></li>`;
  }).join("")}</ol>`;
}

function zHtml(co) {
  const zs = co.zscore || {};
  if (zs.value == null) {
    return `<section class="rc-card rc-z"><h3>Altman Z'' 점수</h3><p class="rc-say">${escHtml(zs.reason || "셀 수 없습니다")}</p></section>`;
  }
  const lo = zs.thresholds.low, hi = zs.thresholds.high;      // 서버 한 곳(company_health.Z_LOW · Z_HIGH) — 값이 있으면 늘 함께 온다
  const top = Math.max(hi + 2, Math.ceil(zs.value) + 1);
  const at = v => `${Math.max(0, Math.min(100, (v / top) * 100))}%`;
  return `<section class="rc-card rc-z"><h3>Altman Z'' 점수 <span class="q-muted">${escHtml(zs.basis?.bsns_year || "")}년 사업보고서</span></h3>
    <div class="rc-z-row"><span class="rc-z-value">${zs.value.toFixed(2)}</span><span class="rc-z-zone">${escHtml(zs.zone_label || "")}</span></div>
    <div class="rc-gauge" role="img" aria-label="Z'' ${zs.value.toFixed(2)} — ${escHtml(zs.zone_label || "")}">
      <span class="rc-g-seg is-low" style="width:${at(lo)}">낮은</span>
      <span class="rc-g-seg is-mid" style="width:calc(${at(hi)} - ${at(lo)})">가운데</span>
      <span class="rc-g-seg is-high" style="flex:1">높은</span>
      <span class="rc-g-mark" style="left:${at(zs.value)}"></span></div>
    <div class="rc-g-scale"><span style="left:${at(lo)}">${lo.toFixed(2)}</span><span style="left:${at(hi)}">${hi.toFixed(2)}</span></div>
    <div class="rc-chart rc-chart-z" data-chart="z" aria-label="해마다 Altman Z'' 점수"></div>
    <p class="rc-say">${escHtml(zs.sentence || "")}</p>
    <ul class="rc-points">${(zs.points || []).map(p => `<li>${escHtml(p)}</li>`).join("")}</ul></section>`;
}

function chartCardHtml(co) {
  const m = pickMetric(co) || {};
  const opOn = S.metric === "operating";
  const chips = [...METRIC_KEYS.map(k => (co.metrics || []).find(x => x.key === k)).filter(Boolean)
    .map(m => [m.key, m.label, m.value != null]), ["operating", "영업이익", (co.operating?.history || []).length > 0]];
  const say = opOn ? opSay(co) : (m.value == null ? (m.reason || "") : (m.sentence || ""));
  const points = opOn ? [] : (m.points || []);
  return `<section class="rc-card rc-chart-card"><h3>흐름</h3>
    <div class="rc-chips" role="group" aria-label="그림 고르기">${chips.map(([k, label, ok]) =>
      `<button type="button" class="rc-chip" data-metric="${k}" aria-pressed="${S.metric === k}" ${ok ? "" : "disabled"}>${escHtml(label)}</button>`).join("")}</div>
    <div class="rc-chart" data-chart="${opOn ? "op" : "metric"}" aria-label="${escHtml(opOn ? "해마다 영업이익" : (m.label || ""))} 그림"></div>
    <p class="rc-cap q-muted">${opOn ? "사업보고서 해마다 · 단위 원" : `분기 · 반기 · 사업보고서마다 · ${escHtml(m.formula || "")}`}</p>
    <p class="rc-say">${escHtml(say)}</p>
    <ul class="rc-points">${points.map(p => `<li>${escHtml(p)}</li>`).join("")}</ul></section>`;
}

function opSay(co) {
  const op = co.operating || {};
  const oy = (op.history || []).at(-1);
  if (!oy) return "사업보고서의 영업이익이 없습니다.";
  const streak = op.loss_streak ? ` · ${op.loss_streak}년 이어 영업손실` : "";
  return `${oy.bsns_year}년 영업이익 ${won(oy.operating_income)}${streak}.`;
}

function unavailHtml(co) {
  const list = co.unavailable || [];
  if (!list.length) return "";
  return `<section class="rc-card rc-unavail"><h3>아직 셀 수 없는 것</h3><ul>${list.map(un =>
    `<li><strong>${escHtml(un.label)}</strong> — ${escHtml(un.reason)}</li>`).join("")}</ul></section>`;
}

function companyHtml() {
  if (S.coBusy) return `<section class="rc-company"><p class="rc-wait q-muted">재무를 불러오는 중…</p></section>`;
  if (S.coErr) return `<section class="rc-company"><p class="rc-error">${escHtml(S.coErr)}</p></section>`;
  const co = S.co;
  if (!co) return `<section class="rc-company"><p class="q-muted">회사를 고르면 재무 건전성이 보입니다.</p></section>`;
  // 두 단의 길이를 맞춘다 — 왼쪽은 숫자 넷 · 점검, 오른쪽은 흐름 그림 · Z'' · 아직 셀 수 없는 것(2026-10-13 화면 확인)
  const left = `${tilesHtml(co)}<section class="rc-card rc-checks-card"><h3>점검</h3>${checksHtml(co)}</section>`;
  const right = `${chartCardHtml(co)}${zHtml(co)}${unavailHtml(co)}`;
  return `<section class="rc-company">${bandHtml(co)}${summaryHtml(co)}
    <div class="rc-grid"><div class="rc-col rc-col-l">${left}</div><div class="rc-col rc-col-r">${right}</div></div></section>`;
}

// ── 시장 신용 ────────────────────────────────────────────────────────────
function macroHtml() {
  if (S.mcBusy && !S.mc) return `<section class="rc-macro"><p class="rc-wait q-muted">시장금리를 불러오는 중…</p></section>`;
  if (S.mcErr) return `<section class="rc-macro"><p class="rc-error">${escHtml(S.mcErr)}</p></section>`;
  const mc = S.mc;
  if (!mc) return "";
  if (!mc.available) {
    return `<section class="rc-macro"><h3>시장 신용</h3><p class="rc-say">${escHtml(mc.reason || "")}</p>
      ${mc.admin_hint ? `<p class="rc-admin q-muted">${escHtml(mc.admin_hint)}</p>` : ""}</section>`;
  }
  const sp = pickSpread(mc);
  return `<section class="rc-macro">
    <div class="rc-macro-body"><h3>시장 신용 <span class="q-muted">마지막 날 ${escHtml(mc.as_of || "")} · 출처 ${escHtml(mc.source || "")}</span></h3>
    <div class="rc-sp-tiles">${(mc.spreads || []).map(x => spTileHtml(x, x.key === sp?.key)).join("")}</div>
    <div class="rc-chart" data-chart="spread" aria-label="${escHtml(sp?.label || "")} 그림"></div>
    <p class="rc-cap q-muted">${mc.years}년 하루값${sp?.stats ? ` · 점선 = 지난 ${sp.stats.years}년 가운데 값(${bp(sp.stats.median)})` : ""} · 단위 bp(0.01%p)</p>
    <p class="rc-say">${escHtml(sp?.sentence || "")}</p>
    <ul class="rc-points">${(sp?.points || []).map(p => `<li>${escHtml(p)}</li>`).join("")}</ul>
    <p class="rc-note q-muted">${escHtml(mc.notice || "")}</p></div></section>`;
}

function spTileHtml(sp, on) {
  return `<button type="button" class="rc-tile${on ? " is-on" : ""}" data-spread="${sp.key}" aria-pressed="${on}">
    <span class="rc-tile-label">${escHtml(sp.label)}</span>
    <span class="rc-tile-value">${sp.latest ? bp(sp.latest.bp) : "—"}</span>
    <span class="rc-tile-say">${sp.stats ? `지난 ${sp.stats.years}년 하루값 가운데 아래에서 ${fmt(sp.stats.pct_rank, 0)}%` : ""}</span></button>`;
}

/** 시장 신용 한 줄 띠 — 세 값 · 지난 몇 해 안 위치(늘 보인다) · 「그림 · 읽는 법 →」 은 시장 신용 탭으로 */
function stripHtml() {
  const mc = S.mc;
  if (!mc || !mc.available) return "";
  const more = `<button type="button" class="rc-strip-more" data-goto="macro">그림 · 읽는 법 →</button>`;
  return `<div class="rc-strip" aria-label="시장 신용 한 줄"><strong>시장 신용</strong>${(mc.spreads || []).map(sp =>
    sp.latest ? `<span>${escHtml(sp.label)} <b>${bp(sp.latest.bp)}</b>${sp.stats ? ` <span class="q-muted">${sp.stats.years}년 중 아래에서 ${fmt(sp.stats.pct_rank, 0)}%</span>` : ""}</span>` : "").join("")}
    ${more}</div>`;
}

/** 고른 비율 · 스프레드 — 고른 것이 없으면 첫째(그림 · 문장이 빈칸으로 남지 않게 · 바꾼 것은 화면 칩이 보인다) */
function pickMetric(co) { const list = co?.metrics || []; return list.find(x => x.key === S.metric) || list[0]; }
function pickSpread(mc) { const list = mc?.spreads || []; return list.find(x => x.key === S.spread) || list[0]; }

function footHtml() {
  // 각주는 보이는 탭에 맞춘다 — 시장 신용 탭은 고지가 칸 안에 이미 있어 재무 문구(「지난 재무제표로 계산」)를 붙이지 않는다(2026-10-13 화면 확인)
  const notice = S.tab === "company" ? (S.co?.notice || "투자 권유가 아닙니다.") : "투자 권유가 아닙니다.";
  return `<footer class="rc-foot"><p>${escHtml(notice)}</p>
    <p class="rc-credit">차트: TradingView Lightweight Charts™ · <a href="${CREDIT_URL}" target="_blank" rel="noopener noreferrer">tradingview.com</a></p></footer>`;
}

// ── 한 번에 그리기 ────────────────────────────────────────────────────────
/** 머리(회사 고르기)는 처음 한 번만 그린다 — 본문을 다시 그려도 입력 칸 · 찾기 목록이 지워지지 않게
 *  (2026-10-13 화면 확인: 재무를 불러오는 사이 전체를 다시 그려 열려 있던 찾기 목록이 사라졌다) */
function mountOnce(el) {
  if (el.querySelector(".rc-body")) return;
  el.innerHTML = headHtml() + `<div class="rc-body"></div>`;
  el.querySelectorAll(".rc-examples .rc-chip").forEach(b => b.addEventListener("click", () => { S.name = b.dataset.name; loadCompany(b.dataset.code); }));
  const input = el.querySelector(".rc-q");
  input?.addEventListener("input", () => suggestRc(input));
  input?.addEventListener("keydown", e => {
    if (e.key === "Enter" && /^\d{6}$/.test(input.value.trim())) { S.name = ""; el.querySelector(".rc-suggest").hidden = true; loadCompany(input.value.trim()); }
  });
}

function paint() {
  const el = root();
  if (!el) return;
  mountOnce(el);
  el.className = `rc-root is-tab-${S.tab}`;
  el.querySelectorAll(".rc-examples .rc-chip").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.code === S.symbol)));
  const body = el.querySelector(".rc-body");
  body.innerHTML = stripHtml() + tabsHtml() + companyHtml() + macroHtml() + footHtml();
  bind(body);
  requestAnimationFrame(() => drawCharts(el));     // 칸 크기가 정해진 뒤에 그린다(S109 — 크기 0 칸에서 그리면 기간이 틀어진다)
}

function bind(el) {
  el.querySelectorAll("[data-metric]").forEach(b => b.addEventListener("click", () => { if (b.disabled) return; S.metric = b.dataset.metric; paint(); }));
  el.querySelectorAll("[data-spread]").forEach(b => b.addEventListener("click", () => { S.spread = b.dataset.spread; paint(); }));
  el.querySelectorAll(".rc-tab").forEach(b => b.addEventListener("click", () => { S.tab = b.dataset.tab; paint(); }));
  el.querySelector(".rc-strip-more")?.addEventListener("click", () => { S.tab = "macro"; paint(); });
}

/** 종목 찾기 — 이름 · 코드로 국내 종목(6자리)만(투자 정보 리서치 화면과 같은 길) */
async function suggestRc(input) {
  const list = root()?.querySelector(".rc-suggest");
  const q = input.value.trim();
  if (!list) return;
  if (!q || /^\d{6}$/.test(q)) { list.hidden = true; return; }
  let rows = [];
  try {
    const r = await api(`/api/stocks/search?q=${encodeURIComponent(q)}`, { redirectOnUnauthorized: false });
    rows = (r.results || []).map(x => ({ code: String(x.symbol || "").replace(/\.(KS|KQ)$/i, ""), name: x.name || "" }))
      .filter(x => /^\d{6}$/.test(x.code)).slice(0, 8);
  } catch { rows = null; }
  if (input.value.trim() !== q) return;
  list.innerHTML = rows === null ? `<li class="q-muted">찾기가 지금 되지 않습니다 — 6자리 종목코드를 넣고 Enter</li>`
    : rows.length ? rows.map(x => `<li role="option" tabindex="-1" data-code="${escHtml(x.code)}" data-name="${escHtml(x.name)}"><strong>${escHtml(x.name)}</strong> <span class="q-muted">${escHtml(x.code)}</span></li>`).join("")
      : `<li class="q-muted">국내 상장 종목에서 찾지 못했습니다</li>`;
  list.hidden = false;
  list.querySelectorAll("li[data-code]").forEach(li => li.addEventListener("click", () => { S.name = li.dataset.name; list.hidden = true; input.value = ""; loadCompany(li.dataset.code); }));
}

// ── 그림 ──────────────────────────────────────────────────────────────────
function newChartRc(L, el) {
  return L.createChart(el, {
    autoSize: true,
    layout: { background: { color: "#ffffff" }, textColor: "#334155", fontSize: 11, attributionLogo: true,
      fontFamily: getComputedStyle(document.body).fontFamily },
    grid: { vertLines: { color: "#f1f5f9" }, horzLines: { color: "#eef1f6" } },
    rightPriceScale: { borderColor: "#dde2ec", scaleMargins: { top: 0.1, bottom: 0.18 } },
    timeScale: { borderColor: "#dde2ec", fixLeftEdge: true, fixRightEdge: true, lockVisibleTimeRangeOnResize: true },
    crosshair: { mode: 0 },
    localization: { locale: "ko-KR", dateFormat: "yyyy-MM-dd" },
    handleScroll: false, handleScale: false,
  });
}

async function drawCharts(el) {
  charts.forEach(c => { try { c.remove(); } catch { /* 이미 지움 */ } });
  charts = [];
  const slots = [...el.querySelectorAll(".rc-chart")].filter(x => x.getBoundingClientRect().width > 0);
  if (!slots.length) return;
  let L;
  try { L = await loadChartsRc(); } catch {
    slots.forEach(x => { x.innerHTML = `<p class="q-muted rc-nochart">그림 도구를 불러오지 못해 숫자 · 글만 보입니다.</p>`; });
    return;
  }
  for (const slot of slots) {
    const kind = slot.dataset.chart;
    const c = newChartRc(L, slot);
    if (kind === "metric") {
      const m = pickMetric(S.co);
      const s = c.addSeries(L.LineSeries, { color: accentRc(), lineWidth: 2, priceLineVisible: false,
        priceFormat: { type: "custom", formatter: v => `${Math.round(v)}%`, minMove: 0.1 } });
      s.setData((m?.history || []).map(mh => ({ time: mh.period_end, value: mh.value })));
      // 유동비율 100% — 유동자산 = 유동부채인 자리(정의에서 나오는 선 · 판단 기준이 아니다)
      if (S.metric === "current_ratio") s.createPriceLine({ price: 100, color: COLORS.gray, lineStyle: 2, lineWidth: 1, axisLabelVisible: true, title: "100%" });
    } else if (kind === "op") {
      const s = c.addSeries(L.HistogramSeries, { color: COLORS.slate, priceLineVisible: false,
        priceFormat: { type: "custom", formatter: v => won(v), minMove: 1 } });
      s.setData((S.co?.operating?.history || []).filter(oy => oy.operating_income != null)
        .map(oy => ({ time: oy.period_end, value: oy.operating_income, color: oy.operating_income < 0 ? COLORS.gray : COLORS.slate })));
    } else if (kind === "z") {
      const zs = S.co?.zscore || {};
      const s = c.addSeries(L.HistogramSeries, { color: COLORS.slate, priceLineVisible: false,
        priceFormat: { type: "custom", formatter: v => v.toFixed(2), minMove: 0.01 } });
      s.setData((zs.history || []).map(zh => ({ time: zh.period_end, value: zh.value })));
      for (const v of [zs.thresholds?.low, zs.thresholds?.high]) {
        // 경계 이름은 축이 아니라 선 위에만 — 축 이름표가 0 · 4 · 마지막 값과 겹쳤다(2026-10-13 화면 확인)
        if (v != null) s.createPriceLine({ price: v, color: COLORS.gray, lineStyle: 2, lineWidth: 1, axisLabelVisible: false, title: v.toFixed(2) });
      }
    } else if (kind === "spread") {
      const sp = pickSpread(S.mc);
      const s = c.addSeries(L.LineSeries, { color: accentRc(), lineWidth: 2, priceLineVisible: false,
        priceFormat: { type: "custom", formatter: v => `${Math.round(v)}bp`, minMove: 0.1 } });
      s.setData((sp?.history || []).map(d => ({ time: d.date, value: d.bp })));
      if (sp?.stats) s.createPriceLine({ price: sp.stats.median, color: COLORS.gray, lineStyle: 2, lineWidth: 1, axisLabelVisible: true, title: `${sp.stats.years}년 가운데` });
    }
    c.timeScale().fitContent();
    charts.push(c);
  }
}

// ── 화면 진입 ─────────────────────────────────────────────────────────────
export function onRiskViewActivated(view) {
  if (view !== "agent-cb") return;   // 글자 그대로 — 화면 스캐너(scripts/view_scan.py)가 이 모양으로 진입 훅을 읽는다
  if (!root()) return;
  if (!S.symbol) {
    let saved = "";
    try { saved = sessionStorage.getItem(SYMBOL_KEY) || ""; } catch { saved = ""; }
    const ex = EXAMPLES.find(([c]) => c === saved);
    S.name = ex ? ex[1] : (saved ? "" : EXAMPLES[0][1]);
    loadCompany(saved || EXAMPLES[0][0]);
  } else {
    paint();
  }
  loadMacro();
}

