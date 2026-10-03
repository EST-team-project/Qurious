"""KIS 자격증명 — 사용자마다 자기 키 (TC-KC · Qurious 2026-10-03 결정).

강사님 9478811 의 같은 이름 시험은 「서버가 KIS 계좌 하나를 관리한다」(Secrets Manager 조회 · 캐시 · .env 폴백 ·
라우트가 사용자 키를 지운다)를 쟀다. Qurious 는 여러 사람이 쓰는 모의투자 플랫폼이라 사용자마다 자기 키를 쓰기로
했으므로(app/services/kis_credentials.py 머리말), 같은 자리에서 그 반대를 잰다 — 서버 계좌는 없고, 라우트는 사용자
키를 저장하고, 화면용 상태에는 키 원문이 없다. 강사님 시험 10건 가운데 그대로 맞는 것(계좌 가리기 · KIS 밖 증권사)은 남겼다.
"""
import asyncio
import json
from types import SimpleNamespace

import pytest

from app.config import settings
from app.services import kis_credentials as kc


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    for k in ("KIS_SECRETS_NAME", "KIS_APP_KEY", "KIS_APP_SECRET", "KIS_ACCOUNT_NO"):
        monkeypatch.setattr(settings, k, "")
    monkeypatch.setattr(settings, "KIS_ENVIRONMENT", "paper")
    kc.invalidate()
    yield
    kc.invalidate()


def _kis_row(**over):
    base = dict(broker="kis", app_key="PSuserkey", app_secret="usersecret", account_no="5012345601", paper=True)
    base.update(over)
    return SimpleNamespace(**base)


def test_서버_계좌는_없다():
    assert kc.MANAGED_BROKERS == frozenset() and kc.is_managed("kis") is False
    assert kc.is_configured() is False and kc.resolve() is None
    assert asyncio.run(kc.get_credentials()) is None
    st = asyncio.run(kc.get_status())
    assert st["configured"] is False and st["managed"] is False and st["source"] is None


def test_서버_env_에_KIS_키를_넣어도_쓰지_않는다(monkeypatch):
    """강사님 판은 .env 의 KIS_APP_KEY 를 모든 사용자의 계좌로 썼다 — 우리 판은 읽지 않는다."""
    monkeypatch.setattr(settings, "KIS_APP_KEY", "server-key")
    monkeypatch.setattr(settings, "KIS_APP_SECRET", "server-secret")
    monkeypatch.setattr(settings, "KIS_ACCOUNT_NO", "1234567890")
    assert kc.is_configured() is False and asyncio.run(kc.get_credentials()) is None
    assert kc.for_user(_kis_row()).app_key == "PSuserkey"


def test_for_user_는_그_사용자의_KIS_키를_돌려준다():
    creds = kc.for_user(_kis_row())
    assert (creds.app_key, creds.app_secret, creds.account_no, creds.source) == ("PSuserkey", "usersecret", "5012345601", "user")
    assert creds.paper is True and creds.environment == "paper"   # 실거래 승인 없음 → 모의


def test_for_user_는_KIS_가_아니거나_키가_비면_None():
    assert kc.for_user(None) is None
    assert kc.for_user(_kis_row(broker="kb")) is None
    assert kc.for_user(_kis_row(app_secret="")) is None
    assert kc.for_user(_kis_row(app_key="  ")) is None
    assert kc.for_user(_kis_row(account_no="")).account_no == ""   # 계좌 없이도 돌려준다(잔고 조회는 부르는 쪽이 판단)


def test_화면용_상태에_키_원문이_없다():
    st = kc.status(kc.for_user(_kis_row()))
    assert st["configured"] and st["source"] == "user" and st["account_masked"] == "5012****01"
    assert st["environment"] == "paper" and st["has_account"] is True
    assert "PSuserkey" not in json.dumps(st, ensure_ascii=False) and "usersecret" not in json.dumps(st, ensure_ascii=False)


def test_자격증명이_없을_때도_환경은_글자다():
    """강사님 판은 이 칸에 참/거짓을 넣었다(화면 표시 결함) — 우리 판은 늘 paper | real."""
    assert kc.status(None)["environment"] == "paper"


def test_mask_account():
    assert kc.mask_account("") == ""
    assert kc.mask_account("123456") == "******"
    assert kc.mask_account("5012345601") == "5012****01"


# ── 라우트: KIS 도 사용자가 보낸 키를 저장하고 그 키를 쓴다 ─────────────────
from app.routes import stocks as stocks_routes  # noqa: E402


def test_설정_저장은_KIS_도_사용자_키를_남긴다():
    row = SimpleNamespace(app_key="old", app_secret="old", account_no="old")
    stocks_routes._apply_credentials(row, "kis", "userkey", "usersec", "999")
    assert (row.app_key, row.app_secret, row.account_no) == ("userkey", "usersec", "999")
    stocks_routes._apply_credentials(row, "kb", "kbkey", "kbsec", "111")
    assert (row.app_key, row.app_secret, row.account_no) == ("kbkey", "kbsec", "111")


def test_KIS_연동은_사용자_행을_쓰고_화면에는_가린_키만():
    row = _kis_row()
    assert asyncio.run(stocks_routes._resolve_credentials(row)) == ("kis", "PSuserkey", "usersecret", "5012345601", True)
    view = asyncio.run(stocks_routes._connection_view(row))
    assert view["connected"] is True and view["app_key"] == "PSus****" and view["kis_managed"] is None


def test_resolve_credentials_non_managed_uses_row():
    row = SimpleNamespace(broker="kb", app_key="k", app_secret="s", account_no="a", paper=False)
    assert asyncio.run(stocks_routes._resolve_credentials(row)) == ("kb", "k", "s", "a", False)
    assert asyncio.run(stocks_routes._resolve_credentials(None)) == ("mock", "", "", "", True)
