/* 종목 군집화 — ML·딥러닝 화면(화면 키 ml-cluster) (2026-10-14)
 *
 * 무엇을 그리나(서버가 묶음 · 지도 좌표 · 낱말 · 문장 · 고르기 값을 짓고 이 파일은 그대로 그린다 — 문장을 여기서 다시 짓지 않는다):
 *   GET /api/clusters?universe=&period=&method=&k=  (API-CLUS-01 · app/services/stock_clusters.py)
 *     같이 움직인 묶음(시장 몫을 뺀 일간 수익률 상관 · Ward 계층 군집) 또는 위험 · 수익 특성 묶음(KMeans) · 실루엣으로 묶음 수
 * 화면 꼴(Figma 「Qurious · 계절성 분석 · 종목 군집화」 05 [결정] · 사용자 2026-10-14): 안 A(종목 지도) + 안 B(묶음 카드) 융합.
 *   위 — 종목 지도(이름은 겹치지 않게 묶음마다 가운데에 가까운 몇만 · 나머지는 점에 마우스를 올리면) ·
 *   아래 — 묶음 카드(특징 낱말 · 네 숫자 막대 · 종목 칩) · 31종목처럼 작은 대상일 때만 「같이 움직인 정도」(상관 표) 탭.
 * 옛 칸은 강사님 POST /api/ml/cluster 를 불렀는데 본문을 두 번 JSON 으로 바꿔 늘 422 였다(DF-108 · 2026-10-14 실측) —
 *   이 화면은 그 길을 쓰지 않는다.
 * 고르기 값(대상 · 기간 · 방법 · 묶음 수)과 기준값은 응답(choices · thresholds)에서만 읽는다 — 화면에 따로 적으면 서버를 고칠 때
 *   한쪽만 바뀐다(S110 규칙 · TC-CUS 화면 시험이 지킨다). 처음 부름은 값 없이 — 기본은 서버가 정한다.
 * 색 — 묶음 색은 구분용일 뿐 좋음 · 나쁨이 아니다(빨강이 「위험」 으로 읽히지 않게 범례 낱말로 묶음 번호를 함께 쓴다).
 * 차트: ApexCharts(app.html 이 이미 싣는 3.49.2) — 흩어진 점 · 막대. 강사님 파일(app.html · main.js · core.js)에는 뿌리 칸 ·
 *   부르는 줄 · 도움말 글만 둔다.
 */
import { api, escHtml } from "/js/common.js";

const VIEW = "ml-cluster";
const PAL = ["#2563eb", "#dc2626", "#16a34a", "#d97706", "#7c3aed", "#0891b2", "#db2777", "#4b5563"];
const PREF_KEY = "cu_pref_v1";
//: 묶음 카드에 먼저 보이는 종목 칩 수 — 넘치면 「외 n종목 더 보기」
const MEMBERS_SHOWN = 24;
//: 지도에 이름을 붙이는 수 — 묶음마다 가운데에 가까운 종목(이름이 겹치지 않게 · 나머지는 마우스를 올리면)
const LABELS_PER_CLUSTER = 2;

const S = { q: null, d: null, err: "", busy: false, tab: "cards", open: {} };
let charts = [];
//: 창 크기가 바뀌면 그림만 다시 — ApexCharts 자체 크기 맞춤은 끈다(크기를 바꾼 직후 탭 · 고르기를 누르면 미뤄 둔 맞춤이
//: 지운 그림에 돌아 「translate(NaN, 0)」 오류 · 2026-10-14 실측). 우리 타이머는 다시 그리기 전에 취소할 수 있다.
let resizeTimer = null;
const RESIZE_WAIT_MS = 200;

function root() { return document.querySelector(`.view[data-view="${VIEW}"] .cu-root`); }
function col(id) { return PAL[(id - 1) % PAL.length]; }
function pctCu(v, nd = 1) { return v == null ? "—" : `${v > 0 ? "+" : ""}${Number(v).toFixed(nd)}%`; }

function readPref() {
  try { const p = JSON.parse(localStorage.getItem(PREF_KEY) || "null"); return p && typeof p === "object" ? p : null; } catch { return null; }
}
function savePref(q) { try { localStorage.setItem(PREF_KEY, JSON.stringify(q)); } catch { /* 저장소를 못 쓰면 고른 값만 잊는다 */ } }

async function loadClusters(q, fromPref = false) {
  S.busy = true;
  S.err = "";
  S.note = "";
  paint();
  const qs = q ? `?${new URLSearchParams({ universe: q.universe, period: q.period, method: q.method, k: String(q.k || 0) })}` : "";
  try {
    const d = await api(`/api/clusters${qs}`);
    S.d = d;
    if (d.available) {
      S.q = { universe: d.universe.key, period: d.period.key, method: d.method.key, k: d.k_auto ? 0 : d.k };
      savePref(S.q);
    } else {
      S.q = q || S.q;
    }
    if (S.tab === "matrix" && !(d.matrix)) S.tab = "cards";
  } catch (e) {
    if (fromPref && e && e.status === 422) {
      // 저장해 둔 고르기 값이 지금 서버 규칙과 맞지 않는다 — 말없이 바꾸지 않고 기본으로 다시 부른 사실을 알린다
      try { localStorage.removeItem(PREF_KEY); } catch { /* 저장소를 못 쓰면 그대로 */ }
      S.busy = false;
      await loadClusters(null);
      S.note = "지난번에 고른 값을 지금은 쓸 수 없어 기본 값으로 다시 불렀습니다.";
      paint();
      return;
    }
    S.err = e && e.message ? e.message : "불러오지 못했습니다.";
  } finally {
    S.busy = false;
    paint();
  }
}

function segHtml(name, items, cur) {
  return `<div class="cu-seg" role="group">${items.map(it => `<button type="button" class="${String(it.key) === String(cur) ? "on" : ""}"
    data-q="${name}" data-v="${escHtml(String(it.key))}" aria-pressed="${String(it.key) === String(cur)}">${escHtml(it.label)}</button>`).join("")}</div>`;
}

function controlsHtml(d) {
  const ch = d.choices;
  const q = S.q || {};
  const kItems = [{ key: 0, label: d.available && d.k_auto ? `자동(${d.k})` : "자동" }, ...ch.k.map(k => ({ key: k, label: String(k) }))];
  return `<div class="cu-bar">
    <span class="cu-lbl">대상</span>${segHtml("universe", ch.universe, q.universe)}
    <span class="cu-lbl">기간</span>${segHtml("period", ch.period, q.period)}
    <span class="cu-lbl">묶는 법</span>${segHtml("method", ch.method, q.method)}
    <span class="cu-lbl">묶음 수</span>
    <select class="cu-k" data-q="k" aria-label="묶음 수">${kItems.map(it => `<option value="${it.key}" ${Number(q.k || 0) === Number(it.key) ? "selected" : ""}>${escHtml(it.label)}</option>`).join("")}</select>
  </div>`;
}

function kpiHtml(d) {
  const sep = d.separation || {};
  return `<div class="cu-kpi">
    <div><span>묶은 종목</span><b>${d.points.length}</b></div>
    <div><span>묶음</span><b>${d.k}개</b></div>
    <div><span>같은 묶음끼리 평균 상관</span><b>${sep.within == null ? "—" : sep.within.toFixed(2)}</b></div>
    <div><span>다른 묶음끼리 평균 상관</span><b>${sep.between == null ? "—" : sep.between.toFixed(2)}</b></div>
    <div><span>실루엣</span><b>${d.silhouette_mean.toFixed(2)}</b></div>
  </div>`;
}

function rangeOf(d, key) {
  const vs = d.points.map(p => p[key]).filter(v => v != null);
  return vs.length ? [Math.min(...vs), Math.max(...vs)] : [0, 1];
}

function metricHtml(d, label, key, v, fmtFn) {
  const [lo, hi] = rangeOf(d, key);
  const w = v == null ? 0 : hi > lo ? (v - lo) / (hi - lo) * 100 : 50;
  return `<div class="cu-met"><span>${label}</span><div class="cu-track" title="대상 종목 안에서의 자리"><div class="cu-fill" style="width:${Math.max(3, w).toFixed(1)}%"></div></div><span class="cu-num">${fmtFn(v)}</span></div>`;
}

function cardHtml(d, c) {
  const open = !!S.open[c.id];
  const shown = open ? c.members : c.members.slice(0, MEMBERS_SHOWN);
  const more = c.members.length - shown.length;
  return `<article class="cu-card" style="--cu-c:${col(c.id)}" data-cluster="${c.id}">
    <h3><span class="cu-dot" aria-hidden="true"></span>묶음 ${c.id} <small>${c.size}종목</small></h3>
    <div class="cu-words">${c.words.map(w => `<span>${escHtml(w)}</span>`).join("")}</div>
    ${metricHtml(d, "연 수익률", "ret", c.summary.ret, pctCu)}
    ${metricHtml(d, "변동성", "vol", c.summary.vol, pctCu)}
    ${metricHtml(d, "시장 민감도", "beta", c.summary.beta, v => (v == null ? "—" : Number(v).toFixed(2)))}
    ${metricHtml(d, "최대 낙폭", "mdd", c.summary.mdd, pctCu)}
    ${c.summary.corr_in != null ? `<div class="cu-note">묶음 안 평균 상관 ${c.summary.corr_in.toFixed(2)}</div>` : ""}
    <div class="cu-chips">${shown.map(m => `<span class="cu-chip">${escHtml(m.name)}${m.sector ? `<em>${escHtml(m.sector)}</em>` : ""}</span>`).join("")}
      ${more > 0 ? `<button type="button" class="cu-more" data-more="${c.id}">외 ${more}종목 더 보기</button>` : ""}
      ${open && c.members.length > MEMBERS_SHOWN ? `<button type="button" class="cu-more" data-more="${c.id}">접기</button>` : ""}</div>
  </article>`;
}

function matrixHtml(d) {
  const mx = d.matrix;
  if (!mx) return "";
  const name = Object.fromEntries(d.points.map(p => [p.code, p.name]));
  const lab = Object.fromEntries(d.points.map(p => [p.code, p.cluster]));
  const cell = v => `<td style="background:rgba(220,38,38,${(Math.max(0, Math.min(1, v)) * 0.9).toFixed(2)})" title="${v.toFixed(2)}"></td>`;
  return `<div class="cu-mx-wrap"><table class="cu-mx" aria-label="같이 움직인 정도(상관)">
    <thead><tr><th></th>${mx.order.map(c => `<th scope="col" style="color:${col(lab[c])}"><span>${escHtml(name[c])}</span></th>`).join("")}</tr></thead>
    <tbody>${mx.order.map((a, i) => `<tr><th scope="row" style="color:${col(lab[a])}">${escHtml(name[a])}</th>${mx.values[i].map(cell).join("")}</tr>`).join("")}</tbody>
  </table></div>
  <p class="cu-note">진할수록 날마다의 수익률이 같이 오르내렸습니다 · 묶음 차례로 놓아 같은 묶음이 대각선 둘레에 네모로 모입니다</p>`;
}

function defsHtml(d) {
  const lab = { movement: "같이 움직임", profile: "위험 · 수익 특성", silhouette: "실루엣", map: "종목 지도", coverage: "빠지는 종목", ari: "업종과 같은 정도" };
  return `<details class="cu-defs"><summary>용어 풀이</summary><dl>${Object.entries(d.definitions).map(([k, v]) =>
    `<dt>${escHtml(lab[k] || k)}</dt><dd>${escHtml(v)}</dd>`).join("")}</dl></details>`;
}

function excludedHtml(d) {
  if (!d.excluded || !d.excluded.length) return "";
  return `<details class="cu-excl"><summary>자료가 모자라 뺀 종목 ${d.excluded.length}</summary><ul>${d.excluded.map(e =>
    `<li>${escHtml(e.name || e.code)} <span class="cu-note">${escHtml(e.reason)}</span></li>`).join("")}</ul></details>`;
}

function dropCharts() {
  clearTimeout(resizeTimer);
  charts.forEach(c => { try { c.destroy(); } catch { /* 이미 사라진 그림 */ } });
  charts = [];
}

function onResizeCu() {
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
  const head = `<header class="cu-head"><h2>종목 군집화</h2>
    <p>지난 기간에 서로 비슷하게 움직인 종목끼리 묶어 봅니다${d && d.as_of ? ` · 기준일 ${escHtml(d.as_of)}` : ""}</p></header>`;
  if (!d) {
    el.innerHTML = `${head}<div class="cu-card cu-state">${S.err ? escHtml(S.err) : "묶는 중입니다…"}</div>`;
    return;
  }
  const busy = S.busy ? `<div class="cu-busy" role="status">묶는 중입니다… 종목이 많으면 몇 초 걸립니다</div>` : "";
  const err = (S.err ? `<div class="cu-card cu-state" role="alert">${escHtml(S.err)}</div>` : "")
    + (S.note ? `<div class="cu-note cu-notice" role="status">${escHtml(S.note)}</div>` : "");
  if (!d.available) {
    el.innerHTML = `${head}${controlsHtml(d)}${busy}${err}<div class="cu-card cu-state">${escHtml(d.reason)}${d.admin_hint ? `<div class="cu-admin">${escHtml(d.admin_hint)}</div>` : ""}</div>
      ${excludedHtml(d)}<p class="cu-note">${escHtml(d.notice)}</p>`;
    return;
  }
  const tabs = [["cards", "묶음"], ...(d.matrix ? [["matrix", "같이 움직인 정도"]] : [])];
  const panel = S.tab === "matrix" && d.matrix ? matrixHtml(d) : `<div class="cu-cards">${d.clusters.map(c => cardHtml(d, c)).join("")}</div>`;
  el.innerHTML = `${head}${controlsHtml(d)}${busy}${err}${kpiHtml(d)}
    <div class="cu-grid">
      <section class="cu-card cu-mapcard"><h3>종목 지도</h3>
        <p class="cu-note">점 사이가 가까울수록 지난 기간에 비슷하게 움직였습니다 · 색은 묶음 · 점에 마우스를 올리면 이름과 가장 같이 움직인 종목</p>
        <div class="cu-map" id="cu-map"></div></section>
      <section class="cu-card cu-why"><h3>묶음 수를 고른 까닭</h3>
        <p class="cu-note">묶음 수마다 실루엣(자기 묶음과는 가깝고 다른 묶음과는 먼 정도)을 셌습니다</p><div id="cu-k"></div>
        <ul class="cu-say">${d.sentences.map(s => `<li>${escHtml(s)}</li>`).join("")}</ul></section>
    </div>
    <div class="cu-tabs" role="tablist">${tabs.map(([k, t]) => `<button type="button" role="tab" aria-selected="${S.tab === k}" class="${S.tab === k ? "on" : ""}" data-tab="${k}">${t}</button>`).join("")}</div>
    ${panel}
    ${excludedHtml(d)}${defsHtml(d)}
    <p class="cu-note">${escHtml(d.notice)} · 출처: ${escHtml(d.source)}</p>`;
  requestAnimationFrame(() => drawCharts(d));
}

/** 이름을 붙일 점 — 묶음마다 가운데에 가까운 차례로 돌아가며 고르되, 이미 이름을 붙인 점과 화면 비율로 가까우면 건너뛴다
 *  (2026-10-14 구현 확인: 묶음마다 둘을 그냥 붙이면 가운데에 몰린 묶음들의 이름이 겹쳤다). 큰 대상(60 넘음)은 이름 없이 · 마우스로. */
function labelSet(d) {
  if (d.points.length > 60) return new Set();
  const xs = d.points.map(p => p.x);
  const ys = d.points.map(p => p.y);
  const xr = (Math.max(...xs) - Math.min(...xs)) || 1;
  const yr = (Math.max(...ys) - Math.min(...ys)) || 1;
  const queues = d.clusters.map(c => {
    const pts = d.points.filter(p => p.cluster === c.id);
    const cx = pts.reduce((s, p) => s + p.x, 0) / pts.length;
    const cy = pts.reduce((s, p) => s + p.y, 0) / pts.length;
    return pts.slice().sort((a, b) => ((a.x - cx) ** 2 + (a.y - cy) ** 2) - ((b.x - cx) ** 2 + (b.y - cy) ** 2));
  });
  const picked = [];
  for (let round = 0; round < LABELS_PER_CLUSTER; round++) {
    for (const q of queues) {
      const p = q[round];
      if (!p) continue;
      // 이름 상자 어림 — 가로는 지도 폭의 14%, 세로는 6% 안에 다른 이름이 있으면 붙이지 않는다
      if (picked.every(o => Math.abs(o.x - p.x) / xr > 0.14 || Math.abs(o.y - p.y) / yr > 0.06)) picked.push(p);
    }
  }
  return new Set(picked.map(p => p.code));
}

function drawCharts(d) {
  if (!window.ApexCharts) return;   // 그림 도구가 없으면 숫자 · 카드 · 문장만(화면은 그대로 쓸 수 있다)
  const mapEl = document.getElementById("cu-map");
  if (mapEl) {
    const named = labelSet(d);
    const series = d.clusters.map(c => ({ name: `묶음 ${c.id}`, data: d.points.filter(p => p.cluster === c.id).map(p => ({ x: p.x, y: p.y, p })) }));
    const ch = new ApexCharts(mapEl, {
      chart: { type: "scatter", height: mapEl.clientWidth < 520 ? 340 : 440, toolbar: { show: false }, animations: { enabled: false }, zoom: { enabled: false },
        redrawOnWindowResize: false, redrawOnParentResize: false },
      series, colors: d.clusters.map(c => col(c.id)), markers: { size: d.points.length > 60 ? 4 : 7 },
      dataLabels: { enabled: named.size > 0, formatter: (v, o) => { const p = o.w.config.series[o.seriesIndex].data[o.dataPointIndex].p; return named.has(p.code) ? p.name : ""; },
        offsetY: -9, style: { fontSize: "11px", colors: ["#334155"] }, background: { enabled: false } },
      xaxis: { labels: { show: false }, axisTicks: { show: false }, axisBorder: { show: false }, tooltip: { enabled: false } },
      yaxis: { labels: { show: false } }, grid: { borderColor: "rgba(148,163,184,.25)" }, legend: { position: "bottom" },
      tooltip: { custom: ({ seriesIndex, dataPointIndex, w }) => { const p = w.config.series[seriesIndex].data[dataPointIndex].p;
        return `<div class="cu-tip"><b>${escHtml(p.name)}</b>${p.sector ? ` <em>${escHtml(p.sector)}</em>` : ""}<br>묶음 ${p.cluster} · 연 수익률 ${pctCu(p.ret)} · 변동성 ${pctCu(p.vol)}${p.nearest ? `<br>가장 같이 움직인 종목: ${escHtml(p.nearest.name)}(${p.nearest.corr.toFixed(2)})` : ""}</div>`; } },
    });
    ch.render();
    charts.push(ch);
  }
  const kEl = document.getElementById("cu-k");
  if (kEl && d.k_scores && d.k_scores.length) {
    const ch = new ApexCharts(kEl, {
      chart: { type: "bar", height: 160, toolbar: { show: false }, animations: { enabled: false }, redrawOnWindowResize: false, redrawOnParentResize: false },
      series: [{ name: "실루엣", data: d.k_scores.map(s => s.silhouette) }],
      xaxis: { categories: d.k_scores.map(s => `${s.k}개`) }, yaxis: { labels: { formatter: v => v.toFixed(2) } },
      colors: d.k_scores.map(s => (s.k === d.k ? "#2563eb" : "#cbd5e1")), plotOptions: { bar: { distributed: true, columnWidth: "55%" } },
      legend: { show: false }, dataLabels: { enabled: false }, tooltip: { enabled: false },
    });
    ch.render();
    charts.push(ch);
  }
}

function onClickCu(ev) {
  const t = ev.target.closest("button, [data-q]");
  if (!t || !root() || !root().contains(t)) return;
  if (t.dataset.tab) { S.tab = t.dataset.tab; paint(); return; }
  if (t.dataset.more) { S.open[t.dataset.more] = !S.open[t.dataset.more]; paint(); return; }
  if (t.dataset.q && t.tagName === "BUTTON" && S.q && !S.busy) {
    const q = { ...S.q, [t.dataset.q]: t.dataset.v };
    if (t.dataset.q !== "k") q.k = 0;   // 대상 · 기간 · 방법을 바꾸면 묶음 수는 다시 자동
    loadClusters(q);
  }
}

function onChangeCu(ev) {
  const t = ev.target;
  if (!t || t.dataset.q !== "k" || !S.q || S.busy) return;
  loadClusters({ ...S.q, k: Number(t.value) || 0 });
}

let wired = false;
export function onClusterViewActivated(view) {
  if (view !== "ml-cluster") return;   // 글자 그대로 — 화면 스캐너(scripts/view_scan.py)가 이 모양으로 진입 훅을 읽는다
  const el = root();
  if (!el) return;
  if (!wired) {
    el.addEventListener("click", onClickCu);
    el.addEventListener("change", onChangeCu);
    window.addEventListener("resize", onResizeCu);
    wired = true;
  }
  if (!S.d && !S.busy) { const pref = readPref(); loadClusters(pref, !!pref); }
  else paint();
}
