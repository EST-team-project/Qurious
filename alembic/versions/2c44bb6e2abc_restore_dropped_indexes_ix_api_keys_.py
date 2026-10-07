"""restore dropped indexes ix_api_keys_user ix_portfolio_user_id

Revision ID: 2c44bb6e2abc
Revises: afeb0a91df5a
Create Date: 2026-10-02 08:04:41.067557

⚠️ 빈 판 — 실제 인덱스 복구는 6a66f7ddbe61 에서 한다.

배경 (이슈 #88):
    같은 제목의 판이 둘이다 (2c44bb6e2abc · 6a66f7ddbe61). 이름이 같아
    다음 사람이 헷갈린다. 2c44bb6e2abc 의 upgrade/downgrade 는 pass 이고,
    실제 인덱스 복구는 6a66f7ddbe61 에서 이루어진다.

    이미 적용된 판이라 지우면 안 된다 — 그 판까지 올린 DB 가 판을 못 찾는다.
    설명만 바꾸는 것은 안전하므로 이 주석을 남긴다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2c44bb6e2abc'
down_revision: Union[str, Sequence[str], None] = 'afeb0a91df5a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
