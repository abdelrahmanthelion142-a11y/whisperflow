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
async def test_get_active_excludes_archived(
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

    active = await service.get_active(user_id=test_user.id)

    ids = {s.id for s in active}
    assert keep.id in ids
    assert drop.id not in ids


@pytest.mark.asyncio
async def test_get_active_scopes_to_user(
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

    mine_active = await service.get_active(user_id=test_user.id)
    theirs_active = await service.get_active(user_id=other.id)

    assert {s.id for s in mine_active} == {mine.id}
    assert {s.id for s in theirs_active} == {theirs.id}


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
    assert snippet.id not in {
        s.id for s in await service.get_active(user_id=test_user.id)
    }


@pytest.mark.asyncio
async def test_archive_missing_snippet_raises(
    db_session, test_user: User
) -> None:
    service = SnippetService(db=db_session)

    with pytest.raises(SnippetNotFoundException):
        await service.archive_snippet(user_id=test_user.id, snippet_id=424242)
