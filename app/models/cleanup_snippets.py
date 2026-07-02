from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.cleanups import Cleanup
    from app.models.snippets import Snippet


class CleanupSnippet(Base):
    __tablename__ = "cleanup_snippets"

    cleanup_id: Mapped[int] = mapped_column(
        ForeignKey("cleanups.id", ondelete="CASCADE"),
        primary_key=True,
    )
    snippet_id: Mapped[int] = mapped_column(
        ForeignKey("snippets.id", ondelete="CASCADE"),
        primary_key=True,
    )

    cleanup: Mapped["Cleanup"] = relationship(back_populates="snippet_links")
    snippet: Mapped["Snippet"] = relationship()
