"""Qdrant 문지기 계약 시험 (TC-VD) — app/lib/vector_db.py 가 기대는 qdrant-client 동작을 진짜 라이브러리로 확인한다.

왜 있나 (DF-149 · 2026-10-23)
- 라이브러리는 부 판에서도 메서드를 없앤다(1.16.0 이 `search` 를 지움). 가짜 클라이언트로 도는 시험(TC-CR)은
  메서드가 없어져도 통과하므로, 「가짜가 진짜와 같은가」 를 진짜 메모리 Qdrant 로 따로 본다(Fowler 「ContractTest」).
- 이 파일은 잠금 판(requirements.lock)으로 만든 앱 이미지에서 돌고, 카나리아 줄(test.ps1 -Canary)은 같은 파일을
  지켜볼 패키지만 최신으로 올려 돌린다 — 다음 판에서 깨지는 것을 올리기 전에 안다.

무엇을 보나
1. 앱이 부르는 메서드(`vector_db.USED_METHODS`)가 동기 · 비동기 클라이언트에 다 있다 · `query_points` 가 우리가 넘기는 인자를 받는다.
2. 점 하나를 넣으면 검색 한 건 · 결과 세 칸(id · score · payload) · 거름 · 없는 모음은 False.
3. 빈 넣기는 부르지 않고 0(1.20 은 빈 upsert 를 ValueError 로 거절) · 빈 지우기도 부르지 않는다 · 모음 만들기는 한 번만.
4. 「닿지 못함」 은 VectorDBUnavailable(연결 실패 · 서버 오류) · 원격 404 는 CollectionMissing · 우리 코드 잘못은 그대로 올라간다.

돌리는 법 — 앱 이미지 일회용 컨테이너(test.ps1 의 컨테이너 묶음 ctr). 호스트에는 qdrant-client 가 없어 건너뛴다.
"""
from __future__ import annotations

import asyncio
import inspect

import pytest

qdrant_client = pytest.importorskip("qdrant_client")

from qdrant_client.http import exceptions as qe  # noqa: E402

from app.lib import vector_db  # noqa: E402

C = "vd_contract"


def _mem():
    return qdrant_client.AsyncQdrantClient(location=":memory:")


def test_used_methods_exist_on_both_clients():
    """TC-VD-01 · 앱이 부르는 메서드가 동기 · 비동기 클라이언트 모두에 있다 — 판이 메서드를 지우면 여기서 먼저 깨진다."""
    for cls in (qdrant_client.QdrantClient, qdrant_client.AsyncQdrantClient):
        missing = [m for m in vector_db.USED_METHODS if not hasattr(cls, m)]
        assert not missing, f"{cls.__name__} 에 없는 메서드: {missing}"
    params = inspect.signature(qdrant_client.AsyncQdrantClient.query_points).parameters
    assert {"collection_name", "query", "query_filter", "limit", "with_payload"} <= set(params)


def test_query_finds_point_with_three_fields():
    """TC-VD-02 · 점 하나 → 검색 한 건 · 결과는 id · score · payload 세 칸(라이브러리의 결과 꼴이 바뀌어도 부르는 쪽은 이것만)."""
    async def go():
        c = _mem()
        assert await vector_db.ensure_collection(c, C, 2) is True
        qm = vector_db.models()
        assert await vector_db.upsert(c, C, [qm.PointStruct(id=7, vector=[1.0, 0.0], payload={"text": "가"})]) == 1
        hits = await vector_db.query(c, C, [1.0, 0.0], limit=3)
        await vector_db.aclose(c)
        return hits

    (h,) = asyncio.run(go())
    assert isinstance(h, vector_db.Hit) and h.id == 7 and h.payload == {"text": "가"}
    assert h.score == pytest.approx(1.0)


def test_filter_and_exists():
    """TC-VD-03 · payload 거름은 맞는 점만 · 없는 모음은 exists 가 False(메모리 모드는 없는 모음 검색을 ValueError 로 낸다)."""
    async def go():
        c = _mem()
        await vector_db.ensure_collection(c, C, 2)
        qm = vector_db.models()
        await vector_db.upsert(c, C, [qm.PointStruct(id=1, vector=[1.0, 0.0], payload={"lang": "en"}),
                                      qm.PointStruct(id=2, vector=[0.9, 0.1], payload={"lang": "ja"})])
        flt = qm.Filter(must=[qm.FieldCondition(key="lang", match=qm.MatchValue(value="ja"))])
        hits = await vector_db.query(c, C, [1.0, 0.0], query_filter=flt, limit=5)
        gone = await vector_db.exists(c, "없는_모음")
        await vector_db.aclose(c)
        return hits, gone

    hits, gone = asyncio.run(go())
    assert [h.id for h in hits] == [2] and gone is False


class _Spy:
    """부른 메서드를 기록하는 껍데기 — 진짜 메모리 클라이언트에 그대로 넘긴다."""

    def __init__(self, inner):
        self.inner, self.calls = inner, []

    def __getattr__(self, name):
        target = getattr(self.inner, name)

        def _wrap(*a, **k):
            self.calls.append(name)
            return target(*a, **k)
        return _wrap


def test_empty_batches_are_not_sent_and_create_once():
    """TC-VD-04 · 빈 넣기 → 0 · 부르지 않음(1.20 은 빈 upsert 를 ValueError) · 빈 ID 지우기도 부르지 않음 · 모음 만들기는 처음 한 번만."""
    async def go():
        spy = _Spy(_mem())
        made = [await vector_db.ensure_collection(spy, C, 2), await vector_db.ensure_collection(spy, C, 2)]
        n = await vector_db.upsert(spy, C, [])
        await vector_db.delete(spy, C, vector_db.models().PointIdsList(points=[]))
        return made, n, spy.calls

    made, n, calls = asyncio.run(go())
    assert made == [True, False] and n == 0
    assert calls.count("create_collection") == 1 and "upsert" not in calls and "delete" not in calls


def test_dim_function_is_called_only_when_creating():
    """TC-VD-05 · 크기를 재는 함수(임베딩 한 번)는 모음을 새로 만들 때만 부른다 — 크롤 저장이 매번 임베딩을 더 하지 않게."""
    asked: list[int] = []

    async def dim():
        asked.append(1)
        return 2

    async def go():
        c = _mem()
        await vector_db.ensure_collection(c, C, dim)
        await vector_db.ensure_collection(c, C, dim)
        await vector_db.aclose(c)

    asyncio.run(go())
    assert asked == [1]


def test_unreachable_server_is_vector_db_unavailable():
    """TC-VD-06 · 닿지 못하면(아무도 듣지 않는 주소) ResponseHandlingException → VectorDBUnavailable(라우트 503)."""
    async def go():
        c = qdrant_client.AsyncQdrantClient(url="http://127.0.0.1:9", timeout=1, check_compatibility=False)
        try:
            await vector_db.exists(c, C)
        finally:
            await vector_db.aclose(c)

    with pytest.raises(vector_db.VectorDBUnavailable, match="ResponseHandlingException") as e:
        asyncio.run(go())
    assert isinstance(e.value.__cause__, qe.ApiException)


class _Raises:
    def __init__(self, exc):
        self.exc = exc

    async def query_points(self, **kw):
        raise self.exc


def test_remote_404_is_collection_missing_and_code_errors_pass():
    """TC-VD-07 · 원격 404(그 사이 모음이 지워짐)는 CollectionMissing · 다른 서버 오류는 VectorDBUnavailable ·
    우리 코드 잘못(AttributeError · TypeError)은 바꾸지 않고 그대로 올라간다(DF-149 의 뿌리를 다시 숨기지 않게)."""
    import httpx

    not_found = qe.UnexpectedResponse(404, "Not Found", b'{"status":{"error":"Not found"}}', httpx.Headers())
    server_err = qe.UnexpectedResponse(500, "Internal Server Error", b"{}", httpx.Headers())
    with pytest.raises(vector_db.CollectionMissing):
        asyncio.run(vector_db.query(_Raises(not_found), C, [1.0]))
    with pytest.raises(vector_db.VectorDBUnavailable, match="500"):
        asyncio.run(vector_db.query(_Raises(server_err), C, [1.0]))
    for exc in (AttributeError("x"), TypeError("y")):
        with pytest.raises(type(exc)):
            asyncio.run(vector_db.query(_Raises(exc), C, [1.0]))


def test_clients_are_made_in_one_place():
    """TC-VD-08 · 문지기가 만드는 클라이언트는 진짜 qdrant 클래스이고 주소는 설정 한 곳에서 온다(동기는 LangChain 용 · DF-38)."""
    sync_src = inspect.getsource(vector_db.sync_client)
    async_src = inspect.getsource(vector_db.async_client)
    assert "QdrantClient(url=settings.QDRANT_URL)" in sync_src and "Async" not in sync_src
    assert "AsyncQdrantClient(url=settings.QDRANT_URL)" in async_src
