/* 내 계정 — 마이페이지 (2026-09-30)
 *
 * 화면   app.html 의 data-view="mypage" (더보기 › 내 계정 · 머리글의 이름을 눌러도 온다)
 * API    app/routes/auth.py 의 「계정 관리」 절 — GET /api/me · PATCH /api/me · PUT /api/me/password
 *        · GET /api/sessions · DELETE /api/sessions · DELETE /api/me · GET /api/auth/password-policy
 * 규칙   app/services/account.py (이메일 소문자 · 비밀번호 규칙 · 탈퇴 때 데이터 파기)
 *
 * 왜 이렇게 만들었나
 *  - 비밀번호 바꾸기 · 탈퇴는 현재 비밀번호를 다시 받는다 — OWASP 인증 치트시트의 「민감한 변경 전 재인증」.
 *  - 탈퇴는 가입보다 어렵지 않게 — 개인정보 보호법 제38조 제4항. 이 화면 하나에서 비밀번호 + 확인 문구로 끝난다.
 *  - 비밀번호 규칙은 서버가 내려준 값(/api/auth/password-policy)으로 안내 · 검사한다 — 규칙이 서버 한 곳에만 있게.
 *    화면 검사는 편의일 뿐이고, 같은 검사를 서버가 다시 한다.
 *  - 이름 · 이메일은 textContent 로만 넣는다 — 사용자가 넣은 글자가 HTML 로 해석되지 않게(XSS).
 */
import { api, escHtml, setToast } from "/js/common.js";
import { getTermView, setTermView, TERM_VIEWS } from "/js/termcard.js";

let bound = false;        // 폼 이벤트는 한 번만 붙인다(화면에 다시 들어올 때마다 붙이면 제출이 여러 번 된다)
let policy = null;        // 서버의 비밀번호 규칙 — 처음 한 번만 받는다

const $ = (id) => document.getElementById(id);

/** 화면이 켜질 때마다 main.js 가 부른다 — 이 화면이 아니면 아무것도 안 한다. */
export async function onMyPageActivated(view) {
  if (view !== "mypage") return;
  bindOnce();
  ensureDisplaySettings();
  await loadMyPage();
}

/* 화면 설정 — 다른 화면에서 용어를 누르면 뜨는 풀이의 모양(2026-10-02 화면 설계 결정 ②).
 * 기본은 오른쪽 서랍. 이 브라우저에 저장한다(계정에 저장하는 것은 다음 — 기기마다 화면 크기가 달라 기기별 값도 쓸모 있다).
 * 카드는 화면 HTML 이 아니라 여기서 붙인다 — app.html 은 강사님 기초 코드라 고칠 곳을 줄인다. */
function ensureDisplaySettings() {
  const host = document.querySelector('.view[data-view="mypage"] .space-y-4');
  if (!host || document.getElementById("mp-display")) return;
  const card = document.createElement("div");
  card.className = "card space-y-3";
  card.id = "mp-display";
  const now = getTermView();
  card.innerHTML = `<h2 class="text-lg font-semibold">🖥️ 화면 설정</h2>
    <fieldset class="space-y-2"><legend class="text-sm font-medium">용어를 누르면 풀이를 어디에 보여 줄까요?</legend>
      ${TERM_VIEWS.map(v => `<label class="flex items-start gap-2 text-sm cursor-pointer">
        <input type="radio" name="mp-term-view" value="${v.value}" ${v.value === now ? "checked" : ""} class="mt-1" />
        <span><strong>${escHtml(v.label)}</strong> <span class="text-slate-400">— ${escHtml(v.hint)}</span></span></label>`).join("")}
      <p class="text-xs text-slate-400">풀이에 표 · 그림이 있거나 글이 길면 창을 자동으로 넓힙니다. 이 브라우저에만 저장됩니다.</p>
    </fieldset>
    <button type="button" class="btn-secondary text-xs" id="mp-term-try">지금 설정으로 열어 보기 — 「샤프 비율」</button>`;
  host.insertBefore(card, host.children[1] || null);
  card.querySelectorAll('input[name="mp-term-view"]').forEach(r => r.addEventListener("change", () => {
    setTermView(r.value);
    setToast(`용어 풀이를 「${TERM_VIEWS.find(v => v.value === r.value).label}」 에 보여 줍니다`, "ok");
  }));
  $("mp-term-try").addEventListener("click", () => window.QTerm?.open("sharpe"));
}

async function loadMyPage() {
  try {
    const [{ user }, sessions] = await Promise.all([
      api("/api/me"),
      api("/api/sessions").catch(() => null),   // 세션 수는 못 받아도 화면은 그린다
    ]);
    $("mp-name").textContent = user.name || "-";
    $("mp-email").textContent = user.email || "-";
    $("mp-created").textContent = user.createdAt ? new Date(user.createdAt).toLocaleString("ko-KR") : "-";
    $("mp-roles").textContent = (user.roles || []).join(", ") || "-";
    $("mp-name-input").value = user.name || "";
    $("mp-sessions").textContent = sessions
      ? `지금 로그인된 기기(브라우저) ${sessions.count}곳`
      : "로그인된 기기 수를 불러오지 못했습니다.";
  } catch (err) {
    setToast(`내 정보를 불러오지 못했습니다: ${err.message}`, "error");
  }
  if (!policy) {
    policy = await api("/api/auth/password-policy").catch(() => null);
  }
  const ul = $("mp-pw-rules");
  ul.innerHTML = "";
  for (const rule of policy?.rules || ["8자 이상"]) {
    const li = document.createElement("li");
    li.textContent = rule;
    ul.appendChild(li);
  }
  if (policy) {
    for (const id of ["mp-pw-new", "mp-pw-new2"]) {
      $(id).minLength = policy.min_length;
      $(id).maxLength = policy.max_length;
    }
  }
}

/** 새 비밀번호를 서버에 보내기 전에 화면에서 먼저 본다 — 틀리면 이유 한 줄, 맞으면 null. */
function precheckNewPassword(pw, pw2) {
  if (pw !== pw2) return "새 비밀번호 두 칸이 서로 다릅니다.";
  if (!policy) return null;
  if (pw.length < policy.min_length) return `새 비밀번호는 ${policy.min_length}자 이상이어야 합니다.`;
  // 한글은 UTF-8 에서 한 글자 3바이트 — 글자 수가 아니라 바이트로 잰다(bcrypt 72바이트 한계).
  if (new TextEncoder().encode(pw).length > policy.max_bytes) {
    return `새 비밀번호가 너무 깁니다 — ${policy.max_bytes}바이트(영문 72자 · 한글 24자) 이하로 입력하세요.`;
  }
  return null;
}

function bindOnce() {
  if (bound) return;
  bound = true;

  // 이름 바꾸기 → 머리글의 이름 · 아바타도 바로 바꾼다
  $("mp-name-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const { user } = await api("/api/me", { method: "PATCH", body: { name: $("mp-name-input").value } });
      $("mp-name").textContent = user.name;
      $("user-name").textContent = user.name;
      const avatar = $("user-avatar");
      if (avatar) avatar.textContent = (user.name || "U").charAt(0).toUpperCase();
      setToast("이름을 바꿨습니다.");
    } catch (err) {
      setToast(err.message, "error");
    }
  });

  // 비밀번호 바꾸기 → 서버가 이 기기에 새 세션을 주고(쿠키가 바뀜) 다른 기기를 로그아웃시킨다
  $("mp-pw-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const current = $("mp-pw-current").value;
    const pw = $("mp-pw-new").value;
    const problem = precheckNewPassword(pw, $("mp-pw-new2").value);
    if (problem) { setToast(problem, "error"); return; }
    try {
      const res = await api("/api/me/password", { method: "PUT", body: { current_password: current, new_password: pw } });
      e.target.reset();
      setToast(`비밀번호를 바꿨습니다 — 다른 기기 ${res.other_sessions_revoked}곳은 로그아웃됐습니다.`);
      await loadMyPage();
    } catch (err) {
      setToast(err.message, "error");
    }
  });

  // 모든 기기에서 로그아웃 — 이 기기도 포함이라 로그인 화면으로 간다
  $("mp-logout-all").addEventListener("click", async () => {
    if (!window.confirm("이 기기를 포함한 모든 기기에서 로그아웃할까요?")) return;
    try {
      await api("/api/sessions", { method: "DELETE" });
    } catch (err) {
      setToast(err.message, "error");
      return;
    }
    location.replace("/login.html");
  });

  // 회원 탈퇴 — 확인 문구 · 비밀번호 · 한 번 더 묻기. 성공하면 뒤로가기로 앱에 못 돌아오게 기록을 바꿔 치운다.
  $("mp-delete-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const confirmText = $("mp-del-confirm").value.trim();
    if (confirmText !== "탈퇴") { setToast("확인 칸에 「탈퇴」 를 입력하세요.", "error"); return; }
    if (!window.confirm("정말 탈퇴할까요? 모의투자 · 자동매매 장부와 설정이 즉시 삭제되고 되돌릴 수 없습니다.")) return;
    try {
      await api("/api/me", { method: "DELETE", body: { password: $("mp-del-pw").value, confirm: confirmText } });
    } catch (err) {
      setToast(err.message, "error");
      return;
    }
    window.alert("탈퇴했습니다. 그동안 이용해 주셔서 감사합니다.");
    location.replace("/login.html");
  });
}
