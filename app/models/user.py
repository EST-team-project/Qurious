from __future__ import annotations

import uuid

from sqlalchemy import Index, String, func, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPkMixin


class User(Base, UUIDPkMixin, CreatedAtMixin):
    __tablename__ = "users"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    client_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    roles: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, server_default=text("ARRAY['user']::varchar[]")
    )


# 이메일은 대소문자를 가리지 않는다 — 소문자 기준 유일 색인(마이그레이션 0010 · app/services/account.py).
# 모델에도 적어 두어야 alembic 대조가 「DB 에만 있는 색인」 으로 보지 않는다.
Index("uq_users_email_lower", func.lower(User.email), unique=True)
