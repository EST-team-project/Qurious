/* 화면 사용법 — 윗줄 「사용법」 단추 + 가운데 창(2026-10-16 · 결정 안 A)
 *
 * core.js 의 renderViewGuide 가 화면을 바꿀 때마다 window.QHowto.render(화면 키, 사용법 글, { terms, label, group }) 를 부른다.
 *   · 윗줄은 화면 뿌리 밖(화면의 첫 자식)에 둔다 — 화면 JS 가 머리를 다시 그려도(상품 안내 탭 · 데이터 관제 30초) 단추가 남는다.
 *   · 창은 <dialog> 하나를 showModal 로 연다 — 뒤 화면을 막고(inert) 초점을 창 안에 가두는 일을 브라우저가 한다.
 *   · 크기 · 이어 줄 장 · HTML 은 js/howtoview.js 한 곳에서 정한다(이 파일은 붙이고 여닫기만).
 *   · 용어 칩은 창 안에서 용어 카드를 그린다 — 맨 위 층 창 뒤에는 용어 서랍(QTerm)이 깔려 눌리지 않는다.
 *     받기 · 대체 글 · 다시 시도는 용어 서랍과 같은 함수(termcard.js fillTermCard)를 쓴다.
 * 무엇도 브라우저에 남기지 않는다(옛 접이식의 열림 기억을 버림) · 화면을 바꾸면 창을 닫는다.
 *
 * 사용법 영상(D132 첫 단계 · 2026-10-18): 첫 화면을 그릴 때 영상 표(/help/videos.json — git 밖 로컬 폴더)를 한 번 받는다.
 *   · 받으면 이미 그린 윗줄을 다시 그려 「▶ 영상」 이 나타난다 · 빈 표(받지 않은 PC)거나 못 받으면 영상 칸 · 단추가 숨는다(결정 ⑥).
 *   · 로그인 전(401)이면 1분 뒤 다음 화면을 그릴 때 다시 묻는다.
 *   · 「영상으로 보기」 를 누르면 그 자리에서 그 화면이 나오는 장부터 튼다 · 장 단추로 옮기고 지금 장은 파랑.
 */
import { fillTermCard } from "/js/termcard.js";
import { chapterBadge, chapterIndexAt, howtoHtml, playerHtml, sizeOf, topRowHtml, VIDEO_MANIFEST_URL, videoOf } from "/js/howtoview.js";

const DATA = new Map();    // 화면 키 → { guide, terms, label, group } — 단추를 누를 때 읽는다
let dialog = null;
let trigger = null;        // 창을 연 단추 — 닫으면 초점을 돌려준다
let termSeq = 0;           // 용어를 연달아 누르면 앞 응답은 버린다
let manifest = null;       // 영상 표 — 못 받았으면 null(영상 칸 숨김)
let videosState = "idle";  // idle · loading · done · later(로그인 전 — retryAt 뒤 다시)
let retryAt = 0;

function videoFor(viewKey) {
  return videoOf(viewKey, manifest);
}

async function loadVideos() {
  videosState = "loading";
  try {
    const r = await fetch(VIDEO_MANIFEST_URL, { cache: "no-cache", credentials: "same-origin" });
    if (r.status === 401) { videosState = "later"; retryAt = Date.now() + 60_000; return; }
    if (!r.ok) { videosState = "done"; return; }
    manifest = await r.json();
    videosState = "done";
    if (manifest?.missing) return;                             // 영상을 받지 않은 PC — 빈 표(서버가 200 으로 준다)
    if (!Object.keys(manifest?.views || {}).some((k) => videoOf(k, manifest))) {
      console.warn("사용법 영상 표의 꼴이 맞지 않아 영상 칸을 숨깁니다");
    }
  } catch (err) {
    videosState = "done";
    console.warn("사용법 영상 표를 받지 못해 영상 칸을 숨깁니다", err);
  }
  for (const [k, d] of DATA) render(k, d.guide, d);           // 표가 늦게 와도 이미 그린 윗줄에 단추가 나타나게
}

function ensureVideos() {
  if (videosState === "idle" || (videosState === "later" && Date.now() >= retryAt)) loadVideos();
}

function render(viewKey, guide, { terms = {}, label = "", group = "" } = {}) {
  const viewEl = document.querySelector(`.view[data-view="${viewKey}"]`);
  if (!viewEl) return;
  viewEl.querySelector(":scope > .view-guide")?.remove();   // 옛 접이식(기초 코드 판)이 남아 있으면 지운다
  let row = viewEl.querySelector(":scope > .q-howto-top");
  if (!guide) { row?.remove(); DATA.delete(viewKey); return; }
  DATA.set(viewKey, { guide, terms, label, group });
  ensureVideos();
  if (!row) {
    row = document.createElement("div");
    row.className = "q-howto-top";
    row.addEventListener("click", (e) => {
      const b = e.target.closest("[data-howto-open]");
      if (b) open(viewKey, b, { play: b.dataset.howtoOpen === "video" });
    });
    viewEl.prepend(row);
  }
  row.innerHTML = topRowHtml(viewKey, { group, label, video: videoFor(viewKey) });
}

function ensureDialog() {
  if (dialog) return dialog;
  dialog = document.createElement("dialog");
  dialog.id = "q-howto-dialog";
  dialog.setAttribute("aria-labelledby", "q-howto-title");
  document.body.appendChild(dialog);
  dialog.addEventListener("click", onDialogClick);
  // Esc — 창 안 용어 카드가 떠 있으면 사용법으로 먼저 돌아간다(다음 Esc 에 닫힘)
  dialog.addEventListener("cancel", (e) => {
    if (!termViewOpen()) return;
    e.preventDefault();
    backToGuide();
  });
  dialog.addEventListener("close", () => {
    dialog.querySelectorAll("video").forEach((v) => v.pause());   // 닫힌 창 뒤에서 영상이 계속 돌지 않게
    termSeq++;                                     // 받는 중인 용어 응답은 버린다
    if (trigger?.isConnected) trigger.focus();
    trigger = null;
  });
  // 화면을 바꾸면 닫는다(그 화면의 단추는 숨으므로 초점은 돌려주지 않는다)
  document.addEventListener("lumina:view-changed", () => {
    if (!dialog.open) return;
    trigger = null;
    dialog.close();
  });
  return dialog;
}

function open(viewKey, button, { play = false } = {}) {
  const d = DATA.get(viewKey);
  if (!d) return;
  const dlg = ensureDialog();
  const video = videoFor(viewKey);
  dlg.className = `q-howto-dialog q-howto-dialog--${sizeOf(viewKey, d.guide, { video })}`;
  dlg.dataset.view = viewKey;
  dlg.innerHTML = howtoHtml(viewKey, d.guide, { terms: d.terms, label: d.label, video });
  trigger = button || null;
  if (!dlg.open) dlg.showModal();
  if (play) dlg.querySelector("[data-howto-video]")?.click();
}

function close() {
  if (dialog?.open) dialog.close();
}

function onDialogClick(e) {
  // 덮개(창 바깥)를 누르면 닫는다 — 창 안 빈 곳은 그대로
  if (e.target === dialog) {
    const r = dialog.getBoundingClientRect();
    if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) dialog.close();
    return;
  }
  const t = e.target.closest("[data-howto], [data-howto-term], [data-howto-video]");
  if (!t) return;
  if (t.dataset.howto === "close") return dialog.close();
  if (t.dataset.howto === "back") return backToGuide();
  if (t.dataset.howto === "leave") { trigger = null; dialog.close(); return; }   // 앱 안 다른 화면으로 — 닫고 이동
  if (t.dataset.howtoTerm) return showTerm(t.dataset.howtoTerm);
  if (t.dataset.howtoVideo) return playVideo(t);
}

function playVideo(btn) {
  const v = videoFor(btn.dataset.howtoVideo);
  if (!v) return;
  const wrap = btn.closest(".q-howto-video");
  wrap.innerHTML = playerHtml(v);                  // 그 화면이 나오는 장부터(#t=) · 장 단추 · 장 표시
  const video = wrap.querySelector("video");
  const chaps = [...wrap.querySelectorAll("[data-howto-chap]")];
  const badge = wrap.querySelector(".q-howto-chapbadge");
  let shown = v.startChapter;
  const mark = () => {
    const k = chapterIndexAt(v.chapters, video.currentTime);
    if (k === shown) return;
    shown = k;
    chaps.forEach((b, i) => (i === k ? b.setAttribute("aria-current", "true") : b.removeAttribute("aria-current")));
    if (badge) badge.textContent = chapterBadge(k, v.chapters.length);
  };
  video.addEventListener("timeupdate", mark);
  video.addEventListener("seeked", mark);
  wrap.addEventListener("click", (e) => {
    const b = e.target.closest("[data-howto-chap]");
    const ch = b && v.chapters[Number(b.dataset.howtoChap)];
    if (!ch) return;
    video.currentTime = ch.start;
    video.play().catch(() => { /* 자동 재생이 막히면 재생 단추를 누르면 된다 */ });
  });
  video.play().catch(() => { /* 자동 재생이 막히면 재생 단추를 누르면 된다 */ });
}

function termViewOpen() {
  const tv = dialog?.querySelector(".q-howto-termview");
  return Boolean(tv && !tv.hidden);
}

function showTerm(key) {
  const d = DATA.get(dialog.dataset.view);
  const fallback = d?.terms?.[key] || null;
  dialog.querySelector(".q-howto-guide").hidden = true;
  const tv = dialog.querySelector(".q-howto-termview");
  tv.hidden = false;
  tv.innerHTML = `<button type="button" class="q-howto-back" data-howto="back">← 사용법으로</button>
    <div class="q-howto-termcard"><div class="q-term-loading" aria-label="불러오는 중"><span></span><span></span><span></span></div></div>`;
  tv.querySelector(".q-howto-back").focus();
  const card = tv.querySelector(".q-howto-termcard");
  const mine = ++termSeq;
  fillTermCard(card, key, {
    label: fallback?.title || "",
    fallback,
    onTerm: (k) => showTerm(k),                    // 연관 개념도 창 안에서 연다
    isCurrent: () => mine === termSeq && termViewOpen(),
  }).then((drawn) => {
    if (drawn) card.querySelector(".q-term-retry")?.addEventListener("click", () => showTerm(key));
  });
}

function backToGuide() {
  termSeq++;
  const tv = dialog.querySelector(".q-howto-termview");
  tv.hidden = true;
  tv.replaceChildren();
  dialog.querySelector(".q-howto-guide").hidden = false;
  dialog.querySelector("#q-howto-title")?.focus();
}

window.QHowto = { render, open: (viewKey) => open(viewKey, null), close };
