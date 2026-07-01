from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import oauth2_scheme
from app.dependencies import get_db
from app.schemas.Snippet import SnippetCreate, SnippetRead, SnippetUpdate
from app.services.exceptions import (
    DuplicateShortcutException,
    InvalidTokenException,
    SnippetNotFoundException,
)
from app.services.snippets import SnippetService
from app.services.users import UserService

router = APIRouter()


async def get_current_user_dependency(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    user_service = UserService(db=db)
    try:
        return await user_service.get_current_user(token)
    except InvalidTokenException as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


@router.post(
    "",
    response_model=SnippetRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_snippet(
    payload: SnippetCreate,
    current_user=Depends(get_current_user_dependency),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
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


@router.get("", response_model=list[SnippetRead])
async def list_snippets(
    current_user=Depends(get_current_user_dependency),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    service = SnippetService(db=db)
    return await service.get_active(user_id=current_user.id)


@router.put("/{snippet_id}", response_model=SnippetRead)
async def update_snippet(
    snippet_id: int,
    payload: SnippetUpdate,
    current_user=Depends(get_current_user_dependency),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
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
    current_user=Depends(get_current_user_dependency),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    service = SnippetService(db=db)
    try:
        await service.archive_snippet(
            user_id=current_user.id, snippet_id=snippet_id
        )
    except SnippetNotFoundException:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Snippet not found",
        )
