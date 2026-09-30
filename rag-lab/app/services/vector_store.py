"""
VectorStore — pgvector 기반 벡터 저장소 (ADR-0001)
──────────────────────────────────────────────────
Qdrant 의존을 제거하고, 이미 docker-compose에서 운영 중인 PostgreSQL(pgvector
확장) 한 곳에 메타데이터와 벡터를 함께 저장한다.

인터페이스(upsert_chunks, search)는 기존과 동일하게 유지하여
rag_service.py · hybrid_search.py · ingest_data_root.py 호출 코드에
변경이 없도록 한다.

search() 반환값은 Qdrant ScoredPoint 호환 네임드튜플을 사용한다.
"""

import time
import uuid
from collections import namedtuple

from sqlalchemy import text

from app.core.config import settings
from app.core.database import SessionLocal


# Qdrant ScoredPoint 호환 — hybrid_search.py가 r.payload / r.score 로 접근
ScoredPoint = namedtuple("ScoredPoint", ["payload", "score"])


_DDL = """
CREATE TABLE IF NOT EXISTS vector_chunks (
    id          TEXT PRIMARY KEY,
    chunk_id    TEXT NOT NULL,
    document_id TEXT NOT NULL,
    title       TEXT NOT NULL DEFAULT '',
    content     TEXT NOT NULL DEFAULT '',
    chunk_index INTEGER NOT NULL DEFAULT 0,
    domain      TEXT NOT NULL DEFAULT 'general',
    metadata    JSONB,
    embedding   vector({dim})
);
CREATE INDEX IF NOT EXISTS idx_vector_chunks_domain ON vector_chunks (domain);
CREATE INDEX IF NOT EXISTS idx_vector_chunks_chunk_id ON vector_chunks (chunk_id);
"""

_UPSERT = """
INSERT INTO vector_chunks (id, chunk_id, document_id, title, content, chunk_index, domain, metadata, embedding)
VALUES (:id, :chunk_id, :document_id, :title, :content, :chunk_index, :domain, :metadata, :embedding)
ON CONFLICT (id) DO UPDATE SET
    title     = EXCLUDED.title,
    content   = EXCLUDED.content,
    domain    = EXCLUDED.domain,
    metadata  = EXCLUDED.metadata,
    embedding = EXCLUDED.embedding;
"""

_SEARCH = """
SELECT chunk_id, document_id, title, content, chunk_index, domain, metadata,
       1 - (embedding <=> :query_vec) AS cosine_similarity
FROM   vector_chunks
{where}
ORDER BY embedding <=> :query_vec
LIMIT :top_k;
"""


class VectorStore:
    def __init__(self):
        self.vector_size = settings.embedding_dim
        self._ensure_table()

    def _ensure_table(self):
        """pgvector 확장 + vector_chunks 테이블이 존재하는지 확인/생성."""
        last_error = None
        for _ in range(15):
            try:
                with SessionLocal() as session:
                    session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                    session.execute(text(_DDL.format(dim=self.vector_size)))
                    session.commit()
                return
            except Exception as error:
                last_error = error
                time.sleep(2)
        raise RuntimeError(
            f"PostgreSQL(pgvector) 연결에 실패했습니다 "
            f"({settings.postgres_host}:{settings.postgres_port})."
        ) from last_error

    def upsert_chunks(self, chunks: list[dict], vectors: list[list[float]]):
        """청크 + 벡터를 vector_chunks 테이블에 upsert."""
        with SessionLocal() as session:
            for chunk, vector in zip(chunks, vectors):
                point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, chunk["chunk_id"]))
                import json
                session.execute(
                    text(_UPSERT),
                    {
                        "id": point_id,
                        "chunk_id": chunk["chunk_id"],
                        "document_id": chunk["document_id"],
                        "title": chunk["title"],
                        "content": chunk["content"],
                        "chunk_index": chunk["chunk_index"],
                        "domain": chunk.get("domain", "general"),
                        "metadata": json.dumps(chunk.get("metadata")) if chunk.get("metadata") else None,
                        "embedding": str(vector),
                    },
                )
            session.commit()

    def search(
        self,
        query_vector: list[float],
        top_k: int = 4,
        domain: str | None = None,
    ) -> list:
        """
        pgvector 코사인 유사도 검색.

        Returns
        -------
        list[ScoredPoint]  — 각 항목이 .payload (dict) 와 .score (float) 를 가짐.
        Qdrant 반환 형식과 호환되므로 hybrid_search.py 등의 호출 코드를 변경할 필요 없음.
        """
        where = ""
        params: dict = {
            "query_vec": str(query_vector),
            "top_k": top_k,
        }
        if domain and domain != "general":
            where = "WHERE domain = :domain"
            params["domain"] = domain

        sql = _SEARCH.format(where=where)

        with SessionLocal() as session:
            rows = session.execute(text(sql), params).fetchall()

        results = []
        for row in rows:
            payload = {
                "chunk_id": row.chunk_id,
                "document_id": row.document_id,
                "title": row.title,
                "content": row.content,
                "chunk_index": row.chunk_index,
                "domain": row.domain,
            }
            if row.metadata:
                payload["metadata"] = row.metadata
            results.append(ScoredPoint(payload=payload, score=float(row.cosine_similarity)))

        return results
