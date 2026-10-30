/* 랜딩(로그인 전 첫 화면) — 인트로와 카드 펼침 · 2026-10-29 (시안: Figma 「Qurious · 랜딩」 · 사용자 결정 ① ~ ④)
 *
 * 이 파일이 하는 일은 둘이다.
 *  1. 인트로를 끝낸다 — 「건너뛰기」 · 화면 누르기 · Esc · Enter · Space 가 올 때까지 머문다(저절로 넘어가지 않는다 · 2026-10-29 개정).
 *     인트로를 보일지는 index.html 앞 스크립트가 이미 정했다(html.intro-on). 움직임 줄이기가 아니면 열 때마다 보인다 —
 *     새로고침하면 다시 뜬다(2026-10-30 개정 · 전에는 이 탭에서 한 번만 · sessionStorage). 위쪽 막대는 눈에 안 보이고 Tab 으로 닿으면 나타난다.
 *  2. 카드를 누르면 펼친다 — 한 번에 하나만, 펼친 카드를 다시 누르면 접는다. 펼침 상태는 aria-expanded 로 읽어 준다.
 *
 * 로그인한 사람을 앱으로 보내는 일은 서버(`/` 라우트)가 한다. 여기서는 뒤로가기 캐시(bfcache)로 이 화면이 되살아났는데
 * 그 사이 로그인했는지만 한 번 더 본다(login.html 과 같은 방식).
 */
function endIntro() {
  const intro = document.getElementById("intro");
  document.documentElement.classList.remove("intro-on");   // 본문 스크롤 잠금을 풀고
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
  // 건너뛰기 버튼에 미리 초점을 두지 않는다 — 두면 눈에 안 보이게 둔 위쪽 막대가 나타난다. 키보드는 Esc · Enter · Space 로 끝낸다.
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

/* 3. 지수 종가 한 줄(S166) — 수집 DB 의 가장 최근 거래일 종가를 서버가 그대로 준다.
 *    공공누리 제4유형(출처 표시 · 비상업 · 변경 금지)이라 계산 · 가공 없이 종가만 · 기준일 · 출처를 같이 적는다.
 *    못 받거나 목록이 비면 칸을 숨긴 채 둔다. 실시간 시세가 아니다(글에도 「종가」 라고만 적는다). */
async function setupTicker() {
  const el = document.getElementById("index-ticker");
  if (!el) return;
  try {
    const r = await fetch("/api/public/index-closes", { credentials: "omit" });
    if (!r.ok) return;
    const d = await r.json();
    if (!d || !d.as_of || !Array.isArray(d.items) || d.items.length === 0) return;
    el.replaceChildren();
    for (const it of d.items) {
      const item = document.createElement("span");
      item.className = "tk-item";
      const name = document.createElement("span");
      name.className = "tk-name";
      name.textContent = it.name;
      const value = document.createElement("b");
      value.textContent = Number(it.close).toLocaleString("ko-KR", { minimumFractionDigits: 2, maximumFractionDigits: 4 });
      item.append(name, " ", value);
      el.append(item);
    }
    const note = document.createElement("span");
    note.className = "tk-note";
    note.textContent = `${d.as_of} 종가 · 출처: ${d.source}`;
    el.append(note);
    el.hidden = false;
  } catch { /* 서버에 못 닿으면 칸을 숨긴 채 둔다 */ }
}

setupIntro();
setupCards();
setupBfcache();
setupTicker();
