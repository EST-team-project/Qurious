"""올린 문서 사용자 격리 시험 (TC-DI) — 비공개 모음 문지기 app/services/user_docs.py · 공용 검색 rag_pipeline.rag_search.

무엇을 지키나 (DF-146 · 2026-10-23)
1. **남의 올린 문서는 어디서도 안 보인다** — 문서 검색 · 남의 출처 키 지정 · 채팅 근거 모두 0건. 예전에는 올린 문서가
   크롤링 조각과 같은 공용 모음에 들어가 다른 사용자의 채팅 · 검색에 그대로 나왔다(일회용 계정 둘로 재현).
2. **주인 없이는 비공개 모음을 열 수 없다** — 주인 ID 가 없거나 틀리면 ValueError(검색 실패처럼 빈 목록으로 삼키지 않는다).
   비공개 모음으로 가는 찾기 · 세기 · 지우기 호출에는 늘 주인 조건이 붙는다(호출을 엿봐서 잰다).
3. **공용 검색은 올린 꼴 조각을 읽지 않고, 크롤 조각의 본문은 읽는다** — 옛 올린 조각 · 병합으로 다시 들어온 조각을 빼고,
   크롤 꼴(payload 맨 위 text)의 본문 · 제목이 빈 글로 나오던 것(실측 M18)도 함께 고쳤다.
4. **지우기는 그 문서 · 그 사람 것만, 지운 수를 재고, 실패를 숨기지 않는다** — 같은 이름 파일 둘 중 하나만 지운다 ·
   지운 뒤 남으면 · 벡터 DB 가 꺼져 있으면 VectorStoreError(부르는 쪽이 503 으로 멈춘다 — 탈퇴 · 문서 지우기).
5. **옛 조각 옮기기** — 미리 보기 수 = 실제 수 · 살아 있는 사람 것은 비공개 모음으로 · 탈퇴자 것은 지움 · 다시 돌리면 0.

돌리는 법 — Qdrant 서버 없이 qdrant-client 메모리 모드와 글자로 만든 가짜 임베딩으로 돈다. 호스트 파이썬에 langchain-qdrant ·
langchain-ollama 가 없으면 이 파일은 건너뛴다 → 앱 이미지로 일회용 컨테이너를 띄워 돌린다(테스트 계획서 TC-DI 줄).
"""
from __future__ import annotations

import asyncio
import math
import uuid

import pytest

pytest.importorskip("langchain_qdrant")
pytest.importorskip("langchain_ollama")
qdrant_client = pytest.importorskip("qdrant_client")

from langchain_core.embeddings import Embeddings  # noqa: E402
from qdrant_client.http import models as qm  # noqa: E402

from app.config import settings  # noqa: E402
from app.services import rag_pipeline as rp  # noqa: E402
from app.services import user_docs as ud  # noqa: E402

DIM = 768
A = "00000000-0000-0000-0000-00000000000a"
B = "00000000-0000-0000-0000-00000000000b"
C = "00000000-0000-0000-0000-00000000000c"
GAP = "괴리율은 ETF 가 거래소에서 거래되는 가격과 순자산가치(NAV)의 차이를 비율로 나타낸 값이다."
MEMO = "가짜 비공개 메모 — A 만 보아야 하는 괴리율 계산 노트."
CRAWL = "ETF 괴리율 공시는 거래소 누리집에서 매일 볼 수 있다."


class _CharEmbeddings(Embeddings):
    """글자를 768 칸에 흩어 세는 가짜 임베딩(test_rag_pipeline 과 같은 꼴 · 네트워크 없음)."""

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
def mq(monkeypatch):
    """한 시험 안에서 같은 메모리 Qdrant 를 쓰게 한다(코드는 부를 때마다 클라이언트를 만들고 닫는다)."""
    client = qdrant_client.QdrantClient(location=":memory:")
    client.close = lambda *a, **k: None
    monkeypatch.setattr(rp, "_make_client", lambda: client)
    monkeypatch.setattr(rp, "_make_embeddings", lambda: _CharEmbeddings())
    return client


def _run(coro):
    return asyncio.run(coro)


def _key(owner: str, name: str) -> str:
    return f"upload:{owner}:{name}"


def _put(owner: str, name: str, text: str, doc: str | None = None) -> str:
    doc = doc or str(uuid.uuid4())
    meta = {"url": f"upload://{name}", "title": name, "source": _key(owner, name), "uploader": f"{owner[-1]}@example.com"}
    assert _run(ud.store(owner, doc, [text], meta)) == 1
    return doc


def _shared(client, *points: dict) -> None:
    """공용 모음(크롤 꼴 · 옛 올린 꼴)을 직접 채운다 — 크롤은 payload 맨 위 text, 옛 올린 꼴은 page_content + metadata."""
    coll = settings.QDRANT_COLLECTION
    if not client.collection_exists(coll):
        client.create_collection(coll, vectors_config=qm.VectorParams(size=DIM, distance=qm.Distance.COSINE))
    emb = _CharEmbeddings()
    client.upsert(coll, points=[
        qm.PointStruct(id=str(uuid.uuid4()), vector=emb.embed_query(p.get("text") or p.get("page_content", "")), payload=p)
        for p in points
    ], wait=True)


def _crawl(text: str = CRAWL) -> dict:
    return {"url": "https://example.com/etf", "title": "ETF 공시 안내", "source": "web", "text": text, "chunk_index": 0}


def _legacy(owner: str, name: str, text: str) -> dict:
    return {"page_content": text, "metadata": {"url": f"upload://{name}", "title": name, "source": _key(owner, name),
                                              "uploader": f"{owner[-1]}@example.com"}}


def test_other_user_never_sees_my_upload(mq):
    """TC-DI-01 · B 의 문서 검색에 A 가 올린 조각이 없다 — A 자신은 본문 · 출처 · 문서 ID 까지 그대로 본다."""
    doc = _put(A, "memo.txt", MEMO)
    assert _run(ud.search(B, "괴리율 메모", top_k=5)) == []
    mine = _run(ud.search(A, "괴리율 메모", top_k=5))
    assert [h["text"] for h in mine] == [MEMO]
    assert mine[0]["source"] == _key(A, "memo.txt") and mine[0]["doc_id"] == doc


def test_other_users_source_key_returns_nothing(mq):
    """TC-DI-02 · 남의 출처 키를 콕 집어도 0건 — 출처 거름은 늘 「내 문서 안에서」 만 좁힌다."""
    _put(A, "memo.txt", MEMO)
    assert _run(ud.search(B, "메모", top_k=5, source=_key(A, "memo.txt"))) == []
    assert len(_run(ud.search(A, "메모", top_k=5, source=_key(A, "memo.txt")))) == 1


def test_chat_evidence_is_shared_plus_mine(mq):
    """TC-DI-03 · 채팅 근거 = 공용 크롤 조각 + 내 문서 — B 는 크롤만, A 는 둘 다 · 크롤 본문 · 제목이 빈 글이 아니다(M18)."""
    _shared(mq, _crawl())
    _put(A, "memo.txt", MEMO)
    b = _run(ud.search_with_shared("ETF 괴리율", B, top_k=5))
    assert [h["text"] for h in b] == [CRAWL], "B 의 채팅 근거에 A 문서가 섞였거나 크롤 본문이 비었다"
    assert b[0]["title"] == "ETF 공시 안내" and b[0]["url"] == "https://example.com/etf"
    a = _run(ud.search_with_shared("ETF 괴리율", A, top_k=5))
    assert sorted(h["text"] for h in a) == sorted([CRAWL, MEMO])
    assert [h["score"] for h in a] == sorted((h["score"] for h in a), reverse=True), "점수 순이 아니다"


@pytest.mark.parametrize("bad", [None, "", "  ", "u1", "not-a-uuid"])
def test_owner_is_required_and_not_swallowed(mq, bad):
    """TC-DI-04 · 주인 ID 가 없거나 틀리면 ValueError — 찾기 · 채팅 · 넣기 · 지우기 모두(빈 목록으로 삼키지 않는다)."""
    doc = str(uuid.uuid4())
    for call in (lambda: ud.search(bad, "x"), lambda: ud.search_with_shared("x", bad),
                 lambda: ud.store(bad, doc, ["x"], {}), lambda: ud.delete_doc(bad, doc),
                 lambda: ud.delete_owner(bad)):
        with pytest.raises(ValueError):
            _run(call())


def _has_owner(flt) -> bool:
    return any(isinstance(c, qm.FieldCondition) and c.key == ud.OWNER_KEY for c in (getattr(flt, "must", None) or []))


def test_every_private_call_carries_owner_condition(mq):
    """TC-DI-05 · 비공개 모음으로 가는 찾기 · 세기 · 지우기 호출에 늘 주인 조건이 붙는다(호출을 엿봐서 잰다 · M19)."""
    seen: list[tuple[str, bool]] = []

    def spy(name, fn, pick):
        def wrapper(*a, **k):
            coll = k.get("collection_name") or (a[0] if a else "")
            if coll == ud.USER_DOCS_COLLECTION:
                seen.append((name, _has_owner(pick(a, k))))
            return fn(*a, **k)
        return wrapper

    mq.query_points = spy("query_points", mq.query_points, lambda a, k: k.get("query_filter"))
    mq.count = spy("count", mq.count, lambda a, k: k.get("count_filter"))
    mq.delete = spy("delete", mq.delete, lambda a, k: getattr(k.get("points_selector"), "filter", None))
    doc = _put(A, "memo.txt", MEMO)
    _run(ud.search(A, "메모"))
    _run(ud.search_with_shared("메모", A))
    _run(ud.delete_doc(A, doc, _key(A, "memo.txt")))
    _put(A, "memo2.txt", MEMO)
    _run(ud.delete_owner(A, [_key(A, "memo2.txt")]))
    kinds = {n for n, _ in seen}
    assert {"query_points", "count", "delete"} <= kinds, f"엿본 호출이 모자라다: {kinds}"
    assert all(ok for _, ok in seen), f"주인 조건 없는 비공개 모음 호출: {[n for n, ok in seen if not ok]}"


def test_shared_search_skips_upload_shaped_points(mq):
    """TC-DI-06 · 공용 검색은 올린 꼴 조각(옛 올린 사람 이메일 · 주인 칸)을 읽지 않는다 — 크롤 조각만."""
    _shared(mq, _crawl(), _legacy(A, "old.txt", GAP),
            {"page_content": MEMO, "metadata": {"source": _key(B, "x.txt"), "owner_id": B}})
    hits = _run(rp.rag_search("ETF 괴리율 메모", top_k=10))
    assert [h["text"] for h in hits] == [CRAWL]


def test_rag_search_refuses_private_collection(mq):
    """TC-DI-07 · 공용 검색 함수로 비공개 모음을 열면 ValueError — 문지기를 거치지 않는 길을 막는다."""
    with pytest.raises(ValueError):
        _run(rp.rag_search("x", collection=ud.USER_DOCS_COLLECTION))


def test_delete_doc_removes_only_that_doc_and_counts(mq):
    """TC-DI-08 · 같은 이름 파일 둘 중 하나만 지운다 · 지운 수를 돌려준다 · 공용에 남은 그 출처의 옛 조각도 지운다."""
    one = _put(A, "same.txt", MEMO)
    two = _put(A, "same.txt", GAP)
    _shared(mq, _legacy(A, "same.txt", "옛 조각"), _crawl())
    assert _run(ud.delete_doc(A, one, _key(A, "same.txt"))) == 2   # 비공개 1 + 공용 옛 조각 1
    left = _run(ud.search(A, "괴리율", top_k=5, source=_key(A, "same.txt")))
    assert [h["doc_id"] for h in left] == [two]
    assert [h["text"] for h in _run(rp.rag_search("ETF 괴리율 옛 조각", top_k=10))] == [CRAWL]
    assert mq.count(settings.QDRANT_COLLECTION, exact=True).count == 1, "공용의 옛 올린 조각이 남았다"


def test_delete_owner_removes_everything_of_that_owner_only(mq):
    """TC-DI-09 · 탈퇴 지우기는 그 사람 것만 — B 의 문서 · 공용 옛 조각은 남고, 남의 출처 키를 섞어 넘겨도 지우지 않는다."""
    _put(A, "a1.txt", MEMO)
    _put(A, "a2.txt", GAP)
    _put(B, "b1.txt", GAP)
    _shared(mq, _legacy(A, "a1.txt", "A 옛 조각"), _legacy(B, "b1.txt", "B 옛 조각"))
    n = _run(ud.delete_owner(A, [_key(A, "a1.txt"), _key(B, "b1.txt")]))
    assert n == 3   # 비공개 2 + A 의 공용 옛 조각 1
    assert _run(ud.search(A, "괴리율 메모", top_k=5)) == []
    assert len(_run(ud.search(B, "괴리율", top_k=5))) == 1
    legacy = qm.Filter(must_not=[qm.IsEmptyCondition(is_empty=qm.PayloadField(key=rp.UPLOADER_KEY))])
    assert mq.count(settings.QDRANT_COLLECTION, count_filter=legacy, exact=True).count == 1, "B 의 옛 조각까지 지웠다"


class _DownClient:
    """꺼진 벡터 DB 처럼 — 모음 확인은 되지만 세기 · 지우기에서 예외(실측 M20 의 ResponseHandlingException 자리)."""

    def collection_exists(self, name):
        return True

    def count(self, *a, **k):
        raise ConnectionError("Qdrant 에 닿지 못함")

    delete = count

    def close(self, *a, **k):
        pass


def test_delete_failure_raises_vector_store_error(monkeypatch):
    """TC-DI-10 · 벡터 DB 가 꺼지면 VectorStoreError — 부르는 쪽(탈퇴 · 문서 지우기)이 503 으로 멈추게 숨기지 않는다."""
    monkeypatch.setattr(rp, "_make_client", lambda: _DownClient())
    with pytest.raises(rp.VectorStoreError):
        _run(ud.delete_doc(A, str(uuid.uuid4()), _key(A, "x.txt")))
    with pytest.raises(rp.VectorStoreError):
        _run(ud.delete_owner(A, [_key(A, "x.txt")]))


def test_private_collection_asks_for_tenant_index(mq):
    """TC-DI-11 · 비공개 모음을 만들 때 주인 칸에 is_tenant 키워드 색인을 요청한다(메모리 모드는 색인을 무시하므로 요청까지 · M8)."""
    asked: list = []
    real = mq.create_payload_index

    def spy(collection_name, field_name, field_schema=None, **k):
        asked.append((collection_name, field_name, field_schema))
        return real(collection_name, field_name, field_schema=field_schema, **k)

    mq.create_payload_index = spy
    _put(A, "memo.txt", MEMO)
    owner = [s for c, f, s in asked if c == ud.USER_DOCS_COLLECTION and f == ud.OWNER_KEY]
    assert owner and getattr(owner[0], "is_tenant", False) is True


def test_migrate_moves_live_and_drops_orphans(mq):
    """TC-DI-12 · 옛 조각 옮기기 — 미리 보기 = 실제 · 산 사람 것은 비공개로(이메일 칸 없이) · 탈퇴자 것은 지움 · 다시 돌리면 0."""
    _shared(mq, _crawl(), _legacy(A, "a:b.txt", MEMO), _legacy(C, "c.txt", GAP))
    live = {_key(A, "a:b.txt"): str(uuid.uuid4())}   # C 는 탈퇴해 DB 행이 없다 · 파일 이름에 「:」 가 있어도 주인을 찾는다
    preview = _run(ud.migrate_legacy(live))
    assert (preview["found"], preview["move"], preview["drop"], preview["apply"]) == (2, 1, 1, False)
    assert mq.count(settings.QDRANT_COLLECTION, exact=True).count == 3, "미리 보기가 무언가를 바꿨다"
    done = _run(ud.migrate_legacy(live, apply=True))
    assert (done["moved"], done["dropped"], done["left"]) == (1, 1, 0)
    mine = _run(ud.search(A, "괴리율 메모", top_k=5))
    assert [h["text"] for h in mine] == [MEMO] and mine[0]["doc_id"] == live[_key(A, "a:b.txt")]
    pts, _ = mq.scroll(ud.USER_DOCS_COLLECTION, limit=10, with_payload=True)
    assert all("uploader" not in (p.payload.get("metadata") or {}) for p in pts), "옮긴 조각에 올린 사람 이메일이 남았다"
    assert [h["text"] for h in _run(rp.rag_search("ETF 괴리율", top_k=10))] == [CRAWL]
    again = _run(ud.migrate_legacy(live, apply=True))
    assert again["found"] == 0 and again["moved"] == 0
