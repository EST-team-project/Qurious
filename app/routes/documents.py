"""문서 업로드 → VLM 파싱 → Qdrant RAG 인제스트 API.

엔드포인트:
  POST   /api/documents/upload     - 파일 업로드 및 RAG 인제스트
  GET    /api/documents/list       - 업로드된 문서 목록
  DELETE /api/documents/{doc_id}   - 문서 삭제 (메타 + 벡터)
  POST   /api/documents/search     - 문서 전용 RAG 검색

(Qurious 2026-10-23 · DF-146) 올린 문서 조각은 사용자 비공개 모음에만 둔다 — 넣기 · 찾기 · 지우기는 모두
`app/services/user_docs.py`(문지기)를 거치고, 그 모듈이 주인 거름을 건다. 예전에는 크롤링 조각과 같은 공용 모음에
들어가 다른 사용자의 채팅 · 문서 검색에 보였고, 탈퇴 · 지우기 뒤에도 조각이 남을 수 있었다.
"""
from __future__ import annotations
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.postgres import get_pg_session
from app.lib.session import get_current_user
from app.lib.llm_client import get_llm_client
from app.models import UploadedDoc
from app.services.doc_parser import parse_document, SUPPORTED_EXTENSIONS
from app.services import user_docs
from app.services.rag_pipeline import VectorStoreError
from app.config import settings

router = APIRouter(prefix="/api/documents", tags=["documents"])

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


# ── 업로드 ────────────────────────────────────────────────────────────────────

@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_pg_session),
):
    """
    문서 파일을 업로드하여 VLM으로 파싱한 뒤 Qdrant RAG에 인제스트한다.

    - 지원 형식: pptx, ppt, docx, doc, xlsx, xls, pdf, md, txt
    - 이미지 슬라이드/페이지는 Ollama VLM(llava)이 자동으로 설명 텍스트 생성
    - 청크는 올린 사람의 비공개 모음에 저장되며, 그 사람의 채팅 근거 · 문서 검색에만 쓰인다(DF-146)
    """
    from pathlib import Path
    ext = Path(file.filename or "").suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            400,
            f"지원하지 않는 파일 형식입니다. 허용: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(413, "파일 크기가 50 MB를 초과합니다.")
    if len(content) == 0:
        raise HTTPException(400, "빈 파일입니다.")

    ollama = get_llm_client()

    try:
        chunks = await parse_document(file.filename, content, ollama)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(422, f"문서 파싱 실패: {str(e)[:200]}")

    if not chunks:
        raise HTTPException(422, "문서에서 텍스트를 추출할 수 없습니다.")

    source_key = f"upload:{user['id']}:{file.filename}"
    # 문서 ID 를 먼저 정해 조각에도 싣는다 — 같은 이름 파일을 두 번 올려도 문서마다 따로 지운다(DF-146).
    # 올린 사람 이메일은 조각에 싣지 않는다(주인 UUID 만 · 이메일은 이 사람의 DB 행에만).
    doc_id = uuid.uuid4()
    meta = {
        "url":      f"upload://{file.filename}",
        "title":    file.filename,
        "source":   source_key,
    }

    try:
        stored = await user_docs.store(user["id"], doc_id, chunks, meta)
    except VectorStoreError as e:
        # (Qurious 2026-10-02 · DF-38) 예전에는 저장이 실패해도 「업로드 완료 (0청크 저장)」 200 이었다.
        raise HTTPException(503, f"벡터 저장소(Qdrant) · 임베딩 모델({settings.EMBED_MODEL})에 저장하지 못했습니다 — {e}")

    doc = UploadedDoc(
        id=doc_id,
        filename=file.filename,
        uploader=user["email"],
        user_id=uuid.UUID(user["id"]),
        source_key=source_key,
        chunks=stored,
        file_size=len(content),
        ext=ext,
    )
    db.add(doc)
    try:
        await db.commit()
    except Exception as exc:
        # 목록에 없는 조각을 남기지 않는다 — 방금 넣은 조각을 지우고 다시 올려 달라고 알린다.
        await db.rollback()
        try:
            await user_docs.delete_doc(user["id"], doc_id, source_key)
        except VectorStoreError as cleanup:
            logging.getLogger("qurious.documents").warning("올리기 되돌리기 실패 (%s): %s", doc_id, cleanup)
        raise HTTPException(500, "문서 정보를 저장하지 못했습니다 — 다시 올려 주세요.") from exc
    await db.refresh(doc)

    return {
        "ok":       True,
        "doc_id":   str(doc.id),
        "filename": file.filename,
        "chunks":   stored,
        "message":  f"'{file.filename}' 업로드 완료 ({stored}청크 저장)",
    }


# ── 목록 조회 ─────────────────────────────────────────────────────────────────

@router.get("/list")
async def list_documents(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_pg_session),
):
    """현재 사용자가 업로드한 문서 목록을 반환한다."""
    result = await db.execute(
        select(UploadedDoc)
        .where(UploadedDoc.user_id == uuid.UUID(user["id"]))
        .order_by(UploadedDoc.created_at.desc())
        .limit(100)
    )
    items = [{
        "doc_id": str(d.id), "filename": d.filename, "chunks": d.chunks,
        "file_size": d.file_size, "ext": d.ext, "created_at": d.created_at.isoformat(),
    } for d in result.scalars().all()]

    return {"items": items}


# ── 삭제 ─────────────────────────────────────────────────────────────────────

@router.delete("/{doc_id}")
async def delete_document(
    doc_id: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_pg_session),
):
    """
    문서의 PostgreSQL 메타데이터와 Qdrant 벡터를 모두 삭제한다.
    본인이 업로드한 문서만 삭제할 수 있다.
    """
    try:
        oid = uuid.UUID(doc_id)
    except Exception:
        raise HTTPException(400, "유효하지 않은 doc_id입니다.")

    result = await db.execute(
        select(UploadedDoc).where(UploadedDoc.id == oid, UploadedDoc.user_id == uuid.UUID(user["id"]))
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(404, "문서를 찾을 수 없거나 삭제 권한이 없습니다.")

    # 조각부터 지운다 — 못 지우면 DB 행을 남겨 두고 503(예전엔 실패해도 행을 지워 조각만 남았다 · DF-146).
    try:
        await user_docs.delete_doc(user["id"], doc.id, doc.source_key or "")
    except VectorStoreError as exc:
        logging.getLogger("qurious.documents").warning("문서 조각 지우기 실패 (%s): %s", doc.id, exc)
        raise HTTPException(503, "문서 조각을 지우지 못해 멈췄습니다 — 잠시 뒤 다시 해 주세요(문서는 그대로 있습니다).")

    filename = doc.filename
    await db.delete(doc)
    await db.commit()

    return {"ok": True, "message": f"'{filename}' 삭제 완료"}


# ── 문서 전용 RAG 검색 ────────────────────────────────────────────────────────

class DocSearchBody(BaseModel):
    query:  str = Field(..., min_length=1, max_length=2000)
    top_k:  int = Field(5, ge=1, le=user_docs.MAX_TOP_K)
    source: str | None = Field(None, max_length=400)   # 내 문서 가운데 그 source_key 로 좁힌다(남의 키를 주면 0건)


@router.post("/search")
async def search_documents(
    body: DocSearchBody,
    user=Depends(get_current_user),
):
    """내가 올린 문서에서만 쿼리와 비슷한 조각을 찾는다(주인 거름은 문지기가 건다 · DF-146)."""
    hits = await user_docs.search(user["id"], body.query, top_k=body.top_k, source=body.source)
    return {"ok": True, "hits": hits}
