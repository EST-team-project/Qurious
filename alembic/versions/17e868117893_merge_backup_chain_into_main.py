"""merge backup chain into main

Revision ID: 17e868117893
Revises: 6a66f7ddbe61, c3d81e5a9b40
Create Date: 2026-10-02 08:46:09.415938

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '17e868117893'
down_revision: Union[str, Sequence[str], None] = ('6a66f7ddbe61', 'c3d81e5a9b40')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
