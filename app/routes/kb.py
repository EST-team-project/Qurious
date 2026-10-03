"""근거 문서 API — /api/kb (목표 기능 ① W5 · 설계서 5.3 · 7절)

- GET /api/kb/documents?kind=                                   : 받아 둔 법령 · 감독규정의 판 목록(시행일 · 받은 때 · 지문 · 벡터 수)
- GET /api/kb/search?q=&k=&as_of=&kind=&docs=&mode=&model=&route= : 근거 청크 — 낱말 + 벡터 → RRF · 질문 분류 가중

문서 목록은 로그인 없이 — 공개 법령의 판 정보뿐이다. 찾기는 로그인 뒤 — 검색어마다 임베딩 모델을 부른다
(설계서 7절 「수집 자료와 LLM 호출은 로그인 뒤」). 답 만들기(`POST /api/kb/ask` · W6)는 이 찾기 위에 얹는다.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query

from app.lib.session import get_current_user
from app.services import kb_search

router = APIRouter(prefix="/api/kb", tags=["kb"])


@router.get("/documents", summary="근거 문서 판 목록")
async def kb_documents(kind: str | None = Query(None, description="law(법령) · admrul(감독규정 · 행정규칙) — 비우면 전부")):
    try:
        return await asyncio.to_thread(kb_search.documents, kind)
    except kb_search.KbError as e:
        raise HTTPException(status_code=e.status, detail=e.detail()) from None


@router.get("/search", summary="근거 청크 찾기")
async def kb_search_route(
    q: str = Query(..., min_length=1, max_length=200, description="질문이나 낱말 — 예: 2026년 코스피 증권거래세율"),
    k: int = Query(kb_search.DEFAULT_K, ge=1, le=kb_search.MAX_K, description="돌려줄 근거 수"),
    as_of: str | None = Query(None, description="기준일 YYYY-MM-DD — 그날 시행 중인 판만 찾는다(비우면 오늘 KST)"),
    kind: str | None = Query(None, description="law · admrul — 비우면 둘 다"),
    docs: str | None = Query(None, max_length=300, description="문서 ID 몇 개만(쉼표) — /api/kb/documents 의 doc_id"),
    mode: str = Query("hybrid", description="hybrid(낱말 + 벡터) · lexical · dense"),
    model: str | None = Query(None, description="임베딩 모델 — bge-m3(기본) · nomic-embed-text"),
    route: bool = Query(True, description="질문 분류 가중(세금 · 회사 · 투자 규제) — 끄면 낱말 · 벡터만"),
    _user=Depends(get_current_user),
):
    doc_list = [d.strip() for d in docs.split(",") if d.strip()] if docs else None
    try:
        # SQLite 읽기 · 임베딩 호출이 이벤트 루프를 막지 않게 스레드에서
        return await asyncio.to_thread(kb_search.search, q, k, as_of=as_of, kind=kind, docs=doc_list,
                                       mode=mode, model=model, route=route)
    except kb_search.KbError as e:
        raise HTTPException(status_code=e.status, detail=e.detail()) from None
