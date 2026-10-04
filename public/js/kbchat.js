/* AI 투자 상담 · 근거 답 — 답 아래 출처 카드와 처음 엔진 「자동 — 근거 먼저」 (목표 기능 ① W6 화면)
 *
 * 무엇을 하나
 *   강사님 채팅 화면(agent.js · 화면 agent-chat)의 「답변 엔진」 에 두 칸을 더하고, 그 두 칸의 답을 그린다.
 *   - auto 「자동 — 근거 먼저」(처음 엔진): 근거 답(POST /api/kb/ask)을 먼저 부르고, 근거 문서(법령 · 감독규정)에
 *     없는 질문이면(no_evidence) Local Ollama 채팅(POST /api/chat)이 이어 받는다. 그 답에는 「출처 없는 일반 AI 답」
 *     표시를 붙인다 — 넘어갔다는 것을 숨기지 않는다. 가격 예측 · 매수 권유(declined)는 넘기지 않는다.
 *   - kb 「근거 답 — 법령 · 규정 출처」: 근거 답만. 근거가 없으면 「일반 AI 에게 묻기」 단추.
 *   - 다른 엔진(Local Ollama · OpenAI · 순수 RAG)의 답 아래에는 「근거 답으로 다시 묻기」 단추(afterChatAnswer).
 *
 * 답 모양(안 A · 답 아래 카드)
 *   답 바로 아래 번호 카드 — 답에 쓴 근거는 조문 글(excerpt)을 펼치고, 함께 찾은 근거는 한 줄씩 접어 둔다.
 *   본문의 출처 번호를 누르면 그 카드가 펼쳐지며 밝아진다. 답이 틀릴 수 있어(번호가 맞아도 잘못 읽음 · 결함 DF-59)
 *   함께 찾은 근거까지 사람이 조문으로 확인할 수 있게 하는 것이 목표다.
 *
 * 결정 · 근거: Figma 「Qurious · AI 투자 상담 — 근거 답과 출처」 05 결정 기록(2026-10-04) · 목표 기능 ① 설계서 v1.0
 *   5.3.4 · 5.3.6 · 조사서 「근거 답의 출처 표시 화면」.
 * 강사님 파일(agent.js)에는 가져오기 · 보내기 갈림만 두고 그리기는 모두 여기서 한다 — 다음 기초 코드 반영 때 충돌을 줄이려고.
 */
import { api, setToast, escHtml } from "/js/common.js";

export const KB_MODES = new Set(["auto", "kb"]);
/** 서버 AskBody.q 의 max_length — 넘으면 422 이므로 보내기 전에 막는다(화면 → API 상한) */
export const MAX_Q = 300;
const ENGINE_OPTIONS = [
  ["auto", "자동 — 근거 먼저 (없으면 Local Ollama)"],
  ["kb", "근거 답 — 법령 · 규정 출처"],
];
const EXAMPLES = ["2026년 코스피 증권거래세율은?", "배당소득에는 어떤 소득이 포함되나요?", "투자를 권유할 때 설명의무는 무엇인가요?"];
const GENERAL_NOTE = "근거 문서(법령 · 감독규정)에 없는 질문이라 Local Ollama 가 답했습니다. 사실 여부를 따로 확인하세요.";

// ── 1. 답변 엔진 칸 ──────────────────────────────────────────────────
// agent.js 가 저장해 둔 엔진을 되살리기 전에 칸이 있어야 한다 → 이 모듈을 불러올 때(agent.js 본문보다 먼저) 바로 더한다.
function addEngineOptions() {
  const sel = document.getElementById("chat-llm-mode");
  if (!sel || sel.querySelector('option[value="auto"]')) return;
  [...ENGINE_OPTIONS].reverse().forEach(([value, label]) => sel.insertBefore(new Option(label, value), sel.firstChild));
  sel.value = "auto";   // 저장값이 없을 때의 처음 엔진(결정 ③ ㄱ) — 저장값이 있으면 agent.js 가 그것으로 바꾼다
}
addEngineOptions();

/** 답변 엔진마다 입력칸 안내 — 근거 답 칸이 아니면 빈 글자(agent.js 가 원래 안내를 쓴다) */
export function placeholderFor(mode) {
  if (mode === "auto") return "법 · 규정 질문은 근거 조문과 함께, 그 밖의 질문은 일반 AI 가 답합니다. 예) 2026년 코스피 증권거래세율은?";
  if (mode === "kb") return "법 · 규정을 물어보세요 — 답 아래에 근거 조문이 붙습니다. 예) 배당소득에는 어떤 소득이 포함되나요?";
  return "";
}

// ── 2. 작은 부품 ─────────────────────────────────────────────────────
function el(tag, cls, html) {
  const d = document.createElement(tag);
  if (cls) d.className = cls;
  if (html != null) d.innerHTML = html;
  return d;
}

function scrollBottom() {
  const box = document.getElementById("chat-messages");
  if (box) box.scrollTop = box.scrollHeight;
}

/** 답 말풍선 하나를 대화 끝에 붙인다(강사님 채팅과 같은 왼쪽 정렬) */
function appendBubble(box, cls) {
  const row = el("div", "flex justify-start");
  const bubble = el("div", `kb-bubble${cls ? " " + cls : ""}`);
  row.appendChild(bubble);
  box.appendChild(row);
  return bubble;
}

/** 기다리는 동안 — 무엇을 하는 중인지와 걸린 초를 1초마다 보인다(근거 답 약 25초 · 일반 AI 약 70초 · 이 PC 실측) */
function startWaiting(box, label) {
  const row = el("div", "flex justify-start");
  const b = el("div", "kb-wait");
  row.appendChild(b);
  box.appendChild(row);
  const t0 = Date.now();
  const draw = () => {
    b.innerHTML = `<i class="fa-solid fa-circle-notch fa-spin"></i>${escHtml(label)} · ${Math.round((Date.now() - t0) / 1000)}초`;
  };
  draw();
  const timer = setInterval(draw, 1000);
  scrollBottom();
  return { stop() { clearInterval(timer); row.remove(); } };
}

/** 답 글의 「[출처 n]」 → 누를 수 있는 번호 단추(카드와 이어진다) */
function answerHtml(text) {
  return escHtml(text || "").replace(/\[출처 (\d+)\]/g,
    (_, n) => `<button type="button" class="kb-n" data-n="${n}" title="출처 ${n} 조문 보기">${n}</button>`);
}

function citeTitle(c) {
  return `${c.title} ${c.article}${c.article_title ? `(${c.article_title})` : ""}`;
}

function citeMeta(c) {
  const kind = c.kind === "admrul" ? "감독규정" : "법령";
  const eff = c.effective_at && !(c.version_label || "").includes(c.effective_at) ? ` · ${c.effective_at} 시행` : "";
  return `${c.version_label || ""}${eff} · ${kind}(등급 ${c.grade}) · ${c.used ? "답에 씀" : "함께 찾음"}`;
}

function setOpen(card, open) {
  card.classList.toggle("is-open", open);
  card.querySelector(".kb-src-head")?.setAttribute("aria-expanded", String(open));
}

/** 출처 카드 하나 — 머리(번호 · 문서 조(제목) · 시행일)를 누르면 조문 글이 펼쳐지고 접힌다 */
function sourceCard(c, open) {
  const card = el("div", `kb-src${c.used ? "" : " kb-src--extra"}`);
  card.dataset.n = String(c.n);
  const link = c.url
    ? `<a class="kb-src-link" href="${escHtml(c.url)}" target="_blank" rel="noopener noreferrer">원문 보기 ↗</a>` : "";
  card.innerHTML = `
    <button type="button" class="kb-src-head" aria-expanded="false">
      <span class="kb-n${c.used ? "" : " kb-n--ghost"}">${c.n}</span>
      <span class="kb-src-title">${escHtml(citeTitle(c))}</span>
      <span class="kb-src-eff">${escHtml(c.effective_at || "")} 시행</span>
    </button>
    <div class="kb-src-body">
      <div class="kb-src-meta">${escHtml(citeMeta(c))}${link}</div>
      <div class="kb-quote">${escHtml(c.excerpt || "조문 글이 없습니다 — 원문 보기로 확인하세요.")}</div>
    </div>`;
  card.querySelector(".kb-src-head").addEventListener("click", () => setOpen(card, !card.classList.contains("is-open")));
  setOpen(card, open);
  return card;
}

/** 출처 묶음 — 맨 위 한 줄(쓴 근거 · 함께 찾은 근거 수) · 쓴 근거는 펼침 · 함께 찾은 근거는 한 줄씩 */
function sourcesBlock(citations, { usedLabel = "답에 쓴 근거", extraLabel = "함께 찾은 근거", openExtra = true } = {}) {
  const used = citations.filter(c => c.used);
  const extra = citations.filter(c => !c.used);
  const wrap = el("div", "kb-srcs");
  wrap.appendChild(el("div", "kb-srcs-h", `<b>${usedLabel} ${used.length}</b> · ${extraLabel} ${extra.length}`));
  used.forEach(c => wrap.appendChild(sourceCard(c, true)));
  if (extra.length) {
    const more = el("button", "kb-more", `${extraLabel} ${extra.length}개 <span aria-hidden="true">▾</span>`);
    more.type = "button";
    const list = el("div", "kb-extra");
    extra.forEach(c => list.appendChild(sourceCard(c, false)));
    list.hidden = !openExtra;
    more.classList.toggle("is-closed", list.hidden);
    more.addEventListener("click", () => { list.hidden = !list.hidden; more.classList.toggle("is-closed", list.hidden); });
    wrap.append(more, list);
  }
  return wrap;
}

/** 본문 번호를 누르면 — 그 카드를 펼치고(접힌 목록이면 목록부터) 잠깐 밝힌다 */
function focusCard(bubble, n) {
  const card = bubble.querySelector(`.kb-src[data-n="${n}"]`);
  if (!card) return;
  const list = card.closest(".kb-extra");
  if (list && list.hidden) {
    list.hidden = false;
    list.previousElementSibling?.classList.remove("is-closed");
  }
  setOpen(card, true);
  card.classList.add("is-flash");
  card.scrollIntoView({ block: "nearest", behavior: "smooth" });
  setTimeout(() => card.classList.remove("is-flash"), 1400);
}

function footHtml(res, { excerpt = false } = {}) {
  const parts = [];
  if (res.model) parts.push(`답 모델 ${escHtml(res.model)}`);
  if (res.timing?.total_ms != null) parts.push(`${(res.timing.total_ms / 1000).toFixed(1)}초`);
  parts.push(`<span class="kb-warn">답이 근거와 맞는지 조문을 열어 확인하세요.</span>`);
  if (res.check?.invalid?.length) parts.push(`근거 목록 밖의 출처 번호 ${res.check.invalid.length}개를 지웠습니다`);
  let html = parts.join(" · ");
  if (excerpt && res.reason) html += `<br>까닭: ${escHtml(res.reason)}`;
  if (res.notice) html += `<br>${escHtml(res.notice)}`;
  return html;
}

/** 근거 발췌일 때 맨 위 한 줄 — 왜 LLM 글 대신 조문을 보이는지 */
function excerptLead(res) {
  const why = res.reason || "";
  if (res.llm?.error) return "답 모델이 응답하지 않아 찾은 조문을 그대로 보여 드립니다.";
  if (why.includes("LLM 없이")) return "근거 발췌만 요청해 찾은 조문을 그대로 보여 드립니다.";
  return "답 모델의 글을 근거로 확인할 수 없어 찾은 조문을 그대로 보여 드립니다.";
}

// ── 3. 상태마다 그리기 ───────────────────────────────────────────────
/** answered · excerpt — 답(또는 발췌 안내)과 그 아래 출처 카드 */
function renderKbAnswer(box, res) {
  const excerpt = res.status === "excerpt";
  const bubble = appendBubble(box);
  bubble.innerHTML = `
    <div class="kb-tag"><span class="kb-pill">${excerpt ? "근거 발췌" : "근거 답"}</span>기준일 ${escHtml(res.as_of)} · 그날 시행 중인 판</div>
    <div class="kb-ans">${excerpt ? escHtml(excerptLead(res)) : answerHtml(res.answer)}</div>`;
  if (res.citations?.length) {
    bubble.appendChild(sourcesBlock(res.citations, excerpt ? { usedLabel: "보여 드린 근거" } : {}));
  }
  bubble.appendChild(el("div", "kb-foot", footHtml(res, { excerpt })));
  bubble.querySelectorAll(".kb-ans .kb-n").forEach(b => b.addEventListener("click", () => focusCard(bubble, b.dataset.n)));
}

/** declined — 답하지 않는 질문 · 물을 수 있는 예시(누르면 입력칸에 넣는다) */
function renderDeclined(box, res) {
  const bubble = appendBubble(box);
  bubble.innerHTML = `
    <div class="kb-tag"><span class="kb-pill">근거 답</span>답하지 않는 질문</div>
    <div class="kb-ans">${escHtml(res.answer)}</div>
    <div class="kb-foot">이렇게 물어보세요 ${EXAMPLES.map(q => `<button type="button" class="kb-ex">${escHtml(q)}</button>`).join("")}</div>`;
  bubble.querySelectorAll(".kb-ex").forEach(b => b.addEventListener("click", () => {
    const inp = document.getElementById("chat-input");
    if (inp) { inp.value = b.textContent; inp.focus(); }
  }));
}

/** no_evidence — 자동이면 한 줄 알림(뒤이어 일반 AI 가 답한다) · 근거 답만이면 찾은 조문과 「일반 AI 에게 묻기」 */
function renderNoEvidence(box, res, { auto, onGeneral } = {}) {
  const n = res.citations?.length || 0;
  const why = n ? `찾은 조문 ${n}개 가운데 답에 쓸 근거가 없었습니다` : "근거 문서에서 관련 조문을 찾지 못했습니다";
  const bubble = appendBubble(box, auto ? "kb-bubble--line" : "");
  bubble.innerHTML = `<div class="kb-tag"><span class="kb-pill">근거 답</span>근거를 찾지 못했습니다 · ${why}</div>`;
  if (auto) return;
  if (n) bubble.appendChild(sourcesBlock(res.citations, { usedLabel: "답에 쓴 근거", extraLabel: "찾은 조문", openExtra: false }));
  const wrap = el("div", "kb-again-wrap");
  const btn = el("button", "kb-again", "일반 AI(Local Ollama)에게 묻기");
  btn.type = "button";
  btn.addEventListener("click", () => { btn.disabled = true; onGeneral?.(); });
  wrap.appendChild(btn);
  bubble.appendChild(wrap);
}

// ── 대화 스레드 — 모델이 보는 대화 = 화면에 보이는 대화 ─────────────────
// 채팅 서버는 화면이 대화 기록을 보내지 않으면(새로 연 화면의 첫 질문) 저장된 「활성 대화」 의 지난 10개를 몰래
// 문맥으로 쓴다. 화면은 비어 있는데 모델은 지난 대화를 보고, 점검 계정은 질문과 상관없이 점검 스크립트가 물었던
// 「ETF 괴리율」 을 답했다(결함 DF-60 · 2026-10-04). 그래서 화면을 새로 열거나 「초기화」 한 뒤 첫 채팅 전에 새
// 대화를 연다(강사님 API POST /api/conversations — 새 스레드를 만들고 활성으로 바꾼다 · 지난 대화는 지우지 않는다).
let freshThread = false;

/** 이 화면에서 아직 새 대화를 열지 않았으면 연다 — 열지 못해도 질문은 보낸다(대신 지난 대화가 섞일 수 있다) */
export async function ensureFreshThread() {
  if (freshThread) return;
  try {
    await api("/api/conversations", { method: "POST", body: {} });
    freshThread = true;
  } catch (e) {
    console.warn("새 대화를 열지 못했습니다 — 지난 대화가 답에 섞일 수 있습니다:", e.message);
  }
}

/** 「초기화」 — 다음 채팅 전에 새 대화를 다시 연다 */
export function resetThread() {
  freshThread = false;
}

/** 일반 AI(Local Ollama) 답 — 강사님 말풍선으로 그리고 「출처 없는 일반 AI 답」 표시를 붙인다 */
async function askGeneralAi(q, ctx) {
  const box = document.getElementById("chat-messages");
  const waiting = startWaiting(box, "근거 문서에 없는 질문이라 Local Ollama 가 답하는 중");
  try {
    await ensureFreshThread();
    const chat = await api("/api/chat", { method: "POST", body: { question: q, history: ctx.history(), llm_mode: "ollama" } });
    waiting.stop();
    ctx.pushHistory(q, chat.answer);
    ctx.appendAssistantMsg(chat.answer, chat.steps, {});
    const bubble = box.lastElementChild?.firstElementChild;
    if (bubble) {
      bubble.classList.add("kb-general");
      bubble.insertAdjacentHTML("afterbegin",
        `<div class="kb-tag"><span class="kb-pill kb-pill--general">일반 AI 답 · 출처 없음</span>Local Ollama</div>`);
      bubble.insertAdjacentHTML("beforeend", `<div class="kb-foot kb-warn">${escHtml(GENERAL_NOTE)}</div>`);
    }
  } catch (e) {
    waiting.stop();
    setToast(e.message, "error");
  }
  scrollBottom();
}

// ── 4. 보내기 ────────────────────────────────────────────────────────
/**
 * 근거 답 칸(auto · kb)의 보내기 — agent.js 의 sendChat 이 이 두 칸이면 여기로 넘긴다.
 * ctx = agent.js 가 주는 것 { appendUserMsg, appendAssistantMsg, clearInput, history, pushHistory }.
 * 질문이 길면 보내지 않고 false(입력칸을 지우지 않는다) · 보냈으면 true.
 * keepInput — 「근거 답으로 다시 묻기」 처럼 입력칸이 아닌 곳에서 보낼 때는 입력칸에 쓰던 글을 지우지 않는다.
 */
export async function sendKbChat(q, mode, ctx, { keepInput = false } = {}) {
  const box = document.getElementById("chat-messages");
  if (!box) return false;
  if (q.length > MAX_Q) {
    setToast(`질문은 ${MAX_Q}자까지 보낼 수 있습니다(지금 ${q.length}자).`, "error");
    return false;
  }
  if (!keepInput) ctx.clearInput?.();
  ctx.appendUserMsg(q);
  const waiting = startWaiting(box, "법령 · 감독규정에서 근거를 찾고 답을 쓰는 중");
  let res;
  try {
    res = await api("/api/kb/ask", { method: "POST", body: { q } });
  } catch (e) {
    waiting.stop();
    setToast(e.message, "error");
    return true;
  }
  waiting.stop();
  if (res.status === "no_evidence") {
    if (mode === "auto") {
      renderNoEvidence(box, res, { auto: true });
      scrollBottom();
      await askGeneralAi(q, ctx);
    } else {
      renderNoEvidence(box, res, { auto: false, onGeneral: () => askGeneralAi(q, ctx) });
    }
  } else if (res.status === "declined") {
    renderDeclined(box, res);   // 「자동」 이어도 일반 AI 로 넘기지 않는다(가격 예측 · 매수 권유)
  } else {
    renderKbAnswer(box, res);
  }
  scrollBottom();
  return true;
}

/** 다른 엔진(Local Ollama · OpenAI · 순수 RAG)의 답 아래 — 같은 질문을 근거 답으로 다시 묻는 단추 */
export function afterChatAnswer(q, mode, ctx) {
  if (KB_MODES.has(mode)) return;
  const bubble = document.getElementById("chat-messages")?.lastElementChild?.firstElementChild;
  if (!bubble) return;
  const wrap = el("div", "kb-again-wrap");
  const btn = el("button", "kb-again", "근거 답으로 다시 묻기");
  btn.type = "button";
  btn.addEventListener("click", () => { btn.disabled = true; sendKbChat(q, "kb", ctx, { keepInput: true }); });
  wrap.append(btn, el("span", "kb-again-note", "이 답에는 출처가 없습니다. 법 · 규정 질문은 근거 답으로 물으면 조문이 함께 나옵니다."));
  bubble.appendChild(wrap);
}
