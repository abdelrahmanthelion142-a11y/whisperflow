from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.snippets import Snippet
    from app.models.transcriptions import Transcription


class TranscriptionSnippet(Base):
    __tablename__ = "transcription_snippets"

    transcription_id: Mapped[int] = mapped_column(
        ForeignKey("transcriptions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    snippet_id: Mapped[int] = mapped_column(
        ForeignKey("snippets.id", ondelete="CASCADE"),
        primary_key=True,
    )

    transcription: Mapped["Transcription"] = relationship(
        back_populates="snippet_links"
    )
    snippet: Mapped["Snippet"] = relationship()
