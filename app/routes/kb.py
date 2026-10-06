"""근거 문서 API — /api/kb (목표 기능 ① W5 · W6 · 설계서 5.3 · 7절)

- GET  /api/kb/documents?kind=                                   : 받아 둔 법령 · 감독규정의 판 목록(시행일 · 받은 때 · 지문 · 벡터 수)
- GET  /api/kb/search?q=&k=&as_of=&kind=&docs=&mode=&model=&route=&links=&synonyms= : 근거 청크 — 낱말 + 벡터 → RRF ·
      질문 분류 가중 · 법령 말로 검색어 넓히기(synonyms) · 근거마다 위임 조(delegated)
- POST /api/kb/ask                                               : 근거 번호가 달린 답 — 찾기 위에 LLM 답 · 서버의 출처 검사

문서 목록은 로그인 없이 — 공개 법령의 판 정보뿐이다. 찾기 · 답하기는 로그인 뒤 — 질문마다 임베딩 · 답 모델을 부른다
(설계서 7절 「수집 자료와 LLM 호출은 로그인 뒤」).
"""
from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.lib.session import get_current_user
from app.services import kb_answer, kb_search

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
    links: bool = Query(True, description="위임 조 잇기 — 찾은 법 조가 하위 법령에 맡긴 조를 근거마다 delegated 로"),
    synonyms: bool = Query(True, description="질문 말 → 법령 말(코스피 → 유가증권시장)로 검색어 넓히기"),
    _user=Depends(get_current_user),
):
    doc_list = [d.strip() for d in docs.split(",") if d.strip()] if docs else None
    try:
        # SQLite 읽기 · 임베딩 호출이 이벤트 루프를 막지 않게 스레드에서
        return await asyncio.to_thread(kb_search.search, q, k, as_of=as_of, kind=kind, docs=doc_list,
                                       mode=mode, model=model, route=route, links=links, synonyms=synonyms)
    except kb_search.KbError as e:
        raise HTTPException(status_code=e.status, detail=e.detail()) from None


class AskBody(BaseModel):
    """`POST /api/kb/ask` 몸통 — 찾기 인자에 답 방식(`answer`) · 답 모델(`llm`)을 더했다."""

    q: str = Field(..., min_length=1, max_length=300, description="질문 — 예: 로보어드바이저는 법에서 뭐라고 부르나요?")
    k: int = Field(kb_answer.DEFAULT_ASK_K, ge=1, le=kb_answer.MAX_ASK_K, description="답에 넣을 근거 수")
    as_of: str | None = Field(None, description="기준일 YYYY-MM-DD — 그날 시행 중인 판만 근거로(비우면 오늘 KST)")
    kind: str | None = Field(None, description="law · admrul — 비우면 둘 다")
    docs: list[str] | None = Field(None, max_length=20, description="문서 ID 몇 개만 — /api/kb/documents 의 doc_id")
    mode: Literal["hybrid", "lexical", "dense"] = Field("hybrid", description="찾기 방식")
    model: str | None = Field(None, description="임베딩 모델 — bge-m3(기본) · nomic-embed-text")
    route: bool = Field(True, description="질문 분류 가중(세금 · 회사 · 투자 규제)")
    links: bool = Field(True, description="위임 조 잇기 — 법 조가 하위 법령에 맡긴 조를 윗 조 바로 뒤 근거로")
    synonyms: bool = Field(True, description="질문 말 → 법령 말 — 검색어 넓히기 · 답 문맥의 질문에 괄호로 덧붙이기")
    answer: Literal["llm", "extract"] = Field("llm", description="llm(답 모델이 근거로 답함) · extract(LLM 없이 근거 발췌)")
    llm: str | None = Field(None, max_length=120, description="답 모델(Ollama 이름) — 비우면 서버 기본값")


@router.post("/ask", summary="근거 번호가 달린 답")
async def kb_ask_route(body: AskBody, _user=Depends(get_current_user)):
    try:
        # 찾기 · 생성(수십 초)이 이벤트 루프를 막지 않게 스레드에서
        return await asyncio.to_thread(kb_answer.ask, body.q, body.k, as_of=body.as_of, kind=body.kind,
                                       docs=body.docs, mode=body.mode, model=body.model, route=body.route,
                                       links=body.links, synonyms=body.synonyms, answer=body.answer, llm=body.llm)
    except kb_search.KbError as e:
        raise HTTPException(status_code=e.status, detail=e.detail()) from None
