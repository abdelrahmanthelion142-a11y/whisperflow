"""Read-side service for voice-message history queries.

The transcription coordinator owns the write path (issue #4). This
service is dedicated to the history feed: it joins voice messages
with their transcriptions and cleanups, scopes to a single user,
applies cursor-based pagination, and returns a list of
``VoiceMessageHistoryItem`` domain objects for the router to
serialize.

The shared ``paginate`` utility from ``app.core.pagination`` is
reused so the cursor contract stays consistent with the snippet
list endpoint.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import paginate
from app.models.cleanups import Cleanup
from app.models.transcriptions import Transcription
from app.models.voice_messages import VoiceMessage
from app.schemas.VoiceMessage import VoiceMessageHistoryItem


class VoiceMessageService:
    def __init__(self, db: AsyncSession) -> None:
        self.db: AsyncSession = db

    async def list_history(
        self, user_id: int, cursor: int | None, size: int
    ) -> tuple[list[VoiceMessageHistoryItem], int | None]:
        stmt = select(VoiceMessage).where(VoiceMessage.user_id == user_id)
        voice_messages, next_cursor = await paginate(
            db=self.db,
            stmt=stmt,
            cursor=cursor,
            size=size,
            id_column=VoiceMessage.id,
        )
        if not voice_messages:
            return [], next_cursor

        transcriptions_by_id, cleanups_by_id = await self._load_related(
            [vm.id for vm in voice_messages]
        )

        items = [
            VoiceMessageHistoryItem(
                id=vm.id,
                filename=vm.filename,
                language=vm.language,
                audio_duration_secs=vm.audio_duration_secs,
                created_at=vm.created_at,
                has_transcription=vm.id in transcriptions_by_id,
                has_cleanup=vm.id in cleanups_by_id,
                text=_resolve_text(
                    transcriptions_by_id.get(vm.id),
                    cleanups_by_id.get(vm.id),
                ),
            )
            for vm in voice_messages
        ]
        return items, next_cursor

    async def _load_related(
        self, voice_message_ids: list[int]
    ) -> tuple[dict[int, Transcription], dict[int, Cleanup]]:
        transcription_result = await self.db.execute(
            select(Transcription).where(
                Transcription.voice_message_id.in_(voice_message_ids)
            )
        )
        transcriptions_by_id: dict[int, Transcription] = {
            t.voice_message_id: t for t in transcription_result.scalars().all()
        }

        cleanup_result = await self.db.execute(
            select(Cleanup).where(
                Cleanup.voice_message_id.in_(voice_message_ids)
            )
        )
        cleanups_by_id: dict[int, Cleanup] = {
            c.voice_message_id: c for c in cleanup_result.scalars().all()
        }

        return transcriptions_by_id, cleanups_by_id


def _resolve_text(
    transcription: Transcription | None,
    cleanup: Cleanup | None,
) -> str | None:
    if cleanup is not None:
        return cleanup.cleaned_text
    if transcription is not None:
        return transcription.raw_text
    return None
