"""동의 · 철회 기록 (2026-10-29 · 할 일 ①-09) — 행을 쌓기만 하고 고치지 않는다.

한 사람이 한 항목에 동의했다가 철회하고 다시 동의하면 행이 셋 생긴다. 지금 동의 상태는 그 항목의 **가장 늦은 행**이
`grant` 인지로 읽는다(app.services.consent.is_granted). 행을 덮어쓰면 「언제 어느 판에 동의했나」 를 입증할 수 없다.

감사 기록(audit_events)과 달리 이 표는 사용자 행과 **같은 트랜잭션**으로 쓴다 — audit() 은 모든 예외를 삼켜
기록이 조용히 빠질 수 있었다. 탈퇴하면 사용자 행과 함께 지워진다(탈퇴 뒤 남는 입증 자료는 계정과 연결을 끊은
감사 기록 `terms.agree` 뿐이다 · 처리방침 3항).
"""
from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPkMixin

#: 행의 동작 — 동의 / 철회
CONSENT_GRANT = "grant"
CONSENT_WITHDRAW = "withdraw"


class UserConsent(Base, UUIDPkMixin, CreatedAtMixin):
    __tablename__ = "user_consents"
    __table_args__ = (
        Index("ix_user_consents_user_key_created", "user_id", "consent_key", "created_at"),
        CheckConstraint("action in ('grant', 'withdraw')", name="ck_user_consents_action"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    #: 항목 — 가입 필수 셋(service · privacy · invest)과 선택 동의(notify_integration)
    consent_key: Mapped[str] = mapped_column(String(40), nullable=False)
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    #: 동의한 문구의 판 — 가입은 약관 판(TERMS_VERSION), 알림 연동은 그 동의문의 판(NOTIFY_CONSENT_VERSION)
    terms_version: Mapped[str] = mapped_column(String(40), nullable=False)
    #: 어느 화면에서 받았나 — signup · notification_settings
    source: Mapped[str] = mapped_column(String(40), nullable=False)
