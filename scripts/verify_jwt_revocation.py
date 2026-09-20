"""JWT 폐기(revocation)를 실제 Redis 로 검증한다.

고친 것이 정말 고쳐졌는지, 그리고 **예전 코드였다면 실패했을 것**인지를 같이 본다.
확인하는 것은 일곱 가지다.

  1. 두 사용자의 토큰이 **서로 다른 폐기 키**를 갖는다 (결함 1)
     — 예전 `token[:32]` 였다면 둘이 같았다
  2. A 가 로그아웃해도 **B 는 멀쩡하다** (결함 1 의 실제 증상)
  3. 액세스와 리프레시가 **다른 jti** 를 갖는다 (create_token_pair 함정)
  4. 리프레시로 새로 받은 액세스에 **옛 jti 가 묻어오지 않는다** (refresh 복사 함정)
  5. 서명부만 바꾼 변조본은 폐기 키를 **비켜 가지 못한다** (JWT malleability)
  6. `exp` 없는 토큰은 **거절된다** (python-jose 의 require_exp 기본값이 False)
  7. `JWT_SECRET` 이 자리표시자면 **발급이 막힌다**

쓰는 법 (임시 Redis 를 띄워 두고)
    docker run -d --name qurious-jwt-test -p 16380:6379 redis:7-alpine
    PYTHONPATH=. python scripts/verify_jwt_revocation.py
    docker stop qurious-jwt-test && docker rm qurious-jwt-test

Redis 주소는 환경변수 `JWT_TEST_REDIS_URL` 로 바꿀 수 있다.
"""
import asyncio
import base64
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 설정을 import 하기 **전에** 넣어야 pydantic Settings 가 읽는다.
os.environ.setdefault("REDIS_URL", os.getenv("JWT_TEST_REDIS_URL", "redis://localhost:16380"))
os.environ.setdefault("JWT_SECRET", "verify-script-secret-0123456789abcdef")

from fastapi import HTTPException  # noqa: E402
from jose import jwt  # noqa: E402

from app.config import settings  # noqa: E402
from app.lib import jwt_auth  # noqa: E402
from app.lib.redis_cache import connect_redis, close_redis  # noqa: E402

USER_A = {"sub": "user-a", "id": "user-a", "name": "가", "email": "a@x.kr", "roles": ["user"]}
USER_B = {"sub": "user-b", "id": "user-b", "name": "나", "email": "b@x.kr", "roles": ["user"]}

_ok = 0
_ng = 0


def check(label: str, passed: bool, note: str = "") -> None:
    global _ok, _ng
    mark = "🟢 통과" if passed else "🔴 실패"
    if passed:
        _ok += 1
    else:
        _ng += 1
    print(f"  {mark}  {label}" + (f"\n           {note}" if note else ""))


def claims_of(token: str) -> dict:
    """서명 검증 없이 클레임만 들여다본다 (검사용)."""
    part = token.split(".")[1]
    part += "=" * (-len(part) % 4)
    return json.loads(base64.urlsafe_b64decode(part))


async def main() -> None:
    await connect_redis()
    print(f"Redis: {settings.REDIS_URL}\n")

    # ── 1. 폐기 키가 토큰마다 다른가 ─────────────────────────────────────────
    print("[1] 폐기 키가 토큰마다 다른가 — 결함 1 의 핵심")
    ta = jwt_auth.create_access_token(USER_A)
    tb = jwt_auth.create_access_token(USER_B)
    ka = jwt_auth._bl_key(ta, jwt_auth.decode_token(ta))
    kb = jwt_auth._bl_key(tb, jwt_auth.decode_token(tb))
    check("A 와 B 의 폐기 키가 다르다", ka != kb, f"A={ka[:28]}… B={kb[:28]}…")
    check("옛 방식(token[:32])이었다면 같았을 것", ta[:32] == tb[:32],
          f"앞 32자: {ta[:32]}  ← 두 토큰이 글자까지 같다")

    # ── 2. A 가 로그아웃해도 B 는 멀쩡한가 ───────────────────────────────────
    print("\n[2] A 로그아웃이 B 를 끊지 않는가 — 결함 1 의 실제 증상")
    await jwt_auth.revoke_token(ta)
    a_dead = await jwt_auth.is_revoked(ta, jwt_auth.decode_token(ta))
    b_alive = not await jwt_auth.is_revoked(tb, jwt_auth.decode_token(tb))
    check("A 의 토큰은 폐기됐다", a_dead)
    check("B 의 토큰은 그대로 쓸 수 있다", b_alive,
          "여기가 실패하면 한 사람의 로그아웃이 전원을 끊던 옛 동작이다")

    # ── 3. 액세스와 리프레시가 다른 jti 인가 ────────────────────────────────
    print("\n[3] 한 쌍의 액세스·리프레시가 서로 다른 jti 인가")
    pair = jwt_auth.create_token_pair(USER_A)
    jti_ac = claims_of(pair["access_token"])["jti"]
    jti_rf = claims_of(pair["refresh_token"])["jti"]
    check("액세스 jti ≠ 리프레시 jti", jti_ac != jti_rf, f"{jti_ac[:12]}… vs {jti_rf[:12]}…")
    await jwt_auth.revoke_token(pair["access_token"])
    rf_alive = not await jwt_auth.is_revoked(
        pair["refresh_token"], jwt_auth.decode_token(pair["refresh_token"]))
    check("액세스를 폐기해도 리프레시는 살아 있다", rf_alive)

    # ── 4. 리프레시로 받은 액세스에 옛 jti 가 묻어오는가 ────────────────────
    print("\n[4] 리프레시가 jti 를 새 액세스에 복사하지 않는가")
    rf_claims = jwt_auth.decode_token(pair["refresh_token"])
    carried = {k: v for k, v in rf_claims.items() if k not in ("type", "jti", "iat", "exp")}
    fresh = jwt_auth.create_access_token(carried)
    check("새 액세스의 jti 가 리프레시와 다르다", claims_of(fresh)["jti"] != jti_rf)
    check("넘겨준 payload 에 jti 가 섞여 있어도 덮어쓴다",
          claims_of(jwt_auth.create_access_token({**carried, "jti": jti_rf}))["jti"] != jti_rf,
          "create_access_token 안에서 jti 를 새로 만들기 때문")

    # ── 5. 서명부만 바꾼 변조본이 폐기를 비켜 가는가 ────────────────────────
    print("\n[5] 서명부 변조본이 폐기 키를 비켜 가지 못하는가 — JWT malleability")
    victim = jwt_auth.create_access_token(USER_B)
    v_payload = jwt_auth.decode_token(victim)
    await jwt_auth.revoke_token(victim)
    head_pay, sig = victim.rsplit(".", 1)
    tampered = f"{head_pay}.{sig}="          # base64 패딩만 덧붙인 변조본
    same_key = jwt_auth._bl_key(victim, v_payload) == jwt_auth._bl_key(tampered, v_payload)
    check("변조본도 같은 폐기 키로 떨어진다", same_key,
          "토큰 전체를 sha256 했다면 키가 달라져 폐기를 비켜 갔을 것")

    # ── 6. exp 없는 토큰 ────────────────────────────────────────────────────
    print("\n[6] exp 없는 토큰이 거절되는가")
    no_exp = jwt.encode({"sub": "x", "id": "x", "type": "access"},
                        settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    try:
        jwt_auth.decode_token(no_exp)
        check("exp 없는 토큰이 거절된다", False, "통과해 버렸다 — require_exp 가 안 걸렸다")
    except HTTPException as e:
        check("exp 없는 토큰이 거절된다", e.status_code == 401, f"401: {e.detail[:60]}")

    # ── 7. 자리표시자 비밀값 ────────────────────────────────────────────────
    print("\n[7] 자리표시자 JWT_SECRET 으로는 발급이 막히는가")
    real = settings.JWT_SECRET
    settings.JWT_SECRET = jwt_auth._PLACEHOLDER_SECRET
    try:
        jwt_auth.create_access_token(USER_A)
        check("자리표시자면 발급이 막힌다", False, "발급돼 버렸다")
    except HTTPException as e:
        check("자리표시자면 발급이 막힌다", e.status_code == 500, e.detail[:70])
    settings.JWT_ALLOW_INSECURE_SECRET = True
    try:
        jwt_auth.create_access_token(USER_A)
        check("JWT_ALLOW_INSECURE_SECRET=true 면 통과한다(탈출구)", True)
    except HTTPException:
        check("JWT_ALLOW_INSECURE_SECRET=true 면 통과한다(탈출구)", False)
    settings.JWT_ALLOW_INSECURE_SECRET = False
    settings.JWT_SECRET = real

    # ── 8. 폐기 API 의 소유권 검사 ──────────────────────────────────────────
    print("\n[8] 남의 토큰을 폐기할 수 없는가 — 결함 2")
    from app.routes.auth import TokenRevokeBody, revoke_tokens

    victim_tok = jwt_auth.create_access_token(USER_B)
    try:
        await revoke_tokens(TokenRevokeBody(access_token=victim_tok), user=USER_A)
        check("A 가 B 의 토큰을 폐기하면 거절된다", False, "폐기돼 버렸다")
    except HTTPException as e:
        check("A 가 B 의 토큰을 폐기하면 거절된다", e.status_code == 403, f"403: {e.detail}")
    still_alive = not await jwt_auth.is_revoked(victim_tok, jwt_auth.decode_token(victim_tok))
    check("거절된 뒤 B 의 토큰은 그대로다", still_alive)

    own = jwt_auth.create_token_pair(USER_A)
    out = await revoke_tokens(
        TokenRevokeBody(access_token=own["access_token"], refresh_token=own["refresh_token"]),
        user=USER_A,
    )
    check("자기 토큰 두 개는 폐기된다", out.get("revoked") == 2, str(out))
    both_dead = all([
        await jwt_auth.is_revoked(own["access_token"], jwt_auth.decode_token(own["access_token"])),
        await jwt_auth.is_revoked(own["refresh_token"], jwt_auth.decode_token(own["refresh_token"])),
    ])
    check("액세스·리프레시가 둘 다 죽었다", both_dead)

    await close_redis()
    print(f"\n── 결과: 통과 {_ok} · 실패 {_ng} ──")
    sys.exit(1 if _ng else 0)


if __name__ == "__main__":
    asyncio.run(main())
