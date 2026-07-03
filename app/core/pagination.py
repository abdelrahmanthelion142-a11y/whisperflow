"""Shared cursor pagination utility.

Exposes a generic ``Page[T]`` response schema and a ``paginate`` helper
that executes a SQLAlchemy ``Select`` statement with an optional
``id < cursor`` filter, orders by ``id DESC``, and fetches ``size + 1``
rows to detect whether a next page exists.
"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel
from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: int | None = None


async def paginate(
    db: AsyncSession,
    stmt: Select[tuple[T]],
    cursor: int | None,
    size: int,
    *,
    id_column: InstrumentedAttribute[int],
) -> tuple[list[T], int | None]:
    if cursor is not None:
        stmt = stmt.where(id_column < cursor)
    stmt = stmt.order_by(id_column.desc()).limit(size + 1)
    result = await db.execute(stmt)
    rows: list[Any] = list(result.scalars().all())
    if len(rows) > size:
        last = rows[size - 1]
        return rows[:size], getattr(last, id_column.key)
    return rows, None
