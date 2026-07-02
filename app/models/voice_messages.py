from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.cleanups import Cleanup
    from app.models.transcriptions import Transcription


class VoiceMessage(Base):
    __tablename__ = "voice_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("account.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    language: Mapped[str] = mapped_column(String(50), nullable=False, default="auto")
    snippets_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    clean_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    audio_duration_secs: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    transcription: Mapped["Transcription | None"] = relationship(
        back_populates="voice_message",
        cascade="all, delete-orphan",
        uselist=False,
    )
    cleanup: Mapped["Cleanup | None"] = relationship(
        back_populates="voice_message",
        cascade="all, delete-orphan",
        uselist=False,
    )
