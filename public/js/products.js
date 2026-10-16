/* 투자 성향별 상품 안내 — 로보 어드바이저 화면(옛 「맞춤 상품 추천」 자리 · 화면 키 agent-products) (2026-10-12)
 *
 * 화면 설계 결정(Figma 「Qurious · 투자 성향별 상품 안내」 03 · 05 [결정] 안 A · 사용자 결정 2026-10-12):
 *   자산군 탭(내 자산 배분 비중 큰 순) + 맨 끝 「레버리지 · 인버스」 탭. 탭 안은 거래소 유형 순서의 묶음
 *   (시장 대표 → 업종 · 테마 → 전략 · 스타일 …)이고, 묶음마다 순자산 큰 순 몇 줄 + 「n개 모두 보기」(정렬 · 더 보기).
 *   - 숨기지 않는다 — 탭 숫자를 모두 더하면 그날 상장 ETF 전부(서버 불변식 · 시험 TC-PG). 레버리지 · 인버스 · 거래 정지 ·
 *     분류 못 함도 목록에 남고 표시만 붙는다(사용자 「위험하거나 목록이 길어진다고 보여 주지 않는 것은 옳지 않다」).
 *   - 「추천」 이 아니다 — 공시된 상품 정보를 같은 기준으로 늘어놓은 것이고, 순서 기준을 글로 보인다. 수익률에 오름 · 내림
 *     색을 칠하지 않는다(좋고 나쁨으로 읽히지 않게).
 *   - 위험은 숫자만 + 「공식 등급 아님」 — 1년 변동성 · 1년 최대 낙폭(우리 자료로 잼). 공식 투자위험등급 6색을 흉내 내지 않는다.
 *   - 레버리지 · 인버스 탭 머리에는 닫을 수 없는 주의 상자와 「실제로 사려면」 칸 — 숫자 · 기준일 · 출처는 서버 요건
 *     상수표(app/services/etp_requirements.py) 그대로 그린다(여기에 숫자를 따로 적지 않는다).
 *   - 현금성 탭에는 원화 단기 금리 ETF 와 함께 예금 · 적금 · 연금저축(금융감독원 「금융상품 한눈에」 실시간 · 저장하지 않음 ·
 *     출처 문구 그대로 · 약관 제9조). 그 탭을 처음 열 때 한 번 부르고, 조건을 바꿀 때만 다시 부른다(하루 호출 한도).
 * 투자 성향 · 자산 배분 비중은 읽기만 한다(오준영 님 몫 — 「자산배분·최적화」 화면).
 *   - 성향: 그 화면이 이 브라우저에 남긴 진단 결과(localStorage robo_risk_profile)를 읽는다.
 *   - 비중: 같은 표를 여기 복제하지 않는다. 화면에 들어올 때마다 저절로 부른다 — 저장본 먼저 · 404 일 때만 기본 비중 ·
 *     그 밖 오류는 까닭(#179 계약 · 2026-10-16). 판단은 js/productweights.js 한 곳에 두고 여기서는 그 결과만 그린다.
 *     받은 비중은 브라우저에 남기지 않는다(같은 탭에서 다른 사람이 로그인해도 앞사람 비중이 보이지 않게).
 * 강사님 파일(app.html · main.js · core.js · agent.js)에는 뿌리 칸 · 부르는 줄 · 메뉴 이름 · 옛 단추 가드만 두고 그리기는 모두 여기서.
 * ETF 이름을 누르면 상품 상세 창(js/productchart.js · API-PROD-04 · Figma 03-2 · 05 [결정] 안 B)이 열린다 — 차트 · 쉬운 말 근거는 그 파일에.
 *
 * 응답을 읽는 변수 이름은 객체마다 하나로 고정한다 — 시험(TC-PD)이 「변수.칸」 을 모아 서버 응답 칸과 맞댄다.
 *   ov 한눈에 응답 · ls 목록 응답 · it ETF 한 줄 · cls 자산군 · grp 묶음 · dv 레버리지 · 인버스 칸 · rq 요건 하나 ·
 *   sv 예금 · 적금 · 연금저축 응답 · p 그 상품 한 줄 · rt 그 기간 금리 줄 · al 기본 비중 응답 · sa 저장본 응답
 *   (al · sa 는 js/productweights.js 에서 읽는다 — 시험은 두 파일을 함께 모은다)
 */
import { api, escHtml, fmt } from "/js/common.js";
import { navigate } from "/js/core.js";
import { openProductChart } from "/js/productchart.js";
import { resolveWeights } from "/js/productweights.js";

const VIEW = "agent-products";
const PER_GROUP = 5;             // 묶음마다 먼저 보일 줄 수(Figma 안 A)
const PAGE = 50;                 // 「모두 보기」 한 번에 받을 줄 수
const DEFAULT_ORDER = ["국내주식", "해외주식", "국내채권", "대체자산", "현금", "그 밖"];
const DERIV_TAB = "derivatives";
//: 「모두 보기」 정렬 — 서버 SORT_KEYS 의 키 · 방향(이름은 화면 글)
const SORTS = [
  ["aum:desc", "순자산 큰 순"], ["trade_value:desc", "20일 거래대금 큰 순"], ["return_1y:desc", "1년 수익률 높은 순"],
  ["vol_1y:asc", "1년 변동성 낮은 순"], ["name:asc", "이름 순"],
];
const SAVING_KINDS = [["deposit", "정기예금"], ["saving", "적금"], ["annuity", "연금저축"]];
const SAVING_SECTORS = [["bank", "은행"], ["savings_bank", "저축은행"], ["insurance", "보험"], ["investment", "금융투자"],
  ["credit_card", "여신전문"]];
const SAVING_TERMS = [6, 12, 24, 36];
const MULTIPLE_TEXT = { 2: "+2배", "-1": "−1배", "-2": "−2배" };

let ov = null;                   // 마지막 한눈에 응답
let active = null;               // 고른 탭(자산군 키 · DERIV_TAB)
let seq = 0;                     // 늦게 온 응답이 새로 그린 화면을 덮지 않게
const expanded = new Map();      // 「모두 보기」 를 연 묶음 → { sort, items, total, loading, error }
let search = null;               // { q, ls, loading, error } — 이름 찾기
let savings = { kind: "deposit", sector: "bank", term: 12, sort: "base", sv: null, loading: false, error: "" };
let savingsSeq = 0;              // 조건을 연달아 바꿀 때 옛 응답이 새 조건의 화면을 덮지 않게
//: 연금저축은 보험 · 금융투자 업권에 있다(2026-10-12 실측 은행 0 · 보험 46 · 금융투자 297) — 다른 업권에서 바꾸면 보험으로
const ANNUITY_SECTORS = ["insurance", "investment"];
let weights = null;              // productweights.js resolveWeights 가 돌려준 것({ state: "ok" | "none" | "error", … }) | null
let weightsLoading = false;
let weightsSeq = 0;              // 화면에 다시 들어온 사이에 온 옛 응답이 새 결과를 덮지 않게
let tabPicked = false;           // 사용자가 탭을 고른 뒤에는 비중이 바뀌어도 고른 탭을 그대로 둔다

// ── 작은 도구 ──────────────────────────────────────────────────────────
/** 25.2조 · 4,213억 · 5,000만 — 순자산 · 거래대금 */
function won(v) {
  if (v == null) return "—";
  if (v >= 1e12) return `${(v / 1e12).toFixed(1)}조`;
  if (v >= 1e8) return `${fmt(Math.round(v / 1e8))}억`;
  return `${fmt(Math.round(v / 1e4))}만`;
}
/** +12.3% · −4.0% — 부호를 붙이고 색은 칠하지 않는다 */
function signed(v, digits = 1) {
  if (v == null) return "—";
  const s = Math.abs(v).toFixed(digits);
  return v > 0 ? `+${s}%` : v < 0 ? `−${s}%` : `${s}%`;
}
function plain(v, digits = 1) { return v == null ? "—" : `${v.toFixed(digits)}%`; }
function rate(v) { return v == null ? "—" : `${v.toFixed(2)}%`; }
function readProfile() {
  try { return JSON.parse(localStorage.getItem("robo_risk_profile") || "null"); } catch (_) { return null; }
}
/** 비중을 받았을 때만 자산군 → % (그 밖에는 null — 탭은 기본 차례) */
function loadedAllocations() { return weights?.state === "ok" ? weights.allocations : null; }
/** 자산 배분 화면의 성향 고르기 글(app.html #robo-risk) — 이름표를 여기 따로 적지 않는다. 없으면 빈 글 */
function riskLabel(key) {
  const opt = document.querySelector(`#robo-risk option[value="${CSS.escape(key || "")}"]`);
  return opt ? opt.textContent.trim() : "";
}
/** 저장 시각(ISO · 시간대 포함) → 「10월 15일 14:32」(KST) */
function savedWhen(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  // 이름 parts — 머리말 규칙의 p(상품 한 줄)와 겹치면 TC-PD-01 이 응답 칸으로 읽는다
  const parts = Object.fromEntries(new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", month: "numeric", day: "numeric",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(d).map(x => [x.type, x.value]));
  return `${parts.month}월 ${parts.day}일 ${parts.hour}:${parts.minute}`;
}
/** 개념 학습 장으로 가는 링크(새 탭 — 고른 탭 · 펼친 묶음을 잃지 않게). 장 이름(slug)은 시험(TC-PD-07)이 교재에 있는지 본다 */
function learnLink(slug, title) {
  return `<a class="pd-learn-link" href="/learn/#/p/${slug}" target="_blank" rel="noopener">「${escHtml(title)}」 →</a>`;
}
function classLabel(key) {
  const cls = (ov?.classes || []).find(c => c.key === key);
  return cls ? cls.label : key;
}
function root() { return document.querySelector(`.view[data-view="${VIEW}"] .pd-root`); }

/** 탭 차례 — 비중을 불러왔으면 비중 큰 순(같으면 기본 차례), 아니면 기본 차례. 「그 밖」 · 레버리지 · 인버스는 늘 끝 */
function tabOrder() {
  const keys = DEFAULT_ORDER.filter(k => k !== "그 밖");
  const wt = loadedAllocations();
  if (wt) keys.sort((a, b) => (wt[b] ?? -1) - (wt[a] ?? -1) || DEFAULT_ORDER.indexOf(a) - DEFAULT_ORDER.indexOf(b));
  return [...keys, "그 밖", DERIV_TAB];
}

// ── 그리기 ─────────────────────────────────────────────────────────────
function badges(it) {
  const out = [];
  if (it.multiple !== 1 && MULTIPLE_TEXT[it.multiple]) out.push(`<span class="pd-badge pd-badge--warn">${MULTIPLE_TEXT[it.multiple]}</span>`);
  if (it.single_stock) out.push(`<span class="pd-badge pd-badge--warn">단일종목</span>`);
  for (const f of it.flags || []) {
    if (f === "leverage" || f === "inverse") continue;            // 배수 표시가 이미 말한다
    const label = ov?.flag_labels?.[f] || f;
    out.push(`<span class="pd-badge" title="${escHtml(ov?.flag_notes?.[f] || "")}">${escHtml(label)}</span>`);
  }
  if (it.halted) out.push(`<span class="pd-badge pd-badge--warn">거래 정지</span>`);
  if (it.history_from) out.push(`<span class="pd-badge" title="우리 자료에서 처음 보인 날 — 1년이 안 된 숫자는 비워 둡니다">상장 ${escHtml(it.history_from)}</span>`);
  return out.join("");
}

function etfTable(items) {
  if (!items.length) return `<p class="pd-empty">이 묶음에 상품이 없습니다.</p>`;
  const rows = items.map(it => `<tr>
      <td class="pd-name"><button type="button" class="pd-name-main pd-open" data-chart="${escHtml(it.code)}"
        aria-label="${escHtml(it.name)} 상세 — 수익 · 낙폭 그림과 쉬운 말 근거">${escHtml(it.name)}</button>
        <div class="pd-name-sub">${escHtml(it.code)} · ${escHtml(it.index_name || "기초지수 정보 없음")}</div>${badges(it)}</td>
      <td class="pd-num">${won(it.aum)}</td>
      <td class="pd-num">${won(it.trade_value_20d)}</td>
      <td class="pd-num">${signed(it.premium_pct, 2)}</td>
      <td class="pd-num" title="가격만 본 1년 수익률 ${signed(it.price_return_1y_pct)}">${signed(it.return_1y_pct)}</td>
      <td class="pd-num">${plain(it.vol_1y_pct)}</td>
      <td class="pd-num">${signed(it.mdd_1y_pct)}</td>
    </tr>`).join("");
  return `<div class="pd-table-wrap"><table class="pd-table">
    <thead><tr><th>이름 · 기초지수</th><th class="pd-num">순자산</th><th class="pd-num">20일 거래대금</th>
      <th class="pd-num" title="종가 ÷ 순자산가치(NAV) − 1">괴리율</th><th class="pd-num">1년 수익률*</th>
      <th class="pd-num">1년 변동성*</th><th class="pd-num">1년 최대 낙폭*</th></tr></thead>
    <tbody>${rows}</tbody></table></div>`;
}

/** 머리의 자산 배분 줄 — 상태 다섯(불러오는 중 · 저장본 · 기본 비중 · 둘 다 없음 · 못 읽음)을 productweights.js 결과 그대로 */
function mixHtml(prof) {
  const w = weights;
  if (!w) {
    return `<span class="pd-dim">${weightsLoading ? "자산 배분 비중을 불러오는 중…" : ""}</span>`;
  }
  if (w.state === "none") {
    return `<span>투자 성향을 진단하면 탭이 내 자산 배분 비중 큰 순으로 바뀝니다.</span>
      <button class="pd-link" data-go="robo-portfolio">투자 성향 진단하기 →</button>`;
  }
  if (w.state === "error") {
    const what = w.step === "default" ? "저장한 배분이 없어 기본 비중을 불러오려 했지만 읽지 못했습니다" : "자산 배분 비중을 읽지 못했습니다";
    return `<span class="pd-mix-err">${what} — ${escHtml(w.message)} · 탭은 기본 차례입니다.</span>
      <button class="btn-secondary pd-weights-btn" data-act="weights" ${weightsLoading ? "disabled" : ""}>
        ${weightsLoading ? "다시 불러오는 중…" : "다시 불러오기"}</button>
      <button class="pd-link" data-go="robo-portfolio">자산 배분 화면 →</button>`;
  }
  const wt = w.allocations;
  const parts = tabOrder().filter(k => wt[k] != null).map(k => `${escHtml(classLabel(k))} ${wt[k]}%`);
  const basis = w.source === "saved"
    ? `저장한 배분${savedWhen(w.saved_at) ? ` · ${savedWhen(w.saved_at)}` : ""} · 투자 기간 ${escHtml(w.horizon_years)}년`
    : `저장한 배분이 없어 진단 성향의 기본 비중 · 투자 기간 ${escHtml(w.horizon_years)}년`;
  const go = w.source === "saved" ? "자산 배분 보기 →" : "자산 배분 계산하기 →";
  let out = `<span>자산 배분 — ${parts.join(" · ")} <span class="pd-dim">(${basis})</span></span>
    <button class="pd-link" data-go="robo-portfolio">${go}</button>`;
  if (w.differs) {
    const savedName = riskLabel(w.risk_profile);
    // 성향 이름표에 괄호가 들어 있어(「보수적 (안정추구형)」) 괄호로 다시 감싸지 않고 낫표로 — 겹친 괄호는 읽기 어렵다
    out += `<p class="pd-mix-note">저장한 배분은 ${savedName ? `「${escHtml(savedName)}」 성향으로` : "다른 성향으로"} 계산했고,
      지금 진단한 성향은 「${escHtml(prof?.level || "")}」 입니다 — 자산 배분 화면에서 다시 계산하면 탭 차례도 새 비중으로 바뀝니다.
      <button class="pd-link" data-go="robo-portfolio">다시 계산하러 가기 →</button></p>`;
  }
  return out;
}

function headerHtml() {
  const prof = readProfile();
  const chip = prof ? `<span class="pd-chip">투자 성향 ${escHtml(prof.level || prof.risk_profile)}</span>` : `<span class="pd-chip pd-chip--none">투자 성향 진단 전</span>`;
  return `<div class="pd-head">
      <h2>투자 성향별 상품 안내</h2>
      <p class="pd-lead">자산 배분 결과의 자산군마다 공시된 상품 정보를 같은 기준으로 모아 보여 줍니다.</p>
      <p class="pd-learn">처음이라면 — 개념 학습 ${learnLink("funds-etf", "펀드와 ETF")} · ${learnLink("investor-profile-suitability", "투자 성향과 적합성")}</p>
      <div class="pd-mix">${chip}${mixHtml(prof)}</div>
    </div>
    <div class="pd-note">공시된 상품 정보를 같은 기준으로 나열한 것입니다. 특정 상품의 추천이나 투자 권유가 아니며,
      순서(묶음은 거래소 유형 순서 · 묶음 안은 순자산 큰 순)는 상품의 좋고 나쁨을 뜻하지 않습니다.
      <div class="pd-dim">기준일 ${escHtml(ov?.as_of || "—")} · 출처 <a href="${escHtml(ov?.source?.url || "#")}" target="_blank" rel="noopener">${escHtml(ov?.source?.name || "")}</a></div>
    </div>`;
}

function tabsHtml() {
  const wt = loadedAllocations();
  const btns = tabOrder().map(key => {
    const on = key === active;
    if (key === DERIV_TAB) {
      return `<button role="tab" aria-selected="${on}" class="pd-tab pd-tab--warn ${on ? "is-on" : ""}" data-tab="${DERIV_TAB}">
        ${escHtml(ov.derivatives.label)} <span class="pd-tab-n">${fmt(ov.derivatives.count)}</span></button>`;
    }
    const cls = ov.classes.find(c => c.key === key);
    const w = wt && wt[key] != null ? ` ${wt[key]}%` : "";
    return `<button role="tab" aria-selected="${on}" class="pd-tab ${on ? "is-on" : ""}" data-tab="${escHtml(key)}">
      ${escHtml(cls.label)}${w} <span class="pd-tab-n">${fmt(cls.count)}</span></button>`;
  }).join("");
  const order = wt ? "탭 차례 = 내 자산 배분 비중 큰 순" : "탭 차례 = 기본 차례";
  return `<div class="pd-tabs" role="tablist">${btns}</div>
    <p class="pd-dim pd-tabs-note">${order} · 숫자 = 상품 수(모든 탭을 더하면 ${fmt(ov.total)}개 = 그날 상장 ETF 전부)</p>`;
}

function groupHtml(grp, scope) {
  const key = `${scope}|${grp.key}`;
  const ex = expanded.get(key);
  const sortSel = ex ? `<label class="pd-sort">정렬 <select data-sort="${escHtml(key)}">${SORTS.map(([v, t]) =>
    `<option value="${v}" ${ex.sort === v ? "selected" : ""}>${t}</option>`).join("")}</select></label>` : "";
  const more = !ex && grp.count > grp.items.length
    ? `<button class="pd-link" data-more="${escHtml(key)}">${fmt(grp.count)}개 모두 보기 →</button>` : "";
  const fold = ex ? `<button class="pd-link" data-fold="${escHtml(key)}">접기</button>` : "";
  let body = etfTable(ex ? ex.items : grp.items);
  if (ex?.error) body += `<p class="pd-err">${escHtml(ex.error)}</p>`;
  if (ex && ex.items.length < ex.total) {
    body += `<div class="pd-pager"><button class="btn-secondary" data-page="${escHtml(key)}" ${ex.loading ? "disabled" : ""}>
      ${ex.loading ? "불러오는 중…" : `더 보기 (${fmt(ex.items.length)} / ${fmt(ex.total)})`}</button></div>`;
  } else if (ex && ex.total) {
    body += `<p class="pd-dim pd-pager">${fmt(ex.total)}개를 모두 보였습니다.</p>`;
  }
  const req = grp.requirement && ov.requirements?.items?.[grp.requirement];
  const reqLine = req ? `<p class="pd-group-req">${escHtml(needText(req))}</p>` : "";
  return `<section class="pd-group" data-group="${escHtml(key)}">
      <div class="pd-group-head"><h3>${escHtml(grp.label)} <span class="pd-dim">${fmt(grp.count)}개</span></h3>
        <div class="pd-group-tools">${sortSel}${more}${fold}</div></div>
      ${reqLine}${body}
    </section>`;
}

/** 요건 한 줄 — 숫자는 응답(상수표)에서만 */
function needText(rq) {
  const parts = [];
  if (rq.education_hours) parts.push(`사전교육 ${rq.education_hours}시간`);
  if (rq.deposit_krw) parts.push(`${rq.deposit_cash_only ? "현금 " : ""}기본예탁금 ${won(rq.deposit_krw)} 원`);
  return parts.length ? `사려면 — ${parts.join(" · ")} (시행 ${rq.since})` : `사전교육 · 기본예탁금 대상 아님 — ${rq.other[0] || ""}`;
}

function requirementsHtml() {
  const items = ov.requirements?.items || {};
  const cards = ["leveraged_2x", "single_stock", "inverse_1x"].filter(k => items[k]).map(k => {
    const rq = items[k];
    const edu = rq.education_hours ? `${rq.education_hours}시간` : "대상 아님";
    const dep = rq.deposit_krw ? `${rq.deposit_cash_only ? "현금 " : ""}${won(rq.deposit_krw)} 원` : "대상 아님";
    const lis = [...rq.other.map(t => `<li>${escHtml(t)}</li>`),
      ...rq.planned.map(t => `<li class="pd-dim">예정 — ${escHtml(t)}</li>`)].join("");
    const src = rq.sources.map(s => `<a href="${escHtml(s.url)}" target="_blank" rel="noopener">${escHtml(s.title)}</a>`).join("<br>");
    return `<div class="pd-req">
        <div class="pd-req-title">${escHtml(rq.label)}</div>
        <p class="pd-dim">${escHtml(rq.applies_to)}</p>
        <dl><dt>사전교육</dt><dd>${escHtml(edu)} <span class="pd-dim">${escHtml(rq.education_note)}</span></dd>
          <dt>기본예탁금</dt><dd>${escHtml(dep)} <span class="pd-dim">${escHtml(rq.deposit_note)}</span></dd>
          <dt>시행</dt><dd>${escHtml(rq.since)}</dd></dl>
        ${lis ? `<ul>${lis}</ul>` : ""}
        <details><summary>출처 · 확실도</summary><p class="pd-dim">${escHtml(rq.certainty)}</p><p>${src}</p></details>
      </div>`;
  }).join("");
  return `<div class="pd-reqs"><h3>실제로 사려면 <span class="pd-dim">${escHtml(ov.requirements?.as_of || "")} 기준</span></h3>
      <div class="pd-req-grid">${cards}</div><p class="pd-dim">${escHtml(ov.requirements?.notice || "")}</p></div>`;
}

function derivativesHtml() {
  const dv = ov.derivatives;
  // 요건 문장은 바로 아래 「실제로 사려면」 카드와 같은 내용이라 상자에는 위험 구조(처음 줄)와 기준일(끝 줄)만 — 두 번 읽히지 않게
  const notes = [dv.notes[0], dv.notes[dv.notes.length - 1]].filter(Boolean).map(t => `<li>${escHtml(t)}</li>`).join("");
  const groups = dv.groups.filter(grp => grp.count > 0).map(grp => groupHtml(grp, DERIV_TAB)).join("");
  return `<div class="pd-warn" role="note"><b>주의 — 하루 수익률을 배수(또는 반대)로 따라가는 단기 매매용 상품입니다.
      자산 배분 비중을 채우는 상품이 아닙니다.</b><ul>${notes}</ul>
      <p class="pd-learn">오래 들고 있으면 왜 기초지수 수익률의 배수와 달라지나 — 개념 학습 ${learnLink("funds-etf", "펀드와 ETF")}</p></div>
    ${requirementsHtml()}${groups}`;
}

function classHtml(key) {
  const cls = ov.classes.find(c => c.key === key);
  const moved = cls.derivatives_count
    ? `<div class="pd-pointer">↪ 기초 자산이 ${escHtml(cls.label)}인 레버리지 · 인버스 <b>${fmt(cls.derivatives_count)}개</b>는 구조가 달라
        「${escHtml(ov.derivatives.label)}」 탭에 따로 모았습니다. <button class="pd-link" data-tab="${DERIV_TAB}">그 탭 보기 →</button></div>` : "";
  const groups = cls.groups.filter(grp => grp.count > 0).map(grp => groupHtml(grp, cls.key)).join("");
  return `${moved}${groups || `<p class="pd-empty">이 자산군에 상장된 ETF 가 없습니다.</p>`}${key === "현금" ? savingsHtml() : ""}`;
}

function savingsHtml() {
  const s = savings;
  const pick = (list, cur, attr) => list.map(([v, t]) =>
    `<button class="pd-pill ${String(cur) === String(v) ? "is-on" : ""}" data-${attr}="${v}">${t}</button>`).join("");
  const terms = s.kind === "annuity" ? "" : `<span class="pd-pill-sep"></span>${SAVING_TERMS.map(t =>
    `<button class="pd-pill ${s.term === t ? "is-on" : ""}" data-term="${t}">${t}개월</button>`).join("")}`;
  let body = "";
  const sv = s.sv;
  if (s.loading) {
    body = `<p class="pd-dim">금융감독원 공시를 불러오는 중…${s.kind === "saving"
      ? " 적금은 금융감독원이 목록을 만드는 데 오래 걸려 20초 ~ 1분쯤 걸릴 수 있습니다." : ""}</p>`;
  }
  else if (s.error) body = `<p class="pd-err">${escHtml(s.error)}</p>`;
  else if (sv && sv.status !== "ok") {
    body = `<p class="pd-err">${escHtml(sv.message)}</p>${sv.admin_detail ? `<p class="pd-dim">관리자 — ${escHtml(sv.admin_detail)}</p>` : ""}`;
  } else if (sv) body = savingsTable(sv);
  return `<section class="pd-group pd-savings">
      <div class="pd-group-head"><h3>예금 · 적금 · 연금저축 <span class="pd-dim">— 금융감독원 공시를 그때그때 불러옵니다(저장하지 않음)</span></h3></div>
      <div class="pd-pills">${pick(SAVING_KINDS, s.kind, "kind")}<span class="pd-pill-sep"></span>${pick(SAVING_SECTORS, s.sector, "sector")}${terms}</div>
      ${body}
    </section>`;
}

function savingsTable(sv) {
  const kindText = (SAVING_KINDS.find(([v]) => v === sv.kind) || [, ""])[1];
  const sectorText = (SAVING_SECTORS.find(([v]) => v === sv.sector) || [, ""])[1];
  const order = sv.kind === "annuity" ? "공시 이율 높은 순" : `${sv.term}개월 기본 금리 높은 순`;
  const cut = sv.truncated ? ` · 앞의 ${fmt(sv.pages_read)}쪽만 읽음(전체 ${fmt(sv.max_page_no)}쪽)` : "";
  const head = `<p class="pd-dim">${escHtml(sectorText)} ${escHtml(kindText)} ${fmt(sv.total_count)}개 · ${order} · 공시 ${escHtml(sv.disclosed_month || "—")}${cut}</p>`;
  if (!sv.items.length) {
    return `${head}<p class="pd-empty">이 업권에 공시된 ${escHtml(kindText)} 상품이 없습니다 — 다른 업권을 골라 보세요.</p>
      <p class="pd-source">${escHtml(sv.source_notice)}</p>`;
  }
  let table;
  if (sv.kind === "annuity") {
    const rows = sv.items.map(p => `<tr><td class="pd-name"><div class="pd-name-main">${escHtml(p.product)}</div>
        <div class="pd-name-sub">${escHtml(p.company)} · ${escHtml(p.pension_kind)} · ${escHtml(p.product_type)}</div></td>
        <td class="pd-num">${rate(p.disclosed_rate)}</td><td class="pd-num">${rate(p.guaranteed_rate)}</td>
        <td class="pd-num">${rate(p.avg_return)}</td><td class="pd-num">${p.past_returns.map(rate).join(" · ")}</td></tr>`).join("");
    table = `<thead><tr><th>상품 · 회사</th><th class="pd-num">공시 이율</th><th class="pd-num">최저 보증</th>
      <th class="pd-num">평균 수익률</th><th class="pd-num">지난 세 해(전년 · 전전년 · 3년 전)</th></tr></thead><tbody>${rows}</tbody>`;
  } else {
    const rows = sv.items.map(p => {
      const rt = p.rate;
      const cond = (p.special_conditions || "").split("\n")[0].slice(0, 60);
      return `<tr><td class="pd-name"><div class="pd-name-main">${escHtml(p.product)}</div>
          <div class="pd-name-sub">${escHtml(p.company)} · ${escHtml(p.join_way.join(", "))}${p.join_deny ? ` · ${escHtml(p.join_deny)}` : ""}</div></td>
          <td class="pd-num">${rate(rt?.base)}</td><td class="pd-num">${rate(rt?.max)}</td>
          <td class="pd-cond">${escHtml(rt ? [rt.rate_type, rt.reserve_type].filter(Boolean).join(" · ") : `${sv.term}개월 상품 없음`)}</td>
          <td class="pd-cond">${escHtml(cond)}</td></tr>`;
    }).join("");
    table = `<thead><tr><th>상품 · 회사 · 가입 방법</th><th class="pd-num">기본 금리</th><th class="pd-num">최고 우대</th>
      <th>이자 방식</th><th>우대 조건(앞부분)</th></tr></thead><tbody>${rows}</tbody>`;
  }
  return `${head}<div class="pd-table-wrap"><table class="pd-table">${table}</table></div>
    <p class="pd-source">${escHtml(sv.source_notice)} <a href="${escHtml(sv.source_url)}" target="_blank" rel="noopener">금융상품 한눈에 →</a></p>`;
}

function searchHtml() {
  const s = search;
  let body = "";
  if (s?.loading) body = `<p class="pd-dim">찾는 중…</p>`;
  else if (s?.error) body = `<p class="pd-err">${escHtml(s.error)}</p>`;
  else if (s?.ls) {
    const ls = s.ls;
    body = `<p class="pd-dim">「${escHtml(s.q)}」 찾은 결과 ${fmt(ls.total)}개${ls.total > ls.items.length ? ` · 앞의 ${fmt(ls.items.length)}개` : ""}
      · ${escHtml(ls.sort.label)}</p>${etfTable(ls.items)}`;
  }
  return `<form class="pd-search" data-act="search"><input class="input" name="q" maxlength="40" placeholder="이름 · 기초지수 · 종목코드로 찾기"
      value="${escHtml(s?.q || "")}" aria-label="ETF 찾기" />
      <button class="btn-secondary" type="submit">찾기</button>${s ? `<button class="pd-link" type="button" data-act="clear">지우기</button>` : ""}</form>
    ${s ? `<div class="pd-search-res">${body}</div>` : ""}`;
}

function footHtml() {
  const notes = (ov?.notes || []).map(t => `<li>${escHtml(t)}</li>`).join("");
  return `<div class="pd-foot"><p>* 우리가 모은 자료로 잰 숫자입니다(최근 1년). 과거 수익률은 미래 수익을 보장하지 않습니다.</p>
      <ul>${notes}</ul></div>`;
}

function draw() {
  const el = root();
  if (!el) return;
  if (!ov) { el.innerHTML = `<p class="pd-dim">상품 정보를 불러오는 중…</p>`; return; }
  if (ov.status !== "ok") {
    const why = ov.status === "no_data" ? "아직 모은 ETF 시세가 없습니다 — 매일 낮 자료 갱신 뒤에 다시 열어 주세요."
      : "ETF 시세 자료를 읽지 못했습니다 — 잠시 뒤 다시 열어 주세요.";
    el.innerHTML = `${headerHtml()}<p class="pd-err">${why}</p>`;
    return;
  }
  const body = search ? "" : (active === DERIV_TAB ? derivativesHtml() : classHtml(active));
  el.innerHTML = `${headerHtml()}${searchHtml()}${search ? "" : tabsHtml()}<div class="pd-body">${body}</div>${footHtml()}`;
}

// ── 불러오기 ───────────────────────────────────────────────────────────
async function loadOverview() {
  const my = ++seq;
  try {
    const r = await api(`/api/products/etfs/overview?per_group=${PER_GROUP}`);
    if (my !== seq) return;
    ov = r;
    if (!active || (active !== DERIV_TAB && !ov.classes.some(c => c.key === active))) active = tabOrder()[0];
  } catch (e) {
    if (my !== seq) return;
    ov = { status: "error", notes: [] };
  }
  draw();
  if (active === "현금" && !savings.sv && !savings.loading) loadSavings();
}

function listUrl(key, offset, sort) {
  const [scope, group] = key.split("|");
  const [by, order] = sort.split(":");
  const q = new URLSearchParams({ group, sort: by, order, offset: String(offset), limit: String(PAGE) });
  if (scope !== DERIV_TAB) q.set("asset_class", scope);
  return `/api/products/etfs?${q}`;
}

async function loadGroup(key, { more = false } = {}) {
  const ex = expanded.get(key) || { sort: SORTS[0][0], items: [], total: 0 };
  ex.loading = true; ex.error = "";
  expanded.set(key, ex);
  draw();
  try {
    const ls = await api(listUrl(key, more ? ex.items.length : 0, ex.sort));
    ex.items = more ? ex.items.concat(ls.items) : ls.items;
    ex.total = ls.total;
  } catch (e) {
    ex.error = `목록을 불러오지 못했습니다 — ${e.message}`;
  }
  ex.loading = false;
  draw();
}

async function loadSavings() {
  const s = savings;
  const my = ++savingsSeq;
  s.loading = true; s.error = "";
  draw();
  const q = new URLSearchParams({ kind: s.kind, sector: s.sector, sort: s.kind === "annuity" ? "base" : s.sort });
  if (s.kind !== "annuity") q.set("term", String(s.term));
  try {
    const sv = await api(`/api/products/savings?${q}`);
    if (my !== savingsSeq) return;                                   // 조건을 바꾼 사이에 온 옛 응답은 버린다
    s.sv = sv;
  } catch (e) {
    if (my !== savingsSeq) return;
    s.sv = null;
    s.error = `금융감독원 공시를 불러오지 못했습니다 — ${e.message}`;
  }
  s.loading = false;
  draw();
}

/** 비중 — 화면에 들어올 때마다 저절로(가벼운 GET 하나 · 저장본이 없을 때만 둘) · 못 읽었을 때는 「다시 불러오기」 단추로 */
async function loadWeights() {
  const my = ++weightsSeq;
  weightsLoading = true;
  draw();
  const w = await resolveWeights(api, readProfile());
  if (my !== weightsSeq) return;                                    // 다시 들어온 사이에 온 옛 결과는 버린다
  weights = w;
  weightsLoading = false;
  if (!tabPicked && ov?.status === "ok") active = tabOrder()[0];    // 고른 탭이 없을 때만 비중 큰 탭으로
  draw();
  if (active === "현금" && !savings.sv && !savings.loading) loadSavings();
}

async function runSearch(q) {
  search = { q, loading: true };
  draw();
  try {
    const ls = await api(`/api/products/etfs?${new URLSearchParams({ q, limit: String(PAGE) })}`);
    if (search?.q === q) search = { q, ls };
  } catch (e) {
    if (search?.q === q) search = { q, error: `찾지 못했습니다 — ${e.message}` };
  }
  draw();
}

// ── 단추 ──────────────────────────────────────────────────────────────
function onClick(ev) {
  const t = ev.target.closest("button");
  if (!t || !root()?.contains(t)) return;
  const d = t.dataset;
  // ETF 이름 → 상품 상세 창(js/productchart.js) — 닫으면 초점을 이 단추로 돌려준다
  if (d.chart) { openProductChart(d.chart, { name: t.textContent.trim(), returnFocus: t }); return; }
  if (d.go) { navigate(d.go); return; }
  if (d.tab) {
    active = d.tab;
    tabPicked = true;
    draw();
    root()?.querySelector(".pd-tabs")?.scrollIntoView({ block: "nearest" });
    if (active === "현금" && !savings.sv && !savings.loading) loadSavings();
    return;
  }
  if (d.act === "weights") { loadWeights(); return; }
  if (d.act === "clear") { search = null; draw(); return; }
  if (d.more) { loadGroup(d.more); return; }
  if (d.page) { loadGroup(d.page, { more: true }); return; }
  if (d.fold) { expanded.delete(d.fold); draw(); return; }
  if (d.kind) {
    savings.kind = d.kind;
    if (d.kind === "annuity" && !ANNUITY_SECTORS.includes(savings.sector)) savings.sector = ANNUITY_SECTORS[0];
    savings.sv = null; loadSavings(); return;
  }
  if (d.sector) { savings.sector = d.sector; savings.sv = null; loadSavings(); return; }
  if (d.term) { savings.term = Number(d.term); savings.sv = null; loadSavings(); }
}

function onChange(ev) {
  const sel = ev.target.closest("select[data-sort]");
  if (!sel || !root()?.contains(sel)) return;
  const ex = expanded.get(sel.dataset.sort);
  if (!ex) return;
  ex.sort = sel.value;
  loadGroup(sel.dataset.sort);
}

function onSubmit(ev) {
  const form = ev.target.closest("form[data-act=search]");
  if (!form || !root()?.contains(form)) return;
  ev.preventDefault();
  const q = (form.elements.q.value || "").trim();
  if (!q) { search = null; draw(); return; }
  runSearch(q);
}

let wired = false;
function wire() {
  if (wired) return;
  const el = root();
  if (!el) return;
  el.addEventListener("click", onClick);
  el.addEventListener("change", onChange);
  el.addEventListener("submit", onSubmit);
  wired = true;
}

export function onProductsViewActivated(view) {
  if (view !== "agent-products") return;   // 글자 그대로 — 화면 스캐너(scripts/view_scan.py)가 이 모양으로 진입 훅을 읽는다
  wire();
  draw();
  loadOverview();
  loadWeights();
}
