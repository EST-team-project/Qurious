/* 화면 사용법 — 윗줄 「사용법」 단추 + 가운데 창(2026-10-16 · 결정 안 A)
 *
 * core.js 의 renderViewGuide 가 화면을 바꿀 때마다 window.QHowto.render(화면 키, 사용법 글, { terms, label, group }) 를 부른다.
 *   · 윗줄은 화면 뿌리 밖(화면의 첫 자식)에 둔다 — 화면 JS 가 머리를 다시 그려도(상품 안내 탭 · 데이터 관제 30초) 단추가 남는다.
 *   · 창은 <dialog> 하나를 showModal 로 연다 — 뒤 화면을 막고(inert) 초점을 창 안에 가두는 일을 브라우저가 한다.
 *   · 크기 · 이어 줄 장 · HTML 은 js/howtoview.js 한 곳에서 정한다(이 파일은 붙이고 여닫기만).
 *   · 용어 칩은 창 안에서 용어 카드를 그린다 — 맨 위 층 창 뒤에는 용어 서랍(QTerm)이 깔려 눌리지 않는다.
 *     받기 · 대체 글 · 다시 시도는 용어 서랍과 같은 함수(termcard.js fillTermCard)를 쓴다.
 * 무엇도 브라우저에 남기지 않는다(옛 접이식의 열림 기억을 버림) · 화면을 바꾸면 창을 닫는다.
 */
import { fillTermCard } from "/js/termcard.js";
import { howtoHtml, sizeOf, topRowHtml, VIDEOS } from "/js/howtoview.js";

const DATA = new Map();    // 화면 키 → { guide, terms, label, group } — 단추를 누를 때 읽는다
let dialog = null;
let trigger = null;        // 창을 연 단추 — 닫으면 초점을 돌려준다
let termSeq = 0;           // 용어를 연달아 누르면 앞 응답은 버린다

function render(viewKey, guide, { terms = {}, label = "", group = "" } = {}) {
  const viewEl = document.querySelector(`.view[data-view="${viewKey}"]`);
  if (!viewEl) return;
  viewEl.querySelector(":scope > .view-guide")?.remove();   // 옛 접이식(기초 코드 판)이 남아 있으면 지운다
  let row = viewEl.querySelector(":scope > .q-howto-top");
  if (!guide) { row?.remove(); DATA.delete(viewKey); return; }
  DATA.set(viewKey, { guide, terms, label, group });
  if (!row) {
    row = document.createElement("div");
    row.className = "q-howto-top";
    row.addEventListener("click", (e) => {
      const b = e.target.closest("[data-howto-open]");
      if (b) open(viewKey, b, { play: b.dataset.howtoOpen === "video" });
    });
    viewEl.prepend(row);
  }
  row.innerHTML = topRowHtml(viewKey, { group, label, video: VIDEOS[viewKey] || null });
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
  const video = VIDEOS[viewKey] || null;
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
  const v = VIDEOS[btn.dataset.howtoVideo];
  if (!v) return;
  const wrap = btn.closest(".q-howto-video");
  const video = document.createElement("video");
  video.className = "q-howto-player";
  video.controls = true;
  video.preload = "metadata";
  video.src = v.src;
  if (v.captions) {
    const track = document.createElement("track");
    Object.assign(track, { kind: "captions", srclang: "ko", label: "한국어", src: v.captions, default: true });
    video.appendChild(track);
  }
  wrap.replaceChildren(video);
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
