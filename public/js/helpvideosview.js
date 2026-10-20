/* 사용법 영상 목록 — 차례 · 다음 편 · 그릴 HTML 을 정하는 곳(2026-10-20 · D132 둘째 단계)
 *
 * 결정(Figma 「Qurious · 메뉴 개편 · 영상 보기 자리」 10-3 · 10-4 · 07 결정 기록 — 다섯 모두 추천대로):
 *   - 자리 = 개념 학습 묶음 첫 줄 「사용법 영상」(앱 안 화면) · 영상 파일이 하나도 없는 PC 에서는 메뉴 줄째 숨긴다
 *   - 왼쪽 = 지금 편(영상 · 장 단추 · 「이 화면 열기 →」 · 「다음 →」) · 오른쪽 = 차례 · 바닥 고지 한 줄
 *   - 차례는 두 묶음 — 여정(V · 처음 쓰는 사람이 지나는 차례) · 기능(F). 시안(10-18)은 여정 일곱 편뿐이었고,
 *     기능 영상 여덟 편(10-18 밤에 찍음)을 같은 목록 아래 묶음으로 더했다.
 *
 * 영상 표(/help/videos.json)는 사용법 창과 같은 표 하나다 — 편 하나의 꼴은 howtoview.js 의 videoById 한 곳에서 만든다
 * (두 화면이 같은 영상을 다르게 읽지 않게). 이 파일은 DOM · 서버를 모른다 — 시험이 node 로 그대로 불러 돌린다(TC-HV).
 */
import { esc, fmtTime, playerHtml, videoById } from "./howtoview.js";

// 바닥 고지(10-3 시안 ④) — 영상 속 주문은 모두 앱 안 모의 계좌다
export const LIST_NOTE = "영상 속 주문은 모두 모의 계좌입니다 · 투자 권유가 아닙니다";
// 끝까지 본 편(✓) — 이 브라우저에만 남긴다(10-3 시안 ③ · 못 남겨도 화면은 그대로)
export const WATCHED_KEY = "q-help-videos-watched";

// 편 이름의 앞 글자 → 묶음. 차례는 묶음 차례 → 번호 차례.
export const GROUPS = Object.freeze([
  Object.freeze({ key: "journey", prefix: "V", title: "로보 어드바이저 처음부터 끝까지", hint: "쓰는 순서" }),
  Object.freeze({ key: "feature", prefix: "F", title: "기능 영상", hint: "기능마다 한 편" }),
]);
const ID_RE = /^([VF])(\d{2})-/;
const KO_COUNT = ["", "한", "두", "세", "네", "다섯", "여섯", "일곱", "여덟", "아홉", "열", "열한", "열두", "열세", "열네", "열다섯"];

/** 그 편을 첫 장부터 쓰는 화면 키 — 표의 화면 줄 가운데 가장 앞 장 · 같으면 화면 키 글자 차례. 없으면 "". */
export function viewOfVideo(id, manifest) {
  let best = null;
  for (const [key, ref] of Object.entries(manifest?.views || {})) {
    if (ref?.video !== id) continue;
    const ch = Math.max(0, Math.trunc(Number(ref.chapter) || 0));
    if (!best || ch < best.ch || (ch === best.ch && key < best.key)) best = { key, ch };
  }
  return best ? best.key : "";
}

/** 편 목록 — [{ id, group, num, n, title, video, view }] · 여정 → 기능 · 번호 차례 · n 은 묶음 안 차례(1부터).
 *  표가 없거나(영상을 받지 않은 PC — 서버가 { missing } 을 준다) 꼴이 틀린 편은 빼고, 하나도 없으면 빈 목록. */
export function listOf(manifest) {
  if (!manifest || manifest.missing) return [];
  const items = [];
  for (const id of Object.keys(manifest.videos || {})) {
    const m = ID_RE.exec(id);
    if (!m) continue;
    const video = videoById(id, manifest, 0);
    if (!video) continue;
    const group = GROUPS.find((g) => g.prefix === m[1]).key;
    items.push({ id, group, num: Number(m[2]), title: String(manifest.videos[id].title || id), video, view: viewOfVideo(id, manifest) });
  }
  const order = Object.fromEntries(GROUPS.map((g, i) => [g.key, i]));
  items.sort((a, b) => order[a.group] - order[b.group] || a.num - b.num || (a.id < b.id ? -1 : 1));
  const seen = {};
  for (const it of items) it.n = (seen[it.group] = (seen[it.group] || 0) + 1);
  return items;
}

/** 묶음 한 줄 요약 — 「일곱 편 · 모두 5분 46초 · 한국어 자막」(자막이 있는 편이 하나라도 있으면 자막 말을 붙인다). */
export function groupSummary(items, groupKey) {
  const g = items.filter((it) => it.group === groupKey);
  if (!g.length) return "";
  const total = Math.floor(g.reduce((s, it) => s + (Number(it.video.durationSec) || 0), 0));
  const m = Math.floor(total / 60);
  const s = total % 60;
  const time = m ? `${m}분${s ? ` ${s}초` : ""}` : `${s}초`;
  const count = KO_COUNT[g.length] ? `${KO_COUNT[g.length]} 편` : `${g.length}편`;
  return [count, `모두 ${time}`, g.some((it) => it.video.captions) ? "한국어 자막" : ""].filter(Boolean).join(" · ");
}

/** 다음 편 — 목록 차례로 다음(묶음을 넘어간다) · 끝이면 null. */
export function nextOf(items, id) {
  const i = items.findIndex((it) => it.id === id);
  return i >= 0 && i + 1 < items.length ? items[i + 1] : null;
}

/** 처음 열 편 — 고른 편이 목록에 있으면 그것 · 아니면 아직 끝까지 보지 않은 첫 편 · 모두 봤으면 첫 편. 빈 목록이면 null. */
export function initialOf(items, wantId, watched) {
  if (!items.length) return null;
  const want = items.find((it) => it.id === wantId);
  if (want) return want;
  const seen = watched instanceof Set ? watched : new Set();
  return items.find((it) => !seen.has(it.id)) || items[0];
}

/** 왼쪽 칸 — 묶음 제목 · 요약 · 영상(장 단추) · 편 제목 · 이 영상의 화면 · 다음 행동 단추.
 *  pathLabel 은 core.js 메뉴 이름(「로보 어드바이저 › 투자 성향별 상품 안내」) · canOpen 은 그 화면이 앱에 있을 때만. */
export function stageHtml(item, items, { pathLabel = "", canOpen = false } = {}) {
  const group = GROUPS.find((g) => g.key === item.group);
  const count = items.filter((it) => it.group === item.group).length;
  const next = nextOf(items, item.id);
  const where = item.view && pathLabel
    ? `<p class="hv-where">이 영상의 화면 <b>${esc(pathLabel)}</b></p>` : "";
  const open = item.view && canOpen
    ? `<button type="button" class="btn-primary" data-hv-open="${esc(item.view)}">이 화면 열기 →</button>` : "";
  const nextBtn = next
    ? `<button type="button" class="btn-secondary" data-hv-next="${esc(next.id)}">다음: ${esc(next.title)} →</button>` : "";
  return `<div class="hv-head"><h2 class="hv-title">${esc(group.title)}</h2>`
    + `<p class="hv-sub">${esc(groupSummary(items, item.group))}</p></div>`
    + playerHtml(item.video)
    + `<h3 class="hv-ep"><span class="hv-ep-n">${item.n} / ${count} 편</span>${esc(item.title)} <small>${esc(item.video.duration)}</small></h3>`
    + where
    + (open || nextBtn ? `<div class="hv-actions">${open}${nextBtn}</div>` : "");
}

/** 오른쪽 칸 — 묶음마다 차례(지금 편은 aria-current · 끝까지 본 편은 ✓) + 바닥 고지. */
export function queueHtml(items, currentId, watched) {
  const seen = watched instanceof Set ? watched : new Set();
  const groups = GROUPS.map((g) => {
    const rows = items.filter((it) => it.group === g.key).map((it) => {
      const done = seen.has(it.id);
      const mark = done ? `<i class="fa-solid fa-check" aria-hidden="true"></i><span class="sr-only">끝까지 봄</span>` : String(it.n);
      return `<li><button type="button" class="hv-item${done ? " is-watched" : ""}" data-hv-id="${esc(it.id)}"`
        + `${it.id === currentId ? ' aria-current="true"' : ""}>`
        + `<span class="hv-num">${mark}</span><span class="hv-name">${esc(it.title)}</span>`
        + `<small class="hv-len">${esc(fmtTime(it.video.durationSec))}</small></button></li>`;
    }).join("");
    return rows ? `<section class="hv-group"><h3 class="hv-qh">${esc(g.title)} <small>${esc(g.hint)}</small></h3><ol class="hv-list">${rows}</ol></section>` : "";
  }).join("");
  return `<h2 class="hv-qtitle">차례</h2>${groups}<p class="hv-note"><i class="fa-solid fa-circle-info" aria-hidden="true"></i> ${esc(LIST_NOTE)}</p>`;
}
