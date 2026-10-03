"""근거 답 만들기 시험 (TC-KA) — `POST /api/kb/ask` (목표 기능 ① W6 · 설계서 5.3.4 답변 정책).

무엇을 지키나 —
1. **답한 글에는 근거 목록 안의 출처 번호만** 남는다 — 목록 밖 번호는 지우고 `check.invalid` 에 싣는다.
   남은 출처가 하나도 없으면 LLM 글을 버리고 근거 발췌로 답한다(근거 없는 글을 보이지 않는다).
2. **근거 없음** — 찾은 근거가 0 이면 LLM 을 부르지 않는다. 모델이 정해진 「근거를 찾지 못했습니다.」 를 쓰면 그대로 알린다.
3. **답하지 않는 질문** — 종목 매수 · 매도 권유 · 가격 예측 질문은 찾기 · 생성 없이 돌려보낸다. 「공매도」 같은 규정 질문은 지나간다.
4. **시점 고정** — 프롬프트에는 기준일에 시행 중인 판의 글만 들어간다(옛 세율 · 내년 판이 섞이지 않는다).
5. **LLM 이 꺼져도 근거는 보인다** — 근거 발췌와 `llm.error`. 모델이 없으면 받을 명령을 알려 준다.
6. 출처 표기 꼴이 달라도(「[1]」 · 「[출처1, 2]」 · 「(출처 3)」) 한 꼴로 맞추고, 마침표 뒤 번호를 문장 안으로 옮겨 문장마다 센다.
7. 생각하는 모델(qwen3 등)에는 think=false 를 보내고, 새어 나온 생각 글 · 끝 표시 토큰은 지운다 · 한국어가 아닌 답은 근거 발췌 ·
   찾기 · 답하기는 로그인 뒤 · 잘못된 입력은 422.

네트워크 · 실제 kb.sqlite3 · Ollama 를 쓰지 않는다 — TC-KB 의 가짜 문서 DB 와 가짜 생성 길을 쓴다.
"""
from __future__ import annotations

import urllib.error

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.lib.session import get_current_user
from app.routes import kb as kb_routes
from app.services import kb_answer, kb_search
from tests.test_kb_search import NEW_RATE, OLD_RATE, FakeDense, kb  # noqa: F401 — kb 는 고정값(가짜 문서 DB)


class FakeLlm(kb_answer.LlmBackend):
    """Ollama 대신 — 정해 둔 답을 돌려주고 받은 요청을 남긴다."""

    def __init__(self, content: str = "", fail: Exception | None = None):
        # dataclass 의 http 칸에 가짜 함수를 넘긴다(메서드로 덮으면 부모 __init__ 이 실제 함수를 다시 넣는다)
        super().__init__(ollama_url="http://fake-ollama", http=self._fake_http)
        self.content, self.fail, self.calls = content, fail, []

    def _fake_http(self, method, url, body, timeout):
        self.calls.append(body)
        if self.fail:
            raise self.fail
        return {"message": {"role": "assistant", "content": self.content}, "prompt_eval_count": 321,
                "eval_count": 45, "done_reason": "stop"}


def _ask(kb_path, q, content="", fail=None, **kw):
    llm = FakeLlm(content, fail)
    out = kb_answer.ask(q, kw.pop("k", 3), mode="lexical", as_of=kw.pop("as_of", "2026-10-02"), path=kb_path,
                        backend=FakeDense(), llm_backend=llm, llm=kw.pop("llm", "llama3.1"), **kw)
    return out, llm


def test_answer_keeps_only_listed_citations(kb):
    """TC-KA-01 · 목록 밖 번호(9)는 지우고 알린다 · 쓰인 출처만 used · 응답에 기준일 · 모델 · 걸린 시간."""
    out, llm = _ask(kb, "2026년 증권거래세 세율은?",
                    "유가증권시장 주권의 증권거래세율은 1만분의 5입니다 [출처 1][출처 9]. 코스닥은 1만분의 20입니다 [출처 1].")
    assert out["status"] == "answered"
    assert "[출처 9]" not in out["answer"] and out["answer"].count("[출처 1]") == 2
    assert out["check"] == {"valid": [1], "invalid": [9], "sentences": 2, "uncited": 0}
    assert [c["used"] for c in out["citations"]][0] is True
    assert out["citations"][0]["doc_id"] == "stt_decree" and out["citations"][0]["n"] == 1
    assert out["as_of"] == "2026-10-02" and out["model"] == "llama3.1"
    assert out["llm"]["prompt_tokens"] == 321 and out["timing"]["llm_ms"] >= 0
    assert len(llm.calls) == 1


def test_no_valid_citation_falls_back_to_excerpt(kb):
    """TC-KA-02 · 출처 번호가 하나도 맞지 않으면 LLM 글을 버리고 근거 발췌(원문은 llm.raw 에만)."""
    out, _ = _ask(kb, "2026년 증권거래세 세율은?", "세율은 0.15% 입니다 [출처 7].")
    assert out["status"] == "excerpt"
    assert "0.15%" not in out["answer"] and out["answer"].startswith("근거 문서에서 찾은 조문입니다")
    assert out["check"]["valid"] == [] and out["check"]["invalid"] == [7]
    assert "0.15%" in out["llm"]["raw"]
    assert "출처 번호가 하나도 없어" in out["reason"]


def test_model_no_answer_sentence_is_no_evidence(kb):
    """TC-KA-03 · 모델이 정해진 「근거를 찾지 못했습니다.」 를 쓰면 no_evidence — 근거 목록은 함께 준다(쓰이지 않음)."""
    out, _ = _ask(kb, "증권거래세 세율 공시 방법은?", "근거를 찾지 못했습니다.")
    assert out["status"] == "no_evidence" and out["answer"] == kb_answer.NO_ANSWER
    assert out["citations"] and not any(c["used"] for c in out["citations"])


def test_no_hits_does_not_call_llm(kb):
    """TC-KA-04 · 찾은 근거가 0 이면 LLM 을 부르지 않는다."""
    out, llm = _ask(kb, "블록체인 스테이블코인 발행 인가", "아무 말")
    assert out["status"] == "no_evidence" and out["citations"] == []
    assert llm.calls == [] and out["timing"]["llm_ms"] == 0


@pytest.mark.parametrize("q", ["삼성전자 내일 오를까?", "지금 이 종목 사야 할까요", "목표 주가 알려줘"])
def test_investment_advice_is_declined_without_search(kb, q, monkeypatch):
    """TC-KA-05 · 매수 · 매도 권유 · 가격 예측 질문은 찾기 · 생성 없이 declined."""
    monkeypatch.setattr(kb_search, "search", lambda *a, **k: pytest.fail("찾기를 부르면 안 된다"))
    out, llm = _ask(kb, q, "아무 말")
    assert out["status"] == "declined" and out["citations"] == [] and llm.calls == []


def test_regulation_question_with_sell_word_is_not_declined(kb):
    """TC-KA-05b · 「공매도」 · 「설명의무」 같은 규정 질문은 거절 낱말에 걸리지 않는다."""
    out, llm = _ask(kb, "공매도 규제와 설명의무는 어떻게 되나요?", "설명하여야 합니다 [출처 1].")
    assert out["status"] != "declined" and len(llm.calls) == 1


def test_prompt_has_only_as_of_version(kb):
    """TC-KA-06 · 프롬프트에는 기준일 판의 글만 — 2026-10-02 면 새 세율, 2025-06-01 이면 옛 세율 · 기준일이 프롬프트에."""
    _, llm = _ask(kb, "증권거래세 탄력세율", "세율 [출처 1].", as_of="2026-10-02")
    user = llm.calls[0]["messages"][1]["content"]
    assert "기준일: 2026-10-02" in user and NEW_RATE in user and OLD_RATE not in user
    assert "대통령령 제35947호 · 2026-01-02 시행\n" in user and "시행 · 2026-01-02 시행" not in user   # 시행일은 한 번만
    _, llm = _ask(kb, "증권거래세 탄력세율", "세율 [출처 1].", as_of="2025-06-01")
    user = llm.calls[0]["messages"][1]["content"]
    assert OLD_RATE in user and NEW_RATE not in user
    assert "내년에 시행되는 규정" not in user                       # 2027 시행 판은 들어오지 않는다
    opts = llm.calls[0]["options"]
    assert opts["temperature"] == 0 and opts["seed"] == kb_answer.SEED and opts["num_predict"] == kb_answer.NUM_PREDICT


def test_llm_down_returns_excerpt_with_error(kb):
    """TC-KA-07 · LLM 에 닿지 못하면 근거 발췌 + llm.error · 모델이 없으면(404) 받을 명령을."""
    out, _ = _ask(kb, "증권거래세 세율", fail=urllib.error.URLError("refused"))
    assert out["status"] == "excerpt" and "닿지 못했다" in out["llm"]["error"]
    assert out["citations"] and out["answer"].startswith("근거 문서에서 찾은 조문입니다")
    err404 = urllib.error.HTTPError("http://fake-ollama/api/chat", 404, "not found", {}, None)
    out, _ = _ask(kb, "증권거래세 세율", fail=err404, llm="qwen3:4b")
    assert "ollama pull qwen3:4b" in out["llm"]["error"] and "fake-ollama" not in out["llm"]["error"]


def test_citation_forms_are_normalized_and_counted_per_sentence():
    """TC-KA-08 · 「[1]」 · 「[출처1, 2]」 · 「(출처 3)」 → 「[출처 n]」 · 마침표 뒤 번호는 문장 안으로 · 문장마다 센다."""
    text, valid, invalid = kb_answer.normalize_citations(
        "세율은 1만분의 5이다. [1] 납세의무자는 양도자다 [출처1, 2]. 기타 사항이다 (출처 3). 출처 없는 문장이다.", 3)
    assert valid == [1, 2, 3] and invalid == []
    assert "세율은 1만분의 5이다 [출처 1]." in text and "[출처 1][출처 2]" in text and "[출처 3]" in text
    assert kb_answer.sentence_check(text) == (4, 1)
    _, valid, invalid = kb_answer.normalize_citations("[별표 1] 과 [2] 와 [12]", 3)
    assert valid == [2] and invalid == []                        # 목록 밖 [12] 는 출처로 보지 않고 글로 둔다


def test_thinking_model_gets_think_false(kb):
    """TC-KA-09 · qwen3 계열에는 think=false · 다른 모델에는 보내지 않는다 · <think> 글 · 닫는 태그 앞 글(생각 전용 판) ·
    끝 표시 토큰 뒤(커뮤니티 GGUF)는 지운다 · 답 글이 한국어가 아니면 근거 발췌(2026-10-03 근거답 평가에서 본 세 꼴)."""
    _, llm = _ask(kb, "증권거래세 세율", "<think>속생각</think>세율 [출처 1].", llm="qwen3:4b")
    assert llm.calls[0].get("think") is False
    out, llm = _ask(kb, "증권거래세 세율", "<think>속생각</think>세율 [출처 1].", llm="llama3.1")
    assert "think" not in llm.calls[0] and "속생각" not in out["answer"]
    # 생각 전용 판 — 여는 태그 없이 닫는 태그만 남는 꼴
    out, _ = _ask(kb, "증권거래세 세율", "Okay, let's tackle this.\n</think>\n\n세율은 1만분의 5 [출처 1].", llm="qwen3:4b")
    assert out["answer"].startswith("세율은") and "tackle" not in out["answer"]
    # 생각 글이 길이 상한에서 잘려 닫는 태그도 없이 온 꼴 — 출처 번호가 있어도 한국어가 아니면 근거 발췌
    out, _ = _ask(kb, "증권거래세 세율", "Okay, let's tackle this question. The user asks about [출처 1] rates and", llm="qwen3:4b")
    assert out["status"] == "excerpt" and "한국어가 아니다" in out["reason"]
    # 끝 표시 토큰이 글자로 새고 그 뒤에 다음 차례를 지어낸 꼴 — 토큰 앞에서 자른다
    out, _ = _ask(kb, "증권거래세 세율", "세율은 1만분의 5 [출처 1].<|eot_id|><|start_header_id|>user 다음 질문 [출처 2]",
                  llm="hf.co/x/kanana-GGUF:Q4_K_M")
    assert out["answer"] == "세율은 1만분의 5 [출처 1]." and out["check"]["valid"] == [1]


def test_context_caps_trim_and_drop_low_ranked():
    """TC-KA-10 · 근거 한 개는 글자 상한에서 자르고, 전체 상한을 넘는 뒤 순위 근거는 넣지 않는다."""
    hit = {"title": "법", "article": "제1조", "article_title": "", "version_label": "법률 제1호",
           "effective_at": "2026-01-01", "text": "가" * 2000}
    msgs, n = kb_answer.build_messages("질문", "2026-10-02", [hit] * 8, chunk_chars=900, context_chars=2000)
    assert n == 2 and "…(뒤 생략)" in msgs[1]["content"] and "[출처 3]" not in msgs[1]["content"]


def test_api_ask_needs_login_and_validates(kb, monkeypatch):
    """TC-KA-11 · `POST /api/kb/ask` 는 로그인 뒤 · 잘못된 입력 422 · extract 는 LLM 없이."""
    monkeypatch.setenv(kb_search.ENV_DB_PATH, str(kb))
    app = FastAPI()
    app.include_router(kb_routes.router)
    c = TestClient(app)
    assert c.post("/api/kb/ask", json={"q": "세율"}).status_code == 401
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "name": "시험", "email": "t@example.com"}
    assert c.post("/api/kb/ask", json={"q": ""}).status_code == 422
    assert c.post("/api/kb/ask", json={"q": "세율", "k": 99}).status_code == 422
    assert c.post("/api/kb/ask", json={"q": "세율", "answer": "magic"}).status_code == 422
    assert c.post("/api/kb/ask", json={"q": "세율", "llm": "bad name; rm -rf"}).status_code == 422
    j = c.post("/api/kb/ask", json={"q": "증권거래세 세율", "mode": "lexical", "answer": "extract",
                                    "as_of": "2026-10-02"}).json()
    assert j["status"] == "excerpt" and j["citations"][0]["doc_id"] == "stt_decree"
    assert j["model"] is None and j["notice"] == kb_answer.NOTICE
    # 기본 답 모델 — 설정이 없으면 평가로 고른 모델, KB_ANSWER_MODEL 이 있으면 그것(채팅용 LLM_MODEL 과 따로)
    monkeypatch.delenv(kb_answer.ENV_MODEL, raising=False)
    assert kb_answer.default_model() == kb_answer.DEFAULT_ANSWER_MODEL == "qwen3:4b-instruct"
    monkeypatch.setenv(kb_answer.ENV_MODEL, "exaone3.5:2.4b")
    assert kb_answer.default_model() == "exaone3.5:2.4b"
