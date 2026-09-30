"""users.email — 소문자로 맞추고 소문자 기준 유일 색인 (이메일 대소문자 무관 로그인)

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-30

왜
  가입은 이메일 도메인을 소문자로 바꿔 저장하고 로그인은 친 글자 그대로 비교해서, 대문자가 섞인 이메일로
  가입하면 같은 글자로도 로그인이 안 됐다. 앱은 이제 이메일을 전부 소문자로 저장 · 비교한다
  (app/services/account.py). 이 마이그레이션은 **이미 저장된 행**을 같은 모양으로 맞추고, DB 가 대소문자만
  다른 두 번째 가입을 막게 `lower(email)` 유일 색인을 만든다.

안전장치
  대소문자만 다른 행이 이미 둘 이상이면(규칙 전에는 둘 다 가입될 수 있었다) 그 행들은 바꾸지 않고 색인도
  만들지 않는다 — 앱은 켜질 때 마이그레이션을 돌리므로 여기서 실패하면 앱이 아예 뜨지 않는다. 그 경우에도
  로그인은 `lower(email)` 비교로 되고, 새 가입은 앱이 막는다. 어느 이메일이 겹치는지 경고로 남긴다.
"""
import logging
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "uq_users_email_lower"
logger = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    conn = op.get_bind()
    dups = [r[0] for r in conn.execute(sa.text(
        "SELECT lower(btrim(email)) FROM users GROUP BY lower(btrim(email)) HAVING count(*) > 1"
    ))]
    # 겹치지 않는 행만 소문자 · 앞뒤 공백 없음으로 맞춘다.
    conn.execute(sa.text(
        "UPDATE users SET email = lower(btrim(email)) "
        "WHERE email <> lower(btrim(email)) "
        "AND lower(btrim(email)) NOT IN ("
        "  SELECT lower(btrim(email)) FROM users GROUP BY lower(btrim(email)) HAVING count(*) > 1)"
    ))
    if dups:
        logger.warning("대소문자만 다른 이메일이 겹쳐 %s 색인을 만들지 않았다: %s", INDEX_NAME, ", ".join(dups))
        return
    op.create_index(INDEX_NAME, "users", [sa.text("lower(email)")], unique=True)


def downgrade() -> None:
    op.execute(sa.text(f"DROP INDEX IF EXISTS {INDEX_NAME}"))
