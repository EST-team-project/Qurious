"""번역 적재 · 검색 회귀 시험 (TC-TR) — app/services/translation_ingest.py (DF-149 · 2026-10-23).

무엇을 지키나
1. **넣은 번역 조각이 검색된다** — 예전엔 qdrant-client 1.16 에서 없어진 `search` 를 불러 AttributeError 가 났고,
   `except Exception: return []` 가 그것을 삼켜 번역 검색은 늘 0건이었다(DF-149 · 1.19.1 재현).
2. **「모음 없음」 · 「Qdrant 장애」 · 「임베딩 장애」 · 「0건」 이 갈린다** — 앞의 셋은 예외(라우트가 404 · 503 · 503),
   결과가 없을 때만 빈 목록이다. 모음이 없으면 임베딩 모델을 부르지 않는다.
3. **우리 코드 잘못은 삼키지 않는다** — 판이 바뀌어 메서드가 없어지면 「0건」 이 아니라 그 오류가 보인다. 클라이언트는 예외 길에서도 닫는다.
4. **적재 길** — zip 고르기(라벨링 · 원천 · 분류 · 언어) · 10문장 조각 · payload 칸 · 다시 적재해도 점 수가 같다(정해진 점 ID).
5. **고정 자료의 출처** — Tatoeba 문장은 모두 출처 표(tests/fixtures/translation/ATTRIBUTION.md)에 있다(CC BY 2.0 FR).

돌리는 법 — 앱 이미지 일회용 컨테이너(test.ps1 의 컨테이너 묶음 ctr)에서 qdrant-client **메모리 모드**와 글자로 만든
가짜 임베딩으로 돈다. 호스트 파이썬에는 qdrant-client 가 없어 이 파일은 통째로 건너뛴다. 고정 자료에 AI허브 문장은 없다.
"""
from __future__ import annotations

import asyncio
import json
import math
import re
import zipfile
from pathlib import Path

import httpx
import pytest

qdrant_client = pytest.importorskip("qdrant_client")

from app.lib import vector_db  # noqa: E402
from app.services import translation_ingest as ti  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "translation"
DIM = 768   # nomic-embed-text 크기 — 가짜 임베딩도 같은 크기(TC-VS 와 같은 셈법)
_REAL_ASYNC = qdrant_client.AsyncQdrantClient   # 아래 고정 장치가 바꿔 끼우기 전의 진짜 클래스


def _vec(text: str) -> list[float]:
    """글자를 768 칸에 흩어 센 단위 벡터 — 같은 글이면 같은 벡터 · 같은 글자를 많이 나누는 글끼리 가깝다(네트워크 없음)."""
    v = [0.0] * DIM
    for ch in text:
        v[ord(ch) % DIM] += 1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class _FakeEmbedder:
    """OllamaClient 자리 — fail 이 "down" 이면 연결 실패(httpx 오류) · "empty" 면 빈 답."""

    def __init__(self, fail: str | None = None):
        self.fail = fail
        self.calls = 0

    async def embed(self, model: str, text: str) -> list[float]:
        self.calls += 1
        if self.fail == "down":
            raise httpx.ConnectError("임베딩 서버에 닿지 않음")
        if self.fail == "empty":
            return []
        return _vec(text)


class _Mem:
    """메모리 Qdrant 하나를 한 시험 동안 나눠 쓴다 — 코드는 부를 때마다 만들고 닫으므로, 닫기는 세기만 한다(닫으면 저장소가 사라짐)."""

    def __init__(self):
        self.client = None
        self.made = 0
        self.closed = 0

    def __call__(self, *a, **k):
        if self.client is None:
            self.client = _REAL_ASYNC(location=":memory:")

            async def _close(*a, **k):
                self.closed += 1
            self.client.close = _close
        self.made += 1
        return self.client


@pytest.fixture
def mem(monkeypatch):
    m = _Mem()
    monkeypatch.setattr(vector_db, "async_client", m)
    # 깨 보기용 — 문지기 이전 코드(함수 안에서 AsyncQdrantClient(url=…) 를 직접 만듦)도 같은 메모리 Qdrant 를 쓰게 한다.
    # 그래야 옛 코드로 돌렸을 때 TR-01 이 「주소에 닿지 못함」 이 아니라 DF-149 그대로(없는 search → 삼킴 → 0건) 실패한다.
    monkeypatch.setattr(qdrant_client, "AsyncQdrantClient", m)
    return m


def _spec() -> dict:
    return json.loads((FIXTURE / "docs.json").read_text(encoding="utf-8"))


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """고정 자료로 data/1.데이터/ 와 같은 꼴의 폴더 · zip 을 임시 폴더에 만든다."""
    base = tmp_path / "1.데이터"
    for z in _spec()["zips"]:
        d = base / z["split"] / z["sub"]
        d.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(d / z["name"], "w") as zf:
            for m in z["members"]:
                zf.writestr(m["name"], m["raw"] if "raw" in m else json.dumps(m["doc"], ensure_ascii=False))
    monkeypatch.setattr(ti, "DATA_DIR", str(base))
    return base


PAYLOAD_KEYS = {"text", "translation", "doc_no", "domain", "category", "source_language",
                "target_language", "data_type", "chunk_index"}


# ── 1. 검색이 된다 ──────────────────────────────────────────────────────────
def test_inserted_point_is_found(mem):
    """TC-TR-01 · DF-149 — 넣은 조각이 검색된다(예전: 없는 `search` → AttributeError → except 가 삼켜 늘 0건)."""
    text = "그 가격에는 세금이 포함되어 있다."

    async def go():
        c = vector_db.async_client()
        await vector_db.ensure_collection(c, ti.TRANSLATION_COLLECTION, DIM)
        qm = vector_db.models()
        await vector_db.upsert(c, ti.TRANSLATION_COLLECTION, [qm.PointStruct(id=1, vector=_vec(text), payload={
            "text": text, "translation": "The price includes tax.", "doc_no": "TATOEBA-11105314",
            "category": "news", "target_language": "en", "domain": "tatoeba"})])
        return await ti.translation_search(text, _FakeEmbedder(), top_k=3)

    hits = asyncio.run(go())
    assert len(hits) == 1, "넣은 점이 검색되지 않았다 — DF-149 재발"
    h = hits[0]
    assert (h["text"], h["translation"], h["doc_no"]) == (text, "The price includes tax.", "TATOEBA-11105314")
    assert (h["category"], h["target_language"], h["domain"]) == ("news", "en", "tatoeba")
    assert h["score"] == pytest.approx(1.0, abs=1e-6)


# ── 4. 적재 길 ──────────────────────────────────────────────────────────────
def test_ingest_fixture_counts_and_is_idempotent(mem, data_dir):
    """TC-TR-02 · 합성 zip 적재(기본 = 라벨링만) — 문서 12 · 조각 12 · 점 12 · JSON 아닌 것은 건너뜀 · 읽은 zip 이름 기록 ·
    다시 적재해도 점 12(점 ID 가 zip 이름 · 문서 번호 · 조각 번호로 정해진 값)."""
    emb = _FakeEmbedder()

    async def go():
        r1 = await ti.run_translation_ingest(emb, [])
        r2 = await ti.run_translation_ingest(emb, [])
        c = vector_db.async_client()
        n = (await c.count(ti.TRANSLATION_COLLECTION, exact=True)).count
        pts, _ = await c.scroll(ti.TRANSLATION_COLLECTION, limit=100, with_payload=True)
        return r1, r2, n, pts

    r1, r2, n, pts = asyncio.run(go())
    assert (r1["total_docs"], r1["total_chunks"], r1["total_points"], r1["skipped_chunks"]) == (12, 12, 12, 0)
    assert r1["zips"] == ["TL_4. 뉴스기사_3. 일본어.zip", "TL_5. 공시정보_1. 영어.zip", "TL_4. 뉴스기사_1. 영어.zip"]
    assert r2 == r1 and n == 12, "다시 적재했는데 점이 늘었다 — 점 ID 가 정해진 값이 아니다"
    assert all(set(p.payload) == PAYLOAD_KEYS for p in pts)
    assert {p.payload["data_type"] for p in pts} == {"labeled"}
    disc = sorted((p.payload for p in pts if p.payload["doc_no"] == "SYN-DISC-001"), key=lambda x: x["chunk_index"])
    assert [d["chunk_index"] for d in disc] == [0, 1], "12문장 문서가 10 + 2 두 조각이 아니다"
    assert disc[0]["text"].startswith("당사는 2026년"), "손질한 원문(source_cleaned)을 쓰지 않았다"
    assert disc[1]["translation"].endswith("review by the external auditor."), "손질 번역이 없을 때 기계 번역(mt)으로 물러서지 않았다"
    assert {(p.payload["category"], p.payload["target_language"]) for p in pts} == {("news", "ja"), ("disclosure", "en"), ("news", "en")}


def test_ingest_filters_pick_zips(mem, data_dir):
    """TC-TR-03 · 고르기 — 원천만(번역 없음) · 일본어만 · 분류만 · 모두(원천 + 라벨링 = 문서 13)."""
    emb = _FakeEmbedder()

    async def go():
        src = await ti.run_translation_ingest(emb, [], data_type="source")
        ja = await ti.run_translation_ingest(emb, [], languages=["ja"])
        news = await ti.run_translation_ingest(emb, [], categories=["news"])
        both = await ti.run_translation_ingest(emb, [], data_type="all")
        pts, _ = await vector_db.async_client().scroll(ti.TRANSLATION_COLLECTION, limit=100, with_payload=True)
        return src, ja, news, both, pts

    src, ja, news, both, pts = asyncio.run(go())
    assert (src["total_docs"], src["zips"]) == (1, ["TS_5. 공시정보_1. 영어.zip"])
    assert (ja["total_docs"], ja["zips"]) == (1, ["TL_4. 뉴스기사_3. 일본어.zip"])
    assert (news["total_docs"], news["zips"]) == (9, ["TL_4. 뉴스기사_3. 일본어.zip", "TL_4. 뉴스기사_1. 영어.zip"])
    assert (both["total_docs"], both["total_chunks"]) == (13, 13)
    (source_pt,) = [p for p in pts if p.payload["doc_no"] == "SYN-SRC-001"]
    assert source_pt.payload["data_type"] == "source" and source_pt.payload["translation"] == ""


def test_search_filters_and_exact_sentence(mem, data_dir):
    """TC-TR-04 · 검색 거름 — 분류 · 언어로 좁힌다 · 같은 문장으로 찾으면 그 Tatoeba 문서가 맨 위(번역까지)."""
    emb = _FakeEmbedder()

    async def go():
        await ti.run_translation_ingest(emb, [])
        ja = await ti.translation_search("기준금리 동결", emb, category="news", target_language="ja")
        disc = await ti.translation_search("현금배당", emb, top_k=20, category="disclosure", target_language="en")
        exact = await ti.translation_search("기름 가격은 이번 주에 떨어졌다.", emb, top_k=1)
        return ja, disc, exact

    ja, disc, exact = asyncio.run(go())
    assert {h["doc_no"] for h in ja} == {"SYN-NEWS-JA-001"}
    assert ja[0]["translation"].startswith("韓国銀行")
    assert {h["doc_no"] for h in disc} == {"SYN-DISC-001", "SYN-DISC-002"}
    assert len(exact) == 1 and exact[0]["doc_no"] == "TATOEBA-5526782"
    assert exact[0]["translation"] == "The price of oil is down this week."


# ── 2 · 3. 실패를 가른다 · 삼키지 않는다 ───────────────────────────────────────
def test_missing_collection_is_not_zero_hits(mem):
    """TC-TR-05 · 모음이 없으면 빈 목록이 아니라 CollectionMissing(라우트 404) — 임베딩 모델은 부르지 않고 클라이언트는 닫는다."""
    emb = _FakeEmbedder()
    with pytest.raises(vector_db.CollectionMissing):
        asyncio.run(ti.translation_search("배당", emb))
    assert emb.calls == 0 and mem.made == mem.closed == 1


def test_qdrant_down_is_raised(monkeypatch):
    """TC-TR-06 · Qdrant 에 닿지 못하면 VectorDBUnavailable(라우트 503) — 예전엔 빈 목록이라 「0건」 과 같아 보였다."""
    closed: list[int] = []

    def _unreachable():
        c = qdrant_client.AsyncQdrantClient(url="http://127.0.0.1:9", timeout=1, check_compatibility=False)
        real = c.close

        async def _close(*a, **k):
            closed.append(1)
            await real()
        c.close = _close
        return c

    monkeypatch.setattr(vector_db, "async_client", _unreachable)
    with pytest.raises(vector_db.VectorDBUnavailable, match="ResponseHandlingException"):
        asyncio.run(ti.translation_search("배당", _FakeEmbedder()))
    assert closed == [1], "예외 길에서 클라이언트를 닫지 않았다"


def test_code_error_is_not_swallowed(monkeypatch):
    """TC-TR-07 · DF-149 의 뿌리 — 판이 바뀌어 메서드가 없어지면 「0건」 이 아니라 그 오류(AttributeError)가 그대로 보인다."""
    class _NoQueryPoints:   # query_points 가 없어진 판을 흉내(1.16 에서 search 가 없어진 것처럼)
        closed = 0

        async def collection_exists(self, name):
            return True

        async def close(self):
            _NoQueryPoints.closed += 1

    monkeypatch.setattr(vector_db, "async_client", _NoQueryPoints)
    with pytest.raises(AttributeError, match="query_points"):
        asyncio.run(ti.translation_search("배당", _FakeEmbedder()))
    assert _NoQueryPoints.closed == 1


def test_embedding_down_or_empty_is_raised(mem, data_dir):
    """TC-TR-08 · 임베딩 장애 — 적재 · 검색 모두 EmbeddingUnavailable(라우트 503) · 예전 적재는 200 + error 칸, 검색은 빈 목록이었다."""
    async def make_collection():
        c = vector_db.async_client()
        await vector_db.ensure_collection(c, ti.TRANSLATION_COLLECTION, DIM)
        await vector_db.aclose(c)
    asyncio.run(make_collection())
    for fail in ("down", "empty"):
        with pytest.raises(ti.EmbeddingUnavailable):
            asyncio.run(ti.run_translation_ingest(_FakeEmbedder(fail), []))
        with pytest.raises(ti.EmbeddingUnavailable):
            asyncio.run(ti.translation_search("배당", _FakeEmbedder(fail)))
    assert mem.closed == mem.made, "예외 길에서 클라이언트를 닫지 않았다"


def test_missing_data_dir_is_raised(mem, monkeypatch, tmp_path):
    """TC-TR-09 · 원자료 폴더가 없으면 TranslationDataMissing(라우트 404 · 받는 법 안내) — 예전엔 「0문서 · 성공」. Qdrant 는 열지 않는다."""
    monkeypatch.setattr(ti, "DATA_DIR", str(tmp_path / "없음"))
    with pytest.raises(ti.TranslationDataMissing):
        asyncio.run(ti.run_translation_ingest(_FakeEmbedder(), []))
    assert mem.made == 0


def test_top_k_is_capped(mem, data_dir, monkeypatch):
    """TC-TR-10 · 한 번에 돌려주는 수는 20 까지 · 0 이면 기본 5 · 음수면 1(원문을 한꺼번에 빼 가지 못하게 · user_docs 와 같은 상한)."""
    emb = _FakeEmbedder()
    asked: list[int] = []

    async def go():
        await ti.run_translation_ingest(emb, [])
        c = vector_db.async_client()
        real = c.query_points

        async def spy(*a, **kw):
            asked.append(kw["limit"])
            return await real(*a, **kw)
        c.query_points = spy
        for k in (1000, 0, -3):
            await ti.translation_search("가격", emb, top_k=k)

    asyncio.run(go())
    assert asked == [ti.MAX_TOP_K, 5, 1] and ti.MAX_TOP_K == 20


# ── 5. 고정 자료의 출처 ──────────────────────────────────────────────────────
def test_fixture_attribution_is_complete():
    """TC-TR-11 · 고정 자료 문서는 합성(SYN-*) · Tatoeba(TATOEBA-*) 둘뿐이고, Tatoeba 문서는 모두 출처 표에 두 문장 번호 · 저작자 ·
    사용 허가(CC BY 2.0 FR)와 함께 있다 — 문장마다 저작자 표시가 사용 조건이다."""
    table = (FIXTURE / "ATTRIBUTION.md").read_text(encoding="utf-8")
    docs = [m["doc"] for z in _spec()["zips"] for m in z["members"] if "doc" in m]
    assert docs and all(re.match(r"^(SYN|TATOEBA)-", d["meta"]["doc_no"]) for d in docs)
    tatoeba = [d for d in docs if d["meta"]["doc_no"].startswith("TATOEBA-")]
    assert len(tatoeba) == 8
    for d in tatoeba:
        ids = d["meta"]["tatoeba"]
        row = next((line for line in table.splitlines() if line.startswith(f"| {d['meta']['doc_no']} |")), "")
        assert f"#{ids['ko_id']}" in row and f"#{ids['en_id']}" in row and row.rstrip().endswith("| CC BY 2.0 FR |"), d["meta"]["doc_no"]
        (sent,) = d["sents"]
        assert sent["source_original"] in row and sent["mtpe"] in row, "출처 표의 문장과 고정 자료의 문장이 다르다"
