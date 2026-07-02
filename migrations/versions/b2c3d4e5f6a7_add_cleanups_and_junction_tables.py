"""add cleanups and junction tables for issue #4 cleanup/snippet expansion pipeline

Revision ID: b2c3d4e5f6a7
Revises: 3a1b2c4d5e6f
Create Date: 2026-07-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "3a1b2c4d5e6f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cleanups",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("voice_message_id", sa.Integer(), nullable=False),
        sa.Column("cleaned_text", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=50), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["voice_message_id"],
            ["voice_messages.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("voice_message_id", name="uq_cleanups_voice_message"),
    )

    op.create_table(
        "transcription_snippets",
        sa.Column("transcription_id", sa.Integer(), nullable=False),
        sa.Column("snippet_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["snippet_id"], ["snippets.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["transcription_id"],
            ["transcriptions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("transcription_id", "snippet_id"),
    )

    op.create_table(
        "cleanup_snippets",
        sa.Column("cleanup_id", sa.Integer(), nullable=False),
        sa.Column("snippet_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["cleanup_id"], ["cleanups.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["snippet_id"], ["snippets.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("cleanup_id", "snippet_id"),
    )


def downgrade() -> None:
    op.drop_table("cleanup_snippets")
    op.drop_table("transcription_snippets")
    op.drop_table("cleanups")
