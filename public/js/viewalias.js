/* 화면 별칭 — 옛 화면 주소를 합친 화면의 탭으로 잇는다 (2026-10-30 · ①-18 완전 통합 · Figma 「Qurious · 전략 분석」 03 설계 · 05 결정 6번)
 *
 * 「성과 검증 (Python)」 은 「전략 분석」 화면 안의 두 번째 탭이 되었다. 화면 선언(app.html)과 메뉴 줄은 하나뿐이지만
 * 옛 주소(#indicator-backtest) · 도움말 · 금융 필수 지식의 링크 · 점검표 키는 그대로 쓸 수 있어야 한다.
 *   · 별칭 키 = 탭 키 — 탭을 누르면 주소가 그 키로 바뀌고, 사용법 글 · 기능 완성도 점수는 탭 키로 찾는다.
 *   · 화면(.view) · 메뉴 줄을 고를 때만 resolveView 로 합친 화면 키를 쓴다.
 * 의존이 없어 node 로 그대로 시험한다(TC-BNC).
 */
export const VIEW_ALIAS = Object.freeze({ "indicator-backtest": "quant-backtest" });

/* 마이페이지 안에 본체가 있는 화면 키 → 열 구역 (2026-11-03 · ②-31 · Open API 는 S195)
 * 주소(#settings · #notification-settings · #paper-openapi)와 사용법 · 점수의 화면 키는 그대로 두고, 보이는 화면만 마이페이지의 그 구역이다.
 * app.html 에는 화면 키를 위한 빈 껍데기 .view 가 남아 있다(처음 주소 이동 검사 · 기능 완성도 점수). */
export const MYPAGE_HOSTED = Object.freeze({ "settings": "broker", "notification-settings": "notify", "paper-openapi": "external" });

/* 화면 키 → 실제로 선언된 화면 키(별칭이 아니면 그대로) */
export function resolveView(key) {
  return Object.prototype.hasOwnProperty.call(VIEW_ALIAS, key) ? VIEW_ALIAS[key] : key;
}
