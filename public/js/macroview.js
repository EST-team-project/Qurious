/* 거시경제 화면 — 한국은행 통계 카드 판단: DOM 없이 글 · 표시만 정한다(node 로 시험 · TC-MK · 2026-10-29 · 할 일 ①-10 거시).
 *
 * 왜 따로 두나 — 이 화면의 불러오기는 ml.js(강사님 기초 코드에서 출발)에 있어서, 규칙은 여기 한 곳에 두고 ml.js 는 부르기만 한다
 * (fundview.js · techview.js 와 같은 짜임).
 *
 * 읽는 길 하나 — GET /api/macro/ecos (수집 DB 의 한국은행 통계 · app/services/macro_ecos.py). 옛 길(/api/macro/indicators)은 야후 시세로
 * 미국 10년물 · 유가를 그렸고 한국 거시가 아니었다. 그 길은 「해외 · 원자재 시세」 로 이름을 바꿔 아래에 그대로 둔다.
 *
 * 규칙
 *   1. 숫자는 응답에 있는 값만. 없으면 줄표와 서버 까닭. 화면이 값을 셈하지 않는다(변화 · 전년 대비는 서버가 한 곳에서 셈한다).
 *   2. 값마다 기준일을 붙인다 — 묶음마다 기준일이 다르다(일 계열은 날마다 · 물가는 달마다).
 *   3. 변화는 「직전 관측일(날짜) 대비」 라고 쓴다 — 어제 대비가 아니다(주말 · 휴일은 건너뛴다).
 *   4. 한국은행 통계의 변화에는 초록 · 빨강을 쓰지 않는다 — 금리 · 환율 · 물가가 오른 것이 좋은지 나쁜지는 보는 사람마다 다르다. 화살표와 부호만.
 *      (산업 표의 종목 등락은 옛 표와 같이 오름 초록 · 내림 빨강 — 종목 등락은 읽는 관례가 있다.)
 *   5. 출처(한국은행 경제통계시스템)와 작성기관, 실시간이 아니라는 말을 늘 붙인다(ECOS 약관 제7조②).
 *
 * 산업 표 — GET /api/macro/industry-kr (app/services/macro_industry.py): KSIC 중분류별 종목 수 · 하루 등락 중앙값 · 오른 / 내린 종목 수 · 대표 종목.
 *   업종 전체 지수가 아니다 — 수집 대상 몇 곳만의 값이라 곳 수와 그 말을 늘 붙이고, 종목이 적은 업종에는 「종목 적음」 표시를 한다.
 */

const DASH = "—";
const isNum = v => typeof v === "number" && Number.isFinite(v);

/** 숫자 → 천 단위 쉼표 · 소수는 받은 그대로(끝자리 0 은 뗀다) — 값을 바꾸지 않고 모양만. */
export function numText(v, maxFrac = 3) {
  if (!isNum(v)) return DASH;
  return v.toLocaleString("ko-KR", { minimumFractionDigits: 0, maximumFractionDigits: maxFrac });
}

/** 부호 붙은 변화 글 — 「+0.32%」 · 「−0.03%p」 · 0 은 「0%p」 (음수는 마이너스 기호 U+2212). */
export function signedText(v, unit, maxFrac = 2) {
  if (!isNum(v)) return DASH;
  const sign = v > 0 ? "+" : v < 0 ? "−" : "";
  return `${sign}${numText(Math.abs(v), maxFrac)}${unit}`;
}

/** 값 글 — 단위마다 붙이는 자리가 다르다(연% 는 뒤 · 원 · 포인트는 뒤 한 칸). */
export function valueText(item) {
  if (!item || !isNum(item.value)) return DASH;
  if (item.unit === "연%") return `${numText(item.value, 3)}%`;
  if (item.unit === "원") return `${numText(item.value, 2)}원`;
  if (item.unit === "포인트") return `${numText(item.value, 2)} 포인트`;
  return numText(item.value, 2);
}

/** 변화의 세 조각 — 무엇과 견줬나(base) · 얼마나(main) · 물가의 전년 같은 달(yoy). 직전이 없으면 null. 서버가 준 값만. */
export function changeParts(item) {
  if (!item || !item.prev) return null;
  const arrow = !item.change || !isNum(item.change.value) ? "" :
    item.change.value > 0 ? "▲ " : item.change.value < 0 ? "▼ " : "";
  const main = item.change && isNum(item.change.value)
    ? `${arrow}${signedText(item.change.value, item.change.unit)}` : DASH;
  const base = item.cycle === "M" ? `전월(${item.prev.date})` : `직전 관측일(${item.prev.date})`;
  const yoy = item.kind === "cpi"
    ? (isNum(item.yoy_pct) ? `전년 같은 달 대비 ${signedText(item.yoy_pct, "%")}` : "전년 같은 달 대비 —") : "";
  return { base, main, yoy };
}

/** 변화 글 한 줄 — 직전이 없으면 줄표. */
export function changeText(item) {
  const p = changeParts(item);
  if (!p) return DASH;
  return [`${p.base} 대비 ${p.main}`, p.yoy].filter(Boolean).join(" · ");
}

/** 수집 시각 「2026-10-28T12:42:19+09:00」 → 「2026-10-28 12:42 KST」 — 모르면 빈 글. */
export function stampText(iso) {
  const m = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(String(iso || ""));
  return m ? `${m[1]} ${m[2]} KST` : "";
}

/** 응답 → 카드 묶음 HTML. esc 는 화면이 쓰는 이스케이프 함수. */
export function renderEcos(res, esc) {
  if (!res || res.ok === false) {
    return `<div class="text-sm text-slate-400">한국은행 통계를 불러오지 못했습니다${res?.error ? ` — ${esc(res.error)}` : ""}.</div>`;
  }
  const d = res.data || {};
  if (d.available === false) {
    const hint = d.admin_hint ? `<div class="text-xs mt-1" style="color:var(--text-mute);">관리자 안내: ${esc(d.admin_hint)}</div>` : "";
    return `<div class="text-sm text-slate-400">${esc(d.reason || "한국은행 통계를 아직 받지 못했습니다.")}</div>${hint}`;
  }
  const groups = (d.groups || []).map(g => {
    const cards = (g.items || []).map(it => {
      const known = isNum(it.value);
      const date = known ? `기준일 ${esc(it.date)}` : esc(it.reason || "아직 받은 값이 없습니다.");
      // 화살표 · 부호가 줄 끝에서 따로 떨어지지 않게 「얼마나」 는 한 덩어리로 묶는다
      const p = changeParts(it);
      const change = p
        ? `${esc(p.base)} 대비 <span style="white-space:nowrap;">${esc(p.main)}</span>${p.yoy ? `<br>${esc(p.yoy)}` : ""}`
        : DASH;
      return `<div class="p-3 rounded" style="background:var(--bg);border:1px solid var(--border);" data-ecos="${esc(it.key)}">
        <div class="text-xs text-slate-400 mb-1">${esc(it.label)}</div>
        <div class="text-base font-bold">${esc(valueText(it))}</div>
        <div class="text-xs mt-1" style="color:var(--text-mute);">${change}</div>
        <div class="text-xs mt-1" style="color:var(--text-mute);">${date}</div>
      </div>`;
    }).join("");
    return `<div class="mb-4">
      <h3 class="text-sm font-semibold mb-2">${esc(g.label)} <span class="text-xs font-normal text-slate-400">· 작성기관 ${esc(g.origin)}</span></h3>
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">${cards}</div>
    </div>`;
  }).join("");
  const stamp = stampText(d.updated_at);
  return `${groups}<p class="text-xs mt-2" style="color:var(--text-mute);">출처: ${esc(d.source)}${stamp ? ` · 수집 ${esc(stamp)}` : ""}<br>${esc(d.notice)}</p>`;
}

/** 서버에서 받아 온다 — 실패해도 던지지 않고 { ok:false, error } (화면 나머지는 그대로 그려진다). */
export async function loadEcos(api) {
  try {
    return { ok: true, data: await api("/api/macro/ecos") };
  } catch (e) {
    return { ok: false, error: e?.message || String(e) };
  }
}

/** 산업 표 HTML — 서버 값 그대로(곳 수 · 중앙값 · 오른 / 내린 · 대표 종목). */
export function renderIndustry(res, esc) {
  if (!res || res.ok === false) {
    return `<div class="text-sm text-slate-400">국내 산업별 등락을 불러오지 못했습니다${res?.error ? ` — ${esc(res.error)}` : ""}.</div>`;
  }
  const d = res.data || {};
  if (d.available === false) {
    const hint = d.admin_hint ? `<div class="text-xs mt-1" style="color:var(--text-mute);">관리자 안내: ${esc(d.admin_hint)}</div>` : "";
    return `<div class="text-sm text-slate-400">${esc(d.reason || "업종별 자료를 아직 받지 못했습니다.")}</div>${hint}`;
  }
  const rows = (d.groups || []).map(g => {
    const known = isNum(g.change_median);
    const clr = !known ? "var(--text-mute)" : g.change_median > 0 ? "#22c55e" : g.change_median < 0 ? "#ef4444" : "var(--text-mute)";
    const arrow = !known ? "" : g.change_median > 0 ? "▲ " : g.change_median < 0 ? "▼ " : "";
    const sec = g.section && g.section.name ? `<div class="text-xs" style="color:var(--text-mute);">${esc(g.section.name)}</div>` : "";
    const thin = g.thin ? ` <span class="text-xs" style="color:var(--text-mute);">(종목 적음)</span>` : "";
    const count = g.priced === g.n ? `${g.n}곳` : `${g.n}곳 (등락 ${g.priced}곳)`;
    const top = (g.top || []).map(t => esc(t.name)).join(" · ");
    return `<tr class="border-b border-slate-800 text-slate-300" data-industry="${esc(g.code)}">
      <td class="py-2 pr-2"><span class="font-medium">${esc(g.name)}</span>${thin}${sec}</td>
      <td class="py-2 text-right whitespace-nowrap">${esc(count)}</td>
      <td class="py-2 text-right whitespace-nowrap" style="color:${clr};">${known ? `${arrow}${esc(signedText(g.change_median, "%"))}` : DASH}</td>
      <td class="py-2 text-right whitespace-nowrap">오른 ${g.up} · 내린 ${g.down}${g.flat ? ` · 보합 ${g.flat}` : ""}</td>
      <td class="py-2 pl-3 text-xs" style="color:var(--text-mute);">${top || DASH}</td>
    </tr>`;
  }).join("");
  return `<p class="text-xs mb-2" style="color:var(--text-mute);">기준일 ${esc(d.as_of)} · 수집 대상 ${esc(d.universe)}곳 · 업종은 한국표준산업분류(KSIC) 중분류 · 등락은 그날 하루 등락률의 중앙값</p>
    <div class="overflow-x-auto"><table class="w-full text-xs">
      <thead><tr class="border-b border-slate-700 text-slate-400">
        <th class="py-2 text-left">업종</th><th class="py-2 text-right">종목 수</th><th class="py-2 text-right">등락 중앙값</th>
        <th class="py-2 text-right">오른 · 내린</th><th class="py-2 text-left pl-3">시가총액 큰 종목</th>
      </tr></thead><tbody>${rows}</tbody></table></div>
    <p class="text-xs mt-2" style="color:var(--text-mute);">출처: ${esc(d.source)}<br>${esc(d.notice)}</p>`;
}

/** 서버에서 받아 온다 — 실패해도 던지지 않는다. */
export async function loadIndustryKr(api) {
  try {
    return { ok: true, data: await api("/api/macro/industry-kr") };
  } catch (e) {
    return { ok: false, error: e?.message || String(e) };
  }
}
