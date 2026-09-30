"""계정 서비스 — 이메일 정규화 · 비밀번호 규칙과 확인 · 이름 규칙 · 탈퇴 때 사용자 데이터 파기.

왜 따로 두나
------------
가입 · 로그인 · 토큰 발급 · 회원 정보 수정 · 비밀번호 변경 · 탈퇴가 모두 **같은 규칙**(이메일을 어떤 모양으로
맞추나 · 비밀번호를 어떻게 검사하나)을 써야 한다. 라우트마다 따로 적으면 한 곳만 고쳐 어긋난다 — 실제로
가입은 이메일 도메인을 소문자로 바꿔 저장하고 로그인은 친 글자 그대로 비교해서, 대문자가 섞인 이메일로
가입하면 **가입한 그대로 쳐도 로그인이 안 됐다**. 이 모듈이 그 규칙이 사는 한 곳이다.

규칙과 근거 (2026-09-30 조사 · 확실도는 문서 「기능별 동작 원리서」 2절)
- **이메일(로그인 ID)** — 앞뒤 공백을 떼고 **전부 소문자**로 저장 · 비교한다. 메일 표준(RFC 5321 2.4)은
  @ 앞부분을 대소문자 구분으로 두지만 "그 구분에 기대는 것은 상호 운용을 해쳐 권하지 않는다" 고 적고,
  실제 메일 서비스도 구분하지 않는다. 옛 행(대소문자가 섞여 저장된 것)도 찾도록 비교는 `lower(email)` 로 한다.
- **비밀번호** — NIST SP 800-63B-4(2025-08) 3.1.1.2 를 따른다: 조합 규칙(대문자 · 특수문자 강제)을 두지 않고
  길이 · 흔한 비밀번호 차단 · 최대 길이(64자 이상 허용) · 자르지 않기 · 유니코드 NFC 정규화.
  최소 길이는 설정 `PASSWORD_MIN_LENGTH`(기본 8 — 가입 화면의 기존 규칙). NIST 는 다중 인증이 없는
  비밀번호에 15자 이상을 요구하고 OWASP 도 15자 미만을 약하다고 본다 — 올릴지는 팀 결정이라 설정으로 뺐다.
- **bcrypt 72바이트** — bcrypt 는 앞 72바이트만 쓴다. 5.0 부터는 넘으면 잘라 주지 않고 예외(ValueError)를
  내서, 긴 비밀번호로 가입 · 로그인하면 서버 오류(500)가 났다. 그래서 **72바이트를 넘는 비밀번호는 받지 않는다**
  (영문 72자 · 한글 24자). 글자 수 상한 64자와 함께 먼저 걸리는 쪽이 적용된다.
- **재인증** — 비밀번호 변경 · 탈퇴는 현재 비밀번호를 다시 받는다(OWASP 인증 치트시트: 민감한 정보를 바꾸기
  전에 현재 자격 증명을 요구).
- **탈퇴** — 개인정보 보호법 제21조(목적을 이룬 개인정보는 지체 없이 파기) · 제38조 제4항(삭제 요구 절차는
  수집 절차보다 어렵지 않게). 마이페이지에서 비밀번호와 확인 문구만으로 바로 지운다. 사용자 행을 가리키는
  표의 행을 **한 트랜잭션**에서 지우고, 감사 기록만 사용자 칸을 비워 남긴다(`delete_user_data`).

이 모듈은 DB 세션(`AsyncSession`)만 받고 Redis(세션 · 토큰)는 만지지 않는다 — 세션을 끊는 일은 라우트가
`app/lib/session.py` · `app/lib/jwt_auth.py` 로 한다. 그래서 DB 쪽 규칙을 Redis 없이 시험할 수 있다.
"""
from __future__ import annotations

import logging
import unicodedata
import uuid

import bcrypt
from email_validator import EmailNotValidError, validate_email
from sqlalchemy import Column, Table, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

logger = logging.getLogger(__name__)

#: bcrypt 가 실제로 보는 길이(바이트). 넘는 입력은 5.0 부터 예외가 난다.
BCRYPT_MAX_BYTES = 72
#: 글자 수 상한. NIST 는 「최소 64자까지는 허용」 을 권한다 — 64 로 두면 영문 긴 암호문도 들어간다.
PASSWORD_MAX_CHARS = 64
#: 화면 표시 이름 상한. DB 칸은 200자지만, 머리글 · 목록에 들어가는 이름이라 50자로 묶는다.
NAME_MAX_CHARS = 50
#: 탈퇴 확인 문구 — 버튼 한 번으로 지워지지 않게, 화면과 API 가 같은 문구를 요구한다.
CONFIRM_DELETE_PHRASE = "탈퇴"
#: 탈퇴해도 행을 지우지 않고 사용자 칸만 비우는 표 — 「누가」 는 지우고 「무슨 일이 있었나」 는 남긴다.
DEIDENTIFY_TABLES = frozenset({"audit_events"})

#: 흔한 비밀번호 — NIST 가 요구하는 「흔하거나 예상 가능하거나 유출된 비밀번호 목록」 의 최소판.
#: 공개 유출 목록(수천만 건)을 통째로 넣는 대신, 8자 이상이면서 가장 자주 쓰이는 것만 둔다.
#: 대소문자를 가리지 않고 비교한다.
COMMON_PASSWORDS = frozenset({
    "password", "password1", "password12", "password123", "passw0rd", "p@ssw0rd", "p@ssword",
    "12345678", "123456789", "1234567890", "0123456789", "87654321", "11111111", "00000000",
    "12341234", "11223344", "12121212", "123123123", "1q2w3e4r", "1q2w3e4r!", "1q2w3e4r5t",
    "q1w2e3r4", "qwer1234", "qwer1234!", "asdf1234", "zxcv1234", "qwerty12", "qwerty123",
    "qwertyuiop", "asdfghjk", "zxcvbnm1", "1qaz2wsx", "abcd1234", "abc12345", "a1234567",
    "aa123456", "test1234", "admin1234", "iloveyou", "sunshine", "princess", "football",
    "baseball", "superman", "trustno1", "letmein1", "welcome1", "dragon12", "monkey12",
})


class AccountError(ValueError):
    """사용자에게 그대로 보여 줄 수 있는 입력 오류. 라우트가 422 로 바꾼다."""


# ── 이메일 · 이름 ──────────────────────────────────────────────────────────────

def normalize_email(raw: str | None) -> str:
    """가입 · 수정용 — 형식을 검사하고 저장할 모양(앞뒤 공백 없음 · 전부 소문자)으로 돌려준다.

    형식 검사는 email-validator(pydantic 의 EmailStr 이 쓰는 것과 같은 패키지)로 하되, 도메인이 실제로
    메일을 받는지(DNS)는 보지 않는다 — 로컬 · 시험 환경에서도 같게 돌아야 해서다.
    """
    s = (raw or "").strip()
    if not s:
        raise AccountError("이메일을 입력하세요.")
    try:
        info = validate_email(s, check_deliverability=False)
    except EmailNotValidError:
        raise AccountError("이메일 형식이 올바르지 않습니다. 예) you@example.com") from None
    return info.normalized.lower()


def login_key(raw: str | None) -> str:
    """로그인 · 토큰 발급용 — 형식 검사 없이 비교할 모양만 맞춘다(틀린 형식은 어차피 찾지 못한다)."""
    return (raw or "").strip().lower()


def validate_name(raw: str | None) -> str:
    """표시 이름 — 앞뒤 공백을 떼고 겹친 공백을 하나로. 비었거나 너무 길면 AccountError."""
    s = " ".join((raw or "").split())
    if not s:
        raise AccountError("이름을 입력하세요.")
    if len(s) > NAME_MAX_CHARS:
        raise AccountError(f"이름은 {NAME_MAX_CHARS}자 이하로 입력하세요.")
    return s


def admin_emails() -> set[str]:
    """관리자 이메일 목록(설정 `ADMIN_EMAILS`)을 소문자로 — 가입 때 역할을 정할 때 쓴다."""
    return {e.lower() for e in settings.admin_email_list}


# ── 비밀번호 ───────────────────────────────────────────────────────────────────

def _nfc(pw: str) -> str:
    """유니코드 NFC 정규화 — 같은 한글이라도 입력기에 따라 조합형(NFD)으로 올 수 있어, 한 모양으로 맞춰 해시한다."""
    return unicodedata.normalize("NFC", pw)


def min_password_length() -> int:
    return max(1, int(getattr(settings, "PASSWORD_MIN_LENGTH", 8) or 8))


def password_policy() -> dict:
    """화면이 규칙을 안내하고 같은 값으로 입력 칸을 막도록, 서버가 규칙을 내려준다(규칙이 한 곳에만 있게)."""
    n = min_password_length()
    return {
        "min_length": n,
        "max_length": PASSWORD_MAX_CHARS,
        "max_bytes": BCRYPT_MAX_BYTES,
        "rules": [
            f"{n}자 이상 · {PASSWORD_MAX_CHARS}자 이하",
            f"{BCRYPT_MAX_BYTES}바이트 이하 — 한글은 한 글자가 3바이트라 24자까지",
            "대문자 · 특수문자를 꼭 섞을 필요는 없다 — 길고 외우기 쉬운 문장형을 권한다",
            "너무 흔한 비밀번호 · 같은 글자 반복 · 이메일과 같은 비밀번호는 쓸 수 없다",
        ],
    }


def check_new_password(pw: str | None, *, email: str | None = None, current: str | None = None) -> str:
    """새 비밀번호를 규칙으로 검사하고, 해시할 모양(NFC)으로 돌려준다. 어기면 AccountError.

    기존 계정의 로그인에는 쓰지 않는다 — 규칙은 **새로 정할 때만** 적용한다(예전 규칙으로 만든 비밀번호로도
    로그인은 된다). NIST 가 금하는 「주기적 변경 강제」 도 하지 않는다.
    """
    if not isinstance(pw, str) or pw == "":
        raise AccountError("비밀번호를 입력하세요.")
    p = _nfc(pw)
    n = min_password_length()
    if len(p) < n:
        raise AccountError(f"비밀번호는 {n}자 이상이어야 합니다.")
    if len(p) > PASSWORD_MAX_CHARS:
        raise AccountError(f"비밀번호는 {PASSWORD_MAX_CHARS}자 이하여야 합니다.")
    if len(p.encode("utf-8")) > BCRYPT_MAX_BYTES:
        raise AccountError(f"비밀번호가 너무 깁니다 — {BCRYPT_MAX_BYTES}바이트(영문 72자 · 한글 24자) 이하로 입력하세요.")
    low = p.lower()
    if low in COMMON_PASSWORDS:
        raise AccountError("너무 흔한 비밀번호입니다 — 다른 비밀번호를 쓰세요.")
    if len(set(p)) == 1:
        raise AccountError("같은 글자만 반복한 비밀번호는 쓸 수 없습니다.")
    if email:
        e = email.lower()
        local = e.split("@", 1)[0]
        if low == e or (len(local) >= 4 and low == local):
            raise AccountError("이메일(또는 @ 앞부분)과 같은 비밀번호는 쓸 수 없습니다.")
    if current is not None and _nfc(current) == p:
        raise AccountError("새 비밀번호가 지금 비밀번호와 같습니다.")
    return p


def hash_password(pw_nfc: str) -> str:
    """`check_new_password` 를 통과한 비밀번호를 bcrypt 로 해시한다(평문은 어디에도 저장하지 않는다)."""
    return bcrypt.hashpw(pw_nfc.encode("utf-8"), bcrypt.gensalt()).decode()


_DUMMY_HASH: bytes | None = None


def _dummy_hash() -> bytes:
    """없는 계정의 로그인도 비밀번호 확인과 비슷한 시간이 걸리게 하는 가짜 해시(처음 한 번만 만든다)."""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = bcrypt.hashpw(b"qurious-dummy-password", bcrypt.gensalt())
    return _DUMMY_HASH


def verify_password(raw: str | None, hashed: str | None) -> bool:
    """로그인 · 재인증 비밀번호 확인. **예외를 내지 않는다** — 틀리면 False.

    - 계정이 없으면(`hashed` 없음) 가짜 해시로 한 번 확인한다. 없는 계정은 바로 돌려보내면 응답 시간 차이로
      「이 이메일은 가입돼 있다」 가 새어 나간다.
    - 72바이트를 넘는 입력은 bcrypt 5.0 이 예외를 낸다. 그런 비밀번호는 저장된 적이 없으므로 곧바로 False.
    - NFC 로 먼저 비교하고, NFC 가 아닌 모양으로 해시된 옛 가입에 대비해 원래 모양도 한 번 본다.
    """
    if not isinstance(raw, str) or raw == "":
        return False
    if not hashed:
        try:
            bcrypt.checkpw(b"x", _dummy_hash())
        except ValueError:
            pass
        return False
    for cand in dict.fromkeys((_nfc(raw), raw)):      # 순서를 지키고, 둘이 같으면 한 번만
        b = cand.encode("utf-8")
        if len(b) > BCRYPT_MAX_BYTES:
            continue
        try:
            if bcrypt.checkpw(b, hashed.encode("utf-8")):
                return True
        except ValueError:                             # 해시 문자열이 망가진 행 — 로그인 실패로 다룬다
            return False
    return False


# ── 사용자 찾기 ────────────────────────────────────────────────────────────────

async def find_user_by_email(db: AsyncSession, email: str | None):
    """이메일로 사용자를 찾는다 — 대소문자를 가리지 않는다.

    `lower(email)` 로 비교하므로, 이 규칙이 생기기 전에 대소문자가 섞여 저장된 옛 행도 찾는다.
    대소문자만 다른 옛 행이 둘 이상이면(규칙 전에는 둘 다 가입될 수 있었다) 글자까지 같은 행 → 먼저 가입한 행
    순으로 고르고 로그를 남긴다.
    """
    from app.models import User

    key = login_key(email)
    if not key:
        return None
    rows = (await db.execute(
        select(User).where(func.lower(User.email) == key).order_by(User.created_at)
    )).scalars().all()
    if not rows:
        return None
    if len(rows) > 1:
        logger.warning("대소문자만 다른 계정이 %d개 — %s (먼저 가입한 계정으로 로그인)", len(rows), key)
    exact = [u for u in rows if u.email == key]
    return exact[0] if exact else rows[0]


async def email_taken(db: AsyncSession, email_normalized: str) -> bool:
    """대소문자를 가리지 않고 이미 쓰는 이메일인가 — 가입 전 확인(DB 의 소문자 유일 색인이 한 번 더 막는다)."""
    from app.models import User

    n = (await db.execute(
        select(func.count()).select_from(User).where(func.lower(User.email) == email_normalized)
    )).scalar_one()
    return n > 0


# ── 탈퇴 — 사용자 데이터 파기 ───────────────────────────────────────────────────

def user_owned_columns() -> list[tuple[Table, Column]]:
    """사용자 행(`users.id`)을 가리키는 모든 (표, 칸) — **모델 메타데이터에서 읽는다.**

    표 이름을 손으로 적지 않는 이유: 표가 새로 생길 때마다 이 목록을 고치는 것을 잊으면, 탈퇴한 사람의
    데이터가 그 표에 남는다(또는 외래 키 때문에 탈퇴가 실패한다). 2026-09-30 기준 25개.
    자식 표가 부모 표보다 먼저 오게 `sorted_tables` 의 역순으로 둔다.
    """
    import app.models  # noqa: F401 — 모든 모델을 메타데이터에 올린다
    from app.models.base import Base

    out: list[tuple[Table, Column]] = []
    for table in reversed(Base.metadata.sorted_tables):
        for fk in table.foreign_keys:
            if fk.column.table.name == "users":
                out.append((table, fk.parent))
    return out


async def delete_user_data(db: AsyncSession, user_id: uuid.UUID) -> dict[str, int]:
    """한 사용자의 데이터를 모두 지우고 사용자 행까지 지운다. 표별로 바뀐 행 수를 돌려준다.

    커밋은 호출자(라우트)가 한다 — 한 트랜잭션이라 중간에 실패하면 아무것도 지워지지 않는다.
    - 감사 기록(`audit_events`)은 지우지 않고 사용자 칸만 비운다 — 누가 했는지는 남기지 않되, 무슨 일이
      있었는지(주문 · 설정 변경 수)는 서비스 기록으로 남긴다.
    - 대화 메시지 · 수식 지표의 판과 결과 · 체결 내역처럼 손자 표는 부모 표의 `ON DELETE CASCADE` 로 따라 지워진다.
    - 자동매매 사이클 기록은 표가 아니라 캐시 표(`data_cache`)에 사용자 ID 를 키로 들어 있어 따로 지운다.
    """
    from app.models import DataCache, User

    counts: dict[str, int] = {}
    for table, col in user_owned_columns():
        if table.name in DEIDENTIFY_TABLES and col.nullable:
            res = await db.execute(update(table).where(col == user_id).values({col.name: None}))
            key = f"{table.name}(사용자 칸 비움)"
        else:
            res = await db.execute(delete(table).where(col == user_id))
            key = table.name
        if res.rowcount:
            counts[key] = counts.get(key, 0) + int(res.rowcount)
    res = await db.execute(delete(DataCache).where(DataCache.key == f"quant:cycle_log:{user_id}"))
    if res.rowcount:
        counts["data_cache"] = int(res.rowcount)
    res = await db.execute(delete(User).where(User.id == user_id))
    counts["users"] = int(res.rowcount or 0)
    return counts
