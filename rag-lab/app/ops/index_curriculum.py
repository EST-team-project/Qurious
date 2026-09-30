"""Index UTF-8 learning documents into the Qdrant collection used by /api/rag."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.request
import urllib.error
import uuid
from pathlib import Path

DATA_DIR = Path("/app/data")
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333").rstrip("/")
COLLECTION = os.getenv("RAG_QDRANT_COLLECTION", "investment_docs")
CHUNK_SIZE, OVERLAP = 1200, 180


def request(method: str, path: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload else None
    req = urllib.request.Request(f"{QDRANT_URL}{path}", data=body, method=method,
        headers={"Content-Type": "application/json"} if body else {})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def embed(text: str, dim: int = 384) -> list[float]:
    vector = [0.0] * dim
    for token in re.findall(r"[0-9A-Za-z가-힣_]+", text.lower()):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        vector[int.from_bytes(digest[:4], "big") % dim] += 1.0 if digest[4] & 1 == 0 else -1.0
    norm = sum(value * value for value in vector) ** 0.5
    return [value / norm for value in vector] if norm else vector


def split(text: str) -> list[str]:
    clean = re.sub(r"\r\n?", "\n", text).strip()
    return [clean[i:i + CHUNK_SIZE] for i in range(0, len(clean), CHUNK_SIZE - OVERLAP) if clean[i:i + CHUNK_SIZE].strip()]


def document_title(text: str, fallback: str) -> str:
    match = re.search(r"^#\s+(.+)$", text, flags=re.MULTILINE)
    return match.group(1).strip() if match else fallback


def main() -> None:
    try:
        request("PUT", f"/collections/{COLLECTION}", {"vectors": {"size": 384, "distance": "Cosine"}})
    except urllib.error.HTTPError as error:
        if error.code != 409:
            raise
    files = sorted((DATA_DIR / "curriculum").glob("unit*.md"))
    if len(files) != 10:
        raise RuntimeError("Expected exactly 10 UTF-8 curriculum units")
    points = []
    for path in files:
        content = path.read_text(encoding="utf-8")
        source = path.relative_to(DATA_DIR).as_posix()
        for index, chunk in enumerate(split(content)):
            point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"investment-rag-lab/{source}:{index}"))
            points.append({"id": point_id, "vector": embed(chunk), "payload": {
                "source_doc": source, "section": document_title(content, path.stem),
                "chunk_index": index, "text": chunk, "indexed_at": int(time.time()),
            }})
    for start in range(0, len(points), 100):
        request("PUT", f"/collections/{COLLECTION}/points?wait=true", {"points": points[start:start + 100]})
    print(f"Indexed {len(files)} UTF-8 documents / {len(points)} chunks into {COLLECTION}.")
    # Domain RAG uses a different hashing algorithm and SQL hybrid search.
    # Never mix incompatible embeddings in the same Qdrant collection.
    from app.core.database import SessionLocal
    from app.services.rag_service import RAGService
    rag = RAGService()
    domain_chunks = 0
    with SessionLocal() as db:
        for path in files:
            content = path.read_text(encoding="utf-8")
            domain_chunks += rag.ingest_text(db, f"curriculum-{path.stem}", document_title(content, path.stem), content, "finance")
    print(f"Indexed {len(files)} units / {domain_chunks} chunks into domain RAG and PostgreSQL.")


if __name__ == "__main__":
    main()
