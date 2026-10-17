/* 글 끝 「이 글의 용어」 칩 줄 — 글 속 용어를 서버가 찾아 주면 칩으로 붙이고, 누르면 용어 풀이(서랍)를 연다
 * (2026-10-17 · Figma 「AI 투자 상담 — 근거 답과 출처」 03-2 [결정] 용어 칩 (가) 글 끝 칩 줄 · 모의투자 점검 L5).
 *
 * 왜 글 끝인가 — AI 답 글을 건드리지 않는다(몰래 고치지 않음). 잘못 찾은 용어가 있어도 끝 줄이라 덜 거슬린다.
 * 찾는 규칙(띄어쓰기 접기 · 영문은 대문자 약어만 · 짧은 한글은 금융 고유어만 · 겹치면 긴 이름 · 같은 용어는 한 번)은 서버 한 곳
 * (POST /api/glossary/scan — app/services/glossary_scan.py · text_match.py)이 정한다 — 이 파일은 그리고 잇기만 한다.
 * 다른 화면(차트 패턴 · 스크리닝 · 상품 상세 — 다른 주담당 화면 포함)도 같은 부품을 부를 수 있게 따로 둔다:
 *   import { appendTermChips } from "/js/termchips.js";
 *   appendTermChips(칩 줄을 붙일 칸, 글, { label: "이 글의 용어" });   // 찾은 용어가 없으면 아무것도 그리지 않는다
 */
import { api, escHtml } from "/js/common.js";
import { openTerm } from "/js/termcard.js";

/** 서버 POST /api/glossary/scan 의 글 상한(glossary_scan.MAX_TEXT) — 넘기면 422 라 보내기 전에 자른다(화면 → API 상한 · TC-TCH) */
export const TERM_SCAN_MAX = 4000;
/** 칩 수 상한 — 결정 「최대 여섯」(서버 상한 MAX_LIMIT 안) */
export const TERM_CHIPS_MAX = 6;

/** host 끝에 칩 줄을 붙인다 → 붙인 줄(없으면 null). 찾은 용어가 없거나 찾기가 실패하면 줄을 그리지 않는다 — 글은 그대로 둔다. */
export async function appendTermChips(host, text, { label = "이 글의 용어", limit = TERM_CHIPS_MAX } = {}) {
  if (!host || !String(text || "").trim()) return null;
  let items = [];
  try {
    const res = await api("/api/glossary/scan", { method: "POST", body: { text: String(text).slice(0, TERM_SCAN_MAX), limit } });
    items = res.items || [];
  } catch (err) {
    console.warn("글 속 용어를 찾지 못해 용어 칩 줄을 그리지 않았습니다:", err.message);
    return null;
  }
  if (!items.length) return null;
  const row = document.createElement("div");
  row.className = "q-term-chips";
  row.innerHTML = `<span class="q-term-chips-label">${escHtml(label)}</span>` + items.map(t =>
    `<button type="button" class="q-term-chip q-term-chip--link" data-term="${escHtml(t.id)}" title="${escHtml(t.summary || "")}">${escHtml(t.term)} ›</button>`).join("");
  row.querySelectorAll("[data-term]").forEach(b => b.addEventListener("click", () => openTerm(b.dataset.term)));
  host.appendChild(row);
  return row;
}
