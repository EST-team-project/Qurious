/* 위 메뉴 「더보기 N ▾」 펼침 목록 · 아바타 메뉴 (DF-109 · 2026-10-14 화면 결정 D84 = 융합안 D)
 *
 * 왜 — 묶음 탭 열 개(합 약 1,174px)와 머리 오른쪽(시세 · 자료 상태 · 동기화 · 이름 · 로그아웃 · ⋮ — 588 ~ 727px)이
 *      한 줄을 다투어 1920 에서도 뒤 두 묶음(투자분석 · ML·딥러닝)이 숨었고, 숨은 묶음의 입구는 오른쪽 끝
 *      「⋮」 아이콘 하나뿐이었다(글자 · 숨은 수 없음 · 사용자 10-14 보고).
 * 무엇 — ① 탭 줄 끝에 글자 단추 「더보기 N ▾」(N = 숨은 묶음 수) — 누르면 숨은 묶음 · 그 밖의 메뉴 · 전체 메뉴 보기.
 *        ② 이름 · 로그아웃은 아바타 ▾ 메뉴로 옮겨 오른쪽을 줄인다(그만큼 탭 칸이 넓어진다).
 *        ③ 「n분 전 동기화」 글은 점의 title 로(글이 바뀌면 따라간다).
 * 나눔 — 어떤 탭을 숨기고 바꿔 끼울지는 core.js fitGnbTabs 한 곳이 계산해 더보기 단추에 적는다(data-hidden · 숫자 ·
 *        title). 여기서는 그 값을 읽어 목록만 그린다 — 계산을 두 벌 두지 않는다.
 * 꼴 — WAI-ARIA APG Disclosure(단추 + aria-expanded · aria-controls). 링크 · 단추 목록이라 메뉴 역할(menu role)은 쓰지 않는다.
 *      Esc(초점은 단추로) · 바깥 누름 · 초점이 목록 밖으로 · 화면이 바뀌면 · 창 크기가 바뀌면 닫는다.
 *      목록은 탭 칸(.gnb-tabs — 넘침을 자른다) 밖 body 에 붙여 fixed 로 단추 아래에 둔다.
 * 근거 — GitHub Primer UnderlineNav(넘친 항목은 탭 줄 끝 「More」 · 아이콘부터 뺌 · 지금 항목 바꿔 끼움) ·
 *        NN/g 「Hamburger Menus and Hidden Navigation Hurt UX Metrics」(2016) · 조사 배경-머리메뉴/결과.md 4.5절.
 */
import { GNB_MENUS, MENU_DRAWER_ONLY, fitGnbTabs, navigate, openGnbGroup } from "/js/core.js";

const ACCOUNT_GROUP = "account";   // 아바타 메뉴로 가는 묶음(내 계정) — 더보기 목록의 「그 밖의 메뉴」 에서는 뺀다
const plain = html => html.replace(/<[^>]+>/g, "").trim();
const iconOf = html => (html.match(/class='([^']+)'/) || [])[1] || "fa-solid fa-folder";
const screenCount = menu => menu.items.filter(it => it.key && !it.heading).length;

let moreBtn = null;
let morePop = null;
let userBtn = null;
let userPop = null;

function groupRow(key) {
  const menu = GNB_MENUS[key];
  if (!menu) return "";
  const out = menu.items.every(it => it.heading || it.href);   // 개념 학습처럼 모두 바깥 주소인 묶음
  const meta = out ? '새 화면 <i class="fa-solid fa-arrow-up-right-from-square" aria-hidden="true"></i>' : `${screenCount(menu)}`;
  return `<button type="button" class="gnb-pop-item" data-gnb-group="${key}">` +
    `<i class="${iconOf(menu.label)}" aria-hidden="true"></i><span>${plain(menu.label)}</span>` +
    `<span class="gnb-pop-meta">${meta}</span></button>`;
}

function renderMore() {
  const hidden = (moreBtn.dataset.hidden || "").split(" ").filter(Boolean);
  const others = MENU_DRAWER_ONLY.filter(key => key !== ACCOUNT_GROUP);
  morePop.innerHTML =
    (hidden.length ? `<div class="gnb-pop-title">숨은 메뉴 묶음</div>${hidden.map(groupRow).join("")}<div class="gnb-pop-sep"></div>` : "") +
    `<div class="gnb-pop-title">그 밖의 메뉴</div>${others.map(groupRow).join("")}<div class="gnb-pop-sep"></div>` +
    `<button type="button" class="gnb-pop-item" data-open-drawer="1"><i class="fa-solid fa-list" aria-hidden="true"></i>` +
    `<span>전체 메뉴 보기</span><span class="gnb-pop-meta"><i class="fa-solid fa-arrow-right" aria-hidden="true"></i></span></button>`;
}

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

function place(pop, anchor, alignRight) {
  const r = anchor.getBoundingClientRect();
  pop.style.top = `${Math.round(r.bottom + 4)}px`;
  pop.hidden = false;
  const w = pop.offsetWidth;
  const left = alignRight ? r.right - w : r.left;
  pop.style.left = `${Math.round(Math.max(8, Math.min(left, window.innerWidth - w - 8)))}px`;
}

function close(pop, trigger, focusTrigger) {
  if (!pop || pop.hidden) return;
  pop.hidden = true;
  trigger.setAttribute("aria-expanded", "false");
  if (focusTrigger) trigger.focus();
}

function closeAll(focusTrigger) {
  close(morePop, moreBtn, focusTrigger && !morePop.hidden);
  close(userPop, userBtn, focusTrigger && !userPop.hidden);
}

function toggle(pop, trigger, render, alignRight) {
  const opening = pop.hidden;
  closeAll(false);
  if (!opening) return;
  render();
  place(pop, trigger, alignRight);
  trigger.setAttribute("aria-expanded", "true");
  pop.querySelector(".gnb-pop-item")?.focus();
}

function makePop(id, label) {
  const pop = document.createElement("div");
  pop.id = id;
  pop.className = "gnb-pop";
  pop.hidden = true;
  pop.setAttribute("aria-label", label);
  document.body.appendChild(pop);
  // 초점이 단추 · 목록 밖으로 나가면 닫는다(Tab 으로 지나가기 — APG Disclosure)
  pop.addEventListener("focusout", event => {
    const to = event.relatedTarget;
    if (to && (pop.contains(to) || to === moreBtn || to === userBtn)) return;
    if (to) closeAll(false);
  });
  return pop;
}

/** 부트에서 한 번(js/main.js) — 더보기 단추 · 두 목록을 만들고 탭을 다시 맞춘다. */
export function initGnbMore() {
  const bar = document.querySelector("#gnb .gnb-tabs");
  if (!bar || document.getElementById("gnb-more-tab")) return;

  const more = document.createElement("button");
  more.type = "button";
  more.id = "gnb-more-tab";
  more.className = "gnb-more-tab";
  more.innerHTML = `<span>더보기</span><span class="gnb-more-count" aria-hidden="true"></span>` +
    `<i class="fa-solid fa-chevron-down gnb-more-caret" aria-hidden="true"></i>`;
  bar.appendChild(more);
  moreBtn = more;
  morePop = makePop("gnb-more-pop", "더보기 메뉴");
  more.setAttribute("aria-expanded", "false");
  more.setAttribute("aria-controls", morePop.id);
  more.addEventListener("click", () => toggle(morePop, more, renderMore, false));
  morePop.addEventListener("click", event => {
    const group = event.target.closest("[data-gnb-group]");
    if (group) { closeAll(false); openGnbGroup(group.dataset.gnbGroup); return; }
    if (event.target.closest("[data-open-drawer]")) {
      closeAll(false);
      document.getElementById("gnb-more-btn")?.click();   // 전체 메뉴 서랍(core.js) — 단추는 숨었어도 누를 수 있다
    }
  });

  userBtn = document.getElementById("gnb-user");
  if (userBtn) {
    userPop = makePop("gnb-user-pop", "내 계정 메뉴");
    userBtn.setAttribute("aria-expanded", "false");
    userBtn.setAttribute("aria-controls", userPop.id);
    userBtn.title = "내 계정";
    userBtn.insertAdjacentHTML("beforeend", '<i class="fa-solid fa-chevron-down gnb-user-caret" aria-hidden="true"></i>');
    userBtn.addEventListener("click", () => toggle(userPop, userBtn, renderUser, true));
    userBtn.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); toggle(userPop, userBtn, renderUser, true); }
    });
    userPop.addEventListener("click", event => {
      const go = event.target.closest("[data-go-view]");
      if (go) { closeAll(false); navigate(go.dataset.goView); return; }
      if (event.target.closest("[data-logout]")) {
        closeAll(false);
        document.getElementById("logout-btn").click();   // 로그아웃 처리는 main.js 한 곳(단추는 숨었다)
      }
    });
  } else {
    userPop = makePop("gnb-user-pop", "내 계정 메뉴");   // 머리에 사용자 칸이 없는 판 — 빈 목록(닫기 처리만 같게)
    userBtn = more;
  }

  document.addEventListener("keydown", event => {
    if (event.key === "Escape") closeAll(true);
  });
  document.addEventListener("pointerdown", event => {
    const t = event.target;
    if (morePop.contains(t) || userPop.contains(t) || more.contains(t) || userBtn.contains(t)) return;
    closeAll(false);
  });
  document.addEventListener("lumina:view-changed", () => closeAll(false));
  window.addEventListener("resize", () => closeAll(false));

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
