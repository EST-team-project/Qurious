"""위임 조 함께 넣기 시험 (TC-KD) — 법 조가 하위 법령에 맡긴 값을 그 조와 함께 근거로 (목표 기능 ① W5 · DF-59).

무엇을 지키나 —
1. 맡기는 말이 든 항을 찾는다 — 「대통령령으로 정하는」 은 시행령, 「금융위원회가 정하여 고시하는」 은 감독규정.
2. 아래 조가 윗 조를 부르는 꼴만 잇는다 — 「법 제8조제2항」 은 잇고 「법 제8조의2」 · 「법 제80조」 · 「같은 법 제8조」 ·
   「소득세법 제8조」 는 잇지 않는다.
3. **시행하는 조만** — 문단 첫머리 · 따옴표로 맡긴 말을 받는 조는 잇고, 본문 중간에서 「법 제8조에 따른 세율을 적용하여」
   처럼 쓰기만 하는 조는 잇지 않는다.
4. 아래 조도 **같은 기준일의 판**에서 — 2025 년 기준일이면 옛 시행령 세율(1만분의 15), 2026 이면 새 세율(1만분의 5).
5. 문서 거름(docs)과 상관없이 잇는다 — 「증권거래세법만」 으로 찾아도 맡긴 값은 시행령에 있다.
6. 답 문맥 — 위임 조를 윗 조 바로 뒤에 끼우고, **둘 다 들어간 때만** 「이 조가 맡긴 내용은 [출처 n]」 을 단다.
7. 시행령이 근거 문서에 없는 법(소득세법)은 잇지 않는다 · links=False 면 잇지 않는다.

네트워크 · 실제 kb.sqlite3 를 쓰지 않는다 — 작은 가짜 문서로 시험 DB 를 만든다.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.services import kb_answer, kb_links, kb_search, kb_text
from collector import kb_law
from collector.kb_law import Article
from tests.test_kb_answer import FakeLlm
from tests.test_kb_search import FakeDense, _store, _v

NL = chr(10)

STT_ACT = kb_law.DOC_BY_ID["stt_act"]
STT_DEC = kb_law.DOC_BY_ID["stt_decree"]
CAP_DEC = kb_law.DOC_BY_ID["capmkt_decree"]
FIS = kb_law.DOC_BY_ID["fis_reg"]
INCOME = kb_law.DOC_BY_ID["income_tax_act"]

ACT8 = ("① 증권거래세의 세율은 1만분의 35로 한다." + NL
        + "② 제1항의 세율은 자본시장 육성을 위하여 긴급히 필요하다고 인정될 때에는 증권시장에서 거래되는 주권에 "
          "한정하여 종목별로 대통령령으로 정하는 바에 따라 낮추거나 영(零)으로 할 수 있다.")
DEC5_OLD = "법 제8조제2항을 적용받는 주권과 그 세율은 다음 각 호와 같다. 1. 유가증권시장에서 양도되는 주권: 1만분의 15"
DEC5_NEW = "법 제8조제2항을 적용받는 주권과 그 세율은 다음 각 호와 같다. 1. 유가증권시장에서 양도되는 주권: 1만분의 5"
#: 본문 중간에서 쓰기만 하는 조 — 잇지 않는다
DEC7 = "① 납세의무자는 신고하여야 한다. 이 경우 세액은 과세표준에 법 제8조에 따른 세율을 적용하여 계산한다."
#: 다른 법 · 다른 조를 부르는 꼴 — 잇지 않는다
DEC9 = ("「소득세법」 제94조와 같은 법 제8조에 따른 양도 · 소득세법 제8조의 세율 · 법 제8조의2제1항에 따른 신고 · "
        "법 제80조에 따른 세율")
CAP_DEC2 = ("6. \"전자적 투자조언장치\"란 다음 각 목의 요건을 모두 갖춘 자동화된 전산정보처리장치를 말한다. "
            "가. 투자자의 투자성향을 분석할 것 다. 그 밖에 투자자 보호를 위해 금융위원회가 정하여 고시하는 요건을 갖출 것")
FIS_1_2_2 = ("영 제2조제6호다목에서 \"금융위원회가 정하여 고시하는 요건\"이란 다음 각 호의 요건을 말한다. "
             "1. 전자적 투자조언장치를 활용하는 업무의 종류에 따라 점검할 것")
INCOME129 = "① 원천징수세율은 다음 각 호와 같다. 1. 이자소득: 100분의 14 ② 그 밖의 세율은 대통령령으로 정하는 바에 따른다."


@pytest.fixture()
def kbl(tmp_path) -> Path:
    path = tmp_path / "kb.sqlite3"
    conn = kb_law.connect(path)
    _store(conn, STT_ACT, _v("18724", "2021-12-21", "2022-07-01", "법률"), [Article("제8조", "세율", "", ACT8)])
    _store(conn, STT_DEC, _v("35300", "2025-02-28", "2025-02-28"), [
        Article("제5조", "탄력세율", "", DEC5_OLD),
        Article("제7조", "신고ㆍ납부", "", DEC7),
        Article("제9조", "다른 법", "", DEC9),
    ])
    _store(conn, STT_DEC, _v("35947", "2025-12-30", "2026-01-02"), [
        Article("제5조", "탄력세율", "", DEC5_NEW),
        Article("제7조", "신고ㆍ납부", "", DEC7),
        Article("제9조", "다른 법", "", DEC9),
    ])
    _store(conn, CAP_DEC, _v("36728", "2026-09-30", "2026-10-02"), [Article("제2조", "용어의 정의", "제1편 총칙", CAP_DEC2)])
    _store(conn, FIS, _v("2026-38", "2026-09-12", "2026-09-15", "고시"), [
        Article("제1-2조의2", "전자적 투자조언장치의 요건", "제1편 총칙", FIS_1_2_2),
    ])
    _store(conn, INCOME, _v("21221", "2025-12-23", "2026-07-01", "법률"), [Article("제129조", "원천징수세율", "", INCOME129)])
    conn.close()
    return path


def _ro(path: Path) -> sqlite3.Connection:
    c = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def test_delegating_paragraphs_by_level():
    """TC-KD-01 · 맡기는 말이 든 항 — 단계마다(시행령 · 감독규정) · 항 표시가 없으면 None."""
    assert kb_links.delegating_paragraphs("증권거래세법 > 제8조(세율)" + NL + ACT8) == {"decree": {2}}
    assert kb_links.delegating_paragraphs(CAP_DEC2) == {"notice": {None}}
    assert kb_links.delegating_paragraphs("① 세율은 1만분의 35로 한다.") == {}
    both = kb_links.delegating_paragraphs("① 대통령령으로 정한다. ② 금융위원회가 정하여 고시하는 기준 ③ 총리령으로 정한다.")
    assert both == {"decree": {1}, "notice": {2}, "rule": {3}}


def test_ref_pattern_exact_article_only():
    """TC-KD-02 · 「법 제8조(제2항)」 만 — 「제8조의2」 · 「제80조」 · 「같은 법」 · 「소득세법」 · 「「…법」」 은 아니다."""
    p = kb_links.ref_pattern("법", "제8조")
    assert [m.group(0) for m in p.finditer("법 제8조제2항을 적용받는 · 법 제8조에 따른")] == ["법 제8조제2항", "법 제8조"]
    for text in ("법 제8조의2제1항", "법 제80조", "같은 법 제8조", "소득세법 제8조", "「증권거래세법」 제8조"):
        assert p.search(text) is None, text
    assert kb_links.ref_pattern("영", "제2조").search("영 제2조제6호다목에서")
    assert kb_links.ref_pattern("규정", "제1-2조의2").search("규정 제1-2조의2제1항에 따른")
    assert kb_links.ref_pattern("규정", "제1-2조").search("규정 제1-2조의2") is None


def test_ref_scores_implementing_over_mention():
    """TC-KD-03 · 점수 — 첫머리 + 항 맞음 4 · 따옴표로 받기 + 첫머리 5 · 중간에서 쓰기만 0 · 다른 항 −2."""
    assert kb_links.find_refs(DEC5_NEW, "법", "제8조", {2})[0].score == 4
    assert kb_links.find_refs(FIS_1_2_2, "영", "제2조", {None})[0].score == 5
    assert kb_links.find_refs(DEC7, "법", "제8조", {2})[0].score == 0
    assert kb_links.find_refs("법 제8조제1항을 적용받는 주권", "법", "제8조", {2})[0].score == 0   # 첫머리 2 · 다른 항 −2
    assert kb_links.find_refs(DEC9, "법", "제8조", {2}) == []


def test_search_attaches_delegated_child_of_as_of_version(kbl):
    """TC-KD-04 · 찾은 법 조에 시행령 조가 붙는다 — 같은 기준일 판(2026 → 1만분의 5 · 2025 → 1만분의 15)."""
    new = kb_search.search("증권거래세 세율", 3, as_of="2026-10-02", mode="lexical", synonyms=False, path=kbl)
    act = next(h for h in new["hits"] if h["doc_id"] == "stt_act")
    assert [(d["doc_id"], d["article"]) for d in act["delegated"]] == [("stt_decree", "제5조")]
    d = act["delegated"][0]
    assert "1만분의 5" in d["text"] and "1만분의 15" not in d["text"]
    assert d["via"]["ref"] == "법 제8조제2항" and d["via"]["level"] == "decree" and d["via"]["para"] == 2
    assert d["via"]["chunk_id"] == act["chunk_id"] and new["retrieval"]["delegated"] >= 1

    old = kb_search.search("증권거래세 세율", 3, as_of="2025-06-01", mode="lexical", synonyms=False, path=kbl)
    act_old = next(h for h in old["hits"] if h["doc_id"] == "stt_act")
    assert "1만분의 15" in act_old["delegated"][0]["text"]


def test_mentions_and_other_laws_are_not_linked(kbl):
    """TC-KD-05 · 쓰기만 하는 조(제7조) · 다른 법 · 다른 조를 부른 조(제9조)는 잇지 않는다."""
    res = kb_search.search("증권거래세 세율 신고", 5, as_of="2026-10-02", mode="lexical", synonyms=False, path=kbl)
    act = next(h for h in res["hits"] if h["doc_id"] == "stt_act")
    assert {d["article"] for d in act["delegated"]} == {"제5조"}


def test_links_ignore_doc_filter_and_follow_chain_to_notice(kbl):
    """TC-KD-06 · 문서 거름과 상관없이 잇는다 · 시행령 → 감독규정(「금융위원회가 정하여 고시하는」 · 따옴표로 받기)."""
    only = kb_search.search("증권거래세 세율", 3, as_of="2026-10-02", docs=["stt_act"], mode="lexical",
                            synonyms=False, path=kbl)
    assert {h["doc_id"] for h in only["hits"]} == {"stt_act"}
    assert only["hits"][0]["delegated"][0]["doc_id"] == "stt_decree"

    rob = kb_search.search("전자적 투자조언장치 요건", 3, as_of="2026-10-02", docs=["capmkt_decree"], mode="lexical",
                           synonyms=False, path=kbl)
    dec = rob["hits"][0]
    assert dec["doc_id"] == "capmkt_decree"
    assert [(d["doc_id"], d["article"]) for d in dec["delegated"]] == [("fis_reg", "제1-2조의2")]
    assert dec["delegated"][0]["via"]["level_name"] == "금융위원회 고시" and dec["delegated"][0]["via"]["score"] == 5


def test_no_child_document_or_links_off(kbl):
    """TC-KD-07 · 시행령이 근거 문서에 없는 법(소득세법)은 잇지 않는다 · links=False 면 아무것도 잇지 않는다."""
    tax = kb_search.search("원천징수세율 이자소득", 3, as_of="2026-10-02", mode="lexical", synonyms=False, path=kbl)
    inc = next(h for h in tax["hits"] if h["doc_id"] == "income_tax_act")
    assert inc["delegated"] == []
    off = kb_search.search("증권거래세 세율", 3, as_of="2026-10-02", mode="lexical", links=False, synonyms=False,
                           path=kbl)
    assert all("delegated" not in h for h in off["hits"]) and off["retrieval"]["delegated"] == 0


def test_children_must_be_search_candidates(kbl):
    """TC-KD-08 · 위임 조는 이번 검색 후보(합친 순위 20 안)에 든 것만 — 1위 근거라도 후보 밖이면 잇지 않는다
    (근거답 평가 A09 — 후보 51위 인가요건 조가 끼어 답이 빗나갔다) · 거름으로 검색에서 빠진 문서는 순위 3 안 근거의 첫째만."""
    conn = _ro(kbl)
    try:
        row = conn.execute("SELECT * FROM kb_chunk WHERE doc_id='stt_act' AND article='제8조'").fetchone()
        child = conn.execute("SELECT chunk_id FROM kb_chunk WHERE doc_id='stt_decree' AND article='제5조'"
                             " AND version_label LIKE '%35947%'").fetchone()[0]
        versions = {"stt_decree": conn.execute("SELECT version_label FROM kb_chunk WHERE chunk_id=?",
                                               (child,)).fetchone()[0]}
        hit = {"chunk_id": row["chunk_id"], "doc_id": "stt_act", "article": "제8조", "text": row["text"], "rank": 1}
        assert kb_links.find_links(conn, [hit], versions, {}) == {}                                   # 후보 밖
        assert kb_links.find_links(conn, [hit], versions, {child: kb_links.IN_SEARCH_TOP + 1}) == {}
        got = kb_links.find_links(conn, [hit], versions, {child: 7})
        assert [link.child["chunk_id"] for link in got[row["chunk_id"]]] == [child]
        # 거름으로 시행령이 검색에서 빠졌으면(후보 순위가 없다) 순위 3 안 근거의 첫째는 잇고 4위 근거는 잇지 않는다
        assert row["chunk_id"] in kb_links.find_links(conn, [hit], versions, {}, searched={"stt_act"})
        hit["rank"] = 4
        assert kb_links.find_links(conn, [hit], versions, {}, searched={"stt_act"}) == {}
    finally:
        conn.close()


def _h(cid: str, doc: str, art: str, text: str = "본문", delegated=None, via=None) -> dict:
    h = {"chunk_id": cid, "doc_id": doc, "title": kb_law.DOC_BY_ID[doc].title, "article": art, "article_title": "",
         "version_label": "판", "effective_at": "2026-01-02", "text": text, "grade": 1, "kind": "law", "part": "",
         "url": "", "score": 0.1}
    if delegated is not None:
        h["delegated"] = delegated
    if via is not None:
        h["via"] = via
    return h


VIA = {"chunk_id": "p", "doc_id": "stt_act", "title": "증권거래세법", "article": "제8조", "article_title": "세율",
       "ref": "법 제8조제2항", "para": 2, "level": "decree", "level_name": "대통령령", "score": 4}


def test_expand_order_and_context_notes():
    """TC-KD-09 · 위임 조는 윗 조 바로 뒤(뒤에 있던 것은 당겨 옴 · 겹치면 한 번) · 알림은 둘 다 들어간 때만."""
    child = _h("c", "stt_decree", "제5조", DEC5_NEW, via=VIA)
    parent = _h("p", "stt_act", "제8조", ACT8, delegated=[child])
    other = _h("o", "income_tax_act", "제129조", INCOME129)
    ev = kb_links.expand([parent, other, child])
    assert [e["chunk_id"] for e in ev] == ["p", "c", "o"]
    assert kb_links.pairs(ev) == [(1, 2, VIA)]
    # 아래 조가 먼저 나왔으면 그 자리 그대로 — 번호는 바뀐 자리로
    assert [e["chunk_id"] for e in kb_links.expand([child, parent])] == ["c", "p"]
    assert kb_links.pairs(kb_links.expand([child, parent])) == [(2, 1, VIA)]

    msgs, n = kb_answer.build_messages("세율은?", "2026-10-02", ev)
    user = msgs[1]["content"]
    assert n == 3
    assert "※ 이 조가 대통령령에 맡긴 내용은 [출처 2](증권거래세법 시행령 제5조)에 있다." in user
    assert "[출처 1] 증권거래세법 제8조제2항에서 대통령령에 맡긴 조(위임 조)" in user
    assert "6. 법 조가 값을" in msgs[0]["content"]
    # 글자 상한으로 위임 조가 빠지면 알림도 없다(없는 번호를 가리키지 않게)
    msgs1, n1 = kb_answer.build_messages("세율은?", "2026-10-02", ev, context_chars=len(ACT8) + 80)
    assert n1 == 1 and "※" not in msgs1[1]["content"] and "[출처 2]" not in msgs1[1]["content"]


def test_ask_cites_delegated_child_with_via(kbl):
    """TC-KD-10 · 답 API — 위임 조가 윗 조 바로 뒤 출처가 되고 via(윗 조 번호 · 부른 꼴)를 싣는다."""
    llm = FakeLlm("유가증권시장 주권의 세율은 1만분의 5다 [출처 2].")
    out = kb_answer.ask("증권거래세 세율", 3, mode="lexical", as_of="2026-10-02", docs=["stt_act"], synonyms=False,
                        path=kbl, backend=FakeDense(), llm_backend=llm, llm="llama3.1")
    assert out["status"] == "answered"
    assert [(c["doc_id"], c["article"]) for c in out["citations"][:2]] == [("stt_act", "제8조"), ("stt_decree", "제5조")]
    via = out["citations"][1]["via"]
    assert via["n"] == 1 and via["ref"] == "법 제8조제2항" and "대통령령에 맡긴 조" in via["label"]
    assert out["citations"][1]["used"] is True and "via" not in out["citations"][0]
    prompt = llm.calls[0]["messages"][1]["content"]
    assert "※ 이 조가 대통령령에 맡긴 내용은 [출처 2]" in prompt

    off = kb_answer.ask("증권거래세 세율", 3, mode="lexical", as_of="2026-10-02", docs=["stt_act"], links=False,
                        synonyms=False, path=kbl, backend=FakeDense(), llm_backend=FakeLlm("세율 [출처 1]."),
                        llm="llama3.1")
    assert [c["doc_id"] for c in off["citations"]] == ["stt_act"]


def test_children_never_push_out_original_hits():
    """TC-KD-12 · 위임 조는 원래 근거를 문맥 밖으로 밀어내지 않는다(근거답 평가 A09 — 관련 없는 1 · 2위 조의 위임 조가
    4,500자를 먼저 채워 4위 정답 조가 빠졌다) · 원래 근거가 먼저 · 위임 조는 따로 둔 몫 · 윗 조가 빠지면 위임 조도 뺀다."""
    body = "가" * 850
    a = _h("a", "capmkt_decree", "제16조", body)
    b = _h("b", "capmkt_decree", "제68조", body)
    a["delegated"] = [_h("ca", "fis_reg", "제2-1조", body, via={**VIA, "chunk_id": "a"})]
    b["delegated"] = [_h("cb", "fis_reg", "제4-19조", body, via={**VIA, "chunk_id": "b"})]
    rest = [_h("c", "capmkt_decree", "제324조의4", body), _h("d", "capmkt_act", "제176조", body),
            _h("e", "capmkt_decree", "제318조의5", body)]
    hits = [a, b, *rest]
    originals = [h["chunk_id"] for h in hits]
    ev = kb_links.expand(hits)
    assert [e["chunk_id"] for e in ev] == ["a", "ca", "b", "cb", "c", "d", "e"]

    off = [e["chunk_id"] for e in kb_answer.fit_evidence(hits, originals, link_chars=0)]
    # 기본(위임 조 몫 0) — 원래 근거는 끈 때와 같고 문맥은 상한을 넘지 않는다(내장 GPU 가 긴 문맥에서 멈춘 DF-65)
    base = kb_answer.fit_evidence(ev, originals)
    assert [e["chunk_id"] for e in base if e["chunk_id"] in originals] == off and "d" in off
    assert sum(len(kb_answer._block(i, e)) for i, e in enumerate(base, start=1)) <= kb_answer.CONTEXT_CHARS
    # 몫을 따로 주면 위임 조는 윗 조 바로 뒤 · 몫 안에서만
    picked = kb_answer.fit_evidence(ev, originals, link_chars=1800)
    fit = [e["chunk_id"] for e in picked]
    assert fit[:2] == ["a", "ca"] and [x for x in fit if x in originals] == off
    for lc in (0, 1000, 1800):                                           # 위임 조는 「남은 자리 + 몫」 안에서만
        got = kb_answer.fit_evidence(ev, originals, link_chars=lc)
        used = sum(len(kb_answer._block(1, e)) for e in got if e["chunk_id"] in originals)
        kids = sum(len(kb_answer._block(1, e)) for e in got if e["chunk_id"] not in originals)
        assert kids <= max(0, kb_answer.CONTEXT_CHARS - used) + lc, lc
    # 윗 조가 상한으로 빠지면 그 위임 조도 뺀다
    small = [e["chunk_id"] for e in kb_answer.fit_evidence(ev, originals, context_chars=1000, link_chars=1800)]
    assert small == ["a", "ca"]


def test_chain_label_avoids_particle_guess():
    """TC-KD-11 · 한 줄 꼴 — 조사는 「에서」(조 번호 끝 글자에 따라 이/가 가 바뀌지 않게) · 항이 없으면 조까지."""
    assert kb_links.chain_label(VIA) == "증권거래세법 제8조제2항에서 대통령령에 맡긴 조"
    assert kb_links.chain_label({**VIA, "para": None, "article": "제5조의3"}) == "증권거래세법 제5조의3에서 대통령령에 맡긴 조"
    assert kb_text.version_key("a", "b") == "a@b"
