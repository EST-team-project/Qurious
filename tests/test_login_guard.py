"""TC-LG — 로그인 시도 횟수 제한(app/services/login_guard.py · app/routes/auth.py) · 2026-10-29 · 할 일 ①-09

비밀번호를 계속 바꿔 넣어 보는 공격을 늦춘다. 약속:
1. 같은 이메일로 다섯 번 틀리면 그 창(열 분)이 끝날 때까지 막는다 — **비밀번호가 맞아도**. 창이 끝나면 풀린다. (TC-LG-01)
2. 없는 이메일도 똑같이 센다 — 가입 여부가 새지 않는다 · 이메일은 대소문자 · 앞뒤 공백을 가리지 않고 키에 원문이 없다. (TC-LG-02)
3. 맞게 로그인하면 그 이메일의 횟수만 지운다 · **주소(IP) 잠금은 기본 꺼짐** — 도커 · 프록시 뒤에서는 모든 사용자가 한 주소(실측 172.18.0.1)로 보여 켜면 전원이 잠긴다. 켜면(`LOGIN_IP_MAX_FAILS`) 한 주소가 이메일을 바꿔 가며 한도만큼 틀릴 때 그 주소를 막고 주소 횟수는 성공해도 남는다. (TC-LG-03)
4. 키에 만료가 빠졌으면 다시 붙인다(영영 잠기지 않게) · Redis 가 안 되면 막지 않는다. (TC-LG-04)
5. 라우트: 두 로그인 길(`/auth/login` · `/auth/token`)이 같은 제한을 쓴다 · 429 + Retry-After + 한국어 글 · 401 글은 남은 횟수가 적을 때만 경고. (TC-LG-05 ~ 06)
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.lib import redis_cache
from app.routes import auth as auth_routes
from app.services import account, login_guard as G


class FakeRedis:
    """get · incr · expire · ttl · delete 만 — 가짜 시계가 있다."""

    def __init__(self):
        self.kv: dict[str, int] = {}
        self.exp: dict[str, float] = {}
        self.now = 1_000.0

    def _alive(self, k):
        if k in self.exp and self.exp[k] <= self.now:
            self.kv.pop(k, None)
            self.exp.pop(k, None)
        return k in self.kv

    async def get(self, k):
        return str(self.kv[k]) if self._alive(k) else None

    async def incr(self, k):
        self._alive(k)
        self.kv[k] = self.kv.get(k, 0) + 1
        return self.kv[k]

    async def expire(self, k, ttl):
        if self._alive(k):
            self.exp[k] = self.now + ttl

    async def ttl(self, k):
        if not self._alive(k):
            return -2
        return int(self.exp[k] - self.now) if k in self.exp else -1

    async def delete(self, *ks):
        for k in ks:
            self.kv.pop(k, None)
            self.exp.pop(k, None)


@pytest.fixture()
def redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(redis_cache, "_redis", fake)
    return fake


def run(coro):
    return asyncio.run(coro)


def fail(email, ip="1.1.1.1", n=1):
    for _ in range(n):
        run(G.record_failure(email, ip))


def test_five_failures_lock_even_correct_password_then_window_frees(redis):
    """TC-LG-01 · 네 번까지는 열려 있고 다섯 번째에 잠긴다 · 잠금은 창이 끝나면 풀린다 · 남은 시간이 retry_after 로."""
    fail("a@x.com", n=4)
    run(G.check("a@x.com", "1.1.1.1"))                              # 네 번 틀림 — 아직 열려 있다
    fail("a@x.com")
    with pytest.raises(G.LoginLocked) as lock:
        run(G.check("a@x.com", "1.1.1.1"))
    assert 1 <= lock.value.retry_after <= G.WINDOW_SEC and "10분" in lock.value.message()
    redis.now += G.WINDOW_SEC + 1                                   # 창이 끝났다
    run(G.check("a@x.com", "1.1.1.1"))


def test_unknown_email_counts_the_same_and_key_has_no_raw_email(redis):
    """TC-LG-02 · 없는 이메일도 같은 횟수에 잠긴다 · 대소문자 · 공백을 가리지 않는다 · 키에 이메일 원문이 없다."""
    fail("nobody@x.com", n=2)
    fail("  NoBody@X.com ", n=3)
    with pytest.raises(G.LoginLocked):
        run(G.check("nobody@x.com", "9.9.9.9"))
    assert all("nobody" not in k.lower() and "@" not in k for k in redis.kv)
    run(G.check("someone-else@x.com", "9.9.9.9"))                   # 다른 이메일은 영향 없음


def test_ip_lock_off_by_default_and_when_enabled_blocks_spraying(redis, monkeypatch):
    """TC-LG-03 · 기본은 IP 잠금 꺼짐 — 모두가 한 주소(도커 게이트웨이 172.18.0.1)로 보여도 새 이메일은 열려 있고 주소를 저장하지도 않는다 ·
    켜면(LOGIN_IP_MAX_FAILS) 한 주소가 이메일을 바꿔 가며 한도만큼 틀릴 때 그 주소가 막히고, 맞게 로그인하면 이메일 횟수만 지워진다(주소 횟수는 남음)."""
    assert G.IP_MAX_FAILS == 0
    for i in range(200):
        run(G.record_failure(f"user{i}@x.com", "172.18.0.1"))
    run(G.check("brand-new@x.com", "172.18.0.1"))                     # 막히지 않는다
    assert not any(k.startswith("login_fail:ip:") for k in redis.kv)  # 주소 원문을 남기지 않는다
    redis.kv.clear()
    monkeypatch.setattr(G, "IP_MAX_FAILS", 30)
    fail("a@x.com", ip="2.2.2.2", n=3)
    run(G.reset("a@x.com"))
    assert not any(k.startswith("login_fail:e:") for k in redis.kv)
    assert redis.kv["login_fail:ip:2.2.2.2"] == 3
    for i in range(G.IP_MAX_FAILS - 3):                              # 이메일은 매번 다르다 — 이메일 한도는 안 닿는다
        run(G.record_failure(f"user{i}@x.com", "2.2.2.2"))
    with pytest.raises(G.LoginLocked):
        run(G.check("brand-new@x.com", "2.2.2.2"))                    # 새 이메일이어도 그 주소는 막힘
    run(G.check("brand-new@x.com", "3.3.3.3"))                        # 다른 주소는 열려 있다


def test_missing_expiry_is_reattached_and_redis_down_is_fail_open(redis, monkeypatch):
    """TC-LG-04 · 만료가 빠진 키는 다시 붙인다(영영 잠기지 않게) · Redis 가 터져도 check · record_failure · reset 이 던지지 않는다."""
    k = G._email_key("a@x.com")
    redis.kv[k] = 3                                                  # INCR 뒤 EXPIRE 전에 끊긴 키 — 만료가 없다
    assert run(redis.ttl(k)) == -1
    left = run(G.record_failure("a@x.com", "1.1.1.1"))
    assert run(redis.ttl(k)) > 0 and left == G.MAX_FAILS - 4

    class Boom:
        def __getattr__(self, name):
            async def f(*a, **k):
                raise ConnectionError("redis down")
            return f

    monkeypatch.setattr(redis_cache, "_redis", Boom())
    run(G.check("a@x.com", "1.1.1.1"))                               # 막지 않는다
    assert run(G.record_failure("a@x.com", "1.1.1.1")) == G.MAX_FAILS
    run(G.reset("a@x.com"))


def test_failure_message_warns_only_when_few_left():
    """TC-LG-05a · 401 글은 남은 횟수가 적을 때만 경고한다 — 이메일이 없어도 같은 글이라 가입 여부가 새지 않는다."""
    base = "이메일 또는 비밀번호가 올바르지 않습니다."
    assert G.failure_message(5) == base and G.failure_message(3) == base
    assert "2회 더 틀리면 10분 동안" in G.failure_message(2) and "1회 더" in G.failure_message(1)
    assert "5번 틀려 10분 동안 로그인이 잠겼습니다" in G.failure_message(0)


# ── 라우트 ──────────────────────────────────────────────────────────────────────

PW = "Correct-Horse-9"
USER = type("U", (), {"id": 7, "name": "홍길동", "email": "a@x.com", "client_id": "C1", "roles": ["user"],
                      "password_hash": account.hash_password(PW)})()


class _DB:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


@pytest.fixture()
def client(redis, monkeypatch):
    async def find(db, email):
        return USER if str(email).strip().lower() == USER.email else None

    async def noop(*a, **k):
        return None

    async def sid(*a, **k):
        return "sid"

    monkeypatch.setattr(auth_routes, "get_session_factory", lambda: (lambda: _DB()))
    monkeypatch.setattr(auth_routes, "_find_user_by_email", find)
    monkeypatch.setattr(auth_routes, "create_session", sid)
    monkeypatch.setattr(auth_routes, "mark_online", noop)
    monkeypatch.setattr(auth_routes, "create_token_pair", lambda payload: {"access_token": "a", "refresh_token": "r"})
    app = FastAPI()
    app.include_router(auth_routes.router)
    return TestClient(app)


@pytest.mark.parametrize("path", ["/api/auth/login", "/api/auth/token"])
def test_both_login_routes_share_the_limit(client, path):
    """TC-LG-05 · 두 로그인 길이 같은 제한 — 다섯 번 틀리면 429(+ Retry-After · 한국어 글), 그 뒤엔 맞는 비밀번호도 429."""
    bad = {"email": "a@x.com", "password": "wrong-pass-1"}
    for i in range(G.MAX_FAILS):
        r = client.post(path, json=bad)
        assert r.status_code == 401, (i, r.text)
    last_msg = r.json()["detail"]
    assert "잠겼습니다" in last_msg                                    # 다섯 번째 틀림 — 이미 잠겼다고 알린다
    r = client.post(path, json=bad)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1 and "분 뒤에 다시" in r.json()["detail"]
    r = client.post(path, json={"email": "a@x.com", "password": PW})   # 맞는 비밀번호여도 막힌다
    assert r.status_code == 429
    r = client.post(path, json={"email": "A@X.com ", "password": PW})  # 대소문자 · 공백으로 피해 가지 못한다
    assert r.status_code == 429
    other = {"email": "other@x.com", "password": "x"}                  # 다른 이메일은 이 이메일의 잠금과 무관(주소 한도는 아직)
    assert client.post(path, json=other).status_code == 401


def test_success_clears_failures_and_unknown_email_gets_same_401(client, redis):
    """TC-LG-06 · 네 번 틀린 뒤 맞게 로그인하면 횟수가 지워진다 · 없는 이메일의 401 글이 있는 이메일과 같다."""
    bad = {"email": "a@x.com", "password": "wrong-pass-1"}
    for _ in range(4):
        client.post("/api/auth/login", json=bad)
    ok = client.post("/api/auth/login", json={"email": "a@x.com", "password": PW})
    assert ok.status_code == 200 and ok.json()["ok"] is True
    assert client.post("/api/auth/login", json=bad).status_code == 401   # 횟수가 지워져 다시 하나부터
    assert not [k for k in redis.kv if k.startswith("login_fail:e:") and redis.kv[k] > 1]
    known = client.post("/api/auth/login", json=bad).json()["detail"]
    unknown = client.post("/api/auth/login", json={"email": "ghost@x.com", "password": "x"}).json()["detail"]
    assert known.split(" ")[0:3] == unknown.split(" ")[0:3] and "올바르지 않습니다" in unknown
