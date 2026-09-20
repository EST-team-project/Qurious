"""인증 라우터.

세션 쿠키 방식(기존)과 JWT Bearer 방식(신규)을 모두 지원합니다.

쿠키 방식 (브라우저):
  POST /api/auth/register  – 회원가입 + 세션 쿠키 발급
  POST /api/auth/login     – 로그인 + 세션 쿠키 발급
  POST /api/auth/logout    – 로그아웃 + 쿠키 삭제

JWT 방식 (API 클라이언트 / 모바일):
  POST /api/auth/token         – 로그인 → access_token + refresh_token 반환
  POST /api/auth/token/refresh – refresh_token → 새 access_token 발급
  POST /api/auth/token/revoke  – 토큰 폐기 (블랙리스트 등록)

공용:
  GET  /api/me       – 현재 사용자 정보 (쿠키 또는 Bearer 모두 허용)
  GET  /api/sessions – 내 활성 세션 목록
  DELETE /api/sessions/{sid} – 특정 세션 강제 만료
"""
import uuid

import bcrypt
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.database.postgres import get_session_factory
from app.models import User
from app.lib.jwt_auth import (
    create_token_pair,
    decode_token,
    get_current_user_any,
    is_revoked,
    require_roles,
    revoke_token,
)
from app.lib.session import (
    create_session,
    delete_all_user_sessions,
    delete_session,
    get_current_user,
    get_session,
    list_user_sessions,
)
from app.lib.user_state import clear_user_state, mark_offline, mark_online

router = APIRouter(prefix="/api")


# ── 요청/응답 스키마 ───────────────────────────────────────────────────────────

class RegisterBody(BaseModel):
    name: str
    email: EmailStr
    password: str


class LoginBody(BaseModel):
    email: str
    password: str


class TokenRefreshBody(BaseModel):
    refresh_token: str


class TokenRevokeBody(BaseModel):
    access_token: str
    refresh_token: str | None = None


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _build_session_data(user_id: str, user: dict) -> dict:
    return {
        "id": user_id,
        "name": user["name"],
        "email": user["email"],
        "client_id": user.get("client_id", ""),
        "roles": user.get("roles", ["user"]),
    }


async def _find_user_by_email(db, email: str) -> User | None:
    try:
        result = await db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()
    except Exception as e:
        raise HTTPException(503, f"데이터베이스 오류: {e}")


def _user_to_dict(user: User) -> dict:
    return {
        "name": user.name,
        "email": user.email,
        "client_id": user.client_id,
        "roles": list(user.roles),
    }


# ── 쿠키 기반 인증 ─────────────────────────────────────────────────────────────

@router.post("/auth/register")
async def register(body: RegisterBody, response: Response):
    try:
        session_factory = get_session_factory()
    except RuntimeError:
        raise HTTPException(503, "인증 서버(PostgreSQL)에 연결할 수 없습니다.")

    pw_hash = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()
    client_id = str(uuid.uuid4()).replace("-", "")[:16].upper()
    roles = ["admin"] if body.email in settings.admin_email_list else ["user"]

    async with session_factory() as db:
        user = User(
            name=body.name, email=body.email, password_hash=pw_hash,
            client_id=client_id, roles=roles,
        )
        db.add(user)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise HTTPException(400, "이미 사용 중인 이메일입니다.")
        user_id = str(user.id)

    session_data = _build_session_data(user_id, {
        "name": body.name, "email": body.email, "client_id": client_id, "roles": roles,
    })
    sid = await create_session(session_data)
    await mark_online(user_id)

    response.set_cookie(
        "fin_session", sid,
        httponly=True, samesite=settings.COOKIE_SAMESITE,
        secure=settings.COOKIE_SECURE, max_age=settings.SESSION_TTL,
    )
    return {"ok": True, "user": {"name": body.name, "email": body.email,
                                  "clientId": client_id, "roles": roles}}


@router.post("/auth/login")
async def login(body: LoginBody, response: Response):
    try:
        session_factory = get_session_factory()
    except RuntimeError:
        raise HTTPException(503, "인증 서버(PostgreSQL)에 연결할 수 없습니다.")

    async with session_factory() as db:
        user = await _find_user_by_email(db, body.email)
        if not user or not bcrypt.checkpw(body.password.encode(), user.password_hash.encode()):
            raise HTTPException(401, "이메일 또는 비밀번호가 올바르지 않습니다.")
        user_id = str(user.id)
        user_dict = _user_to_dict(user)

    session_data = _build_session_data(user_id, user_dict)
    sid = await create_session(session_data)
    await mark_online(user_id)

    response.set_cookie(
        "fin_session", sid,
        httponly=True, samesite=settings.COOKIE_SAMESITE,
        secure=settings.COOKIE_SECURE, max_age=settings.SESSION_TTL,
    )
    return {"ok": True, "user": {"name": user_dict["name"], "email": user_dict["email"],
                                  "clientId": user_dict["client_id"],
                                  "roles": user_dict["roles"]}}


@router.post("/auth/logout")
async def logout(
    response: Response,
    user=Depends(get_current_user),
    fin_session: str | None = Cookie(default=None),
):
    if fin_session:
        await delete_session(fin_session)
    await mark_offline(user["id"])
    response.delete_cookie("fin_session")
    return {"ok": True}


# ── JWT 기반 인증 ──────────────────────────────────────────────────────────────

@router.post("/auth/token")
async def issue_token(body: LoginBody):
    """JWT 액세스/리프레시 토큰을 발급합니다 (API 클라이언트용)."""
    try:
        session_factory = get_session_factory()
    except RuntimeError:
        raise HTTPException(503, "인증 서버(PostgreSQL)에 연결할 수 없습니다.")

    async with session_factory() as db:
        user = await _find_user_by_email(db, body.email)
        if not user or not bcrypt.checkpw(body.password.encode(), user.password_hash.encode()):
            raise HTTPException(401, "이메일 또는 비밀번호가 올바르지 않습니다.")
        user_id = str(user.id)
        user_dict = _user_to_dict(user)

    payload = {
        "sub": user_id,
        "id": user_id,
        "name": user_dict["name"],
        "email": user_dict["email"],
        "client_id": user_dict["client_id"],
        "roles": user_dict["roles"],
    }
    await mark_online(user_id)
    return create_token_pair(payload)


@router.post("/auth/token/refresh")
async def refresh_token(body: TokenRefreshBody):
    """리프레시 토큰으로 새 액세스 토큰을 발급합니다."""
    # 서명을 먼저 검증해야 폐기 목록 키를 믿을 수 있다 (jwt_auth._bl_key 주석 참고).
    payload = decode_token(body.refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(401, "리프레시 토큰이 아닙니다.")
    if await is_revoked(body.refresh_token, payload):
        raise HTTPException(401, "만료(폐기)된 리프레시 토큰입니다.")

    # 기존 리프레시 토큰은 유지, 새 액세스 토큰만 발급.
    # ★ jti 를 빼고 넘긴다 — 남기면 리프레시의 jti 가 새 액세스에 복사되어,
    #   액세스 하나를 폐기할 때 리프레시까지 함께 끊긴다.
    _CARRY_OVER_EXCLUDE = ("type", "jti", "iat", "exp")
    from app.lib.jwt_auth import create_access_token
    user_payload = {k: v for k, v in payload.items() if k not in _CARRY_OVER_EXCLUDE}
    return {
        "access_token": create_access_token(user_payload),
        "token_type": "bearer",
        "expires_in": settings.JWT_ACCESS_TTL,
    }


@router.post("/auth/token/revoke")
async def revoke_tokens(body: TokenRevokeBody, user=Depends(get_current_user_any)):
    """내 토큰을 폐기 목록에 올립니다 (JWT 로그아웃).

    예전에는 인증이 없어서, 유효한 토큰 문자열 하나만 있으면 **누구나** 부를 수 있었습니다.
    폐기 목록 키가 전 사용자 공통이던 결함과 겹쳐, 호출 한 번으로 서비스 전체의 JWT 를
    최대 7일간 막을 수 있었습니다.

    이제 두 가지를 함께 요구합니다 (RFC 7009 §2.1 이 폐기 요청에 요구하는 바와 같습니다):

    1. **호출자 인증** — Bearer 토큰이나 세션 쿠키로 자신을 밝혀야 합니다.
    2. **소유 확인** — 제출한 토큰의 주인이 호출자 자신이어야 합니다.

    액세스 토큰이 이미 만료된 채로 로그아웃하는 흐름을 살리려고, 제출된 토큰은
    ``verify_exp=False`` 로 읽습니다. 서명은 그대로 검증하므로 위조는 통하지 않습니다.
    """
    caller_id = str(user.get("id") or user.get("sub") or "")
    revoked = 0

    def _assert_mine(payload: dict) -> None:
        owner = str(payload.get("id") or payload.get("sub") or "")
        if not owner or owner != caller_id:
            # 남의 토큰인지 알려 주지 않으려고 존재 여부를 흐린다.
            raise HTTPException(403, "내 토큰만 폐기할 수 있습니다.")

    for token in (body.access_token, body.refresh_token):
        if not token:
            continue
        # 폐기하기 **전에** 주인을 확인한다. revoke_token 이 다시 디코드하지만,
        # 순서를 지키려면 여기서 한 번 읽는 편이 분명하다.
        _assert_mine(decode_token(token, verify_exp=False))
        await revoke_token(token)
        revoked += 1

    # 오프라인 표시는 **호출자 자신**에게만 한다 (예전에는 본문 토큰의 id 를 썼다).
    await mark_offline(caller_id)
    return {"ok": True, "revoked": revoked}


# ── 공용 엔드포인트 ────────────────────────────────────────────────────────────

@router.get("/me")
async def me(user=Depends(get_current_user_any)):
    """현재 사용자 정보를 반환합니다 (쿠키 or Bearer 모두 허용)."""
    from app.lib.user_state import get_user_state
    state = await get_user_state(user["id"])
    return {
        "user": {
            "name": user["name"],
            "email": user["email"],
            "clientId": user.get("client_id", ""),
            "roles": user.get("roles", ["user"]),
        },
        "state": {
            "online": state.get("online", False),
            "last_seen": state.get("last_seen"),
            "active_conversation_id": state.get("active_conversation_id"),
        },
    }


@router.get("/sessions")
async def list_sessions(user=Depends(get_current_user_any)):
    """내 활성 세션 목록을 반환합니다."""
    sids = await list_user_sessions(user["id"])
    return {"sessions": sids, "count": len(sids)}


@router.delete("/sessions/{sid}")
async def revoke_session(
    sid: str,
    user=Depends(get_current_user_any),
):
    """특정 세션을 강제 만료시킵니다."""
    session = await get_session(sid)
    if not session or session.get("id") != user["id"]:
        raise HTTPException(404, "세션을 찾을 수 없습니다.")
    await delete_session(sid)
    return {"ok": True}


@router.delete("/sessions")
async def revoke_all_sessions(user=Depends(require_roles("admin", "user"))):
    """내 모든 세션을 일괄 만료시킵니다 (전체 로그아웃)."""
    count = await delete_all_user_sessions(user["id"])
    await clear_user_state(user["id"])
    return {"ok": True, "revoked": count}
