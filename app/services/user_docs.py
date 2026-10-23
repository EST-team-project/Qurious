"""올린 문서 조각의 문지기 — 사용자 비공개 모음은 이 모듈만 연다 (DF-146 · 2026-10-23).

왜 따로 두나
- 예전에는 올린 문서가 크롤링 조각과 같은 공용 모음(`fin_chunks`)에 들어갔고, 채팅 · 문서 검색 · 그래프 검색이
  올린 사람으로 거르지 않아 남의 문서가 근거로 보였다. 탈퇴해도 조각이 남아 계속 보였다(2026-10-23 재현).
- 이제 비공개 조각은 `USER_DOCS_COLLECTION` 한 곳에만 둔다. 공용 경로가 거름을 잊어도 볼 비공개 조각이 없다
  — 실패해도 「안 보임」 쪽으로 난다(Microsoft 다중 사용자 RAG 안내 · OWASP LLM08:2025).
- 이 모음으로 가는 읽기 · 쓰기 · 지우기는 모두 주인 ID 를 받고, 거름은 이 모듈이 만든다. 부르는 쪽이 거름을 빠뜨릴 수 없다.
- 모음 이름은 설정(`DOCUMENT_COLLECTION`)이 아니라 이 모듈의 상수다 — 강사님 기초 코드의 그 설정 값은 공용 모음과 같아,
  병합으로 되돌아와도 비공개 조각이 공용으로 가지 않게 한다(기초 코드 지킴이 TC-BM 이 지킨다).
- 주인 칸은 Qdrant 권고(한 모음 안에서 payload 로 가르기)대로 `metadata.owner_id` 에 `is_tenant` 키워드 색인을 건다.

조사 · 실측: docs/phase-3/01-analysis/research/배경조사/2026-10-23-올린문서-사용자격리/결과.md

옛 조각 옮기기(공용 모음에 남은 올린 조각 → 이 모음) — 앱 컨테이너에서:
  python -m app.services.user_docs migrate            # 미리 보기(수만 센다)
  python -m app.services.user_docs migrate --apply    # 옮기고 지운다
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Iterable

from langchain_core.documents import Document
from qdrant_client.http import models as qm

from app.config import settings
from app.services import rag_pipeline as rp
from app.services.rag_pipeline import OWNER_KEY, SOURCE_KEY, UPLOADER_KEY, VectorStoreError

USER_DOCS_COLLECTION = "user_docs"
DOC_KEY = "metadata.doc_id"   # 같은 이름 파일을 두 번 올려도 문서마다 따로 지운다(예전엔 출처 키가 같아 함께 지워졌다)
MAX_TOP_K = 20
_BATCH = 256
_DIM = 768   # nomic-embed-text — rag_pipeline._ensure_collection 과 같은 크기


def _log():
    return logging.getLogger("qurious.user_docs")


def owner_id_of(value) -> str:
    """주인 ID 를 UUID 글로 바꾼다 — 없거나 꼴이 틀리면 ValueError(검색 실패처럼 삼키지 않는다)."""
    if value is None or str(value).strip() == "":
        raise ValueError("주인 ID 가 없다 — 비공개 모음은 주인 없이 열지 않는다")
    return str(uuid.UUID(str(value)))


def _doc_id_of(value) -> str:
    return str(uuid.UUID(str(value)))


def _match(key: str, value: str) -> qm.FieldCondition:
    return qm.FieldCondition(key=key, match=qm.MatchValue(value=value))


def _empty(key: str) -> qm.IsEmptyCondition:
    return qm.IsEmptyCondition(is_empty=qm.PayloadField(key=key))


def owner_filter(owner_id, *, source: str | None = None) -> qm.Filter:
    """비공개 모음의 검색 거름 — 주인 조건은 늘 들어간다(출처를 주면 그 안에서만 좁힌다)."""
    must = [_match(OWNER_KEY, owner_id_of(owner_id))]
    if source:
        must.append(_match(SOURCE_KEY, source))
    return qm.Filter(must=must)


def _ensure_private_collection(client) -> None:
    """비공개 모음이 없으면 만든다 — 주인 칸에 is_tenant 색인 · 문서 ID 칸에 키워드 색인."""
    if client.collection_exists(USER_DOCS_COLLECTION):
        return
    try:
        client.create_collection(USER_DOCS_COLLECTION,
                                 vectors_config=qm.VectorParams(size=_DIM, distance=qm.Distance.COSINE))
    except Exception:
        if client.collection_exists(USER_DOCS_COLLECTION):   # 다른 워커가 먼저 만들었다
            return
        raise
    client.create_payload_index(USER_DOCS_COLLECTION, OWNER_KEY,
                                field_schema=qm.KeywordIndexParams(type=qm.KeywordIndexType.KEYWORD, is_tenant=True))
    client.create_payload_index(USER_DOCS_COLLECTION, DOC_KEY, field_schema=qm.PayloadSchemaType.KEYWORD)


async def _open_private():
    client = rp._make_client()
    await asyncio.to_thread(_ensure_private_collection, client)
    store = await asyncio.to_thread(rp.CompatibleQdrantStore, client=client,
                                    collection_name=USER_DOCS_COLLECTION, embedding=rp._make_embeddings())
    return client, store


# ── 저장 · 검색 ─────────────────────────────────────────────────────────────

async def store(owner_id, doc_id, chunks: list[str], meta: dict | None = None) -> int:
    """올린 문서의 조각을 비공개 모음에 넣는다. 올린 사람 이메일은 싣지 않는다(주인 UUID 만 · 조사 9절 ③).

    Raises:
        ValueError: 주인 ID · 문서 ID 가 없거나 틀렸다.
        VectorStoreError: Qdrant · 임베딩 모델에 닿지 못했다(부르는 쪽이 503 으로 알린다).
    """
    owner, doc = owner_id_of(owner_id), _doc_id_of(doc_id)
    if not chunks:
        return 0
    payload = {k: v for k, v in (meta or {}).items() if k not in ("uploader", "owner_id", "doc_id")}
    payload.update(owner_id=owner, doc_id=doc)
    try:
        client, st = await _open_private()
        try:
            await st.aadd_documents([Document(page_content=c, metadata=dict(payload)) for c in chunks])
        finally:
            client.close()
        return len(chunks)
    except Exception as exc:
        _log().warning("올린 문서 저장 실패 (%s · %s): %s", USER_DOCS_COLLECTION, settings.QDRANT_URL, exc)
        raise VectorStoreError(f"{type(exc).__name__}: {str(exc)[:200]}") from exc


def _hits(results) -> list[dict]:
    return [{
        "text": d.page_content,
        "url": d.metadata.get("url", ""),
        "title": d.metadata.get("title", ""),
        "source": d.metadata.get("source", ""),
        "doc_id": d.metadata.get("doc_id", ""),
        "score": float(score),
    } for d, score in results]


async def search(owner_id, query: str, top_k: int = 5, source: str | None = None) -> list[dict]:
    """내가 올린 문서에서만 찾는다. 주인 ID 가 틀리면 ValueError — 아래 try 가 삼키지 않게 거름을 먼저 만든다."""
    flt = owner_filter(owner_id, source=source)
    k = max(1, min(int(top_k or 5), MAX_TOP_K))
    try:
        client, st = await _open_private()
        try:
            results = await st.asimilarity_search_with_score(query, k=k, filter=flt)
        finally:
            client.close()
        return _hits(results)
    except Exception as exc:
        # 채팅은 검색이 안 돼도 답해야 하므로 빈 목록 — 원인은 남긴다(rag_search 와 같은 규칙).
        _log().warning("올린 문서 검색 실패 (%s · %s): %s", USER_DOCS_COLLECTION, settings.QDRANT_URL, exc)
        return []


async def search_with_shared(query: str, owner_id, top_k: int = 5) -> list[dict]:
    """채팅 근거 — 공용 크롤 조각 + 내가 올린 문서만, 점수 순으로 합친다.

    두 모음은 같은 임베딩 모델 · 같은 거리(코사인)라 점수를 견줄 수 있다. 남의 올린 문서는 어느 쪽에서도 나오지 않는다.
    """
    owner = owner_id_of(owner_id)
    k = max(1, min(int(top_k or 5), MAX_TOP_K))
    shared = await rp.rag_search(query, top_k=k)
    own = await search(owner, query, top_k=k)
    return sorted([*shared, *own], key=lambda h: h.get("score", 0.0), reverse=True)[:k]


# ── 지우기 ──────────────────────────────────────────────────────────────────

def _count(client, collection: str, flt: qm.Filter) -> int:
    return int(client.count(collection, count_filter=flt, exact=True).count)


def _legacy_filter(source_key: str) -> qm.Filter:
    """공용 모음에 남은 옛 올린 조각(올린 사람 이메일 칸이 있는 것) 가운데 그 출처의 것."""
    return qm.Filter(must=[_match(SOURCE_KEY, source_key)], must_not=[_empty(UPLOADER_KEY)])


def _is_own_key(owner: str, key: str) -> bool:
    """출처 키 `upload:<주인>:<파일>` 가 그 주인 것인가 — 남의 옛 조각을 지우지 않게 공용 쪽 지우기 앞에서 본다."""
    return bool(key) and key.startswith(f"upload:{owner}:")


def _purge(client, targets: list[tuple[str, qm.Filter]]) -> int:
    """(모음, 거름) 묶음을 지우고 앞뒤 수로 지운 수를 잰다 — Qdrant 의 지우기는 지운 수를 주지 않는다(실측 M10).

    지우고도 남으면 VectorStoreError — 파기 결과를 확인하라는 표준 개인정보 보호지침 제10조 ④ 를 코드로 지킨다.
    """
    total = 0
    for coll, flt in targets:
        if not client.collection_exists(coll):
            continue
        n = _count(client, coll, flt)
        if n:
            client.delete(coll, points_selector=qm.FilterSelector(filter=flt), wait=True)
            left = _count(client, coll, flt)
            if left:
                raise VectorStoreError(f"{coll} 에 지울 조각 {left}개가 남았다")
        total += n
    return total


async def _run_purge(targets: list[tuple[str, qm.Filter]]) -> int:
    try:
        client = rp._make_client()
        try:
            return await asyncio.to_thread(_purge, client, targets)
        finally:
            client.close()
    except VectorStoreError:
        raise
    except Exception as exc:
        _log().warning("올린 문서 조각 지우기 실패 (%s): %s", settings.QDRANT_URL, exc)
        raise VectorStoreError(f"{type(exc).__name__}: {str(exc)[:200]}") from exc


async def delete_doc(owner_id, doc_id, source_key: str = "") -> int:
    """문서 하나의 조각을 지운다 — 지운 수. 실패하면 VectorStoreError(부르는 쪽은 DB 행을 지우지 않는다).

    지우는 것: 비공개 모음의 그 문서 조각 · 문서 ID 없이 옮겨 온 그 출처의 옛 조각 · 공용 모음에 남은 그 출처의 옛 조각.
    """
    owner, doc = owner_id_of(owner_id), _doc_id_of(doc_id)
    which = [_match(DOC_KEY, doc)]
    if source_key:
        which.append(qm.Filter(must=[_match(SOURCE_KEY, source_key), _empty(DOC_KEY)]))
    targets = [(USER_DOCS_COLLECTION, qm.Filter(must=[_match(OWNER_KEY, owner)], should=which))]
    if _is_own_key(owner, source_key):
        targets.append((settings.QDRANT_COLLECTION, _legacy_filter(source_key)))
    return await _run_purge(targets)


async def delete_owner(owner_id, source_keys: Iterable[str] = ()) -> int:
    """한 사람이 올린 조각을 모두 지운다(탈퇴) — 지운 수. 실패하면 VectorStoreError(부르는 쪽은 탈퇴를 멈춘다)."""
    owner = owner_id_of(owner_id)
    targets = [(USER_DOCS_COLLECTION, qm.Filter(must=[_match(OWNER_KEY, owner)]))]
    for key in dict.fromkeys(k for k in source_keys if _is_own_key(owner, k)):
        targets.append((settings.QDRANT_COLLECTION, _legacy_filter(key)))
    return await _run_purge(targets)


# ── 옛 조각 옮기기 ───────────────────────────────────────────────────────────

def _owner_of_key(key: str) -> str | None:
    parts = key.split(":", 2)   # 파일 이름에 「:」 가 있어도 앞 둘만 자른다
    if len(parts) != 3 or parts[0] != "upload":
        return None
    try:
        return str(uuid.UUID(parts[1]))
    except ValueError:
        return None


def _migrate(client, live: dict[str, str | None], apply: bool) -> dict:
    shared = settings.QDRANT_COLLECTION
    report = {"found": 0, "move": 0, "drop": 0, "moved": 0, "dropped": 0, "apply": bool(apply)}
    if not client.collection_exists(shared):
        return report
    legacy = qm.Filter(must_not=[_empty(UPLOADER_KEY)])
    move: list[qm.PointStruct] = []
    drop: list = []
    offset = None
    while True:
        points, offset = client.scroll(shared, scroll_filter=legacy, limit=_BATCH, offset=offset,
                                       with_payload=True, with_vectors=True)
        for p in points:
            payload = p.payload or {}
            meta = dict(payload.get("metadata") or {})
            key = str(meta.get("source", ""))
            owner = _owner_of_key(key)
            if owner and key in live:
                meta.pop("uploader", None)
                meta["owner_id"] = owner
                if live[key]:
                    meta["doc_id"] = live[key]
                move.append(qm.PointStruct(id=p.id, vector=p.vector,
                                           payload={"page_content": payload.get("page_content", ""), "metadata": meta}))
            else:
                drop.append(p.id)
        if offset is None:
            break
    report.update(found=len(move) + len(drop), move=len(move), drop=len(drop))
    if not apply:
        return report
    if move:
        _ensure_private_collection(client)
        for i in range(0, len(move), _BATCH):   # 빈 묶음은 부르지 않는다(qdrant-client 1.20 은 빈 upsert 가 ValueError)
            client.upsert(USER_DOCS_COLLECTION, points=move[i:i + _BATCH], wait=True)
        ids = [p.id for p in move]
        got = len(client.retrieve(USER_DOCS_COLLECTION, ids=ids, with_payload=False, with_vectors=False))
        if got != len(ids):
            raise VectorStoreError(f"옮긴 조각 {got}/{len(ids)} — 공용 모음에서 지우지 않고 멈췄다")
        report["moved"] = got
    gone = [p.id for p in move] + drop
    for i in range(0, len(gone), _BATCH):
        client.delete(shared, points_selector=qm.PointIdsList(points=gone[i:i + _BATCH]), wait=True)
    report["dropped"] = len(drop)
    report["left"] = _count(client, shared, legacy)
    return report


async def migrate_legacy(live: dict[str, str | None], apply: bool = False) -> dict:
    """공용 모음의 옛 올린 조각을 비공개 모음으로 옮긴다 — 미리 보기가 기본(apply=False · 수만 센다).

    live = 지금 있는 올린 문서의 {출처 키: 문서 ID(같은 출처가 둘 이상이면 None)} — DB 를 읽는 쪽(아래 `_main`)이 넘긴다.
    - 주인(출처 키의 사용자 ID)이 있고 live 에 그 출처가 있으면, 같은 점 ID · 벡터로 복사하며 주인 칸을 더하고 공용에서 지운다.
    - live 에 없는 조각(탈퇴자 · DB 행 없음)은 옮기지 않고 지운다 — 파기 대상(개인정보 보호법 제21조 · 표준지침 제10조).
    - 올린 사람 이메일 칸은 옮기지 않는다. 다시 돌리면 찾는 것이 0 이다(실측 M17).
    """
    client = rp._make_client()
    try:
        return await asyncio.to_thread(_migrate, client, live, apply)
    finally:
        client.close()


async def _main(apply: bool) -> dict:
    from sqlalchemy import select

    from app.database.postgres import close_postgres, connect_postgres, get_session_factory
    from app.models import UploadedDoc

    await connect_postgres()
    try:
        async with get_session_factory()() as db:
            rows = (await db.execute(select(UploadedDoc.source_key, UploadedDoc.id))).all()
    finally:
        await close_postgres()
    live: dict[str, str | None] = {}
    for key, did in rows:
        live[key] = None if key in live else str(did)
    return await migrate_legacy(live, apply=apply)


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser(description="공용 모음의 옛 올린 조각을 비공개 모음으로 옮긴다(기본은 미리 보기)")
    ap.add_argument("command", choices=["migrate"])
    ap.add_argument("--apply", action="store_true", help="실제로 옮기고 지운다(빼면 수만 센다)")
    args = ap.parse_args()
    print(json.dumps(asyncio.run(_main(args.apply)), ensure_ascii=False))
