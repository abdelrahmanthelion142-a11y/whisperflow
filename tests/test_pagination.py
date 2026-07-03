"""Unit tests for the shared cursor pagination helper.

The helper takes a SQLAlchemy ``Select`` statement, an optional integer
``cursor``, and a ``size``. It returns a tuple of ``(items, next_cursor)``
where ``items`` is at most ``size`` rows ordered by ``id DESC`` and
``next_cursor`` is the id of the last item on the page when more rows
exist, otherwise ``None``.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import Page, paginate
from app.models.snippets import Snippet
from app.models.users import User


@pytest_asyncio.fixture
async def seeded(
    db_session: AsyncSession, test_user: User
) -> list[int]:
    created_ids: list[int] = []
    for i in range(5):
        snippet = Snippet(
            user_id=test_user.id, shortcut=f"k{i}", expansion=f"value-{i}"
        )
        db_session.add(snippet)
        await db_session.commit()
        await db_session.refresh(snippet)
        created_ids.append(snippet.id)
    return created_ids


@pytest.mark.asyncio
async def test_paginate_first_page_no_cursor(
    db_session: AsyncSession, seeded: list[int], test_user: User
) -> None:
    stmt = select(Snippet).where(Snippet.user_id == test_user.id)
    items, next_cursor = await paginate(
        db=db_session, stmt=stmt, cursor=None, size=2, id_column=Snippet.id
    )

    assert [s.id for s in items] == [seeded[-1], seeded[-2]]
    assert next_cursor == seeded[-2]


@pytest.mark.asyncio
async def test_paginate_applies_id_lt_cursor(
    db_session: AsyncSession, seeded: list[int], test_user: User
) -> None:
    cursor = seeded[-1]
    stmt = select(Snippet).where(Snippet.user_id == test_user.id)
    items, next_cursor = await paginate(
        db=db_session,
        stmt=stmt,
        cursor=cursor,
        size=2,
        id_column=Snippet.id,
    )

    assert [s.id for s in items] == [seeded[-2], seeded[-3]]
    assert next_cursor == seeded[-3]


@pytest.mark.asyncio
async def test_paginate_last_page_returns_none_cursor(
    db_session: AsyncSession, seeded: list[int], test_user: User
) -> None:
    stmt = select(Snippet).where(Snippet.user_id == test_user.id)
    items, next_cursor = await paginate(
        db=db_session, stmt=stmt, cursor=None, size=10, id_column=Snippet.id
    )

    assert len(items) == len(seeded)
    assert next_cursor is None


@pytest.mark.asyncio
async def test_paginate_detects_next_page_via_size_plus_one(
    db_session: AsyncSession, seeded: list[int], test_user: User
) -> None:
    stmt = select(Snippet).where(Snippet.user_id == test_user.id)
    items, next_cursor = await paginate(
        db=db_session, stmt=stmt, cursor=None, size=4, id_column=Snippet.id
    )

    assert len(items) == 4
    assert next_cursor == seeded[-4]
    assert [s.id for s in items] == [seeded[-1], seeded[-2], seeded[-3], seeded[-4]]


@pytest.mark.asyncio
async def test_paginate_no_extra_row_means_no_next_cursor(
    db_session: AsyncSession, seeded: list[int], test_user: User
) -> None:
    stmt = select(Snippet).where(Snippet.user_id == test_user.id)
    items, next_cursor = await paginate(
        db=db_session, stmt=stmt, cursor=None, size=5, id_column=Snippet.id
    )

    assert len(items) == 5
    assert next_cursor is None


def test_page_generic_schema_serializes_envelope() -> None:
    page = Page[int](items=[1, 2, 3], next_cursor=7)
    assert page.model_dump() == {"items": [1, 2, 3], "next_cursor": 7}


def test_page_generic_schema_allows_none_cursor() -> None:
    page = Page[int](items=[], next_cursor=None)
    assert page.model_dump() == {"items": [], "next_cursor": None}
