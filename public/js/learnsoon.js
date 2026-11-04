/* 「준비 중」 장 보이기 설정 — 학습 목차 · 금융 보충 장 · 사용법 창이 함께 쓴다 (2026-11-04)
 *
 * 사용자 결정(11-04): 목록 · 검색 · 사용법 연결에서는 읽을 수 있는 장만 기본으로 보이고,
 * 「준비 중」 장은 「준비 중인 장도 보기」 를 켠 사람에게만 보인다. 켠 값은 이 브라우저에만 남는다(localStorage).
 * 장 주소를 직접 연 경우(북마크 · 글 속 링크)는 설정과 상관없이 열린다 — 이 설정은 목록에서 숨기기만 한다.
 *
 * 아무것도 가져오지 않는다(DOM · 서버 없음) — 시험이 node 로 그대로 불러 돌릴 수 있다.
 */

export const SOON_KEY = "q-learn-show-soon";
export const SOON_EVENT = "q-learn-soon";

/** 준비 중(뼈대) 장인가 — 서버가 주는 status 값(skeleton) 기준. */
export const isSoon = p => !!p && p.status === "skeleton";

/** 「준비 중인 장도 보기」 를 켰는가 — 저장소가 막혀 있으면 꺼진 것으로 본다. */
export function showSoon() {
  try { return globalThis.localStorage.getItem(SOON_KEY) === "1"; } catch { return false; }
}

export function setShowSoon(on) {
  try { globalThis.localStorage.setItem(SOON_KEY, on ? "1" : "0"); } catch { /* 저장이 안 돼도 이번 화면은 바뀐다 */ }
}

/** 목록에 보일 장 — 기본은 준비 중이 아닌 장만. */
export function visiblePages(pages, show = showSoon()) {
  return show ? pages : pages.filter(p => !isSoon(p));
}

/** 목록 위의 「준비 중인 장도 보기」 스위치 — 숨길 장이 없으면 그리지 않는다. */
export function soonToggleHtml(soonCount, show = showSoon()) {
  if (!soonCount) return "";
  return `<label class="cl-soon-toggle"><input type="checkbox" data-cl-soon${show ? " checked" : ""}> `
    + `준비 중인 장 ${soonCount}개도 보기</label>`;
}

// 스위치를 누르면 값을 저장하고 알린다 — 각 화면(conceptlearn.js · finlearn.js)이 이 알림을 받아 자기 목록만 다시 그린다.
if (typeof document !== "undefined") {
  document.addEventListener("change", e => {
    const t = e.target;
    if (!t || !t.matches || !t.matches("[data-cl-soon]")) return;
    setShowSoon(t.checked);
    document.dispatchEvent(new CustomEvent(SOON_EVENT, { detail: { show: t.checked, from: t } }));
  });
}
