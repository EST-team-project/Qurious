/* 비밀번호 보기 · 숨기기 버튼 (2026-10-29 · 할 일 ①-09)
 *
 * 입력 칸 하나를 받아 오른쪽 끝에 「보기」 버튼을 붙인다. 누르면 글자가 보이고(type=text) 다시 누르면 가려진다(type=password).
 * 로그인 · 가입 화면은 자기 스타일만 가진 따로 선 페이지라, 버튼 모양은 이 파일 안에서 정한다(색은 글자색을 물려받는다).
 * 안전 — 화면이 뒤로가기 캐시(bfcache)로 되살아나거나 닫힐 때 다시 가린다(누군가 어깨 너머로 보지 않게). 접근성 — 버튼에
 * aria-label · aria-pressed 를 두고, 입력 칸 자체(이름 · 자동완성 · 필수 속성)는 건드리지 않는다.
 */
export function attachPasswordToggle(input) {
  if (!input || input.dataset.pwToggle === "1") return;
  input.dataset.pwToggle = "1";
  const wrap = document.createElement("div");
  wrap.style.position = "relative";
  input.parentNode.insertBefore(wrap, input);
  wrap.appendChild(input);
  input.style.paddingRight = "64px";   // 글자가 버튼 밑으로 들어가지 않게

  const btn = document.createElement("button");
  btn.type = "button";
  btn.textContent = "보기";
  btn.setAttribute("aria-label", "비밀번호 보기");
  btn.setAttribute("aria-pressed", "false");
  Object.assign(btn.style, {
    position: "absolute", right: "8px", top: "50%", transform: "translateY(-50%)", background: "transparent",
    border: "0", cursor: "pointer", fontSize: "12px", color: "inherit", opacity: ".75", padding: "4px 6px",
  });
  const set = (show) => {
    input.type = show ? "text" : "password";
    btn.textContent = show ? "숨기기" : "보기";
    btn.setAttribute("aria-pressed", String(show));
    btn.setAttribute("aria-label", show ? "비밀번호 숨기기" : "비밀번호 보기");
  };
  btn.addEventListener("click", () => set(input.type === "password"));
  window.addEventListener("pagehide", () => set(false));
  window.addEventListener("pageshow", () => set(false));
  wrap.appendChild(btn);
}

/** 한 화면의 비밀번호 칸을 한꺼번에 — selector 에 맞는 type=password 칸마다. */
export function attachPasswordToggles(root = document, selector = 'input[type="password"]') {
  root.querySelectorAll(selector).forEach(attachPasswordToggle);
}
