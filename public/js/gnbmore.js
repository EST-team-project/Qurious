/* 아바타 메뉴 · 동기화 점 글 (DF-109 · 2026-10-14 화면 결정 D84 → 2026-10-18 메뉴 개편 D129 안 가)
 *
 * 왜 — 위 메뉴를 고정 탭 여섯 + 왼쪽 「전체 메뉴」 트리로 바꾸면서(js/core.js MENU_TOP · MENU_TREE) 탭 줄 끝
 *      「더보기 N ▾」 와 오른쪽 서랍 「전체 메뉴」 가 할 일이 없어졌다 — 숨은 묶음이 없고, 모든 묶음은 왼쪽 트리
 *      (좁은 화면은 ☰)에 늘 있다. 이 파일에는 머리 오른쪽을 줄이는 두 가지만 남는다.
 * 무엇 — ① 이름 · 로그아웃은 아바타 ▾ 메뉴로(그만큼 탭 칸이 넓어진다).
 *        ② 「n분 전 동기화」 글은 점의 title · aria-label 로(글이 바뀌면 따라간다).
 * 꼴 — WAI-ARIA APG Disclosure(단추 + aria-expanded · aria-controls). 링크 · 단추 목록이라 메뉴 역할(menu role)은 쓰지 않는다.
 *      Esc(초점은 단추로) · 바깥 누름 · 초점이 목록 밖으로 · 화면이 바뀌면 · 창 크기가 바뀌면 닫는다.
 *      목록은 body 에 붙여 fixed 로 단추 아래에 둔다.
 * 이름 — 파일 이름 · initGnbMore 는 main.js 가 부르는 이름이라 그대로 둔다.
 */
import { GNB_MENUS, fitGnbTabs, navigate } from "/js/core.js";

const ACCOUNT_GROUP = "account";   // 아바타 메뉴로 가는 묶음(내 계정)

let userBtn = null;
let userPop = null;

function renderUser() {
  const name = document.getElementById("user-name")?.textContent?.trim() || "내 계정";
  const account = GNB_MENUS[ACCOUNT_GROUP];
  const items = (account ? account.items : []).filter(it => it.key && !it.heading);
  userPop.innerHTML = `<div class="gnb-pop-head"></div>` +
    items.map(it => `<button type="button" class="gnb-pop-item" data-go-view="${it.key}"><i class="${it.icon}" aria-hidden="true"></i><span>${it.label}</span></button>`).join("") +
    `<div class="gnb-pop-sep"></div><button type="button" class="gnb-pop-item" data-logout="1">` +
    `<i class="fa-solid fa-arrow-right-from-bracket" aria-hidden="true"></i><span>로그아웃</span></button>`;
  userPop.querySelector(".gnb-pop-head").textContent = name;   // 이름은 글자로만(태그로 읽지 않는다)
}

function place(pop, anchor) {
  const r = anchor.getBoundingClientRect();
  pop.style.top = `${Math.round(r.bottom + 4)}px`;
  pop.hidden = false;
  const w = pop.offsetWidth;
  pop.style.left = `${Math.round(Math.max(8, Math.min(r.right - w, window.innerWidth - w - 8)))}px`;
}

function closeUser(focusTrigger) {
  if (!userPop || userPop.hidden) return;
  userPop.hidden = true;
  userBtn.setAttribute("aria-expanded", "false");
  if (focusTrigger) userBtn.focus();
}

function toggleUser() {
  if (!userPop.hidden) { closeUser(false); return; }
  renderUser();
  place(userPop, userBtn);
  userBtn.setAttribute("aria-expanded", "true");
  userPop.querySelector(".gnb-pop-item")?.focus();
}

/** 부트에서 한 번(js/main.js) — 아바타 메뉴를 만들고 동기화 글을 점으로 옮긴 뒤 탭 폭을 다시 잰다. */
export function initGnbMore() {
  if (document.getElementById("gnb-user-pop")) return;
  userBtn = document.getElementById("gnb-user");
  if (userBtn) {
    userPop = document.createElement("div");
    userPop.id = "gnb-user-pop";
    userPop.className = "gnb-pop";
    userPop.hidden = true;
    userPop.setAttribute("aria-label", "내 계정 메뉴");
    document.body.appendChild(userPop);
    // 초점이 단추 · 목록 밖으로 나가면 닫는다(Tab 으로 지나가기 — APG Disclosure)
    userPop.addEventListener("focusout", event => {
      const to = event.relatedTarget;
      if (to && (userPop.contains(to) || to === userBtn)) return;
      if (to) closeUser(false);
    });
    userBtn.setAttribute("aria-expanded", "false");
    userBtn.setAttribute("aria-controls", userPop.id);
    userBtn.title = "내 계정";
    userBtn.insertAdjacentHTML("beforeend", '<i class="fa-solid fa-chevron-down gnb-user-caret" aria-hidden="true"></i>');
    userBtn.addEventListener("click", toggleUser);
    userBtn.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); toggleUser(); }
    });
    userPop.addEventListener("click", event => {
      const go = event.target.closest("[data-go-view]");
      if (go) { closeUser(false); navigate(go.dataset.goView); return; }
      if (event.target.closest("[data-logout]")) {
        closeUser(false);
        document.getElementById("logout-btn").click();   // 로그아웃 처리는 main.js 한 곳(단추는 숨었다)
      }
    });
    document.addEventListener("keydown", event => {
      if (event.key === "Escape") closeUser(true);
    });
    document.addEventListener("pointerdown", event => {
      if (userPop.contains(event.target) || userBtn.contains(event.target)) return;
      closeUser(false);
    });
    document.addEventListener("lumina:view-changed", () => closeUser(false));
    window.addEventListener("resize", () => closeUser(false));
  }

  // 「n분 전 동기화」 글은 머리에서 숨기고(점만 · css/qurious.css) 같은 글을 title · aria-label 로 옮긴다
  const syncText = document.getElementById("sync-badge-text");
  const badge = document.getElementById("sync-badge");
  if (syncText && badge) {
    const mirror = () => {
      const text = syncText.textContent.trim();
      badge.title = text ? `${text} — 누르면 바로 동기화` : "누르면 바로 동기화";
      badge.setAttribute("aria-label", badge.title);
    };
    new MutationObserver(mirror).observe(syncText, { childList: true, characterData: true, subtree: true });
    mirror();
  }

  fitGnbTabs();
}
