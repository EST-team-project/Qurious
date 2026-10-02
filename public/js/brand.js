/* 서비스 이름 · 부제 · 바닥글 — 한 곳에서 관리한다 (2026-10-02).
 *
 * 화면(앱 · 로그인 · 가입)의 「data-brand="이름"」 자리를 아래 값으로 채운다. 이름을 바꾸려면 이 파일만 고친다.
 * HTML 에도 같은 글자를 적어 두는 것은 스크립트가 늦게 읽혀도 빈칸이 보이지 않게 하려는 것이다.
 *
 * 왜 따로 두나 — 화면 파일은 강사님 기초 코드라 다음 반영 때마다 3-way 병합을 한다. 이름을 곳곳에서 바꾸면
 * 그때마다 충돌이 나므로, 바꾸는 값은 이 파일에 모으고 HTML 에는 자리 표시(data-brand)만 둔다.
 * 기초 코드의 원저작자(edumgt/lumina-invest) 표시는 화면이 아니라 NOTICE.md · README 에 남긴다.
 */
export const BRAND = {
  name: "Qurious",
  tagline: "AI Financial Quant Platform",
  // 바닥글의 기술 목록 — 지금 실제로 도는 것만(2026-10-02 · MongoDB 는 아직 없다)
  stack: "FastAPI · PostgreSQL · Redis · Qdrant · Ollama",
  notice: "투자 자문이 아닌 정보 제공 목적입니다.",
};

export function applyBrand(root = document) {
  root.querySelectorAll("[data-brand]").forEach(el => {
    const value = BRAND[el.dataset.brand];
    if (value != null) el.textContent = value;
  });
}

// 모듈이 읽히면 바로 한 번 — 화면 HTML 에 <script type="module" src="/js/brand.js"> 한 줄이면 된다.
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => applyBrand());
} else {
  applyBrand();
}
