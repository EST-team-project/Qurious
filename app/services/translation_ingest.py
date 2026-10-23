"""1.데이터 다국어 번역 데이터 → Qdrant RAG 인제스트.

Qurious(2026-10-23 · DF-149) — 강사님 기초 코드에서 바꾼 것(줄마다 「Qurious:」 표시):
- Qdrant 는 문지기(app/lib/vector_db.py)로 부른다. 검색은 `query_points`(예전 `search` 는 qdrant-client 1.16 에서 없어져
  AttributeError 가 났고, 넓은 except 가 그것을 「0건」 으로 숨겨 번역 검색은 한 번도 결과를 낸 적이 없다).
- 「모음 없음(적재 전)」 · 「Qdrant · 임베딩 장애」 · 「결과 0건」 을 가른다 — 앞의 둘은 예외로 올리고 라우트가 404 · 503 으로 알린다.
- 클라이언트는 예외 길에서도 닫는다. 원자료 폴더가 없으면 「적재 0건 · 성공」 이 아니라 TranslationDataMissing.
- 점 ID 는 그대로 zip 파일 이름을 품는다(결정 T5) — AI허브에서 **받은 이름 그대로** 두어야 다시 적재해도 같은 점을 덮어쓴다.
  적재 결과에 읽은 zip 이름을 남긴다(다른 사람의 모음과 맞대 볼 때의 기록).
원자료는 각자 AI허브에 신청해 이 PC 에만 둔다 — HF · Colab · 해외 서버에 올리지 않는다(국외 반출 · 조사
docs/phase-3/01-analysis/research/배경조사/2026-10-23-번역모음-대조-대안/결과.md).
"""
import asyncio
import hashlib
import json
import os
import zipfile
from typing import AsyncIterator

import httpx  # Qurious: 임베딩 호출 실패(httpx 오류)를 EmbeddingUnavailable 로 가른다

from app.config import settings
from app.lib import vector_db  # Qurious: Qdrant 문지기(DF-149)
from app.lib.ollama import OllamaClient

TRANSLATION_COLLECTION = "translation_docs"
SENTS_PER_CHUNK = 10       # 문장 N개를 하나의 청크로 묶음
EMBED_BATCH = 32           # Qdrant upsert 배치 크기
MAX_TOP_K = 20             # Qurious: 검색 한 번에 돌려줄 최대 건수(user_docs 와 같은 상한 — 원문을 한꺼번에 빼 가지 못하게)

DATA_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "1.데이터")
)

CATEGORY_MAP = {
    "1. 학술논문": "academic",
    "2. 규제정보": "regulation",
    "3. 보고서": "report",
    "4. 뉴스기사": "news",
    "5. 공시정보": "disclosure",
}

LANG_MAP = {
    "1. 영어": "en",
    "2. 중국어간체": "zh",
    "3. 일본어": "ja",
    "4. 베트남어": "vi",
    "5. 인도네시아어": "id",
}


class TranslationDataMissing(FileNotFoundError):
    """Qurious: 번역 원자료 폴더(data/1.데이터/)가 없다 — 각자 AI허브 71782 를 신청해 받아 두어야 한다(라우트 404)."""


class EmbeddingUnavailable(RuntimeError):
    """Qurious: 임베딩 모델이 답하지 않았다(연결 실패 · 빈 답) — 라우트 503."""


def _parse_zip_name(fname: str) -> dict:
    """파일명에서 카테고리·언어 추출. e.g. TL_4. 뉴스기사_3. 일본어.zip"""
    stem = os.path.splitext(fname)[0]
    parts = stem.split("_", 1)
    prefix = parts[0]  # TS / TL
    rest = parts[1] if len(parts) > 1 else ""
    cat_raw, lang_raw = (rest.split("_", 1) + [""])[:2]

    category = next((v for k, v in CATEGORY_MAP.items() if k in cat_raw), cat_raw.strip())
    target_lang = next((v for k, v in LANG_MAP.items() if k in lang_raw), "")
    data_type = "labeled" if prefix == "TL" else "source"
    return {"category": category, "target_language": target_lang, "data_type": data_type}


def _doc_chunks(doc: dict, zip_meta: dict) -> list[dict]:
    """JSON 문서 하나 → 청크 리스트."""
    meta = doc.get("meta", {})
    sents = doc.get("sents", [])
    if not sents:
        return []

    chunks = []
    for i in range(0, len(sents), SENTS_PER_CHUNK):
        batch = sents[i: i + SENTS_PER_CHUNK]
        src_text = " ".join(
            s.get("source_cleaned") or s.get("source_original", "") for s in batch
        ).strip()
        if not src_text:
            continue

        tgt_text = ""
        if zip_meta["data_type"] == "labeled":
            tgt_text = " ".join(s.get("mtpe") or s.get("mt", "") for s in batch).strip()

        chunks.append({
            "text": src_text,
            "translation": tgt_text,
            "doc_no": meta.get("doc_no", ""),
            "domain": meta.get("domain", ""),
            "category": zip_meta["category"],
            "source_language": meta.get("source_language", "ko"),
            "target_language": zip_meta["target_language"],
            "data_type": zip_meta["data_type"],
            "chunk_index": i // SENTS_PER_CHUNK,
        })
    return chunks


def _chunk_id(doc_no: str, chunk_index: int, zip_name: str) -> int:
    # Qurious(결정 T5): zip 이름을 품는다 — 이름을 바꿔 두면 내용이 같아도 ID 가 모두 달라진다(받은 이름 그대로 둘 것).
    # 내용 기반(doc_no · 유형 · 언어)으로 바꾸면 라벨링(TL_) · 원천(TS_) zip 의 같은 문서가 같은 ID 로 부딪혀 번역을 덮어쓴다.
    raw = f"{zip_name}::{doc_no}::{chunk_index}"
    return int(hashlib.sha256(raw.encode()).hexdigest()[:15], 16)


async def _ensure_collection(client, dim: int):
    await vector_db.ensure_collection(client, TRANSLATION_COLLECTION, dim)  # Qurious: 문지기(없으면 만들기 · 닿지 못하면 예외)


async def _upsert_batch(client, points: list):
    qm = vector_db.models()  # Qurious: 문지기
    structs = [
        qm.PointStruct(id=p["id"], vector=p["vector"], payload=p["payload"])
        for p in points
    ]
    await vector_db.upsert(client, TRANSLATION_COLLECTION, structs)  # Qurious: 빈 묶음은 부르지 않음 · 닿지 못하면 예외


async def _embed(ollama: OllamaClient, text: str) -> list[float]:
    """Qurious: 임베딩 한 번 — 닿지 못하면 EmbeddingUnavailable(예전엔 검색이 빈 목록으로 숨었다). 빈 답은 빈 목록 그대로."""
    try:
        return await ollama.embed(settings.EMBED_MODEL, text) or []
    except httpx.HTTPError as exc:
        raise EmbeddingUnavailable(
            f"임베딩 모델({settings.EMBED_MODEL}) 호출 실패 — {type(exc).__name__}: {str(exc)[:200]}"
        ) from exc


async def _iter_zips(data_type_filter: str, categories: list[str], languages: list[str]):
    """필터 조건에 맞는 zip 파일 경로를 순회."""
    for split in ("Training", "Validation"):
        for sub in ("01.원천데이터", "02.라벨링데이터"):
            dirpath = os.path.join(DATA_DIR, split, sub)
            if not os.path.isdir(dirpath):
                continue
            for fname in sorted(os.listdir(dirpath)):
                if not fname.endswith(".zip"):
                    continue
                zm = _parse_zip_name(fname)
                if data_type_filter != "all" and zm["data_type"] != data_type_filter:
                    continue
                if categories and zm["category"] not in categories:
                    continue
                if languages and zm["target_language"] and zm["target_language"] not in languages:
                    continue
                yield os.path.join(dirpath, fname), fname, zm


async def run_translation_ingest(
    ollama: OllamaClient,
    log: list[str],
    data_type: str = "labeled",
    categories: list[str] | None = None,
    languages: list[str] | None = None,
    max_docs: int = 0,
) -> dict:
    """
    data_type: "labeled" | "source" | "all"
    categories: ["news","report",...] or None (전체)
    languages:  ["en","ja","zh","vi","id"] or None (전체)
    max_docs:   0 = 무제한

    Raises(Qurious):
        TranslationDataMissing: 원자료 폴더가 없다(라우트 404).
        EmbeddingUnavailable · vector_db.VectorDBUnavailable: 임베딩 모델 · Qdrant 에 닿지 못했다(라우트 503).
            중간에 멈춰도 다시 돌리면 된다 — 점 ID 가 정해진 값이라 같은 점을 덮어쓴다.
    """
    cats = categories or []
    langs = languages or []

    if not os.path.isdir(DATA_DIR):  # Qurious: 예전엔 「0문서 · 성공」 이었다
        raise TranslationDataMissing(DATA_DIR)

    client = vector_db.async_client()  # Qurious: 문지기
    try:  # Qurious: 예외 길에서도 닫는다
        # 차원 확인
        test_emb = await _embed(ollama, "test")
        if not test_emb:
            log.append("[ERROR] 임베딩 모델 응답 없음")
            raise EmbeddingUnavailable(f"임베딩 모델({settings.EMBED_MODEL}) 응답이 비었다")  # Qurious: 예전엔 200 + error 칸
        dim = len(test_emb)
        await _ensure_collection(client, dim)

        total_docs = 0
        total_chunks = 0
        total_points = 0
        skipped_chunks = 0  # Qurious: 임베딩이 빈 답이라 넣지 못한 조각
        zips: list[str] = []  # Qurious(결정 T5): 읽은 zip 이름 — 받은 이름 그대로인지 맞대 볼 기록
        pending: list[dict] = []

        async def flush():
            nonlocal total_points
            if pending:
                await _upsert_batch(client, pending)
                total_points += len(pending)
                pending.clear()

        async for zip_path, zip_name, zm in _iter_zips(data_type, cats, langs):
            log.append(f"[ZIP] {zip_name} ({zm['data_type']}, {zm['category']}, {zm['target_language']})")
            try:
                zf = zipfile.ZipFile(zip_path)
            except Exception as e:
                log.append(f"  [SKIP] {e}")
                continue
            zips.append(zip_name)

            zip_docs = 0
            zip_chunks = 0
            with zf:  # Qurious: zip 파일 손잡이를 닫는다
                for member in zf.namelist():
                    if not member.endswith(".json"):
                        continue
                    if max_docs and total_docs >= max_docs:
                        break
                    try:
                        doc = json.loads(zf.read(member))
                    except Exception:
                        continue

                    chunks = _doc_chunks(doc, zm)
                    for ch in chunks:
                        emb = await _embed(ollama, ch["text"])
                        if not emb:
                            skipped_chunks += 1
                            continue
                        pending.append({
                            "id": _chunk_id(ch["doc_no"], ch["chunk_index"], zip_name),
                            "vector": emb,
                            "payload": ch,
                        })
                        if len(pending) >= EMBED_BATCH:
                            await flush()

                    zip_docs += 1
                    zip_chunks += len(chunks)
                    total_docs += 1
                    total_chunks += len(chunks)

            await flush()
            log.append(f"  → {zip_docs}문서 / {zip_chunks}청크")

        await flush()
    finally:
        await vector_db.aclose(client)

    summary = {
        "total_docs": total_docs,
        "total_chunks": total_chunks,
        "total_points": total_points,
        "skipped_chunks": skipped_chunks,
        "zips": zips,
        "collection": TRANSLATION_COLLECTION,
    }
    log.append(f"\n완료: {total_docs}문서, {total_chunks}청크, Qdrant {total_points}건")
    return summary


async def translation_search(
    query: str,
    ollama: OllamaClient,
    top_k: int = 5,
    category: str | None = None,
    target_language: str | None = None,
) -> list[dict]:
    """번역 데이터 벡터 검색 — 결과가 없으면 빈 목록.

    Raises(Qurious · DF-149 — 예전엔 셋 모두 빈 목록이라 「적재 전」 · 「장애」 · 「0건」 을 가를 수 없었다):
        vector_db.CollectionMissing: 번역 모음이 아직 없다(적재 전 · 라우트 404). 임베딩 모델은 부르지 않는다.
        vector_db.VectorDBUnavailable: Qdrant 에 닿지 못했다(라우트 503).
        EmbeddingUnavailable: 임베딩 모델이 답하지 않았다(라우트 503).
        그 밖(AttributeError 등 우리 코드 잘못)은 삼키지 않는다.
    """
    k = max(1, min(int(top_k or 5), MAX_TOP_K))  # Qurious: 상한
    qm = vector_db.models()
    conditions = []
    if category:
        conditions.append(qm.FieldCondition(key="category", match=qm.MatchValue(value=category)))
    if target_language:
        conditions.append(qm.FieldCondition(key="target_language", match=qm.MatchValue(value=target_language)))
    flt = qm.Filter(must=conditions) if conditions else None

    client = vector_db.async_client()
    try:
        if not await vector_db.exists(client, TRANSLATION_COLLECTION):
            raise vector_db.CollectionMissing(TRANSLATION_COLLECTION)
        qemb = await _embed(ollama, query)
        if not qemb:
            raise EmbeddingUnavailable(f"임베딩 모델({settings.EMBED_MODEL}) 응답이 비었다")
        hits = await vector_db.query(client, TRANSLATION_COLLECTION, qemb, query_filter=flt, limit=k)
    finally:
        await vector_db.aclose(client)
    return [
        {
            "score": h.score,
            "text": h.payload.get("text", ""),
            "translation": h.payload.get("translation", ""),
            "doc_no": h.payload.get("doc_no", ""),
            "category": h.payload.get("category", ""),
            "target_language": h.payload.get("target_language", ""),
            "domain": h.payload.get("domain", ""),
        }
        for h in hits
    ]
