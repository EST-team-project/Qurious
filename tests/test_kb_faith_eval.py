"""근거 답 충실도 자동 평가 시험 (TC-KF) — `collector/kb_faith_eval.py` (목표 기능 ① W8 · 조사서 「근거충실도-자동지표」).

무엇을 지키나 —
1. **다시 만든 문맥 = 답 모델이 받은 문맥** — 평가 결과 파일에는 근거 글이 없어 같은 검색 길로 다시 만든다. 그 길이
   `kb_answer.ask` 와 갈라지면 다른 문맥으로 잰 점수가 그 답의 점수로 둔갑한다 → 같은 질문으로 ask 가 모델에 넣은
   프롬프트와 다시 만든 덩어리 · 근거 목록이 같아야 한다.
2. **숫자 근거 확인** — 값(「1만분의 5」 · 「30억원」 · 「2주」)만 뽑고 조 · 항 · 호 번호와 출처 표시는 뺀다. 질문에 이미
   있는 숫자는 따지지 않는다(되풀이한 전제).
3. **사람 판정과 맞추기** — 판정표의 판정 칸이 정답 · 부분 · 오답 밖이면 멈춘다 · 같은 답(same_as)은 한 번만 센다.
4. **Ragas 그대로 · 예시만 한국어** — 지시문과 출력 칸(JSON 스키마)은 Ragas 원본 그대로이고 예시만 한국어다.
5. **깨진 심판 출력은 씨앗을 바꿔 한 번 더** — 다시 재도 깨지면 점수 없음(오류를 남긴다).

네트워크 · 실제 kb.sqlite3 · Ollama 를 쓰지 않는다 — TC-KB 의 가짜 문서 DB · 가짜 벡터 길과 가짜 심판을 쓴다.
Ragas 가 없는 환경(앱 이미지)에서는 4 · 5 를 건너뛴다 — Ragas 는 호스트 평가 도구에만 둔다(조사서 4절).
"""
from __future__ import annotations

import json

import pytest

from app.services import kb_answer
from collector import kb_faith_eval as fe
from tests.test_kb_answer import FakeLlm
from tests.test_kb_search import FakeDense, kb  # noqa: F401 — kb 는 고정값(가짜 문서 DB)


@pytest.mark.parametrize("q, as_of, n, has, hasnt", [
    # 옛 판이 골라지는 기준일 — 복원 길이 기준일을 놓치면 새 판(1만분의 20)이 들어와 드러난다
    ("증권거래세 세율 유가증권시장", "2025-06-01", 1, "1만분의 15", "1만분의 20"),
    # 근거 셋이 다 들어가는 질문 — 복원 길이 근거 수를 줄이거나 순서를 바꾸면 드러난다
    ("주주총회 배당 세율", "2026-10-02", 3, "1만분의 5", "1만분의 15"),
])
def test_rebuilt_context_matches_what_ask_sent(kb, q, as_of, n, has, hasnt):
    """TC-KF-01 · 다시 만든 근거 덩어리 · 목록이 ask 가 모델에 넣은 프롬프트 · 출처 목록과 같다(기준일 · 근거 수 · 순서)."""
    llm = FakeLlm("근거에 있는 값입니다 [출처 1].")
    out = kb_answer.ask(q, 3, mode="lexical", as_of=as_of, path=kb, backend=FakeDense(), llm_backend=llm,
                        llm="llama3.1")
    ctx = fe.rebuild_context(q, 3, mode="lexical", as_of=as_of, path=kb, backend=FakeDense())
    assert len(out["citations"]) == n
    assert ctx["cited"] == [f"{c['doc_id']}:{c['article']}" for c in out["citations"]]
    sent = llm.calls[0]["messages"][1]["content"]
    assert ctx["contexts"] and all(b in sent for b in ctx["contexts"])
    assert "\n\n".join(ctx["contexts"]) in sent and ctx["contexts"][0].startswith("[출처 1] ")
    assert any(has in b for b in ctx["contexts"]) and not any(hasnt in b for b in ctx["contexts"])


def test_split_blocks_keeps_link_notes_with_their_block():
    """TC-KF-02 · 「[출처 n]」 머리로만 나누고, 위임 조 알림 줄(「※ 이 조가 … [출처 2]」)은 그 덩어리에 붙인 채로 둔다."""
    user = ("기준일: 2026-10-02 (이날 시행 중인 판의 조문만 근거로 넣었다)\n\n[근거]\n[출처 1] 법 제8조\n본문 가\n"
            "※ 이 조가 대통령령에 맡긴 내용은 [출처 2](시행령 제5조)에 있다.\n\n[출처 2] 시행령 제5조\n본문 나\n\n[질문]\n세율은?")
    blocks = fe.split_blocks(user)
    assert len(blocks) == 2 and "※ 이 조가" in blocks[0] and blocks[1].startswith("[출처 2]")


@pytest.mark.parametrize("answer, want", [
    ("유가증권시장은 1만분의 5이다 [출처 1]. 법 제8조 제1항 제2호에 따른다 [출처 2].", ["1만분의 5"]),
    ("공모 금액 30억원 이상이면 신고서를 낸다 [출처 1].", ["30억원"]),
    ("주주총회 2주 전에 통지한다 [출처 1]. 배당은 1개월 안에 준다 [출처 2].", ["2주", "1개월"]),
    ("맥주는 1킬로리터당 88만5700원이다 [출처 1].", ["1킬로리터", "88만5700원"]),
    ("제3조에 따라 허가를 받는다 [출처 1].", []),
])
def test_number_phrases_skip_article_numbers(answer, want):
    """TC-KF-03 · 값만 뽑는다 — 조 · 항 · 호 번호와 출처 표시는 값이 아니다."""
    assert fe.number_phrases(answer) == want


def test_number_check_found_missing_and_echo():
    """TC-KF-04 · 근거에 있는 숫자 · 없는 숫자 · 질문에 이미 있던 숫자(따지지 않음)를 가른다(공백 · 쉼표 무시)."""
    ctx = ["[출처 1] 증권거래세법 시행령 제5조\n유가증권시장: 1만분의 5", "[출처 2] 상법\n2주 전에 통지"]
    got = fe.number_check("2026년에는 1만분의 5이고 3주 전에 통지한다 [출처 1].", ctx, "2026년 세율은?")
    assert got == {"found": ["1만분의 5"], "missing": ["3주"], "echo": ["2026년"]}


def test_load_labels_rejects_unknown_label(tmp_path):
    """TC-KF-05 · 판정 칸은 정답 · 부분 · 오답만 — 다른 글이면 멈춘다 · (결과 파일, id) 로 찾는다."""
    head = "결과파일\tid\t길\t평가셋\t질문\t판정\t오답_종류\t까닭\n"
    good = tmp_path / "good.tsv"
    good.write_text(head + "kb_answer_eval-1\tA01\t분류\t근거답\t질문\t오답\t근거 밖 단정\t—\n", encoding="utf-8")
    assert fe.load_labels(good)[("kb_answer_eval-1", "A01")]["오답_종류"] == "근거 밖 단정"
    bad = tmp_path / "bad.tsv"
    bad.write_text(head + "kb_answer_eval-1\tA01\t분류\t근거답\t질문\t미룸\t\t—\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        fe.load_labels(bad)


def test_summarize_counts_below_thresholds_once_per_answer():
    """TC-KF-06 · 판정별 평균과 「점수 < 문턱」 수 · 같은 답(same_as)은 한 번 · 점수 없음은 따로 센다."""
    def it(i, label, score, same=None):
        return {"file": "f", "id": i, "label": label, "same_as": same,
                "judges": {"j": {"score": score}} if not same else None}
    items = [it("A", "정답", 1.0), it("B", "정답", 0.75), it("C", "오답", 0.5), it("D", "정답", None),
             it("E", "정답", None, same="f:A")]
    s = fe.summarize(fe.resolve(items), "j")
    assert s["n"] == 4 and s["no_score"] == 1
    assert s["labels"]["정답"] == {"n": 2, "mean": 0.875, "below": {"1.0": 1, "0.8": 1, "0.5": 0}}
    assert s["labels"]["오답"]["below"] == {"1.0": 1, "0.8": 1, "0.5": 0}


def _fake_http(replies):
    """심판 자리의 가짜 Ollama — 받은 요청(씨앗 포함)을 남기고 정해 둔 글을 차례로 돌려준다."""
    seen = []

    def http(url, body, timeout):
        seen.append(body)
        return {"message": {"content": replies[len(seen) - 1]}, "prompt_eval_count": 10, "eval_count": 5}
    return http, seen


def test_korean_prompts_keep_ragas_instruction_and_schema():
    """TC-KF-07 · 지시문 · 출력 칸은 Ragas 원본 그대로, 예시만 한국어 — 영어 예시를 따라 숫자를 틀리게 옮기던 것(2026-10-06)."""
    pytest.importorskip("ragas")
    _, faith_cls, _ = fe._ragas()
    http, _ = _fake_http([])
    base = faith_cls(llm=fe.make_judge("judge", http=http))
    ko = fe.korean_prompts(faith_cls(llm=fe.make_judge("judge", http=http)))
    assert ko.statement_generator_prompt.instruction == base.statement_generator_prompt.instruction
    assert ko.nli_statement_prompt.output_model is base.nli_statement_prompt.output_model
    assert "아인슈타인" in ko.statement_generator_prompt.examples[0][0].question
    assert [o.verdict for o in ko.nli_statement_prompt.examples[0][1].statements] == [0, 0, 1, 0]
    assert ko.nli_statement_prompt.language == "korean"


def test_broken_judge_json_is_retried_once_with_other_seed():
    """TC-KF-08 · 첫 심판의 출력이 깨진 JSON 이면 씨앗 43 으로 한 번 더 · 점수는 Ragas 와 같은 「뒷받침 ÷ 전체」."""
    pytest.importorskip("ragas")
    stmts = json.dumps({"statements": ["세율은 1만분의 5이다.", "증권사는 세율을 바꿀 수 있다."]}, ensure_ascii=False)
    nli = json.dumps({"statements": [
        {"statement": "세율은 1만분의 5이다.", "reason": "근거에 있다", "verdict": 1},
        {"statement": "증권사는 세율을 바꿀 수 있다.", "reason": "근거에 없다", "verdict": 0}]}, ensure_ascii=False)
    first, seen1 = _fake_http([stmts, '{"statements": [{"statement": "세율'])   # 판정에서 잘림
    second, seen2 = _fake_http([stmts, nli])
    r = fe.judge_answer(fe.make_judge("judge", http=first), "세율은?", "세율은 1만분의 5이다 [출처 1].", ["근거"],
                        retry_judge=fe.make_judge("judge", http=second, seed=43))
    assert r["score"] == 0.5 and r["error"] is None and r["retried"]["seed"] == 43
    assert seen1[0]["options"]["seed"] == 42 and seen2[0]["options"]["seed"] == 43
    assert seen1[0]["format"]["properties"]["statements"] and "[출처" not in seen1[0]["messages"][0]["content"].split(
        "Now perform the same")[1]
    broken, _ = _fake_http([stmts, "{"])
    r2 = fe.judge_answer(fe.make_judge("judge", http=broken), "세율은?", "세율은 1만분의 5이다.", ["근거"])
    assert r2["score"] is None and r2["error"].startswith("ValidationError")
