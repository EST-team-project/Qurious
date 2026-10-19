"""KIS 토큰을 환경·키별로 공유한다. Redis 발급 슬롯은 성공/실패 뒤에도 1분 유지한다."""
import asyncio
import hashlib
import json
import time

import redis.asyncio as redis
from redis.exceptions import RedisError

from app.config import settings


class KISTokenError(RuntimeError):
    def __init__(self, code: str, message: str, *, upstream_status=None, vendor_code=None):
        super().__init__(message)
        self.code = code
        self.upstream_status = upstream_status
        self.vendor_code = vendor_code


def cache_key(base_url: str, app_key: str, app_secret: str) -> str:
    fingerprint = hashlib.sha256(json.dumps([base_url, app_key, app_secret]).encode()).hexdigest()
    return "kis:access-token:v1:" + fingerprint


async def shared_token(key: str, issue) -> dict:
    # Celery는 회차마다 이벤트 루프를 새로 만들 수 있으므로 연결도 이 호출 안에서 닫는다.
    try:
        async with redis.from_url(settings.REDIS_URL, decode_responses=True,
                                  socket_connect_timeout=2, socket_timeout=2) as store:
            async def read():
                raw = await store.get(key)
                if raw:
                    data = json.loads(raw)
                    if data.get("token") and float(data.get("expires_at", 0)) > time.time() + 30:
                        return data
                return None

            data = await read()
            if data:
                return data
            if await store.set(key + ":issue", "1", nx=True, ex=60):
                # 읽기와 슬롯 획득 사이에 다른 요청이 발급을 마쳤을 수 있다.
                data = await read()
                if data:
                    return data
                data = await issue()
                ttl = max(1, int(data["expires_at"] - time.time() - 30))
                await store.set(key, json.dumps(data), ex=ttl)
                return data
            # 같은 회차의 동시 주문은 선행 요청이 받아 둔 토큰을 기다린다.
            for _ in range(110):
                await asyncio.sleep(0.1)
                data = await read()
                if data:
                    return data
            raise KISTokenError("KIS_TOKEN_RATE_LIMIT", "접속 토큰 발급 제한 또는 발급 대기 중입니다.")
    except (RedisError, ValueError, TypeError, KeyError) as exc:
        # 공유 잠금 없이 재발급하면 여러 워커가 다시 403을 유발한다. 주문 전에 차단한다.
        raise KISTokenError("KIS_TOKEN_UNAVAILABLE", "접속 토큰 저장소를 확인하지 못했습니다.") from exc
