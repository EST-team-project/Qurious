"""LangChain LCEL 기반 RAG 파이프라인.

구성:
  OllamaEmbeddings  →  QdrantVectorStore  →  similarity_search
  LCEL 체인: retriever | format_docs | prompt | llm | StrOutputParser
"""
from __future__ import annotations
import asyncio
import logging
from typing import Any

from langchain_ollama import OllamaEmbeddings
from langchain_qdrant import QdrantVectorStore
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough, RunnableLambda
from langchain_ollama import ChatOllama
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, FieldCondition, Filter, MatchValue, VectorParams

from app.config import settings
from app.lib.llm_limits import answer_options


class CompatibleQdrantStore(QdrantVectorStore):
    @classmethod
    def _document_from_point(cls, point, collection_name, content_payload_key, metadata_payload_key):
        payload = point.payload or {}
        metadata = dict(payload.get(metadata_payload_key) or {k:v for k,v in payload.items() if k not in ('text','page_content')})
        metadata.update({'_id':point.id,'_collection_name':collection_name})
        return Document(page_content=payload.get(content_payload_key) or payload.get('text') or payload.get('page_content') or '', metadata=metadata)


# ── 내부 팩토리 ───────────────────────────────────────────────────────────────
#
# (Qurious 2026-10-02 · DF-38) 예전에는 LangChain 의 QdrantVectorStore 에 **비동기** 클라이언트(AsyncQdrantClient)를
# 넘겼다. langchain-qdrant 1.x 의 QdrantVectorStore 는 만들 때 컬렉션 설정을 **동기 호출**로 검사하므로
# 'coroutine' object has no attribute 'config' 로 죽었고, 아래 함수들의 except 가 그것을 삼켜 「0청크 저장」 ·
# 「검색 결과 없음」 이 성공처럼 보였다 — 문서 저장 · 검색이 한 번도 동작한 적이 없다.
# 그래서 동기 QdrantClient 를 넘긴다. 비동기 메서드(aadd_documents · asimilarity_search_with_score)는
# 부모 VectorStore 가 동기판을 실행기(스레드)에서 돌린다. 동기 네트워크 호출은 asyncio.to_thread 로 밀어낸다.

#: LangChain 은 메타데이터를 payload 의 "metadata" 아래에 둔다 → 출처로 거르거나 지울 때의 키(예전 "source" 는 늘 0건).
SOURCE_KEY = "metadata.source"


def _make_embeddings() -> OllamaEmbeddings:
    return OllamaEmbeddings(
        base_url=settings.OLLAMA_BASE_URL,
        model=settings.EMBED_MODEL,
    )


def _make_client() -> QdrantClient:
    """LangChain 에 넘길 동기 클라이언트(시험은 이 함수를 메모리 Qdrant 로 바꾼다)."""
    return QdrantClient(url=settings.QDRANT_URL)


def _ensure_collection(client: QdrantClient, collection: str) -> None:
    """Qdrant 컬렉션이 없으면 nomic-embed-text 기준 dim=768로 생성한다."""
    if not client.collection_exists(collection):
        client.create_collection(
            collection,
            vectors_config=VectorParams(size=768, distance=Distance.COSINE),
        )


def _log():
    # 모듈을 읽을 때 만든 로거는 앱 시작 때 alembic 의 로그 설정이 꺼 버린다(옛 분석 D3) — 쓸 때 만들어 살아 있게.
    return logging.getLogger("qurious.rag_pipeline")


class VectorStoreError(RuntimeError):
    """벡터 저장소에 쓰지 못했다 — 부르는 쪽이 사용자에게 이유를 보여 줄 수 있게 삼키지 않고 올린다."""


async def _open_store(collection: str) -> tuple[QdrantClient, QdrantVectorStore]:
    client = _make_client()
    await asyncio.to_thread(_ensure_collection, client, collection)
    store = await asyncio.to_thread(
        QdrantVectorStore, client=client, collection_name=collection, embedding=_make_embeddings(),
    )
    return client, store


# ── 공개 함수 ─────────────────────────────────────────────────────────────────

async def rag_search(
    query:      str,
    top_k:      int  = 5,
    collection: str | None = None,
    filter_source: str | None = None,
) -> list[dict]:
    """
    LangChain QdrantVectorStore를 통해 유사 문서를 검색한다.

    Args:
        query:         검색 쿼리
        top_k:         반환할 최대 문서 수
        collection:    Qdrant 컬렉션명 (None이면 settings.QDRANT_COLLECTION 사용)
        filter_source: 특정 source만 필터링 (예: "upload", "github:...")

    Returns:
        [{"text": ..., "url": ..., "title": ..., "source": ..., "score": ...}, ...]
    """
    coll = collection or settings.QDRANT_COLLECTION
    try:
        client, store = await _open_store(coll)

        qdrant_filter = None
        if filter_source:
            qdrant_filter = Filter(
                must=[FieldCondition(key=SOURCE_KEY, match=MatchValue(value=filter_source))]
            )

        results = await store.asimilarity_search_with_score(
            query, k=top_k, filter=qdrant_filter
        )
        client.close()

        return [
            {
                "text":   doc.page_content,
                "url":    doc.metadata.get("url", ""),
                "title":  doc.metadata.get("title", ""),
                "source": doc.metadata.get("source", ""),
                "score":  float(score),
            }
            for doc, score in results
        ]
    except Exception as exc:
        # 채팅은 검색이 안 돼도 답해야 하므로 빈 목록을 돌려준다 — 대신 원인을 남긴다(예전엔 아무 흔적이 없었다).
        _log().warning("RAG 검색 실패 (%s · %s): %s", coll, settings.QDRANT_URL, exc)
        return []


async def store_chunks(
    chunks:     list[str],
    metadata:   dict,
    collection: str | None = None,
) -> int:
    """
    텍스트 청크 목록을 OllamaEmbeddings로 임베딩하여 Qdrant에 저장한다.

    Returns:
        실제 저장된 청크 수

    Raises:
        VectorStoreError: Qdrant · 임베딩 모델에 닿지 못했거나 저장이 실패했다. 예전에는 0 을 돌려줘
            화면이 「업로드 완료 (0청크 저장)」 을 성공으로 보여 줬다(DF-38).
    """
    if not chunks:
        return 0

    coll = collection or settings.QDRANT_COLLECTION
    try:
        client, store = await _open_store(coll)
        docs = [Document(page_content=chunk, metadata=metadata) for chunk in chunks]
        await store.aadd_documents(docs)
        client.close()
        return len(docs)
    except Exception as exc:
        _log().warning("벡터 저장 실패 (%s · %s): %s", coll, settings.QDRANT_URL, exc)
        raise VectorStoreError(f"{type(exc).__name__}: {str(exc)[:200]}") from exc


def build_rag_chain(collection: str | None = None):
    """
    LCEL 기반 RAG 체인을 반환한다.

    사용 예:
        chain = build_rag_chain()
        answer = await chain.ainvoke({"question": "..."})
    """
    coll = collection or settings.QDRANT_COLLECTION

    # 동기 Qdrant 클라이언트 (LCEL retriever는 sync 인터페이스 사용)
    from qdrant_client import QdrantClient
    sync_client = QdrantClient(url=settings.QDRANT_URL)

    vector_store = CompatibleQdrantStore(
        client=sync_client,
        collection_name=coll,
        embedding=_make_embeddings(),
        content_payload_key="text",
    )
    retriever = vector_store.as_retriever(search_kwargs={"k": settings.TOP_K})

    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            "너는 금융 AI 어시스턴트다. 아래 참고 문서를 바탕으로 질문에 한국어로 답하라.\n\n"
            "[참고 문서]\n{context}",
        ),
        ("human", "{question}"),
    ])

    llm = ChatOllama(
        base_url=settings.OLLAMA_BASE_URL,
        model=settings.LLM_MODEL,
        temperature=0.2,
        **answer_options(),   # Qurious: 답 상한 · 문맥 창은 설정 한 곳(app/lib/llm_limits.py · 2026-10-08)
    )

    def format_docs(docs: list[Document]) -> str:
        return "\n\n".join(
            f"[{d.metadata.get('title', '문서')}]\n{d.page_content}" for d in docs
        )

    chain = (
        {"context": retriever | RunnableLambda(format_docs), "question": RunnablePassthrough()}
        | prompt
        | llm
        | StrOutputParser()
    )
    return chain


async def delete_chunks_by_source(source: str, collection: str | None = None) -> int:
    """
    특정 source 메타데이터를 가진 모든 벡터를 Qdrant에서 삭제한다.

    Returns:
        삭제 요청이 성공하면 1, 실패하면 0
    """
    coll = collection or settings.QDRANT_COLLECTION
    try:
        client = _make_client()
        # 키는 SOURCE_KEY("metadata.source") — 예전 "source" 는 아무것도 지우지 못하고 1(성공)을 돌려줬다(DF-38).
        await asyncio.to_thread(
            client.delete,
            collection_name=coll,
            points_selector=Filter(
                must=[FieldCondition(key=SOURCE_KEY, match=MatchValue(value=source))]
            ),
        )
        client.close()
        return 1
    except Exception as exc:
        _log().warning("벡터 삭제 실패 (%s · %s): %s", coll, source, exc)
        return 0
