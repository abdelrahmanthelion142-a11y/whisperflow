from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import Page
from app.dependencies import get_current_user, get_db
from app.models.users import User
from app.schemas.Snippet import SnippetCreate, SnippetRead, SnippetUpdate
from app.services.exceptions import (
    DuplicateShortcutException,
    SnippetNotFoundException,
)
from app.services.snippets import SnippetService

router = APIRouter(prefix="/snippets")

MAX_PAGE_SIZE = 20
DEFAULT_PAGE_SIZE = 20


@router.post(
    "",
    response_model=SnippetRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_snippet(
    payload: SnippetCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = SnippetService(db=db)
    try:
        snippet = await service.create_snippet(
            user_id=current_user.id,
            shortcut=payload.shortcut,
            expansion=payload.expansion,
        )
    except DuplicateShortcutException:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Shortcut already exists",
        )
    return snippet


@router.get("", response_model=Page[SnippetRead])
async def list_snippets(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    cursor: Annotated[int | None, Query()] = None,
    size: Annotated[int, Query(ge=1)] = DEFAULT_PAGE_SIZE,
):
    capped_size = min(size, MAX_PAGE_SIZE)
    service = SnippetService(db=db)
    items, next_cursor = await service.list_paginated(
        user_id=current_user.id, cursor=cursor, size=capped_size
    )
    return Page[SnippetRead](
        items=[SnippetRead.model_validate(s) for s in items],
        next_cursor=next_cursor,
    )


@router.put("/{snippet_id}", response_model=SnippetRead)
async def update_snippet(
    snippet_id: int,
    payload: SnippetUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = SnippetService(db=db)
    try:
        return await service.update_snippet(
            user_id=current_user.id,
            snippet_id=snippet_id,
            shortcut=payload.shortcut,
            expansion=payload.expansion,
        )
    except SnippetNotFoundException:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Snippet not found",
        )
    except DuplicateShortcutException:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Shortcut already exists",
        )


@router.delete("/{snippet_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_snippet(
    snippet_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = SnippetService(db=db)
    try:
        await service.archive_snippet(user_id=current_user.id, snippet_id=snippet_id)
    except SnippetNotFoundException:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Snippet not found",
        )
