"""create snippets table

Revision ID: 3a1b2c4d5e6f
Revises: c55b2b527f75
Create Date: 2026-07-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "3a1b2c4d5e6f"
down_revision: Union[str, Sequence[str], None] = "c55b2b527f75"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "snippets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("shortcut", sa.String(length=100), nullable=False),
        sa.Column("expansion", sa.Text(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["account.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "shortcut", name="uq_snippets_user_shortcut"),
    )
    op.create_index(
        op.f("ix_snippets_user_id"), "snippets", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_snippets_user_id"), table_name="snippets")
    op.drop_table("snippets")
