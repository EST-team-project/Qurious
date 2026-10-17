"""용어사전 API — /api/glossary

- GET /api/glossary               : 용어 목록 · 검색 (q · category · limit · offset)
- GET /api/glossary/categories    : 분류 목록과 분류마다의 용어 수
- GET /api/glossary/meta          : 지금 표에 든 용어사전의 판(체크섬 · 적재 시각 · 자료별 용어 수)
- GET /api/glossary/{name}        : 용어 한 건 — 대표 이름 · ID · 약어 · 영어 이름 · 화면 키 어느 것으로도 찾는다
                                    (2026-10-02~ 연관 개념 `related[]` — 헷갈리는 말 · 상위 · 하위 · 연관)
- GET /api/glossary/{name}/graph  : 관계 지도 — 한 용어에서 1 · 2 단계까지 이어진 용어(노드)와 관계(간선)
- POST /api/glossary/scan         : 글 속 용어 찾기 — 답 · 신호 이름 · 본문에 든 용어(2026-10-17 · `app/services/glossary_scan.py`)
                                    글이 길어(상담 답 4,000자까지) 주소 대신 본문으로 받는다 · 아무것도 바꾸지 않는다

로그인 없이 읽는다
    용어 풀이는 누구에게나 같은 참조 자료이고 사용자 데이터가 없다. 읽기 전용이라 바꾸는 주소도 없다(찾기의 POST 도 읽기만).
    (용어를 고치는 길은 API 가 아니라 파일이다 — scripts/glossary_build.py)

주소 차례
    `/categories` · `/meta` 를 `/{name}` 보다 **먼저** 등록한다. FastAPI 는 먼저 등록한 주소부터 맞춰 보므로,
    차례가 바뀌면 「categories」 라는 이름의 용어를 찾다가 404 를 낸다.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.postgres import get_pg_session
from app.services import glossary, glossary_scan

router = APIRouter(prefix="/api/glossary", tags=["glossary"])


class ScanBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=glossary_scan.MAX_TEXT, description="찾을 글(상담 답 · 신호 이름 · 본문)")
    limit: int = Field(glossary_scan.DEFAULT_LIMIT, ge=1, le=glossary_scan.MAX_LIMIT, description="돌려줄 용어 수 상한")


@router.post("/scan", summary="글 속 용어 찾기 — 답 · 신호 이름 · 본문에 든 용어사전 용어")
async def scan_terms(body: ScanBody):
    """글에 든 용어(대표 이름 · 약어 · 다른 이름)를 나온 차례로 — 화면은 `id` 로 용어 칩(`data-term`)을 붙인다."""
    items = await asyncio.to_thread(glossary_scan.scan, body.text, limit=body.limit)
    return {
        "items": items,
        "rule": ("띄어쓰기는 접어 견줍니다 · 영문은 대문자 약어만 · 한글 두 글자 이하는 금융 고유어만 · 겹치면 긴 이름 · "
                 "같은 용어는 한 번 · 글에 나온 차례"),
    }


@router.get("", summary="용어 목록 · 검색")
async def list_terms(
    q: str = Query("", max_length=60, description="검색어 — 이름 · 약어 · 영어 · 초성(두 글자 이상) · 풀이 본문. 비우면 전체"),
    category: str | None = Query(None, max_length=20, description="분류 코드 (GET /api/glossary/categories 의 code)"),
    limit: int = Query(30, ge=1, le=glossary.MAX_LIMIT, description="한 번에 받을 개수"),
    offset: int = Query(0, ge=0, description="건너뛸 개수"),
    db: AsyncSession = Depends(get_pg_session),
):
    """용어를 찾는다. 이름이 정확히 같은 것 → 이름이 검색어로 시작하는 것 → 이름에 든 것 → 풀이에 든 것 차례로 돌려준다."""
    return await glossary.search(db, q, category, limit, offset)


@router.get("/categories", summary="분류 목록")
async def list_categories(db: AsyncSession = Depends(get_pg_session)):
    """분류와 분류마다의 용어 수를 화면에 늘어놓는 차례로 돌려준다."""
    return await glossary.categories(db)


@router.get("/meta", summary="용어사전의 판")
async def glossary_meta(db: AsyncSession = Depends(get_pg_session)):
    """표에 든 용어사전이 언제 · 어떤 파일 판으로 들어왔는지, 지금 파일과 같은 판인지 돌려준다."""
    return await glossary.meta(db)


@router.get("/{name}", summary="용어 한 건", responses={404: {"description": "그 이름의 용어가 없다"}})
async def get_term(name: str, db: AsyncSession = Depends(get_pg_session)):
    """이름 하나로 용어를 찾는다. 화면의 용어 키(예: sharpe)로도 찾는다 — 설명창이 같은 키로 이 주소를 부를 수 있다."""
    if len(name) > 120:          # 별칭 칸의 길이를 넘는 이름은 있을 수 없다 — DB 에 묻지 않고 돌려보낸다
        raise HTTPException(404, "용어를 찾지 못했습니다.")
    found = await glossary.get_term(db, name)
    if found is None:
        raise HTTPException(404, "용어를 찾지 못했습니다.")
    return found


@router.get("/{name}/graph", summary="관계 지도", responses={404: {"description": "그 이름의 용어가 없다"}})
async def term_graph(
    name: str,
    depth: int = Query(1, ge=1, le=2, description="몇 단계까지 퍼질까 — 1 은 바로 이어진 용어만, 2 는 그 이웃까지"),
    db: AsyncSession = Depends(get_pg_session),
):
    """용어 하나에서 이어진 용어와 관계를 그래프 모양(노드 · 간선)으로 돌려준다 — 용어 카드의 「작은 관계 지도」 가 쓴다."""
    if len(name) > 120:
        raise HTTPException(404, "용어를 찾지 못했습니다.")
    found = await glossary.graph(db, name, depth)
    if found is None:
        raise HTTPException(404, "용어를 찾지 못했습니다.")
    return found
