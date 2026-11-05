// 자유 산식 지표 계산 결과 목록(indicator-formula) 위 줄 + 새로고침 안내 글 도우미(리서치 · 상품 안내 화면 공용) (2026-11-05 화면 전수 점검 뒤).
// 규칙(paperlists.js 와 같다)
//  1) 걸러 보는 것은 「이미 받은 줄 안」 이다 — 서버 인자를 늘리지 않는다. 그 한계(서버가 준 최근 N건)는 안내 글에 밝힌다.
//  2) 새로고침은 「저장된 것을 서버에서 다시 읽기」 뿐이다. 계산(compute)을 부르지 않는다 — 그 길은 이 파일이 알지도 못한다(ta_utils 를 지나는 길).
//  3) 칩의 값(종목 · 버전)은 응답에서 읽는다. 눌러 둔 값이 새 응답에 없어도 칩을 남겨 풀 수 있게 한다.
import { createListPanel, distinctOptions } from "/js/paperlists.js";
import { refreshStamp } from "/js/listbar.js";

const MORE_ALL = { value: "", label: "전체" };
export const FORMULA_RESULT_LIMIT = 30;   // 서버에 요청하는 최근 결과 수(옛 화면과 같다)

/** 새로고침이 끝난 뒤 안내 글 — 성공이면 「다시 읽었습니다(HH:MM)」 + 뜻 · 실패면 시각 대신 실패를 알린다(옛 값 위에 새로 읽었다고 쓰지 않는다). */
export function refreshOutcomeText(ok, { error = "", tail = "", meaning = "서버에서 다시 읽었습니다", now = new Date() } = {}) {
  if (!ok) return `다시 읽지 못했습니다${error ? `(${error})` : ""} — 이전에 받은 값을 보입니다`;
  return `${refreshStamp(meaning, now)}${tail ? ` — ${tail}` : ""}`;
}

/** 종목 · 버전 칩 — rows(계산 결과 줄)의 symbol · version 값만. filters 는 지금 눌려 있는 값(응답에서 사라져도 칩을 남긴다). */
export function formulaResultGroups(rows, filters = {}) {
  const sym = distinctOptions(rows.map(x => x.symbol), [], filters.symbol || "");
  const ver = distinctOptions(rows.map(x => x.version), [], filters.version || "");
  return [
    { key: "symbol", label: "종목", options: [MORE_ALL, ...sym.map(v => ({ value: v, label: v }))] },
    { key: "version", label: "버전", options: [MORE_ALL, ...ver.map(v => ({ value: v, label: `v${v}` }))] },
  ];
}

/** 계산 결과 표 — 옛 화면 글 그대로. 비면 안내 한 줄. deps: { esc, ts }. */
export function formulaResultsBodyHtml(rows, deps) {
  const { esc, ts } = deps;
  if (!rows.length) return `<div class="text-sm" style="color:var(--text-mute);">아직 저장된 계산 결과가 없습니다. '계산 실행'을 누르면 (버전·종목·기간) 별로 저장됩니다.</div>`;
  return `<table><thead><tr><th>시각</th><th>버전</th><th>종목</th><th>기간</th><th>기준일</th><th style="text-align:right">최신값</th><th>신호</th><th style="text-align:right">수익률</th><th style="text-align:right">샤프</th><th style="text-align:right">MDD</th><th></th></tr></thead><tbody>${
    rows.map(x => { const m = x.metrics || {}; return `<tr data-fx-result-row><td class="text-xs">${esc(ts(x.created_at))}</td><td>v${esc(x.version)}</td><td class="font-mono text-xs">${esc(x.symbol)}</td><td>${esc(x.period)}</td><td class="text-xs">${esc(x.as_of)}</td><td style="text-align:right">${x.latest_value == null ? "-" : Number(x.latest_value).toFixed(3)}</td>
      <td><span class="${/BUY/.test(x.latest_signal) ? "badge-buy" : /SELL/.test(x.latest_signal) ? "badge-sell" : "badge-hold"}" style="font-size:11px;">${esc(x.latest_signal)}</span></td>
      <td style="text-align:right">${m.total_return_pct ?? "-"}${m.total_return_pct != null ? "%" : ""}</td><td style="text-align:right">${m.sharpe_ratio ?? "-"}</td><td style="text-align:right">${m.mdd_pct ?? "-"}${m.mdd_pct != null ? "%" : ""}</td>
      <td><button class="btn-secondary text-xs fx-view" data-id="${esc(x.id)}">보기</button></td></tr>`; }).join("")}</tbody></table>`;
}

/**
 * 계산 결과 목록 제어기 — 종목 · 버전 칩 + 새로고침. deps: { esc, ts, byId, api, getCurrent, onView?, now? }
 *   getCurrent() 가 지금 열어 둔 지표({id}) 또는 null. 지표가 없으면 서버를 부르지 않고 빈 목록.
 *   onView(row) — 줄의 「보기」 단추(저장된 조건으로 캐시 재사용 호출 · 옛 동작 그대로).
 */
export function formulaResultsPanel(deps) {
  return createListPanel({
    host: "fx-results",
    label: "계산 결과 필터",
    unit: "건",
    groups: (rows, filters) => formulaResultGroups(rows, filters),
    getters: { symbol: x => x.symbol, version: x => x.version },
    limitNote: (rows, filtered, meta) => (meta ? `서버가 준 최근 ${rows.length}건(최대 ${FORMULA_RESULT_LIMIT}건) 안에서 거릅니다` : ""),
    meaning: "서버에서 다시 읽었습니다",
    tail: "저장된 계산 결과 목록만 다시 읽었습니다 — 계산은 하지 않습니다",
    load: async () => {
      const cur = deps.getCurrent();
      if (!cur) return { rows: [], meta: null };
      const r = await deps.api(`/api/formula-indicators/${cur.id}/results?limit=${FORMULA_RESULT_LIMIT}`);
      return { rows: (r && r.results) || [], meta: { id: cur.id } };
    },
    body: rows => formulaResultsBodyHtml(rows, deps),
    after: (host, ctx) => {
      if (!deps.onView || !host.querySelectorAll) return;
      host.querySelectorAll(".fx-view").forEach(b => b.addEventListener("click", () => {
        const row = ctx.rows.find(x => String(x.id) === String(b.dataset.id));
        if (row) deps.onView(row);
      }));
    },
  }, { esc: deps.esc, byId: deps.byId, now: deps.now });
}
