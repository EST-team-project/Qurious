"""KIS(한국투자증권) 자격증명 — 사용자마다 자기 키를 쓴다 (Qurious · 2026-10-03 결정).

강사님 기초 코드(9478811)는 서버가 KIS 계좌 하나를 관리한다(AWS Secrets Manager → .env 의 KIS_APP_KEY …).
사용자는 증권사로 KIS 를 고르기만 하고, KIS 를 고른 모든 사용자의 주문 · 잔고가 그 한 계좌로 모인다.
혼자 운영하는 사이트라면 맞지만, Qurious 는 여러 사람이 쓰는 모의투자 플랫폼이라 포지션 · 잔고가 섞이고
설정을 저장할 때마다 각자 넣은 키가 지워진다 — 사용자 결정 「사용자마다 받는 것으로 처음부터」.

그래서 이 모듈은 강사님 판과 **이름은 같고 뜻이 다르다.**
  - MANAGED_BROKERS 를 비운다 → is_managed() 가 늘 거짓 → 강사님 코드의 「서버 관리」 갈래
    (routes/stocks.py 의 _apply_credentials · _resolve_credentials · _connection_view, auto_trade 의 실주문)가
    모두 사용자 행(broker_settings 의 app_key · app_secret · account_no)을 쓰고, 저장할 때 키를 지우지 않는다.
  - 서버 계좌를 읽던 함수(is_configured · resolve · get_credentials · get_status)는 이름만 남기고
    「서버 계좌 없음」 을 돌려준다. 대시보드 · 원클릭은 for_user(row) 로 그 사용자의 키를 읽는다.
  - Secrets Manager(boto3) 갈래는 뺐다 — 2026-09-15 에 AWS 를 걷어냈다(tests/test_base_code_merge_guard.py).
환경(모의 · 실전)은 실거래 승인(QURIOUS_ALLOW_LIVE_TRADING · ADR-0001)이 정한다 — 키를 넣었다고 실전이 되지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.services.brokers.factory import live_trading_allowed

# 서버가 자격증명을 관리하는 증권사 — 우리 판은 없다(사용자마다 자기 키).
MANAGED_BROKERS: frozenset[str] = frozenset()


@dataclass(frozen=True)
class KISCredentials:
    app_key: str
    app_secret: str
    account_no: str
    paper: bool
    source: str  # 우리 판은 늘 "user"(강사님 판: "secrets-manager" | "env")

    @property
    def environment(self) -> str:
        return "paper" if self.paper else "real"


def is_managed(broker: str | None) -> bool:
    """이 증권사의 자격증명을 서버가 관리하는가 — 우리 판은 늘 거짓(사용자별 키)."""
    return (broker or "").strip().lower() in MANAGED_BROKERS


def is_configured() -> bool:
    """서버 계좌가 설정돼 있는가 — 우리 판은 서버 계좌를 두지 않는다."""
    return False


def invalidate() -> None:
    """강사님 판의 캐시 비우기 자리 — 우리 판은 캐시할 서버 계좌가 없다."""


def resolve(force: bool = False) -> KISCredentials | None:
    """서버 계좌 — 우리 판은 없다. 사용자 키는 for_user(row)."""
    return None


async def get_credentials(force: bool = False) -> KISCredentials | None:
    """서버 계좌 — 우리 판은 없다(강사님 코드가 부르는 이름이라 남긴다)."""
    return None


def for_user(row: Any) -> KISCredentials | None:
    """그 사용자의 KIS 키(broker_settings 행). 증권사가 KIS 가 아니거나 키가 비면 None.

    계좌번호가 비어도 돌려준다(잔고 조회 가능 여부는 부르는 쪽이 본다).
    환경은 실거래 승인이 정한다 — 승인이 없으면 모의(Testbed).
    """
    if row is None or (getattr(row, "broker", "") or "").strip().lower() != "kis":
        return None
    app_key = (getattr(row, "app_key", "") or "").strip()
    app_secret = (getattr(row, "app_secret", "") or "").strip()
    if not app_key or not app_secret:
        return None
    return KISCredentials(
        app_key=app_key,
        app_secret=app_secret,
        account_no=(getattr(row, "account_no", "") or "").strip(),
        paper=not live_trading_allowed(),
        source="user",
    )


def mask_account(account_no: str) -> str:
    """앞 4자리·뒤 2자리만 남긴다 (예: 5012****01). 짧으면 전부 가린다."""
    if not account_no:
        return ""
    if len(account_no) <= 6:
        return "*" * len(account_no)
    return account_no[:4] + "*" * (len(account_no) - 6) + account_no[-2:]


def status(creds: KISCredentials | None, *, resolved: bool = True) -> dict:
    """화면 표시용. 키 원문은 넣지 않는다."""
    return {
        "managed": False,
        "configured": creds is not None,
        "source": creds.source if creds else None,
        "secret_name": "",
        "account_masked": mask_account(creds.account_no) if creds else "",
        "has_account": bool(creds and creds.account_no),
        # 강사님 판은 자격증명이 없을 때 이 칸에 참/거짓을 넣었다 — 우리 판은 늘 글자(paper | real).
        "environment": creds.environment if creds else ("real" if live_trading_allowed() else "paper"),
        "error": "",
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds") if resolved else None,
    }


async def get_status() -> dict:
    """서버 계좌 상태 — 우리 판은 늘 「없음」. 사용자 상태는 status(for_user(row))."""
    return status(None, resolved=False)
