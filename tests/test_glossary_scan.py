"""TC-GS — 글 속 용어 찾기 (app/services/glossary_scan.py · POST /api/glossary/scan · 2026-10-17 · 모의투자 점검 L5).

지키는 것
  - 대표 이름 · 별칭을 찾고 띄어쓰기는 접어 견준다(「볼린저 밴드」 = 「볼린저밴드」)
  - 영문은 대문자 약어만 · 글 쪽도 대문자(「per」 · 「performance」 · 「AI」 에 걸리지 않음)
  - 한글 두 글자 이하는 금융 고유어만 · 낱말 경계(「배당금」 안의 「배당」 은 아님)
  - 같은 용어는 한 번 · 나온 차례 · 상한 · 자리(at)와 글자(matched)는 원래 글 그대로
  - 경계 · 겹침 규칙은 종목 이름 찾기와 같은 한 곳(text_match)
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services import glossary, glossary_scan as G, text_match


def _seed(tmp_path, terms):
    p = tmp_path / "terms.json"
    p.write_text(json.dumps({"format_version": 2, "sources": [], "categories": [], "terms": terms, "relations": []},
                            ensure_ascii=False), encoding="utf-8")
    return p


def _t(tid, term, *aliases, summary="풀이"):
    return {"id": tid, "term": term, "aliases": [{"alias": a, "kind": "약어"} for a in aliases], "summary": summary}


TERMS = [
    _t("rsi", "RSI", "상대강도지수"), _t("macd", "MACD"), _t("볼린저밴드", "볼린저밴드", "Bollinger Bands"),
    _t("per", "주가수익비율", "PER"), _t("ai", "인공지능", "AI"), _t("배당", "배당"), _t("배당금", "배당금"),
    _t("경제", "경제"), _t("골든크로스", "골든크로스"), _t("buy", "매수 주문", "Buy"),
]


@pytest.fixture
def table(tmp_path):
    return G.entries(_seed(tmp_path, TERMS))


def test_entries_rules(table, tmp_path):
    """TC-GS-01 · 찾을 이름 — 영문은 대문자 약어만(「Bollinger Bands」 · 「Buy」 빠짐) · AI 빠짐 · 두 글자 한글은 고유어만(「경제」 빠짐) ·
    두 용어가 같은 이름을 가지면 먼저 가진 쪽(용어사전 별칭 표와 같은 규칙)."""
    names = {n for n, *_ in table}
    assert {"RSI", "상대강도지수", "MACD", "볼린저밴드", "PER", "주가수익비율", "배당", "배당금", "골든크로스", "매수주문"} <= names
    assert not names & {"BollingerBands", "Buy", "AI", "경제", "bollingerbands"}
    d = tmp_path / "shared"
    d.mkdir()
    shared = G.entries(_seed(d, [_t("first", "앞용어", "같은별칭"), _t("second", "뒤용어", "같은별칭")]))
    assert [tid for n, tid, *_ in shared if n == "같은별칭"] == ["first"]


@pytest.mark.parametrize("text, want", [
    ("RSI 가 30 아래이고 MACD 가 신호선 위입니다", ["rsi", "macd"]),
    ("종가가 볼린저 밴드 하단을 벗어났습니다", ["볼린저밴드"]),                  # 띄어쓰기를 접어 견줌
    ("PER 은 주가수익비율이라고도 합니다", ["per"]),                            # 같은 용어는 한 번
    ("per share performance 와 AI 전망", []),                                  # 소문자 · 영어 낱말 · AI
    ("배당은 해마다 달라요", ["배당"]),
    ("배당금을 받는 날", ["배당금"]),                                           # 긴 이름이 이김 · 「배당」 따로 없음
    ("배당금을 받고 배당은 따로", ["배당금", "배당"]),                         # 앞 자리가 경계에 걸려도(배당금 안) 뒤 자리는 읽는다
    ("경제가 좋아지면", []),
    ("골든크로스가 나오고 RSI 도 올랐다", ["골든크로스", "rsi"]),               # 나온 차례
])
def test_scan_cases(table, text, want):
    """TC-GS-02 · 글 속 용어 — 경계 · 겹침 · 한 번 · 차례 · 자리와 글자는 원래 글 그대로."""
    got = G.scan(text, table=table)
    assert [x["id"] for x in got] == want
    for x in got:
        assert text[x["at"]:x["at"] + len(x["matched"])] == x["matched"]
        assert x["summary"] == "풀이"


def test_scan_limit_and_cap(table, tmp_path):
    """TC-GS-03 · 상한(최대 20 · 최소 1) · 4,000자 뒤는 보지 않는다."""
    text = "RSI MACD 볼린저밴드 PER 배당 골든크로스"
    assert len(G.scan(text, table=table, limit=3)) == 3 and len(G.scan(text, table=table, limit=999)) == 6
    assert len(G.scan(text, table=table, limit=0)) == 1
    assert G.scan("가" * G.MAX_TEXT + " RSI", table=table) == []
    d = tmp_path / "many"
    d.mkdir()
    many = G.entries(_seed(d, [_t(f"t{i}", f"용어{i:02d}번") for i in range(25)]))
    assert len(G.scan(" ".join(f"용어{i:02d}번" for i in range(25)), table=many, limit=999)) == G.MAX_LIMIT


def test_entries_cache_follows_file(tmp_path):
    """TC-GS-04 · 같은 파일 · 같은 수정 시각이면 지난 목록 · 파일이 바뀌면 다시 만든다."""
    import os
    p = _seed(tmp_path, [_t("rsi", "RSI")])
    first = G.entries(p)
    assert G.entries(p) is first
    p.write_text(json.dumps({"format_version": 2, "sources": [], "categories": [], "relations": [],
                             "terms": [_t("rsi", "RSI"), _t("macd", "MACD")]}, ensure_ascii=False), encoding="utf-8")
    st = p.stat()
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    assert {n for n, *_ in G.entries(p)} == {"RSI", "MACD"}


def test_real_glossary_has_signal_terms():
    """TC-GS-05 · 실제 용어 파일 — 신호 · 패턴 설명에 쓰는 낱말이 찾아진다(용어가 빠지면 칩이 비어 보인다)."""
    got = G.scan("일봉은 RSI 가 과열이고 MACD 가 신호선 아래 · 볼린저 밴드 상단 · 골든크로스 · 부채비율 120%")
    ids = [x["id"] for x in got]
    for want in ("rsi", "macd", "볼린저밴드", "골든크로스", "부채비율"):
        assert want in ids, (want, ids)


def test_same_rules_module_as_stock_mentions():
    """TC-GS-06 · 경계 · 겹침 규칙은 한 곳 — 두 찾기가 text_match 를 모듈 이름으로 부른다(별칭으로 묶으면 고쳐도 따라가지 않음) ·
    짧은 한글 이름은 앞 · 뒤 모두 낱말 경계(「태양광」 의 태양 · 「고배당」 의 배당은 아님)."""
    import inspect
    from app.services import stock_hub
    for mod in (G, stock_hub):
        src = inspect.getsource(mod)
        assert "text_match.edges_ok(" in src and "text_match.longest_first(" in src
        assert "def edges_ok" not in src and "def longest_first" not in src
    assert text_match.edges_ok("태양광", 0, 2, "태양") is False and text_match.edges_ok("SKT", 0, 2, "SK") is False
    assert text_match.edges_ok("고배당", 1, 3, "배당") is False and text_match.edges_ok("배당은", 0, 2, "배당") is True


@pytest.fixture
def client():
    from app.routes import glossary as routes
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app)


def test_scan_endpoint(client, monkeypatch, tmp_path):
    """TC-GS-07 · POST /api/glossary/scan — 로그인 없이 · 빈 글 · 너무 긴 글 · 상한 넘김은 422."""
    monkeypatch.setattr(glossary, "SEED_PATH", _seed(tmp_path, TERMS))
    r = client.post("/api/glossary/scan", json={"text": "RSI 와 MACD"})
    assert r.status_code == 200 and [x["id"] for x in r.json()["items"]] == ["rsi", "macd"] and "rule" in r.json()
    assert client.post("/api/glossary/scan", json={"text": ""}).status_code == 422
    assert client.post("/api/glossary/scan", json={"text": "가" * (G.MAX_TEXT + 1)}).status_code == 422
    assert client.post("/api/glossary/scan", json={"text": "RSI", "limit": G.MAX_LIMIT + 1}).status_code == 422
