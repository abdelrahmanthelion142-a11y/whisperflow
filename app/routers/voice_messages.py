"""HTTP routes for voice-message history."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import Page
from app.dependencies import get_current_user, get_db
from app.models.users import User
from app.schemas.VoiceMessage import VoiceMessageHistoryItem
from app.services.voice_messages import VoiceMessageService

router = APIRouter(prefix="/voice-messages")

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = DEFAULT_PAGE_SIZE


@router.get("", response_model=Page[VoiceMessageHistoryItem])
async def list_voice_messages(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    cursor: Annotated[int | None, Query()] = None,
    size: Annotated[int, Query(ge=1)] = DEFAULT_PAGE_SIZE,
) -> Page[VoiceMessageHistoryItem]:
    capped_size = min(size, MAX_PAGE_SIZE)
    service = VoiceMessageService(db=db)
    items, next_cursor = await service.list_history(
        user_id=current_user.id, cursor=cursor, size=capped_size
    )
    return Page[VoiceMessageHistoryItem](
        items=items,
        next_cursor=next_cursor,
    )
