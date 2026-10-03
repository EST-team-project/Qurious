"""근거 문서 찾기 시험 (TC-KB) — `GET /api/kb/search` · `GET /api/kb/documents` (목표 기능 ① W5 · 설계서 5.3.3 · 8절 「TC-KB」).

무엇을 지키나 —
1. **기준일의 판만** 찾는다 — 증권거래세 세율처럼 판마다 값이 다른 조는 기준일에 시행 중인 판의 글만 나온다.
   그 기준일에 판이 없는 문서는 조용히 옛 판을 쓰지 않고 `missing` 에 싣는다.
2. **질문 분류 가중** — 세금 · 회사 · 투자 규제 낱말이 있으면 그 문서 후보를 한 번 더 세어(RRF 셋째 목록) 앞으로
   옮긴다. 거르지 않으므로 분류가 틀려도 답이 0건이 되지 않는다. 「배당」 처럼 세 묶음에 다 걸리는 말은 넣지 않았다.
3. **벡터가 꺼져도 낱말로 답한다** — Qdrant · Ollama 에 닿지 못하면 `dense_error` 를 싣고 낱말 결과를 준다.
4. **벡터 DB 의 옛 점은 버린다** — 다시 쪼갠 뒤 남은 점(지금 SQLite 에 없는 청크 ID)을 결과에 싣지 않는다.
5. 잘못된 입력은 422 · DB 가 없으면 503 과 할 일.
6. 문서 목록의 벡터 수는 **본문 지문이 같은 것만** 센다(쪼개기를 바꾼 뒤 옛 벡터는 「넣은 것」 이 아니다).
7. 문서 목록은 로그인 없이 · 찾기는 로그인 뒤.

네트워크 · 실제 kb.sqlite3 를 쓰지 않는다 — 작은 가짜 문서로 시험 DB 를 만든다(수집기의 실제 스키마 · 쪼개기 그대로).
"""
from __future__ import annotations

import urllib.error
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.lib.session import get_current_user
from app.routes import kb as kb_routes
from app.services import kb_search, kb_text
from collector import kb_law
from collector.kb_law import Article, DocSpec


def _v(no: str, prom: str, eff: str, law_type: str = "대통령령") -> kb_text.Version:
    return kb_text.Version(source_id=f"s{no}", promulgation_no=no, promulgated_at=prom, effective_at=eff,
                           status="", law_type=law_type)


def _store(conn, spec: DocSpec, v: kb_text.Version, arts: list[Article]) -> None:
    chunks = [c for a in arts for c in kb_law.chunk_article(spec.title, a)]
    sha = kb_text.text_sha256("\n\n".join(f"{a.label}\n{a.body}" for a in arts))
    kb_law.store_version(conn, spec, v, spec.title, "", chunks, len(arts), sha, "2026-10-02", "", "")


COMMERCIAL = kb_law.DOC_BY_ID["commercial_act"]
INCOME = kb_law.DOC_BY_ID["income_tax_act"]
FCPA = kb_law.DOC_BY_ID["fcpa_act"]
STT = kb_law.DOC_BY_ID["stt_decree"]
FUTURE = DocSpec("future_rule", "내년에 시행되는 규정", "admrul", 2)

OLD_RATE = "유가증권시장에서 양도되는 주권: 1만분의 15 · 코스닥시장에서 양도되는 주권: 1만분의 15"
NEW_RATE = "유가증권시장에서 양도되는 주권: 1만분의 5 · 코스닥시장에서 양도되는 주권: 1만분의 20"


@pytest.fixture()
def kb(tmp_path) -> Path:
    path = tmp_path / "kb.sqlite3"
    conn = kb_law.connect(path)
    _store(conn, COMMERCIAL, _v("21044", "2025-03-04", "2026-09-10", "법률"), [
        Article("제651조", "고지의무위반으로 인한 계약해지", "제4편 보험 > 제1장 통칙",
                "보험계약당시에 보험계약자 또는 피보험자가 고의 또는 중대한 과실로 인하여 중요한 사항을 고지하지 "
                "아니하거나 부실의 고지를 한 때에는 보험자는 위험을 안 날부터 1월 내에 계약을 해지할 수 있다."),
        Article("제464조의2", "이익배당의 지급시기", "제3편 회사 > 제4장 주식회사 > 제7절 회사의 회계 <개정 2011.4.14>",
                "회사는 이익배당을 주주총회나 이사회의 결의가 있은 날부터 1개월 내에 하여야 한다."),
    ])
    _store(conn, INCOME, _v("21221", "2025-12-23", "2026-07-01", "법률"), [
        Article("제17조", "배당소득", "제2장 거주자의 종합소득 및 퇴직소득에 대한 납세의무",
                "배당소득은 해당 과세기간에 발생한 다음 각 호의 소득으로 한다. 내국법인으로부터 받는 이익이나 잉여금의 배당"),
    ])
    _store(conn, FCPA, _v("21065", "2025-12-30", "2026-01-02", "법률"), [
        Article("제19조", "설명의무", "제4장 금융상품판매업자등의 영업행위 준수사항",
                "금융상품판매업자등은 일반금융소비자에게 계약 체결을 권유하는 경우 금융상품의 위험 등 중요한 사항을 "
                "일반금융소비자가 이해할 수 있도록 설명하여야 한다."),
    ])
    _store(conn, STT, _v("35300", "2025-02-28", "2025-02-28"), [Article("제5조", "탄력세율", "", OLD_RATE)])
    _store(conn, STT, _v("35947", "2025-12-30", "2026-01-02"), [Article("제5조", "탄력세율", "", NEW_RATE)])
    _store(conn, FUTURE, _v("2027-1", "2026-09-30", "2027-01-01", "고시"), [
        Article("제1조", "목적", "", "이 규정은 증권거래세 세율 공시의 방법을 정한다."),
    ])
    conn.close()
    return path


def cid(path: Path, doc: str, article: str) -> str:
    import sqlite3

    c = sqlite3.connect(path)
    try:
        return c.execute("SELECT chunk_id FROM kb_chunk WHERE doc_id=? AND article=? ORDER BY version_label DESC",
                         (doc, article)).fetchone()[0]
    finally:
        c.close()


class FakeDense(kb_search.DenseBackend):
    """Qdrant · Ollama 대신 — 정해 둔 청크 ID 순서를 돌려준다."""

    def __init__(self, ids: list[str] | None = None, fail: Exception | None = None):
        super().__init__(ollama_url="http://fake-ollama", qdrant_url="http://fake-qdrant")
        self.ids, self.fail, self.calls = ids or [], fail, []

    def embed(self, model, q):
        if self.fail:
            raise self.fail
        return [0.0] * model.dim

    def query(self, model, vec, keys, n):
        self.calls.append(sorted(keys))
        return list(self.ids)


def test_as_of_picks_version_and_reports_missing(kb):
    """TC-KB-01 · 기준일에 시행 중인 판의 글만 · 판이 없는 문서는 missing."""
    old = kb_search.search("증권거래세 세율 유가증권시장", 3, as_of="2025-06-01", mode="lexical", path=kb)
    assert [h["version_label"] for h in old["hits"] if h["doc_id"] == "stt_decree"] == ["대통령령 제35300호 · 2025-02-28 시행"]
    assert "1만분의 15" in old["hits"][0]["text"]

    new = kb_search.search("증권거래세 세율 유가증권시장", 3, as_of="2026-10-02", mode="lexical", path=kb)
    stt = [h for h in new["hits"] if h["doc_id"] == "stt_decree"]
    assert len(stt) == 1 and "1만분의 5" in stt[0]["text"] and "1만분의 15" not in stt[0]["text"]
    assert [m["doc_id"] for m in new["missing"]] == ["future_rule"]
    assert new["missing"][0]["earliest_effective_at"] == "2027-01-01"
    assert all(h["doc_id"] != "future_rule" for h in new["hits"])
    # 판이 아직 없던 날에는 그 문서도 missing — 옛 판을 대신 쓰지 않는다
    early = kb_search.search("배당", 3, as_of="2025-01-01", mode="lexical", path=kb)
    assert {m["doc_id"] for m in early["missing"]} >= {"stt_decree", "fcpa_act", "income_tax_act"}


def test_classify_domains():
    """TC-KB-02 · 질문 분류 — 세금 · 회사 · 투자 규제 · 없음 · 「배당」 만으로는 고르지 않는다."""
    assert kb_search.classify("배당소득 세금은 얼마나 내나")[0] == ["tax"]
    assert "income_tax_act" in kb_search.classify("배당소득 세금")[1]
    assert kb_search.classify("주주총회 결의 요건")[0] == ["company"]
    assert kb_search.classify("투자권유 할 때 설명의무")[0] == ["regulation"]
    assert kb_search.classify("로보 어드바이저 규제")[0] == ["regulation"]       # 띄어 써도
    assert kb_search.classify("이익배당 세율")[0] == ["tax", "company"]          # 둘 다 걸리면 합친다
    assert kb_search.classify("배당금 언제 들어와요") == ([], [])
    assert kb_search.classify("오늘 날씨") == ([], [])


def test_route_reorders_without_filtering(kb):
    """TC-KB-03 · 가중은 순위만 옮긴다 — 끄면 보험편이 먼저 · 켜면 금융소비자보호법이 먼저 · 둘 다 결과에 남는다."""
    c651, f19 = cid(kb, "commercial_act", "제651조"), cid(kb, "fcpa_act", "제19조")
    # 낱말은 보험편(「고지의무」 머리 · 본문 고지 둘)을 1위로, 가짜 벡터는 설명의무를 1위로 — 끄면 동점이라 먼저 나온 보험편
    q = "위험 고지의무"
    off = kb_search.search(q, 5, as_of="2026-10-02", path=kb, route=False, backend=FakeDense([f19, c651]))
    on = kb_search.search(q, 5, as_of="2026-10-02", path=kb, route=True, backend=FakeDense([f19, c651]))
    assert off["hits"][0]["ranks"]["lexical"] == 1
    assert on["route"]["domains"] == ["regulation"] and "fcpa_act" in on["route"]["docs"]
    assert off["hits"][0]["chunk_id"] == c651
    assert on["hits"][0]["chunk_id"] == f19
    assert {h["chunk_id"] for h in on["hits"]} >= {c651, f19}
    assert on["retrieval"]["method"] == "fts5+dense+rrf"


def test_dense_down_falls_back_to_lexical(kb):
    """TC-KB-04 · 벡터 쪽에 닿지 못하면 낱말만 · dense 만 달라면 503."""
    down = FakeDense(fail=urllib.error.URLError("refused"))
    r = kb_search.search("이익배당 지급시기", 3, as_of="2026-10-02", path=kb, backend=down)
    assert r["retrieval"]["method"] == "fts5"
    assert "닿지 못했다" in r["retrieval"]["dense_error"]
    assert r["hits"] and r["hits"][0]["article"] == "제464조의2"
    assert r["model"] is None
    with pytest.raises(kb_search.KbError) as e:
        kb_search.search("이익배당", 3, as_of="2026-10-02", path=kb, mode="dense", backend=down)
    assert e.value.status == 503


def test_stale_vector_points_are_dropped(kb):
    """TC-KB-05 · SQLite 에 없는 청크 ID(다시 쪼개기 전의 점)는 결과에 싣지 않는다 · 순위는 거른 뒤로 센다."""
    f19 = cid(kb, "fcpa_act", "제19조")
    r = kb_search.search("설명", 3, as_of="2026-10-02", path=kb, mode="dense",
                         backend=FakeDense(["0" * 32, f19]))
    assert [h["chunk_id"] for h in r["hits"]] == [f19]
    assert r["hits"][0]["ranks"] == {"dense": 1}
    assert r["retrieval"]["candidates"] == {"dense": 1}


def test_hit_shape_and_part_cleaned(kb):
    """TC-KB-05b · 결과 한 줄 — 출처를 달 칸이 다 있고 경로의 <개정 …> 꼬리표는 뺀다."""
    r = kb_search.search("이익배당 지급시기", 1, as_of="2026-10-02", mode="lexical", path=kb)
    h = r["hits"][0]
    assert {"chunk_id", "doc_id", "title", "grade", "version_label", "effective_at", "article", "article_title",
            "part", "text", "url", "score", "ranks"} <= set(h)
    assert h["part"] == "제3편 회사 > 제4장 주식회사 > 제7절 회사의 회계"
    assert h["text"].splitlines()[0] == "상법 > 제3편 회사 > 제4장 주식회사 > 제7절 회사의 회계 > 제464조의2(이익배당의 지급시기)"
    assert r["source"] and r["notice"]


@pytest.mark.parametrize("kw", [
    {"k": 0}, {"k": kb_search.MAX_K + 1}, {"mode": "both"}, {"kind": "news"}, {"as_of": "20261002"},
    {"as_of": "2026-13-01"}, {"docs": ["nope_act"]}, {"model": "gpt"},
])
def test_bad_input_is_422(kb, kw):
    """TC-KB-06 · 잘못된 입력은 422 와 고칠 말."""
    args = {"k": 3, **kw}
    with pytest.raises(kb_search.KbError) as e:
        kb_search.search("세율", args.pop("k"), path=kb, mode=args.pop("mode", "lexical"), **args)
    assert e.value.status == 422


def test_missing_db_is_503_with_hint(tmp_path, monkeypatch):
    """TC-KB-06b · kb.sqlite3 가 없으면 503 과 할 일 — KB_DB_PATH 가 없는 파일이면 db_path() 는 None."""
    monkeypatch.setenv(kb_search.ENV_DB_PATH, str(tmp_path / "none.sqlite3"))
    assert kb_search.db_path() is None
    with pytest.raises(kb_search.KbError) as e:
        kb_search.search("세율", 3, mode="lexical")
    assert e.value.status == 503 and "kb_law fetch" in e.value.hint
    with pytest.raises(kb_search.KbError):
        kb_search.search("   ", 3, path=tmp_path / "none.sqlite3")


def test_documents_counts_only_current_vectors(kb):
    """TC-KB-07 · 판 목록 · 벡터 수는 본문 지문이 같은 것만 · kind 거름."""
    import sqlite3

    c = sqlite3.connect(kb)
    rows = c.execute("SELECT chunk_id, text_sha256 FROM kb_chunk WHERE doc_id='commercial_act' ORDER BY article_key").fetchall()
    c.execute("INSERT INTO kb_vector VALUES (?, 'bge-m3', ?, 1024, '2026-10-03T00:00:00+09:00')", rows[0])
    c.execute("INSERT INTO kb_vector VALUES (?, 'bge-m3', 'stale', 1024, '2026-10-03T00:00:00+09:00')", (rows[1][0],))
    c.commit()
    c.close()
    d = kb_search.documents(path=kb)
    com = next(x for x in d["documents"] if x["doc_id"] == "commercial_act")
    assert com["vectors"] == {"bge-m3": 1, "nomic-embed-text": 0}
    assert [x["version_label"] for x in d["documents"] if x["doc_id"] == "stt_decree"] == [
        "대통령령 제35947호 · 2026-01-02 시행", "대통령령 제35300호 · 2025-02-28 시행"]   # 새 판이 먼저
    assert {x["kind"] for x in kb_search.documents("admrul", path=kb)["documents"]} == {"admrul"}
    with pytest.raises(kb_search.KbError):
        kb_search.documents("news", path=kb)


def test_index_prune_drops_points_of_vanished_chunks(kb, monkeypatch):
    """TC-KB-09 · 다시 쪼개 사라진 청크 ID 의 점은 넣기 전에 지운다 · 남아 있는 청크의 점은 그대로."""
    import sqlite3

    from collector import kb_index

    c = sqlite3.connect(kb)
    live = c.execute("SELECT chunk_id, text_sha256 FROM kb_chunk LIMIT 1").fetchone()
    c.execute("INSERT INTO kb_vector VALUES (?, 'bge-m3', ?, 1024, 'x')", live)
    c.execute("INSERT INTO kb_vector VALUES (?, 'bge-m3', 'old', 1024, 'x')", ("f" * 32,))
    c.execute("INSERT INTO kb_vector VALUES (?, 'nomic-embed-text', 'old', 768, 'x')", ("f" * 32,))
    c.commit()
    calls = []
    monkeypatch.setattr(kb_index, "_http", lambda method, url, body=None, timeout=600: calls.append((method, url, body)) or {})
    assert kb_index.prune(c) == 1
    assert calls == [("POST", f"{kb_index.QDRANT_URL}/collections/kb_v1/points/delete?wait=true",
                      {"points": [kb_text.point_id("f" * 32)]})]
    assert [r[0] for r in c.execute("SELECT chunk_id FROM kb_vector")] == [live[0]]
    assert kb_index.prune(c) == 0 and len(calls) == 1          # 지울 것이 없으면 부르지 않는다
    c.close()


def test_api_documents_public_search_needs_login(kb, monkeypatch):
    """TC-KB-08 · 문서 목록은 로그인 없이 200 · 찾기는 401 → 로그인하면 200."""
    monkeypatch.setenv(kb_search.ENV_DB_PATH, str(kb))
    app = FastAPI()
    app.include_router(kb_routes.router)
    c = TestClient(app)
    assert c.get("/api/kb/documents").status_code == 200
    assert c.get("/api/kb/search", params={"q": "세율"}).status_code == 401
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "name": "시험", "email": "t@example.com"}
    j = c.get("/api/kb/search", params={"q": "증권거래세 세율", "mode": "lexical", "as_of": "2026-10-02"}).json()
    assert j["hits"] and j["hits"][0]["doc_id"] == "stt_decree"
    bad = c.get("/api/kb/search", params={"q": "세율", "mode": "lexical", "docs": "nope_act"})
    assert bad.status_code == 422 and "있는 것" in bad.json()["detail"]["hint"]
