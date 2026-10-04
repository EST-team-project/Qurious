"""질문 말 → 법령 말 시험 (TC-SY) — 검색어 넓히기 · 답 문맥의 괄호 풀이 (목표 기능 ① W5 · DF-59 · 설계서 5.3.3).

무엇을 지키나 —
1. **표 모양** — 실제 표(app/services/kb_data/synonyms.tsv)의 줄마다 근거 「문서:조」 가 받아 둔 문서이고, 확실도 ·
   자리 칸이 정해진 값이다(사람이 조문으로 확인한 줄만 둔다는 약속을 모양으로라도 지킨다). 모양이 틀리면 몇째 줄인지 알린다.
2. **고르기** — 띄어쓰기 무시(「로보 어드바이저」) · 질문에 법령 말이 이미 있으면 고르지 않음 · 「조건」 말이 없으면
   고르지 않음(「누가 내나」 만으로는 세금인지 모른다) · 「제외」 말(「코스피200」)이 있으면 고르지 않음 ·
   법령 말이 같은 두 줄은 한 번만.
3. **괄호 풀이** — 「코스피(유가증권시장)」 처럼 질문 말 바로 뒤 · 구절 꼴은 질문 끝에 「(법령 말: …)」.
4. **검색** — 넓힌 검색어로 낱말 검색이 법령 말 조를 찾는다(끄면 못 찾는다) · 응답에 고른 줄과 쓴 검색어.
5. **답** — 답 모델에 가는 질문은 괄호 풀이를 단 것 · 응답의 query 는 원래 질문 그대로.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services import kb_answer, kb_search, kb_synonyms, kb_text
from collector import kb_law
from collector.kb_law import Article
from tests.test_kb_answer import FakeLlm
from tests.test_kb_search import FakeDense, _store, _v

CAP_DEC = kb_law.DOC_BY_ID["capmkt_decree"]
STT_DEC = kb_law.DOC_BY_ID["stt_decree"]


def test_real_table_shape():
    """TC-SY-01 · 실제 표 — 줄마다 근거 문서가 받아 둔 문서 · 조 번호 모양 · 확실도 · 자리 · 메모."""
    entries = kb_synonyms.load()
    assert len(entries) >= 15
    for e in entries:
        doc, _, art = e.source.partition(":")
        assert doc in kb_law.DOC_BY_ID, e.source
        assert kb_text.ARTICLE_RE.fullmatch(art), e.source
        assert e.confidence in kb_synonyms.CONFIDENCE and e.place in kb_synonyms.PLACES
        assert e.note, e.asks
        # 질문 말과 법령 말이 같으면 넓힐 것이 없다 — 표에 둘 까닭이 없는 줄
        assert not set(map(kb_synonyms._flat, e.asks)) & set(map(kb_synonyms._flat, e.legal)), e.asks


def test_bad_table_line_is_reported(tmp_path):
    """TC-SY-02 · 모양이 틀린 줄은 몇째 줄인지 알린다(자리 칸에 정해지지 않은 값)."""
    bad = tmp_path / "s.tsv"
    bad.write_text("질문말\t법령말\t조건\t제외\t자리\t근거\t확실도\t메모\n"
                   "코스피\t유가증권시장\t\t\t옆\tstt_decree:제5조\t높음\t메모\n", encoding="utf-8")
    with pytest.raises(ValueError, match="2줄"):
        kb_synonyms.load(bad)


def _legal(q: str) -> list:
    return [m.entry.legal for m in kb_synonyms.match(q)]


def test_match_rules():
    """TC-SY-03 · 띄어쓰기 무시 · 이미 법령 말 · 조건 · 제외 · 같은 법령 말은 한 번."""
    assert _legal("2026년 코스피 상장 주식을 팔 때 증권거래세율은?") == [("유가증권시장",)]
    assert _legal("로보 어드바이저 규제는?") == [("전자적 투자조언장치",)]
    assert _legal("유가증권시장(코스피) 세율") == []                       # 이미 법령 말로 물었다
    assert _legal("코스피200 선물 증거금률은?") == []                      # 제외 말
    assert _legal("누가 내나요?") == []                                   # 조건(세금 말) 없음
    assert _legal("증권거래세는 누가 내나요?") == [("납세의무자",)]
    assert _legal("5%룰 위반하면 지분을 더 못 사나요?") == [("대량보유",)]   # 「5%룰」 과 「지분 5%」 두 줄 — 한 번만
    assert _legal("배당 수익률이 5%면 높은가요?") == []                    # 「5%」 만으로는 고르지 않는다
    assert _legal("투자 위험을 제대로 고지받지 못했어요") == [("설명의무",)]
    assert _legal("보험 계약 때 고지의무") == []                           # 「위험」 이 없으면 보험편 고지와 헷갈린다


def test_annotate_and_expand():
    """TC-SY-04 · 괄호 풀이는 질문 말 바로 뒤 · 구절은 끝 · 검색어는 법령 말을 한 번씩 덧붙인다."""
    q = "2026년 코스피 상장 주식을 팔 때 증권거래세율은?"
    m = kb_synonyms.match(q)
    assert kb_synonyms.annotate(q, m) == "2026년 코스피(유가증권시장) 상장 주식을 팔 때 증권거래세율은?"
    assert kb_synonyms.expand(q, m) == q + " 유가증권시장"
    q2 = "증권거래세는 누가 내나요?"
    assert kb_synonyms.annotate(q2, kb_synonyms.match(q2)) == "증권거래세는 누가 내나요? (법령 말: 납세의무자)"
    q3 = "증권사 신용거래 반대매매 기준은?"
    m3 = kb_synonyms.match(q3)
    assert kb_synonyms.annotate(q3, m3) == ("증권사(투자매매업자 · 투자중개업자) 신용거래(신용공여) "
                                            "반대매매(임의상환 · 임의처분) 기준은?")
    assert kb_synonyms.expand(q3, m3).split()[-5:] == ["투자매매업자", "투자중개업자", "신용공여", "임의상환", "임의처분"]
    assert kb_synonyms.annotate("오늘 날씨", []) == "오늘 날씨" and kb_synonyms.expand("오늘 날씨", []) == "오늘 날씨"


@pytest.fixture()
def kbs(tmp_path) -> Path:
    path = tmp_path / "kb.sqlite3"
    conn = kb_law.connect(path)
    _store(conn, CAP_DEC, _v("36728", "2026-09-30", "2026-10-02"), [
        Article("제2조", "용어의 정의", "제1편 총칙",
                "6. \"전자적 투자조언장치\"란 투자자의 투자성향을 분석하는 자동화된 전산정보처리장치를 말한다."),
        Article("제87조", "불건전 영업행위의 금지", "", "투자자문업자는 투자자에게 확정된 수익을 약속하여서는 아니 된다."),
    ])
    _store(conn, STT_DEC, _v("35947", "2025-12-30", "2026-01-02"), [
        Article("제5조", "탄력세율", "", "1. 유가증권시장에서 양도되는 주권: 1만분의 5 2. 코넥스시장: 1만분의 10"),
    ])
    conn.close()
    return path


def test_search_uses_expanded_query(kbs):
    """TC-SY-05 · 낱말 검색 — 「로보어드바이저」 는 말뭉치에 없어 끄면 정의 조를 못 찾고 켜면 찾는다 · 응답에 고른 줄."""
    q = "로보어드바이저는 법에서 뭐라고 부르나요?"
    off = kb_search.search(q, 3, as_of="2026-10-02", mode="lexical", synonyms=False, path=kbs)
    on = kb_search.search(q, 3, as_of="2026-10-02", mode="lexical", path=kbs)
    assert ("capmkt_decree", "제2조") not in [(h["doc_id"], h["article"]) for h in off["hits"]]
    assert (on["hits"][0]["doc_id"], on["hits"][0]["article"]) == ("capmkt_decree", "제2조")
    assert on["synonyms"] == [{"from": "로보어드바이저", "to": ["전자적 투자조언장치"], "source": "capmkt_decree:제2조",
                               "confidence": "높음"}]
    assert on["query_used"] == q + " 전자적 투자조언장치" and on["query"] == q
    assert off["synonyms"] == [] and off["query_used"] == q


def test_answer_prompt_gets_annotated_question(kbs):
    """TC-SY-06 · 답 모델에는 「코스피(유가증권시장)」 · 응답의 query 는 원래 질문 · 끄면 괄호 없음."""
    q = "2026년 코스피 상장 주식을 팔 때 증권거래세율은?"
    llm = FakeLlm("유가증권시장 주권은 1만분의 5다 [출처 1].")
    out = kb_answer.ask(q, 3, mode="lexical", as_of="2026-10-02", path=kbs, backend=FakeDense(), llm_backend=llm,
                        llm="llama3.1")
    prompt = llm.calls[0]["messages"][1]["content"]
    assert "[질문]\n2026년 코스피(유가증권시장) 상장 주식을 팔 때 증권거래세율은?" in prompt
    assert out["query"] == q and out["synonyms"][0]["to"] == ["유가증권시장"]
    assert out["citations"][0]["doc_id"] == "stt_decree"

    llm2 = FakeLlm("세율 [출처 1].")
    kb_answer.ask(q, 3, mode="lexical", as_of="2026-10-02", synonyms=False, path=kbs, backend=FakeDense(),
                  llm_backend=llm2, llm="llama3.1")
    assert not re.search(r"코스피\(", llm2.calls[0]["messages"][1]["content"])
