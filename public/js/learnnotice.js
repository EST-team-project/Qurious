/* 「시작하기 전에」 — 금융 필수 지식 · 개념 학습 두 메뉴가 함께 쓰는 고지 한 벌(장 대장 F00 · 2026-10-20)
 *
 * 붙이는 곳(장 대장 F00 「고지 문구 한 벌을 두 메뉴 꼬리에」): 강의실 맨 앞 카드(전문) + 두 메뉴 화면 꼬리(한 줄 · 전문으로 가는 링크).
 * 강사님 강의 페이지의 꼬리말은 원본(10-08)에서 사라진 적이 있다 — 우리 고지를 원본에 기대지 않게 앱이 직접 그린다.
 * 글은 여기 한 곳이다(화면 파일에 같은 글을 두지 않는다). 바뀌는 사실(자료가 들어오는 시각 · 법령 판)은 숫자 옆 기준일과
 * 장 머리가 말하고, 이 글은 그 읽는 법만 적는다. 「현재가」 는 지금 받은 값이다(UI 명세서 2.2절 — 「실시간」 낱말 없음).
 * 아무것도 가져오지 않는다 — 시험이 글을 그대로 읽는다(TC-CLV-06).
 */

export const NOTICE_TITLE = "시작하기 전에 — 이 서비스로 할 수 있는 것과 없는 것";

export const NOTICE_ROWS = Object.freeze([
  Object.freeze({ head: "할 수 있는 것", body: "투자 개념을 배우고, 내 규칙을 과거 자료로 재 보고, 앱 안 모의 계좌로 연습합니다." }),
  Object.freeze({ head: "하지 않는 것", body: "실제 돈으로 주문하지 않습니다 — 증권사에는 모의투자 계좌로만 주문하고, 실거래 주문은 승인 전까지 서버가 막습니다. 특정 상품 · 종목을 권하지 않습니다." }),
  Object.freeze({ head: "숫자의 날짜", body: "판단 · 검증에 쓰는 숫자는 받은 날의 공식 자료입니다(시세는 다음 영업일 낮에 들어옵니다) — 숫자 옆에 기준일 · 출처를 적습니다. 「현재가」 는 지금 받은 값이고 출처와 시각을 함께 적습니다. 법령 · 제도 설명은 장 머리에 적은 기준일의 판입니다." }),
  Object.freeze({ head: "판단은 이용자 몫", body: "교육 · 연습용이며 투자 권유가 아닙니다. 과거 성과는 미래 수익을 보장하지 않습니다." }),
]);

export const NOTICE_LINE = "교육 · 연습용이며 투자 권유가 아닙니다 · 주문은 모의 계좌로만 · 숫자는 옆에 적힌 기준일의 자료입니다";

/** 강의실 맨 앞 카드 — 제목 + 네 줄. */
export function noticeCardHtml() {
  const rows = NOTICE_ROWS.map((r) => `<li><b>${r.head}</b><span>${r.body}</span></li>`).join("");
  return `<section class="fl-card q-notice" aria-labelledby="q-notice-title">`
    + `<h3 id="q-notice-title"><i class="fa-solid fa-circle-info" aria-hidden="true"></i> ${NOTICE_TITLE}</h3>`
    + `<ul class="q-notice-rows">${rows}</ul></section>`;
}

/** 두 메뉴 화면 꼬리 한 줄 — 전문(강의실 맨 앞 카드)으로 가는 링크. */
export function noticeLineHtml() {
  return `<p class="q-notice-line"><i class="fa-solid fa-circle-info" aria-hidden="true"></i> ${NOTICE_LINE} · `
    + `<a href="#fin-lectures">시작하기 전에</a></p>`;
}
