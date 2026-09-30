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

계정 관리 (마이페이지 · 2026-09-30 추가 — 규칙은 app/services/account.py):
  GET    /api/auth/password-policy – 비밀번호 규칙 (가입 · 마이페이지 화면이 안내에 쓴다)
  PATCH  /api/me                   – 이름 바꾸기
  PUT    /api/me/password          – 비밀번호 바꾸기 (현재 비밀번호 확인 · 다른 기기 로그아웃)
  DELETE /api/me                   – 회원 탈퇴 (비밀번호 · 확인 문구 · 데이터 파기)
"""
import uuid

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel
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
    revoke_all_tokens_for,
    revoke_token,
)
from app.lib.redis_cache import session_cache
from app.lib.session import (
    create_session,
    delete_all_user_sessions,
    delete_session,
    get_current_user,
    get_session,
    list_user_sessions,
)
from app.lib.user_state import clear_user_state, mark_offline, mark_online
from app.services import account
from app.services.audit import audit

router = APIRouter(prefix="/api")


# ── 요청/응답 스키마 ───────────────────────────────────────────────────────────

class RegisterBody(BaseModel):
    # 이메일 형식 검사는 account.normalize_email 이 한다 — EmailStr 의 422 는 오류가 목록 모양이라
    # 화면에 「[object Object]」 로 보였고, 도메인만 소문자로 바꿔 로그인과 어긋났다.
    name: str
    email: str
    password: str


class LoginBody(BaseModel):
    email: str
    password: str


class TokenRefreshBody(BaseModel):
    refresh_token: str


class TokenRevokeBody(BaseModel):
    access_token: str
    refresh_token: str | None = None


class ProfileUpdateBody(BaseModel):
    name: str


class PasswordChangeBody(BaseModel):
    current_password: str
    new_password: str


class AccountDeleteBody(BaseModel):
    password: str
    confirm: str = ""


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
    # 대소문자를 가리지 않는다 — 규칙과 이유는 account.find_user_by_email
    try:
        return await account.find_user_by_email(db, email)
    except Exception as e:
        raise HTTPException(503, f"데이터베이스 오류: {e}")


def _set_session_cookie(response: Response, sid: str) -> None:
    response.set_cookie(
        "fin_session", sid,
        httponly=True, samesite=settings.COOKIE_SAMESITE,
        secure=settings.COOKIE_SECURE, max_age=settings.SESSION_TTL,
    )


async def _load_user(db, user: dict) -> User:
    """세션 · 토큰의 사용자 ID 로 DB 행을 읽는다. 행이 없으면(탈퇴 등) 401."""
    try:
        uid = uuid.UUID(str(user.get("id") or user.get("sub") or ""))
    except ValueError:
        raise HTTPException(401, "로그인이 필요합니다.")
    row = await db.get(User, uid)
    if row is None:
        raise HTTPException(401, "계정을 찾을 수 없습니다 — 다시 로그인하세요.")
    return row


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

    # 입력 규칙(이메일은 소문자 · 이름 · 비밀번호 규칙)은 account 가 한 곳에서 본다 — 어기면 한국어 한 줄로 422.
    try:
        email = account.normalize_email(body.email)
        name = account.validate_name(body.name)
        password = account.check_new_password(body.password, email=email)
    except account.AccountError as exc:
        raise HTTPException(422, str(exc))
    pw_hash = account.hash_password(password)
    client_id = str(uuid.uuid4()).replace("-", "")[:16].upper()
    roles = ["admin"] if email in account.admin_emails() else ["user"]

    async with session_factory() as db:
        # 대소문자만 다른 옛 계정도 「이미 사용 중」 으로 본다(DB 의 소문자 유일 색인이 한 번 더 막는다).
        if await account.email_taken(db, email):
            raise HTTPException(400, "이미 사용 중인 이메일입니다.")
        user = User(
            name=name, email=email, password_hash=pw_hash,
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
        "name": name, "email": email, "client_id": client_id, "roles": roles,
    })
    sid = await create_session(session_data)
    await mark_online(user_id)

    _set_session_cookie(response, sid)
    return {"ok": True, "user": {"name": name, "email": email,
                                  "clientId": client_id, "roles": roles}}


@router.post("/auth/login")
async def login(body: LoginBody, response: Response):
    try:
        session_factory = get_session_factory()
    except RuntimeError:
        raise HTTPException(503, "인증 서버(PostgreSQL)에 연결할 수 없습니다.")

    async with session_factory() as db:
        user = await _find_user_by_email(db, body.email)
        # verify_password 는 예외를 내지 않는다(긴 비밀번호 500 방지) · 없는 계정도 비슷한 시간이 걸린다.
        if not account.verify_password(body.password, user.password_hash if user else None):
            raise HTTPException(401, "이메일 또는 비밀번호가 올바르지 않습니다.")
        user_id = str(user.id)
        user_dict = _user_to_dict(user)

    session_data = _build_session_data(user_id, user_dict)
    sid = await create_session(session_data)
    await mark_online(user_id)

    _set_session_cookie(response, sid)
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
        if not account.verify_password(body.password, user.password_hash if user else None):
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
    """현재 사용자 정보를 반환합니다 (쿠키 or Bearer 모두 허용).

    이름 · 이메일 · 역할은 세션에 복사해 둔 값이 아니라 **DB 의 지금 값**을 준다 — 마이페이지에서 이름을
    바꾸거나 관리자가 역할을 바꾸면 곧바로 보여야 해서다. 탈퇴한 계정의 남은 쿠키 · 토큰은 여기서 401.
    """
    from app.lib.user_state import get_user_state
    async with get_session_factory()() as db:
        row = await _load_user(db, user)
    state = await get_user_state(user["id"])
    return {
        "user": {
            "name": row.name,
            "email": row.email,
            "clientId": row.client_id,
            "roles": list(row.roles),
            "createdAt": row.created_at.isoformat() if row.created_at else None,
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


# ── 계정 관리 (마이페이지) ──────────────────────────────────────────────────────
# 규칙 · 근거는 app/services/account.py 머리말. 여기서는 순서만 지킨다:
#   입력 검사 → 재인증(현재 비밀번호) → DB 변경 커밋 → 세션 · 토큰 정리 → 감사 기록.
# DB 를 먼저 커밋하는 이유: 세션을 먼저 지웠는데 DB 가 실패하면 「로그아웃만 되고 아무것도 안 바뀐」 상태가 된다.

@router.get("/auth/password-policy")
async def password_policy():
    """비밀번호 규칙 — 가입 · 마이페이지 화면이 같은 값으로 안내 · 입력 칸 제한을 건다(로그인 전에도 연다)."""
    return account.password_policy()


@router.patch("/me")
async def update_me(body: ProfileUpdateBody, user=Depends(get_current_user_any)):
    """이름 바꾸기. 이메일(로그인 ID)은 바꾸지 않는다 — 바꾸려면 새 주소로 확인 메일을 보내야 하는데
    (현업 관행) 메일 발송 기능이 아직 없다."""
    try:
        name = account.validate_name(body.name)
    except account.AccountError as exc:
        raise HTTPException(422, str(exc))
    async with get_session_factory()() as db:
        row = await _load_user(db, user)
        row.name = name
        await db.commit()
    # 세션에 복사해 둔 이름도 바꾼다(남은 만료 시간은 그대로) — 세션의 이름을 쓰는 화면 · 기록이 옛 이름을 보이지 않게.
    for sid in await list_user_sessions(str(row.id)):
        data = await get_session(sid)
        if data:
            data["name"] = name
            ttl = await session_cache.ttl(sid)
            await session_cache.set(sid, data, ttl=ttl if ttl and ttl > 0 else settings.SESSION_TTL)
    await audit(str(row.id), row.client_id, "account.profile_updated", {"fields": ["name"]})
    return {"ok": True, "user": {"name": name, "email": row.email}}


@router.put("/me/password")
async def change_password(
    body: PasswordChangeBody,
    response: Response,
    user=Depends(get_current_user_any),
    fin_session: str | None = Cookie(default=None),
):
    """비밀번호 바꾸기 — 현재 비밀번호를 다시 확인하고, 바꾼 뒤에는 **다른 기기를 모두 로그아웃**시킨다.

    OWASP: 민감한 정보를 바꾸기 전에 현재 자격 증명을 요구 · 권한과 관련된 변화 뒤에는 세션 ID 를 새로 발급.
    그래서 지금 기기도 세션을 새로 받는다(쿠키가 바뀐다). 앱 밖 프로그램의 토큰은 전부 끊긴다.
    """
    async with get_session_factory()() as db:
        row = await _load_user(db, user)
        if not account.verify_password(body.current_password, row.password_hash):
            raise HTTPException(400, "현재 비밀번호가 올바르지 않습니다.")
        try:
            new_pw = account.check_new_password(body.new_password, email=row.email, current=body.current_password)
        except account.AccountError as exc:
            raise HTTPException(422, str(exc))
        row.password_hash = account.hash_password(new_pw)
        await db.commit()
        uid, user_dict = str(row.id), _user_to_dict(row)
    revoked = await delete_all_user_sessions(uid)
    await revoke_all_tokens_for(uid)
    if fin_session:
        # 이 요청이 쿠키로 왔으면 이 기기는 로그인을 유지한다 — 새 세션 ID 로.
        _set_session_cookie(response, await create_session(_build_session_data(uid, user_dict)))
        revoked = max(0, revoked - 1)
    await audit(uid, user_dict.get("client_id", ""), "account.password_changed", {"other_sessions_revoked": revoked})
    return {"ok": True, "other_sessions_revoked": revoked}


@router.delete("/me")
async def delete_me(body: AccountDeleteBody, response: Response, user=Depends(get_current_user_any)):
    """회원 탈퇴 — 현재 비밀번호와 확인 문구를 받고, 내 데이터를 **즉시 파기**한 뒤 모든 세션 · 토큰을 끊는다.

    지우는 범위는 사용자 행을 가리키는 모든 표(account.delete_user_data · 모델 메타데이터에서 찾는다).
    되돌릴 수 없어 화면과 API 가 같은 확인 문구(account.CONFIRM_DELETE_PHRASE)를 요구한다.
    """
    if (body.confirm or "").strip() != account.CONFIRM_DELETE_PHRASE:
        raise HTTPException(422, f"확인 문구로 「{account.CONFIRM_DELETE_PHRASE}」 를 입력하세요.")
    async with get_session_factory()() as db:
        row = await _load_user(db, user)
        if not account.verify_password(body.password, row.password_hash):
            raise HTTPException(400, "비밀번호가 올바르지 않습니다.")
        uid = row.id
        counts = await account.delete_user_data(db, uid)
        await db.commit()
    await delete_all_user_sessions(str(uid))
    await clear_user_state(str(uid))
    await revoke_all_tokens_for(str(uid))
    response.delete_cookie("fin_session")
    # 감사 기록에는 누구였는지 남기지 않는다(사용자 칸 비움) — 몇 개 표에서 무엇을 지웠는지만.
    await audit("", "", "account.deleted", {"deleted": counts})
    return {"ok": True, "deleted": counts}
