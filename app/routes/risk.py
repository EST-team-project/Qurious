"""재무 · 신용 위험 API — /api/risk (화면 키 `agent-cb` · 결정 ② A · 2026-10-13)

- GET /api/risk/company : 상장사 한 곳의 재무 건전성 — 우리 DART 주요계정(판 고르기 · 시점 고정은 `data_financials` 한 곳)으로
  유동비율 · 부채비율 · 자기자본비율 · 자본잠식률 · Altman Z'' · 영업이익 흐름 · 점검 일곱(자료가 없는 둘은 까닭과 함께)
- GET /api/risk/macro   : 시장 전체의 신용 스프레드 — 한국은행 ECOS 시장금리(수집기가 매일 받음)로 회사채 AA- · BBB- − 국고채
  3년 · CP − CD(같은 날만 · 지난 10년 안의 위치)

옛 화면(신용 리스크 분석)은 조건을 글로 만들어 범용 대화 API 에 물었고, 대화 쪽 도구는 비어 있는 개인 · 기업 CB 표를
되풀이 읽어 답이 약 2분 걸렸다(점검표 「외부 의존」 · −2). 이 API 는 대화를 거치지 않고 숫자 · 쉬운 말 · 출처를 돌려준다.
로그인한 사람만. 일반 사용자 답에는 표 이름 · 명령을 싣지 않는다(관리자에게만 할 일).
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query

from app.lib.session import get_current_user
from app.services import company_health, macro_credit

router = APIRouter(prefix="/api/risk", tags=["risk"])


@router.get("/company", summary="재무 · 신용 위험 — 상장사 재무 건전성(DART 주요계정)")
async def company(
    symbol: str = Query(..., max_length=6, description="종목 단축코드 6자리"),
    as_of: str | None = Query(None, description="YYYY-MM-DD — 이날 전날까지 접수된 판만(비우면 가장 최근 판)"),
    fs: str = Query("CFS", max_length=3, description="CFS(연결 · 없으면 별도로 바꾸고 그 사실을 fs_note 로) · OFS(별도)"),
    user=Depends(get_current_user),
):
    try:
        return await asyncio.to_thread(company_health.read_health, symbol, as_of, fs)
    except company_health.HealthError as e:
        # 수집 · 설정 문제(5xx)의 할 일(명령)은 관리자에게만 — 일반 사용자는 글만 본다
        raise HTTPException(status_code=e.status, detail=e.detail("admin" in user.get("roles", []))) from None


@router.get("/macro", summary="재무 · 신용 위험 — 신용 스프레드(ECOS 시장금리)")
async def macro(
    years: int = Query(macro_credit.DEFAULT_YEARS, ge=1, le=macro_credit.MAX_YEARS, description="그림에 보일 햇수"),
    user=Depends(get_current_user),
):
    admin = "admin" in user.get("roles", [])
    try:
        return await asyncio.to_thread(macro_credit.read_macro, years, admin)
    except macro_credit.MacroError as e:
        raise HTTPException(status_code=e.status, detail=e.detail()) from None
