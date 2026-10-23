"""Qdrant 문지기 — 앱이 Qdrant 를 부르는 길을 한 곳에 모은다 (DF-149 · 2026-10-23).

왜 따로 두나
- qdrant-client 는 부 판에서도 메서드를 없앤다. 1.16.0(2025-11-17)이 `search` 를 지웠고, 우리 이미지(1.19.1)에서
  번역 검색이 그 이름을 불러 AttributeError 가 났다. 넓은 `except Exception` 이 그것을 「0건」 으로 바꿔
  번역 검색은 한 번도 결과를 낸 적이 없다(DF-149 · 2026-10-23 재현).
- 그래서 ① 클라이언트를 만드는 곳 ② 검색 · 넣기 · 지우기 · 모음 만들기 ③ 「닿지 못함」 판정을 여기 한 곳에 둔다.
  라이브러리가 바뀌면 이 파일과 계약 시험(tests/test_vector_db.py · TC-VD)만 고친다.
- 잡는 예외는 qdrant 의 ApiException 뿐이다 — 연결 실패(ResponseHandlingException)와 서버 오류(UnexpectedResponse)가
  그 자식이다(1.19.1 실측). 우리 코드 잘못(AttributeError · TypeError)은 삼키지 않고 그대로 올린다(Ruff BLE001 의 생각).
- qdrant-client 는 함수 안에서 import 한다 — 호스트 시험 파이썬에는 이 패키지가 없고(크롤 시험은 가짜 모듈을 끼운다),
  앱 모듈을 import 만 하는 시험이 많다.

이 파일을 거치지 않는 곳
- rag_pipeline · user_docs — LangChain QdrantVectorStore 에 동기 클라이언트를 넘긴다(클라이언트는 여기 sync_client() 로 만든다).
- kb_search · collector/kb_* — Qdrant REST 를 직접 부른다(근거 DB · 서버 REST 판에 묶임).

지킴이: tests/test_deps_lock.py(호스트 · 클라이언트를 만드는 곳 · 없어진 API 이름) · 계약: tests/test_vector_db.py(앱 이미지 컨테이너).
판 짝(서버 ↔ 클라이언트 부 판 1 이내 · 서버 먼저)은 docs/phase-3/05-deployment/로컬실행안내서.md 「의존성 잠금 · 갱신」 절.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.config import settings

#: 앱이 qdrant 클라이언트에서 부르는 메서드 — 계약 시험(TC-VD)이 설치된 판(잠금 판 · 카나리아 최신 판)에 다 있는지 본다.
#: 새 메서드를 부르기 시작하면 여기에도 적는다(LangChain 이 안에서 부르는 것은 langchain-qdrant 판이 책임진다).
USED_METHODS: tuple[str, ...] = (
    "collection_exists", "create_collection", "create_payload_index", "count", "delete",
    "scroll", "upsert", "retrieve", "query_points", "close",
)


def _log():
    # 모듈을 읽을 때 만든 로거는 앱 시작 때 alembic 의 로그 설정이 꺼 버린다(rag_pipeline 과 같은 까닭) — 쓸 때 만든다.
    return logging.getLogger("qurious.vector_db")


class VectorDBUnavailable(RuntimeError):
    """Qdrant 에 닿지 못했거나 서버가 오류를 돌려줬다 — 라우트는 503 으로 알린다."""


class CollectionMissing(LookupError):
    """모음이 아직 없다(적재 전) — 장애와 갈라 라우트는 404 로 알린다."""

    def __init__(self, collection: str):
        super().__init__(f"모음 없음: {collection}")
        self.collection = collection


@dataclass(frozen=True)
class Hit:
    """검색 결과 한 건 — 라이브러리의 결과 꼴(ScoredPoint)이 바뀌어도 부르는 쪽은 이 세 칸만 본다."""

    id: Any
    score: float
    payload: dict


def models():
    """qdrant 모델 모듈(PointStruct · Filter · VectorParams …)."""
    from qdrant_client.http import models as qm
    return qm


def _api_exception():
    from qdrant_client.http.exceptions import ApiException
    return ApiException


def sync_client():
    """동기 클라이언트 — LangChain QdrantVectorStore 에 넘긴다(비동기를 넘기면 만들 때 죽는다 · DF-38)."""
    from qdrant_client import QdrantClient
    return QdrantClient(url=settings.QDRANT_URL)


def async_client():
    """비동기 클라이언트 — 번역 적재 · 검색 · 크롤 저장이 쓴다. 다 쓰면 `aclose()` 로 닫는다."""
    from qdrant_client import AsyncQdrantClient
    return AsyncQdrantClient(url=settings.QDRANT_URL)


async def _guard(awaitable: Awaitable, what: str):
    """qdrant 오류(ApiException)만 VectorDBUnavailable 로 바꾼다 — 그 밖은 그대로 올라간다."""
    api_error = _api_exception()
    try:
        return await awaitable
    except api_error as exc:
        status = getattr(exc, "status_code", None)
        raise VectorDBUnavailable(
            f"Qdrant {what} 실패 — {type(exc).__name__}{f' {status}' if status else ''}: {str(exc)[:200]}"
        ) from exc


async def exists(client, collection: str) -> bool:
    """모음이 있는가. 닿지 못하면 VectorDBUnavailable."""
    return bool(await _guard(client.collection_exists(collection), "모음 확인"))


async def ensure_collection(client, collection: str, dim: int | Callable[[], Awaitable[int]]) -> bool:
    """모음이 없으면 코사인 거리로 만든다 — 만들었으면 True.

    dim 은 정수 또는 「크기를 재는 비동기 함수」 — 모음이 이미 있으면 부르지 않는다(크롤 저장은 임베딩 한 번을 아낀다).
    다른 워커가 같은 때 먼저 만들었으면(만들기가 실패했는데 모음이 있음) 만든 것으로 치지 않고 False.
    """
    if await exists(client, collection):
        return False
    size = dim if isinstance(dim, int) else await dim()
    qm = models()
    try:
        await _guard(client.create_collection(
            collection, vectors_config=qm.VectorParams(size=size, distance=qm.Distance.COSINE),
        ), "모음 만들기")
    except VectorDBUnavailable:
        if await exists(client, collection):
            return False
        raise
    return True


async def query(client, collection: str, vector: list[float], *, query_filter=None, limit: int = 5) -> list[Hit]:
    """벡터로 가까운 점을 찾는다 — `query_points`(1.10 부터 · `search` 는 1.16 에서 없어짐).

    모음이 없으면 CollectionMissing(부르는 쪽이 먼저 `exists` 로 보는 것이 기본 — 메모리 모드는 없는 모음을 ValueError 로 낸다).
    원격에서 그 사이 모음이 지워져 404 가 오면 그것도 CollectionMissing 으로 바꾼다.
    """
    try:
        res = await _guard(client.query_points(
            collection_name=collection, query=vector, query_filter=query_filter, limit=limit, with_payload=True,
        ), "검색")
    except VectorDBUnavailable as exc:
        if getattr(exc.__cause__, "status_code", None) == 404:
            raise CollectionMissing(collection) from exc
        raise
    return [Hit(id=p.id, score=float(p.score), payload=dict(p.payload or {})) for p in res.points]


async def upsert(client, collection: str, points: list) -> int:
    """점을 넣는다 — 넣은 수. 빈 묶음은 부르지 않고 0(qdrant-client 1.20 은 빈 upsert 를 ValueError 로 거절 · #1512)."""
    if not points:
        return 0
    await _guard(client.upsert(collection_name=collection, points=points), "넣기")
    return len(points)


async def delete(client, collection: str, selector) -> None:
    """거름 · ID 목록으로 점을 지운다. 지울 것이 없으면(빈 ID 목록) 부르지 않는다."""
    if selector is None or getattr(selector, "points", None) == []:
        return
    await _guard(client.delete(collection_name=collection, points_selector=selector), "지우기")


def versions_compatible(server: str | None, client: str | None) -> bool | None:
    """판 짝 판정 — 주 판이 같고 부 판 차가 1 이하면 True(Qdrant 공식 「Upgrades」: SDK 는 클러스터와 부 판 1 이내).

    어느 하나라도 모르면(서버에 닿지 못함 · 패키지 없음 · 꼴이 틀림) None — 판정하지 못한 것이지 어긋난 것이 아니다.
    """
    def _mm(v: str) -> tuple[int, int]:
        parts = str(v).strip().lstrip("v").split(".")
        return int(parts[0]), int(parts[1])
    if not server or not client:
        return None
    try:
        (sm, sn), (cm, cn) = _mm(server), _mm(client)
    except (ValueError, IndexError):
        return None
    return sm == cm and abs(sn - cn) <= 1


async def version_pair(timeout: float = 2.0) -> dict:
    """서버 판(GET / 의 version) · 클라이언트 판(설치된 qdrant-client) · 판 짝 — 상태 API 의 Qdrant 줄 · check.ps1 이 쓴다.

    클라이언트 자체 판 검사는 경고(UserWarning)만 내고 시험은 그 경고를 꺼 두어, 어긋나도 아무도 보지 못했다(2026-10-23 조사).
    """
    import importlib.metadata as md

    import httpx

    try:
        client = md.version("qdrant-client")
    except md.PackageNotFoundError:
        client = None
    server = None
    try:
        async with httpx.AsyncClient(timeout=timeout) as cli:
            r = await cli.get(settings.QDRANT_URL.rstrip("/") + "/")
            server = (r.json() or {}).get("version")
    except (httpx.HTTPError, ValueError):
        server = None
    return {"server_version": server, "client_version": client, "version_ok": versions_compatible(server, client)}


async def aclose(client) -> None:
    """비동기 클라이언트를 닫는다 — 닫다 난 오류는 기록만 한다(앞에서 난 진짜 오류를 가리지 않게)."""
    try:
        await client.close()
    except Exception as exc:  # noqa: BLE001 — 닫기 실패는 결과를 바꾸지 않는다 · 기록은 남긴다
        _log().warning("Qdrant 클라이언트 닫기 실패: %s", exc)
