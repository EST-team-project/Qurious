"""크롤 조각 점 ID 시험 (TC-CR) — 같은 글을 다시 모아도 벡터 DB 에 같은 조각이 쌓이지 않는다.

무엇을 지키나 (2026-10-04 · 기능 완성도 점검에서 이동원 몫으로 고침)
1. **점 ID 가 프로세스마다 같다** — 예전 `abs(hash(...))` 는 PYTHONHASHSEED 에 따라 값이 달라, 앱을 다시 켜고
   같은 글을 모으면 같은 조각이 새 점으로 하나 더 쌓였다(옛 분석 A11 · 2026-09-17 실측). 이제 sha256(주소 · 조각 번호).
2. **다시 모으면 옛 점을 정리한다** — 같은 주소에서 이번에 쓰지 않은 점(글이 짧아진 꼬리 · 예전 hash() ID 중복)을 지운다.
3. **실패하면 지우지 않는다** — 임베딩이 하나도 안 되면(Ollama 꺼짐) 올리지도 지우지도 않는다(옛 근거라도 남긴다).

돌리는 법 — Qdrant 서버도 qdrant-client 도 없이 돈다. `_store_qdrant` 가 함수 안에서 `qdrant_client` 를 import 하므로
가짜 모듈을 sys.modules 에 끼워 넣어 부른 값(올린 점 · 지운 거름)을 기록한다.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

from app.services import crawl
from app.services.crawl_points import crawl_point_id

ROOT = Path(__file__).resolve().parents[1]
URL = "https://example.com/docs/guide"


# ── 1. 점 ID ──────────────────────────────────────────────────────────────
def _ids_in_child(seed: str, code: str) -> str:
    """다른 PYTHONHASHSEED 로 새 파이썬을 띄워 code 의 출력을 받는다(내장 hash() 가 프로세스마다 다른 것을 재현)."""
    env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(ROOT)}
    out = subprocess.run([sys.executable, "-c", code], env=env, cwd=str(ROOT),
                         capture_output=True, text=True, timeout=60, check=True)
    return out.stdout.strip()


def test_point_id_same_in_every_process():
    """TC-CR-01 · 새 ID 는 PYTHONHASHSEED 0 · 1 · 2 에서 같고, 옛 방식은 셋이 다르다(고친 이유)."""
    new = {_ids_in_child(s, "from app.services.crawl_points import crawl_point_id as f; "
                            f"print(f({URL!r}, 3))") for s in ("0", "1", "2")}
    old = {_ids_in_child(s, f"print(abs(hash('{URL}-3')) % (2 ** 63))") for s in ("0", "1", "2")}
    assert len(new) == 1
    assert len(old) == 3, "옛 방식이 우연히 같은 값을 냈다 — 시험의 전제(내장 hash 가 프로세스마다 다름)를 다시 볼 것"


def test_point_id_range_and_distinct():
    """TC-CR-02 · Qdrant 정수 ID 범위(부호 없는 64비트) 안이고, 주소나 조각 번호가 다르면 다른 값이다."""
    a = crawl_point_id(URL, 0)
    assert isinstance(a, int) and 0 <= a < 2 ** 60
    assert a == crawl_point_id(URL, 0)
    assert len({crawl_point_id(URL, i) for i in range(200)}) == 200
    assert crawl_point_id(URL + "/2", 0) != a
    # 주소 끝 숫자와 조각 번호가 붙어 같은 글자가 되지 않는다("…/a1" + 0 ↔ "…/a" + 10)
    assert crawl_point_id("https://x.io/a1", 0) != crawl_point_id("https://x.io/a", 10)


def test_crawl_no_longer_uses_builtin_hash():
    """TC-CR-03 · 회귀 방지 — 크롤 저장 코드에 내장 hash() 점 ID 가 다시 들어오지 않는다."""
    src = (ROOT / "app" / "services" / "crawl.py").read_text(encoding="utf-8")
    assert "abs(hash(" not in src
    assert "crawl_point_id(" in src


# ── 2 · 3. 저장 · 정리 (가짜 qdrant_client) ─────────────────────────────────
class _Rec:
    """가짜 모델 — 받은 인수를 그대로 들고 있는다."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


class _FakeClient:
    """부른 값을 기록하는 가짜 AsyncQdrantClient — 컬렉션은 이미 있다고 답한다."""

    made: list["_FakeClient"] = []

    def __init__(self, url=None, **kw):
        self.upserts: list = []
        self.deletes: list = []
        _FakeClient.made.append(self)

    async def get_collection(self, name):
        return {"name": name}

    async def upsert(self, collection_name, points):
        self.upserts.append((collection_name, points))

    async def delete(self, collection_name, points_selector):
        self.deletes.append((collection_name, points_selector))

    async def close(self):
        return None


class _FakeOllama:
    def __init__(self, ok: bool = True):
        self.ok = ok

    async def embed(self, model, text):
        return [0.1, 0.2, 0.3] if self.ok else None


@pytest.fixture
def fake_qdrant(monkeypatch):
    models = types.ModuleType("qdrant_client.http.models")
    for name in ("PointStruct", "Filter", "FieldCondition", "MatchValue", "FilterSelector",
                 "HasIdCondition", "Distance", "VectorParams"):
        setattr(models, name, type(name, (_Rec,), {}))
    http = types.ModuleType("qdrant_client.http")
    http.models = models
    root = types.ModuleType("qdrant_client")
    root.AsyncQdrantClient = _FakeClient
    root.http = http
    monkeypatch.setitem(sys.modules, "qdrant_client", root)
    monkeypatch.setitem(sys.modules, "qdrant_client.http", http)
    monkeypatch.setitem(sys.modules, "qdrant_client.http.models", models)
    _FakeClient.made = []
    return _FakeClient


def _store(chunks, ok=True):
    meta = {"url": URL, "title": "guide", "source": "web"}
    return asyncio.run(crawl._store_qdrant(chunks, meta, _FakeOllama(ok)))


def test_recrawl_writes_same_ids_and_prunes_the_rest(fake_qdrant):
    """TC-CR-04 · 두 번 모으면 같은 ID 로 덮어쓰고, 이번에 쓴 ID 밖의 같은 주소 점을 지우는 거름을 보낸다."""
    assert _store(["가", "나", "다"]) == 3
    assert _store(["가", "나", "다"]) == 3
    first, second = fake_qdrant.made
    ids1 = [p.id for p in first.upserts[0][1]]
    ids2 = [p.id for p in second.upserts[0][1]]
    assert ids1 == ids2 == [crawl_point_id(URL, i) for i in range(3)]
    # payload 는 예전과 같다(채팅 근거 검색 · crawl.qdrant_search 가 읽는 칸)
    assert first.upserts[0][1][0].payload == {"url": URL, "title": "guide", "source": "web", "text": "가", "chunk_index": 0}

    (_, selector), = second.deletes
    flt = selector.filter
    (must,) = flt.must
    (must_not,) = flt.must_not
    assert must.key == "url" and must.match.value == URL
    assert must_not.has_id == ids2


def test_shorter_recrawl_keeps_only_new_chunks(fake_qdrant):
    """TC-CR-05 · 글이 짧아지면(3조각 → 2조각) 정리 거름이 남길 ID 는 새 두 조각뿐이다 — 셋째 조각이 지워진다."""
    _store(["가", "나", "다"])
    _store(["가", "나"])
    (_, selector), = fake_qdrant.made[-1].deletes
    assert selector.filter.must_not[0].has_id == [crawl_point_id(URL, 0), crawl_point_id(URL, 1)]


def test_embedding_down_means_no_write_no_delete(fake_qdrant):
    """TC-CR-06 · 임베딩이 하나도 안 되면 올리지도 지우지도 않는다 — 옛 근거를 남긴다."""
    assert _store(["가", "나"], ok=False) == 0
    client = fake_qdrant.made[-1]
    assert client.upserts == [] and client.deletes == []
