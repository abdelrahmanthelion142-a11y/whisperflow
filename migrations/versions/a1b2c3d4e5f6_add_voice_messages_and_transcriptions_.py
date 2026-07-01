"""add voice_messages and transcriptions tables for issue #2 transcription pipeline

Revision ID: a1b2c3d4e5f6
Revises: c55b2b527f75
Create Date: 2026-07-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "c55b2b527f75"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "voice_messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("account.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("language", sa.String(length=50), nullable=False),
        sa.Column("snippets_enabled", sa.Boolean(), nullable=False),
        sa.Column("clean_enabled", sa.Boolean(), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("audio_duration_secs", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_voice_messages_user_id", "voice_messages", ["user_id"]
    )

    op.create_table(
        "transcriptions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "voice_message_id",
            sa.Integer(),
            sa.ForeignKey("voice_messages.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("detected_language", sa.String(length=50), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("model", sa.String(length=50), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("transcriptions")
    op.drop_index("ix_voice_messages_user_id", table_name="voice_messages")
    op.drop_table("voice_messages")
