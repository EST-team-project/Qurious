"""ADR-0002 1단계 계약 시험 — 분석 RAG 가 Qdrant 를 찾고, 색인 잡이 같은 곳 · 같은 방식으로 넣는다.

도커 없이 파일만 읽는다. 실제 기동 검증(`docker compose --profile vector up` → `/api/rag/search`)은
docs/60-시스템/아키텍처-다중저장소 문서 §7 의 명령으로 한다.
지키는 것:
  1. Qdrant 는 선택 저장소다 — vector 프로필에만 있고, api 는 Qdrant 를 기다리지 않는다(없으면 그 기능만 503).
  2. 색인 잡은 Qdrant 가 준비된 뒤에 돌고, api 와 같은 주소 · 같은 컬렉션을 쓴다.
  3. 색인 잡의 임베딩과 질의 임베딩이 같다 — 다르면 검색이 예외 없이 조용히 틀린다(설계 문서 P2).
  4. private HF 데이터 캐시가 공개 저장소에 올라가지 않는다(설계 문서 §6).
"""
from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
# (compose 파일, 그 파일의 교재 색인 잡 이름)
COMPOSE_JOBS = [("docker-compose.yml", "docs-index"), ("docker-compose.prod.yml", "curriculum-index")]


def _services(name: str) -> dict:
    return yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))["services"]


@pytest.mark.parametrize("compose_file, job", COMPOSE_JOBS)
def test_qdrant_and_index_job_live_only_in_vector_profile(compose_file: str, job: str) -> None:
    services = _services(compose_file)
    assert services["qdrant"]["profiles"] == ["vector"]
    # 색인 잡을 tools 같은 다른 프로필에도 두면 `--profile tools` 만 켰을 때
    # 「depends on undefined service qdrant」로 compose 전체가 거절된다(2026-09-28 실측).
    assert services[job]["profiles"] == ["vector"]


@pytest.mark.parametrize("compose_file, job", COMPOSE_JOBS)
def test_api_starts_without_qdrant(compose_file: str, job: str) -> None:
    api = _services(compose_file)["api"]
    assert "qdrant" not in (api.get("depends_on") or {}), "api 가 선택 저장소를 기다리면 vector 프로필 없이 뜨지 않는다"
    assert "qdrant:6333" in api["environment"]["QDRANT_URL"]


@pytest.mark.parametrize("compose_file, job", COMPOSE_JOBS)
def test_index_job_waits_for_qdrant_and_uses_api_collection(compose_file: str, job: str) -> None:
    services = _services(compose_file)
    index_job, api = services[job], services["api"]
    assert index_job["depends_on"]["qdrant"]["condition"] == "service_healthy"
    assert index_job["environment"]["QDRANT_URL"] == "http://qdrant:6333"
    assert index_job["environment"]["RAG_QDRANT_COLLECTION"] == api["environment"]["RAG_QDRANT_COLLECTION"]
    command = index_job["command"]
    command = " ".join(command) if isinstance(command, list) else command
    assert "app.ops.index_curriculum" in command


@pytest.mark.parametrize("compose_file", [name for name, _ in COMPOSE_JOBS])
def test_api_query_embedding_is_the_one_the_index_job_writes(compose_file: str) -> None:
    # 색인 잡(index_curriculum.embed)은 sha256 토큰 해시만 쓴다 → 질의도 hash 여야 같은 공간이다.
    env = _services(compose_file)["api"]["environment"]
    assert env["RAG_EMBEDDING_PROVIDER"] in ("hash", "${RAG_EMBEDDING_PROVIDER:-hash}")


@pytest.mark.parametrize("text", ["채권 금리와 듀레이션", "ETF 분산투자 PER 10배", "", "   "])
def test_index_and_query_hash_embeddings_are_identical(text: str) -> None:
    pytest.importorskip("fastapi")
    from app.api.routes.rag_analysis import _hash_embed
    from app.ops.index_curriculum import embed

    assert embed(text) == _hash_embed(text)
    assert len(embed(text)) == 384


@pytest.mark.parametrize("server_up, expected", [
    (False, "--profile vector up -d"),
    (True, "--profile vector run --rm docs-index"),
])
def test_503_message_tells_the_vector_profile_command(monkeypatch: pytest.MonkeyPatch, server_up: bool, expected: str) -> None:
    pytest.importorskip("fastapi")
    from fastapi import HTTPException

    import app.api.routes.rag_analysis as rag

    monkeypatch.setattr(rag, "_qdrant_available", lambda: server_up)
    monkeypatch.setattr(rag, "_qdrant_collection_available", lambda: False)
    with pytest.raises(HTTPException) as error:
        rag._require_qdrant()
    assert error.value.status_code == 503
    assert expected in error.value.detail


def test_prod_qdrant_sets_no_cpu_limit() -> None:
    # 도커는 호스트 코어 수보다 큰 cpus 를 거절한다(「range of CPUs is from 0.01 to N」 · 2026-09-28 실측).
    # 1 vCPU 서버에서 cpus: 2 면 qdrant 가 뜨지 않는다.
    assert "cpus" not in _services("docker-compose.prod.yml")["qdrant"]


def test_local_qdrant_cpu_limit_is_overridable() -> None:
    assert _services("docker-compose.yml")["qdrant"]["cpus"] == "${QDRANT_CPUS:-2}"


def test_hf_cache_is_ignored() -> None:
    lines = {line.strip() for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()}
    assert "data/hf_cache/" in lines
    assert "*.parquet" in lines
