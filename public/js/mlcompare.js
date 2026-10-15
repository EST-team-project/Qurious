/* 모델 비교 — ML·딥러닝 화면(화면 키 ml-compare) (2026-10-15)
 *
 * 무엇을 그리나(서버가 판정 · 문장 · 이름표 · 고르기 값을 짓고 이 파일은 그대로 그린다 — 문장을 여기서 다시 짓지 않는다):
 *   GET  /api/model-compare/choices      고르기 값(기간 · 종목 제안 · 관리자 손잡이 범위) · 관리자 여부     (API-MCMP-02)
 *   POST /api/model-compare/jobs         계산 시작 — 저장본이 맞으면 곧바로 결과(200) · 아니면 앱 안 작업(202) (API-MCMP-03)
 *   GET  /api/model-compare/jobs/{id}    1초마다 진행(몇째 모델 · 몇째 겹 — 서버가 센 값 · 지난 시간 · 보통 시간) · 끝나면 결과 (API-MCMP-04)
 * 계산은 서버 `app/services/model_compare.py`(시간 순서 검증 · 기준선 넷 · 블록 부트스트랩 · 홀름 · 셋 모두보다 뚜렷할 때만 「낫다」).
 * 옛 칸은 강사님 GET /api/ml/compare(교차검증이 미래 자료로 학습 · 기준선 없음 · 「7종」 인데 모델 8개)를 불렀다 — 그 길은 그대로
 *   두고 이 화면만 새 길을 쓴다. 강사님 파일(app.html · main.js · core.js · ml.js)에는 뿌리 칸 · 부르는 줄 · 이름표 · 도움말 글만.
 * 숫자 + 그림 + 쉬운 말 근거를 한 덩어리로(사용자 규칙) · 과거 성과 고지 · 다음 행동 단추(명확성 · 흐름 · CTA).
 * 그림은 SVG 를 직접 그린다(점 그림 · 겹 띠 — 바깥 그림 도구 없이 · 테마 색은 app.css 토큰).
 */
import { api, escHtml } from "/js/common.js";
import { compareTrayAdd, navigate, renderCompareTrayAll } from "/js/core.js";

const VIEW = "ml-compare";
const ACTION = { "X-Qurious-Action": "model-compare" };
const POLL_MS = 1000;
const LATE_MS = 30000;      // 이보다 오래 걸리면 「계속 기다리기 · 나중에 보기」 를 보인다(NN/g 10초 · 사용자 결정 2026-10-15)
const PREF_KEY = "mv_pref_v1";

const S = { ch: null, admin: false, q: null, job: null, d: null, err: null, busy: false, late: false, waitOk: false,
            pollTimer: null, tab: "plot", note: "" };

function root() { return document.querySelector(`.view[data-view="${VIEW}"] .mv-root`); }
function pct(v, nd = 1) { return v == null || Number.isNaN(v) ? "—" : `${(v * 100).toFixed(nd)}%`; }
function pp(v) { return v == null ? "—" : `${v >= 0 ? "+" : "−"}${Math.abs(v * 100).toFixed(1)}%p`; }
function secs(ms) { return ms == null ? "—" : `${Math.round(ms / 1000)}초`; }
function nameOf(code) {
  const hit = (S.ch && S.ch.choices.suggest || []).find(s => s.code === code);
  return hit ? hit.name : "";
}

function readPref() {
  try { const p = JSON.parse(localStorage.getItem(PREF_KEY) || "null"); return p && typeof p === "object" ? p : null; } catch { return null; }
}
function savePref(q) { try { localStorage.setItem(PREF_KEY, JSON.stringify({ symbol: q.symbol, period: q.period })); } catch { /* 저장소를 못 쓰면 고른 값만 잊는다 */ } }

// ── 고르기 줄 ─────────────────────────────────────────────────────

function controlsHtml() {
  const c = S.ch.choices;
  const q = S.q;
  const noJudge = c.periods.filter(p => !p.judged).map(p => p.label);   // 판정하지 않는 기간 — 서버 고르기 값에서
  const seg = c.periods.map(p => `<button type="button" class="${p.key === q.period ? "on" : ""}" data-period="${p.key}"
      aria-pressed="${p.key === q.period}" title="${p.judged ? "" : "시험 자료가 적어 판정하지 않고 겹별 점수만 봅니다"}">${escHtml(p.label)}${p.judged ? "" : " *"}</button>`).join("");
  // 이름표와 칸은 한 묶음(.mv-field)으로 — 좁은 폭에서 「기간」 이름표만 윗줄에 남지 않게(390 확인 · 2026-10-15)
  const admin = S.admin ? `<span class="mv-field"><span class="mv-lbl">겹 수</span>
      <input class="mv-num" type="number" data-q="n_splits" min="${c.n_splits.min}" max="${c.n_splits.max}" value="${q.n_splits ?? c.n_splits.default}" aria-label="겹 수(관리자)"></span>
      <span class="mv-field"><span class="mv-lbl">간격(거래일)</span>
      <input class="mv-num" type="number" data-q="gap" min="${c.gap.min}" max="${c.gap.max}" value="${q.gap ?? c.gap.default}" aria-label="간격(관리자)">
      <span class="mv-admin-tag">관리자</span></span>` : "";
  return `<div class="mv-bar">
    <span class="mv-field"><label class="mv-lbl" for="mv-symbol">종목</label>
    <input id="mv-symbol" class="mv-sym" list="mv-suggest" maxlength="9" value="${escHtml(q.symbol)}" placeholder="005930" autocomplete="off">
    <datalist id="mv-suggest">${c.suggest.map(s => `<option value="${escHtml(s.code)}">${escHtml(s.name)}</option>`).join("")}</datalist>
    <span class="mv-symname">${escHtml(nameOf(q.symbol))}</span></span>
    <span class="mv-field"><span class="mv-lbl">기간</span><div class="mv-seg" role="group" aria-label="기간">${seg}</div></span>
    ${admin}
    <button type="button" class="mv-run" data-act="run" ${S.busy ? "disabled" : ""}>${S.busy ? "계산 중…" : "비교하기"}</button>
  </div>${noJudge.length ? `
  <p class="mv-note">* ${escHtml(noJudge.join(" · "))}은 시험 자료가 적어 모델이 기준선보다 나은지 판정하지 않습니다(겹별 점수만).</p>` : ""}`;
}

// ── 진행 · 오류 ───────────────────────────────────────────────────

function progressHtml() {
  const j = S.job || {};
  const p = j.progress || {};
  const total = p.model_count || (S.ch ? S.ch.model_count : 8);
  const done = p.stage === "judging" ? total : Math.max(0, (p.model_index || 1) - 1);
  const boxes = Array.from({ length: total }, (_, i) => `<i class="${i < done ? "on" : i === done && p.stage === "models" ? "now" : ""}"></i>`).join("");
  const basis = j.expected_basis === "last" ? `지난번 ${secs(j.expected_ms)}` : `보통 ${secs(j.expected_ms)} 안팎`;
  const step = p.stage === "queued" || !p.stage ? "차례를 기다리는 중 — 다른 계산이 끝나면 시작합니다"
    : p.stage === "baselines" ? "기준선 넷을 계산하는 중"
    : p.stage === "judging" ? "모든 시험 날을 합쳐 기준선과 견주는 중(판정)"
    : `모델 ${p.model_index} / ${total} — ${escHtml(p.model || "")} · 겹 ${p.fold} / ${p.folds}`;
  const range = p.stage === "models" && p.test_from ? `<div class="mv-note">지금 시험 구간 ${escHtml(p.test_from)} ~ ${escHtml(p.test_to)}</div>` : "";
  const late = S.late && !S.waitOk ? `<div class="mv-late">생각보다 오래 걸립니다.
      <button type="button" class="mv-btn" data-act="wait">계속 기다리기</button>
      <button type="button" class="mv-btn" data-act="later">나중에 보기</button></div>` : "";
  return `<div class="mv-card mv-progress" role="status" aria-live="polite">
    <div class="mv-prog-head"><b>계산 중</b> · ${secs(j.elapsed_ms)} 지남 · ${basis}</div>
    <div class="mv-boxes" aria-hidden="true">${boxes}</div>
    <div class="mv-step">${step}</div>${range}
    <div class="mv-note">다른 화면에 다녀와도 계산은 이어집니다 — 끝나면 저장돼 다음부터는 바로 보입니다.</div>${late}
  </div>`;
}

function errorHtml() {
  const e = S.err || {};
  const code = e.code || "";
  const act = ["symbol_not_found", "bad_symbol", "etf_not_supported"].includes(code)
    ? `<div class="mv-chips">${S.ch.choices.suggest.slice(0, 8).map(s => `<button type="button" class="mv-chip" data-pick="${escHtml(s.code)}">${escHtml(s.name)}</button>`).join("")}</div>`
    : `<button type="button" class="mv-btn" data-act="run">다시 시도</button>`;
  return `<div class="mv-card mv-state" role="alert"><p>${escHtml(e.message || "계산하지 못했습니다.")}</p>${act}
    ${e.admin_hint ? `<div class="mv-admin">${escHtml(e.admin_hint)}</div>` : ""}</div>`;
}

// ── 결과 부품 — C 요약 카드 · 왜 · B 그림 · A 표 ───────────────────

function metaHtml(d) {
  const f0 = d.cv.folds[0], fl = d.cv.folds[d.cv.folds.length - 1];
  const cache = d.cached ? " · 저장된 결과" : "";
  return `<p class="mv-meta">자료 기준일 <b>${escHtml(d.data.as_of)}</b> · ${escHtml(d.data.label)} · 기간 ${escHtml(d.data.window)}
    · 시험한 날 ${d.samples.test_rows}일(${escHtml(f0.test_from)} ~ ${escHtml(fl.test_to)}) · 계산 ${escHtml((d.computed_at || "").slice(0, 16).replace("T", " "))}
    · ${secs(d.elapsed_ms)}${cache}</p>`;
}

function cardsHtml(d) {
  const better = d.models.filter(m => m.verdict === "better").length;
  const strong = d.baselines.find(b => b.strongest) || d.baselines[0];
  const f0 = d.cv.folds[0], fl = d.cv.folds[d.cv.folds.length - 1];
  const first = d.samples.judged
    ? `<b>${better} / ${d.model_count}</b><span>기준선 셋 모두보다 뚜렷이 나은 모델</span>`
    : `<b>${escHtml(d.verdict_labels.insufficient)}</b><span>시험 자료 ${d.samples.test_rows}일(최소 ${d.samples.min_judge_rows}일)</span>`;
  return `<div class="mv-cards">
    <div class="mv-kpi">${first}</div>
    <div class="mv-kpi"><b>${escHtml(strong.name)} ${pct(strong.balanced_accuracy)}</b><span>이번 시험에서 가장 높았던 기준선(균형 정확도)</span></div>
    <div class="mv-kpi"><b>${d.samples.test_rows}일</b><span>${escHtml(f0.test_from)} ~ ${escHtml(fl.test_to)} · 겹 ${d.cv.n_splits} · 간격 ${d.cv.gap}거래일</span></div>
  </div>`;
}

function whyHtml(d) {
  const items = d.insights || [];
  if (!items.length) return "";
  return `<section class="mv-card"><h3>왜 이런 결과인가</h3><div class="mv-why">${items.map(it => {
    const top = Math.max(0.6, ...it.bars.map(b => b.value));
    return `<div class="mv-why-item"><h4>${escHtml(it.title)}</h4><p>${escHtml(it.text)}</p>
      ${it.bars.map(b => `<div class="mv-hbar"><span>${escHtml(b.label)}</span><div class="mv-track"><div class="mv-fill" style="width:${(b.value / top * 100).toFixed(1)}%"></div></div><span class="mv-num-r">${pct(b.value)}</span></div>`).join("")}
    </div>`;
  }).join("")}</div></section>`;
}

function verdictBadge(d, v) {
  return `<span class="mv-badge mv-v-${v}" title="${escHtml(d.verdict_texts[v])}">${escHtml(d.verdict_labels[v])}</span>`;
}

function bandSvg(d) {
  const n = d.samples.rows, W = 760, padL = 52, padR = 12, rowH = 16, top = 8;
  const H = top + d.cv.folds.length * (rowH + 6) + 22;
  const x = i => padL + i / Math.max(1, n - 1) * (W - padL - padR);
  const rows = d.cv.folds.map((f, k) => {
    const y = top + k * (rowH + 6);
    const te = f.test_start_idx + f.test_rows - 1;
    return `<text x="${padL - 8}" y="${y + rowH - 4}" class="mv-svg-lbl" text-anchor="end">겹 ${f.k}</text>
      <rect x="${x(0)}" y="${y}" width="${x(f.train_end_idx) - x(0)}" height="${rowH}" class="mv-tr"><title>학습 ${f.train_from} ~ ${f.train_to} · ${f.train_rows}일</title></rect>
      <rect x="${x(f.train_end_idx)}" y="${y}" width="${Math.max(1, x(f.test_start_idx) - x(f.train_end_idx))}" height="${rowH}" class="mv-gap"><title>간격 ${d.cv.gap}거래일 — 비움</title></rect>
      <rect x="${x(f.test_start_idx)}" y="${y}" width="${Math.max(2, x(te) - x(f.test_start_idx))}" height="${rowH}" class="mv-te"><title>시험 ${f.test_from} ~ ${f.test_to} · ${f.test_rows}일</title></rect>`;
  }).join("");
  const yb = top + d.cv.folds.length * (rowH + 6) + 14;
  return `<div class="mv-plotwrap"><svg class="mv-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="겹 나누기 — 과거로 학습하고 바로 뒤 구간으로 시험">
    ${rows}<text x="${padL}" y="${yb}" class="mv-svg-lbl">${escHtml(d.period.from)}</text>
    <text x="${W - padR}" y="${yb}" class="mv-svg-lbl" text-anchor="end">${escHtml(d.period.to)}</text></svg></div>
    <p class="mv-legend"><i class="mv-tr"></i>학습 <i class="mv-gap"></i>간격(비움) <i class="mv-te"></i>시험 — 시험 구간은 늘 학습 구간 뒤입니다</p>`;
}

function plotSvg(d) {
  const rows = [...d.models.map(m => ({ ...m, kind: "model" })), { sep: true }, ...d.baselines.map(b => ({ ...b, kind: "base" }))];
  const W = 760, padL = 178, padR = 110, rowH = 26, top = 26;
  const H = top + rows.length * rowH + 26;
  const vals = [...d.models, ...d.baselines].flatMap(r => [...r.fold_scores, r.balanced_accuracy]);
  const lo = Math.max(0, Math.floor((Math.min(...vals) - 0.02) * 20) / 20);
  const hi = Math.min(1, Math.ceil((Math.max(...vals) + 0.02) * 20) / 20);
  const x = v => padL + (v - lo) / Math.max(0.01, hi - lo) * (W - padL - padR);
  const rnd = d.baselines.find(b => b.key === "random");
  const strong = d.baselines.find(b => b.strongest);
  const ticks = [];
  for (let t = lo; t <= hi + 1e-9; t += 0.05) ticks.push(t);
  let y = top;
  const body = rows.map(r => {
    if (r.sep) { y += rowH; return `<line x1="${padL - 160}" x2="${W - 8}" y1="${y - rowH / 2}" y2="${y - rowH / 2}" class="mv-sep"/>`; }
    const cy = y + rowH / 2;
    y += rowH;
    const dots = r.fold_scores.map((s, i) => `<circle cx="${x(s)}" cy="${cy}" r="3.4" class="mv-dot ${r.kind}"><title>겹 ${i + 1} · ${pct(s)}</title></circle>`).join("");
    const cx = x(r.balanced_accuracy);
    const dia = `<polygon points="${cx},${cy - 6} ${cx + 6},${cy} ${cx},${cy + 6} ${cx - 6},${cy}" class="mv-dia ${r.kind} ${r.kind === "model" ? `mv-v-${r.verdict}` : ""}"><title>${escHtml(r.name)} · 시험 합침 ${pct(r.balanced_accuracy)}</title></polygon>`;
    const right = r.kind === "model" ? `<text x="${W - padR + 8}" y="${cy + 4}" class="mv-svg-lbl mv-v-txt mv-v-${r.verdict}">${escHtml(d.verdict_labels[r.verdict])}</text>`
      : `<text x="${W - padR + 8}" y="${cy + 4}" class="mv-svg-lbl mv-mute">${r.role === "chance_band" ? "우연 띠" : "기준선"}</text>`;
    return `<text x="${padL - 10}" y="${cy + 4}" class="mv-svg-lbl ${r.kind === "base" ? "mv-mute" : ""}" text-anchor="end">${escHtml(r.name)}</text>${dots}${dia}${right}`;
  }).join("");
  // 좁은 폭에서는 그림을 최소 폭(CSS .mv-plotwrap)으로 두고 옆으로 민다 — 줄여 그리면 모델 이름 · 판정 글이 읽히지 않는다(390 확인)
  return `<p class="mv-swipe">그림을 옆으로 밀어 전체를 봅니다</p><div class="mv-plotwrap"><svg class="mv-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="모델과 기준선의 균형 정확도 — 겹마다 점 · 합친 값은 마름모">
    ${rnd ? `<rect x="${x(rnd.fold_min)}" y="${top - 6}" width="${Math.max(1, x(rnd.fold_max) - x(rnd.fold_min))}" height="${H - top - 14}" class="mv-band"><title>${escHtml(rnd.name)} 기준선이 겹마다 낸 범위 ${pct(rnd.fold_min)} ~ ${pct(rnd.fold_max)}</title></rect>` : ""}
    ${ticks.map(t => `<line x1="${x(t)}" x2="${x(t)}" y1="${top - 6}" y2="${H - 20}" class="mv-grid"/><text x="${x(t)}" y="${H - 6}" class="mv-svg-lbl" text-anchor="middle">${Math.round(t * 100)}%</text>`).join("")}
    ${strong ? `<line x1="${x(strong.balanced_accuracy)}" x2="${x(strong.balanced_accuracy)}" y1="${top - 10}" y2="${H - 20}" class="mv-strong"/><text x="${x(strong.balanced_accuracy)}" y="${top - 12}" class="mv-svg-lbl" text-anchor="middle">가장 높았던 기준선</text>` : ""}
    ${body}</svg></div>
    <p class="mv-legend"><i class="mv-dot-i"></i>겹 하나의 점수 <i class="mv-dia-i"></i>시험 날을 합친 점수 <i class="mv-band-i"></i>우연 띠(찍기 기준선이 겹마다 낸 범위) — 오른쪽으로 갈수록 잘 맞힘</p>`;
}

function tableHtml(d) {
  const head = `<tr><th>순위</th><th>모델</th><th class="r">균형 정확도</th><th class="r">겹별(최저 ~ 최고)</th><th class="r">정확도</th>
    <th class="r">학습 점수</th>${d.models[0].vs_baselines.map(c => `<th class="r">「${escHtml(d.baselines.find(b => b.key === c.baseline).name)}」 대비</th>`).join("")}<th>판정</th></tr>`;
  const mrows = d.models.map(m => `<tr><td>${m.rank}${m.top_group ? ' <span class="mv-top" title="1등과 차이가 우연 범위 안">1등 묶음</span>' : ""}</td>
    <td>${escHtml(m.name)}${m.warnings.length ? ` <span class="mv-warn" title="${escHtml(m.warnings.join(" · "))}">!</span>` : ""}</td>
    <td class="r">${pct(m.balanced_accuracy)}</td><td class="r">${pct(m.fold_min)} ~ ${pct(m.fold_max)}</td><td class="r">${pct(m.accuracy)}</td>
    <td class="r">${pct(m.train_fold_mean)}</td>
    ${m.vs_baselines.map(c => `<td class="r" title="95% 구간 ${pp(c.ci95[0])} ~ ${pp(c.ci95[1])} · 보정 p ${c.p_holm ?? "—"}">${pp(c.diff)}</td>`).join("")}
    <td>${verdictBadge(d, m.verdict)}</td></tr>`).join("");
  const brows = d.baselines.map(b => `<tr class="mv-base"><td>—</td><td>${escHtml(b.name)}<span class="mv-mute"> · ${b.role === "chance_band" ? "우연 띠" : "기준선"}</span></td>
    <td class="r">${pct(b.balanced_accuracy)}</td><td class="r">${pct(b.fold_min)} ~ ${pct(b.fold_max)}</td><td class="r">${pct(b.accuracy)}</td><td class="r">—</td>
    ${d.models[0].vs_baselines.map(() => "<td></td>").join("")}<td></td></tr>`).join("");
  return `<div class="mv-tablewrap"><table class="mv-table"><caption class="mv-note">겹 ${d.cv.n_splits} · 간격 ${d.cv.gap}거래일 · 기준선과 차이는 같은 시험 날끼리 견준 값(마우스를 올리면 95% 구간)</caption>
    <thead>${head}</thead><tbody>${mrows}${brows}</tbody></table></div>`;
}

function detailHtml(d) {
  const tabs = `<div class="mv-tabs" role="tablist">
    <button type="button" role="tab" data-tab="plot" aria-selected="${S.tab === "plot"}" class="${S.tab === "plot" ? "on" : ""}">그림으로 보기</button>
    <button type="button" role="tab" data-tab="table" aria-selected="${S.tab === "table"}" class="${S.tab === "table" ? "on" : ""}">표로 보기</button></div>`;
  return `${tabs}${S.tab === "table" ? tableHtml(d) : `${plotSvg(d)}<h4 class="mv-sub">겹 나누기</h4>${bandSvg(d)}`}`;
}

function ctaHtml() {
  return `<div class="mv-cta">
    <button type="button" class="mv-btn" data-act="screening">종목 스크리닝에서 판단 근거(XAI) 보기</button>
    <button type="button" class="mv-btn" data-act="lectures">강의실 — 교차 검증 실습</button>
    <button type="button" class="mv-btn" data-act="tray">비교에 추가</button>
    <button type="button" class="mv-btn" data-act="other">다른 종목 보기</button>
  </div>`;
}

function defsHtml(d) {
  const lab = { balanced_accuracy: "균형 정확도", accuracy: "정확도", direction_hit: "방향 적중", coverage: "신호 비율", train_score: "학습 점수",
    fold: "겹", gap: "간격", weighting: "계층 균형 가중", verdict: "판정", top_group: "1등 묶음" };
  return `<details class="mv-defs"><summary>용어 풀이 · 한계</summary><dl>${Object.entries(d.definitions).map(([k, v]) =>
    `<dt>${escHtml(lab[k] || k)}</dt><dd>${escHtml(v)}</dd>`).join("")}</dl>
    <ul class="mv-limits">${d.limits.map(t => `<li>${escHtml(t)}</li>`).join("")}</ul></details>`;
}

function resultHtml(d) {
  const title = `<h3 class="mv-title">${escHtml(nameOf(d.symbol) || d.symbol)} <small>${escHtml(d.symbol)} · ${escHtml(d.request ? d.request.period_label : "")}</small></h3>`;
  const head = `<section class="mv-card mv-headline">${title}<p class="mv-hl">${escHtml(d.headline)}</p>${metaHtml(d)}</section>`;
  // 화면 꼴(Figma 「Qurious · 모델 비교」 05 [결정] · 사용자 2026-10-15): 요약 카드 + 「왜」 위에, 「자세히」 안에 점 그림 · 겹 띠와 표를 탭으로
  const body = `${cardsHtml(d)}${whyHtml(d)}<details class="mv-card mv-more" open><summary><b>자세히</b> — 겹마다 점수 · 표로 보기</summary>${detailHtml(d)}</details>`;
  // 비교 트레이 자리 — core.js COMPARE_TRAY_MOUNTS 의 옛 id 를 그대로 쓴다(옛 칸과 함께 사라지면 「비교에 추가」 뒤 볼 곳이 없다)
  return `${head}${body}${ctaHtml()}<div id="mlc-compare-tray"></div>${defsHtml(d)}
    <p class="mv-note mv-notice">${escHtml(d.notice)} · 자료: ${escHtml(d.data.attribution)}</p>`;
}

function paint() {
  const el = root();
  if (!el) return;
  const head = `<header class="mv-head"><h2>모델 비교</h2>
    <p>지난 시세로 학습한 모델이 5거래일 뒤 오름 · 관망 · 내림을 얼마나 맞히는지, 아무것도 배우지 않은 기준선과 견줍니다${S.ch ? ` · 모델 ${S.ch.model_count}개 · 기준선 4개` : ""}</p></header>`;
  if (!S.ch) { el.innerHTML = `${head}<div class="mv-card mv-state">${S.err ? escHtml(S.err.message) : "불러오는 중입니다…"}</div>`; return; }
  const status = S.busy ? progressHtml() : S.err ? errorHtml() : "";
  const note = S.note ? `<p class="mv-note mv-notice" role="status">${escHtml(S.note)}</p>` : "";
  const ms = S.ch.choices.periods.map(p => p.expected_ms);
  const intro = !S.d && !S.busy && !S.err ? `<div class="mv-card mv-intro"><p>종목과 기간을 고르고 <b>비교하기</b>를 누르세요. 처음 계산은 보통 ${secs(Math.min(...ms))} ~ ${secs(Math.max(...ms))} 걸리고, 한 번 계산한 결과는 저장돼 다음부터 바로 보입니다.</p>
    <button type="button" class="mv-run" data-act="run">${escHtml(nameOf(S.q.symbol) || S.q.symbol)} · ${escHtml((S.ch.choices.periods.find(p => p.key === S.q.period) || {}).label || S.q.period)}로 비교하기</button></div>` : "";
  el.innerHTML = `${head}${controlsHtml()}${note}${status}${intro}${S.d && !S.busy ? resultHtml(S.d) : ""}`;
  if (S.d && !S.busy) renderCompareTrayAll();   // 다시 그린 트레이 자리에 담아 둔 항목을 채운다
}

// ── 계산 · 진행 묻기 ───────────────────────────────────────────────

function stopPoll() { clearTimeout(S.pollTimer); S.pollTimer = null; }

function finish(d) {
  stopPoll();
  S.busy = false;
  S.job = null;
  S.d = d;
  S.err = null;
  paint();
}

function fail(e) {
  stopPoll();
  S.busy = false;
  S.job = null;
  S.err = (e && e.detail) || { message: e && e.message ? e.message : "계산하지 못했습니다." };
  paint();
}

async function poll(jobId, startedAt) {
  try {
    const st = await api(`/api/model-compare/jobs/${encodeURIComponent(jobId)}`);
    if (st.status === "done") return finish(st.result);
    S.job = st;
    S.late = Date.now() - startedAt > LATE_MS;
    paint();
    S.pollTimer = setTimeout(() => poll(jobId, startedAt), POLL_MS);
  } catch (e) { fail(e); }
}

async function run() {
  if (S.busy) return;
  readControls();
  savePref(S.q);
  stopPoll();
  S.busy = true; S.err = null; S.note = ""; S.late = false; S.waitOk = false;
  S.job = { progress: { stage: "queued" }, elapsed_ms: 0 };
  paint();
  const body = { symbol: S.q.symbol, period: S.q.period };
  if (S.admin) { body.n_splits = S.q.n_splits; body.gap = S.q.gap; }
  try {
    const st = await api("/api/model-compare/jobs", { method: "POST", body, headers: ACTION });
    if (st.status === "done") return finish(st.result);
    S.job = st;
    paint();
    const startedAt = Date.now() - (st.elapsed_ms || 0);
    S.pollTimer = setTimeout(() => poll(st.job_id, startedAt), POLL_MS);
  } catch (e) { fail(e); }
}

function readControls() {
  const el = root();
  if (!el) return;
  const sym = el.querySelector("#mv-symbol");
  if (sym) S.q.symbol = sym.value.trim();
  if (S.admin) {
    const n = el.querySelector('[data-q="n_splits"]');
    const g = el.querySelector('[data-q="gap"]');
    S.q.n_splits = n && n.value !== "" ? Number(n.value) : null;
    S.q.gap = g && g.value !== "" ? Number(g.value) : null;
  }
}

function onClick(ev) {
  const t = ev.target.closest("button");
  if (!t) return;
  if (t.dataset.period) { readControls(); S.q.period = t.dataset.period; paint(); return; }
  if (t.dataset.tab) { S.tab = t.dataset.tab; paint(); return; }
  if (t.dataset.pick) { S.q.symbol = t.dataset.pick; S.err = null; paint(); run(); return; }
  const act = t.dataset.act;
  if (act === "run") run();
  else if (act === "wait") { S.waitOk = true; paint(); }
  else if (act === "later") {
    stopPoll(); S.busy = false; S.job = null;
    S.note = "계산은 서버에서 이어집니다 — 조금 뒤 「비교하기」 를 다시 누르면 저장된 결과를 바로 봅니다.";
    paint();
  } else if (act === "screening") navigate("robo-screening");
  else if (act === "lectures") navigate("fin-lectures");
  else if (act === "other") { const s = root().querySelector("#mv-symbol"); if (s) { s.focus(); s.select(); } }
  else if (act === "tray" && S.d) {
    const d = S.d;
    const better = d.models.filter(m => m.verdict === "better").length;
    const top = d.models[0];
    compareTrayAdd({
      source: "모델 비교",
      label: `${nameOf(d.symbol) || d.symbol} · ${d.request ? d.request.period_label : ""}`,
      summary: `기준선을 뚜렷이 넘은 모델 ${better}/${d.model_count} · 가장 높은 모델 ${top.name} ${pct(top.balanced_accuracy)} · 기준일 ${d.data.as_of}`,
    });
  }
}

function onChange(ev) {
  if (ev.target && ev.target.id === "mv-symbol") { readControls(); const n = root().querySelector(".mv-symname"); if (n) n.textContent = nameOf(S.q.symbol); }
}

async function loadChoices() {
  try {
    const r = await api("/api/model-compare/choices");
    S.ch = r;
    S.admin = !!r.admin;
    const pref = readPref() || {};
    const valid = r.choices.periods.some(p => p.key === pref.period);
    S.q = { symbol: pref.symbol || r.choices.default.symbol, period: valid ? pref.period : r.choices.default.period,
            n_splits: null, gap: null };
  } catch (e) {
    S.err = (e && e.detail) || { message: "고르기 값을 불러오지 못했습니다. 잠시 뒤 다시 시도해 주세요." };
  }
  paint();
}

let wired = false;
export function onModelCompareViewActivated(view) {
  if (view !== "ml-compare") return;   // 글자 그대로 — 화면 스캐너(scripts/view_scan.py)가 이 모양으로 진입 훅을 읽는다
  const el = root();
  if (!el) return;
  if (!wired) {
    el.addEventListener("click", onClick);
    el.addEventListener("change", onChange);
    wired = true;
  }
  if (!S.ch) loadChoices();
  else paint();
}
