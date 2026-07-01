from app.db.base import Base
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String  , DateTime
from sqlalchemy import func
from datetime import datetime


class User(Base):
    __tablename__ = "account"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), nullable=False)
    email: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(),onupdate=func.now() ,nullable=False)
    


