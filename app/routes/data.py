"""데이터 상태 API — /api/data (목표 기능 ① W4 · 설계서 5.2.2 · 7절)

- GET /api/data/status : 일일 갱신(12:30 러너) 결과 · 표별 기준일과 늦음 판정 · 거래일 달력 · HF 태그

로그인한 사람만 — 수집 자료의 양 · 상태와 PC 의 작업 기록이라(설계서 7절 「수집 자료는 로그인 뒤」).
`GET /api/system/sync-status`(외부 시세 캐시의 신선도)와는 다른 것을 본다 — 화면의 「데이터 기준일」 은 이쪽이다.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends

from app.lib.session import get_current_user
from app.services import data_status

router = APIRouter(prefix="/api/data", tags=["data"])


@router.get("/status", summary="데이터 상태")
async def status(_user=Depends(get_current_user)):
    # 표 세기 · 파일 읽기는 1초 안팎이지만 이벤트 루프를 막지 않게 스레드에서 돈다.
    return await asyncio.to_thread(data_status.get_status)
