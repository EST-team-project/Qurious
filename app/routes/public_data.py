"""로그인 없이 읽는 공개 자료 — /api/public

- GET /api/public/index-closes : 랜딩의 지수 종가 한 줄 — 코스피 · 코스닥의 **가장 최근 거래일 종가**(S166)

로그인 없이 읽는다
    로그인 전 첫 화면(랜딩)이 부른다. 값은 수집 DB 의 지수 일봉(공공데이터포털 금융위원회 지수시세정보 —
    공공누리 제4유형)이고 **가공 없이 종가 그대로** · 기준일 · 출처 문구를 같이 싣는다. 외부 시세 사이트는 부르지 않는다.

가볍게 지킨다
    - 서버 캐시 10분 — 수집 DB 는 하루 한 번(12:30 회차) 바뀐다.
    - 같은 주소에서 분당 30번까지(넘으면 429) — 로그인 전 화면이라 아무나 반복해서 부를 수 있다.
    - 못 읽으면 `items` 가 빈 목록인 200 — 화면은 칸을 통째로 숨긴다(빈 숫자를 첫 화면에 두지 않는다).
"""
from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request, Response

from app.lib.redis_cache import rate_limit_cache
from app.services import collector_db
from app.services.login_guard import client_ip

router = APIRouter(prefix="/api/public", tags=["public"])

CACHE_TTL_SEC = 600
RATE_WINDOW_SEC = 60
RATE_MAX = 30

_cache: dict = {"at": 0.0, "value": None}


async def _allowed(request: Request) -> bool:
    """같은 주소에서 한 창(분)에 RATE_MAX 번까지. 횟수 저장소가 안 되면 막지 않는다(캐시가 있어 값싼 읽기)."""
    bucket = f"public-index:{client_ip(request)}:{int(time.time() // RATE_WINDOW_SEC)}"
    try:
        return await rate_limit_cache.incr(bucket, ttl=RATE_WINDOW_SEC) <= RATE_MAX
    except Exception:
        return True


@router.get("/index-closes")
async def index_closes(request: Request, response: Response):
    if not await _allowed(request):
        raise HTTPException(429, "잠시 뒤에 다시 불러 주세요.")
    now = time.monotonic()
    value = _cache["value"]
    if value is None or now - _cache["at"] > CACHE_TTL_SEC:
        value = await collector_db.get_latest_index_closes()
        _cache["at"], _cache["value"] = now, value
    response.headers["Cache-Control"] = "public, max-age=300"
    return {"as_of": value["as_of"], "source": collector_db.INDEX_SOURCE, "items": value["items"]}
