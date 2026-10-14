/* 계절성 분석 — 금융 필수 지식 화면(화면 키 quant-seasonal) (2026-10-14)
 *
 * 무엇을 그리나(서버가 달 수익률 · 판정 · 문장 · 고르기 값을 짓고 이 파일은 그대로 그린다 — 계산 · 문장을 여기서 다시 하지 않는다):
 *   GET /api/seasonality?target=&basis=  (API-SEAS-01 · app/services/seasonality.py)
 *     코스피 · 코스닥(한국은행 ECOS 가격 지수 · 1995 · 2003 ~) 또는 종목(수집 시세로 만든 총수익 · 가격 지수 · 2020 ~)
 * 화면 꼴(Figma 「Qurious · 계절성 분석 · 종목 군집화」 03-1 · 사용자 2026-10-14 「A + B + C 탭」):
 *   요약 숫자 넷 → 달마다 평균 막대 + 오른 해 비율 선(안 B) → [해마다 표(안 A) | 한 해 흐름(안 C · 곡선)] 탭 →
 *   요일 · 산타 랠리 · 연말 · 반년 비교 → 읽는 법(서버 문장) → 알려진 계절성 효과 · 용어 풀이 → 고지 · 출처.
 *   안 B 의 달 카드 12장은 빼고, 표 맨 아래 세 줄(평균 · 오른 해 · 판정)이 대신한다 — 평균만 크게 보이면 「4월이 좋다」 로
 *   잘못 읽힌다(코스피 실측: 다른 달과 뚜렷이 다른 달 0개).
 * 옛 칸은 강사님 GET /api/ml/seasonality(야후 · 일간 수익률의 달별 평균)를 불렀다 — 이 화면은 그 길을 쓰지 않는다
 *   (`public/js/ml.js` 의 옛 단추 코드는 단추가 없으면 아무 일도 하지 않는다).
 * 고르기 값(대상 · 값)과 판정 글은 응답(choices · distinct_text · judge_text)에서만 읽는다 — TC-SES 화면 시험이 지킨다.
 * 색 — 국내 시세 표기대로 오름 빨강 · 내림 파랑. 차트: ApexCharts(app.html 이 이미 싣는 3.49.2).
 */
import { api, escHtml } from "/js/common.js";

const VIEW = "quant-seasonal";
const PREF_KEY = "se_pref_v1";
const UP = "#dc2626";
const DOWN = "#2563eb";
//: 해마다 표 칸 색이 가장 진해지는 달 수익률(%) — 넘는 칸도 같은 진하기(2026년 같은 ±30% 칸이 나머지를 옅게 만들지 않게)
const HEAT_FULL = 8;
//: 요일 막대 눈금의 바닥(%) — 다섯 요일이 모두 0 에 가까워도 막대가 화면 끝까지 부풀지 않게
const WEEKDAY_SCALE_FLOOR = 0.05;

const S = { q: null, d: null, err: "", hint: "", busy: false, tab: "table", note: "", stockMode: false };
let charts = [];
let suggestTimer = null;
//: 창 크기가 바뀌면 그림만 다시 — ApexCharts 자체 크기 맞춤은 끈다(크기를 바꾼 직후 탭을 누르면 미뤄 둔 맞춤이 지운 그림에
//: 돌아 「translate(NaN, 0)」 오류 · 2026-10-14 실측). 우리 타이머는 다시 그리기 전에 취소할 수 있다.
let resizeTimer = null;
const RESIZE_WAIT_MS = 200;

function root() { return document.querySelector(`.view[data-view="${VIEW}"] .se-root`); }
function pctSe(v, nd = 1) { return v == null ? "—" : `${v > 0 ? "+" : ""}${Number(v).toFixed(nd)}%`; }
function heat(v) {
  if (v == null) return "transparent";
  const a = (Math.min(1, Math.abs(v) / HEAT_FULL) * 0.85).toFixed(2);
  return v >= 0 ? `rgba(220,38,38,${a})` : `rgba(37,99,235,${a})`;
}
function ink(v) { return v != null && Math.abs(v) > HEAT_FULL * 0.6 ? "#fff" : "var(--text)"; }

function readPref() {
  try { const p = JSON.parse(localStorage.getItem(PREF_KEY) || "null"); return p && typeof p === "object" ? p : null; } catch { return null; }
}
function savePref(q) { try { localStorage.setItem(PREF_KEY, JSON.stringify(q)); } catch { /* 저장소를 못 쓰면 고른 값만 잊는다 */ } }

async function loadSeason(q, fromPref = false) {
  S.busy = true;
  S.err = "";
  S.hint = "";
  S.note = "";
  paint();
  const qs = q ? `?${new URLSearchParams({ target: q.target, basis: q.basis })}` : "";
  try {
    const d = await api(`/api/seasonality${qs}`);
    S.d = d;
    S.stockMode = d.target && d.target.kind === "stock";
    // 고른 값(basis)은 사용자가 누른 것 — 시장 지수는 서버가 가격으로 셈을 바꾸고 basis_note 로 알리지만, 종목으로 옮기면
    // 다시 고른 값으로 부른다. 처음 부름의 기본은 응답 choices 의 첫 칸(서버 기본과 같은 차례)
    S.q = { target: d.target.code, basis: q && q.basis ? q.basis : d.choices.bases[0].key };
    if (d.available) savePref(S.q);
  } catch (e) {
    if (fromPref && e && (e.status === 422 || e.status === 404)) {
      // 저장해 둔 고르기 값을 지금은 쓸 수 없다 — 말없이 바꾸지 않고 기본으로 다시 부른 사실을 알린다
      try { localStorage.removeItem(PREF_KEY); } catch { /* 저장소를 못 쓰면 그대로 */ }
      S.busy = false;
      await loadSeason(null);
      S.note = "지난번에 고른 대상을 지금은 쓸 수 없어 기본 대상으로 다시 불렀습니다.";
      paint();
      return;
    }
    S.err = e && e.message ? e.message : "불러오지 못했습니다.";
    S.hint = e && e.detail && e.detail.admin_hint ? e.detail.admin_hint : "";
  } finally {
    S.busy = false;
    paint();
  }
}

// ── 고르기 · 요약 ─────────────────────────────────────────────────────
function segHtml(name, items, cur) {
  return `<div class="se-seg" role="group">${items.map(it => `<button type="button" class="${String(it.key) === String(cur) ? "on" : ""}"
    data-q="${name}" data-v="${escHtml(String(it.key))}" aria-pressed="${String(it.key) === String(cur)}">${escHtml(it.label)}</button>`).join("")}</div>`;
}

function controlsHtml(d) {
  const ch = d.choices;
  const tgt = d.target || {};
  const curTarget = S.stockMode ? "__stock" : tgt.code;
  const targets = [...ch.markets, { key: "__stock", label: ch.stock.label }];
  const search = S.stockMode ? `<div class="se-find">
      <input type="search" class="se-search" placeholder="${escHtml(ch.stock.placeholder)}" aria-label="${escHtml(ch.stock.placeholder)}" autocomplete="off"
        value="" />
      <ul class="se-suggest" role="listbox" hidden></ul>
      ${tgt.kind === "stock" ? `<span class="se-picked">${escHtml(tgt.name)} <small>${escHtml(tgt.code)}</small></span>` : ""}
    </div>` : "";
  return `<div class="se-bar">
    <span class="se-lbl">대상</span>${segHtml("target", targets, curTarget)}${search}
    <span class="se-lbl">값</span>${segHtml("basis", ch.bases, d.basis)}
  </div>`;
}

function kpiHtml(d) {
  const seen = d.by_month.filter(m => m.n);
  const best = seen.length ? seen.reduce((a, b) => (b.mean > a.mean ? b : a)) : null;
  const worst = seen.length ? seen.reduce((a, b) => (b.mean < a.mean ? b : a)) : null;
  const judged = d.by_month.some(m => m.distinct !== null);
  const nDistinct = d.by_month.filter(m => m.distinct).length;
  return `<div class="se-kpi">
    <div><span>기간</span><b>${escHtml(d.span.text)}</b></div>
    <div><span>가장 높은 달(평균)</span><b>${best ? `${escHtml(best.label)} ${pctSe(best.mean)}` : "—"}</b></div>
    <div><span>가장 낮은 달(평균)</span><b>${worst ? `${escHtml(worst.label)} ${pctSe(worst.mean)}` : "—"}</b></div>
    <div><span>다른 달과 뚜렷이 다른 달</span><b>${judged ? `${nDistinct}개` : escHtml(d.by_month[0].distinct_text)}</b></div>
  </div>`;
}

// ── 해마다 표(안 A) ─────────────────────────────────────────────────────
function tableHtml(d) {
  const labels = d.by_month.map(m => m.label);
  const rows = d.matrix.slice().reverse().map(r => `<tr><th scope="row">${r.year}</th>${r.months.map((v, i) =>
    `<td style="background:${heat(v)};color:${ink(v)}" ${v == null ? "" : `title="${r.year}년 ${escHtml(labels[i])} ${pctSe(v)}"`}>${v == null ? "" : Number(v).toFixed(1)}</td>`).join("")}</tr>`).join("");
  return `<div class="se-tbl-wrap"><table class="se-tbl" aria-label="해마다 달 수익률(%)">
      <thead><tr><th scope="col">해</th>${labels.map(l => `<th scope="col">${escHtml(l)}</th>`).join("")}</tr></thead>
      <tbody>${rows}</tbody>
      <tfoot>
        <tr><th scope="row">평균</th>${d.by_month.map(m => `<td>${m.mean == null ? "" : Number(m.mean).toFixed(1)}</td>`).join("")}</tr>
        <tr><th scope="row">오른 해</th>${d.by_month.map(m => `<td>${m.n ? `${m.up}/${m.n}` : ""}</td>`).join("")}</tr>
        <tr class="se-judge"><th scope="row">판정</th>${d.by_month.map(m => `<td class="${m.distinct ? "on" : ""}">${escHtml(m.distinct_text)}</td>`).join("")}</tr>
      </tfoot>
    </table></div>
    <p class="se-note">칸 = ${escHtml(d.definitions.month_return)} · 빨강은 오름 · 파랑은 내림 · 진할수록 큼(±${HEAT_FULL}% 넘으면 같은 진하기) · 맨 아래 세 줄은 늘 보입니다</p>`;
}

// ── 한 해 흐름(안 C) ────────────────────────────────────────────────────
function curveHtml(d) {
  const cy = d.curves.current_year;
  const nMean = Math.max(...d.curves.n);
  return `<div class="se-line" id="se-line"></div>
    <p class="se-note">옅은 선 = 지난 해마다 · 진한 선 = 평균(1월 값이 있는 ${nMean}해) · 빨간 선 = ${cy}년 · ${escHtml(d.definitions.curve)}</p>`;
}

// ── 요일 · 산타 · 연말 · 반년 ───────────────────────────────────────────
function weekdayHtml(d) {
  const top = Math.max(WEEKDAY_SCALE_FLOOR, ...d.weekday.map(w => Math.abs(w.mean || 0))) * 1.15;
  return `<section class="se-card"><h3>요일별 하루 평균</h3>
    ${d.weekday.map(w => {
      const W = Math.min(50, Math.abs(w.mean || 0) / top * 50);
      return `<div class="se-wk" title="${escHtml(w.label)}요일 · 관측 ${w.n}일 · 오른 날 ${w.hit_rate == null ? "—" : w.hit_rate + "%"} · ${escHtml(w.distinct_text)}">
        <span>${escHtml(w.label)}</span>
        <div class="se-track"><i style="${(w.mean || 0) >= 0 ? "left:50%" : "right:50%"};width:${W.toFixed(1)}%;background:${(w.mean || 0) >= 0 ? UP : DOWN}"></i><b></b></div>
        <span class="se-num">${pctSe(w.mean, 2)}</span></div>`;
    }).join("")}
    <p class="se-note">${escHtml(d.definitions.weekday_return)} · 판정: ${d.weekday.map(w => `${escHtml(w.label)} ${escHtml(w.distinct_text)}`).join(" · ")}</p></section>`;
}

function santaHtml(d) {
  const s = d.windows.santa;
  const top = Math.max(1, ...s.years.map(y => Math.abs(y.ret)));
  return `<section class="se-card"><h3>산타 랠리 창</h3>
    <p class="se-note">${escHtml(d.definitions.santa)}</p>
    <div class="se-kpi se-kpi-sm">
      <div><span>오른 해</span><b>${s.stats.n ? `${s.stats.up} / ${s.stats.n}` : "—"}</b></div>
      <div><span>창 평균</span><b>${pctSe(s.stats.mean, 2)}</b></div>
      <div><span>아무 ${s.baseline.days}거래일 평균</span><b>${pctSe(s.baseline.mean, 2)}</b></div>
    </div>
    <div class="se-santa" aria-label="해마다 산타 랠리 창 수익률">${s.years.map(y =>
      `<i title="${y.year}년 ${pctSe(y.ret, 2)}" style="height:${(4 + Math.abs(y.ret) / top * 56).toFixed(0)}px;background:${y.ret >= 0 ? UP : DOWN}"></i>`).join("")}</div>
    <p class="se-note">${s.years.length ? `${s.years[0].year} ~ ${s.years[s.years.length - 1].year} · 막대에 마우스를 올리면 그해 값` : "아직 창이 한 번도 끝나지 않았습니다"} · ${escHtml(d.definitions.baseline)}</p></section>`;
}

function compareRow(title, defn, a, aLab, b, bLab, c) {
  return `<div class="se-cmp"><h4>${escHtml(title)}</h4>
    <div class="se-cmp-nums"><div><span>${escHtml(aLab)}</span><b>${pctSe(a, 2)}</b></div><div><span>${escHtml(bLab)}</span><b>${pctSe(b, 2)}</b></div>
      <div><span>차이</span><b>${c.diff == null ? "—" : `${c.diff > 0 ? "+" : ""}${Number(c.diff).toFixed(2)}%p`}</b></div></div>
    <p class="se-badge ${c.p_value != null && c.p_value < S.d.thresholds.alpha ? "on" : ""}">${escHtml(c.judge_text)}${c.p_value == null ? "" : ` · p ${Number(c.p_value).toFixed(3)}`}</p>
    <p class="se-note">${escHtml(defn)}</p></div>`;
}

function compareHtml(d) {
  const ye = d.windows.year_end;
  const hv = d.windows.halves;
  return `<section class="se-card"><h3>연말 · 반년 비교</h3>
    ${compareRow("연말 두 달", d.definitions.year_end, ye.mean, "11 · 12월", ye.other_mean, "나머지 달", ye)}
    ${compareRow("반년 비교", d.definitions.halves, hv.winter_mean, "11 ~ 4월", hv.summer_mean, "5 ~ 10월", hv)}
    <p class="se-note">달 평균 · ${escHtml(d.definitions.judge)}</p></section>`;
}

// ── 알려진 효과 · 용어 ─────────────────────────────────────────────────
//: 교과서에 나오는 계절성 넷 — 처음 관찰된 곳 · 이 화면에서 확인하는 칸(값은 서버 응답 · 여기 글은 길잡이만)
const EFFECTS = [
  ["1월 효과", "미국 자료에서 1월 수익률, 특히 작은 회사 주식이 높았다는 관찰입니다(Rozeff · Kinney 1976 · Keim 1983). 연말에 손실 종목을 팔아 세금을 줄이고 1월에 되사는 흐름이 까닭으로 꼽힙니다.", "해마다 표의 1월 열 · 맨 아래 판정"],
  ["5월에 팔고 떠나라(핼러윈 효과)", "11 ~ 4월이 5 ~ 10월보다 수익률이 높았다는 관찰입니다(Bouman · Jacobsen 2002 · 여러 나라 자료).", "연말 · 반년 비교의 「반년 비교」"],
  ["월요일 효과", "주말을 건넌 월요일 수익률이 낮았다는 관찰입니다(French 1980). 1990년대 뒤 자료에서는 약해졌다는 보고가 많습니다.", "요일별 하루 평균"],
  ["산타 랠리", "12월 마지막 5거래일과 1월 첫 2거래일에 오른다는 관찰입니다(Yale Hirsch 「Stock Trader's Almanac」 1972).", "산타 랠리 창"],
];

function effectsHtml() {
  return `<details class="se-defs"><summary>알려진 계절성 효과 — 이 화면에서 확인하기</summary><dl>${EFFECTS.map(([t, body, where]) =>
    `<dt>${escHtml(t)}</dt><dd>${escHtml(body)} <span class="se-where">→ ${escHtml(where)}</span></dd>`).join("")}</dl>
    <p class="se-note">처음 관찰된 시장과 기간이 우리 시장 · 지금과 다를 수 있습니다 — 그래서 위 숫자를 우리 자료로 다시 셌습니다.</p></details>`;
}

function defsHtml(d) {
  const lab = { month_return: "달 수익률", weekday_return: "요일 수익률", distinct: "뚜렷한 달(요일)", santa: "산타 랠리 창",
    baseline: "견줄 기준", year_end: "연말 두 달", halves: "반년 비교", curve: "한 해 흐름", judge: "차이 판정" };
  return `<details class="se-defs"><summary>용어 풀이</summary><dl>${Object.entries(d.definitions).map(([k, v]) =>
    `<dt>${escHtml(lab[k] || k)}</dt><dd>${escHtml(v)}</dd>`).join("")}</dl></details>`;
}

// ── 그리기 ─────────────────────────────────────────────────────────────
function dropCharts() {
  clearTimeout(resizeTimer);
  charts.forEach(c => { try { c.destroy(); } catch { /* 이미 사라진 그림 */ } });
  charts = [];
}

function onResizeSe() {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    const el = root();
    if (!el || el.offsetParent === null || !S.d || !S.d.available) return;   // 다른 화면이면 그리지 않는다(돌아올 때 다시 그린다)
    dropCharts();
    drawCharts(S.d);
  }, RESIZE_WAIT_MS);
}

function paint() {
  const el = root();
  if (!el) return;
  dropCharts();
  const d = S.d;
  const head = `<header class="se-head"><h2>계절성 분석</h2>
    <p>달 · 요일 · 연말에 값이 어떻게 움직였는지 지난 기록으로 봅니다${d && d.as_of ? ` · 기준일 ${escHtml(d.as_of)}` : ""}</p></header>`;
  const busy = S.busy ? `<div class="se-busy" role="status">세는 중입니다…</div>` : "";
  const err = (S.err ? `<div class="se-card se-state" role="alert">${escHtml(S.err)}${S.hint ? `<div class="se-admin">${escHtml(S.hint)}</div>` : ""}</div>` : "")
    + (S.note ? `<div class="se-note se-notice" role="status">${escHtml(S.note)}</div>` : "");
  if (!d) {
    el.innerHTML = `${head}${busy}${err}${S.err ? "" : `<div class="se-card se-state">불러오는 중입니다…</div>`}`;
    return;
  }
  if (!d.available) {
    el.innerHTML = `${head}${controlsHtml(d)}${busy}${err}<div class="se-card se-state">${escHtml(d.reason)}${d.admin_hint ? `<div class="se-admin">${escHtml(d.admin_hint)}</div>` : ""}</div>
      <p class="se-note">${escHtml(d.notice)} · 출처: ${escHtml(d.source)}</p>`;
    bindSearch(el);
    return;
  }
  const tabs = [["table", "해마다 표"], ["curve", "한 해 흐름"]];
  el.innerHTML = `${head}${controlsHtml(d)}
    ${d.basis_note ? `<p class="se-note">${escHtml(d.basis_note)}</p>` : ""}
    ${busy}${err}${kpiHtml(d)}
    <section class="se-card"><h3>달마다 평균 수익률과 오른 해 비율</h3>
      <p class="se-note">막대 = 그달의 해마다 달 수익률 평균(빨강 오름 · 파랑 내림) · 선 = 그달에 오른 해의 비율 · 막대에 마우스를 올리면 가운데 값 · 판정</p>
      <div class="se-bars" id="se-bar"></div></section>
    <div class="se-tabs" role="tablist">${tabs.map(([k, t]) => `<button type="button" role="tab" aria-selected="${S.tab === k}" class="${S.tab === k ? "on" : ""}" data-tab="${k}">${t}</button>`).join("")}</div>
    <section class="se-card se-panel">${S.tab === "curve" ? curveHtml(d) : tableHtml(d)}</section>
    <div class="se-trio">${weekdayHtml(d)}${santaHtml(d)}${compareHtml(d)}</div>
    <section class="se-card"><h3>읽는 법</h3><ul class="se-say">${d.sentences.map(s => `<li>${escHtml(s)}</li>`).join("")}</ul></section>
    ${effectsHtml()}${defsHtml(d)}
    <p class="se-note">${escHtml(d.notice)} · 출처: ${escHtml(d.source)}</p>`;
  bindSearch(el);
  requestAnimationFrame(() => drawCharts(d));
}

function drawCharts(d) {
  if (!window.ApexCharts) return;   // 그림 도구가 없으면 표 · 숫자 · 문장만(화면은 그대로 쓸 수 있다)
  const barEl = document.getElementById("se-bar");
  if (barEl) {
    const ms = d.by_month;
    const ch = new ApexCharts(barEl, {
      chart: { type: "line", height: barEl.clientWidth < 520 ? 240 : 280, toolbar: { show: false }, animations: { enabled: false }, zoom: { enabled: false },
        redrawOnWindowResize: false, redrawOnParentResize: false },
      series: [{ name: "평균 수익률(%)", type: "column", data: ms.map(m => m.mean) }, { name: "오른 해 비율(%)", type: "line", data: ms.map(m => m.hit_rate) }],
      xaxis: { categories: ms.map(m => m.label), tooltip: { enabled: false } },
      // 축 제목은 두지 않는다 — 좁은 폭에서 세로 글자가 뭉개진다(2026-10-14 실측) · 범례가 같은 말을 한다
      yaxis: [{ labels: { formatter: v => (v == null ? "" : `${v.toFixed(1)}%`) } },
        { opposite: true, min: 0, max: 100, labels: { formatter: v => (v == null ? "" : `${v.toFixed(0)}%`) } }],
      colors: ["#64748b", "#d97706"], stroke: { width: [0, 2] }, markers: { size: [0, 3] }, dataLabels: { enabled: false }, legend: { position: "top" },
      plotOptions: { bar: { columnWidth: "55%", colors: { ranges: [{ from: -1000, to: 0, color: DOWN }, { from: 0, to: 1000, color: UP }] } } },
      tooltip: { shared: true, custom: ({ dataPointIndex }) => { const m = ms[dataPointIndex]; if (!m) return "";
        return `<div class="se-tip"><b>${escHtml(m.label)}</b> · ${m.n}해<br>평균 ${pctSe(m.mean, 2)} · 가운데 ${pctSe(m.median, 2)}<br>오른 해 ${m.up}/${m.n}${m.best ? `<br>가장 좋았던 해 ${m.best.year} ${pctSe(m.best.ret)} · 가장 나빴던 해 ${m.worst.year} ${pctSe(m.worst.ret)}` : ""}<br>판정: ${escHtml(m.distinct_text)}</div>`; } },
    });
    ch.render();
    charts.push(ch);
  }
  const lineEl = document.getElementById("se-line");
  if (lineEl) {
    const labels = d.by_month.map(m => m.label);
    const cy = d.curves.current_year;
    const past = d.curves.years.filter(y => y.year !== cy);
    const cur = d.curves.years.find(y => y.year === cy);
    const series = [...past.map(y => ({ name: `${y.year}년`, data: y.path })), { name: "평균", data: d.curves.mean },
      ...(cur ? [{ name: `${cy}년`, data: cur.path }] : [])];
    const ch = new ApexCharts(lineEl, {
      chart: { type: "line", height: lineEl.clientWidth < 520 ? 300 : 380, toolbar: { show: false }, animations: { enabled: false }, zoom: { enabled: false },
        redrawOnWindowResize: false, redrawOnParentResize: false },
      series, xaxis: { categories: labels, tooltip: { enabled: false } }, yaxis: { labels: { formatter: v => (v == null ? "" : `${v.toFixed(0)}%`) } },
      colors: [...past.map(() => "#cbd5e1"), "#0f172a", ...(cur ? [UP] : [])],
      stroke: { width: [...past.map(() => 1), 3, ...(cur ? [3] : [])], curve: "straight" },
      legend: { show: false }, dataLabels: { enabled: false }, markers: { size: 0, hover: { size: 4 } },
      tooltip: { shared: false, intersect: false, custom: ({ seriesIndex, dataPointIndex, w }) => {
        const s = w.config.series[seriesIndex]; const v = s && s.data[dataPointIndex];
        return v == null ? "" : `<div class="se-tip"><b>${escHtml(s.name)}</b> · ${escHtml(labels[dataPointIndex])}까지 ${pctSe(v)}</div>`; } },
    });
    ch.render();
    charts.push(ch);
  }
}

// ── 종목 찾기 — 이름 · 코드로 국내 종목(6자리)만(재무 · 신용 위험 화면과 같은 길) ─────────────────
function bindSearch(el) {
  const input = el.querySelector(".se-search");
  if (!input) return;
  if (S.stockMode && !(S.d && S.d.target && S.d.target.kind === "stock")) input.focus();
  input.addEventListener("input", () => { clearTimeout(suggestTimer); suggestTimer = setTimeout(() => suggestSe(input), 250); });
  input.addEventListener("keydown", ev => {
    if (ev.key !== "Enter") return;
    const q = input.value.trim();
    if (/^\d{6}$/.test(q)) { ev.preventDefault(); loadSeason({ target: q, basis: S.q ? S.q.basis : "" }); }
  });
}

async function suggestSe(input) {
  const list = root()?.querySelector(".se-suggest");
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
  list.innerHTML = rows === null ? `<li class="se-muted">찾기가 지금 되지 않습니다 — 6자리 종목코드를 넣고 Enter</li>`
    : rows.length ? rows.map(x => `<li role="option" tabindex="-1" data-code="${escHtml(x.code)}"><strong>${escHtml(x.name)}</strong> <span class="se-muted">${escHtml(x.code)}</span></li>`).join("")
      : `<li class="se-muted">국내 상장 종목에서 찾지 못했습니다</li>`;
  list.hidden = false;
}

function onClickSe(ev) {
  const li = ev.target.closest(".se-suggest li[data-code]");
  if (li && root() && root().contains(li) && !S.busy) { loadSeason({ target: li.dataset.code, basis: S.q ? S.q.basis : "" }); return; }
  const t = ev.target.closest("button");
  if (!t || !root() || !root().contains(t)) return;
  if (t.dataset.tab) { S.tab = t.dataset.tab; paint(); return; }
  // 「종목」 은 찾기 칸만 연다(부르지 않는다) — 불러오는 중에도 눌리게
  if (t.dataset.q === "target" && t.dataset.v === "__stock" && S.d) { S.stockMode = true; paint(); return; }
  if (!t.dataset.q || S.busy || !S.d) return;
  if (t.dataset.q === "target") {
    loadSeason({ target: t.dataset.v, basis: S.q ? S.q.basis : "" });
    return;
  }
  if (t.dataset.q === "basis" && S.d.target) {
    loadSeason({ target: S.d.target.code, basis: t.dataset.v });
  }
}

let wired = false;
export function onSeasonalViewActivated(view) {
  if (view !== "quant-seasonal") return;   // 글자 그대로 — 화면 스캐너(scripts/view_scan.py)가 이 모양으로 진입 훅을 읽는다
  const el = root();
  if (!el) return;
  if (!wired) {
    el.addEventListener("click", onClickSe);
    window.addEventListener("resize", onResizeSe);
    wired = true;
  }
  if (!S.d && !S.busy) { const pref = readPref(); loadSeason(pref, !!pref); }
  else paint();
}
