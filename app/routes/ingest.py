import os
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.postgres import get_pg_session
from app.lib.session import get_current_user
from app.lib.llm_client import get_llm_client
from app.models import CrawledDoc
from app.services.financial_ingest import run_full_ingest
from app.services.crawl import run_auto_crawl, crawl_url, crawl_naver_stock, _chunk_text, _store_qdrant
from app.services import url_guard  # Qurious: 주소 검사(허용 목록 · 내부망 · robots) — 규칙은 그 파일에
from app.services.task_access import enqueue_owned_task
from app.config import settings  # Qurious: 번역 자료 API 켜기 설정(TRANSLATION_API_ENABLED)
from app.lib import vector_db  # Qurious: 「모음 없음」 · 「Qdrant 장애」 를 가르는 예외(DF-149)
from app.services.translation_ingest import (
    run_translation_ingest,
    translation_search,
    TRANSLATION_COLLECTION,
    EmbeddingUnavailable,  # Qurious
    TranslationDataMissing,  # Qurious
)

router = APIRouter(prefix="/api")


def _translation_gate(user=Depends(get_current_user)):
    """Qurious(2026-10-23 · 결정 T6): 번역 자료 API 문지기 — 기본은 꺼짐 · 켜도 관리자만.

    모음 조각에 AI허브 원문 · 번역이 그대로 있어, 로그인만 보면 승인받지 않은 사람이 원문을 본다(이용정책 5항 「열람」).
    꺼짐 · 관리자 아님 모두 403 — 404 는 「모음 없음(적재 전)」 에만 쓴다(검색 응답과 헷갈리지 않게).
    """
    if not settings.TRANSLATION_API_ENABLED:
        raise HTTPException(403, "번역 자료 API 가 꺼져 있습니다 — AI허브 원문은 승인받은 사람만 볼 수 있어 기본으로 끕니다"
                                 "(설정 TRANSLATION_API_ENABLED).")
    if "admin" not in user.get("roles", []):
        raise HTTPException(403, "관리자 권한이 필요합니다.")
    return user


@router.post("/ingest/financial")
async def ingest_financial(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_pg_session),
):
    log: list[str] = []
    result = await run_full_ingest(db, log)
    return {"ok": True, "result": result, "log": log}


@router.post("/ingest/crawl/auto")
async def crawl_auto(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_pg_session),
):
    ollama = get_llm_client()
    log: list[str] = []
    result = await run_auto_crawl(db, ollama, log)
    return {"ok": True, "result": result, "log": log}


class CrawlUrlBody(BaseModel):
    url: str


@router.post("/ingest/crawl/url")
async def crawl_manual(
    body: CrawlUrlBody,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_pg_session),
):
    await url_guard.ensure_allowed(body.url)  # Qurious: 막히면 400
    ollama = get_llm_client()
    log: list[str] = []
    chunks = await crawl_url(body.url, db, ollama, log)
    return {"ok": True, "chunks": chunks, "log": log}


class CrawlNaverBody(BaseModel):
    code: str  # 6-digit stock code (e.g. 005930)


@router.post("/ingest/crawl/naver")
async def crawl_naver(
    body: CrawlNaverBody,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_pg_session),
):
    """네이버 금융 종목 페이지 전용 크롤링."""
    await url_guard.ensure_allowed(f"https://finance.naver.com/item/main.naver?code={body.code}")  # Qurious: 결정 ① 「막음」
    ollama = get_llm_client()
    log: list[str] = []
    chunks = await crawl_naver_stock(body.code, db, ollama, log)
    message = "네이버 주식 크롤링이 완료되었습니다." if chunks > 0 else "네이버 주식 크롤링 결과가 없습니다."
    return {"ok": True, "chunks": chunks, "message": message}


@router.post("/ingest/local-docs")
async def ingest_local_docs(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_pg_session),
):
    """data/raw/ 하위 로컬 Markdown 문서를 Qdrant RAG에 인제스트."""
    ollama = get_llm_client()
    log: list[str] = []
    total = 0

    raw_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "data", "raw")
    )

    for dirpath, _, files in os.walk(raw_root):
        for fname in files:
            if not fname.endswith(".md"):
                continue
            fpath = os.path.join(dirpath, fname)
            with open(fpath, encoding="utf-8") as f:
                content = f.read()
            if len(content) < 50:
                continue

            chunks = _chunk_text(content)
            rel_path = os.path.relpath(fpath, raw_root)
            url = f"local://{rel_path}"
            source = f"local:{rel_path}"
            meta = {"url": url, "title": fname, "source": source}
            stored = await _store_qdrant(chunks, meta, ollama)
            stmt = pg_insert(CrawledDoc).values(url=url, title=fname, content=content[:5000], source=source)
            stmt = stmt.on_conflict_do_update(
                index_elements=[CrawledDoc.url],
                set_={"title": fname, "content": content[:5000], "source": source},
            )
            await db.execute(stmt)
            await db.commit()
            log.append(f"✓ {rel_path} → {len(chunks)}청크 (Qdrant {stored}건)")
            total += len(chunks)

    return {"ok": True, "total_chunks": total, "log": log}


class TranslationIngestBody(BaseModel):
    data_type: str = "labeled"       # "labeled" | "source" | "all"
    categories: list[str] = []       # [] = 전체. e.g. ["news","report"]
    languages: list[str] = []        # [] = 전체. e.g. ["en","ja"]
    max_docs: int = 0                # 0 = 무제한


@router.post("/ingest/translation-data")
async def ingest_translation_data(
    body: TranslationIngestBody,
    user=Depends(_translation_gate),  # Qurious: 기본 끔 · 관리자만(결정 T6)
):
    """data/1.데이터 다국어 번역 ZIP → Qdrant translation_docs 컬렉션 인제스트."""
    ollama = get_llm_client()
    log: list[str] = []
    try:  # Qurious: 예전엔 원자료가 없어도 · 임베딩이 죽어도 200(0건 · error 칸)이었다
        result = await run_translation_ingest(
            ollama,
            log,
            data_type=body.data_type,
            categories=body.categories or None,
            languages=body.languages or None,
            max_docs=body.max_docs,
        )
    except TranslationDataMissing:
        raise HTTPException(404, "번역 원자료 폴더(data/1.데이터/)가 없습니다 — AI허브 71782 자료를 각자 신청해 받아 "
                                 "받은 파일 이름 그대로 두세요(이 PC 에만 · 저장소 · 해외 서버에 올리지 않음).") from None
    except (vector_db.VectorDBUnavailable, EmbeddingUnavailable) as exc:
        raise HTTPException(503, f"번역 자료를 적재하지 못했습니다 — {exc}") from None
    return {"ok": True, "result": result, "log": log}


class TranslationSearchBody(BaseModel):
    query: str
    top_k: int = 5
    category: str | None = None
    target_language: str | None = None


@router.post("/ingest/translation-search")
async def search_translation(
    body: TranslationSearchBody,
    user=Depends(_translation_gate),  # Qurious: 기본 끔 · 관리자만(결정 T6)
):
    """translation_docs 컬렉션에서 한국어 쿼리로 유사 문서 검색.

    Qurious(DF-149 · 결정 T2): 모음 없음 = 404 · Qdrant · 임베딩 장애 = 503 · 결과 0건 = 200 빈 목록(top_k 는 20 까지).
    """
    ollama = get_llm_client()
    try:
        hits = await translation_search(
            body.query,
            ollama,
            top_k=body.top_k,
            category=body.category,
            target_language=body.target_language,
        )
    except vector_db.CollectionMissing:
        raise HTTPException(404, "번역 자료가 아직 적재되지 않았습니다 — 관리자가 data/1.데이터/ 에 AI허브 자료를 두고 "
                                 "POST /api/ingest/translation-data 로 적재한 뒤 검색할 수 있습니다.") from None
    except (vector_db.VectorDBUnavailable, EmbeddingUnavailable) as exc:
        raise HTTPException(503, f"번역 검색을 하지 못했습니다 — {exc}") from None
    return {"ok": True, "hits": hits, "collection": TRANSLATION_COLLECTION}


# ── 비동기 인제스트 엔드포인트 (Celery) ──────────────────────────────────────────

@router.post("/ingest/financial/async", summary="금융 데이터 비동기 인제스트")
async def ingest_financial_async(user=Depends(get_current_user), db: AsyncSession = Depends(get_pg_session)):
    """CSV 금융 데이터 인제스트를 Celery 워커에 위임하고 task_id 를 반환한다.
    GET /api/tasks/{task_id} 로 완료 여부와 결과를 폴링한다.
    """
    from app.tasks.ingest_tasks import financial_ingest_task
    task_id = await enqueue_owned_task(db, user, financial_ingest_task)
    return {"task_id": task_id, "poll_url": f"/api/tasks/{task_id}"}


@router.post("/ingest/crawl/auto/async", summary="자동 크롤링 비동기 인제스트")
async def crawl_auto_async(user=Depends(get_current_user), db: AsyncSession = Depends(get_pg_session)):
    """자동 크롤링을 Celery 워커에 위임한다."""
    from app.tasks.ingest_tasks import auto_crawl_task
    task_id = await enqueue_owned_task(db, user, auto_crawl_task)
    return {"task_id": task_id, "poll_url": f"/api/tasks/{task_id}"}


@router.post("/ingest/crawl/url/async", summary="URL 크롤링 비동기 인제스트")
async def crawl_url_async(body: CrawlUrlBody, user=Depends(get_current_user), db: AsyncSession = Depends(get_pg_session)):
    """단일 URL 크롤링을 Celery 워커에 위임한다."""
    await url_guard.ensure_allowed(body.url)  # Qurious: 막히면 400
    from app.tasks.ingest_tasks import url_crawl_task
    task_id = await enqueue_owned_task(db, user, url_crawl_task, url=body.url)
    return {"task_id": task_id, "poll_url": f"/api/tasks/{task_id}"}


@router.post("/ingest/translation-data/async", summary="번역 데이터 비동기 인제스트")
async def ingest_translation_async(
    body: TranslationIngestBody,
    user=Depends(_translation_gate),  # Qurious: 기본 끔 · 관리자만(결정 T6) — 비동기 길도 같은 문지기
    db: AsyncSession = Depends(get_pg_session),
):
    """다국어 번역 데이터 인제스트를 Celery 워커에 위임한다."""
    from app.tasks.ingest_tasks import translation_ingest_task
    task_id = await enqueue_owned_task(db, user, translation_ingest_task,
        data_type=body.data_type,
        categories=body.categories or None,
        languages=body.languages or None,
        max_docs=body.max_docs,
    )
    return {"task_id": task_id, "poll_url": f"/api/tasks/{task_id}"}


@router.get("/ingest/crawl/list")
async def list_crawled(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_pg_session),
):
    result = await db.execute(
        select(CrawledDoc.url, CrawledDoc.title, CrawledDoc.source, CrawledDoc.crawled_at)
        .order_by(CrawledDoc.crawled_at.desc())
        .limit(100)
    )
    items = [
        {"url": r.url, "title": r.title, "source": r.source, "crawled_at": r.crawled_at.isoformat()}
        for r in result.all()
    ]
    return {"items": items}
