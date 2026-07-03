"""merge heads: transcription and cleanup pipelines

Revision ID: 7224832fa22d
Revises: a1b2c3d4e5f6, b2c3d4e5f6a7
Create Date: 2026-07-04 00:28:37.500600

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7224832fa22d'
down_revision: Union[str, Sequence[str], None] = ('b2c3d4e5f6a7', 'a1b2c3d4e5f6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
