from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Snippet(Base):
    __tablename__ = "snippets"
    __table_args__ = (
        UniqueConstraint("user_id", "shortcut", name="uq_snippets_user_shortcut"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("account.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    shortcut: Mapped[str] = mapped_column(String(100), nullable=False)
    expansion: Mapped[str] = mapped_column(Text, nullable=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )
