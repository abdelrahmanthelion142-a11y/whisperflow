"""Unit tests for SnippetService.

These tests exercise the service layer against a real (in-memory SQLite)
database so the unique constraint, soft-delete semantics, and user
scoping can be validated end-to-end.
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from app.models.snippets import Snippet
from app.models.users import User
from app.services.exceptions import (
    DuplicateShortcutException,
    SnippetNotFoundException,
)
from app.services.snippets import SnippetService


@pytest.mark.asyncio
async def test_create_snippet_persists_row(
    db_session, test_user: User
) -> None:
    service = SnippetService(db=db_session)

    snippet = await service.create_snippet(
        user_id=test_user.id, shortcut="myemail", expansion="me@example.com"
    )

    assert snippet.id is not None
    assert snippet.user_id == test_user.id
    assert snippet.shortcut == "myemail"
    assert snippet.expansion == "me@example.com"
    assert snippet.archived is False


@pytest.mark.asyncio
async def test_create_duplicate_shortcut_raises(
    db_session, test_user: User
) -> None:
    service = SnippetService(db=db_session)
    await service.create_snippet(
        user_id=test_user.id, shortcut="addr", expansion="first@example.com"
    )

    with pytest.raises(DuplicateShortcutException):
        await service.create_snippet(
            user_id=test_user.id, shortcut="addr", expansion="second@example.com"
        )


@pytest.mark.asyncio
async def test_duplicate_shortcut_blocked_after_archive(
    db_session, test_user: User
) -> None:
    service = SnippetService(db=db_session)
    snippet = await service.create_snippet(
        user_id=test_user.id, shortcut="addr", expansion="first@example.com"
    )
    await service.archive_snippet(user_id=test_user.id, snippet_id=snippet.id)

    with pytest.raises(DuplicateShortcutException):
        await service.create_snippet(
            user_id=test_user.id, shortcut="addr", expansion="second@example.com"
        )


@pytest.mark.asyncio
async def test_list_paginated_excludes_archived(
    db_session, test_user: User
) -> None:
    service = SnippetService(db=db_session)
    keep = await service.create_snippet(
        user_id=test_user.id, shortcut="keep", expansion="kept"
    )
    drop = await service.create_snippet(
        user_id=test_user.id, shortcut="drop", expansion="dropped"
    )
    await service.archive_snippet(user_id=test_user.id, snippet_id=drop.id)

    items, next_cursor = await service.list_paginated(
        user_id=test_user.id, cursor=None, size=20
    )

    ids = {s.id for s in items}
    assert keep.id in ids
    assert drop.id not in ids
    assert next_cursor is None


@pytest.mark.asyncio
async def test_list_paginated_scopes_to_user(
    db_session, test_user: User
) -> None:
    other = User(
        username="other",
        email="other@example.com",
        password_hash="x",
    )
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)

    service = SnippetService(db=db_session)
    mine = await service.create_snippet(
        user_id=test_user.id, shortcut="mine", expansion="m"
    )
    theirs = await service.create_snippet(
        user_id=other.id, shortcut="theirs", expansion="t"
    )

    mine_items, _ = await service.list_paginated(
        user_id=test_user.id, cursor=None, size=20
    )
    theirs_items, _ = await service.list_paginated(
        user_id=other.id, cursor=None, size=20
    )

    assert {s.id for s in mine_items} == {mine.id}
    assert {s.id for s in theirs_items} == {theirs.id}


@pytest.mark.asyncio
async def test_list_paginated_returns_newest_first_with_cursor(
    db_session, test_user: User
) -> None:
    service = SnippetService(db=db_session)
    created: list[int] = []
    for i in range(5):
        snippet = await service.create_snippet(
            user_id=test_user.id, shortcut=f"k{i}", expansion=f"v{i}"
        )
        created.append(snippet.id)

    first_page, next_cursor = await service.list_paginated(
        user_id=test_user.id, cursor=None, size=2
    )
    assert [s.id for s in first_page] == [created[-1], created[-2]]
    assert next_cursor == created[-2]

    second_page, end_cursor = await service.list_paginated(
        user_id=test_user.id, cursor=next_cursor, size=2
    )
    assert [s.id for s in second_page] == [created[-3], created[-4]]
    assert end_cursor == created[-4]

    final_page, end_cursor = await service.list_paginated(
        user_id=test_user.id, cursor=end_cursor, size=2
    )
    assert [s.id for s in final_page] == [created[-5]]
    assert end_cursor is None


@pytest.mark.asyncio
async def test_update_snippet_changes_fields(
    db_session, test_user: User
) -> None:
    service = SnippetService(db=db_session)
    snippet = await service.create_snippet(
        user_id=test_user.id, shortcut="old", expansion="old body"
    )

    updated = await service.update_snippet(
        user_id=test_user.id,
        snippet_id=snippet.id,
        shortcut="new",
        expansion="new body",
    )

    assert updated.shortcut == "new"
    assert updated.expansion == "new body"


@pytest.mark.asyncio
async def test_update_missing_snippet_raises(
    db_session, test_user: User
) -> None:
    service = SnippetService(db=db_session)

    with pytest.raises(SnippetNotFoundException):
        await service.update_snippet(
            user_id=test_user.id, snippet_id=9999, shortcut="x"
        )


@pytest.mark.asyncio
async def test_archive_snippet_soft_deletes(
    db_session, test_user: User
) -> None:
    service = SnippetService(db=db_session)
    snippet = await service.create_snippet(
        user_id=test_user.id, shortcut="bye", expansion="b"
    )

    await service.archive_snippet(user_id=test_user.id, snippet_id=snippet.id)

    archived = await service.get_by_id(
        user_id=test_user.id, snippet_id=snippet.id
    )
    assert archived is not None
    assert archived.archived is True

    items, _ = await service.list_paginated(
        user_id=test_user.id, cursor=None, size=20
    )
    assert snippet.id not in {s.id for s in items}


@pytest.mark.asyncio
async def test_archive_missing_snippet_raises(
    db_session, test_user: User
) -> None:
    service = SnippetService(db=db_session)

    with pytest.raises(SnippetNotFoundException):
        await service.archive_snippet(user_id=test_user.id, snippet_id=424242)
