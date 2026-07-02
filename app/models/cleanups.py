from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.cleanup_snippets import CleanupSnippet
    from app.models.voice_messages import VoiceMessage


class Cleanup(Base):
    __tablename__ = "cleanups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    voice_message_id: Mapped[int] = mapped_column(
        ForeignKey("voice_messages.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    cleaned_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str] = mapped_column(String(50), nullable=False)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    voice_message: Mapped["VoiceMessage"] = relationship(back_populates="cleanup")
    snippet_links: Mapped[list["CleanupSnippet"]] = relationship(
        back_populates="cleanup",
        cascade="all, delete-orphan",
    )
