"""벡터 저장 · 검색 시험 (TC-VS) — 문서 올리기 · 채팅 근거 검색이 쓰는 app/services/rag_pipeline.py.

무엇을 지키나 (DF-38 · 2026-10-02)
1. **저장한 것이 검색된다** — 예전에는 LangChain 의 QdrantVectorStore 에 비동기 클라이언트를 넘겨 만들 때마다
   죽었고, 그 오류를 except 가 삼켜 「0청크 저장」 · 「검색 결과 없음」 이 성공처럼 보였다.
2. **출처로 거르고 지우는 키가 맞다** — LangChain 은 메타데이터를 payload 의 "metadata" 아래에 두므로
   키는 "metadata.source" 다(예전 "source" 는 늘 0건 · 지우기는 아무것도 안 지우고 성공).
3. **실패는 숨기지 않는다** — 저장 실패는 VectorStoreError 로 올라가고(화면에 503 과 이유), 검색 실패는 채팅이 계속
   답할 수 있게 빈 목록이되 기록을 남긴다.

돌리는 법 — Qdrant 서버 없이 qdrant-client 의 **메모리 모드**(":memory:")와 글자로 만든 가짜 임베딩으로 돈다.
호스트 파이썬에 langchain-qdrant · langchain-ollama 가 없으면 이 파일만 건너뛴다(앱 이미지에는 있다).
"""
from __future__ import annotations

import asyncio
import math

import pytest

pytest.importorskip("langchain_qdrant")
pytest.importorskip("langchain_ollama")
qdrant_client = pytest.importorskip("qdrant_client")

from langchain_core.embeddings import Embeddings  # noqa: E402

from app.services import rag_pipeline as rp  # noqa: E402

DIM = 768   # 컬렉션을 만들 때 쓰는 크기(nomic-embed-text) — 가짜 임베딩도 같은 크기


class _CharEmbeddings(Embeddings):
    """글자를 768 칸에 흩어 세는 가짜 임베딩 — 같은 글자를 많이 나누는 글끼리 가깝다(네트워크 없음)."""

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * DIM
        for ch in text:
            v[ord(ch) % DIM] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


@pytest.fixture
def memory_qdrant(monkeypatch):
    """한 시험 안에서 같은 메모리 Qdrant 를 쓰게 한다(코드는 부를 때마다 클라이언트를 새로 만들고 닫는다)."""
    client = qdrant_client.QdrantClient(location=":memory:")
    client.close = lambda *a, **k: None   # 닫으면 메모리 저장소가 사라지므로 시험 동안은 열어 둔다
    monkeypatch.setattr(rp, "_make_client", lambda: client)
    monkeypatch.setattr(rp, "_make_embeddings", lambda: _CharEmbeddings())
    return client


def _run(coro):
    return asyncio.run(coro)


GAP = "괴리율은 ETF 가 거래소에서 거래되는 가격과 순자산가치(NAV)의 차이를 비율로 나타낸 값이다."
INAV = "iNAV 는 장중에 실시간으로 계산한 추정 순자산가치다."
BOND = "채권 가격은 금리가 오르면 내리고, 금리가 내리면 오른다."


def test_stored_chunks_are_found_again(memory_qdrant):
    """TC-VS-01 · 저장한 청크가 검색된다 — 본문(page_content) · 제목 · 주소 · 출처가 그대로 돌아온다."""
    meta = {"url": "upload://etf.txt", "title": "etf.txt", "source": "upload:u1:etf.txt"}
    assert _run(rp.store_chunks([GAP, INAV], meta, collection="docs")) == 2
    hits = _run(rp.rag_search("ETF 괴리율", top_k=2, collection="docs"))
    assert len(hits) == 2
    assert hits[0]["text"] == GAP, "가장 가까운 청크가 괴리율 문장이어야 한다"
    assert hits[0]["title"] == "etf.txt" and hits[0]["url"] == "upload://etf.txt"
    assert hits[0]["source"] == "upload:u1:etf.txt"


def test_filter_and_delete_use_the_metadata_source_key(memory_qdrant):
    """TC-VS-02 · 출처로 거르고 지우는 키가 "metadata.source" 다 — 다른 출처의 청크는 남는다."""
    assert rp.SOURCE_KEY == "metadata.source"
    _run(rp.store_chunks([GAP, INAV], {"source": "upload:u1:etf.txt", "title": "etf"}, collection="docs"))
    _run(rp.store_chunks([BOND], {"source": "upload:u2:bond.txt", "title": "bond"}, collection="docs"))

    only_bond = _run(rp.rag_search("금리", top_k=5, collection="docs", filter_source="upload:u2:bond.txt"))
    assert [h["text"] for h in only_bond] == [BOND]

    assert _run(rp.delete_chunks_by_source("upload:u1:etf.txt", collection="docs")) == 1
    left = _run(rp.rag_search("가격", top_k=5, collection="docs"))
    assert [h["source"] for h in left] == ["upload:u2:bond.txt"], "지운 출처의 청크가 남았다"


def test_store_failure_is_raised_not_hidden(monkeypatch):
    """TC-VS-03 · 저장 실패는 VectorStoreError 로 올라간다(예전: 0 을 돌려줘 「0청크 저장」 성공처럼 보였다)."""
    def _boom():
        raise ConnectionError("qdrant 에 닿지 않음")
    monkeypatch.setattr(rp, "_make_client", _boom)
    with pytest.raises(rp.VectorStoreError, match="ConnectionError"):
        _run(rp.store_chunks([GAP], {"source": "s"}, collection="docs"))
    assert _run(rp.store_chunks([], {"source": "s"}, collection="docs")) == 0   # 빈 입력은 그대로 0


def test_search_failure_returns_empty_so_chat_still_answers(monkeypatch):
    """TC-VS-04 · 검색 실패는 빈 목록 — 채팅은 근거 없이라도 답한다(대신 기록을 남긴다 · 로그는 시험에서 보지 않음)."""
    def _boom():
        raise ConnectionError("qdrant 에 닿지 않음")
    monkeypatch.setattr(rp, "_make_client", _boom)
    assert _run(rp.rag_search("괴리율", collection="docs")) == []


def test_vector_store_gets_a_sync_client():
    """TC-VS-05 · LangChain 에 넘기는 클라이언트는 동기 QdrantClient 다(비동기를 넘기면 만들 때 죽는다 — DF-38 재발 방지)."""
    import inspect

    src = inspect.getsource(rp)
    # 머리 주석이 옛 방식(비동기 클라이언트)을 설명하므로 이름 자체가 아니라 「가져오기 · 만들기」 만 본다.
    assert "import AsyncQdrantClient" not in src and "AsyncQdrantClient(" not in src
    assert "QdrantClient(url=settings.QDRANT_URL)" in inspect.getsource(rp._make_client)
