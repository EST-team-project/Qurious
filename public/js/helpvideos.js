/* 사용법 영상 목록 화면 — 개념 학습 › 사용법 영상(learn-videos · 2026-10-20 · D132 둘째 단계)
 *
 * 판단(차례 · 다음 편 · 그릴 HTML)은 js/helpvideosview.js 에 있고, 여기는 표 받기 · 그리기 · 단추만 한다.
 *   - 영상 표는 사용법 창과 같은 주소(/help/videos.json) — 로그인 전(401)이면 1분 뒤 다음 화면을 그릴 때 다시 묻는다
 *   - 볼 편이 하나라도 있으면 <html> 에 q-help-videos — 그때만 메뉴 줄이 보인다(helpvideos.css · 메뉴를 다시 그려도 그대로)
 *   - 「이 화면 열기 →」 = 그 화면으로 옮긴 뒤 사용법 창까지 연다(window.QHowto · js/howto.js)
 *   - 화면을 떠나면 영상을 멈춘다 · 끝까지 본 편은 이 브라우저에만 ✓(localStorage — 못 남겨도 화면은 그대로)
 */
import { GNB_MENUS, navigate } from "/js/core.js";
import { resolveView } from "/js/viewalias.js";
import { chapterBadge, chapterIndexAt, VIDEO_MANIFEST_URL } from "/js/howtoview.js";
import { initialOf, listOf, queueHtml, stageHtml, WATCHED_KEY } from "/js/helpvideosview.js";

const VIEW = "learn-videos";
let items = [];
let state = "idle";   // idle · loading · done · later(로그인 전 — retryAt 뒤 다시)
let retryAt = 0;
let currentId = null;

function readWatched() {
  try { return new Set(JSON.parse(localStorage.getItem(WATCHED_KEY) || "[]")); } catch { return new Set(); }
}

function saveWatched(set) {
  try { localStorage.setItem(WATCHED_KEY, JSON.stringify([...set])); } catch { /* 남기지 못해도 화면은 그대로 */ }
}

// 메뉴 이름 「묶음 › 화면」 — core.js 의 메뉴 표에서 읽는다(여기에 다시 적지 않는다)
function pathOf(viewKey) {
  for (const menu of Object.values(GNB_MENUS)) {
    const it = (menu.items || []).find((x) => x.key === viewKey);
    if (it) return `${String(menu.label || "").replace(/<[^>]*>/g, "").trim()} › ${it.label}`;
  }
  return "";
}

async function hvLoad() {
  state = "loading";
  try {
    const r = await fetch(VIDEO_MANIFEST_URL, { cache: "no-cache", credentials: "same-origin" });
    if (r.status === 401) { state = "later"; retryAt = Date.now() + 60_000; return; }
    items = r.ok ? listOf(await r.json()) : [];
  } catch (err) {
    items = [];
    console.warn("사용법 영상 표를 받지 못해 목록을 숨깁니다", err);
  }
  state = "done";
  document.documentElement.classList.toggle("q-help-videos", items.length > 0);
  if (document.querySelector(`.view[data-view="${VIEW}"].active`)) hvRender();
}

function hvRender() {
  const root = document.getElementById("hv-root");
  if (!root) return;
  if (state !== "done") {
    root.innerHTML = `<div class="card"><p class="hv-sub">영상 목록을 불러오는 중입니다…</p></div>`;
    return;
  }
  if (!items.length) {
    root.innerHTML = `<div class="card"><p class="hv-sub">아직 볼 수 있는 사용법 영상이 없습니다.</p></div>`;
    return;
  }
  const watched = readWatched();
  const item = initialOf(items, currentId, watched);
  currentId = item.id;
  const canOpen = !!(item.view && document.querySelector(`.view[data-view="${resolveView(item.view)}"]`));
  root.innerHTML = `<div class="hv-wrap"><div class="card hv-main">${stageHtml(item, items, { pathLabel: pathOf(item.view), canOpen })}</div>`
    + `<aside class="card hv-side" aria-label="사용법 영상 차례">${queueHtml(items, item.id, watched)}</aside></div>`;
  wireVideo(root, item);
  if (!root.dataset.hvWired) {
    root.dataset.hvWired = "1";
    root.addEventListener("click", hvOnClick);
  }
}

// 영상 — 재생 시각에 맞춰 장 단추 · 장 표시를 옮기고, 끝까지 보면 ✓
function wireVideo(root, item) {
  const video = root.querySelector("video.q-howto-player");
  if (!video) return;
  const chaps = item.video.chapters;
  const badge = root.querySelector(".q-howto-chapbadge");
  video.addEventListener("timeupdate", () => {
    const k = chapterIndexAt(chaps, video.currentTime);
    root.querySelectorAll("[data-howto-chap]").forEach((b, i) => {
      if (i === k) b.setAttribute("aria-current", "true"); else b.removeAttribute("aria-current");
    });
    if (badge) badge.textContent = chapterBadge(k, chaps.length);
  });
  video.addEventListener("ended", () => {
    const watched = readWatched();
    watched.add(item.id);
    saveWatched(watched);
    const side = root.querySelector(".hv-side");
    if (side) side.innerHTML = queueHtml(items, item.id, watched);
  });
}

function hvOnClick(event) {
  const root = event.currentTarget;
  const chap = event.target.closest("[data-howto-chap]");
  if (chap) {
    const item = items.find((it) => it.id === currentId);
    const video = root.querySelector("video.q-howto-player");
    const c = item?.video.chapters[Number(chap.dataset.howtoChap)];
    if (video && c) { video.currentTime = c.start; video.play().catch(() => {}); }
    return;
  }
  const pick = event.target.closest("[data-hv-id], [data-hv-next]");
  if (pick) {
    currentId = pick.dataset.hvId || pick.dataset.hvNext;
    hvRender();
    document.getElementById("main-content")?.scrollTo({ top: 0 });   // 앱의 굴러가는 칸(창이 아님 · DF-134)
    return;
  }
  const open = event.target.closest("[data-hv-open]");
  if (open) {
    const key = open.dataset.hvOpen;
    navigate(key);
    setTimeout(() => window.QHowto?.open(key), 60);   // 옮긴 화면의 윗줄이 그려진 뒤 사용법 창
  }
}

/** main.js 가 화면을 바꿀 때마다 부른다 — 표는 한 번 받고(로그인 전이면 나중에), 이 화면이면 그리고, 떠나면 영상을 멈춘다. */
export function onHelpVideosViewActivated(view) {
  if (state === "idle" || (state === "later" && Date.now() >= retryAt)) hvLoad();
  if (view === VIEW) { hvRender(); return; }
  document.querySelector("#hv-root video")?.pause();
}

