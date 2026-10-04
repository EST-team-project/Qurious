"""이름표 시험 (TC-TG) — `collector/tagging.py` (목표 기능 ① W7 · 설계서 5.1.6).

여기서 지키는 것 —
1. 주제 규칙 — 넣을 낱말로 붙이고, 뺄 낱말이 있으면 붙이지 않는다(「신주인수권부사채」 · 「주식분할」 이 합병·분할이 되지 않는다).
2. 용어 이름표 — 용어사전 표제어 · 다른 이름이 글에 그대로 나오면 붙인다. 긴 이름이 먼저고, 겹친 짧은 이름은 뺀다.
   영문 약어는 앞뒤가 영문 · 숫자가 아닐 때만(「SPAC」 안의 「PA」 를 막는다).
3. 종목 이름 사전 — 세 글자 미만 · 스팩 · 우선주(본주가 있으면)를 빼고, 긴 이름부터 맞춘다.
4. 공시는 DART 종목 코드 칸 · 유형을 그대로 · 뉴스는 이름이 글에 있을 때만 종목을 붙인다(검색어로 쓴 종목이라도).

네트워크를 쓰지 않는다.
"""
from __future__ import annotations

from collector import tagging as T


def topics(s):
    return [t for t, _ in T.topics_of(s)]


def test_topic_rules_include_and_exclude():
    """TC-TG-01 · 공시 제목 열한 꼴 — 주제가 하나씩 바르게 붙고 헷갈리는 꼴은 빠진다."""
    assert topics("주요사항보고서(유상증자결정)") == ["증자"]
    assert topics("주요사항보고서(신주인수권부사채권발행결정)") == ["사채"]
    assert topics("주식분할결정") == ["주식분할"]                    # 합병·분할에 붙지 않는다
    assert topics("회사분할결정") == ["합병·분할"]
    assert topics("연결재무제표기준영업(잠정)실적(공정공시)") == ["실적"]
    assert topics("현금ㆍ현물배당결정") == ["배당"]
    assert topics("단일판매ㆍ공급계약체결") == ["공급계약"]
    assert topics("[기재정정]주주총회소집결의 (임시주주총회)") == ["주주총회"]
    assert topics("감사보고서제출") == ["회계·감사"]
    assert topics("주권매매거래정지기간변경 (상장적격성 실질심사 대상 결정)") == ["거래정지·상장"]
    assert topics("상장채권관련기타주요사항") == []


def test_topics_match_spaced_news_text():
    """TC-TG-02 · 뉴스처럼 띄어 쓴 글에도 맞는다(공백을 빼고 찾는다) · 한 주제는 한 번."""
    assert topics("A사, 2천억 공급 계약 체결 … 수주 잔고 늘어") == ["공급계약"]
    assert topics("기준 금리 인하 기대에 배당주 강세") == ["배당", "금리"]


def test_terms_longest_first_and_ascii_boundary():
    """TC-TG-03 · 긴 표제어가 먼저 · 겹친 짧은 것은 뺀다 · 영문 약어는 낱말 경계에서만."""
    entries = [T.TermEntry("자기주식", "자기주식"), T.TermEntry("자기주식처분", "자기주식처분"),
               T.TermEntry("PER", "PER"), T.TermEntry("ETF", "ETF")]
    entries.sort(key=lambda e: -len(e.name))
    assert T.terms_of("자기주식처분결정", entries) == ["자기주식처분"]
    assert T.terms_of("저PER 종목과 ETF 자금", entries) == ["PER", "ETF"]
    assert T.terms_of("SUPERETF", entries) == []                        # 낱말 안의 약어는 아니다


def test_name_dict_drops_short_spac_and_preferred():
    """TC-TG-04 · 세 글자 미만 · 스팩 · 본주가 있는 우선주는 사전에서 빠지고, 긴 이름부터 맞춘다."""
    names = T.build_name_dict([("005930", "삼성전자"), ("005935", "삼성전자우"), ("001680", "대상"),
                               ("435870", "신한제11호스팩"), ("000660", "SK하이닉스"), ("028260", "삼성물산")])
    assert [(e.name, e.symbol) for e in names] == [("SK하이닉스", "000660"), ("삼성전자", "005930"), ("삼성물산", "028260")]
    assert T.symbols_of("삼성전자 · SK하이닉스 반도체 · 대상 그룹", names) == ["000660", "005930"]


def test_disclosure_and_news_tags():
    """TC-TG-05 · 공시는 DART 칸(종목 · 유형)을 그대로 · 뉴스는 글에 이름이 있을 때만 종목 이름표."""
    terms = [T.TermEntry("유상증자", "유상증자")]
    d = T.disclosure_tags({"stock_code": "006360", "pblntf_ty": "B", "report_nm": "주요사항보고서(유상증자결정)",
                           "title": "주요사항보고서(유상증자결정)"}, terms)
    assert ("symbol", "006360", "dart_field") in d and ("dtype", "B", "dart_type") in d
    assert ("topic", "증자", "rule:유상증자") in d and ("term", "유상증자", "glossary") in d
    names = T.build_name_dict([("006360", "GS건설")])
    with_name = T.news_tags({"title": "GS건설, 유상증자 결정", "description": ""}, names, terms, query_symbol="006360")
    assert ("symbol", "006360", "name_dict:query") in with_name
    without = T.news_tags({"title": "건설업계 유상증자 잇따라", "description": ""}, names, terms, query_symbol="006360")
    assert not [t for t in without if t[0] == "symbol"]
