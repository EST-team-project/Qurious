/* 랜딩(로그인 전 첫 화면) — 인트로와 카드 펼침 · 2026-10-29 (시안: Figma 「Qurious · 랜딩」 · 사용자 결정 ① ~ ④)
 *
 * 이 파일이 하는 일은 둘이다.
 *  1. 인트로를 끝낸다 — 「건너뛰기」 · 화면 누르기 · Esc · Enter · Space 가 올 때까지 머문다(저절로 넘어가지 않는다 · 2026-10-29 개정).
 *     인트로를 보일지는 index.html 앞 스크립트가 이미 정했다(html.intro-on). 이 탭에서 한 번 봤으면 다시 안 보인다(sessionStorage).
 *  2. 카드를 누르면 펼친다 — 한 번에 하나만, 펼친 카드를 다시 누르면 접는다. 펼침 상태는 aria-expanded 로 읽어 준다.
 *
 * 로그인한 사람을 앱으로 보내는 일은 서버(`/` 라우트)가 한다. 여기서는 뒤로가기 캐시(bfcache)로 이 화면이 되살아났는데
 * 그 사이 로그인했는지만 한 번 더 본다(login.html 과 같은 방식).
 */
const SEEN_KEY = "qurious-intro-seen";

function endIntro() {
  const intro = document.getElementById("intro");
  document.documentElement.classList.remove("intro-on");   // 본문 스크롤 잠금을 풀고
  try { window.sessionStorage.setItem(SEEN_KEY, "1"); } catch { /* 저장 못 해도 이번 탭에서는 이미 끝났다 */ }
  if (!intro || intro.dataset.done) return;
  intro.dataset.done = "1";
  intro.classList.add("intro--out");
  window.setTimeout(() => intro.remove(), 450);
}

function setupIntro() {
  const root = document.documentElement;
  const intro = document.getElementById("intro");
  if (!intro) return;
  if (!root.classList.contains("intro-on")) { intro.remove(); return; }   // 안 보이는 경우 — 요소도 치운다(읽기 도구가 읽지 않게)
  const skip = () => endIntro();     // 저절로 넘어가지 않는다 — 누를 때까지 머문다(2026-10-29 사용자 피드백)
  document.getElementById("intro-skip")?.addEventListener("click", (e) => { e.stopPropagation(); skip(); });
  // 로그인 · 가입 링크는 그대로 눌린다(이동하므로 건너뛰기를 따로 부르지 않는다)
  intro.querySelectorAll(".intro-link").forEach((a) => a.addEventListener("click", (e) => e.stopPropagation()));
  intro.addEventListener("click", skip);
  window.addEventListener("keydown", (e) => {
    if (!intro.isConnected) return;
    if (e.key === "Escape" || e.key === "Enter" || e.key === " ") { e.preventDefault(); skip(); }
  });
  document.getElementById("intro-skip")?.focus({ preventScroll: true });
}

function setupCards() {
  const cards = Array.from(document.querySelectorAll("#cards .card"));
  const setOpen = (card, open) => {
    card.classList.toggle("is-open", open);
    card.querySelector(".card-head")?.setAttribute("aria-expanded", open ? "true" : "false");
  };
  cards.forEach((card) => {
    setOpen(card, false);
    card.querySelector(".card-head")?.addEventListener("click", () => {
      const willOpen = !card.classList.contains("is-open");
      cards.forEach((c) => setOpen(c, false));      // 한 번에 하나만
      setOpen(card, willOpen);
    });
  });
}

function setupBfcache() {
  window.addEventListener("pageshow", async (ev) => {
    if (!ev.persisted) return;
    try {
      const r = await fetch("/api/me", { credentials: "same-origin" });
      if (r.ok) window.location.replace("/app.html");   // 로그인돼 있으면 앱으로 — 로그인 안 됨(401)은 그대로
    } catch { /* 서버에 못 닿으면 그대로 둔다 */ }
  });
}

setupIntro();
setupCards();
setupBfcache();
