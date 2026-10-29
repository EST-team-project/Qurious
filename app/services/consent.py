"""동의 · 철회 기록을 쓰고 읽는다 (2026-10-29 · 할 일 ①-09). 표는 app.models.consent.UserConsent.

원칙
- **행을 쌓기만 한다** — 철회도 새 행(`withdraw`)이다. 지금 상태는 그 항목의 가장 늦은 행이 `grant` 인지로 읽는다.
- **쓰기는 호출자의 트랜잭션에 얹는다**(add_rows 는 commit 하지 않는다) — 가입은 사용자 행과, 알림 설정은 그 설정 저장과
  한 번에 commit 된다. audit() 처럼 예외를 삼키지 않는다: 기록이 안 들어가면 가입 · 저장도 안 된다.
- 선택 동의는 가입이 아니라 **그 기능을 처음 쓰는 화면**에서 받는다(알림 연동 → 알림 설정 화면).
"""
from __future__ import annotations

import uuid
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.consent import CONSENT_GRANT, CONSENT_WITHDRAW, UserConsent

#: 알림 연동 정보 수집 · 이용(선택) — 알림 채널의 토큰 · 웹훅 · 이메일 발송 비밀번호 · 휴대전화번호 · API 키.
NOTIFY_CONSENT_KEY = "notify_integration"
#: 그 동의문의 판 — public/js/terms.js 의 NOTIFY_CONSENT_VERSION 과 같아야 한다(시험 TC-UC 가 지킨다).
#: 다르면 저장을 거절한다: 오래된 화면(캐시)이 옛 문구를 보여 줬는데 새 판에 동의한 것으로 기록되는 일을 막는다.
NOTIFY_CONSENT_VERSION = "2026-10-29-n0.1"

SOURCE_SIGNUP = "signup"
SOURCE_NOTIFICATION_SETTINGS = "notification_settings"


def add_rows(db: AsyncSession, user_id: uuid.UUID, keys: Iterable[str], action: str,
             version: str, source: str) -> list[UserConsent]:
    """동의(grant) 또는 철회(withdraw) 행을 세션에 더한다. commit 은 호출자가 한다 — 사용자 행 · 설정 저장과 한 트랜잭션."""
    if action not in (CONSENT_GRANT, CONSENT_WITHDRAW):
        raise ValueError(f"알 수 없는 동의 동작: {action}")
    rows = [UserConsent(user_id=user_id, consent_key=k, action=action, terms_version=version, source=source)
            for k in sorted(set(keys))]
    db.add_all(rows)
    return rows


async def latest(db: AsyncSession, user_id: uuid.UUID, key: str) -> UserConsent | None:
    """그 항목의 가장 늦은 행(없으면 None)."""
    res = await db.execute(
        select(UserConsent)
        .where(UserConsent.user_id == user_id, UserConsent.consent_key == key)
        .order_by(UserConsent.created_at.desc())
        .limit(1)
    )
    return res.scalar_one_or_none()


async def is_granted(db: AsyncSession, user_id: uuid.UUID, key: str) -> bool:
    """지금 동의한 상태인가 — 가장 늦은 행이 grant 일 때만 True. 한 번도 안 받았거나 철회했으면 False."""
    row = await latest(db, user_id, key)
    return row is not None and row.action == CONSENT_GRANT
