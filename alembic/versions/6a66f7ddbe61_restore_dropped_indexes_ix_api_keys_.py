"""restore dropped indexes ix_api_keys_user ix_portfolio_user_id

Revision ID: 6a66f7ddbe61
Revises: 2c44bb6e2abc
Create Date: 2026-10-02 08:05:25.776473

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6a66f7ddbe61'
down_revision: Union[str, Sequence[str], None] = '2c44bb6e2abc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """삭제됐던 인덱스 복구 (2026-10-02) — PR #85 QFRS 마이그레이션이 실수로 지운 것."""
    op.create_index('ix_portfolio_user_id', 'portfolio', ['user_id'])
    op.create_index('ix_api_keys_user', 'api_keys', ['user_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_api_keys_user', table_name='api_keys')
    op.drop_index('ix_portfolio_user_id', table_name='portfolio')
