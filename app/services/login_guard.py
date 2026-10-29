"""로그인 시도 횟수 제한 (할 일 ①-09 · 2026-10-29).

비밀번호를 계속 바꿔 넣어 보는 공격(무차별 대입 · 비밀번호 뿌리기)을 늦춘다 — OWASP 인증 치트시트의 「로그인 시도 제한」.
`POST /api/auth/login` · `POST /api/auth/token` 이 비밀번호를 확인하기 **전에** `check`, 틀리면 `record_failure`, 맞으면 `reset` 을 부른다
(두 길 모두 막지 않으면 막지 않은 쪽으로 돌아간다).

규칙
  - **실패만 센다.** 정상 로그인이 많아도 걸리지 않는다. 열 분(`WINDOW_SEC`) 안에 같은 이메일로 다섯 번(`MAX_FAILS`) 틀리면, 그 창이 끝날 때까지
    그 이메일의 로그인은 **비밀번호가 맞아도** 막는다(맞는 것을 알려 주면 막은 뜻이 없다).
  - **주소(IP) 잠금은 기본 꺼짐**(`LOGIN_IP_MAX_FAILS` 환경변수가 0 이거나 없을 때 — 켜려면 양수 · 예 30). 이 앱은 도커 · 프록시 뒤에 있어 **모든 사용자가
    한 주소로 보인다**(2026-10-29 실측: 컨테이너가 본 주소가 전부 도커 게이트웨이 `172.18.0.1`). 그 상태에서 IP 잠금을 켜면 누구든 10분에 30번만 틀려도
    **전원이 로그인하지 못한다**(맞는 비밀번호도). 진짜 접속 주소를 믿을 수 있는 배치(프록시가 넘기는 주소를 검증해 쓰는 경우)에서만 켠다.
  - **없는 이메일도 똑같이 센다** — 가입된 이메일만 잠기면 「이 이메일은 가입돼 있다」 가 새어 나간다(account.verify_password 가 시간을 맞추는 것과 같은 까닭).
  - 맞게 로그인하면 그 이메일의 실패 횟수를 지운다(주소 횟수는 지우지 않는다 — 한 주소가 이메일을 바꿔 가며 뿌리는 것을 늦춰야 해서).
  - 키에는 이메일 원문을 두지 않고 지문(sha256 앞 24자)만 둔다. 만료는 Redis 가 한다 — 키에 만료가 빠진 것을 발견하면(INCR 뒤 EXPIRE 전에 끊긴 경우)
    다시 붙인다. 안 그러면 그 이메일이 영영 잠긴다.
  - **Redis 가 안 되면 막지 않는다(열린 채로 둔다)** — 이 서비스의 세션 · 토큰도 Redis 를 쓰므로 Redis 가 죽으면 로그인 자체가 안 된다. 제한 때문에
    정상 사용자를 더 막지 않고 경고만 남긴다.
  - 주소는 `request.client.host` 만 본다(`X-Forwarded-For` 는 보내는 쪽이 꾸밀 수 있다) — IP 잠금을 켠 배치에서만 쓰인다.
"""
from __future__ import annotations

import hashlib
import logging
import os

from app.lib import redis_cache

log = logging.getLogger("qurious.login_guard")

MAX_FAILS = 5          # 한 이메일이 창 안에서 틀릴 수 있는 횟수
IP_MAX_FAILS = int(os.environ.get("LOGIN_IP_MAX_FAILS", "0") or 0)   # 한 주소가 창 안에서 틀릴 수 있는 횟수 — 0 이면 IP 잠금 없음(기본 · 모듈 머리말)
WINDOW_SEC = 600       # 실패를 세는 창이자 잠금이 풀리는 시간(첫 실패부터)
WARN_AT = 2            # 남은 횟수가 이것 이하면 401 글에 「N회 더 틀리면 …」 를 붙인다(이메일이 없어도 같은 글이라 새지 않는다)


class LoginLocked(Exception):
    """너무 많이 틀렸다 — retry_after 초 뒤에 다시."""

    def __init__(self, retry_after: int):
        super().__init__(f"locked for {retry_after}s")
        self.retry_after = max(1, int(retry_after))

    def message(self) -> str:
        minutes = (self.retry_after + 59) // 60
        return f"로그인 시도가 너무 많습니다. {minutes}분 뒤에 다시 시도해 주세요."


def _email_key(email: str) -> str:
    digest = hashlib.sha256((email or "").strip().lower().encode("utf-8")).hexdigest()[:24]
    return f"login_fail:e:{digest}"


def _ip_key(ip: str) -> str:
    return f"login_fail:ip:{ip or 'unknown'}"


async def _count(r, key: str) -> int:
    v = await r.get(key)
    return int(v) if v else 0


async def check(email: str, ip: str) -> None:
    """한도를 넘었으면 LoginLocked. Redis 가 안 되면 그냥 지나간다."""
    try:
        r = redis_cache.get_redis()
        limits = [(_email_key(email), MAX_FAILS)]
        if IP_MAX_FAILS > 0:
            limits.append((_ip_key(ip), IP_MAX_FAILS))
        for key, limit in limits:
            if await _count(r, key) >= limit:
                ttl = await r.ttl(key)
                raise LoginLocked(ttl if isinstance(ttl, int) and ttl > 0 else WINDOW_SEC)
    except LoginLocked:
        raise
    except Exception as exc:  # noqa: BLE001 — Redis 오류는 로그인을 더 막지 않는다
        log.warning("로그인 제한 확인을 건너뜁니다(Redis): %s", exc)


async def record_failure(email: str, ip: str) -> int:
    """틀렸다 — 이메일 · 주소 횟수를 올리고 이 이메일이 몇 번 더 틀릴 수 있는지(0 이상)를 돌려준다. Redis 가 안 되면 MAX_FAILS."""
    try:
        r = redis_cache.get_redis()
        left = MAX_FAILS
        keys = [(_email_key(email), True)]
        if IP_MAX_FAILS > 0:                 # IP 잠금이 꺼져 있으면 주소를 저장하지도 않는다(수집 항목을 늘리지 않는다)
            keys.append((_ip_key(ip), False))
        for key, is_email in keys:
            n = await r.incr(key)
            if n == 1 or (await r.ttl(key)) < 0:     # 첫 실패이거나, 만료가 빠진 키(INCR 뒤 끊김)
                await r.expire(key, WINDOW_SEC)
            if is_email:
                left = max(0, MAX_FAILS - int(n))
        return left
    except Exception as exc:  # noqa: BLE001
        log.warning("로그인 실패 횟수를 못 셌습니다(Redis): %s", exc)
        return MAX_FAILS


async def reset(email: str) -> None:
    """맞게 로그인했다 — 이 이메일의 실패 횟수를 지운다(주소 횟수는 두는 까닭은 모듈 머리말 — IP 잠금을 켠 배치에서)."""
    try:
        await redis_cache.get_redis().delete(_email_key(email))
    except Exception as exc:  # noqa: BLE001
        log.warning("로그인 실패 횟수를 못 지웠습니다(Redis): %s", exc)


def failure_message(left: int) -> str:
    """401 글 — 남은 횟수가 적을 때만 경고를 덧붙인다."""
    base = "이메일 또는 비밀번호가 올바르지 않습니다."
    if left == 0:
        return f"{base} {MAX_FAILS}번 틀려 {WINDOW_SEC // 60}분 동안 로그인이 잠겼습니다."
    if left <= WARN_AT:
        return f"{base} {left}회 더 틀리면 {WINDOW_SEC // 60}분 동안 로그인이 잠깁니다."
    return base


def client_ip(request) -> str:
    """요청의 주소 — 요청 객체 없이 직접 불린 경우(시험)는 「unknown」 하나로 센다."""
    client = getattr(request, "client", None)
    return client.host if client else "unknown"
