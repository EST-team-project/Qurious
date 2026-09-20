"""JWT 기반 액세스/리프레시 토큰 발급 및 검증.

인증 흐름:
1. POST /api/auth/token → access_token(단기) + refresh_token(장기) 반환
2. Authorization: Bearer <access_token> 헤더로 API 호출
3. 액세스 토큰 만료 시 POST /api/auth/token/refresh → 새 액세스 토큰 발급
4. 로그아웃 시 POST /api/auth/token/revoke → Redis 폐기 목록 등록

세션 쿠키 방식과 병행 지원 – get_current_user_any()로 두 방식 모두 허용.

── 폐기(revocation) 설계 메모 ────────────────────────────────────────────────
폐기 목록의 키는 **토큰마다 달라야** 한다. 2026-09-20 이전에는 ``token[:32]`` 를 썼는데,
HS256 토큰의 헤더 base64 는 언제나 ``eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9``(36자)라
앞 32자가 **모든 토큰에서 한 글자까지 같았다**. 그래서 누가 한 번 로그아웃하면
``jwt_bl:eyJhbGciOiJIUzI1NiIsInR5cCI6IkpX`` 단 하나의 키가 켜지고, 전 사용자의 JWT 가
그 토큰의 남은 수명(리프레시면 최대 7일) 동안 막혔다.

지금은 두 단계로 키를 고른다:

1. ``jti`` 클레임 — 토큰마다 새로 만드는 uuid4. RFC 7519 §4.1.7 이 정의하는
   "충돌 확률이 무시할 만한 고유 식별자"이고, OWASP JWT Cheat Sheet 가 폐기 목록의
   키로 권하는 값이다.
2. ``jti`` 가 없는 옛 토큰 — ``sha256(header.payload)``.
   **토큰 전체가 아니라 서명 앞까지**만 해싱하는 이유는, 서명 부분의 base64 는 HMAC 이
   덮는 범위 밖이라 같은 서명을 여러 문자열로 표현할 수 있기 때문이다(JWT malleability).
   토큰 전체를 해싱하면 한 글자만 바꾼 변조본이 폐기 목록을 비켜 간다.
   ``header.payload`` 는 HMAC 의 입력 바이트 그 자체라 한 바이트만 달라져도 서명 검증에서
   먼저 걸린다.
"""
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.config import settings
from app.lib.redis_cache import jwt_blacklist_cache

_bearer = HTTPBearer(auto_error=False)

#: 저장소에 커밋된 자리표시자 비밀값. 이 값으로는 토큰을 발급·검증하지 않는다.
_PLACEHOLDER_SECRET = "change-me-jwt-secret-32chars-min!!"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _unix(dt: datetime) -> int:
    return int(dt.timestamp())


def _require_real_secret() -> None:
    """기본 비밀값으로 JWT 를 쓰지 못하게 막습니다.

    ``JWT_SECRET`` 기본값은 **공개 저장소에 그대로 들어 있습니다**. 그 값으로 서명하면
    누구나 아무 사용자의 토큰을 위조할 수 있어, 폐기 목록을 고쳐도 소용이 없습니다.
    그래서 기본값이면 여기서 멈춥니다.

    막는 자리를 모듈 import 가 아니라 **토큰을 만들고 읽는 시점**으로 잡은 이유는,
    ``app.config`` 를 함께 쓰는 수집기(``collector/``)나 스크립트가 JWT 와 무관한데도
    못 돌게 되는 일을 피하기 위해서입니다.

    로컬에서 임시로 넘기려면 ``JWT_ALLOW_INSECURE_SECRET=true`` 를 환경에 둡니다.
    """
    if settings.JWT_SECRET != _PLACEHOLDER_SECRET:
        return
    if settings.JWT_ALLOW_INSECURE_SECRET:
        return
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=(
            "JWT_SECRET 이 저장소에 커밋된 기본값 그대로입니다. "
            "`openssl rand -hex 32` 로 만든 값을 .env 파일의 JWT_SECRET 에 넣으세요. "
            "(로컬 실험용으로 넘기려면 JWT_ALLOW_INSECURE_SECRET=true)"
        ),
    )


# ── 토큰 생성 ──────────────────────────────────────────────────────────────────

def create_access_token(payload: dict) -> str:
    """단기 액세스 토큰 (기본 15분).

    ``jti`` 는 **이 함수 안에서** 새로 만듭니다. 호출부에서 넣어 주면
    ``create_token_pair`` 가 같은 payload 를 두 번 쓰는 탓에 액세스와 리프레시가
    같은 ``jti`` 를 갖게 되고, 하나를 폐기하면 둘 다 끊깁니다.
    호출부가 넣어 온 ``jti`` 는 일부러 덮어씁니다.
    """
    _require_real_secret()
    data = {
        **payload,
        "type": "access",
        "jti": uuid.uuid4().hex,
        "iat": _unix(_now()),
        "exp": _unix(_now() + timedelta(seconds=settings.JWT_ACCESS_TTL)),
    }
    return jwt.encode(data, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(payload: dict) -> str:
    """장기 리프레시 토큰 (기본 7일). ``jti`` 는 액세스와 따로 만듭니다."""
    _require_real_secret()
    data = {
        **payload,
        "type": "refresh",
        "jti": uuid.uuid4().hex,
        "iat": _unix(_now()),
        "exp": _unix(_now() + timedelta(seconds=settings.JWT_REFRESH_TTL)),
    }
    return jwt.encode(data, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_token_pair(user_payload: dict) -> dict:
    """액세스 + 리프레시 토큰 쌍 반환."""
    return {
        "access_token": create_access_token(user_payload),
        "refresh_token": create_refresh_token(user_payload),
        "token_type": "bearer",
        "expires_in": settings.JWT_ACCESS_TTL,
    }


# ── 토큰 검증 ──────────────────────────────────────────────────────────────────

def decode_token(token: str, *, verify_exp: bool = True) -> dict:
    """서명을 검증하고 클레임을 돌려줍니다.

    ``exp`` 를 **필수**로 둡니다. python-jose 는 ``exp`` 가 없으면 만료 검증을 통째로
    건너뛰므로(``require_exp`` 기본값이 False), 만료도 폐기도 되지 않는 토큰이 생깁니다.

    ``verify_exp=False`` 는 폐기 경로 전용입니다 — 이미 만료된 리프레시 토큰을
    로그아웃 때 제출하더라도 서명은 확인하되 만료를 이유로 거절하지 않기 위해서입니다.
    """
    _require_real_secret()
    try:
        return jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require_exp": True, "verify_exp": verify_exp},
        )
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"유효하지 않은 토큰: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _bl_key(token: str, payload: dict) -> str:
    """폐기 목록 키. 토큰마다 달라야 합니다 (모듈 상단 설계 메모 참고).

    ``payload`` 는 **서명이 검증된 클레임**이어야 합니다. 검증 전 값으로 키를 만들면
    공격자가 원하는 키를 지목할 수 있습니다.
    """
    jti = payload.get("jti")
    if jti:
        return f"jti:{jti}"
    # jti 가 없는 옛 토큰 — 서명 앞까지(HMAC 이 덮는 범위)만 해싱한다.
    signed_part = token.rsplit(".", 1)[0]
    return "sha:" + hashlib.sha256(signed_part.encode()).hexdigest()


async def revoke_token(token: str) -> dict:
    """토큰을 폐기 목록에 올립니다.

    돌려주는 값은 폐기된 토큰의 클레임입니다. 호출부가 "누구의 토큰인지"를 확인하는 데
    씁니다. 서명이 틀리면 :class:`HTTPException` 이 그대로 올라갑니다 —
    예전처럼 조용히 삼키면 실패한 로그아웃이 성공으로 보입니다.
    """
    payload = decode_token(token, verify_exp=False)
    ttl = max(0, payload.get("exp", 0) - _unix(_now()))
    if ttl > 0:
        await jwt_blacklist_cache.set(_bl_key(token, payload), "revoked", ttl=ttl)
    return payload


async def is_revoked(token: str, payload: dict) -> bool:
    """폐기 여부. **서명 검증을 마친 payload** 를 함께 받습니다."""
    return await jwt_blacklist_cache.exists(_bl_key(token, payload))


# ── FastAPI Depends ────────────────────────────────────────────────────────────

async def get_current_user_jwt(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    """Bearer 토큰으로 현재 사용자를 반환합니다."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer 토큰이 필요합니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials
    # 순서가 중요하다 — 먼저 서명을 검증해야 폐기 목록 키를 믿을 수 있다.
    payload = decode_token(token)
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="액세스 토큰이 아닙니다.",
        )
    if await is_revoked(token, payload):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="만료(폐기)된 토큰입니다.",
        )
    return payload


async def get_current_user_any(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    fin_session: Optional[str] = Cookie(default=None),
) -> dict:
    """Bearer JWT 또는 세션 쿠키 중 하나로 인증합니다.

    JWT가 있으면 우선 처리, 없으면 쿠키 세션으로 폴백합니다.
    """
    if credentials and credentials.credentials:
        return await get_current_user_jwt(credentials)

    if fin_session:
        from app.lib.session import get_session  # 순환 임포트 방지
        user = await get_session(fin_session)
        if user:
            return user

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="로그인이 필요합니다.",
    )


def require_roles(*roles: str):
    """특정 역할을 가진 사용자만 허용하는 Depends 팩토리.

    사용 예::

        @router.get("/admin")
        async def admin_only(user=Depends(require_roles("admin"))):
            ...
    """
    async def _check(user: dict = Depends(get_current_user_any)) -> dict:
        user_roles = user.get("roles", [])
        if not any(r in user_roles for r in roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"권한이 없습니다. 필요 역할: {list(roles)}",
            )
        return user
    return _check
