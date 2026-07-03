"""Unit tests for VoiceMessageService.

These tests exercise the history read query against a real in-memory
SQLite database so the fallback chain (cleanup -> raw -> null),
newest-first ordering, user scoping, and cursor pagination can be
validated end-to-end.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cleanups import Cleanup
from app.models.transcriptions import Transcription
from app.models.users import User
from app.models.voice_messages import VoiceMessage
from app.services.voice_messages import VoiceMessageService


async def _make_voice_message(
    db: AsyncSession,
    user_id: int,
    *,
    filename: str = "clip.mp3",
    language: str = "en",
    audio_duration_secs: float = 1.0,
) -> VoiceMessage:
    vm = VoiceMessage(
        user_id=user_id,
        filename=filename,
        language=language,
        snippets_enabled=True,
        clean_enabled=True,
        file_size_bytes=1024,
        audio_duration_secs=audio_duration_secs,
    )
    db.add(vm)
    await db.commit()
    await db.refresh(vm)
    return vm


async def _attach_transcription(
    db: AsyncSession, voice_message_id: int, raw_text: str
) -> Transcription:
    t = Transcription(
        voice_message_id=voice_message_id,
        raw_text=raw_text,
        detected_language="en",
        latency_ms=10.0,
        model="whisper-1",
    )
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t


async def _attach_cleanup(
    db: AsyncSession, voice_message_id: int, cleaned_text: str | None
) -> Cleanup:
    c = Cleanup(
        voice_message_id=voice_message_id,
        cleaned_text=cleaned_text,
        model="gpt-4o-mini",
        latency_ms=20.0,
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


@pytest_asyncio.fixture
async def service(db_session: AsyncSession) -> VoiceMessageService:
    return VoiceMessageService(db=db_session)


@pytest.mark.asyncio
async def test_list_history_prefers_cleanup_text(
    db_session: AsyncSession, test_user: User, service: VoiceMessageService
) -> None:
    vm = await _make_voice_message(db_session, test_user.id)
    await _attach_transcription(db_session, vm.id, "raw text here")
    await _attach_cleanup(db_session, vm.id, "cleaned text here")

    items, next_cursor = await service.list_history(
        user_id=test_user.id, cursor=None, size=20
    )

    assert len(items) == 1
    assert items[0].id == vm.id
    assert items[0].text == "cleaned text here"
    assert items[0].has_transcription is True
    assert items[0].has_cleanup is True
    assert next_cursor is None


@pytest.mark.asyncio
async def test_list_history_falls_back_to_raw_text(
    db_session: AsyncSession, test_user: User, service: VoiceMessageService
) -> None:
    vm = await _make_voice_message(db_session, test_user.id)
    await _attach_transcription(db_session, vm.id, "raw text only")

    items, _ = await service.list_history(
        user_id=test_user.id, cursor=None, size=20
    )

    assert len(items) == 1
    assert items[0].has_transcription is True
    assert items[0].has_cleanup is False
    assert items[0].text == "raw text only"


@pytest.mark.asyncio
async def test_list_history_returns_null_text_when_no_transcription_or_cleanup(
    db_session: AsyncSession, test_user: User, service: VoiceMessageService
) -> None:
    await _make_voice_message(db_session, test_user.id)

    items, _ = await service.list_history(
        user_id=test_user.id, cursor=None, size=20
    )

    assert len(items) == 1
    assert items[0].has_transcription is False
    assert items[0].has_cleanup is False
    assert items[0].text is None


@pytest.mark.asyncio
async def test_list_history_orders_newest_first(
    db_session: AsyncSession, test_user: User, service: VoiceMessageService
) -> None:
    first = await _make_voice_message(
        db_session, test_user.id, filename="first.mp3"
    )
    second = await _make_voice_message(
        db_session, test_user.id, filename="second.mp3"
    )
    third = await _make_voice_message(
        db_session, test_user.id, filename="third.mp3"
    )

    items, _ = await service.list_history(
        user_id=test_user.id, cursor=None, size=20
    )

    assert [item.id for item in items] == [third.id, second.id, first.id]
    assert [item.filename for item in items] == [
        "third.mp3",
        "second.mp3",
        "first.mp3",
    ]


@pytest.mark.asyncio
async def test_list_history_scopes_to_user(
    db_session: AsyncSession, test_user: User, service: VoiceMessageService
) -> None:
    other = User(
        username="other",
        email="other@example.com",
        password_hash="x",
    )
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)

    mine = await _make_voice_message(db_session, test_user.id, filename="mine.mp3")
    theirs = await _make_voice_message(
        db_session, other.id, filename="theirs.mp3"
    )

    my_items, _ = await service.list_history(
        user_id=test_user.id, cursor=None, size=20
    )
    their_items, _ = await service.list_history(
        user_id=other.id, cursor=None, size=20
    )

    assert [item.id for item in my_items] == [mine.id]
    assert [item.id for item in their_items] == [theirs.id]


@pytest.mark.asyncio
async def test_list_history_returns_envelope_fields(
    db_session: AsyncSession, test_user: User, service: VoiceMessageService
) -> None:
    vm = await _make_voice_message(
        db_session,
        test_user.id,
        filename="clip.mp3",
        language="fr",
        audio_duration_secs=12.5,
    )
    await _attach_transcription(db_session, vm.id, "bonjour")
    await _attach_cleanup(db_session, vm.id, "Bonjour!")

    items, _ = await service.list_history(
        user_id=test_user.id, cursor=None, size=20
    )

    assert len(items) == 1
    item = items[0]
    assert item.id == vm.id
    assert item.filename == "clip.mp3"
    assert item.language == "fr"
    assert item.audio_duration_secs == 12.5
    assert item.created_at == vm.created_at


@pytest.mark.asyncio
async def test_list_history_paginates_with_cursor(
    db_session: AsyncSession, test_user: User, service: VoiceMessageService
) -> None:
    created: list[int] = []
    for i in range(5):
        vm = await _make_voice_message(
            db_session, test_user.id, filename=f"clip-{i}.mp3"
        )
        created.append(vm.id)

    first_page, next_cursor = await service.list_history(
        user_id=test_user.id, cursor=None, size=2
    )
    assert [item.id for item in first_page] == [created[-1], created[-2]]
    assert next_cursor == created[-2]

    second_page, end_cursor = await service.list_history(
        user_id=test_user.id, cursor=next_cursor, size=2
    )
    assert [item.id for item in second_page] == [created[-3], created[-4]]
    assert end_cursor == created[-4]

    final_page, end_cursor = await service.list_history(
        user_id=test_user.id, cursor=end_cursor, size=2
    )
    assert [item.id for item in final_page] == [created[-5]]
    assert end_cursor is None


@pytest.mark.asyncio
async def test_list_history_empty_for_user_with_no_voice_messages(
    db_session: AsyncSession, test_user: User, service: VoiceMessageService
) -> None:
    items, next_cursor = await service.list_history(
        user_id=test_user.id, cursor=None, size=20
    )

    assert items == []
    assert next_cursor is None
