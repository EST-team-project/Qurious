"""AI 투자 상담 · 근거 답 화면 시험 (TC-KS) — 화면 설계 결정(Figma 「AI 투자 상담 — 근거 답과 출처」 2026-10-04)이
코드에 이어졌나.

결정 넷: ① 안 A 답 아래 카드 ② (가) 답변 엔진에 「근거 답」 칸 ③ ㄱ 처음 엔진 「자동 — 근거 먼저」(근거가 없으면
Local Ollama 가 이어 받음 · 가격 예측 · 매수 권유는 넘기지 않음) ④ 화면을 새로 열거나 초기화하면 새 대화(결함 DF-60).
화면 자체는 브라우저로 눌러 확인했다(2026-10-04 · 1280 · 390 · 콘솔 오류 0). 여기서는 사람이 놓치기 쉬운 것을 잰다.
1. 연결 — 강사님 채팅(agent.js)이 근거 답 칸을 넘기고, 다른 엔진 답 뒤 단추 · 새 대화 열기 · 초기화가 이어져 있나.
2. 규약 — 화면이 읽는 응답 칸이 서버 응답에 실제로 있나(서버가 칸 이름을 바꾸면 화면은 오류 없이 빈칸을 그린다).
   화면 → API 글자 상한이 서버와 같나(넘기면 422 — 용어사전 분류 카드 결함 DF-44 와 같은 꼴).
3. 스캐너 — API 명세서 「부르는 화면」 칸이 이 화면에 근거 답 · 채팅 · 새 대화 API 를 붙이나.
네트워크 · 실제 kb.sqlite3 · Ollama 없이 돈다(가짜 문서 DB 는 TC-KB 의 고정값).
"""
from __future__ import annotations

import re
from pathlib import Path

from app.routes import kb as kb_routes
from app.services import kb_answer
from tests.test_kb_answer import FakeLlm
from tests.test_kb_search import FakeDense, kb  # noqa: F401 — kb 는 고정값(가짜 문서 DB)

ROOT = Path(__file__).resolve().parents[1]
PUB = ROOT / "public"


def _read(rel: str) -> str:
    return (PUB / rel).read_text(encoding="utf-8")


def test_agent_js_hands_kb_engines_to_kbchat():
    """TC-KS-01 · 강사님 채팅이 근거 답 칸(auto · kb)을 kbchat 으로 넘기고, 다른 엔진 답 뒤에 「다시 묻기」 를 붙이며,
    채팅을 보내기 직전 새 대화를 열고 · 초기화하면 다시 연다 · 저장 키 이름을 바꿔 처음 엔진(자동)이 한 번 보인다."""
    src = _read("js/agent.js")
    assert 'from "/js/kbchat.js"' in src
    send = src[src.index("async function sendChat()"):src.index('document.getElementById("chat-send")')]
    kb_branch = send.index("if (KB_MODES.has(mode))")
    assert kb_branch < send.index('mode === "openai"'), "근거 답 칸은 OpenAI 키 검사보다 먼저 넘긴다"
    assert send.index("await ensureFreshThread();") < send.index('api("/api/chat"'), "새 대화를 연 뒤에 채팅을 부른다"
    assert send.index("appendAssistantMsg(res.answer") < send.index("afterChatAnswer(q,")
    clear = src[src.index('getElementById("clear-chat")'):]
    assert "resetThread();" in clear[:clear.index("});")]
    assert 'LLM_MODE_KEY = "qurious.chat.llmMode"' in src
    assert "placeholderFor(mode) ||" in src


def test_engine_options_default_auto_and_limits_match_server():
    """TC-KS-02 · 답변 엔진에 자동 · 근거 답 두 칸을 맨 앞에 · 처음 값은 자동 · 질문 글자 상한이 서버(AskBody.q)와 같다 ·
    보내는 몸통은 서버가 받는 칸(q)만."""
    src = _read("js/kbchat.js")
    block = src[src.index("const ENGINE_OPTIONS = ["):]
    block = block[:block.index("];")]
    opts = re.findall(r'\["([a-z]+)", "([^"]+)"\]', block)
    assert [o[0] for o in opts] == ["auto", "kb"]
    assert 'sel.value = "auto"' in src and "sel.firstChild" in src
    assert int(re.search(r"export const MAX_Q = (\d+);", src).group(1)) == kb_routes.AskBody.model_fields["q"].metadata[1].max_length
    bodies = re.findall(r'api\("/api/kb/ask", \{ method: "POST", body: \{ ([^}]*) \} \}\)', src)
    assert bodies == ["q"], bodies


def test_screen_reads_only_fields_the_server_sends(kb):
    """TC-KS-03 · 화면이 읽는 응답 칸(res.* · c.*)이 서버 응답(답한 때)에 모두 있다 — 출처 카드의 조문 글(excerpt) 포함."""
    src = _read("js/kbchat.js")
    res_fields = set(re.findall(r"\bres\.([a-z_]+)", src))
    cite_fields = set(re.findall(r"\bc\.([a-z_]+)", src))
    out = kb_answer.ask("2026년 증권거래세 세율은?", 3, mode="lexical", as_of="2026-10-02", path=kb, backend=FakeDense(),
                        llm_backend=FakeLlm("유가증권시장 주권은 1만분의 5입니다 [출처 1]."), llm="llama3.1")
    assert out["status"] == "answered"
    missing_res = res_fields - set(out)
    missing_cite = cite_fields - set(out["citations"][0])
    assert not missing_res, f"화면이 읽는데 응답에 없는 칸: {missing_res}"
    assert not missing_cite, f"출처 카드가 읽는데 citations 에 없는 칸: {missing_cite}"
    assert {"excerpt", "used", "url", "version_label"} <= cite_fields


def test_every_answer_status_is_drawn_and_declined_never_falls_back():
    """TC-KS-04 · 서버의 상태 넷(answered · excerpt · no_evidence · declined)을 모두 그린다 · 일반 AI 로 넘기는 것은
    no_evidence 의 자동 칸뿐이다(거절은 넘기지 않는다 — 결정 ③)."""
    server = (ROOT / "app" / "services" / "kb_answer.py").read_text(encoding="utf-8")
    statuses = set(re.findall(r'_result\([^,]+, [^,]+, "([a-z_]+)"', server))
    assert statuses == {"answered", "excerpt", "no_evidence", "declined"}
    src = _read("js/kbchat.js")
    assert 'res.status === "no_evidence"' in src and 'res.status === "declined"' in src
    assert 'res.status === "excerpt"' in src                 # 근거 발췌는 안내 한 줄 + 카드
    send = src[src.index("export async function sendKbChat"):src.index("export function afterChatAnswer")]
    declined = send[send.index('res.status === "declined"'):]
    declined = declined[:declined.index("}")]
    assert "askGeneralAi" not in declined
    no_ev = send[send.index('res.status === "no_evidence"'):send.index('res.status === "declined"')]
    assert 'mode === "auto"' in no_ev and "await askGeneralAi(q, ctx)" in no_ev


def test_general_ai_answer_is_labeled_and_opens_fresh_thread():
    """TC-KS-05 · 일반 AI 로 넘어간 답에는 「출처 없는 일반 AI 답」 꼬리표와 확인 안내 · 그 전에 새 대화를 연다(DF-60)."""
    src = _read("js/kbchat.js")
    gen = src[src.index("async function askGeneralAi"):src.index("// ── 4. 보내기")]
    assert gen.index("await ensureFreshThread();") < gen.index('api("/api/chat"')
    assert "일반 AI 답 · 출처 없음" in gen and "GENERAL_NOTE" in gen
    fresh = src[src.index("export async function ensureFreshThread"):src.index("export function resetThread")]
    assert 'api("/api/conversations", { method: "POST"' in fresh
    assert "kb-general" in _read("css/qurious.css") and ".kb-src" in _read("css/qurious.css")


def test_subtitle_does_not_promise_investment_advice():
    """TC-KS-06 · 화면 부제가 「투자 자문을 제공」 하지 않는다 — 근거 답은 정보 제공이고 안내 문구도 그렇게 말한다."""
    app = _read("app.html")
    view = app[app.index('data-view="agent-chat"'):app.index('data-view="agent-cb"')]
    assert "투자 자문을 제공" not in view
    assert "근거 조문과 함께" in view
    assert "투자 권유가 아니며" in kb_answer.NOTICE


def test_api_scan_attaches_kb_chat_and_thread_apis_to_agent_chat():
    """TC-KS-07 · 화면 스캐너가 이 화면(agent-chat)에 근거 답 · 채팅 · 새 대화 API 를 붙인다 — API 명세서 「부르는 화면」 칸."""
    from scripts import view_scan
    row = next(r for r in view_scan.scan()["rows"] if r["key"] == "agent-chat")
    apis = set(row["entry_apis"]) | set(row["action_apis"])
    assert {"/api/kb/ask", "/api/chat", "/api/conversations"} <= apis, sorted(apis)
