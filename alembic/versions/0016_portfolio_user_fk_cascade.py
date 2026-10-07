"""portfolio user fk cascade

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-07 15:49:12.402095

portfolio.user_id 외래키를 ondelete=CASCADE 로 다시 만든다.
- 모델(app/models/trading.py Portfolio.user_id)은 이미 CASCADE
- DB 의 portfolio_user_id_fkey 는 CASCADE 없이 만들어져 있어 alembic check 가 어긋난다
- 이슈 #88 후속 (갱신 04 · 2026-10-06)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0016'
down_revision: Union[str, Sequence[str], None] = '0015'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


FK_NAME = "portfolio_user_id_fkey"


def upgrade() -> None:
    """portfolio.user_id FK 를 ondelete=CASCADE 로 재생성."""
    op.drop_constraint(FK_NAME, "portfolio", type_="foreignkey")
    op.create_foreign_key(
        FK_NAME, "portfolio", "users",
        ["user_id"], ["id"], ondelete="CASCADE",
    )


def downgrade() -> None:
    """CASCADE 를 뺀 원래 FK 로 되돌린다."""
    op.drop_constraint(FK_NAME, "portfolio", type_="foreignkey")
    op.create_foreign_key(
        FK_NAME, "portfolio", "users",
        ["user_id"], ["id"],
    )