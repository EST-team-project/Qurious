"""인증 라우터.

세션 쿠키 방식(기존)과 JWT Bearer 방식(신규)을 모두 지원합니다.

쿠키 방식 (브라우저):
  POST /api/auth/register  – 회원가입 + 세션 쿠키 발급
  POST /api/auth/login     – 로그인 + 세션 쿠키 발급
  POST /api/auth/logout    – 로그아웃 + 쿠키 삭제 (세션이 이미 만료돼 있어도 쿠키는 지운다)
  세션은 슬라이딩 만료: 인증된 요청이 있을 때마다 서버 TTL 과 브라우저 쿠키 만료가 함께 연장된다
  (app/lib/session.py 의 touch_session + SessionCookieRefreshMiddleware).

JWT 방식 (API 클라이언트 / 모바일):
  POST /api/auth/token         – 로그인 → access_token + refresh_token 반환
  POST /api/auth/token/refresh – refresh_token → 새 access_token + 새 refresh_token 발급(슬라이딩)
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
import logging
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
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
    COOKIE_NAME,
    clear_session_cookie,
    create_session,
    delete_all_user_sessions,
    delete_session,
    get_session,
    list_user_sessions,
    mark_cookie_refresh,
    set_session_cookie,
)
from app.lib.user_state import clear_user_state, mark_offline, mark_online
from app.services import account, login_guard
from app.services.audit import audit

router = APIRouter(prefix="/api")


# ── 요청/응답 스키마 ───────────────────────────────────────────────────────────

class RegisterBody(BaseModel):
    # 이메일 형식 검사는 account.normalize_email 이 한다 — EmailStr 의 422 는 오류가 목록 모양이라
    # 화면에 「[object Object]」 로 보였고, 도메인만 소문자로 바꿔 로그인과 어긋났다.
    name: str
    email: str
    password: str
    # 약관 · 개인정보 동의(2026-10-29 · 가입 화면 public/register.html · 문구는 public/js/terms.js).
    # 강제다(2026-10-29 S162 — 이전에는 선택이라 화면을 거치지 않는 직접 호출은 동의 없이 가입됐다).
    # 서버가 동의한 판과 항목을 감사 기록(audit_events)에 남겨(나중에 입증) 필수 항목이 빠졌으면 422.
    terms_version: str | None = None
    agreed: list[str] | None = None
    # 생년월일("YYYY-MM-DD") — 만 14세 이상인지 서버가 계산하는 데만 쓴다(S162 · 개인정보 보호법 제22조의2).
    # **저장하지도, 기록하지도, 오류 메시지에 되돌리지도 않는다** — 약관·처리방침이 그렇게 약속한다(시험 TC-TM-10).
    birth_date: str | None = None


#: 서버가 아는 현재 약관 판 — public/js/terms.js 의 TERMS_VERSION 과 같아야 한다(시험 TC-TM-01 이 지킨다).
#: 다르면 가입을 거절한다: 오래된 화면이 옛 문구에 동의한 채 새 판 동의로 기록되는 일을 막는다.
TERMS_VERSION = "2026-10-29-v0.2"

#: 가입할 수 있는 최소 만 나이(개인정보 보호법 제22조의2 — 만 14세 미만은 법정대리인 동의가 필요한데 그 절차를 두지 않았다).
MIN_SIGNUP_AGE = 14

_KST = timezone(timedelta(hours=9))


def _check_age(birth_date: str | None, today: date | None = None) -> None:
    """만 14세 이상인지 계산한다. 아니면 422. 생년월일은 여기서만 읽고 어디에도 남기지 않는다."""
    today = today or datetime.now(_KST).date()
    try:
        born = date.fromisoformat((birth_date or "").strip())
    except ValueError:
        raise HTTPException(422, "생년월일을 확인해 주세요. (예: 2000-01-31)")
    if born > today or born.year < today.year - 120:
        raise HTTPException(422, "생년월일을 확인해 주세요.")
    # 만 나이 — 올해 생일이 아직 안 지났으면 한 살 덜 센다(2월 29일생은 평년에 2월 28일 다음 날인 3월 1일에 한 살을 더한다)
    try:
        birthday = born.replace(year=born.year + MIN_SIGNUP_AGE)
    except ValueError:
        birthday = date(born.year + MIN_SIGNUP_AGE, 3, 1)
    if birthday > today:
        raise HTTPException(422, f"만 {MIN_SIGNUP_AGE}세 미만은 가입할 수 없습니다.")


#: 가입 때 모두 동의해야 하는 항목 — public/js/terms.js 의 TERMS id 와 같아야 한다(시험 TC-TM 이 지킨다).
REQUIRED_AGREEMENTS = ("service", "privacy", "invest")

#: 가입 때 따로 묻는 선택 동의 항목. 지금은 **비어 있다** — 앱이 실제로 하는 일 가운데 가입 때 선택으로 받아야 할
#: 수집·이용(광고성 정보 전송 등)이 아직 없기 때문이다(약관에는 앱이 하지 않는 일을 쓰지 않는다 · 시험 TC-TM-03).
#: 항목을 더하면 필수와 섞이지 않게 여기에만 넣는다 — 안 동의해도 가입은 된다(개인정보 보호법 제16조 제3항).
OPTIONAL_AGREEMENTS: tuple[str, ...] = ()


def _check_agreements(body: "RegisterBody") -> dict:
    """동의 항목을 검사해 감사 기록에 넣을 값을 돌려준다. 판 번호가 없거나 필수 항목이 빠졌으면 422.

    알려진 항목(필수 + 선택)만 인정하고 나머지 값은 버린다 — 서버가 모르는 항목을 기록에 남기지 않는다.
    """
    version = (body.terms_version or "").strip()
    if version and version != TERMS_VERSION:
        # 오래된 화면(캐시)이 옛 문구를 보여 줬을 수 있다 — 새로고침하면 새 문구를 보고 다시 동의한다
        raise HTTPException(422, "이용약관이 바뀌었습니다. 화면을 새로고침한 뒤 다시 동의해 주세요.")
    known = set(REQUIRED_AGREEMENTS) | set(OPTIONAL_AGREEMENTS)
    agreed = {a for a in (body.agreed or []) if isinstance(a, str) and a in known}
    if not version:
        raise HTTPException(422, "가입 화면에서 이용약관 · 개인정보 수집·이용 · 투자 유의사항에 동의해야 가입할 수 있습니다.")
    if [a for a in REQUIRED_AGREEMENTS if a not in agreed]:
        raise HTTPException(422, "이용약관 · 개인정보 수집·이용 · 투자 유의사항에 모두 동의해야 가입할 수 있습니다.")
    return {"version": version, "agreed": sorted(agreed),
            "optional": sorted(agreed & set(OPTIONAL_AGREEMENTS))}


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
    consent = _check_agreements(body)
    _check_age(body.birth_date)             # 생년월일은 이 줄에서 계산하고 버린다 — 이 아래로 넘기지 않는다
    consent["age_check"] = f"{MIN_SIGNUP_AGE}+"   # 감사 기록에는 「만 14세 이상 확인함」 만 남는다(날짜는 안 남김)
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

    # 이름 · 이메일은 싣지 않는다 — 판 번호와 항목만(탈퇴해도 남는 감사 기록이라 개인정보를 늘리지 않는다)
    await audit(user_id, client_id, "terms.agree", consent)

    session_data = _build_session_data(user_id, {
        "name": name, "email": email, "client_id": client_id, "roles": roles,
    })
    sid = await create_session(session_data)
    await mark_online(user_id)

    set_session_cookie(response, sid)
    return {"ok": True, "user": {"name": name, "email": email,
                                  "clientId": client_id, "roles": roles}}


async def _guard_check(email: str, request: Request) -> None:
    """비밀번호를 확인하기 **전에** — 많이 틀린 이메일 · 주소는 맞는 비밀번호여도 막는다(429 + Retry-After). 규칙은 login_guard."""
    try:
        await login_guard.check(email, login_guard.client_ip(request))
    except login_guard.LoginLocked as lock:
        raise HTTPException(429, lock.message(), headers={"Retry-After": str(lock.retry_after)}) from None


async def _guard_fail(email: str, request: Request) -> None:
    """틀렸다 — 횟수를 올리고 401(남은 횟수가 적으면 경고 한 줄)."""
    left = await login_guard.record_failure(email, login_guard.client_ip(request))
    raise HTTPException(401, login_guard.failure_message(left))


@router.post("/auth/login")
# request 는 맨 뒤 · 기본값 None — 시험들이 login(body, response) 로 직접 부른다(그때는 주소를 모르니 「unknown」 으로 센다)
async def login(body: LoginBody, response: Response, request: Request = None):
    try:
        session_factory = get_session_factory()
    except RuntimeError:
        raise HTTPException(503, "인증 서버(PostgreSQL)에 연결할 수 없습니다.")

    await _guard_check(body.email, request)
    async with session_factory() as db:
        user = await _find_user_by_email(db, body.email)
        # verify_password 는 예외를 내지 않는다(긴 비밀번호 500 방지) · 없는 계정도 비슷한 시간이 걸린다.
        if not account.verify_password(body.password, user.password_hash if user else None):
            await _guard_fail(body.email, request)
        user_id = str(user.id)
        user_dict = _user_to_dict(user)
    await login_guard.reset(body.email)

    session_data = _build_session_data(user_id, user_dict)
    sid = await create_session(session_data)
    await mark_online(user_id)

    set_session_cookie(response, sid)
    return {"ok": True, "user": {"name": user_dict["name"], "email": user_dict["email"],
                                  "clientId": user_dict["client_id"],
                                  "roles": user_dict["roles"]}}


@router.post("/auth/logout")
async def logout(
    response: Response,
    fin_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
):
    """세션을 삭제하고 쿠키를 지웁니다.

    세션이 이미 만료됐거나 Redis 에 없어도 401 을 내지 않고 쿠키만 정리합니다
    (만료된 쿠키가 브라우저에 남아 로그아웃이 실패하는 상황 방지).
    """
    if fin_session:
        session = await get_session(fin_session)
        if session:
            await delete_session(fin_session)
            await mark_offline(session["id"])
    clear_session_cookie(response)
    return {"ok": True}


# ── JWT 기반 인증 ──────────────────────────────────────────────────────────────

@router.post("/auth/token")
async def issue_token(body: LoginBody, request: Request = None):
    """JWT 액세스/리프레시 토큰을 발급합니다 (API 클라이언트용). /auth/login 과 같은 시도 횟수 제한을 쓴다(한쪽만 막으면 다른 쪽으로 돌아간다)."""
    try:
        session_factory = get_session_factory()
    except RuntimeError:
        raise HTTPException(503, "인증 서버(PostgreSQL)에 연결할 수 없습니다.")

    await _guard_check(body.email, request)
    async with session_factory() as db:
        user = await _find_user_by_email(db, body.email)
        if not account.verify_password(body.password, user.password_hash if user else None):
            await _guard_fail(body.email, request)
        user_id = str(user.id)
        user_dict = _user_to_dict(user)
    await login_guard.reset(body.email)

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

    # 슬라이딩 만료(강사님 기초 코드 289bfb5): 새 액세스 토큰과 함께 만료가 연장된 새 리프레시 토큰을 발급한다.
    # 활동 중인 클라이언트가 JWT_REFRESH_TTL(기본 7일) 마다 재로그인하지 않도록 하기 위함.
    # 기존 리프레시 토큰은 폐기하지 않고 원래 만료 시각까지 유효하다 (새 토큰을 저장하지 않는
    # 구형 클라이언트와의 호환). 즉시 무효화가 필요하면 /auth/token/revoke 를 호출한다.
    # ★ jti 를 빼고 넘긴다(우리 고침 · 2026-09-20) — 남기면 옛 리프레시의 jti 가 새 두 토큰에 복사되어,
    #   토큰 하나를 폐기할 때 나머지까지 함께 끊긴다. 새 토큰은 create_token_pair 가 jti 를 새로 만든다.
    _CARRY_OVER_EXCLUDE = ("type", "jti", "iat", "exp")
    user_payload = {k: v for k, v in payload.items() if k not in _CARRY_OVER_EXCLUDE}
    return create_token_pair(user_payload)


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
    request: Request,
    response: Response,
    user=Depends(get_current_user_any),
    fin_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
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
        new_sid = await create_session(_build_session_data(uid, user_dict))
        set_session_cookie(response, new_sid)
        # ★ 쿠키 재발급 미들웨어(SessionCookieRefreshMiddleware)에도 새 ID 를 알린다. 위의 인증 의존성이
        #   이 요청에서 「5분 지난 세션 연장」 을 했다면 옛 ID 의 재발급이 예약돼 있어, 응답 끝에 옛 쿠키가
        #   한 줄 더 붙는다 — 같은 이름의 쿠키는 뒤엣것이 이기므로, 방금 지운 옛 세션이 남아 이 기기도
        #   로그아웃된다(2026-10-02 강사님 289bfb5 반영 때 찾음 · DF-37).
        mark_cookie_refresh(request, new_sid)
        revoked = max(0, revoked - 1)
    await audit(uid, user_dict.get("client_id", ""), "account.password_changed", {"other_sessions_revoked": revoked})
    return {"ok": True, "other_sessions_revoked": revoked}


@router.delete("/me")
async def delete_me(body: AccountDeleteBody, request: Request, response: Response,
                    user=Depends(get_current_user_any)):
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
        # (DF-146 · 2026-10-23) 올린 문서가 있으면 벡터 조각부터 지운다 — 못 지우면 탈퇴를 멈추고 503(사용자 결정 10-23).
        # 「즉시 파기」 를 약속하므로 DB 만 지우고 조각을 남기지 않는다(예전엔 조각이 남아 남의 채팅에 계속 보였다).
        # 올린 문서가 없으면 벡터 DB 와 상관없이 탈퇴한다 — 문지기 모듈(LangChain · Qdrant)도 그때만 가져온다.
        keys = await account.uploaded_source_keys(db, uid)
        purged = 0
        if keys:
            from app.services import user_docs
            from app.services.rag_pipeline import VectorStoreError
            try:
                purged = await user_docs.delete_owner(str(uid), keys)
            except VectorStoreError as exc:
                logging.getLogger("qurious.auth").warning("탈퇴 — 올린 문서 조각 지우기 실패: %s", exc)
                raise HTTPException(503, "올린 문서를 지우지 못해 탈퇴를 멈췄습니다 — 잠시 뒤 다시 해 주세요. "
                                         "계정과 기록은 그대로 있습니다.") from exc
        counts = await account.delete_user_data(db, uid)
        if purged:
            counts["user_docs(벡터 조각)"] = purged
        await db.commit()
    await delete_all_user_sessions(str(uid))
    await clear_user_state(str(uid))
    await revoke_all_tokens_for(str(uid))
    # 쿠키를 지우고, 인증 의존성이 예약했을 수 있는 「옛 쿠키 재발급」 도 취소한다(위 change_password 의 ★ 참고 —
    # 취소하지 않으면 지운 쿠키 뒤에 30일짜리 죽은 쿠키가 다시 붙는다).
    mark_cookie_refresh(request, None)
    clear_session_cookie(response)
    # 감사 기록에는 누구였는지 남기지 않는다(사용자 칸 비움) — 몇 개 표에서 무엇을 지웠는지만.
    await audit("", "", "account.deleted", {"deleted": counts})
    return {"ok": True, "deleted": counts}
