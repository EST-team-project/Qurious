"""restore dropped indexes ix_api_keys_user ix_portfolio_user_id

Revision ID: 2c44bb6e2abc
Revises: afeb0a91df5a
Create Date: 2026-10-02 08:04:41.067557

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
